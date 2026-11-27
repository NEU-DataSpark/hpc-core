"""Every action the workflows use is pinned to a full commit SHA, not a tag or branch."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
_PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _uses() -> list[tuple[str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for match in _USES.finditer(path.read_text(encoding="utf-8")):
            found.append((path.name, match.group(1)))
    return found


def test_workflows_use_at_least_one_action() -> None:
    assert _uses()


@pytest.mark.parametrize(("workflow", "action"), _uses())
def test_action_is_pinned_to_a_full_sha(workflow: str, action: str) -> None:
    assert _PINNED.fullmatch(action), f"{workflow}: {action} is not pinned to a 40-character SHA"
