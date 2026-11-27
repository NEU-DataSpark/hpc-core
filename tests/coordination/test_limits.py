"""Profile limits and slot leases: one limit per profile, reclaim, release, repair, usage."""

from __future__ import annotations

import logging

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.limits import (
    GRANTED,
    NO_SLOT,
    UNKNOWN_PROFILE,
    LeaseHandle,
    SlotResult,
    acquire,
    read_profile,
    release,
    renew,
    repair,
    set_limit,
    usage,
)
from hpc_core.coordination.records import LeaseRecord, encode
from hpc_core.coordination.registry import NodeIdentity, NodeSession
from hpc_core.coordination.store import NotFound
from hpc_core.testing import ManualClock, MemoryFolderStore


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _register(
    store: MemoryFolderStore, clock: ManualClock, node: str, profile: str = "alice", limit: int = 2
) -> NodeSession:
    session = NodeSession(
        store,
        NodeIdentity(node, profile, "console", interval_seconds=60, concurrency_limit=limit),
        clock=clock.now,
    )
    session.register()
    return session


def _take(
    store: MemoryFolderStore, clock: ManualClock, node: str, profile: str = "alice"
) -> SlotResult:
    return acquire(store, profile, node_id=node, interval_seconds=60, clock=clock.now)


def _lease_files(store: MemoryFolderStore, profile: str = "alice") -> list[str]:
    return [entry.name for entry in store.list_dir(layout.lease_dir(profile)).entries]


def test_a_second_registration_keeps_the_existing_limit(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=2)
    _register(store, clock, "alice-console-b2", limit=5)
    profile = read_profile(store, "alice")
    assert profile.concurrency_limit == 2  # type: ignore[union-attr]


def test_an_invalid_limit_is_refused_and_the_error_names_the_range(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    for bad in (0, 2000):
        with pytest.raises(ValidationError, match="1 to 1024"):
            set_limit(store, "alice", bad, node_id="alice-console-a1", clock=clock.now)


def test_two_nodes_racing_for_the_last_slot_give_one_winner(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=1)
    _register(store, clock, "alice-console-b2", limit=1)
    first = _take(store, clock, "alice-console-a1")
    second = _take(store, clock, "alice-console-b2")
    assert first.outcome == GRANTED and second.outcome == NO_SLOT
    assert _lease_files(store) == ["slot-01.json"]


def test_a_stale_lease_is_reclaimed_and_a_fresh_one_is_not(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=1)
    _register(store, clock, "alice-console-b2", limit=1)
    assert _take(store, clock, "alice-console-a1").outcome == GRANTED
    assert _take(store, clock, "alice-console-b2").outcome == NO_SLOT  # holder still fresh
    clock.advance(10 * 60)  # the holder stopped renewing
    assert _take(store, clock, "alice-console-b2").outcome == GRANTED


def test_release_frees_the_slot_and_releasing_another_nodes_lease_is_refused(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=1)
    _register(store, clock, "alice-console-b2", limit=1)
    held = _take(store, clock, "alice-console-a1").lease
    assert held is not None
    intruder = LeaseHandle("alice", held.slot, "alice-console-b2", held.acquired_at, 60)
    assert release(store, intruder) is False
    assert release(store, held) is True
    assert _take(store, clock, "alice-console-b2").outcome == GRANTED


def test_a_lost_lease_is_reported_on_renewal(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hpc_core.coordination")
    _register(store, clock, "alice-console-a1", limit=1)
    held = _take(store, clock, "alice-console-a1").lease
    assert held is not None
    store.remove(layout.lease_path("alice", held.slot))
    assert renew(store, held) is False
    assert "lease.lost" in [record.getMessage() for record in caplog.records]


def test_a_renewal_keeps_the_lease_fresh(store: MemoryFolderStore, clock: ManualClock) -> None:
    _register(store, clock, "alice-console-a1", limit=1)
    held = _take(store, clock, "alice-console-a1").lease
    assert held is not None
    clock.advance(10 * 60 - 60)
    assert renew(store, held) is True
    clock.advance(60)
    assert _take(store, clock, "alice-console-b2").outcome == NO_SLOT


def test_an_over_limit_state_is_repaired_by_the_latest_holder(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=2)
    store.make_dirs(layout.lease_dir("alice"))
    holders = (
        (1, "alice-console-a1", "2027-01-01T00:00:00Z"),
        (2, "alice-console-b2", "2027-01-01T00:00:01Z"),
        (3, "alice-console-c3", "2027-01-01T00:00:02Z"),
    )
    for slot, node, acquired in holders:
        record = LeaseRecord(1, "alice", slot, node, acquired, 60)
        store.write_text(layout.lease_path("alice", slot), encode(record))
    latest = LeaseHandle("alice", 3, "alice-console-c3", "2027-01-01T00:00:02Z", 60)
    result = repair(store, latest, 2)
    assert result.outcome == NO_SLOT
    assert _lease_files(store) == ["slot-01.json", "slot-02.json"]


def test_a_lowered_limit_keeps_the_holders_and_grants_nothing_new(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=3)
    _take(store, clock, "alice-console-a1")
    _take(store, clock, "alice-console-b2")
    _take(store, clock, "alice-console-c3")
    set_limit(store, "alice", 1, node_id="alice-console-a1", clock=clock.now)
    assert usage(store, "alice").valid_leases == 3
    assert _take(store, clock, "alice-console-d4").outcome == NO_SLOT


def test_profiles_do_not_count_against_each_other(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", "alice", limit=1)
    _register(store, clock, "bob-console-a1", "bob", limit=1)
    assert _take(store, clock, "alice-console-a1", "alice").outcome == GRANTED
    assert _take(store, clock, "bob-console-a1", "bob").outcome == GRANTED


def test_usage_separates_a_renewed_holder_from_a_silent_one(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _register(store, clock, "alice-console-a1", limit=4)
    _register(store, clock, "alice-console-b2", limit=4)
    kept = _take(store, clock, "alice-console-a1").lease
    _take(store, clock, "alice-console-b2")
    assert kept is not None
    clock.advance(10 * 60)  # both are now past the online window
    assert renew(store, kept) is True  # only a1 keeps beating
    report = usage(store, "alice")
    assert (report.limit, report.valid_leases, report.stale_leases, report.nodes) == (4, 1, 1, 2)


def test_an_unknown_profile_is_a_result_and_creates_no_folder(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    assert _take(store, clock, "ghost-console-a1", "ghost").outcome == UNKNOWN_PROFILE
    with pytest.raises(NotFound):
        store.list_dir(layout.lease_dir("ghost"))
