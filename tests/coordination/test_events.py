"""Events: the vocabulary, the package logger, and the checker that keeps paths and bodies out."""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from hpc_core.coordination import events


def test_importing_the_package_prints_nothing() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import hpc_core.coordination"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_a_host_handler_receives_the_events(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=events.LOGGER_NAME)
    events.emit(events.NODE_BEAT, node_id="alice-console-a1", count=3)
    records = [r for r in caplog.records if getattr(r, "hpc_event", None) == events.NODE_BEAT]
    assert len(records) == 1
    assert records[0].name == events.LOGGER_NAME
    assert records[0].hpc_fields == {"node_id": "alice-console-a1", "count": 3}  # type: ignore[attr-defined]


def test_the_logger_has_a_null_handler_so_unattached_events_are_silent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger(events.LOGGER_NAME)
    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)
    events.emit(events.STORE_ERROR, during="beat", kind="io")
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_checker_accepts_ids_counts_flags_and_codes() -> None:
    checked = events.fields(
        node_id="alice-console-a1", count=3, duration=0.25, flag=True, kind="stale", missing=None
    )
    assert checked == {
        "node_id": "alice-console-a1",
        "count": 3,
        "duration": 0.25,
        "flag": True,
        "kind": "stale",
        "missing": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        "/srv/team/_cluster",  # a folder path
        "..",  # a parent reference
        "~/keys/id_ed25519",  # a home path
        "C:\\team\\x",  # a Windows path
        "https://example.invalid",  # a URL
        "token=abc",  # a key-like pair
        "please run this now",  # a message body is free text
        "x" * (events.MAX_TEXT_LENGTH + 1),  # over the length cap
    ],
)
def test_the_checker_refuses_paths_free_text_and_long_values(value: str) -> None:
    with pytest.raises(events.UnsafeField):
        events.fields(field=value)


def test_the_checker_refuses_structured_values() -> None:
    with pytest.raises(events.UnsafeField):
        events.fields(body={"text": "hello"})


def test_emitting_an_unknown_event_name_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown coordination event"):
        events.emit("made.up")


def test_the_vocabulary_is_the_nineteen_events_of_design_d15_and_the_shared_data_change() -> None:
    assert len(events.EVENTS) == 19
    assert {
        "node.registered",
        "node.beat",
        "node.beat_failed",
        "node.conflict",
        "node.left",
        "node.pruned",
        "lease.acquired",
        "lease.denied",
        "lease.reclaimed",
        "lease.lost",
        "lease.repaired",
        "message.sent",
        "message.refused",
        "message.acked",
        "record.unreadable",
        "store.error",
        "shared.published",
        "shared.read_failed",
        "shared.collector_changed",
    } == set(events.EVENTS)
