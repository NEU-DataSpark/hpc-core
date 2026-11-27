"""Accelerator-aware slots: account and node limits per type, typed and untyped counted apart,
the over-limit repair per type and a race on the last slot. Manual clock, in-memory folder."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.limits import (
    GRANTED,
    NO_SLOT,
    REASON_ACCOUNT_LIMIT,
    REASON_NODE_LIMIT,
    SlotResult,
    acquire,
    acquire_typed,
    release,
    set_share_queue,
)
from hpc_core.coordination.registry import NodeIdentity, NodeSession
from hpc_core.testing import ManualClock, MemoryFolderStore


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _account(
    store: MemoryFolderStore, clock: ManualClock, quota: dict[str, int], limit: int = 1
) -> None:
    """Create the profile with an untyped limit and the per-type account quota."""
    NodeSession(
        store,
        NodeIdentity("owner-a1", "alice", "console", interval_seconds=60, concurrency_limit=limit),
        clock=clock.now,
    ).register()
    set_share_queue(store, "alice", quota, node_id="owner-a1", clock=clock.now)


def _typed(
    store: MemoryFolderStore,
    clock: ManualClock,
    node: str,
    accelerator: str,
    node_limit: int,
) -> SlotResult:
    return acquire_typed(
        store,
        "alice",
        accelerator,
        node_id=node,
        node_limit=node_limit,
        interval_seconds=60,
        clock=clock.now,
    )


def _lease_files(store: MemoryFolderStore) -> list[str]:
    return sorted(entry.name for entry in store.list_dir(layout.lease_dir("alice")).entries)


# --- 2.1 account and node limits -----------------------------------------------------------------


def test_three_nodes_with_limits_1_1_and_0_under_account_2(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    first = _typed(store, clock, "a", "h200", 1)
    second = _typed(store, clock, "b", "h200", 1)
    assert (first.outcome, second.outcome) == (GRANTED, GRANTED)
    assert first.lease is not None and first.lease.accelerator == "h200"
    before = _lease_files(store)
    refused = _typed(store, clock, "c", "h200", 0)
    assert (refused.outcome, refused.reason) == (NO_SLOT, REASON_NODE_LIMIT)
    assert refused.lease is None
    assert _lease_files(store) == before


def test_a_refusal_for_the_account_creates_no_file(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _typed(store, clock, "a", "h200", 1)
    _typed(store, clock, "b", "h200", 1)
    before = _lease_files(store)
    result = _typed(store, clock, "d", "h200", 1)
    assert (result.outcome, result.reason) == (NO_SLOT, REASON_ACCOUNT_LIMIT)
    assert _lease_files(store) == before


def test_node_quota_reached_is_refused_even_with_room_in_the_account(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 3})
    assert _typed(store, clock, "a", "h200", 1).outcome == GRANTED
    result = _typed(store, clock, "a", "h200", 1)
    assert (result.outcome, result.reason) == (NO_SLOT, REASON_NODE_LIMIT)


def test_zero_never_grants_and_creates_no_file(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    for _ in range(3):
        result = _typed(store, clock, "c", "h200", 0)
        assert (result.outcome, result.reason) == (NO_SLOT, REASON_NODE_LIMIT)
    assert _lease_files(store) == []


def test_a_type_the_account_does_not_list_counts_as_zero(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    result = _typed(store, clock, "a", "h100", 1)
    assert (result.outcome, result.reason) == (NO_SLOT, REASON_ACCOUNT_LIMIT)
    assert _lease_files(store) == []


# --- 2.2 typed and untyped counted apart ---------------------------------------------------------


def test_an_untyped_request_succeeds_while_a_typed_lease_is_held(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2}, limit=1)
    assert _typed(store, clock, "a", "h200", 1).outcome == GRANTED
    untyped = acquire(store, "alice", node_id="b", interval_seconds=60, clock=clock.now)
    assert untyped.outcome == GRANTED
    assert untyped.lease is not None and untyped.lease.accelerator is None


def test_a_typed_lease_does_not_use_up_the_untyped_limit(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2}, limit=1)
    assert acquire(store, "alice", node_id="a", interval_seconds=60, clock=clock.now).outcome == (
        GRANTED
    )
    assert _typed(store, clock, "b", "h200", 1).outcome == GRANTED
    assert acquire(store, "alice", node_id="c", interval_seconds=60, clock=clock.now).outcome == (
        NO_SLOT
    )


def test_untyped_refusal_keeps_its_concurrency_reason(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2}, limit=1)
    acquire(store, "alice", node_id="a", interval_seconds=60, clock=clock.now)
    result = acquire(store, "alice", node_id="b", interval_seconds=60, clock=clock.now)
    assert (result.outcome, result.reason) == (NO_SLOT, "concurrency")


def test_lowering_a_node_quota_keeps_the_holder_and_stops_new_slots(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    held = _typed(store, clock, "a", "h200", 1)
    assert held.lease is not None
    # The node's effective limit drops to 0: the holder keeps its lease, no new one is granted.
    assert _typed(store, clock, "a", "h200", 0).reason == REASON_NODE_LIMIT
    assert len(_lease_files(store)) == 1
    assert release(store, held.lease) is True


def test_lowering_the_account_keeps_held_slots(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _typed(store, clock, "a", "h200", 1)
    _typed(store, clock, "b", "h200", 1)
    set_share_queue(store, "alice", {"h200": 1}, node_id="owner-a1", clock=clock.now)
    assert len(_lease_files(store)) == 2
    assert _typed(store, clock, "c", "h200", 1).reason == REASON_ACCOUNT_LIMIT


# --- 2.3 over-limit repair per type --------------------------------------------------------------


class _RacingStore(MemoryFolderStore):
    """Holds two racing takers at the same point: after each has listed the folder for its
    check, and after each has created its lease, before either recounts. The barrier is passed
    the same number of times by each taker, so the race cannot deadlock."""

    def __init__(self, clock: ManualClock, barrier: threading.Barrier) -> None:
        super().__init__(clock=clock)
        self._barrier = barrier
        self._local = threading.local()

    def create_exclusive(self, path: str, text: str) -> None:
        super().create_exclusive(path, text)
        if path.startswith(layout.lease_dir("alice")):
            self._local.created = True

    def list_dir(self, path: str, *, hidden: bool = False) -> Any:
        if path == layout.lease_dir("alice"):
            if getattr(self._local, "created", False):
                self._local.created = False
                self._barrier.wait(timeout=10)
            else:
                self._barrier.wait(timeout=10)
        return super().list_dir(path, hidden=hidden)


def test_two_nodes_race_for_the_last_h200_slot_and_one_valid_lease_remains(
    clock: ManualClock,
) -> None:
    racing = _RacingStore(clock, threading.Barrier(2))
    _account(racing, clock, {"h200": 1})
    # Pass the barrier per taker: each takes three waits (two before the create, one after).
    results: dict[str, SlotResult] = {}

    def take(node: str, moment: float) -> None:
        results[node] = acquire_typed(
            racing,
            "alice",
            "h200",
            node_id=node,
            node_limit=1,
            interval_seconds=60,
            clock=lambda: moment,
        )

    first = threading.Thread(target=take, args=("a", clock.now()))
    second = threading.Thread(target=take, args=("b", clock.now() + 1))
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive() and not second.is_alive()
    # Read the folder past the racing wrapper: the barrier belongs to the two racing takers only.
    remaining = MemoryFolderStore.list_dir(racing, layout.lease_dir("alice")).entries
    assert len(remaining) == 1
    assert results["a"].outcome == GRANTED
    assert (results["b"].outcome, results["b"].reason) == (NO_SLOT, REASON_ACCOUNT_LIMIT)


def test_a_typed_lease_is_released_by_its_holder(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 1})
    granted = _typed(store, clock, "a", "h200", 1)
    assert granted.lease is not None and release(store, granted.lease)
    assert _typed(store, clock, "b", "h200", 1).outcome == GRANTED
