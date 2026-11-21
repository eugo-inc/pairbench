# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench schema``: print a shipped JSON Schema."""

from __future__ import annotations

import argparse

from pairbench.cli.common import emit
from pairbench.errors import EXIT_OK

NAMES = ("capture", "results", "config", "diagnostics")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The name of the schema."""
    parser.add_argument("name", choices=NAMES, help="which schema to print")


def command(options: argparse.Namespace) -> int:
    """Print the schema on standard output."""
    from pairbench.results import schema_text

    emit(schema_text(options.name))
    return EXIT_OK


__all__ = ["NAMES", "add_arguments", "command"]
