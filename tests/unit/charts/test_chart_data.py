# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the charts show, decided without drawing: texts, axes, rows, panels and files.

None of these tests needs the plot extra.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

import pytest

from pairbench.charts import (
    LARGEST_REACH,
    SMALLEST_REACH,
    band_of,
    bar_text,
    change_text,
    floor_text,
    log_limits,
    log_ticks,
    median_text,
    noise,
    number_text,
    p_text,
    ratio_text,
    resources,
    rounds,
    verdict,
)
from pairbench.model import Diagnostics, Results

# ---------------------------------------------------------------------------
# Texts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ratio", "kind", "text"),
    [
        (0.8, "time", "1.25x faster"),
        (1.04, "time", "1.04x slower"),
        (0.5, "other", "2.00x lower"),
        (1.26, "count", "1.26x higher"),
        (1.0, "time", "1.00x"),
        (None, "time", "no ratio"),
        (-0.5, "time", "-0.50x"),
        (0.0, "other", "0.00x"),
    ],
)
def test_the_change_in_words(ratio: float | None, kind: str, text: str) -> None:
    assert change_text(ratio, kind) == text


def test_the_texts_of_a_ratio_a_bar_a_floor_a_p_value_and_a_median() -> None:
    assert ratio_text(0.797) == "0.80x"
    assert bar_text(0.018, "fraction") == "±1.8%"
    assert bar_text(1.8, "percent") == "±1.8%"
    assert floor_text(0.011, "fraction") == "1.1%"
    assert floor_text(1.1, "percent") == "1.1%"
    assert p_text(0.001) == "0.0010"
    assert p_text(0.23) == "0.23"
    assert p_text(0.00003) == "3.0e-05"
    assert median_text(1.9234, "s") == "1.92 s"
    assert median_text(7.8, "") == "7.80"
    assert number_text(2410000000) == "2410000000"
    assert number_text(0.0005) == "0.000500"
    assert number_text(0) == "0"


# ---------------------------------------------------------------------------
# The ratio axis
# ---------------------------------------------------------------------------


def test_a_ratio_and_its_inverse_sit_equally_far_from_the_centre() -> None:
    assert log_limits([2.0]) == log_limits([0.5])
    low, high = log_limits([2.0])
    assert low * high == pytest.approx(1.0)
    assert high == pytest.approx(math.exp(math.log(2.0) * 1.15))


def test_the_ratio_axis_shows_at_least_its_smallest_reach() -> None:
    assert SMALLEST_REACH == 1.25
    assert log_limits([]) == pytest.approx((0.8, 1.25))
    assert log_limits([1.01]) == pytest.approx((0.8, 1.25))
    assert log_limits([0.0, -2.0, math.inf]) == pytest.approx((0.8, 1.25))


def test_the_ratio_axis_ends_stay_finite_for_ratios_far_out() -> None:
    assert LARGEST_REACH == 1e100
    assert log_limits([1e300]) == pytest.approx((1e-100, 1e100))
    assert log_limits([5e-324]) == pytest.approx((1e-100, 1e100))
    assert log_limits([1.0 + 1e308]) == pytest.approx((1e-100, 1e100))
    assert [text for _, text in log_ticks(1e100)] == ["0.001x", "1x", "1000x"]


def test_a_ratio_of_a_million_or_more_is_written_with_an_exponent() -> None:
    assert ratio_text(999999.99) == "999999.99x"
    assert ratio_text(1e6) == "1e+06x"
    assert ratio_text(2.5e7) == "2.5e+07x"
    assert change_text(1e-300, "time") == "1e+300x faster"
    assert change_text(0.8, "time", better="higher") == "1.25x lower"
    assert change_text(1.25, "time", better="higher") == "1.25x higher"
    assert change_text(1e300, "other") == "1e+300x higher"


