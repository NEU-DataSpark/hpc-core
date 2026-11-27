"""``hpc-core parse``: every recorded scheduler fixture, empty input, profiles and errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FeedStdin, RunCli

from hpc_core.cli._profiles import DEFAULT_PROFILE, PROFILES
from hpc_core.testing import load_cases
from hpc_core.testing.fixtures import Case

SCHEDULER_CASES = load_cases("scheduler")


@pytest.mark.parametrize("case", SCHEDULER_CASES, ids=lambda case: case.name)
def test_every_scheduler_fixture_matches_its_expected_json(
    case: Case, run_cli: RunCli, tmp_path: Path
) -> None:
    expected = case.expected
    source = tmp_path / "output.txt"
    source.write_text(case.text, encoding="utf-8")

    code, out, err = run_cli(
        "parse", expected["command"], "--profile", expected["profile"], str(source)
    )

    assert code == 0, err
    assert err == ""
    assert json.loads(out) == {"records": expected["records"], "skipped": expected["skipped"]}


def test_the_default_profile_is_the_operator_profile(run_cli: RunCli, tmp_path: Path) -> None:
    case = next(c for c in SCHEDULER_CASES if c.name == "squeue-operator")
    source = tmp_path / "output.txt"
    source.write_text(case.text, encoding="utf-8")

    code, out, _ = run_cli("parse", "squeue", str(source))

    assert code == 0
    assert json.loads(out) == {
        "records": case.expected["records"],
        "skipped": case.expected["skipped"],
    }
    assert DEFAULT_PROFILE["squeue"] == "operator-sampling"


def test_standard_input_is_read_for_dash(run_cli: RunCli, feed_stdin: FeedStdin) -> None:
    case = next(c for c in SCHEDULER_CASES if c.name == "sinfo-capacity")
    feed_stdin(case.text)

    code, out, _ = run_cli("parse", "sinfo", "--profile", "capacity", "-")

    assert code == 0
    assert json.loads(out)["records"] == case.expected["records"]


def test_empty_input_gives_no_records_and_no_skips(run_cli: RunCli, feed_stdin: FeedStdin) -> None:
    feed_stdin("")
    code, out, err = run_cli("parse", "squeue")
    assert code == 0
    assert err == ""
    assert json.loads(out) == {"records": [], "skipped": 0}


def test_a_bad_row_is_counted_and_not_printed(run_cli: RunCli, feed_stdin: FeedStdin) -> None:
    feed_stdin("only-one-cell\n")
    code, out, err = run_cli("parse", "sinfo", "--profile", "capacity")
    assert code == 0
    assert json.loads(out) == {"records": [], "skipped": 1}
    assert "only-one-cell" not in out + err


def test_an_unknown_profile_exits_2_and_names_the_valid_profiles(
    run_cli: RunCli, tmp_path: Path
) -> None:
    source = tmp_path / "output.txt"
    source.write_text("", encoding="utf-8")
    code, out, err = run_cli("parse", "squeue", "--profile", "no-such-profile", str(source))
    assert code == 2
    assert out == ""
    for name in PROFILES["squeue"]:
        assert name in err


def test_a_profile_of_another_command_is_refused(run_cli: RunCli, tmp_path: Path) -> None:
    source = tmp_path / "output.txt"
    source.write_text("", encoding="utf-8")
    code, _, err = run_cli("parse", "sinfo", "--profile", "operator-sampling", str(source))
    assert code == 2
    assert "capacity" in err


def test_a_missing_input_file_exits_2(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, err = run_cli("parse", "sacct", str(tmp_path / "gone.txt"))
    assert code == 2
    assert out == ""
    assert "gone.txt" in err
