"""Profile limits and slot leases: how the nodes of one profile share its concurrency limit.

A profile record holds the untyped limit (1 to 1024) and, optionally, the account quota per
accelerator type (0 to 1024 each, at most 16 types). A slot is a lease file ``slot-NN.json``
created exclusively; a lease is renewed by its holder at each heartbeat and is stale when it has
not been renewed for 3 of the holder's intervals. Leases are advisory: they coordinate cooperating
nodes, and the scheduler stays the authority.

An untyped lease counts only against the concurrency limit. A typed lease (it names an accelerator
type) counts only against that type: the profile's valid leases of the type against the account
quota, and the node's own valid leases of the type against the node's effective limit. Typed and
untyped leases share one slot-number sequence per profile.

Taking a slot reclaims stale leases, creates the lowest free slot and, after that, repairs an
over-limit state by making the latest holder release its own lease. A refusal names its reason:
``concurrency`` for an untyped request, or ``node_limit`` or ``account_limit`` for a typed one.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable, Mapping
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
from .registry import DEFAULT_LIMIT, ONLINE, NodeView, check_interval, classify, discover
from .store import Exists, FolderStore, NotFound, StoreError

GRANTED = "granted"
NO_SLOT = "no-slot"
UNKNOWN_PROFILE = "unknown-profile"
UNREADABLE_PROFILE = "unreadable-profile"

# Reasons a request got no slot.
REASON_CONCURRENCY = "concurrency"
REASON_NODE_LIMIT = "node_limit"
REASON_ACCOUNT_LIMIT = "account_limit"
REASON_NO_FREE_SLOT = "no-free-slot"

_SLOT_NAME = re.compile(r"slot-(\d{2,4})\.json")


@dataclass(frozen=True)
class LeaseHandle:
    profile_id: str
    slot: int
    node_id: str
    acquired_at: str
    interval_seconds: int
    accelerator: str | None = None


@dataclass(frozen=True)
class SlotResult:
    outcome: str
    lease: LeaseHandle | None = None
    reason: str | None = None


@dataclass(frozen=True)
class NodeUsage:
    """One node's share of an accelerator type: its valid leases and its effective limit."""

    node_id: str
    held: int
    limit: int


@dataclass(frozen=True)
class AcceleratorUsage:
    """The share-queue usage of one accelerator type of a profile."""

    accelerator: str
    account_limit: int
    valid_leases: int
    stale_leases: int
    nodes: tuple[NodeUsage, ...] = ()


@dataclass(frozen=True)
class ProfileUsage:
    profile_id: str
    limit: int
    valid_leases: int
    stale_leases: int
    nodes: int
    accelerators: tuple[AcceleratorUsage, ...] = ()


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


def _current_share_queue(store: FolderStore, profile_id: str) -> dict[str, int]:
    """The account quota already in the profile record, or empty when there is none."""
    try:
        record = read_profile(store, profile_id)
    except NotFound:
        return {}
    return {} if isinstance(record, Unreadable) else dict(record.share_queue_limits)


def set_limit(
    store: FolderStore,
    profile_id: str,
    limit: int,
    *,
    node_id: str,
    clock: Callable[[], float] = time.time,
) -> ProfileRecord:
    """Replace the profile record with a new limit, recording who changed it and when.

    The account quota per accelerator type already in the record is kept.
    """
    layout.validate_limit(limit)
    record = ProfileRecord(
        schema_version=SCHEMA_VERSION,
        profile_id=profile_id,
        concurrency_limit=limit,
        updated_by=node_id,
        updated_at=time_text(clock()),
        share_queue_limits=_current_share_queue(store, profile_id),
    )
    store.write_text(layout.profile_path(profile_id), encode(record))
    return record


def set_share_queue(
    store: FolderStore,
    profile_id: str,
    share_queue_limits: Mapping[str, int],
    *,
    node_id: str,
    clock: Callable[[], float] = time.time,
) -> ProfileRecord:
    """Set the account quota per accelerator type, keeping the concurrency limit of the record.

    A profile with no record yet is created with the default concurrency limit, so the account
    quota can be set before any node has joined. Raises NotFound when the record exists but cannot
    be read, and ValidationError for a bad name, a value outside 0 to 1024 or more than 16 types;
    nothing is written in either case. Lowering the quota never stops a lease that is already held.
    """
    folded = layout.validate_share_queue(dict(share_queue_limits))
    try:
        current = read_profile(store, profile_id)
    except NotFound:
        concurrency = DEFAULT_LIMIT
    else:
        if isinstance(current, Unreadable):
            raise NotFound(profile_id)
        concurrency = current.concurrency_limit
    record = ProfileRecord(
        schema_version=SCHEMA_VERSION,
        profile_id=profile_id,
        concurrency_limit=concurrency,
        updated_by=node_id,
        updated_at=time_text(clock()),
        share_queue_limits=folded,
    )
    store.make_dirs(layout.subfolder_path("profiles"))
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


