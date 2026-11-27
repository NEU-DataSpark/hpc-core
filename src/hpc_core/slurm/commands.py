"""Fixed, read-only Slurm command templates.

Every builder returns an argument tuple that starts with ``env TZ=UTC`` and runs one of ``squeue``,
``sacct``, ``sinfo`` or ``sstat``. The only values inserted are a validated account, a validated
job id and a bounded number of hours. Nothing else from a caller reaches a command, and no command
here submits, cancels, holds, releases or requeues a job.
"""

from __future__ import annotations

from ..contract.fields import FieldProfile
from ..contract.identifiers import ValidationError, validate_account, validate_job_id

READ_ONLY_PROGRAMS: frozenset[str] = frozenset({"squeue", "sacct", "sinfo", "sstat"})
TIME_PREFIX: tuple[str, ...] = ("env", "TZ=UTC")
MAX_HOURS = 24 * 366


def format_arguments(profile: FieldProfile) -> tuple[str, ...]:
    """The output-format arguments that ask for exactly the profile's fields, in order."""
    tokens = [item.token for item in profile.fields]
    if profile.command in {"squeue", "sinfo"}:
        return ("-o", profile.separator.join(tokens))
    return (f"--format={','.join(tokens)}", f"--delimiter={profile.separator}")


def _hours(hours: int) -> int:
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_HOURS:
        raise ValidationError(f"hours must be a whole number from 1 to {MAX_HOURS}")
    return hours


def squeue_queue(profile: FieldProfile, account: str) -> tuple[str, ...]:
    return (
        *TIME_PREFIX,
        "squeue",
        "--noheader",
        f"--user={validate_account(account)}",
        *format_arguments(profile),
    )


def sacct_finished(profile: FieldProfile, account: str, hours: int) -> tuple[str, ...]:
    return (
        *TIME_PREFIX,
        "sacct",
        "-n",
        "-P",
        "-X",
        f"--user={validate_account(account)}",
        f"--starttime=now-{_hours(hours)}hours",
        *format_arguments(profile),
    )


def sacct_job(profile: FieldProfile, job_id: str) -> tuple[str, ...]:
    return (
        *TIME_PREFIX,
        "sacct",
        "-n",
        "-P",
        "-X",
        f"--jobs={validate_job_id(job_id)}",
        *format_arguments(profile),
    )


def sinfo_capacity(profile: FieldProfile) -> tuple[str, ...]:
    return (*TIME_PREFIX, "sinfo", "--noheader", *format_arguments(profile))


def sstat_usage(profile: FieldProfile, job_id: str) -> tuple[str, ...]:
    if profile.separator != "|":
        raise ValidationError("sstat output is always '|'-separated; use a profile with '|'")
    # sstat has no --delimiter option on Slurm 23.11; -P already separates fields with '|'.
    return (
        *TIME_PREFIX,
        "sstat",
        "-n",
        "-P",
        "-a",
        f"--jobs={validate_job_id(job_id)}",
        f"--format={','.join(item.token for item in profile.fields)}",
    )
