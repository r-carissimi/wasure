"""Tests for the metadata recorded alongside a run's measurements.

A results file that does not say which engine build produced it cannot be
reproduced, and a regression between two runs cannot be attributed to the
engine rather than the benchmark or the machine.
"""

import csv
import json

import pytest

from wasure.tools import export, plot, run, runtimes, utils

from helpers import make_runtime


@pytest.fixture
def versioned_runtimes_file(tmp_path):
    """A runtimes.json whose version-command reports a recognisable version."""

    path = tmp_path / "runtimes" / "runtimes.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "runtimes": [
                    {
                        "name": "engine",
                        "desc": "an engine",
                        "command": "true # {payload}",
                        "version-command": "printf 'engine 1.2.3 (abc1234)\\nbuild details\\n'",
                        "subruntimes": [
                            {
                                "name": "engine-jit",
                                "desc": "jit mode",
                                "command": "true # {payload}",
                            }
                        ],
                    },
                    {
                        "name": "silent",
                        "desc": "reports nothing",
                        "command": "true # {payload}",
                        "version-command": "true",
                    },
                ]
            }
        )
    )
    return str(path)


class TestCollectingVersions:
    def test_version_is_recorded(self, versioned_runtimes_file, tmp_path):
        versions = run.get_runtime_versions(versioned_runtimes_file, str(tmp_path))
        assert versions["engine"] == "engine 1.2.3 (abc1234)"

    def test_only_the_first_line_is_kept(self, versioned_runtimes_file, tmp_path):
        """Engines often follow the version with a build banner."""

        versions = run.get_runtime_versions(versioned_runtimes_file, str(tmp_path))
        assert "build details" not in versions["engine"]

    def test_subruntimes_inherit_their_parents_version(
        self, versioned_runtimes_file, tmp_path
    ):
        """A subruntime is a different mode of the same installed engine, so
        it has no version-command of its own."""

        versions = run.get_runtime_versions(versioned_runtimes_file, str(tmp_path))
        assert versions["engine-jit"] == versions["engine"] == "engine 1.2.3 (abc1234)"

    def test_unknown_version_is_none_not_an_empty_string(
        self, versioned_runtimes_file, tmp_path
    ):
        versions = run.get_runtime_versions(versioned_runtimes_file, str(tmp_path))
        assert versions["silent"] is None

    def test_missing_runtimes_file_yields_nothing(self, tmp_path):
        assert run.get_runtime_versions(str(tmp_path / "absent.json"), str(tmp_path)) == {}


class TestResultsDocument:
    def test_metadata_records_the_selected_runtimes(self):
        metadata = run._build_metadata({"a": "a 1.0", "b": None}, ["a", "b"])
        assert metadata["runtimes"] == {
            "a": {"version": "a 1.0"},
            "b": {"version": None},
        }

    def test_metadata_records_wasure_and_the_machine(self):
        metadata = run._build_metadata({}, [])
        assert metadata["wasure-version"]
        assert metadata["created"]
        assert metadata["platform"]["system"]
        assert metadata["platform"]["cpu-count"]

    def test_document_keeps_measurements_under_results(self):
        metadata = run._build_metadata({"a": "a 1.0"}, ["a"])
        document = run._wrap_results({"a": {"b": []}}, metadata)
        assert document["results"] == {"a": {"b": []}}
        assert document[utils.RESULTS_SCHEMA_KEY] == utils.RESULTS_SCHEMA_VERSION

    def test_without_metadata_the_document_is_the_bare_measurements(self):
        assert run._wrap_results({"a": {}}, None) == {"a": {}}


class TestReadingResults:
    def test_round_trip(self):
        metadata = run._build_metadata({"a": "a 1.0"}, ["a"])
        measurements = {"a": {"bench": [{"elapsed_time_ns": 1, "score": 0, "return_code": 0}]}}
        results, read_back = utils.split_results(
            run._wrap_results(measurements, metadata)
        )
        assert results == measurements
        assert utils.runtime_versions(read_back) == {"a": "a 1.0"}

    def test_a_results_file_without_metadata_still_reads(self):
        """Files written before versions were recorded are a bare mapping of
        runtime name to benchmarks."""

        legacy = {"wasmtime": {"bench": [{"elapsed_time_ns": 5, "score": 0, "return_code": 0}]}}
        results, metadata = utils.split_results(legacy)
        assert results == legacy
        assert metadata == {}
        assert utils.runtime_versions(metadata) == {}

    def test_versions_are_empty_rather_than_missing_when_unknown(self):
        assert utils.runtime_versions(None) == {}
        assert utils.runtime_versions({}) == {}

    def test_non_dict_input_is_handled(self):
        assert utils.split_results([1, 2, 3]) == ({}, {})


