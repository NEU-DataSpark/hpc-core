"""The package's own reader and writer pass both contract checks; broken ones fail with the

case name.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from consumer_standins import standin_job_reader, standin_reader

from hpc_core.contract.report import COLUMNS, ReportRow, format_report
from hpc_core.testing import (
    ContractFailure,
    check_reader,
    check_writer,
    load_case,
    package_reader,
    package_writer,
)

MULTI_JOB = "multi_job_run"


def package_job_reader(job_id: str, text: str) -> tuple[list[dict[str, str]], int]:
    rows, skipped = package_reader(text)
    return [row for row in rows if row["job_id"] == job_id], skipped


def test_package_reader_passes_every_golden_case() -> None:
    assert check_reader(package_reader) == 8


def test_check_reader_with_no_reader_is_refused() -> None:
    with pytest.raises(ValueError):
        check_reader()


def test_multi_job_case_lists_its_jobs_in_order_of_first_appearance() -> None:
    expected = load_case("report", MULTI_JOB).expected
    distinct: list[str] = []
    for row in expected["rows"]:
        if row["job_id"] not in distinct:
            distinct.append(row["job_id"])
    assert len(expected["job_ids"]) >= 2
    assert expected["job_ids"] == distinct


def test_multi_job_case_interleaves_the_jobs_in_time() -> None:
    rows = load_case("report", MULTI_JOB).expected["rows"]
    times = [row["sample_time"] for row in rows]
    assert times == sorted(times)
    sequence = [row["job_id"] for row in rows]
    runs = [job for index, job in enumerate(sequence) if index == 0 or sequence[index - 1] != job]
    assert len(runs) > len(set(sequence))


def test_multi_job_case_is_checked_as_a_whole_report() -> None:
    assert check_reader(package_reader, [load_case("report", MULTI_JOB)]) == 1


def test_per_job_reader_passes_the_multi_job_case() -> None:
    assert check_reader(job_reader=package_job_reader, cases=[load_case("report", MULTI_JOB)]) == 1


def test_per_job_reader_alone_checks_only_the_multi_job_case() -> None:
    assert check_reader(job_reader=package_job_reader) == 1


def test_whole_and_per_job_readers_together_count_every_case() -> None:
    assert check_reader(package_reader, job_reader=package_job_reader) == 8


def test_per_job_reader_returning_another_jobs_row_fails_with_case_and_job() -> None:
    def returns_every_job(job_id: str, text: str) -> tuple[list[dict[str, str]], int]:
        return package_reader(text)

    with pytest.raises(
        ContractFailure,
        match=r"multi_job_run\[job 4812210\]: reader returned a row of another job",
    ):
        check_reader(job_reader=returns_every_job, cases=[load_case("report", MULTI_JOB)])


def test_per_job_reader_dropping_a_row_fails_with_case_and_job() -> None:
    def drops_last_row(job_id: str, text: str) -> tuple[list[dict[str, str]], int]:
        rows, skipped = package_job_reader(job_id, text)
        return rows[:-1], skipped

    with pytest.raises(
        ContractFailure, match=r"multi_job_run\[job 4812210\]: returned cells differ"
    ):
        check_reader(job_reader=drops_last_row, cases=[load_case("report", MULTI_JOB)])


def test_per_job_reader_changing_one_cell_fails_naming_that_job() -> None:
    def changes_job_c(job_id: str, text: str) -> tuple[list[dict[str, str]], int]:
        rows, skipped = package_job_reader(job_id, text)
        if job_id == "4812212":
            rows = [{**row, "cpus_alloc": "1"} for row in rows]
        return rows, skipped

    with pytest.raises(
        ContractFailure, match=r"multi_job_run\[job 4812212\]: returned cells differ"
    ):
        check_reader(job_reader=changes_job_c, cases=[load_case("report", MULTI_JOB)])


def test_per_job_reader_reporting_skipped_rows_fails_with_case_and_job() -> None:
    def skips_one(job_id: str, text: str) -> tuple[list[dict[str, str]], int]:
        rows, _ = package_job_reader(job_id, text)
        return rows, 1

    with pytest.raises(
        ContractFailure, match=r"multi_job_run\[job 4812210\]: skipped 1 rows, expected 0"
    ):
        check_reader(job_reader=skips_one, cases=[load_case("report", MULTI_JOB)])


def test_standin_readers_pass_every_golden_case_together() -> None:
    assert check_reader(standin_reader, job_reader=standin_job_reader) == 8


def test_package_writer_passes_the_canonical_samples() -> None:
    check_writer(package_writer)


def test_reader_dropping_the_real_zero_fails_with_the_case_name() -> None:
    def drops_zero(text: str) -> tuple[list[dict[str, str]], int]:
        rows, skipped = package_reader(text)
        return [
            {key: ("" if value == "0" else value) for key, value in row.items()} for row in rows
        ], skipped

    with pytest.raises(ContractFailure, match="zero_beside_blank"):
        check_reader(drops_zero, [load_case("report", "zero_beside_blank")])


def test_writer_changing_the_column_order_fails_with_the_case_name() -> None:
    def reversed_columns(samples: Sequence[ReportRow]) -> str:
        text = format_report(samples)
        lines = [line.split(",") for line in text.splitlines()]
        reordered = [",".join(reversed(line)) for line in lines]
        return "\n".join(reordered) + "\n"

    with pytest.raises(ContractFailure, match="finished_run"):
        check_writer(reversed_columns)


def test_refused_report_passes_when_the_reader_refuses_with_the_version() -> None:
    check_reader(package_reader, [load_case("report", "unknown_schema_version")])


def test_reader_that_accepts_a_refused_report_fails() -> None:
    def accepts_everything(text: str) -> tuple[list[dict[str, str]], int]:
        return [], 0

    with pytest.raises(ContractFailure, match="unknown_schema_version"):
        check_reader(accepts_everything, [load_case("report", "unknown_schema_version")])


def test_golden_header_is_the_package_columns() -> None:
    text = load_case("report", "finished_run").text
    assert text.splitlines()[0] == ",".join(COLUMNS)
