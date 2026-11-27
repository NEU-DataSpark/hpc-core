"""``hpc-core commands``: each printed tuple equals the package builder's, and bad values exit 2.

Named ``test_cli_commands`` because ``tests/slurm/test_commands.py`` already has the other basename.
"""

from __future__ import annotations

import json

import pytest
from conftest import RunCli

from hpc_core.contract import sacct, sinfo, squeue, sstat
from hpc_core.slurm import commands

ACCOUNT = "example-account"
JOB = "4812201"


@pytest.mark.parametrize("profile", ["operator-sampling", "console-monitor"])
def test_queue_matches_the_builder(run_cli: RunCli, profile: str) -> None:
    chosen = squeue.CONSOLE_MONITOR if profile == "console-monitor" else squeue.OPERATOR_SAMPLING
    code, out, err = run_cli("commands", "queue", "--account", ACCOUNT, "--profile", profile)
    assert code == 0, err
    assert json.loads(out) == list(commands.squeue_queue(chosen, ACCOUNT))


def test_finished_matches_the_builder(run_cli: RunCli) -> None:
    code, out, _ = run_cli("commands", "finished", "--account", ACCOUNT, "--hours", "24")
    assert code == 0
    assert json.loads(out) == list(commands.sacct_finished(sacct.OPERATOR_SAMPLING, ACCOUNT, 24))


def test_job_matches_the_builder(run_cli: RunCli) -> None:
    code, out, _ = run_cli("commands", "job", JOB)
    assert code == 0
    assert json.loads(out) == list(commands.sacct_job(sacct.OPERATOR_SAMPLING, JOB))


def test_usage_matches_the_builder(run_cli: RunCli) -> None:
    code, out, _ = run_cli("commands", "usage", JOB)
    assert code == 0
    assert json.loads(out) == list(commands.sstat_usage(sstat.DEFAULT, JOB))


def test_capacity_needs_no_account_and_matches_the_builder(run_cli: RunCli) -> None:
    code, out, err = run_cli("commands", "capacity")
    assert code == 0, err
    assert json.loads(out) == list(commands.sinfo_capacity(sinfo.CAPACITY))


def test_every_printed_tuple_is_read_only(run_cli: RunCli) -> None:
    argv_list = [
        ["commands", "queue", "--account", ACCOUNT],
        ["commands", "finished", "--account", ACCOUNT, "--hours", "1"],
        ["commands", "job", JOB],
        ["commands", "usage", JOB],
        ["commands", "capacity"],
    ]
    write_programs = {"sbatch", "scancel", "srun", "salloc", "scontrol", "sacctmgr"}
    for argv in argv_list:
        code, out, _ = run_cli(*argv)
        assert code == 0
        parts = set(json.loads(out))
        assert parts.isdisjoint(write_programs)
        assert parts & commands.READ_ONLY_PROGRAMS


@pytest.mark.parametrize("account", ["example account", "-example", "example/account", "a;b"])
def test_an_invalid_account_exits_2_with_no_tuple(run_cli: RunCli, account: str) -> None:
    code, out, err = run_cli("commands", "queue", f"--account={account}")
    assert code == 2
    assert out == ""
    assert err != ""


@pytest.mark.parametrize("job_id", ["12;rm", "abc", "1_2_3", ""])
def test_an_invalid_job_id_exits_2_with_no_tuple(run_cli: RunCli, job_id: str) -> None:
    for argv in (["commands", "job", job_id], ["commands", "usage", job_id]):
        code, out, _ = run_cli(*argv)
        assert code == 2
        assert out == ""


def test_there_is_no_default_account(run_cli: RunCli) -> None:
    for argv in (["commands", "queue"], ["commands", "finished", "--hours", "24"]):
        code, out, err = run_cli(*argv)
        assert code == 2
        assert out == ""
        assert "--account" in err


@pytest.mark.parametrize(
    ("hours", "code"), [("0", 2), ("8785", 2), ("x", 2), ("1", 0), ("8784", 0)]
)
def test_hours_are_bounded(run_cli: RunCli, hours: str, code: int) -> None:
    status, out, _ = run_cli("commands", "finished", "--account", ACCOUNT, "--hours", hours)
    assert status == code
    if code == 2:
        assert out == ""


def test_an_unknown_profile_exits_2(run_cli: RunCli) -> None:
    code, out, err = run_cli("commands", "queue", "--account", ACCOUNT, "--profile", "nope")
    assert code == 2
    assert out == ""
    assert "operator-sampling" in err
