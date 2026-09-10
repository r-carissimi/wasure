"""Exports results to a CSV file"""

import csv
import logging
import os

from . import utils


def parse(parser):
    """Parse command-line arguments for the runtime module."""

    # We use os.path.dirname two times because the script is in the tools
    # folder and we want to get the runtimes folder.
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser.add_argument(
        "results_file",
        help="Path to the results file to plot",
        type=str,
    )

    parser.add_argument(
        "--csv-folder",
        default=os.path.join(script_dir, utils.DEFAULT_RESULTS_FOLDER),
        help=f"Path to the folder where CSVs will be saved (default: {utils.DEFAULT_RESULTS_FOLDER})",
    )

    parser.add_argument(
        "--memory",
        action="store_true",
        default=False,
        help="Include memory usage in the CSV file (default: False)",
    )

    utils.add_log_level_argument(parser)

    return parser


def _write_benchmark_results_to_csv(data, filename, memory):
    """
    Writes every run of benchmark results to a CSV file.

    The input dict format is:
    {
        "runtime_name": {
            "benchmark_name": [
                {"elapsed_time_ns": value1, "score": value2, ...},
                ...
            ],
            ...
        },
        ...
    }

    Args:
        data (dict): Nested dictionary containing benchmark results.
                     The outer keys are benchmark names, and the inner
                     keys are runtime names.
        filename (str): The name of the CSV file to write to.
        memory (bool): If True, include memory usage in the CSV.
    """

    logging.debug("Exporting every run to CSV")

    with open(filename, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # This is to leave out the output of the benchmark from the CSV
        headers = [
            "benchmark",
            "runtime",
            "run_index",
            "elapsed_time_ns",
            "score",
            "return_code",
        ]
        if memory:
            headers.extend(["max_rss_bytes", "max_vms_bytes"])

        writer.writerow(headers)

        for runtime, runtimes in data.items():
            for benchmark, runs in runtimes.items():
                for run_index, run in enumerate(runs):
                    row = [
                        benchmark,
                        runtime,
                        run_index + 1,
                        run.get("elapsed_time_ns", ""),
                        run.get("score", ""),
                        run.get("return_code", ""),
                    ]
                    if memory:
                        row.append(run.get("stats", {}).get("max_rss_bytes", ""))
                        row.append(run.get("stats", {}).get("max_vms_bytes", ""))

                    writer.writerow(row)

    logging.info(f"Results exported to {filename}")


def main(args):
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    os.makedirs(args.csv_folder, exist_ok=True)

    args.results_file = utils.get_absolute_path(args.results_file)
    args.csv_folder = utils.get_absolute_path(args.csv_folder)

    results = utils.load_results_file(args.results_file)
    if not results:
        return

    # CSV filename is the same as the results file, but with a .csv extension
    filename = os.path.join(
        args.csv_folder,
        os.path.splitext(os.path.basename(args.results_file))[0] + ".csv",
    )

    _write_benchmark_results_to_csv(results, filename, args.memory)
