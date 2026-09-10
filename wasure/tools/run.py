"""Runs benchmarks using runtimes

This module provides a command-line interface to run benchmarks using
different runtimes. It allows users to specify which benchmarks and
runtimes to use, and saves the results to a specified folder.
"""

import json
import logging
import os
import re
import subprocess
import time

import psutil

from . import benchmarks, runtimes, utils

# Sentinel return codes for failures that wasure detects itself, rather than
# ones the payload reported. Popen represents death by signal as the negated
# signal number (-2 for SIGINT, -11 for SIGSEGV, ...), so these sit well
# outside that range to stay distinguishable from a killed payload. Both are
# non-zero, so consumers filtering on `return_code != 0` still treat them as
# failures.
RETURN_CODE_TIMEOUT = -1001
RETURN_CODE_VALIDATION_FAILED = -1002


def parse(parser):
    """Parse command-line arguments for the runtime module.

    Args:
        parser (ArgumentParser): The argument parser to add subcommands to.
    """

    # We use os.path.dirname two times because the script is in the tools
    # folder and we want to get the runtimes folder.
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser.add_argument(
        "-r",
        "--runtimes",
        nargs="+",
        default=["all"],
        help="List of runtimes to use. Use 'all' to use all runtimes. Default: all",
    )

    parser.add_argument(
        "-b",
        "--benchmarks",
        nargs="+",
        default=["all"],
        help="""List of benchmarks to use. Use 'all' to use all benchmarks.
            You can choose both a group of benchmarks (e.g. coremark) as well
            as a specific one (e.g. coremark/coremark-1000) Default: all""",
    )

    parser.add_argument(
        "--no-store-output",
        action="store_true",
        default=False,
        help="Do not save the output of the benchmarks to the results file (default: False)",
    )

    parser.add_argument(
        "--benchmarks-folder",
        default=os.path.join(script_dir, utils.DEFAULT_BENCHMARKS_FOLDER),
        help=f"Path to the folder containing benchmarks (default: {utils.DEFAULT_BENCHMARKS_FOLDER})",
    )

    parser.add_argument(
        "--runtimes-file",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FILE),
        help=f"Path to the JSON file containing runtimes (default: {utils.DEFAULT_RUNTIMES_FILE})",
    )

    parser.add_argument(
        "--runtimes-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RUNTIMES_FOLDER),
        help=f"Path to the folder containing runtimes (default: {utils.DEFAULT_RUNTIMES_FOLDER})",
    )

    parser.add_argument(
        "--results-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RESULTS_FOLDER),
        help=f"Path to the folder where results will be saved (default: {utils.DEFAULT_RESULTS_FOLDER})",
    )

    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to repeat each benchmark (default: 1)",
    )

    parser.add_argument(
        "--memory",
        action="store_true",
        default=False,
        help="Pool memory usage for the benchmark (default: False)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Maximum time in seconds for each benchmark to run. If not specified, no timeout is applied.",
    )

    utils.add_log_level_argument(parser)

    return parser


def _filter_runtimes_by_name(selected_runtimes, runtimes_list):
    """Returns only the runtimes that are in the selected_runtimes list."""

    filtered_runtimes = []
    for runtime in runtimes_list:
        if runtime["name"] in selected_runtimes:
            filtered_runtimes.append(runtime)
    return filtered_runtimes


def _get_named_benchmarks(
    benchmarks_list, benchmarks_folder=utils.DEFAULT_BENCHMARKS_FOLDER
):
    benchs = dict()

    for benchmark_name in benchmarks_list:
        # Ignore benchmarks specified as files as they have already been loaded
        if benchmark_name.endswith(".wasm"):
            continue
        b = benchmarks.get_benchmark_from_name(benchmark_name, benchmarks_folder)
        if b is not None:
            for k, v in b.items():
                # This creates a new list if the key does not exist
                # and append the benchmark to the list. This is done to support
                # specifying single benchmarks in a group.
                benchs.setdefault(k, []).extend(v)

    return benchs


