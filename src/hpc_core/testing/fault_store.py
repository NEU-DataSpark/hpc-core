"""A store wrapper that injects the behaviour of a network filesystem, for L3 tests.

Each knob models one behaviour the protocol must survive, and is off by default:

- ``visibility_lag``: a file time is seen this many seconds older than it is (a caching client);
- ``time_resolution``: file times are floored to this many seconds (one-second filesystems);
- ``listing_cache``: a directory listing is served from a snapshot up to this many seconds old;
- ``rename_delay``: a new name is visible only after this delay; until then the old version (or
  nothing) is listed;
- ``refuse_hard_links``: exclusive create reports a refused hard link, not a false ``Exists``;
- ``failures``: a queue of errors; each operation pops one and raises it (transient ESTALE or I/O).

Node clock skew is not a store property: a skewed node stamps its own record fields with its own
clock (``NodeSession(clock=...)``), while liveness uses the folder's file times, so a test models
skew by giving the session a skewed clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..coordination.store import FileEntry, FolderStore, Listing, NotFound, StoreError


@dataclass
class FaultyFolderStore:
    inner: FolderStore
    visibility_lag: float = 0.0
    time_resolution: float = 0.0
    listing_cache: float = 0.0
    rename_delay: float = 0.0
    refuse_hard_links: bool = False
    failures: list[Exception] = field(default_factory=list)
    _renamed: dict[str, tuple[float, float | None]] = field(default_factory=dict)
    _cache: dict[str, tuple[float, Listing]] = field(default_factory=dict)

    def _fail_if_queued(self) -> None:
        if self.failures:
            raise self.failures.pop(0)

    def _note_rename(self, path: str) -> None:
        try:
            previous: float | None = self.inner.stat(path).modified
        except NotFound:
            previous = None
        self._renamed[path] = (self.inner.now(), previous)

    def now(self) -> float:
        return self.inner.now()

    def read_text(self, path: str) -> str:
        self._fail_if_queued()
        return self.inner.read_text(path)

    def write_text(self, path: str, text: str) -> None:
        self._fail_if_queued()
        self._note_rename(path)
        self.inner.write_text(path, text)

    def create_exclusive(self, path: str, text: str) -> None:
        self._fail_if_queued()
        if self.refuse_hard_links:
            raise StoreError("the folder refused a hard link", kind="hard-link-refused")
        self.inner.create_exclusive(path, text)
        self._renamed[path] = (self.inner.now(), None)

    def list_dir(self, path: str, *, hidden: bool = False) -> Listing:
        self._fail_if_queued()
        now = self.inner.now()
        if self.listing_cache > 0 and path in self._cache:
            taken, snapshot = self._cache[path]
            if now - taken < self.listing_cache:
                return snapshot
        listing = self.inner.list_dir(path, hidden=hidden)
        entries: list[FileEntry] = []
        for entry in listing.entries:
            full = f"{path}/{entry.name}"
            modified = entry.modified
            if full in self._renamed and now - self._renamed[full][0] < self.rename_delay:
                previous = self._renamed[full][1]
                if previous is None:
                    continue
                modified = previous
            if self.time_resolution > 0:
                modified = math.floor(modified / self.time_resolution) * self.time_resolution
            entries.append(FileEntry(entry.name, modified - self.visibility_lag, entry.size))
        result = Listing(tuple(entries), listing.now)
        self._cache[path] = (now, result)
        return result

    def list_subdirs(self, path: str) -> tuple[str, ...]:
        self._fail_if_queued()
        return self.inner.list_subdirs(path)

    def read_all(self, path: str) -> dict[str, str]:
        self._fail_if_queued()
        return self.inner.read_all(path)

    def stat(self, path: str) -> FileEntry:
        self._fail_if_queued()
        entry = self.inner.stat(path)
        return FileEntry(entry.name, entry.modified - self.visibility_lag, entry.size)

    def move(self, source: str, target: str, *, replace: bool = True) -> None:
        self._fail_if_queued()
        self.inner.move(source, target, replace=replace)
        self._renamed[target] = (self.inner.now(), None)

    def remove(self, path: str) -> None:
        self._fail_if_queued()
        self.inner.remove(path)

    def remove_tree(self, path: str) -> None:
        self._fail_if_queued()
        self.inner.remove_tree(path)

    def make_dirs(self, path: str) -> None:
        self._fail_if_queued()
        self.inner.make_dirs(path)
