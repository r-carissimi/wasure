"""Tests for turning collected results into plots and CSV."""

import csv
import json
import os
from types import SimpleNamespace

import pytest

from wasure.tools import export, plot, utils


class TestStatistics:
    def test_summary_per_benchmark(self, results):
        stats = plot._compute_statistics(results)
        assert stats["fast"]["one"]["elapsed_time_ns"] == {
            "avg": 1100.0,
            "median": 1100.0,
            "min": 1000,
            "max": 1200,
        }

    def test_median_resists_an_outlier_that_drags_the_mean(self):
        """The reason median is the default: a run can be slowed by unrelated
        load but never made faster, so timings are right-skewed."""

        runs = [{"elapsed_time_ns": ns, "score": 0, "return_code": 0}
                for ns in (100, 105, 110, 115, 2000)]
        elapsed = plot._compute_statistics({"e": {"b": runs}})["e"]["b"]["elapsed_time_ns"]
        assert elapsed["median"] == 110
        assert elapsed["avg"] > 400

    def test_zero_timings_are_excluded(self):
        stats = plot._compute_statistics(
            {
                "engine": {
                    "bench": [
                        {"elapsed_time_ns": 0, "score": 0, "return_code": -1002},
                        {"elapsed_time_ns": 400, "score": 0, "return_code": 0},
                    ]
                }
            }
        )
        assert stats["engine"]["bench"]["elapsed_time_ns"]["min"] == 400

    def test_a_runtime_with_no_usable_runs_is_dropped(self):
        """Keeping it would produce an empty series in the plot."""

        stats = plot._compute_statistics(
            {"broken": {"bench": [{"elapsed_time_ns": 0, "score": 0, "return_code": 1}]}}
        )
        assert stats == {}


class TestStatisticSelection:
    """--statistic picks which summary is plotted."""

    @pytest.fixture
    def skewed(self):
        # One outlier run, so mean, median and min all differ.
        return {
            "engine": {
                "bench": [
                    {"elapsed_time_ns": ns, "score": 0, "return_code": 0}
                    for ns in (100, 110, 120, 3000)
                ]
            }
        }

    @pytest.mark.parametrize(
        "name,expected", [("min", 100), ("median", 115.0), ("mean", 832.5)]
    )
    def test_each_statistic_is_plotted(self, tmp_path, skewed, name, expected):
        stats = plot._compute_statistics(skewed)
        key = plot.STATISTICS[name]
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names, key)
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        data = plot._absolute_values(names, raw, key)
        assert data["engine"]["values"]["bench"] == pytest.approx(expected)

    def test_median_is_the_default(self, tmp_path, skewed):
        source = tmp_path / "r.json"
        source.write_text(json.dumps(skewed))
        # No statistic attribute at all, as an older caller would pass.
        plot.main(
            SimpleNamespace(
                results_file=str(source),
                plots_folder=str(tmp_path / "p"),
                log_level="ERROR",
            )
        )
        assert (tmp_path / "p" / "r.png").exists()

    def test_error_bars_are_never_negative(self, skewed):
        """With min as the plotted value the lower bar would otherwise go
        negative, which matplotlib renders as a bar pointing the wrong way."""

        stats = plot._compute_statistics(skewed)
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names, "min")
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        for builder in (plot._absolute_values, plot._normalize_values):
            data = (
                builder(names, raw, "min")
                if builder is plot._absolute_values
                else builder(names, metrics, raw, "min")
            )
            low, high = data["engine"]["errors"]["bench"]
            assert low >= 0 and high >= 0


class TestMetricSelection:
    def test_score_wins_when_any_runtime_scored(self):
        stats = {
            "a": {"b": {"elapsed_time_ns": {"avg": 5}, "score": {"avg": 10}}},
            "c": {"b": {"elapsed_time_ns": {"avg": 5}, "score": {"avg": 0}}},
        }
        assert plot._determine_benchmark_metrics(stats, ["b"]) == {"b": "score"}

    def test_elapsed_time_is_used_when_nothing_scored(self):
        stats = {"a": {"b": {"elapsed_time_ns": {"avg": 5}, "score": {"avg": 0}}}}
        assert plot._determine_benchmark_metrics(stats, ["b"]) == {"b": "elapsed_time_ns"}


