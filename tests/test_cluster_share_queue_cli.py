"""The share-queue flags of ``hpc-core cluster``: pin on beat, the account quota and show and reset
on limits, with the input-not-acceptable status (1) for refusals and no file written. Uses a
temporary team folder and no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpc_core.cli import main
from hpc_core.coordination import layout

EXIT_OK = 0
EXIT_UNACCEPTABLE = 1


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, object] | None]:
    status = main(["cluster", *args])
    out = capsys.readouterr().out
    return status, (json.loads(out) if out.strip() else None)


@pytest.fixture
def root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    team = tmp_path / "team"
    team.mkdir()
    status, _ = _run(capsys, "init", "--root", str(team))
    assert status == EXIT_OK
    # The account profile exists once a node has registered on it.
    status, _ = _run(
        capsys,
        "beat",
        "--root",
        str(team),
        "--node-id",
        "owner-a1",
        "--profile",
        "alice",
        "--kind",
        "console",
    )
    assert status == EXIT_OK
    return team


def _node_file(team: Path, node: str) -> Path:
    return team / layout.node_path(node)


def test_set_the_account_quota_per_type_and_read_it_back(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "owner-a1",
        "--share-queue",
        "H200=2,h100=4",
    )
    assert status == EXIT_OK
    assert body == {"profile_id": "alice", "share_queue_account": {"h100": 4, "h200": 2}}


def test_pin_a_node_on_beat_and_show_its_source_and_effective_limits(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "owner-a1",
        "--share-queue",
        "h200=2",
    )
    status, _ = _run(
        capsys,
        "beat",
        "--root",
        str(root),
        "--node-id",
        "a1",
        "--profile",
        "alice",
        "--kind",
        "console",
        "--share-queue",
        "h200=1",
    )
    assert status == EXIT_OK
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "a1",
        "--show-node",
    )
    assert status == EXIT_OK
    assert body is not None
    assert body["profile_source"] == "explicit"
    assert body["share_queue_node_quota"] == {"h200": 1}
    assert body["share_queue_effective"] == {"h200": 1}
    assert body["share_queue_account"] == {"h200": 2}


def test_a_pin_above_the_account_quota_exits_1_and_writes_no_node_file(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "owner-a1",
        "--share-queue",
        "h200=2",
    )
    status = main(
        [
            "cluster",
            "beat",
            "--root",
            str(root),
            "--node-id",
            "a1",
            "--profile",
            "alice",
            "--kind",
            "console",
            "--share-queue",
            "h200=3",
        ]
    )
    captured = capsys.readouterr()
    assert status == EXIT_UNACCEPTABLE
    assert captured.out == ""
    assert "h200" in captured.err
    assert not _node_file(root, "a1").exists()


@pytest.mark.parametrize("value", ["h200=-1", "h200", "h200=2000", "h 200=1"])
def test_a_malformed_pin_exits_1_with_the_input_status(
    root: Path, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    status, _ = _run(
        capsys,
        "beat",
        "--root",
        str(root),
        "--node-id",
        "a1",
        "--profile",
        "alice",
        "--kind",
        "console",
        "--share-queue",
        value,
    )
    assert status == EXIT_UNACCEPTABLE
    assert not _node_file(root, "a1").exists()


def test_a_quota_change_without_a_node_id_is_refused_and_writes_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (root / layout.profile_path("alice")).read_text(encoding="utf-8")
    status, _ = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--share-queue",
        "h200=2",
    )
    assert status == EXIT_UNACCEPTABLE
    assert (root / layout.profile_path("alice")).read_text(encoding="utf-8") == before


def test_reset_returns_the_node_to_the_account_quota_and_is_idempotent(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "owner-a1",
        "--share-queue",
        "h200=2",
    )
    _run(
        capsys,
        "beat",
        "--root",
        str(root),
        "--node-id",
        "a1",
        "--profile",
        "alice",
        "--kind",
        "console",
        "--share-queue",
        "h200=1",
    )
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "a1",
        "--reset-node",
    )
    assert (status, body) == (EXIT_OK, {"node_id": "a1", "outcome": "reset"})
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "a1",
        "--reset-node",
    )
    assert (status, body) == (EXIT_OK, {"node_id": "a1", "outcome": "unchanged"})
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(root),
        "--profile",
        "alice",
        "--node-id",
        "a1",
        "--show-node",
    )
    assert body is not None
    assert body["profile_source"] == "default"
    assert body["share_queue_effective"] == {"h200": 2}


def test_the_usage_report_carries_the_per_type_section(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, body = _run(capsys, "limits", "--root", str(root), "--profile", "alice")
    assert status == EXIT_OK
    assert body is not None
    assert body["accelerators"] == []
    assert body["valid_leases"] == 0


def test_a_plain_beat_without_the_flag_keeps_the_default_source(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _ = _run(
        capsys,
        "beat",
        "--root",
        str(root),
        "--node-id",
        "a1",
        "--profile",
        "alice",
        "--kind",
        "console",
    )
    assert status == EXIT_OK
    record = json.loads(_node_file(root, "a1").read_text(encoding="utf-8"))
    assert record["profile_source"] == "default"
    assert "node_quota" not in record


def test_the_account_quota_can_be_set_before_any_node_has_joined(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    team = tmp_path / "team"
    team.mkdir()
    _run(capsys, "init", "--root", str(team))
    status, body = _run(
        capsys,
        "limits",
        "--root",
        str(team),
        "--profile",
        "bob",
        "--node-id",
        "bob-console-a1",
        "--share-queue",
        "h200=2",
    )
    assert status == EXIT_OK
    assert body == {"profile_id": "bob", "share_queue_account": {"h200": 2}}
    profile = json.loads((team / layout.profile_path("bob")).read_text(encoding="utf-8"))
    assert profile["concurrency_limit"] == 1
