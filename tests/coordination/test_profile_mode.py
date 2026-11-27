"""Profile sets (``node-profile-modes``): modes, entry counts, entry rules, enabled entries, the
text reader and the identities a set gives. Pure in-memory checks; no folder, no clock."""

from __future__ import annotations

import json

import pytest

from hpc_core.contract.identifiers import ValidationError
from hpc_core.coordination import layout
from hpc_core.coordination.profile_mode import (
    MAX_PROFILES,
    ProfileEntry,
    ProfileSet,
    identities_for,
    parse_profile_set,
)
from hpc_core.coordination.registry import NodeIdentity


def _entry(profile: str, node: str | None = None, **extra: object) -> ProfileEntry:
    return ProfileEntry(profile_id=profile, node_id=node, **extra)  # type: ignore[arg-type]


def _base() -> NodeIdentity:
    return NodeIdentity(
        node_id="base-console-0",
        profile_id="base",
        kind="console",
        machine="login-label",
        software_version="9.9.9",
        interval_seconds=45,
        concurrency_limit=1,
        display_name="Base name",
    )


# Requirement: two profile modes


def test_a_set_without_a_mode_is_single() -> None:
    profile_set = parse_profile_set(json.dumps({"profiles": [{"profile_id": "alice"}]}))
    assert profile_set.mode == "single"


def test_mode_is_folded_to_lower_case() -> None:
    profile_set = ProfileSet("MULTI", (_entry("alice"),))
    assert profile_set.mode == "multi"


def test_unknown_mode_is_refused_and_the_error_names_the_allowed_modes() -> None:
    with pytest.raises(ValidationError) as caught:
        ProfileSet("many", (_entry("alice"),))
    message = str(caught.value)
    assert "many" in message and "single" in message and "multi" in message


# Requirement: entries per mode


def test_two_entries_in_single_mode_are_refused_naming_the_count() -> None:
    with pytest.raises(ValidationError, match="single.*found 2"):
        ProfileSet("single", (_entry("alice"), _entry("bob")))


def test_no_entry_in_single_mode_is_refused() -> None:
    with pytest.raises(ValidationError, match="found 0"):
        ProfileSet("single", ())


def test_seventeen_entries_in_multi_mode_are_refused_naming_the_limit() -> None:
    entries = tuple(_entry(f"p{index}") for index in range(MAX_PROFILES + 1))
    with pytest.raises(ValidationError, match="from 1 to 16"):
        ProfileSet("multi", entries)


def test_sixteen_entries_in_multi_mode_are_accepted() -> None:
    entries = tuple(_entry(f"p{index}") for index in range(MAX_PROFILES))
    assert len(ProfileSet("multi", entries).entries) == MAX_PROFILES


def test_multi_mode_without_entries_is_refused() -> None:
    with pytest.raises(ValidationError, match="found 0"):
        ProfileSet("multi", ())


# Requirement: a profile entry


def test_a_complete_entry_keeps_its_values() -> None:
    entry = _entry(
        "alice",
        "alice-c-01",
        display_name="Alice A",
        share_queue={"H200": 1, "h100": 0},
        concurrency_limit=2,
    )
    assert entry.share_queue == {"h200": 1, "h100": 0}
    assert entry.concurrency_limit == 2
    assert entry.enabled is True


def test_an_empty_share_queue_means_no_explicit_quota() -> None:
    assert _entry("alice", share_queue={}).share_queue is None


def test_a_bad_node_id_is_refused() -> None:
    with pytest.raises(ValidationError, match="node id"):
        _entry("alice", "../x")


def test_a_bad_profile_id_is_refused() -> None:
    with pytest.raises(ValidationError, match="profile id"):
        _entry("bad id")


@pytest.mark.parametrize("limit", [0, 1025, True, "2"])
def test_a_concurrency_limit_outside_one_to_1024_is_refused(limit: object) -> None:
    with pytest.raises(ValidationError):
        _entry("alice", concurrency_limit=limit)


