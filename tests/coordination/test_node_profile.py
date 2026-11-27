"""Explicit node profiles: parsing, the account bound, effective limits, the two sources, the node
record that carries them and reset. Uses a manual clock and an in-memory folder; no waiting."""

from __future__ import annotations

import json

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.limits import read_profile, set_share_queue
from hpc_core.coordination.profile import (
    SOURCE_DEFAULT,
    SOURCE_EXPLICIT,
    check_against_account,
    effective_limits,
    parse_share_queue,
    resolve,
)
from hpc_core.coordination.records import (
    REASON_SHARE,
    NodeRecord,
    Unreadable,
    decode_node,
)
from hpc_core.coordination.registry import (
    OUTCOME_BEAT,
    OUTCOME_FAILED,
    NodeIdentity,
    NodeSession,
    discover,
    init_layout,
    reset_node_profile,
)
from hpc_core.coordination.store import NotFound, StoreError
from hpc_core.testing import ManualClock, MemoryFolderStore


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _session(
    store: MemoryFolderStore,
    clock: ManualClock,
    node: str,
    *,
    profile: str = "alice",
    node_quota: dict[str, int] | None = None,
) -> NodeSession:
    identity = NodeIdentity(node, profile, "console", interval_seconds=60, node_quota=node_quota)
    return NodeSession(store, identity, clock=clock.now)


def _account(store: MemoryFolderStore, clock: ManualClock, quota: dict[str, int]) -> None:
    """Create the account profile through a default node, then set its per-type quota."""
    _session(store, clock, "owner-a1").register()
    set_share_queue(store, "alice", quota, node_id="owner-a1", clock=clock.now)


def _node(store: MemoryFolderStore, node: str) -> NodeRecord:
    record = decode_node(store.read_text(layout.node_path(node)), node)
    assert isinstance(record, NodeRecord)
    return record


# --- parsing and bounds --------------------------------------------------------------------------


def test_parse_reads_type_number_pairs() -> None:
    assert parse_share_queue("h200=1,h100=0") == {"h200": 1, "h100": 0}


def test_parse_of_blank_text_is_no_explicit_values() -> None:
    assert parse_share_queue("") == {}
    assert parse_share_queue("   ") == {}


