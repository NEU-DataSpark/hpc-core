"""Three nodes of one account on one team folder, with pinned share-queue profiles.

Nodes ``a`` and ``b`` pin ``h200=1`` and node ``c`` pins ``h200=0`` under an account quota of
``h200=2``. The effective limits are read back from discovery, as a host would read them. The suite
uses a manual clock and an in-memory folder: no account, key, network or waiting.
"""

from __future__ import annotations

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.limits import (
    GRANTED,
    NO_SLOT,
    REASON_NODE_LIMIT,
    ProfileUsage,
    SlotResult,
    acquire_typed,
    release,
    set_share_queue,
    usage,
)
from hpc_core.coordination.messages import (
    DELIVERED_ACKNOWLEDGED,
    DELIVERED_PENDING,
    acknowledge,
    delivery_state,
    pending,
    send,
)
from hpc_core.coordination.registry import (
    OUTCOME_CONFLICT,
    STALE,
    NodeIdentity,
    NodeSession,
    discover,
    ensure_profile,
    init_layout,
)
from hpc_core.testing import ManualClock, MemoryFolderStore

NODES = ("a", "b", "c")
PROFILE = "alice"
ACCOUNT_QUOTA = {"h200": 2}
NODE_QUOTAS = {"a": {"h200": 1}, "b": {"h200": 1}, "c": {"h200": 0}}


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


@pytest.fixture
def team(store: MemoryFolderStore, clock: ManualClock) -> dict[str, NodeSession]:
    """The account and the three pinned nodes, each with its own session (its own token)."""
    init_layout(store)
    ensure_profile(store, PROFILE, limit=1, node_id="a", clock=clock.now)
    set_share_queue(store, PROFILE, ACCOUNT_QUOTA, node_id="a", clock=clock.now)
    sessions: dict[str, NodeSession] = {}
    for node in NODES:
        sessions[node] = NodeSession(
            store,
            NodeIdentity(
                f"node-{node}",
                PROFILE,
                "console",
                interval_seconds=60,
                node_quota=NODE_QUOTAS[node],
            ),
            clock=clock.now,
        )
        assert sessions[node].register().outcome == "registered"
    return sessions


def _limits_from_discovery(store: MemoryFolderStore) -> dict[str, int]:
    """Each node's effective H200 limit, as read from the node records."""
    return {
        view.record.node_id: view.record.share_queue_limits.get("h200", 0)
        for view in discover(store).nodes
    }


def _request(store: MemoryFolderStore, clock: ManualClock, node: str) -> SlotResult:
    return acquire_typed(
        store,
        PROFILE,
        "h200",
        node_id=f"node-{node}",
        node_limit=_limits_from_discovery(store)[f"node-{node}"],
        interval_seconds=60,
        clock=clock.now,
    )


def _lease_count(store: MemoryFolderStore) -> int:
    return len(store.list_dir(layout.lease_dir(PROFILE)).entries)


# --- 5.1 slots -----------------------------------------------------------------------------------


def test_discovery_lists_three_pinned_nodes_with_their_effective_limits(
    store: MemoryFolderStore, team: dict[str, NodeSession]
) -> None:
    views = {view.record.node_id: view.record for view in discover(store).nodes}
    assert set(views) == {"node-a", "node-b", "node-c"}
    assert {record.profile_source for record in views.values()} == {"explicit"}
    assert _limits_from_discovery(store) == {"node-a": 1, "node-b": 1, "node-c": 0}


