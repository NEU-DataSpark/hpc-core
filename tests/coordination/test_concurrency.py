"""Layer L4: several processes against one temporary folder.

Exclusive create has one winner, the first creation of a profile record leaves one record, slot
races end at or below the limit after repair, readers never see a partial record, and message ids
stay unique. Each test uses real processes (fork), not threads, so the race is between separate
writers, as it is on the cluster.
"""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.limits import acquire, read_profile, set_limit, usage
from hpc_core.coordination.messages import pending, send
from hpc_core.coordination.records import ProfileRecord, Unreadable, decode_node
from hpc_core.coordination.registry import NodeIdentity, NodeSession, ensure_profile
from hpc_core.coordination.store import Exists, LocalFolderStore, NotFound

PROCESSES = 8
CONTEXT = multiprocessing.get_context("fork")


def _run_all(function: Callable[..., Any], arguments: list[tuple[Any, ...]]) -> list[Any]:
    with ProcessPoolExecutor(max_workers=len(arguments), mp_context=CONTEXT) as pool:
        futures: list[Future[Any]] = [pool.submit(function, *argument) for argument in arguments]
        return [future.result() for future in futures]


def _exclusive_worker(root: str, path: str, text: str) -> str:
    try:
        LocalFolderStore(Path(root)).create_exclusive(path, text)
    except Exists:
        return "exists"
    return "won"


def _profile_worker(root: str, profile_id: str, limit: int, node_id: str) -> int | str:
    result = ensure_profile(
        LocalFolderStore(Path(root)),
        profile_id,
        limit=limit,
        node_id=node_id,
        clock=time.time,
    )
    return result.concurrency_limit if not isinstance(result, Unreadable) else "unreadable"


def _acquire_worker(root: str, profile_id: str, node_id: str) -> str:
    result = acquire(LocalFolderStore(Path(root)), profile_id, node_id=node_id, interval_seconds=30)
    return result.outcome


def _send_worker(root: str, sender: str, recipient: str, count: int) -> list[str]:
    store = LocalFolderStore(Path(root))
    return [
        send(store, sender=sender, recipient=recipient, message_type="notice", body={"n": n})
        for n in range(count)
    ]


def _reader_pending_worker(root: str, recipient: str, rounds: int) -> int:
    store = LocalFolderStore(Path(root))
    skipped_total = 0
    for _ in range(rounds):
        skipped_total += pending(store, recipient).skipped
    return skipped_total


def _writer_limit_worker(root: str, profile_id: str, rounds: int) -> int:
    store = LocalFolderStore(Path(root))
    for index in range(rounds):
        set_limit(store, profile_id, 1 + index % 5, node_id="alice-console-a1")
    return rounds


def _reader_profile_worker(root: str, profile_id: str, seconds: float) -> tuple[int, int]:
    store = LocalFolderStore(Path(root))
    deadline = time.monotonic() + seconds
    reads = 0
    bad = 0
    while time.monotonic() < deadline:
        try:
            record = read_profile(store, profile_id)
        except NotFound:
            continue
        reads += 1
        if isinstance(record, Unreadable) or not 1 <= record.concurrency_limit <= 5:
            bad += 1
    return reads, bad


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "_cluster").mkdir()
    LocalFolderStore(tmp_path).make_dirs(layout.subfolder_path("leases"))
    LocalFolderStore(tmp_path).make_dirs(layout.subfolder_path("profiles"))
    LocalFolderStore(tmp_path).make_dirs(layout.subfolder_path("inbox"))
    LocalFolderStore(tmp_path).make_dirs(layout.subfolder_path("nodes"))
    return tmp_path


def test_exactly_one_process_wins_each_exclusive_create(root: Path) -> None:
    path = "_cluster/nodes/contested.json"
    outcomes = _run_all(
        _exclusive_worker, [(str(root), path, f"writer {n}\n") for n in range(PROCESSES)]
    )
    assert outcomes.count("won") == 1
    assert outcomes.count("exists") == PROCESSES - 1


def test_the_first_creation_of_a_profile_leaves_one_record_and_no_error(root: Path) -> None:
    limits = list(range(2, 2 + PROCESSES))
    values = _run_all(
        _profile_worker,
        [(str(root), "alice", limit, f"alice-node-{n}") for n, limit in enumerate(limits)],
    )
    assert all(value in limits for value in values)
    assert len(set(values)) == 1
    record = read_profile(LocalFolderStore(root), "alice")
    assert not isinstance(record, Unreadable) and record.concurrency_limit == values[0]


def test_slot_races_end_at_or_below_the_limit_after_repair(root: Path) -> None:
    store = LocalFolderStore(root)
    set_limit(store, "alice", 2, node_id="alice-console-a1")
    outcomes = _run_all(
        _acquire_worker, [(str(root), "alice", f"alice-node-{n}") for n in range(PROCESSES)]
    )
    assert outcomes.count("granted") >= 1
    assert usage(store, "alice").valid_leases <= 2


def test_a_reader_never_sees_a_partial_profile_record_while_it_is_replaced(root: Path) -> None:
    store = LocalFolderStore(root)
    set_limit(store, "alice", 1, node_id="alice-console-a1")
    writer = CONTEXT.Process(target=_writer_limit_worker, args=(str(root), "alice", 300))
    writer.start()
    try:
        reads, bad = _reader_profile_worker(str(root), "alice", 1.0)
    finally:
        writer.join(timeout=60)
    assert reads > 0
    assert bad == 0
    assert isinstance(read_profile(store, "alice"), ProfileRecord)


def test_message_ids_stay_unique_and_readers_see_no_partial_file(root: Path) -> None:
    store = LocalFolderStore(root)
    NodeSession(
        store,
        NodeIdentity(
            node_id="bob-skill-c3",
            profile_id="bob",
            kind="skill",
            machine="host-2",
            interval_seconds=60,
        ),
    ).register()
    per_sender = 15
    with ProcessPoolExecutor(max_workers=PROCESSES + 1, mp_context=CONTEXT) as pool:
        senders = [
            pool.submit(_send_worker, str(root), f"alice-node-{n}", "bob-skill-c3", per_sender)
            for n in range(PROCESSES)
        ]
        reader = pool.submit(_reader_pending_worker, str(root), "bob-skill-c3", 40)
        ids = [message for future in senders for message in future.result()]
        skipped = reader.result()
    assert len(ids) == len(set(ids)) == PROCESSES * per_sender
    assert skipped == 0
    final = pending(store, "bob-skill-c3")
    assert len(final.messages) == PROCESSES * per_sender
    assert final.skipped == 0


def test_a_node_record_read_during_a_beat_is_always_whole(root: Path) -> None:
    store = LocalFolderStore(root)
    session = NodeSession(
        store,
        NodeIdentity(
            node_id="alice-console-a1",
            profile_id="alice",
            kind="console",
            machine="host-1",
            interval_seconds=30,
        ),
    )
    session.register()
    for _ in range(50):
        session.beat()
        record = decode_node(
            store.read_text("_cluster/nodes/alice-console-a1.json"), "alice-console-a1"
        )
        assert not isinstance(record, Unreadable)
