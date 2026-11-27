"""Command builders: fixed templates, validated inputs, and only read-only programs."""

from __future__ import annotations

import pytest

from hpc_core.contract import sacct, sinfo, squeue, sstat
from hpc_core.contract.identifiers import ValidationError
from hpc_core.slurm import commands
from hpc_core.slurm.commands import READ_ONLY_PROGRAMS


def test_queue_command_is_the_fixed_template_with_the_account_in_one_argument() -> None:
    argv = commands.squeue_queue(squeue.OPERATOR_SAMPLING, "exampleuser")
    assert argv == (
        "env",
        "TZ=UTC",
        "squeue",
        "--noheader",
        "--user=exampleuser",
        "-o",
        "%i|%P|%T|%V|%S|%C|%b|%r|%j",
    )


def test_finished_jobs_command() -> None:
    argv = commands.sacct_finished(sacct.OPERATOR_SAMPLING, "exampleuser", 48)
    assert argv[:9] == (
        "env",
        "TZ=UTC",
        "sacct",
        "-n",
        "-P",
        "-X",
        "--user=exampleuser",
        "--starttime=now-48hours",
        "--format=JobID,Partition,State,Submit,Start,End,AllocCPUS,AllocTRES,TotalCPU,MaxRSS,JobName",
    )
    assert argv[-1] == "--delimiter=|"


def test_job_history_accepts_an_array_task_id() -> None:
    argv = commands.sacct_job(sacct.OPERATOR_SAMPLING, "4812201_3")
    assert "--jobs=4812201_3" in argv


def test_running_usage_and_capacity_commands() -> None:
    assert commands.sstat_usage(sstat.DEFAULT, "4812201") == (
        "env",
        "TZ=UTC",
        "sstat",
        "-n",
        "-P",
        "-a",
        "--jobs=4812201",
        "--format=JobID,AveCPU,NTasks,MaxRSS",
    )
    assert commands.sinfo_capacity(sinfo.CAPACITY) == (
        "env",
        "TZ=UTC",
        "sinfo",
        "--noheader",
        "-o",
        "%P|%G|%t|%D",
    )


@pytest.mark.parametrize("job_id", ["123; rm -rf ~", "123 456", "$(id)", "--help", ""])
def test_job_id_with_free_text_raises_before_any_command_exists(job_id: str) -> None:
    with pytest.raises(ValidationError):
        commands.sacct_job(sacct.OPERATOR_SAMPLING, job_id)
    with pytest.raises(ValidationError):
        commands.sstat_usage(sstat.DEFAULT, job_id)


@pytest.mark.parametrize("account", ["with space", "-leading", 'quo"te', "a/b"])
def test_account_with_a_bad_shape_raises(account: str) -> None:
    with pytest.raises(ValidationError):
        commands.squeue_queue(squeue.OPERATOR_SAMPLING, account)
    with pytest.raises(ValidationError):
        commands.sacct_finished(sacct.OPERATOR_SAMPLING, account, 1)


@pytest.mark.parametrize("hours", [0, -1, 24 * 366 + 1, True, 1.5])
def test_hours_outside_the_range_raise(hours: object) -> None:
    with pytest.raises(ValidationError):
        commands.sacct_finished(sacct.OPERATOR_SAMPLING, "exampleuser", hours)  # type: ignore[arg-type]


def test_sstat_refuses_a_profile_with_another_separator() -> None:
    from hpc_core.contract.fields import Field, FieldProfile

    semicolon = FieldProfile(
        name="semicolon", command="sstat", fields=(Field("step_id", "JobID"),), separator=";"
    )
    with pytest.raises(ValidationError):
        commands.sstat_usage(semicolon, "4812201")


def test_every_builder_runs_only_a_read_only_program() -> None:
    built = [
        commands.squeue_queue(squeue.OPERATOR_SAMPLING, "exampleuser"),
        commands.sacct_finished(sacct.OPERATOR_SAMPLING, "exampleuser", 1),
        commands.sacct_job(sacct.CONSOLE_MONITOR, "1"),
        commands.sinfo_capacity(sinfo.CAPACITY),
        commands.sstat_usage(sstat.DEFAULT, "1"),
    ]
    for argv in built:
        assert argv[:2] == ("env", "TZ=UTC")
        assert argv[2] in READ_ONLY_PROGRAMS
    assert READ_ONLY_PROGRAMS == frozenset({"squeue", "sacct", "sinfo", "sstat"})
