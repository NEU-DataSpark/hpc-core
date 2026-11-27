# Versioning

The package uses semantic versioning, `MAJOR.MINOR.PATCH`.

## Rules

- **One version.** `pyproject.toml` holds the version. A release tag `vX.Y.Z` must equal it.
  `tools/check_release_tag.py` checks this, and the release workflow runs it before building.
- **Schema changes.** A new `schema_version` for the run-report CSV ships in at least a minor
  release. Consumers pin a tag, so a new schema reaches them only when they choose to move.
- **Breaking changes.** Removing support for an old `schema_version`, or removing or renaming a
  public name, is a major release.
- **Public API.** The public API is the set of names exported from `hpc_core.contract`,
  `hpc_core.transport` and `hpc_core.slurm` (their `__all__`). A name not in those lists is an
  internal detail and may change in any release.
- **Test kit.** `hpc_core.testing` is not part of the public API. Its names and fixture files may
  change in any release, and each change to a golden case is listed in the release notes.

## Releasing

1. Change `version` in `pyproject.toml` and add the change to the release notes.
2. Merge to `main` once CI is green.
3. Tag the commit `vX.Y.Z`. The release workflow fails if the tag and the version differ, builds the
   sdist and wheel, checks them, and attaches them to the run.

Creating the first tag is a separate step, not part of the package change.

## Consumers

Consumers install a tag, for example `hpc-core @ git+https://github.com/NEU-DataSpark/hpc-core.git@vX.Y.Z`.
They move to a new version by changing that tag, and run the contract test in
[`consumer-contract-test.md`](consumer-contract-test.md) before they do.
