"""Records: compact one-line JSON, round trip, and unreadable input returned rather than raised."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.records import (
    KINDS,
    REASON_EMPTY,
    REASON_FIELD,
    REASON_NAME,
    REASON_NOT_JSON,
    REASON_TOO_LARGE,
    REASON_VERSION,
    ClusterManifest,
    LeaseRecord,
    MessageRecord,
    NodeRecord,
    ProfileRecord,
    SharedRecord,
    Unreadable,
    decode_lease,
    decode_manifest,
    decode_message,
    decode_node,
    decode_profile,
    decode_shared,
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


def test_a_node_record_without_the_collector_mark_reads_as_not_a_candidate() -> None:
    text = encode(NODE)  # a node that is not a candidate writes no mark at all
    assert "shared_collector" not in text
    decoded = decode_node(text, "alice-console-a1")
    assert isinstance(decoded, NodeRecord) and decoded.shared_collector is False


def test_the_collector_mark_round_trips_as_a_boolean() -> None:
    marked = replace(NODE, shared_collector=True)
    decoded = decode_node(encode(marked), "alice-console-a1")
    assert isinstance(decoded, NodeRecord) and decoded.shared_collector is True


@pytest.mark.parametrize("value", ['"yes"', "1", "null", "[true]"])
def test_a_collector_mark_that_is_not_a_boolean_makes_the_record_unreadable(value: str) -> None:
    text = encode(NODE).replace("}\n", f',"shared_collector":{value}}}\n')
    decoded = decode_node(text, "alice-console-a1")
    assert isinstance(decoded, Unreadable) and decoded.reason == REASON_FIELD


def _shared_text(**changes: object) -> str:
    body = {
        "schema_version": 1,
        "dataset": "queue",
        "collector_node_id": "alice-console-a1",
        "payload": {"running": 3},
    }
    body.update(changes)
    return json.dumps(body) + "\n"


def test_a_shared_envelope_round_trips_with_its_four_fields() -> None:
    record = SharedRecord(1, "queue", "alice-console-a1", {"running": 3})
    text = encode(record)
    assert json.loads(text) == {
        "schema_version": 1,
        "dataset": "queue",
        "collector_node_id": "alice-console-a1",
        "payload": {"running": 3},
    }
    assert decode_shared(text, "queue") == record


def test_a_shared_envelope_with_a_non_object_payload_is_unreadable() -> None:
    decoded = decode_shared(_shared_text(payload=[1, 2]), "queue")
    assert isinstance(decoded, Unreadable) and decoded.reason == REASON_FIELD


def test_a_shared_envelope_with_an_unknown_version_is_unreadable() -> None:
    decoded = decode_shared(_shared_text(schema_version=2), "queue")
    assert isinstance(decoded, Unreadable) and decoded.reason == REASON_VERSION


def test_a_shared_envelope_for_another_dataset_is_a_name_mismatch() -> None:
    decoded = decode_shared(_shared_text(), "physical")
    assert isinstance(decoded, Unreadable) and decoded.reason == REASON_NAME


def test_a_shared_envelope_with_an_unsafe_dataset_or_collector_is_unreadable() -> None:
    assert isinstance(decode_shared(_shared_text(dataset="../x")), Unreadable)
    bad_collector = decode_shared(_shared_text(collector_node_id="a/b"))
    assert isinstance(bad_collector, Unreadable) and bad_collector.reason == REASON_FIELD


def test_a_shared_file_over_one_mebibyte_is_refused_on_read_and_on_write() -> None:
    big = _shared_text(payload={"blob": "x" * (1024 * 1024)})
    decoded = decode_shared(big, "queue")
    assert isinstance(decoded, Unreadable) and decoded.reason == REASON_TOO_LARGE
    with pytest.raises(ValidationError, match="1024 KiB limit"):
        encode(SharedRecord(1, "queue", "alice-console-a1", {"blob": "x" * (1024 * 1024)}))


def test_a_shared_payload_that_is_not_json_is_refused_on_write() -> None:
    with pytest.raises(ValidationError, match="not JSON"):
        encode(SharedRecord(1, "queue", "alice-console-a1", {"when": object()}))
