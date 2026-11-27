"""The self-check of a team folder: layout, records, leases, profiles, temporary files and a probe.

``run_check`` returns results, each ``ok``, ``warn`` or ``fail`` with a stable code and a one-line
hint. It reads the folder through any store. The probe writes two ``.probe-*`` files under
``_cluster``, tests the atomic rename, the hard-link exclusive create and the listing with its file
time, and removes them again. ``read_only`` skips the probe and writes nothing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import layout
from .limits import read_profile
from .records import (
    REASON_NAME,
    REASON_VERSION,
    Unreadable,
    decode_lease,
    decode_manifest,
    decode_message,
    decode_node,
)
from .registry import ONLINE, classify, discover
from .store import Exists, FolderStore, NotFound, StoreError

OK = "ok"
WARN = "warn"
FAIL = "fail"
PROBE_LAG_WARN_SECONDS = 10.0
_JSON = ".json"


@dataclass(frozen=True)
class CheckResult:
    code: str
    status: str
    hint: str


def _ok(code: str, hint: str) -> CheckResult:
    return CheckResult(code, OK, hint)


def _count(code: str, count: int, problem: str, clean_hint: str) -> CheckResult:
    if count == 0:
        return CheckResult(code, OK, clean_hint)
    return CheckResult(code, WARN, f"{count} {problem}; readers skip them and count them")


def run_check(store: FolderStore, *, read_only: bool = False) -> list[CheckResult]:
    """Inspect the team folder and return the results in a stable order."""
    results: list[CheckResult] = []
    try:
        results.extend(_layout(store))
        results.extend(_records(store))
        results.extend(_leases_and_profiles(store))
        results.extend(_temporary_files(store))
        if not read_only:
            results.extend(_probe(store))
    except StoreError as error:
        results.append(
            CheckResult(
                "store.unreachable",
                FAIL,
                f"the shared folder could not be read ({error.kind}); check the path and the "
                "connection",
            )
        )
    return results


def _layout(store: FolderStore) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        manifest = decode_manifest(store.read_text(layout.manifest_path()))
    except NotFound:
        return [CheckResult("layout.manifest", FAIL, "no cluster.json; run cluster init first")]
    if not isinstance(manifest, Unreadable):
        results.append(_ok("layout.manifest", "cluster.json is present and readable"))
    elif manifest.reason == REASON_VERSION:
        results.append(
            CheckResult("manifest.version", FAIL, "the manifest is from an unsupported version")
        )
    else:
        results.append(
            CheckResult("layout.manifest", FAIL, "cluster.json is unreadable; restore it")
        )
    present = set(_subfolders(store, layout.CLUSTER_FOLDER))
    if all(name in present for name in layout.SUBFOLDERS):
        results.append(_ok("layout.folders", "nodes, profiles, leases and inbox exist"))
    else:
        results.append(
            CheckResult("layout.folders", FAIL, "a sub-folder is missing; run cluster init")
        )
    return results


def _subfolders(store: FolderStore, path: str) -> tuple[str, ...]:
    try:
        return store.list_subdirs(path)
    except NotFound:
        return ()


def _records(store: FolderStore) -> list[CheckResult]:
    unreadable = 0
    mismatched = 0
    version = 0
    nodes_dir = layout.subfolder_path("nodes")
    try:
        listing = store.list_dir(nodes_dir)
        texts = store.read_all(nodes_dir)
    except NotFound:
        listing = None
        texts = {}
    for entry in listing.entries if listing else ():
        stem = entry.name[: -len(_JSON)] if entry.name.endswith(_JSON) else None
        record = decode_node(texts.get(entry.name, ""), expected_id=stem)
        if not isinstance(record, Unreadable):
            continue
        if record.reason == REASON_NAME:
            mismatched += 1
        elif record.reason == REASON_VERSION:
            version += 1
        else:
            unreadable += 1
    messages = _unreadable_messages(store)
    return [
        _count(
            "record.unreadable",
            unreadable + messages,
            "records are unreadable",
            "every record is readable",
        ),
        _count(
            "record.name_mismatch",
            mismatched,
            "records whose id differs from the file name",
            "every record id matches its file name",
        ),
        _count(
            "record.version",
            version,
            "records use an unsupported version",
            "every record uses a supported version",
        ),
    ]


def _unreadable_messages(store: FolderStore) -> int:
    count = 0
    for name in _subfolders(store, layout.subfolder_path("inbox")):
        folder = layout.inbox_dir(name)
        try:
            texts = store.read_all(folder)
        except NotFound:
            continue
        for file_name, text in texts.items():
            if not file_name.endswith(_JSON):
                continue
            stem = file_name[: -len(_JSON)]
            if isinstance(decode_message(text, expected_id=stem), Unreadable):
                count += 1
    return count


def _leases_and_profiles(store: FolderStore) -> list[CheckResult]:
    profiles_dir = layout.subfolder_path("profiles")
    try:
        profile_files = store.list_dir(profiles_dir).entries
    except NotFound:
        profile_files = ()
    nodes = discover(store).nodes
    over_limit = 0
    stale = 0
    without_nodes = 0
    for entry in profile_files:
        if not entry.name.endswith(_JSON):
            continue
        profile_id = entry.name[: -len(_JSON)]
        try:
            layout.validate_id(profile_id)
            profile = read_profile(store, profile_id)
        except (NotFound, ValueError):
            continue
        if isinstance(profile, Unreadable):
            continue
        valid, stale_here = _lease_counts(store, profile_id)
        over_limit += valid > profile.concurrency_limit
        stale += stale_here > 0
        without_nodes += not any(view.record.profile_id == profile_id for view in nodes)
    return [
        _count(
            "lease.over_limit",
            over_limit,
            "profiles hold more leases than their limit",
            "no profile holds more leases than its limit",
        ),
        _count("lease.stale", stale, "profiles hold stale leases", "no profile holds stale leases"),
        _count(
            "profile.no_nodes",
            without_nodes,
            "profiles have no node record",
            "every profile has at least one node record",
        ),
    ]


def _lease_counts(store: FolderStore, profile_id: str) -> tuple[int, int]:
    folder = layout.lease_dir(profile_id)
    try:
        listing = store.list_dir(folder)
        texts = store.read_all(folder)
    except NotFound:
        return 0, 0
    valid = 0
    stale = 0
    for entry in listing.entries:
        record = decode_lease(texts.get(entry.name, ""))
        if isinstance(record, Unreadable):
            continue
        if classify(listing.now - entry.modified, record.interval_seconds) == ONLINE:
            valid += 1
        else:
            stale += 1
    return valid, stale


def _temporary_files(store: FolderStore) -> list[CheckResult]:
    folders = [layout.subfolder_path("nodes"), layout.subfolder_path("profiles")]
    folders += [
        f"{layout.subfolder_path('leases')}/{name}"
        for name in _subfolders(store, layout.subfolder_path("leases"))
    ]
    folders += [
        layout.inbox_dir(name) for name in _subfolders(store, layout.subfolder_path("inbox"))
    ]
    old = 0
    now = store.now()
    for folder in folders:
        try:
            listing = store.list_dir(folder, hidden=True)
        except NotFound:
            continue
        old += sum(
            1
            for entry in listing.entries
            if entry.name.startswith(layout.TEMP_PREFIX)
            and now - entry.modified > layout.TEMP_STALE_SECONDS
        )
    return [
        _count(
            "temp.stale", old, "temporary files are older than 10 minutes", "no old temporary files"
        )
    ]


def _probe(store: FolderStore) -> list[CheckResult]:
    probe_id = secrets.token_hex(6)
    path = layout.probe_path(probe_id)
    link = layout.probe_path(f"{probe_id}-link")
    results: list[CheckResult] = []
    try:
        before = store.now()
        store.write_text(path, "probe\n")
        results.append(_rename_result(store, path))
        results.extend(_link_results(store, link))
        results.extend(_listing_results(store, path, before))
    except NotFound:
        results.append(CheckResult("probe.listing", FAIL, "the probe folder is missing"))
    finally:
        for item in (path, link):
            try:
                store.remove(item)
            except StoreError:
                results.append(CheckResult("probe.cleanup", WARN, "a probe file was not removed"))
    return results


def _rename_result(store: FolderStore, path: str) -> CheckResult:
    try:
        text = store.read_text(path)
    except NotFound:
        return CheckResult("probe.rename", FAIL, "a file written by rename is not readable")
    if text != "probe\n":
        return CheckResult("probe.rename", FAIL, "a file written by rename has the wrong text")
    return _ok("probe.rename", "atomic rename works")


def _link_results(store: FolderStore, link: str) -> list[CheckResult]:
    try:
        store.create_exclusive(link, "probe\n")
    except Exists:
        return [CheckResult("probe.hardlink", FAIL, "a new name already exists")]
    except StoreError as error:
        hint = (
            "the folder refuses hard links; exclusive create cannot be trusted"
            if error.kind == "hard-link-refused"
            else "exclusive create failed; check the folder's permissions"
        )
        return [CheckResult("probe.hardlink", FAIL, hint)]
    results = [_ok("probe.hardlink", "exclusive create works")]
    try:
        store.create_exclusive(link, "probe\n")
    except Exists:
        results.append(_ok("probe.exclusive", "a second exclusive create is refused"))
    else:
        results.append(CheckResult("probe.exclusive", FAIL, "exclusive create overwrote a file"))
    return results


def _listing_results(store: FolderStore, path: str, before: float) -> list[CheckResult]:
    listing = store.list_dir(layout.CLUSTER_FOLDER, hidden=True)
    name = path.rsplit("/", 1)[-1]
    seen = [entry for entry in listing.entries if entry.name == name]
    if not seen:
        return [CheckResult("probe.listing", FAIL, "a new file is not listed yet; try again")]
    lag = max(before - seen[0].modified, 0.0)
    results = [
        CheckResult(
            "probe.listing_delay",
            WARN,
            f"file times lag by about {int(lag)} s; use intervals of at least three times that",
        )
        if lag > PROBE_LAG_WARN_SECONDS
        else _ok("probe.listing_delay", "file times are current"),
    ]
    whole = seen[0].modified == int(seen[0].modified)
    hint = (
        "file times have whole-second resolution; the 30 s interval floor is enough"
        if whole
        else "file times keep fractions of a second"
    )
    results.append(_ok("probe.file_time", hint))
    return results
