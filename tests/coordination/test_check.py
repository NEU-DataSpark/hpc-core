"""Self-check: a healthy folder is all ok, and each code is reported for the fault that seeds it."""

from __future__ import annotations

from pathlib import Path

import pytest

from hpc_core.coordination import layout
from hpc_core.coordination.check import FAIL, OK, WARN, CheckResult, run_check
from hpc_core.coordination.command_store import CommandFolderStore
from hpc_core.coordination.limits import acquire, set_limit
from hpc_core.coordination.records import LeaseRecord, encode
from hpc_core.coordination.registry import NodeIdentity, NodeSession, init_layout
from hpc_core.coordination.store import Listing, StoreError
from hpc_core.testing import ManualClock, MemoryFolderStore
from hpc_core.testing.fault_store import FaultyFolderStore
from hpc_core.testing.subprocess_transport import SubprocessTransport, missing_gnu_feature


def _healthy(clock: ManualClock | None = None) -> tuple[MemoryFolderStore, ManualClock]:
    clock = clock or ManualClock()
    store = MemoryFolderStore(clock=clock)
    init_layout(store, "team")
    session = NodeSession(
        store,
        NodeIdentity(
            "alice-console-a1", "alice", "console", interval_seconds=60, concurrency_limit=2
        ),
        clock=clock.now,
    )
    session.register()
    return store, clock


