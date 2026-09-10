"""Tests for the command-line surface.

The argument declarations are the part of wasure a user actually touches, and
a renamed flag or a changed default is a breaking change even though no logic
moved. These tests pin the flags, their defaults and the exit statuses.
"""

import json
import subprocess
import sys
from argparse import ArgumentParser

import pytest

import wasure.wasure as cli
from wasure.tools import benchmarks, check, commands, export, plot, run, runtimes


def parsed(module, argv):
    """Build a parser the way wasure does and parse argv with it."""

    parser = ArgumentParser()
    module.parse(parser)
    return parser.parse_args(argv)


class TestTopLevelParser:
    def test_every_command_is_registered(self):
        parser = ArgumentParser()
        cli.setup_subparsers(parser, commands)
        for name in ("run", "plot", "export", "check", "runtimes", "benchmarks"):
            assert name in commands

    def test_a_command_is_required(self):
        parser = ArgumentParser()
        cli.setup_subparsers(parser, commands)
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_each_subcommand_gets_a_handler(self):
        parser = ArgumentParser()
        cli.setup_subparsers(parser, commands)
        args = parser.parse_args(["benchmarks", "list"])
        assert args._func is benchmarks.main

    def test_help_comes_from_the_module_docstring(self):
        """setup_subparsers reads the first docstring line, so a module
        without one would crash the whole CLI at startup."""

        for name, module in commands.items():
            assert module.__doc__, f"{name} has no docstring for its help text"
            assert module.__doc__.split("\n")[0].strip()

    def test_version_is_reported_and_exits_cleanly(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["wasure", "--version"])
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
        assert exit_info.value.code == 0
        assert "WASURE" in capsys.readouterr().out

    def test_unknown_command_exits_nonzero(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["wasure", "nonsense"])
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
        assert exit_info.value.code != 0

    def test_setup_logging_sets_the_root_level(self):
        """basicConfig only takes effect when the root logger is unconfigured,
        which is the case when wasure runs as a command but not under pytest,
        so the handlers are cleared first."""

        import logging

        root = logging.getLogger()
        saved = root.handlers[:]
        try:
            root.handlers.clear()
            cli.setup_logging(logging.DEBUG)
            assert root.level == logging.DEBUG
        finally:
            root.handlers[:] = saved
            root.setLevel(logging.WARNING)


