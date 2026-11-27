"""The entry points: --version, the no-command usage error, and help text that matches across the
console command and ``python -m hpc_core``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from conftest import RunCli

from hpc_core.cli import build_parser

PROJECT = Path(__file__).resolve().parents[2]


def _package_version() -> str:
    data = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def _console_script() -> Path:
    return Path(sys.executable).parent / "hpc-core"


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "COLUMNS": "100"}
    return subprocess.run(argv, capture_output=True, text=True, check=False, env=env, timeout=120)


def test_version_prints_the_package_version_and_exits_0(run_cli: RunCli) -> None:
    code, out, err = run_cli("--version")
    assert code == 0
    assert out.strip() == _package_version()
    assert err == ""


def test_no_command_prints_usage_to_standard_error_and_exits_2(run_cli: RunCli) -> None:
    code, out, err = run_cli()
    assert code == 2
    assert out == ""
    assert err.startswith("usage: hpc-core")


def test_a_group_without_its_command_exits_2(run_cli: RunCli) -> None:
    code, out, err = run_cli("parse")
    assert code == 2
    assert out == ""
    assert "COMMAND" in err


def test_help_lists_every_command_group(run_cli: RunCli) -> None:
    code, out, _ = run_cli("--help")
    assert code == 0
    for group in ("parse", "report", "commands", "skills"):
        assert group in out


def test_the_console_command_and_python_m_print_the_same_help() -> None:
    console = _console_script()
    assert console.exists(), "install the project first: uv sync --extra dev"
    via_console = _run([str(console), "--help"])
    via_module = _run([sys.executable, "-m", "hpc_core", "--help"])
    assert via_console.returncode == 0
    assert via_module.returncode == 0
    assert via_console.stdout == via_module.stdout


def test_python_m_runs_the_same_parser() -> None:
    result = _run([sys.executable, "-m", "hpc_core", "parse", "squeue", "--help"])
    assert result.returncode == 0
    assert "--profile" in result.stdout


def test_build_parser_has_the_five_groups() -> None:
    parser = build_parser()
    (groups,) = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    assert set(groups.choices) == {"parse", "report", "commands", "skills", "cluster"}
