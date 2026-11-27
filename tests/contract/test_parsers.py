"""Parsers reproduce each recorded case's expected result; the spec's field rules hold on real

rows.
"""

from __future__ import annotations

import pytest

from hpc_core.contract.fields import FieldProfile
from hpc_core.contract.sacct import CONSOLE_MONITOR, parse_sacct
from hpc_core.contract.sacct import OPERATOR_SAMPLING as SACCT_OPERATOR
from hpc_core.contract.squeue import OPERATOR_SAMPLING as SQUEUE_OPERATOR
from hpc_core.contract.squeue import parse_squeue
from hpc_core.testing.fixtures import load_case, load_cases, run_scheduler_case


@pytest.mark.parametrize("case", load_cases("scheduler"), ids=lambda case: case.name)
def test_parser_reproduces_expected_result(case: object) -> None:
    from hpc_core.testing.fixtures import Case

    assert isinstance(case, Case)
    expected = {key: case.expected[key] for key in ("records", "skipped")}
    assert run_scheduler_case(case) == expected


def test_every_scheduler_command_has_a_populated_and_an_empty_case() -> None:
    names = {case.name for case in load_cases("scheduler")}
    for command in ("squeue", "sacct", "sinfo", "sstat"):
        assert any(name.startswith(f"{command}-") and name.endswith("empty") for name in names), (
            command
        )
        assert any(
            name.startswith(f"{command}-") and not name.endswith("empty") for name in names
        ), command


def test_every_scheduler_fixture_has_a_header_and_expected_json() -> None:
    for case in load_cases("scheduler"):
        assert case.header and case.header[0].startswith("# recorded:"), case.name
        assert "records" in case.expected and "skipped" in case.expected, case.name


def test_empty_output_gives_no_records_and_no_skips() -> None:
    result = parse_squeue("", SQUEUE_OPERATOR)
    assert result.records == () and result.skipped == 0
    assert parse_squeue("   \n\n", SQUEUE_OPERATOR).skipped == 0


def test_placeholder_start_time_is_unset_and_submit_time_is_read() -> None:
    record = parse_squeue(load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR).records[
        0
    ]
    assert record.start_time is None
    assert (
        record.submit_time is not None
        and record.submit_time.isoformat() == "2026-01-05T01:00:00+00:00"
    )


def test_malformed_row_is_skipped_and_counted_and_the_rest_are_kept() -> None:
    result = parse_squeue(load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR)
    assert len(result.records) == 4
    assert result.skipped == 1


def test_array_task_id_is_a_valid_job_id() -> None:
    record = parse_squeue(load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR).records[
        2
    ]
    assert record.job_id == "100003_3"


def test_job_name_with_the_separator_is_kept_whole() -> None:
    record = parse_squeue(load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR).records[
        3
    ]
    assert record.job_name == "sample|pipe|name"


def test_qualified_state_reads_as_its_first_word_and_is_final() -> None:
    record = parse_sacct(load_case("scheduler", "sacct-operator").text, SACCT_OPERATOR).records[1]
    assert record.state == "CANCELLED"
    assert record.state_class == "final"


def test_unknown_state_keeps_the_record_and_its_text() -> None:
    text = "9|short|WEIRD_STATE|2026-01-05T10:00:00|Unknown|1|N/A|None|odd\n"
    record = parse_squeue(text, SQUEUE_OPERATOR).records[0]
    assert record.state == "WEIRD_STATE"
    assert record.state_class is None


def test_real_zero_is_kept_and_missing_value_is_unset() -> None:
    records = parse_sacct(load_case("scheduler", "sacct-operator").text, SACCT_OPERATOR).records
    cancelled = records[1]
    failed = records[3]
    assert cancelled.cpus_allocated == 0
    assert cancelled.max_rss_mib == 0.0
    assert failed.max_rss_mib is None


def test_two_profiles_one_parser_fields_outside_a_profile_are_unset() -> None:
    operator = parse_sacct(load_case("scheduler", "sacct-operator").text, SACCT_OPERATOR).records[0]
    console = parse_sacct(load_case("scheduler", "sacct-console").text, CONSOLE_MONITOR).records[0]
    assert operator.total_cpu_seconds == 3723.5
    assert operator.time_limit_seconds is None
    assert console.time_limit_seconds == 86400.0
    assert console.total_cpu_seconds is None


def test_operator_profile_requests_no_command_text() -> None:
    assert isinstance(SQUEUE_OPERATOR, FieldProfile)
    assert not {"command", "command_text", "job_command"} & set(SQUEUE_OPERATOR.names)
    assert not {"command", "command_text", "job_command"} & set(SACCT_OPERATOR.names)
    # The record has a command field for the console profile, but the operator profile never
    # requests it, so every record it reads leaves it unset.
    records = parse_squeue(load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR).records
    assert records and all(record.command is None for record in records)


def test_console_fields_are_unset_for_operator_sampling() -> None:
    squeue_records = parse_squeue(
        load_case("scheduler", "squeue-operator").text, SQUEUE_OPERATOR
    ).records
    sacct_text = load_case("scheduler", "sacct-operator").text
    sacct_records = parse_sacct(sacct_text, SACCT_OPERATOR).records
    assert squeue_records and sacct_records

    for record in squeue_records:
        assert record.end_time is None
        assert record.node_count is None
        assert record.dependency_text is None
        assert record.command is None
    for record in sacct_records:
        assert record.node_count is None
        assert record.dependency_text is None
        assert record.command is None


def test_parsing_touches_no_file_process_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import socket
    import subprocess

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a parser touched the outside world")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    text = load_case("scheduler", "sacct-operator").text
    assert len(parse_sacct(text, SACCT_OPERATOR).records) == 4


def test_missing_allocated_cpus_is_unset_not_zero() -> None:
    row = (
        "1234|p|COMPLETED|2031-07-02T09:00:00|2031-07-02T09:05:00|2031-07-02T10:00:00"
        "||billing=1|00:00:00||job\n"
    )
    result = parse_sacct(row, SACCT_OPERATOR)
    assert result.skipped == 0
    assert result.records[0].cpus_allocated is None


def test_unknown_multi_word_state_keeps_its_text_in_both_parsers() -> None:
    sacct_row = "1234|p|WEIRD by 99|2031-07-02T09:00:00|Unknown|Unknown|1|billing=1|00:00:00||job\n"
    squeue_row = "1234|p|WEIRD by 99|2031-07-02T09:00:00|Unknown|1|N/A|None|job\n"
    assert parse_sacct(sacct_row, SACCT_OPERATOR).records[0].state == "WEIRD by 99"
    assert parse_squeue(squeue_row, SQUEUE_OPERATOR).records[0].state == "WEIRD by 99"
