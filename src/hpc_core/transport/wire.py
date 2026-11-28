"""The wire contract between a command client and the executor that runs the command.

It defines the request, result and error shapes, the error kinds, the HTTP status of each kind and
the exception a client raises for each kind. It is data only: no I/O, no network, standard library
and ``hpc_core.transport.protocol`` only. Every client and the executor use this one definition.

Each object is encoded as JSON with sorted keys and no extra whitespace, so one value has one
encoding. A reader refuses an object with a missing or an extra key, or a value of the wrong type.
The golden examples in ``hpc_core.testing.wire_examples`` check that a reader and a writer agree.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, NoReturn

from .protocol import (
    CommandResult,
    InputTooLarge,
    TransportError,
    TransportTimeout,
    check_input,
)

# The version in the path of every command request. An executor refuses a version it does not serve.
PROTOCOL_VERSION: Final = 1
COMMANDS_PATH: Final = f"/v{PROTOCOL_VERSION}/commands"


class WireFormatError(ValueError):
    """A request, result or error is not in the wire shape, or breaks a rule of it. Nothing runs."""


class ErrorKind(StrEnum):
    """The one kind an error object names. Every kind is listed here and in ``STATUS_BY_KIND``."""

    TIMEOUT = "timeout"
    INPUT_TOO_LARGE = "input_too_large"
    BUSY = "busy"
    UNAUTHORIZED = "unauthorized"
    INVALID = "invalid"
    CONNECTION = "connection"


# The HTTP status an executor answers with for each kind.
STATUS_BY_KIND: Final[Mapping[ErrorKind, int]] = MappingProxyType(
    {
        ErrorKind.TIMEOUT: 504,
        ErrorKind.INPUT_TOO_LARGE: 413,
        ErrorKind.BUSY: 503,
        ErrorKind.UNAUTHORIZED: 401,
        ErrorKind.INVALID: 422,
        ErrorKind.CONNECTION: 502,
    }
)

_REQUEST_KEYS: Final = frozenset({"argv", "input", "max_output_bytes", "timeout"})
_RESULT_KEYS: Final = frozenset({"exit_status", "stderr", "stdout", "truncated"})
_ERROR_KEYS: Final = frozenset({"kind", "message"})


def _argv(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise WireFormatError("argv must be a non-empty list of strings")
    if not all(isinstance(item, str) for item in value):
        raise WireFormatError("every argument must be a string")
    return tuple(value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class CommandRequest:
    """One fixed command: an argument tuple, a timeout in seconds, an output limit and an optional
    standard-input text. It holds no shell string.

    Construction checks every field. The standard input is checked with ``check_input``, so an
    oversized input raises ``InputTooLarge`` and no request object exists for it.
    """

    argv: tuple[str, ...]
    timeout: float
    max_output_bytes: int
    input: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", _argv(self.argv))
        timeout = self.timeout
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise WireFormatError("timeout must be a number of seconds")
        if not math.isfinite(timeout) or timeout <= 0:
            raise WireFormatError("timeout must be a positive, finite number of seconds")
        object.__setattr__(self, "timeout", float(timeout))
        if not _is_int(self.max_output_bytes) or self.max_output_bytes < 1:
            raise WireFormatError("max_output_bytes must be a positive whole number")
        if self.input is not None and not isinstance(self.input, str):
            raise WireFormatError("input must be a string or null")
        check_input(self.input)


@dataclass(frozen=True)
class ErrorBody:
    """A failure with no result: one error kind and a short message. The message names no key
    path, token, command input or raw standard error."""

    kind: str
    message: str


def _reject_constant(name: str) -> NoReturn:
    raise WireFormatError(f"{name} is not valid JSON")


def _object(text: str, keys: frozenset[str]) -> dict[str, Any]:
    try:
        data: Any = json.loads(text, parse_constant=_reject_constant)
    except ValueError as error:
        raise WireFormatError("the body is not valid JSON") from error
    if not isinstance(data, dict):
        raise WireFormatError("the body is not a JSON object")
    if set(data) != keys:
        raise WireFormatError("the object has a missing or an unexpected field")
    return data


def _dump(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def encode_request(request: CommandRequest) -> str:
    """The request as its one canonical JSON text."""
    return _dump(
        {
            "argv": list(request.argv),
            "input": request.input,
            "max_output_bytes": request.max_output_bytes,
            "timeout": request.timeout,
        }
    )


def decode_request(text: str) -> CommandRequest:
    """Read a request. Raises ``WireFormatError`` for a shape or type error and ``InputTooLarge``
    for a standard-input text over the limit."""
    data = _object(text, _REQUEST_KEYS)
    return CommandRequest(
        argv=data["argv"],
        timeout=data["timeout"],
        max_output_bytes=data["max_output_bytes"],
        input=data["input"],
    )


def encode_result(result: CommandResult) -> str:
    """The result as its one canonical JSON text."""
    return _dump(
        {
            "exit_status": result.exit_status,
            "stderr": result.stderr,
            "stdout": result.stdout,
            "truncated": result.truncated,
        }
    )


def decode_result(text: str) -> CommandResult:
    """Read a result. Raises ``WireFormatError`` when a field is missing or has the wrong type."""
    data = _object(text, _RESULT_KEYS)
    stdout, stderr = data["stdout"], data["stderr"]
    exit_status, truncated = data["exit_status"], data["truncated"]
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise WireFormatError("stdout and stderr must be strings")
    if not _is_int(exit_status):
        raise WireFormatError("exit_status must be a whole number")
    if not isinstance(truncated, bool):
        raise WireFormatError("truncated must be true or false")
    return CommandResult(
        stdout=stdout, stderr=stderr, exit_status=exit_status, truncated=truncated
    )


def encode_error(body: ErrorBody) -> str:
    """The error object as its one canonical JSON text."""
    return _dump({"kind": body.kind, "message": body.message})


def decode_error(text: str) -> ErrorBody:
    """Read an error object. Raises ``WireFormatError`` when a field is missing or not a string.
    An unknown kind is read as is; ``raise_for_error`` maps it to the transport error."""
    data = _object(text, _ERROR_KEYS)
    kind, message = data["kind"], data["message"]
    if not isinstance(kind, str) or not kind:
        raise WireFormatError("kind must be a non-empty string")
    if not isinstance(message, str):
        raise WireFormatError("message must be a string")
    return ErrorBody(kind=kind, message=message)


def raise_for_error(body: ErrorBody | str) -> NoReturn:
    """Raise the transport exception for an error object, given as an ``ErrorBody`` or its text.

    A timeout raises ``TransportTimeout``, an oversized input raises ``InputTooLarge`` and every
    other kind, known or not, raises ``TransportError``.
    """
    error = decode_error(body) if isinstance(body, str) else body
    if error.kind == ErrorKind.TIMEOUT:
        raise TransportTimeout(error.message)
    if error.kind == ErrorKind.INPUT_TOO_LARGE:
        raise InputTooLarge(error.message)
    raise TransportError(error.message)
