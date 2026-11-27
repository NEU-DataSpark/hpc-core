"""``hpc-core skills``: list, install all or one, refusals, --force, byte-identical copies and the
rule that nothing is written outside the destination."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path

from conftest import RunCli

from hpc_core.cli._version import package_version

SKILLS = ("hpc-run-report", "hpc-scheduler-output")


def _packaged(name: str) -> bytes:
    return (resources.files("hpc_core") / "skills" / name / "SKILL.md").read_bytes()


def test_list_names_both_skills_with_the_package_version(run_cli: RunCli) -> None:
    code, out, err = run_cli("skills", "list")
    assert code == 0, err
    assert json.loads(out) == [
        {"name": "hpc-run-report", "version": package_version()},
        {"name": "hpc-scheduler-output", "version": package_version()},
    ]


def test_install_all_copies_both_folders_byte_for_byte(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    code, out, err = run_cli("skills", "install", str(dest))
    assert code == 0, err
    assert {entry["name"] for entry in json.loads(out)["installed"]} == set(SKILLS)
    for name in SKILLS:
        assert (dest / name / "SKILL.md").read_bytes() == _packaged(name)


def test_install_one_copies_only_that_skill(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    code, _, err = run_cli("skills", "install", str(dest), "--skill", "hpc-run-report")
    assert code == 0, err
    assert (dest / "hpc-run-report" / "SKILL.md").read_bytes() == _packaged("hpc-run-report")
    assert not (dest / "hpc-scheduler-output").exists()


def test_an_unknown_skill_exits_2_and_lists_the_valid_names(
    run_cli: RunCli, tmp_path: Path
) -> None:
    dest = tmp_path / "skills"
    code, out, err = run_cli("skills", "install", str(dest), "--skill", "no-such-skill")
    assert code == 2
    assert out == ""
    for name in SKILLS:
        assert name in err
    assert not dest.exists()


def test_an_existing_folder_exits_1_and_nothing_is_copied(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    (dest / "hpc-run-report").mkdir(parents=True)
    (dest / "hpc-run-report" / "SKILL.md").write_text("mine", encoding="utf-8")

    code, out, err = run_cli("skills", "install", str(dest))

    assert code == 1
    assert out == ""
    assert "hpc-run-report" in err
    assert (dest / "hpc-run-report" / "SKILL.md").read_text(encoding="utf-8") == "mine"
    assert not (dest / "hpc-scheduler-output").exists()


def test_force_replaces_the_skill_file_with_the_packaged_bytes(
    run_cli: RunCli, tmp_path: Path
) -> None:
    dest = tmp_path / "skills"
    (dest / "hpc-run-report").mkdir(parents=True)
    (dest / "hpc-run-report" / "SKILL.md").write_text("old", encoding="utf-8")

    code, _, err = run_cli("skills", "install", str(dest), "--force")

    assert code == 0, err
    assert (dest / "hpc-run-report" / "SKILL.md").read_bytes() == _packaged("hpc-run-report")
    assert (dest / "hpc-scheduler-output" / "SKILL.md").read_bytes() == _packaged(
        "hpc-scheduler-output"
    )


def test_a_name_that_leaves_the_destination_exits_2(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    code, _, _ = run_cli("skills", "install", str(dest), "--skill", "../escape")
    assert code == 2
    assert list(tmp_path.glob("escape*")) == []
    assert not (tmp_path / "escape").exists()


def test_a_symlinked_destination_exits_2_and_writes_nothing_behind_it(
    run_cli: RunCli, tmp_path: Path
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link, target_is_directory=True)

    code, _, err = run_cli("skills", "install", str(link))

    assert code == 2
    assert "link" in err
    assert list(real.iterdir()) == []


def test_a_symlinked_skill_folder_is_not_followed(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, dest / "hpc-run-report", target_is_directory=True)

    code, _, _ = run_cli("skills", "install", str(dest), "--force")

    assert code == 2
    assert list(outside.iterdir()) == []


def test_a_symlinked_skill_file_is_not_followed(run_cli: RunCli, tmp_path: Path) -> None:
    dest = tmp_path / "skills"
    (dest / "hpc-run-report").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("untouched", encoding="utf-8")
    os.symlink(outside, dest / "hpc-run-report" / "SKILL.md")

    code, _, _ = run_cli("skills", "install", str(dest), "--skill", "hpc-run-report", "--force")

    assert code == 2
    assert outside.read_text(encoding="utf-8") == "untouched"
