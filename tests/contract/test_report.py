"""Run-report CSV: columns, formatting, the name-based reader, refusals and closed sets."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest

from hpc_core.contract import report
from hpc_core.contract.report import (
    COLUMNS,
    ReportError,
    ReportRow,
    format_report,
    format_row,
    read_report,
)

SAMPLE = ReportRow(
    job_id="4812201_3",
    job_name="train|model",
    partition="short",
    stage="post",
    sample_time=datetime(2026, 1, 5, 11, tzinfo=UTC),
    scheduler_state="COMPLETED",
    submit_time=datetime(2026, 1, 5, 9, tzinfo=UTC),
    start_time=datetime(2026, 1, 5, 9, 5, 30, tzinfo=UTC),
    end_time=datetime(2026, 1, 5, 10, tzinfo=UTC),
    wait_seconds=330,
    elapsed_seconds=3150,
    cpus_alloc=8,
    cpu_seconds_used=93784.5,
    mem_peak_mb=2048.0,
    gpus_alloc=2,
    gpu_type="a100",
    gpu_util_pct=71.25,
    gpu_mem_mb=None,
    source="sacct+nvidia-smi",
    unavailable="gpu_mem_mb",
    report_status="complete",
)
ZERO = ReportRow(
    job_id="77",
    stage="running",
    sample_time=datetime(2026, 1, 5, 9, tzinfo=UTC),
    source="squeue",
    report_status="in_progress",
    gpus_alloc=0,
    mem_peak_mb=None,
)


def _cells(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_header_is_the_22_columns_in_order() -> None:
    assert COLUMNS == (
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
    assert len(COLUMNS) == 22
    assert [field for field in ReportRow.__dataclass_fields__] == list(COLUMNS)


def test_good_file_is_read() -> None:
    result = read_report(format_report([SAMPLE]))
    assert result.skipped == 0
    assert result.rows == (SAMPLE,)


def test_reordered_columns_give_the_same_values() -> None:
    cells = _cells(format_report([SAMPLE]))
    order = list(reversed(range(len(COLUMNS))))
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows([[row[i] for i in order] for row in cells])
    assert read_report(buffer.getvalue()).rows == (SAMPLE,)


def test_bad_row_is_skipped_and_counted_and_others_are_kept() -> None:
    cells = _cells(format_report([SAMPLE, ZERO]))
    cells[1][COLUMNS.index("cpus_alloc")] = "eight"
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(cells)
    result = read_report(buffer.getvalue())
    assert result.skipped == 1
    assert result.rows == (ZERO,)


def test_version_99_is_refused_as_a_whole_and_names_the_version() -> None:
    text = format_report([ZERO]).replace("\n1,", "\n99,", 1)
    with pytest.raises(ReportError, match="99"):
        read_report(text)


def test_missing_stage_column_is_refused() -> None:
    cells = _cells(format_report([ZERO]))
    keep = [index for index, name in enumerate(cells[0]) if name != "stage"]
    text = "\n".join(",".join(row[i] for i in keep) for row in cells) + "\n"
    with pytest.raises(ReportError, match="'stage'"):
        read_report(text)


def test_real_zero_is_zero_and_blank_is_unset() -> None:
    line = _cells(format_report([ZERO]))[1]
    assert line[COLUMNS.index("gpus_alloc")] == "0"
    assert line[COLUMNS.index("mem_peak_mb")] == ""
    back = read_report(format_report([ZERO])).rows[0]
    assert back.gpus_alloc == 0
    assert back.mem_peak_mb is None


def test_round_trip_keeps_every_value() -> None:
    for row in (SAMPLE, ZERO):
        assert read_report(format_report([row])).rows == (row,)


def test_whole_numbers_have_no_decimal_point_and_times_end_in_z() -> None:
    cells = dict(zip(COLUMNS, format_row(SAMPLE), strict=True))
    assert cells["gpus_alloc"] == "2"
    assert cells["mem_peak_mb"] == "2048"
    assert cells["cpu_seconds_used"] == "93784.5"
    assert cells["sample_time"] == "2026-01-05T11:00:00Z"
    assert cells["gpu_mem_mb"] == ""


@pytest.mark.parametrize(
    ("stage", "accepted"), [("pre", True), ("running", True), ("later", False)]
)
def test_stage_is_a_closed_set(stage: str, accepted: bool) -> None:
    cells = _cells(format_report([ZERO]))
    cells[1][COLUMNS.index("stage")] = stage
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(cells)
    result = read_report(buffer.getvalue())
    assert len(result.rows) == (1 if accepted else 0)
    assert result.skipped == (0 if accepted else 1)


def test_joined_sources_are_accepted_and_unknown_sources_are_skipped() -> None:
    cells = _cells(format_report([ZERO]))
    cells[1][COLUMNS.index("source")] = "squeue+sstat"
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(cells)
    assert len(read_report(buffer.getvalue()).rows) == 1
    with pytest.raises(ValueError):
        ReportRow(
            job_id="1",
            stage="pre",
            sample_time=ZERO.sample_time,
            source="bogus",
            report_status="complete",
        )


def test_report_status_is_a_closed_set() -> None:
    with pytest.raises(ValueError):
        ReportRow(
            job_id="1",
            stage="pre",
            sample_time=ZERO.sample_time,
            source="squeue",
            report_status="done",
        )


def test_empty_report_is_refused() -> None:
    with pytest.raises(ReportError):
        read_report("")


def test_header_only_report_has_no_rows() -> None:
    result = read_report(",".join(COLUMNS) + "\n")
    assert result.rows == () and result.skipped == 0


def test_report_module_exports_the_schema_version() -> None:
    assert report.SCHEMA_VERSION == 1
    assert report.SUPPORTED_VERSIONS == frozenset({1})
