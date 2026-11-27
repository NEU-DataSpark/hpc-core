"""The run-report CSV contract: columns, schema version, a formatter and a strict reader.

The writer and the reader here are the reference. A consumer that writes or reads reports runs
the contract checks in ``hpc_core.testing`` against its own code.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .identifiers import is_job_id
from .times import format_time, parse_report_time

COLUMNS: tuple[str, ...] = (
    "schema_version",
    "job_id",
    "job_name",
    "partition",
    "stage",
    "sample_time",
    "scheduler_state",
    "submit_time",
    "start_time",
    "end_time",
    "wait_seconds",
    "elapsed_seconds",
    "cpus_alloc",
    "cpu_seconds_used",
    "mem_peak_mb",
    "gpus_alloc",
    "gpu_type",
    "gpu_util_pct",
    "gpu_mem_mb",
    "source",
    "unavailable",
    "report_status",
)
SCHEMA_VERSION = 1
SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})
STAGES: frozenset[str] = frozenset({"pre", "running", "post"})
REPORT_STATUSES: frozenset[str] = frozenset({"in_progress", "complete", "samples_only"})
SOURCE_PARTS: frozenset[str] = frozenset({"squeue", "sstat", "nvidia-smi", "sacct", "samples"})

_INT_COLUMNS = frozenset(
    {"schema_version", "wait_seconds", "elapsed_seconds", "cpus_alloc", "gpus_alloc"}
)
_FLOAT_COLUMNS = frozenset({"cpu_seconds_used", "mem_peak_mb", "gpu_util_pct", "gpu_mem_mb"})
_TIME_COLUMNS = frozenset({"sample_time", "submit_time", "start_time", "end_time"})
_REQUIRED_READ = frozenset({"schema_version", "job_id", "stage", "sample_time"})


class ReportError(ValueError):
    """The whole report is refused. The message names what was wrong."""


class RowError(ValueError):
    """One row cannot be read. The reader skips it and counts it."""


def is_valid_source(source: str) -> bool:
    parts = source.split("+")
    return all(part in SOURCE_PARTS for part in parts)


@dataclass(frozen=True)
class ReportRow:
    """One report row. Blank in the CSV reads as None; a real zero stays 0."""

    schema_version: int = SCHEMA_VERSION
    job_id: str = ""
    job_name: str | None = None
    partition: str | None = None
    stage: str = ""
    sample_time: datetime | None = None
    scheduler_state: str | None = None
    submit_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    wait_seconds: int | None = None
    elapsed_seconds: int | None = None
    cpus_alloc: int | None = None
    cpu_seconds_used: float | None = None
    mem_peak_mb: float | None = None
    gpus_alloc: int | None = None
    gpu_type: str | None = None
    gpu_util_pct: float | None = None
    gpu_mem_mb: float | None = None
    source: str = ""
    unavailable: str | None = None
    report_status: str = ""

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_VERSIONS:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        if not is_job_id(self.job_id):
            raise ValueError("job_id is not a valid job id")
        if self.stage not in STAGES:
            raise ValueError("stage is outside pre, running, post")
        if self.report_status not in REPORT_STATUSES:
            raise ValueError("report_status is outside in_progress, complete, samples_only")
        if not is_valid_source(self.source):
            raise ValueError("source is outside the known sources")
        if self.sample_time is None:
            raise ValueError("sample_time is required")


def _format_float(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _format_cell(column: str, value: object) -> str:
    if value is None:
        return ""
    if column in _TIME_COLUMNS:
        if not isinstance(value, datetime):
            raise ValueError(f"{column} must be a datetime")
        return format_time(value)
    if column in _INT_COLUMNS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{column} must be a whole number")
        return str(value)
    if column in _FLOAT_COLUMNS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{column} must be a number")
        return _format_float(float(value))
    return str(value)


def format_row(row: ReportRow) -> list[str]:
    """One row in COLUMNS order. Whole numbers have no decimal point; unset values are empty."""
    return [_format_cell(column, getattr(row, column)) for column in COLUMNS]


def format_report(rows: Iterable[ReportRow]) -> str:
    """The header and the rows as CSV text with ``\\n`` line endings."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(format_row(row))
    return buffer.getvalue()


@dataclass(frozen=True)
class ReadResult:
    rows: tuple[ReportRow, ...]
    skipped: int


