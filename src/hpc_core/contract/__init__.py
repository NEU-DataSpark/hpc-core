"""Contract layer: standard library only, no I/O.

Scheduler output parsing, identifiers, the run-report CSV schema and its reader, and metrics.
"""

from .fields import (
    Field,
    FieldProfile,
    JobRecord,
    NodeRecord,
    ParseResult,
    ProfileError,
    SstatRecord,
)
from .identifiers import (
    ValidationError,
    is_extended_job_id,
    is_job_id,
    is_step_id,
    validate_account,
    validate_extended_job_id,
    validate_job_id,
)
from .metrics import (
    cpu_hours,
    cpu_seconds_used,
    elapsed_seconds,
    gpu_hours,
    mean,
    peak,
    running_cpu_seconds,
    wait_seconds,
)
from .report import (
    COLUMNS,
    SCHEMA_VERSION,
    SUPPORTED_VERSIONS,
    ReadResult,
    ReportError,
    ReportRow,
    format_report,
    format_row,
    read_report,
)
from .squeue import CONSOLE_MONITOR as SQUEUE_CONSOLE_MONITOR
from .squeue import parse_squeue
from .states import classify_state, state_word
from .times import format_time, parse_duration, parse_report_time, parse_time

__all__ = [
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
    "SQUEUE_CONSOLE_MONITOR",
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
]
