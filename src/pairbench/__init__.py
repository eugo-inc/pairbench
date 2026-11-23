# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""pairbench: paired benchmarking with a measured noise floor and a verdict.

The functions here are the whole Python API. Each one imports the module
that does its work when it is called, so importing ``pairbench`` needs no
container engine and no external program.

Importing ``pairbench`` imports no other module of the package. The classes
of the data model and the version are public names of the package all the
same: each is loaded from the model the first time it is used.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pairbench.api import Notify, ReportOptions
    from pairbench.errors import Refusal
    from pairbench.model import (
        Capture,
        Case,
        CaseSettings,
        Comparison,
        ControlSettings,
        Diagnostics,
        EnergySettings,
        Experiment,
        ExplainSettings,
        Floors,
        GateSettings,
        Launch,
        LaunchCostSettings,
        LaunchSettings,
        LoadSettings,
        Observation,
        Plan,
        PlanRow,
        PlotSettings,
        Ready,
        ReportSettings,
        Results,
        Rule,
        RuleSettings,
        RunSettings,
        ServeSpec,
        Side,
    )

    __version__: str

# The public names that are classes of the data model. Each is loaded from
# ``pairbench.model`` the first time it is asked for.
_FROM_MODEL = frozenset(
    {
        "Capture",
        "Case",
        "CaseSettings",
        "Comparison",
        "ControlSettings",
        "Diagnostics",
        "EnergySettings",
        "Experiment",
        "ExplainSettings",
        "Floors",
        "GateSettings",
        "Launch",
        "LaunchCostSettings",
        "LaunchSettings",
        "LoadSettings",
        "Observation",
        "Plan",
        "PlanRow",
        "PlotSettings",
        "Ready",
        "ReportSettings",
        "Results",
        "Rule",
        "RuleSettings",
        "RunSettings",
        "ServeSpec",
        "Side",
    }
)

__all__ = [
    "Capture",
    "Case",
    "CaseSettings",
    "Comparison",
    "ControlSettings",
    "Diagnostics",
    "EnergySettings",
    "Experiment",
    "ExplainSettings",
    "Floors",
    "GateSettings",
    "Launch",
    "LaunchCostSettings",
    "LaunchSettings",
    "LoadSettings",
    "Observation",
    "Plan",
    "PlanRow",
    "PlotSettings",
    "Ready",
    "ReportSettings",
    "Results",
    "Rule",
    "RuleSettings",
    "RunSettings",
    "ServeSpec",
    "Side",
    "__version__",
    "analyse",
    "check_pool",
    "draw",
    "explain",
    "fill",
    "load_capture",
    "load_diagnostics",
    "load_results",
    "plan",
    "render",
    "run",
]


def __getattr__(name: str) -> Any:
    """Load a public name of the data model, or the version, on first use."""
    if name in _FROM_MODEL:
        value = getattr(importlib.import_module("pairbench.model"), name)
    elif name == "__version__":
        value = importlib.import_module("pairbench.model").TOOL_VERSION
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


