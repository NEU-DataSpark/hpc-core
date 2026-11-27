"""Identifiers that may be placed in a Slurm command: a job id and an account name.

Nothing else is inserted into a command. The rules are strict on purpose: an identifier that
fails them raises ``ValidationError`` before any command exists.
"""

from __future__ import annotations

import re

# A plain job id, or an array task id such as 4812201_3.
JOB_ID_PATTERN = re.compile(r"[0-9]+(?:_[0-9]+)?")
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


def validate_account(text: str) -> str:
    if ACCOUNT_PATTERN.fullmatch(text) is None:
        raise ValidationError(
            "account name may hold only letters, digits, '_', '.' and '-', "
            "and must not start with '-'"
        )
    return text
