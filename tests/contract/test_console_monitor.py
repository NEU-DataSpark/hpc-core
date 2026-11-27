"""The console's Task Monitor squeue profile: fourteen fields on the unit separator, the id opt-in,
and the record fields it fills. Rows are built with the console's own format."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from hpc_core.contract.fields import UNIT_SEPARATOR, JobRecord
from hpc_core.contract.squeue import CONSOLE_MONITOR, parse_squeue
from hpc_core.testing.fixtures import load_case, to_json_value

SEP = UNIT_SEPARATOR


def row(
    *,
    job_id: str = "100",
    name: str = "train",
    partition: str = "cpu",
    state: str = "RUNNING",
    submit: str = "2026-10-23T10:00:00",
    start: str = "2026-10-23T10:05:00",
    end: str = "2026-10-23T14:05:00",
    cpus: str = "4",
    nodes: str = "1",
    gres: str = "(null)",
    limit: str = "4:00:00",
    reason: str = "None",
    dependency: str = "(null)",
    command: str = "/home/exampleuser/run.sh",
) -> str:
    cells = [
        job_id,
        name,
        partition,
        state,
        submit,
        start,
        end,
        cpus,
        nodes,
        gres,
        limit,
        reason,
        dependency,
        command,
    ]
    return SEP.join(cells) + "\n"


def test_full_row_fills_every_console_field() -> None:
    result = parse_squeue(row(), CONSOLE_MONITOR)

    assert result.skipped == 0
    [record] = result.records
    assert record.job_id == "100"
    assert record.job_name == "train"
    assert record.partition == "cpu"
    assert record.state == "RUNNING"
    assert record.submit_time == datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    assert record.start_time == datetime(2026, 10, 23, 10, 5, tzinfo=UTC)
    assert record.end_time == datetime(2026, 10, 23, 14, 5, tzinfo=UTC)
    assert record.cpus_requested == 4
    assert record.node_count == 1
    assert record.time_limit_seconds == 14400.0
    assert record.reason == "None"
    assert record.dependency_text is None
    assert record.command == "/home/exampleuser/run.sh"


def test_gpu_gres_is_read_per_node_and_node_count_is_kept() -> None:
    [record] = parse_squeue(row(gres="gpu:a30:2", nodes="2"), CONSOLE_MONITOR).records

    assert record.gpus_requested == 2
    assert record.gpu_type == "a30"
    assert record.node_count == 2


def test_name_containing_a_pipe_does_not_shift_other_fields() -> None:
    [record] = parse_squeue(row(name="a|b | c", command="echo a | wc -l"), CONSOLE_MONITOR).records

    assert record.job_name == "a|b | c"
    assert record.cpus_requested == 4
    assert record.node_count == 1
    assert record.command == "echo a | wc -l"


def test_na_end_time_and_unlimited_time_limit_stay_unset_not_zero() -> None:
    text = row(state="PENDING", start="N/A", end="N/A", limit="UNLIMITED", reason="Resources")

    [record] = parse_squeue(text, CONSOLE_MONITOR).records

    assert record.end_time is None
    assert record.start_time is None
    assert record.time_limit_seconds is None
    assert record.reason == "Resources"


def test_pending_row_keeps_its_dependency_text() -> None:
    text = row(state="PENDING", dependency="afterok:100(unfulfilled),afterany:101(unfulfilled)")

    [record] = parse_squeue(text, CONSOLE_MONITOR).records

    assert record.dependency_text == "afterok:100(unfulfilled),afterany:101(unfulfilled)"


@pytest.mark.parametrize("placeholder", ["(null)", "N/A", ""])
def test_placeholder_dependency_and_command_are_unset(placeholder: str) -> None:
    [record] = parse_squeue(
        row(dependency=placeholder, command=placeholder), CONSOLE_MONITOR
    ).records

    assert record.dependency_text is None
    assert record.command is None


def test_short_row_is_skipped_and_counted_and_the_rest_are_kept() -> None:
    short = SEP.join(["101", "short", "cpu", "RUNNING"]) + "\n"
    text = row(job_id="100") + short + row(job_id="102")

    result = parse_squeue(text, CONSOLE_MONITOR)

    assert [record.job_id for record in result.records] == ["100", "102"]
    assert result.skipped == 1


def test_command_with_vertical_tab_or_line_separator_stays_one_row() -> None:
    command = "echo a\x0bb c\x0cd | wc"
    text = row(job_id="100", command=command) + row(job_id="101")

    result = parse_squeue(text, CONSOLE_MONITOR)

    assert result.skipped == 0
    assert [record.job_id for record in result.records] == ["100", "101"]
    assert result.records[0].command == command


@pytest.mark.parametrize("job_id", ["300_[1-10]", "300_[1-10%2]", "300+1"])
def test_pending_array_range_or_het_id_is_read_only_with_the_opt_in(job_id: str) -> None:
    text = row(job_id=job_id, state="PENDING", start="N/A", end="N/A")

    opted_in = parse_squeue(text, CONSOLE_MONITOR)
    assert [record.job_id for record in opted_in.records] == [job_id]
    assert opted_in.skipped == 0

    without_opt_in = replace(CONSOLE_MONITOR, extended_job_ids=False)
    refused = parse_squeue(text, without_opt_in)
    assert refused.records == ()
    assert refused.skipped == 1


@pytest.mark.parametrize("job_id", ["300_[1-", "abc"])
def test_malformed_id_is_skipped_and_counted_even_with_the_opt_in(job_id: str) -> None:
    result = parse_squeue(row(job_id=job_id), CONSOLE_MONITOR)

    assert result.records == ()
    assert result.skipped == 1


def test_recorded_console_fixture_has_each_required_shape() -> None:
    case = load_case("scheduler", "squeue-console")
    records = parse_squeue(case.text, CONSOLE_MONITOR).records

    by_id = {record.job_id: record for record in records}
    assert "100002_[1-10]" in by_id, "pending array range"
    assert by_id["100002_[1-10]"].state == "PENDING"
    assert by_id["100002_[1-10]"].end_time is None
    assert by_id["100002_[1-10]"].time_limit_seconds is None
    assert by_id["100001"].dependency_text is None
    assert by_id["100002_[1-10]"].dependency_text == "afterok:100001(unfulfilled)"
    assert by_id["100002_[1-10]"].job_name == "sample|sweep"
    assert by_id["100002_[1-10]"].command == "python sweep.py --name a|b"


def test_serializer_leaves_a_new_field_out_only_when_unset() -> None:
    unset = to_json_value(JobRecord(job_id="1"))
    assert isinstance(unset, dict)
    assert "end_time" in unset and unset["end_time"] is None
    assert not {"node_count", "dependency_text", "command"} & set(unset)

    set_ = to_json_value(JobRecord(job_id="1", node_count=2, command="run"))
    assert isinstance(set_, dict)
    assert set_["node_count"] == 2
    assert set_["command"] == "run"
    assert "dependency_text" not in set_
