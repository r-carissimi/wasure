"""Helpers shared between test modules.

Kept separate from conftest.py so that test modules can import it directly
without the tests directory having to be a package.
"""


def make_runtime(name="mock", command="true", **extra):
    """Build a runtime dict whose command is an ordinary shell command.

    Nothing in wasure requires a runtime's command to be a real WebAssembly
    engine, so a plain shell command with predictable output is enough to
    exercise the run pipeline. `{payload}` is appended when the template does
    not already reference it, so callers can pass a bare command such as
    "exit 3" and still exercise the normal path formatting.
    """

    if "{payload}" not in command:
        command = f"{command} # {{payload}}"
    return {"name": name, "desc": f"mock runtime {name}", "command": command, **extra}
