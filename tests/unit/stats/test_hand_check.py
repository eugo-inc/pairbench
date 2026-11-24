# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The check by hand that the method page gives agrees with the grading, and the text says it.

The page's check is done here as the page states it: the primary cases sorted by
``p_raw_fraction``, equal fractions in places next to each other, a case passing only when
its own check and the check of every case before it pass, and a secondary case checked alone
with a multiplier of 1. Every family of up to three cases over a small grid of sign-test
fractions, ties included, gets the same answer from the page's check as from the exact Holm
correction. The twin note is described as compared on the exact corrected fraction.
"""

from __future__ import annotations

import itertools
from fractions import Fraction
from pathlib import Path

import pytest

from pairbench.model import STRICT, Case, Floors, Rule, TwinCheck
from pairbench.stats import rules
from pairbench.stats.holm import holm_exact
from pairbench.stats.rules import grade
from pairbench.stats.signtest import SignTest

from .conftest import build_grid

PAGE = "docs/method/multiple-comparisons.md"
ROUNDS = 12
TIED = Fraction(2, 64)


def flat(text: str) -> str:
    return " ".join(text.split())


def by_hand(fractions: list[Fraction], inclusive: bool) -> list[bool]:
    """The page's check of each primary case at alpha 0.05, in the order given."""
    m = len(fractions)
    order = sorted(range(m), key=lambda i: fractions[i])

    def check(place: int) -> bool:
        p = fractions[order[place]]
        left = 20 * (m - place) * p.numerator
        return left <= p.denominator if inclusive else left < p.denominator

    passed = [False] * m
    for place, index in enumerate(order):
        passed[index] = all(check(before) for before in range(place + 1))
    return passed


def test_the_page_says_how_tied_p_values_are_checked(repo_root: Path) -> None:
    text = flat((repo_root / PAGE).read_text(encoding="utf-8"))
    for sentence in (
        "The cases before a case are the cases with a smaller p-value and the cases with an "
        "equal p-value placed ahead of it.",
        "Cases with equal p-values pass or fail together, whatever their order among "
        "themselves: the first of them has the largest multiplier, so its check decides them "
        "all.",
        "Two primary cases with `p_raw_fraction` `[2, 64]` and `m` 2 both fail: the one at "
        "place 0 checks `20 * 2 * 2 = 80`, not below 64, and the one at place 1 passes its own "
        "check, `20 * 1 * 2 = 40`, but not the check before it.",
        "A secondary case, and every case under a rule whose `p_source` is `raw`, is checked "
        "alone on its own `p_raw_fraction`, with `m - i` replaced by 1.",
        "a rule whose `p_inclusive` is true fails `p = 2 ** -25` itself. The alpha of a rule "
        "from a plug-in, chosen with `--rule`, is read the same way;",
    ):
        assert sentence in text
    assert "the cases with a smaller p-value, passes too" not in text


def test_the_check_by_hand_agrees_with_the_exact_correction_ties_included() -> None:
    values = sorted({Fraction(min(2 * k, 2**n), 2**n) for n in range(2, 9) for k in range(n)})
    checked = 0
    for size in (1, 2, 3):
        for family in itertools.product(values, repeat=size):
            exact = holm_exact(list(family))
            for inclusive in (False, True):
                alpha = Fraction(1, 20)
                expected = [p <= alpha if inclusive else p < alpha for p in exact]
                assert by_hand(list(family), inclusive) == expected, (family, inclusive)
                checked += 1
    assert checked == 2 * (len(values) + len(values) ** 2 + len(values) ** 3)


def test_two_tied_primary_cases_both_fail_as_the_page_says() -> None:
    assert holm_exact([TIED, TIED]) == [Fraction(1, 16), Fraction(1, 16)]
    assert by_hand([TIED, TIED], inclusive=False) == [False, False]


def _crafted(monkeypatch: pytest.MonkeyPatch, fraction: Fraction) -> None:
    """Make every sign test of the grading give ``fraction``."""
    test = SignTest(
        n_lower=ROUNDS,
        n_higher=0,
        n=ROUNDS,
        p=float(fraction),
        fraction=(fraction.numerator, fraction.denominator),
    )
    monkeypatch.setattr(rules, "sign_test", lambda n_lower, n_higher: test)


@pytest.mark.parametrize(
    ("rule", "primary", "secondary"),
    [
        (STRICT, ("unresolved", "not_significant"), ("better", None)),
        (Rule("made-up-raw", p_source="raw"), ("better", None), ("better", None)),
    ],
)
def test_a_grading_with_tied_and_secondary_cases_matches_the_check_by_hand(
    monkeypatch: pytest.MonkeyPatch,
    rule: Rule,
    primary: tuple[str, str | None],
    secondary: tuple[str, str | None],
) -> None:
    cases = (
        Case(id="c0", metric="m0", unit="s", kind="time"),
        Case(id="c1", metric="m1", unit="s", kind="time"),
        Case(id="c2", metric="m2", unit="s", kind="time", primary=False),
    )
    values = {
        "new": {c.id: [1.0] * ROUNDS for c in cases},
        "old": {c.id: [2.0] * ROUNDS for c in cases},
    }
    _crafted(monkeypatch, TIED)
    grading = grade(build_grid(values, cases=cases), rule, floors=Floors(0.0625))
    assert grading.family_size == 2
    outcomes = {c.case.id: (c.outcome, c.reason) for c in grading.comparisons}
    assert outcomes == {"c0": primary, "c1": primary, "c2": secondary}


def test_the_twin_note_is_described_as_compared_on_the_exact_fraction(repo_root: Path) -> None:
    schema = flat((repo_root / "docs/reference/results-schema.md").read_text(encoding="utf-8"))
    doc = flat(TwinCheck.__doc__ or "")
    stored = flat(
        (repo_root / "src/pairbench/results/schema/results.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        "the compare is made on the exact Holm correction of the sign test's fraction against "
        "exactly 1/20, not on the float `p_corrected`." in schema
    )
    assert (
        "given for a side whose corrected p-value lies below 1/20, compared as the exact Holm "
        "correction of the sign test's fraction, not as the float ``p_corrected``." in doc
    )
    assert (
        "given for a side whose corrected p-value lies below 1/20, compared as the exact Holm "
        "correction of the sign test's fraction, not as the float p_corrected." in stored
    )
    for text in (schema, doc, stored):
        assert "p_corrected` is below 0.05" not in text
        assert "p_corrected`` lies below 0.05" not in text
        assert "p_corrected lies below 0.05" not in text
