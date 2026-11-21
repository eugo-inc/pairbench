# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the pages say a verdict at 8 rounds needs is what the sign test gives.

A tie is not a trial, so a verdict at 8 rounds needs every round that is not a tie to agree,
not all 8 rounds: 7 rounds that agree and one tie give p = 1/64 and can give a verdict for one
primary case. Each sentence is a row here, and the claim is checked against the sign test, the
correction and the plan's own count of primary cases.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pairbench.model import STRICT
from pairbench.plan import most_primary_cases, rounds_to_agree
from pairbench.stats import holm, min_rounds, sign_test

ROUNDS = 8
# The sentence each page says it in, with the page.
SENTENCES = {
    "docs/method/sign-test.md": (
        "At 8 rounds a verdict is possible for at most 6 primary cases, and only when every "
        "round that is not a tie agrees (all 8 when none tie). A tie is not a trial, so 7 "
        "rounds that agree and one tie give p = 0.015625 and can give a verdict for one "
        "primary case."
    ),
    "docs/guides/guidellm.md": (
        "At 8 rounds a verdict needs every round that is not a tie to agree (all 8 when none "
        "tie), and at most 6 primary cases can receive one."
    ),
}
# A claim that leaves the ties out: all 8 rounds must agree.
ALL_EIGHT = re.compile(r"\ball (?:8|eight)(?: rounds)?(?: to)? agree", re.IGNORECASE)


def flat(text: str) -> str:
    return " ".join(text.split())


def can_give_a_verdict(agree: int, disagree: int, cases: int) -> bool:
    """Whether the first of ``cases`` corrected tests passes with these counts at 8 rounds."""
    if min_rounds(cases, STRICT.alpha) > ROUNDS:
        return False
    first = sign_test(agree, disagree).p
    return holm([first, *[1.0] * (cases - 1)])[0] < STRICT.alpha


def test_each_page_says_a_tie_is_not_counted(repo_root: Path) -> None:
    missing = [
        page
        for page, sentence in SENTENCES.items()
        if sentence not in flat((repo_root / page).read_text(encoding="utf-8"))
    ]
    assert missing == []


def test_no_page_says_a_verdict_needs_all_eight_rounds_to_agree(repo_root: Path, kit: Any) -> None:
    hits = [
        f"{path.relative_to(repo_root)}: {found[0]}"
        for path in kit.documents(repo_root)
        for found in ALL_EIGHT.finditer(flat(path.read_text(encoding="utf-8")))
    ]
    assert hits == []


def test_a_verdict_at_eight_rounds_needs_every_untied_round_to_agree() -> None:
    # Rounds that agree one way or the other: the larger count agrees, the smaller does not.
    passing = {
        (max(lower, higher), min(lower, higher), ROUNDS - lower - higher)
        for lower in range(ROUNDS + 1)
        for higher in range(ROUNDS + 1 - lower)
        if can_give_a_verdict(lower, higher, 1)
    }
    assert passing == {(8, 0, 0), (7, 0, 1), (6, 0, 2)}
    assert sign_test(7, 0).p == 0.015625
    assert rounds_to_agree(ROUNDS, 1, STRICT) == 8


def test_at_most_six_primary_cases_and_only_with_no_tie() -> None:
    assert most_primary_cases(ROUNDS, 1, STRICT) == 6
    assert can_give_a_verdict(8, 0, 6)
    assert not can_give_a_verdict(7, 0, 6)
    assert not can_give_a_verdict(8, 0, 7)
