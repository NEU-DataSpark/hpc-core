"""Parser for ``sstat`` step rows, for running-job usage. Pure: text in, records out."""

from __future__ import annotations

from .fields import Field, FieldProfile, ParseResult, SstatRecord, check_known_names, iter_rows
from .identifiers import is_step_id
from .resources import parse_count, parse_memory_mib
from .times import parse_duration

KNOWN = frozenset({"step_id", "ave_cpu_seconds", "ntasks", "max_rss_mib"})

# The operator's running-usage read: `sstat -a -n -P -o JobID,AveCPU,NTasks,MaxRSS`.
DEFAULT = FieldProfile(
    name="running-usage",
    command="sstat",
    fields=(
        Field("step_id", "JobID"),
        Field("ave_cpu_seconds", "AveCPU"),
        Field("ntasks", "NTasks"),
        Field("max_rss_mib", "MaxRSS"),
    ),
)


def parse_sstat(text: str, profile: FieldProfile) -> ParseResult[SstatRecord]:
    check_known_names(profile, KNOWN)
    rows, skipped = iter_rows(text, profile)
    records: list[SstatRecord] = []
    for cells in rows:
        step_id = cells.get("step_id", "")
        if not is_step_id(step_id):
            skipped += 1
            continue
        records.append(
            SstatRecord(
                step_id=step_id,
                ave_cpu_seconds=parse_duration(cells["ave_cpu_seconds"])
                if "ave_cpu_seconds" in cells
                else None,
                ntasks=parse_count(cells["ntasks"]) if "ntasks" in cells else None,
                max_rss_mib=parse_memory_mib(cells["max_rss_mib"])
                if "max_rss_mib" in cells
                else None,
            )
        )
    return ParseResult(tuple(records), skipped)
