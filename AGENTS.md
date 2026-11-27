# hpc-core: assistant conventions

- This repository is one Python distribution, `hpc-core`, with four layers and a test kit:
  `hpc_core.contract` (parsing, run-report schema, metrics; no I/O), `hpc_core.transport`
  (a protocol for running one fixed command), `hpc_core.slurm` (fixed Slurm command builders and
  the adapter), `hpc_core.cli` (the `hpc-core` command and `python -m hpc_core`; offline, reads
  files or standard input) and `hpc_core.testing` (fixtures, contract checks, fake transport).
  The skills shipped as package data live in `src/hpc_core/skills/`.
- Layer direction is enforced by `tests/test_layering.py`: `contract` imports only itself,
  `transport` may import `contract`, `slurm` may import `contract` and `transport`, `cli` may
  import `contract`, `transport` and `slurm`, and `testing` may import every layer except `cli`.
  Nothing imports `cli`. The guard resolves relative imports too. Do not add an import that breaks
  this.
- CLI conventions: the command line only builds, parses and prints. It never opens a connection or
  runs Slurm, and `commands` prints an argument list instead of running it. Standard output holds
  only JSON; messages go to standard error. Exit status: 0 success, 1 input read but not
  acceptable, 2 usage or argument error. A failed row is counted in `skipped` and never printed.
  The profile table is `hpc_core/cli/_profiles.py`, the one place the command line reads profile
  names from. Do not import `hpc_core.testing` from `cli`.
- The command surface (every command, sub-command and option) is pinned in
  `tests/snapshots/cli_surface.txt`. After an intended change, regenerate it with
  `uv run python tests/test_cli_surface.py --write` and review the diff. Every `hpc-core` command
  in a skill or in `docs/cli.md` must parse against the real parser; the tests check this.
- The runtime has no third-party dependency. `tests/test_stdlib_only.py` fails on any import that
  is neither standard library nor `hpc_core`. Development tools belong in the `dev` extra only.
- No private data in this repository: no host names, account names, key paths, cluster paths or
  e-mail addresses. Fixtures are anonymised; a new recording goes through `tools/scrub_fixture.py`
  and must pass `tools/hygiene_scan.py`. Never commit a raw recording.
- Write code, tests, docs and commit messages in English.
- Python dependencies are managed with `uv`. `uv.lock` is committed. Commands, run from the
  repository root:
  - install: `uv sync --extra dev`
  - lock check: `uv lock --check` (run `uv lock` after changing `pyproject.toml`)
  - tests: `uv run pytest`
  - lint: `uv run ruff check .`
  - type check: `uv run mypy`
  - hygiene scan: `uv run python tools/hygiene_scan.py`
- Versioning: one version in `pyproject.toml`; a release tag `vX.Y.Z` must equal it. `uv.lock`
  records the project version too, so run `uv lock` after changing it. A change to the run-report
  columns needs a new `schema_version`, a new header snapshot and a minor release. See
  `docs/versioning.md`.
