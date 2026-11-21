# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The serving odds: how often a round count catches a real difference, read from the data file.

The wording is pinned on made-up counts; the line of the data file the package
carries is pinned for 8 and 16 rounds with 4 primary cases.
"""

from __future__ import annotations

import pytest

from pairbench.report import odds
from pairbench.report.odds import ErrorRates, Setting, Span, from_data, odds_line

LINK = "https://eugo.io/docs/pairbench/latest/method/error-rates/"

# Made-up counts: (rounds, cases, difference) -> right-direction counts of the models a and b,
# out of 100 experiments of `cases` comparisons each.
MADE_UP_WORSE = {
    (8, 1, 2): (45, 50),
    (8, 1, 4): (90, 95),
    (8, 4, 2): (140, 150),
    (8, 4, 4): (380, 390),
    (16, 1, 2): (80, 85),
    (16, 1, 4): (100, 100),
    (16, 4, 2): (340, 348),
    (16, 4, 4): (400, 400),
    (16, 10, 2): (700, 720),
    (16, 10, 4): (1000, 1000),
}

# The line of the data file the package carries, for a board of 4 primary cases.
CARRIED_8_ROUNDS = (
    "real differences caught at 8 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 33 to 39 percent of the time (about one metric in three), four times the "
    "noise 92 to 98 percent of the time; with --rounds 16, twice the noise is caught 83 to 88 "
    "percent of the time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction "
    f"appears in the simulated experiments ({LINK})"
)
CARRIED_16_ROUNDS = (
    "real differences caught at 16 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 83 to 88 percent of the time, four times the noise 100 percent of the "
    "time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction appears in "
    f"the simulated experiments ({LINK})"
)


def _setting(
    model: str, rounds: int, cases: int, difference: int, *, wrong: int = 0, any_verdict: int = 0
) -> Setting:
    comparisons = 100 * cases
    if rounds == 8 and cases == 10:
        outcomes = {"better": 0, "worse": 0, "tie": 0, "unresolved": 0, "no_verdict": comparisons}
    else:
        pair = MADE_UP_WORSE.get((rounds, cases, difference), (0, 0))
        worse = pair[0] if model == "a" else pair[1]
        outcomes = {
            "better": wrong,
            "worse": worse,
            "tie": comparisons - worse - wrong,
            "unresolved": 0,
            "no_verdict": 0,
        }
    return Setting(
        model=model,
        rounds=rounds,
        cases=cases,
        noise=0.01,
        difference=difference,
        experiments=100,
        comparisons=comparisons,
        outcomes=outcomes,
        any_verdict=any_verdict,
    )


def _made_up(*, wrong: int = 0) -> ErrorRates:
    settings = tuple(
        _setting(
            model,
            rounds,
            cases,
            difference,
            wrong=wrong if difference else 0,
            any_verdict=(3 if model == "b" and rounds == 16 else 1) if difference == 0 else 0,
        )
        for model in ("a", "b")
        for difference in (0, 2, 4)
        for rounds in (8, 16)
        for cases in (1, 4, 10)
    )
    return ErrorRates(seed=7, experiments=100, rule="strict", alpha=0.05, settings=settings)


@pytest.mark.parametrize(
    ("low", "high", "text"),
    [
        ("33.1", "38.7", "33 to 39"),
        ("32.5", "38.5", "33 to 39"),
        ("92.4", "97.5", "92 to 98"),
        ("83.3", "88.4", "83 to 88"),
        ("100.0", "100.0", "100"),
        ("99.5", "100.0", "100"),
    ],
)
def test_a_range_is_in_whole_percent_rounded_half_up(low: str, high: str, text: str) -> None:
    assert Span(low, high).text() == text


@pytest.mark.parametrize(
    ("low", "high", "about"),
    [
        ("33.1", "38.7", "one in three"),
        ("8.0", "9.2", "one in 12"),
        ("45.0", "50.0", "one in two"),
        ("83.3", "88.4", None),
        ("0.0", "0.0", None),
    ],
)
def test_about_one_in_n_comes_from_the_middle_of_the_range(
    low: str, high: str, about: str | None
) -> None:
    assert Span(low, high).about() == about


def test_a_share_is_shown_with_one_decimal_as_the_page_shows_it() -> None:
    assert odds.percent_text(387 / 1000) == "38.7"
    assert odds.whole_percent("97.5") == 98
    assert odds.whole_percent("97.4") == 97


def test_eight_rounds_with_four_cases_reads_the_made_up_counts() -> None:
    line = odds_line([8], 4, rule="strict", more_rounds=16, rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds with 4 primary cases: a true difference of twice "
        "the noise is caught 35 to 38 percent of the time (about one metric in three), four "
        "times the noise 95 to 98 percent of the time; with --rounds 16, twice the noise is "
        "caught 85 to 87 percent of the time; a miss reads TIE or UNRESOLVED, and no verdict in "
        f"the wrong direction appears in the simulated experiments ({LINK})"
    )


def test_one_case_says_one_run_in_n() -> None:
    line = odds_line([8], 1, rule="strict", rates=_made_up())
    assert "caught 45 to 50 percent of the time (about one run in two)" in line
    assert "--rounds" not in line


def test_the_next_round_count_is_left_out_at_or_above_it() -> None:
    line = odds_line([16], 4, rule="strict", more_rounds=16, rates=_made_up())
    assert line == (
        "real differences caught at 16 rounds with 4 primary cases: a true difference of twice "
        "the noise is caught 85 to 87 percent of the time, four times the noise 100 percent of "
        "the time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction "
        f"appears in the simulated experiments ({LINK})"
    )


def test_too_few_rounds_for_the_cases_says_none() -> None:
    line = odds_line([8], 10, rule="strict", more_rounds=16, rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds with 10 primary cases: none, as 8 rounds are too "
        f"few for a verdict on 10 primary cases ({LINK})"
    )


@pytest.mark.parametrize(
    ("rounds", "cases", "missing"),
    [
        ([12], 4, "12 rounds with 4 primary cases: the error-rate page has no row for 12 rounds"),
        ([12], 3, "has no row for 12 rounds or for 3 primary cases"),
        ([7, 8], 4, "7 to 8 rounds with 4 primary cases: the error-rate page has no row for a mix"),
        ([12], None, "real differences caught at 12 rounds: the error-rate page has no row for 12"),
    ],
)
def test_a_count_without_a_row_is_said_not_guessed(
    rounds: list[int], cases: int | None, missing: str
) -> None:
    line = odds_line(rounds, cases, rule="strict", more_rounds=16, rates=_made_up())
    assert missing in line
    assert "percent" not in line
    assert line.endswith(f"({LINK})")


def test_a_number_of_cases_without_a_row_gives_the_counts_the_page_has() -> None:
    line = odds_line([8], 3, rule="strict", more_rounds=16, rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds with 3 primary cases: the error-rate page has no "
        "row for 3 primary cases; for the numbers of primary cases it has, a true difference of "
        "twice the noise is caught 45 to 50 percent with 1, 35 to 38 percent with 4, none with "
        "10 (too few rounds); four times the noise 90 to 95 percent with 1, 95 to 98 percent "
        "with 4, none with 10 (too few rounds); a miss reads TIE or UNRESOLVED, and no verdict "
        f"in the wrong direction appears in the simulated experiments ({LINK})"
    )


def test_more_than_one_subject_has_no_row() -> None:
    line = odds_line([8], 4, subjects=2, rule="strict", rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds: the error-rate page simulates one side against "
        f"the baseline and has no row for 2 sides compared with it ({LINK})"
    )


def test_another_rule_has_no_row() -> None:
    line = odds_line([8], 4, rule="lenient", rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds: the error-rate page simulates the rule strict "
        f"and has no row for the rule lenient ({LINK})"
    )


def test_an_unknown_number_of_cases_gives_every_count_the_page_has() -> None:
    line = odds_line([8], None, rule="strict", more_rounds=16, rates=_made_up())
    assert line == (
        "real differences caught at 8 rounds depend on the number of primary cases, known after "
        "warm-up: a true difference of twice the noise is caught 45 to 50 percent with 1, 35 to "
        "38 percent with 4, none with 10 (too few rounds); four times the noise 90 to 95 percent "
        "with 1, 95 to 98 percent with 4, none with 10 (too few rounds); a miss reads TIE or "
        "UNRESOLVED, and no verdict in the wrong direction appears in the simulated experiments "
        f"({LINK})"
    )


def test_a_verdict_in_the_wrong_direction_is_said_with_its_largest_share() -> None:
    line = odds_line([8], 4, rule="strict", rates=_made_up(wrong=2))
    assert "or the wrong direction for up to 2.0 percent of the metrics" in line
    assert "no verdict in the wrong direction" not in line


def test_the_page_figures_of_a_miss() -> None:
    rates = _made_up()
    assert len(rates.with_difference()) == 24
    assert rates.wrong_direction() == 0
    assert rates.false_verdict_most() == "3.0"
    assert rates.alpha_percent() == "5"


def test_a_report_sentence_has_a_capital_and_a_full_stop() -> None:
    assert odds.sentence("real differences caught") == "Real differences caught."


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("seed"), "has no 'seed'"),
        (lambda d: d["settings"][0].pop("worse"), "settings[0] has no 'worse'"),
        (lambda d: d["settings"][0].update(worse=-1), "settings[0].worse is not a count"),
        (lambda d: d["settings"][0].update(tie=0), "do not add up"),
        (lambda d: d["settings"][0].update(any_verdict=101), "more experiments with a verdict"),
        (lambda d: d.update(settings={}), "settings is not a list"),
    ],
)
def test_a_data_file_that_is_not_one_is_refused(change: object, message: str) -> None:
    rates = _made_up()
    data = {
        "seed": rates.seed,
        "experiments": rates.experiments,
        "rule": rates.rule,
        "alpha": rates.alpha,
        "settings": odds.settings_rows(rates.settings),
    }
    assert from_data(data) == rates
    assert callable(change)
    change(data)
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        from_data(data)


def test_the_carried_data_is_pinned_for_8_and_16_rounds_with_4_primary_cases() -> None:
    assert odds_line([8], 4, rule="strict", more_rounds=16) == CARRIED_8_ROUNDS
    assert odds_line([16], 4, rule="strict", more_rounds=16) == CARRIED_16_ROUNDS
