# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench compare``: analyse or pool captures, or compare result files from other tools.

Captures are named as arguments; each file may hold several runs, and all
of them are pooled. Result files of other tools are sides of kind ``file``
(``--side NAME=file:GLOB``, with ``--driver``, and ``--levels`` for a
driver that reads a result file as one load level): they are read into a
run folder, launching nothing, and analysed. The results say ``off`` for the
explain step and the charts, which ``compare`` never runs. When it writes
results files or prints the results document, also those of a refusal, it
prints the note on what the shared files show of the command, as ``run``
does.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pairbench.cli.common import CHOICES, emit, fail_on_code, one_baseline, print_command_note
from pairbench.errors import Refusal
from pairbench.model import KIND_FILE

if TYPE_CHECKING:
    from pairbench.model import Capture, Results


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The flags of ``compare``: the capture files, ``--reader`` and the rest."""
    parser.add_argument("captures", nargs="*", metavar="FILE", help="capture files to analyse")
    parser.add_argument("--baseline", action="append", default=[], metavar="NAME")
    parser.add_argument("--rule", metavar="NAME")
    parser.add_argument(
        "--fail-on", action="append", default=[], dest="fail_on", choices=CHOICES["--fail-on"]
    )
    parser.add_argument(
        "--case", action="append", default=[], metavar="GLOB", help="show only these cases"
    )
    parser.add_argument("--out", metavar="DIR", help="write results.json and results.md here")
    parser.add_argument("--json", action="store_true", help="print the results document")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--allow-mixed-machines", action="store_true")
    parser.add_argument("--assume-interleaved", action="store_true")
    parser.add_argument(
        "--side", action="append", default=[], metavar="NAME=file:GLOB", help="(repeat)"
    )
    parser.add_argument("--driver", metavar="NAME", help="the driver that reads the files")
    parser.add_argument(
        "--levels", metavar="LIST", help="the load level the result files were made at"
    )
    parser.add_argument("--reader", metavar="NAME", help="the reader of the capture files")
    parser.add_argument("--no-plugins", action="store_true", dest="no_plugins")


def _file_sides(options: argparse.Namespace) -> list[Capture]:
    """Read result files of other tools into a run folder and return its capture."""
    import pairbench
    from pairbench import config

    if not options.driver:
        raise Refusal("E_USAGE", "result files given with --side need --driver NAME")
    flags = config.flag_config(
        {
            "--driver": options.driver,
            "--levels": options.levels,
            "--rule": options.rule,
            "--out": options.out,
            "--explain": "off",
            "--plots": "off",
        },
        sides=options.side,
        baseline=one_baseline(options),
    )
    experiment = config.load_experiment(None, environ={}, flags=flags)
    others = [side.name for side in experiment.sides if side.kind != KIND_FILE]
    if others:
        raise Refusal(
            "E_USAGE",
            "compare takes sides that are result files (NAME=file:GLOB); "
            f"run the others with pairbench run: {', '.join(others)}",
        )
    from pairbench.cli.run import run_out

    try:
        return [pairbench.run(experiment, out=run_out(experiment))]
    except Refusal as refusal:
        run_dir = refusal.detail.get("run_dir")
        _write_refused(refusal, Path(run_dir) if isinstance(run_dir, str) else None, options)
        raise


def _write_refused(refusal: Refusal, folder: Path | None, options: argparse.Namespace) -> None:
    """Write the results a refusal carries into the folder, and print them under ``--json``.

    Either way, the note on what the shared files show of the command
    follows, before the refusal's own lines.
    """
    import pairbench
    from pairbench.api import WriteResults, delegate

    if refusal.results is None:
        return
    refused = refusal.results
    if folder is not None:
        write_results: WriteResults = delegate("write_results")
        refused = write_results(refused, folder)
    if options.json:
        emit(pairbench.render(refused, "json"), sys.stdout)
    if folder is not None or options.json:
        print_command_note()


def _folder(capture: Capture) -> Path | None:
    path = capture.source.path if capture.source is not None else None
    return Path(path).parent if path else None


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench compare``."""
    import pairbench
    from pairbench import registry
    from pairbench.api import ReportOptions, WriteResults, delegate

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    if options.side and options.captures:
        raise Refusal("E_USAGE", "give capture files or --side NAME=file:GLOB, not both")
    if not options.side and not options.captures:
        raise Refusal("E_USAGE", "compare needs capture files or --side NAME=file:GLOB")
    if options.reader and options.side:
        raise Refusal("E_USAGE", "--reader reads capture files; result files take --driver")
    if options.driver and not options.side:
        raise Refusal("E_USAGE", "--driver reads result files given with --side")
    if options.levels and not options.side:
        raise Refusal("E_USAGE", "--levels names the load level of result files given with --side")

    folder: Path | None
    baseline: str | None
    if options.side:
        captures = _file_sides(options)
        folder = _folder(captures[0])
        baseline = None
    else:
        captures = [
            capture
            for path in options.captures
            for capture in pairbench.load_capture(path, reader=options.reader)
        ]
        folder = Path(options.out) if options.out else None
        baseline = one_baseline(options)

    write_results: WriteResults = delegate("write_results")
    rule = options.rule or "strict"
    try:
        results: Results = pairbench.analyse(
            captures,
            rule=rule,
            baseline=baseline,
            allow_incomplete=options.allow_incomplete,
            allow_mixed_machines=options.allow_mixed_machines,
            assume_interleaved=options.assume_interleaved,
        )
    except Refusal as refusal:
        _write_refused(refusal, folder, options)
        raise
    code = fail_on_code(results, options.fail_on)
    if folder is not None:
        results = write_results(results, folder)
    shown = ReportOptions(cases=tuple(options.case))
    emit(
        pairbench.render(results, "terminal", options=shown),
        sys.stderr if options.json else sys.stdout,
    )
    if options.json:
        emit(pairbench.render(results, "json"), sys.stdout)
    if folder is not None or options.json:
        print_command_note()
    return code


__all__ = ["add_arguments", "command"]