def test_an_unknown_field_in_a_document_is_refused_by_name() -> None:
    text = json.dumps({"profiles": [{"profile_id": "alice", "key_path": "/k/secret"}]})
    with pytest.raises(ValidationError) as caught:
        parse_profile_set(text)
    assert "key_path" in str(caught.value)
    assert "/k/secret" not in str(caught.value)


def test_an_unknown_top_level_field_is_refused() -> None:
    with pytest.raises(ValidationError, match="unknown fields 'host'"):
        parse_profile_set(json.dumps({"host": "h", "profiles": []}))


# Requirement: entries are independent nodes


def test_duplicate_node_ids_are_refused_naming_the_id_and_both_positions() -> None:
    with pytest.raises(ValidationError) as caught:
        ProfileSet("multi", (_entry("alice", "n-1"), _entry("bob", "n-1")))
    message = str(caught.value)
    assert "n-1" in message and "1" in message and "2" in message


def test_two_nodes_of_one_profile_keep_their_own_quotas() -> None:
    profile_set = ProfileSet(
        "multi",
        (
            _entry("alice", "alice-a1", share_queue={"h200": 1}),
            _entry("alice", "alice-a2", share_queue={"h200": 2}),
        ),
    )
    quotas = [entry.share_queue for entry in profile_set.entries]
    assert quotas == [{"h200": 1}, {"h200": 2}]


def test_conflicting_limits_for_one_profile_are_refused_naming_both_values() -> None:
    with pytest.raises(ValidationError) as caught:
        ProfileSet(
            "multi",
            (
                _entry("alice", "alice-a1", concurrency_limit=1),
                _entry("alice", "alice-a2", concurrency_limit=3),
            ),
        )
    message = str(caught.value)
    assert "alice" in message and "1" in message and "3" in message


def test_a_disabled_entry_takes_part_in_the_limit_agreement() -> None:
    with pytest.raises(ValidationError, match="conflicting"):
        ProfileSet(
            "multi",
            (
                _entry("alice", "alice-a1", concurrency_limit=1),
                _entry("alice", "alice-a2", concurrency_limit=3, enabled=False),
            ),
        )


def test_a_disabled_entry_takes_part_in_the_node_id_uniqueness() -> None:
    with pytest.raises(ValidationError, match="used by profile entries 1 and 2"):
        ProfileSet(
            "multi",
            (
                _entry("alice", "same"),
                _entry("bob", "same", enabled=False),
            ),
        )


def test_missing_node_ids_are_generated_distinct_and_in_the_expected_form() -> None:
    profile_set = ProfileSet(
        "multi",
        (_entry("alice", "alice-console-fixed"), _entry("alice"), _entry("alice")),
    )
    generated = [entry.node_id for entry in profile_set.entries[1:]]
    assert all(node_id is not None for node_id in generated)
    assert len(set(generated)) == 2
    assert "alice-console-fixed" not in generated
    for node_id in generated:
        assert node_id is not None
        assert node_id.startswith("alice-console-")
        layout.validate_id(node_id, "node id")


# Requirement: enabled entries (design D10)


def test_enabled_defaults_to_true() -> None:
    assert _entry("alice").enabled is True


def test_a_multi_set_with_no_enabled_entry_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least one enabled"):
        ProfileSet("multi", (_entry("alice", enabled=False),))


def test_active_entries_of_multi_mode_are_the_enabled_ones() -> None:
    profile_set = ProfileSet(
        "multi",
        (
            _entry("alice", "alice-a1"),
            _entry("bob", "bob-b1", enabled=False),
            _entry("carol", "carol-c1"),
        ),
    )
    assert [entry.profile_id for entry in profile_set.active_entries] == ["alice", "carol"]


def test_single_mode_ignores_enabled_and_keeps_its_one_entry_active() -> None:
    profile_set = ProfileSet("single", (_entry("alice", "alice-a1", enabled=False),))
    assert profile_set.active_entries == profile_set.entries
    assert profile_set.is_active(profile_set.entries[0]) is True


