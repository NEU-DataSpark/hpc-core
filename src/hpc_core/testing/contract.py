"""Contract checks a consumer runs against its own reader and writer.

``check_reader`` compares the cells a consumer's reader returns with the golden values, with the
real zero kept and blanks kept blank. It takes two kinds of reader, either or both:

- a whole-report reader, ``text -> (rows, skipped)``, run on every report case;
- a per-job reader, ``(job_id, text) -> (rows, skipped)``, which returns the rows of one job. It is
  run once for each job ID a case lists, and must return exactly that job's rows.

Each row maps a column name to its canonical cell text (see
``hpc_core.contract.report.format_row``). A reader may raise instead, for a refused report.

``check_writer`` gives the writer the canonical samples and compares the bytes it produces with the
golden file. Each failure names the case, and for a per-job run the job ID, so the consumer's test
output says which contract it broke. A writer is any callable taking the canonical samples and
returning CSV text.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from itertools import zip_longest

from ..contract.report import COLUMNS, ReportRow, format_report, format_row, read_report
from ..coordination.store import Exists, FolderStore, NotFound, StoreError
from .fixtures import Case, load_case, load_cases

CANONICAL_CASE = "finished_run"

ReaderOutput = tuple[list[dict[str, str]], int]
Reader = Callable[[str], ReaderOutput]
JobReader = Callable[[str, str], ReaderOutput]
Writer = Callable[[Sequence[ReportRow]], str]


class ContractFailure(AssertionError):
    """A consumer's reader or writer disagrees with a golden case. The message names the case."""


def package_reader(text: str) -> ReaderOutput:
    """The package's own reader, in the canonical cell form the checks compare."""
    result = read_report(text)
    rows = [dict(zip(COLUMNS, format_row(row), strict=True)) for row in result.rows]
    return rows, result.skipped


def package_writer(samples: Sequence[ReportRow]) -> str:
    return format_report(samples)


def canonical_samples() -> tuple[ReportRow, ...]:
    """The rows of the canonical golden case, as the package reads them."""
    return read_report(load_case("report", CANONICAL_CASE).text).rows


def _report_cases(cases: Iterable[Case] | None) -> list[Case]:
    chosen = load_cases("report") if cases is None else list(cases)
    return [case for case in chosen if case.kind == "report"]


def _check_read(name: str, expected: dict[str, object], reader: Reader, text: str) -> None:
    try:
        rows, skipped = reader(text)
    except Exception as error:
        if expected.get("outcome") == "refused" and str(expected.get("error_contains", "")) in str(
            error
        ):
            return
        raise ContractFailure(f"{name}: reader refused the report: {error}") from error
    if expected.get("outcome") != "read":
        raise ContractFailure(f"{name}: reader accepted a report that must be refused")
    if skipped != expected["skipped"]:
        raise ContractFailure(f"{name}: skipped {skipped} rows, expected {expected['skipped']}")
    if [dict(row) for row in rows] != expected["rows"]:
        raise ContractFailure(f"{name}: returned cells differ from the golden values")


def _check_job(case: Case, job_id: str, job_reader: JobReader) -> None:
    label = f"{case.name}[job {job_id}]"
    try:
        rows, skipped = job_reader(job_id, case.text)
    except Exception as error:
        raise ContractFailure(f"{label}: job reader raised: {error}") from error
    if any(row.get("job_id") != job_id for row in rows):
        raise ContractFailure(f"{label}: reader returned a row of another job")
    if skipped != 0:
        raise ContractFailure(f"{label}: skipped {skipped} rows, expected 0")
    expected = [dict(row) for row in case.expected["rows"] if row["job_id"] == job_id]
    if [dict(row) for row in rows] != expected:
        raise ContractFailure(f"{label}: returned cells differ from the golden values")


