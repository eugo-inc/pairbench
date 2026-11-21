# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The exact sign test: known answers, as constants."""

from __future__ import annotations

import math
import time

import pytest

from pairbench import model, stats
from pairbench.stats.signtest import SignTest, sign_test

# A sign test of 15000 pairs ends well within this many seconds; summing each
# binomial coefficient from scratch takes several times longer.
QUICK_S = 1.0


@pytest.mark.parametrize(
    ("n_lower", "n_higher", "fraction"),
    [
        (12, 0, (2, 4096)),
        (10, 2, (158, 4096)),
        (6, 0, (2, 64)),
        (5, 1, (14, 64)),
        (0, 2, (2, 4)),
        (0, 0, (1, 1)),
        (13, 7, (275960, 1048576)),
        (5, 0, (2, 32)),
    ],
)
def test_the_fraction_is_twice_the_tail_over_the_power_of_two_unreduced(
    n_lower: int, n_higher: int, fraction: tuple[int, int]
) -> None:
    assert sign_test(n_lower, n_higher).fraction == fraction


@pytest.mark.parametrize(
    ("n_lower", "n_higher", "p"),
    [
        (12, 0, 2 / 4096),
        (10, 2, 158 / 4096),
        (6, 0, 0.03125),
        (5, 1, 0.21875),
        (0, 2, 0.5),
        (0, 0, 1.0),
        (5, 0, 0.0625),
        (13, 7, 275960 / 1048576),
    ],
)
def test_the_known_p_values(n_lower: int, n_higher: int, p: float) -> None:
    assert sign_test(n_lower, n_higher).p == p


def test_eighteen_against_six_gives_0_0227_to_four_places() -> None:
    assert round(sign_test(18, 6).p, 4) == 0.0227


def test_no_p_below_0_05_is_reachable_with_fewer_than_six_untied_pairs() -> None:
    for n in range(6):
        for lower in range(n + 1):
            assert sign_test(lower, n - lower).p >= 0.05


def test_the_test_is_two_sided_and_symmetric() -> None:
    assert sign_test(2, 9) == SignTest(
        n_lower=2, n_higher=9, n=11, p=134 / 2048, fraction=(134, 2048)
    )
    assert sign_test(9, 2).p == sign_test(2, 9).p


def test_the_tail_is_exact_integer_arithmetic_for_many_pairs() -> None:
    result = sign_test(1000, 0)
    assert result.fraction == (2, 1 << 1000)
    assert result.p == 2.0**-999
    assert result.n == 1000


@pytest.mark.parametrize(
    ("n_lower", "n_higher"), [(0, 0), (1, 0), (0, 7), (3, 3), (5, 12), (40, 61), (250, 199)]
)
def test_the_tail_matches_the_sum_of_binomial_coefficients(n_lower: int, n_higher: int) -> None:
    n = n_lower + n_higher
    k = min(n_lower, n_higher)
    tail = sum(math.comb(n, i) for i in range(k + 1))
    assert sign_test(n_lower, n_higher).fraction == (min(2 * tail, 1 << n), 1 << n)


def test_a_long_nearly_tied_run_is_tested_quickly_and_exactly() -> None:
    # 15000 untied pairs split 7400 to 7600. Twice the lower tail is the whole
    # 2**n less the binomial coefficients between the two tails, a sum of only
    # 199 terms.
    n_lower, n_higher = 7400, 7600
    n = n_lower + n_higher
    middle = sum(math.comb(n, i) for i in range(n_lower + 1, n - n_lower))
    started = time.perf_counter()
    result = sign_test(n_lower, n_higher)
    took = time.perf_counter() - started
    assert result.fraction == ((1 << n) - middle, 1 << n)
    assert took < QUICK_S


def test_a_balanced_split_never_exceeds_one() -> None:
    assert sign_test(4, 4).fraction == (256, 256)
    assert sign_test(4, 4).p == 1.0


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3", None])
def test_a_count_that_is_no_whole_number_of_zero_or_more_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="whole number"):
        sign_test(bad, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="whole number"):
        sign_test(0, bad)  # type: ignore[arg-type]


def test_the_public_primitives_are_exported() -> None:
    assert stats.sign_test is sign_test
    assert stats.min_rounds is model.min_rounds
    assert callable(stats.holm)
    assert callable(stats.paired)
