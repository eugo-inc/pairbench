# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The figures map of a results document and the text forms of the reports."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

import pairbench
from pairbench.api import ReportOptions
from pairbench.charts import noise
from pairbench.errors import Refusal
from pairbench.model import REASON_TOO_FAR_APART, Floors, Results
from pairbench.report import comparison_reason_words
from pairbench.report.fill import fill_text
from pairbench.results import figures
from pairbench.results.figures import (
    bar_text,
    change_text,
    floor_text,
    median_text,
    number_text,
    p_text,
    percent_text,
    ratio_text,
    with_figures,
    writable_percent,
)
from pairbench.stats.selftest import synthetic_capture

# The figures of the example results document of the format (made-up numbers):
# key -> (value, text).
EXAMPLE_FIGURES: dict[str, tuple[Any, str]] = {
    "matmul.new_vs_old.ratio": (0.797, "0.80x"),
    "matmul.new_vs_old.statistic": (0.797, "0.80x"),
    "matmul.new_vs_old.speedup": (pytest.approx(1.2547051442910915), "1.25x"),
    "matmul.new_vs_old.percent": (pytest.approx(-20.3), "-20.3%"),
    "matmul.new_vs_old.p": (0.0005, "0.00050"),
    "matmul.new_vs_old.p_corrected": (0.001, "0.0010"),
    "matmul.new_vs_old.bar": (0.018, "±1.8%"),
    "matmul.new_vs_old.floor_subject": (0.011, "1.1%"),
    "matmul.new_vs_old.floor_baseline": (0.007, "0.7%"),
    "matmul.new_vs_old.n": (16, "16"),
    "matmul.new_vs_old.verdict": ("better", "FASTER"),
    "matmul.new.median": (1.92, "1.92 s"),
    "matmul.old.median": (2.41, "2.41 s"),
    "launch_cost.median": (0.0005, "0.000500 s"),
    "launch_cost.spread": (pytest.approx(0.0003), "0.000300 s"),
}

NO_FLOOR: dict[str, Any] = {
    "source": "twins",
    "unit": "fraction",
    "subject": None,
    "baseline": None,
    "mode": "NONE",
}


def _pairs(results: Results) -> dict[str, tuple[Any, str]]:
    return {key: (figure.value, figure.text) for key, figure in results.figures.items()}


def test_the_example_document_gives_every_figure_of_the_format(build: Any) -> None:
    filled = with_figures(build(figures={}))
    assert _pairs(filled) == EXAMPLE_FIGURES
    assert list(filled.figures) == list(EXAMPLE_FIGURES)


def test_with_figures_changes_nothing_but_the_figures(build: Any) -> None:
    before = build(figures={})
    after = with_figures(before)
    assert dataclasses.replace(after, figures={}) == before
    left, right = before.to_json(), after.to_json()
    assert [key for key in left if left[key] != right[key]] == ["figures"]


def test_a_map_already_held_is_replaced(build: Any) -> None:
    stale = build(figures={"made.up.key": {"value": 1.0, "text": "1.0"}})
    assert "made.up.key" not in with_figures(stale).figures


def test_rounding_happens_only_in_the_text(build: Any) -> None:
    filled = with_figures(build(comparisons=[{"ratio": 0.79654321, "statistic": 0.79654321}]))
    ratio = filled.figures["matmul.new_vs_old.ratio"]
    assert ratio.value == 0.79654321
    assert ratio.text == "0.80x"


def test_a_describing_case_gives_higher_and_no_speedup(build: Any) -> None:
    resource = {
        "case": "res/cores",
        "primary": False,
        "subject_median": 7.8,
        "baseline_median": 1.0,
        "ratio": 7.8,
        "statistic": 7.8,
        "p_corrected": None,
        "verdict": "HIGHER",
        "outcome": "higher",
        "sensitivity": {"rounds_set_aside": [], "ratio": 7.8, "outcome": "higher", "agrees": True},
    }
    filled = with_figures(
        build(comparisons=[resource], cases=(("res/cores", "cores", "none", "other", False),))
    )
    pairs = _pairs(filled)
    assert pairs["res/cores.new_vs_old.verdict"] == ("higher", "HIGHER")
    assert pairs["res/cores.new_vs_old.ratio"] == (7.8, "7.80x")
    assert pairs["res/cores.new_vs_old.percent"] == (pytest.approx(680.0), "+680.0%")
    assert pairs["res/cores.new.median"] == (7.8, "7.80 cores")
    assert pairs["res/cores.old.median"] == (1.0, "1.00 cores")
    assert "res/cores.new_vs_old.speedup" not in pairs
    assert "res/cores.new_vs_old.p_corrected" not in pairs


