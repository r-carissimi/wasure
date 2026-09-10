"""Manages WebAssembly runtimes

This module provides a command-line interface (CLI) for managing WebAssembly runtimes.
"""

import json
import logging
import os
import shutil
import subprocess

from . import run, utils


def parse(parser):
    """Parse command-line arguments for the runtime module.

    Args:
        parser (ArgumentParser): The argument parser to add subcommands to.
    """

    # We use os.path.dirname two times because the script is in the tools
    # folder and we want to get the runtimes folder.
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    subparsers = parser.add_subparsers(dest="operation", required=True)

    # "list" command to list installed runtimes
    list_parser = subparsers.add_parser(
        "list",
        help=list_runtimes.__doc__.split("\n")[0],
        description=list_runtimes.__doc__.split("\n")[0],
    )

    list_parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    # "available" command to list available runtimes
    available_parser = subparsers.add_parser(
        "available",
        help=_list_available_runtimes.__doc__.split("\n")[0],
        description=_list_available_runtimes.__doc__.split("\n")[0],
    )

    available_parser.add_argument(
        "--installers-folder",
        default=os.path.join(script_dir, utils.DEFAULT_INSTALLERS_FOLDER),
        help=f"Path to the folder containing installers (default: {utils.DEFAULT_INSTALLERS_FOLDER})",
    )

    # "install" command to install a runtime
    install_parser = subparsers.add_parser(
        "install",
        help="Install a runtime",
        description="Install a runtime",
    )

    install_parser.add_argument(
        "name",
        help="Name of the runtime to install",
        type=str,
    )

    install_parser.add_argument(
        "--installers-folder",
        default=os.path.join(script_dir, utils.DEFAULT_INSTALLERS_FOLDER),
        help=f"Path to the folder containing installers (default: {utils.DEFAULT_INSTALLERS_FOLDER})",
    )

    install_parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    install_parser.add_argument(
        "--runtimes-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FOLDER),
        help=f"Path to the folder containing runtimes (default: {utils.DEFAULT_RUNTIMES_FOLDER})",
    )

    install_parser.add_argument(
        "--benchmarks-folder",
        default=os.path.join(script_dir, utils.DEFAULT_BENCHMARKS_FOLDER),
        help=f"Path to the folder containing the benchmarks (default: {utils.DEFAULT_BENCHMARKS_FOLDER})",
    )

    install_parser.add_argument(
        "--no-runtime-check",
        action="store_true",
        default=False,
        help="Skip runtime check after installation",
    )

    install_parser.add_argument(
        "--allow-partial",
        action="store_true",
        default=False,
        help="Succeed even if some of the runtime's configurations do not work",
    )

    # "remove" command to remove a runtime
    remove_parser = subparsers.add_parser(
        "remove",
        help=_remove_runtime.__doc__.split("\n")[0],
        description=_remove_runtime.__doc__.split("\n")[0],
    )

    remove_parser.add_argument(
        "name",
        help="Name of the runtime to remove",
        type=str,
    )

    remove_parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    remove_parser.add_argument(
        "--runtimes-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FOLDER),
        help=f"Path to the folder containing runtimes (default: {utils.DEFAULT_RUNTIMES_FOLDER})",
    )

    # "version" command to get the version of all runtimes
    version_parser = subparsers.add_parser(
        "version",
        help="Get the version of all runtimes",
        description="Get the version of all runtimes",
    )

    version_parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    version_parser.add_argument(
        "--runtimes-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FOLDER),
        help=f"Path to the folder containing runtimes (default: {utils.DEFAULT_RUNTIMES_FOLDER})",
    )

    # "update" command to update the runtimes
    update_parser = subparsers.add_parser(
        "update",
        help="Update a runtime",
        description="Update a runtime",
    )

    update_parser.add_argument(
        "name",
        help="Name of the runtime to update",
        type=str,
    )

    update_parser.add_argument(
        "--runtimes-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FOLDER),
        help=f"Path to the folder containing runtimes (default: {utils.DEFAULT_RUNTIMES_FOLDER})",
    )

    update_parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    for subparser in subparsers.choices.values():
        utils.add_log_level_argument(subparser)

    return parser


