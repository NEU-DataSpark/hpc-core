"""The adapter over FakeTransport: typed errors, truncation, empty results, and the recorded

fixtures.
"""

from __future__ import annotations

import pytest

from hpc_core.contract import sacct, squeue
from hpc_core.contract.identifiers import ValidationError
from hpc_core.slurm import (
    SlurmAdapter,
    SlurmCommandFailed,
    SlurmOutputTruncated,
    SlurmTimeout,
    SlurmTransportError,
)
from hpc_core.testing import FakeTransport, load_case
from hpc_core.testing.fixtures import run_scheduler_case
from hpc_core.transport import CommandResult, TransportError, TransportTimeout


def _adapter(replies: dict[str, object]) -> tuple[SlurmAdapter, FakeTransport]:
    transport = FakeTransport(replies)  # type: ignore[arg-type]
    return SlurmAdapter(transport, account="exampleuser"), transport


def test_timeout_is_typed_and_names_the_command() -> None:
    adapter, _ = _adapter({"squeue": TransportTimeout()})
    with pytest.raises(SlurmTimeout) as error:
        adapter.queue()
    assert error.value.program == "squeue"
    assert "squeue" in str(error.value)


def test_transport_failure_is_typed() -> None:
    adapter, _ = _adapter({"sacct": TransportError()})
    with pytest.raises(SlurmTransportError) as error:
        adapter.finished_jobs(24)
    assert error.value.program == "sacct"


def test_non_zero_exit_names_the_command_and_status_without_stderr() -> None:
    secret = "login01.internal failed: permission denied for /private/path"
    adapter, _ = _adapter({"sacct": CommandResult(stdout="", stderr=secret, exit_status=1)})
    with pytest.raises(SlurmCommandFailed) as error:
        adapter.job_history("4812201")
    message = str(error.value)
    assert "sacct" in message and "status 1" in message
    assert secret not in message
    assert "internal" not in message and "/private" not in message
    assert error.value.exit_status == 1


def test_truncated_output_raises_and_returns_no_records() -> None:
    adapter, _ = _adapter(
        {
            "squeue": CommandResult(
                stdout="1|short|PENDING|...\n", stderr="", exit_status=0, truncated=True
            )
        }
    )
    with pytest.raises(SlurmOutputTruncated):
        adapter.queue()


def test_empty_queue_returns_an_empty_result_without_error() -> None:
    adapter, _ = _adapter({"squeue": CommandResult(stdout="", stderr="", exit_status=0)})
    result = adapter.queue()
    assert result.records == () and result.skipped == 0


def test_invalid_account_is_refused_at_construction() -> None:
    with pytest.raises(ValidationError):
        SlurmAdapter(FakeTransport({}), account="bad account")


def test_invalid_job_id_runs_no_command() -> None:
    adapter, transport = _adapter({"sacct": CommandResult(stdout="", stderr="", exit_status=0)})
    with pytest.raises(ValidationError):
        adapter.job_history("123; rm -rf ~")
    assert transport.calls == []


def test_the_account_comes_from_the_consumer_and_is_the_only_user_argument() -> None:
    adapter, transport = _adapter({"squeue": CommandResult(stdout="", stderr="", exit_status=0)})
    adapter.queue(squeue.OPERATOR_SAMPLING)
    assert "--user=exampleuser" in transport.calls[0]


def test_operator_profile_builds_a_command_with_no_command_text_field() -> None:
    adapter, transport = _adapter({"sacct": CommandResult(stdout="", stderr="", exit_status=0)})
    adapter.finished_jobs(12, sacct.OPERATOR_SAMPLING)
    fmt = [arg for arg in transport.calls[0] if arg.startswith("--format=")][0]
    assert "Command" not in fmt and "%o" not in fmt


def _read_counts(adapter: SlurmAdapter, program: str) -> tuple[int, int]:
    if program == "squeue":
        queued = adapter.queue()
        return queued.skipped, len(queued.records)
    if program == "sacct":
        history = adapter.job_history("100001")
        return history.skipped, len(history.records)
    if program == "sinfo":
        nodes = adapter.capacity()
        return nodes.skipped, len(nodes.records)
    steps = adapter.running_usage("100001")
    return steps.skipped, len(steps.records)


@pytest.mark.parametrize(
    ("case_name", "program"),
    [
        ("squeue-operator", "squeue"),
        ("sacct-operator", "sacct"),
        ("sinfo-capacity", "sinfo"),
        ("sstat-running", "sstat"),
    ],
)
def test_each_read_against_its_recorded_fixture_matches_the_expected_result(
    case_name: str, program: str
) -> None:
    case = load_case("scheduler", case_name)
    adapter, _ = _adapter({program: CommandResult(stdout=case.text, stderr="", exit_status=0)})
    expected = run_scheduler_case(case)
    assert _read_counts(adapter, program) == (expected["skipped"], len(expected["records"]))
