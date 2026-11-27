# Recording fixtures

Fixtures are anonymised scheduler outputs and golden run-reports that ship inside the package
(`src/hpc_core/testing/fixtures/`). A fixture is only ever a scrubbed copy of a recording, and the
raw recording never enters the repository.

## Steps

1. **Record with read-only commands and `TZ=UTC`.** Run on the login node, in your own session:

   ```bash
   TZ=UTC squeue --noheader --user=<account> -o '%i|%P|%T|%V|%S|%C|%b|%r|%j' > raw-squeue.txt
   TZ=UTC sacct -n -P -j <job-id> -o JobID,Partition,State,Submit,Start,End,AllocCPUS,AllocTRES,TotalCPU,MaxRSS,JobName > raw-sacct.txt
   TZ=UTC sinfo -h -o '%P|%G|%t|%D' > raw-sinfo.txt
   TZ=UTC sstat -a -n -P -j <job-id> -o JobID,AveCPU,NTasks,MaxRSS > raw-sstat.txt
   ```

   Only `squeue`, `sacct`, `sinfo` and `sstat` are run. `TZ=UTC` is required: without it Slurm
   prints local times and the recorded times are wrong by the zone offset.

2. **Scrub.** Pass every real value the recording holds as a run-time argument. The tool replaces
   the account with `exampleuser`, each partition and name with the placeholder you give, each job
   id with a sequential id (its `_<index>` array suffix is kept), and shifts every time by one
   constant so the earliest time lands on the base date (default `2026-01-05`):

   ```bash
   python tools/scrub_fixture.py \
     --account <account> \
     --partition <real-partition>=short \
     --partition <real-gpu-partition>=gpu \
     --job-id <base-job-id> \
     --replace <real-job-name>=sample-job \
     < raw-squeue.txt > scrubbed-squeue.txt
   ```

   Give the base job id (digits), not an array task id. Run the tool once per file, with the same
   arguments. Unknown values are not detected: the tool only replaces what it is told, so list
   every name, partition and id that appears in the recording. If a placeholder would still
   contain a real value, the tool refuses, writes nothing and exits with status 2.

3. **Run the hygiene scan.** It must pass before the file is added:

   ```bash
   python tools/hygiene_scan.py scrubbed-squeue.txt
   ```

4. **Store the fixture with a header comment.** The first lines of a scheduler fixture start with
   `#` and hold the recording month and the Slurm version the site runs. The loader strips this
   header before the parser sees the output:

   ```text
   # recorded: 2026-01 (month only; no site or account information)
   # slurm: 24.11
   # command: squeue -o '%i|%P|%T|%V|%S|%C|%b|%r|%j'
   4812201|short|COMPLETED|2026-01-05T00:00:00|...
   ```

   Put the file under `src/hpc_core/testing/fixtures/scheduler/` with an expected-result JSON beside
   it, named the same with `.expected.json`.

5. **Never commit the raw recording.** Raw files stay outside the repository, and a fixture diff
   is reviewed before it is merged.

## Synthetic recordings

A recording that cannot be taken from a cluster may be written by hand to the same format. Such a
fixture must say so in its header (`# synthetic: not recorded from a cluster`) and must still
pass the scrub and the hygiene scan. It stands in for a recording and does not claim to show what
a particular Slurm version prints.

## Refreshing

Refresh a fixture when a site upgrade changes a format, and record the new Slurm version in the
header. A changed column set changes the parser profile and needs a new test expectation, not only
a new file.
