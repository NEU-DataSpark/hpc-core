"""Development builds use unique versions newer than the current release."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from prepare_dev_version import development_version, prepare


def test_development_versions_order_runs_and_attempts() -> None:
    assert development_version("0.1.0", 42, 1) == "0.1.1.dev42001"
    assert development_version("0.1.0", 42, 2) == "0.1.1.dev42002"
    assert development_version("0.1.0", 43, 1) == "0.1.1.dev43001"


@pytest.mark.parametrize(
    ("version", "run_number", "attempt"),
    [("0.1.0.dev1", 1, 1), ("0.01.0", 1, 1), ("0.1.0", 0, 1), ("0.1.0", 1, 1000)],
)
def test_invalid_version_or_run_metadata_fails(version: str, run_number: int, attempt: int) -> None:
    with pytest.raises(ValueError):
        development_version(version, run_number, attempt)


def test_prepare_changes_only_the_project_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    original = '[project]\nname = "hpc-core"\nversion = "0.1.0"\n'
    pyproject.write_text(original, encoding="utf-8")

    assert prepare(pyproject, 42, 1) == "0.1.1.dev42001"
    result = pyproject.read_text(encoding="utf-8")
    assert result == original.replace('"0.1.0"', '"0.1.1.dev42001"')
    assert tomllib.loads(result)["project"]["version"] == "0.1.1.dev42001"


def test_ambiguous_version_is_rejected_without_writing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    original = '[project]\nversion = "0.1.0"\n[other]\nversion = "0.1.0"\n'
    pyproject.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="uniquely"):
        prepare(pyproject, 42, 1)
    assert pyproject.read_text(encoding="utf-8") == original
