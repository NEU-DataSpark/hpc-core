"""Explicit node profiles: the one place that parses, bounds and resolves share-queue limits.

A profile's account quota is the per-type limit in the profile record. A node may pin an explicit
node quota, which can only narrow the account quota. The effective limit of a node is, for each
type, the smaller of its node quota and the current account quota; a type the node does not list
takes the account value. A node with no explicit values has the source ``default`` and uses the
account quota alone. The rules live here so the CLI, the console and the tests cannot drift.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ..contract.identifiers import ValidationError
from .layout import validate_share_pairs
from .records import SOURCE_DEFAULT, SOURCE_EXPLICIT, SOURCES

__all__ = [
    "SOURCES",
    "SOURCE_DEFAULT",
    "SOURCE_EXPLICIT",
    "ResolvedProfile",
    "check_against_account",
    "effective_limits",
    "parse_share_queue",
    "resolve",
]

_WHOLE_NUMBER = re.compile(r"-?\d+")


@dataclass(frozen=True)
class ResolvedProfile:
    """A node's profile: the account quota, its explicit values, the effective limits and source."""

    account: dict[str, int]
    node_quota: dict[str, int] | None
    effective: dict[str, int]
    source: str


def parse_share_queue(text: str) -> dict[str, int]:
    """Parse ``type=number`` pairs such as ``h200=1,h100=0``.

    Blank text gives an empty mapping (no explicit values). Any other malformed pair, a repeated
    type and any value outside the limits raise ValidationError naming the pair or the value.
    """
    if not text.strip():
        return {}
    pairs: list[tuple[str, str]] = []
    for part in text.split(","):
        item = part.strip()
        name, separator, value = item.partition("=")
        if not separator or not name.strip() or not value.strip():
            raise ValidationError(f"{item!r} is not a type=number pair")
        number = value.strip()
        if _WHOLE_NUMBER.fullmatch(number) is None:
            raise ValidationError(
                f"limit for {name.strip()} must be a whole number, not {number!r}"
            )
        pairs.append((name.strip(), number))
    parsed: list[tuple[object, object]] = [(name, int(number)) for name, number in pairs]
    return validate_share_pairs(parsed)


def check_against_account(node_quota: Mapping[str, int], account: Mapping[str, int]) -> None:
    """Refuse a node quota that exceeds the account quota for any type. A type the account does
    not list counts as 0. The error names the type, the requested value and the account quota."""
    for accelerator in sorted(node_quota):
        requested = node_quota[accelerator]
        quota = account.get(accelerator, 0)
        if requested > quota:
            raise ValidationError(
                f"node quota for {accelerator} is {requested}, above the account quota {quota}"
            )


def effective_limits(
    account: Mapping[str, int], node_quota: Mapping[str, int] | None
) -> dict[str, int]:
    """Per type: the smaller of the node quota and the account quota; an unlisted type takes the
    account value. Without a node quota the account quota is the result."""
    result = dict(account)
    if not node_quota:
        return result
    for accelerator, requested in node_quota.items():
        result[accelerator] = min(requested, account.get(accelerator, 0))
    return result


def resolve(account: Mapping[str, int], node_quota: Mapping[str, int] | None) -> ResolvedProfile:
    """The profile a node publishes. An empty node quota counts as no explicit values."""
    explicit = dict(node_quota) if node_quota else None
    source = SOURCE_EXPLICIT if explicit is not None else SOURCE_DEFAULT
    return ResolvedProfile(
        account=dict(account),
        node_quota=explicit,
        effective=effective_limits(account, explicit),
        source=source,
    )