def load_benchmarks(benchmarks_list, benchmarks_folder):
    """Load benchmarks from a list of names and files.

    Args:
        benchmarks (list): List of benchmark names or file paths.
        benchmarks_folder (str): Path to the folder containing benchmark definitions.

    Returns:
        list: A list of benchmark dictionaries with their names and paths.
        Returns an empty list if no benchmarks are found.
    """

    # Load benchmarks from files
    file_benchmarks = [
        {"name": os.path.basename(b), "path": os.path.abspath(b)}
        for b in benchmarks_list
        if b.endswith(".wasm") and os.path.isfile(b)
    ]

    logging.debug(f"File benchmarks: {file_benchmarks}")

    # Load benchmarks from benchmark groups
    named_benchmarks = (
        benchmarks.list_benchmarks(benchmarks_folder)
        if "all" in benchmarks_list
        else _get_named_benchmarks(benchmarks_list, benchmarks_folder)
    )

    return _flatten_benchmarks(named_benchmarks) + file_benchmarks


def _flatten_benchmarks(benchmarks_list):
    """This function takes a dict of benchmark groups and returns a list of
    benchmarks, without their group. It also adds the group name to the
    path of each benchmark, thus having the full path for each benchmark in the
    object itself.

    This is the input format:

    {
        "group_name": [
            {
                "name": "benchmark1",
                "path": "path/to/benchmark1"
                ...
            },
            {
                "name": "benchmark2",
                "path": "path/to/benchmark2"
                ...
            },
            ...
        ],
        ""group_name2": [...]
    }

    This is the output format:

    [
        {
            "name": "benchmark1",
            "path": "group_name/path/to/benchmark1"
            ...
        },
        {
            "name": "benchmark2",
            "path": "group_name/path/to/benchmark2"
            ...
        },
        ...
    ]
    """

    return [
        {**b, "path": f"{group_name}/{b['path']}"}
        for group_name, group_list in benchmarks_list.items()
        for b in group_list
    ]


def _parse_score(output, score_parser):
    match = re.search(score_parser, output)
    if match:
        return float(match.group("score"))
    return 0


def _merge_output(stdout, stderr):
    """Merge the stdout and stderr of a benchmark into a single string.

    The two streams are kept on separate lines. Concatenating them directly
    would let the last token of stdout fuse with the first token of stderr,
    which silently breaks `score-parser` and `output-validator` regexes.
    """

    parts = [stream.decode(errors="replace").strip() for stream in (stdout, stderr)]
    return "\n".join(part for part in parts if part)