def check_reader(
    reader: Reader | None = None,
    cases: Iterable[Case] | None = None,
    *,
    job_reader: JobReader | None = None,
) -> int:
    """Run the given readers over the report cases. Returns the number of cases checked.

    The whole-report reader runs on every case. The per-job reader runs once for each job ID a
    case lists, and only such a case is checked that way. A case counts when at least one reader
    ran on it. At least one of the two readers is required.
    """
    if reader is None and job_reader is None:
        raise ValueError("check_reader needs a whole-report reader, a per-job reader, or both")
    checked = 0
    for case in _report_cases(cases):
        ran = False
        if reader is not None:
            _check_read(case.name, case.expected, reader, case.text)
            ran = True
        if job_reader is not None:
            for job_id in case.expected.get("job_ids", []):
                _check_job(case, job_id, job_reader)
                ran = True
        if ran:
            checked += 1
    return checked


def check_writer(writer: Writer, samples: Sequence[ReportRow] | None = None) -> None:
    """The writer's bytes for the canonical samples must equal the canonical golden file."""
    golden = load_case("report", CANONICAL_CASE).text
    produced = writer(canonical_samples() if samples is None else samples)
    if produced != golden:
        first = next(
            (
                number
                for number, (left, right) in enumerate(
                    zip_longest(produced.splitlines(), golden.splitlines()), 1
                )
                if left != right
            ),
            None,
        )
        where = f" (first difference on line {first})" if first is not None else ""
        raise ContractFailure(
            f"{CANONICAL_CASE}: writer output differs from the golden file{where}"
        )


# -- folder store conformance ------------------------------------------------------------------

_STORE_ROOT = "_cluster/nodes"


def run_store_script(store: FolderStore) -> list[object]:
    """Run the fixed store script and return one ``(step, result)`` pair per step.

    File times and clocks are left out, because they differ between stores; names, texts and the
    outcomes ``not-found``, ``exists`` and ``store-error`` must match on every store.
    """
    results: list[object] = []

    def attempt(label: str, action: Callable[[], object]) -> None:
        try:
            results.append((label, action()))
        except NotFound:
            results.append((label, "not-found"))
        except Exists:
            results.append((label, "exists"))
        except StoreError:
            results.append((label, "store-error"))

    folder = _STORE_ROOT
    attempt("mkdir", lambda: store.make_dirs(folder))
    attempt("write-a", lambda: store.write_text(f"{folder}/a.json", "A\n"))
    attempt("read-a", lambda: store.read_text(f"{folder}/a.json"))
    attempt("read-missing", lambda: store.read_text(f"{folder}/missing.json"))
    attempt("create-a-again", lambda: store.create_exclusive(f"{folder}/a.json", "X\n"))
    attempt("create-b", lambda: store.create_exclusive(f"{folder}/b.json", "B\n"))
    attempt("list", lambda: [e.name for e in store.list_dir(folder).entries])
    attempt("read-all", lambda: store.read_all(folder))
    attempt(
        "move-no-replace",
        lambda: store.move(f"{folder}/b.json", f"{folder}/a.json", replace=False),
    )
    attempt("move", lambda: store.move(f"{folder}/b.json", f"{folder}/c.json"))
    attempt("list-after-move", lambda: [e.name for e in store.list_dir(folder).entries])
    attempt("remove-c", lambda: store.remove(f"{folder}/c.json"))
    attempt("remove-c-again", lambda: store.remove(f"{folder}/c.json"))
    attempt("list-missing", lambda: store.list_dir("_cluster/absent"))
    attempt("subdirs", lambda: list(store.list_subdirs("_cluster")))
    attempt("remove-tree", lambda: store.remove_tree(folder))
    attempt("list-after-tree", lambda: store.list_dir(folder))
    return results


def check_store_conformance(store: FolderStore) -> None:
    """Raise ContractFailure unless ``store`` gives the reference results of the store script.

    The reference is a fresh in-memory folder store. A consumer runs this against its own store
    (a mounted folder, a remote command store) to see that it keeps the protocol's rules.
    """
    from .memory_store import MemoryFolderStore

    expected = run_store_script(MemoryFolderStore())
    actual = run_store_script(store)
    for number, (want, got) in enumerate(zip_longest(expected, actual), 1):
        if want != got:
            raise ContractFailure(f"store step {number} differs: expected {want!r}, got {got!r}")
