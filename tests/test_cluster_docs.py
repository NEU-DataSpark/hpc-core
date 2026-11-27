"""Every ``hpc-core cluster`` command the docs show parses with the real command line."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from hpc_core.cli import build_parser

DOCS = Path(__file__).resolve().parent.parent / "docs"
DOCUMENTED = ("cluster-coordination.md", "cli.md")
_CODE_SPAN = re.compile(r"`(hpc-core cluster [^`]+)`")


def _documented_commands() -> list[str]:
    commands: list[str] = []
    for name in DOCUMENTED:
        commands.extend(_CODE_SPAN.findall((DOCS / name).read_text(encoding="utf-8")))
    return commands


def test_the_docs_show_cluster_commands() -> None:
    commands = _documented_commands()
    assert len(commands) >= 10
    assert {shlex.split(c)[2] for c in commands} >= {
        "init",
        "nodes",
        "beat",
        "leave",
        "send",
        "inbox",
        "ack",
        "limits",
        "check",
    }


@pytest.mark.parametrize("command", _documented_commands())
def test_every_documented_cluster_command_parses(command: str) -> None:
    argv = shlex.split(command)[1:]
    namespace = build_parser().parse_args(argv)
    assert getattr(namespace, "handler", None) is not None
