"""Contract checks a consumer runs against its own reader and writer.

``check_reader`` gives each golden report to the consumer's reader and compares the cells it
returns, with the real zero kept and blanks kept blank. ``check_writer`` gives the writer the
canonical samples and compares the bytes it produces with the golden file. Each failure names the
case, so the consumer's test output says which contract it broke.

A reader is any callable ``text -> (rows, skipped)``, where each row maps a column name to its
canonical cell text (see ``hpc_core.contract.report.format_row``). It may raise instead, for a
refused report. A writer is any callable taking the canonical samples and returning CSV text.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from itertools import zip_longest

from ..contract.report import COLUMNS, ReportRow, format_report, format_row, read_report
from .fixtures import Case, load_case, load_cases

CANONICAL_CASE = "finished_run"

ReaderOutput = tuple[list[dict[str, str]], int]
Reader = Callable[[str], ReaderOutput]
Writer = Callable[[Sequence[ReportRow]], str]


class ContractFailure(AssertionError):
    """A consumer's reader or writer disagrees with a golden case. The message names the case."""


def package_reader(text: str) -> ReaderOutput:
    """The package's own reader, in the canonical cell form the checks compare."""
    result = read_report(text)
    rows = [dict(zip(COLUMNS, format_row(row), strict=True)) for row in result.rows]
    return rows, result.skipped


def package_writer(samples: Sequence[ReportRow]) -> str:
    return format_report(samples)


def canonical_samples() -> tuple[ReportRow, ...]:
    """The rows of the canonical golden case, as the package reads them."""
    return read_report(load_case("report", CANONICAL_CASE).text).rows


def _report_cases(cases: Iterable[Case] | None) -> list[Case]:
    chosen = load_cases("report") if cases is None else list(cases)
    return [case for case in chosen if case.kind == "report"]


def _check_read(name: str, expected: dict[str, object], reader: Reader, text: str) -> None:
    try:
        rows, skipped = reader(text)
    except Exception as error:
        if expected.get("outcome") == "refused" and str(expected.get("error_contains", "")) in str(
            error
        ):
            return
        raise ContractFailure(f"{name}: reader refused the report: {error}") from error
    if expected.get("outcome") != "read":
        raise ContractFailure(f"{name}: reader accepted a report that must be refused")
    if skipped != expected["skipped"]:
        raise ContractFailure(f"{name}: skipped {skipped} rows, expected {expected['skipped']}")
    if [dict(row) for row in rows] != expected["rows"]:
        raise ContractFailure(f"{name}: returned cells differ from the golden values")


def check_reader(reader: Reader, cases: Iterable[Case] | None = None) -> int:
    """Run the reader over every report case. Returns the number of cases checked."""
    checked = 0
    for case in _report_cases(cases):
        _check_read(case.name, case.expected, reader, case.text)
        checked += 1
    return checked


def check_writer(writer: Writer, samples: Sequence[ReportRow] | None = None) -> None:
    """The writer's bytes for the canonical samples must equal the canonical golden file."""
    golden = load_case("report", CANONICAL_CASE).text
    produced = writer(canonical_samples() if samples is None else samples)
    if produced != golden:
        first = next(
            (
                number
                for number, (left, right) in enumerate(
                    zip_longest(produced.splitlines(), golden.splitlines()), 1
                )
                if left != right
            ),
            None,
        )
        where = f" (first difference on line {first})" if first is not None else ""
        raise ContractFailure(
            f"{CANONICAL_CASE}: writer output differs from the golden file{where}"
        )
