"""Shared fixtures for the WASURE test suite.

The key idea here is that a runtime is only a JSON `command` template that
gets run through a shell. Nothing in wasure requires that command to be a
real WebAssembly engine, so almost the whole run pipeline can be tested with
a "runtime" that is a plain shell command with predictable output. That keeps
the suite fast and lets it run in CI with no engines installed.
"""

import json
import os

# Force a non-interactive matplotlib backend before wasure.tools.plot imports
# pyplot, so the plot tests never try to open a window.
os.environ.setdefault("MPLBACKEND", "Agg")

import pytest

from helpers import make_runtime


@pytest.fixture
def runtime_factory():
    return make_runtime


@pytest.fixture
def benchmarks_folder(tmp_path):
    """A benchmarks folder laid out the way wasure expects.

    Contains two groups so that group selection, single-benchmark selection
    and the "all" case can all be exercised.
    """

    root = tmp_path / "benchmarks"

    alpha = root / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "one.wasm").write_bytes(b"\0asm\x01\0\0\0")
    (alpha / "two.wasm").write_bytes(b"\0asm\x01\0\0\0")
    (alpha / "benchmarks.json").write_text(
        json.dumps(
            {
                "benchmarks": [
                    {"name": "one", "path": "one.wasm"},
                    {"name": "two", "path": "two.wasm", "args": "7"},
                ]
            }
        )
    )

    beta = root / "beta"
    beta.mkdir(parents=True)
    (beta / "three.wasm").write_bytes(b"\0asm\x01\0\0\0")
    (beta / "benchmarks.json").write_text(
        json.dumps({"benchmarks": [{"name": "three", "path": "three.wasm"}]})
    )

    # A directory without benchmarks.json must not be treated as a group.
    (root / "not-a-group").mkdir()

    return str(root)


@pytest.fixture
def benchmark():
    """A minimal benchmark. Its payload need not exist unless the runtime reads it."""

    return {"name": "one", "path": "alpha/one.wasm"}


@pytest.fixture
def runtimes_file(tmp_path):
    """A runtimes.json containing one runtime with two subruntimes."""

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
                        "subruntimes": [
                            {
                                "name": "engine-jit",
                                "desc": "jit mode",
                                "command": "true # {payload}",
                            },
                            {
                                "name": "engine-int",
                                "desc": "interpreter mode",
                                "command": "true # {payload}",
                            },
                        ],
                    }
                ]
            }
        )
    )
    return str(path)


@pytest.fixture
def results():
    """A results structure shaped the way `wasure run` writes it.

    Note the nesting is results[runtime][benchmark], which is the opposite of
    the CSV column order and an easy thing to get backwards.
    """

    return {
        "fast": {
            "one": [
                {"elapsed_time_ns": 1000, "score": 0, "return_code": 0},
                {"elapsed_time_ns": 1200, "score": 0, "return_code": 0},
            ],
            "two": [{"elapsed_time_ns": 2000, "score": 0, "return_code": 0}],
        },
        "slow": {
            "one": [{"elapsed_time_ns": 5000, "score": 0, "return_code": 0}],
            "two": [{"elapsed_time_ns": 9000, "score": 0, "return_code": 0}],
        },
    }


@pytest.fixture
def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
