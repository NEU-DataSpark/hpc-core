"""The opt-in job-id rule: pending array ranges and heterogeneous components, on request only."""

from __future__ import annotations

import pytest

from hpc_core.contract.identifiers import (
    ValidationError,
    is_extended_job_id,
    is_job_id,
    validate_extended_job_id,
    validate_job_id,
)


@pytest.mark.parametrize("job_id", ["300_[1-10]", "300_[1-10%2]", "300+1", "300_[1,3-5:2]"])
def test_opted_in_rule_accepts_ranges_and_heterogeneous_components(job_id: str) -> None:
    assert is_extended_job_id(job_id)
    assert validate_extended_job_id(job_id) == job_id


@pytest.mark.parametrize("job_id", ["123", "4812201", "4812201_3"])
def test_opted_in_rule_still_accepts_the_plain_ids(job_id: str) -> None:
    assert validate_extended_job_id(job_id) == job_id


@pytest.mark.parametrize("job_id", ["300_[1-10]", "300_[1-10%2]", "300+1"])
def test_default_rule_still_rejects_ranges_and_heterogeneous_components(job_id: str) -> None:
    assert not is_job_id(job_id)
    with pytest.raises(ValidationError):
        validate_job_id(job_id)


@pytest.mark.parametrize(
    "job_id",
    [
        "300_[1-",  # unterminated range
        "abc",  # not a job id at all
        "300_[1-10]x",  # trailing text after the range
        "300_[]",  # empty range
        "300_[1-]",  # open range
        "300+",  # heterogeneous component without an index
        "300_[1-10]; rm -rf ~",  # shell metacharacters after a valid range
        "300_[1-10]\n",  # trailing newline must not pass the end anchor
        "",
    ],
)
def test_malformed_ids_are_rejected_with_and_without_the_opt_in(job_id: str) -> None:
    assert not is_job_id(job_id)
    assert not is_extended_job_id(job_id)
    with pytest.raises(ValidationError):
        validate_extended_job_id(job_id)


def test_rejection_message_names_the_rule_not_the_value() -> None:
    with pytest.raises(ValidationError) as error:
        validate_extended_job_id("300_[1-")

    assert "300_[1-" not in str(error.value)
    assert "array range" in str(error.value)
