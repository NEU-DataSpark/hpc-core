"""The optional standard-input payload: absent input behaves as before, present input reaches the
command as a separate value, and anything over 64 KiB is refused before a command runs."""

from __future__ import annotations

import pytest

from hpc_core.testing import FakeTransport
from hpc_core.transport.protocol import MAX_INPUT_BYTES, CommandResult, InputTooLarge


def _fake() -> FakeTransport:
    return FakeTransport({"dd": CommandResult(stdout="", stderr="", exit_status=0)})


def test_a_call_without_input_behaves_as_before() -> None:
    fake = FakeTransport({"squeue": CommandResult(stdout="1\n", stderr="", exit_status=0)})
    result = fake.run(("env", "TZ=UTC", "squeue", "--noheader"), timeout=5, max_output_bytes=100)
    assert result.stdout == "1\n"
    assert fake.calls == [("env", "TZ=UTC", "squeue", "--noheader")]
    assert fake.inputs == [None]


def test_input_reaches_the_command_as_a_separate_value() -> None:
    fake = _fake()
    fake.run(("dd", "of=target", "status=none"), timeout=5, max_output_bytes=100, input="hello\n")
    assert fake.inputs == ["hello\n"]
    assert all("hello" not in argument for argument in fake.calls[0])


def test_input_of_exactly_the_limit_is_accepted() -> None:
    fake = _fake()
    payload = "x" * MAX_INPUT_BYTES
    fake.run(("dd",), timeout=5, max_output_bytes=10, input=payload)
    assert fake.inputs == [payload]


def test_input_of_70_kib_is_refused_before_any_command_runs() -> None:
    fake = _fake()
    with pytest.raises(InputTooLarge):
        fake.run(("dd",), timeout=5, max_output_bytes=10, input="x" * (70 * 1024))
    assert fake.calls == []
