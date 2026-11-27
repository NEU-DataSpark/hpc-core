"""``hpc-core parse``: recorded scheduler output in, JSON records and a skipped count out."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from ..contract import sacct, sinfo, squeue, sstat
from ..contract.fields import FieldProfile, ParseResult
from ._io import EXIT_OK, STDIN_MARK, print_json, read_text
from ._profiles import DEFAULT_PROFILE, PROFILES, profile_names

PARSERS: dict[str, Callable[[str, FieldProfile], ParseResult[Any]]] = {
    "squeue": squeue.parse_squeue,
    "sacct": sacct.parse_sacct,
    "sinfo": sinfo.parse_sinfo,
    "sstat": sstat.parse_sstat,
}

_HELP = {
    "squeue": "Parse squeue output into job records.",
    "sacct": "Parse sacct output into job allocation records.",
    "sinfo": "Parse sinfo output into partition capacity records.",
    "sstat": "Parse sstat output into running job step records.",
}


def run(args: argparse.Namespace) -> int:
    command: str = args.scheduler
    profile = PROFILES[command][args.profile or DEFAULT_PROFILE[command]]
    result = PARSERS[command](read_text(args.input), profile)
    print_json({"records": result.records, "skipped": result.skipped})
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser(
        "parse", help="Parse recorded scheduler output into JSON records."
    )
    commands = group.add_subparsers(metavar="COMMAND", dest="parse_command", required=True)
    for command in PARSERS:
        parser = commands.add_parser(command, help=_HELP[command])
        parser.add_argument(
            "--profile",
            choices=profile_names(command),
            default=None,
            help=f"field profile to read (default: {DEFAULT_PROFILE[command]})",
        )
        parser.add_argument(
            "input",
            nargs="?",
            default=STDIN_MARK,
            metavar="FILE",
            help="file with the command output; '-' or no argument reads standard input",
        )
        parser.set_defaults(handler=run, scheduler=command)
