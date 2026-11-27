"""Node registration, heartbeat, leave, discovery, liveness and pruning.

A node writes only its own record. Liveness is the age of the record's file time as the folder's
host reports it, compared with the node's own heartbeat interval: ``online`` within 3 intervals,
``stale`` within 20 and ``offline`` beyond. A heartbeat failure is returned as a result, never
raised into the host program, and never stops it.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from ..contract.identifiers import ValidationError
from . import events, layout
from .layout import PRUNE_AGE_SECONDS, subfolder_path, validate_share_queue
from .profile import check_against_account, resolve
from .records import (
    DEFAULT_INTERVAL_SECONDS,
    KINDS,
    MIN_INTERVAL_SECONDS,
    SCHEMA_VERSION,
    SOURCE_DEFAULT,
    ClusterManifest,
    NodeRecord,
    ProfileRecord,
    Unreadable,
    decode_manifest,
    decode_node,
    decode_profile,
    encode,
    time_text,
)
from .store import Exists, FolderStore, NotFound, StoreError

ONLINE = "online"
STALE = "stale"
OFFLINE = "offline"
ONLINE_INTERVALS = 3
STALE_INTERVALS = 20
MAX_INTERVAL_SECONDS = 86400
DEFAULT_LIMIT = 1
NODE_SUFFIX = ".json"

# Outcomes of a heartbeat or registration.
OUTCOME_REGISTERED = "registered"
OUTCOME_BEAT = "beat"
OUTCOME_CONFLICT = "conflict"
OUTCOME_FAILED = "failed"


def classify(age_seconds: float, interval_seconds: int) -> str:
    """The liveness state of a record that is ``age_seconds`` old and beats every interval."""
    age = max(age_seconds, 0.0)
    if age <= ONLINE_INTERVALS * interval_seconds:
        return ONLINE
    if age <= STALE_INTERVALS * interval_seconds:
        return STALE
    return OFFLINE


def check_interval(interval_seconds: int) -> int:
    if (
        isinstance(interval_seconds, bool)
        or not isinstance(interval_seconds, int)
        or not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS
    ):
        raise ValidationError(
            f"heartbeat interval must be a whole number of seconds from "
            f"{MIN_INTERVAL_SECONDS} (the minimum) to {MAX_INTERVAL_SECONDS}"
        )
    return interval_seconds


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValidationError(f"kind must be one of: {', '.join(KINDS)}")
    return kind


@dataclass(frozen=True)
class NodeIdentity:
    """What a node says about itself. Validated when built; the id rules are in ``layout``."""

    node_id: str
    profile_id: str
    kind: str
    display_name: str = ""
    machine: str = ""
    software_version: str = ""
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    concurrency_limit: int = DEFAULT_LIMIT
    # The node's explicit share-queue values. None means keep whatever the node's own record
    # already holds (an empty mapping counts as None); the account quota is never set here.
    node_quota: dict[str, int] | None = None

    def __post_init__(self) -> None:
        layout.validate_id(self.node_id, "node id")
        layout.validate_id(self.profile_id, "profile id")
        check_kind(self.kind)
        check_interval(self.interval_seconds)
        layout.validate_limit(self.concurrency_limit)
        if self.node_quota is not None:
            folded = validate_share_queue(dict(self.node_quota))
            object.__setattr__(self, "node_quota", folded or None)


@dataclass(frozen=True)
class NodeView:
    record: NodeRecord
    state: str
    age_seconds: float


@dataclass(frozen=True)
class Discovery:
    nodes: tuple[NodeView, ...]
    unreadable: int
    now: float


@dataclass(frozen=True)
class BeatResult:
    outcome: str
    failure: str | None = None
    consecutive_failures: int = 0
    heartbeat_count: int = 0


def init_layout(store: FolderStore, team_label: str = "") -> bool:
    """Create ``_cluster`` with its manifest and sub-folders. True when created, False when the
    layout was already present; an existing manifest is never changed."""
    store.make_dirs(layout.cluster_path())
    for name in layout.SUBFOLDERS:
        store.make_dirs(subfolder_path(name))
    text = encode(ClusterManifest(schema_version=SCHEMA_VERSION, team_label=team_label))
    try:
        store.create_exclusive(layout.manifest_path(), text)
    except Exists:
        return False
    return True


def read_manifest(store: FolderStore) -> ClusterManifest | Unreadable:
    return decode_manifest(store.read_text(layout.manifest_path()))


def ensure_profile(
    store: FolderStore,
    profile_id: str,
    *,
    limit: int,
    node_id: str,
    clock: Callable[[], float],
) -> ProfileRecord | Unreadable:
    """Create the profile record once. An existing record is kept as it is."""
    path = layout.profile_path(profile_id)
    record = ProfileRecord(
        schema_version=SCHEMA_VERSION,
        profile_id=profile_id,
        concurrency_limit=limit,
        updated_by=node_id,
        updated_at=time_text(clock()),
    )
    try:
        store.create_exclusive(path, encode(record))
        return record
    except Exists:
        return decode_profile(store.read_text(path), expected_id=profile_id)


def _age_of(listing_now: float, modified: float) -> float:
    return max(listing_now - modified, 0.0)


def _explicit(node_quota: Mapping[str, int] | None) -> dict[str, int] | None:
    """A node quota as stored: validated and folded, or None when there are no explicit values."""
    if node_quota is None:
        return None
    return validate_share_queue(dict(node_quota)) or None


def _own_quota(store: FolderStore, node_id: str) -> dict[str, int] | None:
    """The explicit values the node's own record holds, or None when there are none."""
    try:
        record = decode_node(store.read_text(layout.node_path(node_id)), node_id)
    except NotFound:
        return None
    return None if isinstance(record, Unreadable) else record.node_quota


