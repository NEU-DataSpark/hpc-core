"""Set a unique development version for a successful main-branch CI run."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


def development_version(version: str, run_number: int, attempt: int) -> str:
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
    if match is None:
        raise ValueError(f"expected a MAJOR.MINOR.PATCH version, got {version!r}")
    if run_number < 1 or not 1 <= attempt <= 999:
        raise ValueError(
            "the CI run number must be positive and the attempt must be between 1 and 999"
        )
    major, minor, patch = match.groups()
    return f"{major}.{minor}.{int(patch) + 1}.dev{run_number * 1000 + attempt}"


def prepare(pyproject: Path, run_number: int, attempt: int) -> str:
    text = pyproject.read_text(encoding="utf-8")
    version = tomllib.loads(text)["project"]["version"]
    if not isinstance(version, str):
        raise ValueError("the project version must be a string")
    dev_version = development_version(version, run_number, attempt)
    pattern = rf"""(?m)^(version\s*=\s*)(["']){re.escape(version)}\2(\s*(?:\#.*)?)$"""
    updated, count = re.subn(pattern, rf'\g<1>"{dev_version}"\g<3>', text)
    if count != 1 or tomllib.loads(updated)["project"]["version"] != dev_version:
        raise ValueError("could not uniquely update the project version")
    pyproject.write_text(updated, encoding="utf-8")
    return dev_version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_number", type=int)
    parser.add_argument("attempt", type=int)
    args = parser.parse_args()
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        version = prepare(pyproject, args.run_number, args.attempt)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Development version: {version}")


if __name__ == "__main__":
    main()
