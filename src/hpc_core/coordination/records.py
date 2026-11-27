"""Record files of the protocol: node, profile, lease, message and manifest.

Each record is compact one-line JSON ending in a newline, with a ``schema_version``. Encoding
refuses a record over its size limit. Decoding never raises for bad text, an unsupported version or
a bad field: it returns ``Unreadable`` with a reason, so a listing can skip the record and count it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from ..contract.identifiers import ValidationError
from ..contract.times import format_time, parse_report_time
from .layout import (
    LEASE_RECORD_LIMIT,
    LIMIT_MAX,
    LIMIT_MIN,
    MESSAGE_LIMIT,
    NODE_RECORD_LIMIT,
    PROFILE_RECORD_LIMIT,
    TYPE_PATTERN,
    validate_id,
)

SCHEMA_VERSION = 1
SUPPORTED_VERSIONS: frozenset[int] = frozenset({SCHEMA_VERSION})
KINDS: tuple[str, ...] = ("console", "skill", "cli")
MIN_INTERVAL_SECONDS = 30
DEFAULT_INTERVAL_SECONDS = 60

# Reasons a record is unreadable. Each maps to a self-check code in ``check``.
REASON_NOT_JSON = "not-json"
REASON_NOT_OBJECT = "not-an-object"
REASON_VERSION = "unsupported-version"
REASON_FIELD = "invalid-field"
REASON_TOO_LARGE = "too-large"
REASON_NAME = "name-mismatch"
REASON_EMPTY = "empty"


@dataclass(frozen=True)
class Unreadable:
    """A record that could not be read. ``reason`` is one of the ``REASON_`` constants."""

    reason: str


@dataclass(frozen=True)
class ClusterManifest:
    schema_version: int
    team_label: str


@dataclass(frozen=True)
class NodeRecord:
    schema_version: int
    node_id: str
    profile_id: str
    kind: str
    display_name: str
    machine: str
    software_version: str
    started_at: str
    interval_seconds: int
    heartbeat_count: int
    instance_token: str


@dataclass(frozen=True)
class ProfileRecord:
    schema_version: int
    profile_id: str
    concurrency_limit: int
    updated_by: str
    updated_at: str


@dataclass(frozen=True)
class LeaseRecord:
    schema_version: int
    profile_id: str
    slot: int
    node_id: str
    acquired_at: str
    interval_seconds: int


@dataclass(frozen=True)
class MessageRecord:
    schema_version: int
    message_id: str
    type: str
    from_node: str
    to_node: str
    created_at: str
    expires_at: str
    in_reply_to: str | None
    body: dict[str, Any]


AnyRecord = ClusterManifest | NodeRecord | ProfileRecord | LeaseRecord | MessageRecord
R = TypeVar("R", ClusterManifest, NodeRecord, ProfileRecord, LeaseRecord, MessageRecord)

RECORD_LIMITS: dict[type[AnyRecord], int] = {
    NodeRecord: NODE_RECORD_LIMIT,
    ProfileRecord: PROFILE_RECORD_LIMIT,
    LeaseRecord: LEASE_RECORD_LIMIT,
    MessageRecord: MESSAGE_LIMIT,
    ClusterManifest: NODE_RECORD_LIMIT,
}


def time_text(epoch_seconds: float) -> str:
    """A clock reading as the protocol's UTC time text, in whole seconds."""
    return format_time(datetime.fromtimestamp(int(epoch_seconds), UTC))


def time_epoch(text: str) -> float:
    """The epoch seconds of a protocol time text. Raises ValueError for any other text."""
    return parse_report_time(text).timestamp()


