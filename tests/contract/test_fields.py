"""Field profiles: named cells, the free-text-last rule, and bad-row splitting."""

from __future__ import annotations

import pytest

from hpc_core.contract.fields import Field, FieldProfile, ProfileError, iter_rows
from hpc_core.contract.squeue import OPERATOR_SAMPLING, parse_squeue

NAME_LAST = FieldProfile(
    name="two",
    command="squeue",
    fields=(Field("job_id", "%i"), Field("job_name", "%j", free_text=True)),
)


def test_name_containing_the_separator_does_not_shift_other_fields() -> None:
    rows, skipped = iter_rows("77|a|b|c\n", NAME_LAST)
    assert rows == [{"job_id": "77", "job_name": "a|b|c"}]
    assert skipped == 0


def test_free_text_not_last_is_rejected_and_named() -> None:
    with pytest.raises(ProfileError, match="'job_name'"):
        FieldProfile(
            name="bad",
            command="squeue",
            fields=(Field("job_name", "%j", free_text=True), Field("job_id", "%i")),
        )


def test_duplicate_field_is_rejected() -> None:
    with pytest.raises(ProfileError, match="duplicate field 'job_id'"):
        FieldProfile(
            name="dup", command="squeue", fields=(Field("job_id", "%i"), Field("job_id", "%i"))
        )


def test_unsupported_command_and_bad_separator_are_rejected() -> None:
    with pytest.raises(ProfileError):
        FieldProfile(name="x", command="rm", fields=(Field("job_id", "%i"),))
    with pytest.raises(ProfileError):
        FieldProfile(name="x", command="squeue", fields=(Field("job_id", "%i"),), separator=",")


def test_profile_naming_a_field_the_parser_does_not_read_is_rejected() -> None:
    profile = FieldProfile(name="odd", command="squeue", fields=(Field("command_text", "%o"),))
    with pytest.raises(ProfileError, match="'command_text'"):
        parse_squeue("1|x", profile)


def test_too_few_cells_is_skipped_and_counted_and_blank_lines_are_not() -> None:
    two = FieldProfile(
        name="two", command="squeue", fields=(Field("job_id", "%i"), Field("partition", "%P"))
    )
    rows, skipped = iter_rows("1|a\n\n2\n3|b\n", two)
    assert [row["job_id"] for row in rows] == ["1", "3"]
    assert skipped == 1


def test_extra_cells_are_skipped_unless_the_last_field_is_free_text() -> None:
    fixed = FieldProfile(
        name="fixed", command="squeue", fields=(Field("a", "%i"), Field("b", "%P"))
    )
    rows, skipped = iter_rows("1|2|3\n", fixed)
    assert rows == [] and skipped == 1


def test_operator_profile_has_no_command_text_field() -> None:
    assert "command" not in OPERATOR_SAMPLING.names
    assert "command_text" not in OPERATOR_SAMPLING.names
