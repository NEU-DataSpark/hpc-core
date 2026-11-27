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
| Test kit | `hpc_core.testing` | Anonymised scheduler fixtures, golden run-reports, reader and writer contract checks, a fake transport | None |

Consumers keep their own transport implementation: the operator skill uses the `ssh` command, and
the HPC Console uses `paramiko`. This package contains neither.

## Install

Once a release has been published to PyPI, install a pinned version:

```bash
python -m pip install "hpc-core==X.Y.Z"
```

Alternatively, install a tagged release directly from Git:

```bash
python -m pip install "hpc-core @ git+https://github.com/NEU-DataSpark/hpc-core.git@vX.Y.Z"
```

See [`docs/versioning.md`](docs/versioning.md) for the release process.

## Development

Run these from the repository root in a virtual environment:

```bash
python -m pip install -e ".[dev]"   # install with the development tools
python -m pytest                    # test suite, including layering, stdlib-only and hygiene guards
python -m ruff check .              # lint
python -m mypy                      # strict type check
python tools/hygiene_scan.py        # scan for paths, addresses, e-mail addresses and key headers
python -m pip wheel --no-deps -w dist .   # build the wheel
```

Documentation is in [`docs/`](docs/): parsing, the run-report contract, the adapter, the consumer
contract test, fixture recording, and versioning.

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