def reset_node_profile(store: FolderStore, node_id: str) -> str:
    """Remove a node's explicit values so its effective limits equal the account quota.

    Edits only the explicit values and the derived fields of the node's own record; the instance
    token and heartbeat count are kept. Returns ``reset``, ``unchanged`` (no explicit values, so
    nothing is written), ``absent`` (no readable record) or ``failed``.
    """
    path = layout.node_path(node_id)
    try:
        record = decode_node(store.read_text(path), node_id)
    except NotFound:
        return "absent"
    except StoreError:
        return "failed"
    if isinstance(record, Unreadable):
        return "absent"
    if record.node_quota is None:
        return "unchanged"
    account = _account_of(store, record.profile_id)
    resolved = resolve(account, None)
    updated = replace(
        record,
        node_quota=None,
        share_queue_limits=resolved.effective,
        profile_source=SOURCE_DEFAULT,
    )
    try:
        store.write_text(path, encode(updated))
    except StoreError:
        return "failed"
    return "reset"


def _account_of(store: FolderStore, profile_id: str) -> dict[str, int]:
    try:
        record = decode_profile(store.read_text(layout.profile_path(profile_id)), profile_id)
    except NotFound:
        return {}
    return {} if isinstance(record, Unreadable) else dict(record.share_queue_limits)