class _Package(types.ModuleType):
    """The package module.

    The package has a function ``plan`` and a submodule ``plan``. Importing
    the submodule leaves the name ``plan`` bound to the function; the
    submodule's names are imported with ``from pairbench.plan import ...``.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "plan" and isinstance(value, types.ModuleType):
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Package


def plan(experiment: Experiment) -> Plan:
    """Lay out the order of every launch of an experiment.

    Nothing is started, pulled, locked or written. The number of primary
    cases is not known before a warm-up, so the plan is made for one.
    """
    from pairbench.api import BuildPlan, delegate

    build_plan: BuildPlan = delegate("plan")
    return build_plan(experiment)


def run(experiment: Experiment, *, out: Path | None = None) -> Capture:
    """Run an experiment and return its capture.

    ``out`` names the run folder itself; without it the folder is the one the
    experiment's run settings name, or a new folder under ``pairbench-runs``.
    The folder receives the capture and the plan that was run. An experiment
    whose sides are result files launches nothing and reads them.

    A refusal after the capture was opened leaves the folder in place; the
    raised ``Refusal`` then carries, as ``results``, the results document of
    the refused run.
    """
    from pairbench.api import RunExperiment, delegate
    from pairbench.errors import Refusal

    run_experiment: RunExperiment = delegate("run")
    try:
        return run_experiment(experiment, out=out)
    except Refusal as refusal:
        folder = refusal.detail.get("run_dir")
        if refusal.results is None and isinstance(folder, str):
            refusal.results = _refused_run(Path(folder), refusal)
        raise


def analyse(
    captures: Capture | Sequence[Capture],
    *,
    rule: str | Rule = "strict",
    baseline: str | None = None,
    floors: Floors | None = None,
    allow_incomplete: bool = False,
    allow_mixed_machines: bool = False,
    assume_interleaved: bool = False,
) -> Results:
    """Analyse one capture, or pool several captures of the same experiment.

    ``rule`` is the name of a rule or a ``Rule``. ``baseline`` names another
    baseline than the recorded one. ``floors`` supplies noise floors measured
    elsewhere. The three switches lift a refusal or a missing verdict and
    stamp the results: ``allow_incomplete`` analyses the complete rounds of a
    capture that has no end record, ``allow_mixed_machines`` pools captures
    of different machines, ``assume_interleaved`` grades rows whose order was
    not recorded.

    A refused analysis raises ``Refusal``, which carries as ``results`` the
    results document of the refused analysis: no comparisons and the refusal
    listed. Every note the analysis adds is also printed on standard error.
    """
    from pairbench import registry
    from pairbench.api import AnalyseCaptures, delegate
    from pairbench.errors import Refusal
    from pairbench.model import Capture

    analyse_captures: AnalyseCaptures = delegate("analyse")
    chosen = registry.rule(rule) if isinstance(rule, str) else rule
    given = (captures,) if isinstance(captures, Capture) else tuple(captures)
    try:
        results = analyse_captures(
            given,
            rule=chosen,
            baseline=baseline,
            floors=floors,
            allow_incomplete=allow_incomplete,
            allow_mixed_machines=allow_mixed_machines,
            assume_interleaved=assume_interleaved,
        )
    except Refusal as refusal:
        if refusal.results is None:
            refusal.results = _refused(given, refusal, chosen)
        raise
    finished = _finish(results)
    _announce(finished, given)
    return finished


def check_pool(captures: Sequence[Capture], *, allow_mixed_machines: bool = False) -> list[Refusal]:
    """Run the checks that pooling ``captures`` in one analysis makes, and return what they refuse.

    The checks and their refusals are those of ``analyse``, which runs the
    same code: the same capture, file or bytes given twice
    (``E_POOL_SAME``), identical rows (``E_POOL_IDENTICAL_ROWS``), a truncated
    copy (``E_POOL_TRUNCATED_COPY``), a capture of one side against its twins
    pooled with a comparison (``E_POOL_MIXED_PURPOSE``), a side, workload,
    setup or working folder that changed (``E_POOL_SIDE_DRIFT``), other cases
    or units (``E_POOL_CASES``), another machine (``E_POOL_MACHINE``, not
    listed with ``allow_mixed_machines``) and names a run marked that cannot
    be read alike (``E_USAGE``). Each is a ``Refusal`` with its text code,
    exit code, scope, message and detail, returned, not raised, in the order
    the analysis meets them. The first is the one ``analyse`` raises for the
    captures in the same order when each is complete or incomplete captures
    are allowed; ``analyse`` refuses an incomplete capture with
    ``E_CAPTURE_INCOMPLETE`` once the first three checks pass. An empty list
    says the captures pool. Nothing is printed. Completeness and the grid of
    each capture are checked by ``analyse`` alone.
    """
    from pairbench.api import CheckPool, delegate
    from pairbench.errors import Refusal
    from pairbench.model import Capture

    if isinstance(captures, Capture):
        raise Refusal("E_USAGE", "check_pool takes a list of captures")
    pool_refusals: CheckPool = delegate("check_pool")
    return pool_refusals(tuple(captures), allow_mixed_machines=allow_mixed_machines)


def load_capture(
    path: Path | str, *, reader: str | None = None, strict: bool = True
) -> list[Capture]:
    """Read the captures in a file: one per run it holds.

    ``reader`` names a capture reader. Without it the readers are asked in
    turn, built-ins first, whether the file is theirs; a file no reader
    claims is refused.

    ``strict=False`` reads the file with the lenient mode of the text
    reader: a value that is no finite number is a missing cell, which the
    capture notes as ``value_not_finite``, one note per cell, and which
    ``analyse`` leaves unpaired while it grades the rest; ``refusals`` stays
    empty. A round whose order contradicts itself is read with its order not
    recorded. A reader that has no lenient mode is refused with ``E_USAGE``.
    """
    from pairbench import registry
    from pairbench.api import GROUP_CAPTURE_READERS
    from pairbench.errors import Refusal

    file = Path(path)
    if not isinstance(strict, bool):
        raise Refusal("E_USAGE", "strict is true or false")
    if reader is not None:
        if not strict:
            return _read_leniently(registry.capture_reader(reader), reader, file)
        return registry.capture_reader(reader).read(file)
    try:
        with file.open("rb") as handle:
            head = handle.read(4096)
    except OSError as exc:
        raise Refusal("E_USAGE", f"cannot read {file.name}: {exc.strerror or exc}") from exc
    for name in registry.names(GROUP_CAPTURE_READERS):
        candidate = registry.capture_reader(name)
        if candidate.sniff(file, head):
            if not strict:
                return _read_leniently(candidate, name, file)
            return candidate.read(file)
    raise Refusal("E_USAGE", f"no capture reader recognises {file.name}; name one with a reader")


def _read_leniently(chosen: Any, name: str, file: Path) -> list[Capture]:
    """Read a file with the lenient mode of the text reader, or refuse another reader."""
    from pairbench.capture.text import TextReader
    from pairbench.errors import Refusal

    if not isinstance(chosen, TextReader):
        raise Refusal(
            "E_USAGE",
            f"the capture reader {name} has no lenient mode; only the text reader reads "
            f"{file.name} leniently",
        )
    return chosen.read(file, strict=False)


def load_results(path: Path | str) -> Results:
    """Read a results document from a file."""
    from pairbench.api import ReadResults, delegate

    read_results: ReadResults = delegate("load_results")
    return read_results(Path(path))


def render(
    results: Results,
    fmt: Literal["terminal", "markdown", "json", "html"],
    *,
    diagnostics: Diagnostics | None = None,
    folder: Path | None = None,
    options: ReportOptions | None = None,
) -> str:
    """Render a results document as a terminal report, markdown, JSON or the report page.

    The function is given what it may show. With ``diagnostics``, the
    terminal and markdown reports add the findings and the page adds the
    diagnostics. With ``folder``, the page embeds the chart and flame-graph
    files found there. Without either, every format is rendered from the
    results alone. ``options`` filters what is displayed. It never changes
    what was tested.
    """
    from pairbench import registry
    from pairbench.api import ReportOptions

    chosen = options or ReportOptions()
    if diagnostics is not None:
        chosen = dataclasses.replace(chosen, diagnostics=diagnostics)
    if folder is not None:
        chosen = dataclasses.replace(chosen, folder=Path(folder))
    return registry.reporter(fmt).render(results, chosen)


def explain(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics:
    """Run the explain step for an analysed run and return the diagnostics document.

    Each subject and the baseline is launched again under instruments,
    untimed. ``out`` is the run folder: it receives ``diagnostics.json`` and
    the files under ``profiles/``. An instrument that cannot run is skipped
    with a loud note; every note of the step is printed on standard error
    and is in the document. A lock that cannot be taken skips every launch
    of the step: the document then says so for each instrument and holds
    one note. The step changes no comparison.
    """
    from pairbench.api import ExplainRun, delegate, note_line

    explain_run: ExplainRun = delegate("explain")
    document = explain_run(experiment, results, out=Path(out))
    for note in document.notes:
        print(note_line(note.code, note.message), file=sys.stderr)
    return document


def load_diagnostics(path: Path | str) -> Diagnostics:
    """Read a diagnostics document from a file."""
    from pairbench.api import ReadDiagnostics, delegate

    read_diagnostics: ReadDiagnostics = delegate("load_diagnostics")
    return read_diagnostics(Path(path))


def draw(
    results: Results,
    *,
    out: Path,
    diagnostics: Diagnostics | None = None,
    max_round_charts: int = 12,
    note: Notify | None = None,
) -> list[Path]:
    """Draw the charts of a run into ``out`` and return their paths.

    The charts are drawn from the results and, when given, the diagnostics
    document, never from a capture. Without the ``plot`` extra nothing is
    drawn and the list is empty. At most ``max_round_charts`` round-by-round
    charts are drawn. Every loud note of the drawing, such as a missing
    extra or charts that were left out, is printed on standard error and
    handed to ``note`` as ``(code, message)`` when one is given.
    """
    from pairbench.api import DrawCharts, delegate, note_line

    def announce(code: str, message: str) -> None:
        print(note_line(code, message), file=sys.stderr)
        if note is not None:
            note(code, message)

    draw_charts: DrawCharts = delegate("draw")
    return draw_charts(
        results,
        out=Path(out),
        diagnostics=diagnostics,
        max_round_charts=max_round_charts,
        note=announce,
    )


def fill(template: str | Path, results: Results | Mapping[str, Results]) -> str:
    """Fill the figure tokens of a document from results.

    A ``Path`` is read as a file, its line endings kept as they are; a
    ``str`` is the template text. One ``Results`` serves the tokens that
    carry no results name. A mapping serves named tokens; its entry named by
    the empty text serves the tokens without a name. Every missing figure is
    refused, all of them listed.
    """
    from pairbench.api import FillText, delegate
    from pairbench.model import Results

    fill_text: FillText = delegate("fill")
    text = template.read_bytes().decode("utf-8") if isinstance(template, Path) else template
    named = {"": results} if isinstance(results, Results) else dict(results)
    return fill_text(text, named)


def _finish(results: Results) -> Results:
    """Add the figures and the plug-in counts to analysed results."""
    from pairbench import registry
    from pairbench.api import WithFigures, delegate

    with_figures: WithFigures = delegate("figures")
    return dataclasses.replace(with_figures(results), plugins=registry.counts())


def _announce(results: Results, captures: Sequence[Capture]) -> None:
    """Print each note the analysis added on standard error.

    A note a capture already holds was printed when the run made it; the
    results show it with absolute paths cut to their last part.
    """
    from pairbench.api import note_line

    recorded = [note for capture in captures for note in capture.notes]
    known = {(note.code, note.message) for note in recorded}
    known |= {(note.code, note.for_results().message) for note in recorded}
    for note in results.notes:
        if (note.code, note.message) not in known:
            known.add((note.code, note.message))
            print(note_line(note.code, note.message), file=sys.stderr)


def _refused(captures: Sequence[Capture], refusal: Refusal, rule: Rule) -> Results | None:
    """Build the results document of a refused run or analysis, when that is possible."""
    try:
        from pairbench.api import RefusedResults, delegate

        refused: RefusedResults = delegate("refused")
        return _finish(refused(captures, refusal, rule=rule))
    except Exception:
        return None


def _refused_run(folder: Path, refusal: Refusal) -> Results | None:
    try:
        from pairbench import registry
        from pairbench.model import FILE_CAPTURE, STRICT

        captures = registry.capture_reader("jsonl").read(folder / FILE_CAPTURE)
        config = captures[0].header.config if captures else {}
        named = config.get("rule", {}).get("name", STRICT.name)
        rule = registry.rule(named) if isinstance(named, str) else STRICT
    except Exception:
        return None
    return _refused(captures, refusal, rule)
