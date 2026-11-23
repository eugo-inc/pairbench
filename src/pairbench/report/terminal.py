# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The terminal report: one verdict table per subject, and the footer that is always printed.

Columns: case, each side's median with its unit, change, noise, p, verdict.
The change is the larger of the ratio and its inverse with a direction
word; the noise is the bar a gap must exceed; p is the corrected p-value
with a star that points at the footer; a case without a verdict shows its
reason in plain words. When the report is given the diagnostics document it
prints, after the footer, the findings made from resource figures and
counters, one sentence each, and where the full diagnostics are. It prints
no function name and no shared-object name.
"""

from __future__ import annotations

from collections.abc import Sequence

from pairbench.api import API_VERSION, ReportOptions
from pairbench.errors import ESCAPED_CHARACTERS
from pairbench.model import Diagnostics, Results
from pairbench.report import (
    Row,
    diagnostics_file,
    footer,
    shareable_findings,
    shown_comparisons,
    tables,
)

# The space between two columns of a table.
GUTTER = "  "


def plain(text: str) -> str:
    """Return a text from a run with every character that ``errors.printable`` escapes shown
    as ``?``: a control character, a line or paragraph separator, a Bidi_Control character
    and a surrogate that stands alone.

    A case name or a message cannot then move the cursor, change the colours of a terminal,
    break its line or change the order the line shows in, and the report always prints.
    """
    return "".join("?" if ord(ch) in ESCAPED_CHARACTERS else ch for ch in text)


def grid(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Return a table as lines of text, every column as wide as its widest cell."""
    cells = [[plain(cell) for cell in line] for line in (header, *rows)]
    widths = [max(len(line[i]) for line in cells) for i in range(len(header))]
    return [
        GUTTER.join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in cells
    ]


def _cells(row: Row) -> tuple[str, ...]:
    return (row.case, row.subject, row.baseline, row.change, row.noise, row.p, row.verdict)


def findings_lines(diagnostics: Diagnostics, where: str) -> list[str]:
    """Return the findings made from resource figures and counters, and where the rest is."""
    found = shareable_findings(diagnostics)
    lines = (
        ["Findings from resource figures and counters:"]
        if found
        else ["No finding from resource figures and counters."]
    )
    lines.extend(f"  {plain(finding.text)}" for finding in found)
    lines.append(f"Full diagnostics, with names from the user's code: {plain(where)}")
    return lines


def findings_text(diagnostics: Diagnostics) -> str:
    """Return the lines a run prints after the explain step.

    The findings made from resource figures and counters alone, one
    sentence each, and where the full diagnostics are. No function name and
    no shared-object name.
    """
    return "\n".join(findings_lines(diagnostics, diagnostics_file(None))) + "\n"


def terminal_text(results: Results, options: ReportOptions) -> str:
    """Return the terminal report of a results document."""
    comparisons = shown_comparisons(results, cases=options.cases, all_cases=options.all_cases)
    lines: list[str] = []
    for table in tables(results, comparisons, verbose=options.verbose):
        lines.append(plain(f"{table.subject} against {table.baseline} (baseline)"))
        lines.append("")
        header = ("case", table.subject, table.baseline, "change", "noise", "p", "verdict")
        lines.extend(grid(header, [_cells(row) for row in table.rows]))
        lines.append("")
    if not comparisons:
        lines.extend(["No comparison to show.", ""])
    for refusal in results.refusals:
        lines.append(plain(f"Refused, {refusal.code} ({refusal.scope}): {refusal.message}"))
    if results.refusals:
        lines.append("")
    lines.extend(plain(fact) for fact in footer(results, comparisons))
    if options.diagnostics is not None:
        lines.append("")
        lines.extend(findings_lines(options.diagnostics, diagnostics_file(results)))
    return "\n".join(lines) + "\n"


class TerminalReporter:
    """The reporter ``terminal``."""

    name = "terminal"
    api_version = API_VERSION

    def render(self, results: Results, options: ReportOptions) -> str:
        """Return the terminal report."""
        return terminal_text(results, options)


__all__ = [
    "GUTTER",
    "TerminalReporter",
    "findings_lines",
    "findings_text",
    "grid",
    "plain",
    "terminal_text",
]
