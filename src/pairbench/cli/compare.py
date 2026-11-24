# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench compare``: analyse or pool captures, or compare result files from other tools.

Captures are named as arguments; each file may hold several runs, and all
of them are pooled. With ``--matching`` the files are text capture files,
read together as one text in the matching mode of the text reader; their
runs pass the pool checks of that mode, and the two-sided view of the side
``--subject`` names against the side ``--baseline`` names is analysed as one
capture, in the unit and the direction the files give for it or that
``--unit`` and ``--better`` name. Result files of other tools are sides of kind ``file``
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
import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO

from pairbench.cli.common import CHOICES, emit, fail_on_code, one_baseline, print_command_note
from pairbench.errors import Refusal
from pairbench.model import KIND_FILE

if TYPE_CHECKING:
    from pairbench import MatchingView
    from pairbench.model import Capture, MatchingInfo, Results, Rule

DIRECTIONS: tuple[Literal["lower"], Literal["higher"]] = ("lower", "higher")
"""The values of ``--better``, and of a ``better=`` line the matching mode takes."""

CHECK_PAIRED_ROUNDS = "paired_rounds"
"""The ``check`` of the refusal of a two-sided view without a round that holds both sides."""


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
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="read text capture files leniently: a value that is not finite is a missing cell",
    )
    parser.add_argument(
        "--matching",
        action="store_true",
        help="read the text capture files together in the matching mode and compare two sides",
    )
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="NAME",
        help="with --matching, the side compared against --baseline",
    )
    parser.add_argument(
        "--unit",
        metavar="UNIT",
        help="with --matching, the unit of the values, over unit= lines that agree",
    )
    parser.add_argument(
        "--better",
        choices=DIRECTIONS,
        help="with --matching, the better direction of the values, over better= lines that agree",
    )
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
    from pairbench.api import WriteResults, delegate

    if refusal.results is None:
        return
    refused = refusal.results
    if folder is not None:
        write_results: WriteResults = delegate("write_results")
        refused = write_results(refused, folder)
    if options.json:
        _print_json(refused)
    if folder is not None or options.json:
        print_command_note()


def _print_json(results: Results) -> None:
    """Print the results document on standard output, as ``pairbench.render`` gives it in JSON.

    A document that holds a lone surrogate, which ``render`` refuses, is printed with the
    surrogate as it stands where standard output can write it (``_writes``): with the error
    handler ``surrogateescape``, which Python gives standard output under a C, POSIX or
    C.UTF-8 locale and in its UTF-8 mode, it writes a surrogate from U+DC80 to U+DCFF as the
    byte it stands for, and a stream without an encoding, as ``io.StringIO``, holds any
    surrogate. Where it cannot, as where it encodes UTF-8 with the error handler ``strict``
    or meets a surrogate below U+DC80, the refusal stands and nothing is printed.
    """
    import pairbench
    from pairbench.errors import lone_surrogate
    from pairbench.results.writer import results_text_as_held

    try:
        text = pairbench.render(results, "json")
    except Refusal:
        if lone_surrogate(results.to_json()) is None:
            raise
        text = results_text_as_held(results)
        if not _writes(text, sys.stdout):
            raise
    emit(text, sys.stdout)


