"""The two guarantees of the command line: failed rows are never printed, and nothing goes online.

The sentinel strings match no hygiene rule and no legitimate output, so finding one in standard
output or standard error means a failed row leaked.
"""

from __future__ import annotations

import csv
import io
import os
import socket
import subprocess
from pathlib import Path

import pytest
from conftest import RunCli

from hpc_core.contract.report import COLUMNS
from hpc_core.testing import load_cases

SENTINEL_HOST = "SENTINEL-HOST-7731"
SENTINEL_PATH = "SENTINEL-PATH-7731"
SCHEDULER_PROFILES = [
    ("squeue", "operator-sampling"),
    ("squeue", "console-monitor"),
    ("sacct", "operator-sampling"),
    ("sacct", "console-monitor"),
    ("sinfo", "capacity"),
    ("sstat", "running-usage"),
]


def _poisoned_scheduler_text() -> str:
    """Rows that cannot be read for any profile: a blank first cell, or the wrong width."""
    rows = [f"{SENTINEL_HOST}|{SENTINEL_PATH}"]
    for width in range(1, 16):
        rows.append("|".join([""] + [SENTINEL_HOST] * (width - 1)))
        rows.append("\x1f".join([""] + [SENTINEL_PATH] * (width - 1)))
    return "\n".join(rows) + "\n"


def _poisoned_report_text() -> str:
    cells = {column: SENTINEL_PATH for column in COLUMNS}
    cells["schema_version"] = "1"
    cells["job_id"] = SENTINEL_HOST
    cells["sample_time"] = SENTINEL_PATH
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerow([cells[column] for column in COLUMNS])
    return buffer.getvalue()


@pytest.mark.parametrize(("command", "profile"), SCHEDULER_PROFILES)
def test_failed_scheduler_rows_are_counted_and_never_printed(
    run_cli: RunCli, tmp_path: Path, command: str, profile: str
) -> None:
    source = tmp_path / "output.txt"
    source.write_text(_poisoned_scheduler_text(), encoding="utf-8")
    code, out, err = run_cli("parse", command, "--profile", profile, str(source))
    assert code == 0
    assert '"records": []' in out
    assert '"skipped": 0' not in out
    assert SENTINEL_HOST not in out + err
    assert SENTINEL_PATH not in out + err


@pytest.mark.parametrize("subcommand", ["validate", "metrics"])
def test_failed_report_rows_are_counted_and_never_printed(
    run_cli: RunCli, tmp_path: Path, subcommand: str
) -> None:
    source = tmp_path / "run-report.csv"
    source.write_text(_poisoned_report_text(), encoding="utf-8")
    code, out, err = run_cli("report", subcommand, str(source))
    assert code == 1
    assert SENTINEL_HOST not in out + err
    assert SENTINEL_PATH not in out + err


def test_a_refused_report_names_no_row(run_cli: RunCli, tmp_path: Path) -> None:
    source = tmp_path / "run-report.csv"
    header = ",".join(COLUMNS)
    source.write_text(f"{header}\n99,{SENTINEL_HOST}\n", encoding="utf-8")
    code, out, err = run_cli("report", "validate", str(source))
    assert code == 1
    assert out == ""
    assert SENTINEL_HOST not in err


@pytest.fixture
def no_network_or_program(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any attempt to open a connection or start a program raise."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("the command line opened a connection or started a program")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "call", blocked)
    monkeypatch.setattr(subprocess, "check_output", blocked)
    monkeypatch.setattr(os, "system", blocked)
    monkeypatch.setattr(os, "popen", blocked)


def test_every_command_runs_offline(
    run_cli: RunCli, tmp_path: Path, no_network_or_program: None
) -> None:
    scheduler = next(c for c in load_cases("scheduler") if c.name == "squeue-operator")
    capacity = next(c for c in load_cases("scheduler") if c.name == "sinfo-capacity")
    report = next(c for c in load_cases("report") if c.name == "finished_run")
    scheduler_file = tmp_path / "squeue.txt"
    scheduler_file.write_text(scheduler.text, encoding="utf-8")
    capacity_file = tmp_path / "sinfo.txt"
    capacity_file.write_text(capacity.text, encoding="utf-8")
    report_file = tmp_path / "run-report.csv"
    report_file.write_text(report.text, encoding="utf-8")

    argv_list: list[tuple[str, ...]] = [
        ("--version",),
        ("--help",),
        ("parse", "squeue", str(scheduler_file)),
        ("parse", "sinfo", "--profile", "capacity", str(capacity_file)),
        ("report", "validate", str(report_file)),
        ("report", "metrics", str(report_file)),
        ("report", "schema"),
        ("commands", "queue", "--account", "example-account"),
        ("commands", "finished", "--account", "example-account", "--hours", "24"),
        ("commands", "job", "4812201"),
        ("commands", "usage", "4812201"),
        ("commands", "capacity"),
        ("skills", "list"),
        ("skills", "install", str(tmp_path / "skills")),
    ]
    # The guard raises AssertionError, which run_cli does not catch, so any call fails the test.
    for argv in argv_list:
        run_cli(*argv)
