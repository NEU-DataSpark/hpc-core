"""Per-type usage report and the self-check of typed leases and share-queue fields, on the
three-node example: account h200=2, node limits 1, 1 and 0. Manual clock, in-memory folder."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.check import FAIL, OK, WARN, CheckResult, run_check
from hpc_core.coordination.limits import acquire_typed, set_share_queue, usage
from hpc_core.coordination.registry import (
    NodeIdentity,
    NodeSession,
    ensure_profile,
    init_layout,
)
from hpc_core.testing import ManualClock, MemoryFolderStore


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(clock: ManualClock) -> MemoryFolderStore:
    return MemoryFolderStore(clock=clock)


def _three_nodes(store: MemoryFolderStore, clock: ManualClock) -> None:
    """Account h200=2 and three pinned nodes of one account: limits 1, 1 and 0."""
    init_layout(store)
    ensure_profile(store, "alice", limit=1, node_id="owner", clock=clock.now)
    set_share_queue(store, "alice", {"h200": 2}, node_id="owner", clock=clock.now)
    for node, value in {"a": 1, "b": 1, "c": 0}.items():
        NodeSession(
            store,
            NodeIdentity(
                node,
                "alice",
                "console",
                interval_seconds=60,
                concurrency_limit=1,
                node_quota={"h200": value},
            ),
            clock=clock.now,
        ).register()


def _status(results: Sequence[CheckResult], code: str) -> str:
    for result in results:
        if result.code == code:
            return result.status
    raise AssertionError(f"no check result {code}")


def test_usage_shows_h200_quota_held_and_each_node_share(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    granted = acquire_typed(
        store, "alice", "h200", node_id="a", node_limit=1, interval_seconds=60, clock=clock.now
    )
    assert granted.lease is not None
    report = usage(store, "alice")
    assert len(report.accelerators) == 1
    h200 = report.accelerators[0]
    assert (h200.accelerator, h200.account_limit, h200.valid_leases, h200.stale_leases) == (
        "h200",
        2,
        1,
        0,
    )
    shares = {share.node_id: (share.held, share.limit) for share in h200.nodes}
    assert shares == {"a": (1, 1), "b": (0, 1), "c": (0, 0)}


def test_usage_keeps_the_untyped_valid_count_apart(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    acquire_typed(
        store, "alice", "h200", node_id="a", node_limit=1, interval_seconds=60, clock=clock.now
    )
    assert usage(store, "alice").valid_leases == 0


def test_check_flags_typed_leases_above_the_account_quota(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    for node in ("a", "b"):
        acquire_typed(
            store, "alice", "h200", node_id=node, node_limit=1, interval_seconds=60, clock=clock.now
        )
    assert _status(run_check(store, read_only=True), "lease.over_account") == OK
    set_share_queue(store, "alice", {"h200": 1}, node_id="a", clock=clock.now)
    assert _status(run_check(store, read_only=True), "lease.over_account") == WARN


def test_check_reports_no_unreadable_share_queue_fields_when_all_are_valid(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    assert _status(run_check(store, read_only=True), "share_queue.unreadable") == OK


def test_check_flags_a_share_queue_field_that_cannot_be_read(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    raw = json.loads(store.read_text(layout.node_path("c")))
    raw["share_queue_limits"] = {"h200": -1}
    store.write_text(layout.node_path("c"), json.dumps(raw))
    assert _status(run_check(store, read_only=True), "share_queue.unreadable") == WARN
    assert _status(run_check(store, read_only=True), "record.unreadable") == WARN


def test_a_check_result_is_never_a_failure_for_share_queue_fields(
    store: MemoryFolderStore, clock: ManualClock
) -> None:
    _three_nodes(store, clock)
    results = run_check(store, read_only=True)
    assert all(result.status != FAIL for result in results if result.code.startswith("share_queue"))