def test_a_lower_outcome_of_a_describing_case(build: Any) -> None:
    resource = {
        "case": "res/rss_peak",
        "primary": False,
        "subject_median": 500.0,
        "baseline_median": 1000.0,
        "ratio": 0.5,
        "statistic": 0.5,
        "verdict": "LOWER",
        "outcome": "lower",
    }
    filled = with_figures(
        build(comparisons=[resource], cases=(("res/rss_peak", "bytes", "none", "other", False),))
    )
    assert _pairs(filled)["res/rss_peak.new_vs_old.verdict"] == ("lower", "LOWER")


def test_where_higher_is_better_the_speedup_is_the_ratio(build: Any) -> None:
    rate = {
        "case": "tokens",
        "subject_median": 125.0,
        "baseline_median": 100.0,
        "ratio": 1.25,
        "statistic": 1.25,
        "verdict": "BETTER",
        "outcome": "better",
    }
    filled = with_figures(
        build(comparisons=[rate], cases=(("tokens", "tokens/s", "higher", "other", True),))
    )
    pairs = _pairs(filled)
    assert pairs["tokens.new_vs_old.speedup"] == (1.25, "1.25x")
    assert pairs["tokens.new_vs_old.percent"] == (pytest.approx(25.0), "+25.0%")
    assert pairs["tokens.new_vs_old.verdict"] == ("better", "BETTER")
    assert pairs["tokens.new.median"] == (125.0, "125 tokens/s")


def test_under_scale_percent_floors_and_bar_are_already_percent(build: Any) -> None:
    percent = {
        "statistic": -20.3,
        "scale": "percent",
        "gap": 20.3,
        "bar": 1.8,
        "floor": {
            "source": "twins",
            "unit": "percent",
            "subject": {
                "value": 1.1,
                "n": 16,
                "provisional": False,
                "spread": 0.02,
                "outlier_rounds": [],
            },
            "baseline": {
                "value": 0.7,
                "n": 16,
                "provisional": False,
                "spread": 0.02,
                "outlier_rounds": [],
            },
            "mode": "TWO-SIDED",
        },
    }
    pairs = _pairs(with_figures(build(comparisons=[percent])))
    assert pairs["matmul.new_vs_old.statistic"] == (-20.3, "-20.3%")
    assert pairs["matmul.new_vs_old.bar"] == (1.8, "±1.8%")
    assert pairs["matmul.new_vs_old.floor_subject"] == (1.1, "1.1%")
    assert pairs["matmul.new_vs_old.floor_baseline"] == (0.7, "0.7%")
    assert pairs["matmul.new_vs_old.ratio"] == (0.797, "0.80x")


def test_a_figure_whose_number_is_absent_is_left_out(build: Any) -> None:
    empty = {
        "n_rounds": 0,
        "n_untied": 0,
        "n_lower": 0,
        "n_higher": 0,
        "subject_median": None,
        "baseline_median": None,
        "ratio": None,
        "statistic": None,
        "gap": None,
        "floor": NO_FLOOR,
        "bar": None,
        "p_raw": None,
        "p_raw_fraction": None,
        "p_corrected": None,
        "verdict": "NO VERDICT",
        "outcome": "no_verdict",
        "reason": "too_few_rounds",
        "reasons": ["too_few_rounds"],
        "order_split": [0, 0],
    }
    filled = with_figures(build(comparisons=[empty], launch_cost=None))
    assert _pairs(filled) == {
        "matmul.new_vs_old.n": (0, "0"),
        "matmul.new_vs_old.verdict": ("no_verdict", "NO VERDICT"),
    }


