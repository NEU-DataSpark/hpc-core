"""``hpc-core cluster``: the protocol through the command line, one process per command."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

RunCli = Callable[..., tuple[int, str, str]]


@pytest.fixture
def root(tmp_path: Path, run_cli: RunCli) -> str:
    team = tmp_path / "team-folder-7731"
    team.mkdir()
    code, out, _ = run_cli("cluster", "init", "--root", str(team))
    assert code == 0 and json.loads(out) == {"created": True}
    return str(team)


def _beat(run_cli: RunCli, root: str, node: str, profile: str, *extra: str) -> tuple[int, str, str]:
    return run_cli(
        "cluster",
        "beat",
        "--root",
        root,
        "--node-id",
        node,
        "--profile",
        profile,
        "--kind",
        "console",
        *extra,
    )


def _tree(path: str) -> list[str]:
    return sorted(str(item.relative_to(path)) for item in Path(path).rglob("*"))


def test_two_beats_with_different_ids_both_show_online(run_cli: RunCli, root: str) -> None:
    assert _beat(run_cli, root, "alice-console-a1", "alice")[0] == 0
    assert _beat(run_cli, root, "bob-console-b2", "bob")[0] == 0
    code, out, _ = run_cli("cluster", "nodes", "--root", root)
    assert code == 0
    nodes = json.loads(out)["nodes"]
    assert [(n["node_id"], n["profile_id"], n["kind"], n["state"]) for n in nodes] == [
        ("alice-console-a1", "alice", "console", "online"),
        ("bob-console-b2", "bob", "console", "online"),
    ]


def test_a_live_duplicate_id_exits_1(run_cli: RunCli, root: str) -> None:
    assert _beat(run_cli, root, "alice-console-a1", "alice")[0] == 0
    code, out, err = _beat(run_cli, root, "alice-console-a1", "alice")
    assert code == 1 and out == ""
    assert "held by another live instance" in err


def test_a_message_goes_through_send_inbox_and_ack(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-skill-a1", "alice")
    _beat(run_cli, root, "bob-console-b2", "bob")
    code, out, _ = run_cli(
        "cluster",
        "send",
        "--root",
        root,
        "--node-id",
        "alice-skill-a1",
        "--to",
        "bob-console-b2",
        "--type",
        "notice",
    )
    assert code == 0
    message_id = json.loads(out)["message_id"]

    code, out, _ = run_cli("cluster", "inbox", "--root", root, "--node-id", "bob-console-b2")
    assert code == 0
    listed = json.loads(out)
    assert [m["message_id"] for m in listed["messages"]] == [message_id]
    assert listed["skipped"] == 0

    code, out, _ = run_cli(
        "cluster", "ack", "--root", root, "--node-id", "bob-console-b2", message_id
    )
    assert code == 0 and json.loads(out)["outcome"] == "acknowledged"
    code, out, _ = run_cli("cluster", "inbox", "--root", root, "--node-id", "bob-console-b2")
    assert json.loads(out)["messages"] == []


def test_a_message_body_is_read_from_a_file_as_data(
    run_cli: RunCli, root: str, tmp_path: Path
) -> None:
    _beat(run_cli, root, "alice-skill-a1", "alice")
    _beat(run_cli, root, "bob-console-b2", "bob")
    body = tmp_path / "body.json"
    body.write_text('{"text": "rm -rf / ; echo hi"}\n', encoding="utf-8")
    code, _, _ = run_cli(
        "cluster",
        "send",
        "--root",
        root,
        "--node-id",
        "alice-skill-a1",
        "--to",
        "bob-console-b2",
        "--type",
        "notice",
        "--body-file",
        str(body),
    )
    assert code == 0
    _, out, _ = run_cli("cluster", "inbox", "--root", root, "--node-id", "bob-console-b2")
    assert json.loads(out)["messages"][0]["body"] == {"text": "rm -rf / ; echo hi"}


def test_a_recipient_with_path_characters_exits_2_and_writes_nothing(
    run_cli: RunCli, root: str
) -> None:
    _beat(run_cli, root, "alice-skill-a1", "alice")
    before = _tree(root)
    code, out, err = run_cli(
        "cluster",
        "send",
        "--root",
        root,
        "--node-id",
        "alice-skill-a1",
        "--to",
        "../x",
        "--type",
        "notice",
    )
    assert code == 2 and out == ""
    assert _tree(root) == before


def test_sending_to_a_node_with_no_record_exits_1(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-skill-a1", "alice")
    code, out, err = run_cli(
        "cluster",
        "send",
        "--root",
        root,
        "--node-id",
        "alice-skill-a1",
        "--to",
        "ghost-console-g9",
        "--type",
        "notice",
    )
    assert code == 1 and out == ""
    assert "no node record" in err


def test_a_missing_root_exits_1_without_printing_the_path(run_cli: RunCli, tmp_path: Path) -> None:
    missing = str(tmp_path / "no-such-folder-4418")
    code, out, err = run_cli("cluster", "nodes", "--root", missing)
    assert code == 1 and out == ""
    assert "no-such-folder-4418" not in err and missing not in err


def test_a_folder_that_was_never_initialised_exits_1(run_cli: RunCli, tmp_path: Path) -> None:
    empty = tmp_path / "bare"
    empty.mkdir()
    code, _, err = run_cli("cluster", "nodes", "--root", str(empty))
    assert code == 1 and "run cluster init first" in err


def test_check_on_a_healthy_folder_prints_all_ok_and_exits_0(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-console-a1", "alice")
    code, out, _ = run_cli("cluster", "check", "--root", root)
    assert code == 0
    results = json.loads(out)
    assert results and all(r["status"] == "ok" for r in results)
    assert any(r["code"] == "probe.hardlink" for r in results)


def test_check_on_a_seeded_fault_exits_1_and_names_the_code(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-console-a1", "alice")
    Path(root, "_cluster", "nodes", "bob-console-b2.json").write_text("{broken\n", encoding="utf-8")
    code, out, _ = run_cli("cluster", "check", "--root", root, "--read-only")
    assert code == 1
    flagged = {r["code"] for r in json.loads(out) if r["status"] != "ok"}
    assert "record.unreadable" in flagged


def test_verbose_writes_events_to_stderr_and_keeps_stdout_json(run_cli: RunCli, root: str) -> None:
    code, out, err = _beat(run_cli, root, "alice-console-a1", "alice", "--verbose")
    assert code == 0
    assert json.loads(out)["outcome"] == "registered"
    assert "node.registered" in err
    assert "node.registered" not in out


def test_quiet_runs_write_no_events(run_cli: RunCli, root: str) -> None:
    _, _, err = _beat(run_cli, root, "alice-console-a1", "alice")
    assert err == ""


def test_limits_show_and_set(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-console-a1", "alice")
    code, out, _ = run_cli("cluster", "limits", "--root", root, "--profile", "alice")
    assert code == 0 and json.loads(out)["limit"] == 1
    code, out, _ = run_cli(
        "cluster",
        "limits",
        "--root",
        root,
        "--profile",
        "alice",
        "--node-id",
        "alice-console-a1",
        "--set",
        "3",
    )
    assert code == 0 and json.loads(out) == {"profile_id": "alice", "concurrency_limit": 3}


def test_setting_a_limit_without_a_node_id_exits_2(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-console-a1", "alice")
    code, out, _ = run_cli("cluster", "limits", "--root", root, "--profile", "alice", "--set", "3")
    assert code == 2 and out == ""


def test_an_out_of_range_limit_exits_2(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-console-a1", "alice")
    code, _, _ = run_cli(
        "cluster",
        "limits",
        "--root",
        root,
        "--profile",
        "alice",
        "--node-id",
        "alice-console-a1",
        "--set",
        "5000",
    )
    assert code == 2


def test_an_unknown_kind_is_refused_by_the_parser(run_cli: RunCli, root: str) -> None:
    code, _, _ = run_cli(
        "cluster",
        "beat",
        "--root",
        root,
        "--node-id",
        "alice-x1",
        "--profile",
        "alice",
        "--kind",
        "laptop",
    )
    assert code == 2


def test_an_interval_under_30_seconds_exits_2(run_cli: RunCli, root: str) -> None:
    code, _, _ = _beat(run_cli, root, "alice-console-a1", "alice", "--interval-seconds", "10")
    assert code == 2


def test_leave_from_a_later_process_cannot_remove_an_earlier_record(
    run_cli: RunCli, root: str
) -> None:
    """Known limit: each command has its own instance token, so a later leave is not ours."""
    _beat(run_cli, root, "alice-console-a1", "alice")
    code, out, err = run_cli(
        "cluster",
        "leave",
        "--root",
        root,
        "--node-id",
        "alice-console-a1",
        "--profile",
        "alice",
        "--kind",
        "console",
    )
    assert code == 1 and out == ""
    assert "belongs to another instance" in err
