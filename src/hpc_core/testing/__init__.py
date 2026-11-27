"""Test kit for consumers: anonymised fixtures, golden run-reports, contract checks and a fake

transport.
"""

from .contract import (
    ContractFailure,
    canonical_samples,
    check_reader,
    check_writer,
    package_reader,
    package_writer,
)
from .fake_transport import FakeTransport
from .fixtures import load_case, load_cases

__all__ = [
    "ContractFailure",
    "FakeTransport",
    "canonical_samples",
    "check_reader",
    "check_writer",
    "load_case",
    "load_cases",
    "package_reader",
    "package_writer",
]
