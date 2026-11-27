"""Build the wheel, install it in a fresh directory and check the loader finds every fixture."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from check_wheel import missing_entries

from hpc_core.testing.fixtures import KINDS, load_cases

REPO = Path(__file__).resolve().parent.parent

_LOADER_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
import hpc_core
from hpc_core.testing.fixtures import KINDS, load_cases
cases = [[case.kind, case.name] for kind in KINDS for case in load_cases(kind)]
print(json.dumps({"module": hpc_core.__file__, "cases": cases}))
"""


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(out), str(REPO)],
        check=True,
        timeout=600,
    )
    wheels = sorted(out.glob("hpc_core-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_wheel_carries_fixtures_py_typed_and_license_files(built_wheel: Path) -> None:
    import zipfile

    with zipfile.ZipFile(built_wheel) as archive:
        assert missing_entries(archive.namelist()) == []


def test_installed_loader_finds_every_fixture_the_repository_has(
    built_wheel: Path, tmp_path: Path
) -> None:
    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "-q",
            "--target",
            str(target),
            str(built_wheel),
        ],
        check=True,
        timeout=600,
    )
    # -I ignores the environment and the working directory, so only the installed copy is found.
    run = subprocess.run(
        [sys.executable, "-I", "-c", _LOADER_SCRIPT, str(target)],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
    )
    report = json.loads(run.stdout)
    assert str(target) in report["module"]

    expected = sorted([case.kind, case.name] for kind in KINDS for case in load_cases(kind))
    assert sorted(report["cases"]) == expected
    assert len(expected) >= 16