def test_the_marks_of_the_ratio_axis_are_symmetric_about_one() -> None:
    marks = log_ticks(1.25)
    assert [text for _, text in marks] == ["0.8x", "0.909x", "1x", "1.1x", "1.25x"]
    assert [value for value, _ in marks] == pytest.approx([0.8, 1 / 1.1, 1.0, 1.1, 1.25])
    wide = log_ticks(2.3)
    assert [text for _, text in wide] == ["0.5x", "0.667x", "1x", "1.5x", "2x"]
    many = log_ticks(12.0)
    assert [text for _, text in many] == ["0.1x", "0.2x", "0.333x", "1x", "3x", "5x", "10x"]
    assert [text for _, text in log_ticks(2000.0)] == ["0.001x", "0.01x", "1x", "100x", "1000x"]
    assert [text for _, text in log_ticks(1e12)] == ["0.001x", "1x", "1000x"]


@pytest.mark.parametrize(
    ("bar", "unit", "band"),
    [
        (0.018, "fraction", (0.982, 1.018)),
        (1.8, "percent", (0.982, 1.018)),
        (0.0, "fraction", (1.0, 1.0)),
        (1.5, "fraction", (-0.5, 2.5)),
    ],
)
def test_the_noise_band_runs_from_one_minus_the_bar_to_one_plus_it(
    bar: float, unit: str, band: tuple[float, float]
) -> None:
    assert band_of(bar, unit) == pytest.approx(band)


def test_a_missing_or_negative_bar_gives_no_band() -> None:
    assert band_of(None, "fraction") is None
    assert band_of(-0.1, "fraction") is None
    assert band_of(math.nan, "fraction") is None


# ---------------------------------------------------------------------------
# The verdict chart
# ---------------------------------------------------------------------------


def test_the_verdict_chart_has_one_row_per_primary_case_and_subject(
    chart_results: Results,
) -> None:
    assert verdict.rows(chart_results) == (
        verdict.VerdictRow(
            label="matmul: new vs old",
            ratio=0.8,
            band=pytest.approx((0.982, 1.018)),  # type: ignore[arg-type]
            change="1.25x faster",
            verdict="FASTER",
            outcome="better",
        ),
        verdict.VerdictRow(
            label="c32/ttft_ms: new vs old",
            ratio=1.25,
            band=pytest.approx((0.982, 1.018)),  # type: ignore[arg-type]
            change="1.25x slower",
            verdict="SLOWER",
            outcome="worse",
        ),
    )


def test_a_row_without_a_ratio_has_no_marker_and_says_why(
    chart_document: dict[str, Any],
) -> None:
    for comparison in chart_document["comparisons"][:2]:
        comparison.update(
            ratio=None if comparison["case"] == "matmul" else -1.0,
            bar=None,
            verdict="NO VERDICT",
            outcome="no_verdict",
            reason="nonpositive_value",
            reasons=["nonpositive_value"],
        )
    chart_rows = verdict.rows(Results.from_json(chart_document))
    assert [(r.ratio, r.band, r.change, r.verdict) for r in chart_rows] == [
        (None, None, "no ratio", "NO VERDICT (nonpositive_value)"),
        (None, None, "-1.00x", "NO VERDICT (nonpositive_value)"),
    ]


def test_an_unresolved_row_names_its_reason(chart_document: dict[str, Any]) -> None:
    chart_document["comparisons"][0].update(
        verdict="UNRESOLVED", outcome="unresolved", reason="inside_noise", reasons=["inside_noise"]
    )
    assert verdict.rows(Results.from_json(chart_document))[0].verdict == "UNRESOLVED (inside_noise)"


def test_the_axis_of_the_verdict_chart_holds_every_ratio_and_band_end() -> None:
    chart_rows = [
        verdict.VerdictRow("a", 0.25, (0.9, 1.1), "4.00x faster", "FASTER", "better"),
        verdict.VerdictRow("b", None, (-0.5, 2.5), "no ratio", "NO VERDICT", "no_verdict"),
    ]
    low, high = verdict.limits(chart_rows)
    assert low * high == pytest.approx(1.0)
    assert high == pytest.approx(math.exp(math.log(4.0) * 1.15))


# ---------------------------------------------------------------------------
# The round-by-round charts
# ---------------------------------------------------------------------------


