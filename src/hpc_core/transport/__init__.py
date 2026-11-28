"""Transport layer: the contract a consumer's login-node transport must meet, and the JSON wire
contract that carries one command to an executor. No implementation here.
"""

from .protocol import (
    CommandResult,
    CommandTransport,
    InputTooLarge,
    TransportError,
    TransportTimeout,
)
from .wire import (
    COMMANDS_PATH,
    PROTOCOL_VERSION,
    STATUS_BY_KIND,
    CommandRequest,
    ErrorBody,
    ErrorKind,
    WireFormatError,
    decode_error,
    decode_request,
    decode_result,
    encode_error,
    encode_request,
    encode_result,
    raise_for_error,
)

__all__ = [
    "COMMANDS_PATH",
    "PROTOCOL_VERSION",
    "STATUS_BY_KIND",
    "CommandRequest",
    "CommandResult",
    "CommandTransport",
    "ErrorBody",
    "ErrorKind",
    "InputTooLarge",
    "TransportError",
    "TransportTimeout",
    "WireFormatError",
    "decode_error",
    "decode_request",
    "decode_result",
    "encode_error",
    "encode_request",
    "encode_result",
    "raise_for_error",
]
