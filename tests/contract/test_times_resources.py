"""Times, durations, memory, counts and GPU requests as Slurm prints them."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hpc_core.contract.resources import (
    parse_count,
    parse_gpu_request,
    parse_memory_mib,
    parse_tres_entries,
)
from hpc_core.contract.times import (
    format_time,
    parse_duration,
    parse_report_time,
    parse_time,
)


def test_duration_with_days_and_fraction() -> None:
    assert parse_duration("1-02:03:04.5") == 93784.5


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("00:01:02.5", 62.5),
        ("2-00", 172800.0),
        ("1-02:03", 93780.0),
        ("03:00", 180.0),  # without days, two parts are minutes and seconds
        ("30", 1800.0),  # one part without days is minutes
        ("00:00:00", 0.0),
    ],
)
def test_durations(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text", ["UNLIMITED", "", "N/A", "Unknown", "None", "INVALID", "5.5", "x:y"]
)
def test_unreadable_durations_are_unset(text: str) -> None:
    assert parse_duration(text) is None


@pytest.mark.parametrize(
    ("text", "mib"),
    [
        ("2048K", 2.0),
        ("512M", 512.0),
        ("1G", 1024.0),
        ("1T", 1024.0 * 1024.0),
        ("1.5G", 1536.0),
        ("0", 0.0),
    ],
)
def test_memory_to_mebibytes(text: str, mib: float) -> None:
    assert parse_memory_mib(text) == mib


@pytest.mark.parametrize("text", ["100", "2048k", "", "N/A", "12X"])
def test_memory_without_a_known_unit_is_unset(text: str) -> None:
    assert parse_memory_mib(text) is None


def test_slurm_time_is_utc() -> None:
    assert parse_time("2026-01-05T10:00:00") == datetime(2026, 1, 5, 10, tzinfo=UTC)


@pytest.mark.parametrize("text", ["Unknown", "None", "N/A", "INVALID", ""])
def test_placeholder_time_is_unset(text: str) -> None:
    assert parse_time(text) is None


def test_format_time_is_utc_with_z_and_whole_seconds() -> None:
    moment = datetime(2026, 1, 5, 12, tzinfo=UTC)
    assert format_time(moment) == "2026-01-05T12:00:00Z"
    assert parse_report_time(format_time(moment)) == moment


def test_format_time_refuses_naive_and_fractional_times() -> None:
    with pytest.raises(ValueError):
        format_time(datetime(2026, 1, 5, 12))
    with pytest.raises(ValueError):
        format_time(datetime(2026, 1, 5, 12, tzinfo=UTC).replace(microsecond=5))


def test_empty_cell_is_unset_and_zero_stays_zero() -> None:
    assert parse_count("") is None
    assert parse_count("N/A") is None
    assert parse_count("0") == 0
    assert parse_count("8") == 8
    assert parse_count("eight") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("gres/gpu:a100=2", (2, "a100")),
        ("gres/gpu=2", (2, None)),
        ("cpu=8,mem=16G", (0, None)),
        ("cpu=8,gres/gpu:a100=2,gres/gpu=2", (2, "a100")),
        ("gres/gpu:a100=2,gres/gpu:h200=1", (3, None)),
        ("gpu:a100:2", (2, "a100")),
        ("gpu:2", (2, None)),
        ("gres:gpu:2", (2, None)),
        ("gpu:2(IDX:0-1)", (2, None)),
        ("gpu:x", (None, None)),
        ("N/A", (None, None)),
        ("", (None, None)),
        ("(null)", (None, None)),
    ],
)
def test_gpu_requests(text: str, expected: tuple[int | None, str | None]) -> None:
    assert parse_gpu_request(text) == expected


def test_tres_entries_are_key_value_pairs() -> None:
    assert parse_tres_entries("cpu=8,mem=16G") == [("cpu", "8"), ("mem", "16G")]
    assert parse_tres_entries("N/A") is None
