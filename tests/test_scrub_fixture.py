"""The scrub tool replaces every real value passed to it and its output passes the hygiene scan."""

from __future__ import annotations

import pytest
from hygiene_scan import scan_text
from scrub_fixture import ScrubError, main, scrub

# A synthetic recording: the values are made up for the test, not taken from any cluster.
RAW = "\n".join(
    [
        "4812201|p-alpha|COMPLETED|2031-07-02T09:00:00|2031-07-02T09:05:00|2031-07-02T10:00:00|8|realuser7|job-x|",
        "4812202_3|p-beta|CANCELLED by 1234|2031-07-02T09:02:00|Unknown|"
        "2031-07-02T09:03:00|8|realuser7|job-x|",
    ]
)
REAL_VALUES = ["realuser7", "p-alpha", "p-beta", "4812201", "4812202", "job-x"]


def _scrubbed() -> str:
    return scrub(
        RAW,
        account="realuser7",
        partitions={"p-alpha": "short", "p-beta": "gpu"},
        job_ids=["4812201", "4812202"],
        replacements={"job-x": "sample-job"},
    )


def test_no_input_value_survives() -> None:
    output = _scrubbed()
    for value in REAL_VALUES:
        assert value not in output


def test_placeholders_and_sequential_ids_are_used() -> None:
    first, second = _scrubbed().splitlines()
    assert first == (
        "100001|short|COMPLETED|2026-01-05T00:00:00|2026-01-05T00:05:00"
        "|2026-01-05T01:00:00|8|exampleuser|sample-job|"
    )
    assert second.startswith("100002_3|gpu|CANCELLED by 1234|")


def test_array_suffix_is_kept() -> None:
    assert "100002_3" in _scrubbed()


def test_times_shift_to_the_base_date_and_keep_spacing() -> None:
    first, second = _scrubbed().splitlines()
    assert first.split("|")[3] == "2026-01-05T00:00:00"
    assert second.split("|")[3] == "2026-01-05T00:02:00"


def test_output_passes_the_hygiene_scan() -> None:
    assert scan_text("recording.txt", _scrubbed()) == []


def test_a_placeholder_that_keeps_the_real_value_is_refused() -> None:
    with pytest.raises(ScrubError, match="partition survives"):
        scrub(RAW, account="", partitions={"p-alpha": "p-alpha"}, job_ids=[], replacements={})


def test_base_job_id_must_be_digits() -> None:
    with pytest.raises(ScrubError):
        scrub("1|x\n", account="", partitions={}, job_ids=["12;rm"], replacements={})


def test_command_line_scrubs_standard_input(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(
        [
            "--account",
            "realuser7",
            "--partition",
            "p-alpha=short",
            "--partition",
            "p-beta=gpu",
            "--job-id",
            "4812201",
            "--job-id",
            "4812202",
            "--replace",
            "job-x=sample-job",
            "--base-date",
            "2026-01-05",
        ],
        stdin=RAW,
    )
    output = capsys.readouterr().out
    assert status == 0
    for value in REAL_VALUES:
        assert value not in output


def test_command_line_refuses_a_malformed_pair(capsys: pytest.CaptureFixture[str]) -> None:
    status = main(["--partition", "p-alpha"], stdin=RAW)
    assert status == 2
    assert "REAL=PLACEHOLDER" in capsys.readouterr().err