class TestRaggedCoverage:
    """A runtime missing from one benchmark used to break plotting entirely.

    The accumulator was seeded from the alphabetically-first benchmark only,
    so any runtime absent from that benchmark raised KeyError. Engines fail
    individual benchmarks all the time, so this was the common case.
    """

    @pytest.fixture
    def ragged(self):
        # "slow" never ran "aaa", which sorts first.
        return {
            "fast": {
                "aaa": [{"elapsed_time_ns": 100, "score": 0, "return_code": 0}],
                "bbb": [{"elapsed_time_ns": 200, "score": 0, "return_code": 0}],
            },
            "slow": {"bbb": [{"elapsed_time_ns": 900, "score": 0, "return_code": 0}]},
        }

    def test_every_runtime_gets_an_entry(self, ragged):
        stats = plot._compute_statistics(ragged)
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names)
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        assert set(plot._empty_runtime_data(names, raw)) == {"fast", "slow"}

    def test_normalizing_does_not_raise(self, ragged):
        stats = plot._compute_statistics(ragged)
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names)
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        data = plot._normalize_values(names, metrics, raw)
        assert set(data) == {"fast", "slow"}
        # The missing cell is simply absent rather than zero-filled.
        assert "aaa" not in data["slow"]["values"]

    def test_absolute_values_do_not_raise(self, ragged):
        stats = plot._compute_statistics(ragged)
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names)
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        assert set(plot._absolute_values(names, raw)) == {"fast", "slow"}

    def test_plot_command_writes_a_file(self, tmp_path, ragged):
        source = tmp_path / "r.json"
        source.write_text(json.dumps(ragged))
        out = tmp_path / "plots"

        plot.main(
            SimpleNamespace(
                results_file=str(source),
                plots_folder=str(out),
                log_level="ERROR",
            )
        )
        assert (out / "r.png").exists()


class TestNormalization:
    def test_elapsed_times_are_relative_to_the_fastest(self, results):
        stats = plot._compute_statistics(results)
        names = plot._collect_benchmarks(stats)
        metrics = plot._determine_benchmark_metrics(stats, names)
        raw = plot._transpose_benchmark_data(stats, names, metrics)
        data = plot._normalize_values(names, metrics, raw)
        # "fast" is the baseline for benchmark "one" at 1100ns average.
        assert data["fast"]["values"]["one"] == pytest.approx(100.0)
        assert data["slow"]["values"]["one"] == pytest.approx(5000 / 1100 * 100)


class TestCsvExport:
    def read(self, path):
        with open(path) as f:
            return list(csv.reader(f))

    def test_column_order_matches_the_header(self, tmp_path, results):
        """The results dict is nested runtime-then-benchmark while the CSV
        lists benchmark first, so the two are easy to transpose by mistake."""

        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(results, out, memory=False)
        rows = self.read(out)

        assert rows[0][:2] == ["benchmark", "runtime"]
        body = rows[1:]
        assert all(r[0] in {"one", "two"} for r in body), "benchmark column wrong"
        assert all(r[1] in {"fast", "slow"} for r in body), "runtime column wrong"

    def test_one_row_per_run_with_a_one_based_index(self, tmp_path, results):
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(results, out, memory=False)
        rows = self.read(out)[1:]
        assert len(rows) == 5
        indices = [r[2] for r in rows if r[0] == "one" and r[1] == "fast"]
        assert indices == ["1", "2"]

    def test_memory_columns_only_when_requested(self, tmp_path, results):
        without = str(tmp_path / "a.csv")
        export._write_benchmark_results_to_csv(results, without, memory=False)
        assert "max_rss_bytes" not in self.read(without)[0]

        with_mem = str(tmp_path / "b.csv")
        export._write_benchmark_results_to_csv(results, with_mem, memory=True)
        assert self.read(with_mem)[0][-2:] == ["max_rss_bytes", "max_vms_bytes"]

    def test_absent_memory_stats_become_empty_cells(self, tmp_path, results):
        """Runs too short to sample have no memory stats; they must not be
        reported as zero, which would look like a real measurement."""

        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(results, out, memory=True)
        assert all(r[-2:] == ["", ""] for r in self.read(out)[1:])

    def test_memory_stats_are_written_when_present(self, tmp_path):
        data = {
            "engine": {
                "bench": [
                    {
                        "elapsed_time_ns": 10,
                        "score": 0,
                        "return_code": 0,
                        "stats": {"max_rss_bytes": 4096, "max_vms_bytes": 8192},
                    }
                ]
            }
        }
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(data, out, memory=True)
        assert self.read(out)[1][-2:] == ["4096", "8192"]

    def test_failure_sentinels_survive_the_round_trip(self, tmp_path):
        data = {
            "engine": {
                "timeout": [{"elapsed_time_ns": 0, "score": 0, "return_code": -1001}],
                "invalid": [{"elapsed_time_ns": 0, "score": 0, "return_code": -1002}],
            }
        }
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(data, out, memory=False)
        codes = {r[0]: r[5] for r in self.read(out)[1:]}
        assert codes == {"timeout": "-1001", "invalid": "-1002"}


class TestLoadingResults:
    def test_malformed_json_returns_nothing(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        assert utils.load_results_file(str(path)) is None

    def test_empty_results_return_nothing(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("{}")
        assert utils.load_results_file(str(path)) is None


class TestPathResolution:
    def test_absolute_paths_are_unchanged(self):
        assert utils.get_absolute_path("/tmp/x") == "/tmp/x"

    def test_relative_paths_resolve_against_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        assert utils.get_absolute_path("x") == os.path.join(str(tmp_path), "x")