def _run_benchmark_with_runtime(
    benchmark,
    runtime,
    benchmarks_folder,
    runtimes_folder,
    precompiled_path=None,
    pool_memory=False,
    timeout_seconds=None,
):
    """Run a benchmark with a given runtime.

    Args:
        benchmark (dict): The benchmark to run.
        runtime (dict): The runtime to use.
        benchmarks_folder (str): The folder containing the benchmarks. Can
                                 be relative or absolute.
        precompiled_path (str): Path to the precompiled AOT file, if applicable.

    Returns:
        tuple: A tuple containing
               * elapsed time: The elapsed time of the benchmark in nanoseconds
               * score: The score of the benchmark (if applicable)
               * return code: The return code of the benchmark
               * output: The output of the benchmark as a string
               * stats: A dictionary containing the parsed stats
    """

    benchmarks_folder = utils.get_absolute_path(benchmarks_folder)

    benchmark_path = os.path.join(
        benchmarks_folder,
        benchmark["path"],
    )

    if precompiled_path:
        benchmark_path = precompiled_path

    # Replaces the path in the arguments with the absolute path to the benchmark
    # folder. This is due to some runtimes that do not support mapping
    # directories to a different path in the WASM module. Hence, we need to
    # provide the absolute path to the benchmark folder for the file to be
    # accessible.
    arguments = benchmark.get("args", "").format(path=os.path.dirname(benchmark_path))

    # Command formatting
    command = runtime["command"].format(
        payload=f'"{benchmark_path}"',
        entrypoint=benchmark.get("entrypoint", "")
        if "{entrypoint}" in runtime["command"]
        else "",
        entrypoint_flag=runtime["entrypoint-flag"]
        if "{entrypoint_flag}" in runtime["command"] and "entrypoint" in benchmark
        else "",
        args=arguments if "{args}" in runtime["command"] else "",
        mount_dir=f'"{os.path.dirname(benchmark_path)}"'
        if "{mount_dir}" in runtime["command"]
        else "",
    )

    logging.debug(f"Running '{command}'")

    start_time = time.perf_counter_ns()
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtimes_folder,
    )

    max_memory_rss = 0
    max_memory_vms = 0
    memory_sampled = False

    try:
        # if pool_memory is True, we will monitor the memory usage of the process
        if pool_memory:
            proc = psutil.Process(process.pid)
            start = time.time()
            can_sample = True
            while process.poll() is None:
                if timeout_seconds and time.time() - start > timeout_seconds:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                if can_sample:
                    try:
                        mem_info = proc.memory_info()
                    except (
                        psutil.NoSuchProcess,
                        psutil.AccessDenied,
                        ProcessLookupError,
                    ):
                        # The process may just have exited in the window
                        # between poll() and memory_info(), which short
                        # benchmarks hit routinely. It may also have become
                        # permanently unreadable. Either way, give up on
                        # sampling but keep looping so that the timeout is
                        # still enforced; the loop exits on its own once the
                        # process is gone.
                        can_sample = False
                    else:
                        max_memory_rss = max(max_memory_rss, mem_info.rss)
                        max_memory_vms = max(max_memory_vms, mem_info.vms)
                        memory_sampled = True
                time.sleep(0.01)
            stdout, stderr = process.communicate()
        else:
            # if pool_memory is False, we wait for the process to finish.
            # timeout_seconds is used to limit the maximum time the benchmark
            # can run. Is None by default.
            stdout, stderr = process.communicate(timeout=timeout_seconds)

    except subprocess.TimeoutExpired:
        process.kill()
        logging.warning(f"Benchmark timed out after {timeout_seconds} seconds")
        stdout, stderr = process.communicate()
        elapsed_time = time.perf_counter_ns() - start_time
        return (
            elapsed_time,
            0,
            RETURN_CODE_TIMEOUT,
            _merge_output(stdout, stderr),
            {},
        )

    end_time = time.perf_counter_ns()
    elapsed_time = end_time - start_time

    logging.debug(f"Elapsed time: {elapsed_time} ns")

    if pool_memory and memory_sampled:
        logging.debug(f"Max RSS memory: {max_memory_rss / 1024} KB")
        logging.debug(f"Max VMS memory: {max_memory_vms / 1024} KB")
    elif pool_memory:
        logging.debug("Memory usage could not be sampled for this run")

    output = _merge_output(stdout, stderr)
    logging.debug(f"Output: {output}")

    # Validate the output with a regex, if specified
    if benchmark.get("output-validator"):
        if not re.search(benchmark.get("output-validator"), output):
            logging.warning(
                f"Output validation failed for benchmark {benchmark['name']} with runtime {runtime['name']}"
            )
            # The payload may well have exited 0 while producing wrong output.
            # Reporting that exit code here would make the run look successful
            # even though it produced no usable timing, so report a dedicated
            # failure code instead.
            return (
                0,
                0,
                process.returncode or RETURN_CODE_VALIDATION_FAILED,
                output,
                {},
            )
        logging.debug(
            f"Output validation succeeded for benchmark {benchmark['name']} with runtime {runtime['name']}"
        )

    score = (
        _parse_score(output, benchmark.get("score-parser"))
        if benchmark.get("score-parser")
        else 0
    )

    stats = {
        stat_name: match.group(stat_name)
        for stat_name, stat_regex in (runtime.get("stats-parser") or {}).items()
        if (match := re.search(stat_regex, output))
    }

    # Only report memory when it was actually measured. Emitting zeros for a
    # run that was never sampled would be indistinguishable from a real
    # measurement once it reaches the CSV.
    if pool_memory and memory_sampled:
        stats["max_rss_bytes"] = max_memory_rss
        stats["max_vms_bytes"] = max_memory_vms

    return elapsed_time, score, process.returncode, output, stats


