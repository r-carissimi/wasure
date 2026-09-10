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


def _write_benchmark_results_to_csv(data, filename, memory, versions=None):
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
        versions (dict): Runtime name to engine version. Rows get an empty
                         version when it is unknown, which is the case for
                         results files recorded before versions were kept.
    """

    logging.debug("Exporting every run to CSV")

    with open(filename, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)

        # This is to leave out the output of the benchmark from the CSV
        headers = [
            "benchmark",
            "runtime",
            "runtime_version",
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
                        (versions or {}).get(runtime) or "",
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

    document = utils.load_results_file(args.results_file)
    if not document:
        return 1

    results, metadata = utils.split_results(document)
    if not results:
        return 1
    versions = utils.runtime_versions(metadata)

    # CSV filename is the same as the results file, but with a .csv extension
    filename = os.path.join(
        args.csv_folder,
        os.path.splitext(os.path.basename(args.results_file))[0] + ".csv",
    )

    _write_benchmark_results_to_csv(results, filename, args.memory, versions)
