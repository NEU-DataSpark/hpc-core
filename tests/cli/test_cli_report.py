"""``hpc-core report``: the golden run reports, skipped rows, refused versions and metric nulls.

Named ``test_cli_report`` because ``tests/contract/test_report.py`` already has the other basename.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import RunCli

from hpc_core.contract.report import COLUMNS, SUPPORTED_VERSIONS
from hpc_core.testing import load_cases
from hpc_core.testing.fixtures import Case

REPORT_CASES = load_cases("report")


def _write(tmp_path: Path, case: Case) -> Path:
    source = tmp_path / "run-report.csv"
    source.write_text(case.text, encoding="utf-8")
    return source


def _case(name: str) -> Case:
    return next(c for c in REPORT_CASES if c.name == name)


@pytest.mark.parametrize("case", REPORT_CASES, ids=lambda case: case.name)
def test_validate_matches_the_golden_outcome(case: Case, run_cli: RunCli, tmp_path: Path) -> None:
    code, out, err = run_cli("report", "validate", str(_write(tmp_path, case)))
    expected = case.expected
    if expected["outcome"] == "refused":
        assert code == 1
        assert out == ""
        assert expected["error_contains"] in err
        return
    skipped = expected["skipped"]
    assert code == (1 if skipped else 0)
    summary = json.loads(out)
    assert summary["rows"] == len(expected["rows"])
    assert summary["skipped"] == skipped
    assert (f"{skipped} row(s)" in err) == bool(skipped)


@pytest.mark.parametrize("case", REPORT_CASES, ids=lambda case: case.name)
def test_metrics_has_one_record_per_readable_row(
    case: Case, run_cli: RunCli, tmp_path: Path
) -> None:
    code, out, err = run_cli("report", "metrics", str(_write(tmp_path, case)))
    if case.expected["outcome"] == "refused":
        assert code == 1
        assert out == ""
        assert case.expected["error_contains"] in err
        return
    data = json.loads(out)
    assert len(data["records"]) == len(case.expected["rows"])
    assert data["skipped"] == case.expected["skipped"]
    assert code == (1 if case.expected["skipped"] else 0)


def test_an_unsupported_schema_version_exits_1_and_names_it(
    run_cli: RunCli, tmp_path: Path
) -> None:
    code, out, err = run_cli(
        "report", "validate", str(_write(tmp_path, _case("unknown_schema_version")))
    )
    assert code == 1
    assert out == ""
    assert "99" in err
    assert "schema_version" in err


def test_a_bad_row_is_counted_and_exits_1(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, err = run_cli("report", "validate", str(_write(tmp_path, _case("bad_row"))))
    assert code == 1
    assert json.loads(out)["skipped"] == 1
    assert "1 row(s)" in err


def test_a_zero_is_kept_and_a_blank_is_null(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, _ = run_cli("report", "metrics", str(_write(tmp_path, _case("zero_beside_blank"))))
    assert code == 0
    (record,) = json.loads(out)["records"]
    assert record["cpu_seconds_used"] == 0.0
    assert record["cpu_hours"] == 0.0
    assert record["mem_peak_mb"] is None
    assert record["unavailable"] == "mem_peak_mb"


def test_unavailable_metrics_are_null_not_zero(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, _ = run_cli("report", "metrics", str(_write(tmp_path, _case("unavailable_metrics"))))
    assert code == 0
    (record,) = json.loads(out)["records"]
    assert record["cpu_seconds_used"] is None
    assert record["mem_peak_mb"] is None
    assert record["unavailable"] == "cpu_seconds_used;mem_peak_mb;gpu_util_pct;gpu_mem_mb"


def test_metrics_compute_hours_from_the_allocation(run_cli: RunCli, tmp_path: Path) -> None:
    # The fixture allocates 4 CPUs and 1 GPU for 1500 elapsed seconds.
    _, out, _ = run_cli("report", "metrics", str(_write(tmp_path, _case("unavailable_metrics"))))
    (record,) = json.loads(out)["records"]
    assert record["elapsed_seconds"] == 1500
    assert record["cpu_hours"] == pytest.approx(4 * 1500 / 3600)
    assert record["gpu_hours"] == pytest.approx(1 * 1500 / 3600)


def test_schema_prints_the_version_and_the_columns(run_cli: RunCli) -> None:
    code, out, err = run_cli("report", "schema")
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["schema_version"] in SUPPORTED_VERSIONS
    assert data["supported_versions"] == sorted(SUPPORTED_VERSIONS)
    assert data["columns"] == list(COLUMNS)


def test_a_missing_report_exits_2(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, err = run_cli("report", "validate", str(tmp_path / "gone.csv"))
    assert code == 2
    assert out == ""
    assert "gone.csv" in err
