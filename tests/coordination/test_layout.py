"""Identifier rules, path builders and size limits of the cluster layout."""

from __future__ import annotations

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout


@pytest.mark.parametrize("value", ["../x", "a/b", "", "has space", "x" * 65, "-leading", ".dot"])
def test_unsafe_identifiers_are_refused_with_the_rule(value: str) -> None:
    with pytest.raises(ValidationError, match="must start with a letter"):
        layout.validate_id(value, "node id")


@pytest.mark.parametrize("value", ["alice.k1", "_team", "9lives", "a-b_c.d", "x" * 64])
def test_accepted_identifiers(value: str) -> None:
    assert layout.validate_id(value) == value


def test_paths_are_built_under_the_cluster_folder() -> None:
    assert layout.node_path("alice.k1") == "_cluster/nodes/alice.k1.json"
    assert layout.profile_path("alice") == "_cluster/profiles/alice.json"
    assert layout.lease_path("alice", 2) == "_cluster/leases/alice/slot-02.json"
    assert layout.inbox_path("bob", "1700-x-abc") == "_cluster/inbox/bob/1700-x-abc.json"
    assert layout.done_path("bob", "1700-x-abc") == "_cluster/inbox/bob/done/1700-x-abc.json"


def test_a_builder_refuses_an_escaping_identifier_before_any_path_exists() -> None:
    with pytest.raises(ValidationError):
        layout.node_path("../x")
    with pytest.raises(ValidationError):
        layout.inbox_dir("a/b")


def test_limits_and_slots_have_their_ranges() -> None:
    assert layout.validate_limit(1) == 1
    assert layout.validate_limit(1024) == 1024
    for bad in (0, 1025, True):
        with pytest.raises(ValidationError, match="1 to 1024"):
            layout.validate_limit(bad)
    with pytest.raises(ValidationError):
        layout.validate_slot(0)


def test_size_limits() -> None:
    assert layout.NODE_RECORD_LIMIT == 16 * 1024
    assert layout.MESSAGE_LIMIT == 64 * 1024


@pytest.mark.parametrize("name", ["h200", "h100", "a-b", "9x", "a", "x" * 32])
def test_accelerator_names_that_follow_the_rule_are_accepted(name: str) -> None:
    assert layout.validate_accelerator(name) == name


def test_upper_case_accelerator_names_are_folded_to_lower_case() -> None:
    assert layout.validate_accelerator("H200") == "h200"
    assert layout.validate_accelerator("H-100") == "h-100"


@pytest.mark.parametrize("name", ["h 200", "h200/x", "x" * 33, "-h200", "h_200", "", "h200.1"])
def test_accelerator_names_outside_the_rule_are_refused_with_the_rule(name: str) -> None:
    with pytest.raises(ValidationError, match="1 to 32 lower-case letters"):
        layout.validate_accelerator(name)


@pytest.mark.parametrize("value", [0, 1, 1024])
def test_share_limits_from_zero_to_1024_are_accepted(value: int) -> None:
    assert layout.validate_share_limit(value, "h200") == value


@pytest.mark.parametrize("value", [-1, 2000, 1025, True, 1.0])
def test_share_limits_outside_the_range_are_refused_with_the_range(value: object) -> None:
    with pytest.raises(ValidationError, match="from 0 to 1024"):
        layout.validate_share_limit(value, "h200")


def test_a_profile_holds_at_most_sixteen_types() -> None:
    sixteen = {f"t{number:02d}": 1 for number in range(16)}
    assert len(layout.validate_share_queue(sixteen)) == 16
    seventeen = {f"t{number:02d}": 1 for number in range(17)}
    with pytest.raises(ValidationError, match="at most 16"):
        layout.validate_share_queue(seventeen)


def test_a_type_given_twice_after_folding_is_refused() -> None:
    with pytest.raises(ValidationError, match="more than once"):
        layout.validate_share_pairs([("h200", 1), ("H200", 2)])
