"""Typed messages between nodes: send into a recipient's inbox, list pending, acknowledge.

A message is one file, written exclusively and never rewritten. Its id is a 13-digit millisecond
time, the sender id and six random hex digits, so a listing in name order is creation order. A
body is a JSON object treated as data: nothing here runs, loads or opens anything taken from it.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn

from ..contract.identifiers import ValidationError
from . import events, layout
from .layout import MAX_PENDING_MESSAGES, MESSAGE_TTL_SECONDS, TYPE_PATTERN
from .records import (
    SCHEMA_VERSION,
    MessageRecord,
    Unreadable,
    decode_message,
    decode_node,
    encode,
    time_epoch,
    time_text,
)
from .store import Exists, FolderStore, NotFound

RESERVED_TYPES: frozenset[str] = frozenset({"ping", "pong", "notice"})
DELIVERED_PENDING = "pending"
DELIVERED_ACKNOWLEDGED = "acknowledged"
DELIVERED_GONE = "gone"
# A message id is 13 time digits, a hyphen, the sender, a hyphen and the random digits.
_MAX_SENDER_LENGTH = layout.ID_MAX_LENGTH - (13 + 1 + 1 + layout.MESSAGE_ID_RANDOM_DIGITS)

_LAST_TIME: dict[str, int] = {}
_LAST_TIME_LOCK = threading.Lock()


class SendRefused(Exception):
    """A message was not written. The message names the rule, never the body."""


@dataclass(frozen=True)
class PendingList:
    messages: tuple[MessageRecord, ...]
    skipped: int


@dataclass(frozen=True)
class AckResult:
    message_id: str
    outcome: str  # "acknowledged" or "already-acknowledged"


def _message_id(sender: str, created_ms: int) -> str:
    random_part = secrets.token_hex(layout.MESSAGE_ID_RANDOM_DIGITS // 2)
    return f"{created_ms:013d}-{sender}-{random_part}"


def _next_time_ms(sender: str, now_ms: int) -> int:
    """A millisecond time for this sender that is never earlier than the sender's last one, so
    two sends in the same millisecond keep their order."""
    with _LAST_TIME_LOCK:
        last = _LAST_TIME.get(sender, 0)
        chosen = now_ms if now_ms > last else last + 1
        _LAST_TIME[sender] = chosen
        return chosen


def send(
    store: FolderStore,
    *,
    sender: str,
    recipient: str,
    message_type: str,
    body: dict[str, Any],
    clock: Callable[[], float] = time.time,
    in_reply_to: str | None = None,
    ttl_seconds: int = MESSAGE_TTL_SECONDS,
) -> str:
    """Write one message into the recipient's inbox and return its id."""
    layout.validate_id(sender, "sender id")
    layout.validate_id(recipient, "recipient id")
    if len(sender) > _MAX_SENDER_LENGTH:
        raise ValidationError("sender id is too long to form a message id")
    if TYPE_PATTERN.fullmatch(message_type) is None:
        raise ValidationError(
            "message type must be 1 to 64 lower-case letters, digits, dots, underscores or hyphens"
        )
    if not isinstance(body, dict):
        raise ValidationError("message body must be a JSON object")
    if in_reply_to is not None:
        layout.validate_id(in_reply_to, "message id")

    try:
        recipient_text = store.read_text(layout.node_path(recipient))
    except NotFound:
        _refuse(recipient, "no-record", "the recipient has no node record")
    if isinstance(decode_node(recipient_text, recipient), Unreadable):
        _refuse(recipient, "unreadable-record", "the recipient's node record is unreadable")

    inbox = layout.inbox_dir(recipient)
    try:
        pending = store.list_dir(inbox)
        waiting = sum(1 for entry in pending.entries if entry.name.endswith(".json"))
    except NotFound:
        waiting = 0
    if waiting >= MAX_PENDING_MESSAGES:
        _refuse(recipient, "inbox-full", "the recipient's inbox is full")

    now = clock()
    created_ms = _next_time_ms(sender, int(now * 1000))
    message_id = _message_id(sender, created_ms)
    record = MessageRecord(
        schema_version=SCHEMA_VERSION,
        message_id=message_id,
        type=message_type,
        from_node=sender,
        to_node=recipient,
        created_at=time_text(now),
        expires_at=time_text(now + ttl_seconds),
        in_reply_to=in_reply_to,
        body=body,
    )
    try:
        text = encode(record)
    except ValidationError:
        _refuse(recipient, "too-large", "the message is over its 64 KiB limit")
    store.make_dirs(inbox)
    try:
        store.create_exclusive(layout.inbox_path(recipient, message_id), text)
    except Exists:
        _refuse(recipient, "id-in-use", "the message id is already in use")
    events.emit(events.MESSAGE_SENT, from_node=sender, to_node=recipient, type=message_type)
    return message_id