def list_runtimes(file=utils.DEFAULT_RUNTIMES_FILE):
    """List installed runtimes.

    Args:
        file (str): Path to the JSON file containing runtimes. File must
                    exist but can be empty.
                    Note that no runtime should be called "all" as that
                    is reserved for selecting all the runtimes.

    Returns:
        list: List of installed runtimes, defined as a list of dictionaries
              containing runtime information. List is empty if no runtimes
              are found.

              Example:
                [
                    {
                        "name": "wasmtime",
                        "desc": "A standalone WebAssembly runtime",
                        "command": "/usr/bin/wasmtime",
                    },
                    {
                        "name": "wasmer",
                        "desc": "A WebAssembly runtime for embedding in other languages",
                        "command": "/usr/bin/wasmer",
                    }
                ]
    """

    if not os.path.exists(file):
        logging.warning(f"{file} file not found.")
        return list()
    if os.path.getsize(file) == 0:
        logging.warning(f"{file} is empty.")
        return list()

    with open(file, "r") as f:
        runtime_list = json.load(f)
        if not runtime_list or "runtimes" not in runtime_list:
            logging.warning("No runtimes found in runtimes.json.")
            return list()

        return runtime_list["runtimes"]


def get_runtime_from_name(name, file=utils.DEFAULT_RUNTIMES_FILE):
    """Get runtime information from a name.

    Args:
        name (str): Name of the runtime.
        file (str): Path to the JSON file containing runtimes. File must
                    exist but can be empty.

    Returns:
        dict: Dictionary containing runtime information. Returns None if
              the runtime is not found.
              Example:
                {
                    "name": "wasmtime",
                    "desc": "A standalone WebAssembly runtime",
                    "command": "/usr/bin/wasmtime"
                }
    """

    runtimes_list = list_runtimes(file)
    for runtime in runtimes_list:
        if runtime["name"] == name:
            return runtime
    logging.warning(f"Runtime {name} not found.")
    return None


def _list_available_runtimes(installers_folder=utils.DEFAULT_INSTALLERS_FOLDER):
    """List available runtimes.

    Args:
        installers_folder (str): Path to the folder containing installer JSON files.

    Returns:
        list[dict]: List of available runtimes, each represented as a dictionary.
    """

    if not os.path.isdir(installers_folder):
        logging.error(f"{installers_folder} is not a valid directory.")
        return []

    runtimes = []
    for entry in os.scandir(installers_folder):
        if entry.is_file() and entry.name.endswith(".json"):
            try:
                with open(entry.path, "r") as f:
                    runtime = json.load(f)
                if isinstance(runtime, dict) and "name" in runtime:
                    runtimes.append(runtime)
                else:
                    logging.warning(
                        f"Invalid or missing 'name' in {entry.name}. Skipping."
                    )
            except (json.JSONDecodeError, Exception) as e:
                logging.error(f"Error processing {entry.name}: {e}")

    if not runtimes:
        logging.warning("No valid runtimes found in installers folder.")

    return runtimes


def _get_available_runtime_by_name(name, runtimes_list):
    """Get runtime information by name.

    Args:
        name (str): Name of the runtime.
        runtimes_list (list): List of runtimes.

    Returns:
        dict: Dictionary containing runtime information. Returns None if
              the runtime is not found.
    """

    for runtime in runtimes_list:
        if runtime["name"] == name:
            return runtime
    logging.warning(f"Runtime {name} not found.")
    return None


