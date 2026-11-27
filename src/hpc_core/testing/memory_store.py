"""An in-memory folder store with a settable clock, for tests.

Files keep the time they were last written (or moved, which keeps the time as ``mv`` does). A folder
exists once it is made, and a file can be written only into an existing folder, as on a real
filesystem. ``ManualClock`` is the one time source, so a test moves time instead of sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..coordination.store import Exists, FileEntry, Listing, NotFound, StoreError


@dataclass
class ManualClock:
    current: float = 1_800_000_000.0

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds

    def set(self, moment: float) -> None:
        self.current = moment


def _norm(path: str) -> str:
    return "/".join(part for part in path.split("/") if part not in ("", "."))


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


@dataclass
class MemoryFolderStore:
    clock: ManualClock = field(default_factory=ManualClock)
    _files: dict[str, tuple[str, float]] = field(default_factory=dict)
    _dirs: set[str] = field(default_factory=lambda: {""})

    def now(self) -> float:
        return self.clock.now()

    def _check_parent(self, path: str) -> None:
        if _parent(path) not in self._dirs:
            raise StoreError("the folder does not exist", kind="io")

    def read_text(self, path: str) -> str:
        key = _norm(path)
        if key not in self._files:
            raise NotFound(path)
        return self._files[key][0]

    def write_text(self, path: str, text: str) -> None:
        key = _norm(path)
        self._check_parent(key)
        self._files[key] = (text, self.clock.now())

    def create_exclusive(self, path: str, text: str) -> None:
        key = _norm(path)
        self._check_parent(key)
        if key in self._files:
            raise Exists(path)
        self._files[key] = (text, self.clock.now())

    def list_dir(self, path: str, *, hidden: bool = False) -> Listing:
        folder = _norm(path)
        if folder not in self._dirs:
            raise NotFound(path)
        entries = [
            FileEntry(key.rsplit("/", 1)[-1], modified, len(text.encode("utf-8")))
            for key, (text, modified) in self._files.items()
            if _parent(key) == folder and (hidden or not key.rsplit("/", 1)[-1].startswith("."))
        ]
        return Listing(tuple(sorted(entries, key=lambda item: item.name)), self.clock.now())

    def list_subdirs(self, path: str) -> tuple[str, ...]:
        folder = _norm(path)
        if folder not in self._dirs:
            raise NotFound(path)
        names = {
            key.rsplit("/", 1)[-1]
            for key in self._dirs
            if key and _parent(key) == folder and not key.rsplit("/", 1)[-1].startswith(".")
        }
        return tuple(sorted(names))

    def read_all(self, path: str) -> dict[str, str]:
        listing = self.list_dir(path)
        folder = _norm(path)
        return {entry.name: self._files[f"{folder}/{entry.name}"][0] for entry in listing.entries}

    def stat(self, path: str) -> FileEntry:
        key = _norm(path)
        if key not in self._files:
            raise NotFound(path)
        text, modified = self._files[key]
        return FileEntry(key.rsplit("/", 1)[-1], modified, len(text.encode("utf-8")))

    def move(self, source: str, target: str, *, replace: bool = True) -> None:
        origin, destination = _norm(source), _norm(target)
        if origin not in self._files:
            raise NotFound(source)
        self._check_parent(destination)
        if not replace and destination in self._files:
            raise Exists(target)
        self._files[destination] = self._files.pop(origin)

    def remove(self, path: str) -> None:
        self._files.pop(_norm(path), None)

    def remove_tree(self, path: str) -> None:
        folder = _norm(path)
        for key in [key for key in self._files if key == folder or key.startswith(folder + "/")]:
            del self._files[key]
        for key in [key for key in self._dirs if key == folder or key.startswith(folder + "/")]:
            self._dirs.discard(key)

    def make_dirs(self, path: str) -> None:
        parts = _norm(path).split("/") if _norm(path) else []
        for index in range(1, len(parts) + 1):
            self._dirs.add("/".join(parts[:index]))
