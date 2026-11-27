"""Parser for ``squeue`` rows. Pure: takes the command's text, returns records."""

from __future__ import annotations

from .fields import (
    UNIT_SEPARATOR,
    Field,
    FieldProfile,
    JobRecord,
    ParseResult,
    check_known_names,
    iter_rows,
)
from .identifiers import is_extended_job_id, is_job_id
from .resources import parse_count, parse_gpu_request
from .states import record_state
from .times import UNSET_TOKENS, parse_duration, parse_time

KNOWN = frozenset(
    {
        "job_id",
        "job_name",
        "partition",
        "state",
        "submit_time",
        "start_time",
        "end_time",
        "cpus_requested",
        "node_count",
        "gres",
        "time_limit_seconds",
        "reason",
        "dependency_text",
        "command",
    }
)

# The operator's run sampling: id, partition, state, submit, start, CPUs, GRES, reason, name.
# No command text: a run report never holds one.
OPERATOR_SAMPLING = FieldProfile(
    name="operator-sampling",
    command="squeue",
    fields=(
        Field("job_id", "%i"),
        Field("partition", "%P"),
        Field("state", "%T"),
        Field("submit_time", "%V"),
        Field("start_time", "%S"),
        Field("cpus_requested", "%C"),
        Field("gres", "%b"),
        Field("reason", "%r"),
        Field("job_name", "%j", free_text=True),
    ),
)


# The console's Task Monitor: the fourteen fields of its squeue format, split on the unit separator.
# Times are read as UTC. gpus_requested is the GRES count per node; the job total is that times
# node_count. Placeholders (N/A, UNLIMITED, (null)) read as unset.
CONSOLE_MONITOR = FieldProfile(
    name="console-monitor",
    command="squeue",
    separator=UNIT_SEPARATOR,
    extended_job_ids=True,
    fields=(
        Field("job_id", "%i"),
        Field("job_name", "%j"),
        Field("partition", "%P"),
        Field("state", "%T"),
        Field("submit_time", "%V"),
        Field("start_time", "%S"),
        Field("end_time", "%e"),
        Field("cpus_requested", "%C"),
        Field("node_count", "%D"),
        Field("gres", "%b"),
        Field("time_limit_seconds", "%l"),
        Field("reason", "%r"),
        Field("dependency_text", "%E"),
        Field("command", "%o", free_text=True),
    ),
)

_NO_TEXT = UNSET_TOKENS | {"(null)"}


def _text_or_none(value: str | None) -> str | None:
    return value if value else None


def _text_or_unset(value: str | None) -> str | None:
    """A text field where Slurm's placeholders mean unset. Surrounding spaces are not kept."""
    if value is None or value.strip() in _NO_TEXT:
        return None
    return value.strip()


def parse_squeue(text: str, profile: FieldProfile) -> ParseResult[JobRecord]:
    check_known_names(profile, KNOWN)
    rows, skipped = iter_rows(text, profile)
    accepts_id = is_extended_job_id if profile.extended_job_ids else is_job_id
    records: list[JobRecord] = []
    for cells in rows:
        job_id = cells.get("job_id", "")
        if not accepts_id(job_id):
            skipped += 1
            continue
        state, state_class = record_state(cells.get("state", ""))
        gpus_requested, gpu_type = (
            parse_gpu_request(cells["gres"]) if "gres" in cells else (None, None)
        )
        records.append(
            JobRecord(
                job_id=job_id,
                job_name=_text_or_none(cells.get("job_name")),
                partition=_text_or_none(cells.get("partition")),
                state=state,
                state_class=state_class,
                reason=_text_or_none(cells.get("reason")),
                submit_time=parse_time(cells["submit_time"]) if "submit_time" in cells else None,
                start_time=parse_time(cells["start_time"]) if "start_time" in cells else None,
                end_time=parse_time(cells["end_time"]) if "end_time" in cells else None,
                cpus_requested=parse_count(cells["cpus_requested"])
                if "cpus_requested" in cells
                else None,
                node_count=parse_count(cells["node_count"]) if "node_count" in cells else None,
                gpus_requested=gpus_requested,
                gpu_type=gpu_type,
                time_limit_seconds=parse_duration(cells["time_limit_seconds"])
                if "time_limit_seconds" in cells
                else None,
                dependency_text=_text_or_unset(cells.get("dependency_text")),
                command=_text_or_unset(cells.get("command")),
            )
        )
    return ParseResult(tuple(records), skipped)
