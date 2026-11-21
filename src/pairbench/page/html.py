# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The report page: one self-contained HTML file, written with the standard library.

The page holds, in this order: the verdict table with its footer facts, the
sides and the result without disturbed rounds; the controls (the positive
control, the cost of a launch, the size of the environment); the charts;
the diagnostics (the resource comparisons and, with the diagnostics
document, its findings, instruments, counters, stacks and shared objects);
the flame graphs; the same-against-same rows; refusals and notes; how to
reproduce the run.

The page is one file. It makes no request to any network address and loads
no outside script, font or style sheet: a content security policy at its
top forbids every fetch, the charts are embedded as pictures, each as a
``data:`` address, and each flame graph as the document of a frame, written
in the frame's ``srcdoc`` attribute, so no address grows with the size of
the graph. A flame graph keeps its own script and its interaction inside
its frame; the frame is sandboxed, so the script cannot reach the page.

Every text that comes from a run (case, side, function and shared-object
names, notes, messages, the command) is escaped before it is put in the
page, and the characters ``=``, ``(`` and ``@`` are written as character
references, so no such text becomes markup, script or an address. When the
page holds the diagnostics document it says at its top that it holds names
from the user's code; flame graphs, which hold such names, are embedded only
then. Without charts the page still exists and says why there are none and
how to get them.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pairbench import model
from pairbench.api import API_VERSION, ReportOptions
from pairbench.charts import (
    PLOT_EXTRA,
    bar_text,
    better_of,
    change_text,
    figure_text,
    floor_text,
    kind_of,
    median_text,
    number_text,
    p_text,
    ratio_text,
    unit_of,
)
from pairbench.model import Comparison, Diagnostics, Results
from pairbench.report import (
    SECONDARY_P_FACT,
    comparison_reason_words,
    degraded_checks,
    serving_odds_fact,
)
from pairbench.results.figures import floor_or, writable_percent

# The line a page that holds the diagnostics document shows at its top.
NAMES_LINE: Final = (
    "This page holds names from the user's code: function names, shared-object names and "
    "sampled call stacks. results.json and results.md hold none of them."
)
# How to get charts that were not drawn.
HOW_TO_DRAW: Final = (
    f"To draw the charts, install {PLOT_EXTRA} and run pairbench report --plots on "
    "in the run folder."
)
# How to draw again charts whose files cannot be shown.
DRAW_AGAIN: Final = "To draw the charts again, run pairbench report --plots on in the run folder."
# The height of a framed flame graph whose own height cannot be read, and the largest height.
FLAME_HEIGHT: Final = 600
FLAME_HEIGHT_MOST: Final = 4000
# The document of a flame graph's frame, around the graph's own text.
FRAME_HEAD: Final = (
    "<!DOCTYPE html><html><head><style>body{margin:0}svg{display:block}</style></head><body>"
)
FRAME_TAIL: Final = "</body></html>"
# Added to the reason "not significant" where the row shows a corrected p-value.
AFTER_CORRECTION: Final = "after the correction"

_AS_REFERENCES = str.maketrans({"=": "&#61;", "(": "&#40;", "@": "&#64;"})

PLOTS_WORDS: Final[Mapping[tuple[str, str | None], str]] = {
    ("drawn", None): "The charts were drawn.",
    ("not_drawn", "extra_missing"): "Charts were not drawn: the plot extra is not installed.",
    ("not_drawn", "failed"): "Charts were not drawn: drawing them failed (see the notes).",
    ("not_drawn", None): "Charts were not drawn.",
    ("off", None): "Charts were turned off for this run.",
    ("pending", None): "Charts had not been drawn when these results were written.",
    ("interrupted", None): "Drawing the charts was interrupted.",
}

DIAGNOSTICS_WORDS: Final[Mapping[tuple[str, str | None], str]] = {
    ("written", None): "The explain step wrote the diagnostics document.",
    ("skipped", "mode_auto_no_difference"): (
        "The explain step was skipped: under explain mode auto it runs only when a primary "
        "case came out better or worse."
    ),
    ("skipped", "lock"): "The explain step was skipped: a lock could not be taken.",
    ("skipped", "no_instrument"): "The explain step was skipped: no instrument could run.",
    ("off", None): "The explain step was turned off for this run.",
    ("failed", None): "The explain step failed (see the notes).",
    ("pending", None): "The explain step had not run when these results were written.",
    ("interrupted", None): "The explain step was interrupted.",
}

_STYLE: Final = """
body { font-family: system-ui, sans-serif; margin: 1.5rem auto; max-width: 75rem;
       padding: 0 1rem; color: #1a1a1a; background: #ffffff; line-height: 1.4; }
h1 { font-size: 1.6rem; } h2 { font-size: 1.25rem; margin-top: 2rem;
     border-bottom: 1px solid #cccccc; } h3 { font-size: 1.05rem; }
table { border-collapse: collapse; margin: 0.5rem 0 1rem; }
th, td { border: 1px solid #cccccc; padding: 0.2rem 0.5rem; text-align: left;
         vertical-align: top; }
th { background: #f0f0f0; }
td.number { text-align: right; font-variant-numeric: tabular-nums; }
p.names { border: 2px solid #b35900; background: #fff4e5; padding: 0.5rem 0.75rem; }
p.missing { color: #555555; }
figure { margin: 1rem 0; }
figure img { max-width: 100%; height: auto; border: 1px solid #dddddd; }
iframe { width: 100%; border: 1px solid #dddddd; }
code { font-family: ui-monospace, monospace; }
"""


def text(value: object) -> str:
    """Escape a text from a run for the page.

    ``&``, ``<``, ``>`` and both quotes become character references, and so
    do ``=``, ``(`` and ``@``, so the text can stand in an element or in a
    quoted attribute and reads as no markup, script or address.
    """
    return html.escape(str(value), quote=True).translate(_AS_REFERENCES)


def _cell(value: object, *, number: bool = False) -> str:
    css = ' class="number"' if number else ""
    return f"<td{css}>{text(value)}</td>"


def _table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Return a table; ``rows`` hold cells already written with ``_cell``."""
    header = "".join(f"<th>{text(h)}</th>" for h in head)
    body = "".join(f"<tr>{''.join(row)}</tr>" for row in rows)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _paragraph(value: object, css: str | None = None) -> str:
    attribute = f' class="{css}"' if css else ""
    return f"<p{attribute}>{text(value)}</p>"


def _items(values: Iterable[object]) -> str:
    return "<ul>" + "".join(f"<li>{text(v)}</li>" for v in values) + "</ul>"


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _value(value: float | None) -> str:
    return "no value" if value is None else number_text(value)


# ---------------------------------------------------------------------------
# Embedded files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Embedded:
    """A chart or flame-graph file of the run folder, read to be embedded, or why it is not.

    ``data`` is the file as base64 text, or ``None`` when the file is not
    embedded; ``problem`` then says why. ``height`` is the height the file
    gives its picture, when it gives one. ``content`` is the file's text.
    """

    file: str
    data: str | None
    problem: str | None
    height: float | None = None
    content: str | None = None


_SVG_HEIGHT = re.compile(r"<svg\b[^>]*?\sheight=\"([0-9]+(?:\.[0-9]+)?)(?:px|pt)?\"")


def embed(folder: Path | None, file: str) -> Embedded:
    """Read one SVG file of the run folder to embed it in the page.

    The file is named relative to the run folder. It is embedded only when
    it ends in ``.svg``, lies inside the folder, exists, reads as UTF-8 SVG
    text and points nowhere outside itself (``model.points_outside``).
    """
    if folder is None:
        return Embedded(file, None, "the page was made without the run folder")
    if not file.endswith(".svg"):
        return Embedded(file, None, "it is not an SVG file")
    if not file or re.search(model.OUTSIDE_RUN_FOLDER, file):
        return Embedded(file, None, "it lies outside the run folder")
    root = folder.resolve()
    path = (folder / file).resolve()
    if root not in path.parents:
        return Embedded(file, None, "it lies outside the run folder")
    if not path.is_file():
        return Embedded(file, None, "it is missing")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return Embedded(file, None, "it cannot be read as UTF-8 text")
    if "<svg" not in content:
        return Embedded(file, None, "it is not an SVG file")
    if model.points_outside(content):
        return Embedded(file, None, "it points outside itself")
    found = _SVG_HEIGHT.search(content)
    height = float(found.group(1)) if found else None
    data = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return Embedded(file, data, None, height, content)


def _data_address(embedded: Embedded) -> str:
    return f"data:image/svg+xml;base64,{embedded.data}"


def frame_document(embedded: Embedded) -> str | None:
    """Return a flame graph as the value of its frame's ``srcdoc`` attribute, or ``None``.

    The graph's text is placed in a small HTML document and escaped for an
    attribute in single quotes. The value carries no address, so a large
    graph is embedded whole: a browser can refuse a long ``data:``
    address. ``None`` says that, escaped, the graph would read as pointing
    outside the page (``model.points_outside``), and it is not embedded.
    """
    if embedded.content is None:
        return None
    escaped = html.escape(FRAME_HEAD + embedded.content + FRAME_TAIL, quote=False)
    escaped = escaped.replace("'", "&#x27;")
    return None if model.points_outside(escaped) else escaped


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Page:
    results: Results
    options: ReportOptions

    @property
    def diagnostics(self) -> Diagnostics | None:
        return self.options.diagnostics

    def shown(self, comparison: Comparison) -> bool:
        if self.options.cases and not model.case_matches(comparison.case, self.options.cases):
            return False
        return comparison.primary or self.options.all_cases

    def figure(self, key: str, fallback: str) -> str:
        found = figure_text(self.results, key)
        return fallback if found is None else found

    def baseline(self) -> str | None:
        for side in self.results.sides:
            if side.role == "baseline":
                return side.name
        return next((c.baseline for c in self.results.comparisons), None)


def _verdict_words(page: _Page, comparison: Comparison) -> str:
    """The verdict with its reason in the words of the terminal and markdown reports.

    The one addition: a reason "not significant" names the correction where
    the row shows a corrected p-value, beside its star.
    """
    words: str = comparison.verdict
    if comparison.outcome in ("unresolved", "no_verdict") and comparison.reason is not None:
        reason = comparison_reason_words(comparison)
        if comparison.reason == "not_significant" and _shows_corrected_p(page, comparison):
            reason = f"{reason} {AFTER_CORRECTION}"
        words = f"{words} ({reason})"
    return words


def _median(page: _Page, case: str, side: str, value: float | None) -> str:
    if value is None:
        return "no value"
    return page.figure(
        model.median_key(case, side), median_text(value, unit_of(page.results, case))
    )


def _graded_on_raw_p(results: Results) -> bool:
    """Whether the rule grades every case on its uncorrected p-value."""
    return model.grades_raw_p(results.rule)


def _shows_corrected_p(page: _Page, c: Comparison) -> bool:
    """Whether a row is graded on its corrected p-value: a primary case under a correcting rule."""
    return c.primary and not _graded_on_raw_p(page.results)


def _p_value(page: _Page, c: Comparison) -> str:
    """The p-value a row shows: the one the case was graded on, as the reports show it.

    A primary case under a rule that corrects shows its corrected p-value
    with a star. A secondary case, and every case under a rule that grades
    uncorrected p-values, shows its uncorrected p-value without a star.
    """
    if not _shows_corrected_p(page, c):
        p_value = "no p-value" if c.p_raw is None else p_text(c.p_raw)
        return page.figure(model.figure_key(c.case, c.subject, c.baseline, "p"), p_value)
    p_value = "no p-value" if c.p_corrected is None else p_text(c.p_corrected)
    p_value = page.figure(model.figure_key(c.case, c.subject, c.baseline, "p_corrected"), p_value)
    return p_value if c.p_corrected is None else f"{p_value}*"


def _verdict_rows(page: _Page, mine: Sequence[Comparison]) -> list[list[str]]:
    rows: list[list[str]] = []
    for c in mine:
        bar = writable_percent(c.bar, c.floor.unit)
        noise = "no bar" if bar is None else bar_text(bar, c.floor.unit)
        noise = page.figure(model.figure_key(c.case, c.subject, c.baseline, "bar"), noise)
        p_value = _p_value(page, c)
        row = [
            _cell(c.case),
            _cell(_median(page, c.case, c.subject, c.subject_median), number=True),
            _cell(_median(page, c.case, c.baseline, c.baseline_median), number=True),
            _cell(
                change_text(
                    c.ratio,
                    kind_of(page.results, c.case),
                    better=better_of(page.results, c.case),
                )
            ),
            _cell(noise, number=True),
            _cell(p_value, number=True),
            _cell(_verdict_words(page, c)),
        ]
        if page.options.verbose:
            for floor in (c.floor.subject, c.floor.baseline):
                value = None if floor is None else writable_percent(floor.value, c.floor.unit)
                shown = "no floor" if value is None else floor_text(value, c.floor.unit)
                row.append(_cell(shown, number=True))
        rows.append(row)
    return rows


def _footer(page: _Page, shown: Sequence[Comparison]) -> str:
    results = page.results
    facts: list[str] = []
    rounds = sorted({c.n_rounds for c in shown})
    if rounds:
        span = str(rounds[0]) if len(rounds) == 1 else f"{rounds[0]} to {rounds[-1]}"
        facts.append(f"Test: the sign test on {span} paired rounds.")
    odds = serving_odds_fact(results)
    if odds is not None:
        facts.append(odds)
    if _graded_on_raw_p(results):
        facts.append(model.raw_p_note(results.rule, results.comparisons))
    else:
        facts.append(f"* p is corrected: {results.rule.plain}.")
        if any(not c.primary for c in shown):
            facts.append(SECONDARY_P_FACT)
    facts.append(f"Rule: {results.rule.name}.")
    facts.append(f"Machine state: {results.machine_state.status}.")
    baseline = page.baseline()
    if baseline is not None:
        facts.append(f"Baseline: {baseline}.")
    control = results.controls.positive
    facts.append(f"Positive control: {control.status.replace('_', ' ')}.")
    for degraded in degraded_checks(results):
        facts.append(f"Check {degraded.name}: {degraded.status}: {degraded.message}")
    wanted = (model.NOTE_FLOOR_SUPPLIED, model.NOTE_FLOOR_PROVISIONAL, model.NOTE_LAUNCH_COST_SHARE)
    for note in results.notes:
        if note.code in wanted:
            facts.append(note.message)
    if results.energy is not None:
        facts.append(
            f"Energy covers the {results.energy.scope} only; it leaves out "
            f"{', '.join(results.energy.excludes)}."
        )
    driver = model.driver_text(results)
    if driver is not None:
        facts.append(driver)
    plan = results.plan
    facts.append(
        f"Rounds: {plan.rounds_completed} completed of {plan.rounds_planned} planned; "
        f"{plan.launches} launches."
    )
    return _items(facts)


def _identity_text(identity: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key, value in identity.items():
        shown = ", ".join(str(v) for v in value) if isinstance(value, tuple) else str(value)
        parts.append(f"{key}: {shown}")
    return "; ".join(parts) if parts else "none"


def _sides(page: _Page) -> str:
    rows = [
        [
            _cell(side.name),
            _cell(side.kind),
            _cell(side.role),
            _cell(_identity_text(side.identity)),
            _cell(side.fingerprint),
            *([] if side.image_ref is None else [_cell(side.image_ref)]),
        ]
        for side in page.results.sides
    ]
    head = ["side", "kind", "role", "identity", "fingerprint"]
    if any(side.image_ref is not None for side in page.results.sides):
        head.append("image reference")
        for row, side in zip(rows, page.results.sides, strict=True):
            if side.image_ref is None:
                row.append(_cell(""))
    return "<h3>Sides</h3>" + _table(head, rows)


def _sensitivity(shown: Sequence[Comparison]) -> str:
    rows: list[list[str]] = []
    for c in shown:
        s = c.sensitivity
        set_aside = ", ".join(str(r) for r in s.rounds_set_aside) or "none"
        if s.not_computed is not None:
            without = f"not computed ({s.not_computed.replace('_', ' ')})"
            agrees = "not known"
        else:
            ratio = "no ratio" if s.ratio is None else ratio_text(s.ratio)
            without = f"{ratio}, {s.outcome or 'no outcome'}"
            agrees = "not known" if s.agrees is None else ("yes" if s.agrees else "no")
        all_rounds = "no ratio" if c.ratio is None else ratio_text(c.ratio)
        rows.append(
            [
                _cell(c.case),
                _cell(c.subject),
                _cell(f"{all_rounds}, {c.outcome}"),
                _cell(set_aside),
                _cell(without),
                _cell(agrees),
            ]
        )
    head = [
        "case",
        "subject",
        "all rounds",
        "rounds set aside as disturbed",
        "without disturbed rounds",
        "agrees",
    ]
    return "<h3>All rounds against the rounds without disturbed rounds</h3>" + _table(head, rows)


def _verdict_section(page: _Page) -> str:
    results = page.results
    shown = [c for c in results.comparisons if page.shown(c)]
    parts = ["<h2>Verdict</h2>"]
    if not shown:
        parts.append(_paragraph("No comparison is shown.", "missing"))
    subjects = list(dict.fromkeys(c.subject for c in shown))
    for subject in subjects:
        mine = [c for c in shown if c.subject == subject]
        baseline = mine[0].baseline
        head = [
            "case",
            f"{subject} median",
            f"{baseline} median",
            "change",
            "noise",
            "p",
            "verdict",
        ]
        if page.options.verbose:
            head += [f"{subject} floor", f"{baseline} floor"]
        parts.append(f"<h3>{text(subject)} against {text(baseline)}</h3>")
        parts.append(_table(head, _verdict_rows(page, mine)))
    if not page.options.all_cases and any(not c.primary for c in results.comparisons):
        parts.append(_paragraph("Secondary cases are shown with --all.", "missing"))
    parts.append(_footer(page, shown))
    parts.append(_sides(page))
    if shown:
        parts.append(_sensitivity(shown))
    return _section("verdict", parts)


def _controls_section(page: _Page) -> str:
    results = page.results
    control = results.controls.positive
    parts = ["<h2>Controls</h2>", "<h3>Positive control</h3>"]
    words = f"State: {control.status.replace('_', ' ')}"
    if control.entry is not None:
        words += f"; entry {control.entry}, made by {control.via}"
    words += f"; tolerance ±{_percent(control.tolerance)} of the expected ratio."
    parts.append(_paragraph(words))
    if control.cases:
        rows = [
            [
                _cell(row.case),
                _cell(ratio_text(row.expected), number=True),
                _cell("no ratio" if row.ratio is None else ratio_text(row.ratio), number=True),
                _cell("no p-value" if row.p_raw is None else p_text(row.p_raw), number=True),
                _cell(row.n_rounds, number=True),
                _cell("yes" if row.passed else "no"),
            ]
            for row in control.cases
        ]
        head = ["case", "expected", "measured", "p (uncorrected)", "paired rounds", "passed"]
        parts.append(_table(head, rows))
    parts.append("<h3>Cost of a launch</h3>")
    cost = results.launch_cost
    if cost is None:
        parts.append(_paragraph("The cost of a launch was not measured in this run.", "missing"))
    else:
        median = page.figure(model.FIGURE_LAUNCH_COST_MEDIAN, median_text(cost.median_s, "s"))
        spread = page.figure(model.FIGURE_LAUNCH_COST_SPREAD, median_text(cost.spread_s, "s"))
        parts.append(
            _paragraph(
                f"Median {median}, spread {spread} (third quartile less the first), from "
                f"{cost.n} launches of the empty command {cost.command}. It is an upper bound "
                "on what the tool adds to a wall value."
            )
        )
        rows = [
            [
                _cell(median_text(cost.min_s, "s"), number=True),
                _cell(median_text(cost.p25_s, "s"), number=True),
                _cell(median_text(cost.median_s, "s"), number=True),
                _cell(median_text(cost.p75_s, "s"), number=True),
            ]
        ]
        parts.append(_table(["least", "first quartile", "median", "third quartile"], rows))
    parts.append("<h3>Size of the environment</h3>")
    pad = results.env_pad
    if pad.varied:
        parts.append(
            _paragraph(
                f"The size of the environment was varied from round to round, from {pad.min} "
                f"to {pad.max} bytes."
            )
        )
    else:
        parts.append(_paragraph("The size of the environment was not varied."))
    return _section("controls", parts)


def _chart_title(file: str, cases: Mapping[str, str]) -> str:
    if file == model.chart_file("verdict"):
        return "Verdict of each primary case"
    if file == model.chart_file("noise"):
        return "Noise: each side against its twin"
    if file == model.chart_file("resources"):
        return "Resource figures of each side"
    if file in cases:
        return f"Round by round: {cases[file]}"
    return file


def _charts_section(page: _Page) -> str:
    results = page.results
    parts = ["<h2>Charts</h2>"]
    plots = results.plots
    files = results.artifacts.charts
    if files and page.options.folder is None:
        parts.append(
            _paragraph(
                f"The charts of this run are files in the run folder: {', '.join(files)}. "
                "This page was made without the run folder; pairbench report --format html "
                "in the run folder embeds them.",
                "missing",
            )
        )
        return _section("charts", parts)
    embedded = [embed(page.options.folder, file) for file in files]
    shown = [e for e in embedded if e.data is not None]
    primary = [c.id for c in results.cases if c.primary]
    names = model.file_names(primary)
    cases = {model.chart_file("rounds", names[case]): case for case in primary}
    for item in embedded:
        if item.data is None:
            parts.append(_paragraph(f"Chart {item.file} is not shown: {item.problem}.", "missing"))
            continue
        title = _chart_title(item.file, cases)
        parts.append(
            f'<figure><img alt="{text(title)}" src="{_data_address(item)}">'
            f"<figcaption>{text(title)} ({text(item.file)})</figcaption></figure>"
        )
    if files and not shown:
        parts.append(_paragraph(DRAW_AGAIN, "missing"))
    elif not files:
        words = PLOTS_WORDS.get((plots.status, plots.reason), f"Charts: {plots.status}.")
        if plots.status == "drawn":
            words = "No chart had data to draw (see the notes)."
        parts.append(_paragraph(f"{words} {HOW_TO_DRAW}", "missing"))
    return _section("charts", parts)


def _resource_rows(page: _Page) -> str:
    rows = [
        [
            _cell(c.case),
            _cell(c.subject),
            _cell(_median(page, c.case, c.subject, c.subject_median), number=True),
            _cell(c.baseline),
            _cell(_median(page, c.case, c.baseline, c.baseline_median), number=True),
            _cell(c.verdict),
        ]
        for c in page.results.comparisons
        if c.case.startswith(model.RES_PREFIX)
    ]
    if not rows:
        return _paragraph("The results hold no res/ comparison.", "missing")
    head = ["case", "subject", "subject median", "baseline", "baseline median", "outcome"]
    return _table(head, rows)


def _stacks(document: Diagnostics) -> list[str]:
    parts: list[str] = []
    for summary in document.stacks:
        parts.append(
            f"<h4>{text(summary.side)}: {text(summary.samples)} samples, taken by "
            f"{text(summary.instrument)}</h4>"
        )
        if summary.top_functions:
            rows = [
                [_cell(f.name), _cell(f.object or "none"), _cell(_percent(f.share), number=True)]
                for f in summary.top_functions
            ]
            parts.append(_table(["function", "shared object", "share of samples"], rows))
        if summary.top_objects:
            rows = [
                [_cell(o.name), _cell(_percent(o.share), number=True)] for o in summary.top_objects
            ]
            parts.append(_table(["shared object", "share of samples"], rows))
    return parts


def _objects(document: Diagnostics) -> list[str]:
    parts: list[str] = []
    only = [(side, names) for side, names in document.objects.only_in.items() if names]
    if only:
        parts.append("<h4>Shared objects only one side loaded</h4>")
        rows = [[_cell(side), _cell(", ".join(names))] for side, names in only]
        parts.append(_table(["side", "shared objects"], rows))
    if document.objects.differ:
        parts.append("<h4>Shared objects with the same name and a different build id</h4>")
        rows = []
        for entry in document.objects.differ:
            ids = "; ".join(f"{side}: {build}" for side, build in entry.items() if side != "name")
            rows.append([_cell(entry["name"]), _cell(ids)])
        parts.append(_table(["shared object", "build id per side"], rows))
    return parts


def _diagnostics_section(page: _Page) -> str:
    results = page.results
    parts = ["<h2>Diagnostics</h2>", "<h3>Resource figures</h3>", _resource_rows(page)]
    state = results.diagnostics
    words = DIAGNOSTICS_WORDS.get((state.status, state.reason), f"Explain step: {state.status}.")
    where = results.artifacts.diagnostics
    document = page.diagnostics
    if document is None:
        if state.status == "written":
            words += " It is not part of this page"
            words += f"; it is {where} in the run folder." if where else "."
        parts.append(_paragraph(words, "missing"))
        return _section("diagnostics", parts)
    parts.append(_paragraph(words))
    parts.append("<h3>Findings</h3>")
    if document.findings:
        parts.append(_items(finding.text for finding in document.findings))
    else:
        parts.append(_paragraph("The diagnostics document holds no finding.", "missing"))
    if document.instruments:
        rows = [
            [
                _cell(row.name),
                _cell(row.side),
                _cell(row.status),
                _cell("" if row.reason is None else model.INSTRUMENT_REASON_WORDS[row.reason]),
                _cell("" if row.rc is None else row.rc, number=True),
            ]
            for row in document.instruments
        ]
        parts.append("<h3>Instruments</h3>")
        parts.append(_table(["instrument", "side", "status", "why not", "exit code"], rows))
    if document.counters:
        rows = [
            [
                _cell(row.event),
                _cell(row.subject),
                _cell(_value(row.subject_value), number=True),
                _cell(row.baseline),
                _cell(_value(row.baseline_value), number=True),
                _cell("no ratio" if row.ratio is None else ratio_text(row.ratio), number=True),
            ]
            for row in document.counters
        ]
        parts.append("<h3>Counters</h3>")
        head = ["event", "subject", "subject count", "baseline", "baseline count", "ratio"]
        parts.append(_table(head, rows))
    if document.stacks:
        parts.append("<h3>Where the samples fell</h3>")
        parts.extend(_stacks(document))
    objects = _objects(document)
    if objects:
        parts.append("<h3>Shared objects</h3>")
        parts.extend(objects)
    if document.notes:
        parts.append("<h3>Notes of the explain step</h3>")
        parts.append(_items(f"{note.code}: {note.message}" for note in document.notes))
    return _section("diagnostics", parts)


def _flame_files(results: Results) -> list[str]:
    return [
        file
        for file in results.artifacts.profiles
        if file.endswith((".flame.svg", ".flame-diff.svg"))
    ]


_FRAME_PROBLEM: Final = "embedded in the page, it would read as pointing outside the page"


def _flame_items(results: Results, options: ReportOptions) -> list[tuple[Embedded, str | None]]:
    """Read the flame graphs the results list, each with its frame document or ``None``.

    Flame graphs hold names from the user's code, so none is read for a page
    made without the diagnostics document.
    """
    if options.diagnostics is None:
        return []
    items = [embed(options.folder, file) for file in _flame_files(results)]
    return [(item, frame_document(item)) for item in items]


def _flame_section(page: _Page, items: Sequence[tuple[Embedded, str | None]]) -> str:
    parts = ["<h2>Flame graphs</h2>"]
    files = _flame_files(page.results)
    if not files:
        parts.append(_paragraph("This run has no flame graph.", "missing"))
        return _section("flame-graphs", parts)
    if page.diagnostics is None:
        parts.append(
            _paragraph(
                "Flame graphs hold names from the user's code and are shown only on a page "
                "made with the diagnostics document. They are files in the run folder: "
                f"{', '.join(files)}.",
                "missing",
            )
        )
        return _section("flame-graphs", parts)
    parts.append(
        _paragraph(
            "Each graph is interactive inside its frame: a click on a frame zooms to it, and "
            "a search marks the matching frames. A viewer that strips scripts from pictures "
            "shows the graph without the interaction."
        )
    )
    for item, document in items:
        if item.data is None or document is None:
            problem = item.problem if item.data is None else _FRAME_PROBLEM
            parts.append(_paragraph(f"Flame graph {item.file} is not shown: {problem}.", "missing"))
            continue
        height = FLAME_HEIGHT if item.height is None else int(item.height) + 20
        height = min(max(height, 100), FLAME_HEIGHT_MOST)
        parts.append(
            f'<figure><iframe sandbox="allow-scripts" title="flame graph {text(item.file)}" '
            f"style=\"height: {height}px\" srcdoc='{document}'></iframe>"
            f"<figcaption>{text(item.file)}</figcaption></figure>"
        )
    return _section("flame-graphs", parts)


def _same_section(page: _Page) -> str:
    parts = ["<h2>Same against same</h2>"]
    rows_in = page.results.same_vs_same
    if not rows_in:
        parts.append(_paragraph("This run had no twins.", "missing"))
        return _section("same-against-same", parts)
    twins = {side.twin_of: side.name for side in page.results.sides if side.twin_of is not None}
    rows = [
        [
            _cell(row.side),
            _cell(twins.get(row.side, f"{row.side}{model.TWIN_SUFFIX}")),
            _cell(row.case),
            _cell("no ratio" if row.ratio is None else ratio_text(row.ratio, 3), number=True),
            _cell(floor_or(row.floor, row.unit, "no floor"), number=True),
            _cell("no p-value" if row.p_raw is None else p_text(row.p_raw), number=True),
            _cell(row.n, number=True),
        ]
        for row in rows_in
    ]
    head = ["side", "twin", "case", "ratio", "floor", "p (uncorrected)", "rounds"]
    parts.append(_table(head, rows))
    return _section("same-against-same", parts)


def _notes_section(page: _Page) -> str:
    results = page.results
    parts = ["<h2>Refusals and notes</h2>"]
    if results.refusals:
        rows = [[_cell(r.code), _cell(r.scope), _cell(r.message)] for r in results.refusals]
        parts.append(_table(["code", "scope", "message"], rows))
    else:
        parts.append(_paragraph("No refusal."))
    if results.notes:
        parts.append(_items(f"{note.code}: {note.message}" for note in results.notes))
    else:
        parts.append(_paragraph("No note."))
    return _section("refusals-and-notes", parts)


def _reproduce_section(page: _Page) -> str:
    results = page.results
    parts = ["<h2>How to reproduce</h2>"]
    command = results.run.command
    if command:
        parts.append(f"<p>Command: <code>{text(command)}</code></p>")
    else:
        parts.append(_paragraph("The command was not recorded.", "missing"))
    config = results.provenance.config_sha256
    parts.append(_paragraph(f"Config hash: {config or 'not recorded'}."))
    parts.append(_paragraph(f"Tool: {results.tool.name} {results.tool.version}."))
    captures = [
        [_cell(c.capture_id), _cell(c.sha256 or "not recorded"), _cell(c.rounds, number=True)]
        for c in results.run.captures
    ]
    if captures:
        parts.append(_table(["capture", "sha256", "rounds"], captures))
    artifacts = results.artifacts
    files = [
        ("capture", artifacts.capture),
        ("markdown report", artifacts.markdown),
        ("plan", artifacts.plan),
        ("report page", artifacts.html),
        ("diagnostics document", artifacts.diagnostics),
    ]
    listed = [f"{what}: {name}" for what, name in files if name]
    listed += [f"profile: {name}" for name in artifacts.profiles]
    if listed:
        parts.append("<h3>Files of the run folder</h3>")
        parts.append(_items(listed))
    return _section("reproduce", parts)


def _section(name: str, parts: Sequence[str]) -> str:
    return f'<section id="{name}">\n' + "\n".join(parts) + "\n</section>"


def _policy(with_scripts: bool) -> str:
    """Return the page's content security policy.

    A frame written in ``srcdoc`` takes on this policy, so the inline script
    of an embedded flame graph needs ``script-src 'unsafe-inline'``; a page
    without one allows no script at all.
    """
    script = "script-src 'unsafe-inline'; " if with_scripts else ""
    return (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        f"{script}base-uri 'none'; form-action 'none'"
    )


def render_page(results: Results, options: ReportOptions) -> str:
    """Return the report page of a results document.

    ``options.diagnostics`` adds the diagnostics and the flame graphs, and
    the line at the top that the page holds names from the user's code.
    ``options.folder`` is the run folder: the chart and flame-graph files
    the results list under ``artifacts`` are read from there and embedded.
    """
    page = _Page(results, options)
    items = _flame_items(results, options)
    flames = any(item.data is not None and document is not None for item, document in items)
    header = ["<header>", "<h1>pairbench report</h1>"]
    if page.diagnostics is not None:
        header.append(_paragraph(NAMES_LINE, "names"))
    run = results.run
    header.append(
        _paragraph(
            f"Run {run.id}; started {run.started_at or 'at a time not recorded'}, finished "
            f"{run.finished_at or 'at a time not recorded'}; "
            f"{results.tool.name} {results.tool.version}."
        )
    )
    header.append("</header>")
    sections = [
        _verdict_section(page),
        _controls_section(page),
        _charts_section(page),
        _diagnostics_section(page),
        _flame_section(page, items),
        _same_section(page),
        _notes_section(page),
        _reproduce_section(page),
    ]
    document = "\n".join(
        [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            f'<meta http-equiv="Content-Security-Policy" content="{_policy(flames)}">',
            '<meta name="referrer" content="no-referrer">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>pairbench report: {text(run.id)}</title>",
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            *header,
            "<main>",
            *sections,
            "</main>",
            "</body>",
            "</html>",
            "",
        ]
    )
    outside = model.points_outside(document)
    if outside:
        raise ValueError(f"the report page points outside itself: {', '.join(outside)}")
    return document


class HtmlReporter:
    """The reporter ``html``: the report page of a run."""

    name = "html"
    api_version = API_VERSION

    def render(self, results: Results, options: ReportOptions) -> str:
        """Return the report page; see ``render_page``."""
        return render_page(results, options)


__all__ = [
    "DIAGNOSTICS_WORDS",
    "DRAW_AGAIN",
    "FLAME_HEIGHT",
    "FRAME_HEAD",
    "FRAME_TAIL",
    "HOW_TO_DRAW",
    "NAMES_LINE",
    "PLOTS_WORDS",
    "Embedded",
    "HtmlReporter",
    "embed",
    "frame_document",
    "render_page",
    "text",
]
