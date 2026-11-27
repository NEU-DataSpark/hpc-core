"""Public-repository hygiene scan.

Flags cluster home and scratch paths (other than the placeholder account), IPv4 addresses, e-mail
addresses, ``.edu`` host names and private-key headers in the files a public repository ships:
package sources and fixtures, documentation, tools and workflows. It never prints the matched
text, only the file, the line and the rule, so a finding does not leak the value into a log.

The rules are written without the literal text they look for, so this file does not flag itself.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER_ACCOUNT = "exampleuser"

# Each pattern is built from fragments, so this source never holds the text it searches for.
_HOME_PATH = re.compile("/" + "home" + r"/(?!" + PLACEHOLDER_ACCOUNT + r"(?:/|\b))[^\s'\"`]*")
_SCRATCH_PATH = re.compile("/" + "scratch" + "/")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IPV4 = re.compile(r"\b(?:" + _OCTET + r"\.){3}" + _OCTET + r"\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\." + "[A-Za-z]{2,}")
_EDU_HOST = re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\." + "edu" + r"\b", re.IGNORECASE)
_KEY_HEADER = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY" + "-----")

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cluster home path", _HOME_PATH),
    ("cluster scratch path", _SCRATCH_PATH),
    ("IPv4 address", _IPV4),
    ("e-mail address", _EMAIL),
    ("host name under the academic domain", _EDU_HOST),
    ("private key header", _KEY_HEADER),
)

SCANNED_DIRECTORIES: tuple[str, ...] = ("src", "docs", "tools", ".github")
SCANNED_FILES: tuple[str, ...] = ("README.md", "AGENTS.md", "SECURITY.md", "pyproject.toml")
SCANNED_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".csv", ".txt", ".header"}
)
SKIPPED_DIRECTORY_NAMES: frozenset[str] = frozenset({"__pycache__", ".git"})


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str


def scan_text(name: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in RULES:
            if pattern.search(line):
                findings.append(Finding(name, number, rule))
    return findings


def scan_files(paths: Iterable[Path], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            name = path.relative_to(root).as_posix()
        except ValueError:
            name = path.name
        findings.extend(scan_text(name, text))
    return findings


def default_targets(root: Path) -> list[Path]:
    """The files of the public repository this scan covers (not tests, which hold planted

    samples).
    """
    targets: list[Path] = []
    for directory in SCANNED_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or SKIPPED_DIRECTORY_NAMES & set(path.parts):
                continue
            if path.suffix in SCANNED_SUFFIXES or path.name == "py.typed":
                targets.append(path)
    for name in SCANNED_FILES:
        path = root / name
        if path.is_file():
            targets.append(path)
    return targets


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    targets = [Path(arg).resolve() for arg in argv] if argv else default_targets(root)
    findings = scan_files(targets, root)
    for finding in findings:
        print(f"{finding.file}:{finding.line}: {finding.rule}")
    if findings:
        print(f"hygiene scan: {len(findings)} finding(s)")
        return 1
    print(f"hygiene scan: clean ({len(targets)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
