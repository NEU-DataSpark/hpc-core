"""Input and JSON output: standard input, a file, a missing file, and the value conversion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import FeedStdin, RunCli

from hpc_core.cli import _io
from hpc_core.cli._io import InputError, read_text, to_json_value
from hpc_core.contract.fields import JobRecord, NodeRecord


def test_standard_input_is_read_for_dash(feed_stdin: FeedStdin) -> None:
    feed_stdin("100|short\n")
    assert read_text("-") == "100|short\n"


def test_standard_input_is_read_when_no_source_is_given(feed_stdin: FeedStdin) -> None:
    feed_stdin("job\n")
    assert read_text(None) == "job\n"


def test_a_file_is_read_as_text(tmp_path: Path) -> None:
    source = tmp_path / "output.txt"
    source.write_text("100|short\n", encoding="utf-8")
    assert read_text(str(source)) == "100|short\n"


def test_a_missing_file_is_an_input_error_that_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent.txt"
    with pytest.raises(InputError) as info:
        read_text(str(missing))
    assert str(missing) in str(info.value)


def test_a_missing_file_exits_2_and_names_the_path(run_cli: RunCli, tmp_path: Path) -> None:
    missing = tmp_path / "absent.txt"
    code, out, err = run_cli("parse", "squeue", str(missing))
    assert code == 2
    assert out == ""
    assert str(missing) in err


def test_a_file_that_is_not_utf8_is_refused_without_its_bytes(
    run_cli: RunCli, tmp_path: Path
) -> None:
    source = tmp_path / "binary.txt"
    source.write_bytes(b"\xff\xfe secret-bytes")
    code, out, err = run_cli("parse", "squeue", str(source))
    assert code == 2
    assert out == ""
    assert "secret-bytes" not in err


def test_none_stays_null() -> None:
    value = to_json_value(JobRecord(job_id="100001", state=None, start_time=None))
    assert isinstance(value, dict)
    assert value["state"] is None
    assert value["start_time"] is None


def test_a_zero_stays_zero() -> None:
    value = to_json_value(JobRecord(job_id="100001", total_cpu_seconds=0.0))
    assert isinstance(value, dict)
    assert value["total_cpu_seconds"] == 0.0


def test_datetime_becomes_iso_8601_utc_text() -> None:
    record = JobRecord(job_id="100001", submit_time=datetime(2026, 1, 5, 1, tzinfo=UTC))
    value = to_json_value(record)
    assert isinstance(value, dict)
    assert value["submit_time"] == "2026-01-05T01:00:00Z"


def test_the_0_2_0_fields_are_left_out_only_when_unset() -> None:
    unset = to_json_value(JobRecord(job_id="100001"))
    assert isinstance(unset, dict)
    assert not {"node_count", "dependency_text", "command"} & set(unset)

    set_node = to_json_value(JobRecord(job_id="100001", node_count=2))
    assert isinstance(set_node, dict)
    assert set_node["node_count"] == 2


def test_another_dataclass_converts_field_by_field() -> None:
    value = to_json_value(NodeRecord(partition="short", node_count=3))
    assert value == {
        "partition": "short",
        "gres": None,
        "state": None,
        "node_count": 3,
        "gpus_per_node": None,
        "gpu_type": None,
    }


def test_print_json_writes_one_document(capsys: pytest.CaptureFixture[str]) -> None:
    _io.print_json({"records": [], "skipped": 0})
    out = capsys.readouterr().out
    assert json.loads(out) == {"records": [], "skipped": 0}
    assert out.endswith("\n")
