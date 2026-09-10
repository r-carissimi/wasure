"""Tests for choosing which benchmarks and runtimes a run will use."""

import json
import os

from wasure.tools import benchmarks, run, runtimes


class TestListingGroups:
    def test_only_directories_with_a_manifest_are_groups(self, benchmarks_folder):
        assert sorted(benchmarks.list_groups(benchmarks_folder)) == ["alpha", "beta"]

    def test_missing_folder_is_not_fatal(self, tmp_path):
        assert benchmarks.list_groups(str(tmp_path / "absent")) == []

    def test_a_file_is_not_a_folder_of_groups(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_text("x")
        assert benchmarks.list_groups(str(path)) == []


class TestListingBenchmarks:
    def test_groups_map_to_their_benchmarks(self, benchmarks_folder):
        listed = benchmarks.list_benchmarks(benchmarks_folder)
        assert sorted(listed) == ["alpha", "beta"]
        assert [b["name"] for b in listed["alpha"]] == ["one", "two"]

    def test_malformed_manifest_is_skipped_not_raised(self, benchmarks_folder):
        broken = os.path.join(benchmarks_folder, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "benchmarks.json"), "w") as f:
            f.write("{not json")
        assert "broken" not in benchmarks.list_benchmarks(benchmarks_folder)

    def test_empty_manifest_is_skipped(self, benchmarks_folder):
        empty = os.path.join(benchmarks_folder, "empty")
        os.makedirs(empty)
        open(os.path.join(empty, "benchmarks.json"), "w").close()
        assert "empty" not in benchmarks.list_benchmarks(benchmarks_folder)

    def test_entries_missing_required_fields_are_dropped(self, benchmarks_folder):
        partial = os.path.join(benchmarks_folder, "partial")
        os.makedirs(partial)
        with open(os.path.join(partial, "benchmarks.json"), "w") as f:
            json.dump(
                {"benchmarks": [{"name": "no-path"}, {"name": "ok", "path": "a.wasm"}]},
                f,
            )
        assert [b["name"] for b in benchmarks.list_benchmarks(benchmarks_folder)["partial"]] == ["ok"]


class TestSelectingByName:
    def test_group_name_selects_the_whole_group(self, benchmarks_folder):
        selected = benchmarks.get_benchmark_from_name("alpha", benchmarks_folder)
        assert [b["name"] for b in selected["alpha"]] == ["one", "two"]

    def test_qualified_name_selects_one_benchmark(self, benchmarks_folder):
        selected = benchmarks.get_benchmark_from_name("alpha/two", benchmarks_folder)
        assert selected == {"alpha": [{"name": "two", "path": "two.wasm", "args": "7"}]}

    def test_unknown_group_returns_nothing(self, benchmarks_folder):
        assert benchmarks.get_benchmark_from_name("nope", benchmarks_folder) is None

    def test_unknown_benchmark_in_a_real_group_returns_nothing(self, benchmarks_folder):
        assert benchmarks.get_benchmark_from_name("alpha/nope", benchmarks_folder) is None

    def test_empty_name_returns_nothing(self, benchmarks_folder):
        assert benchmarks.get_benchmark_from_name("", benchmarks_folder) is None


class TestLoadBenchmarks:
    def test_all_selects_every_group(self, benchmarks_folder):
        loaded = run.load_benchmarks(["all"], benchmarks_folder)
        assert sorted(b["name"] for b in loaded) == ["one", "three", "two"]

    def test_paths_are_prefixed_with_their_group(self, benchmarks_folder):
        loaded = run.load_benchmarks(["alpha"], benchmarks_folder)
        assert {b["path"] for b in loaded} == {"alpha/one.wasm", "alpha/two.wasm"}

    def test_a_wasm_file_can_be_named_directly(self, benchmarks_folder):
        target = os.path.join(benchmarks_folder, "alpha", "one.wasm")
        loaded = run.load_benchmarks([target], benchmarks_folder)
        assert loaded == [{"name": "one.wasm", "path": os.path.abspath(target)}]

    def test_a_nonexistent_wasm_file_is_ignored(self, benchmarks_folder):
        assert run.load_benchmarks(["/nope/missing.wasm"], benchmarks_folder) == []

    def test_groups_and_files_can_be_mixed(self, benchmarks_folder):
        target = os.path.join(benchmarks_folder, "alpha", "one.wasm")
        loaded = run.load_benchmarks(["beta", target], benchmarks_folder)
        assert sorted(b["name"] for b in loaded) == ["one.wasm", "three"]

    def test_selecting_nothing_known_yields_nothing(self, benchmarks_folder):
        assert run.load_benchmarks(["nope"], benchmarks_folder) == []


class TestSelectingRuntimes:
    def test_all_flattens_subruntimes_alongside_their_parent(self, runtimes_file):
        selected = run.get_runtimes(runtimes_file, ["all"])
        assert [r["name"] for r in selected] == ["engine", "engine-jit", "engine-int"]

    def test_a_subruntime_can_be_selected_by_name(self, runtimes_file):
        selected = run.get_runtimes(runtimes_file, ["engine-int"])
        assert [r["name"] for r in selected] == ["engine-int"]

    def test_unknown_names_select_nothing(self, runtimes_file):
        assert run.get_runtimes(runtimes_file, ["absent"]) == []

    def test_parent_and_child_can_be_selected_together(self, runtimes_file):
        selected = run.get_runtimes(runtimes_file, ["engine", "engine-jit"])
        assert sorted(r["name"] for r in selected) == ["engine", "engine-jit"]


class TestListingRuntimes:
    def test_missing_file_is_not_fatal(self, tmp_path):
        assert runtimes.list_runtimes(str(tmp_path / "absent.json")) == []

    def test_empty_file_is_not_fatal(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("")
        assert runtimes.list_runtimes(str(path)) == []

    def test_file_without_the_runtimes_key_is_not_fatal(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"other": []}))
        assert runtimes.list_runtimes(str(path)) == []

    def test_named_lookup(self, runtimes_file):
        assert runtimes.get_runtime_from_name("engine", runtimes_file)["name"] == "engine"
        assert runtimes.get_runtime_from_name("absent", runtimes_file) is None


class TestManifestEdgeCases:
    def test_a_manifest_with_an_empty_benchmark_list_is_skipped(
        self, benchmarks_folder
    ):
        """Valid JSON declaring no benchmarks is different from an empty file."""

        group = os.path.join(benchmarks_folder, "declared-empty")
        os.makedirs(group)
        with open(os.path.join(group, "benchmarks.json"), "w") as f:
            json.dump({"benchmarks": []}, f)
        assert "declared-empty" not in benchmarks.list_benchmarks(benchmarks_folder)

    def test_a_qualified_name_in_an_unknown_group_returns_nothing(
        self, benchmarks_folder
    ):
        """Distinct from an unknown bare name: the group is checked first."""

        assert (
            benchmarks.get_benchmark_from_name("absent-group/one", benchmarks_folder)
            is None
        )
