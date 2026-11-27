# Consumer contract test

The test kit checks a consumer's reader and writer against the golden run reports. Both consumers
run it in their own test suites, so a change that breaks the contract fails in the consumer, with
the name of the case.

## Pinned install

Install a tagged release and pin it. Replace `X.Y.Z` with a tag that exists in the repository:

```bash
python -m pip install "hpc-core @ git+https://github.com/NEU-DataSpark/hpc-core.git@vX.Y.Z"
```

The golden reports ship in the wheel under `hpc_core/testing/fixtures/reports/`. The kit needs no
third-party package.

## Reader check

A reader is any function `text -> (rows, skipped)`. Each row maps a column name to its canonical
cell text, the way `hpc_core.contract.report.format_row` writes it. A reader may raise instead, for
a refused report. The check passes when the reader returns the golden cells and skipped count for
every accepted case, and refuses the refused case with the expected message.

The console runs its own reader against the golden reports:

```python
from hpc_core.testing import check_reader

from consumer_standins import standin_reader  # in the console: its own report reader

assert check_reader(standin_reader) == 7
```

`check_reader` returns the number of cases it checked. A failure raises `ContractFailure`, and its
message starts with the case name, for example `zero_beside_blank: returned cells differ from the
golden values`.

## Writer check

A writer is any function that takes the canonical samples and returns CSV text. The check passes
when the bytes it produces equal the canonical golden file, `finished_run.csv`.

The operator runs its own writer against the canonical samples:

```python
from hpc_core.testing import check_writer

from consumer_standins import standin_writer  # in the operator: its own report writer

check_writer(standin_writer)
```

A writer that reorders the columns fails with a message that names `finished_run` and the first
line that differs.

## Stand-ins in the test suite

`tests/consumer_standins.py` holds a stand-in reader and writer. They are written apart from the
package's own code, so a pass means the checks accept an independent implementation of the same
contract. `tests/test_docs_examples.py` runs the two examples above against them.

## Adding a golden case

1. Add the CSV and its expected-value JSON under `src/hpc_core/testing/fixtures/reports/`, with a
   header comment.
2. Run the package's own reader against it, and check the expected values by hand.
3. Run the consumer's check; it picks up the new case without a code change.