def _valid_records(items: list[_Item]) -> list[LeaseRecord]:
    return [item.record for item in items if item.valid and item.record is not None]


def _reclaim_invalid(store: FolderStore, profile_id: str) -> list[_Item]:
    """Reclaim stale and unreadable leases of the profile and return the listing afterwards."""
    _, items = _items(store, profile_id)
    for item in items:
        if not item.valid:
            if item.record is None:
                events.emit(events.RECORD_UNREADABLE, kind="lease", reason="invalid")
            _reclaim(store, profile_id, item)
    _, items = _items(store, profile_id)
    return items


def _read_profile_for_take(store: FolderStore, profile_id: str) -> ProfileRecord | SlotResult:
    try:
        profile = read_profile(store, profile_id)
    except NotFound:
        return SlotResult(UNKNOWN_PROFILE)
    if isinstance(profile, Unreadable):
        events.emit(events.RECORD_UNREADABLE, kind="profile", reason=profile.reason)
        return SlotResult(UNREADABLE_PROFILE)
    return profile


def _create_lease(
    store: FolderStore,
    profile_id: str,
    *,
    node_id: str,
    interval_seconds: int,
    clock: Callable[[], float],
    accelerator: str | None,
    used: set[int],
    top: int,
) -> LeaseHandle | None:
    """Create the lowest free slot file of the lease among slots 1 to ``top``. None when none is
    free. Racing takers pick the same slot file, so the loser of a race finds no free slot in the
    range and is refused, which keeps the limit a bound under races."""
    for slot in range(layout.LIMIT_MIN, top + 1):
        if slot in used:
            continue
        record = LeaseRecord(
            schema_version=SCHEMA_VERSION,
            profile_id=profile_id,
            slot=slot,
            node_id=node_id,
            acquired_at=time_text(clock()),
            interval_seconds=interval_seconds,
            accelerator=accelerator,
        )
        try:
            store.create_exclusive(layout.lease_path(profile_id, slot), encode(record))
        except Exists:
            continue
        return LeaseHandle(
            profile_id, slot, node_id, record.acquired_at, interval_seconds, accelerator
        )
    return None


def acquire(
    store: FolderStore,
    profile_id: str,
    *,
    node_id: str,
    interval_seconds: int,
    clock: Callable[[], float] = time.time,
) -> SlotResult:
    """Take a free untyped slot of the profile, or report that none is free.

    Creates no file when full. Typed leases do not count against the concurrency limit.
    """
    layout.validate_id(profile_id, "profile id")
    layout.validate_id(node_id, "node id")
    check_interval(interval_seconds)
    profile = _read_profile_for_take(store, profile_id)
    if isinstance(profile, SlotResult):
        return profile
    limit = profile.concurrency_limit
    store.make_dirs(layout.lease_dir(profile_id))

    items = _reclaim_invalid(store, profile_id)
    valid = _valid_records(items)
    held = [record for record in valid if record.accelerator is None]
    if len(held) >= limit:
        events.emit(events.LEASE_DENIED, profile_id=profile_id, limit=limit, held=len(held))
        return SlotResult(NO_SLOT, None, REASON_CONCURRENCY)

    # The search stops at the limit plus the typed leases held, so an untyped request sees the
    # same slot range as before whenever no typed lease exists.
    typed_held = len(valid) - len(held)
    handle = _create_lease(
        store,
        profile_id,
        node_id=node_id,
        interval_seconds=interval_seconds,
        clock=clock,
        accelerator=None,
        used={record.slot for record in valid},
        top=min(layout.SLOT_MAX, limit + typed_held),
    )
    if handle is None:
        events.emit(events.LEASE_DENIED, profile_id=profile_id, limit=limit, held=len(held))
        return SlotResult(NO_SLOT, None, REASON_NO_FREE_SLOT)
    return repair(store, handle, limit)


