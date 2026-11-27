"""Slurm times and durations. Every time is read as UTC; every "no value" token is unset."""

from __future__ import annotations

import re
from datetime import UTC, datetime

# Tokens Slurm prints for "no time" or "no value". A field holding one of them is unset.
UNSET_TOKENS: frozenset[str] = frozenset({"", "Unknown", "None", "N/A", "INVALID"})

_SLURM_TIME = "%Y-%m-%dT%H:%M:%S"
_REPORT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DURATION = re.compile(r"(?:(?P<days>\d+)-)?(?P<clock>\d+(?::\d+){0,2})(?P<frac>\.\d+)?")


def is_unset(text: str) -> bool:
    return text.strip() in UNSET_TOKENS


def parse_time(text: str) -> datetime | None:
    """A Slurm timestamp (``2026-11-20T10:00:00``) as an aware UTC datetime, or None when unset."""
    value = text.strip()
    if value in UNSET_TOKENS:
        return None
    try:
        parsed = datetime.strptime(value, _SLURM_TIME)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def format_time(moment: datetime) -> str:
    """UTC ISO 8601 with a ``Z`` suffix. Naive times and sub-second precision are refused."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("time must be timezone-aware")
    utc = moment.astimezone(UTC)
    if utc.microsecond:
        raise ValueError("time must be whole seconds")
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_report_time(text: str) -> datetime:
    """A report time, strictly in the ``format_time`` shape. Raises ValueError otherwise."""
    if _REPORT_TIME.fullmatch(text) is None:
        raise ValueError("report time must be UTC ISO 8601 ending in Z")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def parse_duration(text: str) -> float | None:
    """A Slurm duration in seconds, or None when unset or unreadable.

    Follows Slurm's time specification: ``[D-]H``, ``[D-]H:M``, ``[D-]H:M:S`` and, without days,
    ``M`` and ``M:S``. Only the seconds component may carry a fraction,
    for example ``1-02:03:04.5``.
    """
    value = text.strip()
    if value in UNSET_TOKENS:
        return None
    match = _DURATION.fullmatch(value)
    if match is None:
        return None
    days_text = match.group("days")
    parts = [int(piece) for piece in match.group("clock").split(":")]
    fraction_text = match.group("frac")
    has_days = days_text is not None
    has_seconds = len(parts) == 3 or (not has_days and len(parts) == 2)
    if fraction_text is not None and not has_seconds:
        return None

    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        if has_days:
            hours, minutes, seconds = parts[0], parts[1], 0
        else:
            hours, minutes, seconds = 0, parts[0], parts[1]
    else:
        if has_days:
            hours, minutes, seconds = parts[0], 0, 0
        else:
            hours, minutes, seconds = 0, parts[0], 0

    days = int(days_text) if has_days else 0
    fraction = float(fraction_text) if fraction_text is not None else 0.0
    return float(days * 86400 + hours * 3600 + minutes * 60 + seconds) + fraction
