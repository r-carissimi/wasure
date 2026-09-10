"""Plots results of the benchmarks"""

import logging
import os
import statistics as statistics_module

import matplotlib.pyplot as plt

from . import utils

# Names offered by --statistic, mapped to the keys _compute_statistics emits.
STATISTICS = {"mean": "avg", "median": "median", "min": "min"}


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
        "--plots-folder",
        default=os.path.join(script_dir, utils.DEFAULT_PLOTS_FOLDER),
        help=f"Path to the folder where plots will be saved (default: {utils.DEFAULT_PLOTS_FOLDER})",
    )

    parser.add_argument(
        "--statistic",
        default="median",
        choices=sorted(STATISTICS),
        help="""Which statistic to plot when a benchmark was repeated.
            Timing distributions are right-skewed, since a run can be slowed
            by unrelated load but never made faster than the machine allows,
            so the median is more representative than the mean.
            (default: median)""",
    )

    utils.add_log_level_argument(parser)

    return parser


def _compute_statistics(results):
    """Compute average, min, and max values for each benchmark and runtime."""

    statistics = {}
    for runtime, benchmarks in results.items():
        statistics[runtime] = {}
        for benchmark, runs in benchmarks.items():
            # filters out runs with elapsed_time_ns <= 0.
            runs = [run for run in runs if run["elapsed_time_ns"] > 0]
            if not runs:
                continue

            elapsed_times = [run["elapsed_time_ns"] for run in runs]
            scores = [run["score"] for run in runs]
            statistics[runtime][benchmark] = {
                "elapsed_time_ns": {
                    "avg": sum(elapsed_times) / len(elapsed_times),
                    "median": statistics_module.median(elapsed_times),
                    "min": min(elapsed_times),
                    "max": max(elapsed_times),
                },
                "score": {
                    "avg": sum(scores) / len(scores),
                    "median": statistics_module.median(scores),
                    "min": min(scores),
                    "max": max(scores),
                },
            }

        # Remove runtimes with no valid benchmarks in order to avoid empty plots later
        if not statistics[runtime]:
            del statistics[runtime]

    return statistics


def _collect_benchmarks(results):
    """Collect and sort benchmark names."""

    benchmarks_set = set()
    for runtime in results.values():
        benchmarks_set.update(runtime.keys())
    return sorted(benchmarks_set)


def _determine_benchmark_metrics(results, benchmarks_list, statistic="avg"):
    """Determine the metric to use for each benchmark.
    If any runtime has a score > 0, use score; otherwise, use elapsed_time_ns.
    """

    benchmark_metrics = {}
    for benchmark in benchmarks_list:
        use_score = any(
            results[runtime][benchmark]["score"][statistic] > 0
            for runtime in results
            if benchmark in results[runtime]
        )
        benchmark_metrics[benchmark] = "score" if use_score else "elapsed_time_ns"

    return benchmark_metrics


def _transpose_benchmark_data(results, benchmarks_list, benchmark_metrics):
    """Transpose the benchmark data for plotting.

    The expected format is:
    {
        "runtime1": {
            "benchmark1": {"avg": value1, "min": value2, "max": value3},
            "benchmark2": {...},
        },
        "runtime2": {...},
    }

    The output format is:

    {
        "benchmark1": {
            "runtime1": {"avg": value1, "min": value2, "max": value3},
            "runtime2": {...},
        },
        "benchmark2": {...},
    }
    """

    raw_values = {
        benchmark: {
            runtime: results[runtime][benchmark][benchmark_metrics[benchmark]]
            for runtime in results
            if benchmark in results[runtime]
        }
        for benchmark in benchmarks_list
    }

    return raw_values


def _empty_runtime_data(benchmarks_list, raw_values):
    """Build the empty per-runtime accumulator used when plotting.

    Every runtime that appears in any benchmark gets an entry. Seeding this
    from a single benchmark instead would raise a KeyError as soon as one
    runtime failed, timed out or was skipped on that particular benchmark.
    """

    return {
        runtime: {"values": {}, "errors": {}}
        for benchmark in benchmarks_list
        for runtime in raw_values[benchmark]
    }


def _normalize_values(benchmarks_list, benchmark_metrics, raw_values, statistic="avg"):
    """Normalize raw values for each benchmark.

    For scores, normalize by the maximum value.
    For elapsed times, normalize by the minimum value.
    """

    runtime_data = _empty_runtime_data(benchmarks_list, raw_values)
    for benchmark in benchmarks_list:
        values = {
            runtime: data[statistic] for runtime, data in raw_values[benchmark].items()
        }
        errors = {
            runtime: (
                max(0, data[statistic] - data["min"]),
                max(0, data["max"] - data[statistic]),
            )
            for runtime, data in raw_values[benchmark].items()
        }
        if benchmark_metrics[benchmark] == "score":
            max_val = max(values.values())
            for runtime, val in values.items():
                runtime_data[runtime]["values"][benchmark] = (
                    (val / max_val * 100) if max_val > 0 else 0
                )
                runtime_data[runtime]["errors"][benchmark] = (
                    (
                        errors[runtime][0] / max_val * 100,
                        errors[runtime][1] / max_val * 100,
                    )
                    if max_val > 0
                    else (0, 0)
                )
        else:
            min_val = min(val for val in values.values() if val > 0) or 1e-9
            for runtime, val in values.items():
                runtime_data[runtime]["values"][benchmark] = (
                    (val / min_val * 100) if val > 0 else 0
                )
                runtime_data[runtime]["errors"][benchmark] = (
                    (
                        errors[runtime][0] / min_val * 100,
                        errors[runtime][1] / min_val * 100,
                    )
                    if val > 0
                    else (0, 0)
                )
    return runtime_data


