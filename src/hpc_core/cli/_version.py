"""The installed version of the package, read from its distribution metadata."""

from __future__ import annotations

from importlib import metadata

DISTRIBUTION = "hpc-core"


def package_version() -> str:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return "unknown"
