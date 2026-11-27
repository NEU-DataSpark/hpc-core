"""Slurm job states, grouped once for the whole package.

The operator and the console disagreed on which states count as queued, running or final. This
module is the single definition: the union of both consumers' lists, with CONFIGURING counted as
running (nodes are allocated and the job is booting). The operator's stage rule is a consumer
concern and must be checked when that consumer migrates.
"""

from __future__ import annotations

from typing import Literal

StateClass = Literal["queued", "running", "final"]

QUEUED: frozenset[str] = frozenset(
    {"PENDING", "REQUEUED", "REQUEUE_HOLD", "REQUEUE_FED", "RESV_DEL_HOLD"}
)
RUNNING: frozenset[str] = frozenset({"RUNNING", "COMPLETING", "SUSPENDED", "CONFIGURING"})
FINAL: frozenset[str] = frozenset(
    {
        "COMPLETED",
        "CANCELLED",
        "FAILED",
        "TIMEOUT",
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "BOOT_FAIL",
        "DEADLINE",
        "PREEMPTED",
        "REVOKED",
        "SPECIAL_EXIT",
    }
)


def state_word(text: str) -> str | None:
    """The state's first word, so ``CANCELLED by 1234`` reads as ``CANCELLED``. None when empty."""
    words = text.split()
    return words[0] if words else None


def record_state(text: str) -> tuple[str | None, StateClass | None]:
    """The state a record keeps, and its class.

    A known state keeps only its first word (``CANCELLED by 1234`` reads as ``CANCELLED``).
    An unknown state keeps its full text, so the record still says what the scheduler reported.
    """
    stripped = text.strip()
    state_class = classify_state(stripped)
    if state_class is not None:
        return state_word(stripped), state_class
    return (stripped or None), None


def classify_state(text: str) -> StateClass | None:
    """queued, running or final for a state, or None when the state is in none of the three sets."""
    word = state_word(text)
    if word is None:
        return None
    if word in QUEUED:
        return "queued"
    if word in RUNNING:
        return "running"
    if word in FINAL:
        return "final"
    return None
