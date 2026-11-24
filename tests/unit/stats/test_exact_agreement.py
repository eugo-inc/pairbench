# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Where floats are exact enough, the float path and the exact path decide alike.

Every two-sided sign test of 2 to 50 untied rounds, each corrected as the
smallest of a family of 1 to 32 cases, is decided twice: from the floats
``holm`` writes, compared with the float alpha, and from the fractions of
``holm_exact``, compared with alpha read as its decimal text. Both decide
alike for alpha 0.05, 0.01, 0.1, 0.005 and 0.001, strict and inclusive.

A sign-test p-value is ``k / 2**n``, so ``(m - r) * k / 2**n`` never equals
one of these alphas, whose denominators hold a factor 5, and lies at least
``1 / (b * 2**n)`` from ``a / b``; at 50 rounds that distance is larger than
the rounding of a float near alpha. Over every tail of 2 to 3000 untied
rounds, Holm multipliers from 1 to 10**12, these five alphas and both
inclusive settings, worked out in whole numbers, the two paths part only at
multipliers above 2 * 10**11, that is in a family of more than two hundred
billion cases; ``test_exact_decision`` pins one of them through the plan.
"""

from __future__ import annotations

from fractions import Fraction

from pairbench.model import Rule
from pairbench.stats.holm import holm, holm_exact
from pairbench.stats.rules import is_significant
from pairbench.stats.signtest import sign_test

ALPHAS = (0.05, 0.01, 0.1, 0.005, 0.001)
MOST_ROUNDS = 50
MOST_CASES = 32
RULES = tuple(
    Rule(f"made-up-{alpha}-{inclusive}", alpha=alpha, p_inclusive=inclusive)
    for alpha in ALPHAS
    for inclusive in (False, True)
)


def test_the_float_and_the_exact_path_agree_on_every_small_sign_test() -> None:
    decided = 0
    for n in range(2, MOST_ROUNDS + 1):
        for k in range(n // 2 + 1):
            test = sign_test(k, n - k)
            exact = Fraction(*test.fraction)
            for cases in range(1, MOST_CASES + 1):
                # The p-value is the smallest of the family, so it gets the multiplier ``cases``.
                floats = holm([test.p] + [1.0] * (cases - 1))[0]
                fractions = holm_exact([exact] + [Fraction(1)] * (cases - 1))[0]
                assert fractions == min(Fraction(1), cases * exact)
                for rule in RULES:
                    assert is_significant(floats, rule) == is_significant(fractions, rule), (
                        n,
                        k,
                        cases,
                        rule.alpha,
                        rule.p_inclusive,
                    )
                    decided += 1
    assert decided == 2 * len(ALPHAS) * MOST_CASES * sum(n // 2 + 1 for n in range(2, 51))
