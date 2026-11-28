---
name: hpc-scheduler-output
description: Build read-only Slurm queue, accounting, partition capacity and job step queries with the hpc-core command line, run them on your own login-node connection, and turn their text into JSON records. Use when an agent needs squeue, sacct, sinfo or sstat results from a cluster without writing its own Slurm parsing.
license: Apache-2.0
metadata:
  version: "0.6.0"
---

# HPC scheduler output

Use the `hpc-core` command line to read a Slurm cluster through a fixed set of read-only queries.
`hpc-core` never opens a connection and never runs Slurm. It prints the argument list to run, and
it turns the text you get back into JSON.

## When to use

- You need the queued jobs of one account, its recent finished jobs, the accounting record of one
  job, the running usage of one job, or the partition capacity.
- You want parsed records and a skipped count, not raw scheduler text.

## The flow

1. Print the argument list, for example for the queue of one account:

   ```bash
   hpc-core commands queue --account example-account
   ```

   The output is a JSON array of strings: the exact command to run, starting with `env TZ=UTC`.
2. Run that list on your own login-node connection. Pass each element as one argument and quote
   each one for the remote shell. `hpc-core` does not do this step.
3. Parse the text you received with the same profile you asked for. Use `-` to read standard input,
   or a file name:

   ```bash
   hpc-core parse squeue --profile operator-sampling -
   ```

4. Read `records` and `skipped` from the JSON document.

## Commands and their parsers

- Queued jobs of an account: `hpc-core commands queue --account example-account`, parsed with
  `hpc-core parse squeue`.
- Finished job allocations: `hpc-core commands finished --account example-account --hours 24`,
  parsed with `hpc-core parse sacct`.
- Accounting record of one job: `hpc-core commands job 4812201`, parsed with `hpc-core parse sacct`.
- Running usage of one job: `hpc-core commands usage 4812201`, parsed with `hpc-core parse sstat`.
- Partition capacity: `hpc-core commands capacity`, parsed with `hpc-core parse sinfo`.

Profiles: `squeue` and `sacct` accept `operator-sampling` (the default) and `console-monitor`;
`sinfo` accepts `capacity`; `sstat` accepts `running-usage`. Pass the same `--profile` to `commands`
and to `parse`. A different profile gives different columns, and the rows will not line up.

## Rules

- Read-only only. The reads are `squeue`, `sacct`, `sinfo` and `sstat`. This skill cannot submit,
  cancel, hold, release or change a job, and it must not be used to build any other Slurm command.
  If the user asks for one of those, say that this skill does not do it.
- Use only the account the user gives you. `commands queue` and `commands finished` have no default
  account, and you must not invent one.
- `null` means the value was not reported. Never read it as zero. A real zero stays `0`.
- `skipped` counts the rows that could not be read. The rows are not printed on purpose, because
  raw output can name hosts and paths. Report the count; do not guess what the rows held.
- The `sacct` read uses `-X`, which lists job allocations and leaves out job steps. If a count looks
  off, check how the cluster's Slurm version treats steps before you trust it.
- Exit status: 0 for success, 2 for a bad argument such as an invalid account or job id.
