# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Run the command line with ``python -m pairbench``."""

from __future__ import annotations


def run() -> int:
    """Run the command line and return its exit code."""
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
