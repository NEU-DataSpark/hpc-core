"""The local-folder store on a temporary directory: atomic writes, exclusive create, not-found, and
hidden temporary names."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from hpc_core.coordination.store import Exists, LocalFolderStore, NotFound, StoreError


@pytest.fixture
def store(tmp_path: Path) -> LocalFolderStore:
    (tmp_path / "_cluster" / "nodes").mkdir(parents=True)
    return LocalFolderStore(tmp_path)


def test_a_writer_that_stopped_before_the_rename_leaves_no_visible_partial_file(
    store: LocalFolderStore, tmp_path: Path
) -> None:
    store.write_text("_cluster/nodes/a.json", '{"complete":true}\n')
    (tmp_path / "_cluster" / "nodes" / ".tmp-crashed").write_text('{"partial', encoding="utf-8")
    listing = store.list_dir("_cluster/nodes")
    assert [entry.name for entry in listing.entries] == ["a.json"]
    assert store.read_text("_cluster/nodes/a.json") == '{"complete":true}\n'


def test_a_write_replaces_the_whole_file(store: LocalFolderStore) -> None:
    store.write_text("_cluster/nodes/a.json", "one\n")
    store.write_text("_cluster/nodes/a.json", "two\n")
    assert store.read_text("_cluster/nodes/a.json") == "two\n"


def test_two_exclusive_creates_give_one_winner(store: LocalFolderStore) -> None:
    store.create_exclusive("_cluster/nodes/a.json", "winner\n")
    with pytest.raises(Exists):
        store.create_exclusive("_cluster/nodes/a.json", "loser\n")
    assert store.read_text("_cluster/nodes/a.json") == "winner\n"


def test_a_missing_file_is_not_found(store: LocalFolderStore) -> None:
    with pytest.raises(NotFound):
        store.read_text("_cluster/nodes/missing.json")
    with pytest.raises(NotFound):
        store.list_dir("_cluster/absent")


def test_dot_prefixed_names_are_not_listed_unless_asked(
    store: LocalFolderStore, tmp_path: Path
) -> None:
    (tmp_path / "_cluster" / "nodes" / ".probe-x").write_text("p", encoding="utf-8")
    store.write_text("_cluster/nodes/b.json", "b\n")
    assert [entry.name for entry in store.list_dir("_cluster/nodes").entries] == ["b.json"]
    hidden = store.list_dir("_cluster/nodes", hidden=True).entries
    assert [entry.name for entry in hidden] == [".probe-x", "b.json"]


def test_a_folder_that_refuses_hard_links_is_a_store_error_not_exists(
    store: LocalFolderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(source: object, target: object) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", refuse)
    with pytest.raises(StoreError) as caught:
        store.create_exclusive("_cluster/nodes/a.json", "x\n")
    assert caught.value.kind == "hard-link-refused"


def test_move_without_replace_refuses_an_existing_target(store: LocalFolderStore) -> None:
    store.write_text("_cluster/nodes/a.json", "a\n")
    store.write_text("_cluster/nodes/b.json", "b\n")
    with pytest.raises(Exists):
        store.move("_cluster/nodes/a.json", "_cluster/nodes/b.json", replace=False)
    assert store.read_text("_cluster/nodes/b.json") == "b\n"


def test_paths_cannot_leave_the_folder(store: LocalFolderStore) -> None:
    with pytest.raises(StoreError):
        store.read_text("../outside.json")
