# hpc-core

Shared Python package for remote HPC operations. It holds the scheduler output parsers, the
run-report CSV contract and its metrics, a minimal transport interface and a fixed-command Slurm
adapter, so the DataSpark HPC tools parse and format the same data the same way.

It has no runtime dependency and needs Python 3.11 or newer.

## Layers

The packages are split by layer, not by lifecycle stage (environment setup, submit, fetch,
monitor, metrics). A lifecycle split would make each package depend on the transport and the data
formats again, and duplicate them.

| Layer | Package | Responsibility | I/O |
| --- | --- | --- | --- |
| Contract | `hpc_core.contract` | Scheduler output parsing (`squeue`, `sacct`, `sinfo`, `sstat`), the run-report CSV schema and its `schema_version`, metric calculations | None. Standard library only |
| Transport | `hpc_core.transport` | A small interface to run a fixed command on the login node: argument tuple, timeout, output limit, exit status | Yes, one implementation per consumer |
| Scheduler adapter | `hpc_core.slurm` | Builds the fixed, read-only Slurm commands and passes their output to the contract layer | Through the transport interface |
| Command line | `hpc_core.cli` | The `hpc-core` command: parses recorded output, checks run reports, prints fixed commands, installs the skills | Files and standard input only; never a connection |
| Test kit | `hpc_core.testing` | Anonymised scheduler fixtures, golden run-reports, reader and writer contract checks, a fake transport | None |

Consumers keep their own transport implementation: the operator skill uses the `ssh` command, and
the HPC Console uses `paramiko`. This package contains neither.

## Install

Consumers use [`uv`](https://docs.astral.sh/uv/). Once a release has been published to PyPI, add a
pinned version to the consumer's project:

```bash
uv add "hpc-core==X.Y.Z"
```

To opt into the latest available development build from `main`, in any environment:

```bash
uv pip install --pre --upgrade hpc-core
```

Alternatively, add a tagged release directly from Git:

```bash
uv add "hpc-core @ git+https://github.com/NEU-DataSpark/hpc-core.git@vX.Y.Z"
```

See [`docs/versioning.md`](docs/versioning.md) for the release process.

Installing the package also installs the `hpc-core` command. To put it on your `PATH` without adding
it to a project, install it as a tool:

```bash
uv tool install "hpc-core==X.Y.Z"
```

## Command line

`hpc-core` (also `python -m hpc_core`) is offline. It reads recorded scheduler output or a run
report from a file or standard input, and prints JSON. It prints the fixed read-only Slurm command
for a query, so the caller runs it on its own login-node transport and passes the output back.

```bash
hpc-core commands queue --account example-account   # the argument list to run
hpc-core parse squeue --profile operator-sampling squeue.txt
hpc-core report validate run-report.csv
hpc-core skills install ./skills
```

Exit status: 0 success, 1 the input was read but is not acceptable, 2 a usage or argument error.
Full reference: [`docs/cli.md`](docs/cli.md).

## Skills

The package ships two agent skills, `hpc-scheduler-output` and `hpc-run-report`. They are in the
wheel and the Git tag, and `hpc-core skills install DEST` copies them into a folder. Each skill
follows the package version. See [`docs/skills.md`](docs/skills.md).

## Development

Run these from the repository root. `uv` creates and uses `.venv` from the committed `uv.lock`:

```bash
uv sync --extra dev                  # install with the development tools
uv lock --check                      # the lock file matches pyproject.toml
uv run pytest                        # test suite, including layering, stdlib-only and hygiene guards
uv run ruff check .                  # lint
uv run mypy                          # strict type check
uv run python tools/hygiene_scan.py  # scan for paths, addresses, e-mail addresses and key headers
uv build --wheel --out-dir dist      # build the wheel
```

Documentation is in [`docs/`](docs/): parsing, the run-report contract, the adapter, the consumer
contract test, fixture recording, versioning, the command line and the skills.

## Rules

- Never commit credentials, host names, account names, key paths or cluster-specific paths. Pass
  them in as arguments or settings.
- Every parser has tests with recorded, anonymised scheduler output as fixtures.
- A change to the run-report CSV format bumps `schema_version` and comes with a contract test that
  both consumers run.

## Consumers

- `DataSpark-Skills` (the `hpc-operator` skill): submits and tracks jobs and writes run reports.
- `hpc-console` (the web console): reads the cluster state and the run reports.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
