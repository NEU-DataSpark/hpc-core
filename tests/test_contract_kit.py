"""The package's own reader and writer pass both contract checks; broken ones fail with the

case name.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from hpc_core.contract.report import COLUMNS, ReportRow, format_report
from hpc_core.testing import (
    ContractFailure,
    check_reader,
    check_writer,
    load_case,
    package_reader,
    package_writer,
)


def test_package_reader_passes_every_golden_case() -> None:
    assert check_reader(package_reader) == 7


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