def test_the_first_two_nodes_are_granted_and_the_zero_node_is_refused(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    assert _request(store, clock, "a").outcome == GRANTED
    assert _request(store, clock, "b").outcome == GRANTED
    refused = _request(store, clock, "c")
    assert (refused.outcome, refused.reason) == (NO_SLOT, REASON_NODE_LIMIT)
    assert _lease_count(store) == 2


def test_a_second_request_from_a_limit_one_node_is_refused(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    assert _request(store, clock, "a").outcome == GRANTED
    again = _request(store, clock, "a")
    assert (again.outcome, again.reason) == (NO_SLOT, REASON_NODE_LIMIT)
    assert _lease_count(store) == 1


def test_releasing_a_slot_does_not_give_the_zero_node_a_slot(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    held = _request(store, clock, "a")
    assert held.lease is not None
    assert release(store, held.lease) is True
    result = _request(store, clock, "c")
    assert (result.outcome, result.reason) == (NO_SLOT, REASON_NODE_LIMIT)
    assert _lease_count(store) == 0


def test_the_profile_uses_two_of_two_when_both_limit_one_nodes_hold_a_slot(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    _request(store, clock, "a")
    _request(store, clock, "b")
    report: ProfileUsage = usage(store, PROFILE)
    h200 = next(item for item in report.accelerators if item.accelerator == "h200")
    assert (h200.valid_leases, h200.account_limit) == (2, 2)


# --- 5.2 mesh, acknowledgement and staleness -----------------------------------------------------


def test_every_node_reads_the_other_two_records(
    store: MemoryFolderStore, team: dict[str, NodeSession]
) -> None:
    for node in NODES:
        others = {
            view.record.node_id
            for view in discover(store).nodes
            if view.record.node_id != f"node-{node}"
        }
        assert others == {f"node-{other}" for other in NODES if other != node}


def test_each_node_sends_one_message_to_each_other_node_and_every_inbox_holds_two(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    for sender in NODES:
        for recipient in NODES:
            if recipient == sender:
                continue
            send(
                store,
                sender=f"node-{sender}",
                recipient=f"node-{recipient}",
                message_type="notice",
                body={"from": sender},
                clock=clock.now,
            )
    for recipient in NODES:
        listed = pending(store, f"node-{recipient}")
        senders = sorted(message.from_node for message in listed.messages)
        assert len(listed.messages) == 2
        assert senders == sorted(f"node-{other}" for other in NODES if other != recipient)
        for message in listed.messages:
            assert message.to_node == f"node-{recipient}"
            assert message.body == {"from": message.from_node.removeprefix("node-")}


def test_a_node_cannot_write_another_nodes_record_while_that_node_is_live(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    before = store.read_text(layout.node_path("node-b"))
    intruder = NodeSession(
        store,
        NodeIdentity(
            "node-b",
            PROFILE,
            "console",
            interval_seconds=60,
            node_quota={"h200": 0},
        ),
        clock=clock.now,
    )
    assert intruder.beat().outcome == OUTCOME_CONFLICT
    assert store.read_text(layout.node_path("node-b")) == before


def test_an_acknowledged_message_shows_as_delivered_to_the_sender(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    message_id = send(
        store,
        sender="node-a",
        recipient="node-b",
        message_type="notice",
        body={},
        clock=clock.now,
    )
    assert delivery_state(store, "node-b", message_id) == DELIVERED_PENDING
    assert acknowledge(store, "node-b", message_id).outcome == "acknowledged"
    assert delivery_state(store, "node-b", message_id) == DELIVERED_ACKNOWLEDGED


def test_a_stale_node_does_not_stop_the_other_two(
    store: MemoryFolderStore, clock: ManualClock, team: dict[str, NodeSession]
) -> None:
    # Node c stops beating; a and b keep beating past the point where c is stale.
    clock.advance(60 * 5)
    team["a"].beat()
    team["b"].beat()
    states = {view.record.node_id: view.state for view in discover(store).nodes}
    assert states["node-c"] == STALE
    assert states["node-a"] != STALE and states["node-b"] != STALE
    message_id = send(
        store,
        sender="node-a",
        recipient="node-b",
        message_type="notice",
        body={},
        clock=clock.now,
    )
    assert acknowledge(store, "node-b", message_id).outcome == "acknowledged"
