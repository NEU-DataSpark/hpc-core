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
