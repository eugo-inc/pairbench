# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Holm correction, of floats and of exact fractions: known answers, as constants."""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from pairbench.stats.holm import holm, holm_exact


@pytest.mark.parametrize(
    ("raw", "adjusted"),
    [
        ([0.01, 0.04, 0.5], [0.03, 0.08, 0.5]),
        ([0.01, 0.012, 0.5], [0.03, 0.03, 0.5]),
        ([0.01, 0.04, 0.03], [0.03, 0.06, 0.06]),
        ([0.03125, 0.03125, 0.21875], [0.09375, 0.09375, 0.21875]),
    ],
)
def test_the_known_answers(raw: list[float], adjusted: list[float]) -> None:
    assert holm(raw) == pytest.approx(adjusted, abs=1e-15)


def test_the_running_maximum_keeps_a_larger_raw_value_from_a_smaller_adjustment() -> None:
    # Without the monotone step, 0.04 would be adjusted to 1 * 0.04.
    assert holm([0.04, 0.01, 0.03]) == pytest.approx([0.06, 0.03, 0.06], abs=1e-15)


def test_values_come_back_in_the_order_given() -> None:
    assert holm([0.5, 0.01]) == pytest.approx([0.5, 0.02], abs=1e-15)


def test_an_adjusted_value_never_exceeds_one() -> None:
    assert holm([0.6, 0.7]) == [1.0, 1.0]


def test_one_value_is_unchanged_and_none_gives_none() -> None:
    assert holm([0.2]) == [0.2]
    assert holm([]) == []


@pytest.mark.parametrize("bad", [-0.1, 1.5, math.nan, math.inf, True, "0.1"])
def test_a_value_that_is_no_p_value_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="p-value"):
        holm([0.1, bad])  # type: ignore[list-item]


@pytest.mark.parametrize(
    ("raw", "adjusted"),
    [
        (["1/100", "1/25", "1/2"], ["3/100", "2/25", "1/2"]),
        (["1/100", "3/250", "1/2"], ["3/100", "3/100", "1/2"]),
        (["1/100", "1/25", "3/100"], ["3/100", "3/50", "3/50"]),
        (["1/32", "1/32", "7/32"], ["3/32", "3/32", "7/32"]),
        (["1/25", "1/100", "3/100"], ["3/50", "3/100", "3/50"]),
        (["3/5", "7/10"], ["1", "1"]),
        (["1/5"], ["1/5"]),
        ([], []),
    ],
)
def test_the_exact_correction_gives_the_known_answers_as_fractions(
    raw: list[str], adjusted: list[str]
) -> None:
    assert holm_exact([Fraction(p) for p in raw]) == [Fraction(a) for a in adjusted]


def test_the_exact_correction_sorts_by_the_exact_value() -> None:
    # Two values whose floats are equal: the smaller one is multiplied by 2.
    small = Fraction(2**64 // 20, 2**64)
    large = Fraction(-(-(2**64) // 20), 2**64)
    assert float(small) == float(large)
    assert holm_exact([large, small]) == [2 * small, 2 * small]


def test_the_exact_correction_keeps_the_floats_of_holm_unchanged() -> None:
    # Seven times this fraction lies above 1/20, while seven times its float lies below 0.05.
    p = Fraction(131762457669353941, 2**64)
    floats = holm([float(p)] * 7)
    exact = holm_exact([p] * 7)
    assert floats == [7 * float(p)] * 7
    assert all(f < 0.05 for f in floats)
    assert exact == [7 * p] * 7
    assert all(e > Fraction(1, 20) for e in exact)


@pytest.mark.parametrize("bad", [0.1, Fraction(-1, 10), Fraction(3, 2), 1])
def test_a_value_that_is_no_exact_p_value_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="p-value"):
        holm_exact([Fraction(1, 10), bad])  # type: ignore[list-item]
