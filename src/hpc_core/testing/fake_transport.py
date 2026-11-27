"""An in-memory transport that replays recorded results. No network, no credentials."""

from __future__ import annotations

from collections.abc import Mapping

from ..coordination.store import Exists, NotFound, StoreError
from ..transport.protocol import CommandResult, TransportError, TransportTimeout, check_input
from .memory_store import MemoryFolderStore

Reply = CommandResult | TransportTimeout | TransportError


def program_of(argv: tuple[str, ...]) -> str:
    """The program a command runs, skipping a leading ``env`` and its ``NAME=value`` settings."""
    rest = argv
    if rest[:1] == ("env",):
        index = 1
        while index < len(rest) and "=" in rest[index]:
            index += 1
        rest = rest[index:]
    return rest[0] if rest else ""


class FakeTransport:
    """Replays one reply per program (``squeue``, ``sacct``, ...) and records every call.

    A reply is a CommandResult, returned as is, or an error, raised. A program with no reply raises
    TransportError, so a test cannot pass by accident. Output over ``max_output_bytes`` is cut and
    marked truncated, as a real transport would do. Standard input is recorded in ``inputs``,
    parallel to ``calls``, and never appears in an argument.
    """

    def __init__(self, replies: Mapping[str, Reply]) -> None:
        self._replies = dict(replies)
        self.calls: list[tuple[str, ...]] = []
        self.inputs: list[str | None] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
        input: str | None = None,
    ) -> CommandResult:
        check_input(input)
        self.calls.append(argv)
        self.inputs.append(input)
        reply = self._replies.get(program_of(argv))
        if reply is None:
            raise TransportError("no recorded reply for this command")
        if isinstance(reply, BaseException):
            raise reply
        encoded = reply.stdout.encode("utf-8")
        if reply.truncated or len(encoded) <= max_output_bytes:
            return reply
        cut = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
        return CommandResult(
            stdout=cut, stderr=reply.stderr, exit_status=reply.exit_status, truncated=True
        )


