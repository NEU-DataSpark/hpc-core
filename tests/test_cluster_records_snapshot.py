"""The cluster record fields are pinned per schema version. A rename needs a version bump."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from hpc_core.coordination import records

SNAPSHOT = Path(__file__).parent / "snapshots" / "cluster_records.json"
LIVE_TYPES = {
    "manifest": records.ClusterManifest,
    "node": records.NodeRecord,
    "profile": records.ProfileRecord,
    "lease": records.LeaseRecord,
    "message": records.MessageRecord,
    "shared": records.SharedRecord,
}


def _pinned() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return loaded


def _live_fields(kind: type) -> list[str]:
    return [field.name for field in dataclasses.fields(kind)]


def drift(pinned: dict[str, Any], live: dict[str, list[str]]) -> list[str]:
    """One line per record whose fields differ from the pinned list; each names the record."""
    lines = []
    for name, expected in sorted(pinned["records"].items()):
        actual = live.get(name)
        if actual != expected:
            lines.append(f"record '{name}' fields changed: pinned {expected}, now {actual}")
    return lines


def test_every_record_matches_its_pinned_fields() -> None:
    pinned = _pinned()
    assert pinned["schema_version"] == records.SCHEMA_VERSION
    live = {name: _live_fields(kind) for name, kind in LIVE_TYPES.items()}
    assert drift(pinned, live) == []


def test_a_renamed_field_fails_and_the_message_names_the_record() -> None:
    pinned = _pinned()
    live = {name: _live_fields(kind) for name, kind in LIVE_TYPES.items()}
    live["node"] = ["node_name" if field == "node_id" else field for field in live["node"]]
    problems = drift(pinned, live)
    assert len(problems) == 1
    assert problems[0].startswith("record 'node' fields changed")
