"""The docs stay true: every python block runs as written, and the run-report document lists the
package's columns."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hpc_core.contract.report import COLUMNS

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
EXECUTED_DOCS = ("parsing.md", "run-report-contract.md", "adapter.md", "consumer-contract-test.md")
_PYTHON_BLOCK = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)
_TEXT_BLOCK = re.compile(r"^```text\n(.*?)^```", re.MULTILINE | re.DOTALL)


@pytest.mark.parametrize("name", EXECUTED_DOCS)
def test_every_python_block_runs_as_written(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(REPO / "tests"))
    blocks = _PYTHON_BLOCK.findall((DOCS / name).read_text(encoding="utf-8"))
    assert blocks, f"{name} has no python example"
    namespace: dict[str, object] = {"__name__": f"docs_{name}"}
    for number, block in enumerate(blocks, 1):
        exec(compile(block, f"{name}#block{number}", "exec"), namespace)


def test_run_report_document_lists_the_package_columns() -> None:
    text = (DOCS / "run-report-contract.md").read_text(encoding="utf-8")
    section = text.split("## Columns", 1)[1]
    block = _TEXT_BLOCK.search(section)
    assert block is not None, "the Columns section has no text block"
    listed = [line.strip() for line in block.group(1).splitlines() if line.strip()]
    assert listed == list(COLUMNS)


def test_consumer_examples_name_the_stand_in_modules() -> None:
    text = (DOCS / "consumer-contract-test.md").read_text(encoding="utf-8")
    assert "from consumer_standins import standin_reader" in text
    assert "from consumer_standins import standin_writer" in text
