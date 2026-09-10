"""Validation of the JSON manifests that ship with WASURE.

Runtimes and benchmarks are declarations rather than code, so nothing checks
them at import time and a typo stays invisible until a benchmark silently
scores zero or a runtime is quietly discarded. These tests parse every
shipped manifest and assert the invariants the loader relies on.
"""

import glob
import json
import os
import re

import pytest


def installer_files(repo_root):
    return sorted(glob.glob(os.path.join(repo_root, "wasure", "installers", "*.json")))


def benchmark_files(repo_root):
    return sorted(
        glob.glob(os.path.join(repo_root, "wasure", "benchmarks", "*", "benchmarks.json"))
    )


def load(path):
    with open(path) as f:
        return json.load(f)


def named_groups(pattern):
    return set(re.compile(pattern).groupindex)


# --------------------------------------------------------------------------
# Installers
# --------------------------------------------------------------------------


def test_installers_are_present(repo_root):
    assert len(installer_files(repo_root)) > 10


@pytest.fixture(params=None)
def installer(request):
    return request.param


def pytest_generate_tests(metafunc):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "installer_path" in metafunc.fixturenames:
        paths = installer_files(root)
        metafunc.parametrize(
            "installer_path", paths, ids=[os.path.basename(p) for p in paths]
        )
    if "benchmark_path" in metafunc.fixturenames:
        paths = benchmark_files(root)
        metafunc.parametrize(
            "benchmark_path",
            paths,
            ids=[os.path.basename(os.path.dirname(p)) for p in paths],
        )


class TestInstallerManifests:
    def test_is_valid_json(self, installer_path):
        load(installer_path)

    def test_has_the_required_fields(self, installer_path):
        data = load(installer_path)
        for field in ("name", "desc", "command", "version-command", "install-command"):
            assert field in data, f"missing required field {field!r}"

    def test_declares_an_install_dir(self, installer_path):
        """Without it, `runtimes remove` cannot delete the runtime's files."""

        assert "install-dir" in load(installer_path)

    def test_run_command_references_the_payload(self, installer_path):
        data = load(installer_path)
        assert "{payload}" in data["command"]

    def test_entrypoint_flag_is_defined_when_used(self, installer_path):
        data = load(installer_path)
        for config in [data] + data.get("subruntimes", []):
            if "{entrypoint_flag}" in config.get("command", ""):
                assert "entrypoint-flag" in config, (
                    f"{config.get('name')} substitutes an entrypoint flag "
                    "but does not define one"
                )

    def test_aot_command_references_input_and_output(self, installer_path):
        data = load(installer_path)
        for config in [data] + data.get("subruntimes", []):
            aot = config.get("aot-command")
            if aot:
                assert "{input}" in aot and "{output}" in aot, config.get("name")

    def test_stats_parser_groups_match_their_keys(self, installer_path):
        """Each stats-parser regex must capture a group named after its key,
        otherwise the statistic is silently never recorded."""

        data = load(installer_path)
        for config in [data] + data.get("subruntimes", []):
            for key, pattern in (config.get("stats-parser") or {}).items():
                assert key in named_groups(pattern), (
                    f"{config.get('name')}: stats-parser {key!r} has no "
                    f"(?P<{key}>...) group"
                )

    def test_subruntimes_are_well_formed(self, installer_path):
        data = load(installer_path)
        for sub in data.get("subruntimes", []):
            assert "name" in sub and "desc" in sub and "command" in sub
            # These belong to the installation, which a subruntime shares.
            for forbidden in ("version-command", "install-dir", "update-command"):
                assert forbidden not in sub, (
                    f"{sub['name']} redefines {forbidden!r}, which is a "
                    "property of the installation"
                )
            assert "subruntimes" not in sub, "subruntimes cannot be nested"


