# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Under a rule that grades raw p-values, the reports name the correction's family as it is."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import pytest

import pairbench
from pairbench.mcp import server
from pairbench.model import Case, Results, Rule
from pairbench.stats.selftest import MATMUL, synthetic_capture

RAW = Rule("made-up-raw", p_source="raw")
FORMATS: tuple[Literal["terminal", "markdown", "html"], ...] = ("terminal", "markdown", "html")
CASES = (MATMUL, Case(id="b", metric="b", unit="s"), Case(id="c", metric="c", unit="s"))


def doubled(entry: str, case: str, round_: int, u: float) -> float:
    """Every subject reads twice the baseline; a twin sits 1 percent off its side in turn."""
    side = 1.0 if entry.startswith("old") else 2.0
    if entry.endswith("~same"):
        return side * (1.01 if round_ % 2 else 0.99)
    return side


def raw_results(subjects: Sequence[str]) -> Results:
    capture = synthetic_capture(doubled, subjects=subjects, cases=CASES, rounds=16)
    return pairbench.analyse(capture, rule=RAW)


@pytest.mark.parametrize(
    ("subjects", "family"),
    [
        pytest.param(("new", "next"), "testing 6 comparisons at once", id="two-subjects"),
        pytest.param(("new",), "testing 3 cases at once", id="one-subject"),
    ],
)
def test_the_raw_p_note_counts_comparisons_when_several_subjects_share_the_family(
    subjects: Sequence[str], family: str
) -> None:
    results = raw_results(subjects)
    assert results.rule.family_size == 3 * len(subjects)
    for fmt in FORMATS:
        text = pairbench.render(results, fmt)
        assert f"does not correct for {family}" in text, fmt
    comparison = results.comparisons[0]
    explained = server.explain_comparison(results, comparison)
    assert f"it does not correct for {family}" in explained


def test_two_subjects_never_read_as_six_cases() -> None:
    results = raw_results(("new", "next"))
    for fmt in FORMATS:
        assert "6 cases" not in pairbench.render(results, fmt)
    assert "6 cases" not in server.explain_comparison(results, results.comparisons[0])
