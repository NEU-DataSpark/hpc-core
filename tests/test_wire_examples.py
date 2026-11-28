"""The golden wire examples: the reference codec conforms, and deliberately wrong codecs fail."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, NoReturn

from hpc_core.testing import REFERENCE_WIRE_CODEC, WireCodec, check_wire_conformance
from hpc_core.transport import CommandRequest, CommandResult, TransportError, wire


def test_the_reference_codec_passes_the_conformance_check() -> None:
    assert check_wire_conformance(REFERENCE_WIRE_CODEC) == []


def _truncation_dropped(text: str) -> CommandResult:
    return dataclasses.replace(wire.decode_result(text), truncated=False)


def _timeout_as_transport_error(body: str) -> NoReturn:
    error = wire.decode_error(body)
    if error.kind == "timeout":
        raise TransportError(error.message)
    wire.raise_for_error(error)


def _loose_request_text(request: CommandRequest) -> str:
    # The same values with spaces after the separators: not the canonical bytes.
    return wire.encode_request(request).replace(",", ", ").replace(":", ": ")


def _accepts_an_empty_argv(text: str) -> CommandRequest:
    data = json.loads(text)
    return CommandRequest(
        argv=tuple(data["argv"]) or ("",),
        timeout=data["timeout"],
        max_output_bytes=data["max_output_bytes"],
        input=data["input"],
    )


def _wrong(**override: Any) -> WireCodec:
    return dataclasses.replace(REFERENCE_WIRE_CODEC, **override)


def test_a_reader_that_drops_the_truncated_flag_fails() -> None:
    problems = check_wire_conformance(_wrong(decode_result=_truncation_dropped))
    assert any(problem.startswith("truncated_output:") for problem in problems)


def test_a_reader_that_maps_a_timeout_to_a_transport_error_fails() -> None:
    problems = check_wire_conformance(_wrong(raise_for_error=_timeout_as_transport_error))
    assert problems == ["timeout: raised TransportError, expected TransportTimeout"]


def test_a_writer_that_is_not_canonical_fails() -> None:
    problems = check_wire_conformance(_wrong(encode_request=_loose_request_text))
    assert problems and all("not written as the golden text" in problem for problem in problems)


def test_a_reader_that_accepts_an_empty_argument_list_fails() -> None:
    problems = check_wire_conformance(_wrong(decode_request=_accepts_an_empty_argv))
    assert "empty_argv: a request that must be refused was accepted" in problems


def test_a_wrong_reader_names_each_disagreement() -> None:
    wrong = _wrong(decode_result=_truncation_dropped, raise_for_error=_timeout_as_transport_error)
    problems = check_wire_conformance(wrong)
    assert len(problems) == 2
    assert {problem.split(":", 1)[0] for problem in problems} == {"truncated_output", "timeout"}
