"""Each D15 event is emitted by its scenario, and no captured event holds a path or a body."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from hpc_core.coordination import events, layout
from hpc_core.coordination.limits import LeaseHandle, acquire, release, renew, repair
from hpc_core.coordination.messages import SendRefused, acknowledge, send
from hpc_core.coordination.records import LeaseRecord, encode
from hpc_core.coordination.registry import NodeIdentity, NodeSession, discover, init_layout, prune
from hpc_core.coordination.store import FolderStore, LocalFolderStore, StoreError
from hpc_core.testing import ManualClock, MemoryFolderStore
from hpc_core.testing.fault_store import FaultyFolderStore

SECRET_BODY = "BODY-TOKEN-7f3a9c"


def _identity(node: str, limit: int = 2) -> NodeIdentity:
    return NodeIdentity(
        node, node.split("-", 1)[0], "console", interval_seconds=60, concurrency_limit=limit
    )


def _session(store: FolderStore, clock: ManualClock, node: str, limit: int = 2) -> NodeSession:
    return NodeSession(store, _identity(node, limit), clock=clock.now)


def _events_of(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [getattr(r, "hpc_event", "") for r in caplog.records]


class _MoveFails(MemoryFolderStore):
    def move(self, source: str, target: str, *, replace: bool = True) -> None:
        if "/slot-" in source:
            raise StoreError("the folder refused the move", kind="io")
        super().move(source, target, replace=replace)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    memory = MemoryFolderStore(clock=clock)
    init_layout(memory, "team")
    return memory


@pytest.fixture(autouse=True)
def _capture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=events.LOGGER_NAME)


def test_registration_and_beat_emit_node_registered_and_node_beat(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    session = _session(store, clock, "alice-console-a1")
    session.register()
    session.beat()
    assert {"node.registered", "node.beat"} <= set(_events_of(caplog))


def test_a_failed_beat_emits_node_beat_failed(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    session = _session(store, clock, "alice-console-a1")
    session.register()
    faulty = FaultyFolderStore(inner=store, failures=[StoreError("transport", kind="unreachable")])
    failing = NodeSession(
        faulty, _identity("alice-console-a1"), clock=clock.now, token=session.token
    )
    result = failing.beat()
    assert result.failure is not None
    assert "node.beat_failed" in _events_of(caplog)


def test_a_live_duplicate_id_emits_node_conflict(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1").register()
    _session(store, clock, "alice-console-a1").register()
    assert "node.conflict" in _events_of(caplog)


def test_leaving_emits_node_left(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    session = _session(store, clock, "alice-console-a1")
    session.register()
    session.leave()
    assert "node.left" in _events_of(caplog)


def test_pruning_a_week_old_offline_node_emits_node_pruned(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1").register()
    clock.advance(8 * 24 * 3600)
    assert prune(store).nodes_removed == 1
    assert "node.pruned" in _events_of(caplog)


def test_an_acquired_lease_emits_lease_acquired(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1", limit=1).register()
    acquire(store, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now)
    assert "lease.acquired" in _events_of(caplog)


def test_a_full_profile_emits_lease_denied(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1", limit=1).register()
    _session(store, clock, "alice-console-b2", limit=1).register()
    acquire(store, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now)
    result = acquire(
        store, "alice", node_id="alice-console-b2", interval_seconds=60, clock=clock.now
    )
    assert result.outcome == "no-slot"
    assert "lease.denied" in _events_of(caplog)


def test_a_stale_lease_is_reclaimed_and_emits_lease_reclaimed(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1", limit=1).register()
    _session(store, clock, "alice-console-b2", limit=1).register()
    acquire(store, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now)
    clock.advance(10 * 60)
    acquire(store, "alice", node_id="alice-console-b2", interval_seconds=60, clock=clock.now)
    assert "lease.reclaimed" in _events_of(caplog)


def test_a_renewal_of_a_removed_lease_emits_lease_lost(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1", limit=1).register()
    result = acquire(
        store, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now
    )
    assert result.lease is not None
    store.remove(layout.lease_path("alice", result.lease.slot))
    assert renew(store, result.lease) is False
    assert "lease.lost" in _events_of(caplog)


def test_an_over_limit_state_emits_lease_repaired(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-console-a1", limit=2).register()
    store.make_dirs(layout.lease_dir("alice"))
    for slot, node, acquired in (
        (1, "alice-console-a1", "2027-01-01T00:00:00Z"),
        (2, "alice-console-b2", "2027-01-01T00:00:01Z"),
        (3, "alice-console-c3", "2027-01-01T00:00:02Z"),
    ):
        store.write_text(
            layout.lease_path("alice", slot),
            encode(LeaseRecord(1, "alice", slot, node, acquired, 60)),
        )
    latest = LeaseHandle("alice", 3, "alice-console-c3", "2027-01-01T00:00:02Z", 60)
    repair(store, latest, 2)
    assert "lease.repaired" in _events_of(caplog)


def test_a_reclaim_the_folder_refuses_emits_store_error(
    clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    failing = _MoveFails(clock=clock)
    init_layout(failing, "team")
    _session(failing, clock, "alice-console-a1", limit=1).register()
    _session(failing, clock, "alice-console-b2", limit=1).register()
    acquire(failing, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now)
    clock.advance(10 * 60)
    acquire(failing, "alice", node_id="alice-console-b2", interval_seconds=60, clock=clock.now)
    assert "store.error" in _events_of(caplog)


def test_send_ack_and_refusal_emit_message_events(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    _session(store, clock, "alice-skill-a1").register()
    _session(store, clock, "bob-console-b2").register()
    message_id = send(
        store,
        sender="alice-skill-a1",
        recipient="bob-console-b2",
        message_type="notice",
        body={},
        clock=clock.now,
    )
    acknowledge(store, "bob-console-b2", message_id)
    with pytest.raises(SendRefused):
        send(
            store,
            sender="alice-skill-a1",
            recipient="ghost-console-g9",
            message_type="notice",
            body={},
            clock=clock.now,
        )
    seen = set(_events_of(caplog))
    assert {"message.sent", "message.acked", "message.refused"} <= seen


def test_an_unreadable_node_record_emits_record_unreadable(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    store.write_text(layout.node_path("bob-console-b2"), "{broken\n")
    discover(store)
    assert "record.unreadable" in _events_of(caplog)


def _run_scenarios(store: FolderStore, clock: ManualClock) -> None:
    session = NodeSession(store, _identity("alice-skill-a1", limit=1), clock=clock.now)
    session.register()
    session.beat()
    acquired = acquire(
        store, "alice", node_id="alice-skill-a1", interval_seconds=60, clock=clock.now
    )
    if acquired.lease is not None:
        release(store, acquired.lease)
    _session(store, clock, "bob-console-b2").register()
    send(
        store,
        sender="alice-skill-a1",
        recipient="bob-console-b2",
        message_type="notice",
        body={"text": SECRET_BODY},
        clock=clock.now,
    )
    session.leave()


@pytest.mark.parametrize("kind", ["memory", "local"])
def test_no_event_holds_a_folder_path_a_key_or_a_message_body(
    kind: str, tmp_path: Path, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    if kind == "memory":
        target: FolderStore = MemoryFolderStore(clock=clock)
        root = ""
    else:
        team = tmp_path / "team-root"
        team.mkdir()
        target = LocalFolderStore(team, clock=time.time)
        root = str(team)
        clock = ManualClock(time.time())
    init_layout(target, "team")
    _run_scenarios(target, clock)
    captured = [r for r in caplog.records if getattr(r, "hpc_event", None)]
    assert captured, "the scenarios emitted no events"
    for record in captured:
        text = record.getMessage() + repr(getattr(record, "hpc_fields", {}))
        assert SECRET_BODY not in text
        if root:
            assert root not in text
        assert "/" not in text and "\\" not in text
        assert "=" not in text