def _writes(text: str, stream: TextIO) -> bool:
    """Say whether ``stream`` can write ``text``, by its encoding and its error handler.

    A stream without an encoding, as ``io.StringIO``, holds any text.
    """
    encoding = getattr(stream, "encoding", None)
    if encoding is None:
        return True
    errors = getattr(stream, "errors", None) or "strict"
    try:
        text.encode(encoding, errors)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _matching_sides(options: argparse.Namespace) -> tuple[str, str]:
    """Refuse what ``--matching`` does not take; return the subject and the baseline."""
    from pairbench.model import validate_side_name

    if options.side:
        raise Refusal(
            "E_USAGE",
            "--matching reads text capture files and takes no --side; "
            "name the compared side with --subject NAME",
        )
    if not options.captures:
        raise Refusal("E_USAGE", "--matching needs text capture files")
    for flag, given in (
        ("--lenient", options.lenient),
        ("--allow-incomplete", options.allow_incomplete),
        ("--allow-mixed-machines", options.allow_mixed_machines),
        ("--assume-interleaved", options.assume_interleaved),
        ("--driver", options.driver),
        ("--levels", options.levels),
    ):
        if given:
            raise Refusal("E_USAGE", f"{flag} does not apply to --matching")
    if options.reader not in (None, "text"):
        raise Refusal(
            "E_USAGE", f"--matching reads with the text reader, not the reader {options.reader}"
        )
    subjects = list(dict.fromkeys(options.subject))
    if len(subjects) > 1:
        raise Refusal("E_USAGE", f"--subject names more than one side: {', '.join(subjects)}")
    baseline = one_baseline(options)
    if not subjects or baseline is None:
        raise Refusal(
            "E_USAGE", "--matching compares two sides: name them with --subject and --baseline"
        )
    if options.unit is not None and not options.unit.strip():
        raise Refusal("E_USAGE", "--unit names a unit: give a text that is not empty")
    if options.unit is not None and not _utf8(options.unit):
        raise Refusal("E_USAGE", f"--unit names a unit: {options.unit!r} is not UTF-8 text")
    subject = subjects[0]
    for flag, name in (("--subject", subject), ("--baseline", baseline)):
        try:
            validate_side_name(name)
        except Refusal as refusal:
            raise Refusal("E_USAGE", f"{flag}: {refusal.message}") from None
    if subject == baseline:
        raise Refusal("E_USAGE", f"--subject and --baseline name the same side {subject!r}")
    return subject, baseline


def _utf8(text: str) -> bool:
    """Whether a text can be written as UTF-8: an argument with a byte that is not UTF-8
    reaches the tool as a lone surrogate, which the results files cannot hold."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _matching_info(view: MatchingView, refusal: Refusal | None = None) -> MatchingInfo:
    from pairbench.model import MatchingInfo

    read = view.read
    return MatchingInfo(
        runs=read.run_count,
        malformed_rows=read.malformed_rows,
        kept_rows=read.kept_rows,
        left_out_rows=view.left_out_no_order,
        other_side_rows=view.left_out_other_sides,
        refusal=dict(refusal.detail) if refusal is not None else None,
    )


def _paired_runs(view: MatchingView) -> set[int]:
    """The runs that give the view's capture a paired round: a round label holding both sides."""
    sides: dict[tuple[int, int], set[str]] = {}
    for kept in view.rows:
        sides.setdefault((kept.row.run, kept.row.round), set()).add(kept.row.side)
    return {run for (run, _label), names in sides.items() if len(names) == 2}


def _stated(
    view: MatchingView, key: str, runs: set[int], *, empty: bool = False
) -> dict[str, list[int]]:
    """The values the ``key=`` lines of ``runs`` state, stripped, each with its runs.

    An empty value is left out unless ``empty`` is true.
    """
    stated: dict[str, list[int]] = {}
    for run in view.read.runs:
        if run.index not in runs:
            continue
        for written, value in run.metadata:
            if written.strip() == key and (empty or value.strip()):
                where = stated.setdefault(value.strip(), [])
                if run.index not in where:
                    where.append(run.index)
    return stated


def _runs_named(runs: list[int]) -> str:
    if len(runs) == 1:
        return f"run {runs[0]}"
    return "runs " + ", ".join(map(str, runs[:-1])) + f" and {runs[-1]}"


def _one_stated(stated: dict[str, list[int]], key: str) -> str | None:
    """The one value of ``stated``, or ``None`` when there is none; more than one is refused."""
    if len(stated) > 1:
        given = ", ".join(
            f"{value or repr(value)} ({_runs_named(stated[value])})" for value in sorted(stated)
        )
        raise Refusal(
            "E_USAGE",
            f"the runs that give the view a paired round give {key}= more than one value: {given}",
        )
    return next(iter(stated), None)


