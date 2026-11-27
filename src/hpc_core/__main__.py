"""Run the command line as ``python -m hpc_core``; the same code as the ``hpc-core`` command."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