def _add_runtime_to_runtimes_file(runtime, file=utils.DEFAULT_RUNTIMES_FILE):
    """Add a runtime to the runtimes.json file.
    It expects that the runtime does not exists in the file.
    """

    try:
        runtimes_list = list_runtimes(file)

        runtime.pop("install-command", None)
        runtimes_list.append(runtime)

        with open(file, "w") as f:
            json.dump({"runtimes": runtimes_list}, f, indent=4)

        logging.info(f"Added {runtime['name']} to {file}.")
    except Exception as e:
        logging.error(f"Failed to add runtime to {file}: {e}")


def _execute_runtime_command(
    runtime, command_key, runtimes_folder=utils.DEFAULT_RUNTIMES_FOLDER
):
    """Execute a runtime command (install/update).

    Args:
        runtime (dict): Runtime information.
        command_key (str): Key in the runtime dictionary for the command to execute.
        runtimes_folder (str): Path to the folder containing runtimes.

    Returns:
        bool: True if the command executed successfully, False otherwise.
    """
    logging.info(f"Executing {command_key} for {runtime['name']}...")

    if not os.path.exists(runtimes_folder):
        os.makedirs(runtimes_folder)
        logging.debug(f"Created {runtimes_folder} folder.")

    # The command is run with cwd set to the runtimes folder rather than by
    # chdir'ing this process into it. Changing the interpreter's working
    # directory would leak out of this function and break any relative path
    # resolved afterwards. stderr is deliberately left attached to the
    # terminal so that long installs keep showing progress.
    process = subprocess.run(
        runtime[command_key],
        shell=True,
        cwd=runtimes_folder,
        stdout=subprocess.PIPE,
        text=True,
    )
    output = process.stdout or ""

    logging.info(f"{output}")

    if process.returncode == 0:
        # Check that the runtime actually works
        version = _get_runtime_version(runtime["version-command"], runtimes_folder)
        if version is None:
            logging.error(
                f"Failed to get version for {runtime['name']}. Probably not executed correctly."
            )
            return False

        logging.info(f"{runtime['name']} {command_key} executed successfully.")
        return True
    else:
        logging.error(f"Failed to execute {command_key} for {runtime['name']}.")
        return False


def _check_runtime_installation(runtime, runtimes_folder, benchmarks_folder):
    """Checks that a runtime is working by executing a dummy payload.

    - If a subruntime is not working, it will be removed from the runtime.
    - If the main runtime is not working, but at least a subruntime is, it will
      not be removed.
    - If the main runtime is not working and no subruntime is working,
      None is returned.
    """

    logging.info(f"Checking installation of {runtime['name']}...")

    # We're using a dummy payload to check if the runtime is working
    dummy_payload = {"name": "dummy", "path": "dummy/dummy.wasm"}

    # Check subruntimes
    if "subruntimes" in runtime:
        runtime["subruntimes"] = [
            subruntime
            for subruntime in runtime["subruntimes"]
            if (
                results := run.run_benchmark_iterations(
                    dummy_payload, subruntime, benchmarks_folder, runtimes_folder
                )
            )
            and results[0].get("return_code", 1) == 0
            or logging.warning(
                f"Subruntime {subruntime['name']} failed dummy run. Removing."
            )
        ]

    # Check main runtime
    results = run.run_benchmark_iterations(
        dummy_payload, runtime, benchmarks_folder, runtimes_folder
    )

    if not results or results[0].get("return_code", 1) != 0:
        logging.warning(f"Main runtime {runtime['name']} failed dummy run.")

        # Delete runtime only if no subruntimes are working
        if not runtime.get("subruntimes"):
            logging.error(
                f"No working subruntimes for {runtime['name']}. Installation failed."
            )
            return None

    return runtime


def _remove_runtime_from_runtimes_file(name, file=utils.DEFAULT_RUNTIMES_FILE):
    """Remove a runtime from the runtimes.json file."""

    try:
        runtimes_list = list_runtimes(file)
        runtimes_list = [
            runtime for runtime in runtimes_list if runtime["name"] != name
        ]

        with open(file, "w") as f:
            json.dump({"runtimes": runtimes_list}, f, indent=4)

        logging.debug(f"Removed {name} from {file}.")
    except Exception as e:
        logging.error(f"Failed to remove runtime from {file}: {e}")


