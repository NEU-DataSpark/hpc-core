"""Layer direction guard: contract <- transport <- slurm and coordination, cli on top, testing may
use all of them but cli.

Absolute and relative imports both count: the package uses relative imports, so a relative import
of a higher layer is resolved to its absolute module name before the rule is applied.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hpc_core

PACKAGE = Path(hpc_core.__file__).parent

# Layer -> the other hpc_core layers it may import. A layer imports only itself unless listed.
# Nothing imports ``cli``: it is the top of the stack, reached only from the entry points.
ALLOWED: dict[str, frozenset[str]] = {
    "contract": frozenset(),
    "transport": frozenset({"contract"}),
    "slurm": frozenset({"contract", "transport"}),
    "coordination": frozenset({"contract", "transport"}),
    "cli": frozenset({"contract", "transport", "slurm", "coordination"}),
    "testing": frozenset({"contract", "transport", "slurm", "coordination"}),
}


def _layer_of(path: Path) -> str | None:
    relative = path.relative_to(PACKAGE)
    return relative.parts[0] if len(relative.parts) > 1 else None


def _resolved_module(path: Path, node: ast.ImportFrom) -> str:
    """The absolute dotted name an ``ImportFrom`` refers to, with relative levels resolved."""
    if node.level == 0:
        return node.module or ""
    package = ["hpc_core", *path.relative_to(PACKAGE).parent.parts]
    kept = package[: len(package) - (node.level - 1)]
    return ".".join([*kept, *(node.module.split(".") if node.module else [])])


def _layer_of_dotted(dotted: str) -> str | None:
    parts = dotted.split(".")
    if parts[0] == "hpc_core" and len(parts) > 1:
        return parts[1]
    return None


def _imported_layers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    layers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                layer = _layer_of_dotted(alias.name)
                if layer is not None:
                    layers.add(layer)
        elif isinstance(node, ast.ImportFrom):
            module = _resolved_module(path, node)
            layer = _layer_of_dotted(module)
            if layer is not None:
                layers.add(layer)
            if module == "hpc_core":
                # ``from hpc_core import slurm`` and ``from .. import slurm`` name a layer here.
                layers.update(alias.name for alias in node.names if alias.name in ALLOWED)
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


def _with_planted(relative: str, source: str) -> list[str]:
    planted = PACKAGE / relative
    planted.write_text(source, encoding="utf-8")
    try:
        return layering_violations()
    finally:
        planted.unlink()


def test_layers_depend_in_one_direction() -> None:
    assert layering_violations() == []


def test_guard_catches_the_from_package_form() -> None:
    problems = _with_planted("contract/_planted_from_package.py", "from hpc_core import slurm\n")
    assert any("contract/_planted_from_package.py" in problem for problem in problems)


def test_guard_names_the_module_on_a_wrong_direction_import() -> None:
    # The guard reads the real package; a planted module proves that a violation is reported.
    problems = _with_planted(
        "contract/_planted_wrong_direction.py", "from hpc_core.slurm import commands\n"
    )
    assert any("contract/_planted_wrong_direction.py" in problem for problem in problems)


def test_guard_catches_a_relative_import_of_a_higher_layer() -> None:
    problems = _with_planted("contract/_planted_relative.py", "from ..slurm import commands\n")
    assert any("contract/_planted_relative.py" in problem for problem in problems)


def test_guard_catches_a_relative_import_of_the_cli_layer() -> None:
    problems = _with_planted("transport/_planted_cli.py", "from .. import cli\n")
    assert any(
        "transport/_planted_cli.py" in problem and "'cli'" in problem for problem in problems
    )


def test_guard_catches_an_absolute_import_of_the_cli_layer() -> None:
    problems = _with_planted("slurm/_planted_cli.py", "from hpc_core.cli import main\n")
    assert any("slurm/_planted_cli.py" in problem for problem in problems)


def test_the_cli_may_import_the_lower_layers() -> None:
    source = (
        "from ..contract import squeue\n"
        "from ..slurm import commands\n"
        "from ..transport import CommandResult\n"
    )
    problems = _with_planted("cli/_planted_ok.py", source)
    assert problems == []


def test_coordination_imports_only_contract_and_transport() -> None:
    problems = _with_planted("coordination/_planted_slurm.py", "from ..slurm import commands\n")
    assert any("coordination/_planted_slurm.py" in problem for problem in problems)


def test_nothing_but_cli_and_testing_may_import_coordination() -> None:
    for layer in ("contract", "transport", "slurm"):
        problems = _with_planted(
            f"{layer}/_planted_coordination.py", "from ..coordination import store\n"
        )
        assert any(f"{layer}/_planted_coordination.py" in problem for problem in problems)


def test_cli_and_testing_may_import_coordination() -> None:
    assert (
        _with_planted("cli/_planted_coordination_ok.py", "from ..coordination import store\n") == []
    )
    assert (
        _with_planted("testing/_planted_coordination_ok.py", "from ..coordination import store\n")
        == []
    )
