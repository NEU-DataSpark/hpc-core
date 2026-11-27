"""``hpc-core commands``: print the fixed, read-only argument tuple for one Slurm read.

The tuple is printed as a JSON array of strings. Nothing is run: the caller runs the tuple on its
own transport and passes the output to ``hpc-core parse``. Use the same ``--profile`` for both.
"""

from __future__ import annotations

import argparse

from ..contract.fields import FieldProfile
from ..slurm import commands
from ._io import EXIT_OK, print_json
from ._profiles import DEFAULT_PROFILE, PROFILES, profile_names


def _profile(command: str, args: argparse.Namespace) -> FieldProfile:
    return PROFILES[command][args.profile or DEFAULT_PROFILE[command]]


def queue_run(args: argparse.Namespace) -> int:
    print_json(commands.squeue_queue(_profile("squeue", args), args.account))
    return EXIT_OK


def finished_run(args: argparse.Namespace) -> int:
    profile = _profile("sacct", args)
    print_json(commands.sacct_finished(profile, args.account, args.hours))
    return EXIT_OK


def job_run(args: argparse.Namespace) -> int:
    print_json(commands.sacct_job(_profile("sacct", args), args.job_id))
    return EXIT_OK


def usage_run(args: argparse.Namespace) -> int:
    print_json(commands.sstat_usage(_profile("sstat", args), args.job_id))
    return EXIT_OK


def capacity_run(args: argparse.Namespace) -> int:
    print_json(commands.sinfo_capacity(_profile("sinfo", args)))
    return EXIT_OK


def _add_profile(parser: argparse.ArgumentParser, command: str) -> None:
    parser.add_argument(
        "--profile",
        choices=profile_names(command),
        default=None,
        help=f"field profile to read (default: {DEFAULT_PROFILE[command]})",
    )


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser(
        "commands", help="Print the read-only Slurm argument tuple for a query; nothing is run."
    )
    sub = group.add_subparsers(metavar="COMMAND", dest="commands_command", required=True)

    queue = sub.add_parser("queue", help="The account's jobs in the queue now (squeue).")
    queue.add_argument(
        "--account", required=True, help="account name; there is no default and it is checked"
    )
    _add_profile(queue, "squeue")
    queue.set_defaults(handler=queue_run)

    finished = sub.add_parser("finished", help="The account's jobs that started recently (sacct).")
    finished.add_argument(
        "--account", required=True, help="account name; there is no default and it is checked"
    )
    finished.add_argument(
        "--hours",
        required=True,
        type=int,
        help=f"look back this many whole hours (1 to {commands.MAX_HOURS})",
    )
    _add_profile(finished, "sacct")
    finished.set_defaults(handler=finished_run)

    job = sub.add_parser("job", help="The accounting record of one job allocation (sacct).")
    job.add_argument("job_id", metavar="JOB_ID", help="a job id such as 4812201 or 4812201_3")
    _add_profile(job, "sacct")
    job.set_defaults(handler=job_run)

    usage = sub.add_parser("usage", help="Usage of the running steps of one job (sstat).")
    usage.add_argument("job_id", metavar="JOB_ID", help="a job id such as 4812201 or 4812201_3")
    _add_profile(usage, "sstat")
    usage.set_defaults(handler=usage_run)

    capacity = sub.add_parser(
        "capacity", help="Partition capacity: nodes, states and GPUs (sinfo)."
    )
    _add_profile(capacity, "sinfo")
    capacity.set_defaults(handler=capacity_run)
