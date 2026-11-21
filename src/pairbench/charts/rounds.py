# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The round-by-round chart: one primary case, each lineup entry's value in every round.

Every lineup entry, twins included, is one line with its own marker shape
and line style and a legend entry with its name. A round set aside as
disturbed is marked on top of each line with a marker of its own and the
legend entry ``disturbed round``. The values come from ``results.series``;
a round without a value leaves a gap in its line.

One chart is drawn per primary case, in the order of the results, up to a
cap; the file of a case is ``model.chart_file("rounds", name)`` with the
name ``model.file_names`` gives the case among the primary cases, so two
cases never share a file.
"""

from __future__ import annotations

import math
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
    new_figure,
    svg_of,
    whole_number,
)
from pairbench.model import NOTE_CHART_WITHOUT_DATA, NOTE_ROUND_CHARTS_LEFT_OUT, Results

WIDTH: Final = 9.0
HEIGHT: Final = 4.8
MARKERS: Final[tuple[str, ...]] = ("o", "s", "^", "D", "v", "P", "*", "<", ">", "h")
LINE_STYLES: Final[tuple[str, ...]] = ("-", "--", "-.", ":")
# The marker of a disturbed round. No lineup entry uses it.
DISTURBED_MARKER: Final = "X"
DISTURBED_LABEL: Final = "disturbed round"


@dataclass(frozen=True)
class Line:
    """One lineup entry on a round-by-round chart.

    ``values[i]`` belongs to round ``i + 1`` and is ``None`` for a round
    without a value. ``disturbed`` names the rounds set aside as disturbed.
    """

    name: str
    values: tuple[float | None, ...]
    disturbed: tuple[int, ...]

    def disturbed_points(self) -> tuple[tuple[int, float], ...]:
        """Return each disturbed round that has a value on this line, with the value."""
        points: list[tuple[int, float]] = []
        for round_ in self.disturbed:
            if 1 <= round_ <= len(self.values):
                value = self.values[round_ - 1]
                if value is not None:
                    points.append((round_, value))
        return tuple(points)


@dataclass(frozen=True)
class RoundChart:
    """The round-by-round chart of one primary case: its file, its axis texts and its lines."""

    case: str
    file: str
    metric: str
    unit: str
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class RoundPlan:
    """Which round-by-round charts are drawn.

    ``charts`` are drawn, in the order of the results. ``without_data``
    names the primary cases for which the results hold no value, and
    ``left_out`` those with values that the cap left out.
    """

    charts: tuple[RoundChart, ...]
    without_data: tuple[str, ...]
    left_out: tuple[str, ...]


def plan(results: Results, max_round_charts: int) -> RoundPlan:
    """Decide the round-by-round charts of a run.

    The primary cases are taken in the order of ``results.cases``. A case
    for which no series holds a value is not drawn. Of the others, the first
    ``max_round_charts`` are drawn and the rest are left out.
    """
    primary = [case for case in results.cases if case.primary]
    names = model.file_names(case.id for case in primary)
    with_data: list[RoundChart] = []
    without_data: list[str] = []
    for case in primary:
        lines = tuple(
            Line(name=s.name, values=s.values, disturbed=s.disturbed_rounds)
            for s in results.series
            if s.case == case.id
        )
        if not any(value is not None for line in lines for value in line.values):
            without_data.append(case.id)
            continue
        with_data.append(
            RoundChart(
                case=case.id,
                file=model.chart_file("rounds", names[case.id]),
                metric=case.metric,
                unit=case.unit,
                lines=lines,
            )
        )
    cap = max(max_round_charts, 0)
    return RoundPlan(
        charts=tuple(with_data[:cap]),
        without_data=tuple(without_data),
        left_out=tuple(chart.case for chart in with_data[cap:]),
    )


def draw(chart: RoundChart) -> bytes:
    """Draw one round-by-round chart and return the SVG bytes."""
    from matplotlib.artist import Artist
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    with drawing():
        figure = new_figure(WIDTH, HEIGHT)
        axes = figure.add_subplot()
        handles: list[Artist] = []
        labels: list[str] = []
        disturbed_shown = False
        divisor = axis_divisor(value for line in chart.lines for value in line.values)
        for index, line in enumerate(chart.lines):
            colour = PALETTE[index % len(PALETTE)]
            rounds = list(range(1, len(line.values) + 1))
            values = [math.nan if value is None else value / divisor for value in line.values]
            (artist,) = axes.plot(
                rounds,
                values,
                marker=MARKERS[index % len(MARKERS)],
                linestyle=LINE_STYLES[index % len(LINE_STYLES)],
                color=colour,
                markersize=6,
            )
            handles.append(artist)
            labels.append(line.name)
            points = line.disturbed_points()
            if points:
                axes.plot(
                    [round_ for round_, _ in points],
                    [value / divisor for _, value in points],
                    marker=DISTURBED_MARKER,
                    markersize=11,
                    linestyle="none",
                    color=INK,
                )
                disturbed_shown = True
        if disturbed_shown:
            handles.append(
                Line2D([], [], marker=DISTURBED_MARKER, markersize=11, linestyle="none", color=INK)
            )
            labels.append(DISTURBED_LABEL)
        axes.xaxis.set_major_locator(MaxNLocator(integer=True))
        axes.xaxis.set_major_formatter(FuncFormatter(whole_number))
        axes.yaxis.set_major_formatter(FuncFormatter(axis_number(divisor)))
        axes.set_xlabel("round")
        axes.set_ylabel(f"{chart.metric} ({chart.unit})" if chart.unit else chart.metric)
        axes.set_title(f"Round by round: {chart.case}")
        figure.legend(
            handles,
            labels,
            loc="outside lower center",
            ncols=min(len(labels), 4),
            frameon=False,
        )
        return svg_of(figure)


def draw_all(results: Results, max_round_charts: int, note: Notify) -> list[tuple[str, bytes]]:
    """Return the file and bytes of each round-by-round chart, and a note for each one left out."""
    decided = plan(results, max_round_charts)
    for case in decided.without_data:
        note(
            NOTE_CHART_WITHOUT_DATA,
            f"round-by-round chart of case {case} not drawn: the results hold no value for it",
        )
    if decided.left_out:
        note(NOTE_ROUND_CHARTS_LEFT_OUT, left_out_message(len(decided.charts), decided.left_out))
    return [(chart.file, draw(chart)) for chart in decided.charts]


def left_out_message(drawn: int, left_out: Sequence[str]) -> str:
    """Return the note that says how many round-by-round charts the cap left out."""
    return (
        f"round-by-round charts were drawn for {drawn} primary cases and not for "
        f"{len(left_out)} more; raise plots.max_round_charts to draw them"
    )
