# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The markdown report, the text of ``results.md``.

The verdict tables and the footer of the terminal report, then: the sides
with their image ID and digest hashes; the same-against-same rows; the
positive control with what it read per primary case; the cost of a launch;
the result over all rounds beside the result without disturbed rounds; the
resource comparisons; where the diagnostics and the report page are;
refusals and notes; how to reproduce.

The file is meant to be shared. It shows what the results document holds and
nothing else: no host, no user, no path outside the run folder, no function
name and no shared-object name, except the forms SECURITY.md lists under
Known limits of the shown command and of the hashes. The command of "how to reproduce" is
``run.command`` of the results as it stands, which the analysis cleaned when
it made the results. Every text that comes from a run is escaped, so a case
name cannot change the layout.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from pairbench.api import API_VERSION, ReportOptions
from pairbench.model import Comparison, Diagnostics, Results, verdict_word
from pairbench.report import (
    IDENTITY_LABELS,
    NONE_SHOWN,
    NOT_COMPUTED_WORDS,
    VIA_WORDS,
    case_label,
    cases_of,
    change_cell,
    diagnostics_file,
    footer,
    graded_on_raw_p,
    p_cell,
    resource_comparisons,
    rounds_list,
    shareable_findings,
    shown_comparisons,
    tables,
    verdict_cell,
)
from pairbench.results.figures import (
    bar_text,
    floor_or,
    median_text,
    p_text,
    ratio_text,
)

TITLE = "# pairbench results"

# Characters that mean something to markdown inside a line.
_SPECIAL = re.compile(r"([\\`*_~\[\]<>|#!])")

# The state of the explain step and of the charts, in plain words.
DIAGNOSTICS_WORDS = {
    "pending": "not run yet",
    "written": "written",
    "skipped": "skipped",
    "off": "off",
    "failed": "failed",
    "interrupted": "interrupted",
}
DIAGNOSTICS_REASON_WORDS = {
    "mode_auto_no_difference": "no primary case came out better or worse",
    "lock": "a lock could not be taken",
    "no_instrument": "no instrument could run",
}
PLOTS_WORDS = {
    "pending": "not drawn yet",
    "drawn": "drawn",
    "not_drawn": "not drawn",
    "off": "off",
    "interrupted": "interrupted",
}
PLOTS_REASON_WORDS = {
    "extra_missing": "the optional extra plot is not installed",
    "failed": "drawing failed",
}


def printable(text: str) -> str:
    """Return a text with every control character shown as ``?``.

    The file can then be printed to a terminal without moving the cursor or
    changing the colours.
    """
    return "".join("?" if unicodedata.category(ch) == "Cc" else ch for ch in text)


