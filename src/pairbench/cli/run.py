# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench run``: measure an experiment and write its run folder.

``run_to_end`` is the whole command for one experiment, from the first
launch to the report page; the tool server calls the same function.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from pairbench.cli.common import (
    add_experiment_arguments,
    emit,
    experiment_from,
    fail_on_code,
    print_command_note,
    print_note,
    refuse_file_sides,
    relative_to,
)
from pairbench.errors import EXIT_INTERRUPTED, Refusal, docs_line
from pairbench.model import (
    FILE_DIAGNOSTICS,
    FILE_REPORT,
    NOTE_CHARTS_FAILED,
    NOTE_EXPLAIN_FAILED,
    NOTE_PAGE_FAILED,
    TOOL_VERSION,
    DiagnosticsState,
    Note,
    PlotsState,
)

if TYPE_CHECKING:
    from pairbench.model import Capture, Diagnostics, Experiment, Results


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Every flag of ``model.FLAG_KEYS``, ``--side``, ``--baseline``, ``--config``, ``--set``."""
    add_experiment_arguments(parser)


def command(options: argparse.Namespace) -> int:
    """Run ``pairbench run``: the plan when it is asked for, the whole run otherwise."""
    experiment = experiment_from(options)
    refuse_file_sides(experiment)
    if experiment.run.print_plan:
        from pairbench.cli.plan import print_plan

        return print_plan(experiment)
    return run_to_end(experiment)


def _interrupted(error: BaseException) -> bool:
    if isinstance(error, KeyboardInterrupt):
        return True
    return isinstance(error, Refusal) and error.code == "E_INTERRUPTED"


def _failure(error: BaseException) -> str:
    """What a failed step says about its failure: a refusal's message or the kind of error."""
    if isinstance(error, Refusal):
        return error.line
    return type(error).__name__


def run_out(experiment: Experiment) -> Path | None:
    """The run folder the experiment's run settings name, or ``None`` for a new one."""
    return Path(experiment.run.out) if experiment.run.out else None


def _folder_of(capture: Capture) -> Path:
    path = capture.source.path if capture.source is not None else None
    if not path:
        raise Refusal("E_INTERNAL", "the capture of the run names no file")
    return Path(path).parent


class _Finish:
    """The steps after the first write of the results, and what each left behind."""

    def __init__(self, experiment: Experiment, first: Results, folder: Path, out: TextIO) -> None:
        self.experiment = experiment
        self.first = first
        self.folder = folder
        self.out = out
        self.diagnostics = DiagnosticsState(status="pending")
        self.plots = PlotsState(status="pending")
        self.notes: list[Note] = []
        self.document: Diagnostics | None = None
        self.charts: tuple[str, ...] = ()

    def note(self, code: str, message: str) -> None:
        """Add a loud note of a step and print it."""
        self.notes.append(Note(code=code, message=message))
        print_note(code, message)

    def explain(self) -> None:
        """Step 4: the explain step, when the mode asks for it; its findings are printed."""
        import pairbench
        from pairbench.api import FindingsText, delegate

        mode = self.experiment.explain.mode
        if mode == "off":
            self.diagnostics = DiagnosticsState(status="off")
            return
        if mode == "auto" and not self.first.has_difference():
            self.diagnostics = DiagnosticsState(status="skipped", reason="mode_auto_no_difference")
            return
        try:
            document = pairbench.explain(self.experiment, self.first, out=self.folder)
        except Exception as error:
            if _interrupted(error):
                raise
            self.diagnostics = DiagnosticsState(status="failed")
            self.note(
                NOTE_EXPLAIN_FAILED,
                f"the explain step failed ({_failure(error)}); the verdicts are unchanged",
            )
            return
        self.document = document
        self.diagnostics = document.state()
        self.notes.extend(document.notes)
        try:
            findings: FindingsText = delegate("findings")
            emit(findings(document), self.out)
        except Exception as error:
            if _interrupted(error):
                raise
            self.note(
                NOTE_EXPLAIN_FAILED,
                f"the findings could not be printed ({_failure(error)})",
            )

    def draw(self) -> None:
        """Step 5: the charts, unless the plot mode is ``off``."""
        import pairbench
        from pairbench import api

        plots = self.experiment.plots
        if plots.mode == "off":
            self.plots = PlotsState(status="off")
            return
        seen: list[Note] = []

        def keep(code: str, message: str) -> None:
            # pairbench.draw prints each note itself; the run only records it.
            seen.append(Note(code=code, message=message))

        try:
            paths = pairbench.draw(
                self.first,
                out=self.folder,
                diagnostics=self.document,
                max_round_charts=plots.max_round_charts,
                note=keep,
            )
        except Exception as error:
            if _interrupted(error):
                raise
            self.notes.extend(seen)
            self.plots = PlotsState(status="not_drawn", reason="failed")
            self.note(
                NOTE_CHARTS_FAILED,
                f"the charts could not be drawn ({_failure(error)}); the verdicts are unchanged",
            )
            return
        self.notes.extend(seen)
        if paths:
            self.charts = relative_to(self.folder, paths)
            self.plots = PlotsState(status="drawn")
        elif not api.plot_extra_installed():
            self.plots = PlotsState(status="not_drawn", reason="extra_missing")
        else:
            self.plots = PlotsState(status="not_drawn")

    def results(self, *, html: bool) -> Results:
        """The document of the second write as the steps left it."""
        document = self.document
        written = document is not None and (self.folder / FILE_DIAGNOSTICS).is_file()
        files = document.files if document is not None else None
        profiles = (
            (*files.folded, *files.folded_diff, *files.flame, *files.flame_diff)
            if files is not None
            else self.first.artifacts.profiles
        )
        artifacts = dataclasses.replace(
            self.first.artifacts,
            diagnostics=FILE_DIAGNOSTICS if written else None,
            charts=self.charts,
            profiles=tuple(profiles),
            html=FILE_REPORT if html else None,
        )
        return self.first.finished(
            diagnostics=self.diagnostics, plots=self.plots, notes=self.notes, artifacts=artifacts
        )

    def page(self) -> str | None:
        """Step 7, in memory: the report page of the final results, or ``None``."""
        import pairbench

        if not self.experiment.report.html:
            return None
        try:
            return pairbench.render(
                self.results(html=True), "html", diagnostics=self.document, folder=self.folder
            )
        except Exception as error:
            if _interrupted(error):
                raise
            self.note(
                NOTE_PAGE_FAILED,
                f"the report page could not be made ({_failure(error)}); the results are written",
            )
            return None