def test_each_primary_case_with_values_gets_a_round_chart_in_the_order_of_the_results(
    chart_results: Results,
) -> None:
    decided = rounds.plan(chart_results, 12)
    assert [(c.case, c.file, c.metric, c.unit) for c in decided.charts] == [
        ("matmul", "charts/rounds.matmul.svg", "time", "s"),
        ("c32/ttft_ms", "charts/rounds.c32_ttft_ms.svg", "ttft_ms", "ms"),
    ]
    assert [line.name for line in decided.charts[0].lines] == ["new", "new~same", "old", "old~same"]
    assert decided.charts[0].lines[3].values == (2.4, None, 2.7, 2.41)
    assert decided.without_data == ()
    assert decided.left_out == ()


def test_two_cases_written_alike_in_a_file_name_get_different_files(
    chart_document: dict[str, Any],
) -> None:
    case = chart_document["cases"][0]
    chart_document["cases"] = [dict(case, id="a/b"), dict(case, id="a_b")]
    chart_document["series"] = [
        {"case": "a/b", "name": "new", "values": [1.0], "disturbed_rounds": []},
        {"case": "a_b", "name": "new", "values": [2.0], "disturbed_rounds": []},
    ]
    decided = rounds.plan(Results.from_json(chart_document), 12)
    assert [(c.case, c.file) for c in decided.charts] == [
        ("a/b", "charts/rounds.a_b-2.svg"),
        ("a_b", "charts/rounds.a_b.svg"),
    ]


def test_round_charts_beyond_the_cap_are_left_out_and_counted(
    chart_document: dict[str, Any],
) -> None:
    case = chart_document["cases"][0]
    chart_document["cases"] = [dict(case, id=f"case-{i}") for i in range(4)]
    chart_document["series"] = [
        {"case": f"case-{i}", "name": "new", "values": [1.0, 2.0], "disturbed_rounds": []}
        for i in range(4)
    ]
    decided = rounds.plan(Results.from_json(chart_document), 2)
    assert [c.case for c in decided.charts] == ["case-0", "case-1"]
    assert decided.left_out == ("case-2", "case-3")
    assert rounds.left_out_message(2, decided.left_out) == (
        "round-by-round charts were drawn for 2 primary cases and not for 2 more; "
        "raise plots.max_round_charts to draw them"
    )
    assert rounds.plan(Results.from_json(chart_document), 0).left_out == (
        "case-0",
        "case-1",
        "case-2",
        "case-3",
    )


def test_a_primary_case_without_any_value_has_no_round_chart(
    chart_document: dict[str, Any],
) -> None:
    chart_document["series"] = [
        s if s["case"] == "matmul" else dict(s, values=[None, None])
        for s in chart_document["series"]
    ]
    decided = rounds.plan(Results.from_json(chart_document), 1)
    assert [c.case for c in decided.charts] == ["matmul"]
    assert decided.without_data == ("c32/ttft_ms",)
    assert decided.left_out == ()


def test_a_disturbed_round_is_marked_only_where_the_line_has_a_value() -> None:
    line = rounds.Line(name="old~same", values=(2.4, None, 2.7), disturbed=(2, 3, 9))
    assert line.disturbed_points() == ((3, 2.7),)


# ---------------------------------------------------------------------------
# The noise chart
# ---------------------------------------------------------------------------


def test_the_noise_chart_groups_each_side_against_its_twin_by_floor_group(
    chart_results: Results,
) -> None:
    chart_rows = noise.rows(chart_results)
    assert [(r.group, r.label, r.ratio, r.text) for r in chart_rows] == [
        (
            "metric time, primary cases",
            "new against new~same: matmul",
            1.004,
            "1.004x, floor ±0.4%",
        ),
        (
            "metric time, primary cases",
            "old against old~same: matmul",
            0.993,
            "0.993x, floor ±0.7%",
        ),
        (
            "metric ttft_ms, primary cases",
            "new against new~same: c32/ttft_ms",
            1.02,
            "1.020x, floor ±2.0%",
        ),
    ]
    assert chart_rows[0].band == pytest.approx((0.996, 1.004))
    assert [label for label, _ in noise.layout(chart_rows)] == [
        "floor group: metric time, primary cases",
        "new against new~same: matmul",
        "old against old~same: matmul",
        "floor group: metric ttft_ms, primary cases",
        "new against new~same: c32/ttft_ms",
    ]


