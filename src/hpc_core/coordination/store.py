"""The folder-store interface and the local-folder store.

A store reaches one team folder through paths relative to the team's shared area (see ``layout``).
Results are the same for every store: a missing file is ``NotFound``, a file that must not be
replaced is ``Exists``, and anything the folder cannot answer is ``StoreError``. A store never
reports a failure as a missing file.

``now()`` and the file times in a listing come from the folder's host, so liveness never depends on
the clock of the node that asks.
"""

from __future__ import annotations

import os
import secrets
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .layout import TEMP_PREFIX, is_hidden


class NotFound(Exception):
    """The file or folder does not exist. Not a failure of the folder."""


class Exists(Exception):
    """The target already exists, so nothing was written."""


class StoreError(Exception):
    """The folder could not be read or written. ``kind`` names the cause, never a path.

    Kinds: ``unreachable`` (login node or transport), ``truncated`` (output cut short),
    ``unexpected-output`` (a command answered in a shape the store does not know), ``io`` (a local
    file error), ``missing-command`` (a POSIX command the store needs is absent),
    ``hard-link-refused`` (the folder refuses hard links).
    """

    def __init__(self, message: str, kind: str = "io") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class FileEntry:
    name: str
    modified: float
    size: int


@dataclass(frozen=True)
class Listing:
    entries: tuple[FileEntry, ...]
    now: float


class FolderStore(Protocol):
    def now(self) -> float: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, text: str) -> None: ...

    def create_exclusive(self, path: str, text: str) -> None: ...

    def list_dir(self, path: str, *, hidden: bool = False) -> Listing: ...

    def list_subdirs(self, path: str) -> tuple[str, ...]: ...

    def read_all(self, path: str) -> dict[str, str]: ...

    def stat(self, path: str) -> FileEntry: ...

    def move(self, source: str, target: str, *, replace: bool = True) -> None: ...

    def remove(self, path: str) -> None: ...

    def remove_tree(self, path: str) -> None: ...

    def make_dirs(self, path: str) -> None: ...


def new_token() -> str:
    return secrets.token_hex(8)


def _safe_parts(path: str) -> tuple[str, ...]:
    parts = tuple(part for part in path.split("/") if part not in ("", "."))
    if any(part == ".." for part in parts):
        raise StoreError("path refused", kind="io")
    return parts


class LocalFolderStore:
    """A store over a folder the process can reach: a mounted or on-cluster path."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time) -> None:
        self._root = root
        self._clock = clock

    def _resolve(self, path: str) -> Path:
        return self._root.joinpath(*_safe_parts(path))

    def now(self) -> float:
        return self._clock()

    def read_text(self, path: str) -> str:
        try:
            return self._resolve(path).read_bytes().decode("utf-8", errors="replace")
        except FileNotFoundError:
            raise NotFound(path) from None
        except OSError as error:
            raise StoreError("the file could not be read", kind="io") from error

    def write_text(self, path: str, text: str) -> None:
        target = self._resolve(path)
        temporary = target.parent / f"{TEMP_PREFIX}{new_token()}"
        try:
            with open(temporary, "xb") as handle:
                handle.write(text.encode("utf-8"))
            os.replace(temporary, target)
        except OSError as error:
            _discard(temporary)
            raise StoreError("the file could not be written", kind="io") from error

    def create_exclusive(self, path: str, text: str) -> None:
        target = self._resolve(path)
        temporary = target.parent / f"{TEMP_PREFIX}{new_token()}"
        try:
            with open(temporary, "xb") as handle:
                handle.write(text.encode("utf-8"))
            try:
                os.link(temporary, target)
            except FileExistsError:
                raise Exists(path) from None
            except OSError as error:
                raise StoreError(
                    "the folder refused a hard link", kind="hard-link-refused"
                ) from error
        except OSError as error:
            raise StoreError("the file could not be created", kind="io") from error
        finally:
            _discard(temporary)

    def list_dir(self, path: str, *, hidden: bool = False) -> Listing:
        folder = self._resolve(path)
        now = self.now()
        try:
            with os.scandir(folder) as scanner:
                entries = []
                for entry in scanner:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if is_hidden(entry.name) and not hidden:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    entries.append(FileEntry(entry.name, info.st_mtime, info.st_size))
        except FileNotFoundError:
            raise NotFound(path) from None
        except OSError as error:
            raise StoreError("the folder could not be listed", kind="io") from error
        return Listing(tuple(sorted(entries, key=lambda item: item.name)), now)

    def list_subdirs(self, path: str) -> tuple[str, ...]:
        folder = self._resolve(path)
        try:
            with os.scandir(folder) as scanner:
                names = [entry.name for entry in scanner if entry.is_dir(follow_symlinks=False)]
        except FileNotFoundError:
            raise NotFound(path) from None
        except OSError as error:
            raise StoreError("the folder could not be listed", kind="io") from error
        return tuple(sorted(names))

    def read_all(self, path: str) -> dict[str, str]:
        listing = self.list_dir(path)
        texts: dict[str, str] = {}
        for entry in listing.entries:
            try:
                texts[entry.name] = self.read_text(f"{path}/{entry.name}")
            except NotFound:
                continue
        return texts

    def stat(self, path: str) -> FileEntry:
        target = self._resolve(path)
        try:
            info = target.stat(follow_symlinks=False)
        except FileNotFoundError:
            raise NotFound(path) from None
        except OSError as error:
            raise StoreError("the file could not be read", kind="io") from error
        return FileEntry(target.name, info.st_mtime, info.st_size)

    def move(self, source: str, target: str, *, replace: bool = True) -> None:
        origin = self._resolve(source)
        destination = self._resolve(target)
        if not origin.exists() and not origin.is_symlink():
            raise NotFound(source)
        try:
            if replace:
                os.replace(origin, destination)
            else:
                os.link(origin, destination)
                os.unlink(origin)
        except FileExistsError:
            raise Exists(target) from None
        except FileNotFoundError:
            raise NotFound(source) from None
        except OSError as error:
            raise StoreError("the file could not be moved", kind="io") from error

    def remove(self, path: str) -> None:
        try:
            self._resolve(path).unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise StoreError("the file could not be removed", kind="io") from error

    def remove_tree(self, path: str) -> None:
        try:
            shutil.rmtree(self._resolve(path))
        except FileNotFoundError:
            return
        except OSError as error:
            raise StoreError("the folder could not be removed", kind="io") from error

    def make_dirs(self, path: str) -> None:
        try:
            self._resolve(path).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StoreError("the folder could not be created", kind="io") from error


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
