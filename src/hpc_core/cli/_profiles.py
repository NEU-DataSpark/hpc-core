"""The named field profiles the command line offers, per Slurm command.

A profile names the columns a command is asked for. ``commands`` and ``parse`` must use the same
profile for one read, so both take their choices from this one table.
"""

from __future__ import annotations

from ..contract import sacct, sinfo, squeue, sstat
from ..contract.fields import FieldProfile

PROFILES: dict[str, dict[str, FieldProfile]] = {
    "squeue": {
        "operator-sampling": squeue.OPERATOR_SAMPLING,
        "console-monitor": squeue.CONSOLE_MONITOR,
    },
    "sacct": {
        "operator-sampling": sacct.OPERATOR_SAMPLING,
        "console-monitor": sacct.CONSOLE_MONITOR,
    },
    "sinfo": {"capacity": sinfo.CAPACITY},
    "sstat": {"running-usage": sstat.DEFAULT},
}

# The profile used when --profile is not given: the operator's own read of each command.
DEFAULT_PROFILE: dict[str, str] = {
    "squeue": "operator-sampling",
    "sacct": "operator-sampling",
    "sinfo": "capacity",
    "sstat": "running-usage",
}


def profile_names(command: str) -> list[str]:
    return sorted(PROFILES[command])
