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
