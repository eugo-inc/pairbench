# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The launch-cost page gives its example of the note in a paragraph of its own, as made up.

The README shows a measured launch cost, so the page's illustration of the note rule must not
read as one: it stands in its own paragraph, says its numbers are made up, and is what the
rule gives with the default share. The paragraph of the rule holds no number of seconds.
"""

from __future__ import annotations

from pathlib import Path

from pairbench import model

PAGE = Path("docs") / "method" / "launch-cost.md"
# The end of the paragraph of the rule, as the page writes it, with no number of seconds.
RULE = (
    "The default share is 0.01, a chosen number: the note appears when the cost is more than one\n"
    "percent of the value. It is a note, never a refusal."
)
# The example, in a paragraph of its own, as the page writes it.
EXAMPLE = (
    "An example with made-up numbers, not a measured launch cost: with a launch-cost median of\n"
    "0.0005 s, a `wall` case with a median of 0.04 s gets the note and one with 0.06 s does not."
)
COST_S = 0.0005
NOTED_S = 0.04
NOT_NOTED_S = 0.06


def paragraphs(repo_root: Path) -> list[str]:
    """The paragraphs of the page, each without the blank lines around it."""
    text = (repo_root / PAGE).read_text(encoding="utf-8")
    return [part.strip("\n") for part in text.split("\n\n")]


def test_the_example_stands_in_a_paragraph_of_its_own_and_says_it_is_made_up(
    repo_root: Path,
) -> None:
    found = paragraphs(repo_root)

    assert EXAMPLE in found
    assert [part for part in found if part.endswith(RULE)] != []


def test_no_other_paragraph_gives_the_example_numbers(repo_root: Path) -> None:
    holding = [part for part in paragraphs(repo_root) if "0.0005 s" in part]

    assert holding == [EXAMPLE]


def test_the_example_is_what_the_rule_gives_with_the_default_share() -> None:
    share = model.LaunchCostSettings().note_share

    assert share == 0.01
    assert model.launch_cost_note(NOTED_S, COST_S, share) is True
    assert model.launch_cost_note(NOT_NOTED_S, COST_S, share) is False
