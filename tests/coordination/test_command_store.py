"""The command store: argument tuples only, content on standard input, and transport errors that
never look like a missing file."""

from __future__ import annotations

import pytest

from hpc_core.coordination.command_store import REQUIRED_COMMANDS, CommandFolderStore
from hpc_core.coordination.store import Exists, NotFound, StoreError
from hpc_core.testing import FakeTransport, MemoryFolderStore, SimulatedFolderTransport
from hpc_core.transport.protocol import CommandResult, TransportError, TransportTimeout

ROOT = "/team"


def _simulated() -> tuple[CommandFolderStore, SimulatedFolderTransport]:
    folder = MemoryFolderStore()
    transport = SimulatedFolderTransport(folder, ROOT)
    return CommandFolderStore(transport, ROOT), transport


def test_every_call_is_an_argument_tuple_and_content_is_only_on_stdin() -> None:
    store, transport = _simulated()
    secret_text = '{"node_id":"alice","token":"abc"}\n'
    store.make_dirs("_cluster/nodes")
    store.write_text("_cluster/nodes/alice.json", secret_text)
    store.create_exclusive("_cluster/nodes/bob.json", secret_text)
    store.read_text("_cluster/nodes/alice.json")
    for argv in transport.calls:
        assert isinstance(argv, tuple)
        assert all(secret_text not in argument and "token" not in argument for argument in argv)
    assert secret_text in transport.inputs


def test_a_transport_error_is_a_store_error_never_not_found() -> None:
    transport = FakeTransport({"env": TransportError("login node unreachable")})
    store = CommandFolderStore(transport, ROOT)
    with pytest.raises(StoreError) as caught:
        store.read_text("_cluster/nodes/a.json")
    assert caught.value.kind == "unreachable"


def test_a_timeout_is_a_store_error_never_not_found() -> None:
    class Slow(FakeTransport):
        def run(
            self,
            argv: tuple[str, ...],
            *,
            timeout: float,
            max_output_bytes: int,
            input: str | None = None,
        ) -> CommandResult:
            del argv, timeout, max_output_bytes, input
            raise TransportTimeout("slow")

    with pytest.raises(StoreError):
        CommandFolderStore(Slow({}), ROOT).list_dir("_cluster/nodes")


def test_truncated_output_is_a_store_error() -> None:
    class Cut:
        def run(
            self,
            argv: tuple[str, ...],
            *,
            timeout: float,
            max_output_bytes: int,
            input: str | None = None,
        ) -> CommandResult:
            del argv, timeout, max_output_bytes, input
            return CommandResult("partial", "", 0, truncated=True)

    with pytest.raises(StoreError) as caught:
        CommandFolderStore(Cut(), ROOT).read_text("_cluster/nodes/a.json")
    assert caught.value.kind == "truncated"


def test_a_missing_command_is_named_once_before_first_use() -> None:
    class NoGrep:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(
            self,
            argv: tuple[str, ...],
            *,
            timeout: float,
            max_output_bytes: int,
            input: str | None = None,
        ) -> CommandResult:
            del timeout, max_output_bytes, input
            self.calls.append(argv)
            program = argv[2]
            if program == "grep":
                return CommandResult("", "env: 'grep': No such file or directory\n", 127)
            return CommandResult("ok\n", "", 0)

    transport = NoGrep()
    store = CommandFolderStore(transport, ROOT)
    with pytest.raises(StoreError) as caught:
        store.now()
    assert caught.value.kind == "missing-command"
    assert "'grep'" in str(caught.value)
    checks = [call for call in transport.calls if call[-1] == "--version"]
    assert [call[2] for call in checks][: len(REQUIRED_COMMANDS)] == list(REQUIRED_COMMANDS)[
        : len(checks)
    ]


def test_not_found_and_exists_come_from_the_command_messages() -> None:
    store, _ = _simulated()
    with pytest.raises(NotFound):
        store.read_text("_cluster/nodes/missing.json")
    store.make_dirs("_cluster/nodes")
    store.create_exclusive("_cluster/nodes/a.json", "a\n")
    with pytest.raises(Exists):
        store.create_exclusive("_cluster/nodes/a.json", "b\n")


def test_the_store_needs_an_absolute_root() -> None:
    with pytest.raises(ValueError):
        CommandFolderStore(FakeTransport({}), "relative/path")
