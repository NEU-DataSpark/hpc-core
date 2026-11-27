"""The package has no runtime dependency: every import is standard library or hpc_core."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import hpc_core

PACKAGE = Path(hpc_core.__file__).parent
# The package may be the installed copy, so the project file is found from this test file.
PROJECT = Path(__file__).resolve().parent.parent
STDLIB = frozenset(sys.stdlib_module_names)


def _foreign_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top != "hpc_core" and top not in STDLIB:
                found.append(name)
    return found


def test_every_import_is_stdlib_or_package() -> None:
    offenders = {
        path.relative_to(PACKAGE.parent).as_posix(): _foreign_imports(path)
        for path in sorted(PACKAGE.rglob("*.py"))
    }
    offenders = {module: names for module, names in offenders.items() if names}
    assert offenders == {}


def test_pyproject_declares_no_runtime_dependency() -> None:
    data = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["dependencies"] == []
