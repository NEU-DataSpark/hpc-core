"""Profile limits and slot leases: how the nodes of one profile share one concurrency limit.

A profile record holds the limit (1 to 1024). A slot is a lease file ``slot-NN.json`` created
exclusively; a lease is renewed by its holder at each heartbeat and is stale when it has not been
renewed for 3 of the holder's intervals. Leases are advisory: they coordinate cooperating nodes,
and the scheduler stays the authority.

Taking a slot reclaims stale leases, creates the lowest free slot below the limit and, after that,
repairs an over-limit state by making the latest holder release its own lease.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import events, layout
from .records import (
    SCHEMA_VERSION,
    LeaseRecord,
    ProfileRecord,
    Unreadable,
    decode_lease,
    decode_profile,
    encode,
    time_epoch,
    time_text,
)
from .registry import ONLINE, check_interval, classify, discover
from .store import Exists, FolderStore, NotFound, StoreError

GRANTED = "granted"
NO_SLOT = "no-slot"
UNKNOWN_PROFILE = "unknown-profile"
UNREADABLE_PROFILE = "unreadable-profile"
_SLOT_NAME = re.compile(r"slot-(\d{2,4})\.json")


@dataclass(frozen=True)
class LeaseHandle:
    profile_id: str
    slot: int
    node_id: str
    acquired_at: str
    interval_seconds: int


@dataclass(frozen=True)
class SlotResult:
    outcome: str
    lease: LeaseHandle | None = None


@dataclass(frozen=True)
class ProfileUsage:
    profile_id: str
    limit: int
    valid_leases: int
    stale_leases: int
    nodes: int


@dataclass(frozen=True)
class _Item:
    name: str
    modified: float
    record: LeaseRecord | None
    slot: int | None
    valid: bool


def read_profile(store: FolderStore, profile_id: str) -> ProfileRecord | Unreadable:
    """The profile record. Raises NotFound when the profile has no record."""
    return decode_profile(store.read_text(layout.profile_path(profile_id)), profile_id)


def set_limit(
    store: FolderStore,
    profile_id: str,
    limit: int,
    *,
    node_id: str,
    clock: Callable[[], float] = time.time,
) -> ProfileRecord:
    """Replace the profile record with a new limit, recording who changed it and when."""
    layout.validate_limit(limit)
    record = ProfileRecord(
        schema_version=SCHEMA_VERSION,
        profile_id=profile_id,
        concurrency_limit=limit,
        updated_by=node_id,
        updated_at=time_text(clock()),
    )
    store.write_text(layout.profile_path(profile_id), encode(record))
    return record


def _slot_of(name: str) -> int | None:
    match = _SLOT_NAME.fullmatch(name)
    if match is None:
        return None
    slot = int(match.group(1))
    return slot if layout.LIMIT_MIN <= slot <= layout.SLOT_MAX else None


def _items(store: FolderStore, profile_id: str) -> tuple[float, list[_Item]]:
    folder = layout.lease_dir(profile_id)
    try:
        listing = store.list_dir(folder)
    except NotFound:
        return store.now(), []
    texts = store.read_all(folder)
    items: list[_Item] = []
    for entry in listing.entries:
        slot = _slot_of(entry.name)
        record = decode_lease(texts.get(entry.name, ""))
        usable = (
            slot is not None
            and not isinstance(record, Unreadable)
            and record.profile_id == profile_id
            and record.slot == slot
        )
        if not usable:
            items.append(_Item(entry.name, entry.modified, None, slot, False))
            continue
        assert isinstance(record, LeaseRecord)
        fresh = classify(listing.now - entry.modified, record.interval_seconds) == ONLINE
        items.append(_Item(entry.name, entry.modified, record, slot, fresh))
    return listing.now, items


def _reclaim(store: FolderStore, profile_id: str, item: _Item) -> None:
    """Move a stale lease aside and delete it, unless it proves fresh, then move it back."""
    folder = layout.lease_dir(profile_id)
    original = f"{folder}/{item.name}"
    aside = f"{folder}/{layout.RECLAIM_PREFIX}{secrets.token_hex(8)}"
    try:
        store.move(original, aside, replace=False)
    except NotFound:
        return
    except StoreError as error:
        events.emit(events.STORE_ERROR, during="reclaim", kind=error.kind)
        return
    try:
        entry = store.stat(aside)
        record = decode_lease(store.read_text(aside))
    except NotFound:
        return
    fresh = (
        not isinstance(record, Unreadable)
        and classify(store.now() - entry.modified, record.interval_seconds) == ONLINE
    )
    if fresh:
        try:
            store.move(aside, original, replace=False)
            return
        except Exists:
            pass
    store.remove(aside)
    kind = "stale" if item.record is not None else "unreadable"
    events.emit(events.LEASE_RECLAIMED, profile_id=profile_id, kind=kind)


def _ordering(record: LeaseRecord) -> tuple[float, str]:
    return (time_epoch(record.acquired_at), record.node_id)


def acquire(
    store: FolderStore,
    profile_id: str,
    *,
    node_id: str,
    interval_seconds: int,
    clock: Callable[[], float] = time.time,
) -> SlotResult:
    """Take a free slot of the profile, or report that none is free. Creates no file when full."""
    layout.validate_id(profile_id, "profile id")
    layout.validate_id(node_id, "node id")
    check_interval(interval_seconds)
    try:
        profile = read_profile(store, profile_id)
    except NotFound:
        return SlotResult(UNKNOWN_PROFILE)
    if isinstance(profile, Unreadable):
        events.emit(events.RECORD_UNREADABLE, kind="profile", reason=profile.reason)
        return SlotResult(UNREADABLE_PROFILE)
    limit = profile.concurrency_limit
    store.make_dirs(layout.lease_dir(profile_id))

    _, items = _items(store, profile_id)
    for item in items:
        if not item.valid:
            if item.record is None:
                events.emit(events.RECORD_UNREADABLE, kind="lease", reason="invalid")
            _reclaim(store, profile_id, item)
    _, items = _items(store, profile_id)
    held = [item for item in items if item.valid and item.record is not None]
    if len(held) >= limit:
        events.emit(events.LEASE_DENIED, profile_id=profile_id, limit=limit, held=len(held))
        return SlotResult(NO_SLOT)

    used = {item.record.slot for item in held if item.record is not None}
    for slot in (number for number in range(1, limit + 1) if number not in used):
        record = LeaseRecord(
            schema_version=SCHEMA_VERSION,
            profile_id=profile_id,
            slot=slot,
            node_id=node_id,
            acquired_at=time_text(clock()),
            interval_seconds=interval_seconds,
        )
        try:
            store.create_exclusive(layout.lease_path(profile_id, slot), encode(record))
        except Exists:
            continue
        handle = LeaseHandle(profile_id, slot, node_id, record.acquired_at, interval_seconds)
        return repair(store, handle, limit)
    events.emit(events.LEASE_DENIED, profile_id=profile_id, limit=limit, held=len(held))
    return SlotResult(NO_SLOT)


def repair(store: FolderStore, handle: LeaseHandle, limit: int) -> SlotResult:
    _, items = _items(store, handle.profile_id)
    valid = sorted(
        (item.record for item in items if item.valid and item.record is not None),
        key=_ordering,
    )
    if len(valid) > limit:
        overflow = valid[limit:]
        if any(
            record.node_id == handle.node_id and record.slot == handle.slot for record in overflow
        ):
            store.remove(layout.lease_path(handle.profile_id, handle.slot))
            events.emit(
                events.LEASE_REPAIRED,
                profile_id=handle.profile_id,
                limit=limit,
                held=len(valid),
            )
            return SlotResult(NO_SLOT)
    events.emit(
        events.LEASE_ACQUIRED,
        profile_id=handle.profile_id,
        slot=handle.slot,
        held=len(valid),
    )
    return SlotResult(GRANTED, handle)


def _is_ours(record: LeaseRecord | Unreadable, handle: LeaseHandle) -> bool:
    return (
        not isinstance(record, Unreadable)
        and record.node_id == handle.node_id
        and record.acquired_at == handle.acquired_at
    )


def renew(store: FolderStore, handle: LeaseHandle) -> bool:
    """Refresh a held lease. False, with ``lease.lost``, when the lease is gone or not ours.

    A renewal keeps the acquisition time and rewrites the file, so its file time moves forward.
    """
    path = layout.lease_path(handle.profile_id, handle.slot)
    try:
        current = decode_lease(store.read_text(path))
    except NotFound:
        events.emit(
            events.LEASE_LOST, profile_id=handle.profile_id, slot=handle.slot, kind="missing"
        )
        return False
    if not _is_ours(current, handle):
        events.emit(events.LEASE_LOST, profile_id=handle.profile_id, slot=handle.slot, kind="taken")
        return False
    store.write_text(
        path,
        encode(
            LeaseRecord(
                schema_version=SCHEMA_VERSION,
                profile_id=handle.profile_id,
                slot=handle.slot,
                node_id=handle.node_id,
                acquired_at=handle.acquired_at,
                interval_seconds=handle.interval_seconds,
            )
        ),
    )
    return True


def release(store: FolderStore, handle: LeaseHandle) -> bool:
    """Free a held lease. False, and nothing changed, when this node does not hold it."""
    path = layout.lease_path(handle.profile_id, handle.slot)
    try:
        current = decode_lease(store.read_text(path))
    except NotFound:
        return False
    if not _is_ours(current, handle):
        return False
    store.remove(path)
    return True


def usage(store: FolderStore, profile_id: str) -> ProfileUsage:
    """The limit, valid and stale leases and node count of one profile. Raises NotFound when the
    profile has no record."""
    profile = read_profile(store, profile_id)
    if isinstance(profile, Unreadable):
        raise NotFound(profile_id)
    _, items = _items(store, profile_id)
    valid = sum(1 for item in items if item.valid)
    stale = sum(1 for item in items if item.record is not None and not item.valid)
    nodes = sum(1 for view in discover(store).nodes if view.record.profile_id == profile_id)
    return ProfileUsage(profile_id, profile.concurrency_limit, valid, stale, nodes)
