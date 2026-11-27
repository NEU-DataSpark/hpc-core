"""The ``hpc-core`` command line: offline parsing, run-report checks, command tuples and skills.

``main`` returns the exit status: 0 for success, 1 when the input was read but is not acceptable,
and 2 for a usage or argument error. Data goes to standard output as JSON; messages for people go
to standard error. Nothing here opens a connection or runs Slurm.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ..contract.identifiers import ValidationError
from ..contract.report import ReportError
from . import cmd_commands, cmd_parse, cmd_report, cmd_skills
from ._io import EXIT_UNACCEPTABLE, EXIT_USAGE, InputError, fail
from ._version import package_version

PROG = "hpc-core"
DESCRIPTION = (
    "Offline HPC scheduler tools: parse Slurm output, check run reports, print fixed read-only "
    "commands and install the shipped skills. Nothing here connects to a cluster."
)

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION)
    parser.add_argument("--version", action="version", version=package_version())
    subparsers = parser.add_subparsers(metavar="COMMAND", dest="group")
    cmd_parse.register(subparsers)
    cmd_report.register(subparsers)
    cmd_commands.register(subparsers)
    cmd_skills.register(subparsers)
    _no_abbreviations(parser)
    return parser


def _no_abbreviations(parser: argparse.ArgumentParser) -> None:
    """Options must be spelled in full. A prefix of a renamed option would otherwise still parse,
    and the pinned surface would not show the rename."""
    parser.allow_abbrev = False
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _no_abbreviations(child)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
    except SystemExit as request:
        # argparse exits 0 for --help and --version, and 2 for a usage error.
        code = request.code
        return code if isinstance(code, int) else EXIT_USAGE

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    try:
        status: int = handler(args)
    except (ValidationError, InputError) as error:
        return fail(str(error), EXIT_USAGE)
    except ReportError as error:
        return fail(str(error), EXIT_UNACCEPTABLE)
    return status