def md(text: str) -> str:
    """Return a text from a run escaped for a markdown line or table cell.

    White space is folded into single spaces, every other control character
    is shown as ``?``, and the characters that mean something to markdown
    are escaped.
    """
    return _SPECIAL.sub(r"\\\1", printable(" ".join(text.split())))


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Return a markdown table; every cell is escaped."""
    lines = ["| " + " | ".join(md(cell) for cell in header) + " |"]
    lines.append("|" + "---|" * len(header))
    lines.extend("| " + " | ".join(md(cell) for cell in row) + " |" for row in rows)
    return lines


def bullets(items: Sequence[str]) -> list[str]:
    """Return a markdown list; every item is escaped."""
    return [f"- {md(item)}" for item in items]


def _verdict_section(results: Results, options: ReportOptions) -> list[str]:
    comparisons = shown_comparisons(results, cases=options.cases, all_cases=options.all_cases)
    lines: list[str] = []
    for each in tables(results, comparisons, verbose=options.verbose):
        lines.extend(["", f"## {md(each.subject)} against {md(each.baseline)} (baseline)", ""])
        header = ("case", each.subject, each.baseline, "change", "noise", "p", "verdict")
        rows = [
            (r.case, r.subject, r.baseline, r.change, r.noise, r.p, r.verdict) for r in each.rows
        ]
        lines.extend(table(header, rows))
    if not comparisons:
        lines.extend(["", "No comparison to show."])
    lines.append("")
    lines.extend(bullets(footer(results, comparisons)))
    return lines


def _identity(identity: dict[str, object]) -> str:
    parts = []
    for key, value in identity.items():
        shown = ", ".join(str(v) for v in value) if isinstance(value, tuple) else str(value)
        parts.append(f"{IDENTITY_LABELS.get(key, key)} {shown or NONE_SHOWN}")
    return "; ".join(parts) or NONE_SHOWN


def _sides_section(results: Results) -> list[str]:
    lines = ["", "## Sides", ""]
    if not results.sides:
        return [*lines, "No side is recorded."]
    with_refs = any(side.image_ref for side in results.sides)
    header = ["side", "role", "kind", "identity", "fingerprint"]
    if with_refs:
        header.insert(3, "image")
    rows = []
    for side in results.sides:
        row = [side.name, side.role, side.kind, _identity(dict(side.identity)), side.fingerprint]
        if with_refs:
            row.insert(3, side.image_ref or NONE_SHOWN)
        rows.append(row)
    return [*lines, *table(header, rows)]


def _same_vs_same_section(results: Results) -> list[str]:
    lines = ["", "## Same against same", ""]
    if not results.same_vs_same:
        return [*lines, "No side was compared with its twin."]
    rows = [
        (
            row.side,
            case_label(row.case),
            NONE_SHOWN if row.ratio is None else ratio_text(row.ratio),
            floor_or(row.floor, row.unit, NONE_SHOWN),
            NONE_SHOWN if row.p_raw is None else p_text(row.p_raw),
            str(row.n),
        )
        for row in results.same_vs_same
    ]
    return [*lines, *table(("side", "case", "ratio", "floor", "p", "rounds"), rows)]


def _control_section(results: Results) -> list[str]:
    control = results.controls.positive
    lines = ["", "## Positive control", ""]
    if control.status == "not_run":
        lines.append("Not run.")
    else:
        via = VIA_WORDS.get(control.via, control.via)
        lines.append(
            md(
                f"{control.status.upper()}: entry {control.entry}, {via} ({control.via}); "
                f"tolerance {bar_text(control.tolerance, 'fraction')} of the expected value."
            )
        )
        if control.status == "failed":
            lines.append("")
            lines.append("Every comparison of this run is NO VERDICT.")
    if control.cases:
        rows = [
            (
                case_label(row.case),
                ratio_text(row.expected),
                NONE_SHOWN if row.ratio is None else ratio_text(row.ratio),
                NONE_SHOWN if row.p_raw is None else p_text(row.p_raw),
                str(row.n_rounds),
                "yes" if row.passed else "no",
            )
            for row in control.cases
        ]
        lines.append("")
        lines.extend(table(("case", "expected", "read", "p", "rounds", "passed"), rows))
    notes = [n.message for n in results.notes if n.code.startswith("positive_control")]
    if notes:
        lines.append("")
        lines.extend(bullets(notes))
    return lines


def _launch_cost_section(results: Results) -> list[str]:
    cost = results.launch_cost
    lines = ["", "## Cost of a launch", ""]
    if cost is None:
        lines.append("Not measured.")
    else:
        lines.append(
            md(
                f"Median {median_text(cost.median_s, 's')} over {cost.n} launches of the empty "
                f"command {cost.command}; first to third quartile "
                f"{median_text(cost.p25_s, 's')} to {median_text(cost.p75_s, 's')}, "
                f"least {median_text(cost.min_s, 's')}. It is an upper bound on what the tool "
                "adds to a wall value of a command side."
            )
        )
    notes = [n.message for n in results.notes if n.code.startswith("launch_cost")]
    if notes:
        lines.append("")
        lines.extend(bullets(notes))
    return lines


def _without_disturbed(comparison: Comparison, kind: str) -> str:
    s = comparison.sensitivity
    if s.not_computed is not None:
        return f"not computed: {NOT_COMPUTED_WORDS.get(s.not_computed, s.not_computed)}"
    if s.outcome is None:
        return NONE_SHOWN
    ratio = NONE_SHOWN if s.ratio is None else ratio_text(s.ratio)
    return f"{ratio} {verdict_word(s.outcome, kind)}"


def _sensitivity_section(results: Results, options: ReportOptions) -> list[str]:
    lines = ["", "## All rounds and without disturbed rounds", ""]
    comparisons = shown_comparisons(results, cases=options.cases, all_cases=options.all_cases)
    if not comparisons:
        return [*lines, "No comparison to show."]
    cases = cases_of(results)
    rows = []
    for c in comparisons:
        case = cases.get(c.case)
        kind = case.kind if case is not None else "other"
        all_rounds = f"{NONE_SHOWN if c.ratio is None else ratio_text(c.ratio)} {c.verdict}"
        set_aside = rounds_list(c.sensitivity.rounds_set_aside) or "none"
        rows.append(
            (
                case_label(c.case),
                c.subject,
                all_rounds,
                _without_disturbed(c, kind),
                set_aside,
            )
        )
    header = ("case", "subject", "all rounds", "without disturbed rounds", "rounds set aside")
    return [*lines, *table(header, rows)]


def _resource_section(results: Results) -> list[str]:
    lines = ["", "## Resource comparisons", ""]
    found = resource_comparisons(results)
    if not found:
        return [*lines, "No resource figure was recorded."]
    cases = cases_of(results)
    rows = []
    for c in found:
        case = cases.get(c.case)
        unit = case.unit if case is not None else ""
        rows.append(
            (
                c.case,
                c.subject,
                c.baseline,
                NONE_SHOWN if c.subject_median is None else median_text(c.subject_median, unit),
                NONE_SHOWN if c.baseline_median is None else median_text(c.baseline_median, unit),
                change_cell(c, case),
                p_cell(c, raw=graded_on_raw_p(results)),
                verdict_cell(c),
            )
        )
    header = (
        "case",
        "subject",
        "baseline",
        "subject median",
        "baseline median",
        "change",
        "p",
        "verdict",
    )
    return [*lines, *table(header, rows)]


def _files_section(results: Results, diagnostics: Diagnostics | None) -> list[str]:
    lines = ["", "## Diagnostics and report page", ""]
    state = results.diagnostics
    words = DIAGNOSTICS_WORDS.get(state.status, state.status)
    if state.reason is not None:
        words += f", {DIAGNOSTICS_REASON_WORDS.get(state.reason, state.reason)}"
    items = [f"Explain step: {words}."]
    if results.artifacts.diagnostics:
        items.append(
            f"Diagnostics: {results.artifacts.diagnostics}. It holds names from the user's "
            "code and is not part of this file."
        )
    plots = results.plots
    plot_words = PLOTS_WORDS.get(plots.status, plots.status)
    if plots.reason is not None:
        plot_words += f", {PLOTS_REASON_WORDS.get(plots.reason, plots.reason)}"
    items.append(f"Charts: {plot_words}.")
    items.extend(f"Chart: {name}" for name in results.artifacts.charts)
    if results.artifacts.html:
        items.append(f"Report page: {results.artifacts.html}.")
    items.extend(f"Profile: {name}" for name in results.artifacts.profiles)
    lines.extend(bullets(items))
    if diagnostics is not None:
        found = shareable_findings(diagnostics)
        lines.extend(["", "### Findings from resource figures and counters", ""])
        if found:
            lines.extend(bullets([f.text for f in found]))
        else:
            lines.append("No finding from resource figures and counters.")
        lines.append("")
        where = diagnostics_file(results)
        lines.append(md(f"The full diagnostics, with names from the user's code: {where}"))
    return lines


def _notes_section(results: Results) -> list[str]:
    lines = ["", "## Refusals and notes", ""]
    items = [f"Refused, {r.code} ({r.scope}): {r.message}" for r in results.refusals]
    items.extend(f"Note {n.code}: {n.message}" for n in results.notes)
    if not items:
        return [*lines, "None."]
    return [*lines, *bullets(items)]


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _reproduce_section(results: Results) -> list[str]:
    """Return how to reproduce the run.

    The command is ``run.command`` as the results record it, already cleaned
    (``model.public_command``), with every control character shown as ``?``
    and nothing else changed, so the line is the command the results record:
    cleaning it a second time would cut the archive path of an image side
    that ``report.include_image_refs`` shows whole.
    """
    lines = ["", "## How to reproduce", ""]
    command = results.run.command
    if command:
        command = printable(command)
        fence = _fence(command)
        lines.extend([fence, command, fence])
    else:
        lines.append("The command line was not recorded.")
    prov = results.provenance
    items = [f"Tool: {results.tool.name} {results.tool.version}."]
    if prov.config_sha256:
        items.append(f"Config hash: {prov.config_sha256}.")
    machine = prov.machine
    items.append(f"Machine: {machine.os}, {machine.arch}, {machine.cpu_model}.")
    items.extend(f"GPU: {gpu.model}, driver {gpu.driver}." for gpu in prov.gpu)
    if prov.engine is not None:
        items.append(f"Engine: {prov.engine.name} {prov.engine.version}.")
    if prov.node_type:
        items.append(f"Node type: {prov.node_type}.")
    plan = results.plan
    items.append(
        f"Rounds: {plan.rounds_completed} completed of {plan.rounds_planned} planned, "
        f"warm-up launches per side: {plan.warmups}, launches in all: {plan.launches}."
    )
    lines.append("")
    lines.extend(bullets(items))
    return lines


def markdown_text(results: Results, options: ReportOptions) -> str:
    """Return the markdown report of a results document."""
    lines = [TITLE]
    lines.extend(_verdict_section(results, options))
    lines.extend(_sides_section(results))
    lines.extend(_same_vs_same_section(results))
    lines.extend(_control_section(results))
    lines.extend(_launch_cost_section(results))
    lines.extend(_sensitivity_section(results, options))
    lines.extend(_resource_section(results))
    lines.extend(_files_section(results, options.diagnostics))
    lines.extend(_notes_section(results))
    lines.extend(_reproduce_section(results))
    return "\n".join(lines) + "\n"


class MarkdownReporter:
    """The reporter ``markdown``: the text of ``results.md``."""

    name = "markdown"
    api_version = API_VERSION

    def render(self, results: Results, options: ReportOptions) -> str:
        """Return the markdown report."""
        return markdown_text(results, options)


__all__ = [
    "TITLE",
    "MarkdownReporter",
    "bullets",
    "markdown_text",
    "md",
    "printable",
    "table",
]
