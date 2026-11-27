"""Records: compact one-line JSON, round trip, and unreadable input returned rather than raised."""

from __future__ import annotations

import json

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.records import (
    KINDS,
    REASON_EMPTY,
    REASON_NAME,
    REASON_NOT_JSON,
    REASON_VERSION,
    ClusterManifest,
    LeaseRecord,
    MessageRecord,
    NodeRecord,
    ProfileRecord,
    Unreadable,
    decode_lease,
    decode_manifest,
    decode_message,
    decode_node,
    decode_profile,
    encode,
)

NODE = NodeRecord(
    schema_version=1,
    node_id="alice-console-a1",
    profile_id="alice",
    kind="console",
    display_name="alice-console-a1",
    machine="host-1",
    software_version="0.3.0",
    started_at="2026-11-26T10:00:00Z",
    interval_seconds=60,
    heartbeat_count=3,
    instance_token="0123456789abcdef",
)


def test_round_trip_is_compact_one_line_json_with_version() -> None:
    text = encode(NODE)
    assert text.endswith("\n") and text.count("\n") == 1
    assert '"schema_version":1' in text and ": " not in text
    assert decode_node(text, "alice-console-a1") == NODE


def test_every_record_kind_round_trips() -> None:
    profile = ProfileRecord(1, "alice", 4, "alice-console-a1", "2026-11-26T10:00:00Z")
    lease = LeaseRecord(1, "alice", 2, "alice-console-a1", "2026-11-26T10:00:00Z", 60)
    message = MessageRecord(
        1,
        "1800000000000-alice-abcdef",
        "notice",
        "alice-console-a1",
        "bob-skill-c3",
        "2026-11-26T10:00:00Z",
        "2026-12-03T10:00:00Z",
        None,
        {"text": "hello"},
    )
    assert decode_profile(encode(profile), "alice") == profile
    assert decode_lease(encode(lease)) == lease
    assert decode_message(encode(message), message.message_id) == message
    assert decode_manifest(encode(ClusterManifest(1, "team"))) == ClusterManifest(1, "team")


def test_a_corrupt_file_is_unreadable_not_an_exception() -> None:
    assert decode_node("{not json\n") == Unreadable(REASON_NOT_JSON)
    assert decode_node("") == Unreadable(REASON_EMPTY)


def test_an_unknown_version_is_unreadable() -> None:
    data = json.loads(encode(NODE))
    data["schema_version"] = 99
    assert decode_node(json.dumps(data)) == Unreadable(REASON_VERSION)


def test_a_record_whose_id_differs_from_its_file_name_is_unreadable() -> None:
    assert decode_node(encode(NODE), "someone-else") == Unreadable(REASON_NAME)


def test_an_oversized_record_is_refused_on_write_and_unreadable_on_read() -> None:
    big = NodeRecord(**{**NODE.__dict__, "display_name": "x" * 20000})
    with pytest.raises(ValidationError, match="16 KiB"):
        encode(big)
    assert decode_node("x" * (16 * 1024 + 1)) == Unreadable("too-large")


def test_kind_is_a_closed_set() -> None:
    assert KINDS == ("console", "skill", "cli")
    data = json.loads(encode(NODE))
    data["kind"] = "robot"
    assert decode_node(json.dumps(data)) == Unreadable("invalid-field")


def test_a_message_body_must_be_an_object() -> None:
    data = {
        "schema_version": 1,
        "message_id": "1800000000000-alice-abcdef",
        "type": "notice",
        "from_node": "alice-console-a1",
        "to_node": "bob-skill-c3",
        "created_at": "2026-11-26T10:00:00Z",
        "expires_at": "2026-12-03T10:00:00Z",
        "in_reply_to": None,
        "body": ["not", "an", "object"],
    }
    assert decode_message(json.dumps(data)) == Unreadable("invalid-field")


def test_layout_identifier_rule_applies_inside_records() -> None:
    data = json.loads(encode(NODE))
    data["profile_id"] = "../alice"
    assert decode_node(json.dumps(data)) == Unreadable("invalid-field")
    assert layout.LIMIT_MAX == 1024
