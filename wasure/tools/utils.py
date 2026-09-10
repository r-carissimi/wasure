import json
import logging
import os

DEFAULT_BENCHMARKS_FOLDER = "benchmarks"
DEFAULT_RESULTS_FOLDER = "results"
DEFAULT_RUNTIMES_FOLDER = "runtimes"
DEFAULT_PLOTS_FOLDER = "plots"
DEFAULT_INSTALLERS_FOLDER = "installers"
DEFAULT_RUNTIMES_FILE = DEFAULT_RUNTIMES_FOLDER + "/runtimes.json"

# Marker identifying a results file that carries metadata alongside the
# measurements. Results written before this existed are a bare mapping of
# runtime name to benchmarks, which split_results still reads.
RESULTS_SCHEMA_KEY = "wasure-results-version"
RESULTS_SCHEMA_VERSION = 1


def add_log_level_argument(parser):
    """Add a --log-level argument to the parser."""

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set the logging level (default: INFO)",
    )

    return parser


def load_results_file(file_path):
    """Load benchmark results from a JSON file.

    Args:
        file_path (str): Path to the JSON file containing benchmark results.

    Returns:
        dict: Parsed benchmark results. If the file is empty or cannot be parsed,
              returns None.
    """
    try:
        with open(file_path, "r") as f:
            results = json.load(f)
            if not results:
                logging.info("No results found in the file.")
                return None
            return results
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON from the results file.")
        return None
    except OSError as error:
        logging.error(f"Could not read the results file: {error}")
        return None


def split_results(document):
    """Separate the measurements in a results file from its metadata.

    Args:
        document (dict): The parsed contents of a results file.

    Returns:
        tuple: (results, metadata), where results is the mapping of runtime
               name to benchmarks and metadata is everything else. Results
               files written before metadata existed are a bare mapping, so
               for those metadata is empty.
    """

    if not isinstance(document, dict):
        return {}, {}

    if document.get(RESULTS_SCHEMA_KEY):
        results = document.get("results") or {}
        metadata = {k: v for k, v in document.items() if k != "results"}
        return results, metadata

    # Legacy file: the whole document is the measurements.
    return document, {}


def runtime_versions(metadata):
    """Read the engine version recorded for each runtime.

    Returns an empty mapping for results files that predate version
    recording, so callers can treat a missing version as unknown rather than
    having to special-case the format.
    """

    runtimes = (metadata or {}).get("runtimes") or {}
    return {
        name: info.get("version")
        for name, info in runtimes.items()
        if isinstance(info, dict)
    }


def get_absolute_path(path):
    """Get the absolute path of a given path.
    - If the path is absolute, return as is.
    - If the path is relative, resolve relative to the user's current working directory.

    Args:
        path (str): The path to convert to an absolute path.

    Returns:
        str: The absolute path.
    """

    if os.path.isabs(path):
        return path

    return os.path.abspath(os.path.join(os.getcwd(), path))
