"""Job states: one definition covering the operator's and the console's lists."""

from __future__ import annotations

import pytest

from hpc_core.contract.states import FINAL, QUEUED, RUNNING, classify_state, state_word

# The operator's lists, from its run_report.py (PRE, RUNNING and FINAL states).
OPERATOR_PRE = {"PENDING", "CONFIGURING"}
OPERATOR_RUNNING = {"RUNNING", "COMPLETING", "SUSPENDED"}
OPERATOR_FINAL = {
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "PREEMPTED",
    "REVOKED",
    "SPECIAL_EXIT",
}
# The console's lists, from its scheduler_tasks.py.
CONSOLE_QUEUED = {"PENDING", "REQUEUED", "REQUEUE_HOLD", "REQUEUE_FED", "RESV_DEL_HOLD"}
CONSOLE_RUNNING = {"RUNNING", "COMPLETING", "SUSPENDED", "CONFIGURING"}
CONSOLE_FINAL = {
    "COMPLETED",
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "CANCELLED",
    "PREEMPTED",
}


def test_every_state_in_either_consumer_list_is_classified() -> None:
    union = (
        OPERATOR_PRE
        | OPERATOR_RUNNING
        | OPERATOR_FINAL
        | CONSOLE_QUEUED
        | CONSOLE_RUNNING
        | CONSOLE_FINAL
    )
    for state in union:
        assert classify_state(state) is not None, state


def test_consumer_final_sets_are_inside_the_package_final_set() -> None:
    assert OPERATOR_FINAL <= FINAL
    assert CONSOLE_FINAL <= FINAL


def test_consumer_queued_and_running_sets_are_inside_the_package_sets() -> None:
    assert CONSOLE_QUEUED <= QUEUED
    assert OPERATOR_RUNNING <= RUNNING
    assert CONSOLE_RUNNING <= RUNNING


def test_configuring_is_running_by_decision() -> None:
    # The operator counts CONFIGURING as pre; the package counts it as running. See states.py.
    assert classify_state("CONFIGURING") == "running"


def test_the_package_sets_do_not_overlap() -> None:
    assert not (QUEUED & RUNNING) and not (QUEUED & FINAL) and not (RUNNING & FINAL)


@pytest.mark.parametrize(
    ("text", "word", "state_class"),
    [
        ("CANCELLED by 1234", "CANCELLED", "final"),
        ("PENDING", "PENDING", "queued"),
        ("RUNNING", "RUNNING", "running"),
    ],
)
def test_first_word_rule(text: str, word: str, state_class: str) -> None:
    assert state_word(text) == word
    assert classify_state(text) == state_class


def test_unknown_state_is_kept_as_text_and_classified_as_none() -> None:
    assert state_word("WEIRD_STATE") == "WEIRD_STATE"
    assert classify_state("WEIRD_STATE") is None


def test_empty_state_has_no_class() -> None:
    assert state_word("   ") is None
    assert classify_state("") is None


def test_record_state_keeps_the_first_word_of_a_known_state() -> None:
    from hpc_core.contract.states import record_state

    assert record_state("CANCELLED by 1234") == ("CANCELLED", "final")


def test_record_state_keeps_the_full_text_of_an_unknown_state() -> None:
    from hpc_core.contract.states import record_state

    assert record_state("WEIRD by 99") == ("WEIRD by 99", None)
    assert record_state("   ") == (None, None)
