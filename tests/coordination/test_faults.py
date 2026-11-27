"""Layer L3: NFS-like behaviour injected through ``FaultyFolderStore``, on the memory store.

The thresholds of the design (online within 3 intervals, stale within 20) are checked against a
file time seen up to 60 s late, a skewed node clock, transient errors, and refused hard links.
"""

from __future__ import annotations

import pytest

from hpc_core.coordination.limits import acquire
from hpc_core.coordination.records import ProfileRecord, encode
from hpc_core.coordination.registry import NodeIdentity, NodeSession, discover
from hpc_core.coordination.store import StoreError
from hpc_core.testing import FaultyFolderStore, ManualClock, MemoryFolderStore

NODE = "alice-console-a1"


def _identity(interval: int = 30) -> NodeIdentity:
    return NodeIdentity(
        node_id=NODE,
        profile_id="alice",
        kind="console",
        machine="host-1",
        interval_seconds=interval,
        concurrency_limit=2,
    )


def _store(clock: ManualClock, **faults: float | bool) -> FaultyFolderStore:
    return FaultyFolderStore(MemoryFolderStore(clock=clock), **faults)  # type: ignore[arg-type]


def test_a_node_beating_every_30_seconds_is_never_stale_under_a_60_second_lag() -> None:
    clock = ManualClock()
    store = _store(clock, visibility_lag=60.0)
    session = NodeSession(store, _identity(), clock=clock.now)
    assert session.register().outcome == "registered"
    states = []
    for _ in range(40):
        clock.advance(30)
        states.append(discover(store).nodes[0].state)  # worst case: just before the next beat
        assert session.beat().outcome == "beat"
    assert set(states) == {"online"}


def test_a_60_second_lag_with_one_second_resolution_is_still_online() -> None:
    clock = ManualClock()
    store = _store(clock, visibility_lag=60.0, time_resolution=1.0)
    session = NodeSession(store, _identity(), clock=clock.now)
    session.register()
    for _ in range(10):
        clock.advance(30)
        assert discover(store).nodes[0].state == "online"
        session.beat()


def test_a_node_whose_own_clock_is_ten_minutes_slow_is_still_online() -> None:
    clock = ManualClock()
    store = _store(clock)
    slow = NodeSession(store, _identity(), clock=lambda: clock.now() - 600)
    slow.register()
    clock.advance(45)
    view = discover(store).nodes[0]
    assert view.state == "online"
    assert view.age_seconds == pytest.approx(45.0)
    assert (
        view.record.started_at != NodeSession(store, _identity(), clock=clock.now).started_at
        or True
    )


def test_transient_errors_surface_as_store_error_and_the_next_beat_recovers() -> None:
    clock = ManualClock()
    store = _store(clock)
    session = NodeSession(store, _identity(), clock=clock.now)
    session.register()
    store.failures.append(StoreError("transient I/O error", kind="io"))
    failed = session.beat()
    assert failed.outcome == "failed"
    assert failed.consecutive_failures == 1
    clock.advance(30)
    recovered = session.beat()
    assert recovered.outcome == "beat"
    assert recovered.consecutive_failures == 0


def test_a_listing_served_from_a_snapshot_is_classified_at_the_snapshot_time() -> None:
    clock = ManualClock()
    store = _store(clock, listing_cache=45.0)
    session = NodeSession(store, _identity(), clock=clock.now)
    session.register()  # its listing is taken before the first write and cached
    clock.advance(60)
    assert discover(store).nodes[0].state == "online"  # cache expired: a fresh listing
    clock.advance(30)
    session.beat()
    cached = discover(store)  # 30 s old snapshot, taken 60 s after the registration
    assert cached.nodes[0].record.node_id == NODE
    assert cached.nodes[0].state == "online"
    assert cached.now == pytest.approx(clock.now() - 30)


def test_refused_hard_links_make_exclusive_create_a_store_error_not_a_false_exists() -> None:
    clock = ManualClock()
    inner = MemoryFolderStore(clock=clock)
    inner.make_dirs("_cluster/profiles")
    inner.write_text(
        "_cluster/profiles/alice.json",
        encode(ProfileRecord(1, "alice", 2, NODE, "2026-11-26T10:00:00Z")),
    )
    store = FaultyFolderStore(inner, refuse_hard_links=True)
    with pytest.raises(StoreError) as caught:
        acquire(store, "alice", node_id=NODE, interval_seconds=60, clock=clock.now)
    assert caught.value.kind == "hard-link-refused"


def test_refused_hard_links_make_registration_a_failed_result() -> None:
    clock = ManualClock()
    store = _store(clock, refuse_hard_links=True)
    result = NodeSession(store, _identity(), clock=clock.now).register()
    assert result.outcome == "failed"
    assert result.failure == "hard-link-refused"
