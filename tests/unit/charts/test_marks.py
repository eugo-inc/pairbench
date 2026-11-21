# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The marks each chart draws: the scale, the bands, the markers and the gaps.

The figure a chart draws is taken before it is written as SVG, so each test
reads the marks themselves. Every test here needs the plot extra and carries
the marker ``needs_plot``.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from pairbench.charts import noise, resources, rounds, verdict
from pairbench.model import Results

pytestmark = pytest.mark.needs_plot


@pytest.fixture
def figures(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Keep each figure a chart draws, in place of writing it as SVG."""
    kept: list[Any] = []

    def keep(figure: Any) -> bytes:
        kept.append(figure)
        return b""

    for module in (verdict, rounds, noise, resources):
        monkeypatch.setattr(module, "svg_of", keep)
    return kept


def spans(axes: Any) -> list[tuple[float, float, float]]:
    """Return each bar of an axes as (start, end, row), rounded to four decimals."""
    return [
        (
            round(float(p.get_x()), 4),
            round(float(p.get_x() + p.get_width()), 4),
            float(p.get_y() + p.get_height() / 2),
        )
        for p in axes.patches
    ]


def points(axes: Any, marker: str) -> list[tuple[float, float]]:
    """Return the single points drawn with a marker, as (x, y)."""
    return [
        (float(line.get_xdata()[0]), float(line.get_ydata()[0]))
        for line in axes.lines
        if line.get_marker() == marker and len(line.get_xdata()) == 1
    ]


def test_the_verdict_chart_is_logarithmic_with_a_band_and_a_marker_per_row(
    chart_results: Results, figures: list[Any]
) -> None:
    verdict.draw(verdict.rows(chart_results))
    axes = figures[0].axes[0]
    assert axes.get_xscale() == "log"
    low, high = axes.get_xlim()
    assert low * high == pytest.approx(1.0)
    assert spans(axes) == [(0.982, 1.018, 0.0), (0.982, 1.018, 1.0)]
    assert points(axes, "o") == [(0.8, 0.0), (1.25, 1.0)]
    centre = [line for line in axes.lines if line.get_linestyle() == "--"]
    assert [list(map(float, line.get_xdata())) for line in centre] == [[1.0, 1.0]]


def test_a_round_chart_marks_disturbed_rounds_with_a_shape_no_entry_uses(
    chart_results: Results, figures: list[Any]
) -> None:
    rounds.draw(rounds.plan(chart_results, 12).charts[0])
    axes = figures[0].axes[0]
    entries = [line for line in axes.lines if len(line.get_xdata()) == 4]
    assert [(line.get_marker(), line.get_linestyle()) for line in entries] == [
        ("o", "-"),
        ("s", "--"),
        ("^", "-."),
        ("D", ":"),
    ]
    disturbed = [line for line in axes.lines if line not in entries]
    assert {line.get_marker() for line in disturbed} == {"X"}
    assert "X" not in {line.get_marker() for line in entries}
    assert [(float(line.get_xdata()[0]), float(line.get_ydata()[0])) for line in disturbed] == [
        (3.0, 2.2),
        (3.0, 2.3),
        (3.0, 2.6),
        (3.0, 2.7),
    ]


def test_a_round_without_a_value_is_a_gap_in_its_line(
    chart_results: Results, figures: list[Any]
) -> None:
    rounds.draw(rounds.plan(chart_results, 12).charts[0])
    twin = figures[0].axes[0].lines[6]
    values = [float(v) for v in twin.get_ydata()]
    assert math.isnan(values[1])
    assert [values[0], values[2], values[3]] == [2.4, 2.7, 2.41]


def test_the_noise_chart_draws_each_floor_band_and_ratio_on_a_log_axis(
    chart_results: Results, figures: list[Any]
) -> None:
    noise.draw(noise.rows(chart_results))
    axes = figures[0].axes[0]
    assert axes.get_xscale() == "log"
    assert spans(axes) == [(0.996, 1.004, 1.0), (0.993, 1.007, 2.0), (0.98, 1.02, 4.0)]
    assert points(axes, "D") == [(1.004, 1.0), (0.993, 2.0), (1.02, 4.0)]


def test_the_resource_chart_draws_each_median_as_a_bar(
    chart_results: Results, figures: list[Any]
) -> None:
    resources.draw(resources.panels(chart_results))
    widths = [[float(p.get_width()) for p in axes.patches] for axes in figures[0].axes]
    assert widths == [[8.0, 1.0], [1.0e9, 2.0e9]]