class TestDispatch:
    def test_a_successful_command_returns_zero(self, monkeypatch, benchmarks_folder):
        monkeypatch.setattr(sys, "argv", [
            "wasure", "benchmarks", "list",
            "--benchmarks-folder", benchmarks_folder,
            "--log-level", "ERROR",
        ])
        assert cli.main() == 0

    def test_a_failing_command_returns_nonzero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "wasure", "plot", str(tmp_path / "missing.json"),
            "--plots-folder", str(tmp_path),
            "--log-level", "ERROR",
        ])
        assert cli.main() == 1

    def test_the_module_entry_point_exists(self):
        """python -m wasure must work, not just the console script."""

        import wasure.__main__ as module_entry

        assert module_entry.main is cli.main

    def test_running_as_a_module_reports_the_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "wasure", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "WASURE" in result.stdout

    def test_running_as_a_module_propagates_failure(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "wasure", "plot",
             str(tmp_path / "missing.json"), "--log-level", "ERROR"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


class TestRunArguments:
    def test_defaults(self):
        args = parsed(run, [])
        assert args.runtimes == ["all"]
        assert args.benchmarks == ["all"]
        assert args.repeat == 1
        assert args.timeout is None
        assert args.memory is False
        assert args.no_store_output is False

    def test_selections_accept_several_values(self):
        args = parsed(run, ["-r", "a", "b", "-b", "x", "y/z"])
        assert args.runtimes == ["a", "b"]
        assert args.benchmarks == ["x", "y/z"]

    def test_repeat_and_timeout_are_integers(self):
        args = parsed(run, ["--repeat", "5", "--timeout", "30"])
        assert (args.repeat, args.timeout) == (5, 30)

    def test_a_non_numeric_repeat_is_rejected(self):
        with pytest.raises(SystemExit):
            parsed(run, ["--repeat", "many"])

    def test_folders_can_be_overridden(self, tmp_path):
        args = parsed(run, ["--results-folder", str(tmp_path)])
        assert args.results_folder == str(tmp_path)

    def test_folder_defaults_point_inside_the_package(self):
        args = parsed(run, [])
        assert args.benchmarks_folder.endswith("benchmarks")
        assert args.runtimes_folder.endswith("runtimes")


class TestPlotArguments:
    def test_results_file_is_required(self):
        with pytest.raises(SystemExit):
            parsed(plot, [])

    def test_statistic_defaults_to_median(self):
        assert parsed(plot, ["r.json"]).statistic == "median"

    @pytest.mark.parametrize("name", ["mean", "median", "min"])
    def test_statistic_accepts_each_choice(self, name):
        assert parsed(plot, ["r.json", "--statistic", name]).statistic == name

    def test_an_unknown_statistic_is_rejected(self):
        with pytest.raises(SystemExit):
            parsed(plot, ["r.json", "--statistic", "geomean"])


class TestExportArguments:
    def test_results_file_is_required(self):
        with pytest.raises(SystemExit):
            parsed(export, [])

    def test_memory_defaults_off(self):
        assert parsed(export, ["r.json"]).memory is False

    def test_memory_can_be_requested(self):
        assert parsed(export, ["r.json", "--memory"]).memory is True


class TestCheckArguments:
    def test_a_benchmark_is_required(self):
        with pytest.raises(SystemExit):
            parsed(check, [])

    def test_runtimes_default_to_all(self):
        assert parsed(check, ["wasm-features"]).runtimes == ["all"]

    def test_runtimes_can_be_narrowed(self):
        args = parsed(check, ["wasm-features", "-r", "one", "two"])
        assert args.runtimes == ["one", "two"]


class TestBenchmarksArguments:
    def test_an_operation_is_required(self):
        with pytest.raises(SystemExit):
            parsed(benchmarks, [])

    def test_list_is_accepted(self):
        assert parsed(benchmarks, ["list"]).operation == "list"

    def test_log_level_is_available_on_the_subcommand(self):
        assert parsed(benchmarks, ["list", "--log-level", "DEBUG"]).log_level == "DEBUG"


class TestRuntimesArguments:
    def test_an_operation_is_required(self):
        with pytest.raises(SystemExit):
            parsed(runtimes, [])

    @pytest.mark.parametrize(
        "argv,operation",
        [
            (["list"], "list"),
            (["available"], "available"),
            (["install", "x"], "install"),
            (["remove", "x"], "remove"),
            (["update", "x"], "update"),
            (["version"], "version"),
        ],
    )
    def test_each_operation_parses(self, argv, operation):
        assert parsed(runtimes, argv).operation == operation

    @pytest.mark.parametrize("operation", ["install", "remove", "update"])
    def test_operations_on_a_runtime_need_its_name(self, operation):
        with pytest.raises(SystemExit):
            parsed(runtimes, [operation])

    def test_install_flags_default_off(self):
        args = parsed(runtimes, ["install", "x"])
        assert args.no_runtime_check is False
        assert args.allow_partial is False

    def test_install_flags_can_be_set(self):
        args = parsed(runtimes, ["install", "x", "--no-runtime-check", "--allow-partial"])
        assert args.no_runtime_check is True
        assert args.allow_partial is True


class TestLogLevelArgument:
    def test_it_defaults_to_info(self):
        parser = ArgumentParser()
        from wasure.tools import utils

        utils.add_log_level_argument(parser)
        assert parser.parse_args([]).log_level == "INFO"

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
    def test_each_level_is_accepted(self, level):
        parser = ArgumentParser()
        from wasure.tools import utils

        utils.add_log_level_argument(parser)
        assert parser.parse_args(["--log-level", level]).log_level == level

    def test_an_unknown_level_is_rejected(self):
        parser = ArgumentParser()
        from wasure.tools import utils

        utils.add_log_level_argument(parser)
        with pytest.raises(SystemExit):
            parser.parse_args(["--log-level", "TRACE"])


class TestBenchmarksCommand:
    def test_it_lists_groups_and_their_benchmarks(self, benchmarks_folder, capsys):
        args = parsed(benchmarks, ["list", "--benchmarks-folder", benchmarks_folder])
        assert benchmarks.main(args) in (None, 0)
        printed = capsys.readouterr().out
        assert "alpha" in printed and "one" in printed and "three" in printed

    def test_an_empty_folder_is_reported(self, tmp_path, capsys):
        empty = tmp_path / "none"
        empty.mkdir()
        args = parsed(benchmarks, ["list", "--benchmarks-folder", str(empty)])
        benchmarks.main(args)
        assert "No benchmarks found" in capsys.readouterr().out

    def test_an_unknown_operation_is_reported(self, benchmarks_folder, capsys):
        from types import SimpleNamespace

        benchmarks.main(
            SimpleNamespace(
                operation="frobnicate",
                benchmarks_folder=benchmarks_folder,
                log_level="ERROR",
            )
        )
        assert "Unknown operation" in capsys.readouterr().out


class TestCheckCommand:
    @pytest.fixture
    def checkable(self, tmp_path, benchmarks_folder):
        """A runtimes file with one passing and one failing runtime."""

        path = tmp_path / "rt" / "runtimes.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "runtimes": [
                        {"name": "good", "desc": "works", "command": "true # {payload}"},
                        {"name": "bad", "desc": "fails", "command": "false # {payload}"},
                    ]
                }
            )
        )
        return str(path), str(path.parent)

    def test_it_reports_a_tick_and_a_cross(self, checkable, benchmarks_folder, capsys):
        runtimes_file, runtimes_folder = checkable
        args = parsed(
            check,
            ["alpha", "--benchmarks-folder", benchmarks_folder,
             "--runtimes-file", runtimes_file, "--runtimes-folder", runtimes_folder],
        )
        assert check.main(args) in (None, 0)
        printed = capsys.readouterr().out
        assert "good" in printed and "bad" in printed
        assert "✓" in printed and "X" in printed

    def test_it_fails_when_no_runtime_matches(self, checkable, benchmarks_folder):
        runtimes_file, runtimes_folder = checkable
        args = parsed(
            check,
            ["alpha", "-r", "absent", "--benchmarks-folder", benchmarks_folder,
             "--runtimes-file", runtimes_file, "--runtimes-folder", runtimes_folder],
        )
        assert check.main(args) == 1

    def test_it_fails_when_the_benchmark_is_unknown(self, checkable, benchmarks_folder):
        runtimes_file, runtimes_folder = checkable
        args = parsed(
            check,
            ["nonexistent", "--benchmarks-folder", benchmarks_folder,
             "--runtimes-file", runtimes_file, "--runtimes-folder", runtimes_folder],
        )
        assert check.main(args) == 1


