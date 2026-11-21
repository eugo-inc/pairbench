# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The noise chart: each side against its twin, per floor group, with the floor.

One row per same-against-same row of the results, under a heading for its
floor group. Each row shows the measured ratio of the side to its twin and
the band of the side's noise floor around a ratio of 1, on the same
logarithmic axis as the verdict chart, with the ratio and the floor written
in words at its right. A run without twins has no rows and no noise chart.
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
    PALETTE,
    band_of,
    case_of,
    drawable_ratio,
    drawing,
    floor_text,
    log_limits,
    log_ticks,
    new_figure,
    ratio_text,
    svg_of,
)
from pairbench.model import NOTE_CHART_WITHOUT_DATA, Results
from pairbench.results.figures import writable_percent

WIDTH: Final = 9.0
BASE_HEIGHT: Final = 1.9
ROW_HEIGHT: Final = 0.45


@dataclass(frozen=True)
class NoiseRow:
    """One side against its twin on one case, as the noise chart draws it.

    ``group`` names the floor group of the case. ``ratio`` is the ratio a
    log axis can show, or ``None``. ``band`` is the side's floor around 1.
    ``text`` is what is written at the right of the row.
    """

    group: str
    label: str
    ratio: float | None
    band: tuple[float, float] | None
    text: str


def group_of(results: Results, case: str) -> str:
    """Return the floor group of a case in words.

    A case with a group of its own is in that group. Every other case is in
    the group of the cases that share its metric and its role.
    """
    record = case_of(results, case)
    if record is None:
        return case
    if record.group is not None:
        return record.group
    role = "primary" if record.primary else "secondary"
    return f"metric {record.metric}, {role} cases"


def _twin_name(results: Results, side: str) -> str:
    twin = next((s.name for s in results.sides if s.twin_of == side), None)
    return twin if twin is not None else f"{side}{model.TWIN_SUFFIX}"


def rows(results: Results) -> tuple[NoiseRow, ...]:
    """Return the rows of the noise chart, grouped by floor group in the order groups appear."""
    made: list[NoiseRow] = []
    for row in results.same_vs_same:
        ratio = drawable_ratio(row.ratio)
        ratio_words = "no ratio" if ratio is None else ratio_text(ratio, 3)
        floor = writable_percent(row.floor, row.unit)
        floor_words = "no floor" if floor is None else f"floor ±{floor_text(floor, row.unit)}"
        made.append(
            NoiseRow(
                group=group_of(results, row.case),
                label=f"{row.side} against {_twin_name(results, row.side)}: {row.case}",
                ratio=ratio,
                band=band_of(row.floor, row.unit),
                text=f"{ratio_words}, {floor_words}",
            )
        )
    order = list(dict.fromkeys(row.group for row in made))
    return tuple(sorted(made, key=lambda row: order.index(row.group)))


def layout(chart_rows: Sequence[NoiseRow]) -> list[tuple[str, NoiseRow | None]]:
    """Return the lines of the chart from the top: a heading per floor group, then its rows."""
    lines: list[tuple[str, NoiseRow | None]] = []
    group: str | None = None
    for row in chart_rows:
        if row.group != group:
            group = row.group
            lines.append((f"floor group: {group}", None))
        lines.append((row.label, row))
    return lines


def draw(chart_rows: Sequence[NoiseRow]) -> bytes:
    """Draw the noise chart of the given rows and return the SVG bytes."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import NullLocator

    values: list[float] = []
    for row in chart_rows:
        if row.ratio is not None:
            values.append(row.ratio)
        if row.band is not None:
            values.extend(end for end in row.band if end > 0)
    low, high = log_limits(values)
    lines = layout(chart_rows)
    count = len(lines)
    with drawing():
        figure = new_figure(WIDTH, BASE_HEIGHT + ROW_HEIGHT * count)
        axes = figure.add_subplot()
        axes.set_xscale("log")
        for index, (_label, shown) in enumerate(lines):
            if shown is None:
                continue
            if shown.band is not None:
                start, end = max(shown.band[0], low), min(shown.band[1], high)
                axes.barh(index, end - start, left=start, height=0.5, color=BAND, linewidth=0)
            if shown.ratio is not None:
                axes.plot(
                    [shown.ratio],
                    [index],
                    marker="D",
                    markersize=7,
                    linestyle="none",
                    color=PALETTE[0],
                    markeredgecolor=INK,
                )
        axes.axvline(1.0, color=INK, linewidth=1.0, linestyle="--")
        axes.set_xlim(low, high)
        ticks = log_ticks(high)
        axes.set_xticks([value for value, _ in ticks], labels=[text for _, text in ticks])
        axes.xaxis.set_minor_locator(NullLocator())
        axes.set_yticks(range(count), labels=[label for label, _ in lines])
        for tick, (_label, heading) in zip(axes.get_yticklabels(), lines, strict=True):
            if heading is None:
                tick.set_fontweight("bold")
        axes.set_ylim(count - 0.5, -0.5)
        right = axes.secondary_yaxis("right")
        right.set_ticks(range(count), labels=["" if r is None else r.text for _, r in lines])
        axes.set_xlabel("ratio of the side's median to its twin's (log scale, centred at 1)")
        axes.set_title("Noise: each side against its twin")
        handles = [
            Line2D([], [], marker="D", linestyle="none", color=PALETTE[0], markeredgecolor=INK),
            Patch(facecolor=BAND),
            Line2D([], [], linestyle="--", color=INK),
        ]
        labels = [
            "ratio of the side to its twin (median of the rounds)",
            "noise floor of the side",
            "no difference (1x)",
        ]
        figure.legend(handles, labels, loc="outside lower center", ncols=3, frameon=False)
        return svg_of(figure)


def draw_all(results: Results, note: Notify) -> list[tuple[str, bytes]]:
    """Return the noise chart's file and bytes, or nothing and a note when the run had no twins."""
    chart_rows = rows(results)
    if not chart_rows:
        note(
            NOTE_CHART_WITHOUT_DATA,
            "noise chart not drawn: the run had no twins, so the results hold no "
            "same-against-same row",
        )
        return []
    return [(model.chart_file("noise"), draw(chart_rows))]
