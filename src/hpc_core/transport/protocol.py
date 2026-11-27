"""The minimal contract between hpc-core and the code that reaches a login node.

A transport runs one command given as an argument tuple. It never takes a shell string, so no
caller can smuggle text into a shell. A non-zero exit is a result, because a caller may want to
read it; a timeout or an unreachable login node is an error, because there is no result at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TransportTimeout(Exception):
    """The command did not finish within its timeout."""


class TransportError(Exception):
    """The login node could not be reached, or the command could not be started."""


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
    ) -> CommandResult:
        """Run ``argv`` on the login node. Raise TransportTimeout or TransportError on failure."""
        ...
