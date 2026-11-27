"""Check that a release tag equals the version in pyproject.toml.

    python tools/check_release_tag.py v0.1.0

Exits 0 when the tag is ``v`` followed by the project version, 1 when it differs, and 2 when the
arguments are wrong.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path


def project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def check(tag: str, version: str) -> str | None:
    """Return None when the tag matches the version, otherwise a message."""
    expected = f"v{version}"
    if tag != expected:
        return f"tag {tag!r} does not match pyproject version {version!r} (expected {expected!r})"
    return None


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_release_tag.py TAG", file=sys.stderr)
        return 2
    base = root if root is not None else Path(__file__).resolve().parent.parent
    message = check(args[0], project_version(base / "pyproject.toml"))
    if message is not None:
        print(f"check_release_tag: {message}", file=sys.stderr)
        return 1
    print(f"check_release_tag: {args[0]} matches the project version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
