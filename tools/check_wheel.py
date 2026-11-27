"""Check that a built wheel carries what the consumer contract, the CLI and the license need.

    python tools/check_wheel.py dist/hpc_core-0.4.0-py3-none-any.whl

Exits 0 when every required file is in the wheel, 1 when one is missing, and 2 for bad arguments.
"""

from __future__ import annotations

import sys
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path

REQUIRED_PREFIXES = (
    "hpc_core/testing/fixtures/scheduler/",
    "hpc_core/testing/fixtures/reports/",
    "hpc_core/py.typed",
)
REQUIRED_SUFFIXES = ("/licenses/LICENSE", "/licenses/NOTICE")
# The skills shipped with the package. Each is one folder holding SKILL.md, named by the skill.
REQUIRED_FILES = (
    "hpc_core/skills/hpc-scheduler-output/SKILL.md",
    "hpc_core/skills/hpc-run-report/SKILL.md",
)


def missing_entries(names: Iterable[str]) -> list[str]:
    listed = list(names)
    missing = [
        prefix
        for prefix in REQUIRED_PREFIXES
        if not any(name.startswith(prefix) for name in listed)
    ]
    missing += [
        suffix for suffix in REQUIRED_SUFFIXES if not any(name.endswith(suffix) for name in listed)
    ]
    missing += [path for path in REQUIRED_FILES if path not in listed]
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_wheel.py WHEEL", file=sys.stderr)
        return 2
    with zipfile.ZipFile(Path(args[0])) as wheel:
        missing = missing_entries(wheel.namelist())
    if missing:
        print(f"check_wheel: {args[0]} lacks: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(
        f"check_wheel: {args[0]} carries the fixtures, py.typed, the skills and the license files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