class TestRunCommandSelection:
    """`run` must fail rather than silently produce an empty results file."""

    def _args(self, tmp_path, benchmarks_folder, runtimes_file, **extra):
        base = dict(
            runtimes=["all"], benchmarks=["all"], no_store_output=True,
            benchmarks_folder=benchmarks_folder, runtimes_file=str(runtimes_file),
            runtimes_folder=str(tmp_path), results_folder=str(tmp_path / "out"),
            repeat=1, memory=False, timeout=None, log_level="ERROR",
        )
        base.update(extra)
        from types import SimpleNamespace

        return SimpleNamespace(**base)

    def test_it_fails_when_no_runtime_is_installed(self, tmp_path, benchmarks_folder):
        assert run.main(
            self._args(tmp_path, benchmarks_folder, tmp_path / "absent.json")
        ) == 1

    def test_it_fails_when_no_benchmark_matches(self, tmp_path, benchmarks_folder):
        runtimes_file = tmp_path / "rt.json"
        runtimes_file.write_text(
            json.dumps({"runtimes": [
                {"name": "e", "desc": "d", "command": "true # {payload}"}
            ]})
        )
        assert run.main(
            self._args(tmp_path, benchmarks_folder, runtimes_file,
                       benchmarks=["nonexistent"])
        ) == 1

    def test_no_results_file_is_written_when_it_fails(
        self, tmp_path, benchmarks_folder
    ):
        run.main(self._args(tmp_path, benchmarks_folder, tmp_path / "absent.json"))
        assert not (tmp_path / "out").exists()
