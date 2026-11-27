"""The command-line documents stay true: each hpc-core example runs as written against recorded
fixtures, every command in the surface is documented, and every relative link resolves."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from test_cli_surface import render_surface

from hpc_core.cli import build_parser
from hpc_core.testing import load_cases

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
EXECUTED_DOCS = (DOCS / "cli.md", DOCS / "skills.md", REPO / "README.md")
LINKED_DOCS = (REPO / "README.md", REPO / "AGENTS.md", *sorted(DOCS.glob("*.md")))
# The files the examples read, each a recorded fixture with its header lines stripped.
FIXTURE_FILES = {
    "squeue.txt": ("scheduler", "squeue-operator-recorded"),
    "run-report.csv": ("report", "finished_run"),
}
_BASH_BLOCK = re.compile(r"^```bash\n(.*?)^```", re.MULTILINE | re.DOTALL)
_LINK = re.compile(r"\]\(([^)\s]+)\)")
# An example starts with the command, or follows a pipe. "hpc-core==X.Y.Z" and a quoted requirement
# such as "hpc-core @ git+..." are install lines, not examples.
_EXAMPLE = re.compile(r"(^|\|\s*)hpc-core\s")


def _example_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for block in _BASH_BLOCK.findall(path.read_text(encoding="utf-8")):
        lines.extend(line for line in block.splitlines() if _EXAMPLE.search(line))
    return lines


def _materialize(directory: Path) -> None:
    for name, (kind, case_name) in FIXTURE_FILES.items():
        case = next(c for c in load_cases(kind) if c.name == case_name)
        (directory / name).write_text(case.text, encoding="utf-8")


def _as_run(line: str) -> str:
    """The example with ``hpc-core`` replaced by this interpreter running the package."""
    prefix = f"{shlex.quote(sys.executable)} -m hpc_core"
    return re.sub(r"\bhpc-core\b", prefix, line)


@pytest.mark.parametrize("path", EXECUTED_DOCS, ids=lambda path: path.name)
def test_every_example_runs_as_written(path: Path, tmp_path: Path) -> None:
    _materialize(tmp_path)
    lines = _example_lines(path)
    assert lines, f"{path.name} has no hpc-core example"
    for line in lines:
        result = subprocess.run(
            _as_run(line),
            shell=True,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"{path.name}: {line!r} exited {result.returncode}: {result.stderr}"
        )


def test_every_command_in_the_surface_is_documented() -> None:
    documented = (DOCS / "cli.md").read_text(encoding="utf-8") + (DOCS / "skills.md").read_text(
        encoding="utf-8"
    )
    for line in render_surface(build_parser()):
        if line.startswith("hpc-core "):
            path = line[len("hpc-core ") :]
            assert path in documented, f"the docs do not show '{path}'"


@pytest.mark.parametrize("path", LINKED_DOCS, ids=lambda path: path.name)
def test_relative_links_resolve(path: Path) -> None:
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        file_part = target.split("#", 1)[0]
        assert (path.parent / file_part).exists(), f"{path.name}: {target} does not resolve"
