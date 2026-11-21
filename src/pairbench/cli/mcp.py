# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench mcp``: start the tool server for AI agents over standard input and output.

The server needs the ``mcp`` extra. The tools that launch commands on the
machine exist only with ``--allow-run``.
"""

from __future__ import annotations

import argparse
import importlib
from typing import Final

from pairbench.errors import Refusal

SERVER_MODULE: Final = "pairbench.mcp.server"
EXTRA_HINT: Final = "install pairbench[mcp]"
# The module the ``mcp`` extra provides; the server may import it when it starts.
EXTRA_MODULE: Final = "mcp"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``--allow-run`` adds the tools that start and cancel runs."""
    parser.add_argument(
        "--allow-run",
        action="store_true",
        dest="allow_run",
        help="add the tools that start and cancel runs; they launch commands on this machine",
    )
    parser.add_argument("--no-plugins", action="store_true", dest="no_plugins")


def command(options: argparse.Namespace) -> int:
    """Start the server and return its exit code when it stops."""
    from pairbench import registry

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    try:
        server = importlib.import_module(SERVER_MODULE)
    except ImportError as exc:
        raise Refusal(
            "E_USAGE",
            f"the tool server is not available here ({exc.name or 'import'}): {EXTRA_HINT}",
        ) from exc
    start = getattr(server, "main", None)
    if start is None:
        raise Refusal("E_INTERNAL", "the tool server has no entry point")
    try:
        code = start(allow_run=options.allow_run)
    except ImportError as exc:
        if (exc.name or "").partition(".")[0] != EXTRA_MODULE:
            raise
        raise Refusal(
            "E_USAGE", f"the tool server is not available here ({exc.name}): {EXTRA_HINT}"
        ) from exc
    return int(code or 0)


__all__ = ["add_arguments", "command"]
