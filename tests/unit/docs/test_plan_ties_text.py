# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The plan's verdict line, and the pages that show it, say that a tie is not counted.

The plan says how many rounds must agree for a verdict when no round is a tie, and that a tie
is not counted, as the sign-test page says: a tie is not a trial, so fewer rounds that agree
can give a verdict when some tie. The README's example of the plan shows the line the plan
prints for sixteen rounds, and the command reference says the same of the plan.
"""

from __future__ import annotations

from pathlib import Path

from pairbench.model import STRICT
from pairbench.plan import rounds_to_agree
from pairbench.stats import sign_test

README_TEMPLATE = "docs/readme/README.in.md"
COMMANDS = "docs/reference/commands.md"
# The line of the README's plan example, at sixteen rounds and one primary case.
README_LINE = (
    "# verdict: reachable; 13 of 16 rounds must agree for one primary case when none tie "
    "(a tie is not counted)"
)
COMMANDS_TEXT = "whether a verdict is reachable and how many rounds must agree when none tie"
ROUNDS = 16
AGREE = 13


def flat(text: str) -> str:
    return " ".join(text.split())


def test_the_readme_example_says_a_tie_is_not_counted(repo_root: Path) -> None:
    lines = (repo_root / README_TEMPLATE).read_text(encoding="utf-8").splitlines()

    assert README_LINE in lines


def test_the_command_reference_says_the_count_is_with_no_tie(repo_root: Path) -> None:
    assert COMMANDS_TEXT in flat((repo_root / COMMANDS).read_text(encoding="utf-8"))


def test_the_readme_count_is_the_plan_count_with_no_tie() -> None:
    assert rounds_to_agree(ROUNDS, 1, STRICT) == AGREE
    assert sign_test(AGREE, ROUNDS - AGREE).p < STRICT.alpha
    assert sign_test(AGREE - 1, ROUNDS - AGREE + 1).p >= STRICT.alpha


def test_with_one_tie_fewer_rounds_that_agree_give_a_verdict() -> None:
    # One tie leaves fifteen trials, and twelve that agree against three are enough.
    assert sign_test(AGREE - 1, ROUNDS - AGREE).p < STRICT.alpha
