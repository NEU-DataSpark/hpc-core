"""A test-only transport that runs each argument tuple with the host's real commands.

It runs ``env LC_ALL=C dd|find|ln|mv|cat|date|rm|mkdir ...`` as a child process, with standard
input when the caller gives one, a timeout and an output limit. It refuses any absolute path outside
the test folder it was given, so a test cannot touch the rest of the host. It is for the command
store's layer test (L2) and for the self-check's real-command run; it is not a production transport.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..transport.protocol import (
    CommandResult,
    TransportError,
    TransportTimeout,
    check_input,
)


class SubprocessTransport:
    def __init__(self, allowed_root: Path) -> None:
        self._root = str(allowed_root.resolve())

    def _inside(self, argument: str) -> bool:
        candidate = argument.removeprefix("of=")
        if not candidate.startswith("/"):
            return True
        return candidate == self._root or candidate.startswith(self._root + "/")

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
        input: str | None = None,
    ) -> CommandResult:
        check_input(input)
        if not all(self._inside(argument) for argument in argv):
            raise TransportError("the command names a path outside the test folder")
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        try:
            completed = subprocess.run(
                list(argv),
                input=None if input is None else input.encode("utf-8"),
                stdin=None if input is not None else subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            raise TransportTimeout("the command did not finish in time") from None
        except OSError:
            raise TransportError("the command could not be started") from None
        truncated = len(completed.stdout) > max_output_bytes
        stdout = completed.stdout[:max_output_bytes] if truncated else completed.stdout
        return CommandResult(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
            exit_status=completed.returncode,
            truncated=truncated,
        )


def missing_gnu_feature() -> str | None:
    """The first GNU feature the command store needs that this host lacks, or None.

    Checks the programs exist, that ``find -printf`` works and that ``date`` is GNU, so a host with
    BSD or busybox tools gets a skip that names what is missing.
    """
    import shutil

    for program in ("find", "dd", "mv", "ln", "date", "grep"):
        if shutil.which(program) is None:
            return f"the host has no '{program}' command"
    found = subprocess.run(
        ["find", "/", "-maxdepth", "0", "-printf", ""],
        capture_output=True,
        check=False,
    )
    if found.returncode != 0:
        return "find has no -printf (GNU findutils)"
    version = subprocess.run(["date", "--version"], capture_output=True, check=False, text=True)
    if version.returncode != 0 or "GNU" not in version.stdout:
        return "date has no GNU extensions (GNU coreutils)"
    return None