@dataclass
class NodeSession:
    """One running node: its identity, its instance token and its heartbeat state.

    ``clock`` stamps the node's own record fields only. Liveness never reads it: the folder's file
    times and the folder host's time decide. A session that is not the owner of its node id sees a
    conflict and writes nothing.

    The node's explicit share-queue values live in its own node record, so an ordinary beat keeps
    them. The record's effective limits are recomputed at every write from the current account
    quota, so a change of the account takes effect at the next beat.
    """

    store: FolderStore
    identity: NodeIdentity
    clock: Callable[[], float] = time.time
    token: str = field(default_factory=lambda: secrets.token_hex(8))
    heartbeat_count: int = 0
    consecutive_failures: int = 0
    started_at: str = ""

    def _record(
        self, count: int, node_quota: dict[str, int] | None, account: Mapping[str, int]
    ) -> NodeRecord:
        identity = self.identity
        resolved = resolve(account, node_quota)
        # A session that never joined here has no start time yet. An empty one would make the
        # record unreadable, and the node would drop out of discovery; this write's time stands in.
        started_at = self.started_at or time_text(self.clock())
        return NodeRecord(
            schema_version=SCHEMA_VERSION,
            node_id=identity.node_id,
            profile_id=identity.profile_id,
            kind=identity.kind,
            display_name=identity.display_name or identity.node_id,
            machine=identity.machine,
            software_version=identity.software_version,
            started_at=started_at,
            interval_seconds=identity.interval_seconds,
            heartbeat_count=count,
            instance_token=self.token,
            share_queue_limits=resolved.effective,
            node_quota=resolved.node_quota,
            profile_source=resolved.source,
        )

    def _failure(self, error: StoreError, during: str) -> BeatResult:
        self.consecutive_failures += 1
        events.emit(
            events.STORE_ERROR, during=during, kind=error.kind, failures=self.consecutive_failures
        )
        if during != "leave":
            events.emit(
                events.NODE_BEAT_FAILED,
                node_id=self.identity.node_id,
                kind=error.kind,
                failures=self.consecutive_failures,
            )
        return BeatResult(
            OUTCOME_FAILED, error.kind, self.consecutive_failures, self.heartbeat_count
        )

    def _live_other(self) -> bool:
        """True when another live instance holds this node id."""
        nodes = layout.subfolder_path("nodes")
        try:
            listing = self.store.list_dir(nodes)
        except NotFound:
            return False
        name = f"{self.identity.node_id}{NODE_SUFFIX}"
        entry = next((item for item in listing.entries if item.name == name), None)
        if entry is None:
            return False
        try:
            text = self.store.read_text(layout.node_path(self.identity.node_id))
        except NotFound:
            return False
        record = decode_node(text, expected_id=self.identity.node_id)
        if isinstance(record, Unreadable):
            return False
        if record.instance_token == self.token:
            return False
        age = _age_of(listing.now, entry.modified)
        return classify(age, record.interval_seconds) == ONLINE

    def _account(self) -> dict[str, int]:
        """The account quota per type from the profile record; empty when there is no record."""
        profile_id = self.identity.profile_id
        try:
            record = decode_profile(
                self.store.read_text(layout.profile_path(profile_id)), profile_id
            )
        except NotFound:
            return {}
        if isinstance(record, Unreadable):
            events.emit(events.RECORD_UNREADABLE, kind="profile", reason=record.reason)
            return {}
        return dict(record.share_queue_limits)

    def register(self) -> BeatResult:
        """Create the layout and the profile if needed, then write the node record.

        An explicit node quota above the account quota is refused before anything is written.
        """
        return self._join(self.identity.node_quota, keep=True)

    def beat(self) -> BeatResult:
        """Refresh the node record. Registers again when the record is gone."""
        return self._publish(self.identity.node_quota, keep=True)

    def publish_profile(self, node_quota: Mapping[str, int] | None) -> BeatResult:
        """Set the node's explicit values now (None or empty means default) and publish them.

        Refused with ValidationError, and nothing written, when a value is above the account quota.
        """
        quota = _explicit(node_quota)
        try:
            account = self._account() if quota is not None else {}
        except StoreError as error:
            return self._failure(error, "publish")
        if quota is not None:
            check_against_account(quota, account)
        self.identity = replace(self.identity, node_quota=quota)
        return self._publish(quota, keep=False)

    def _join(self, node_quota: dict[str, int] | None, *, keep: bool) -> BeatResult:
        self.started_at = time_text(self.clock())
        try:
            account = self._account()
            if keep and node_quota is None:
                node_quota = _own_quota(self.store, self.identity.node_id)
            if node_quota is not None:
                check_against_account(node_quota, account)
            init_layout(self.store)
            profile = ensure_profile(
                self.store,
                self.identity.profile_id,
                limit=self.identity.concurrency_limit,
                node_id=self.identity.node_id,
                clock=self.clock,
            )
            if isinstance(profile, Unreadable):
                events.emit(events.RECORD_UNREADABLE, kind="profile", reason=profile.reason)
            if self._live_other():
                events.emit(events.NODE_CONFLICT, node_id=self.identity.node_id)
                return BeatResult(OUTCOME_CONFLICT, None, 0, self.heartbeat_count)
            self.heartbeat_count = 0
            record = self._record(0, node_quota, account)
            self.store.write_text(layout.node_path(self.identity.node_id), encode(record))
        except StoreError as error:
            return self._failure(error, "register")
        self.consecutive_failures = 0
        events.emit(
            events.NODE_REGISTERED,
            node_id=self.identity.node_id,
            profile_id=self.identity.profile_id,
            kind=self.identity.kind,
        )
        return BeatResult(OUTCOME_REGISTERED, None, 0, self.heartbeat_count)

    def _publish(self, node_quota: dict[str, int] | None, *, keep: bool) -> BeatResult:
        path = layout.node_path(self.identity.node_id)
        try:
            try:
                record = decode_node(self.store.read_text(path), self.identity.node_id)
            except NotFound:
                return self._join(node_quota, keep=keep)
            current: NodeRecord | None = None
            if isinstance(record, Unreadable):
                events.emit(events.RECORD_UNREADABLE, kind="node", reason=record.reason)
            else:
                current = record
                if current.instance_token != self.token:
                    events.emit(events.NODE_CONFLICT, node_id=self.identity.node_id)
                    return BeatResult(OUTCOME_CONFLICT, None, self.consecutive_failures, 0)
            if keep and node_quota is None and current is not None:
                node_quota = current.node_quota
            count = self.heartbeat_count + 1
            self.store.write_text(path, encode(self._record(count, node_quota, self._account())))
        except StoreError as error:
            return self._failure(error, "beat")
        self.heartbeat_count = count
        self.consecutive_failures = 0
        events.emit(events.NODE_BEAT, node_id=self.identity.node_id, count=count)
        return BeatResult(OUTCOME_BEAT, None, 0, count)

    def leave(self) -> str:
        """Remove this node's record. Returns ``left``, ``absent``, ``not-ours`` or ``failed``."""
        path = layout.node_path(self.identity.node_id)
        try:
            try:
                record = decode_node(self.store.read_text(path), self.identity.node_id)
            except NotFound:
                return "absent"
            if not isinstance(record, Unreadable) and record.instance_token != self.token:
                return "not-ours"
            self.store.remove(path)
        except StoreError as error:
            self._failure(error, "leave")
            return "failed"
        events.emit(events.NODE_LEFT, node_id=self.identity.node_id)
        return "left"


