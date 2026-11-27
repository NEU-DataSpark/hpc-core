"""Scheduler adapter layer: fixed read-only Slurm commands run through a transport, parsed by

contract.
"""

from .adapter import (
    SlurmAdapter,
    SlurmCommandFailed,
    SlurmError,
    SlurmOutputTruncated,
    SlurmTimeout,
    SlurmTransportError,
)
from .commands import READ_ONLY_PROGRAMS

__all__ = [
    "READ_ONLY_PROGRAMS",
    "SlurmAdapter",
    "SlurmCommandFailed",
    "SlurmError",
    "SlurmOutputTruncated",
    "SlurmTimeout",
    "SlurmTransportError",
]
