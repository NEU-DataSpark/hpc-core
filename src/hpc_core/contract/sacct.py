"""Parser for ``sacct`` rows. Pure: takes the command's text, returns records."""

from __future__ import annotations

from .fields import Field, FieldProfile, JobRecord, ParseResult, check_known_names, iter_rows
from .identifiers import is_job_id
from .resources import parse_count, parse_gpu_request, parse_memory_mib
from .states import record_state
from .times import parse_duration, parse_time

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
        "cpus_allocated",
        "tres_requested",
        "tres_allocated",
        "total_cpu_seconds",
        "max_rss_mib",
        "time_limit_seconds",
    }
)

# The operator's run sampling (no command text). Free-text job name last.
OPERATOR_SAMPLING = FieldProfile(
    name="operator-sampling",
    command="sacct",
    fields=(
        Field("job_id", "JobID"),
        Field("partition", "Partition"),
        Field("state", "State"),
        Field("submit_time", "Submit"),
        Field("start_time", "Start"),
        Field("end_time", "End"),
        Field("cpus_allocated", "AllocCPUS"),
        Field("tres_allocated", "AllocTRES"),
        Field("total_cpu_seconds", "TotalCPU"),
        Field("max_rss_mib", "MaxRSS"),
        Field("job_name", "JobName", free_text=True),
    ),
)

# The console's task monitor: requested resources and time limit. Free-text job name last.
CONSOLE_MONITOR = FieldProfile(
    name="console-monitor",
    command="sacct",
    fields=(
        Field("job_id", "JobID"),
        Field("partition", "Partition"),
        Field("state", "State"),
        Field("submit_time", "Submit"),
        Field("start_time", "Start"),
        Field("end_time", "End"),
        Field("cpus_requested", "ReqCPUS"),
        Field("tres_requested", "ReqTRES"),
        Field("time_limit_seconds", "Timelimit"),
        Field("job_name", "JobName", free_text=True),
    ),
)


def _text_or_none(value: str | None) -> str | None:
    return value if value else None


def parse_sacct(text: str, profile: FieldProfile) -> ParseResult[JobRecord]:
    check_known_names(profile, KNOWN)
    rows, skipped = iter_rows(text, profile)
    records: list[JobRecord] = []
    for cells in rows:
        job_id = cells.get("job_id", "")
        if not is_job_id(job_id):
            skipped += 1
            continue
        state, state_class = record_state(cells.get("state", ""))
        gpus_allocated, alloc_type = (
            parse_gpu_request(cells["tres_allocated"])
            if "tres_allocated" in cells
            else (None, None)
        )
        gpus_requested, requested_type = (
            parse_gpu_request(cells["tres_requested"])
            if "tres_requested" in cells
            else (None, None)
        )
        records.append(
            JobRecord(
                job_id=job_id,
                job_name=_text_or_none(cells.get("job_name")),
                partition=_text_or_none(cells.get("partition")),
                state=state,
                state_class=state_class,
                submit_time=parse_time(cells["submit_time"]) if "submit_time" in cells else None,
                start_time=parse_time(cells["start_time"]) if "start_time" in cells else None,
                end_time=parse_time(cells["end_time"]) if "end_time" in cells else None,
                cpus_requested=parse_count(cells["cpus_requested"])
                if "cpus_requested" in cells
                else None,
                cpus_allocated=parse_count(cells["cpus_allocated"])
                if "cpus_allocated" in cells
                else None,
                gpus_requested=gpus_requested,
                gpus_allocated=gpus_allocated,
                gpu_type=alloc_type or requested_type,
                total_cpu_seconds=parse_duration(cells["total_cpu_seconds"])
                if "total_cpu_seconds" in cells
                else None,
                max_rss_mib=parse_memory_mib(cells["max_rss_mib"])
                if "max_rss_mib" in cells
                else None,
                time_limit_seconds=parse_duration(cells["time_limit_seconds"])
                if "time_limit_seconds" in cells
                else None,
            )
        )
    return ParseResult(tuple(records), skipped)
