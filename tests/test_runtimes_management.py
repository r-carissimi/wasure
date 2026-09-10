"""Tests for installing, updating and removing runtimes.

This is the code path the real installer bugs lived in -- wasmer silently
shipping one of four backends, six WAMR variants failing at cmake -- and it
was entirely untested because exercising it appeared to require downloading
engines. It does not: an installer is a JSON file whose install-command is an
arbitrary shell command, so a "runtime" that is `mkdir` plus `true` drives the
whole flow.
"""

import json
import os
from types import SimpleNamespace

import pytest

from wasure.tools import runtimes


def installer(name, **overrides):
    """A mock installer that installs by creating its own directory."""

    spec = {
        "name": name,
        "desc": f"mock runtime {name}",
        "install-dir": name,
        "install-command": f"mkdir -p {name} && echo installed",
        "update-command": f"echo updated {name}",
        "version-command": f"echo '{name} 1.0.0'",
        "command": "true # {payload}",
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def installers_folder(tmp_path):
    """A folder of mock installers covering the outcomes install must handle."""

    folder = tmp_path / "installers"
    folder.mkdir()

    specs = [
        # Installs cleanly.
        installer("plain"),
        # Two working configurations and one that fails its dummy run, which
        # is the shape that hid the wasmer bug.
        installer(
            "multi",
            subruntimes=[
                {"name": "multi-ok", "desc": "works", "command": "true # {payload}"},
                {"name": "multi-bad", "desc": "fails", "command": "false # {payload}"},
            ],
        ),
        # The install command itself fails.
        installer("broken", **{"install-command": "exit 1"}),
        # Installs, but the binary does not run, so the version is unknown.
        installer("unversioned", **{"version-command": "exit 1"}),
        # Installs and runs, but the payload itself fails.
        installer("nonworking", command="false # {payload}"),
        # No update path.
        installer("frozen", **{"update-command": None}),
    ]
    for spec in specs:
        spec = {k: v for k, v in spec.items() if v is not None}
        (folder / f"{spec['name']}.json").write_text(json.dumps(spec))

    # Not JSON, and a JSON file without a name: both must be skipped.
    (folder / "notes.txt").write_text("ignore me")
    (folder / "invalid.json").write_text("{ not json")
    (folder / "nameless.json").write_text(json.dumps({"desc": "no name"}))

    return str(folder)


@pytest.fixture
def dummy_benchmarks(tmp_path):
    """The benchmarks folder the post-install check needs.

    _check_runtime_installation always runs dummy/dummy.wasm.
    """

    folder = tmp_path / "benchmarks" / "dummy"
    folder.mkdir(parents=True)
    (folder / "dummy.wasm").write_bytes(b"\0asm\x01\0\0\0")
    (folder / "benchmarks.json").write_text(
        json.dumps({"benchmarks": [{"name": "dummy", "path": "dummy.wasm"}]})
    )
    return str(tmp_path / "benchmarks")


@pytest.fixture
def env(tmp_path, installers_folder, dummy_benchmarks):
    """Argument namespaces for each runtimes subcommand."""

    runtimes_folder = tmp_path / "rt"
    runtimes_file = runtimes_folder / "runtimes.json"

    def args(operation, **extra):
        base = {
            "operation": operation,
            "log_level": "ERROR",
            "runtimes_folder": str(runtimes_folder),
            "runtimes_file": str(runtimes_file),
            "installers_folder": installers_folder,
            "benchmarks_folder": dummy_benchmarks,
            "no_runtime_check": False,
            "allow_partial": False,
            "name": None,
        }
        base.update(extra)
        return SimpleNamespace(**base)

    return SimpleNamespace(
        args=args, folder=str(runtimes_folder), file=str(runtimes_file)
    )


def installed(env):
    """Names recorded in the runtimes file, parents and subruntimes alike."""

    if not os.path.exists(env.file):
        return {}
    with open(env.file) as f:
        return {
            r["name"]: [s["name"] for s in r.get("subruntimes", [])]
            for r in json.load(f).get("runtimes", [])
        }


class TestListingAvailable:
    def test_lists_the_valid_installers(self, env, capsys):
        assert runtimes.main(env.args("available")) in (None, 0)
        printed = capsys.readouterr().out
        for name in ("plain", "multi", "broken"):
            assert name in printed

    def test_skips_files_that_are_not_valid_installers(self, env, capsys):
        runtimes.main(env.args("available"))
        printed = capsys.readouterr().out
        assert "nameless" not in printed
        assert "ignore me" not in printed

    def test_reports_when_the_folder_has_no_installers(self, env, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        runtimes.main(env.args("available", installers_folder=str(empty)))
        assert "No runtimes found" in capsys.readouterr().out

    def test_a_missing_folder_is_not_fatal(self, env, tmp_path, capsys):
        runtimes.main(
            env.args("available", installers_folder=str(tmp_path / "absent"))
        )
        assert "No runtimes found" in capsys.readouterr().out


class TestInstalling:
    def test_a_clean_install_is_recorded(self, env, capsys):
        assert runtimes.main(env.args("install", name="plain")) in (None, 0)
        assert "plain" in installed(env)
        assert os.path.isdir(os.path.join(env.folder, "plain"))

    def test_installing_an_unknown_runtime_fails(self, env, capsys):
        assert runtimes.main(env.args("install", name="absent")) == 1
        assert "not found" in capsys.readouterr().out

    def test_a_failing_install_command_fails(self, env, capsys):
        assert runtimes.main(env.args("install", name="broken")) == 1
        assert installed(env) == {}

    def test_an_engine_whose_version_cannot_be_read_fails(self, env):
        """A binary that will not report its version did not install properly."""

        assert runtimes.main(env.args("install", name="unversioned")) == 1
        assert installed(env) == {}

    def test_an_engine_that_cannot_run_the_dummy_fails(self, env, capsys):
        assert runtimes.main(env.args("install", name="nonworking")) == 1
        assert "does not work" in capsys.readouterr().out
        assert installed(env) == {}

    def test_the_dummy_check_can_be_skipped(self, env):
        """--no-runtime-check accepts an engine without proving it runs."""

        assert runtimes.main(
            env.args("install", name="nonworking", no_runtime_check=True)
        ) in (None, 0)
        assert "nonworking" in installed(env)

    def test_installing_twice_is_not_an_error(self, env, capsys):
        runtimes.main(env.args("install", name="plain"))
        assert runtimes.main(env.args("install", name="plain")) == 0
        assert "already installed" in capsys.readouterr().out

    def test_a_stale_install_directory_is_replaced(self, env):
        stale = os.path.join(env.folder, "plain")
        os.makedirs(stale)
        with open(os.path.join(stale, "leftover"), "w") as f:
            f.write("old")
        runtimes.main(env.args("install", name="plain"))
        assert not os.path.exists(os.path.join(stale, "leftover"))

    def test_the_install_command_is_not_stored(self, env):
        """Storing it would let a stale command be re-run on update."""

        runtimes.main(env.args("install", name="plain"))
        with open(env.file) as f:
            entry = json.load(f)["runtimes"][0]
        assert "install-command" not in entry


class TestPartialInstalls:
    """A runtime can install while losing some of its configurations.

    Those were previously discarded with only a logging warning, so an engine
    could ship most of its backends missing and still look fine.
    """

    def test_working_configurations_are_kept(self, env):
        runtimes.main(env.args("install", name="multi"))
        assert installed(env)["multi"] == ["multi-ok"]

    def test_a_partial_install_is_reported_and_fails(self, env, capsys):
        assert runtimes.main(env.args("install", name="multi")) == 1
        printed = capsys.readouterr().out
        assert "multi-bad" in printed
        assert "1 of 2" in printed

    def test_allow_partial_accepts_it(self, env):
        assert runtimes.main(
            env.args("install", name="multi", allow_partial=True)
        ) == 0
        assert installed(env)["multi"] == ["multi-ok"]

    def test_a_complete_install_says_so(self, env, capsys):
        runtimes.main(env.args("install", name="plain"))
        assert "installed successfully" in capsys.readouterr().out


class TestListingInstalled:
    def test_nothing_installed(self, env, capsys):
        assert runtimes.main(env.args("list")) in (None, 0)
        assert "No runtimes found" in capsys.readouterr().out

    def test_shows_runtimes_and_their_configurations(self, env, capsys):
        runtimes.main(env.args("install", name="multi", allow_partial=True))
        capsys.readouterr()
        runtimes.main(env.args("list"))
        printed = capsys.readouterr().out
        assert "multi" in printed
        assert "multi-ok" in printed


class TestVersions:
    def test_reports_the_installed_version(self, env, capsys):
        runtimes.main(env.args("install", name="plain"))
        capsys.readouterr()
        assert runtimes.main(env.args("version")) in (None, 0)
        assert "plain 1.0.0" in capsys.readouterr().out

    def test_fails_when_nothing_is_installed(self, env, capsys):
        assert runtimes.main(env.args("version")) == 1
        assert "No runtimes found" in capsys.readouterr().out

    def test_an_unreadable_version_does_not_abort_the_listing(self, env, capsys):
        """One broken engine must not hide the others."""

        runtimes.main(env.args("install", name="plain"))
        # Corrupt the recorded version-command for the installed runtime.
        with open(env.file) as f:
            data = json.load(f)
        data["runtimes"].append(
            {"name": "ghost", "desc": "gone", "version-command": "exit 1",
             "command": "true # {payload}"}
        )
        with open(env.file, "w") as f:
            json.dump(data, f)
        capsys.readouterr()
        runtimes.main(env.args("version"))
        assert "plain 1.0.0" in capsys.readouterr().out


class TestUpdating:
    def test_updates_an_installed_runtime(self, env):
        runtimes.main(env.args("install", name="plain"))
        assert runtimes.main(env.args("update", name="plain")) in (None, 0)

    def test_updating_something_not_installed_fails(self, env, capsys):
        assert runtimes.main(env.args("update", name="plain")) == 1
        assert "not installed" in capsys.readouterr().out

    def test_a_runtime_without_an_update_command_says_so(self, env, capsys):
        runtimes.main(env.args("install", name="frozen"))
        capsys.readouterr()
        assert runtimes.main(env.args("update", name="frozen")) == 1
        assert "does not support update" in capsys.readouterr().out

    def test_a_failing_update_is_reported(self, env, capsys):
        runtimes.main(env.args("install", name="plain"))
        with open(env.file) as f:
            data = json.load(f)
        data["runtimes"][0]["update-command"] = "exit 1"
        with open(env.file, "w") as f:
            json.dump(data, f)
        capsys.readouterr()
        assert runtimes.main(env.args("update", name="plain")) == 1
        assert "failed to update" in capsys.readouterr().out


class TestRemoving:
    def test_removes_the_entry_and_the_directory(self, env, capsys):
        runtimes.main(env.args("install", name="plain"))
        capsys.readouterr()
        assert runtimes.main(env.args("remove", name="plain")) in (None, 0)
        assert installed(env) == {}
        assert not os.path.exists(os.path.join(env.folder, "plain"))
        assert "removed successfully" in capsys.readouterr().out

    def test_removing_something_not_installed_fails(self, env, capsys):
        assert runtimes.main(env.args("remove", name="plain")) == 1
        assert "not installed" in capsys.readouterr().out

    def test_a_missing_directory_does_not_prevent_removal(self, env):
        """The entry must still go, or the runtime becomes unremovable."""

        runtimes.main(env.args("install", name="plain"))
        import shutil

        shutil.rmtree(os.path.join(env.folder, "plain"))
        assert runtimes.main(env.args("remove", name="plain")) in (None, 0)
        assert installed(env) == {}

    def test_a_runtime_without_an_install_dir_is_still_removed(self, env, tmp_path):
        os.makedirs(env.folder, exist_ok=True)
        with open(env.file, "w") as f:
            json.dump(
                {"runtimes": [{"name": "manual", "desc": "hand added",
                               "command": "true # {payload}"}]},
                f,
            )
        assert runtimes.main(env.args("remove", name="manual")) in (None, 0)
        assert installed(env) == {}


class TestUnknownOperation:
    def test_it_fails_rather_than_doing_nothing(self, env, capsys):
        assert runtimes.main(env.args("frobnicate")) == 1
        assert "Unknown operation" in capsys.readouterr().out


class TestWritingTheRuntimesFile:
    def test_a_write_failure_is_logged_not_raised(self, env, tmp_path, caplog):
        """The install has already happened by this point, so raising here
        would leave the engine on disk but unrecorded with a traceback."""

        unwritable = tmp_path / "nodir" / "runtimes.json"
        runtimes._add_runtime_to_runtimes_file(
            {"name": "x", "desc": "y"}, str(unwritable)
        )
        assert "Failed to add runtime" in caplog.text

    def test_a_removal_failure_is_logged_not_raised(self, tmp_path, caplog):
        runtimes._remove_runtime_from_runtimes_file(
            "x", str(tmp_path / "nodir" / "runtimes.json")
        )
        assert "Failed to remove runtime" in caplog.text
