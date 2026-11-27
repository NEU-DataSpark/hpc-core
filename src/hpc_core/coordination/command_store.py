"""The command store: the folder store over the package's transport, with a fixed command table.

Every operation is one or two argument tuples, each starting ``env LC_ALL=C`` so that error text is
stable English. Content travels on standard input only, never inside an argument, and every path
is built from identifiers that already passed ``layout``. No shell string is built here.

The table (design D4): ``cat`` to read; ``find -printf`` to list with file times; ``date`` for the
observer's time; ``dd`` plus ``mv -f`` to write atomically; ``dd`` plus ``ln`` plus ``rm`` for an
exclusive create; ``mv``, ``rm``, ``mkdir -p`` and ``rm -r -f`` for the rest. A bulk read uses
``find -exec grep -a -H``, because ``cat`` alone cannot say which file a line came from. That is
the one deviation from D4 and is listed in the change notes.
"""

from __future__ import annotations

import threading

from ..transport.protocol import CommandResult, CommandTransport, TransportError, TransportTimeout
from .store import Exists, FileEntry, Listing, NotFound, StoreError, new_token

REQUIRED_COMMANDS: tuple[str, ...] = (
    "cat",
    "date",
    "dd",
    "find",
    "grep",
    "ln",
    "mkdir",
    "mv",
    "rm",
)
DEFAULT_TIMEOUT_SECONDS = 30.0
SMALL_OUTPUT = 1024 * 1024
BULK_OUTPUT = 8 * 1024 * 1024
_NO_SUCH_FILE = "No such file or directory"
_FILE_EXISTS = "File exists"
_LISTING_FORMAT = "%f\\t%T@\\t%s\\n"


