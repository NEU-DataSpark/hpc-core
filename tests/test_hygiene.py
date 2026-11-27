"""Public-repository hygiene: the shipped files hold no cluster path, address, e-mail or key."""

from __future__ import annotations

from pathlib import Path

from hygiene_scan import default_targets, scan_files, scan_text

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_files_are_clean() -> None:
    findings = scan_files(default_targets(ROOT), ROOT)
    assert findings == [], findings


def test_planted_scratch_path_fails_with_file_and_line(tmp_path: Path) -> None:
    planted = tmp_path / "docs" / "note.md"
    planted.parent.mkdir()
    planted.write_text("first line\nsee /scratch/a/b for the data\n", encoding="utf-8")
    findings = scan_files([planted], tmp_path)
    assert [(f.file, f.line, f.rule) for f in findings] == [
        ("docs/note.md", 2, "cluster scratch path")
    ]


def test_planted_address_and_email_fail() -> None:
    text = "connect to 10.20.30.40 or write to someone@mail.example\n"
    rules = {finding.rule for finding in scan_text("docs/x.md", text)}
    assert {"IPv4 address", "e-mail address"} <= rules


def test_planted_key_header_fails() -> None:
    header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    findings = scan_text("src/x.py", f"x = '''\n{header}\n'''\n")
    assert [(f.line, f.rule) for f in findings] == [(2, "private key header")]


def test_edu_host_name_fails() -> None:
    findings = scan_text("docs/x.md", "login at login.cluster.example.edu today\n")
    assert [f.rule for f in findings] == ["host name under the academic domain"]


def test_placeholder_account_path_is_allowed() -> None:
    assert scan_text("docs/x.md", "use /home/exampleuser/project\n") == []


def test_other_account_path_fails() -> None:
    findings = scan_text("docs/x.md", "use /home/someone/project\n")
    assert [f.rule for f in findings] == ["cluster home path"]


def test_removing_the_planted_text_passes(tmp_path: Path) -> None:
    planted = tmp_path / "docs" / "note.md"
    planted.parent.mkdir()
    planted.write_text("see /scratch/a/b\n", encoding="utf-8")
    assert scan_files([planted], tmp_path)
    planted.write_text("see the shared data area\n", encoding="utf-8")
    assert scan_files([planted], tmp_path) == []
