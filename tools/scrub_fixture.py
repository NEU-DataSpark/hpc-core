"""Anonymise a recording of scheduler output.

Reads the recording from standard input and writes the scrubbed text to standard output. The real
values are given as run-time arguments and are never stored in the repository:

    --account NAME               the real account; replaced by the placeholder account
    --partition REAL=PLACEHOLDER a real partition name and its placeholder (repeatable)
    --job-id ID                  a real base job id (digits); replaced by a sequential id
                                 (its _<index> suffix is kept; repeatable)
    --replace REAL=PLACEHOLDER   any other real value, such as a job name (repeatable)
    --base-date YYYY-MM-DD       the date the earliest time in the recording is moved to

Times are shifted by one constant, so their order and spacing are kept. The recording must have been
taken with TZ=UTC. Before writing, the tool checks that no real value survives; if one does, it
writes nothing and exits with status 2, naming the value's kind but never the value.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime

PLACEHOLDER_ACCOUNT = "exampleuser"
FIRST_PLACEHOLDER_JOB_ID = 100001
DEFAULT_BASE_DATE = date(2026, 1, 5)
_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\b")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
_NAME_CHARACTERS = r"A-Za-z0-9_.\-"
_BASE_JOB_ID = re.compile(r"[0-9]+(?:_[0-9]+)?")


class ScrubError(RuntimeError):
    """The recording cannot be scrubbed safely. The message never contains a real value."""


def _whole_token(value: str) -> re.Pattern[str]:
    return re.compile(
        r"(?<![" + _NAME_CHARACTERS + r"])" + re.escape(value) + r"(?![" + _NAME_CHARACTERS + r"])"
    )


def _whole_job_id(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<![0-9])" + re.escape(value) + r"(?![0-9])")


def _shift_times(text: str, base: datetime) -> str:
    stamps = [datetime.strptime(match.group(0), _TIME_FORMAT) for match in _TIME.finditer(text)]
    if not stamps:
        return text
    shift = base - min(stamps)

    def move(match: re.Match[str]) -> str:
        moved = datetime.strptime(match.group(0), _TIME_FORMAT) + shift
        return moved.strftime(_TIME_FORMAT)

    return _TIME.sub(move, text)


def scrub(
    text: str,
    *,
    account: str,
    partitions: dict[str, str],
    job_ids: Sequence[str],
    replacements: dict[str, str],
    base_date: date = DEFAULT_BASE_DATE,
) -> str:
    """Return the scrubbed text. Raises ScrubError when a real value would survive."""
    real_values: list[tuple[str, re.Pattern[str]]] = []
    result = text

    # Give the base job id; an array suffix (_3) is left in place, so array tasks keep their shape.
    id_map: dict[str, str] = {}
    for job_id in job_ids:
        base = job_id.partition("_")[0]
        if _BASE_JOB_ID.fullmatch(job_id) is None:
            raise ScrubError("job id must be digits, optionally with an _<index> suffix")
        if base not in id_map:
            id_map[base] = str(FIRST_PLACEHOLDER_JOB_ID + len(id_map))
        real_values.append(("job id", _whole_job_id(base)))
    for base, placeholder in id_map.items():
        result = _whole_job_id(base).sub(placeholder, result)

    if account:
        real_values.append(("account", _whole_token(account)))
        result = _whole_token(account).sub(PLACEHOLDER_ACCOUNT, result)
    for real, placeholder in partitions.items():
        real_values.append(("partition", _whole_token(real)))
        result = _whole_token(real).sub(placeholder, result)
    for real, placeholder in replacements.items():
        real_values.append(("replaced value", _whole_token(real)))
        result = _whole_token(real).sub(placeholder, result)

    midnight = datetime(base_date.year, base_date.month, base_date.day)
    result = _shift_times(result, midnight)

    for kind, pattern in real_values:
        if pattern.search(result):
            raise ScrubError(f"a real {kind} survives the scrub; nothing was written")
    return result


def _pairs(values: Sequence[str], option: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        real, separator, placeholder = value.partition("=")
        if not separator or not real or not placeholder:
            raise ScrubError(f"{option} needs REAL=PLACEHOLDER")
        pairs[real] = placeholder
    return pairs


def main(argv: Sequence[str] | None = None, stdin: str | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anonymise a scheduler recording read from standard input."
    )
    parser.add_argument("--account", default="", help="the real account name")
    parser.add_argument("--partition", action="append", default=[], metavar="REAL=PLACEHOLDER")
    parser.add_argument("--job-id", action="append", default=[], metavar="ID")
    parser.add_argument("--replace", action="append", default=[], metavar="REAL=PLACEHOLDER")
    parser.add_argument("--base-date", type=date.fromisoformat, default=DEFAULT_BASE_DATE)
    args = parser.parse_args(argv)
    text = stdin if stdin is not None else sys.stdin.read()
    try:
        scrubbed = scrub(
            text,
            account=args.account,
            partitions=_pairs(args.partition, "--partition"),
            job_ids=list(args.job_id),
            replacements=_pairs(args.replace, "--replace"),
            base_date=args.base_date,
        )
    except ScrubError as error:
        print(f"scrub_fixture: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(scrubbed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
