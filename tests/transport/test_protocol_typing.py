"""mypy --strict accepts a class that implements the protocol and rejects one that takes a

shell string.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

GOOD = """
from hpc_core.transport.protocol import CommandResult, CommandTransport

class Good:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
        input: str | None = None,
    ) -> CommandResult:
        return CommandResult(stdout="", stderr="", exit_status=0)

transport: CommandTransport = Good()
"""

SHELL_STRING = """
from hpc_core.transport.protocol import CommandResult, CommandTransport

class ShellString:
    def run(self, command: str, *, timeout: float, max_output_bytes: int) -> CommandResult:
        return CommandResult(stdout="", stderr="", exit_status=0)

transport: CommandTransport = ShellString()
"""


def _mypy(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    module = tmp_path / "snippet.py"
    module.write_text(textwrap.dedent(source), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(module)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )


def test_class_implementing_the_protocol_passes(tmp_path: Path) -> None:
    result = _mypy(tmp_path, GOOD)
    assert result.returncode == 0, result.stdout + result.stderr


def test_class_taking_a_shell_string_is_rejected(tmp_path: Path) -> None:
    result = _mypy(tmp_path, SHELL_STRING)
    assert result.returncode != 0
    assert "CommandTransport" in result.stdout
