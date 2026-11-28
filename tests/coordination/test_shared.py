"""Shared datasets: election from discovery, the due check, publish and read, on three stores.

The election and due tests run on the memory store and on the command store over the simulated
folder, both with one manual clock. The file-time tests run on a real folder, where a file's time
is the real time of its write and is moved with ``os.utime``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import events, layout
from hpc_core.coordination.command_store import CommandFolderStore
from hpc_core.coordination.records import REASON_NOT_JSON, REASON_VERSION, Unreadable
from hpc_core.coordination.registry import (
    OUTCOME_REGISTERED,
    Discovery,
    NodeIdentity,
    NodeSession,
    discover,
    init_layout,
)
from hpc_core.coordination.shared import (
    SharedCopy,
    SharedMissing,
    elect_collector,
    publish_shared,
    read_shared,
    shared_ages,
    should_collect,
)
from hpc_core.coordination.store import FolderStore, LocalFolderStore, StoreError
from hpc_core.testing import ManualClock, MemoryFolderStore, SimulatedFolderTransport
from hpc_core.testing.fault_store import FaultyFolderStore

ROOT = "/team"
INTERVAL = 60
PAYLOAD = {"partitions": [{"name": "cpu", "pending": 3}], "running": 7}


def _memory() -> tuple[FolderStore, ManualClock]:
    clock = ManualClock()
    folder = MemoryFolderStore(clock=clock)
    init_layout(folder, "team")
    return folder, clock


def _command() -> tuple[FolderStore, ManualClock]:
    clock = ManualClock()
    folder = MemoryFolderStore(clock=clock)
    store = CommandFolderStore(SimulatedFolderTransport(folder, ROOT), ROOT)
    init_layout(store, "team")
    return store, clock


@pytest.fixture(params=[_memory, _command], ids=["memory", "command"])
def world(request: pytest.FixtureRequest) -> tuple[FolderStore, ManualClock]:
    factory: Callable[[], tuple[FolderStore, ManualClock]] = request.param
    return factory()


def _join(
    store: FolderStore, clock: ManualClock, node: str, *, candidate: bool = True
) -> NodeSession:
    identity = NodeIdentity(
        node,
        node.split("-", 1)[0],
        "console",
        interval_seconds=INTERVAL,
        shared_collector=candidate,
    )
    session = NodeSession(store, identity, clock=clock.now)
    assert session.register().outcome == OUTCOME_REGISTERED
    return session


def _only(discovery: Discovery, node: str) -> Discovery:
    """The discovery as seen by one node that sees only itself."""
    return replace(discovery, nodes=tuple(v for v in discovery.nodes if v.record.node_id == node))


# -- election ----------------------------------------------------------------------------------


def test_the_smallest_online_candidate_wins(world: tuple[FolderStore, ManualClock]) -> None:
    store, clock = world
    _join(store, clock, "bob-console-c3")
    _join(store, clock, "alice-console-b2")
    _join(store, clock, "alice-console-a1")
    assert elect_collector(discover(store)) == "alice-console-a1"


def test_a_non_candidate_with_a_smaller_id_is_skipped(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    _join(store, clock, "alice-skill-a1", candidate=False)
    _join(store, clock, "alice-console-b2")
    assert elect_collector(discover(store)) == "alice-console-b2"


def test_a_stale_candidate_is_skipped_and_hands_over_and_back(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    first = _join(store, clock, "alice-console-a1")
    second = _join(store, clock, "alice-console-b2")
    assert elect_collector(discover(store)) == "alice-console-a1"
    clock.advance(200)  # more than three intervals of 60 seconds: a1 is stale
    second.beat()
    assert elect_collector(discover(store)) == "alice-console-b2"
    first.beat()  # a1 registers again and is online
    assert elect_collector(discover(store)) == "alice-console-a1"


def test_no_online_candidate_means_no_collector(world: tuple[FolderStore, ManualClock]) -> None:
    store, clock = world
    _join(store, clock, "alice-console-a1")
    _join(store, clock, "bob-skill-b1", candidate=False)
    clock.advance(10 * INTERVAL)  # every record is stale or offline by now
    assert elect_collector(discover(store)) is None


def test_a_fresh_file_stops_a_second_collector(world: tuple[FolderStore, ManualClock]) -> None:
    store, clock = world
    _join(store, clock, "alice-console-a1")
    b = _join(store, clock, "alice-console-b2")
    discovery = discover(store)
    # a1 publishes; b2, believing it is the collector in its own view, finds the file fresh.
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discovery)
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    clock.advance(5)
    b.beat()
    own_view = _only(discover(store), "alice-console-b2")
    assert elect_collector(own_view) == "alice-console-b2"
    assert should_collect(store, "queue", "alice-console-b2", INTERVAL, own_view) is False


def test_a_collector_collects_again_only_when_the_file_is_older_than_the_interval(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    session = _join(store, clock, "alice-console-a1")
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    clock.advance(INTERVAL)
    session.beat()
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discover(store)) is False
    clock.advance(1)
    session.beat()
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discover(store)) is True


def test_a_missing_or_unreadable_file_is_due_for_the_collector(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    _join(store, clock, "alice-console-a1")
    discovery = discover(store)
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discovery) is True
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    store.write_text(layout.shared_path("queue"), "{not json")
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discovery) is True


def test_a_node_that_is_not_the_collector_never_collects(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    _join(store, clock, "alice-console-a1")
    _join(store, clock, "bob-console-b1")
    discovery = discover(store)
    assert should_collect(store, "queue", "bob-console-b1", INTERVAL, discovery) is False
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discovery) is True


def test_an_unsafe_dataset_is_refused_before_any_store_call() -> None:
    refusing = FaultyFolderStore(MemoryFolderStore(), failures=[RuntimeError("store called")])
    discovery = Discovery((), 0, 0.0)
    with pytest.raises(ValidationError, match="must be 1 to 32"):
        read_shared(refusing, "../x")
    with pytest.raises(ValidationError, match="must be 1 to 32"):
        publish_shared(refusing, "Queue", node_id="alice-console-a1", payload=PAYLOAD)
    with pytest.raises(ValidationError, match="must be 1 to 32"):
        should_collect(refusing, "", "alice-console-a1", INTERVAL, discovery)
    assert len(refusing.failures) == 1


# -- publish and read ----------------------------------------------------------------------------


def test_publish_creates_the_shared_folder_on_first_use(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, _clock = world
    assert "shared" not in store.list_subdirs("_cluster")
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    assert "shared" in store.list_subdirs("_cluster")
    assert store.list_dir("_cluster/shared").entries[0].name == "queue.txt"


def test_read_returns_the_payload_age_and_collector(world: tuple[FolderStore, ManualClock]) -> None:
    store, clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    clock.advance(20)
    result = read_shared(store, "queue")
    assert result == SharedCopy("queue", PAYLOAD, 20.0, "alice-console-a1")


def test_a_wrong_reader_clock_does_not_change_the_age(
    world: tuple[FolderStore, ManualClock],
) -> None:
    # read_shared takes no clock. Its age comes from the folder's clock and the file's time only,
    # so a reader whose own clock is ten minutes ahead gets the same answer as any other reader.
    store, clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    reader_clock = ManualClock(current=clock.now() + 600)
    clock.advance(20)
    result = read_shared(store, "queue")
    assert isinstance(result, SharedCopy)
    assert result.age_seconds == 20.0
    assert reader_clock.now() - clock.now() == 580


def test_a_missing_dataset_is_missing_with_no_age(world: tuple[FolderStore, ManualClock]) -> None:
    store, _clock = world
    assert read_shared(store, "queue") == SharedMissing("queue")


def test_a_writer_stopping_before_the_rename_leaves_the_old_file(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, _clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    store.write_text(f"{layout.shared_dir()}/.tmp-partial", '{"schema_version": 1, "datas')
    result = read_shared(store, "queue")
    assert isinstance(result, SharedCopy) and result.payload == PAYLOAD


def test_a_corrupt_or_unknown_version_file_is_unreadable_not_missing(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, _clock = world
    store.make_dirs(layout.shared_dir())
    store.write_text(layout.shared_path("queue"), "not json at all")
    corrupt = read_shared(store, "queue")
    assert isinstance(corrupt, Unreadable) and corrupt.reason == REASON_NOT_JSON
    store.write_text(
        layout.shared_path("queue"),
        '{"schema_version": 9, "dataset": "queue", "collector_node_id": "a1", "payload": {}}\n',
    )
    unknown = read_shared(store, "queue")
    assert isinstance(unknown, Unreadable) and unknown.reason == REASON_VERSION


def test_an_oversized_payload_is_refused_and_the_previous_file_stays(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, _clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    too_big = {"blob": "x" * (2 * 1024 * 1024)}
    with pytest.raises(ValidationError, match="1024 KiB limit"):
        publish_shared(store, "queue", node_id="alice-console-a1", payload=too_big)
    result = read_shared(store, "queue")
    assert isinstance(result, SharedCopy) and result.payload == PAYLOAD


def test_an_unreachable_folder_raises_a_store_error_not_a_missing_file(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, _clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    broken = FaultyFolderStore(
        store, failures=[StoreError("the login node is unreachable", kind="unreachable")]
    )
    with pytest.raises(StoreError) as caught:
        read_shared(broken, "queue")
    assert caught.value.kind == "unreachable"


def test_shared_ages_lists_each_existing_file_without_reading_it(
    world: tuple[FolderStore, ManualClock],
) -> None:
    store, clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    clock.advance(30)
    assert shared_ages(store) == {"queue": 30.0}


def test_publish_and_read_emit_events_with_ids_and_counts_only(
    world: tuple[FolderStore, ManualClock], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=events.LOGGER_NAME)
    store, _clock = world
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    names = [getattr(record, "hpc_event", "") for record in caplog.records]
    assert "shared.published" in names
    published = next(r for r in caplog.records if getattr(r, "hpc_event", "") == "shared.published")
    fields: dict[str, object] = getattr(published, "hpc_fields", {})
    assert fields["dataset"] == "queue"
    assert isinstance(fields["size"], int)


# -- the real folder: whole-file replacement and file times -------------------------------------


def test_two_writers_leave_one_whole_document(tmp_path: Path) -> None:
    store = LocalFolderStore(tmp_path)
    init_layout(store, "team")
    payloads = [{"writer": "a", "n": n, "pad": "a" * 2000} for n in range(40)]
    payloads += [{"writer": "b", "n": n, "pad": "b" * 2000} for n in range(40)]

    def write(batch: list[dict[str, object]], node: str) -> None:
        for payload in batch:
            publish_shared(store, "queue", node_id=node, payload=payload)

    threads = [
        threading.Thread(target=write, args=(payloads[:40], "alice-console-a1")),
        threading.Thread(target=write, args=(payloads[40:], "bob-console-b1")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    result = read_shared(store, "queue")
    assert isinstance(result, SharedCopy)
    assert result.payload in payloads
    assert result.collector_node_id in {"alice-console-a1", "bob-console-b1"}


def test_the_real_folder_ages_a_file_by_its_own_time(tmp_path: Path) -> None:
    store = LocalFolderStore(tmp_path)
    init_layout(store, "team")
    session = NodeSession(
        store,
        NodeIdentity("alice-console-a1", "alice", "console", shared_collector=True),
    )
    assert session.register().outcome == OUTCOME_REGISTERED
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    path = tmp_path / layout.shared_path("queue")
    moment = time.time() - 120
    os.utime(path, (moment, moment))
    result = read_shared(store, "queue")
    assert isinstance(result, SharedCopy)
    assert 115 <= result.age_seconds <= 130
    # The collector is elected from the real records, and the file is 120 s old: due.
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discover(store)) is True
    publish_shared(store, "queue", node_id="alice-console-a1", payload=PAYLOAD)
    assert should_collect(store, "queue", "alice-console-a1", INTERVAL, discover(store)) is False
