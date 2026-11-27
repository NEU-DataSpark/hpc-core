"""The public API is the names exported by contract, transport and slurm; a change here is a
versioning event (see docs/versioning.md)."""

from __future__ import annotations

import hpc_core.contract
import hpc_core.slurm
import hpc_core.transport

EXPECTED_CONTRACT = {
    "COLUMNS",
    "SCHEMA_VERSION",
    "SUPPORTED_VERSIONS",
    "Field",
    "FieldProfile",
    "JobRecord",
    "NodeRecord",
    "ParseResult",
    "ProfileError",
    "ReadResult",
    "ReportError",
    "ReportRow",
    "SQUEUE_CONSOLE_MONITOR",
    "SstatRecord",
    "ValidationError",
    "classify_state",
    "cpu_hours",
    "cpu_seconds_used",
    "elapsed_seconds",
    "format_report",
    "format_row",
    "format_time",
    "gpu_hours",
    "is_extended_job_id",
    "is_job_id",
    "is_step_id",
    "mean",
    "parse_duration",
    "parse_report_time",
    "parse_squeue",
    "parse_time",
    "peak",
    "read_report",
    "running_cpu_seconds",
    "state_word",
    "validate_account",
    "validate_extended_job_id",
    "validate_job_id",
    "wait_seconds",
}
EXPECTED_TRANSPORT = {"CommandResult", "CommandTransport", "TransportError", "TransportTimeout"}
EXPECTED_SLURM = {
    "READ_ONLY_PROGRAMS",
    "SlurmAdapter",
    "SlurmCommandFailed",
    "SlurmError",
    "SlurmOutputTruncated",
    "SlurmTimeout",
    "SlurmTransportError",
}


def test_contract_public_names() -> None:
    assert set(hpc_core.contract.__all__) == EXPECTED_CONTRACT


def test_transport_public_names() -> None:
    assert set(hpc_core.transport.__all__) == EXPECTED_TRANSPORT


def test_slurm_public_names() -> None:
    assert set(hpc_core.slurm.__all__) == EXPECTED_SLURM
