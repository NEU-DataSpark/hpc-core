"""The scheduler adapter: fixed read-only reads, run through a transport, parsed into records.

The consumer supplies the transport and the account (from its own settings, never from a request).
A failed read raises a typed error that names the command and the exit status. The raw standard
error is never put into an error, because it can name hosts or paths. Truncated output is never
parsed: a cut row would read as a different row.
"""

from __future__ import annotations

from ..contract import sacct, sinfo, squeue, sstat
from ..contract.fields import FieldProfile, JobRecord, NodeRecord, ParseResult, SstatRecord
from ..contract.identifiers import validate_account
from ..transport.protocol import CommandTransport, TransportError, TransportTimeout
from . import commands

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


class SlurmError(Exception):
    """Base class of every adapter failure. ``program`` names the command that failed."""

    def __init__(self, program: str, message: str) -> None:
        super().__init__(message)
        self.program = program


class SlurmTimeout(SlurmError):
    """The command did not finish in time."""


class SlurmTransportError(SlurmError):
    """The login node could not be reached or the command could not be started."""


class SlurmCommandFailed(SlurmError):
    """The command exited with a non-zero status."""

    def __init__(self, program: str, exit_status: int) -> None:
        super().__init__(program, f"{program} exited with status {exit_status}")
        self.exit_status = exit_status


class SlurmOutputTruncated(SlurmError):
    """The output reached the size limit. It was not parsed."""

    def __init__(self, program: str) -> None:
        super().__init__(
            program, f"{program} output was truncated at the size limit; nothing was parsed"
        )


class SlurmAdapter:
    def __init__(
        self,
        transport: CommandTransport,
        *,
        account: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self._transport = transport
        self._account = validate_account(account)
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes

    def queue(self, profile: FieldProfile = squeue.OPERATOR_SAMPLING) -> ParseResult[JobRecord]:
        """The account's jobs in the queue now."""
        text = self._read("squeue", commands.squeue_queue(profile, self._account))
        return squeue.parse_squeue(text, profile)

    def finished_jobs(
        self, hours: int, profile: FieldProfile = sacct.OPERATOR_SAMPLING
    ) -> ParseResult[JobRecord]:
        """The account's job allocations that started in the last ``hours`` hours (steps

        excluded).
        """
        text = self._read("sacct", commands.sacct_finished(profile, self._account, hours))
        return sacct.parse_sacct(text, profile)

    def job_history(
        self, job_id: str, profile: FieldProfile = sacct.OPERATOR_SAMPLING
    ) -> ParseResult[JobRecord]:
        """The accounting record of one job allocation."""
        text = self._read("sacct", commands.sacct_job(profile, job_id))
        return sacct.parse_sacct(text, profile)

    def running_usage(
        self, job_id: str, profile: FieldProfile = sstat.DEFAULT
    ) -> ParseResult[SstatRecord]:
        """Usage of the running steps of one job."""
        text = self._read("sstat", commands.sstat_usage(profile, job_id))
        return sstat.parse_sstat(text, profile)

    def capacity(self, profile: FieldProfile = sinfo.CAPACITY) -> ParseResult[NodeRecord]:
        """Partition capacity: node counts, states and GPUs per node."""
        text = self._read("sinfo", commands.sinfo_capacity(profile))
        return sinfo.parse_sinfo(text, profile)

    def _read(self, program: str, argv: tuple[str, ...]) -> str:
        try:
            result = self._transport.run(
                argv, timeout=self._timeout, max_output_bytes=self._max_output_bytes
            )
        except TransportTimeout:
            raise SlurmTimeout(
                program, f"{program} did not finish within {self._timeout:g} seconds"
            ) from None
        except TransportError:
            raise SlurmTransportError(
                program, f"{program} could not be run on the login node"
            ) from None
        if result.exit_status != 0:
            raise SlurmCommandFailed(program, result.exit_status)
        if result.truncated:
            raise SlurmOutputTruncated(program)
        return result.stdout
