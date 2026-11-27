# Command line

The `hpc-core` command, also run as `python -m hpc_core`, gives people, scripts and AI agents a
way to use the package without writing Python. It reads recorded Slurm output or a run-report CSV
from a file or standard input, and prints JSON. It also prints the fixed read-only Slurm command
for a query, and installs the skills that ship with the package.

The command line is offline. It never opens a connection, never starts another program and never
runs Slurm. It holds no host, account or key. The caller runs the printed command on its own
login-node transport, then passes the output back in.

## Flow

```text
hpc-core commands queue --account example-account   -> argument list, as JSON
run that argument list on your own login-node transport
hpc-core parse squeue --profile operator-sampling -  -> records and skipped count, as JSON
```

## Install

Install the package with `uv` or `pip`. The `hpc-core` command is then on your `PATH`:

```text
uv tool install "hpc-core==X.Y.Z"
python -m pip install "hpc-core==X.Y.Z"
```

## Commands

### parse

Parses recorded scheduler output into JSON records. `FILE` is a file of command output; `-` or no
argument reads standard input.

```bash
hpc-core parse squeue --profile operator-sampling squeue.txt
```

The output is one JSON object: `records` (one entry per readable row) and `skipped` (the number of
rows that could not be read).

| Command | Profiles (default first) |
| --- | --- |
| `parse squeue` | `operator-sampling`, `console-monitor` |
| `parse sacct` | `operator-sampling`, `console-monitor` |
| `parse sinfo` | `capacity` |
| `parse sstat` | `running-usage` |

Use the same `--profile` as the `commands` call that produced the text. A different profile has
different columns.

### report

Checks and measures a run-report CSV. The schema is in `docs/run-report-contract.md`.

```bash
hpc-core report validate run-report.csv
hpc-core report metrics run-report.csv
hpc-core report schema
```

- `validate` prints `schema_versions`, `supported_versions`, `rows` and `skipped`.
- `metrics` prints one record per readable row: its stored values (`wait_seconds`,
  `elapsed_seconds`, `cpu_seconds_used`, `mem_peak_mb`, `unavailable` and the rest), plus
  `cpu_hours` and `gpu_hours`, which are computed from the allocation and the elapsed seconds.
- `schema` prints the schema version this package reads, and the columns.

### commands

Prints the argument list for one fixed read-only Slurm query, as a JSON array of strings. It
starts with `env TZ=UTC`. Nothing is run.

```bash
hpc-core commands queue --account example-account
hpc-core commands finished --account example-account --hours 24
hpc-core commands job 4812201
hpc-core commands usage 4812201
hpc-core commands capacity
```

| Command | Reads | Options |
| --- | --- | --- |
| `commands queue` | `squeue`, the jobs of one account | `--account` (required), `--profile` |
| `commands finished` | `sacct`, the allocations that started recently | `--account` (required), `--hours` (required), `--profile` |
| `commands job` | `sacct`, one job allocation | `JOB_ID`, `--profile` |
| `commands usage` | `sstat`, the running steps of one job | `JOB_ID`, `--profile` |
| `commands capacity` | `sinfo`, partition capacity | `--profile` |

There is no default account. `--account` must be given, and it may hold only letters, digits, `_`,
`.` and `-`, and must not start with `-`. A job id is digits with an optional `_<index>` suffix.
`--hours` is a whole number from 1 to 8784.

### skills

Lists and installs the skills shipped with the package. See [`skills.md`](skills.md).

```bash
hpc-core skills list
```

## Exit status

| Status | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | The input was read but is not acceptable: an unsupported `schema_version`, a report with skipped rows, or a skill folder that already exists. |
| 2 | A usage or argument error: a bad option, an invalid account or job id, an unknown profile or skill, or an input file that cannot be read. |

`parse` exits 0 when rows are skipped; its `skipped` count is the record of that. `report` exits 1
when rows are skipped, because a report with unreadable rows is not fully acceptable.

## Output rules

- Standard output holds only the JSON document. Messages for people go to standard error.
- A row that cannot be read is counted in `skipped`. Its text is never printed, because raw
  scheduler output can name hosts and paths.
- Times are ISO 8601 in UTC with a `Z` suffix, for example `2026-01-05T01:00:00Z`.
- A value that was not reported is `null`. It is never replaced by `0`. A real zero stays `0`.
- Fields added in 0.2.0 (`node_count`, `dependency_text`, `command`) are left out of a record when
  they are unset, so the output matches the golden files written before they existed.

## Stability

The commands, sub-commands and options are public API. The surface is pinned in
`tests/snapshots/cli_surface.txt`. Removing or renaming one is a major release; adding one is a
minor release. See [`versioning.md`](versioning.md).
