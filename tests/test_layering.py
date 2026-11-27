"""Layer direction guard: contract <- transport <- slurm, and testing may use all of them."""

from __future__ import annotations

import ast
from pathlib import Path

import hpc_core

PACKAGE = Path(hpc_core.__file__).parent

# Layer -> the other hpc_core layers it may import. A layer imports only itself unless listed.
ALLOWED: dict[str, frozenset[str]] = {
    "contract": frozenset(),
    "transport": frozenset({"contract"}),
    "slurm": frozenset({"contract", "transport"}),
    "testing": frozenset({"contract", "transport", "slurm"}),
}


def _layer_of(path: Path) -> str | None:
    relative = path.relative_to(PACKAGE)
    return relative.parts[0] if len(relative.parts) > 1 else None


def _imported_layers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    layers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "hpc_core":
            layers.update(alias.name for alias in node.names if alias.name in ALLOWED)
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            parts = name.split(".")
            if parts[0] == "hpc_core" and len(parts) > 1:
                layers.add(parts[1])
    return layers


def layering_violations() -> list[str]:
    """Return one message per forbidden import, naming the module and the layer it reached."""
    problems: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        layer = _layer_of(path)
        if layer is None:
            continue
        allowed = ALLOWED[layer] | {layer}
        for target in sorted(_imported_layers(path)):
            if target not in allowed:
                module = path.relative_to(PACKAGE.parent).as_posix()
                problems.append(f"{module} imports layer '{target}' (layer '{layer}' may not)")
    return problems


def test_layers_depend_in_one_direction() -> None:
    assert layering_violations() == []


def test_guard_catches_the_from_package_form(tmp_path: Path) -> None:
    planted = PACKAGE / "contract" / "_planted_from_package.py"
    planted.write_text("from hpc_core import slurm\n", encoding="utf-8")
    try:
        problems = layering_violations()
    finally:
        planted.unlink()
    assert any("contract/_planted_from_package.py" in problem for problem in problems)


def test_guard_names_the_module_on_a_wrong_direction_import(tmp_path: Path) -> None:
    # The guard reads the real package; a planted module proves that a violation is reported.
    planted = PACKAGE / "contract" / "_planted_wrong_direction.py"
    planted.write_text("from hpc_core.slurm import commands\n", encoding="utf-8")
    try:
        problems = layering_violations()
    finally:
        planted.unlink()
    assert any("contract/_planted_wrong_direction.py" in problem for problem in problems)
