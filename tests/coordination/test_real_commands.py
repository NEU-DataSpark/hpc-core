"""Layer L2: the command store's argument tuples run with the host's real GNU commands.

The store conformance script runs through ``SubprocessTransport`` in a temporary folder, so the
command table, the exit-status and message mapping, and the ``LC_ALL=C`` assumption are checked
against real output. The module is skipped, naming the missing feature, on a host without GNU tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hpc_core.coordination.command_store import CommandFolderStore
from hpc_core.coordination.store import Exists, NotFound, StoreError
from hpc_core.testing import MemoryFolderStore
from hpc_core.testing.contract import check_store_conformance, run_store_script
from hpc_core.testing.subprocess_transport import SubprocessTransport, missing_gnu_feature

_MISSING = missing_gnu_feature()
pytestmark = pytest.mark.skipif(
    _MISSING is not None, reason=f"real-command layer skipped: {_MISSING}"
)


@pytest.fixture
def folder(tmp_path: Path) -> CommandFolderStore:
    team = tmp_path / "team"
    team.mkdir()
    return CommandFolderStore(SubprocessTransport(team), str(team))


def test_the_conformance_script_matches_the_reference_on_real_commands(
    folder: CommandFolderStore,
) -> None:
    check_store_conformance(folder)


def test_real_commands_give_the_same_transcript_as_the_memory_store(
    folder: CommandFolderStore,
) -> None:
    assert run_store_script(folder) == run_store_script(MemoryFolderStore())


def test_exit_status_and_message_map_to_not_found_and_exists(folder: CommandFolderStore) -> None:
    folder.make_dirs("_cluster/nodes")
    with pytest.raises(NotFound):
        folder.read_text("_cluster/nodes/none.json")
    folder.create_exclusive("_cluster/nodes/a.json", "one\n")
    with pytest.raises(Exists):
        folder.create_exclusive("_cluster/nodes/a.json", "two\n")
    assert folder.read_text("_cluster/nodes/a.json") == "one\n"


def test_a_write_into_a_missing_folder_is_a_store_error(folder: CommandFolderStore) -> None:
    with pytest.raises(StoreError):
        folder.write_text("_cluster/absent/a.json", "x\n")


def test_the_real_hard_link_and_rename_leave_no_temporary_file(
    folder: CommandFolderStore, tmp_path: Path
) -> None:
    folder.make_dirs("_cluster/nodes")
    folder.write_text("_cluster/nodes/a.json", "a\n")
    folder.create_exclusive("_cluster/nodes/b.json", "b\n")
    names = sorted(path.name for path in (tmp_path / "team" / "_cluster" / "nodes").iterdir())
    assert names == ["a.json", "b.json"]


def test_standard_input_arrives_byte_for_byte(folder: CommandFolderStore) -> None:
    text = '{"node_id":"a","note":"quote \\" and newline\\n"}\n'
    folder.make_dirs("_cluster/nodes")
    folder.write_text("_cluster/nodes/a.json", text)
    assert folder.read_text("_cluster/nodes/a.json") == text


def test_a_host_without_a_needed_tool_is_named_for_the_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda program: None if program == "find" else "/bin/x")
    assert missing_gnu_feature() == "the host has no 'find' command"
