"""Cross-client checks on one real shared folder: each role runs as its own client process.

Opt-in (marker ``nfs``), so the default run deselects it. The cluster runner starts one process per
role, each on its own host, and the roles talk only through files: a role writes a flag when it
reaches a checkpoint and waits for the other role's flag. Nothing here orders work by the clock.

Environment (the module skips when it is not set):
  NFS_CROSS_ROLE   writer | reader    the client this process plays
  NFS_CROSS_ROOT   the run's work folder, a directory on the shared export that this client sees
  NFS_CROSS_WAIT   optional: seconds any single wait may take (default 1200)

Layout under NFS_CROSS_ROOT:
  team/                the team folder; the _cluster layout is created under it
  team/flags/          one flag file per checkpoint
  team/results/        one file per observation the runner reads back
The login-node client (a separate script outside this repository) plays the third role, ``login``,
through the same files; it is not run by this module.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.check import FAIL, run_check
from hpc_core.coordination.limits import set_share_queue
from hpc_core.coordination.records import Unreadable, decode_node
from hpc_core.coordination.registry import (
    OUTCOME_BEAT,
    OUTCOME_CONFLICT,
    OUTCOME_REGISTERED,
    NodeIdentity,
    NodeSession,
    discover,
    init_layout,
)
from hpc_core.coordination.store import Exists, LocalFolderStore, NotFound, StoreError

pytestmark = pytest.mark.nfs

ROLE = os.environ.get("NFS_CROSS_ROLE", "")
ROOT = os.environ.get("NFS_CROSS_ROOT", "")
WAIT_SECONDS = float(os.environ.get("NFS_CROSS_WAIT", "1200"))
VISIBLE_WITHIN_SECONDS = 90
ROUNDS = 20
READS_DURING_REWRITE = 300
MIN_VERSIONS_DURING_REWRITE = 20
WRITER_NODE = "alice-cross-w1"
LOGIN_NODE = "alice-cross-login"
FLAGS = "flags"
RESULTS = "results"
PROBE_CODES = ("probe.rename", "probe.hardlink", "probe.exclusive")


def _store_for(role: str) -> LocalFolderStore:
    if ROLE != role:
        pytest.skip(f"NFS_CROSS_ROLE is {ROLE or 'unset'}, not {role}: a cluster-run role")
    if not ROOT:
        pytest.skip("NFS_CROSS_ROOT is not set: cross-client checks run as cluster jobs")
    store = LocalFolderStore(Path(ROOT) / "team", clock=time.time)
    store.make_dirs(FLAGS)
    store.make_dirs(RESULTS)
    return store


def _exists(store: LocalFolderStore, path: str) -> bool:
    # A transient store error counts as "not yet": every wait below has a deadline.
    try:
        store.read_text(path)
    except (NotFound, StoreError):
        return False
    return True


def _wait_for(store: LocalFolderStore, path: str, what: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not _exists(store, path):
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} ({path}) was not set within {WAIT_SECONDS:.0f} s")
        time.sleep(2)


def _flag(store: LocalFolderStore, name: str) -> None:
    store.write_text(f"{FLAGS}/{name}", "set\n")


def _wait_flag(store: LocalFolderStore, name: str) -> None:
    _wait_for(store, f"{FLAGS}/{name}", f"flag {name}")


def _publish(store: LocalFolderStore, name: str, payload: Any) -> None:
    store.write_text(f"{RESULTS}/{name}", json.dumps(payload, sort_keys=True) + "\n")


def _read_result(store: LocalFolderStore, name: str) -> Any:
    _wait_for(store, f"{RESULTS}/{name}", f"result {name}")
    return json.loads(store.read_text(f"{RESULTS}/{name}"))


def _create_race_file(store: LocalFolderStore, name: str, who: str) -> str:
    path = f"{layout.subfolder_path('inbox')}/{name}.json"
    try:
        store.create_exclusive(path, f"{who}\n")
    except Exists:
        return "exists"
    return "won"


def _beat_until(session: NodeSession, store: LocalFolderStore, flag: str, every: float) -> int:
    beats = 0
    while not _exists(store, f"{FLAGS}/{flag}"):
        result = session.beat()
        assert result.outcome == OUTCOME_BEAT, f"a beat during the wait was {result}"
        beats += 1
        time.sleep(every)
    return beats


def _poll(what: str, read: Callable[[], Any], timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} was not seen within {timeout:.0f} s")
        time.sleep(5)


def test_writer_role() -> None:
    store = _store_for("writer")
    init_layout(store, "team")
    # The writer is the pinned node of the three-node shape: the account quota first (this creates
    # the profile if it is missing), then the node's own share of it, here 1 of 2.
    set_share_queue(store, "alice", {"h200": 2}, node_id=WRITER_NODE, clock=time.time)
    session = NodeSession(
        store,
        NodeIdentity(
            WRITER_NODE,
            "alice",
            "console",
            display_name="Cross-client writer",
            interval_seconds=30,
            node_quota={"h200": 1},
        ),
        clock=time.time,
    )
    assert session.register().outcome == OUTCOME_REGISTERED
    _flag(store, "writer-registered")
    beats_before_reader = _beat_until(session, store, "reader-saw-both", every=5)

    race: list[dict[str, str]] = []
    for round_number in range(ROUNDS):
        name = f"race-{round_number:02d}"
        _flag(store, f"{name}-writer-ready")
        _wait_flag(store, f"{name}-reader-ready")
        outcome = _create_race_file(store, name, f"writer {round_number}")
        _publish(store, f"{name}-writer", outcome)
        race.append({"round": name, "outcome": outcome})

    # Rewrite the record as fast as possible until the reader says it has read enough. Flags are
    # seen late on an attribute-cached mount, so the reader, not a timer, ends the window.
    _flag(store, "rewrite-start")
    beats_during_rewrite = 0
    failed_beats = 0
    deadline = time.monotonic() + WAIT_SECONDS
    while not _exists(store, f"{FLAGS}/rewrite-done"):
        if time.monotonic() > deadline:
            raise AssertionError("the reader never confirmed its reads during the rewrites")
        result = session.beat()
        assert result.outcome != OUTCOME_CONFLICT, f"a rewrite beat saw a conflict: {result}"
        if result.outcome == OUTCOME_BEAT:
            beats_during_rewrite += 1
        else:
            # A transient store error (for example a stale handle on the writer's own replaced
            # file) is counted and the next beat retries it, as the protocol's design requires.
            failed_beats += 1
        time.sleep(0.05)

    _wait_flag(store, "reader-finished")
    session.leave()
    _publish(
        store,
        "writer",
        {
            "node": WRITER_NODE,
            "beats_before_reader": beats_before_reader,
            "beats_during_rewrite": beats_during_rewrite,
            "failed_beats_during_rewrite": failed_beats,
            "race_rounds": len(race),
        },
    )
    _flag(store, "writer-finished")


def test_reader_role() -> None:
    store = _store_for("reader")
    _wait_flag(store, "writer-registered")
    _wait_flag(store, "login-registered")

    def both_online() -> dict[str, dict[str, Any]] | None:
        found = {view.record.node_id: view for view in discover(store).nodes}
        wanted = (WRITER_NODE, LOGIN_NODE)
        if all(node in found and found[node].state == "online" for node in wanted):
            return {
                node: {"state": found[node].state, "age_seconds": round(found[node].age_seconds, 1)}
                for node in wanted
            }
        return None

    started = time.monotonic()
    online = _poll("both nodes online", both_online, VISIBLE_WITHIN_SECONDS)
    seen_in = round(time.monotonic() - started, 1)
    records = {view.record.node_id: view.record for view in discover(store).nodes}
    writer_record = records[WRITER_NODE]
    assert writer_record.profile_source == "explicit", f"the writer's pin: {writer_record}"
    assert writer_record.share_queue_limits == {"h200": 1}, writer_record.share_queue_limits
    _flag(store, "reader-saw-both")

    outcomes: list[list[str]] = []
    for round_number in range(ROUNDS):
        name = f"race-{round_number:02d}"
        _wait_flag(store, f"{name}-writer-ready")
        _flag(store, f"{name}-reader-ready")
        reader_outcome = _create_race_file(store, name, f"reader {round_number}")
        _publish(store, f"{name}-reader", reader_outcome)
        writer_outcome = _read_result(store, f"{name}-writer")
        outcomes.append(sorted([reader_outcome, str(writer_outcome)]))
    assert all(pair == ["exists", "won"] for pair in outcomes), f"race outcomes: {outcomes}"

    _wait_flag(store, "rewrite-start")
    reads = 0
    missing = 0
    versions: set[int] = set()
    transient_errors: dict[str, int] = {}
    node_path = layout.node_path(WRITER_NODE)
    deadline = time.monotonic() + WAIT_SECONDS
    # Read until the writer has really changed the record several times: a fixed read count can
    # finish before the writer's first rewrite on a fast local folder.
    while reads < READS_DURING_REWRITE or len(versions) < MIN_VERSIONS_DURING_REWRITE:
        if time.monotonic() > deadline:
            break
        try:
            text = store.read_text(node_path)
        except NotFound:
            missing += 1
            continue
        except StoreError as error:
            # On the shared export a read can hit a stale handle while the writer replaces the
            # file (errno 116). That is transient: it must never show as a partial record.
            cause = str(error.__cause__) if error.__cause__ else str(error)
            transient_errors[cause] = transient_errors.get(cause, 0) + 1
            time.sleep(0.02)
            continue
        decoded = decode_node(text, expected_id=WRITER_NODE)
        assert not isinstance(decoded, Unreadable), f"a half-written record was read: {decoded}"
        versions.add(decoded.heartbeat_count)
        reads += 1
    _flag(store, "rewrite-done")
    assert reads >= READS_DURING_REWRITE, f"only {reads} reads during the rewrites"
    assert len(versions) >= MIN_VERSIONS_DURING_REWRITE, (
        f"the record did not change enough during the reads: versions {sorted(versions)}"
    )

    results = run_check(store)
    codes = {result.code: result for result in results}
    for code in PROBE_CODES:
        assert code in codes and codes[code].status != FAIL, f"{code}: {codes.get(code)}"
    assert "probe.listing_delay" in codes, "the probe did not measure the listing delay"
    _publish(
        store,
        "check",
        [{"code": r.code, "status": r.status, "hint": r.hint} for r in results],
    )

    _flag(store, "reader-finished")
    _wait_for(store, f"{FLAGS}/writer-finished", "the writer's finish flag")
    _publish(
        store,
        "reader",
        {
            "online": online,
            "seen_online_after_seconds": seen_in,
            "race_outcomes": outcomes,
            "rewrite_reads": reads,
            "rewrite_missing": missing,
            "rewrite_versions_seen": len(versions),
            "rewrite_transient_errors": transient_errors,
            "probe_listing_delay": codes["probe.listing_delay"].hint,
            "writer_profile_source": writer_record.profile_source,
            "writer_share_queue_limits": writer_record.share_queue_limits,
        },
    )
