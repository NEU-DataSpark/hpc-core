"""One scripted sequence gives the same results on the local store, the memory store and the command
store over the simulated folder. This is the consumer-facing guarantee of the store interface."""

from __future__ import annotations

from pathlib import Path

from hpc_core.coordination.command_store import CommandFolderStore
from hpc_core.coordination.store import LocalFolderStore
from hpc_core.testing import MemoryFolderStore, SimulatedFolderTransport
from hpc_core.testing.contract import check_store_conformance, run_store_script

ROOT = "/team"


def _command_store() -> CommandFolderStore:
    folder = MemoryFolderStore()
    return CommandFolderStore(SimulatedFolderTransport(folder, ROOT), ROOT)


def test_the_script_gives_the_same_results_on_all_three_stores(tmp_path: Path) -> None:
    local = run_store_script(LocalFolderStore(tmp_path))
    memory = run_store_script(MemoryFolderStore())
    command = run_store_script(_command_store())
    assert local == memory == command
    assert ("create-a-again", "exists") in local
    assert ("read-missing", "not-found") in local


def test_the_consumer_check_accepts_a_conforming_store(tmp_path: Path) -> None:
    check_store_conformance(LocalFolderStore(tmp_path))
    check_store_conformance(_command_store())
