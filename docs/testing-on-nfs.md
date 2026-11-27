# Testing on NFS

The protocol in [`cluster-coordination.md`](cluster-coordination.md) runs on a shared folder, and
a network filesystem behaves differently from a local disk: file times are cached, listings lag,
and renames take effect at different times on different clients. The opt-in NFS layer tests the
protocol against a real NFS export on the same machine, so those behaviours are exercised and not
only simulated.

The default test run does not need any of this. The NFS tests carry the `nfs` marker, and
`pyproject.toml` deselects that marker by default, so `uv run pytest` does not run them.

## Prerequisites

- **Root on the host.** Mounting an NFS export needs root. The testbed does not use `sudo`, and it
  does not load kernel modules.
- **NFS in the kernel.** The host kernel needs the NFS client (`nfs` in `/proc/filesystems`) and
  the NFS server (`nfsd`). On many systems they are modules that must be loaded as root first.
- **Docker with Compose.** The NFS server runs in a container from `erichough/nfs-server`, which
  runs privileged. Its port is bound to the loopback address only.
- **uv.** The tests run with `uv run pytest -m nfs tests/nfs`.

`run.sh up` checks these before it starts anything. When one is missing it names the missing
piece, starts no container and mounts nothing:

```text
nfs-testbed: this kernel has no NFS client ('nfs' is not in /proc/filesystems); load it as root
nfs-testbed: nothing was started or mounted
```

## One command per layer

The local layer below needs root and an NFS client on the host. It was not run on the development
host, which has neither. The cluster run further down is the layer that has been run.

Run these from `repos/hpc-core`:

```bash
tools/nfs-testbed/run.sh up     # start the server and mount the export twice
tools/nfs-testbed/run.sh test   # run pytest -m nfs against the two mounts
tools/nfs-testbed/run.sh down   # unmount, stop the server and remove its container
```

`up` mounts the export twice on this machine:

- **Mount A** uses no client caching (`noac`). A write through A is seen at once.
- **Mount B** keeps attributes for 60 seconds (`actimeo=60`). A write through A can take up to a
  minute to show through B. That is the case the protocol must survive.

`test` passes the two mount paths to the tests as `NFS_TESTBED_A` and `NFS_TESTBED_B`. The tests
cover these behaviours:

| Test | What it shows |
| --- | --- |
| a beat through A shows through B as online | file times and listings survive a cached client |
| exclusive create through A and B has one winner | hard-link creates are exclusive across mounts |
| lease races through A and B end at or below the limit | repair works when both mounts race |
| a renamed record is never read half done through B | renames are atomic for a reader on another mount |
| hard-link create works through A | the self-check's link probe succeeds |
| the self-check through B reports the listing delay | the probe measures how late B sees new files |

`down` leaves nothing behind: it unmounts B and then A, runs `docker compose down` with its volumes,
and removes the two mount folders. It is safe to run when the testbed is not up.

## Cluster run

The cross-client checks in `tests/nfs/test_cross_client.py` run on a real shared folder of an HPC
cluster. Each role is its own job on its own compute node, so the protocol is tested between
separate NFS clients, not between two mounts of one machine.

Roles, all in one run folder (`NFS_CROSS_ROOT`) on the shared export:

- **writer** (`NFS_CROSS_ROLE=writer`, one compute node) registers, runs the race rounds, and
  rewrites its record until the reader confirms its reads.
- **reader** (`NFS_CROSS_ROLE=reader`, a second compute node) waits for the writer and the login
  client, checks that discovery shows both online within 90 seconds, runs the race rounds, reads the
  rewritten record, and runs the self-check.
- **login** is a third client that registers and beats from the cluster's login node. It is a
  separate script outside this repository, and this module does not run it.

The roles order their steps with flag files under `team/flags` and report with files under
`team/results`. No role compares clocks across hosts. `NFS_CROSS_WAIT` caps each wait (default 1200
seconds; the cluster run used 7200). Use a new run folder for each run, and remove it afterwards.

The single-client file in `test_protocol_over_nfs.py` can also run on the cluster export. Set
`NFS_TESTBED_SHARED_EXPORT=1` with `NFS_TESTBED_A` and `NFS_TESTBED_B` pointing at folders on that
export. The shared-export flag skips the mount-point check, because the job does not mount the
export itself.

Result of the last run (Python 3.12, two compute nodes plus the login node):

| Check | Result |
| --- | --- |
| Discovery: both clients online | the reader saw the writer and the login client online within 90 s |
| Race rounds (exclusive create) | 20 of 20 rounds had exactly one winner |
| Rewrite reads | 3,719 reads, none missing, 20 distinct record versions, no partial record |
| Writer rewrites during the window | 1,482 beats, none failed |
| Self-check on the shared folder | no FAIL for `probe.rename`, `probe.hardlink`, `probe.exclusive`, or the listing and file-time checks; the listing delay was measured |

Two things were seen on the shared export and are part of the design:

- A read can fail with a stale handle (errno 116) while another client replaces the file. This
  happened once in an earlier run and made the reader fail. The test now counts it as a transient
  error and retries it. A partial record is never accepted. Consumers of the protocol must retry
  this error the same way.
- A writer's beat can fail the same way. The writer retries on its next beat and fails only on a
  conflict.

Limits of this run:

- The cluster job uses the cluster's default NFS mount options. It does not reproduce the strict
  (`noac`) and cached (`actimeo=60`) pair, so the attribute-cache case is covered only by the local
  layer above.
- The race rounds are ordered by flags, so the two creates are not truly simultaneous.

## Reading a skipped layer

The NFS tests are skipped, not failed, when the testbed is not up. A skip names the step to take:

- `NFS testbed not up: run tools/nfs-testbed/run.sh up, then run.sh test`, when the mount variables
  are not set.
- `NFS testbed not mounted: run tools/nfs-testbed/run.sh up first`, when a variable names a folder
  that is not a mount point.

`uv run pytest` without the marker does not run these tests at all. Pytest reports them as
deselected, and the NFS layer is then not part of that run.

## Rules

- **Loopback only.** The server port is bound to the loopback address. Do not change the bind
  address to a network interface, and do not export the folder to other hosts.
- **Fictional data.** The tests write only fictional ids such as `alice-console-a1` into a folder
  that they create and remove. Do not point `run.sh` at a real team folder or at a real export.
- **No host state changes.** The testbed mounts and unmounts folders under its own state folder,
  and it leaves the host's other mounts alone.
- **One testbed at a time.** Run `down` before `up` again with different settings.
