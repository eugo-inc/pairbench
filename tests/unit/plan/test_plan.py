# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The planner: round counts, the control's rows, launches, the budget and the plan text."""

from __future__ import annotations

import dataclasses
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry, runner
from pairbench.api import API_VERSION, GROUP_RULES, SideLookup
from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_USAGE, Refusal
from pairbench.model import (
    STRICT,
    CaseSettings,
    ControlSettings,
    Experiment,
    ExplainSettings,
    Rule,
    RuleSettings,
    RunSettings,
    Side,
    plan_rows,
)
from pairbench.plan import (
    auto_holds_for,
    build_plan,
    format_plan,
    most_primary_cases,
    rounds_to_agree,
)

TWO_SIDES = (
    Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
    Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
)
LINEUP = ("new", "new~same", "old", "old~same")
ONE_SECOND = {"new": 1.0, "old": 1.0}


def _experiment(**run: Any) -> Experiment:
    return Experiment(sides=TWO_SIDES, run=RunSettings(**run))


def _refused(code: str, exit_code: int, **run: Any) -> Refusal:
    with pytest.raises(Refusal) as caught:
        build_plan(_experiment(**run))
    assert caught.value.code == code
    assert caught.value.exit_code == exit_code
    return caught.value


@pytest.mark.parametrize("cases", [None, 1, 2, 3, 4])
def test_auto_plans_sixteen_rounds_for_two_sides_with_twins(cases: int | None) -> None:
    plan = build_plan(_experiment(), primary_cases=cases)
    assert plan.rounds_planned == 16
    assert plan.rounds_requested is None
    assert plan.lineup == LINEUP
    assert plan.is_balanced()


@pytest.mark.parametrize(("cases", "rounds"), [(10, 16), (35, 16), (100, 16), (103, 24)])
def test_auto_grows_with_the_number_of_primary_cases(cases: int, rounds: int) -> None:
    assert build_plan(_experiment(), primary_cases=cases).rounds_planned == rounds


def test_the_control_runs_last_in_every_round_at_position_five() -> None:
    plan = build_plan(_experiment())
    assert plan.control == "old~twice"
    control_rows = [r for r in plan.rows if r.name == "old~twice"]
    assert [r.round for r in control_rows] == list(range(1, 17))
    assert {(r.pos, r.side, r.twin_of) for r in control_rows} == {(5, "old", None)}
    for round_ in range(1, 17):
        last = max((r for r in plan.rows if r.round == round_), key=lambda r: r.pos)
        assert last.name == "old~twice"


def test_eighty_two_launches_with_the_control_and_one_warm_up_per_side() -> None:
    assert build_plan(_experiment()).launches == 82


def test_the_control_changes_neither_the_balance_nor_the_count() -> None:
    with_control = build_plan(_experiment())
    without = build_plan(
        dataclasses.replace(_experiment(), controls=ControlSettings(positive="off"))
    )
    assert without.control is None
    assert without.rounds_planned == with_control.rounds_planned
    assert without.balance == with_control.balance
    assert without.rows == tuple(r for r in with_control.rows if r.name != "old~twice")
    assert without.launches == 66


def test_the_rows_are_those_of_the_model() -> None:
    experiment = _experiment()
    plan = build_plan(experiment)
    assert plan.rows == plan_rows(experiment.lineup(), 16, experiment.control())


def test_quick_plans_the_smallest_balanced_count() -> None:
    plan = build_plan(_experiment(quick=True))
    assert plan.rounds_planned == 8
    assert plan.rounds_requested is None
    assert plan.is_balanced()


@pytest.mark.parametrize(("asked", "planned"), [(12, 16), (16, 16), (17, 24), (20, 24)])
def test_a_round_count_is_rounded_up_to_the_next_balanced_one(asked: int, planned: int) -> None:
    plan = build_plan(_experiment(rounds=asked))
    assert (plan.rounds_requested, plan.rounds_planned) == (asked, planned)
    assert plan.is_balanced()


def test_rounds_exact_runs_exactly_that_many_even_unbalanced() -> None:
    plan = build_plan(_experiment(rounds=12, rounds_exact=True))
    assert (plan.rounds_requested, plan.rounds_planned) == (12, 12)
    assert not plan.is_balanced()
    by_pair = {(p.a, p.b): (p.a_first, p.b_first) for p in plan.balance}
    assert by_pair[("new", "old")] == (6, 6)
    assert by_pair[("new", "new~same")] == (7, 5)
    assert by_pair[("old", "old~same")] == (7, 5)