def _remove_runtime(
    name,
    install_dir,
    runtimes_folder=utils.DEFAULT_RUNTIMES_FOLDER,
    runtimes_file=utils.DEFAULT_RUNTIMES_FILE,
):
    """Remove a runtime."""

    logging.debug(f"Removing {name}...")

    if install_dir:
        # Delete the corresponding folder
        runtime_folder = os.path.join(runtimes_folder, install_dir)
        if os.path.exists(runtime_folder):
            shutil.rmtree(runtime_folder)
            logging.debug(f"Removed {runtime_folder}.")
        else:
            logging.warning(f"{runtime_folder} does not exist.")
    else:
        logging.warning(
            f"No install-dir specified for {name}. Skipping folder removal."
        )

    # Remove the runtime from the runtimes.json file
    _remove_runtime_from_runtimes_file(name, runtimes_file)


def _get_runtime_version(command, runtimes_folder=utils.DEFAULT_RUNTIMES_FOLDER):
    """Get the version of a runtime.

    Args:
        command (str): The command to run to get the version.
        runtimes_folder (str): Path to the folder containing runtimes.

    Returns:
        str: The version of the runtime. Returns None if the version could not be determined.
    """

    # cwd is passed to the child instead of chdir'ing this process, which
    # would leak the directory change to the rest of the run.
    process = subprocess.run(
        command,
        shell=True,
        cwd=runtimes_folder,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if process.returncode != 0:
        # Keep the streams on separate lines so the message stays readable
        # when both of them carry text.
        details = "\n".join(
            part for part in (process.stdout.strip(), process.stderr.strip()) if part
        )
        logging.error(f"Failed to get version: {details}")
        return None

    # Some runtimes report their version on stderr, so fall back to it rather
    # than reporting a successful command as having no version at all. An
    # empty string is still returned as-is: callers treat only None as
    # "the command failed".
    return process.stdout.strip() or process.stderr.strip()


def main(args):
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    if args.operation == "list":
        args.runtimes_file = utils.get_absolute_path(args.runtimes_file)

        runtimes_list = list_runtimes(args.runtimes_file)
        if not runtimes_list:
            print("No runtimes found.")
            return

        print("Runtimes installed:")
        for runtime in runtimes_list:
            logging.debug(f"Found runtime: {runtime}")
            print(f" * {runtime['name']}: {runtime['desc']}")

            # Check if runtime has subruntimes
            if "subruntimes" in runtime:
                for subruntime in runtime["subruntimes"]:
                    print(f"   ↳ {subruntime['name']}: {subruntime['desc']}")

    elif args.operation == "available":
        args.installers_folder = utils.get_absolute_path(args.installers_folder)

        available_runtimes = _list_available_runtimes(args.installers_folder)
        if not available_runtimes:
            print("No runtimes found.")
            return
        print("Available runtimes:")
        for runtime in available_runtimes:
            print(f" * {runtime['name']}: {runtime['desc']}")

    elif args.operation == "install":
        args.installers_folder = utils.get_absolute_path(args.installers_folder)
        args.runtimes_folder = utils.get_absolute_path(args.runtimes_folder)
        args.runtimes_file = utils.get_absolute_path(args.runtimes_file)
        args.benchmarks_folder = utils.get_absolute_path(args.benchmarks_folder)

        available_runtimes = _list_available_runtimes(args.installers_folder)
        runtime = _get_available_runtime_by_name(args.name, available_runtimes)
        if not runtime:
            print(f"Runtime {args.name} not found.")
            return 1

        # Check if the runtime is already installed
        installed_runtimes = list_runtimes(args.runtimes_file)
        if any(rt["name"] == runtime["name"] for rt in installed_runtimes):
            print(f"Runtime {args.name} is already installed.")
            return 0

        # Remove folder if it exists
        install_dir = os.path.join(args.runtimes_folder, runtime["install-dir"])
        logging.debug(f"Checking if {install_dir} already exists")
        if os.path.exists(install_dir):
            shutil.rmtree(install_dir)
            logging.info(f"Removed {install_dir} folder.")

        # Remember what the installer promised, so that configurations
        # dropped by the check below can be reported rather than only warned
        # about. An engine whose backends are silently discarded still looks
        # like a successful install otherwise.
        expected_subruntimes = [s["name"] for s in runtime.get("subruntimes", [])]

        # Install the runtime
        if not _execute_runtime_command(
            runtime, "install-command", args.runtimes_folder
        ):
            print(f"Runtime {args.name} failed to install.")
            return 1

        if not args.no_runtime_check:
            runtime = _check_runtime_installation(
                runtime, args.runtimes_folder, args.benchmarks_folder
            )

        if not runtime:
            print(f"Runtime {args.name} installed but does not work.")
            return 1

        _add_runtime_to_runtimes_file(runtime, args.runtimes_file)

        dropped = [
            name
            for name in expected_subruntimes
            if name not in {s["name"] for s in runtime.get("subruntimes", [])}
        ]
        if dropped:
            print(
                f"Runtime {args.name} installed, but "
                f"{len(dropped)} of {len(expected_subruntimes)} configurations "
                f"did not work and were removed: {', '.join(dropped)}"
            )
            print(
                "Re-run with --log-level DEBUG to see why, or pass "
                "--allow-partial to treat this as success."
            )
            return 0 if args.allow_partial else 1

        print(f"Runtime {args.name} installed successfully.")

    elif args.operation == "remove":
        args.runtimes_folder = utils.get_absolute_path(args.runtimes_folder)
        args.runtimes_file = utils.get_absolute_path(args.runtimes_file)

        # Check if the runtime is installed
        installed_runtimes = list_runtimes(args.runtimes_file)
        if not any(rt["name"] == args.name for rt in installed_runtimes):
            print(f"Runtime {args.name} is not installed.")
            return 1

        # Get the runtime information
        runtime = get_runtime_from_name(args.name, args.runtimes_file)

        # Remove the runtime
        _remove_runtime(
            args.name,
            runtime.get("install-dir"),
            args.runtimes_folder,
            args.runtimes_file,
        )

        print(f"Runtime {args.name} removed successfully.")

    elif args.operation == "version":
        args.runtimes_folder = utils.get_absolute_path(args.runtimes_folder)
        args.runtimes_file = utils.get_absolute_path(args.runtimes_file)

        runtimes_list = list_runtimes(args.runtimes_file)
        if not runtimes_list:
            print("No runtimes found.")
            return 1

        print("Versions installed:")
        for runtime in runtimes_list:
            logging.debug(f"Found runtime: {runtime}")
            version = _get_runtime_version(
                runtime["version-command"], args.runtimes_folder
            )
            if version:
                print(f" * {runtime['name']}: {version.splitlines()[0]}")
            else:
                logging.warning(f"Failed to get version for {runtime['name']}.")

    elif args.operation == "update":
        args.runtimes_folder = utils.get_absolute_path(args.runtimes_folder)
        args.runtimes_file = utils.get_absolute_path(args.runtimes_file)

        # Check if the runtime is installed
        installed_runtimes = list_runtimes(args.runtimes_file)
        if not any(rt["name"] == args.name for rt in installed_runtimes):
            print(f"Runtime {args.name} is not installed.")
            return 1

        # Get the runtime information
        runtime = get_runtime_from_name(args.name, args.runtimes_file)

        if not runtime.get("update-command"):
            logging.debug(f"Runtime {args.name} does not have an update command.")
            print(f"Runtime {args.name} does not support update.")
            return 1

        # Update the runtime
        if not _execute_runtime_command(
            runtime, "update-command", args.runtimes_folder
        ):
            print(f"Runtime {args.name} failed to update.")
            return 1

    else:
        print("Unknown operation. Use 'list' to see available runtimes.")
        return 1
