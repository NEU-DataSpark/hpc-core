"""An in-memory transport that replays recorded results. No network, no credentials."""

from __future__ import annotations

from collections.abc import Mapping

from ..transport.protocol import CommandResult, TransportError, TransportTimeout

Reply = CommandResult | TransportTimeout | TransportError


def program_of(argv: tuple[str, ...]) -> str:
    """The Slurm program a command runs, skipping the ``env TZ=UTC`` prefix."""
    rest = argv
    if rest[:2] == ("env", "TZ=UTC"):
        rest = rest[2:]
    return rest[0] if rest else ""


class FakeTransport:
    """Replays one reply per program (``squeue``, ``sacct``, ...) and records every call.

    A reply is a CommandResult, returned as is, or an error, raised. A program with no reply raises
    TransportError, so a test cannot pass by accident. Output over ``max_output_bytes`` is cut and
    marked truncated, as a real transport would do.
    """

    def __init__(self, replies: Mapping[str, Reply]) -> None:
        self._replies = dict(replies)
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
    ) -> CommandResult:
        self.calls.append(argv)
        reply = self._replies.get(program_of(argv))
        if reply is None:
            raise TransportError("no recorded reply for this command")
        if isinstance(reply, BaseException):
            raise reply
        encoded = reply.stdout.encode("utf-8")
        if reply.truncated or len(encoded) <= max_output_bytes:
            return reply
        cut = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
        return CommandResult(
            stdout=cut, stderr=reply.stderr, exit_status=reply.exit_status, truncated=True
        )
