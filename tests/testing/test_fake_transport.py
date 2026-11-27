"""The fake transport replays a result, a non-zero exit, truncation, a timeout and an

unreachable node.
"""

from __future__ import annotations

import pytest

from hpc_core.testing.fake_transport import FakeTransport
from hpc_core.transport.protocol import CommandResult, TransportError, TransportTimeout

ARGV = ("env", "TZ=UTC", "squeue", "--noheader")


def _run(transport: FakeTransport, max_output_bytes: int = 4 * 1024 * 1024) -> CommandResult:
    return transport.run(ARGV, timeout=10, max_output_bytes=max_output_bytes)


def test_normal_result_is_returned_unchanged() -> None:
    transport = FakeTransport({"squeue": CommandResult(stdout="1|a\n", stderr="", exit_status=0)})
    result = _run(transport)
    assert (result.stdout, result.exit_status, result.truncated) == ("1|a\n", 0, False)
    assert transport.calls == [ARGV]


def test_non_zero_exit_is_a_result_not_an_error() -> None:
    transport = FakeTransport({"squeue": CommandResult(stdout="", stderr="bad", exit_status=1)})
    result = _run(transport)
    assert result.exit_status == 1
    assert result.stderr == "bad"


def test_truncation_is_replayed_as_recorded() -> None:
    transport = FakeTransport(
        {"squeue": CommandResult(stdout="x", stderr="", exit_status=0, truncated=True)}
    )
    assert _run(transport).truncated is True


def test_output_over_the_limit_is_cut_and_marked() -> None:
    transport = FakeTransport({"squeue": CommandResult(stdout="abcdef", stderr="", exit_status=0)})
    result = _run(transport, max_output_bytes=3)
    assert (result.stdout, result.truncated) == ("abc", True)


def test_timeout_is_raised() -> None:
    transport = FakeTransport({"squeue": TransportTimeout()})
    with pytest.raises(TransportTimeout):
        _run(transport)


def test_unreachable_login_node_is_raised() -> None:
    transport = FakeTransport({"squeue": TransportError()})
    with pytest.raises(TransportError):
        _run(transport)


def test_program_without_a_reply_fails_loudly() -> None:
    with pytest.raises(TransportError):
        _run(FakeTransport({}))