def test_a_case_with_a_group_of_its_own_is_shown_under_that_group(
    chart_document: dict[str, Any],
) -> None:
    chart_document["cases"][1]["group"] = "made-up-group"
    chart_document["same_vs_same"].append(
        {"side": "old", "case": "matmul", "ratio": None, "floor": None, "p_raw": None, "n": 0}
    )
    chart_rows = noise.rows(Results.from_json(chart_document))
    assert [r.group for r in chart_rows] == [
        "metric time, primary cases",
        "metric time, primary cases",
        "metric time, primary cases",
        "made-up-group",
    ]
    assert (chart_rows[2].ratio, chart_rows[2].band, chart_rows[2].text) == (
        None,
        None,
        "no ratio, no floor",
    )


def test_a_run_without_twins_has_no_noise_rows(chart_document: dict[str, Any]) -> None:
    chart_document["same_vs_same"] = []
    assert noise.rows(Results.from_json(chart_document)) == ()


# ---------------------------------------------------------------------------
# The resource chart
# ---------------------------------------------------------------------------


def test_the_resource_chart_has_a_panel_per_res_case_with_each_sides_median(
    chart_results: Results,
) -> None:
    assert resources.panels(chart_results) == (
        resources.Panel(
            case="res/cores",
            unit="cores",
            bars=(resources.Bar("new", 8.0), resources.Bar("old", 1.0)),
            outcomes="new against old: HIGHER",
        ),
        resources.Panel(
            case="res/rss_peak",
            unit="bytes",
            bars=(resources.Bar("new", 1.0e9), resources.Bar("old", 2.0e9)),
            outcomes="new against old: LOWER",
        ),
    )


def test_with_several_subjects_the_baseline_comes_last(chart_document: dict[str, Any]) -> None:
    second = copy.deepcopy(chart_document["comparisons"][2])
    second.update(subject="newer", subject_median=4.0)
    chart_document["comparisons"].insert(3, second)
    side = chart_document["sides"][0]
    chart_document["sides"].append(dict(side, name="newer"))
    panel = resources.panels(Results.from_json(chart_document))[0]
    assert panel.bars == (
        resources.Bar("new", 8.0),
        resources.Bar("newer", 4.0),
        resources.Bar("old", 1.0),
    )
    assert panel.outcomes == "new against old: HIGHER; newer against old: HIGHER"


def test_without_res_comparisons_the_diagnostics_document_gives_the_medians(
    chart_document: dict[str, Any], example_diagnostics: dict[str, Any]
) -> None:
    chart_document["comparisons"] = chart_document["comparisons"][:2]
    results = Results.from_json(chart_document)
    assert resources.panels(results) == ()
    document = Diagnostics.from_json(example_diagnostics)
    assert resources.panels(results, document) == (
        resources.Panel(
            case="res/cores",
            unit="cores",
            bars=(resources.Bar("new", 7.8), resources.Bar("old", 1.0)),
            outcomes="new against old: HIGHER",
        ),
    )


def test_a_res_case_without_any_median_has_no_panel(chart_document: dict[str, Any]) -> None:
    chart_document["comparisons"][2].update(subject_median=None, baseline_median=None)
    assert [p.case for p in resources.panels(Results.from_json(chart_document))] == ["res/rss_peak"]


# ---------------------------------------------------------------------------
# Writing the files
# ---------------------------------------------------------------------------


def test_a_failed_write_removes_the_files_the_call_wrote(tmp_path: Path) -> None:
    from pairbench.charts import _write

    (tmp_path / "charts" / "noise.svg").mkdir(parents=True)
    with pytest.raises(IsADirectoryError):
        _write(tmp_path, [("charts/verdict.svg", b"<svg/>"), ("charts/noise.svg", b"<svg/>")])
    assert sorted(p.name for p in (tmp_path / "charts").iterdir()) == ["noise.svg"]
    assert (tmp_path / "charts" / "noise.svg").is_dir()


def test_written_files_are_returned_in_the_order_given(tmp_path: Path) -> None:
    from pairbench.charts import _write

    paths = _write(tmp_path, [("charts/b.svg", b"b"), ("charts/a.svg", b"a")])
    assert paths == [tmp_path / "charts/b.svg", tmp_path / "charts/a.svg"]
    assert [p.read_bytes() for p in paths] == [b"b", b"a"]
