"""Parser for ``sinfo`` partition rows, for capacity reads. Pure: text in, records out."""

from __future__ import annotations

from .fields import Field, FieldProfile, NodeRecord, ParseResult, check_known_names, iter_rows
from .resources import parse_count, parse_gpu_request

KNOWN = frozenset({"partition", "gres", "state", "node_count"})

# The operator's capacity read: partition, GRES, node state, node count.
CAPACITY = FieldProfile(
    name="capacity",
    command="sinfo",
    fields=(
        Field("partition", "%P"),
        Field("gres", "%G"),
        Field("state", "%t"),
        Field("node_count", "%D"),
    ),
)


def parse_sinfo(text: str, profile: FieldProfile) -> ParseResult[NodeRecord]:
    check_known_names(profile, KNOWN)
    rows, skipped = iter_rows(text, profile)
    records: list[NodeRecord] = []
    for cells in rows:
        partition = cells.get("partition", "")
        if not partition:
            skipped += 1
            continue
        gres = cells.get("gres") or None
        gpus_per_node, gpu_type = parse_gpu_request(gres) if gres is not None else (None, None)
        records.append(
            NodeRecord(
                partition=partition,
                gres=gres,
                state=cells.get("state") or None,
                node_count=parse_count(cells["node_count"]) if "node_count" in cells else None,
                gpus_per_node=gpus_per_node,
                gpu_type=gpu_type,
            )
        )
    return ParseResult(tuple(records), skipped)