def _compile_benchmark(benchmark, runtime, benchmarks_folder, runtimes_folder):
    """Compile a benchmark using AOT if applicable.

    Args:
        benchmark (dict): The benchmark to compile.
        runtime (dict): The runtime to use.
        benchmarks_folder (str): The folder containing the benchmarks.

    Returns:
        str: Path to the precompiled AOT file, or None if AOT is not applicable.
    """

    benchmarks_folder = utils.get_absolute_path(benchmarks_folder)

    benchmark_path = os.path.join(
        benchmarks_folder,
        benchmark["path"],
    )

    precompiled_path = os.path.splitext(benchmark_path)[0] + ".aot"

    if runtime["aot-command"]:
        aot_command = runtime["aot-command"].format(
            input=f'"{benchmark_path}"', output=f'"{precompiled_path}"'
        )
        logging.debug(f"Running AOT command: '{aot_command}'")
        process = subprocess.Popen(
            aot_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=runtimes_folder,
        )
        stdout, stderr = process.communicate()

        logging.debug(f"AOT stdout: {stdout.decode().strip()}")
        logging.debug(f"AOT stderr: {stderr.decode().strip()}")

        if process.returncode != 0:
            logging.error(
                f"AOT compilation failed for {benchmark['name']} with runtime {runtime['name']}. "
                f"Error: {stderr.decode().strip()}"
            )
            return None

        logging.info(
            f"AOT compilation succeeded for {benchmark['name']} with runtime {runtime['name']}"
        )
        return precompiled_path

    return None


def _new_results_filename(folder=utils.DEFAULT_RESULTS_FOLDER):
    """Build the path of the results file for this run.

    The name is claimed before the sweep starts, because results are written
    to it as they are collected. Two runs started within the same second
    would otherwise share a name and overwrite each other's results, so a
    counter is appended if the name is already taken.
    """

    stem = time.strftime("%Y-%m-%d_%H-%M-%S")
    filename = os.path.join(folder, f"{stem}.json")

    suffix = 2
    while os.path.exists(filename):
        filename = os.path.join(folder, f"{stem}_{suffix}.json")
        suffix += 1

    return filename


def _save_results_to_file(results, filename):
    """Write results to filename, replacing any previous content.

    This is called after every benchmark rather than only at the end of the
    run, so that a crash or an interrupt part-way through a long sweep does
    not discard the results already collected. The write goes to a temporary
    file first and is then moved into place, so an interrupt during the write
    itself cannot leave a truncated JSON file behind.
    """

    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    tmp_filename = f"{filename}.tmp"
    try:
        with open(tmp_filename, "w") as f:
            json.dump(results, f, indent=4)
        os.replace(tmp_filename, filename)
    except BaseException:
        # Do not leave a partial temporary file behind if the write fails or
        # the run is interrupted. The previous checkpoint stays intact.
        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)
        raise

    logging.debug(f"Results saved to {filename}")


def get_runtimes(runtimes_file, chosen_runtimes):
    """Loads and prepares the list of runtimes.

    Args:
        runtimes_file (str): Path to the JSON file containing runtimes.
        chosen_runtimes (list): List of runtimes to use. Use 'all' to use all runtimes.

    Returns:
        list: A list of dictionaries containing the runtimes.
        Returns an empty list if no runtimes are found.
    """

    runtimes_list = runtimes.list_runtimes(file=runtimes_file)
    flattened_runtimes = [
        runtime
        for runtime in runtimes_list
        for runtime in ([runtime] + runtime.pop("subruntimes", []))
    ]

    if "all" in chosen_runtimes:
        return flattened_runtimes

    return _filter_runtimes_by_name(chosen_runtimes, flattened_runtimes)


