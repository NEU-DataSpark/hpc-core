"""Parser for ``squeue`` rows. Pure: takes the command's text, returns records."""

from __future__ import annotations

from .fields import Field, FieldProfile, JobRecord, ParseResult, check_known_names, iter_rows
from .identifiers import is_job_id
from .resources import parse_count, parse_gpu_request
from .states import record_state
from .times import parse_time

KNOWN = frozenset(
    {
        "job_id",
        "job_name",
        "partition",
        "state",
        "submit_time",
        "start_time",
        "cpus_requested",
        "gres",
        "reason",
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


def _text_or_none(value: str | None) -> str | None:
    return value if value else None


def parse_squeue(text: str, profile: FieldProfile) -> ParseResult[JobRecord]:
    check_known_names(profile, KNOWN)
    rows, skipped = iter_rows(text, profile)
    records: list[JobRecord] = []
    for cells in rows:
        job_id = cells.get("job_id", "")
        if not is_job_id(job_id):
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
                cpus_requested=parse_count(cells["cpus_requested"])
                if "cpus_requested" in cells
                else None,
                gpus_requested=gpus_requested,
                gpu_type=gpu_type,
            )
        )
    return ParseResult(tuple(records), skipped)
