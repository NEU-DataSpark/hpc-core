"""Input and output for the command line: read a file or standard input, write JSON.

Standard output carries only the JSON document. Messages for people go to standard error through
``fail``. Nothing here echoes an input row, an environment value or a host name: an error names the
problem and, for an unreadable file, the path the caller gave.
"""

from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from datetime import datetime

from ..contract.times import format_time

STDIN_MARK = "-"
EXIT_OK = 0
EXIT_UNACCEPTABLE = 1
EXIT_USAGE = 2

# Fields added in 0.2.0. A record leaves one of these out when it is unset, so output stays
# identical to the golden files written before they existed. Every other unset value is null.
OMITTED_WHEN_UNSET: frozenset[str] = frozenset({"node_count", "dependency_text", "command"})


class InputError(Exception):
    """The input cannot be read. The message names the path, never the content."""


def read_text(source: str | None) -> str:
    """The text of a file, or of standard input for ``-`` or no source."""
    if source is None or source == STDIN_MARK:
        try:
            return sys.stdin.read()
        except UnicodeDecodeError:
            raise InputError("standard input is not UTF-8 text") from None
    try:
        with open(source, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError:
        raise InputError(f"input file '{source}' is not UTF-8 text") from None
    except OSError:
        raise InputError(f"cannot read input file '{source}'") from None


def to_json_value(value: object) -> object:
    """A JSON-ready form: objects for dataclasses, UTC ISO 8601 text for datetimes, lists."""
    if isinstance(value, datetime):
        return format_time(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_json_value(getattr(value, item.name))
            for item in fields(value)
            if not (item.name in OMITTED_WHEN_UNSET and getattr(value, item.name) is None)
        }
    if isinstance(value, dict):
        return {key: to_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_json_value(item) for item in value]
    return value


def print_json(value: object) -> None:
    """Write one JSON document to standard output and nothing else."""
    sys.stdout.write(json.dumps(to_json_value(value), indent=2, ensure_ascii=False) + "\n")


def fail(message: str, status: int) -> int:
    """Write a message for people to standard error and return the exit status."""
    sys.stderr.write(f"hpc-core: {message}\n")
    return status