def encode(record: AnyRecord) -> str:
    """Compact one-line JSON with a trailing newline. Refuses a record over its size limit."""
    text = json.dumps(asdict(record), separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    text += "\n"
    limit = RECORD_LIMITS[type(record)]
    if len(text.encode("utf-8")) > limit:
        raise ValidationError(f"record is over its {limit // 1024} KiB limit")
    return text


def _object(text: str, limit: int) -> dict[str, Any] | Unreadable:
    if not text.strip():
        return Unreadable(REASON_EMPTY)
    if len(text.encode("utf-8")) > limit:
        return Unreadable(REASON_TOO_LARGE)
    try:
        value = json.loads(text)
    except ValueError:
        return Unreadable(REASON_NOT_JSON)
    if not isinstance(value, dict):
        return Unreadable(REASON_NOT_OBJECT)
    version = value.get("schema_version")
    if isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
        return Unreadable(REASON_VERSION)
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text")
    return value


def _integer(value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError("integer out of range")
    return value


def _ident(value: Any, what: str) -> str:
    return validate_id(_text(value), what)


def _when(value: Any) -> str:
    text = _text(value)
    time_epoch(text)
    return text


def _build(record_type: type[R], text: str, expected_id: str | None) -> R | Unreadable:
    data = _object(text, RECORD_LIMITS[record_type])
    if isinstance(data, Unreadable):
        return data
    try:
        record = _from_data(record_type, data)
    except (ValueError, ValidationError, TypeError, KeyError):
        return Unreadable(REASON_FIELD)
    id_field = _ID_FIELD[record_type]
    if expected_id is not None and getattr(record, id_field, None) != expected_id:
        return Unreadable(REASON_NAME)
    return record


_ID_FIELD: dict[type[AnyRecord], str] = {
    NodeRecord: "node_id",
    ProfileRecord: "profile_id",
    LeaseRecord: "profile_id",
    MessageRecord: "message_id",
    ClusterManifest: "team_label",
}


def _from_data(record_type: type[R], data: dict[str, Any]) -> R:
    if record_type is NodeRecord:
        kind = _text(data["kind"])
        if kind not in KINDS:
            raise ValueError("unknown kind")
        return NodeRecord(  # type: ignore[return-value]
            schema_version=SCHEMA_VERSION,
            node_id=_ident(data["node_id"], "node id"),
            profile_id=_ident(data["profile_id"], "profile id"),
            kind=kind,
            display_name=_text(data["display_name"])[:200],
            machine=_text(data["machine"])[:200],
            software_version=_text(data["software_version"])[:64],
            started_at=_when(data["started_at"]),
            interval_seconds=_integer(data["interval_seconds"], 1, 86400),
            heartbeat_count=_integer(data["heartbeat_count"], 0, 2**53),
            instance_token=_ident(data["instance_token"], "instance token"),
        )
    if record_type is ProfileRecord:
        return ProfileRecord(  # type: ignore[return-value]
            schema_version=SCHEMA_VERSION,
            profile_id=_ident(data["profile_id"], "profile id"),
            concurrency_limit=_integer(data["concurrency_limit"], LIMIT_MIN, LIMIT_MAX),
            updated_by=_ident(data["updated_by"], "node id"),
            updated_at=_when(data["updated_at"]),
        )
    if record_type is LeaseRecord:
        return LeaseRecord(  # type: ignore[return-value]
            schema_version=SCHEMA_VERSION,
            profile_id=_ident(data["profile_id"], "profile id"),
            slot=_integer(data["slot"], LIMIT_MIN, LIMIT_MAX),
            node_id=_ident(data["node_id"], "node id"),
            acquired_at=_when(data["acquired_at"]),
            interval_seconds=_integer(data["interval_seconds"], 1, 86400),
        )
    if record_type is MessageRecord:
        body = data["body"]
        if not isinstance(body, dict):
            raise ValueError("body must be an object")
        reply = data["in_reply_to"]
        msg_type = _text(data["type"])
        if TYPE_PATTERN.fullmatch(msg_type) is None:
            raise ValueError("bad type")
        return MessageRecord(  # type: ignore[return-value]
            schema_version=SCHEMA_VERSION,
            message_id=_ident(data["message_id"], "message id"),
            type=msg_type,
            from_node=_ident(data["from_node"], "node id"),
            to_node=_ident(data["to_node"], "node id"),
            created_at=_when(data["created_at"]),
            expires_at=_when(data["expires_at"]),
            in_reply_to=None if reply is None else _ident(reply, "message id"),
            body=body,
        )
    if record_type is ClusterManifest:
        return ClusterManifest(  # type: ignore[return-value]
            schema_version=SCHEMA_VERSION,
            team_label=_text(data.get("team_label", ""))[:200],
        )
    raise TypeError("unknown record type")


def decode_node(text: str, expected_id: str | None = None) -> NodeRecord | Unreadable:
    return _build(NodeRecord, text, expected_id)


def decode_profile(text: str, expected_id: str | None = None) -> ProfileRecord | Unreadable:
    return _build(ProfileRecord, text, expected_id)


def decode_lease(text: str, expected_id: str | None = None) -> LeaseRecord | Unreadable:
    return _build(LeaseRecord, text, expected_id)


def decode_message(text: str, expected_id: str | None = None) -> MessageRecord | Unreadable:
    return _build(MessageRecord, text, expected_id)


def decode_manifest(text: str) -> ClusterManifest | Unreadable:
    return _build(ClusterManifest, text, None)
