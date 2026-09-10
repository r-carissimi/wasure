"""Tests for actually executing a benchmark with a runtime.

Every test here uses a shell command in place of a real engine, so the suite
needs no engines installed. Several of these are regression tests for bugs
that silently corrupted recorded results.
"""

import os
import time

import psutil
import pytest

from wasure.tools import run

from helpers import make_runtime


def execute(benchmark, runtime, folder, **kwargs):
    """Call the private runner with the arguments the tests do not care about."""

    return run._run_benchmark_with_runtime(
        benchmark, runtime, folder, folder, **kwargs
    )


class TestReturnCodes:
    def test_success_is_zero(self, benchmark, benchmarks_folder):
        _, _, return_code, _, _ = execute(
            benchmark, make_runtime(command="true"), benchmarks_folder
        )
        assert return_code == 0

    def test_payload_exit_status_is_preserved(self, benchmark, benchmarks_folder):
        _, _, return_code, _, _ = execute(
            benchmark, make_runtime(command="exit 3"), benchmarks_folder
        )
        assert return_code == 3

    @pytest.mark.parametrize(
        "command",
        [
            # A single simple command: the shell may exec it, so the process
            # wasure holds is the payload itself.
            "sleep 5",
            # A compound command forces the shell to fork, so the payload is a
            # grandchild. Killing only the shell leaves it running, holding the
            # output pipes open, and the timeout stops bounding anything.
            "sleep 5 && true",
        ],
        ids=["exec", "fork"],
    )
    @pytest.mark.parametrize("pool_memory", [False, True], ids=["plain", "memory"])
    def test_timeout_actually_cuts_the_run_short(
        self, benchmark, benchmarks_folder, command, pool_memory
    ):
        started = time.monotonic()
        elapsed, score, return_code, _, _ = execute(
            benchmark,
            make_runtime(command=command),
            benchmarks_folder,
            pool_memory=pool_memory,
            timeout_seconds=1,
        )
        wall = time.monotonic() - started

        assert return_code == run.RETURN_CODE_TIMEOUT
        assert score == 0
        # Both the wall clock and the recorded time must reflect the timeout
        # rather than the payload's own five seconds. The bound is loose
        # because CI runners are slow, but far below five seconds.
        assert wall < 3, f"waited {wall:.2f}s for a 1s timeout"
        assert elapsed < 3e9, f"recorded {elapsed / 1e9:.2f}s for a 1s timeout"

    def test_timeout_leaves_no_orphaned_payload(self, benchmark, benchmarks_folder):
        """The payload must not survive its own timeout.

        An abandoned engine keeps consuming CPU and perturbs every benchmark
        measured afterwards. An oddly specific duration is used so that the
        surviving process can be identified exactly, without matching this
        test's own command line.
        """

        duration = "31.41593"
        execute(
            benchmark,
            # The shell must fork here, so the sleep is a grandchild and is
            # only reachable by signalling the whole process group.
            make_runtime(command=f"sleep {duration} && true"),
            benchmarks_folder,
            timeout_seconds=1,
        )

        survivors = []
        for candidate in psutil.process_iter(["cmdline", "status"]):
            try:
                cmdline = candidate.info["cmdline"] or []
                if cmdline[:2] == ["sleep", duration] and candidate.info[
                    "status"
                ] != psutil.STATUS_ZOMBIE:
                    survivors.append(candidate.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
                continue

        assert not survivors, f"payload survived its timeout: pids {survivors}"

    def test_sentinels_cannot_be_confused_with_signal_deaths(self):
        """Popen reports a signal death as the negated signal number.

        SIGINT would collide with -2 and SIGHUP with -1, so the sentinels must
        stay outside the range signals can occupy.
        """

        for sentinel in (run.RETURN_CODE_TIMEOUT, run.RETURN_CODE_VALIDATION_FAILED):
            assert sentinel < -64
        assert run.RETURN_CODE_TIMEOUT != run.RETURN_CODE_VALIDATION_FAILED


class TestOutputValidation:
    def test_matching_output_passes_through(self, benchmark, benchmarks_folder):
        bench = {**benchmark, "output-validator": "all good"}
        _, _, return_code, _, _ = execute(
            bench, make_runtime(command="echo all good"), benchmarks_folder
        )
        assert return_code == 0

    def test_failed_validation_is_not_recorded_as_success(
        self, benchmark, benchmarks_folder
    ):
        """A payload can exit 0 while producing wrong output.

        Reporting that exit status made such a run indistinguishable from a
        successful one: it landed in the results with return_code 0 and a zero
        elapsed time, so it was filtered out of the "successful runs" view for
        having no timing and out of the "failed runs" view for exiting 0.
        """

        bench = {**benchmark, "output-validator": "never appears"}
        elapsed, score, return_code, _, _ = execute(
            bench, make_runtime(command="echo something else"), benchmarks_folder
        )
        assert return_code == run.RETURN_CODE_VALIDATION_FAILED
        assert return_code != 0
        assert (elapsed, score) == (0, 0)

    def test_failed_validation_keeps_a_nonzero_payload_status(
        self, benchmark, benchmarks_folder
    ):
        """When the payload also failed, its own status is more informative."""

        bench = {**benchmark, "output-validator": "never appears"}
        _, _, return_code, _, _ = execute(
            bench, make_runtime(command="exit 4"), benchmarks_folder
        )
        assert return_code == 4

    def test_no_validator_means_no_validation(self, benchmark, benchmarks_folder):
        _, _, return_code, _, _ = execute(
            benchmark, make_runtime(command="echo anything"), benchmarks_folder
        )
        assert return_code == 0


class TestOutputMerging:
    def test_stdout_and_stderr_are_not_concatenated(self):
        """Joining the streams directly fused the last token of one with the
        first of the other, silently corrupting score and validator matches."""

        assert run._merge_output(b"12", b"34") == "12\n34"

    def test_empty_streams_are_dropped(self):
        assert run._merge_output(b"out", b"") == "out"
        assert run._merge_output(b"", b"err") == "err"
        assert run._merge_output(b"", b"") == ""

    def test_undecodable_bytes_do_not_raise(self):
        assert run._merge_output(b"\xff\xfe", b"") != ""

    def test_score_is_read_from_stderr_too(self, benchmark, benchmarks_folder):
        bench = {**benchmark, "score-parser": r"score:\s*(?P<score>\d+)"}
        _, score, _, _, _ = execute(
            bench,
            make_runtime(command="sh -c 'echo score:  99 >&2'"),
            benchmarks_folder,
        )
        assert score == 99

    def test_score_is_not_fused_across_the_stream_boundary(
        self, benchmark, benchmarks_folder
    ):
        """stdout ending in digits followed by stderr starting with digits
        must not be read as one number."""

        bench = {**benchmark, "score-parser": r"(?P<score>\d+)"}
        _, score, _, _, _ = execute(
            bench,
            make_runtime(command="sh -c 'printf 12; printf 34 >&2'"),
            benchmarks_folder,
        )
        assert score == 12


class TestScoreParsing:
    def test_named_group_is_extracted(self, benchmark, benchmarks_folder):
        bench = {**benchmark, "score-parser": r"Dhrystones per Second:\s+(?P<score>\d+)"}
        _, score, _, _, _ = execute(
            bench,
            make_runtime(command="echo 'Dhrystones per Second:    4321'"),
            benchmarks_folder,
        )
        assert score == 4321

    def test_no_match_scores_zero(self):
        assert run._parse_score("nothing here", r"(?P<score>\d+)") == 0

    def test_score_may_be_fractional(self):
        assert run._parse_score("t=1.5s", r"t=(?P<score>[\d.]+)") == 1.5


class TestStatsParsing:
    def test_runtime_stats_are_captured(self, benchmark, benchmarks_folder):
        runtime = make_runtime(
            command="echo 'instructions: 4242'",
            **{"stats-parser": {"instructions": r"instructions:\s*(?P<instructions>\d+)"}},
        )
        _, _, _, _, stats = execute(benchmark, runtime, benchmarks_folder)
        assert stats["instructions"] == "4242"

    def test_unmatched_stats_are_omitted(self, benchmark, benchmarks_folder):
        runtime = make_runtime(
            command="echo nothing",
            **{"stats-parser": {"missing": r"(?P<missing>\d+)"}},
        )
        _, _, _, _, stats = execute(benchmark, runtime, benchmarks_folder)
        assert "missing" not in stats


class TestMemorySampling:
    def test_memory_is_reported_when_sampled(self, benchmark, benchmarks_folder):
        _, _, _, _, stats = execute(
            benchmark,
            make_runtime(command="sleep 0.2"),
            benchmarks_folder,
            pool_memory=True,
        )
        assert stats["max_rss_bytes"] > 0
        assert "max_vms_bytes" in stats

    def test_process_exiting_mid_poll_does_not_crash(
        self, benchmark, benchmarks_folder, monkeypatch
    ):
        """The child can exit between poll() and memory_info().

        Short benchmarks hit this routinely; it used to raise an uncaught
        psutil.NoSuchProcess that aborted the entire sweep.
        """

        def gone(self):
            raise psutil.NoSuchProcess(self.pid)

        monkeypatch.setattr(psutil.Process, "memory_info", gone)

        _, _, return_code, _, stats = execute(
            benchmark,
            make_runtime(command="true"),
            benchmarks_folder,
            pool_memory=True,
        )
        assert return_code == 0
        # Nothing was measured, so nothing should be reported.
        assert "max_rss_bytes" not in stats

    def test_timeout_still_applies_when_sampling_is_impossible(
        self, benchmark, benchmarks_folder, monkeypatch
    ):
        """A permanently unreadable process must not disable the timeout.

        Giving up on the polling loop entirely skipped the timeout check, so a
        payload ran to completion and was recorded as a success.
        """

        def denied(self):
            raise psutil.AccessDenied(self.pid)

        monkeypatch.setattr(psutil.Process, "memory_info", denied)

        elapsed, _, return_code, _, stats = execute(
            benchmark,
            make_runtime(command="sleep 5"),
            benchmarks_folder,
            pool_memory=True,
            timeout_seconds=1,
        )
        assert return_code == run.RETURN_CODE_TIMEOUT
        assert elapsed < 3e9, f"recorded {elapsed / 1e9:.2f}s for a 1s timeout"
        assert not stats

    def test_unsampled_memory_is_absent_rather_than_zero(
        self, benchmark, benchmarks_folder, monkeypatch
    ):
        """Zeros would be indistinguishable from a real measurement in the CSV."""

        monkeypatch.setattr(
            psutil.Process,
            "memory_info",
            lambda self: (_ for _ in ()).throw(psutil.AccessDenied(self.pid)),
        )
        _, _, _, _, stats = execute(
            benchmark,
            make_runtime(command="true"),
            benchmarks_folder,
            pool_memory=True,
        )
        assert stats.get("max_rss_bytes") is None
        assert stats.get("max_vms_bytes") is None


class TestArgumentFormatting:
    def test_path_placeholder_is_expanded(self, benchmarks_folder):
        bench = {
            "name": "one",
            "path": "alpha/one.wasm",
            "args": "{path}/data.bin",
            "score-parser": r"got (?P<score>\d+)",
        }
        runtime = make_runtime(command="echo got 1 {args} # {payload}")
        _, _, _, output, _ = execute(bench, runtime, benchmarks_folder)
        assert os.path.join(benchmarks_folder, "alpha") in output

    def test_entrypoint_flag_only_applied_when_benchmark_names_one(
        self, benchmarks_folder
    ):
        runtime = make_runtime(
            command="echo [{entrypoint_flag}] [{entrypoint}] # {payload}",
            **{"entrypoint-flag": "--invoke"},
        )
        _, _, _, without, _ = execute(
            {"name": "one", "path": "alpha/one.wasm"}, runtime, benchmarks_folder
        )
        assert "[] []" in without

        _, _, _, with_entry, _ = execute(
            {"name": "one", "path": "alpha/one.wasm", "entrypoint": "go"},
            runtime,
            benchmarks_folder,
        )
        assert "[--invoke] [go]" in with_entry


class TestIterations:
    def test_repeat_produces_one_record_per_run(self, benchmark, benchmarks_folder):
        records = run.run_benchmark_iterations(
            benchmark, make_runtime(command="true"), benchmarks_folder,
            benchmarks_folder, repeat=3,
        )
        assert len(records) == 3
        assert all(r["return_code"] == 0 for r in records)

    def test_output_can_be_withheld(self, benchmark, benchmarks_folder):
        kept = run.run_benchmark_iterations(
            benchmark, make_runtime(command="echo hello"), benchmarks_folder,
            benchmarks_folder,
        )
        assert "output" in kept[0]

        dropped = run.run_benchmark_iterations(
            benchmark, make_runtime(command="echo hello"), benchmarks_folder,
            benchmarks_folder, no_store_output=True,
        )
        assert "output" not in dropped[0]

    def test_failed_run_has_its_timing_discarded(self, benchmark, benchmarks_folder):
        records = run.run_benchmark_iterations(
            benchmark, make_runtime(command="exit 1"), benchmarks_folder,
            benchmarks_folder,
        )
        assert records[0]["elapsed_time_ns"] == 0
        assert records[0]["return_code"] == 1


class TestAheadOfTimeCompilation:
    def test_precompiled_artifact_is_used_then_removed(self, benchmarks_folder):
        """The .aot file is an intermediate and must not be left behind."""

        runtime = make_runtime(
            command="cat {payload}", **{"aot-command": "cp {input} {output}"}
        )
        bench = {"name": "one", "path": "alpha/one.wasm"}
        records = run.run_benchmark_iterations(
            bench, runtime, benchmarks_folder, benchmarks_folder
        )
        assert records[0]["return_code"] == 0
        assert not os.path.exists(
            os.path.join(benchmarks_folder, "alpha", "one.aot")
        )

    def test_compilation_failure_yields_no_records(self, benchmarks_folder):
        runtime = make_runtime(command="true", **{"aot-command": "exit 1"})
        bench = {"name": "one", "path": "alpha/one.wasm"}
        assert (
            run.run_benchmark_iterations(
                bench, runtime, benchmarks_folder, benchmarks_folder
            )
            is None
        )


@pytest.mark.parametrize(
    "command,expected",
    [("true", 0), ("exit 7", 7), ("echo hi", 0)],
)
def test_shell_commands_round_trip(benchmark, benchmarks_folder, command, expected):
    _, _, return_code, _, _ = execute(
        benchmark, make_runtime(command=command), benchmarks_folder
    )
    assert return_code == expected


class TestProcessTreeKill:
    def test_killing_an_already_dead_process_is_not_an_error(self):
        """The payload usually exits on its own between the timeout check and
        the kill, so both the group signal and the direct kill must tolerate
        the process being gone."""

        class AlreadyGone:
            # A pid that cannot exist, so os.getpgid raises.
            pid = 2**22 - 1

            def kill(self):
                raise ProcessLookupError

        run._kill_process_tree(AlreadyGone())


class TestAheadOfTimeCompilationSkipped:
    def test_a_runtime_without_an_aot_command_compiles_nothing(
        self, benchmark, benchmarks_folder
    ):
        assert (
            run._compile_benchmark(
                benchmark,
                make_runtime(command="true"),
                benchmarks_folder,
                benchmarks_folder,
            )
            is None
        )