def test_rounds_exact_without_a_count_is_refused() -> None:
    _refused("E_USAGE", EXIT_USAGE, rounds_exact=True)


@pytest.mark.parametrize(
    "run",
    [
        {"budget_s": 600.0, "rounds": 16},
        {"budget_s": 600.0, "quick": True},
        {"budget_s": 600.0, "warmups": 0},
        {"quick": True, "rounds": 16},
        {"quick": True, "rounds": 16, "rounds_exact": True},
    ],
)
def test_settings_that_conflict_are_refused(run: dict[str, Any]) -> None:
    _refused("E_USAGE", EXIT_USAGE, **run)


@pytest.mark.parametrize(
    ("budget", "rounds", "estimate"),
    [(100.0, 16, 98.0), (150.0, 24, 146.0), (145.0, 16, 98.0), (140.0, 16, 98.0), (50.0, 8, 50.0)],
)
def test_the_budget_takes_the_largest_balanced_count_that_fits(
    budget: float, rounds: int, estimate: float
) -> None:
    plan = build_plan(_experiment(budget_s=budget), launch_s=ONE_SECOND)
    assert plan.rounds_planned == rounds
    assert plan.rounds_requested is None
    assert plan.estimate_s == estimate


def test_a_budget_that_fits_no_verdict_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        build_plan(_experiment(budget_s=40.0), launch_s=ONE_SECOND)
    assert caught.value.code == "E_BUDGET"
    assert caught.value.exit_code == EXIT_ANALYSIS
    assert "at least 8 balanced rounds" in caught.value.message


def test_a_budget_without_launch_times_plans_the_fewest_rounds_it_could_give() -> None:
    plan = build_plan(_experiment(budget_s=600.0))
    assert plan.rounds_planned == 8
    assert plan.estimate_s is None


def test_a_budget_of_launches_that_took_no_time_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        build_plan(_experiment(budget_s=60.0), launch_s={"new": 0.0, "old": 0.0})
    assert caught.value.code == "E_BUDGET"
    assert caught.value.exit_code == 6


def test_the_estimate_counts_warm_ups_rounds_and_the_control_twice() -> None:
    plan = build_plan(_experiment(), launch_s={"new": 2.0, "old": 3.0})
    assert plan.estimate_s == 5.0 + 16 * (2.0 + 2.0 + 3.0 + 3.0 + 6.0)


def test_the_estimate_counts_every_warm_up_launch() -> None:
    plan = build_plan(_experiment(warmups=3), launch_s={"new": 2.0, "old": 3.0})
    assert plan.estimate_s == 3 * 5.0 + 16 * (2.0 + 2.0 + 3.0 + 3.0 + 6.0)


def test_the_budget_leaves_time_for_every_warm_up_launch() -> None:
    # Six seconds a round and two a warm-up launch of each side: 100 s fits
    # 16 rounds after one warm-up launch each, and only 15 after three, so
    # the largest balanced count is 8.
    assert build_plan(_experiment(budget_s=100.0), launch_s=ONE_SECOND).rounds_planned == 16
    plan = build_plan(_experiment(budget_s=100.0, warmups=3), launch_s=ONE_SECOND)
    assert (plan.rounds_planned, plan.estimate_s) == (8, 3 * 2.0 + 8 * 6.0)


def test_the_fewest_rounds_count_every_subject_times_every_primary_case() -> None:
    # Two subjects and four primary cases are eight tests: a verdict needs 9
    # rounds, where four or six tests would need 8.
    sides = (*TWO_SIDES[:1], Side(name="mid", kind="cmd", spec={"argv": ["./mid"]}), TWO_SIDES[1])
    experiment = Experiment(sides=sides, run=RunSettings(rounds=8, rounds_exact=True))
    assert build_plan(experiment, primary_cases=3).rounds_planned == 8
    with pytest.raises(Refusal) as caught:
        build_plan(experiment, primary_cases=4)
    assert caught.value.code == "E_TOO_FEW_ROUNDS"
    assert caught.value.detail == {"rounds_planned": 8, "rounds_needed": 9}


def test_too_few_rounds_are_refused() -> None:
    refusal = _refused("E_TOO_FEW_ROUNDS", EXIT_ANALYSIS, rounds=4, rounds_exact=True)
    assert refusal.detail["rounds_needed"] == 6


