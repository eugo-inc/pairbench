# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench profile``: record a profile with a profiler you installed yourself.

``pairbench profile --from results.json --tool nsys|ncu|perf [--case CASE] [--side NAME]``

The run folder is the folder of the results file. ``nsys`` and ``ncu`` run
one untimed launch per side under the GPU profiler; ``perf`` records stacks
as the explain step does. The files written are listed under
``artifacts.profiles`` of the results, which are written again with that
list and nothing else changed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pairbench.cli.common import emit
from pairbench.errors import EXIT_OK


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``--from``, ``--tool``, ``--case`` and ``--side``."""
    from pairbench.api import PROFILE_TOOLS

    parser.add_argument(
        "--from", dest="source", required=True, metavar="RESULTS", help="the run's results.json"
    )
    parser.add_argument("--tool", required=True, choices=tuple(PROFILE_TOOLS))
    parser.add_argument("--case", metavar="CASE", help="the case to profile")
    parser.add_argument("--side", metavar="NAME", help="one side; every subject and the baseline")
    parser.add_argument("--no-plugins", action="store_true", dest="no_plugins")


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench profile``; the files written are printed, one per line."""
    import pairbench
    from pairbench import api, registry
    from pairbench.api import WriteResults, delegate

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    source = Path(options.source)
    results = pairbench.load_results(source)
    run_dir = source.parent
    record = delegate(api.PROFILE_TOOLS[options.tool])
    files: tuple[str, ...] = tuple(
        record(run_dir, tool=options.tool, case=options.case, side=options.side)
    )
    listed = tuple(dict.fromkeys((*results.artifacts.profiles, *files)))
    write_results: WriteResults = delegate("write_results")
    write_results(results, run_dir, profiles=listed)
    if files:
        emit("\n".join(files))
    return EXIT_OK


__all__ = ["add_arguments", "command"]