class TestInstallerIsolation:
    """Installers must not modify the user's machine outside the runtimes folder.

    Vendor install scripts routinely append a `source .../env` line to the
    user's shell startup files. Since WASURE installs engines into a
    throwaway-able runtimes directory, such a line outlives the install and
    breaks every new shell once the directory is removed. This happened with
    wasmedge, which left two dangling lines in a real ~/.zshenv.
    """

    # Ways an installer can stop a vendor script writing to shell startup
    # files: redirect the file it edits, redirect HOME so it edits a throwaway
    # copy, or pass the script's own opt-out flag.
    NEUTRALIZERS = (
        "PROFILE=",
        "HOME=",
        "XDG_CONFIG_HOME=",
        "--no-modify-shell-profile",
        "--no-modify-path",
    )

    def _pipes_a_remote_script(self, command):
        fetches = "curl" in command or "wget" in command
        pipes_to_shell = "| bash" in command or "| sh" in command or "|bash" in command
        return fetches and pipes_to_shell

    def test_piped_installers_cannot_edit_shell_startup_files(self, installer_path):
        data = load(installer_path)
        for key in ("install-command", "update-command"):
            command = data.get(key, "")
            if not self._pipes_a_remote_script(command):
                continue
            assert any(n in command for n in self.NEUTRALIZERS), (
                f"{data['name']}: {key} pipes a remote script into a shell "
                "without preventing it from editing shell startup files. Set "
                "PROFILE or HOME to somewhere disposable, or pass the "
                "script's opt-out flag."
            )

    def test_installs_stay_inside_the_runtimes_folder(self, installer_path):
        """install-dir is relative, so an absolute or escaping path would
        write outside the directory the user asked us to use."""

        install_dir = load(installer_path).get("install-dir", "")
        assert install_dir, "install-dir is required"
        assert not os.path.isabs(install_dir), install_dir
        assert ".." not in install_dir.split(os.sep), install_dir


class TestInstallerNaming:
    def test_names_are_unique_across_all_installers(self, repo_root):
        names = []
        for path in installer_files(repo_root):
            data = load(path)
            names.append(data["name"])
            names.extend(sub["name"] for sub in data.get("subruntimes", []))
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, f"duplicate runtime names: {duplicates}"

    def test_no_runtime_is_called_all(self, repo_root):
        """"all" is reserved by the -r flag to mean every runtime."""

        for path in installer_files(repo_root):
            data = load(path)
            assert data["name"] != "all"
            assert all(s["name"] != "all" for s in data.get("subruntimes", []))

    def test_names_are_usable_as_command_line_arguments(self, repo_root):
        """The name is what `runtimes install` and `-r` match on, so a name
        containing whitespace has to be quoted to be usable at all."""

        offenders = {
            os.path.basename(path): load(path)["name"]
            for path in installer_files(repo_root)
            if load(path)["name"] != load(path)["name"].strip()
            or re.search(r"\s", load(path)["name"])
        }
        assert not offenders, (
            "runtime names containing whitespace must be quoted on the command "
            f"line: {offenders}"
        )


# --------------------------------------------------------------------------
# Benchmarks
# --------------------------------------------------------------------------


class TestBenchmarkManifests:
    def test_is_valid_json(self, benchmark_path):
        load(benchmark_path)

    def test_declares_benchmarks(self, benchmark_path):
        assert load(benchmark_path).get("benchmarks")

    def test_entries_have_a_name_and_path(self, benchmark_path):
        for entry in load(benchmark_path)["benchmarks"]:
            assert "name" in entry and "path" in entry, entry

    def test_payloads_exist(self, benchmark_path):
        group = os.path.dirname(benchmark_path)
        missing = [
            entry["path"]
            for entry in load(benchmark_path)["benchmarks"]
            if not os.path.exists(os.path.join(group, entry["path"]))
        ]
        assert not missing, f"manifest references missing payloads: {missing}"

    def test_names_are_unique_within_a_group(self, benchmark_path):
        names = [entry["name"] for entry in load(benchmark_path)["benchmarks"]]
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, f"duplicate benchmark names: {duplicates}"

    def test_score_parsers_capture_a_score_group(self, benchmark_path):
        """A score-parser without a (?P<score>...) group would raise at
        runtime; one that never matches silently records zero."""

        for entry in load(benchmark_path)["benchmarks"]:
            pattern = entry.get("score-parser")
            if pattern:
                assert "score" in named_groups(pattern), (
                    f"{entry['name']}: score-parser has no (?P<score>...) group"
                )

    def test_regexes_compile(self, benchmark_path):
        for entry in load(benchmark_path)["benchmarks"]:
            for field in ("score-parser", "output-validator"):
                if entry.get(field):
                    re.compile(entry[field])

    def test_args_only_use_the_path_placeholder(self, benchmark_path):
        """args is formatted with path= only, so any other placeholder raises."""

        for entry in load(benchmark_path)["benchmarks"]:
            for placeholder in re.findall(r"\{(\w+)\}", entry.get("args", "")):
                assert placeholder == "path", (
                    f"{entry['name']}: unsupported placeholder {{{placeholder}}} in args"
                )


class TestBenchmarkGroupNaming:
    def test_no_group_is_called_all(self, repo_root):
        for path in benchmark_files(repo_root):
            assert os.path.basename(os.path.dirname(path)) != "all"

    def test_group_names_have_no_slashes(self, repo_root):
        """Benchmarks are selected as "group/name", so a slash in a group name
        would make the benchmark unaddressable."""

        for path in benchmark_files(repo_root):
            assert "/" not in os.path.basename(os.path.dirname(path))
