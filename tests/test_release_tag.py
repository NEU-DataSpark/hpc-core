"""The release tag check: a tag must be ``v`` plus the version in pyproject.toml."""

from __future__ import annotations

from pathlib import Path

import pytest
from check_release_tag import check, main, project_version

REPO = Path(__file__).resolve().parent.parent


def test_the_repository_version_is_read_from_pyproject() -> None:
    version = project_version(REPO / "pyproject.toml")
    assert version.count(".") == 2


def test_matching_tag_passes() -> None:
    assert check("v0.1.0", "0.1.0") is None


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1.1", "v0.1", "v0.1.0-rc1", "refs/tags/v0.1.0"])
def test_a_tag_that_differs_fails(tag: str) -> None:
    assert check(tag, "0.1.0") is not None


def test_main_passes_the_tag_that_matches_the_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    version = project_version(REPO / "pyproject.toml")
    assert main([f"v{version}"], root=REPO) == 0
    assert "matches" in capsys.readouterr().out


def test_main_fails_a_mismatched_tag_and_names_both_versions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["v9.9.9"], root=REPO) == 1
    message = capsys.readouterr().err
    assert "v9.9.9" in message and "does not match" in message


def test_main_needs_exactly_one_argument() -> None:
    assert main([], root=REPO) == 2
    assert main(["v0.1.0", "extra"], root=REPO) == 2
