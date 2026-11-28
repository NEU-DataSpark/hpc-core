"""Node registry: registration, conflict, heartbeat, liveness, discovery, leave and prune."""

from __future__ import annotations

import json
import logging

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.records import NodeRecord, decode_node
from hpc_core.coordination.registry import (
    NodeIdentity,
    NodeSession,
    classify,
    discover,
    init_layout,
    prune,
)
from hpc_core.testing import FaultyFolderStore, ManualClock, MemoryFolderStore


def _identity(
    node_id: str = "alice-console-a1",
    profile: str = "alice",
    kind: str = "console",
    interval: int = 60,
) -> NodeIdentity:
    return NodeIdentity(
        node_id=node_id,
        profile_id=profile,
        kind=kind,
        machine="host-1",
        software_version="0.3.0",
        interval_seconds=interval,
        concurrency_limit=2,
    )


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _session(store: MemoryFolderStore, clock: ManualClock, **kwargs: object) -> NodeSession:
    identity = kwargs.pop("identity", None) or _identity()
    return NodeSession(store, identity, clock=clock.now, **kwargs)  # type: ignore[arg-type]


def test_a_console_registers_with_the_documented_fields_and_appears_in_discovery(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    session = _session(store, clock)
    assert session.register().outcome == "registered"
    record = decode_node(store.read_text(layout.node_path("alice-console-a1")), "alice-console-a1")
    assert isinstance(record, NodeRecord)
    assert record.profile_id == "alice" and record.kind == "console"
    assert record.interval_seconds == 60 and record.heartbeat_count == 0
    assert len(record.instance_token) == 16
    found = discover(store).nodes
    assert [view.record.node_id for view in found] == ["alice-console-a1"]


def test_registration_creates_the_profile_with_its_limit_once(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    other = NodeSession(
        store,
        NodeIdentity("alice-skill-b2", "alice", "skill", interval_seconds=60, concurrency_limit=9),
        clock=clock.now,
    )
    other.register()
    text = store.read_text(layout.profile_path("alice"))
    assert json.loads(text)["concurrency_limit"] == 2


def test_an_unknown_kind_is_refused_and_the_error_lists_the_kinds() -> None:
    with pytest.raises(ValidationError, match="console, skill, cli"):
        _identity(kind="robot")


def test_a_ten_second_interval_is_refused_and_the_error_names_the_minimum() -> None:
    with pytest.raises(ValidationError, match="30"):
        _identity(interval=10)


def test_two_nodes_on_one_machine_are_both_listed(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    _session(store, clock, identity=_identity("alice-console-b2")).register()
    assert [view.record.node_id for view in discover(store).nodes] == [
        "alice-console-a1",
        "alice-console-b2",
    ]


def test_a_duplicate_live_id_is_a_conflict_and_leaves_the_record_unchanged(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    before = store.read_text(layout.node_path("alice-console-a1"))
    second = _session(store, clock)
    assert second.register().outcome == "conflict"
    assert store.read_text(layout.node_path("alice-console-a1")) == before


def test_a_crashed_id_is_taken_over_after_it_goes_stale(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    clock.advance(10 * 60)  # 10 minutes with a 60 s interval: stale, not online
    assert _session(store, clock).register().outcome == "registered"


def test_a_beat_replaces_the_record_and_moves_its_file_time_forward(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    session = _session(store, clock)
    session.register()
    first = store.stat(layout.node_path("alice-console-a1")).modified
    clock.advance(60)
    result = session.beat()
    assert result.outcome == "beat" and result.heartbeat_count == 1
    assert store.stat(layout.node_path("alice-console-a1")).modified > first


def test_the_liveness_thresholds_for_a_60_second_interval(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    clock.advance(100)
    assert discover(store).nodes[0].state == "online"
    clock.advance(10 * 60 - 100)
    assert discover(store).nodes[0].state == "stale"
    clock.advance(30 * 60 - 10 * 60)
    assert discover(store).nodes[0].state == "offline"
    assert classify(180, 60) == "online" and classify(181, 60) == "stale"
    assert classify(1200, 60) == "stale" and classify(1201, 60) == "offline"


def test_a_mixed_team_lists_two_entries_and_counts_the_corrupt_record(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    clock.advance(10 * 60)
    _session(store, clock, identity=_identity("bob-skill-c3", "bob", "skill")).register()
    store.write_text(f"{layout.subfolder_path('nodes')}/corrupt-one.json", "{broken\n")
    result = discover(store)
    # sorted by profile then node: alice's node is stale, bob's is online
    assert [(view.record.profile_id, view.state) for view in result.nodes] == [
        ("alice", "stale"),
        ("bob", "online"),
    ]
    assert result.unreadable == 1


def test_an_empty_team_is_an_empty_listing_not_an_error(store: MemoryFolderStore) -> None:
    result = discover(store)
    assert result.nodes == () and result.unreadable == 0


def test_leave_removes_the_record(store: MemoryFolderStore, clock: ManualClock) -> None:
    session = _session(store, clock)
    session.register()
    assert session.leave() == "left"
    assert discover(store).nodes == ()


def test_leave_while_the_folder_is_unreachable_does_not_raise(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    session = _session(store, clock)
    session.register()
    faulty = FaultyFolderStore(store)
    other = NodeSession(faulty, _identity(), clock=clock.now, token=session.token)
    from hpc_core.coordination.store import StoreError

    faulty.failures.append(StoreError("unreachable", kind="unreachable"))
    assert other.leave() == "failed"
    clock.advance(10 * 60)
    assert discover(store).nodes[0].state == "stale"


def test_a_folder_failure_during_beat_is_a_result_and_the_count_resets(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    from hpc_core.coordination.store import StoreError

    session = _session(store, clock)
    session.register()
    faulty = FaultyFolderStore(store)
    session.store = faulty
    faulty.failures.extend([StoreError("down", kind="unreachable")] * 2)
    assert session.beat().consecutive_failures == 1
    assert session.beat().consecutive_failures == 2
    session.store = store
    assert session.beat().consecutive_failures == 0


def test_pruning_removes_only_records_offline_for_more_than_seven_days(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock, identity=_identity("old-node-1")).register()
    clock.advance(8 * 24 * 3600)
    _session(store, clock, identity=_identity("quiet-node-2")).register()
    clock.advance(2 * 24 * 3600 - 0)  # old-node-1 is 10 days old, quiet-node-2 is 2 days old
    result = prune(store)
    assert result.nodes_removed == 1
    remaining = [view.record.node_id for view in discover(store).nodes]
    assert remaining == ["quiet-node-2"]


def test_a_record_whose_id_differs_from_its_file_name_is_unreadable(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock).register()
    text = store.read_text(layout.node_path("alice-console-a1"))
    store.write_text(f"{layout.subfolder_path('nodes')}/renamed.json", text)
    result = discover(store)
    assert result.unreadable == 1
    assert [view.record.node_id for view in result.nodes] == ["alice-console-a1"]


def test_an_inbox_is_kept_while_its_node_has_a_record_and_pruned_after(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    from hpc_core.coordination.messages import send

    bob = _session(store, clock, identity=_identity("bob-skill-c3", "bob", "skill"))
    bob.register()
    send(
        store,
        sender="alice-console-a1",
        recipient="bob-skill-c3",
        message_type="notice",
        body={"text": "hi"},
        clock=clock.now,
    )
    clock.advance(9 * 24 * 3600)
    bob.beat()  # bob's record stays fresh, so his inbox is kept even though the message is old
    assert prune(store).inboxes_removed == 0
    store.remove(layout.node_path("bob-skill-c3"))
    assert prune(store).inboxes_removed == 1  # no record left and every file is older than 7 days


def test_init_layout_creates_the_layout_and_keeps_an_existing_manifest(
    store: MemoryFolderStore,
) -> None:
    assert init_layout(store, "team") is True
    assert init_layout(store, "other") is False
    assert "team" in store.read_text(layout.manifest_path())


def test_registration_and_conflict_emit_events(
    store: MemoryFolderStore, clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hpc_core.coordination")
    _session(store, clock).register()
    _session(store, clock).register()
    names = [record.getMessage() for record in caplog.records]
    assert "node.registered" in names
    assert "node.conflict" in names


def test_a_corrupt_own_record_is_taken_over(store: MemoryFolderStore, clock: ManualClock) -> None:
    session = _session(store, clock)
    session.register()
    store.write_text(layout.node_path("alice-console-a1"), "{broken\n")
    assert session.beat().outcome == "beat"
    assert isinstance(
        decode_node(store.read_text(layout.node_path("alice-console-a1"))), NodeRecord
    )


def test_a_beat_writes_the_collector_mark_and_only_this_nodes_record(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    alice = NodeSession(
        store,
        NodeIdentity("alice-console-a1", "alice", "console", shared_collector=True),
        clock=clock.now,
    )
    bob = NodeSession(
        store,
        NodeIdentity("alice-console-b2", "alice", "console", shared_collector=False),
        clock=clock.now,
    )
    assert alice.register().outcome == "registered"
    assert bob.register().outcome == "registered"
    assert alice.beat().outcome == "beat"
    marked = decode_node(store.read_text(layout.node_path("alice-console-a1")), "alice-console-a1")
    plain = decode_node(store.read_text(layout.node_path("alice-console-b2")), "alice-console-b2")
    assert isinstance(marked, NodeRecord) and marked.shared_collector is True
    assert isinstance(plain, NodeRecord) and plain.shared_collector is False


def test_the_mark_must_be_a_boolean_in_the_identity() -> None:
    with pytest.raises(ValidationError, match="true or false"):
        NodeIdentity("alice-console-a1", "alice", "console", shared_collector=1)  # type: ignore[arg-type]
