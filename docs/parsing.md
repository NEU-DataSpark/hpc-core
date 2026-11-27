# Parsing scheduler output

The contract layer turns the text of four read-only Slurm commands into records. Each parser takes
the command's output and a **field profile**, and returns a `ParseResult` with the good `records`
and a `skipped` count.

| Command | Parser | Profiles | Record type |
| --- | --- | --- | --- |
| `squeue` | `contract.squeue.parse_squeue` | `OPERATOR_SAMPLING`, `CONSOLE_MONITOR` | `JobRecord` |
| `sacct` | `contract.sacct.parse_sacct` | `OPERATOR_SAMPLING`, `CONSOLE_MONITOR` | `JobRecord` |
| `sinfo` | `contract.sinfo.parse_sinfo` | `CAPACITY` | `NodeRecord` |
| `sstat` | `contract.sstat.parse_sstat` | `DEFAULT` | `SstatRecord` |

## Profiles

A profile names the columns a command was asked for, in the order it asked for them. The parser
reads cells by name, so a field the profile does not name stays unset on the record.

- `squeue.OPERATOR_SAMPLING`: job id, partition, state, submit time, start time, requested CPUs,
  GRES, reason and job name.
- `squeue.CONSOLE_MONITOR` (added in 0.2.0): the fourteen fields of the console's Task Monitor, in
  this order: job id, job name, partition, state, submit, start and end times, requested CPUs,
  node count, GRES, time limit, reason, unfulfilled dependencies and command. It is split on the
  ASCII unit separator (`\x1f`), not `|`, and the command is the free-text field. It opts in to
  the extended job id rule (see below).
- `sacct.OPERATOR_SAMPLING`: job id, partition, state, submit, start and end times, allocated CPUs,
  allocated TRES, total CPU, maximum RSS and job name.
- `sacct.CONSOLE_MONITOR`: job id, partition, state, submit, start and end times, requested CPUs,
  requested TRES, time limit and job name.
- `sinfo.CAPACITY`: partition, GRES, state and node count.
- `sstat.DEFAULT`: step id, average CPU, task count and maximum RSS.

A profile is checked when it is built. A free-text field must be the last field, so a separator
inside it cannot shift the other cells. Field names must be unique. The separator must be one
character: a space, tab or line break is refused, and so are `,` and `%`. The ASCII unit separator
(`\x1f`) is allowed, because Slurm prints no such character in a field.

A profile with the unit separator is split into rows on `\n` only. Its free-text command may hold
any character, such as `\x0b` or `\u2028`, which `splitlines` would treat as a line break. Every
other profile is split as before.

## Rules the parsers follow

- **Malformed rows are skipped and counted.** A row with too few cells, or with extra cells before
  a free-text field, is not a record. The rest of the output is still read.
- **Blank lines are not rows.** Empty output gives no records and a skipped count of zero.
- **Unset is not zero.** A missing or placeholder value (`Unknown`, `None`, `N/A`, `INVALID`, or an
  empty cell) reads as `None`. A real `0` stays `0`.
- **Durations, memory and times** are converted to seconds, MiB and timezone-aware UTC values.
  `1-02:03:04.5` is 93784.5 seconds, and `2048K` is 2 MiB.
- **States** are read by their first word, so `CANCELLED by 1234` is `CANCELLED`. A state the
  package does not know keeps its text and has no state class.
- **Job ids** are validated. `123` and an array task `123_4` are valid; anything else is skipped.
  A profile may opt in to the extended rule, which also accepts a pending array range such as
  `300_[1-10]` or `300_[1-10%2]` and a heterogeneous component such as `300+1`. Slurm prints
  these for pending array and heterogeneous jobs. `300_[1-` and `abc` are rejected under both rules.

## Record fields

`JobRecord` has four fields that a profile may leave unset. Each one stays `None` unless a profile
names it and the cell is readable.

- `end_time`: read from `sacct` profiles and from `squeue.CONSOLE_MONITOR`. A pending job's `N/A`
  reads as `None`.
- `node_count`: the node count (`squeue %D`). Only `CONSOLE_MONITOR` reads it.
- `dependency_text`: the unfulfilled dependency string as Slurm prints it (`squeue %E`), such as
  `afterok:100(unfulfilled),afterany:101(unfulfilled)`. The string is kept unparsed; a consumer
  that needs its entries parses it.
- `command`: the command text (`squeue %o`). Only `CONSOLE_MONITOR` reads it, and the operator
  profiles never do, so a run report holds no command.

`gpus_requested` in `CONSOLE_MONITOR` is the GRES count per node. The job total is that count
times `node_count`. `time_limit_seconds` reads `UNLIMITED` and other placeholders as `None`.

## Example

This runs unchanged against the recorded fixtures shipped in the package:

```python
from hpc_core.contract import sacct, squeue
from hpc_core.testing import load_case

queue = squeue.parse_squeue(
    load_case("scheduler", "squeue-operator").text, squeue.OPERATOR_SAMPLING
)
assert len(queue.records) == 4
assert queue.skipped == 1

history = sacct.parse_sacct(load_case("scheduler", "sacct-console").text, sacct.CONSOLE_MONITOR)
assert history.records[0].time_limit_seconds == 86400.0

monitor = squeue.parse_squeue(load_case("scheduler", "squeue-console").text, squeue.CONSOLE_MONITOR)
pending = monitor.records[1]
assert pending.job_id == "100002_[1-10]"
assert pending.job_name == "sample|sweep"
assert pending.dependency_text == "afterok:100001(unfulfilled)"
assert pending.end_time is None and pending.time_limit_seconds is None
assert pending.command == "python sweep.py --name a|b"
```

The fixtures are synthetic. Their provenance and the way to record new ones are in
[`recording-fixtures.md`](recording-fixtures.md).