class TestConsumersAcceptBothFormats:
    """plot and export must read new and old results files alike."""

    @pytest.fixture
    def measurements(self):
        return {
            "fast": {"bench": [{"elapsed_time_ns": 100, "score": 0, "return_code": 0}]},
            "slow": {"bench": [{"elapsed_time_ns": 900, "score": 0, "return_code": 0}]},
        }

    @pytest.fixture(params=["with-metadata", "legacy"])
    def results_file(self, request, tmp_path, measurements):
        path = tmp_path / "r.json"
        if request.param == "with-metadata":
            metadata = run._build_metadata({"fast": "fast 2.0", "slow": None}, ["fast", "slow"])
            path.write_text(json.dumps(run._wrap_results(measurements, metadata)))
        else:
            path.write_text(json.dumps(measurements))
        return path

    def test_plot_reads_it(self, results_file, tmp_path):
        from types import SimpleNamespace

        out = tmp_path / "plots"
        assert (
            plot.main(
                SimpleNamespace(
                    results_file=str(results_file),
                    plots_folder=str(out),
                    log_level="ERROR",
                    statistic="median",
                )
            )
            in (None, 0)
        )
        assert (out / "r.png").exists()

    def test_export_reads_it(self, results_file, tmp_path):
        from types import SimpleNamespace

        out = tmp_path / "csv"
        export.main(
            SimpleNamespace(
                results_file=str(results_file),
                csv_folder=str(out),
                memory=False,
                log_level="ERROR",
            )
        )
        with open(out / "r.csv") as f:
            rows = list(csv.DictReader(f))
        assert {r["benchmark"] for r in rows} == {"bench"}
        assert {r["runtime"] for r in rows} == {"fast", "slow"}


class TestExportedVersionColumn:
    def read(self, path):
        with open(path) as f:
            return list(csv.DictReader(f))

    def test_version_appears_per_row(self, tmp_path):
        data = {"fast": {"bench": [{"elapsed_time_ns": 1, "score": 0, "return_code": 0}]}}
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(
            data, out, memory=False, versions={"fast": "fast 2.0"}
        )
        assert self.read(out)[0]["runtime_version"] == "fast 2.0"

    def test_unknown_version_is_an_empty_cell(self, tmp_path):
        """An empty cell reads as unknown; a placeholder string would be
        mistaken for a real version."""

        data = {"fast": {"bench": [{"elapsed_time_ns": 1, "score": 0, "return_code": 0}]}}
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(data, out, memory=False, versions={})
        assert self.read(out)[0]["runtime_version"] == ""

    def test_column_sits_next_to_the_runtime(self, tmp_path):
        data = {"fast": {"bench": [{"elapsed_time_ns": 1, "score": 0, "return_code": 0}]}}
        out = str(tmp_path / "out.csv")
        export._write_benchmark_results_to_csv(data, out, memory=False, versions=None)
        with open(out) as f:
            header = next(csv.reader(f))
        assert header[:3] == ["benchmark", "runtime", "runtime_version"]


def test_a_real_run_records_versions(tmp_path, benchmarks_folder, versioned_runtimes_file):
    """End to end: the file `wasure run` writes carries the engine versions."""

    from types import SimpleNamespace

    results_folder = tmp_path / "out"
    exit_code = run.main(
        SimpleNamespace(
            runtimes=["engine"],
            benchmarks=["alpha/one"],
            no_store_output=True,
            benchmarks_folder=benchmarks_folder,
            runtimes_file=versioned_runtimes_file,
            runtimes_folder=str(tmp_path),
            results_folder=str(results_folder),
            repeat=1,
            memory=False,
            timeout=None,
            log_level="ERROR",
        )
    )
    assert exit_code in (None, 0)

    written = list(results_folder.glob("*.json"))
    assert len(written) == 1
    document = json.loads(written[0].read_text())

    results, metadata = utils.split_results(document)
    assert results["engine"]["one"][0]["return_code"] == 0
    assert utils.runtime_versions(metadata)["engine"] == "engine 1.2.3 (abc1234)"