def test_too_few_rounds_go_ahead_when_allowed() -> None:
    plan = build_plan(_experiment(rounds=4, rounds_exact=True, allow_underpowered=True))
    assert plan.rounds_planned == 4


def test_quick_with_more_cases_than_eight_rounds_can_judge_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        build_plan(_experiment(quick=True), primary_cases=7)
    assert caught.value.code == "E_TOO_FEW_ROUNDS"
    assert caught.value.exit_code == 6
    assert build_plan(_experiment(quick=True), primary_cases=6).rounds_planned == 8


def test_a_serving_experiment_plans_eight_rounds_without_the_control() -> None:
    sides = (
        Side(name="new", kind="serve", spec={"image": "example/new"}),
        Side(name="old", kind="serve", spec={"image": "example/old"}),
    )
    experiment = Experiment(sides=sides)
    plan = build_plan(experiment)
    assert plan.rounds_planned == 8
    assert plan.control is None
    assert plan.launches == 34
    text = format_plan(plan, experiment)
    assert "# server starts: 34 (every launch starts the server)\n" in text
    assert (
        "# verdict: reachable; 8 of 8 rounds must agree for one primary case when none tie "
        "(a tie is not counted)\n"
    ) in text
    assert "at most 6 primary cases can get a verdict at 8 rounds" in text
    assert "--rounds 16" in text


def test_sides_that_are_files_are_not_planned() -> None:
    sides = (
        Side(name="new", kind="file", spec={"glob": "new/*.json"}),
        Side(name="old", kind="file", spec={"glob": "old/*.json"}),
    )
    with pytest.raises(Refusal) as caught:
        build_plan(Experiment(sides=sides))
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_the_explain_launches_are_counted_on_their_own() -> None:
    assert build_plan(_experiment()).explain_launches == 4
    off = dataclasses.replace(_experiment(), explain=ExplainSettings(mode="off"))
    assert build_plan(off).explain_launches == 0
    assert build_plan(off).launches == 82


def test_three_sides_with_twins_get_a_balanced_count() -> None:
    sides = (*TWO_SIDES[:1], Side(name="mid", kind="cmd", spec={"argv": ["./mid"]}), TWO_SIDES[1])
    plan = build_plan(Experiment(sides=sides))
    assert plan.is_balanced()
    assert plan.rounds_planned == 12
    assert plan.launches == 12 * 6 + 12 + 3


@pytest.mark.parametrize(
    ("rounds", "tests", "agree"), [(8, 1, 8), (16, 1, 13), (8, 6, 8), (8, 7, None), (5, 1, None)]
)
def test_how_many_rounds_must_agree(rounds: int, tests: int, agree: int | None) -> None:
    assert rounds_to_agree(rounds, tests, STRICT) == agree


@pytest.mark.parametrize(("rounds", "most"), [(5, 0), (6, 1), (8, 6), (16, 1638)])
def test_the_most_primary_cases_a_count_can_judge(rounds: int, most: int) -> None:
    assert most_primary_cases(rounds, 1, STRICT) == most


