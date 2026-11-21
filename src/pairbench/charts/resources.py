# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The resource chart: the ``res/`` figures of each side, the median of each.

One panel per ``res/`` case, in the order the results first name it. A
panel has one bar per side, the subjects first and the baseline last, at
the side's median, with the side's name beside the bar and the median and
its unit written at the bar's end. The panel's title names the case, its
unit and the outcome of each subject against the baseline in words, such as
``HIGHER``. The medians come from the comparisons of the ``res/`` cases in
the results; when the results hold none, from the resource rows of the
diagnostics document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pairbench import model
from pairbench.api import Notify
from pairbench.charts import (
    INK,
    PALETTE,
    axis_divisor,
    axis_number,
    drawing,
    kind_of,
    median_text,
    new_figure,
    svg_of,
    unit_of,
)
from pairbench.model import NOTE_CHART_WITHOUT_DATA, Diagnostics, Results

WIDTH: Final = 9.0
PANEL_HEIGHT: Final = 1.0
BAR_HEIGHT: Final = 0.4
NO_VALUE: Final = "no value"


@dataclass(frozen=True)
class Bar:
    """One side's median on one resource case; ``None`` when the side has no value."""

    side: str
    median: float | None


@dataclass(frozen=True)
class Panel:
    """The bars of one resource case, its unit and the outcomes in words."""

    case: str
    unit: str
    bars: tuple[Bar, ...]
    outcomes: str


@dataclass(frozen=True)
class _Row:
    case: str
    subject: str
    baseline: str
    subject_median: float | None
    baseline_median: float | None
    word: str


def _rows(results: Results, diagnostics: Diagnostics | None) -> list[_Row]:
    rows = [
        _Row(
            case=c.case,
            subject=c.subject,
            baseline=c.baseline,
            subject_median=c.subject_median,
            baseline_median=c.baseline_median,
            word=c.verdict,
        )
        for c in results.comparisons
        if c.case.startswith(model.RES_PREFIX)
    ]
    if rows or diagnostics is None:
        return rows
    return [
        _Row(
            case=r.case,
            subject=r.subject,
            baseline=r.baseline,
            subject_median=r.subject_median,
            baseline_median=r.baseline_median,
            word=model.verdict_word(r.outcome, kind_of(results, r.case)),
        )
        for r in diagnostics.resources
        if r.case.startswith(model.RES_PREFIX)
    ]


def panels(results: Results, diagnostics: Diagnostics | None = None) -> tuple[Panel, ...]:
    """Return the panels of the resource chart.

    A panel in which no side has a value is left out: there is nothing to
    draw for that case.
    """
    rows = _rows(results, diagnostics)
    made: list[Panel] = []
    for case in dict.fromkeys(row.case for row in rows):
        mine = [row for row in rows if row.case == case]
        medians: dict[str, float | None] = {}
        for row in mine:
            medians.setdefault(row.subject, row.subject_median)
        for row in mine:
            medians.setdefault(row.baseline, row.baseline_median)
        bars = tuple(Bar(side=side, median=median) for side, median in medians.items())
        if all(bar.median is None for bar in bars):
            continue
        outcomes = "; ".join(f"{row.subject} against {row.baseline}: {row.word}" for row in mine)
        made.append(Panel(case=case, unit=unit_of(results, case), bars=bars, outcomes=outcomes))
    return tuple(made)


def draw(chart_panels: Sequence[Panel]) -> bytes:
    """Draw the resource chart of the given panels and return the SVG bytes."""
    from matplotlib.ticker import FuncFormatter

    heights = [PANEL_HEIGHT + BAR_HEIGHT * len(panel.bars) for panel in chart_panels]
    with drawing():
        figure = new_figure(WIDTH, 0.6 + sum(heights))
        grid = figure.subplots(
            len(chart_panels), 1, squeeze=False, gridspec_kw={"height_ratios": heights}
        )
        for panel, axes in zip(chart_panels, grid[:, 0], strict=True):
            count = len(panel.bars)
            largest = max((bar.median for bar in panel.bars if bar.median is not None), default=0)
            divisor = axis_divisor(bar.median for bar in panel.bars)
            right_end = largest / divisor * 1.3 if largest > 0 else 1.0
            for index, bar in enumerate(panel.bars):
                if bar.median is None:
                    axes.text(0, index, f" {NO_VALUE}", va="center", ha="left", color=INK)
                    continue
                axes.barh(
                    index,
                    bar.median / divisor,
                    height=0.6,
                    color=PALETTE[index % len(PALETTE)],
                    edgecolor=INK,
                    linewidth=0.5,
                )
                axes.text(
                    bar.median / divisor,
                    index,
                    f" {median_text(bar.median, panel.unit)}",
                    va="center",
                    ha="left",
                    color=INK,
                )
            axes.set_yticks(range(count), labels=[bar.side for bar in panel.bars])
            axes.set_ylim(count - 0.5, -0.5)
            axes.set_xlim(0, right_end)
            axes.xaxis.set_major_formatter(FuncFormatter(axis_number(divisor)))
            unit = f" ({panel.unit})" if panel.unit else ""
            axes.set_title(f"{panel.case}{unit}: {panel.outcomes}", loc="left")
        figure.suptitle("Resource figures of each side (median of the rounds)")
        return svg_of(figure)


def draw_all(
    results: Results, diagnostics: Diagnostics | None, note: Notify
) -> list[tuple[str, bytes]]:
    """Return the resource chart's file and bytes, or nothing and a note when it has no data."""
    chart_panels = panels(results, diagnostics)
    if not chart_panels:
        note(
            NOTE_CHART_WITHOUT_DATA,
            "resource chart not drawn: the results hold no res/ cases with a value",
        )
        return []
    return [(model.chart_file("resources"), draw(chart_panels))]
