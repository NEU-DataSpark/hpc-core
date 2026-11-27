# Versioning

The package uses semantic versioning, `MAJOR.MINOR.PATCH`.

## Rules

- **Release version.** `pyproject.toml` holds the release version. A release tag `vX.Y.Z` must
  equal it. `tools/check_release_tag.py` checks this before building a tagged release.
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

The release draft workflow runs on pushes to `main` and can also be started manually on `main`.
Hagicode's release drafter generates notes from commits and suggests a version; it does not publish
the release or create a tag.

After CI succeeds for a push to `main`, the release workflow also builds that exact commit and
publishes a development release to PyPI. It derives the version by incrementing the patch component
of `pyproject.toml` and appending `.devN`, where `N` is the CI run number multiplied by 1000 plus
its attempt number. For example, `0.1.0` becomes `0.1.1.dev42001` for run 42, attempt 1. This patch
number is a snapshot identifier, not a promise about the next release version. The version change
exists only in the build checkout; it is not committed. CI reruns get a new version, while rerunning
the release workflow for the same CI attempt skips files already on PyPI.

1. Review the draft and set `version` in `pyproject.toml` to the draft version. Merge the version
   change to `main` once CI is green, then review the updated draft and its target commit. If the
   suggested version changed, update the project version again before tagging.
2. Push a `vX.Y.Z` tag pointing to that commit. The release workflow fails if the tag and project
   version differ. It builds and checks the sdist and wheel, stores them as a workflow artifact, and
   publishes them to PyPI with Trusted Publishing.
3. Check that the release workflow succeeded, then publish the GitHub draft manually. Use the
   already-pushed tag when publishing it.

Before the first release, register a PyPI pending trusted publisher for project `hpc-core`, owner
`NEU-DataSpark`, repository `hpc-core`, workflow `release.yml`, and environment `pypi`. If the
project already exists, add the same trusted publisher in its PyPI settings instead. Configure the
GitHub `pypi` environment's protection rules as needed. A pending publisher does not reserve the
project name until the first upload.

## Consumers

Once published, consumers can pin a PyPI release, for example `hpc-core==X.Y.Z`, or continue to
install a Git tag. They move to a new version by changing that pin, and run the contract test in
[`consumer-contract-test.md`](consumer-contract-test.md) before they do.

To opt into development releases, use `python -m pip install --pre --upgrade hpc-core`, or pin a
specific development version with `python -m pip install "hpc-core==X.Y.Z.devN"`. Without `--pre`
or an explicit development-version pin, pip normally selects stable releases.
