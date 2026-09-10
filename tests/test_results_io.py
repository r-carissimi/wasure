"""Tests for writing results to disk.

A benchmark sweep can run for hours, so how results reach the disk matters as
much as the numbers themselves. These are largely regression tests: results
used to be written only after every benchmark had finished, which meant any
crash discarded the whole run.
"""

import json
import os

import pytest

from wasure.tools import run

from helpers import make_runtime


class TestResultsFilename:
    def test_uses_a_timestamped_json_name(self, tmp_path):
        name = run._new_results_filename(str(tmp_path))
        assert name.endswith(".json")
        assert os.path.dirname(name) == str(tmp_path)

    def test_two_runs_in_the_same_second_do_not_collide(self, tmp_path):
        """The name is claimed before the sweep starts and written to
        repeatedly, so a shared name means one run overwrites the other."""

        first = run._new_results_filename(str(tmp_path))
        open(first, "w").close()

        second = run._new_results_filename(str(tmp_path))
        assert second != first

        open(second, "w").close()
        assert run._new_results_filename(str(tmp_path)) not in (first, second)

    def test_works_when_the_folder_does_not_exist_yet(self, tmp_path):
        target = str(tmp_path / "not-created")
        assert run._new_results_filename(target).startswith(target)


class TestSavingResults:
    def test_written_content_round_trips(self, tmp_path, results):
        path = str(tmp_path / "out.json")
        run._save_results_to_file(results, path)
        assert json.load(open(path)) == results

    def test_missing_directories_are_created(self, tmp_path, results):
        path = str(tmp_path / "deep" / "nested" / "out.json")
        run._save_results_to_file(results, path)
        assert os.path.exists(path)

    def test_bare_filename_does_not_raise(self, tmp_path, results, monkeypatch):
        """os.path.dirname("out.json") is empty, which os.makedirs rejects."""

        monkeypatch.chdir(tmp_path)
        run._save_results_to_file(results, "out.json")
        assert os.path.exists(tmp_path / "out.json")

    def test_no_temporary_file_is_left_behind(self, tmp_path, results):
        path = str(tmp_path / "out.json")
        run._save_results_to_file(results, path)
        assert os.listdir(tmp_path) == ["out.json"]

    def test_a_failed_write_leaves_the_previous_checkpoint_intact(
        self, tmp_path, results, monkeypatch
    ):
        path = str(tmp_path / "out.json")
        run._save_results_to_file(results, path)

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json, "dump", explode)
        with pytest.raises(OSError):
            run._save_results_to_file({"other": {}}, path)

        # The good checkpoint survives and no debris is left.
        assert json.load(open(path)) == results
        assert os.listdir(tmp_path) == ["out.json"]


class TestCheckpointing:
    def test_results_are_written_before_the_sweep_finishes(
        self, tmp_path, benchmarks_folder
    ):
        """Each benchmark's results must be on disk as soon as it completes."""

        path = str(tmp_path / "out.json")
        seen = []

        original = run.run_benchmark_iterations

        def record(*args, **kwargs):
            # Capture what is already on disk before this benchmark is run.
            seen.append(
                json.load(open(path)) if os.path.exists(path) else None
            )
            return original(*args, **kwargs)

        runtimes = [make_runtime(name="a"), make_runtime(name="b")]
        benchmarks = [
            {"name": "one", "path": "alpha/one.wasm"},
            {"name": "two", "path": "alpha/two.wasm"},
        ]

        run.run_benchmark_iterations = record
        try:
            run._run_benchmarks(
                runtimes, benchmarks, benchmarks_folder, benchmarks_folder,
                results_file=path,
            )
        finally:
            run.run_benchmark_iterations = original

        # Nothing on disk before the first benchmark, then a growing file.
        assert seen[0] is None
        assert seen[1] is not None, "results were not checkpointed after benchmark 1"
        assert len(seen[-1]) >= 1

    def test_an_interrupted_sweep_keeps_what_it_collected(
        self, tmp_path, benchmarks_folder
    ):
        path = str(tmp_path / "out.json")
        calls = {"n": 0}
        original = run.run_benchmark_iterations

        def fail_on_third(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt
            return original(*args, **kwargs)

        runtimes = [make_runtime(name="a"), make_runtime(name="b")]
        benchmarks = [
            {"name": "one", "path": "alpha/one.wasm"},
            {"name": "two", "path": "alpha/two.wasm"},
        ]

        run.run_benchmark_iterations = fail_on_third
        try:
            with pytest.raises(KeyboardInterrupt):
                run._run_benchmarks(
                    runtimes, benchmarks, benchmarks_folder, benchmarks_folder,
                    results_file=path,
                )
        finally:
            run.run_benchmark_iterations = original

        partial = json.load(open(path))
        # Runtime "a" completed both benchmarks before the interrupt.
        assert partial["a"] == {
            k: v for k, v in partial["a"].items()
        }
        assert len(partial["a"]) == 2

    def test_no_checkpointing_without_a_results_file(
        self, tmp_path, benchmarks_folder
    ):
        collected = run._run_benchmarks(
            [make_runtime()],
            [{"name": "one", "path": "alpha/one.wasm"}],
            benchmarks_folder,
            benchmarks_folder,
        )
        assert list(collected) == ["mock"]
        # Only the benchmarks fixture directory; no results file was written.
        assert not list(tmp_path.glob("*.json"))


def test_results_are_nested_runtime_then_benchmark(benchmarks_folder):
    """The results structure is results[runtime][benchmark].

    This is the opposite of the exported CSV's column order, which has been
    got backwards before, so pin it down.
    """

    collected = run._run_benchmarks(
        [make_runtime(name="engine")],
        [{"name": "bench", "path": "alpha/one.wasm"}],
        benchmarks_folder,
        benchmarks_folder,
    )
    assert "engine" in collected
    assert "bench" in collected["engine"]