def _cell_int(cells: dict[str, str], column: str, *, required: bool = False) -> int | None:
    text = cells.get(column, "").strip()
    if not text:
        if required:
            raise RowError(column)
        return None
    if not text.isdigit():
        raise RowError(column)
    return int(text)


def _cell_float(cells: dict[str, str], column: str) -> float | None:
    text = cells.get(column, "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as error:
        raise RowError(column) from error
    if not math.isfinite(value) or value < 0:
        raise RowError(column)
    return value


def _cell_time(cells: dict[str, str], column: str, *, required: bool = False) -> datetime | None:
    text = cells.get(column, "").strip()
    if not text:
        if required:
            raise RowError(column)
        return None
    try:
        return parse_report_time(text)
    except ValueError as error:
        raise RowError(column) from error


def _cell_text(cells: dict[str, str], column: str) -> str | None:
    text = cells.get(column, "")
    return text if text else None


def _cell_closed(cells: dict[str, str], column: str, allowed: frozenset[str]) -> str:
    text = cells.get(column, "")
    if text not in allowed:
        raise RowError(column)
    return text


def _row_from_cells(cells: dict[str, str]) -> ReportRow:
    job_id = cells.get("job_id", "")
    if not is_job_id(job_id):
        raise RowError("job_id")
    source = cells.get("source", "")
    if not source or not is_valid_source(source):
        raise RowError("source")
    sample_time = _cell_time(cells, "sample_time", required=True)
    try:
        return ReportRow(
            schema_version=_cell_int(cells, "schema_version", required=True) or 0,
            job_id=job_id,
            job_name=_cell_text(cells, "job_name"),
            partition=_cell_text(cells, "partition"),
            stage=_cell_closed(cells, "stage", STAGES),
            sample_time=sample_time,
            scheduler_state=_cell_text(cells, "scheduler_state"),
            submit_time=_cell_time(cells, "submit_time"),
            start_time=_cell_time(cells, "start_time"),
            end_time=_cell_time(cells, "end_time"),
            wait_seconds=_cell_int(cells, "wait_seconds"),
            elapsed_seconds=_cell_int(cells, "elapsed_seconds"),
            cpus_alloc=_cell_int(cells, "cpus_alloc"),
            cpu_seconds_used=_cell_float(cells, "cpu_seconds_used"),
            mem_peak_mb=_cell_float(cells, "mem_peak_mb"),
            gpus_alloc=_cell_int(cells, "gpus_alloc"),
            gpu_type=_cell_text(cells, "gpu_type"),
            gpu_util_pct=_cell_float(cells, "gpu_util_pct"),
            gpu_mem_mb=_cell_float(cells, "gpu_mem_mb"),
            source=source,
            unavailable=_cell_text(cells, "unavailable"),
            report_status=_cell_closed(cells, "report_status", REPORT_STATUSES),
        )
    except (ValueError, RowError) as error:
        raise RowError(str(error)) from error


def read_report(text: str) -> ReadResult:
    """Read a run report by column name.

    Refuses the whole report, with no rows, when the header lacks a required column or a row's
    ``schema_version`` is not supported; the message names the version. Otherwise rows that cannot
    be read are skipped and counted, and the rest are returned.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = [name.strip() for name in next(reader)]
    except StopIteration as error:
        raise ReportError("report is empty: no header") from error
    if len(set(header)) != len(header):
        raise ReportError("report header repeats a column name")
    index = {name: position for position, name in enumerate(header)}
    for column in sorted(_REQUIRED_READ):
        if column not in index:
            raise ReportError(f"report has no '{column}' column")

    rows: list[ReportRow] = []
    skipped = 0
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        cells = {
            name: (raw[position] if position < len(raw) else "") for name, position in index.items()
        }
        version_text = cells.get("schema_version", "").strip()
        if version_text.isdigit() and int(version_text) not in SUPPORTED_VERSIONS:
            raise ReportError(
                f"unsupported schema_version {int(version_text)}; this package reads "
                + ", ".join(str(v) for v in sorted(SUPPORTED_VERSIONS))
            )
        try:
            rows.append(_row_from_cells(cells))
        except RowError:
            skipped += 1
    return ReadResult(tuple(rows), skipped)
