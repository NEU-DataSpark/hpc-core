"""Job-id and account-name rules: what may be placed in a command, and what may not."""

from __future__ import annotations

import pytest

from hpc_core.contract.identifiers import (
    ValidationError,
    is_job_id,
    validate_account,
    validate_job_id,
)


@pytest.mark.parametrize("job_id", ["123", "4812201", "4812201_3", "1_0"])
def test_valid_job_ids(job_id: str) -> None:
    assert is_job_id(job_id)
    assert validate_job_id(job_id) == job_id


@pytest.mark.parametrize(
    "job_id",
    [
        "123; rm -rf ~",  # shell metacharacters
        "123\n",  # trailing newline must not pass a regex end anchor
        " 123",
        "12 34",
        "4812201_",
        "_3",
        "4812201_[3-5]",
        "4812201_3_4",
        "job",
        "",
        "-1",
    ],
)
def test_invalid_job_ids_raise(job_id: str) -> None:
    assert not is_job_id(job_id)
    with pytest.raises(ValidationError):
        validate_job_id(job_id)


@pytest.mark.parametrize("account", ["exampleuser", "a.b-c_d", "ACC1", "_svc", ".hidden"])
def test_valid_accounts(account: str) -> None:
    assert validate_account(account) == account


@pytest.mark.parametrize(
    "account",
    ["with space", 'with"quote', "with/slash", "-leading", "semi;colon", "", "tab\tname"],
)
def test_invalid_accounts_raise(account: str) -> None:
    with pytest.raises(ValidationError):
        validate_account(account)
