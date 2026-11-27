"""``hpc-core report``: check a run-report CSV, print its metrics and describe its schema."""

from __future__ import annotations

import argparse

from ..contract.metrics import cpu_hours, gpu_hours
from ..contract.report import (
    COLUMNS,
    SCHEMA_VERSION,
    SUPPORTED_VERSIONS,
    ReadResult,
    ReportRow,
    read_report,
)
from ._io import EXIT_OK, EXIT_UNACCEPTABLE, STDIN_MARK, fail, print_json, read_text


def _read(source: str) -> ReadResult:
    """The readable rows and the skipped count. Raises ReportError for a refused report."""
    return read_report(read_text(source))


def _skipped_status(skipped: int) -> int:
    """Exit 1 when rows were skipped: the input was read but is not fully acceptable."""
    if skipped == 0:
        return EXIT_OK
    return fail(f"{skipped} row(s) could not be read and were skipped", EXIT_UNACCEPTABLE)


def validate_run(args: argparse.Namespace) -> int:
    result = _read(args.input)
    print_json(
        {
            "schema_versions": sorted({row.schema_version for row in result.rows}),
            "supported_versions": sorted(SUPPORTED_VERSIONS),
            "rows": len(result.rows),
            "skipped": result.skipped,
        }
    )
    return _skipped_status(result.skipped)


def _metrics_for(row: ReportRow) -> dict[str, object]:
    """One row: its stored values, plus the hour totals computed from its allocation.

    A value the row leaves blank stays null, and a real zero stays 0.
    """
    return {
        "job_id": row.job_id,
        "stage": row.stage,
        "sample_time": row.sample_time,
        "source": row.source,
        "report_status": row.report_status,
        "unavailable": row.unavailable,
        "wait_seconds": row.wait_seconds,
        "elapsed_seconds": row.elapsed_seconds,
        "cpu_hours": cpu_hours(row.cpus_alloc, row.elapsed_seconds),
        "gpu_hours": gpu_hours(row.gpus_alloc, row.elapsed_seconds),
        "cpu_seconds_used": row.cpu_seconds_used,
        "mem_peak_mb": row.mem_peak_mb,
    }


def metrics_run(args: argparse.Namespace) -> int:
    result = _read(args.input)
    print_json({"records": [_metrics_for(row) for row in result.rows], "skipped": result.skipped})
    return _skipped_status(result.skipped)


def schema_run(args: argparse.Namespace) -> int:
    del args
    print_json(
        {
            "schema_version": SCHEMA_VERSION,
            "supported_versions": sorted(SUPPORTED_VERSIONS),
            "columns": list(COLUMNS),
        }
    )
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser("report", help="Check, measure and describe a run-report CSV.")
    commands = group.add_subparsers(metavar="COMMAND", dest="report_command", required=True)

    validate = commands.add_parser(
        "validate", help="Check the header, the schema version and the readable rows."
    )
    validate.add_argument(
        "input",
        nargs="?",
        default=STDIN_MARK,
        metavar="FILE",
        help="run-report CSV; '-' or no argument reads standard input",
    )
    validate.set_defaults(handler=validate_run)

    metrics = commands.add_parser("metrics", help="Print the metrics of each row as JSON.")
    metrics.add_argument(
        "input",
        nargs="?",
        default=STDIN_MARK,
        metavar="FILE",
        help="run-report CSV; '-' or no argument reads standard input",
    )
    metrics.set_defaults(handler=metrics_run)

    schema = commands.add_parser("schema", help="Print the supported schema versions and columns.")
    schema.set_defaults(handler=schema_run)