@pytest.mark.parametrize(
    ("ratio", "left_out", "kept"),
    [
        (5e-324, "speedup", ("ratio", "percent")),
        (1e307, "percent", ("ratio", "speedup")),
    ],
)
def test_a_figure_that_is_no_finite_number_is_left_out(
    build: Any, ratio: float, left_out: str, kept: tuple[str, ...]
) -> None:
    filled = with_figures(build(comparisons=[{"ratio": ratio, "statistic": ratio}], figures={}))
    names = {key.rsplit(".", 1)[1] for key in filled.figures if key.startswith("matmul.new_vs")}
    assert left_out not in names
    assert set(kept) <= names


def _doubled(entry: str, case: str, round_: int, u: float) -> float:
    """new reads twice old; a twin sits 1 percent off its side in turn."""
    side = 1.0 if entry.startswith("old") else 2.0
    if entry.endswith("~same"):
        return side * (1.01 if round_ % 2 else 0.99)
    return side


# A supplied floor whose percentage is beyond the float range, and one well inside it.
FLOOR_PAST_PERCENT = 1e307
FLOOR_WRITABLE = 1e305
SUPPLIED_TOO_LARGE = "a supplied noise floor is too large to be a finite number as a percentage"


def test_a_supplied_floor_with_no_finite_percentage_has_no_figure() -> None:
    capture = synthetic_capture(_doubled, rounds=16)
    results = pairbench.analyse(capture, floors=Floors(FLOOR_PAST_PERCENT))
    assert results.comparisons[0].reason == REASON_TOO_FAR_APART
    filled = with_figures(results)
    assert "matmul.new_vs_old.floor_subject" not in filled.figures
    assert "matmul.new_vs_old.floor_baseline" not in filled.figures
    assert not any("inf" in figure.text for figure in filled.figures.values())
    kept = with_figures(pairbench.analyse(capture, floors=Floors(FLOOR_WRITABLE)))
    assert kept.figures["matmul.new_vs_old.floor_subject"].text == "1e+307%"


@pytest.mark.parametrize(
    "floors",
    [Floors(FLOOR_PAST_PERCENT), Floors({"new": FLOOR_PAST_PERCENT, "old": 0.01})],
    ids=["both", "subject"],
)
def test_a_supplied_floor_with_no_finite_percentage_is_shown_as_no_floor(floors: Floors) -> None:
    results = pairbench.analyse(synthetic_capture(_doubled, rounds=16), floors=floors)
    comparison = results.comparisons[0]
    assert comparison.reason == REASON_TOO_FAR_APART
    assert comparison.floor.subject is None
    assert comparison_reason_words(comparison) == SUPPLIED_TOO_LARGE
    for form in ("terminal", "markdown", "html"):
        text = pairbench.render(results, form, options=ReportOptions(verbose=True))
        assert re.search(r"\binf\b", text) is None, form


def test_a_bar_with_no_finite_percentage_has_no_figure(build: Any) -> None:
    filled = with_figures(build(comparisons=[{"bar": FLOOR_PAST_PERCENT}], figures={}))
    assert "matmul.new_vs_old.bar" not in filled.figures
    assert not any("inf" in figure.text for figure in filled.figures.values())


def test_a_document_with_floors_and_a_bar_past_the_float_range_shows_them_as_missing(
    build: Any, example_results: dict[str, Any]
) -> None:
    floor = example_results["comparisons"][0]["floor"]
    floor["subject"]["value"] = FLOOR_PAST_PERCENT
    same = {**example_results["same_vs_same"][0], "floor": FLOOR_PAST_PERCENT}
    results = build(
        comparisons=[{"bar": FLOOR_PAST_PERCENT, "floor": floor}],
        same_vs_same=[same],
        figures={},
    )
    for verbose in (False, True):
        options = ReportOptions(verbose=verbose)
        for form in ("terminal", "markdown", "html"):
            text = pairbench.render(results, form, options=options)
            assert re.search(r"\binf\b", text) is None, (form, verbose)
    assert noise.rows(results)[0].text.endswith(", no floor")
    assert writable_percent(FLOOR_PAST_PERCENT, "fraction") is None
    assert writable_percent(FLOOR_PAST_PERCENT, "percent") == FLOOR_PAST_PERCENT


