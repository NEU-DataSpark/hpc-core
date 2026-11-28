"""The wire contract: requests and results survive a round trip, a malformed request is refused,
every error kind raises the transport exception the protocol names, and an oversized input is
refused before any text is written."""

from __future__ import annotations

import json

import pytest

from hpc_core.transport import (
    COMMANDS_PATH,
    PROTOCOL_VERSION,
    STATUS_BY_KIND,
    CommandRequest,
    CommandResult,
    ErrorBody,
    ErrorKind,
    InputTooLarge,
    TransportError,
    TransportTimeout,
    WireFormatError,
    decode_error,
    decode_request,
    decode_result,
    encode_error,
    encode_request,
    encode_result,
    raise_for_error,
)
from hpc_core.transport.protocol import MAX_INPUT_BYTES

ARGV = ("env", "TZ=UTC", "squeue", "--noheader")


def test_request_survives_a_round_trip() -> None:
    request = CommandRequest(argv=ARGV, timeout=30, max_output_bytes=1024, input="a\nb\n")
    assert decode_request(encode_request(request)) == request


def test_request_without_input_survives_a_round_trip() -> None:
    request = CommandRequest(argv=ARGV, timeout=2.5, max_output_bytes=10)
    text = encode_request(request)
    assert '"input":null' in text
    assert decode_request(text) == request


def test_request_keeps_argument_order_and_holds_no_shell_string() -> None:
    request = decode_request(encode_request(CommandRequest(ARGV, 5, 10)))
    assert request.argv == ARGV
    assert isinstance(request.argv, tuple)


def test_encoding_is_canonical() -> None:
    text = encode_request(CommandRequest(ARGV, 5, 10))
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


def test_result_survives_a_round_trip() -> None:
    result = CommandResult(stdout="1|alice\n", stderr="warning\n", exit_status=3, truncated=True)
    assert decode_result(encode_result(result)) == result


@pytest.mark.parametrize("argv", [(), []])
def test_empty_argument_list_is_refused(argv: tuple[str, ...]) -> None:
    with pytest.raises(WireFormatError):
        CommandRequest(argv=argv, timeout=5, max_output_bytes=10)


@pytest.mark.parametrize("argv", [("squeue", 3), ("squeue", None), ("squeue", b"--noheader")])
def test_non_string_argument_is_refused(argv: tuple[object, ...]) -> None:
    with pytest.raises(WireFormatError):
        CommandRequest(argv=argv, timeout=5, max_output_bytes=10)  # type: ignore[arg-type]


def test_a_request_text_with_a_string_argv_is_refused() -> None:
    text = '{"argv":"squeue --noheader","input":null,"max_output_bytes":10,"timeout":5.0}'
    with pytest.raises(WireFormatError):
        decode_request(text)


def test_a_request_text_with_an_extra_field_is_refused() -> None:
    text = '{"argv":["squeue"],"extra":1,"input":null,"max_output_bytes":10,"timeout":5.0}'
    with pytest.raises(WireFormatError):
        decode_request(text)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "5"])
def test_a_bad_timeout_is_refused(timeout: object) -> None:
    with pytest.raises(WireFormatError):
        CommandRequest(argv=ARGV, timeout=timeout, max_output_bytes=10)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, -5, 1.5, True])
def test_a_bad_output_limit_is_refused(limit: object) -> None:
    with pytest.raises(WireFormatError):
        CommandRequest(argv=ARGV, timeout=5, max_output_bytes=limit)  # type: ignore[arg-type]


def test_non_json_text_is_refused() -> None:
    with pytest.raises(WireFormatError):
        decode_request("{argv:")


def test_a_result_with_a_wrong_type_is_refused() -> None:
    text = '{"exit_status":"0","stderr":"","stdout":"","truncated":false}'
    with pytest.raises(WireFormatError):
        decode_result(text)


def test_a_result_with_a_missing_field_is_refused() -> None:
    with pytest.raises(WireFormatError):
        decode_result('{"exit_status":0,"stderr":"","stdout":""}')


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("timeout", TransportTimeout),
        ("input_too_large", InputTooLarge),
        ("busy", TransportError),
        ("unauthorized", TransportError),
        ("invalid", TransportError),
        ("connection", TransportError),
        ("something_new", TransportError),
    ],
)
def test_each_error_kind_raises_the_matching_exception(
    kind: str, expected: type[Exception]
) -> None:
    body = ErrorBody(kind=kind, message="short message")
    with pytest.raises(expected) as raised:
        raise_for_error(body)
    assert type(raised.value) is expected
    assert str(raised.value) == "short message"


def test_raise_for_error_accepts_the_body_text() -> None:
    text = encode_error(ErrorBody(kind="timeout", message="too slow"))
    with pytest.raises(TransportTimeout, match="too slow"):
        raise_for_error(text)


def test_error_body_survives_a_round_trip() -> None:
    body = ErrorBody(kind="busy", message="the executor is at its command limit")
    assert decode_error(encode_error(body)) == body


def test_error_body_with_a_missing_kind_is_refused() -> None:
    with pytest.raises(WireFormatError):
        decode_error('{"message":"no kind"}')


def test_every_error_kind_has_a_status() -> None:
    assert set(STATUS_BY_KIND) == set(ErrorKind)
    assert STATUS_BY_KIND[ErrorKind.TIMEOUT] == 504
    assert STATUS_BY_KIND[ErrorKind.INPUT_TOO_LARGE] == 413
    assert STATUS_BY_KIND[ErrorKind.BUSY] == 503
    assert STATUS_BY_KIND[ErrorKind.UNAUTHORIZED] == 401
    assert STATUS_BY_KIND[ErrorKind.INVALID] == 422
    assert STATUS_BY_KIND[ErrorKind.CONNECTION] == 502


def test_the_path_carries_the_protocol_version() -> None:
    assert PROTOCOL_VERSION == 1
    assert COMMANDS_PATH == "/v1/commands"


def test_input_of_exactly_the_limit_is_accepted() -> None:
    payload = "x" * MAX_INPUT_BYTES
    request = CommandRequest(argv=("dd",), timeout=5, max_output_bytes=10, input=payload)
    assert decode_request(encode_request(request)) == request


def test_oversized_input_is_refused_before_any_text_is_returned() -> None:
    oversized = "x" * (MAX_INPUT_BYTES + 1)
    returned: list[str] = []
    with pytest.raises(InputTooLarge):
        request = CommandRequest(
            argv=("dd",), timeout=5, max_output_bytes=10, input=oversized
        )
        returned.append(encode_request(request))
    assert returned == []


def test_oversized_input_is_counted_in_bytes_not_characters() -> None:
    # 40 000 characters of two bytes each is 80 000 bytes, over the limit.
    oversized = "é" * 40_000
    with pytest.raises(InputTooLarge):
        CommandRequest(argv=("dd",), timeout=5, max_output_bytes=10, input=oversized)


def test_decoding_an_oversized_input_is_refused_on_receipt() -> None:
    text = json.dumps(
        {
            "argv": ["dd"],
            "input": "x" * (70 * 1024),
            "max_output_bytes": 10,
            "timeout": 5.0,
        }
    )
    with pytest.raises(InputTooLarge):
        decode_request(text)
