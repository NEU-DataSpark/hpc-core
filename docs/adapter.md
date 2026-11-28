# Scheduler adapter

`hpc_core.slurm.SlurmAdapter` runs the four read-only Slurm commands through a transport and
returns parsed records. The transport is the consumer's own: it runs an argument tuple on the login
node. The adapter never builds a shell string.

## The account comes from the consumer

The adapter takes the account name as a constructor argument. A consumer reads it from its own
settings and passes it in. The package never has a default account and never stores one.

```python
from types import SimpleNamespace

from hpc_core.slurm import SlurmAdapter
from hpc_core.testing import FakeTransport

settings = SimpleNamespace(slurm_account="exampleuser")  # the consumer's own settings object
transport = FakeTransport({})  # the consumer's real transport in production
adapter = SlurmAdapter(transport, account=settings.slurm_account)
```

The account must be a plain name: letters, digits, `_`, `.` and `-`, not starting with `-`. Any
other value raises `ValidationError` when the adapter is built.

## Reads

| Method | Command run | Parsed with |
| --- | --- | --- |
| `queue(profile)` | `env TZ=UTC squeue --noheader --user=<account> -o <format>` | `parse_squeue` |
| `finished_jobs(hours, profile)` | `env TZ=UTC sacct -n -P -X --user=<account> --starttime=now-<hours>hours --format=... --delimiter=\|` | `parse_sacct` |
| `job_history(job_id, profile)` | `env TZ=UTC sacct -n -P -X --jobs=<job_id> --format=... --delimiter=\|` | `parse_sacct` |
| `running_usage(job_id, profile)` | `env TZ=UTC sstat -n -P -a --jobs=<job_id> --format=...` | `parse_sstat` |
| `capacity(profile)` | `env TZ=UTC sinfo --noheader -o <format>` | `parse_sinfo` |

The `<format>` option is generated from the profile, so the command asks for exactly the fields the
parser reads. A job id must be digits, optionally with an `_<index>` suffix. `hours` must be a whole
number from 1 to 24 × 366. Anything else raises `ValidationError` before a command is built, so no
command runs.

`finished_jobs` passes `-X`, which asks for job allocations only and leaves out steps. The
operator's current query does not pass `-X`. Confirm the difference on a cluster before a consumer
switches to this adapter.

Only `squeue`, `sacct`, `sinfo` and `sstat` can be run, through the `READ_ONLY_PROGRAMS` set.

## Errors

Every error is a `SlurmError` with the program name in `program`. Its message names the command and
never includes the raw standard error, because that can hold host names or paths.

| Error | Raised when |
| --- | --- |
| `SlurmTimeout` | the transport timed out |
| `SlurmTransportError` | the transport could not reach the login node |
| `SlurmCommandFailed` | the command exited with a non-zero status. `exit_status` holds the number. |
| `SlurmOutputTruncated` | the output reached the byte limit. No records are returned, because the output is incomplete. |

An empty result is not an error. A queue with no jobs gives a `ParseResult` with no records.

## Example

This runs against `FakeTransport`, which replays a recorded output without touching a cluster:

```python
from hpc_core.slurm import SlurmAdapter, SlurmCommandFailed
from hpc_core.testing import FakeTransport, load_case
from hpc_core.transport import CommandResult

recorded = load_case("scheduler", "squeue-operator").text
transport = FakeTransport({"squeue": CommandResult(stdout=recorded, stderr="", exit_status=0)})
adapter = SlurmAdapter(transport, account="exampleuser")

queue = adapter.queue()
assert len(queue.records) == 4
assert queue.skipped == 1
assert "--user=exampleuser" in transport.calls[0]

failing = FakeTransport(
    {"sacct": CommandResult(stdout="", stderr="login01 refused the request", exit_status=1)}
)
try:
    SlurmAdapter(failing, account="exampleuser").finished_jobs(24)
except SlurmCommandFailed as error:
    assert error.exit_status == 1
    assert "refused" not in str(error)
else:
    raise AssertionError("a non-zero exit must raise")
```

## Transport contract

A transport implements `CommandTransport.run(argv, *, timeout, max_output_bytes)` and returns a
`CommandResult`. It must run the tuple as given, with no shell, and must report a timeout as
`TransportTimeout` and an unreachable node as `TransportError`. The package checks this interface
with a `mypy --strict` test that rejects a class taking a shell string.

## Wire contract

A transport that sends a command to a separate executor must send and read the same JSON as every
other client and the executor. `hpc_core.transport` defines that contract once, as pure code with no
I/O. The shapes are below; each object is written with sorted keys and no spaces, so one value has
one text.

**Request**, `POST` to the path `COMMANDS_PATH` (`/v1/commands`, the protocol version is
`PROTOCOL_VERSION`, 1). `argv` is a non-empty list of strings, never a shell string. `timeout` is a
positive number of seconds. `max_output_bytes` is a positive whole number. `input` is a string of at
most 64 KiB, or `null`.

```json
{"argv":["env","TZ=UTC","squeue","--noheader"],"input":null,"max_output_bytes":65536,"timeout":30.0}
```

**Result**, for a command that finished, whatever its exit status. `truncated` is `true` when the
output reached `max_output_bytes`.

```json
{"exit_status":0,"stderr":"","stdout":"1|alice\n","truncated":false}
```

**Error**, for a failure with no result. `kind` names one error kind, and `message` is short and holds
no key path, token, command input or raw standard error.

```json
{"kind":"timeout","message":"the command did not finish in time"}
```

| Error kind | HTTP status | `raise_for_error` raises |
| --- | --- | --- |
| `timeout` | 504 | `TransportTimeout` |
| `input_too_large` | 413 | `InputTooLarge` |
| `busy` | 503 | `TransportError` |
| `unauthorized` | 401 | `TransportError` |
| `invalid` | 422 | `TransportError` |
| `connection` | 502 | `TransportError` |

A kind the package does not know raises `TransportError`, so a newer executor does not break an older
client. An unknown or missing field, a value of the wrong type, an empty argument list or a non-string
argument is refused with `WireFormatError` and nothing runs. A standard-input text over 64 KiB is
refused with `InputTooLarge`, both when a request is built and when one is read, so the limit holds on
both sides.

The functions are `encode_request`, `decode_request`, `encode_result`, `decode_result`,
`encode_error`, `decode_error` and `raise_for_error`. The example below builds a request, reads it
back, and raises the exception for a timeout:

```python
from hpc_core.transport import (
    CommandRequest,
    ErrorBody,
    TransportTimeout,
    decode_request,
    encode_error,
    encode_request,
    raise_for_error,
)

request = CommandRequest(
    argv=("env", "TZ=UTC", "squeue", "--noheader"), timeout=30, max_output_bytes=65536
)
assert decode_request(encode_request(request)) == request

try:
    raise_for_error(encode_error(ErrorBody(kind="timeout", message="the command timed out")))
except TransportTimeout:
    pass
else:
    raise AssertionError("a timeout must raise TransportTimeout")
```

A client or an executor that reads and writes these shapes proves it with the golden examples in
`hpc_core.testing`: `check_wire_conformance(codec)` returns the list of disagreements for a
`WireCodec`, and an empty list means the codec conforms. `REFERENCE_WIRE_CODEC` is the package's own
codec.
