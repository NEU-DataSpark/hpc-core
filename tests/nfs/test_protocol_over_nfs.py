"""The protocol across two NFS mounts of one export: writes through A, reads through B.

Mount B caches attributes for 60 seconds, so a test that waits for B to see a change allows up to
90 seconds. Every test works in its own folder under the export and removes it afterwards.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.check import OK, WARN, run_check
from hpc_core.coordination.limits import acquire, set_limit, usage
from hpc_core.coordination.records import NodeRecord, Unreadable, decode_node, encode
from hpc_core.coordination.registry import NodeIdentity, NodeSession, discover, init_layout
from hpc_core.coordination.store import Exists, LocalFolderStore, NotFound

pytestmark = pytest.mark.nfs

VISIBLE_WITHIN_SECONDS = 90
NODE = "alice-console-a1"


def _wait_for(read: Any, timeout: float = VISIBLE_WITHIN_SECONDS) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(2)


@pytest.fixture(scope="session")
def mounts() -> tuple[Path, Path]:
    """Mount A (no client caching) and mount B (60 s attribute cache) of the testbed export."""
    first = os.environ.get("NFS_TESTBED_A", "")
    second = os.environ.get("NFS_TESTBED_B", "")
    if not first or not second:
        pytest.skip("NFS testbed not up: run tools/nfs-testbed/run.sh up, then run.sh test")
    for path in (first, second):
        if not os.path.ismount(path):
            pytest.skip("NFS testbed not mounted: run tools/nfs-testbed/run.sh up first")
    return Path(first), Path(second)


@dataclass(frozen=True)
class Team:
    """One team folder: its path under each mount, and a store over each."""

    root_a: Path
    root_b: Path
    store_a: LocalFolderStore
    store_b: LocalFolderStore


@pytest.fixture
def team(mounts: tuple[Path, Path]) -> Iterator[Team]:
    first, second = mounts
    name = f"hpc-core-test-{uuid.uuid4().hex[:8]}"
    root_a, root_b = first / name, second / name
    root_a.mkdir()
    try:
        yield Team(
            root_a,
            root_b,
            LocalFolderStore(root_a, clock=time.time),
            LocalFolderStore(root_b, clock=time.time),
        )
    finally:
        shutil.rmtree(root_a, ignore_errors=True)


def _node(count: int) -> NodeRecord:
    return NodeRecord(
        1,
        NODE,
        "alice",
        "console",
        "Alice console",
        "lab-host-1",
        "0.3.0",
        "2027-01-01T00:00:00Z",
        30,
        count,
        "0123456789abcdef",
    )


def test_a_beat_written_through_a_shows_through_b_as_online(team: Team) -> None:
    store_a, store_b = team.store_a, team.store_b
    init_layout(store_a, "team")
    NodeSession(
        store_a, NodeIdentity(NODE, "alice", "console", interval_seconds=30), clock=time.time
    ).register()
    found = _wait_for(lambda: [v for v in discover(store_b).nodes if v.record.node_id == NODE])
    assert found, "the beat did not show through mount B within 90 seconds"
    assert found[0].state == "online"


def _attempt_create(
    store: LocalFolderStore, path: str, barrier: threading.Barrier, outcomes: list[str]
) -> None:
    barrier.wait()
    try:
        store.create_exclusive(path, "x\n")
        outcomes.append("won")
    except Exists:
        outcomes.append("exists")


def test_exclusive_create_through_a_and_b_has_one_winner(team: Team) -> None:
    init_layout(team.store_a, "team")
    for round_number in range(20):
        path = f"{layout.subfolder_path('inbox')}/race-{round_number:02d}.json"
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        threads = [
            threading.Thread(target=_attempt_create, args=(store, path, barrier, outcomes))
            for store in (team.store_a, team.store_b)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["exists", "won"], f"round {round_number}: {outcomes}"


def _lease_worker(job: tuple[str, str]) -> str:
    root, node = job
    store = LocalFolderStore(Path(root), clock=time.time)
    return acquire(store, "alice", node_id=node, interval_seconds=30, clock=time.time).outcome


def test_lease_races_through_a_and_b_end_at_or_below_the_limit(team: Team) -> None:
    init_layout(team.store_a, "team")
    set_limit(team.store_a, "alice", 2, node_id=NODE, clock=time.time)
    jobs = [
        (str(team.root_a if i % 2 == 0 else team.root_b), f"alice-console-n{i:02d}")
        for i in range(8)
    ]
    context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        list(pool.map(_lease_worker, jobs))
    assert usage(team.store_a, "alice").valid_leases <= 2


def test_a_renamed_record_is_never_read_half_done_through_b(team: Team) -> None:
    store_a, store_b = team.store_a, team.store_b
    init_layout(store_a, "team")
    path = layout.node_path(NODE)
    deadline = time.monotonic() + 5
    count = 0
    seen = 0
    while time.monotonic() < deadline:
        count += 1
        store_a.write_text(path, encode(_node(count)))
        try:
            text = store_b.read_text(path)
        except NotFound:
            continue
        seen += 1
        decoded = decode_node(text, NODE)
        assert not isinstance(decoded, Unreadable), f"a half-written record was read: {decoded}"
    assert seen > 0


def test_hard_link_create_works_through_a(team: Team) -> None:
    init_layout(team.store_a, "team")
    results = {r.code: r.status for r in run_check(team.store_a)}
    assert results["probe.hardlink"] == OK
    assert results["probe.exclusive"] == OK


def test_the_self_check_through_b_reports_the_listing_delay(team: Team) -> None:
    init_layout(team.store_a, "team")
    delay = {r.code: r for r in run_check(team.store_b)}.get("probe.listing_delay")
    assert delay is not None, "the probe through B did not measure the listing delay"
    assert delay.status in (OK, WARN)
