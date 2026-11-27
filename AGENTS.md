# hpc-core: assistant conventions

- This repository is one Python distribution, `hpc-core`, with three layers and a test kit:
  `hpc_core.contract` (parsing, run-report schema, metrics; no I/O), `hpc_core.transport`
  (a protocol for running one fixed command), `hpc_core.slurm` (fixed Slurm command builders and
  the adapter) and `hpc_core.testing` (fixtures, contract checks, fake transport).
- Layer direction is enforced by `tests/test_layering.py`: `contract` imports only itself,
  `transport` may import `contract`, `slurm` may import `contract` and `transport`, and
  `testing` may import every layer. Do not add an import that breaks this.
- The runtime has no third-party dependency. `tests/test_stdlib_only.py` fails on any import that
  is neither standard library nor `hpc_core`. Development tools belong in the `dev` extra only.
- No private data in this repository: no host names, account names, key paths, cluster paths or
  e-mail addresses. Fixtures are anonymised; a new recording goes through `tools/scrub_fixture.py`
  and must pass `tools/hygiene_scan.py`. Never commit a raw recording.
- Write code, tests, docs and commit messages in English.
- Commands, run from the repository root:
  - install: `python -m pip install -e ".[dev]"`
  - tests: `python -m pytest`
  - lint: `python -m ruff check .`
  - type check: `python -m mypy`
  - hygiene scan: `python tools/hygiene_scan.py`
- Versioning: one version in `pyproject.toml`; a release tag `vX.Y.Z` must equal it. A change to
  the run-report columns needs a new `schema_version`, a new header snapshot and a minor release.
  See `docs/versioning.md`.
