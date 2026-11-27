"""The minimal contract between hpc-core and the code that reaches a login node.

A transport runs one command given as an argument tuple. It never takes a shell string, so no
caller can smuggle text into a shell. A caller may give standard input as an optional text payload
of at most 64 KiB; it reaches the command on standard input and never in an argument. A non-zero
exit is a result, because a caller may want to read it; a timeout or an unreachable login node is
an error, because there is no result at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# The largest standard-input payload a transport accepts. Larger payloads are refused before any
# command runs.
MAX_INPUT_BYTES = 64 * 1024


class TransportTimeout(Exception):
    """The command did not finish within its timeout."""


class TransportError(Exception):
    """The login node could not be reached, or the command could not be started."""


class InputTooLarge(ValueError):
    """The standard-input payload is over ``MAX_INPUT_BYTES``. Refused before any command runs."""


def check_input(value: str | None) -> None:
    """Refuse a standard-input payload over the limit. ``None`` (no input) is always accepted."""
    if value is not None and len(value.encode("utf-8")) > MAX_INPUT_BYTES:
        raise InputTooLarge("standard input is over the 64 KiB limit")


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_status: int
    truncated: bool = False


class CommandTransport(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
        input: str | None = None,
    ) -> CommandResult:
        """Run ``argv`` on the login node, giving ``input`` as standard input when it is set.

        Raise TransportTimeout or TransportError on failure, and InputTooLarge for an oversized
        ``input`` before any command runs.
        """
        ...
