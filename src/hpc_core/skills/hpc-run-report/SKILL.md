---
name: hpc-run-report
description: Check a run-report CSV with the hpc-core command line, print the metrics of each row, and print the supported schema. Use when an agent must confirm that a run report is readable, read its skipped rows and unavailable metrics, or compute CPU and GPU hours from it.
license: Apache-2.0
metadata:
  version: "0.4.0"
---

# Run report checks

Use the report commands of the hpc-core command line to check a run-report CSV and read its metrics.
It is offline: it reads a file or standard input and prints JSON. It does not write or change a
report.

## Steps

1. Check that the report is readable:

   ```bash
   hpc-core report validate run-report.csv
   ```

2. Read the metrics of each row:

   ```bash
   hpc-core report metrics run-report.csv
   ```

3. Confirm the columns and the supported schema versions:

   ```bash
   hpc-core report schema
   ```

Use `-` in place of the file name to read standard input, for example `hpc-core report validate -`.

## Reading the validate output

`validate` prints `schema_versions` (the versions in the rows it read), `supported_versions`, `rows`
(the rows it could read) and `skipped`.

- Exit 0: every row was read.
- Exit 1 with a skipped count: the report was read, but some rows could not be read, and the rows
  are not printed. Report the count and say those rows are missing from the metrics. Do not fill
  them in.
- Exit 1 with a message that names an unsupported `schema_version`: this package does not read that
  version. Do not parse the file by hand. Say which version the report holds and that a release of
  `hpc-core` that supports it is needed.
- Exit 2: the file could not be read, or the command was wrong.

## Reading the metrics output

`metrics` prints `records`, one per readable row, and `skipped`. Each record holds `job_id`,
`stage`, `sample_time`, `source`, `report_status`, `unavailable`, `wait_seconds`,
`elapsed_seconds`, `cpu_hours`, `gpu_hours`, `cpu_seconds_used` and `mem_peak_mb`.

- `null` means the value is not measured or not available. Never read `null` as zero.
- `unavailable` names the metric the writer could not measure for that row. Use it to explain a
  `null` in the metrics.
- `cpu_hours` and `gpu_hours` are computed from the allocation and the elapsed seconds. They are
  `null` when either input is missing.
- A `0` is a real measured zero, and it stays `0`.

## Rules

- The command line only reads. Do not edit a report to make it pass, and do not create a report
  with this skill.
- Use `hpc-core report schema` for the list of columns. Do not rely on a remembered list.
- Exit status: 0 for success, 1 when the input was read but is not acceptable, 2 for a usage error.
