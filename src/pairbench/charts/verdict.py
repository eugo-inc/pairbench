# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The verdict chart: one row per primary case and subject.

Each row shows the measured ratio of the subject's median to the
baseline's, the noise band (the bar a gap must exceed) around a ratio of 1,
the change in words and the verdict word. The axis is logarithmic in the
ratio and centred at 1, so ``2x faster`` and ``2x slower`` sit equally far
from the centre line, which is labelled ``no difference``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pairbench import model
from pairbench.api import Notify
from pairbench.charts import (
    BAND,
    INK,
    OUTCOME_COLOURS,
    band_of,
    better_of,
    change_text,
    drawable_ratio,
    drawing,
    kind_of,
    log_limits,
    log_ticks,
    new_figure,
    svg_of,
)
from pairbench.model import NOTE_CHART_WITHOUT_DATA, Results

WIDTH: Final = 9.0
BASE_HEIGHT: Final = 1.9
ROW_HEIGHT: Final = 0.45
# The outcomes whose main reason is written beside the verdict word.
_WITH_REASON: Final[tuple[str, ...]] = ("unresolved", "no_verdict")


@dataclass(frozen=True)
class VerdictRow:
    """One row of the verdict chart, as it is drawn.

    ``ratio`` is the ratio a log axis can show, or ``None`` when the
    comparison has none, or one of zero or less: the row then has no marker
    and its text says so. ``band`` runs from ``1 - bar`` to ``1 + bar``.
    ``verdict`` is the verdict word of the results, with the main reason in
    brackets for a comparison that is unresolved or has no verdict.
    """

    label: str
    ratio: float | None
    band: tuple[float, float] | None
    change: str
    verdict: str
    outcome: str


def rows(results: Results) -> tuple[VerdictRow, ...]:
    """Return the rows of the verdict chart: the primary comparisons, in the results' order."""
    out: list[VerdictRow] = []
    for comparison in results.comparisons:
        if not comparison.primary:
            continue
        verdict: str = comparison.verdict
        if comparison.outcome in _WITH_REASON and comparison.reason is not None:
            verdict = f"{verdict} ({comparison.reason})"
        out.append(
            VerdictRow(
                label=f"{comparison.case}: {comparison.subject} vs {comparison.baseline}",
                ratio=drawable_ratio(comparison.ratio),
                band=band_of(comparison.bar, comparison.floor.unit),
                change=change_text(
                    comparison.ratio,
                    kind_of(results, comparison.case),
                    better=better_of(results, comparison.case),
                ),
                verdict=verdict,
                outcome=comparison.outcome,
            )
        )
    return tuple(out)


def limits(chart_rows: Sequence[VerdictRow]) -> tuple[float, float]:
    """Return the ends of the ratio axis: every ratio and every band end above 0 fits."""
    values: list[float] = []
    for row in chart_rows:
        if row.ratio is not None:
            values.append(row.ratio)
        if row.band is not None:
            values.extend(end for end in row.band if end > 0)
    return log_limits(values)


def draw(chart_rows: Sequence[VerdictRow]) -> bytes:
    """Draw the verdict chart of the given rows and return the SVG bytes."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import NullLocator

    low, high = limits(chart_rows)
    count = len(chart_rows)
    with drawing():
        figure = new_figure(WIDTH, BASE_HEIGHT + ROW_HEIGHT * count)
        axes = figure.add_subplot()
        axes.set_xscale("log")
        for index, row in enumerate(chart_rows):
            if row.band is not None:
                start, end = max(row.band[0], low), min(row.band[1], high)
                axes.barh(index, end - start, left=start, height=0.5, color=BAND, linewidth=0)
            if row.ratio is not None:
                axes.plot(
                    [row.ratio],
                    [index],
                    marker="o",
                    markersize=8,
                    linestyle="none",
                    color=OUTCOME_COLOURS.get(row.outcome, INK),
                    markeredgecolor=INK,
                )
        axes.axvline(1.0, color=INK, linewidth=1.0, linestyle="--")
        axes.set_xlim(low, high)
        ticks = log_ticks(high)
        axes.set_xticks([value for value, _ in ticks], labels=[text for _, text in ticks])
        axes.xaxis.set_minor_locator(NullLocator())
        axes.set_yticks(range(count), labels=[row.label for row in chart_rows])
        axes.set_ylim(count - 0.5, -0.5)
        right = axes.secondary_yaxis("right")
        right.set_ticks(
            range(count), labels=[f"{row.change}   {row.verdict}" for row in chart_rows]
        )
        axes.set_xlabel("ratio of the subject's median to the baseline's (log scale, centred at 1)")
        axes.set_title("Verdict of each primary case")
        handles = [
            Line2D([], [], marker="o", linestyle="none", color=INK),
            Patch(facecolor=BAND),
            Line2D([], [], linestyle="--", color=INK),
        ]
        labels = [
            "measured ratio (median of the rounds)",
            "noise band (the bar a change must exceed)",
            "no difference (1x)",
        ]
        figure.legend(handles, labels, loc="outside lower center", ncols=3, frameon=False)
        return svg_of(figure)


def draw_all(results: Results, note: Notify) -> list[tuple[str, bytes]]:
    """Return the verdict chart's file and bytes, or nothing and a note when no row has data."""
    chart_rows = rows(results)
    if not chart_rows:
        note(
            NOTE_CHART_WITHOUT_DATA,
            "verdict chart not drawn: the results hold no comparison of a primary case",
        )
        return []
    return [(model.chart_file("verdict"), draw(chart_rows))]
