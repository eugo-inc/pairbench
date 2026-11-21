# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench report``: render a results file.

The report is printed on standard output. ``--case`` and ``--all`` filter
what is shown, never what was tested. The diagnostics document of the same
folder, when there is one, is handed to the reporter; the JSON report, which
does not show it, does not read it unless charts are drawn. ``--plots`` draws the
charts again from the results and the diagnostics into the folder; the
report printed then names them. The results file itself is not changed.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

from pairbench.cli.common import CHOICES, emit, relative_to
from pairbench.errors import EXIT_OK
from pairbench.model import FILE_DIAGNOSTICS, PlotsState

FORMATS = ("terminal", "markdown", "json", "html")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The results file, the format, the display filters and ``--plots``."""
    parser.add_argument("results", metavar="RESULTS", help="a results.json file")
    parser.add_argument("--format", choices=FORMATS, default="terminal")
    parser.add_argument("--case", action="append", default=[], metavar="GLOB")
    parser.add_argument("--all", action="store_true", dest="all_cases", help="show every case")
    parser.add_argument("--verbose", action="store_true", help="add each side's own floor")
    parser.add_argument(
        "--plots",
        choices=CHOICES["--plots"],
        default="off",
        help="draw the charts again into the folder of the results",
    )
    parser.add_argument("--no-plugins", action="store_true", dest="no_plugins")


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench report``."""
    import pairbench
    from pairbench import api, registry
    from pairbench.api import ReportOptions

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    path = Path(options.results)
    results = pairbench.load_results(path)
    folder = path.parent
    diagnostics_file = folder / FILE_DIAGNOSTICS
    used = options.format != "json" or options.plots != "off"
    diagnostics = (
        pairbench.load_diagnostics(diagnostics_file)
        if used and diagnostics_file.is_file()
        else None
    )
    if options.plots != "off":
        api.require_plot_extra(options.plots)
        paths = pairbench.draw(results, out=folder, diagnostics=diagnostics)
        if paths:
            results = dataclasses.replace(
                results,
                plots=PlotsState(status="drawn"),
                artifacts=dataclasses.replace(results.artifacts, charts=relative_to(folder, paths)),
            )
    shown = ReportOptions(
        cases=tuple(options.case), all_cases=options.all_cases, verbose=options.verbose
    )
    text = pairbench.render(
        results, options.format, diagnostics=diagnostics, folder=folder, options=shown
    )
    emit(text)
    return EXIT_OK


__all__ = ["FORMATS", "add_arguments", "command"]