def _unit_and_better(
    options: argparse.Namespace, view: MatchingView
) -> tuple[str, Literal["lower", "higher"]]:
    """The unit and the better direction of the view's capture.

    Only the runs that give the view's capture a paired round count. When
    their ``unit=`` lines, or their ``better=`` lines, state more than one
    value, or a ``better=`` line states one that is neither ``lower`` nor
    ``higher``, the comparison is refused with ``E_USAGE``, ``--unit`` and
    ``--better`` given or not; an empty ``better=`` value is one such. Otherwise
    ``--unit`` and ``--better`` name the unit and the direction; without them,
    each is the one value those lines state, or, when they state none, the
    view capture's default: ``ns``, and ``lower``. A ``unit=`` line with an
    empty value states nothing.
    """
    runs = _paired_runs(view)
    stated_unit = _one_stated(_stated(view, "unit", runs), "unit")
    stated_better = _stated(view, "better", runs, empty=True)
    direction = _one_stated(stated_better, "better")
    if direction is not None and direction not in DIRECTIONS:
        raise Refusal(
            "E_USAGE",
            f"{_runs_named(stated_better[direction])}: better= is lower or higher, "
            f"not {direction!r}",
        )
    unit: str = options.unit.strip() if options.unit is not None else stated_unit or "ns"
    better: Literal["lower", "higher"] = options.better or (
        "higher" if direction == "higher" else "lower"
    )
    return unit, better


def _rows(count: int) -> str:
    return f"{count} row" if count == 1 else f"{count} rows"


def _matching_refused(
    refusal: Refusal, captures: list[Capture], rule: Rule, view: MatchingView
) -> Refusal:
    """Give a refusal of the matching mode the results document of the refused comparison."""
    from pairbench import registry
    from pairbench.api import RefusedResults, WithFigures, delegate

    refused: RefusedResults = delegate("refused")
    with_figures: WithFigures = delegate("figures")
    results = with_figures(refused(captures, refusal, rule=rule))
    refusal.results = dataclasses.replace(
        results, plugins=registry.counts(), matching=_matching_info(view, refusal)
    )
    return refusal


def _matching(
    options: argparse.Namespace, subject: str, baseline: str
) -> tuple[Capture, MatchingInfo]:
    """Read the files in the matching mode, check the pool, and give the view's capture.

    A pool that a check of the matching mode refuses, and a view without a
    round that holds both sides, are refused with exit code 6; the refusal
    carries the results document, whose ``matching`` holds its detail.
    """
    import pairbench
    from pairbench import registry
    from pairbench.errors import EXIT_ANALYSIS

    rule = registry.rule(options.rule or "strict")
    read = pairbench.read_text_matching([Path(path) for path in options.captures], default_order="")
    view = read.two_sided(subject, baseline)
    paired = bool(_paired_runs(view))
    unit, better = _unit_and_better(options, view)
    found = pairbench.check_matching_pool(read)
    if found:
        captures = [view.capture(unit=unit, better=better)] if paired else []
        raise _matching_refused(found[0], captures, rule, view)
    if not paired:
        raise _matching_refused(
            Refusal(
                "E_GRID",
                f"no round of the two-sided view holds both {subject} and {baseline}: "
                f"the view keeps {_rows(len(view.rows))} of the two sides; "
                f"{_rows(view.left_out_no_order)} left out because no pass-order line "
                "of their run named both sides before them",
                exit_code=EXIT_ANALYSIS,
                detail={
                    "check": CHECK_PAIRED_ROUNDS,
                    "view_rows": len(view.rows),
                    "left_out_rows": view.left_out_no_order,
                    "other_side_rows": view.left_out_other_sides,
                },
            ),
            [],
            rule,
            view,
        )
    return view.capture(unit=unit, better=better), _matching_info(view)


