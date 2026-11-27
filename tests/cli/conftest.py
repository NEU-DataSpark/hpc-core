"""Shared helpers for the command-line tests: run ``main`` and capture what it writes."""

from __future__ import annotations

import io
import sys
from collections.abc import Callable

import pytest

from hpc_core.cli import main

RunCli = Callable[..., tuple[int, str, str]]
FeedStdin = Callable[[str], None]


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> RunCli:
    """Run the command line in process. Returns (exit status, standard output, standard error)."""

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


@pytest.fixture
def feed_stdin(monkeypatch: pytest.MonkeyPatch) -> FeedStdin:
    """Replace standard input with the given text."""

    def feed(text: str) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))

    return feed