def _refuse(recipient: str, code: str, reason: str) -> NoReturn:
    events.emit(events.MESSAGE_REFUSED, to_node=recipient, reason=code)
    raise SendRefused(f"message not sent to '{recipient}': {reason}")


def pending(store: FolderStore, node_id: str) -> PendingList:
    """The node's pending messages, oldest first. Expired and unreadable files are counted."""
    layout.validate_id(node_id, "node id")
    inbox = layout.inbox_dir(node_id)
    try:
        listing = store.list_dir(inbox)
    except NotFound:
        return PendingList((), 0)
    texts = store.read_all(inbox)
    messages: list[MessageRecord] = []
    skipped = 0
    for entry in listing.entries:
        stem = entry.name[: -len(".json")] if entry.name.endswith(".json") else ""
        record = decode_message(texts.get(entry.name, ""), expected_id=stem or None)
        if isinstance(record, Unreadable):
            skipped += 1
            events.emit(events.RECORD_UNREADABLE, kind="message", reason=record.reason)
            continue
        if time_epoch(record.expires_at) <= listing.now:
            skipped += 1
            continue
        messages.append(record)
    return PendingList(tuple(messages), skipped)


def acknowledge(store: FolderStore, node_id: str, message_id: str) -> AckResult:
    """Move a pending message to ``done``. Acknowledging twice succeeds the second time."""
    layout.validate_id(node_id, "node id")
    layout.validate_id(message_id, "message id")
    source = layout.inbox_path(node_id, message_id)
    target = layout.done_path(node_id, message_id)
    store.make_dirs(layout.done_dir(node_id))
    try:
        store.move(source, target, replace=True)
    except NotFound:
        try:
            store.stat(target)
        except NotFound:
            raise NotFound(message_id) from None
        return AckResult(message_id, "already-acknowledged")
    events.emit(events.MESSAGE_ACKED, node_id=node_id)
    return AckResult(message_id, "acknowledged")


def delivery_state(store: FolderStore, recipient: str, message_id: str) -> str:
    """``pending``, ``acknowledged`` or ``gone`` for a message the sender addressed to recipient."""
    layout.validate_id(recipient, "recipient id")
    layout.validate_id(message_id, "message id")
    for path, state in (
        (layout.inbox_path(recipient, message_id), DELIVERED_PENDING),
        (layout.done_path(recipient, message_id), DELIVERED_ACKNOWLEDGED),
    ):
        try:
            store.stat(path)
        except NotFound:
            continue
        return state
    return DELIVERED_GONE


def cleanup(store: FolderStore, node_id: str) -> int:
    """Remove expired pending messages and ``done`` messages older than 7 days.

    Returns the number of files removed.
    """
    layout.validate_id(node_id, "node id")
    removed = 0
    inbox = layout.inbox_dir(node_id)
    try:
        listing = store.list_dir(inbox)
        texts = store.read_all(inbox)
    except NotFound:
        listing = None
        texts = {}
    if listing is not None:
        for entry in listing.entries:
            record = decode_message(texts.get(entry.name, ""))
            if isinstance(record, Unreadable):
                continue
            if time_epoch(record.expires_at) <= listing.now:
                store.remove(layout.inbox_path(node_id, record.message_id))
                removed += 1
    try:
        done = store.list_dir(layout.done_dir(node_id))
    except NotFound:
        return removed
    now = store.now()
    for entry in done.entries:
        if now - entry.modified > MESSAGE_TTL_SECONDS:
            store.remove(f"{layout.done_dir(node_id)}/{entry.name}")
            removed += 1
    return removed


def answer_ping(
    store: FolderStore,
    responder: str,
    ping: MessageRecord,
    *,
    clock: Callable[[], float] = time.time,
) -> str:
    """Answer a ``ping`` with a ``pong`` that references it. Returns the pong's id."""
    if ping.type != "ping":
        raise ValidationError("only a ping can be answered with a pong")
    return send(
        store,
        sender=responder,
        recipient=ping.from_node,
        message_type="pong",
        body={},
        clock=clock,
        in_reply_to=ping.message_id,
    )