def test_several_subjects_have_figures_each_and_the_baseline_median_once(build: Any) -> None:
    filled = with_figures(
        build(
            comparisons=[
                {"subject": "new"},
                {"subject": "newer", "subject_median": 1.5, "ratio": 0.62, "statistic": 0.62},
            ]
        )
    )
    pairs = _pairs(filled)
    assert pairs["matmul.newer_vs_old.ratio"] == (0.62, "0.62x")
    assert pairs["matmul.newer.median"] == (1.5, "1.50 s")
    assert [key for key in pairs if key.endswith(".old.median")] == ["matmul.old.median"]


def test_a_key_that_two_comparisons_would_share_is_left_out(build: Any) -> None:
    # Case "a.b" with subject "c" and case "a" with subject "b.c" give the same keys.
    filled = with_figures(
        build(
            comparisons=[
                {"case": "a.b", "subject": "c", "ratio": 0.5, "statistic": 0.5},
                {"case": "a", "subject": "b.c", "ratio": 0.9, "statistic": 0.9},
            ],
            cases=(("a.b", "s", "lower", "time", True), ("a", "s", "lower", "time", True)),
        )
    )
    shared = [key for key in filled.figures if key.startswith("a.b.c")]
    assert shared == []
    assert _pairs(filled)["a.b.old.median"] == (2.41, "2.41 s")
    with pytest.raises(Refusal) as caught:
        fill_text("{{fig:a.b.c_vs_old.ratio}}", {"": filled})
    assert (caught.value.code, caught.value.exit_code) == ("E_FIGURE_MISSING", 7)


def test_a_baseline_median_that_differs_between_its_comparisons_is_left_out(build: Any) -> None:
    filled = with_figures(
        build(
            comparisons=[
                {"subject": "new", "baseline_median": 2.41},
                {"subject": "newer", "baseline_median": 2.5},
            ]
        )
    )
    assert "matmul.old.median" not in filled.figures
    assert _pairs(filled)["matmul.new.median"] == (1.92, "1.92 s")
    assert _pairs(filled)["matmul.newer.median"] == (1.92, "1.92 s")


def test_a_key_left_out_stays_out_when_a_later_comparison_writes_it_again(build: Any) -> None:
    filled = with_figures(
        build(
            comparisons=[
                {"subject": "new", "baseline_median": 2.41},
                {"subject": "newer", "baseline_median": 2.5},
                {"subject": "newest", "baseline_median": 2.41},
            ]
        )
    )
    assert "matmul.old.median" not in filled.figures
    assert _pairs(filled)["matmul.newest.median"] == (1.92, "1.92 s")


def test_a_case_id_with_a_slash_keeps_it_in_the_key(build: Any) -> None:
    serving = {"case": "c32/ttft_ms_median", "subject_median": 41.0, "baseline_median": 50.0}
    filled = with_figures(
        build(
            comparisons=[serving],
            cases=(("c32/ttft_ms_median", "ms", "lower", "time", True),),
        )
    )
    assert _pairs(filled)["c32/ttft_ms_median.new.median"] == (41.0, "41.0 ms")


def test_n_counts_the_untied_pairs_not_the_paired_rounds(build: Any) -> None:
    tied = {"n_rounds": 16, "n_untied": 14, "n_lower": 13, "n_higher": 1}
    filled = with_figures(build(comparisons=[tied]))
    assert _pairs(filled)["matmul.new_vs_old.n"] == (14, "14")


def test_no_launch_cost_gives_no_launch_cost_figures(build: Any) -> None:
    filled = with_figures(build(launch_cost=None))
    assert "launch_cost.median" not in filled.figures
    assert "launch_cost.spread" not in filled.figures


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1.9234, "1.92"),
        (2410000000.0, "2410000000"),
        (0.0005, "0.000500"),
        (9.996, "10.0"),
        (0.000123456, "0.000123"),
        (100.0, "100"),
        (0.0, "0"),
    ],
)
def test_numbers_are_written_with_three_significant_digits(value: float, text: str) -> None:
    assert number_text(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1e300, "1.00e+300"),
        (-2.5e300, "-2.50e+300"),
        (1e15, "1.00e+15"),
        (9.996e14, "1.00e+15"),
        (9.99e14, "999000000000000"),
        (0.0000123, "1.23e-05"),
        (1e-10, "1.00e-10"),
        (5e-324, "4.94e-324"),
        (0.00009996, "0.000100"),
    ],
)
def test_very_large_and_very_small_numbers_have_the_short_form(value: float, text: str) -> None:
    assert number_text(value) == text
    assert median_text(value, "s") == f"{text} s"