def _by_code(results: list[CheckResult]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for result in results:
        grouped.setdefault(result.code, []).append(result.status)
    return grouped


def _has(results: list[CheckResult], code: str, status: str) -> bool:
    return any(r.code == code and r.status == status for r in results)


def _text(store: MemoryFolderStore, path: str) -> str:
    return store.read_text(path)


def test_a_healthy_folder_gives_all_ok_and_leaves_no_probe_file() -> None:
    store, _ = _healthy()
    results = run_check(store)
    assert results and all(r.status == OK for r in results)
    names = [entry.name for entry in store.list_dir(layout.CLUSTER_FOLDER, hidden=True).entries]
    assert not [name for name in names if name.startswith(layout.PROBE_PREFIX)]


def test_read_only_skips_the_probe_and_writes_nothing() -> None:
    store, _ = _healthy()
    results = run_check(store, read_only=True)
    assert all(not r.code.startswith("probe.") for r in results)
    assert all(r.status == OK for r in results)


def test_a_missing_manifest_is_a_failure() -> None:
    results = run_check(MemoryFolderStore(), read_only=True)
    assert _has(results, "layout.manifest", FAIL)


def test_an_unsupported_manifest_version_is_a_failure() -> None:
    store, _ = _healthy()
    text = _text(store, layout.manifest_path())
    store.write_text(
        layout.manifest_path(), text.replace('"schema_version":1', '"schema_version":99', 1)
    )
    assert _has(run_check(store, read_only=True), "manifest.version", FAIL)


def test_a_missing_sub_folder_is_a_failure() -> None:
    store, _ = _healthy()
    store.remove_tree(layout.subfolder_path("profiles"))
    assert _has(run_check(store, read_only=True), "layout.folders", FAIL)


def test_an_unreadable_record_is_a_warning() -> None:
    store, _ = _healthy()
    store.write_text(layout.node_path("bob-console-b2"), "{not json\n")
    assert _has(run_check(store, read_only=True), "record.unreadable", WARN)


def test_a_record_whose_id_differs_from_its_file_name_is_a_warning() -> None:
    store, _ = _healthy()
    store.write_text(
        layout.node_path("bob-console-b2"), _text(store, layout.node_path("alice-console-a1"))
    )
    assert _has(run_check(store, read_only=True), "record.name_mismatch", WARN)


def test_a_record_with_an_unsupported_version_is_a_warning() -> None:
    store, _ = _healthy()
    path = layout.node_path("alice-console-a1")
    store.write_text(
        path, _text(store, path).replace('"schema_version":1', '"schema_version":99', 1)
    )
    assert _has(run_check(store, read_only=True), "record.version", WARN)


def test_more_leases_than_the_limit_is_a_warning() -> None:
    store, clock = _healthy()
    set_limit(store, "alice", 1, node_id="alice-console-a1", clock=clock.now)
    store.make_dirs(layout.lease_dir("alice"))
    for slot in (1, 2):
        record = LeaseRecord(1, "alice", slot, "alice-console-a1", "2027-01-01T00:00:00Z", 60)
        store.write_text(layout.lease_path("alice", slot), encode(record))
    assert _has(run_check(store, read_only=True), "lease.over_limit", WARN)


def test_a_stale_lease_is_a_warning() -> None:
    store, clock = _healthy()
    acquire(store, "alice", node_id="alice-console-a1", interval_seconds=60, clock=clock.now)
    clock.advance(10 * 60)
    assert _has(run_check(store, read_only=True), "lease.stale", WARN)


def test_a_profile_with_no_node_is_a_warning() -> None:
    store, clock = _healthy()
    set_limit(store, "bob", 1, node_id="alice-console-a1", clock=clock.now)
    assert _has(run_check(store, read_only=True), "profile.no_nodes", WARN)


def test_an_old_temporary_file_is_a_warning() -> None:
    store, clock = _healthy()
    store.write_text(f"{layout.subfolder_path('nodes')}/{layout.TEMP_PREFIX}abc.json", "partial")
    clock.advance(11 * 60)
    assert _has(run_check(store, read_only=True), "temp.stale", WARN)


def test_a_store_that_fails_is_reported_as_unreachable_with_no_path() -> None:
    store, _ = _healthy()
    faulty = FaultyFolderStore(inner=store, failures=[StoreError("transport", kind="unreachable")])
    results = run_check(faulty)
    unreachable = [r for r in results if r.code == "store.unreachable"]
    assert [r.status for r in unreachable] == [FAIL]
    assert "_cluster" not in unreachable[0].hint


def test_a_folder_that_refuses_hard_links_fails_the_probe_clearly() -> None:
    store, _ = _healthy()
    faulty = FaultyFolderStore(inner=store, refuse_hard_links=True)
    results = run_check(faulty)
    assert _has(results, "probe.hardlink", FAIL)
    hint = next(r.hint for r in results if r.code == "probe.hardlink" and r.status == FAIL)
    assert "hard links" in hint


def test_a_listing_delay_is_reported_with_its_size() -> None:
    store, _ = _healthy()
    results = run_check(FaultyFolderStore(inner=store, visibility_lag=60.0))
    delay = next(r for r in results if r.code == "probe.listing_delay")
    assert delay.status == WARN and "60 s" in delay.hint


class _RenameLies(MemoryFolderStore):
    def read_text(self, path: str) -> str:
        if layout.PROBE_PREFIX in path:
            return "garbage\n"
        return super().read_text(path)


class _ExclusiveLies(MemoryFolderStore):
    def create_exclusive(self, path: str, text: str) -> None:
        if "-link" in path:
            self.write_text(path, text)
            return
        super().create_exclusive(path, text)


class _ProbeHidden(MemoryFolderStore):
    def list_dir(self, path: str, *, hidden: bool = False) -> Listing:
        listing = super().list_dir(path, hidden=hidden)
        kept = tuple(e for e in listing.entries if layout.PROBE_PREFIX not in e.name)
        return Listing(kept, listing.now)


class _ProbeStuck(MemoryFolderStore):
    def remove(self, path: str) -> None:
        if layout.PROBE_PREFIX in path:
            raise StoreError("could not remove", kind="io")
        super().remove(path)


def _lying(cls: type[MemoryFolderStore]) -> MemoryFolderStore:
    clock = ManualClock()
    store = cls(clock=clock)
    init_layout(store, "team")
    return store


def test_a_probe_that_reads_back_wrong_text_fails_the_rename_check() -> None:
    store = _lying(_RenameLies)
    assert _has(run_check(store), "probe.rename", FAIL)


def test_an_exclusive_create_that_overwrites_fails_the_exclusive_check() -> None:
    store = _lying(_ExclusiveLies)
    assert _has(run_check(store), "probe.exclusive", FAIL)


def test_a_probe_file_that_is_not_listed_fails_the_listing_check() -> None:
    store = _lying(_ProbeHidden)
    assert _has(run_check(store), "probe.listing", FAIL)


def test_a_probe_file_that_cannot_be_removed_is_a_warning() -> None:
    store = _lying(_ProbeStuck)
    assert _has(run_check(store), "probe.cleanup", WARN)


def test_the_probe_says_file_times_are_whole_seconds_on_a_whole_second_clock() -> None:
    store, _ = _healthy()
    hint = next(r.hint for r in run_check(store) if r.code == "probe.file_time")
    assert "whole-second" in hint


def test_the_real_command_transport_reports_the_refused_hard_link_and_the_injected_delay(
    tmp_path: Path,
) -> None:
    reason = missing_gnu_feature()
    if reason:
        pytest.skip(f"needs GNU coreutils: {reason}")
    team = tmp_path / "team"
    team.mkdir()
    command = CommandFolderStore(SubprocessTransport(team), str(team))
    init_layout(command, "team")
    healthy = _by_code(run_check(command))
    assert healthy["probe.hardlink"] == [OK] and healthy["probe.exclusive"] == [OK]
    refused = _by_code(run_check(FaultyFolderStore(inner=command, refuse_hard_links=True)))
    assert FAIL in refused["probe.hardlink"]
    delayed = _by_code(run_check(FaultyFolderStore(inner=command, visibility_lag=60.0)))
    assert WARN in delayed["probe.listing_delay"]
