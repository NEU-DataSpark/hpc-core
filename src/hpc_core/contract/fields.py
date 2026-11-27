"""Named field profiles, the records parsers return, and the row splitter.

A profile names the columns a command was asked for, in order. Cells are read by name, so a field
the profile does not name is unset on the record. A free-text field (a job name) may only be the
last field, so a separator inside it cannot shift the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from .states import StateClass

SUPPORTED_COMMANDS: frozenset[str] = frozenset({"squeue", "sacct", "sinfo", "sstat"})


class ProfileError(ValueError):
    """A field profile that breaks the rules. The message names the offending field."""


@dataclass(frozen=True)
class Field:
    name: str
    token: str
    free_text: bool = False


@dataclass(frozen=True)
class FieldProfile:
    name: str
    command: str
    fields: tuple[Field, ...]
    separator: str = "|"

    def __post_init__(self) -> None:
        if self.command not in SUPPORTED_COMMANDS:
            raise ProfileError(f"profile '{self.name}': unsupported command '{self.command}'")
        if len(self.separator) != 1 or self.separator.isspace() or self.separator in ",%":
            raise ProfileError(f"profile '{self.name}': separator must be one plain character")
        if not self.fields:
            raise ProfileError(f"profile '{self.name}': no fields")
        names = [item.name for item in self.fields]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ProfileError(f"profile '{self.name}': duplicate field '{duplicates[0]}'")
        for item in self.fields:
            if not item.token or any(ch in item.token for ch in ", \t\n"):
                raise ProfileError(f"profile '{self.name}': bad token for field '{item.name}'")
        for item in self.fields[:-1]:
            if item.free_text:
                raise ProfileError(
                    f"profile '{self.name}': free-text field '{item.name}' must be the last field"
                )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)


T = TypeVar("T")


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    records: tuple[T, ...]
    skipped: int


def check_known_names(profile: FieldProfile, known: frozenset[str]) -> None:
    for name in profile.names:
        if name not in known:
            raise ProfileError(
                f"profile '{profile.name}': field '{name}' is not read by {profile.command}"
            )


def iter_rows(text: str, profile: FieldProfile) -> tuple[list[dict[str, str]], int]:
    """Split command output into rows keyed by field name. Returns (good rows, skipped count).

    Blank lines are not rows and are not counted. A row with too few cells is skipped; so is a row
    with extra cells unless the last field is free text, which keeps any extra separators.
    """
    width = len(profile.fields)
    last = profile.fields[-1]
    good: list[dict[str, str]] = []
    skipped = 0
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        cells = line.split(profile.separator)
        if last.free_text:
            if len(cells) < width:
                skipped += 1
                continue
            cells = cells[: width - 1] + [profile.separator.join(cells[width - 1 :])]
        elif len(cells) != width:
            skipped += 1
            continue
        row = {
            item.name: (cell if item.free_text else cell.strip())
            for item, cell in zip(profile.fields, cells, strict=True)
        }
        good.append(row)
    return good, skipped


@dataclass(frozen=True)
class JobRecord:
    """One job row from squeue or sacct. Every field is unset unless the profile named it and

    the cell was readable.
    """

    job_id: str
    job_name: str | None = None
    partition: str | None = None
    state: str | None = None
    state_class: StateClass | None = None
    reason: str | None = None
    submit_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    cpus_requested: int | None = None
    cpus_allocated: int | None = None
    gpus_requested: int | None = None
    gpus_allocated: int | None = None
    gpu_type: str | None = None
    total_cpu_seconds: float | None = None
    max_rss_mib: float | None = None
    time_limit_seconds: float | None = None


@dataclass(frozen=True)
class SstatRecord:
    """One job step row from sstat."""

    step_id: str
    ave_cpu_seconds: float | None = None
    ntasks: int | None = None
    max_rss_mib: float | None = None


@dataclass(frozen=True)
class NodeRecord:
    """One partition row from sinfo."""

    partition: str | None = None
    gres: str | None = None
    state: str | None = None
    node_count: int | None = None
    gpus_per_node: int | None = None
    gpu_type: str | None = None
