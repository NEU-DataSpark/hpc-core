# Parsing scheduler output

The contract layer turns the text of four read-only Slurm commands into records. Each parser takes
the command's output and a **field profile**, and returns a `ParseResult` with the good `records`
and a `skipped` count.

| Command | Parser | Profiles | Record type |
| --- | --- | --- | --- |
| `squeue` | `contract.squeue.parse_squeue` | `OPERATOR_SAMPLING` | `JobRecord` |
| `sacct` | `contract.sacct.parse_sacct` | `OPERATOR_SAMPLING`, `CONSOLE_MONITOR` | `JobRecord` |
| `sinfo` | `contract.sinfo.parse_sinfo` | `CAPACITY` | `NodeRecord` |
| `sstat` | `contract.sstat.parse_sstat` | `DEFAULT` | `SstatRecord` |

## Profiles

A profile names the columns a command was asked for, in the order it asked for them. The parser
reads cells by name, so a field the profile does not name stays unset on the record.

- `squeue.OPERATOR_SAMPLING`: job id, partition, state, submit time, start time, requested CPUs,
  GRES, reason and job name.
- `sacct.OPERATOR_SAMPLING`: job id, partition, state, submit, start and end times, allocated CPUs,
  allocated TRES, total CPU, maximum RSS and job name.
- `sacct.CONSOLE_MONITOR`: job id, partition, state, submit, start and end times, requested CPUs,
  requested TRES, time limit and job name.
- `sinfo.CAPACITY`: partition, GRES, state and node count.
- `sstat.DEFAULT`: step id, average CPU, task count and maximum RSS.

A profile is checked when it is built. A free-text field (the job name) must be the last field, so
a separator inside a name cannot shift the other cells. Field names must be unique, and the
separator must be one plain character that is not `,` or `%`.

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
```

The fixtures are synthetic. Their provenance and the way to record new ones are in
[`recording-fixtures.md`](recording-fixtures.md).
