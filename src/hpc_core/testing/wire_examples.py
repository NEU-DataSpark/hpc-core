"""Golden wire examples and the conformance check that a client or an executor runs against them.

A codec is one reader and writer for each wire shape. ``check_wire_conformance`` passes only when
the codec writes every golden object as the exact golden text, reads every golden text back to the
same object, refuses every refused text, and raises the matching transport exception for every
error text. The reference codec is the one in ``hpc_core.transport.wire``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from ..transport import wire
from ..transport.protocol import (
    MAX_INPUT_BYTES,
    CommandResult,
    InputTooLarge,
    TransportError,
    TransportTimeout,
)
from ..transport.wire import CommandRequest, ErrorBody, WireFormatError


@dataclass(frozen=True)
class WireCodec:
    """One reader and writer for each wire shape. ``raise_for_error`` takes the error text."""

    encode_request: Callable[[CommandRequest], str]
    decode_request: Callable[[str], CommandRequest]
    encode_result: Callable[[CommandResult], str]
    decode_result: Callable[[str], CommandResult]
    encode_error: Callable[[ErrorBody], str]
    decode_error: Callable[[str], ErrorBody]
    raise_for_error: Callable[[str], NoReturn]


REFERENCE_WIRE_CODEC = WireCodec(
    encode_request=wire.encode_request,
    decode_request=wire.decode_request,
    encode_result=wire.encode_result,
    decode_result=wire.decode_result,
    encode_error=wire.encode_error,
    decode_error=wire.decode_error,
    raise_for_error=wire.raise_for_error,
)

# name, object, canonical text
REQUEST_EXAMPLES: tuple[tuple[str, CommandRequest, str], ...] = (
    (
        "squeue_with_env",
        CommandRequest(
            argv=("env", "TZ=UTC", "squeue", "--noheader"), timeout=30, max_output_bytes=1048576
        ),
        '{"argv":["env","TZ=UTC","squeue","--noheader"],"input":null,'
        '"max_output_bytes":1048576,"timeout":30.0}',
    ),
    (
        "with_standard_input",
        CommandRequest(
            argv=("dd", "of=target", "status=none"),
            timeout=5.5,
            max_output_bytes=4096,
            input="hello\n",
        ),
        '{"argv":["dd","of=target","status=none"],"input":"hello\\n",'
        '"max_output_bytes":4096,"timeout":5.5}',
    ),
)

# name, object, canonical text
RESULT_EXAMPLES: tuple[tuple[str, CommandResult, str], ...] = (
    (
        "success",
        CommandResult(stdout="1|alice\n", stderr="", exit_status=0),
        '{"exit_status":0,"stderr":"","stdout":"1|alice\\n","truncated":false}',
    ),
    (
        "non_zero_exit",
        CommandResult(stdout="", stderr="no such account", exit_status=1),
        '{"exit_status":1,"stderr":"no such account","stdout":"","truncated":false}',
    ),
    (
        "truncated_output",
        CommandResult(stdout="abc", stderr="", exit_status=0, truncated=True),
        '{"exit_status":0,"stderr":"","stdout":"abc","truncated":true}',
    ),
)

# name, object, canonical text, the exception the text raises through raise_for_error
ERROR_EXAMPLES: tuple[tuple[str, ErrorBody, str, type[Exception]], ...] = (
    (
        "timeout",
        ErrorBody(kind="timeout", message="the command did not finish in time"),
        '{"kind":"timeout","message":"the command did not finish in time"}',
        TransportTimeout,
    ),
    (
        "input_too_large",
        ErrorBody(kind="input_too_large", message="standard input is over the limit"),
        '{"kind":"input_too_large","message":"standard input is over the limit"}',
        InputTooLarge,
    ),
    (
        "busy",
        ErrorBody(kind="busy", message="the executor is at its command limit"),
        '{"kind":"busy","message":"the executor is at its command limit"}',
        TransportError,
    ),
    (
        "unauthorized",
        ErrorBody(kind="unauthorized", message="the token was refused"),
        '{"kind":"unauthorized","message":"the token was refused"}',
        TransportError,
    ),
    (
        "invalid",
        ErrorBody(kind="invalid", message="the request is not valid"),
        '{"kind":"invalid","message":"the request is not valid"}',
        TransportError,
    ),
    (
        "connection",
        ErrorBody(kind="connection", message="the login node could not be reached"),
        '{"kind":"connection","message":"the login node could not be reached"}',
        TransportError,
    ),
)


def _oversized_input_text() -> str:
    payload = "x" * (MAX_INPUT_BYTES + 1)
    return json.dumps(
        {"argv": ["dd"], "input": payload, "max_output_bytes": 10, "timeout": 5.0},
        sort_keys=True,
        separators=(",", ":"),
    )


# name, text that must be refused, the exception it must raise
REFUSED_REQUEST_EXAMPLES: tuple[tuple[str, str, type[Exception]], ...] = (
    (
        "empty_argv",
        '{"argv":[],"input":null,"max_output_bytes":10,"timeout":5.0}',
        WireFormatError,
    ),
    (
        "non_string_argument",
        '{"argv":["squeue",3],"input":null,"max_output_bytes":10,"timeout":5.0}',
        WireFormatError,
    ),
    (
        "shell_string_instead_of_list",
        '{"argv":"squeue --noheader","input":null,"max_output_bytes":10,"timeout":5.0}',
        WireFormatError,
    ),
    (
        "missing_input_field",
        '{"argv":["squeue"],"max_output_bytes":10,"timeout":5.0}',
        WireFormatError,
    ),
    (
        "oversized_input_on_receipt",
        _oversized_input_text(),
        InputTooLarge,
    ),
)


def _problem_for_exception(name: str, action: str, error: BaseException) -> str:
    return f"{name}: {action} raised {type(error).__name__}"


def check_wire_conformance(codec: WireCodec) -> list[str]:
    """Run ``codec`` against every golden example. Returns one message per disagreement, naming the
    example; an empty list means the codec conforms."""
    problems: list[str] = []

    for name, request, text in REQUEST_EXAMPLES:
        try:
            decoded_request = codec.decode_request(text)
        except Exception as error:
            problems.append(_problem_for_exception(name, "reading a request", error))
        else:
            if decoded_request != request:
                problems.append(f"{name}: a request read back differently")
        try:
            written_request = codec.encode_request(request)
        except Exception as error:
            problems.append(_problem_for_exception(name, "writing a request", error))
        else:
            if written_request != text:
                problems.append(f"{name}: a request is not written as the golden text")

    for name, result, text in RESULT_EXAMPLES:
        try:
            decoded_result = codec.decode_result(text)
        except Exception as error:
            problems.append(_problem_for_exception(name, "reading a result", error))
        else:
            if decoded_result != result:
                problems.append(f"{name}: a result read back differently")
        try:
            written_result = codec.encode_result(result)
        except Exception as error:
            problems.append(_problem_for_exception(name, "writing a result", error))
        else:
            if written_result != text:
                problems.append(f"{name}: a result is not written as the golden text")

    for name, body, text, expected in ERROR_EXAMPLES:
        try:
            decoded_body = codec.decode_error(text)
        except Exception as error:
            problems.append(_problem_for_exception(name, "reading an error", error))
        else:
            if decoded_body != body:
                problems.append(f"{name}: an error read back differently")
        try:
            written_body = codec.encode_error(body)
        except Exception as error:
            problems.append(_problem_for_exception(name, "writing an error", error))
        else:
            if written_body != text:
                problems.append(f"{name}: an error is not written as the golden text")
        try:
            codec.raise_for_error(text)
        except Exception as error:
            if type(error) is not expected:
                problems.append(
                    f"{name}: raised {type(error).__name__}, expected {expected.__name__}"
                )
        else:
            problems.append(f"{name}: did not raise")

    for name, text, expected_refusal in REFUSED_REQUEST_EXAMPLES:
        try:
            codec.decode_request(text)
        except Exception as error:
            if type(error) is not expected_refusal:
                problems.append(
                    f"{name}: refused with {type(error).__name__}, "
                    f"expected {expected_refusal.__name__}"
                )
        else:
            problems.append(f"{name}: a request that must be refused was accepted")

    return problems