def _run_benchmarks(
    runtimes_list,
    benchmarks_list,
    benchmarks_folder,
    runtimes_folder,
    repeat=1,
    no_store_output=False,
    pool_memory=False,
    timeout_seconds=None,
    results_file=None,
):
    """Runs benchmarks for each runtime and collects results.

    If results_file is given, the results collected so far are written to it
    after every benchmark, so that an interrupted sweep keeps its partial
    results instead of losing everything.
    """

    results = {}

    for runtime in runtimes_list:
        logging.debug(f"Using runtime: {runtime['name']}")
        results[runtime["name"]] = {}

        for benchmark in benchmarks_list:
            logging.info(
                f"Running benchmark: {benchmark['name']} with runtime: {runtime['name']}"
            )
            results[runtime["name"]][benchmark["name"]] = run_benchmark_iterations(
                benchmark,
                runtime,
                benchmarks_folder,
                runtimes_folder,
                repeat,
                no_store_output,
                pool_memory,
                timeout_seconds,
            )

            if results_file:
                _save_results_to_file(results, results_file)

    return results


def run_benchmark_iterations(
    benchmark,
    runtime,
    benchmarks_folder,
    runtimes_folder,
    repeat=1,
    no_store_output=False,
    pool_memory=False,
    timeout_seconds=None,
):
    """Runs multiple iterations of a benchmark and collects results.

    Args:
        benchmark (dict): The benchmark to run.
        runtime (dict): The runtime to use.
        benchmarks_folder (str): The folder containing the benchmarks.
        runtimes_folder (str): The folder containing the runtimes.
        repeat (int): Number of times to repeat the benchmark.
        no_store_output (bool): If True, do not store the output of the benchmark.
        pool_memory (bool): If True, pool memory usage for the benchmark.
        timeout_seconds (int): Maximum time in seconds for each benchmark to run.

    Returns:
        list: A list of dictionaries containing the results of each iteration.
        Returns None if the benchmark fails to compile.
    """

    iterations_results = []
    precompiled_path = None

    if runtime.get("aot-command"):
        precompiled_path = _compile_benchmark(
            benchmark, runtime, benchmarks_folder, runtimes_folder
        )
        if precompiled_path is None:
            return None

    for i in range(repeat):
        logging.info(f"Running iteration {i + 1}/{repeat}")
        elapsed_time, score, return_code, output, stats = _run_benchmark_with_runtime(
            benchmark,
            runtime,
            benchmarks_folder,
            runtimes_folder,
            precompiled_path,
            pool_memory,
            timeout_seconds,
        )

        if return_code != 0:
            logging.warning(
                f"Benchmark {benchmark['name']} failed with return code {return_code}"
            )
            elapsed_time, score = 0, 0

        iterations_results.append(
            {
                "elapsed_time_ns": elapsed_time,
                "score": score,
                "return_code": return_code,
                **({"output": output} if not no_store_output else {}),
                **({"stats": stats} if stats else {}),
            }
        )

    if precompiled_path and os.path.exists(precompiled_path):
        os.remove(precompiled_path)
        logging.debug(f"Removed precompiled file: {precompiled_path}")

    return iterations_results


def main(args):
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))

    # Resolve absolute paths
    benchmarks_folder = utils.get_absolute_path(args.benchmarks_folder)
    runtimes_file = utils.get_absolute_path(args.runtimes_file)
    results_folder = utils.get_absolute_path(args.results_folder)
    runtimes_folder = utils.get_absolute_path(args.runtimes_folder)

    # Loads the runtimes
    runtimes_list = get_runtimes(runtimes_file, args.runtimes)
    logging.debug(f"Using runtimes: {[r['name'] for r in runtimes_list]}")

    if not runtimes_list:
        logging.error("No runtimes found. Exiting.")
        return

    # Load the benchmarks from the command line arguments
    benchmarks_list = load_benchmarks(args.benchmarks, benchmarks_folder)
    logging.debug(f"Using benchmarks: {benchmarks_list}")

    if not benchmarks_list:
        logging.error("No benchmarks found. Exiting.")
        return

    # Results are checkpointed to this file after every benchmark, so the
    # name is fixed up front rather than when the sweep finishes.
    results_file = _new_results_filename(results_folder)

    # Run benchmarks
    results = _run_benchmarks(
        runtimes_list,
        benchmarks_list,
        benchmarks_folder,
        runtimes_folder,
        args.repeat,
        args.no_store_output,
        args.memory,
        args.timeout,
        results_file,
    )

    # Save results
    _save_results_to_file(results, results_file)
    logging.info(f"Results saved to {results_file}")
