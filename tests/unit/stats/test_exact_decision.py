# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Verdicts are decided on exact fractions: the Holm multiply and the compare with alpha.

Each test feeds a p-value, as an exact fraction, for which the float multiply
or the float compare gives the other answer than exact arithmetic. The
fractions have the denominator ``2**64`` of a sign test of 64 untied rounds;
the sign test is replaced where a whole grading is run, so that a test does
not need a run of that length. The floats a grading writes keep their values.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from pairbench.model import STRICT, Case, Floors, Rule, min_rounds
from pairbench.plan import most_primary_cases, rounds_to_agree
from pairbench.stats import analyse, rules
from pairbench.stats.rules import Grid, grade, is_significant
from pairbench.stats.signtest import SignTest

from .conftest import build_grid

WHOLE = 2**64
ONE_TWENTIETH = Fraction(1, 20)
# Just above and just below 1/20; the float of each is the float 0.05.
ABOVE = Fraction(-(-WHOLE // 20), WHOLE)
BELOW = Fraction(WHOLE // 20, WHOLE)
# Three times this is just below 1/20, yet three times its float is the float 0.05.
THIRD_BELOW = Fraction(307445734561825860, WHOLE)
# Three times this is just above 1/20, and three times its float is the float 0.05.
THIRD_ABOVE = Fraction(307445734561825861, WHOLE)
# Seven times this is just above 1/20, yet seven times its float is below the float 0.05.
SEVENTH_ABOVE = Fraction(131762457669353941, WHOLE)

INCLUSIVE = Rule("made-up-inclusive", p_inclusive=True)
RAW = Rule("made-up-raw", p_source="raw")
ROUNDS = 12


def test_the_crafted_fractions_sit_where_the_floats_disagree() -> None:
    assert (float(ABOVE), float(BELOW)) == (0.05, 0.05)
    assert BELOW < ONE_TWENTIETH < ABOVE
    assert 3 * THIRD_BELOW < ONE_TWENTIETH < 3 * THIRD_ABOVE
    assert 3 * float(THIRD_BELOW) == 0.05
    assert 3 * float(THIRD_ABOVE) == 0.05
    assert 7 * SEVENTH_ABOVE > ONE_TWENTIETH
    assert 7 * float(SEVENTH_ABOVE) < 0.05


def test_a_fraction_is_compared_with_exactly_one_twentieth() -> None:
    assert is_significant(BELOW, STRICT) is True
    assert is_significant(ABOVE, STRICT) is False
    assert is_significant(ABOVE, INCLUSIVE) is False
    assert is_significant(ONE_TWENTIETH, STRICT) is False
    assert is_significant(ONE_TWENTIETH, INCLUSIVE) is True


def test_a_fraction_between_one_twentieth_and_the_float_alpha_is_not_significant() -> None:
    # The float 0.05 lies above 1/20; a p-value between the two is above alpha.
    between = ONE_TWENTIETH + Fraction(1, 10**19)
    assert between < Fraction(0.05)
    assert is_significant(between, STRICT) is False
    assert is_significant(between, INCLUSIVE) is False


def test_alpha_is_read_as_its_decimal_text() -> None:
    tenth = Rule("made-up-tenth", alpha=0.1)
    assert is_significant(Fraction(1, 10) - Fraction(1, 10**30), tenth) is True
    assert is_significant(Fraction(1, 10) + Fraction(1, 10**30), tenth) is False


def test_a_float_is_still_compared_as_a_float() -> None:
    assert is_significant(float(BELOW), STRICT) is False
    assert is_significant(float(ABOVE), INCLUSIVE) is True


# ---------------------------------------------------------------------------
# A whole grading, with the sign test replaced by a crafted fraction
# ---------------------------------------------------------------------------


def _crafted(monkeypatch: pytest.MonkeyPatch, fraction: Fraction) -> float:
    """Make every sign test of the grading give ``fraction``; return its float."""
    p = float(fraction)
    test = SignTest(
        n_lower=ROUNDS,
        n_higher=0,
        n=ROUNDS,
        p=p,
        fraction=(fraction.numerator, fraction.denominator),
    )
    monkeypatch.setattr(rules, "sign_test", lambda n_lower, n_higher: test)
    return p


def _cases(count: int) -> tuple[Case, ...]:
    return tuple(Case(id=f"c{i}", metric=f"m{i}", unit="s", kind="time") for i in range(count))


def _better_by_half(count: int) -> Grid:
    """``count`` primary cases on which the subject takes half the time in every round."""
    cases = _cases(count)
    values = {
        "new": {c.id: [1.0] * ROUNDS for c in cases},
        "old": {c.id: [2.0] * ROUNDS for c in cases},
    }
    return build_grid(values, cases=cases)


def _outcomes(monkeypatch: pytest.MonkeyPatch, fraction: Fraction, count: int, rule: Rule):  # type: ignore[no-untyped-def]
    p = _crafted(monkeypatch, fraction)
    grading = grade(_better_by_half(count), rule, floors=Floors(0.0625))
    assert grading.family_size == count
    assert {c.p_raw for c in grading.comparisons} == {p}
    return grading, {(c.outcome, c.reason) for c in grading.comparisons}


def test_seven_cases_whose_float_product_rounds_below_alpha_get_no_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grading, outcomes = _outcomes(monkeypatch, SEVENTH_ABOVE, 7, STRICT)
    assert outcomes == {("unresolved", "not_significant")}
    # The corrected p-value written is the float product.
    written = {c.p_corrected for c in grading.comparisons}
    assert written == {7 * float(SEVENTH_ABOVE)}
    assert written != {0.05}


def test_three_cases_whose_float_product_rounds_onto_alpha_get_their_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grading, outcomes = _outcomes(monkeypatch, THIRD_BELOW, 3, STRICT)
    assert outcomes == {("better", None)}
    assert {c.p_corrected for c in grading.comparisons} == {0.05}


def test_an_inclusive_rule_gives_no_verdict_above_one_twentieth_when_the_float_is_alpha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grading, outcomes = _outcomes(monkeypatch, THIRD_ABOVE, 3, INCLUSIVE)
    assert outcomes == {("unresolved", "not_significant")}
    assert {c.p_corrected for c in grading.comparisons} == {0.05}


def test_a_raw_p_value_below_one_twentieth_whose_float_is_alpha_gives_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, outcomes = _outcomes(monkeypatch, BELOW, 3, RAW)
    assert outcomes == {("better", None)}


def test_the_twin_note_compares_the_exact_corrected_fraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = Case(id="matmul", metric="time", unit="s", kind="time")
    values = {
        "new": {"matmul": [1.0] * ROUNDS},
        "new~same": {"matmul": [1.0625] * ROUNDS},
        "old": {"matmul": [2.0] * ROUNDS},
    }
    grid = build_grid(values, cases=(case,))
    _crafted(monkeypatch, BELOW)
    below = grade(grid, STRICT)
    assert [c.p_corrected for c in below.twin_checks] == [0.05]
    assert [c.side for c in below.twin_differs()] == ["new"]
    _crafted(monkeypatch, ABOVE)
    assert grade(grid, STRICT).twin_differs() == ()


def test_the_positive_control_compares_the_exact_fraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = Case(id="matmul", metric="time", unit="s", kind="time")
    xs, ys = [2.0] * ROUNDS, [1.0] * ROUNDS
    got = list(range(1, ROUNDS + 1))
    test = SignTest(
        n_lower=0,
        n_higher=ROUNDS,
        n=ROUNDS,
        p=0.05,
        fraction=(ABOVE.numerator, ABOVE.denominator),
    )
    monkeypatch.setattr(analyse, "sign_test", lambda n_lower, n_higher: test)
    row = analyse._control_row(case, 2.0, got, xs, ys, 6, 0.25, INCLUSIVE)
    assert (row.p_raw, row.passed) == (0.05, False)
    test = SignTest(
        n_lower=0,
        n_higher=ROUNDS,
        n=ROUNDS,
        p=0.05,
        fraction=(BELOW.numerator, BELOW.denominator),
    )
    row = analyse._control_row(case, 2.0, got, xs, ys, 6, 0.25, STRICT)
    assert (row.p_raw, row.passed) == (0.05, True)


# ---------------------------------------------------------------------------
# The plan and the fewest rounds take alpha exactly too
# ---------------------------------------------------------------------------


def test_the_fewest_rounds_take_alpha_as_its_decimal_text() -> None:
    # 5404319552844595 / 2**54 is the float 0.3, which lies below 3/10: at 55
    # rounds this many cases already pass an alpha of exactly 3/10.
    assert Fraction(5404319552844595, 2**54) == Fraction(0.3)
    assert min_rounds(5404319552844595, 0.3) == 55


def test_a_power_of_two_finer_than_its_decimal_text_means_the_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2**-24 is the largest power of two whose shortest decimal text is another
    # number: 5.960464477539063e-08 lies just above it.
    alpha = 2.0**-24
    assert repr(alpha) == "5.960464477539063e-08"
    assert Fraction(repr(alpha)) > Fraction(alpha)
    assert min_rounds(1, alpha) == 25
    # 25 rounds all one way give p = 2 / 2**25 = 2**-24, below the decimal alpha.
    rule = Rule("made-up-fine", alpha=alpha, p_source="raw", min_rounds=25)
    values = {"new": {"matmul": [1.0] * 25}, "old": {"matmul": [2.0] * 25}}
    graded = grade(build_grid(values), rule, floors=Floors(0.0625)).comparisons
    assert [(c.p_raw, c.outcome) for c in graded] == [(alpha, "better")]


def test_an_inclusive_rule_fails_a_power_of_two_above_its_decimal_text() -> None:
    # 2.9802322387695312e-08 lies just below 2**-25, so p = 2**-25 does not reach
    # alpha even under an inclusive rule; the method page says so.
    alpha = 2.0**-25
    assert repr(alpha) == "2.9802322387695312e-08"
    assert Fraction(repr(alpha)) < Fraction(alpha)
    rule = Rule("made-up-fine-inclusive", alpha=alpha, p_inclusive=True, p_source="raw")
    assert is_significant(Fraction(1, 2**25), rule) is False
    assert is_significant(Fraction(1, 2**26), rule) is True
    # Every power of two from 2**-23 up reads as its own value, as the page says.
    assert [k for k in range(24) if Fraction(repr(2.0**-k)) != Fraction(2.0**-k)] == []


def test_the_plan_counts_with_alpha_as_its_decimal_text() -> None:
    # All 200 rounds agreeing passes while n * 2 / 2**200 stays below exactly 1/20.
    assert most_primary_cases(200, 1, STRICT) == -(-(2**199) // 20) - 1


def test_the_plan_takes_the_multiply_and_the_compare_exactly() -> None:
    # 145 of 190 rounds give 2 * sum(comb(190, i) for i <= 45) / 2**190; times
    # 542784042981 tests it lies just above alpha 0.1, while the float product
    # rounds onto the float 0.1, which an inclusive rule passes.
    rule = Rule("made-up-tenth", alpha=0.1, p_inclusive=True)
    assert rounds_to_agree(190, 542784042981, rule) == 146
