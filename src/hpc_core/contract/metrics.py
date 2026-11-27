"""Wait, elapsed, CPU-hours, GPU-hours and peak use. Unset inputs give unset results, never zero."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def wait_seconds(
    submit: datetime | None,
    start: datetime | None = None,
    *,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> int | None:
    """Seconds from submit to start. A job that has not started counts to its end (if it was
    cancelled before starting) or to ``as_of``. Returns None when no reference time is known or
    the reference is before the submit time."""
    if submit is None:
        return None
    reference = start if start is not None else (end if end is not None else as_of)
    if reference is None:
        return None
    seconds = (reference - submit).total_seconds()
    return None if seconds < 0 else int(seconds)


def elapsed_seconds(
    start: datetime | None,
    *,
    end: datetime | None = None,
    as_of: datetime | None = None,
) -> int | None:
    """Seconds from start to the end time, or to ``as_of`` while running. Unset before a start."""
    if start is None:
        return None
    reference = end if end is not None else as_of
    if reference is None:
        return None
    seconds = (reference - start).total_seconds()
    return None if seconds < 0 else int(seconds)


def cpu_hours(cpus: int | None, elapsed: int | None) -> float | None:
    if cpus is None or elapsed is None:
        return None
    return cpus * elapsed / 3600


def gpu_hours(gpus: int | None, elapsed: int | None) -> float | None:
    if gpus is None or elapsed is None:
        return None
    return gpus * elapsed / 3600


def peak(values: Iterable[float | None]) -> float | None:
    """The largest value that was read. Gaps are ignored; no reading gives None."""
    readings = [value for value in values if value is not None]
    return max(readings) if readings else None


def mean(values: Iterable[float | None]) -> float | None:
    readings = [value for value in values if value is not None]
    return sum(readings) / len(readings) if readings else None


def running_cpu_seconds(steps: Iterable[tuple[float | None, int | None]]) -> float | None:
    """CPU seconds used so far: over steps, average CPU time per task times the task count.

    Returns None when there is no step, or when any step lacks its average or its task count: a
    partial sum would understate the job's usage.
    """
    total = 0.0
    seen = False
    for average, tasks in steps:
        seen = True
        if average is None or tasks is None:
            return None
        total += average * tasks
    return total if seen else None


def cpu_seconds_used(
    *,
    final: bool,
    total_cpu_seconds: float | None,
    steps: Iterable[tuple[float | None, int | None]],
) -> float | None:
    """The accounting TotalCPU for a finished job; the step sum for a running one."""
    if final:
        return total_cpu_seconds
    return running_cpu_seconds(steps)
