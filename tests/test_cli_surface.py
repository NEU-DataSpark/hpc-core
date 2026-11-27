"""The command surface is pinned: every command path and option is listed in a snapshot file.

A command or option that is added, removed or renamed changes the parser, so this test fails and
names the entry. Removing or renaming one is a major release (docs/versioning.md). After an
intended change, regenerate the snapshot and review the diff:

    uv run python tests/test_cli_surface.py --write
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from hpc_core.cli import build_parser

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "cli_surface.txt"


def _option_text(action: argparse.Action) -> str:
    flags = "/".join(action.option_strings)
    value = ""
    if action.nargs != 0:
        if action.choices:
            value = " {" + ",".join(str(choice) for choice in action.choices) + "}"
        else:
            metavar = action.metavar if isinstance(action.metavar, str) else None
            value = " " + (metavar or action.dest.upper())
    required = " (required)" if action.required else ""
    return f"{flags}{value}{required}"


def _positional_text(action: argparse.Action) -> str:
    name = action.metavar if isinstance(action.metavar, str) else action.dest
    return f"[{name}]" if action.nargs == "?" else name


def _walk(parser: argparse.ArgumentParser, path: str, lines: list[str]) -> None:
    lines.append(path)
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            for name in sorted(action.choices):
                _walk(action.choices[name], f"{path} {name}", lines)
        elif action.option_strings:
            lines.append("  " + _option_text(action))
        else:
            lines.append("  " + _positional_text(action))


def render_surface(parser: argparse.ArgumentParser) -> list[str]:
    lines: list[str] = []
    _walk(parser, "hpc-core", lines)
    return lines


def _find(parser: argparse.ArgumentParser, *path: str) -> argparse.ArgumentParser:
    current = parser
    for name in path:
        groups = [a for a in current._actions if isinstance(a, argparse._SubParsersAction)]
        current = groups[0].choices[name]
    return current


def test_surface_matches_the_snapshot() -> None:
    expected = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    diff = list(
        difflib.unified_diff(
            expected, render_surface(build_parser()), "snapshot", "parser", lineterm=""
        )
    )
    assert not diff, (
        "command surface changed (update tests/snapshots/cli_surface.txt if intended):\n"
        + "\n".join(diff)
    )


def test_an_added_option_is_reported_by_name() -> None:
    parser = build_parser()
    _find(parser, "parse", "squeue").add_argument("--format-name", help="test only")
    expected = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(expected, render_surface(parser), lineterm=""))
    assert any(line.startswith("+") and "--format-name" in line for line in diff)


def test_a_removed_command_is_reported_by_name() -> None:
    parser = build_parser()
    groups = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    del groups[0].choices["skills"]
    expected = SNAPSHOT.read_text(encoding="utf-8").splitlines()
    diff = list(difflib.unified_diff(expected, render_surface(parser), lineterm=""))
    assert any(line.startswith("-hpc-core skills") for line in diff)


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        SNAPSHOT.write_text("\n".join(render_surface(build_parser())) + "\n", encoding="utf-8")
        print(f"wrote {SNAPSHOT}")
    else:
        print("\n".join(render_surface(build_parser())))
