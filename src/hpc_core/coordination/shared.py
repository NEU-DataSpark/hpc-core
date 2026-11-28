"""Shared datasets: one collector chosen from discovery, and one plain-text file per dataset.

A dataset file is ``_cluster/shared/<dataset>.txt``: one JSON envelope around a payload this package
does not read (see ``records.SharedRecord``). The collector is the smallest id among the nodes that
discovery reports ``online`` and marked as candidates, so every node computes the same answer from
the same records and nothing extra is written. A due check uses the folder's own clock and the
file's time, so a node's clock never decides freshness. Nothing here runs a scheduler command or
knows what a payload holds: the console and the skill decide what to collect and what may be shared.

The election is advisory. A wrong answer costs at most one extra collection, because each publish
replaces the file whole and the due check stops a second collector while the file is fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contract.identifiers import ValidationError
from . import events, layout
from .records import SCHEMA_VERSION, SharedRecord, Unreadable, decode_shared, encode
from .registry import ONLINE, Discovery
from .store import FolderStore, NotFound, StoreError

SHARED_SUFFIX = ".txt"


@dataclass(frozen=True)
class SharedCopy:
    """A readable shared dataset: its payload, the age of its file and the node that wrote it."""

    dataset: str
    payload: dict[str, Any]
    age_seconds: float
    collector_node_id: str


@dataclass(frozen=True)
class SharedMissing:
    """No shared file exists for the dataset. Not a failure of the folder."""

    dataset: str


SharedResult = SharedCopy | SharedMissing | Unreadable


def _age(now: float, modified: float) -> float:
    return max(now - modified, 0.0)


def elect_collector(discovery: Discovery) -> str | None:
    """The smallest node id among online candidates, or None when no candidate is online."""
    candidates = [
        view.record.node_id
        for view in discovery.nodes
        if view.state == ONLINE and view.record.shared_collector
    ]
    return min(candidates) if candidates else None


def should_collect(
    store: FolderStore,
    dataset: str,
    node_id: str,
    interval: int,
    discovery: Discovery,
) -> bool:
    """True only when ``node_id`` is the elected collector and the dataset is due.

    Due means: the file is missing, older than ``interval`` seconds by the folder's clock, or it
    cannot be parsed. A node that is not the collector is never due, so it never publishes.
    """
    layout.validate_dataset(dataset)
    if elect_collector(discovery) != node_id:
        return False
    try:
        listing = store.list_dir(layout.shared_dir())
    except NotFound:
        return True
    entry = next((item for item in listing.entries if item.name == _file(dataset)), None)
    if entry is None or _age(listing.now, entry.modified) > interval:
        return True
    try:
        text = store.read_text(layout.shared_path(dataset))
    except NotFound:
        return True
    return isinstance(decode_shared(text, dataset), Unreadable)


def publish_shared(
    store: FolderStore,
    dataset: str,
    *,
    node_id: str,
    payload: dict[str, Any],
) -> None:
    """Replace the dataset file with one whole document. Creates the shared folder on first use.

    A payload that makes the file over 1 MiB is refused before anything is written, so the previous
    file stays in place. The caller decides whether this node is the collector.
    """
    layout.validate_dataset(dataset)
    layout.validate_id(node_id, "node id")
    text = encode(SharedRecord(SCHEMA_VERSION, dataset, node_id, payload))
    store.make_dirs(layout.shared_dir())
    store.write_text(layout.shared_path(dataset), text)
    events.emit(
        events.SHARED_PUBLISHED,
        dataset=dataset,
        node_id=node_id,
        size=len(text.encode("utf-8")),
    )


def read_shared(store: FolderStore, dataset: str) -> SharedResult:
    """The dataset's payload with its age and collector id, or a missing or unreadable result.

    Writes nothing. The age is the folder's current time minus the file's time, both from the
    folder. An unreachable folder raises ``StoreError``; a missing file is not an error.
    """
    layout.validate_dataset(dataset)
    try:
        listing = store.list_dir(layout.shared_dir())
        entry = next((item for item in listing.entries if item.name == _file(dataset)), None)
        if entry is None:
            return SharedMissing(dataset)
        text = store.read_text(layout.shared_path(dataset))
    except NotFound:
        return SharedMissing(dataset)
    except StoreError as error:
        events.emit(events.SHARED_READ_FAILED, dataset=dataset, reason=error.kind)
        raise
    record = decode_shared(text, dataset)
    if isinstance(record, Unreadable):
        events.emit(events.SHARED_READ_FAILED, dataset=dataset, reason=record.reason)
        return record
    return SharedCopy(
        dataset=dataset,
        payload=record.payload,
        age_seconds=_age(listing.now, entry.modified),
        collector_node_id=record.collector_node_id,
    )


def shared_ages(store: FolderStore) -> dict[str, float]:
    """The age of each shared dataset file that exists, by dataset name. Reads no contents."""
    try:
        listing = store.list_dir(layout.shared_dir())
    except NotFound:
        return {}
    ages: dict[str, float] = {}
    for entry in listing.entries:
        if not entry.name.endswith(SHARED_SUFFIX):
            continue
        dataset = entry.name[: -len(SHARED_SUFFIX)]
        try:
            layout.validate_dataset(dataset)
        except ValidationError:
            continue
        ages[dataset] = _age(listing.now, entry.modified)
    return ages


def _file(dataset: str) -> str:
    return f"{dataset}{SHARED_SUFFIX}"