def acquire_typed(
    store: FolderStore,
    profile_id: str,
    accelerator: str,
    *,
    node_id: str,
    node_limit: int,
    interval_seconds: int,
    clock: Callable[[], float] = time.time,
) -> SlotResult:
    """Take a slot of one accelerator type, or report why not. Creates no file when refused.

    The node's own valid leases of the type are checked against ``node_limit`` first, so a node
    with a limit of 0 is always refused with ``node_limit``. Then the profile's valid leases of the
    type are checked against the account quota; a type the account does not list counts as 0.
    """
    layout.validate_id(profile_id, "profile id")
    layout.validate_id(node_id, "node id")
    name = layout.validate_accelerator(accelerator)
    layout.validate_share_limit(node_limit, name)
    check_interval(interval_seconds)
    profile = _read_profile_for_take(store, profile_id)
    if isinstance(profile, SlotResult):
        return profile
    account_limit = profile.share_queue_limits.get(name, 0)
    store.make_dirs(layout.lease_dir(profile_id))

    items = _reclaim_invalid(store, profile_id)
    valid = _valid_records(items)
    typed = [record for record in valid if record.accelerator == name]
    own = sum(1 for record in typed if record.node_id == node_id)
    if own >= node_limit:
        events.emit(
            events.LEASE_DENIED, profile_id=profile_id, accelerator=name, held=own, limit=node_limit
        )
        return SlotResult(NO_SLOT, None, REASON_NODE_LIMIT)
    if len(typed) >= account_limit:
        events.emit(
            events.LEASE_DENIED,
            profile_id=profile_id,
            accelerator=name,
            held=len(typed),
            limit=account_limit,
        )
        return SlotResult(NO_SLOT, None, REASON_ACCOUNT_LIMIT)

    handle = _create_lease(
        store,
        profile_id,
        node_id=node_id,
        interval_seconds=interval_seconds,
        clock=clock,
        accelerator=name,
        used={record.slot for record in valid},
        top=layout.SLOT_MAX,
    )
    if handle is None:
        events.emit(events.LEASE_DENIED, profile_id=profile_id, accelerator=name, held=len(typed))
        return SlotResult(NO_SLOT, None, REASON_NO_FREE_SLOT)
    return repair(store, handle, account_limit)


def repair(store: FolderStore, handle: LeaseHandle, limit: int) -> SlotResult:
    """After taking a slot, make the over-limit state right for the lease's own kind.

    Only the valid leases of the same kind count: untyped against ``limit``, or a typed lease
    against the account quota of its type. When the count is above the limit, the holder with the
    later acquisition time (ties broken by node id) releases its lease if that is this node's.
    """
    _, items = _items(store, handle.profile_id)
    valid = sorted(
        (record for record in _valid_records(items) if record.accelerator == handle.accelerator),
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
            return SlotResult(NO_SLOT, None, _refusal_reason(handle))
    events.emit(
        events.LEASE_ACQUIRED,
        profile_id=handle.profile_id,
        slot=handle.slot,
        held=len(valid),
    )
    return SlotResult(GRANTED, handle)


def _refusal_reason(handle: LeaseHandle) -> str:
    return REASON_CONCURRENCY if handle.accelerator is None else REASON_ACCOUNT_LIMIT


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
                accelerator=handle.accelerator,
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
    """The limit, valid and stale leases and node count of one profile, with the share-queue
    usage per accelerator type. ``valid_leases`` counts the untyped leases that the concurrency
    limit applies to. Raises NotFound when the profile has no record."""
    profile = read_profile(store, profile_id)
    if isinstance(profile, Unreadable):
        raise NotFound(profile_id)
    _, items = _items(store, profile_id)
    untyped_valid = sum(
        1 for item in items if item.valid and item.record and item.record.accelerator is None
    )
    stale = sum(1 for item in items if item.record is not None and not item.valid)
    views = [view for view in discover(store).nodes if view.record.profile_id == profile_id]
    return ProfileUsage(
        profile_id=profile_id,
        limit=profile.concurrency_limit,
        valid_leases=untyped_valid,
        stale_leases=stale,
        nodes=len(views),
        accelerators=_accelerator_usage(profile.share_queue_limits, items, views),
    )


def _accelerator_usage(
    account: Mapping[str, int], items: list[_Item], views: list[NodeView]
) -> tuple[AcceleratorUsage, ...]:
    """Per accelerator type: the account quota, the valid and stale leases, and each profile
    node's held count and effective limit. Sorted by type name."""
    names = set(account)
    for item in items:
        if item.record is not None and item.record.accelerator is not None:
            names.add(item.record.accelerator)
    result: list[AcceleratorUsage] = []
    for name in sorted(names):
        typed = [
            item for item in items if item.record is not None and item.record.accelerator == name
        ]
        valid = [item for item in typed if item.valid]
        nodes = tuple(
            NodeUsage(
                node_id=view.record.node_id,
                held=sum(
                    1
                    for item in valid
                    if item.record is not None and item.record.node_id == view.record.node_id
                ),
                limit=view.record.share_queue_limits.get(name, 0),
            )
            for view in views
        )
        result.append(
            AcceleratorUsage(
                accelerator=name,
                account_limit=account.get(name, 0),
                valid_leases=len(valid),
                stale_leases=len(typed) - len(valid),
                nodes=nodes,
            )
        )
    return tuple(result)
