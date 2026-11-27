"""The event vocabulary of the coordination layer, on the standard ``logging`` package.

The package logger ``hpc_core.coordination`` has a ``NullHandler``, so importing the package prints
nothing. A host attaches its own handler to see events. Every event carries only ids, counts,
durations and short codes, passed as ``fields``. ``fields`` refuses any value that looks like a
path, is too long, or is not a plain scalar, so a folder path, a key path, an environment value or
a message body cannot reach a log through this module.
"""

from __future__ import annotations

import logging
import re
from typing import Final

LOGGER_NAME: Final = "hpc_core.coordination"
MAX_TEXT_LENGTH: Final = 64

NODE_REGISTERED: Final = "node.registered"
NODE_BEAT: Final = "node.beat"
NODE_BEAT_FAILED: Final = "node.beat_failed"
NODE_CONFLICT: Final = "node.conflict"
NODE_LEFT: Final = "node.left"
NODE_PRUNED: Final = "node.pruned"
LEASE_ACQUIRED: Final = "lease.acquired"
LEASE_DENIED: Final = "lease.denied"
LEASE_RECLAIMED: Final = "lease.reclaimed"
LEASE_LOST: Final = "lease.lost"
LEASE_REPAIRED: Final = "lease.repaired"
MESSAGE_SENT: Final = "message.sent"
MESSAGE_REFUSED: Final = "message.refused"
MESSAGE_ACKED: Final = "message.acked"
RECORD_UNREADABLE: Final = "record.unreadable"
STORE_ERROR: Final = "store.error"

EVENTS: Final[frozenset[str]] = frozenset(
    {
        NODE_REGISTERED,
        NODE_BEAT,
        NODE_BEAT_FAILED,
        NODE_CONFLICT,
        NODE_LEFT,
        NODE_PRUNED,
        LEASE_ACQUIRED,
        LEASE_DENIED,
        LEASE_RECLAIMED,
        LEASE_LOST,
        LEASE_REPAIRED,
        MESSAGE_SENT,
        MESSAGE_REFUSED,
        MESSAGE_ACKED,
        RECORD_UNREADABLE,
        STORE_ERROR,
    }
)

# Levels of events that report a problem; everything else is INFO.
_LEVELS: Final[dict[str, int]] = {
    NODE_BEAT_FAILED: logging.WARNING,
    NODE_CONFLICT: logging.WARNING,
    LEASE_LOST: logging.WARNING,
    LEASE_DENIED: logging.INFO,
    MESSAGE_REFUSED: logging.WARNING,
    RECORD_UNREADABLE: logging.WARNING,
    STORE_ERROR: logging.WARNING,
}

_PATH_LIKE = re.compile(r"[/\\]|^~|\.\.|=|://")

logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())


class UnsafeField(ValueError):
    """A field value looks like a path or a body, or is not a plain scalar. Not logged."""


def fields(**values: object) -> dict[str, object]:
    """Check event fields: ids, counts, durations and codes only. Raises UnsafeField otherwise."""
    checked: dict[str, object] = {}
    for name, value in values.items():
        if value is None or isinstance(value, bool | int | float):
            checked[name] = value
            continue
        if not isinstance(value, str):
            raise UnsafeField(f"field '{name}' must be a number, a flag or short text")
        if len(value) > MAX_TEXT_LENGTH:
            raise UnsafeField(f"field '{name}' is longer than {MAX_TEXT_LENGTH} characters")
        if _PATH_LIKE.search(value) or any(character.isspace() for character in value):
            raise UnsafeField(f"field '{name}' looks like a path or free text")
        checked[name] = value
    return checked


def emit(event: str, **values: object) -> None:
    """Log one event of the vocabulary with checked fields. An unknown event name is an error."""
    if event not in EVENTS:
        raise ValueError("unknown coordination event")
    logger.log(
        _LEVELS.get(event, logging.INFO),
        event,
        extra={"hpc_event": event, "hpc_fields": fields(**values)},
    )
