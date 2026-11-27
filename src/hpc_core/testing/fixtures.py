"""Loader for the fixtures packaged in ``hpc_core/testing/fixtures``.

Two kinds of case:

- ``scheduler``: a recorded ``squeue``, ``sacct``, ``sinfo`` or ``sstat`` output in ``scheduler/``.
  Leading ``#`` lines are a header (recording month, Slurm version, command); they are not command
  output and are stripped before a parser sees the text. The expected JSON names the profile and
  holds the records and the skipped count.
- ``report``: a run-report CSV in ``reports/``. Its expected JSON is either the cells and skipped
  count the reader must return, or a refusal whose message must contain a given text.

Every case also has an ``<name>.expected.json`` beside it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from ..contract import sacct, sinfo, squeue, sstat
from ..contract.fields import FieldProfile, ParseResult
from ..contract.times import format_time

KINDS: tuple[str, ...] = ("report", "scheduler")

PROFILES: dict[tuple[str, str], FieldProfile] = {
    ("squeue", "operator-sampling"): squeue.OPERATOR_SAMPLING,
    ("sacct", "operator-sampling"): sacct.OPERATOR_SAMPLING,
    ("sacct", "console-monitor"): sacct.CONSOLE_MONITOR,
    ("sinfo", "capacity"): sinfo.CAPACITY,
    ("sstat", "running-usage"): sstat.DEFAULT,
}
PARSERS: dict[str, Callable[[str, FieldProfile], ParseResult[Any]]] = {
    "squeue": squeue.parse_squeue,
    "sacct": sacct.parse_sacct,
    "sinfo": sinfo.parse_sinfo,
    "sstat": sstat.parse_sstat,
}


@dataclass(frozen=True)
class Case:
    kind: str
    name: str
    text: str
    header: tuple[str, ...]
    expected: dict[str, Any]


def fixture_root() -> Path:
    return Path(str(resources.files("hpc_core.testing") / "fixtures"))


def split_header(text: str) -> tuple[tuple[str, ...], str]:
    """Separate the leading ``#`` lines (the header) from the command output."""
    header: list[str] = []
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines) and lines[index].startswith("#"):
        header.append(lines[index].rstrip("\r\n"))
        index += 1
    return tuple(header), "".join(lines[index:])


def _read_case(kind: str, path: Path) -> Case:
    expected_path = path.with_name(path.name.rsplit(".", 1)[0] + ".expected.json")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    raw = path.read_text(encoding="utf-8")
    if kind == "scheduler":
        header, body = split_header(raw)
    else:
        header, body = (), raw
    return Case(
        kind=kind, name=path.name.rsplit(".", 1)[0], text=body, header=header, expected=expected
    )


def load_cases(kind: str | None = None) -> list[Case]:
    """Every case of a kind (or of all kinds), sorted by kind and name."""
    kinds = KINDS if kind is None else (kind,)
    cases: list[Case] = []
    for current in kinds:
        if current not in KINDS:
            raise ValueError(f"unknown fixture kind: {current}")
        directory = fixture_root() / ("reports" if current == "report" else "scheduler")
        pattern = "*.csv" if current == "report" else "*.txt"
        for path in sorted(directory.glob(pattern)):
            cases.append(_read_case(current, path))
    return cases


def load_case(kind: str, name: str) -> Case:
    for case in load_cases(kind):
        if case.name == name:
            return case
    raise KeyError(f"no {kind} case named {name!r}")


def to_json_value(value: object) -> object:
    """A JSON-ready form of a record: times in the report's UTC ``Z`` form, dataclasses as dicts."""
    if isinstance(value, datetime):
        return format_time(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple | list):
        return [to_json_value(item) for item in value]
    return value


def run_scheduler_case(case: Case) -> dict[str, Any]:
    """Parse a scheduler case with the profile its expected JSON names."""
    command = case.expected["command"]
    profile = PROFILES[(command, case.expected["profile"])]
    result = PARSERS[command](case.text, profile)
    return {
        "records": to_json_value(result.records),
        "skipped": result.skipped,
    }
