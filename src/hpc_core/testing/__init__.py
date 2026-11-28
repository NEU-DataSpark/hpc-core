"""Test kit for consumers: anonymised fixtures, golden run-reports, contract checks and a fake

transport.
"""

from .contract import (
    ContractFailure,
    JobReader,
    canonical_samples,
    check_reader,
    check_store_conformance,
    check_writer,
    package_reader,
    package_writer,
    run_store_script,
)
from .fake_transport import FakeTransport, SimulatedFolderTransport
from .fault_store import FaultyFolderStore
from .fixtures import load_case, load_cases
from .memory_store import ManualClock, MemoryFolderStore
from .subprocess_transport import SubprocessTransport
from .wire_examples import REFERENCE_WIRE_CODEC, WireCodec, check_wire_conformance

__all__ = [
    "ContractFailure",
    "FakeTransport",
    "FaultyFolderStore",
    "JobReader",
    "ManualClock",
    "MemoryFolderStore",
    "REFERENCE_WIRE_CODEC",
    "SimulatedFolderTransport",
    "SubprocessTransport",
    "WireCodec",
    "canonical_samples",
    "check_reader",
    "check_store_conformance",
    "check_wire_conformance",
    "check_writer",
    "load_case",
    "load_cases",
    "package_reader",
    "package_writer",
    "run_store_script",
]
