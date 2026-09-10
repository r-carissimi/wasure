"""Checks a benchmark suite on runtimes"""

import logging
import os

from . import run, utils


def parse(parser):
    """Parse command-line arguments for the runtime module.

    Args:
        parser (ArgumentParser): The argument parser to add subcommands to.
    """

    # We use os.path.dirname two times because the script is in the tools
    # folder and we want to get the runtimes folder.
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser.add_argument(
        "benchmark",
        help="Benchmark to check on runtimes",
        type=str,
    )

    parser.add_argument(
        "-r",
        "--runtimes",
        nargs="+",
        default=["all"],
        help="List of runtimes to use. Use 'all' to use all runtimes. Default: all",
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

    utils.add_log_level_argument(parser)
    return parser


def _print_return_codes(return_codes):
    """Prints returns codes in a fancy way"""

    for runtime, benchmarks in return_codes.items():
        print(f" * {runtime}")
        for benchmark, return_code in benchmarks.items():
            status = "\033[92m✓\033[0m" if return_code == 0 else "\033[91mX\033[0m"
            print(f"  ↳ {benchmark}: {status}")


def main(args):
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    benchmarks_folder = utils.get_absolute_path(args.benchmarks_folder)
    runtimes_file = utils.get_absolute_path(args.runtimes_file)
    runtimes_folder = utils.get_absolute_path(args.runtimes_folder)

    # Loads the runtimes
    runtimes_list = run.get_runtimes(runtimes_file, args.runtimes)
    logging.debug(f"Using runtimes: {[r['name'] for r in runtimes_list]}")

    if not runtimes_list:
        logging.error("No runtimes found. Exiting.")
        return 1

    # Load the benchmarks from the command line arguments
    benchmarks_list = run.load_benchmarks([args.benchmark], benchmarks_folder)
    logging.debug(f"Using benchmarks: {benchmarks_list}")

    if not benchmarks_list:
        logging.error("No benchmarks found. Exiting.")
        return 1

    # Run benchmarks on runtimes and collect return codes
    return_codes = {}
    for runtime in runtimes_list:
        logging.debug(f"Using runtime: {runtime['name']}")
        return_codes[runtime["name"]] = {}

        for benchmark in benchmarks_list:
            logging.debug(
                f"Checking benchmark: {benchmark['name']} with runtime: {runtime['name']}"
            )

            logging.disable(logging.CRITICAL)
            result = run.run_benchmark_iterations(
                benchmark,
                runtime,
                benchmarks_folder,
                runtimes_folder,
            )
            logging.disable(logging.NOTSET)

            return_codes[runtime["name"]][benchmark["name"]] = (
                result[0].get("return_code", 1) if result else 1
            )

    # Print the return codes
    _print_return_codes(return_codes)
