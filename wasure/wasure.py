import logging
import sys
from argparse import ArgumentParser

from wasure.tools import commands, utils

VERSION_NUMBER = "0.9"
VERSION = f"{VERSION_NUMBER}α (2025-06-17)"


def setup_subparsers(parser, commands):
    """Set up subparsers for the given commands."""
    subparser = parser.add_subparsers(dest="command", required=True)
    for name, command in commands.items():
        cmd_parser = subparser.add_parser(
            name,
            help=command.__doc__.split("\n")[0],
            description=command.__doc__.split("\n")[0],
            add_help=True,
        )
        command.parse(cmd_parser)
        cmd_parser.set_defaults(_func=command.main)


def setup_logging(level=logging.WARNING):
    """Set up logging configuration."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def main():
    parser = ArgumentParser(
        description="WASURE - WebAssembly SUite for Runtime Evaluation"
    )
    parser.add_argument("--version", action="version", version=f"WASURE {VERSION}")
    utils.add_log_level_argument(parser)
    setup_subparsers(parser, commands)

    args = parser.parse_args()
    setup_logging(level=getattr(logging, args.log_level.upper()))

    if not hasattr(args, "_func"):  # pragma: no cover - argparse requires one
        # setup_subparsers marks the subcommand required, so argparse exits
        # before reaching this. Kept as a safety net rather than relying on
        # that remaining true.
        parser.print_help()
        return 1

    # Subcommands return an exit status, or None when they succeeded, so that
    # failures are visible to scripts and CI rather than only in the log.
    return args._func(args) or 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
