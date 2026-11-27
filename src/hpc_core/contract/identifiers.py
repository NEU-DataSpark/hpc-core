"""Identifiers that may be placed in a Slurm command: a job id and an account name.

Nothing else is inserted into a command. The rules are strict on purpose: an identifier that
fails them raises ``ValidationError`` before any command exists.
"""

from __future__ import annotations

import re

# A plain job id, or an array task id such as 4812201_3.
JOB_ID_PATTERN = re.compile(r"[0-9]+(?:_[0-9]+)?")
# Opt-in only (see is_extended_job_id): a pending array range such as 300_[1-10], 300_[1-10%2] or
# 300_[1,3-5:2], and a heterogeneous job component such as 300+1. Slurm prints these for pending
# array and heterogeneous jobs, so a reader that expects only running tasks must not accept them by
# default.
_RANGE_ITEM = r"[0-9]+(?:-[0-9]+(?::[0-9]+)?)?"
_ARRAY_RANGE = r"_\[" + _RANGE_ITEM + r"(?:," + _RANGE_ITEM + r")*(?:%[0-9]+)?\]"
EXTENDED_JOB_ID_PATTERN = re.compile(r"[0-9]+(?:_[0-9]+|" + _ARRAY_RANGE + r"|\+[0-9]+)?")
# A job step id as printed by sstat, such as 4812201.0 or 4812201_3.batch.
STEP_ID_PATTERN = re.compile(r"[0-9]+(?:_[0-9]+)?\.[A-Za-z0-9]+")
# Letters, digits, underscore, dot and hyphen; must not start with a hyphen.
ACCOUNT_PATTERN = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*")


class ValidationError(ValueError):
    """A value that may not be used in a command. The message names the rule, not the value."""


def is_job_id(text: str) -> bool:
    return JOB_ID_PATTERN.fullmatch(text) is not None


def is_step_id(text: str) -> bool:
    return STEP_ID_PATTERN.fullmatch(text) is not None


def validate_job_id(text: str) -> str:
    if not is_job_id(text):
        raise ValidationError("job id must be digits with an optional _<index> suffix")
    return text


def is_extended_job_id(text: str) -> bool:
    """A job id that also allows a pending array range or a heterogeneous component.

    This is the opt-in rule. ``is_job_id`` and ``validate_job_id`` keep their default behaviour.
    """
    return EXTENDED_JOB_ID_PATTERN.fullmatch(text) is not None


def validate_extended_job_id(text: str) -> str:
    if not is_extended_job_id(text):
        raise ValidationError(
            "job id must be digits, an optional _<index> suffix, an array range such as "
            "_[1-10%2], or a heterogeneous component such as +1"
        )
    return text


def validate_account(text: str) -> str:
    if ACCOUNT_PATTERN.fullmatch(text) is None:
        raise ValidationError(
            "account name may hold only letters, digits, '_', '.' and '-', "
            "and must not start with '-'"
        )
    return text