def _write_refused(refusal: Refusal, folder: Path | None, experiment: Experiment) -> None:
    """Write the results a refusal carries once, as they are, and print them under ``--json``.

    The note on what the shared files show of the command follows, before
    the refusal's own lines.
    """
    import pairbench
    from pairbench.api import WriteResults, delegate

    if refusal.results is None or folder is None:
        return
    write_results: WriteResults = delegate("write_results")
    written = write_results(refusal.results, folder)
    if experiment.run.json:
        emit(pairbench.render(written, "json"), sys.stdout)
    print_command_note()


def run_to_end(experiment: Experiment) -> int:
    """Everything ``pairbench run`` does for one experiment; returns the exit code.

    1. ``require_plot_extra(experiment.plots.mode)``, then ``pairbench.run``.
    2. ``pairbench.analyse``; this and ``rule.fail_on`` fix the exit code.
    3. First write of the results with ``Results.pending()``; the terminal
       report is printed (on standard error under ``run.json``, so that
       standard output holds the results document alone).
    4. ``pairbench.explain`` under mode ``always``, or ``auto`` with a
       difference; the findings are printed.
    5. ``pairbench.draw`` unless the plot mode is ``off``.
    6. Second write with ``Results.finished(...)``; under ``run.json`` this
       document is printed on standard output.
    7. ``report.html`` when ``report.html`` is set.

    8. One note on standard error (``NOTE_COMMAND_SHOWN``): the shared files
       show the command with each ``--side`` spec, each ``--set`` value and
       the secret forms the tool recognises hidden, and each absolute path
       cut to its last part; secrets belong in environment variables.

    A failure in step 4, 5 or 7 is a loud note and never fails the run. An
    interrupt in steps 4 to 7 writes the results once more with
    ``Results.interrupted()``, writes no report page and returns 130. A
    refusal that carries results has them written once, as they are, and
    is raised again. Whenever results are written, the note of step 8 is
    printed once, after their last write and before an interrupt's or a
    refusal's lines.
    """
    import pairbench
    from pairbench import api
    from pairbench.api import WriteResults, delegate
    from pairbench.results.writer import replace_file

    write_results: WriteResults = delegate("write_results")
    out = sys.stderr if experiment.run.json else sys.stdout

    api.require_plot_extra(experiment.plots.mode)
    try:
        capture = pairbench.run(experiment, out=run_out(experiment))
    except Refusal as refusal:
        run_dir = refusal.detail.get("run_dir")
        _write_refused(refusal, Path(run_dir) if isinstance(run_dir, str) else None, experiment)
        raise
    folder = _folder_of(capture)
    try:
        analysed = pairbench.analyse(capture, rule=experiment.rule.name)
    except Refusal as refusal:
        _write_refused(refusal, folder, experiment)
        raise
    code = fail_on_code(analysed, experiment.rule.fail_on)

    first = write_results(analysed.pending(), folder)
    emit(pairbench.render(first, "terminal"), out)

    finish = _Finish(experiment, first, folder, out)
    page: str | None = None
    try:
        finish.explain()
        finish.draw()
        page = finish.page()
        second = write_results(finish.results(html=page is not None), folder)
        if page is not None:
            try:
                replace_file(folder / FILE_REPORT, page)
            except OSError as error:
                finish.note(
                    NOTE_PAGE_FAILED,
                    f"the report page could not be written ({error.strerror or 'error'})",
                )
                second = write_results(finish.results(html=False), folder)
    except BaseException as error:
        if not _interrupted(error):
            raise
        write_results(finish.results(html=False).interrupted(), folder)
        print_command_note()
        print(
            Refusal("E_INTERRUPTED", "interrupted after the results were written").line,
            file=sys.stderr,
        )
        print(docs_line("E_INTERRUPTED", TOOL_VERSION), file=sys.stderr)
        return EXIT_INTERRUPTED
    if experiment.run.json:
        emit(pairbench.render(second, "json"), sys.stdout)
    print_command_note()
    return code


__all__ = ["add_arguments", "command", "run_out", "run_to_end"]
