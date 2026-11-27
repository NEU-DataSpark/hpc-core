"""The run-report header is pinned per schema version: a column change needs a version change."""

from __future__ import annotations

from pathlib import Path

from hpc_core.contract import report

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _snapshot_columns(version: int) -> tuple[str, ...]:
    text = (SNAPSHOTS / f"schema_v{version}.header").read_text(encoding="utf-8").strip()
    return tuple(text.split(","))


def _matches_snapshot(columns: tuple[str, ...]) -> bool:
    """The header check: the columns must equal the snapshot of the current version."""
    return columns == _snapshot_columns(report.SCHEMA_VERSION)


def test_current_columns_match_the_snapshot_of_the_current_version() -> None:
    assert _matches_snapshot(report.COLUMNS)


def test_planted_column_without_a_version_bump_fails() -> None:
    assert not _matches_snapshot(report.COLUMNS + ("extra_column",))


def test_every_supported_version_has_a_snapshot() -> None:
    for version in report.SUPPORTED_VERSIONS:
        assert (SNAPSHOTS / f"schema_v{version}.header").is_file()