@pytest.mark.parametrize(
    ("ratio", "text"),
    [
        (1e-10, "1e-10x"),
        (0.0099, "0.0099x"),
        (0.01, "0.01x"),
        (999999.99, "999999.99x"),
        (1e6, "1e+06x"),
        (2.5e7, "2.5e+07x"),
        (0.0, "0.00x"),
    ],
)
def test_a_ratio_far_from_one_has_the_short_form(ratio: float, text: str) -> None:
    assert ratio_text(ratio) == text


def test_a_change_far_from_one_has_the_short_form() -> None:
    assert change_text(1e-10, "time") == "1e+10x faster"
    assert change_text(3e9, "other") == "3e+09x higher"


def test_percentages_floors_and_bars_of_a_million_percent_or_more_have_the_short_form() -> None:
    assert percent_text(999999.94) == "+999999.9%"
    assert percent_text(1e8) == "+1e+08%"
    assert bar_text(1e4, "fraction") == "±1e+06%"
    assert floor_text(2.5e10, "percent") == "2.5e+10%"


@pytest.mark.parametrize(
    ("p", "text"),
    [
        (1.0, "1.0"),
        (0.5, "0.50"),
        (0.0005, "0.00050"),
        (0.001, "0.0010"),
        (0.00048828125, "0.00049"),
        (0.0227, "0.023"),
        (0.00003, "3.0e-05"),
        (1e-300, "1.0e-300"),
    ],
)
def test_p_values_have_two_significant_digits(p: float, text: str) -> None:
    assert p_text(p) == text


@pytest.mark.parametrize("p", [9.9e-301, 5e-324, 0.0])
def test_a_p_value_below_the_smallest_written_is_a_bound(p: float) -> None:
    assert p_text(p) == "< 1e-300"


@pytest.mark.parametrize(
    ("percent", "text"),
    [(-20.3, "-20.3%"), (5.0, "+5.0%"), (-0.04, "0.0%"), (0.04, "0.0%"), (0.0, "0.0%")],
)
def test_percentages_carry_their_sign(percent: float, text: str) -> None:
    assert percent_text(percent) == text


@pytest.mark.parametrize(
    ("ratio", "kind", "text"),
    [
        (1 / 1.26, "time", "1.26x faster"),
        (1.04, "time", "1.04x slower"),
        (1.26, "other", "1.26x higher"),
        (1 / 1.04, "other", "1.04x lower"),
        (1 / 1.04, "count", "1.04x lower"),
        (1.0, "time", "1.00x"),
    ],
)
def test_the_change_is_the_larger_of_the_ratio_and_its_inverse(
    ratio: float, kind: str, text: str
) -> None:
    assert change_text(ratio, kind) == text


@pytest.mark.parametrize(
    ("ratio", "text"), [(1 / 1.25, "1.25x lower"), (1.25, "1.25x higher"), (1.0, "1.00x")]
)
def test_a_time_case_where_higher_is_better_moves_higher_or_lower(ratio: float, text: str) -> None:
    assert change_text(ratio, "time", better="higher") == text


def test_the_other_text_forms() -> None:
    assert ratio_text(0.797) == "0.80x"
    assert bar_text(0.018, "fraction") == "±1.8%"
    assert bar_text(1.8, "percent") == "±1.8%"
    assert floor_text(0.011, "fraction") == "1.1%"
    assert floor_text(1.1, "percent") == "1.1%"
    assert median_text(1.92, "s") == "1.92 s"
    assert median_text(3.0, "") == "3.00"


def test_the_module_imports_nothing_of_the_reports() -> None:
    source = figures.__loader__.get_source(figures.__name__)  # type: ignore[union-attr]
    assert source is not None
    assert "pairbench.report" not in source