class CommandFolderStore:
    """A folder store that reaches one team folder on a login node through a transport."""

    def __init__(
        self,
        transport: CommandTransport,
        root: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not root.startswith("/") or "\n" in root or "\x00" in root:
            raise ValueError("the command store needs an absolute folder path")
        self._transport = transport
        self._root = root.rstrip("/") or "/"
        self._timeout = timeout
        self._checked = False
        self._check_lock = threading.Lock()

    # -- plumbing -----------------------------------------------------------------------------

    def _absolute(self, path: str) -> str:
        relative = "/".join(part for part in path.split("/") if part not in ("", "."))
        if ".." in relative.split("/"):
            raise StoreError("path refused", kind="io")
        return f"{self._root}/{relative}" if self._root != "/" else f"/{relative}"

    def _run(
        self,
        *args: str,
        input: str | None = None,
        max_output: int = SMALL_OUTPUT,
    ) -> CommandResult:
        argv = ("env", "LC_ALL=C", *args)
        # Standard input is passed only when there is some, so a transport written before the
        # input option existed keeps working for every call that needs none.
        extra: dict[str, str] = {} if input is None else {"input": input}
        try:
            result = self._transport.run(
                argv, timeout=self._timeout, max_output_bytes=max_output, **extra
            )
        except (TransportError, TransportTimeout) as error:
            raise StoreError(
                "the login node could not run the folder command", "unreachable"
            ) from error
        if result.truncated:
            raise StoreError("the folder command output was cut short", kind="truncated")
        return result

    def _ensure_commands(self) -> None:
        with self._check_lock:
            if self._checked:
                return
            for program in REQUIRED_COMMANDS:
                result = self._run(program, "--version")
                if result.exit_status != 0:
                    raise StoreError(
                        f"the login node has no '{program}' command the store needs",
                        kind="missing-command",
                    )
            self._checked = True

    @staticmethod
    def _is_missing(result: CommandResult) -> bool:
        return result.exit_status != 0 and _NO_SUCH_FILE in result.stderr

    def _fail(self, what: str, result: CommandResult) -> StoreError:
        del result  # the command's own text can name a path, so it never reaches the caller
        return StoreError(f"{what} failed on the login node", kind="io")

    @staticmethod
    def _parse_listing(text: str) -> tuple[FileEntry, ...]:
        entries: list[FileEntry] = []
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                raise StoreError("the folder listing had an unexpected shape", "unexpected-output")
            name, modified, size = parts
            try:
                entries.append(FileEntry(name, float(modified), int(size)))
            except ValueError:
                raise StoreError(
                    "the folder listing had an unexpected shape", "unexpected-output"
                ) from None
        return tuple(sorted(entries, key=lambda item: item.name))

    def _time(self) -> float:
        result = self._run("date", "+%s.%N")
        if result.exit_status != 0:
            raise self._fail("reading the folder time", result)
        try:
            return float(result.stdout.strip())
        except ValueError:
            raise StoreError("the folder time was not readable", "unexpected-output") from None

    # -- the store interface --------------------------------------------------------------------

    def now(self) -> float:
        self._ensure_commands()
        return self._time()

    def read_text(self, path: str) -> str:
        self._ensure_commands()
        result = self._run("cat", "--", self._absolute(path))
        if self._is_missing(result):
            raise NotFound(path)
        if result.exit_status != 0:
            raise self._fail("reading a file", result)
        return result.stdout

    def write_text(self, path: str, text: str) -> None:
        self._ensure_commands()
        target = self._absolute(path)
        folder = target.rsplit("/", 1)[0]
        temporary = f"{folder}/.tmp-{new_token()}"
        written = self._run("dd", f"of={temporary}", "status=none", input=text)
        if written.exit_status != 0:
            self._remove_quietly(temporary)
            raise self._fail("writing a file", written)
        moved = self._run("mv", "-f", "--", temporary, target)
        if moved.exit_status != 0:
            self._remove_quietly(temporary)
            raise self._fail("replacing a file", moved)

    def create_exclusive(self, path: str, text: str) -> None:
        self._ensure_commands()
        target = self._absolute(path)
        folder = target.rsplit("/", 1)[0]
        temporary = f"{folder}/.tmp-{new_token()}"
        try:
            written = self._run("dd", f"of={temporary}", "status=none", input=text)
            if written.exit_status != 0:
                raise self._fail("writing a file", written)
            linked = self._run("ln", "--", temporary, target)
            if linked.exit_status != 0:
                if _FILE_EXISTS in linked.stderr:
                    raise Exists(path)
                if _NO_SUCH_FILE in linked.stderr:
                    raise NotFound(path)
                raise StoreError("the folder refused a hard link", kind="hard-link-refused")
        finally:
            self._remove_quietly(temporary)

    def list_dir(self, path: str, *, hidden: bool = False) -> Listing:
        self._ensure_commands()
        now = self._time()
        folder = self._absolute(path)
        result = self._run(
            "find", folder, "-maxdepth", "1", "-type", "f", "-printf", _LISTING_FORMAT
        )
        if self._is_missing(result):
            raise NotFound(path)
        if result.exit_status != 0:
            raise self._fail("listing a folder", result)
        entries = tuple(
            entry
            for entry in self._parse_listing(result.stdout)
            if hidden or not entry.name.startswith(".")
        )
        return Listing(entries, now)

    def list_subdirs(self, path: str) -> tuple[str, ...]:
        self._ensure_commands()
        folder = self._absolute(path)
        result = self._run(
            "find", folder, "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-printf", "%f\\n"
        )
        if self._is_missing(result):
            raise NotFound(path)
        if result.exit_status != 0:
            raise self._fail("listing sub-folders", result)
        names = [line for line in result.stdout.splitlines() if line and not line.startswith(".")]
        return tuple(sorted(names))

    def read_all(self, path: str) -> dict[str, str]:
        self._ensure_commands()
        folder = self._absolute(path)
        result = self._run(
            "find",
            folder,
            "-maxdepth",
            "1",
            "-type",
            "f",
            "-exec",
            "grep",
            "-a",
            "-H",
            "",
            "{}",
            "+",
            max_output=BULK_OUTPUT,
        )
        if result.exit_status != 0 and not _only_vanished(result.stderr):
            raise self._fail("reading a folder", result)
        prefix = folder.rstrip("/") + "/"
        texts: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if not line.startswith(prefix):
                raise StoreError("the folder read had an unexpected shape", "unexpected-output")
            name, separator, content = line[len(prefix) :].partition(":")
            if not separator:
                raise StoreError("the folder read had an unexpected shape", "unexpected-output")
            if name.startswith("."):
                continue
            texts[name] = texts.get(name, "") + content + "\n"
        return texts

    def stat(self, path: str) -> FileEntry:
        self._ensure_commands()
        result = self._run(
            "find", self._absolute(path), "-maxdepth", "0", "-printf", _LISTING_FORMAT
        )
        if self._is_missing(result):
            raise NotFound(path)
        if result.exit_status != 0:
            raise self._fail("reading a file's time", result)
        entries = self._parse_listing(result.stdout)
        if len(entries) != 1:
            raise StoreError("the file time was not readable", "unexpected-output")
        return entries[0]

    def move(self, source: str, target: str, *, replace: bool = True) -> None:
        self._ensure_commands()
        origin = self._absolute(source)
        destination = self._absolute(target)
        result = self._run("mv", "-f" if replace else "-n", "--", origin, destination)
        if self._is_missing(result):
            raise NotFound(source)
        if result.exit_status != 0:
            raise self._fail("moving a file", result)
        if not replace:
            # ``mv -n`` exits 0 without moving when the target exists, so the source tells.
            try:
                self.stat(source)
            except NotFound:
                return
            raise Exists(target)

    def remove(self, path: str) -> None:
        self._ensure_commands()
        result = self._run("rm", "-f", "--", self._absolute(path))
        if result.exit_status != 0:
            raise self._fail("removing a file", result)

    def remove_tree(self, path: str) -> None:
        self._ensure_commands()
        result = self._run("rm", "-r", "-f", "--", self._absolute(path))
        if result.exit_status != 0:
            raise self._fail("removing a folder", result)

    def make_dirs(self, path: str) -> None:
        self._ensure_commands()
        result = self._run("mkdir", "-p", "--", self._absolute(path))
        if result.exit_status != 0:
            raise self._fail("creating a folder", result)

    def _remove_quietly(self, path: str) -> None:
        try:
            self._run("rm", "-f", "--", path)
        except StoreError:
            pass


def _only_vanished(stderr: str) -> bool:
    """True when every complaint on standard error is a file removed while it was being read."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    return all(_NO_SUCH_FILE in line for line in lines)
