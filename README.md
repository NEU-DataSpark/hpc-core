# hpc-core

Shared Python packages for remote HPC operations. This repository is the single source of the packages that the DataSpark HPC tools build on, so the parsing and the data formats are written once and used by every consumer.

**Status:** early. The scope is agreed in an OpenSpec proposal; no package is released yet.

## Scope

The packages are split by layer, not by lifecycle stage (environment setup, submit, fetch, monitor, metrics). A lifecycle split would make each package depend on the transport and the data formats again, and duplicate them.

| Layer | Responsibility | I/O |
| --- | --- | --- |
| Contract | Scheduler output parsing (`squeue`, `sacct`, `sinfo`), the run-report CSV schema and its `schema_version`, metric calculations | None. Standard library only |
| Transport | A small interface to run a fixed command on the login node: timeout, output limit, exit status | Yes, one implementation per consumer |
| Scheduler adapter | Builds the fixed Slurm command strings and passes their output to the contract layer | Through the transport interface |

Consumers keep their own transport implementation: the operator skill uses the `ssh` command, and the HPC Console uses `paramiko`. The contract layer has no third-party dependency, so the operator skill can still depend on the standard library alone.

## Consumers

- `DataSpark-Skills` (the `hpc-operator` skill): submits and tracks jobs and writes run reports.
- `hpc-console` (the web console): reads the cluster state and the run reports.

## Rules

- Never commit credentials, host names, account names, key paths or cluster-specific paths. Pass them in as arguments or settings.
- Every parser has tests with recorded, anonymised scheduler output as fixtures.
- A change to the run-report CSV format bumps `schema_version` and comes with a contract test that both consumers run.

## Development

No package code exists yet. Build and test commands will be added here with the first package.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