def test_parse_folds_upper_case_names_to_lower_case() -> None:
    assert parse_share_queue("H200=2") == {"h200": 2}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("h200", "not a type=number pair"),
        ("h200=", "not a type=number pair"),
        ("=1", "not a type=number pair"),
        ("h200=1.5", "must be a whole number"),
        ("h200=-1", "from 0 to 1024, not -1"),
        ("h200=2000", "from 0 to 1024, not 2000"),
        ("h 200=1", "h 200"),
        ("h200=1,H200=2", "given more than once"),
    ],
)
def test_parse_refuses_bad_pairs_and_names_the_problem(text: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_share_queue(text)


# --- account bound and effective limits ----------------------------------------------------------


def test_node_quota_above_the_account_is_refused_and_the_error_names_the_type() -> None:
    with pytest.raises(ValidationError) as error:
        check_against_account({"h200": 3}, {"h200": 2})
    assert "h200" in str(error.value)
    assert "3" in str(error.value)
    assert "2" in str(error.value)


def test_a_type_the_account_does_not_list_counts_as_zero() -> None:
    with pytest.raises(ValidationError, match="h100"):
        check_against_account({"h100": 1}, {"h200": 2})
    check_against_account({"h100": 0}, {"h200": 2})


def test_node_below_account_takes_the_node_value_for_its_type() -> None:
    assert effective_limits({"h200": 2, "h100": 4}, {"h200": 1}) == {"h200": 1, "h100": 4}


def test_unlisted_types_take_the_account_value() -> None:
    assert effective_limits({"h200": 2, "h100": 4}, None) == {"h200": 2, "h100": 4}


def test_account_lowered_then_raised_restores_the_node_value() -> None:
    node_quota = {"h200": 2}
    assert effective_limits({"h200": 2}, node_quota) == {"h200": 2}
    assert effective_limits({"h200": 1}, node_quota) == {"h200": 1}
    assert effective_limits({"h200": 2}, node_quota) == {"h200": 2}


def test_resolve_names_the_source() -> None:
    assert resolve({"h200": 2}, None).source == SOURCE_DEFAULT
    explicit = resolve({"h200": 2}, {"h200": 1})
    assert explicit.source == SOURCE_EXPLICIT
    assert explicit.effective == {"h200": 1}
    assert resolve({"h200": 2}, {}).source == SOURCE_DEFAULT


# --- node join, beat, record content -------------------------------------------------------------


def test_a_node_with_no_explicit_profile_writes_its_earlier_record_plus_default_source(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock, "plain-a1").register()
    raw = json.loads(store.read_text(layout.node_path("plain-a1")))
    earlier_keys = {
        "schema_version",
        "node_id",
        "profile_id",
        "kind",
        "display_name",
        "machine",
        "software_version",
        "started_at",
        "interval_seconds",
        "heartbeat_count",
        "instance_token",
    }
    assert set(raw) == earlier_keys | {"profile_source"}
    assert raw["profile_source"] == SOURCE_DEFAULT


def test_a_pinned_node_publishes_explicit_values_and_effective_limits(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _session(store, clock, "a1", node_quota={"h200": 1}).register()
    record = _node(store, "a1")
    assert record.profile_source == SOURCE_EXPLICIT
    assert record.node_quota == {"h200": 1}
    assert record.share_queue_limits == {"h200": 1}


def test_a_refused_pin_writes_no_node_record(store: MemoryFolderStore, clock: ManualClock) -> None:
    _account(store, clock, {"h200": 2})
    with pytest.raises(ValidationError, match="h200"):
        _session(store, clock, "a1", node_quota={"h200": 3}).register()
    with pytest.raises(NotFound):
        store.read_text(layout.node_path("a1"))


def test_an_ordinary_beat_keeps_the_explicit_values_the_node_already_holds(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    session = _session(store, clock, "a1", node_quota={"h200": 1})
    session.register()
    session.beat()
    record = _node(store, "a1")
    assert record.profile_source == SOURCE_EXPLICIT
    assert record.share_queue_limits == {"h200": 1}


def test_a_later_process_without_the_flag_keeps_explicit_values_once_the_old_record_is_stale(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _session(store, clock, "a1", node_quota={"h200": 1}).register()
    # The first instance's record goes offline after 20 intervals of 60 seconds; then a new
    # process (a new token) registers again with no flag and keeps the explicit values.
    clock.advance(3600)
    _session(store, clock, "a1").register()
    record = _node(store, "a1")
    assert record.profile_source == SOURCE_EXPLICIT
    assert record.node_quota == {"h200": 1}


def test_a_live_second_instance_of_the_same_node_is_a_conflict_and_writes_nothing(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _session(store, clock, "a1", node_quota={"h200": 1}).register()
    before = store.read_text(layout.node_path("a1"))
    result = _session(store, clock, "a1").beat()
    assert result.outcome == "conflict"
    assert store.read_text(layout.node_path("a1")) == before


def test_a_beat_after_the_account_is_lowered_takes_the_lower_value(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    session = _session(store, clock, "a1", node_quota={"h200": 2})
    session.register()
    set_share_queue(store, "alice", {"h200": 1}, node_id="owner-a1", clock=clock.now)
    session.beat()
    assert _node(store, "a1").share_queue_limits == {"h200": 1}
    set_share_queue(store, "alice", {"h200": 2}, node_id="owner-a1", clock=clock.now)
    session.beat()
    assert _node(store, "a1").share_queue_limits == {"h200": 2}


def test_the_console_path_publishes_a_new_profile_and_refuses_above_the_account(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    session = _session(store, clock, "a1")
    session.register()
    session.publish_profile({"h200": 0})
    assert _node(store, "a1").share_queue_limits == {"h200": 0}
    with pytest.raises(ValidationError):
        session.publish_profile({"h200": 3})
    assert _node(store, "a1").node_quota == {"h200": 0}


# --- reset ---------------------------------------------------------------------------------------


def test_reset_after_adjustment_returns_the_node_to_the_account_quota(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _session(store, clock, "a1", node_quota={"h200": 1}).register()
    assert reset_node_profile(store, "a1") == "reset"
    record = _node(store, "a1")
    assert record.profile_source == SOURCE_DEFAULT
    assert record.node_quota is None
    assert record.share_queue_limits == {"h200": 2}


def test_reset_twice_changes_nothing_the_second_time(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    _session(store, clock, "a1", node_quota={"h200": 1}).register()
    assert reset_node_profile(store, "a1") == "reset"
    before = store.read_text(layout.node_path("a1"))
    assert reset_node_profile(store, "a1") == "unchanged"
    assert store.read_text(layout.node_path("a1")) == before


def test_reset_keeps_the_instance_token_and_heartbeat_count(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _account(store, clock, {"h200": 2})
    session = _session(store, clock, "a1", node_quota={"h200": 1})
    session.register()
    session.beat()
    before = _node(store, "a1")
    reset_node_profile(store, "a1")
    after = _node(store, "a1")
    assert (after.instance_token, after.heartbeat_count) == (
        before.instance_token,
        before.heartbeat_count,
    )


def test_reset_of_an_absent_node_changes_nothing(store: MemoryFolderStore) -> None:
    assert reset_node_profile(store, "ghost") == "absent"
    with pytest.raises(NotFound):
        store.read_text(layout.node_path("ghost"))


# --- records -------------------------------------------------------------------------------------


def test_an_unknown_key_is_ignored_by_the_decoder(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock, "plain-a1").register()
    raw = json.loads(store.read_text(layout.node_path("plain-a1")))
    raw["future_field"] = "kept by a later version"
    decoded = decode_node(json.dumps(raw), "plain-a1")
    assert isinstance(decoded, NodeRecord)


def test_a_record_from_an_earlier_version_reads_as_default(store: MemoryFolderStore) -> None:
    earlier = {
        "schema_version": 1,
        "node_id": "old-a1",
        "profile_id": "alice",
        "kind": "console",
        "display_name": "old-a1",
        "machine": "",
        "software_version": "",
        "started_at": "2026-11-01T00:00:00Z",
        "interval_seconds": 60,
        "heartbeat_count": 3,
        "instance_token": "tok",
    }
    record = decode_node(json.dumps(earlier), "old-a1")
    assert isinstance(record, NodeRecord)
    assert record.share_queue_limits == {}
    assert record.node_quota is None
    assert record.profile_source == SOURCE_DEFAULT


@pytest.mark.parametrize(
    "patch",
    [
        {"share_queue_limits": {"h200": -1}},
        {"share_queue_limits": {"h200": 2000}},
        {"share_queue_limits": {"bad name": 1}},
        {"node_quota": {"h200": 1025}},
        {"profile_source": "guess"},
    ],
)
def test_an_invalid_share_queue_field_reads_as_unreadable(
    store: MemoryFolderStore, clock: ManualClock, patch: dict[str, object]
) -> None:
    _session(store, clock, "plain-a1").register()
    raw = json.loads(store.read_text(layout.node_path("plain-a1")))
    raw.update(patch)
    result = decode_node(json.dumps(raw), "plain-a1")
    assert isinstance(result, Unreadable)
    assert result.reason == REASON_SHARE


def test_a_profile_record_with_more_than_16_types_is_refused_before_it_is_written(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _session(store, clock, "owner-a1").register()
    too_many = {f"t{number:02d}": 1 for number in range(17)}
    with pytest.raises(ValidationError, match="at most 16"):
        set_share_queue(store, "alice", too_many, node_id="owner-a1", clock=clock.now)
    profile = read_profile(store, "alice")
    assert not isinstance(profile, Unreadable)
    assert profile.share_queue_limits == {}


class _UnreachableStore(MemoryFolderStore):
    """Every read fails the way an unreachable shared folder does."""

    def read_text(self, path: str) -> str:
        raise StoreError("the folder is unreachable", kind="io")


def test_an_unreachable_folder_with_an_explicit_quota_fails_without_raising() -> None:
    clock = ManualClock()
    store = _UnreachableStore(clock=clock)
    session = NodeSession(
        store,
        NodeIdentity("alice-console-x1", "alice", "console", node_quota={"h200": 1}),
        clock=clock.now,
    )
    result = session.register()
    assert result.outcome == OUTCOME_FAILED
    assert session.publish_profile({"h200": 1}).outcome == OUTCOME_FAILED


def test_publishing_over_an_unreadable_record_keeps_the_node_discoverable() -> None:
    clock = ManualClock()
    store = MemoryFolderStore(clock=clock)
    init_layout(store)
    set_share_queue(store, "alice", {"h200": 2}, node_id="alice-console-owner", clock=clock.now)
    store.write_text(layout.node_path("alice-console-x2"), "not json")
    session = NodeSession(
        store,
        NodeIdentity("alice-console-x2", "alice", "console", interval_seconds=60),
        clock=clock.now,
    )
    assert session.publish_profile({"h200": 1}).outcome == OUTCOME_BEAT
    record = decode_node(store.read_text(layout.node_path("alice-console-x2")), "alice-console-x2")
    assert not isinstance(record, Unreadable)
    assert record.started_at != ""
    assert record.node_quota == {"h200": 1}
    assert [view.record.node_id for view in discover(store).nodes] == ["alice-console-x2"]
