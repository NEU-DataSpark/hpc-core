"""The shipped skills stay true to the package: front matter, version, commands, read-only guidance
and hygiene. ``skill_problems`` is the one check; the tests run it on the real skills and on
planted drift to show it fails."""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import shlex
import tomllib
from pathlib import Path

import pytest
from hygiene_scan import default_targets, scan_files, scan_text

from hpc_core.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "src" / "hpc_core" / "skills"
SKILL_NAMES = ("hpc-scheduler-output", "hpc-run-report")
WRITE_PROGRAMS = ("sbatch", "scancel", "srun", "salloc", "scontrol", "sacctmgr")
LICENSE = "Apache-2.0"


def package_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1]
    return text


def parse_front_matter(text: str) -> dict[str, object]:
    """The front matter as a dict. Supports the subset the skills use: top-level scalars and one
    level of nested scalars. Anything else raises ValueError."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("does not start with '---'")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("front matter is not closed with '---'") from error
    data: dict[str, object] = {}
    nested: dict[str, object] | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw.startswith("  "):
            if nested is None:
                raise ValueError(f"nested line without a parent: {raw.strip()!r}")
            key, separator, value = raw.strip().partition(": ")
            if not separator:
                raise ValueError(f"nested line is not 'key: value': {raw.strip()!r}")
            nested[key] = _unquote(value)
            continue
        key, separator, value = raw.partition(":")
        if not separator:
            raise ValueError(f"line is not 'key: value': {raw!r}")
        if value.strip() == "":
            nested = {}
            data[key] = nested
        else:
            nested = None
            data[key] = _unquote(value)
    return data


_FENCED_BLOCK = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)


def skill_commands(text: str) -> list[str]:
    """The ``hpc-core`` commands a skill shows: lines in code fences and inline code spans.

    Fenced blocks are read first and then removed, so their backticks cannot pair up with the
    backticks of an inline span.
    """
    commands: list[str] = []
    for block in _FENCED_BLOCK.findall(text):
        commands.extend(
            line.strip() for line in block.splitlines() if line.strip().startswith("hpc-core ")
        )
    prose = _FENCED_BLOCK.sub("", text)
    commands.extend(
        span for span in re.findall(r"`([^`\n]+)`", prose) if span.startswith("hpc-core ")
    )
    return commands


def command_problems(command: str, parser: argparse.ArgumentParser) -> list[str]:
    """Problems with one command against the real parser: empty when it parses."""
    try:
        argv = shlex.split(command)[1:]
    except ValueError as error:
        return [f"{command!r} is not a shell command: {error}"]
    sink = io.StringIO()
    try:
        with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(argv)
    except SystemExit as request:
        if request.code == 0:
            return []
        detail = sink.getvalue().strip().splitlines()[-1:] or ["rejected"]
        return [f"{command!r} does not parse against the command surface: {detail[0]}"]
    return []


def skill_problems(
    folder: str, text: str, version: str, parser: argparse.ArgumentParser
) -> list[str]:
    """Every problem with one skill, named by its folder. Empty when the skill is consistent."""
    try:
        data = parse_front_matter(text)
    except ValueError as error:
        return [f"{folder}: front matter {error}"]

    problems: list[str] = []
    for field in ("name", "description", "license", "metadata"):
        if field not in data:
            problems.append(f"{folder}: front matter has no '{field}'")
    if data.get("name") != folder:
        problems.append(f"{folder}: front matter name {data.get('name')!r} is not the folder name")
    if data.get("license") != LICENSE:
        problems.append(f"{folder}: license is not {LICENSE}")
    metadata = data.get("metadata")
    skill_version = metadata.get("version") if isinstance(metadata, dict) else None
    if skill_version != version:
        problems.append(
            f"{folder}: metadata.version {skill_version!r} is not the package version {version!r}"
        )
    description = data.get("description")
    if not isinstance(description, str) or not description:
        problems.append(f"{folder}: description is empty")
    else:
        if not re.search(r"\bUse when\b", description):
            problems.append(f"{folder}: description does not say when to use the skill")
        if ": " in description or " #" in description:
            problems.append(f"{folder}: description is not a plain YAML scalar")

    commands = skill_commands(text)
    if not commands:
        problems.append(f"{folder}: shows no hpc-core command")
    for command in commands:
        problems.extend(f"{folder}: {problem}" for problem in command_problems(command, parser))
    for program in WRITE_PROGRAMS:
        if re.search(rf"\b{program}\b", text):
            problems.append(f"{folder}: names the write command {program}")
    return problems


def _skill_text(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_each_skill_is_consistent_with_the_package(name: str) -> None:
    assert skill_problems(name, _skill_text(name), package_version(), build_parser()) == []


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_front_matter_has_the_fields_the_format_needs(name: str) -> None:
    data = parse_front_matter(_skill_text(name))
    assert data["name"] == name
    assert data["license"] == LICENSE
    assert isinstance(data["metadata"], dict)
    assert data["metadata"]["version"] == package_version()


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_hpc_core_command_in_a_skill_parses(name: str) -> None:
    commands = skill_commands(_skill_text(name))
    assert commands
    parser = build_parser()
    for command in commands:
        assert command_problems(command, parser) == [], command


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_skill_text_names_only_read_only_commands(name: str) -> None:
    text = _skill_text(name)
    for program in WRITE_PROGRAMS:
        assert not re.search(rf"\b{program}\b", text), program


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_hygiene_scan_covers_and_clears_the_skill_file(name: str) -> None:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path in default_targets(ROOT)
    assert scan_files([path], ROOT) == []


def test_a_planted_address_in_a_skill_fails_the_hygiene_scan() -> None:
    rules = {
        f.rule for f in scan_text("src/hpc_core/skills/x/SKILL.md", "mail someone@mail.example\n")
    }
    assert "e-mail address" in rules


def test_a_changed_skill_version_fails_and_names_the_skill() -> None:
    text = _skill_text("hpc-run-report").replace('version: "', 'version: "9.9.', 1)
    problems = skill_problems("hpc-run-report", text, package_version(), build_parser())
    assert any(
        "hpc-run-report" in problem and "metadata.version" in problem for problem in problems
    )


def test_a_command_with_a_changed_option_fails_and_names_the_command() -> None:
    # --window is not an option of the real parser; a prefix such as --hour is refused too.
    text = _skill_text("hpc-scheduler-output").replace("--hours 24", "--window 24")
    problems = skill_problems("hpc-scheduler-output", text, package_version(), build_parser())
    assert any("--window" in problem for problem in problems)


def test_a_prefix_of_an_option_is_refused() -> None:
    assert command_problems(
        "hpc-core commands finished --account example-account --hour 24", build_parser()
    )


def test_a_skill_that_names_a_write_command_fails() -> None:
    text = _skill_text("hpc-run-report") + "\nRun `scancel` to stop the job.\n"
    problems = skill_problems("hpc-run-report", text, package_version(), build_parser())
    assert any("scancel" in problem for problem in problems)


def test_a_skill_with_a_mismatched_name_fails() -> None:
    problems = skill_problems(
        "hpc-run-report", _skill_text("hpc-scheduler-output"), package_version(), build_parser()
    )
    assert any("is not the folder name" in problem for problem in problems)
