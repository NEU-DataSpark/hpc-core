"""Wait, elapsed, CPU-hours, GPU-hours, peak use and running CPU time, with the spec's examples."""

from __future__ import annotations

from datetime import UTC, datetime

from hpc_core.contract.metrics import (
    cpu_hours,
    cpu_seconds_used,
    elapsed_seconds,
    gpu_hours,
    mean,
    peak,
    running_cpu_seconds,
    wait_seconds,
)

T0 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)


def _at(minutes: int, seconds: int = 0) -> datetime:
    return datetime(2026, 1, 5, 10 + minutes // 60, minutes % 60, seconds, tzinfo=UTC)


def test_started_job_waits_330_seconds() -> None:
    assert wait_seconds(T0, _at(5, 30)) == 330


def test_pending_job_waits_to_the_moment_given_and_has_no_elapsed() -> None:
    assert wait_seconds(T0, None, as_of=_at(2)) == 120
    assert elapsed_seconds(None, as_of=_at(2)) is None


def test_cancelled_before_start_waits_to_its_end() -> None:
    assert wait_seconds(T0, None, end=_at(3)) == 180
    assert elapsed_seconds(None, end=_at(3)) is None


def test_no_reference_time_gives_unset_wait() -> None:
    assert wait_seconds(T0, None) is None
    assert wait_seconds(None, _at(1)) is None


def test_negative_wait_is_unset_not_negative() -> None:
    assert wait_seconds(_at(5), _at(1)) is None


def test_two_hour_one_gpu_run_is_two_gpu_hours_and_sixteen_cpu_hours() -> None:
    assert gpu_hours(1, 7200) == 2
    assert cpu_hours(8, 7200) == 16


def test_unset_elapsed_gives_unset_hours_not_zero() -> None:
    assert cpu_hours(8, None) is None
    assert gpu_hours(1, None) is None


def test_zero_gpu_job_has_zero_gpu_hours() -> None:
    assert gpu_hours(0, 3600) == 0


def test_unset_gpu_count_gives_unset_gpu_hours() -> None:
    assert gpu_hours(None, 3600) is None


def test_peak_ignores_gaps() -> None:
    assert peak([100.0, None, 300.0]) == 300.0


def test_peak_and_mean_are_unset_without_readings() -> None:
    assert peak([None, None]) is None
    assert mean([None]) is None
    assert mean([2.0, None, 4.0]) == 3.0


def test_running_cpu_time_sums_steps() -> None:
    assert running_cpu_seconds([(10.0, 4), (5.0, 2)]) == 50


def test_running_cpu_time_is_unset_when_a_step_is_incomplete_or_absent() -> None:
    assert running_cpu_seconds([]) is None
    assert running_cpu_seconds([(10.0, 4), (None, 2)]) is None


def test_finished_job_uses_accounting_total_cpu() -> None:
    assert cpu_seconds_used(final=True, total_cpu_seconds=123.0, steps=[(10.0, 4)]) == 123.0
    assert cpu_seconds_used(final=False, total_cpu_seconds=123.0, steps=[(10.0, 4)]) == 40