class SimulatedFolderTransport:
    """A transport that answers the command store's fixed table from a ``MemoryFolderStore``.

    It understands exactly the argument tuples of ``coordination.command_store`` (after ``env
    LC_ALL=C``) and answers them with the same exit statuses and English messages GNU tools use,
    so the command store's mapping is exercised without a shell or a host folder. ``root`` is the
    absolute folder the simulated store lives under. ``fail_next`` queues transport errors that the
    next calls raise, to test a dropped connection.
    """

    def __init__(self, folder: MemoryFolderStore, root: str) -> None:
        self._folder = folder
        self._root = root.rstrip("/")
        self.calls: list[tuple[str, ...]] = []
        self.inputs: list[str | None] = []
        self.fail_next: list[TransportError | TransportTimeout] = []

    def _relative(self, absolute: str) -> str | None:
        if absolute == self._root:
            return ""
        if absolute.startswith(self._root + "/"):
            return absolute[len(self._root) + 1 :]
        return None

    def _missing(self, what: str, path: str) -> CommandResult:
        return CommandResult("", f"{what}: '{path}': No such file or directory\n", 1)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout: float,
        max_output_bytes: int,
        input: str | None = None,
    ) -> CommandResult:
        check_input(input)
        self.calls.append(argv)
        self.inputs.append(input)
        if self.fail_next:
            raise self.fail_next.pop(0)
        args = list(argv[2:]) if argv[:2] == ("env", "LC_ALL=C") else list(argv)
        if argv[:2] != ("env", "LC_ALL=C"):
            raise TransportError("simulated folder commands need the LC_ALL=C prefix")
        result = self._dispatch(args, input)
        return _cut(result, max_output_bytes)

    def _dispatch(self, args: list[str], input: str | None) -> CommandResult:
        program, rest = args[0], args[1:]
        if rest == ["--version"]:
            return CommandResult("simulated\n", "", 0)
        if program == "date":
            return CommandResult(f"{self._folder.now():.9f}\n", "", 0)
        if program == "cat":
            path = self._relative(rest[-1])
            if path is None or not self._exists_file(path):
                return CommandResult("", f"cat: '{rest[-1]}': No such file or directory\n", 1)
            return CommandResult(self._folder.read_text(path), "", 0)
        if program == "find":
            return self._find(rest)
        if program == "dd":
            target = rest[0].removeprefix("of=")
            path = self._relative(target)
            if path is None or input is None:
                return CommandResult("", "dd: failed to open the output\n", 1)
            try:
                self._folder.write_text(path, input)
            except StoreError:
                return CommandResult("", "dd: failed to open the output\n", 1)
            return CommandResult("", "", 0)
        if program == "mv":
            return self._mv(rest)
        if program == "ln":
            return self._ln(rest)
        if program == "rm":
            return self._rm(rest)
        if program == "mkdir":
            path = self._relative(rest[-1])
            if path is None:
                return CommandResult("", "mkdir: cannot create directory\n", 1)
            self._folder.make_dirs(path)
            return CommandResult("", "", 0)
        return CommandResult("", f"{program}: not simulated\n", 127)

    def _exists_file(self, path: str) -> bool:
        try:
            self._folder.stat(path)
        except NotFound:
            return False
        return True

    def _find(self, rest: list[str]) -> CommandResult:
        folder = self._relative(rest[0])
        if folder is None:
            return self._missing("find", rest[0])
        if "-maxdepth" in rest and rest[rest.index("-maxdepth") + 1] == "0":
            if not self._exists_file(folder):
                return self._missing("find", rest[0])
            entry = self._folder.stat(folder)
            return CommandResult(f"{entry.name}\t{entry.modified:.9f}\t{entry.size}\n", "", 0)
        if "-exec" in rest:
            return self._grep(folder, rest[0])
        if "-type" in rest and rest[rest.index("-type") + 1] == "d":
            try:
                names = self._folder.list_subdirs(folder)
            except NotFound:
                return self._missing("find", rest[0])
            return CommandResult("".join(f"{name}\n" for name in names), "", 0)
        try:
            listing = self._folder.list_dir(folder, hidden=True)
        except NotFound:
            return self._missing("find", rest[0])
        lines = "".join(
            f"{entry.name}\t{entry.modified:.9f}\t{entry.size}\n" for entry in listing.entries
        )
        return CommandResult(lines, "", 0)

    def _grep(self, folder: str, absolute: str) -> CommandResult:
        try:
            listing = self._folder.list_dir(folder, hidden=True)
        except NotFound:
            return self._missing("find", absolute)
        out: list[str] = []
        for entry in listing.entries:
            text = self._folder.read_text(f"{folder}/{entry.name}")
            for line in text.splitlines():
                out.append(f"{absolute.rstrip('/')}/{entry.name}:{line}\n")
        return CommandResult("".join(out), "", 0)

    def _mv(self, rest: list[str]) -> CommandResult:
        replace = rest[0] == "-f"
        source, target = rest[-2], rest[-1]
        origin, destination = self._relative(source), self._relative(target)
        if origin is None or not self._exists_file(origin):
            return CommandResult("", f"mv: cannot stat '{source}': No such file or directory\n", 1)
        if destination is None:
            return CommandResult("", "mv: cannot move into the folder\n", 1)
        if not replace and self._exists_file(destination):
            return CommandResult("", "", 0)
        try:
            self._folder.move(origin, destination, replace=True)
        except StoreError:
            return CommandResult("", "mv: cannot move\n", 1)
        return CommandResult("", "", 0)

    def _ln(self, rest: list[str]) -> CommandResult:
        source, target = rest[-2], rest[-1]
        origin, destination = self._relative(source), self._relative(target)
        if origin is None or not self._exists_file(origin) or destination is None:
            return CommandResult("", "ln: No such file or directory\n", 1)
        try:
            self._folder.create_exclusive(destination, self._folder.read_text(origin))
        except Exists:
            return CommandResult(
                "", f"ln: failed to create hard link '{source}' => '{target}': File exists\n", 1
            )
        except StoreError:
            return CommandResult("", "ln: failed to create hard link\n", 1)
        return CommandResult("", "", 0)

    def _rm(self, rest: list[str]) -> CommandResult:
        recursive = "-r" in rest
        path = self._relative(rest[-1])
        if path is None:
            return CommandResult("", "", 0)
        if recursive:
            self._folder.remove_tree(path)
        else:
            self._folder.remove(path)
        return CommandResult("", "", 0)


def _cut(result: CommandResult, max_output_bytes: int) -> CommandResult:
    if result.truncated:
        return result
    encoded = result.stdout.encode("utf-8")
    if len(encoded) <= max_output_bytes:
        return result
    cut = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
    return CommandResult(
        stdout=cut, stderr=result.stderr, exit_status=result.exit_status, truncated=True
    )