def _counting_comb(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Count the binomial coefficients the planner works out."""
    plan_module = sys.modules["pairbench.plan"]
    calls: list[tuple[int, int]] = []
    real = plan_module.comb

    def counted(n: int, k: int) -> int:
        calls.append((n, k))
        return int(real(n, k))

    monkeypatch.setattr(plan_module, "comb", counted)
    return calls


def _least_agreeing(rounds: int, tests: int) -> int | None:
    """The fewest of ``rounds`` rounds that must agree, by bisection over exact tail sums."""
    alpha = Fraction(STRICT.alpha) / tests

    def passes(agree: int) -> bool:
        tail = sum(math.comb(rounds, i) for i in range(rounds - agree + 1))
        return Fraction(2 * tail, 2**rounds) < alpha

    if not passes(rounds):
        return None
    low, high = rounds // 2, rounds
    while high - low > 1:
        middle = (low + high) // 2
        low, high = (low, middle) if passes(middle) else (middle, high)
    return high


def test_the_most_primary_cases_need_no_search_over_sign_test_sums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _counting_comb(monkeypatch)
    # All 200 rounds agreeing passes for n tests while n * 2 / 2**200 stays below alpha.
    limit = Fraction(STRICT.alpha) * 2**199
    assert most_primary_cases(200, 3, STRICT) == (math.ceil(limit) - 1) // 3
    assert calls == []


def test_the_most_primary_cases_of_a_round_count_past_float_range_are_exact() -> None:
    limit = Fraction(STRICT.alpha) * 2**1999
    assert most_primary_cases(2000, 1, STRICT) == math.ceil(limit) - 1


@pytest.mark.parametrize(("rounds", "tests"), [(200, 1), (200, 50), (2000, 1), (2000, 10**6)])
def test_how_many_rounds_must_agree_takes_one_pass_over_the_tail(
    monkeypatch: pytest.MonkeyPatch, rounds: int, tests: int
) -> None:
    expected = _least_agreeing(rounds, tests)
    calls = _counting_comb(monkeypatch)
    assert rounds_to_agree(rounds, tests, STRICT) == expected
    assert len(calls) <= rounds


RAW = dataclasses.replace(STRICT, name="made-up-raw", p_source="raw")


class _RawRule:
    name: str = "made-up-raw"
    api_version: int = API_VERSION

    def rule(self) -> Rule:
        return RAW


@pytest.mark.parametrize(("rounds", "most"), [(5, 0), (6, 1), (8, 6), (16, 1638)])
def test_a_rule_on_raw_p_values_judges_as_many_cases_as_the_fewest_rounds_allow(
    rounds: int, most: int
) -> None:
    # A raw p-value does not divide alpha among the tests, but the fewest rounds
    # a verdict needs still grow with them, and the run refuses below that count.
    assert most_primary_cases(rounds, 1, RAW) == most


def test_the_plan_text_of_a_rule_on_raw_p_values_counts_the_cases_the_run_takes() -> None:
    registry.register(GROUP_RULES, "made-up-raw", _RawRule())
    experiment = dataclasses.replace(_experiment(rounds=8), rule=RuleSettings(name="made-up-raw"))
    text = format_plan(build_plan(experiment), experiment)
    assert "# primary cases: at most 6 primary cases can get a verdict at 8 rounds\n" in text
    assert build_plan(experiment, primary_cases=6).rounds_planned == 8
    with pytest.raises(Refusal) as caught:
        build_plan(experiment, primary_cases=7)
    assert (caught.value.code, caught.value.exit_code) == ("E_TOO_FEW_ROUNDS", EXIT_ANALYSIS)
    assert caught.value.detail == {"rounds_planned": 8, "rounds_needed": 9}


@pytest.mark.parametrize(
    "rule",
    [
        STRICT,
        RAW,
        dataclasses.replace(STRICT, name="made-up-inclusive", alpha=0.25, p_inclusive=True),
        dataclasses.replace(RAW, name="made-up-raw-inclusive", alpha=0.25, p_inclusive=True),
    ],
    ids=["corrected", "raw", "corrected-inclusive", "raw-inclusive"],
)
@pytest.mark.parametrize("subjects", [1, 2, 3])
def test_the_most_primary_cases_are_those_the_analysis_grades(rule: Rule, subjects: int) -> None:
    from pairbench.stats.rules import needed_rounds

    for rounds in range(1, 21):
        most = most_primary_cases(rounds, subjects, rule)
        assert most is not None
        if most:
            assert needed_rounds(rule, subjects * most) <= rounds
        assert needed_rounds(rule, subjects * (most + 1)) > rounds or (
            rule.p_source == "corrected"
            and rounds_to_agree(rounds, subjects * (most + 1), rule) is None
        )


def test_a_rule_on_raw_p_values_that_fixes_the_fewest_rounds_judges_any_number() -> None:
    fixed = dataclasses.replace(RAW, min_rounds=8)
    assert most_primary_cases(8, 1, fixed) is None
    assert most_primary_cases(7, 1, fixed) == 0


MOST_CASES_SHOWN = 10**9


def test_the_plan_text_of_a_round_count_too_large_to_print_its_cases_says_more_than() -> None:
    experiment = _experiment(rounds=14290, rounds_exact=True)
    header = _header(format_plan(build_plan(experiment), experiment))
    assert (
        f"# primary cases: more than {MOST_CASES_SHOWN} primary cases can get a verdict "
        "at 14290 rounds"
    ) in header


@pytest.mark.parametrize(("rounds", "shown"), [(35, "at most 858993459"), (36, "more than")])
def test_the_plan_text_names_the_count_of_primary_cases_up_to_a_limit(
    rounds: int, shown: str
) -> None:
    experiment = _experiment(rounds=rounds, rounds_exact=True)
    header = _header(format_plan(build_plan(experiment), experiment))
    [line] = [x for x in header if x.startswith("# primary cases:")]
    assert line.startswith(f"# primary cases: {shown} ")


def test_auto_holds_for_up_to_a_number_of_cases() -> None:
    assert auto_holds_for(_experiment(), STRICT, 16) == 102
    assert auto_holds_for(_experiment(), STRICT, 24) == 0


class _FixedRule:
    name: str = "made-up-fixed"
    api_version: int = API_VERSION

    def rule(self) -> Rule:
        return dataclasses.replace(STRICT, name="made-up-fixed", min_rounds=10)


def test_a_rule_that_fixes_the_fewest_rounds_sets_the_minimum() -> None:
    registry.register(GROUP_RULES, "made-up-fixed", _FixedRule())
    experiment = dataclasses.replace(_experiment(), rule=RuleSettings(name="made-up-fixed"))
    assert build_plan(experiment).rounds_planned == 16
    quick = dataclasses.replace(experiment, run=RunSettings(quick=True))
    with pytest.raises(Refusal) as caught:
        build_plan(quick)
    assert caught.value.code == "E_TOO_FEW_ROUNDS"
    assert caught.value.exit_code == 6


# ---------------------------------------------------------------------------
# The plan text
# ---------------------------------------------------------------------------


def _header(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("# ")]


def test_the_plan_text_is_a_header_then_the_table() -> None:
    experiment = _experiment()
    plan = build_plan(experiment)
    text = format_plan(plan, experiment)
    header = _header(text)
    assert text.startswith("".join(line + "\n" for line in header))
    assert text.endswith(plan.to_tsv())
    assert plan.to_tsv().startswith("round\tpos\tname\tside\ttwin_of\n")
    assert "1\t5\told~twice\told\t\n" in text
    assert "# lineup: new, new~same, old, old~same" in header
    assert "# positive control: old~twice, last in every round at position 5" in header
    assert "# rounds: requested auto, planned 16" in header
    assert "# launches: 82 (16 rounds of 5, and 2 warm-up launches)" in header
    assert (
        "# balance new / new~same: new first in 8, new~same first in 8, "
        "positions differ by 0 in sum"
    ) in header
    assert (
        "# verdict: reachable; 13 of 16 rounds must agree for one primary case when none tie "
        "(a tie is not counted)"
    ) in header
    assert any("fixed after warm-up" in line for line in header)
    assert (
        "# the round count of 16 holds for up to 102 primary cases; more raise it after warm-up"
        in header
    )
    assert "# positive control costs 16 launches; turn it off with --positive-control off" in header
    assert any(line.endswith("turn them off with --explain off") for line in header)
    assert "# estimated duration: not known before a warm-up launch is timed" in header
    assert "# sides differ in: new: argv" in header


def test_the_plan_text_of_quick_says_every_untied_round_must_agree() -> None:
    experiment = _experiment(quick=True)
    text = format_plan(build_plan(experiment), experiment)
    assert (
        "# verdict: reachable; 8 of 8 rounds must agree for one primary case when none tie "
        "(a tie is not counted)\n"
    ) in text
    assert "# primary cases: at most 6 primary cases can get a verdict at 8 rounds\n" in text


def test_the_plan_text_names_a_count_that_was_rounded_up() -> None:
    experiment = _experiment(rounds=12)
    text = format_plan(build_plan(experiment), experiment)
    assert "# rounds: requested 12, planned 16 (rounded up to the next balanced count)\n" in text


def test_the_plan_text_names_an_unbalanced_count() -> None:
    experiment = _experiment(rounds=12, rounds_exact=True)
    text = format_plan(build_plan(experiment), experiment)
    assert "planned 12 (not balanced: the capture is stamped unbalanced)" in text


def test_the_plan_text_gives_the_cost_in_time_when_launches_were_timed() -> None:
    experiment = _experiment()
    plan = build_plan(experiment, launch_s={"new": 2.0, "old": 2.0})
    text = format_plan(plan, experiment)
    assert "# estimated duration: 3.27 min\n" in text
    assert "# positive control costs 16 launches, about 64 s; turn it off" in text
    assert "# explain launches: 4, about 8 s, after the analysis" in text


def test_the_plan_text_says_when_the_control_is_off() -> None:
    experiment = dataclasses.replace(_experiment(), controls=ControlSettings(positive="off"))
    text = format_plan(build_plan(experiment), experiment)
    assert "# positive control: off\n" in text
    assert "old~twice" not in text


def test_without_twins_the_plan_says_no_verdict_can_come() -> None:
    experiment = _experiment(same_vs_same="off")
    text = format_plan(build_plan(experiment), experiment)
    assert "# warning: no side has a twin, so rule strict cannot give a verdict" in text
    assert "# verdict: not reachable: no side has a twin and rule strict needs both noise " in text
    assert "verdict: reachable" not in text


def test_a_side_without_a_twin_is_named() -> None:
    experiment = _experiment(same_vs_same=("new",))
    text = format_plan(build_plan(experiment), experiment)
    assert "# warning: old has no twin, so rule strict gives no verdict" in text
    assert "# verdict: not reachable: old has no twin and rule strict needs both noise " in text


def test_one_side_with_its_twin_is_planned_with_no_subject_to_compare() -> None:
    experiment = Experiment(sides=TWO_SIDES[1:])
    header = _header(format_plan(build_plan(experiment), experiment))
    assert header[0] == "# lineup: old, old~same"
    assert (
        "# verdict: none: the experiment has one side, old, so no subject is compared with it; "
        "the run measures its noise floor against its twin"
    ) in header
    assert "# primary cases: none can get a verdict, as no subject is compared" in header
    assert not any("no twin" in line or "()" in line for line in header)


def test_one_side_without_a_twin_is_planned_with_nothing_to_compare() -> None:
    experiment = Experiment(sides=TWO_SIDES[1:], run=RunSettings(same_vs_same="off"))
    header = _header(format_plan(build_plan(experiment), experiment))
    assert (
        "# verdict: none: the experiment has one side, old, so no subject is compared with it"
        in header
    )
    assert "# primary cases: none can get a verdict, as no subject is compared" in header
    assert not any("()" in line for line in header)


ONE_SIDE_ROUND_COUNT = (
    "# the round count of 10 holds for up to 1 primary case; more raise it after warm-up, "
    "although no case gets a verdict"
)


@pytest.mark.parametrize("same_vs_same", ["on", "off"])
def test_the_round_count_of_one_side_says_plainly_that_no_case_gets_a_verdict(
    same_vs_same: str,
) -> None:
    experiment = Experiment(sides=TWO_SIDES[1:], run=RunSettings(same_vs_same=same_vs_same))
    header = _header(format_plan(build_plan(experiment), experiment))
    assert ONE_SIDE_ROUND_COUNT in header
    assert not any("1 primary cases" in line for line in header)


@pytest.mark.parametrize(
    ("run", "rounds"),
    [
        ({"rounds": 2}, 2),
        ({"rounds": 1, "rounds_exact": True}, 1),
        ({"quick": True}, 2),
        # Four seconds a round (the control counts twice) and one for the
        # warm-up: ten seconds fit two rounds.
        ({"budget_s": 10.0}, 2),
    ],
)
def test_one_side_is_never_refused_for_too_few_rounds_for_a_verdict(
    run: dict[str, Any], rounds: int
) -> None:
    experiment = Experiment(sides=TWO_SIDES[1:], run=RunSettings(**run))
    plan = build_plan(experiment, launch_s={"old": 1.0})
    assert plan.rounds_planned == rounds


def test_a_budget_too_small_for_one_side_names_the_smallest_balanced_count() -> None:
    experiment = Experiment(sides=TWO_SIDES[1:], run=RunSettings(budget_s=6.0))
    with pytest.raises(Refusal) as caught:
        build_plan(experiment, launch_s={"old": 1.0})
    assert caught.value.code == "E_BUDGET"
    assert caught.value.exit_code == EXIT_ANALYSIS
    assert "; a balanced run needs at least 2 balanced rounds, " in caught.value.message
    assert "verdict" not in caught.value.message


@pytest.mark.parametrize(
    ("rounds", "line"),
    [
        (5, "# primary cases: none can get a verdict at 5 rounds"),
        (6, "# primary cases: at most 1 primary case can get a verdict at 6 rounds"),
        (7, "# primary cases: at most 3 primary cases can get a verdict at 7 rounds"),
    ],
)
def test_the_count_of_primary_cases_reads_right_for_none_one_and_more(
    rounds: int, line: str
) -> None:
    experiment = _experiment(rounds=rounds, rounds_exact=True, allow_underpowered=True)
    header = _header(format_plan(build_plan(experiment), experiment))
    assert line in header


class _OneFloorRule:
    name: str = "made-up-one-floor"
    api_version: int = API_VERSION

    def rule(self) -> Rule:
        return dataclasses.replace(STRICT, name="made-up-one-floor", require_both_floors=False)


def test_a_rule_that_does_not_need_both_floors_keeps_the_verdict_reachable() -> None:
    registry.register(GROUP_RULES, "made-up-one-floor", _OneFloorRule())
    experiment = dataclasses.replace(
        _experiment(same_vs_same=("new",)), rule=RuleSettings(name="made-up-one-floor")
    )
    text = format_plan(build_plan(experiment), experiment)
    assert "# verdict: reachable; " in text
    assert "has no twin" not in text


def test_the_plan_text_shows_each_look_up() -> None:
    experiment = _experiment()
    lookups = {
        "new": SideLookup(status="identified", identity={"version": "0.0.0"}),
        "old": SideLookup(status="unchecked", message="no container engine could be reached"),
    }
    text = format_plan(build_plan(experiment), experiment, lookups=lookups)
    assert "# side new: identified (version=0.0.0)\n" in text
    assert (
        "# pairbench: note: identity_not_checked: side old: identity was not checked; "
        "no container engine could be reached\n"
    ) in text


def test_the_plan_text_shows_only_the_last_part_of_a_looked_up_path() -> None:
    experiment = _experiment()
    lookups = {
        "new": SideLookup(
            status="identified",
            identity={"executable": "/made/up/zqmkcx/bin/prog", "version": "0.0.0"},
        ),
        "old": SideLookup(
            status="identified",
            identity={"version": "0.0.0"},
            message="read from /made/up/zqmkcy/cache/old.json",
        ),
    }
    text = format_plan(build_plan(experiment), experiment, lookups=lookups)
    assert "# side new: identified (executable=prog, version=0.0.0)\n" in text
    assert "# side old: identified (version=0.0.0); read from old.json\n" in text
    assert "zqmkcx" not in text and "zqmkcy" not in text and "/made/up" not in text


# ---------------------------------------------------------------------------
# How often a serving experiment's round count catches a real difference
# ---------------------------------------------------------------------------

SERVING_SIDES = (
    Side(name="new", kind="serve", spec={"image": "example/new"}),
    Side(name="old", kind="serve", spec={"image": "example/old"}),
)
ERROR_RATES_LINK = "https://eugo.io/docs/pairbench/latest/method/error-rates/"
ODDS_AT_8_ROUNDS = (
    "# real differences caught at 8 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 33 to 39 percent of the time (about one metric in three), four times the "
    "noise 92 to 98 percent of the time; with --rounds 16, twice the noise is caught 83 to 88 "
    "percent of the time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction "
    f"appears in the simulated experiments ({ERROR_RATES_LINK})"
)
ODDS_AT_16_ROUNDS = (
    "# real differences caught at 16 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 83 to 88 percent of the time, four times the noise 100 percent of the "
    "time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction appears in "
    f"the simulated experiments ({ERROR_RATES_LINK})"
)
FOUR_CASES = ("c32/ttft_ms_median", "c32/itl_ms_median", "c32/output_tokens_per_s", "c32/other")
# The default board of the GuideLLM driver when power is sampled, each case named as written.
POWER_BOARD = (
    "c32/ttft_ms_median",
    "c32/itl_ms_median",
    "c32/output_tokens_per_s",
    "c32/tokens_per_joule[gpu]",
)


def _serving(**run: Any) -> Experiment:
    return Experiment(sides=SERVING_SIDES, run=RunSettings(**run))


def _odds(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("# real differences caught")]


def test_the_plan_of_a_serving_run_says_how_often_8_rounds_catch_a_real_difference() -> None:
    experiment = _serving()
    plan = build_plan(experiment, primary_cases=4)
    lines = format_plan(plan, experiment, primary_cases=4).splitlines()
    more = lines.index("# for 16 rounds, run again with --rounds 16")
    assert lines[more - 1] == ODDS_AT_8_ROUNDS
    assert _odds("\n".join(lines)) == [ODDS_AT_8_ROUNDS]


def test_the_plan_of_a_serving_run_at_16_rounds_says_what_16_rounds_catch() -> None:
    experiment = _serving(rounds=16)
    plan = build_plan(experiment, primary_cases=4)
    assert plan.rounds_planned == 16
    assert _odds(format_plan(plan, experiment, primary_cases=4)) == [ODDS_AT_16_ROUNDS]


def test_primary_cases_named_one_by_one_are_the_board_the_plan_counts() -> None:
    experiment = dataclasses.replace(_serving(), cases=CaseSettings(primary=FOUR_CASES))
    assert _odds(format_plan(build_plan(experiment), experiment)) == [ODDS_AT_8_ROUNDS]


def test_an_energy_case_named_as_written_counts_as_one_case_of_the_board() -> None:
    experiment = dataclasses.replace(_serving(), cases=CaseSettings(primary=POWER_BOARD))
    assert _odds(format_plan(build_plan(experiment), experiment)) == [ODDS_AT_8_ROUNDS]


def test_the_plan_command_words_the_line_for_the_cases_it_is_given(
    cli: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "look_up_sides", lambda experiment: {})
    named = [arg for case in POWER_BOARD for arg in ("--case", case)]
    result = cli(
        "plan",
        "--side",
        "new=serve:example/new",
        "--side",
        "old=serve:example/old",
        "--baseline",
        "old",
        "--driver",
        "guidellm",
        *named,
        "--",
        "--data",
        "kind=synthetic_text,prompt_tokens=8,output_tokens=8",
    )
    assert result.code == EXIT_OK
    assert result.err == ""
    lines = result.out.splitlines()
    assert _odds(result.out) == [ODDS_AT_8_ROUNDS]
    assert lines[lines.index(ODDS_AT_8_ROUNDS) + 1] == "# for 16 rounds, run again with --rounds 16"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("primary", [(), ("c32/*",), ("c[14]/ttft_ms_median",)])
def test_without_a_known_board_the_plan_gives_every_count_the_page_has(
    primary: tuple[str, ...],
) -> None:
    experiment = dataclasses.replace(_serving(), cases=CaseSettings(primary=primary))
    (line,) = _odds(format_plan(build_plan(experiment), experiment))
    assert line.startswith(
        "# real differences caught at 8 rounds depend on the number of primary cases, known "
        "after warm-up: a true difference of twice the noise is caught "
    )
    assert "33 to 39 percent with 4" in line
    assert "none with 10 (too few rounds)" in line
    assert line.endswith(f"({ERROR_RATES_LINK})")


def test_a_board_without_a_row_on_the_page_is_said() -> None:
    experiment = _serving()
    plan = build_plan(experiment, primary_cases=3)
    assert _odds(format_plan(plan, experiment, primary_cases=3)) == [
        "# real differences caught at 8 rounds with 3 primary cases: the error-rate page has no "
        "row for 3 primary cases; for the numbers of primary cases it has, a true difference of "
        "twice the noise is caught 41 to 51 percent with 1, 33 to 39 percent with 4, none with "
        "10 (too few rounds); four times the noise 93 to 98 percent with 1, 92 to 98 percent with "
        "4, none with 10 (too few rounds); a miss reads TIE or UNRESOLVED, and no verdict in the "
        f"wrong direction appears in the simulated experiments ({ERROR_RATES_LINK})"
    ]


def test_a_round_count_without_a_row_on_the_page_is_said() -> None:
    experiment = _serving(rounds=32)
    plan = build_plan(experiment, primary_cases=4)
    assert plan.rounds_planned == 32
    assert _odds(format_plan(plan, experiment, primary_cases=4)) == [
        "# real differences caught at 32 rounds with 4 primary cases: the error-rate page has no "
        f"row for 32 rounds ({ERROR_RATES_LINK})"
    ]


def test_a_plan_that_is_not_serving_has_no_odds_line() -> None:
    experiment = _experiment()
    assert _odds(format_plan(build_plan(experiment, primary_cases=4), experiment)) == []


def test_a_serving_plan_that_can_give_no_verdict_has_no_odds_line() -> None:
    experiment = _serving(same_vs_same="off")
    assert _odds(format_plan(build_plan(experiment), experiment, primary_cases=4)) == []