def test_a_non_boolean_enabled_is_refused() -> None:
    with pytest.raises(ValidationError, match="enabled"):
        _entry("alice", enabled="yes")


# Requirement: reading a profile set from text


def test_a_multi_document_holds_two_entries_and_the_first_has_quota_h200_1() -> None:
    text = json.dumps(
        {
            "mode": "multi",
            "profiles": [
                {"profile_id": "alice", "share_queue": "h200=1"},
                {"profile_id": "bob"},
            ],
        }
    )
    profile_set = parse_profile_set(text)
    assert profile_set.mode == "multi"
    assert len(profile_set.entries) == 2
    assert profile_set.entries[0].share_queue == {"h200": 1}
    assert profile_set.entries[0].node_id is not None


def test_a_document_that_is_not_json_says_so_and_does_not_echo_it() -> None:
    with pytest.raises(ValidationError) as caught:
        parse_profile_set('{"profiles": [ secret-token-here')
    assert "not valid JSON" in str(caught.value)
    assert "secret-token-here" not in str(caught.value)


def test_an_entry_error_names_the_position_and_the_field() -> None:
    text = json.dumps(
        {
            "mode": "multi",
            "profiles": [{"profile_id": "alice"}, {"profile_id": "bob", "node_id": "../x"}],
        }
    )
    with pytest.raises(ValidationError) as caught:
        parse_profile_set(text)
    message = str(caught.value)
    assert "profile entry 2" in message
    assert "node_id" in message


def test_a_bad_share_queue_names_the_entry_and_the_field() -> None:
    text = json.dumps({"profiles": [{"profile_id": "alice", "share_queue": "h200"}]})
    with pytest.raises(ValidationError) as caught:
        parse_profile_set(text)
    assert "profile entry 1" in str(caught.value)
    assert "share_queue" in str(caught.value)


def test_a_missing_profile_id_is_refused_by_field() -> None:
    with pytest.raises(ValidationError, match="profile_id"):
        parse_profile_set(json.dumps({"profiles": [{"node_id": "a-1"}]}))


def test_profiles_must_be_a_list() -> None:
    with pytest.raises(ValidationError, match="list named profiles"):
        parse_profile_set(json.dumps({"mode": "single", "profiles": {"profile_id": "a"}}))


# Identities built from a set (task 1.4)


def test_a_single_entry_that_repeats_the_base_gives_the_base_identity() -> None:
    # The single-node path: one entry that names the same node, profile and no extra settings
    # yields exactly the base identity, so a set in single mode gives the node its usual config.
    base = _base()
    single = ProfileSet("single", (_entry("base", "base-console-0"),))
    assert identities_for(single, base) == (base,)


def test_each_enabled_entry_becomes_its_own_identity_from_the_base() -> None:
    profile_set = ProfileSet(
        "multi",
        (
            _entry("alice", "alice-a1", share_queue={"h200": 1}, display_name="Alice one"),
            _entry("bob", "bob-b1", enabled=False),
            _entry("carol", "carol-c1"),
        ),
    )
    identities = identities_for(profile_set, _base())
    assert [identity.node_id for identity in identities] == ["alice-a1", "carol-c1"]
    first = identities[0]
    assert first.profile_id == "alice"
    assert first.node_quota == {"h200": 1}
    assert first.display_name == "Alice one"
    # Shared settings come from the base configuration.
    assert first.kind == "console"
    assert first.machine == "login-label"
    assert first.software_version == "9.9.9"
    assert first.interval_seconds == 45
    # An entry without its own display name uses the base name.
    assert identities[1].display_name == "Base name"


def test_entries_of_one_profile_share_the_profile_limit_and_fall_back_to_the_base() -> None:
    profile_set = ProfileSet(
        "multi",
        (
            _entry("alice", "alice-a1", concurrency_limit=2),
            _entry("alice", "alice-a2"),
            _entry("bob", "bob-b1"),
        ),
    )
    limits = [identity.concurrency_limit for identity in identities_for(profile_set, _base())]
    assert limits == [2, 2, 1]
