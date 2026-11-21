# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every page about serving runs says how often the default round count catches a real difference.

The figures on the pages are checked against the data file the error-rate generator
writes, the same counts the error-rate page shows: a stated range that differs from the
data, a missing figure or a missing link to the error-rate page fails here.
"""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

import pytest

from pairbench.report import odds
from pairbench.report.odds import ErrorRates, Span

from .conftest import linked_file

ROOT = Path(__file__).resolve().parents[3]
ERROR_RATE_PAGE = ROOT / "docs" / "method" / "error-rates.md"
GUIDES = ROOT / "docs" / "guides"
SHOWCASE = ROOT / "showcases" / "inference-server-versions"
# The serving pages, with the folder their relative links start from. The README template
# is filled into README.md at the root, so its links start from the root.
PAGES = {
    "README.md": ROOT,
    "docs/readme/README.in.md": ROOT,
    "docs/guides/guidellm.md": GUIDES,
    "docs/guides/aiperf.md": GUIDES,
    "docs/guides/vllm-bench.md": GUIDES,
    "showcases/inference-server-versions/README.md": SHOWCASE,
}
# The README and its template link the pages by their addresses on the documentation site,
# since the README is read on GitHub and on the package index; every other serving page
# links them by relative paths.
SITE_LINKED = frozenset({"README.md", "docs/readme/README.in.md"})
# The words every serving page uses for verdicts in the wrong direction; they mark the
# paragraph on the odds.
MARK = "none in the simulated experiments"
# A page that says what the report of a serving run states, and the words the report uses
# for a run the error-rate page has no figures for.
REPORT_ODDS = "The report of a serving run"
NO_ROW = "has no row"
DEFAULT_ROUNDS = 8
MORE_ROUNDS = 16
BOARD = 4
ONE_CASE = 1
TWICE = 2
FOUR_TIMES = 4
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
RANGE = re.compile(r"\b(\d+) to (\d+) percent")
ABOUT_PERCENT = re.compile(r"\babout (\d+) percent")
ABOUT_SHARE = re.compile(r"\babout (a third|a quarter|a half|two thirds|three quarters)\b")
SHARES = {
    "a quarter": Fraction(1, 4),
    "a third": Fraction(1, 3),
    "a half": Fraction(1, 2),
    "two thirds": Fraction(2, 3),
    "three quarters": Fraction(3, 4),
}
LIST_ITEM = re.compile(r"^\s*[-*] ")
# A figure on a page is about the round count, the number of primary cases and the multiple
# of the noise its paragraph names last before it.
ROUNDS_NAMED = re.compile(r"\b(\d+) rounds\b")
BOARD_NAMED = re.compile(r"\b(\d+|one) primary (?:metrics?|cases?)\b")
NOISE_NAMED = re.compile(r"\b(twice|four times) the noise\b")
NUMBER_WORDS = {"one": ONE_CASE, "twice": TWICE, "four times": FOUR_TIMES}


def _rates() -> ErrorRates:
    return odds.error_rates()


def _span(rounds: int, cases: int, difference: int) -> Span:
    span = _rates().caught(rounds, cases, difference)
    assert span is not None, (rounds, cases, difference)
    return span


def _paragraphs(text: str) -> list[str]:
    """The paragraphs and list items of a page, each with its whitespace folded."""
    found: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        item: list[str] = []
        for line in block.splitlines():
            if LIST_ITEM.match(line) and item:
                found.append(" ".join(" ".join(item).split()))
                item = []
            item.append(line)
        if item:
            found.append(" ".join(" ".join(item).split()))
    return found


def _odds_paragraph(page: str) -> str:
    text = (ROOT / page).read_text(encoding="utf-8")
    marked = [paragraph for paragraph in _paragraphs(text) if MARK in paragraph]
    assert len(marked) == 1, f"{page}: {len(marked)} paragraphs say {MARK!r}"
    return marked[0]


def _named_last(pattern: re.Pattern[str], paragraph: str, at: int) -> int | None:
    found = [match.group(1) for match in pattern.finditer(paragraph, 0, at)]
    if not found:
        return None
    return NUMBER_WORDS[found[-1]] if found[-1] in NUMBER_WORDS else int(found[-1])


def _wrong_figures(paragraph: str) -> list[str]:
    """Every range or rounded share of a paragraph that is not the data's for what it is about.

    What a figure is about is the round count, the number of primary cases and the multiple
    of the noise the paragraph names last before it; a figure with no such setting before it,
    or a setting the data has no row for, is wrong too.
    """
    wrong: list[str] = []
    figures = [*RANGE.finditer(paragraph), *ABOUT_PERCENT.finditer(paragraph)]
    figures += ABOUT_SHARE.finditer(paragraph)
    for figure in figures:
        setting = tuple(
            _named_last(pattern, paragraph, figure.start())
            for pattern in (ROUNDS_NAMED, BOARD_NAMED, NOISE_NAMED)
        )
        rounds, cases, difference = setting
        if rounds is None or cases is None or difference is None:
            wrong.append(f"{figure.group(0)!r} names no setting before it")
            continue
        span = _rates().caught(rounds, cases, difference)
        if span is None:
            wrong.append(f"{figure.group(0)!r}: the data has no row for {setting}")
        elif figure.re is RANGE:
            if f"{figure.group(1)} to {figure.group(2)}" != span.text():
                wrong.append(f"{figure.group(0)!r} for {setting}: the data says {span.text()}")
        elif figure.re is ABOUT_PERCENT:
            low, high = odds.whole_percent(span.low), odds.whole_percent(span.high)
            if not low <= int(figure.group(1)) <= high:
                wrong.append(f"{figure.group(0)!r} for {setting}: the data says {span.text()}")
        elif not Fraction(span.low) <= SHARES[figure.group(1)] * 100 <= Fraction(span.high):
            wrong.append(f"{figure.group(0)!r} for {setting}: the data says {span.text()}")
    return wrong


def test_the_data_holds_what_the_pages_say_of_a_miss() -> None:
    rates = _rates()
    assert rates.wrong_direction() == 0
    assert Fraction(rates.false_verdict_most()) < Fraction(rates.alpha_percent())


@pytest.mark.parametrize("page", sorted(PAGES))
def test_a_serving_page_states_the_odds_of_the_default_from_the_data(page: str) -> None:
    paragraph = _odds_paragraph(page)
    rates = _rates()
    required = (
        f"{_span(DEFAULT_ROUNDS, BOARD, TWICE).text()} percent",
        f"{_span(MORE_ROUNDS, BOARD, TWICE).text()} percent",
        f"{_span(DEFAULT_ROUNDS, BOARD, FOUR_TIMES).text()} percent",
        f"{BOARD} primary metrics",
        f"{DEFAULT_ROUNDS} rounds",
        f"--rounds {MORE_ROUNDS}",
        f"{len(rates.with_difference())} settings",
        f"{rates.false_verdict_most()} percent",
        f"{rates.alpha_percent()} percent",
        "SLOWER",
        "UNRESOLVED",
        "TIE",
        "default",
    )
    missing = [phrase for phrase in required if phrase not in paragraph]
    assert missing == [], f"{page}: {missing}"


@pytest.mark.parametrize("page", sorted(PAGES))
def test_every_figure_on_a_serving_page_is_the_data_for_what_it_is_about(page: str) -> None:
    paragraph = _odds_paragraph(page)
    assert RANGE.search(paragraph), page
    assert _wrong_figures(paragraph) == [], page


@pytest.mark.parametrize("page", sorted(PAGES))
def test_a_serving_page_links_the_error_rate_page(page: str) -> None:
    paragraph = _odds_paragraph(page)
    written = LINK.findall(paragraph)
    if page in SITE_LINKED:
        found = [linked_file(ROOT, target) for target in written]
        targets = [path.resolve() for path in found if path is not None]
    else:
        targets = [(PAGES[page] / target.split("#", 1)[0]).resolve() for target in written]
    assert ERROR_RATE_PAGE.resolve() in targets, page


def test_a_page_on_the_report_s_odds_says_what_the_report_says_off_the_error_rate_page() -> None:
    rates = _rates()
    off_the_page = max(rates.cases) + 1
    for line in (
        odds.odds_line([DEFAULT_ROUNDS], off_the_page, rule=rates.rule, rates=rates),
        odds.odds_line([DEFAULT_ROUNDS], BOARD, subjects=TWICE, rule=rates.rule, rates=rates),
        odds.odds_line([DEFAULT_ROUNDS], BOARD, rule=rates.rule + "-other", rates=rates),
    ):
        assert NO_ROW in line
    describing = [page for page in sorted(PAGES) if REPORT_ODDS in _odds_paragraph(page)]
    assert describing == [
        "docs/guides/aiperf.md",
        "docs/guides/guidellm.md",
        "docs/guides/vllm-bench.md",
    ]
    assert [page for page in describing if NO_ROW not in _odds_paragraph(page)] == []


@pytest.mark.parametrize("page", sorted(PAGES))
def test_a_serving_page_does_not_say_never_of_a_simulation(page: str) -> None:
    assert not re.search(r"\bnever\b", _odds_paragraph(page), re.IGNORECASE), page


def test_the_page_checks_find_what_they_are_for() -> None:
    sample = (
        "Intro.\n\n- One item.\n- Two items say none in the simulated experiments,\n"
        "  33 to 39 percent.\n\nLast."
    )
    assert _paragraphs(sample) == [
        "Intro.",
        "- One item.",
        "- Two items say none in the simulated experiments, 33 to 39 percent.",
        "Last.",
    ]
    assert RANGE.findall("caught 33 to 39 percent") == [("33", "39")]
    assert ABOUT_PERCENT.findall("about 85 percent") == ["85"]
    assert ABOUT_SHARE.findall("for about a third of") == ["a third"]


def test_a_figure_stated_for_another_setting_is_found() -> None:
    eight, sixteen = _span(DEFAULT_ROUNDS, BOARD, TWICE), _span(MORE_ROUNDS, BOARD, TWICE)
    four = _span(DEFAULT_ROUNDS, BOARD, FOUR_TIMES)
    one = _span(DEFAULT_ROUNDS, ONE_CASE, TWICE)

    def paragraph(at_eight: str, at_sixteen: str, share: str = "a third") -> str:
        return (
            f"With a board of {BOARD} primary metrics and twice the noise, 8 rounds catch about "
            f"{share} ({at_eight} percent); 16 rounds catch {at_sixteen} percent. A difference "
            f"of four times the noise is caught at 8 rounds {four.text()} percent."
        )

    assert _wrong_figures(paragraph(eight.text(), sixteen.text())) == []
    assert len(_wrong_figures(paragraph(sixteen.text(), eight.text()))) == 2
    assert len(_wrong_figures(paragraph(one.text(), sixteen.text()))) == 1
    assert len(_wrong_figures(paragraph(eight.text(), sixteen.text(), "a half"))) == 1
    assert _wrong_figures("It is caught about 85 percent of the time.") == [
        "'about 85 percent' names no setting before it"
    ]
