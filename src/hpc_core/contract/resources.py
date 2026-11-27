"""Memory, counts and GPU requests as Slurm prints them."""

from __future__ import annotations

import re

from .times import UNSET_TOKENS

_MEMORY = re.compile(r"(?P<number>\d+(?:\.\d+)?)(?P<unit>[KMGT]?)")
_MIB_PER_UNIT: dict[str, float] = {"K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024.0}
_COUNT = re.compile(r"\d+")
_ANNOTATION = re.compile(r"\(.*\)$")


def parse_memory_mib(text: str) -> float | None:
    """Memory in mebibytes. ``2048K`` is 2 MiB. A bare number has no unit, so only zero is read."""
    value = text.strip()
    if value in UNSET_TOKENS:
        return None
    match = _MEMORY.fullmatch(value)
    if match is None:
        return None
    number = float(match.group("number"))
    unit = match.group("unit")
    if unit == "":
        return 0.0 if number == 0 else None
    return number * _MIB_PER_UNIT[unit]


def parse_count(text: str) -> int | None:
    """A non-negative whole number. An empty cell is unset; a read ``0`` stays zero."""
    value = text.strip()
    if value in UNSET_TOKENS or _COUNT.fullmatch(value) is None:
        return None
    return int(value)


def parse_tres_entries(text: str) -> list[tuple[str, str]] | None:
    """``key=value`` pairs from a TRES string such as ``cpu=8,mem=16G``. None when unset."""
    value = text.strip()
    if value in UNSET_TOKENS:
        return None
    entries: list[tuple[str, str]] = []
    for piece in value.split(","):
        key, separator, number = piece.strip().partition("=")
        if separator:
            entries.append((key, number))
    return entries


def parse_gpu_request(text: str) -> tuple[int | None, str | None]:
    """(GPU count, GPU type) from a GRES or TRES string. The type is None when it is not named.

    Accepted forms: ``gres/gpu=2``, ``gres/gpu:a100=2`` (TRES), and ``gpu:2``, ``gpu:a100:2``,
    ``gres:gpu:a100:2`` (GRES, as ``squeue %b`` prints). Typed entries are counted in place of the
    untyped total, so one request is never counted twice. Unset text gives (None, None); readable
    text with no GPU entry gives (0, None). An unreadable GPU count gives (None, None).
    """
    value = text.strip()
    if value in UNSET_TOKENS or value == "(null)":
        return (None, None)

    typed: dict[str, int] = {}
    untyped_total = 0
    saw_untyped = False
    for raw_entry in value.split(","):
        entry = _ANNOTATION.sub("", raw_entry.strip()).strip()
        if not entry:
            continue
        if "=" in entry:
            key, _, number = entry.partition("=")
            if key != "gres/gpu" and not key.startswith("gres/gpu:"):
                continue
            if _COUNT.fullmatch(number) is None:
                return (None, None)
            if key == "gres/gpu":
                saw_untyped = True
                untyped_total += int(number)
            else:
                gpu_type = key[len("gres/gpu:") :]
                typed[gpu_type] = typed.get(gpu_type, 0) + int(number)
            continue
        parts = entry.removeprefix("gres:").split(":")
        if parts[0] != "gpu":
            continue
        if len(parts) == 2 and _COUNT.fullmatch(parts[1]):
            saw_untyped = True
            untyped_total += int(parts[1])
        elif len(parts) == 3 and parts[1] and _COUNT.fullmatch(parts[2]):
            typed[parts[1]] = typed.get(parts[1], 0) + int(parts[2])
        else:
            return (None, None)

    if typed:
        only_type = next(iter(typed)) if len(typed) == 1 else None
        return (sum(typed.values()), only_type)
    if saw_untyped:
        return (untyped_total, None)
    return (0, None)
