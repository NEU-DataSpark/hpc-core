"""Golden cluster fixtures: a good record decodes; corrupt text and an unknown version come back
as ``Unreadable`` with a reason, never as an exception."""

from __future__ import annotations

from importlib import resources

import pytest

from hpc_core.coordination import records

FIXTURES = resources.files("hpc_core.testing") / "fixtures" / "cluster"


def _text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def test_the_node_fixture_decodes_with_fictional_ids() -> None:
    node = records.decode_node(_text("node"), expected_id="alice-console-a1")
    assert isinstance(node, records.NodeRecord)
    assert (node.profile_id, node.kind, node.interval_seconds) == ("alice", "console", 60)


def test_the_profile_lease_and_message_fixtures_decode() -> None:
    profile = records.decode_profile(_text("profile"), expected_id="alice")
    lease = records.decode_lease(_text("lease"), expected_id=None)
    message = records.decode_message(_text("message"))
    assert isinstance(profile, records.ProfileRecord) and profile.concurrency_limit == 2
    assert isinstance(lease, records.LeaseRecord) and lease.slot == 1
    assert isinstance(message, records.MessageRecord) and message.type == "notice"


def test_a_corrupt_fixture_is_unreadable_not_an_exception() -> None:
    result = records.decode_node(_text("corrupt"), expected_id="alice-console-a1")
    assert isinstance(result, records.Unreadable)
    assert result.reason == records.REASON_NOT_JSON


def test_an_unknown_version_fixture_is_unreadable_with_the_version_reason() -> None:
    result = records.decode_node(_text("unknown_version"), expected_id="alice-console-a1")
    assert isinstance(result, records.Unreadable)
    assert result.reason == records.REASON_VERSION


@pytest.mark.parametrize("name", ["node", "profile", "lease", "message", "unknown_version"])
def test_every_fixture_is_one_compact_line_ending_in_a_newline(name: str) -> None:
    text = _text(name)
    assert text.endswith("\n") and text.count("\n") == 1
