# Run-report contract

A run report is a CSV file. Each row is one sample of a job, taken at one stage of the run. The
writer produces it and the readers consume it, so both sides follow this document. Its column list
is checked against `hpc_core.contract.report.COLUMNS` by `tests/test_docs_examples.py`.

## Columns

The file has one header line with these 22 columns, in this order. The current `schema_version` is
1.

```text
schema_version
job_id
job_name
partition
stage
sample_time
scheduler_state
submit_time
start_time
end_time
wait_seconds
elapsed_seconds
cpus_alloc
cpu_seconds_used
mem_peak_mb
gpus_alloc
gpu_type
gpu_util_pct
gpu_mem_mb
source
unavailable
report_status
```

## Values

- **Whole numbers** are written without a decimal point, for example `3270`. Other numbers keep
  their value, for example `93784.5`.
- **Times** are UTC and end in `Z`, for example `2031-07-02T09:00:00Z`. A naive or fractional time
  is refused by the writer.
- **Unset** is an empty cell. **A real zero** is `0`. The two are never mixed up.
- **Closed sets:**
  - `stage`: `pre`, `running`, `post`.
  - `report_status`: `in_progress`, `complete`, `samples_only`.
  - `source`: parts from `squeue`, `sstat`, `nvidia-smi`, `sacct`, `samples`, joined with `+`.

## Reading

A reader refuses the whole file when:

- the file is empty or has a duplicate header;
- a required column is missing: `schema_version`, `job_id`, `stage` or `sample_time`;
- `schema_version` is not supported. The error names the number, for example `99`.

A reader skips and counts a row that does not parse, such as a non-numeric `cpus_alloc`, and
carries on with the others.

## Versioning

A change to the columns or their meaning bumps `schema_version`. See
[`versioning.md`](versioning.md) for when that is allowed.

## Metrics

The metric functions are in `hpc_core.contract.metrics`. Every input may be unset, and an unset
input gives an unset result, never zero.

| Quantity | Formula |
| --- | --- |
| Wait | start − submit. A job cancelled before it started counts to its end. A job still pending counts to the sample time. A negative result is unset. |
| Elapsed | end − start, or the sample time − start while the job runs. Unset before a start. |
| CPU-hours | CPUs × elapsed ÷ 3600 |
| GPU-hours | GPUs × elapsed ÷ 3600. A job with zero GPUs gives zero GPU-hours. |
| CPU seconds used, finished | the accounting `TotalCPU` |
| CPU seconds used, running | sum over steps of average CPU time × task count. Unset if there is no step, or if any step lacks either value, because a partial sum would understate the usage. |
| Peak | the largest reading across the samples. Gaps are ignored. No reading gives an unset value. |
| Mean | the average of the readings, gaps ignored. No reading gives an unset value. |

A peak is taken over the samples in the report. It is never copied from a value the scheduler
reports on its own.

## Examples

```python
from hpc_core.contract.metrics import cpu_hours, gpu_hours, peak, wait_seconds
from datetime import datetime, timezone

submit = datetime(2031, 7, 2, 9, 0, tzinfo=timezone.utc)
start = datetime(2031, 7, 2, 9, 5, 30, tzinfo=timezone.utc)
assert wait_seconds(submit, start) == 330

assert gpu_hours(1, 7200) == 2.0
assert gpu_hours(0, 7200) == 0.0
assert gpu_hours(1, None) is None

assert peak([512.0, None, 2048.0]) == 2048.0
assert peak([None, None]) is None
```
