# Skills

The package ships two agent skills. A skill tells an agent which `hpc-core` command to run, and
what the output means. The skills are versioned with the package, so the text an agent reads
matches the command line it runs.

| Skill | Use it for |
| --- | --- |
| `hpc-scheduler-output` | Building read-only Slurm queries, running them on the caller's own transport, and parsing the output. |
| `hpc-run-report` | Checking a run-report CSV, reading its skipped rows and unavailable metrics, and computing its hours. |

## Layout

Each skill is one folder, named by the skill, that holds a `SKILL.md`:

```text
src/hpc_core/skills/
  hpc-scheduler-output/SKILL.md
  hpc-run-report/SKILL.md
```

Each `SKILL.md` starts with YAML front matter that has `name` (the folder name), `description`
(what the skill does and when to use it), `license` (`Apache-2.0`) and `metadata.version` (the
package version). The files are packaged as data in the wheel and in the Git tag, so the bytes are
the same in both.

## Install

List the skills that this version ships:

```bash
hpc-core skills list
```

Copy both skill folders into a directory of your choice:

```bash
hpc-core skills install ./skills
```

Copy one skill:

```bash
hpc-core skills install ./one --skill hpc-run-report
```

The copy is byte for byte. It refuses to replace a folder that already exists, and exits 1 and
copies nothing. It refuses a link at the destination or in a skill folder, and exits 2. It writes
nothing outside the destination.

To replace an installed skill with the version that ships with this package, use `--force`:

```bash
hpc-core skills install ./skills --force
```

`--force` replaces the `SKILL.md` of each named skill. It does not remove other files in the folder.

## Versions

A skill's `metadata.version` equals the package version. The test suite checks this, and it fails
when a release changes the version without changing the skills. A release therefore changes
`pyproject.toml` and both `SKILL.md` files in the same change.

## Updating after a release

1. Install the new release of `hpc-core`.
2. Run `hpc-core skills install ./skills --force` in the folder where your agent reads skills.
3. Run `hpc-core skills list` and check that the version matches the release you installed.

Skills never change on their own. A consumer that pins a release keeps the skills of that release
until it installs again.

## Rules for the skill text

- The skills use only the read-only Slurm commands the package builds: `squeue`, `sacct`, `sinfo`
  and `sstat`. They do not describe submitting, cancelling or changing a job.
- The skills use obviously fictional example values, such as `example-account`. They hold no
  credential, key path, host name, cluster path or e-mail address.
- Every `hpc-core` command in a skill must parse against the real command surface. The test suite
  checks this, so a changed option is caught before release.
