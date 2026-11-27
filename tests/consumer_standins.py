"""Stand-ins for a consumer's reader and writer.

The examples in docs/consumer-contract-test.md run against these.

They are written apart from the package's own reader and writer. A pass therefore means the checks
accept an independent implementation of the same contract.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import datetime

from hpc_core.contract.report import COLUMNS, ReportRow

_INTEGER_COLUMNS = ("schema_version", "wait_seconds", "elapsed_seconds", "cpus_alloc", "gpus_alloc")


def standin_reader(text: str) -> tuple[list[dict[str, str]], int]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    if "schema_version" not in header:
        raise ValueError("missing schema_version column")
    index = {name: position for position, name in enumerate(header)}
    version_column = index["schema_version"]
    rows: list[dict[str, str]] = []
    skipped = 0
    for cells in reader:
        if not cells:
            continue
        version = cells[version_column] if version_column < len(cells) else ""
        if version != "1":
            raise ValueError(f"unsupported schema_version {version}")
        if len(cells) != len(header) or not all(
            cells[index[name]].isdigit() or cells[index[name]] == ""
            for name in _INTEGER_COLUMNS
            if name in index
        ):
            skipped += 1
            continue
        rows.append({name: cells[index[name]] for name in header})
    return rows, skipped


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def standin_writer(samples: Sequence[ReportRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for sample in samples:
        writer.writerow([_cell(getattr(sample, column)) for column in COLUMNS])
    return buffer.getvalue()