def discover(store: FolderStore) -> Discovery:
    """Every readable node record of the team, with its liveness, sorted by profile and node."""
    nodes_dir = subfolder_path("nodes")
    try:
        listing = store.list_dir(nodes_dir)
    except NotFound:
        return Discovery((), 0, store.now())
    texts = store.read_all(nodes_dir)
    views: list[NodeView] = []
    unreadable = 0
    for entry in listing.entries:
        if not entry.name.endswith(NODE_SUFFIX):
            unreadable += 1
            events.emit(events.RECORD_UNREADABLE, kind="node", reason="name-mismatch")
            continue
        stem = entry.name[: -len(NODE_SUFFIX)]
        record = decode_node(texts.get(entry.name, ""), expected_id=stem)
        if isinstance(record, Unreadable):
            unreadable += 1
            events.emit(events.RECORD_UNREADABLE, kind="node", reason=record.reason)
            continue
        age = _age_of(listing.now, entry.modified)
        views.append(NodeView(record, classify(age, record.interval_seconds), age))
    views.sort(key=lambda view: (view.record.profile_id, view.record.node_id))
    return Discovery(tuple(views), unreadable, listing.now)


@dataclass(frozen=True)
class PruneResult:
    nodes_removed: int
    inboxes_removed: int


def prune(store: FolderStore) -> PruneResult:
    """Remove node records offline for more than 7 days, then the inboxes of nodes that have no
    record left and whose files are all older than 7 days. Nothing else is removed."""
    nodes_dir = subfolder_path("nodes")
    nodes_removed = 0
    try:
        listing = store.list_dir(nodes_dir)
        texts = store.read_all(nodes_dir)
    except NotFound:
        listing = None
        texts = {}
    remaining: set[str] = set()
    if listing is not None:
        for entry in listing.entries:
            stem = entry.name[: -len(NODE_SUFFIX)] if entry.name.endswith(NODE_SUFFIX) else ""
            remaining.add(stem)
            record = decode_node(texts.get(entry.name, ""), expected_id=stem or None)
            if isinstance(record, Unreadable):
                continue
            age = _age_of(listing.now, entry.modified)
            if classify(age, record.interval_seconds) == OFFLINE and age > PRUNE_AGE_SECONDS:
                store.remove(layout.node_path(record.node_id))
                remaining.discard(stem)
                nodes_removed += 1
                events.emit(events.NODE_PRUNED, node_id=record.node_id, kind="record")
    inboxes_removed = _prune_inboxes(store, remaining)
    return PruneResult(nodes_removed, inboxes_removed)


def _prune_inboxes(store: FolderStore, live_nodes: set[str]) -> int:
    inbox = subfolder_path("inbox")
    try:
        names = store.list_subdirs(inbox)
    except NotFound:
        return 0
    removed = 0
    for name in names:
        try:
            layout.validate_id(name, "node id")
        except ValidationError:
            continue
        if name in live_nodes:
            continue
        now = store.now()
        old = True
        for folder in (layout.inbox_dir(name), layout.done_dir(name)):
            try:
                files = store.list_dir(folder, hidden=True)
            except NotFound:
                continue
            if any(now - item.modified <= PRUNE_AGE_SECONDS for item in files.entries):
                old = False
                break
        if old:
            store.remove_tree(layout.inbox_dir(name))
            removed += 1
            events.emit(events.NODE_PRUNED, node_id=name, kind="inbox")
    return removed
