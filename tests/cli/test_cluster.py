"""``hpc-core cluster``: the protocol through the command line, one process per command."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from hpc_core.coordination.registry import NodeIdentity, NodeSession
from hpc_core.coordination.shared import publish_shared
from hpc_core.coordination.store import LocalFolderStore

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


# ``cluster profiles``: read a profile set file, open no team folder (task 1.7)


def _write(tmp_path: Path, document: object, name: str = "profiles.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_profiles_prints_mode_and_entries_with_their_node_ids(
    run_cli: RunCli, tmp_path: Path
) -> None:
    path = _write(
        tmp_path,
        {
            "mode": "multi",
            "profiles": [
                {"profile_id": "alice", "node_id": "alice-a1", "share_queue": "h200=1"},
                {"profile_id": "bob", "node_id": "bob-b1", "enabled": False},
            ],
        },
    )
    code, out, err = run_cli("cluster", "profiles", "--file", path)
    assert code == 0 and err == ""
    document = json.loads(out)
    assert document["mode"] == "multi"
    assert [
        (row["profile_id"], row["node_id"], row["enabled"]) for row in document["profiles"]
    ] == [
        ("alice", "alice-a1", True),
        ("bob", "bob-b1", False),
    ]
    assert document["profiles"][0]["share_queue"] == {"h200": 1}


def test_profiles_reports_a_single_entry_as_enabled_even_when_the_file_says_otherwise(
    run_cli: RunCli, tmp_path: Path
) -> None:
    path = _write(tmp_path, {"profiles": [{"profile_id": "alice", "enabled": False}]})
    code, out, _ = run_cli("cluster", "profiles", "--file", path)
    assert code == 0
    row = json.loads(out)["profiles"][0]
    assert json.loads(out)["mode"] == "single"
    assert row["enabled"] is True and row["node_id"]


def test_a_refused_profile_file_exits_1_and_prints_no_entries(
    run_cli: RunCli, tmp_path: Path
) -> None:
    path = _write(
        tmp_path,
        {
            "mode": "multi",
            "profiles": [
                {"profile_id": "alice", "node_id": "same"},
                {"profile_id": "bob", "node_id": "same"},
            ],
        },
    )
    code, out, err = run_cli("cluster", "profiles", "--file", path)
    assert code == 1 and out == ""
    assert "same" in err


def test_a_profile_file_with_two_entries_in_single_mode_is_refused(
    run_cli: RunCli, tmp_path: Path
) -> None:
    path = _write(
        tmp_path, {"mode": "single", "profiles": [{"profile_id": "a"}, {"profile_id": "b"}]}
    )
    code, out, err = run_cli("cluster", "profiles", "--file", path)
    assert code == 1 and out == ""
    assert "single" in err and "2" in err


def test_profiles_reads_standard_input_with_a_dash(
    run_cli: RunCli, feed_stdin: Callable[[str], None]
) -> None:
    feed_stdin(json.dumps({"mode": "multi", "profiles": [{"profile_id": "alice"}]}))
    code, out, _ = run_cli("cluster", "profiles", "--file", "-")
    assert code == 0
    assert json.loads(out)["profiles"][0]["profile_id"] == "alice"


def test_profiles_takes_no_team_folder(run_cli: RunCli, tmp_path: Path) -> None:
    # The command opens no folder, so it has no --root; passing one is a usage error.
    path = _write(tmp_path, {"profiles": [{"profile_id": "alice"}]})
    before = _tree(str(tmp_path))
    code, _, _ = run_cli("cluster", "profiles", "--root", str(tmp_path), "--file", path)
    assert code == 2
    assert _tree(str(tmp_path)) == before


def test_an_unreadable_profile_file_exits_2(run_cli: RunCli, tmp_path: Path) -> None:
    code, out, err = run_cli("cluster", "profiles", "--file", str(tmp_path / "missing.json"))
    assert code == 2 and out == ""
    assert "cannot read input file" in err


# -- shared datasets: read-only commands -------------------------------------------------------


def _mark_candidate(root: str, node: str) -> None:
    """A console that can collect writes its own marked record. The CLI does not set the mark."""
    identity = NodeIdentity(node, node.split("-", 1)[0], "console", shared_collector=True)
    assert NodeSession(LocalFolderStore(Path(root)), identity).register().outcome == "registered"


def _publish(root: str, dataset: str, node: str, payload: dict[str, object]) -> None:
    publish_shared(LocalFolderStore(Path(root)), dataset, node_id=node, payload=payload)


def test_collector_names_the_elected_candidate_and_the_age_of_each_shared_file(
    run_cli: RunCli, root: str
) -> None:
    _mark_candidate(root, "alice-console-a1")
    _mark_candidate(root, "bob-console-b2")
    _publish(root, "queue", "alice-console-a1", {"running": 3})
    code, out, err = run_cli("cluster", "collector", "--root", root)
    assert code == 0 and err == ""
    report = json.loads(out)
    assert report["collector_node_id"] == "alice-console-a1"
    assert [(row["dataset"], type(row["age_seconds"]).__name__) for row in report["shared"]] == [
        ("queue", "int")
    ]


def test_collector_is_null_when_no_candidate_is_online(run_cli: RunCli, root: str) -> None:
    _beat(run_cli, root, "alice-skill-a1", "alice")
    code, out, _ = run_cli("cluster", "collector", "--root", root)
    assert code == 0
    assert json.loads(out) == {"collector_node_id": None, "shared": []}


def test_shared_prints_the_payload_age_and_collector(run_cli: RunCli, root: str) -> None:
    _publish(root, "queue", "alice-console-a1", {"running": 3})
    code, out, err = run_cli("cluster", "shared", "--root", root, "--dataset", "queue")
    assert code == 0 and err == ""
    body = json.loads(out)
    assert body["status"] == "present"
    assert body["collector_node_id"] == "alice-console-a1"
    assert body["payload"] == {"running": 3}
    assert isinstance(body["age_seconds"], int) and body["age_seconds"] >= 0


def test_a_missing_dataset_is_reported_with_status_zero(run_cli: RunCli, root: str) -> None:
    code, out, err = run_cli("cluster", "shared", "--root", root, "--dataset", "physical")
    assert code == 0 and err == ""
    assert json.loads(out) == {"dataset": "physical", "status": "missing"}


def test_an_unreadable_shared_file_exits_1_with_nothing_on_standard_output(
    run_cli: RunCli, root: str
) -> None:
    (Path(root) / "_cluster" / "shared").mkdir()
    (Path(root) / "_cluster" / "shared" / "queue.txt").write_text("not json", encoding="utf-8")
    code, out, err = run_cli("cluster", "shared", "--root", root, "--dataset", "queue")
    assert code == 1 and out == ""
    assert "unreadable" in err


def test_a_bad_dataset_name_is_a_usage_error_that_names_the_rule(
    run_cli: RunCli, root: str
) -> None:
    code, out, err = run_cli("cluster", "shared", "--root", root, "--dataset", "../x")
    assert code == 2 and out == ""
    assert "must be 1 to 32" in err


def test_the_shared_commands_change_nothing_in_the_folder(run_cli: RunCli, root: str) -> None:
    _mark_candidate(root, "alice-console-a1")
    _publish(root, "queue", "alice-console-a1", {"running": 3})
    before = _tree(root)
    before_bytes = (Path(root) / "_cluster" / "shared" / "queue.txt").read_bytes()
    assert run_cli("cluster", "collector", "--root", root)[0] == 0
    assert run_cli("cluster", "shared", "--root", root, "--dataset", "queue")[0] == 0
    assert run_cli("cluster", "shared", "--root", root, "--dataset", "physical")[0] == 0
    assert _tree(root) == before
    assert (Path(root) / "_cluster" / "shared" / "queue.txt").read_bytes() == before_bytes