def _folder(capture: Capture) -> Path | None:
    path = capture.source.path if capture.source is not None else None
    return Path(path).parent if path else None


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench compare``."""
    import pairbench
    from pairbench import registry

    if options.no_plugins:
        registry.set_plugins_enabled(False)
    if options.subject and not options.matching:
        raise Refusal("E_USAGE", "--subject names the compared side of --matching")
    if options.unit is not None and not options.matching:
        raise Refusal("E_USAGE", "--unit names the unit of --matching")
    if options.better is not None and not options.matching:
        raise Refusal("E_USAGE", "--better names the direction of --matching")
    if options.matching:
        return _analysed(options, *_read_matching(options))
    if options.side and options.captures:
        raise Refusal("E_USAGE", "give capture files or --side NAME=file:GLOB, not both")
    if not options.side and not options.captures:
        raise Refusal("E_USAGE", "compare needs capture files or --side NAME=file:GLOB")
    if options.reader and options.side:
        raise Refusal("E_USAGE", "--reader reads capture files; result files take --driver")
    if options.lenient and options.side:
        raise Refusal("E_USAGE", "--lenient reads text capture files; result files take --driver")
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
            for capture in pairbench.load_capture(
                path, reader=options.reader, strict=not options.lenient
            )
        ]
        folder = Path(options.out) if options.out else None
        baseline = one_baseline(options)
    return _analysed(options, captures, folder, baseline)


def _read_matching(
    options: argparse.Namespace,
) -> tuple[list[Capture], Path | None, str, MatchingInfo]:
    """The capture of ``--matching``, its folder, its baseline and what the reading found."""
    subject, baseline = _matching_sides(options)
    folder = Path(options.out) if options.out else None
    try:
        capture, matching = _matching(options, subject, baseline)
    except Refusal as refusal:
        _write_refused(refusal, folder, options)
        raise
    return [capture], folder, baseline, matching


def _with_no_twin_notes(results: Results) -> Results:
    """Give the results of ``--matching`` a note for each case that has no noise floor.

    The view has no twins, so no case of it has a floor, and a rule that
    needs one gives it no verdict. Each note is printed on standard error.
    """
    from pairbench.api import note_line
    from pairbench.model import NOTE_VIEW_WITHOUT_TWINS, Note

    added = tuple(
        Note(
            code=NOTE_VIEW_WITHOUT_TWINS,
            message=(
                f"the case {c.case!r} has no noise floor: the two-sided view of {c.subject} "
                f"and {c.baseline} has no twins, so the rule {results.rule.name} gives it no "
                "verdict; pairbench.analyse grades the view's capture with noise floors "
                "measured elsewhere"
            ),
        )
        for c in results.comparisons
        if "no_floor" in c.reasons
    )
    for note in added:
        print(note_line(note.code, note.message), file=sys.stderr)
    return dataclasses.replace(results, notes=(*results.notes, *added))


def _analysed(
    options: argparse.Namespace,
    captures: list[Capture],
    folder: Path | None,
    baseline: str | None,
    matching: MatchingInfo | None = None,
) -> int:
    """Analyse the captures, write and show the results, and return the exit code."""
    import pairbench
    from pairbench.api import ReportOptions, WriteResults, delegate

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
        if matching is not None and refusal.results is not None:
            refusal.results = dataclasses.replace(refusal.results, matching=matching)
        _write_refused(refusal, folder, options)
        raise
    if matching is not None:
        results = dataclasses.replace(results, matching=matching)
        results = _with_no_twin_notes(results)
    code = fail_on_code(results, options.fail_on)
    if folder is not None:
        results = write_results(results, folder)
    shown = ReportOptions(cases=tuple(options.case))
    emit(
        pairbench.render(results, "terminal", options=shown),
        sys.stderr if options.json else sys.stdout,
    )
    if options.json:
        _print_json(results)
    if folder is not None or options.json:
        print_command_note()
    return code


__all__ = ["add_arguments", "command"]