def _all_benchmarks_single_runtime(statistics, benchmarks_list):
    """Return True if every benchmark has only one runtime."""

    for benchmark in benchmarks_list:
        runtimes = [
            runtime for runtime in statistics if benchmark in statistics[runtime]
        ]
        if len(runtimes) != 1:
            return False
    return True


def _absolute_values(benchmarks_list, raw_values, statistic="avg"):
    """Prepare absolute values for plotting (no normalization)."""

    runtime_data = _empty_runtime_data(benchmarks_list, raw_values)
    for benchmark in benchmarks_list:
        for runtime, data in raw_values[benchmark].items():
            runtime_data[runtime]["values"][benchmark] = data[statistic]
            runtime_data[runtime]["errors"][benchmark] = (
                max(0, data[statistic] - data["min"]),
                max(0, data["max"] - data[statistic]),
            )
    return runtime_data


def _plot_results(
    runtime_data, benchmarks_list, benchmark_metrics, results_file, plots_folder, ylabel
):
    """Plot the normalized benchmark results with error bars and save the file."""

    x = range(len(benchmarks_list))
    bar_width = 0.8 / len(runtime_data)
    colors = plt.cm.tab10.colors
    plt.figure(figsize=(16, 10))

    for i, (runtime, data) in enumerate(runtime_data.items()):
        y_values = [data["values"].get(benchmark, 0) for benchmark in benchmarks_list]
        y_errors = [
            data["errors"].get(benchmark, (0, 0)) for benchmark in benchmarks_list
        ]
        y_err_lower = [err[0] for err in y_errors]
        y_err_upper = [err[1] for err in y_errors]
        plt.bar(
            [pos + i * bar_width for pos in x],
            y_values,
            bar_width,
            label=runtime,
            color=colors[i % len(colors)],
            yerr=[y_err_lower, y_err_upper],
            capsize=5,
        )

    plt.grid(axis="y", linestyle="--", alpha=0.7)
    plt.title("Benchmark Results Grouped by Runtime")
    plt.ylabel(ylabel)
    plt.xlabel("Benchmark")
    plt.xticks(
        [pos + (len(runtime_data) - 1) * bar_width / 2 for pos in x],
        [f"{b}\n({benchmark_metrics[b]})" for b in benchmarks_list],
        rotation=45,
        ha="right",
    )
    plt.legend()
    plt.tight_layout()

    plot_filename = os.path.splitext(os.path.basename(results_file))[0] + ".png"
    plot_path = os.path.join(plots_folder, plot_filename)
    plt.savefig(plot_path)
    plt.close()
    logging.info(f"Saved plot to {plot_path}")


def main(args):
    logging.getLogger().setLevel(getattr(logging, args.log_level.upper()))
    os.makedirs(args.plots_folder, exist_ok=True)

    args.results_file = utils.get_absolute_path(args.results_file)
    args.plots_folder = utils.get_absolute_path(args.plots_folder)

    document = utils.load_results_file(args.results_file)
    if not document:
        logging.error("No results found in the file.")
        return 1

    results, _ = utils.split_results(document)
    if not results:
        logging.error("No results found in the file.")
        return 1

    statistic = STATISTICS[getattr(args, "statistic", "median")]

    statistics = _compute_statistics(results)
    # Avoids empty plots
    if not statistics:
        logging.error("No valid results found in the file.")
        return 1

    benchmarks_list = _collect_benchmarks(statistics)
    benchmark_metrics = _determine_benchmark_metrics(
        statistics, benchmarks_list, statistic
    )
    raw_values = _transpose_benchmark_data(
        statistics, benchmarks_list, benchmark_metrics
    )

    label = getattr(args, "statistic", "median")
    if _all_benchmarks_single_runtime(statistics, benchmarks_list):
        runtime_data = _absolute_values(benchmarks_list, raw_values, statistic)
        ylabel = f"Absolute Metric Value ({label} of runs)"
    else:
        runtime_data = _normalize_values(
            benchmarks_list, benchmark_metrics, raw_values, statistic
        )
        ylabel = f"Normalized Metric Value (%, {label} of runs)"

    _plot_results(
        runtime_data,
        benchmarks_list,
        benchmark_metrics,
        args.results_file,
        args.plots_folder,
        ylabel,
    )
