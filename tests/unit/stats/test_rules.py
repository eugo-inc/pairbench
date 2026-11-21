# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The verdict rule: every option of the rule object, the table, the reasons and the downgrades.

Values are dyadic and floors are supplied where a test sits on a boundary, so
that equality is exact.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from fractions import Fraction
from typing import Any

import pytest

from pairbench.errors import Refusal
from pairbench.model import STRICT, Case, Floors, Rule, resource_case
from pairbench.stats.rules import (
    Grading,
    Grid,
    form_bar,
    grade,
    group_key,
    in_order,
    is_outside,
    is_significant,
    is_unbalanced,
    is_zero_floor,
    table,
)

GridBuilder = Callable[..., Grid]
Values = dict[str, dict[str, Sequence[float | None]]]
MATMUL = Case(id="matmul", metric="time", unit="s", kind="time")


def entries(
    new: Sequence[float | None],
    old: Sequence[float | None],
    *,
    new_twin: Sequence[float | None] | None = None,
    old_twin: Sequence[float | None] | None = None,
    case: str = "matmul",
) -> dict[str, dict[str, Sequence[float | None]]]:
    out: dict[str, dict[str, Sequence[float | None]]] = {"new": {case: new}}
    if new_twin is not None:
        out["new~same"] = {case: new_twin}
    out["old"] = {case: old}
    if old_twin is not None:
        out["old~same"] = {case: old_twin}
    return out


def only(grading: Grading, case: str = "matmul", subject: str = "new"):  # type: ignore[no-untyped-def]
    found = [c for c in grading.comparisons if c.case.id == case and c.subject == subject]
    assert len(found) == 1
    return found[0]


# Sixteen rounds in which the twin of each side reads 1/16 below it: both
# floors are 1/16 exactly, so the default bar is 1/8.
R16 = 16
NEW = [1.0625] * R16
NEW_TWIN = [1.0] * R16
OLD = [2.125] * R16
OLD_TWIN = [2.0] * R16


def test_significance_and_the_bar_honour_their_inclusive_options() -> None:
    assert not is_significant(0.05, STRICT)
    assert is_significant(0.05, Rule("r", p_inclusive=True))
    assert is_significant(0.049, STRICT)
    assert not is_outside(0.5, 0.5, STRICT)
    assert is_outside(0.5, 0.5, Rule("r", gap_inclusive=True))
    assert is_outside(0.625, 0.5, STRICT)


def test_every_bar_option() -> None:
    assert form_bar(STRICT, 0.0625, 0.125, None) == 0.1875
    assert form_bar(STRICT, 0.0625, None, None) == 0.0625
    assert form_bar(STRICT, None, None, None) is None
    assert form_bar(Rule("r", bar="twice_larger"), 0.0625, 0.125, None) == 0.25
    assert form_bar(Rule("r", bar="twice_experiment_max"), 0.0625, 0.125, 0.5) == 1.0
    assert form_bar(Rule("r", bar="twice_experiment_max"), 0.0625, 0.125, None) is None
    rounding = Rule("r", bar_round_digits=1)
    assert form_bar(rounding, 0.26, 0.04, None) == 0.3
    assert is_zero_floor(0.04, rounding)
    assert not is_zero_floor(0.04, STRICT)
    assert is_zero_floor(0.0, STRICT)


def test_the_table_of_the_default_rule() -> None:
    assert table(STRICT, 0.5, 0.5, 0.125, 0.001, "lower") == ("better", None)
    assert table(STRICT, 0.5, 0.5, 0.125, 0.001, "higher") == ("worse", None)
    assert table(STRICT, 2.0, 1.0, 0.125, 0.001, "lower") == ("worse", None)
    assert table(STRICT, 2.0, 1.0, 0.125, 0.001, "none") == ("higher", None)
    assert table(STRICT, 0.5, 0.5, 0.125, 0.001, "none") == ("lower", None)
    assert table(STRICT, 0.5, 0.5, 0.125, 0.5, "lower") == ("unresolved", "not_significant")
    assert table(STRICT, 1.0625, 0.0625, 0.125, 0.5, "lower") == ("tie", None)
    assert table(STRICT, 1.0625, 0.0625, 0.125, 0.001, "lower") == ("unresolved", "inside_noise")


def test_the_tie_options() -> None:
    inside = Rule("r", tie="inside")
    never = Rule("r", tie="never")
    assert table(inside, 1.0625, 0.0625, 0.125, 0.001, "lower") == ("tie", None)
    assert table(inside, 1.0625, 0.0625, 0.125, 0.5, "lower") == ("tie", None)
    assert table(never, 1.0625, 0.0625, 0.125, 0.5, "lower") == ("unresolved", "inside_noise")
    assert table(never, 1.0625, 0.0625, 0.125, 0.001, "lower") == ("unresolved", "inside_noise")


def test_the_percent_scale_grades_around_zero() -> None:
    percent = Rule("r", scale="percent")
    assert table(percent, -50.0, 50.0, 2.0, 0.001, "lower") == ("better", None)
    assert table(percent, 1.0, 1.0, 2.0, 0.5, "lower") == ("tie", None)


def test_reasons_come_in_the_order_that_picks_the_main_one() -> None:
    order = ("a", "b", "c")
    assert in_order({"c", "a"}, order) == ("a", "c")  # type: ignore[comparison-overlap]


def test_an_order_is_unbalanced_past_three_to_one() -> None:
    assert not is_unbalanced((12, 4))
    assert is_unbalanced((13, 4))
    assert is_unbalanced((1, 0))
    assert not is_unbalanced((0, 0))
    assert not is_unbalanced((8, 8))


def test_the_floor_group_of_a_case() -> None:
    assert group_key(Case(id="a", metric="time", unit="s")) == ("metric", "time", "primary")
    assert group_key(Case(id="b", metric="time", unit="s", primary=False)) == (
        "metric",
        "time",
        "secondary",
    )
    assert group_key(Case(id="c", metric="time", unit="s", group="mine")) == ("group", "mine")


def test_a_known_difference_reads_faster_under_the_default_rule(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, OLD, new_twin=[1.0 / 1.0625] * R16, old_twin=OLD_TWIN))
    grading = grade(grid, STRICT)
    got = only(grading)
    assert got.outcome == "better"
    assert got.reason is None
    assert got.reasons == ()
    assert (got.n_rounds, got.n_unpaired, got.n_lower, got.n_higher) == (16, 0, 16, 0)
    assert got.p_raw == 2 / 65536
    assert got.p_fraction == (2, 65536)
    assert got.p_corrected == 2 / 65536
    assert got.ratio == 1.0 / 2.125
    assert got.mode == "TWO-SIDED"
    assert got.source == "twins"
    assert got.order_split == (8, 8)
    assert grading.family_size == 1
    assert grading.tests == 1
    assert grading.needed == 6
    assert got.sensitivity.agrees is True
    assert got.sensitivity.outcome == "better"
    assert got.sensitivity.rounds_set_aside == ()


def test_a_gap_equal_to_the_bar_is_inside_unless_inclusive(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16))
    floors = Floors(0.25)
    strict = only(grade(grid, STRICT, floors=floors))
    assert (strict.gap, strict.bar) == (0.5, 0.5)
    assert (strict.outcome, strict.reason) == ("unresolved", "inside_noise")
    assert strict.source == "supplied"
    inclusive = only(grade(grid, Rule("r", gap_inclusive=True), floors=floors))
    assert inclusive.outcome == "better"


def test_a_p_value_equal_to_alpha_is_significant_only_when_inclusive(
    grid_of: GridBuilder,
) -> None:
    grid = grid_of(entries([1.0] * 6, [2.0] * 6))
    floors = Floors(0.0625)
    base = {"alpha": 0.03125, "p_source": "raw", "min_rounds": 6}
    strict = only(grade(grid, Rule("r", **base), floors=floors))  # type: ignore[arg-type]
    assert strict.p_raw == 0.03125
    assert (strict.outcome, strict.reason) == ("unresolved", "not_significant")
    inclusive = only(grade(grid, Rule("r", p_inclusive=True, **base), floors=floors))  # type: ignore[arg-type]
    assert inclusive.outcome == "better"


def test_ties_are_not_trials(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0, 1.0, 1.0, 2.0, 2.0, 2.0], [2.0] * 6))
    got = only(grade(grid, STRICT, floors=Floors(0.0625)))
    assert (got.n_rounds, got.n_untied, got.n_lower, got.n_higher) == (6, 3, 3, 0)
    assert got.p_raw == 0.25


def test_the_tie_options_through_a_whole_grading(grid_of: GridBuilder) -> None:
    equal = grid_of(entries([2.0] * R16, [2.0] * R16))
    floors = Floors(0.0625)
    assert only(grade(equal, STRICT, floors=floors)).outcome == "tie"
    never = only(grade(equal, Rule("r", tie="never"), floors=floors))
    assert (never.outcome, never.reason) == ("unresolved", "inside_noise")
    close = grid_of(entries([1.9375] * R16, [2.0] * R16))
    strict = only(grade(close, STRICT, floors=floors))
    assert (strict.outcome, strict.reason) == ("unresolved", "inside_noise")
    assert only(grade(close, Rule("r", tie="inside"), floors=floors)).outcome == "tie"


def test_every_reason_is_listed_and_the_first_in_order_is_the_main_one(
    grid_of: GridBuilder,
) -> None:
    grid = grid_of(entries([0.0], [2.0]), order=False)
    got = only(grade(grid, STRICT))
    assert got.outcome == "no_verdict"
    assert got.reasons == (
        "nonpositive_value",
        "single_measurement",
        "order_not_recorded",
        "too_few_rounds",
        "no_floor",
    )
    assert got.reason == "nonpositive_value"
    assert got.p_raw is None
    assert got.ratio is None
    assert got.subject_median == 0.0


def test_one_pair_gives_no_p_value(grid_of: GridBuilder) -> None:
    got = only(grade(grid_of(entries([1.0], [2.0])), STRICT, floors=Floors(0.0625)))
    assert got.p_raw is None
    assert got.p_corrected is None
    assert got.reasons == ("single_measurement", "too_few_rounds")


def test_a_comparison_with_no_paired_round_has_zero_rounds(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0, None], [None, 2.0]))
    got = only(grade(grid, STRICT, floors=Floors(0.0625)))
    assert (got.n_rounds, got.n_unpaired) == (0, 2)
    assert got.reasons == ("too_few_rounds",)


def test_an_order_not_recorded_is_graded_only_when_assumed_interleaved(
    grid_of: GridBuilder,
) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16), order=False)
    floors = Floors(0.0625)
    assert only(grade(grid, STRICT, floors=floors)).reason == "order_not_recorded"
    assumed = only(grade(grid, STRICT, floors=floors, assume_interleaved=True))
    assert assumed.outcome == "better"
    assert assumed.order_split == (0, 0)


def test_missing_twins(grid_of: GridBuilder) -> None:
    neither = only(grade(grid_of(entries([1.0] * R16, OLD)), STRICT))
    assert neither.reasons == ("no_floor",)
    assert neither.mode == "NONE"
    assert neither.bar is None
    one = grid_of(entries([1.0] * R16, OLD, old_twin=OLD_TWIN))
    strict = only(grade(one, STRICT))
    assert strict.reasons == ("one_sided_floor",)
    assert strict.mode == "ONE-SIDED"
    loose = grade(one, Rule("r", require_both_floors=False))
    got = only(loose)
    assert got.outcome == "better"
    assert got.bar == 0.0625
    assert got.mode == "ONE-SIDED"
    assert loose.one_sided() == (got,)


def test_a_zero_floor_gives_no_verdict(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, OLD, new_twin=[1.0] * R16, old_twin=OLD_TWIN))
    got = only(grade(grid, STRICT))
    assert got.reasons == ("zero_floor",)
    rounding = grid_of(entries(NEW, [2.0] * R16, new_twin=NEW_TWIN, old_twin=[1.9375] * R16))
    assert only(grade(rounding, STRICT)).outcome == "better"
    assert only(grade(rounding, Rule("r", bar_round_digits=1))).reasons == ("zero_floor",)


def test_supplied_floors_per_side_and_the_bar_options(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16))
    floors = Floors({"new": 0.0625, "old": 0.125})
    assert only(grade(grid, STRICT, floors=floors)).bar == 0.1875
    assert only(grade(grid, Rule("r", bar="twice_larger"), floors=floors)).bar == 0.25
    assert only(grade(grid, Rule("r", bar="twice_experiment_max"), floors=floors)).bar == 0.25
    partly = only(grade(grid, STRICT, floors=Floors({"old": 0.125})))
    assert partly.reasons == ("one_sided_floor",)


def two_case_grid(grid_of: GridBuilder) -> Grid:
    # Floors of new: 1/16 on a, 1/8 on b, 1/2 on the secondary c; old: 1/16 everywhere.
    second = Case(id="b", metric="time", unit="s", kind="time")
    third = Case(id="c", metric="other", unit="s", kind="time", primary=False)
    first = Case(id="a", metric="time", unit="s", kind="time")
    values = {
        "new": {"a": [1.0625] * R16, "b": [1.125] * R16, "c": [1.5] * R16},
        "new~same": {"a": [1.0] * R16, "b": [1.0] * R16, "c": [1.0] * R16},
        "old": {"a": [2.125] * R16, "b": [2.125] * R16, "c": [2.125] * R16},
        "old~same": {"a": [2.0] * R16, "b": [2.0] * R16, "c": [2.0] * R16},
    }
    return grid_of(values, cases=(first, second, third))


@pytest.mark.parametrize(
    ("scope", "floor_a", "floor_c", "baseline_a"),
    [
        ("case", 0.0625, 0.5, 0.0625),
        ("group", 0.125, 0.5, 0.0625),
        ("side", 0.5, 0.5, 0.0625),
        ("experiment", 0.5, 0.5, 0.5),
    ],
)
def test_every_floor_scope(
    grid_of: GridBuilder, scope: str, floor_a: float, floor_c: float, baseline_a: float
) -> None:
    grading = grade(two_case_grid(grid_of), Rule("r", floor_scope=scope))  # type: ignore[arg-type]
    a = only(grading, "a")
    c = only(grading, "c")
    assert a.subject_floor is not None and a.subject_floor.value == floor_a
    assert c.subject_floor is not None and c.subject_floor.value == floor_c
    assert a.baseline_floor is not None and a.baseline_floor.value == baseline_a


def test_twice_the_experiment_floor(grid_of: GridBuilder) -> None:
    grading = grade(two_case_grid(grid_of), Rule("r", bar="twice_experiment_max"))
    assert only(grading, "a").bar == 1.0


def test_the_percent_scale_through_a_whole_grading(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16))
    got = only(grade(grid, Rule("r", scale="percent"), floors=Floors(1.0)))
    assert got.ratio == 0.5
    assert got.statistic == -50.0
    assert got.gap == 50.0
    assert got.bar == 2.0
    assert got.outcome == "better"


def test_secondary_comparisons_use_the_raw_p_value_and_stay_out_of_the_family(
    grid_of: GridBuilder,
) -> None:
    primary = Case(id="a", metric="time", unit="s", kind="time")
    secondary = Case(id="b", metric="time", unit="s", kind="time", primary=False)
    values = {
        "new": {"a": [1.0] * R16, "b": [1.0] * R16},
        "old": {"a": [2.0] * R16, "b": [2.0] * R16},
    }
    grading = grade(grid_of(values, cases=(primary, secondary)), STRICT, floors=Floors(0.0625))
    assert grading.family_size == 1
    assert grading.tests == 1
    b = only(grading, "b")
    assert b.p_corrected is None
    assert b.outcome == "better"


def test_a_case_that_describes_reads_higher_or_lower(grid_of: GridBuilder) -> None:
    cores = Case(id="res/cores", metric="cores", unit="cores", better="none", primary=False)
    values = {"new": {"res/cores": [8.0] * R16}, "old": {"res/cores": [1.0] * R16}}
    got = only(grade(grid_of(values, cases=(cores,)), STRICT, floors=Floors(0.0625)), "res/cores")
    assert got.outcome == "higher"


def test_a_failed_control_gives_every_comparison_no_verdict(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16))
    got = only(grade(grid, STRICT, floors=Floors(0.0625), control_failed=True))
    assert got.outcome == "no_verdict"
    assert got.reason == "positive_control_failed"
    assert got.ratio == 0.5


def test_a_value_of_zero_or_less_on_any_side_gives_the_case_no_verdict(
    grid_of: GridBuilder,
) -> None:
    values = {
        "a": {"matmul": [1.0] * R16},
        "b": {"matmul": [1.0] * 15 + [-1.0]},
        "old": {"matmul": [2.0] * R16},
    }
    grading = grade(grid_of(values, subjects=("a", "b")), STRICT, floors=Floors(0.0625))
    assert only(grading, subject="a").reason == "nonpositive_value"
    assert only(grading, subject="b").reason == "nonpositive_value"
    assert grading.tests == 2
    assert grading.family_size == 0


def test_a_floor_lost_to_a_zero_forms_no_one_sided_bar_under_a_rule_needing_both(
    grid_of: GridBuilder,
) -> None:
    values = {
        "new": {"matmul": NEW},
        "new~same": {"matmul": [0.0, *NEW_TWIN[1:]]},
        "old": {"matmul": [2.0] * R16},
        "old~same": {"matmul": [2.125] * R16},
    }
    grading = grade(grid_of(values), STRICT)
    got = only(grading)
    assert got.reason == "nonpositive_value"
    assert got.bar is None
    assert grading.one_sided() == ()
    loose = grade(grid_of(values), Rule("r", require_both_floors=False))
    assert only(loose).bar is not None
    assert loose.one_sided() == (only(loose),)


def test_a_zero_in_a_twin_round_touches_only_the_cases_of_that_group(
    grid_of: GridBuilder,
) -> None:
    first = Case(id="a", metric="time", unit="s", kind="time")
    own = Case(id="b", metric="time", unit="s", kind="time", group="b")
    values = {
        "new": {"a": NEW, "b": NEW},
        "new~same": {"a": [0.0, *NEW_TWIN[1:]], "b": NEW_TWIN},
        "old": {"a": [2.0] * R16, "b": [2.0] * R16},
        "old~same": {"a": [2.125] * R16, "b": [2.125] * R16},
    }
    grading = grade(grid_of(values, cases=(first, own)), STRICT)
    assert only(grading, "a").reason == "nonpositive_value"
    assert only(grading, "a").subject_floor is not None
    assert only(grading, "b").outcome == "better"
    rows = {(r.side, r.case): r for r in grading.same_vs_same}
    assert rows[("new", "a")].floor is None
    assert rows[("new", "a")].p_raw is None
    assert rows[("new", "b")].floor == 0.0625


def test_the_correction_spans_every_primary_case(grid_of: GridBuilder) -> None:
    # 18 rounds lower, 6 higher: p = 0.0227 alone, about 0.09 when four cases are tested.
    row = [1.0] * 18 + [2.125] * 6
    old = [2.0] * 24
    one = grade(
        grid_of({"new": {"matmul": row}, "old": {"matmul": old}}), STRICT, floors=Floors(0.0625)
    )
    assert only(one).outcome == "better"
    cases = tuple(Case(id=f"c{i}", metric="time", unit="s", kind="time") for i in range(4))
    four = grade(
        grid_of(
            {"new": {c.id: row for c in cases}, "old": {c.id: old for c in cases}}, cases=cases
        ),
        STRICT,
        floors=Floors(0.0625),
    )
    assert four.family_size == 4
    assert four.tests == 4
    assert four.needed == 8
    for case in cases:
        got = only(four, case.id)
        assert (got.outcome, got.reason) == ("unresolved", "not_significant")
        assert got.p_corrected == pytest.approx(4 * got.p_raw)


def test_the_family_is_every_subject_times_every_primary_case(grid_of: GridBuilder) -> None:
    # Two subjects and four primary cases are eight tests: a verdict needs 9
    # rounds, where four or six tests would need 8.
    cases = tuple(Case(id=f"c{i}", metric="time", unit="s", kind="time") for i in range(4))
    values = {
        entry: {c.id: [value] * 8 for c in cases}
        for entry, value in (("new", 1.0), ("mid", 1.5), ("old", 2.0))
    }
    graded = grade(
        grid_of(values, subjects=("new", "mid"), cases=cases), STRICT, floors=Floors(0.0625)
    )
    assert (graded.family_size, graded.tests, graded.needed) == (8, 8, 9)
    for subject in ("new", "mid"):
        for case in cases:
            assert "too_few_rounds" in only(graded, case.id, subject).reasons


def test_an_order_run_first_more_than_three_times_as_often_downgrades(
    grid_of: GridBuilder,
) -> None:
    positions = {}
    for r in range(1, R16 + 1):
        first = r <= 13
        positions[(r, "new")] = 1 if first else 2
        positions[(r, "old")] = 2 if first else 1
    grid = grid_of(entries([1.0] * R16, [2.0] * R16), positions=positions)
    got = only(grade(grid, STRICT, floors=Floors(0.0625)))
    assert got.order_split == (13, 3)
    assert (got.outcome, got.reason, got.reasons) == (
        "unresolved",
        "order_unbalanced",
        ("order_unbalanced",),
    )


def test_a_rule_with_a_fixed_minimum_of_rounds(grid_of: GridBuilder) -> None:
    grid = grid_of(entries([1.0] * R16, [2.0] * R16))
    got = only(grade(grid, Rule("r", min_rounds=20), floors=Floors(0.0625)))
    assert got.reasons == ("too_few_rounds",)


# 13 rounds lower and 3 higher: p = 0.0213. Without rounds 1 and 2 (both lower)
# it is 11 against 3, p = 0.0574, which is not significant.
SENSITIVE_NEW = [1.0] * 13 + [2.125] * 3


def test_a_verdict_that_changes_without_the_disturbed_rounds_is_downgraded(
    grid_of: GridBuilder,
) -> None:
    grid = grid_of(entries(SENSITIVE_NEW, [2.0] * R16), disturbed=(1, 2))
    got = only(grade(grid, STRICT, floors=Floors(0.0625)))
    assert got.p_raw == 1394 / 65536
    assert (got.outcome, got.reason) == ("unresolved", "sensitive_to_disturbed_rounds")
    assert got.sensitivity.rounds_set_aside == (1, 2)
    assert got.sensitivity.outcome == "unresolved"
    assert got.sensitivity.agrees is False
    calm = only(grade(grid_of(entries(SENSITIVE_NEW, [2.0] * R16)), STRICT, floors=Floors(0.0625)))
    assert calm.outcome == "better"


def test_setting_rounds_aside_never_produces_a_verdict(grid_of: GridBuilder) -> None:
    # 11 lower and 5 higher is not significant; without the five higher rounds it would be.
    new = [2.125] * 5 + [1.0] * 11
    grid = grid_of(entries(new, [2.0] * R16), disturbed=(1, 2, 3, 4, 5))
    got = only(grade(grid, STRICT, floors=Floors(0.0625)))
    assert got.outcome == "unresolved"
    assert got.reason == "not_significant"
    assert got.sensitivity.outcome == "better"
    assert got.sensitivity.agrees is False


def test_the_repeat_is_not_computed_with_too_few_or_too_many_rounds_left(
    grid_of: GridBuilder,
) -> None:
    few = grid_of(entries([1.0] * 8, [2.0] * 8), disturbed=(1, 2, 3))
    got = grade(few, STRICT, floors=Floors(0.0625))
    assert only(got).sensitivity.not_computed == "too_few_rounds"
    assert only(got).sensitivity.rounds_set_aside == (1, 2, 3)
    assert not got.busy
    many = grid_of(entries([1.0] * R16, [2.0] * R16), disturbed=tuple(range(1, 10)))
    busy = grade(many, STRICT, floors=Floors(0.0625))
    assert only(busy).sensitivity.not_computed == "too_many_disturbed"
    assert only(busy).outcome == "better"
    assert busy.busy


def test_exactly_half_the_rounds_disturbed_is_not_busy(grid_of: GridBuilder) -> None:
    half = grid_of(entries([1.0] * R16, [2.0] * R16), disturbed=tuple(range(1, 9)))
    got = grade(half, STRICT, floors=Floors(0.0625))
    assert not got.busy
    assert only(got).sensitivity.not_computed is None
    assert only(got).sensitivity.rounds_set_aside == tuple(range(1, 9))
    assert only(got).sensitivity.outcome == "better"


def check_of(check: Any) -> tuple[str, int, int, int, float | None, float | None]:
    """A side's combined check against its twin as one tuple."""
    return (
        check.side,
        check.n_rounds,
        check.n_better,
        check.n_worse,
        check.p_raw,
        check.p_corrected,
    )


def test_each_side_against_its_twin(grid_of: GridBuilder) -> None:
    grid = grid_of(entries(NEW, OLD, new_twin=NEW_TWIN, old_twin=OLD_TWIN))
    grading = grade(grid, STRICT)
    rows = {(r.side, r.case): r for r in grading.same_vs_same}
    assert set(rows) == {("new", "matmul"), ("old", "matmul")}
    new = rows[("new", "matmul")]
    assert (new.ratio, new.floor, new.n) == (1.0625, 0.0625, 16)
    assert new.p_raw == 2 / 65536
    # Each side reads 1/16 above its twin in all 16 rounds, and lower is
    # better: each looks worse than its twin in every round. Two sides are
    # tested, so each p-value is doubled.
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 16, 0, 16, 2 / 65536, 4 / 65536),
        ("old", 16, 0, 16, 2 / 65536, 4 / 65536),
    ]
    assert grading.twin_family_size() == 2
    assert [c.side for c in grading.twin_differs()] == ["new", "old"]


def test_a_side_against_its_twin_over_one_pair_has_no_p_value(grid_of: GridBuilder) -> None:
    grading = grade(grid_of(entries([1.0625], [2.125], new_twin=[1.0], old_twin=[2.0])), STRICT)
    assert [(r.side, r.n, r.floor, r.p_raw) for r in grading.same_vs_same] == [
        ("new", 1, 0.0625, None),
        ("old", 1, 0.0625, None),
    ]
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 1, 0, 1, None, None),
        ("old", 1, 0, 1, None, None),
    ]
    assert grading.twin_family_size() == 0
    assert grading.twin_differs() == ()


def test_a_side_differs_from_its_twin_only_below_five_percent(grid_of: GridBuilder) -> None:
    # The twin reads below its side in 12 rounds and above it in 4: p = 5034/65536,
    # doubled for the two sides tested.
    near = grade(
        grid_of(entries(NEW, OLD, new_twin=[1.0] * 12 + [1.125] * 4, old_twin=OLD)), STRICT
    )
    assert [(r.side, r.p_raw) for r in near.same_vs_same] == [("new", 5034 / 65536), ("old", 1.0)]
    assert [check_of(c) for c in near.twin_checks] == [
        ("new", 16, 4, 12, 5034 / 65536, 10068 / 65536),
        ("old", 16, 0, 0, 1.0, 1.0),
    ]
    assert near.twin_differs() == ()
    # 13 against 3: p = 1394/65536, doubled to 2788/65536, below 0.05.
    far = grade(grid_of(entries(NEW, OLD, new_twin=[1.0] * 13 + [1.125] * 3, old_twin=OLD)), STRICT)
    assert [(c.side, c.p_raw, c.p_corrected) for c in far.twin_differs()] == [
        ("new", 1394 / 65536, 2788 / 65536)
    ]


# Five primary cases where lower is better, as a batch run measures them.
FIVE = tuple(Case(id=f"c{i}", metric=f"m{i}", unit="s", kind="time") for i in range(5))
# Three load levels of five serving metrics, the three primary ones at the
# highest level: two where lower is better and one where higher is.
SERVING = tuple(
    Case(
        id=f"{level}/{metric}",
        metric=metric,
        unit=unit,
        better=better,
        primary=primary and level == "c32",
    )
    for level in ("c1", "c8", "c32")
    for metric, unit, better, primary in (
        ("ttft_ms_median", "ms", "lower", True),
        ("ttft_ms_p90", "ms", "lower", False),
        ("itl_ms_median", "ms", "lower", True),
        ("output_tokens_per_s", "1/s", "higher", True),
        ("requests_per_s", "1/s", "higher", False),
    )
)
# Eight primary cases where lower is better: a round of all eight is scored by
# the mean of the two in the middle.
EIGHT = tuple(Case(id=f"e{i}", metric=f"e{i}", unit="s", kind="time") for i in range(8))
SHAPES = {"batch": FIVE, "serving": SERVING, "eight": EIGHT}
# The primary cases of each shape made much noisier than the others: the last
# one, or the last two.
NOISIER = {
    "batch": ("c4",),
    "serving": ("c32/output_tokens_per_s",),
    "eight": ("e7",),
}
TWO_NOISIER = {
    "batch": ("c3", "c4"),
    "serving": ("c32/itl_ms_median", "c32/output_tokens_per_s"),
    "eight": ("e6", "e7"),
}
# Runs with no bias, and the tolerance on their rate of notes: three standard
# errors of a rate of 1 in 20 over that many runs.
NULL_RUNS = 2000
NULL_TOLERANCE = 3 * math.sqrt(0.05 * 0.95 / NULL_RUNS)
# Runs with a planted bias on one copy, and how many of them may miss the
# note. A serving side has three primary cases, so a round there leans with
# the bias only when two of its three do, and it may miss more often than a
# batch side, whose round needs three of five.
BIAS_RUNS = 100
BIAS_MISSES = {"batch": 2, "serving": 5}
# 14 rounds against 4 out of 18: p = 8096/262144, about 0.031.
P_14_OF_18 = 8096 / 262144
SPLIT_14_OF_18 = [0.99] * 14 + [1.01] * 4


def exact(rounds: int, cases: Sequence[Case]) -> Values:
    """Every twin reads exactly as its side: new reads 1 and old reads 2."""
    return {
        "new": {c.id: [1.0] * rounds for c in cases},
        "new~same": {c.id: [1.0] * rounds for c in cases},
        "old": {c.id: [2.0] * rounds for c in cases},
        "old~same": {c.id: [2.0] * rounds for c in cases},
    }


def noisy(
    seed: int,
    rounds: int,
    cases: Sequence[Case],
    *,
    slower: float = 0.0,
    on: Sequence[str] = (),
    loud: Sequence[str] = (),
) -> Values:
    """Every entry reads 1 with independent noise of 1 percent, or 20 percent on the cases ``loud``.

    The twin of new is ``slower`` slower on the cases ``on`` names: its value
    is multiplied by ``1 + slower`` where lower is better and divided by it
    where higher is better.
    """
    rng = random.Random(seed)
    values: Values = {
        name: {
            c.id: [
                1.0 + (0.2 if c.id in loud else 0.01) * rng.gauss(0.0, 1.0) for _ in range(rounds)
            ]
            for c in cases
        }
        for name in ("new", "new~same", "old", "old~same")
    }
    for c in cases:
        if c.id in on:
            factor = 1.0 + slower if c.better == "lower" else 1.0 / (1.0 + slower)
            twin = values["new~same"][c.id]
            values["new~same"][c.id] = [factor * v for v in twin if v is not None]
    return values


# The first primary case of each shape.
FIRST_PRIMARY = {"batch": "c0", "serving": "c32/ttft_ms_median"}


def bias_twin(values: Values, cases: Sequence[Case], ids: Sequence[str], bias: float) -> None:
    """Make the twin of new read ``bias`` slower on the cases ``ids`` names, in every round.

    Slower is ``1 + bias`` times new's value where lower is better and
    ``1 - bias`` times it where higher is better.
    """
    for case in cases:
        if case.id in ids:
            factor = 1.0 + bias if case.better == "lower" else 1.0 - bias
            values["new~same"][case.id] = [
                factor * v for v in values["new"][case.id] if v is not None
            ]


@pytest.mark.parametrize(
    ("shape", "rounds", "noise"),
    [
        ("batch", 16, "equal"),
        ("serving", 8, "equal"),
        ("batch", 16, "one noisier case"),
        ("serving", 16, "one noisier case"),
        ("batch", 16, "two noisier cases"),
        ("serving", 16, "two noisier cases"),
        ("eight", 8, "equal"),
        ("eight", 16, "equal"),
    ],
)
def test_runs_with_no_bias_get_the_twin_note_at_most_one_time_in_twenty(
    grid_of: GridBuilder, shape: str, rounds: int, noise: str
) -> None:
    # Swapping a side and its twin in a round turns that round's median the
    # other way and leaves the others, so with no bias each round leans
    # either way with chance one half, however noisy each case is.
    cases = SHAPES[shape]
    loud = {"equal": (), "one noisier case": NOISIER, "two noisier cases": TWO_NOISIER}[noise]
    noted = sum(
        1
        for seed in range(NULL_RUNS)
        if grade(
            grid_of(noisy(seed, rounds, cases, loud=loud[shape] if loud else ()), cases=cases),
            STRICT,
        ).twin_differs()
    )
    assert noted / NULL_RUNS <= 0.05 + NULL_TOLERANCE


@pytest.mark.parametrize("shape", ["batch", "serving"])
def test_a_broad_bias_on_one_copy_gives_the_twin_note_at_eight_rounds(
    grid_of: GridBuilder, shape: str
) -> None:
    # The twin of new is 3 percent slower on every primary case: a copy the
    # machine treats unfairly moves all of its measurements at once.
    cases = SHAPES[shape]
    primary = [c.id for c in cases if c.primary]
    noted = 0
    for seed in range(BIAS_RUNS):
        values = noisy(seed, 8, cases, slower=0.03, on=primary)
        sides = {r.side for r in grade(grid_of(values, cases=cases), STRICT).twin_differs()}
        noted += "new" in sides
    assert noted >= BIAS_RUNS - BIAS_MISSES[shape]


def test_a_round_is_scored_by_the_median_of_its_primary_cases(grid_of: GridBuilder) -> None:
    # In every round the twin of new reads 1.01 times new on c0, c2 and c4,
    # and 0.75 times new on c1 and c3. The median follows the three that
    # lean a little, so new looks better in all 8 rounds, though the mean of
    # the five would make it look worse.
    values = exact(8, FIVE)
    for case, twin in zip(
        ("c0", "c1", "c2", "c3", "c4"), (1.01, 0.75, 1.01, 0.75, 1.01), strict=True
    ):
        values["new~same"][case] = [twin] * 8
    grading = grade(grid_of(values, cases=FIVE), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 8, 0, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert [c.side for c in grading.twin_differs()] == ["new"]


@pytest.mark.parametrize("shape", ["batch", "serving"])
def test_a_bias_on_one_primary_case_alone_gives_no_twin_note(
    grid_of: GridBuilder, shape: str
) -> None:
    # The twin of new is 1 percent slower on the first primary case in all 8
    # rounds and reads as new on the others. The case in the middle of every
    # round reads as its twin, so every round is a tie. Its same-against-same
    # row still shows p = 2/256.
    cases = SHAPES[shape]
    values = exact(8, cases)
    bias_twin(values, cases, [FIRST_PRIMARY[shape]], 0.01)
    grading = grade(grid_of(values, cases=cases), STRICT)
    rows = {(r.side, r.case): r.p_raw for r in grading.same_vs_same}
    assert rows[("new", FIRST_PRIMARY[shape])] == 2 / 256
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 0, 0, 1.0, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert grading.twin_differs() == ()


def test_a_bias_on_one_quiet_primary_case_beside_a_much_noisier_one_gives_no_twin_note(
    grid_of: GridBuilder,
) -> None:
    # The twin of new is 1 percent slower on c0 in all 8 rounds. On c4 it
    # reads 1.1 times new in odd rounds and new 1.1 times it in even ones, as
    # a much noisier case would; the others read as new. The case in the
    # middle of every round reads as its twin, so every round is a tie,
    # whichever way c4 leans.
    values = exact(8, FIVE)
    values["new~same"]["c0"] = [1.01] * 8
    values["new~same"]["c4"] = [1.1, 1 / 1.1] * 4
    grading = grade(grid_of(values, cases=FIVE), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 0, 0, 1.0, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert grading.twin_differs() == ()


@pytest.mark.parametrize("shape", ["batch", "serving"])
@pytest.mark.parametrize("noisier", [False, True])
def test_a_bias_shared_by_every_primary_case_gives_the_twin_note(
    grid_of: GridBuilder, shape: str, noisier: bool
) -> None:
    # The twin of new is 1 percent slower on every primary case. With a much
    # noisier case, the twin's value of the last primary case is also
    # multiplied by 1.1 in odd rounds and divided by it in even ones, so that
    # case leans one way and then the other: the others still lean with the
    # bias, so the median does, and new looks better in all 8 rounds.
    cases = SHAPES[shape]
    primary = [c.id for c in cases if c.primary]
    values = exact(8, cases)
    bias_twin(values, cases, primary, 0.01)
    if noisier:
        (last,) = NOISIER[shape]
        twin = values["new~same"][last]
        values["new~same"][last] = [
            v * swing for v, swing in zip(twin, [1.1, 1 / 1.1] * 4, strict=True) if v is not None
        ]
    grading = grade(grid_of(values, cases=cases), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 8, 0, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert [c.side for c in grading.twin_differs()] == ["new"]


@pytest.mark.parametrize(("shape", "biased"), [("batch", 3), ("serving", 2)])
def test_a_bias_shared_by_most_primary_cases_gives_the_twin_note(
    grid_of: GridBuilder, shape: str, biased: int
) -> None:
    # The twin of new is 1 percent slower on three of five primary cases, or
    # two of three, and reads as new on the rest: the case in the middle of
    # every round leans, and new looks better in all 8 rounds.
    cases = SHAPES[shape]
    ids = [c.id for c in cases if c.primary][:biased]
    values = exact(8, cases)
    bias_twin(values, cases, ids, 0.01)
    grading = grade(grid_of(values, cases=cases), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 8, 0, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert [c.side for c in grading.twin_differs()] == ["new"]


def test_a_bias_on_two_of_five_primary_cases_gives_no_twin_note_when_the_rest_read_as_their_twins(
    grid_of: GridBuilder,
) -> None:
    # The twin of new is 1 percent slower on c0 and c1 and reads as new on
    # the other three: the case in the middle of every round reads as its
    # twin, and every round is a tie. With noise on the other three, a round
    # leans with the bias whenever one of them leans its way.
    values = exact(8, FIVE)
    bias_twin(values, FIVE, ["c0", "c1"], 0.01)
    grading = grade(grid_of(values, cases=FIVE), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 0, 0, 1.0, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert grading.twin_differs() == ()


def test_a_round_of_two_primary_cases_is_scored_by_their_mean(grid_of: GridBuilder) -> None:
    # The twin of new is 1 percent slower on c0 and reads as new on c1. The
    # median of two cases is their mean, so c0 makes new look better in every
    # round.
    two = FIVE[:2]
    values = exact(8, two)
    values["new~same"]["c0"] = [1.01] * 8
    grading = grade(grid_of(values, cases=two), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 8, 0, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert [c.side for c in grading.twin_differs()] == ["new"]


def test_the_median_of_a_round_is_taken_over_the_cases_scored_in_it(
    grid_of: GridBuilder,
) -> None:
    # The twin of new is 1 percent slower on c0 in all 8 rounds and reads as
    # new on c1 and c2, but has no value of c2 from round 5 on. Rounds 1 to 4
    # score three cases, whose middle one reads as its twin: ties. Rounds 5 to
    # 8 score two, whose mean leans with c0: 4 against 0, p = 2/16.
    three = FIVE[:3]
    values = exact(8, three)
    values["new~same"]["c0"] = [1.01] * 8
    values["new~same"]["c2"] = [1.0] * 4 + [None] * 4
    grading = grade(grid_of(values, cases=three), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 4, 0, 2 / 16, 4 / 16),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_a_round_of_an_even_number_of_cases_is_scored_by_the_mean_of_the_two_in_the_middle(
    grid_of: GridBuilder,
) -> None:
    # Four primary cases. The twin of new reads 3 times new on c0 and half of
    # it on c2 in every round; on c1 and c3, the two in the middle, it reads
    # 0.98 and 1.01 times new in rounds 1 to 3 and 0.99 and 1.02 times new in
    # rounds 4 to 8. The two in the middle multiply to below 1 in the first
    # three rounds and above 1 in the other five: 5 against 3. Either middle
    # case alone, or the mean of all four, would put every round one way.
    four = FIVE[:4]
    values = exact(8, four)
    values["new~same"]["c0"] = [3.0] * 8
    values["new~same"]["c1"] = [0.98] * 3 + [0.99] * 5
    values["new~same"]["c2"] = [0.5] * 8
    values["new~same"]["c3"] = [1.01] * 3 + [1.02] * 5
    grading = grade(grid_of(values, cases=four), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 5, 3, 186 / 256, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_the_cases_of_a_round_are_put_in_order_by_their_exact_quotients(
    grid_of: GridBuilder,
) -> None:
    # Four primary cases. On c0 the twin of new reads a little more than 1.25
    # times new, and on c1 a little less, though both quotients round to 1.25
    # in floating point; on c2 it reads exactly 0.8 times new and on c3 half
    # of it. In exact order c1 comes before c0, so the two in the middle are
    # c2 and c1, whose quotients multiply to just below 1: new looks worse in
    # every round. Put in order by the rounded quotients, c0 would stay first
    # of the two and the middle pair would multiply to just above 1.
    assert 1.366217793073376 / 1.0929742344587008 == 1.2578872983181393 / 1.0063098386545115
    four = FIVE[:4]
    values = exact(8, four)
    values["new"]["c0"] = [1.0929742344587008] * 8
    values["new~same"]["c0"] = [1.366217793073376] * 8
    values["new"]["c1"] = [1.0063098386545115] * 8
    values["new~same"]["c1"] = [1.2578872983181393] * 8
    values["new"]["c2"] = [1.25] * 8
    values["new"]["c3"] = [2.0] * 8
    grading = grade(grid_of(values, cases=four), STRICT)
    assert check_of(grading.twin_checks[0]) == ("new", 8, 0, 8, 2 / 256, 4 / 256)


def one_case_bound(cases: int, rounds: int) -> float:
    """Return the chance that new gets the note when one of its odd number of primary cases leans.

    That case makes new look better in every round, and each of the other
    ``cases - 1`` leans either way with chance one half, so a round makes new
    look better when at least half of the others do. Every round of old is a
    fair coin. The note needs new's p-value of the exact two-sided sign test,
    corrected with Holm's method across the two sides, below 0.05.
    """
    others = cases - 1
    lean = Fraction(sum(math.comb(others, k) for k in range(others // 2, others + 1)), 2**others)

    def p_of(k: int) -> Fraction:
        tail = sum(math.comb(rounds, i) for i in range(min(k, rounds - k) + 1))
        return min(Fraction(1), Fraction(2 * tail, 2**rounds))

    total = Fraction(0)
    for k in range(rounds + 1):
        chance_k = math.comb(rounds, k) * lean**k * (1 - lean) ** (rounds - k)
        for j in range(rounds + 1):
            new, old = p_of(k), p_of(j)
            corrected = 2 * new if new <= old else max(2 * old, new)
            if corrected < Fraction(1, 20):
                total += chance_k * Fraction(math.comb(rounds, j), 2**rounds)
    return float(total)


@pytest.mark.parametrize(
    ("shape", "rounds", "noisier"),
    [
        ("batch", 8, False),
        ("batch", 16, False),
        ("serving", 8, False),
        ("serving", 16, False),
        ("batch", 16, True),
        ("serving", 16, True),
    ],
)
def test_a_bias_on_one_primary_case_gives_the_twin_note_at_most_as_often_as_one_leaning_every_round(
    grid_of: GridBuilder, shape: str, rounds: int, noisier: bool
) -> None:
    # The twin of new is 5 percent slower on the first primary case, five
    # times the noise of a value, and with a much noisier case its last
    # primary case has 20 percent noise. A round leans with the bias only when
    # at least half of the other cases lean its way by chance, so new gets the
    # note at most as often as one_case_bound gives, however large the bias
    # and however noisy the other cases.
    cases = SHAPES[shape]
    noted = 0
    for seed in range(NULL_RUNS):
        values = noisy(
            seed,
            rounds,
            cases,
            slower=0.05,
            on=[FIRST_PRIMARY[shape]],
            loud=NOISIER[shape] if noisier else (),
        )
        sides = {r.side for r in grade(grid_of(values, cases=cases), STRICT).twin_differs()}
        noted += "new" in sides
    bound = one_case_bound(sum(c.primary for c in cases), rounds)
    assert noted / NULL_RUNS <= bound + 3 * math.sqrt(bound * (1 - bound) / NULL_RUNS)


def test_a_side_with_one_primary_case_is_checked_on_that_case_alone(grid_of: GridBuilder) -> None:
    # The secondary case and the case that only describes differ from their
    # twins in every round, and stay out of the check.
    primary = Case(id="a", metric="time", unit="s", kind="time")
    secondary = Case(id="b", metric="other", unit="s", kind="time", primary=False)
    cores = Case(id="res/cores", metric="cores", unit="cores", better="none", primary=False)
    values: Values = {
        "new": {"a": NEW, "b": [1.0] * R16, "res/cores": [4.0] * R16},
        "new~same": {"a": [1.0] * 13 + [1.125] * 3, "b": [0.5] * R16, "res/cores": [8.0] * R16},
        "old": {"a": OLD, "b": [1.0] * R16, "res/cores": [4.0] * R16},
        "old~same": {"a": OLD, "b": [1.0] * R16, "res/cores": [4.0] * R16},
    }
    grading = grade(grid_of(values, cases=(primary, secondary, cores)), STRICT)
    rows = {(r.side, r.case): r.p_raw for r in grading.same_vs_same}
    assert (rows[("new", "a")], rows[("new", "b")], rows[("new", "res/cores")]) == (
        1394 / 65536,
        2 / 65536,
        2 / 65536,
    )
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 16, 3, 13, 1394 / 65536, 2788 / 65536),
        ("old", 16, 0, 0, 1.0, 1.0),
    ]


def test_a_run_whose_cases_only_describe_gets_no_twin_check(grid_of: GridBuilder) -> None:
    # A primary case always has a better direction.
    with pytest.raises(Refusal) as caught:
        Case(id="x", metric="m", unit="s", better="none")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    cores = Case(id="res/cores", metric="cores", unit="cores", better="none", primary=False)
    values = entries([4.0] * 8, [4.0] * 8, new_twin=[8.0] * 8, old_twin=[4.0] * 8, case=cores.id)
    grading = grade(grid_of(values, cases=(cores,)), STRICT)
    assert [(r.side, r.p_raw) for r in grading.same_vs_same] == [("new", 2 / 256), ("old", 1.0)]
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 0, 0, 0, None, None),
        ("old", 0, 0, 0, None, None),
    ]
    assert grading.twin_family_size() == 0
    assert grading.twin_differs() == ()


def test_a_round_is_scored_from_the_primary_cases_measured_in_it(grid_of: GridBuilder) -> None:
    # Rounds 1 to 4 hold c0 alone, where the twin of new is slower: new looks
    # better. Rounds 5 to 7 hold both cases, and the twin's lead on c1
    # outweighs its lag on c0: new looks worse. Round 8 holds neither and is
    # not scored.
    two = FIVE[:2]
    values = exact(8, two)
    values["new~same"]["c0"] = [1.01] * 7 + [None]
    values["new~same"]["c1"] = [None] * 4 + [0.97] * 3 + [None]
    grading = grade(grid_of(values, cases=two), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 7, 4, 3, 1.0, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_a_value_of_zero_or_less_is_left_out_of_its_round_score(grid_of: GridBuilder) -> None:
    # The twin of new reads 0 on c1 in round 1 and new reads -1 there in
    # round 2: those values stay out of the score of their round, which c0
    # alone then decides. The case itself gets no verdict for that value.
    two = FIVE[:2]
    values = exact(8, two)
    values["new~same"]["c0"] = [1.01] * 8
    values["new~same"]["c1"] = [0.0] + [1.0] * 7
    values["new"]["c1"] = [1.0, -1.0] + [1.0] * 6
    grading = grade(grid_of(values, cases=two), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 8, 0, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert (only(grading, "c1").outcome, only(grading, "c1").reason) == (
        "no_verdict",
        "nonpositive_value",
    )


def test_a_value_of_zero_or_less_on_the_side_itself_is_left_out_of_its_round_score(
    grid_of: GridBuilder,
) -> None:
    # The twin of new reads 1 percent below it on c0 in every round, so new
    # looks worse there. New itself reads 0 on c1 in round 1 and -1 there in
    # round 2: those values stay out of the score of their round, which c0
    # alone then decides, so all 8 rounds lean against new.
    two = FIVE[:2]
    values = exact(8, two)
    values["new~same"]["c0"] = [0.99] * 8
    values["new"]["c1"] = [0.0, -1.0] + [1.0] * 6
    grading = grade(grid_of(values, cases=two), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 0, 8, 2 / 256, 4 / 256),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_rounds_whose_combined_score_is_zero_are_ties_and_dropped(grid_of: GridBuilder) -> None:
    # The twin of new reads as new in rounds 1 and 2 and 1 percent slower in
    # the other six: 6 against 0 with two ties, p = 2/64. Old ties in every
    # round, p = 1, so two sides are tested and 2/64 doubles to 0.0625: no
    # note, though the uncorrected p-value is below 0.05.
    one = grade(
        grid_of(entries([1.0] * 8, [2.0] * 8, new_twin=[1.0] * 2 + [1.01] * 6, old_twin=[2.0] * 8)),
        STRICT,
    )
    assert [check_of(c) for c in one.twin_checks] == [
        ("new", 8, 6, 0, 2 / 64, 4 / 64),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert one.twin_differs() == ()
    # In rounds 1 and 2 the twin reads twice new on c0 and half of it on c1:
    # the two logs cancel exactly, and the round is a tie.
    two = FIVE[:2]
    values = exact(8, two)
    values["new~same"]["c0"] = [2.0] * 2 + [1.01] * 6
    values["new~same"]["c1"] = [0.5] * 2 + [1.0] * 6
    cancel = grade(grid_of(values, cases=two), STRICT)
    assert [check_of(c) for c in cancel.twin_checks] == [
        ("new", 8, 6, 0, 2 / 64, 4 / 64),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_each_case_is_turned_by_its_better_direction(grid_of: GridBuilder) -> None:
    # Where higher is better, a twin that reads above its side makes the side
    # look worse.
    rate = Case(id="rate", metric="rate", unit="1/s", better="higher")
    up = grade(
        grid_of(
            entries([1.0] * 8, [2.0] * 8, new_twin=[1.01] * 8, old_twin=[2.0] * 8, case="rate"),
            cases=(rate,),
        ),
        STRICT,
    )
    assert check_of(up.twin_checks[0]) == ("new", 8, 0, 8, 2 / 256, 4 / 256)
    # A twin that reads twice its side where lower is better and half of it
    # where higher is better makes the side look better on both cases.
    time = Case(id="time", metric="time", unit="s", kind="time")
    values: Values = {
        "new": {"time": [1.0] * 8, "rate": [1.0] * 8},
        "new~same": {"time": [2.0] * 8, "rate": [0.5] * 8},
        "old": {"time": [2.0] * 8, "rate": [2.0] * 8},
        "old~same": {"time": [2.0] * 8, "rate": [2.0] * 8},
    }
    both = grade(grid_of(values, cases=(time, rate)), STRICT)
    assert check_of(both.twin_checks[0]) == ("new", 8, 8, 0, 2 / 256, 4 / 256)


def test_a_side_is_scored_by_the_order_of_its_values_however_far_or_near(
    grid_of: GridBuilder,
) -> None:
    # new over its twin is beyond the largest float: new reads higher, and
    # looks worse, in every round.
    far = grade(
        grid_of(entries([1e300] * 8, [2.0] * 8, new_twin=[1e-300] * 8, old_twin=[2.0] * 8)),
        STRICT,
    )
    assert check_of(far.twin_checks[0]) == ("new", 8, 0, 8, 2 / 256, 4 / 256)
    # The twin reads the next float above new: a difference, not a tie, as
    # in the same-against-same rows.
    above = math.nextafter(1e10, math.inf)
    near = grade(
        grid_of(entries([1e10] * 8, [2.0] * 8, new_twin=[above] * 8, old_twin=[2.0] * 8)),
        STRICT,
    )
    assert near.same_vs_same[0].p_raw == 2 / 256
    assert check_of(near.twin_checks[0]) == ("new", 8, 8, 0, 2 / 256, 4 / 256)


def test_the_twin_note_steps_down_as_holm_does(grid_of: GridBuilder) -> None:
    # The twin of new reads below it in all 18 rounds; the twin of old reads
    # below it in 14 and above it in 4. Holm multiplies the larger p-value by
    # one, so both are noted; multiplying both by two would give about 0.062.
    grid = grid_of(
        entries(
            [1.0] * 18,
            [2.0] * 18,
            new_twin=[0.99] * 18,
            old_twin=[2.0 * v for v in SPLIT_14_OF_18],
        )
    )
    got = grade(grid, STRICT)
    assert [check_of(c) for c in got.twin_checks] == [
        ("new", 18, 0, 18, 2 / 2**18, 4 / 2**18),
        ("old", 18, 4, 14, P_14_OF_18, P_14_OF_18),
    ]
    assert [c.side for c in got.twin_differs()] == ["new", "old"]


def test_a_side_without_a_p_value_stays_out_of_the_correction(grid_of: GridBuilder) -> None:
    # The twin of old ran in one round only: old has no p-value, and new is
    # the one side tested, so 2/64 stays 2/64.
    grading = grade(
        grid_of(
            entries(
                [1.0] * 8,
                [2.0] * 8,
                new_twin=[1.0] * 2 + [1.01] * 6,
                old_twin=[2.0] + [None] * 7,
            )
        ),
        STRICT,
    )
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 6, 0, 2 / 64, 2 / 64),
        ("old", 1, 0, 0, None, None),
    ]
    assert grading.twin_family_size() == 1
    assert [c.side for c in grading.twin_differs()] == ["new"]


@pytest.mark.parametrize(("sides", "noted"), [(6, True), (7, False)])
def test_at_eight_rounds_the_twin_note_reaches_at_most_six_sides(
    grid_of: GridBuilder, sides: int, noted: bool
) -> None:
    # The twin of s0 reads above it in all 8 rounds: p = 2/256, times the
    # sides tested. 6 sides give 12/256, about 0.047; 7 give 14/256, about 0.055.
    names = [f"s{i}" for i in range(sides)]
    values: Values = {}
    for name in names:
        values[name] = {"matmul": [1.0] * 8}
        values[f"{name}~same"] = {"matmul": [1.0] * 8}
    values["s0~same"] = {"matmul": [1.01] * 8}
    grading = grade(grid_of(values, subjects=names[:-1], baseline=names[-1]), STRICT)
    assert grading.twin_family_size() == sides
    assert check_of(grading.twin_checks[0]) == ("s0", 8, 8, 0, 2 / 256, sides * 2 / 256)
    assert [c.side for c in grading.twin_differs()] == (["s0"] if noted else [])


@pytest.mark.parametrize(
    ("rounds", "twinned", "noted"), [(6, 1, True), (6, 2, False), (7, 2, True)]
)
def test_the_twin_note_needs_six_one_way_rounds_for_one_side_and_seven_for_the_smaller_of_two(
    grid_of: GridBuilder, rounds: int, twinned: int, noted: bool
) -> None:
    # The twin of new reads above it in every round. With two sides tested, old
    # reads as its twin in every round, so new's p-value is the smaller.
    old_twin = [2.0] * rounds if twinned == 2 else None
    values = entries([1.0] * rounds, [2.0] * rounds, new_twin=[1.01] * rounds, old_twin=old_twin)
    grading = grade(grid_of(values), STRICT)
    p = 2 / 2**rounds
    assert check_of(grading.twin_checks[0]) == ("new", rounds, rounds, 0, p, twinned * p)
    assert [c.side for c in grading.twin_differs()] == (["new"] if noted else [])


@pytest.mark.parametrize(
    ("rounds", "old_ties", "expected", "noted"),
    [
        (
            7,
            1,
            [("new", 7, 7, 0, 2 / 128, 4 / 128), ("old", 7, 6, 0, 2 / 64, 4 / 128)],
            ["new", "old"],
        ),
        (
            8,
            2,
            [("new", 8, 8, 0, 2 / 256, 4 / 256), ("old", 8, 6, 0, 2 / 64, 2 / 64)],
            ["new", "old"],
        ),
    ],
)
def test_beside_a_side_noted_with_seven_one_way_rounds_six_give_the_twin_note(
    grid_of: GridBuilder,
    rounds: int,
    old_ties: int,
    expected: list[tuple[str, int, int, int, float, float]],
    noted: list[str],
) -> None:
    # The twin of new reads above it in every round. The twin of old reads
    # above it in all but its last rounds, where it reads as old: ties. The
    # correction doubles the smaller p-value and keeps the larger at least as
    # high, so old's 6 untied rounds give the note beside new's 7 or 8.
    old_twin = [2.02] * (rounds - old_ties) + [2.0] * old_ties
    values = entries([1.0] * rounds, [2.0] * rounds, new_twin=[1.01] * rounds, old_twin=old_twin)
    grading = grade(grid_of(values), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == expected
    assert [c.side for c in grading.twin_differs()] == noted


def test_two_sides_with_six_one_way_rounds_each_give_no_twin_note(grid_of: GridBuilder) -> None:
    # Both twins read above their sides in 6 of 7 rounds and as them in the
    # last: each p-value is 2/64, and the correction doubles the first.
    values = entries([1.0] * 7, [2.0] * 7, new_twin=[1.01] * 6 + [1.0], old_twin=[2.02] * 6 + [2.0])
    grading = grade(grid_of(values), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 7, 6, 0, 2 / 64, 4 / 64),
        ("old", 7, 6, 0, 2 / 64, 4 / 64),
    ]
    assert grading.twin_differs() == ()


@pytest.mark.parametrize(
    ("side", "twin"),
    [
        ((1.1, 1.3), (1.3, 1.1)),
        ((7.0, 11.0), (11.0, 7.0)),
        ((1.0, 1.0, 2.0), (3.0, 1.0, 1.0)),
        ((1.0, 1.25, 1.0, 1.0), (1.25, 1.0, 9.0, 0.125)),
        ((1e300, 1e-300), (1e-300, 1e300)),
    ],
)
def test_a_round_whose_turned_quotients_multiply_to_one_is_a_tie(
    grid_of: GridBuilder, side: tuple[float, ...], twin: tuple[float, ...]
) -> None:
    # The twin of new reads above new on some cases and below it on others.
    # With two cases the turned quotients multiply to exactly 1; with three,
    # the one in the middle is exactly 1; with four, the two in the middle
    # multiply to exactly 1. The median of the turned logs is exactly zero in
    # every round, so every round is a tie and the check gives no note.
    cases = FIVE[: len(side)]
    values = exact(8, cases)
    for case, s, t in zip(cases, side, twin, strict=True):
        values["new"][case.id] = [s] * 8
        values["new~same"][case.id] = [t] * 8
    grading = grade(grid_of(values, cases=cases), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 0, 0, 1.0, 1.0),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]
    assert grading.twin_differs() == ()


def test_a_twin_one_float_step_above_its_side_leans_every_round(grid_of: GridBuilder) -> None:
    # The twin of new reads the next float above new's value in every round:
    # the product is not exactly 1, so no round is a tie.
    above = math.nextafter(1.0, 2.0)
    grading = grade(
        grid_of(entries([1.0] * 8, [2.0] * 8, new_twin=[above] * 8, old_twin=[2.0] * 8)),
        STRICT,
    )
    assert check_of(grading.twin_checks[0]) == ("new", 8, 8, 0, 2 / 256, 4 / 256)


def test_a_round_is_scored_by_the_product_of_its_quotients(grid_of: GridBuilder) -> None:
    # On c0 the twin of new reads 1.42 where new reads 1, and on c1 1.42 where
    # new reads 1.96: the quotients 1.42 and 1.42 / 1.96 multiply to about
    # 1.03, above 1, so new looks better in every round, though the twin's two
    # values add up to less than new's.
    cases = FIVE[:2]
    values = exact(8, cases)
    values["new"] = {"c0": [1.0] * 8, "c1": [1.96] * 8}
    values["new~same"] = {"c0": [1.42] * 8, "c1": [1.42] * 8}
    grading = grade(grid_of(values, cases=cases), STRICT)
    assert check_of(grading.twin_checks[0]) == ("new", 8, 8, 0, 2 / 256, 4 / 256)


# Grids whose side and twin are swapped, and the cases they draw from: where
# lower is better and where higher is, in turn.
SWAP_GRIDS = 200
SWAP_SEED = 7919
SWAP_CASES = (
    Case(id="c0", metric="m0", unit="s", kind="time"),
    Case(id="r0", metric="r0", unit="1/s", better="higher"),
    Case(id="c1", metric="m1", unit="s", kind="time"),
    Case(id="r1", metric="r1", unit="1/s", better="higher"),
)


def test_swapping_a_side_and_its_twin_turns_every_round_the_other_way(
    grid_of: GridBuilder,
) -> None:
    # In half of the rounds two of the cases cancel exactly: one reads x on the
    # side and y on the twin, and the other reads y and x where it leans the
    # same way as the first, or x and y where it leans the other way. Every
    # other case reads the same on both. In the other half each case leans by
    # a small random factor. With side and twin swapped, each round that
    # looked better looks worse and each tie stays a tie. In a round that
    # cancels, the turned quotient in the middle is exactly 1, or the two in
    # the middle multiply to exactly 1, so the ties come from grids of every
    # size.
    rng = random.Random(SWAP_SEED)
    ties = 0
    for _ in range(SWAP_GRIDS):
        cases = SWAP_CASES[: rng.randint(2, 4)]
        values = exact(16, cases)
        for r in range(16):
            cancel = rng.random() < 0.5
            first, second = rng.sample(range(len(cases)), 2)
            x, y = rng.uniform(0.5, 2.0), rng.uniform(0.5, 2.0)
            for i, case in enumerate(cases):
                side = rng.uniform(0.5, 2.0)
                if not cancel:
                    twin = side * math.exp(rng.uniform(-0.05, 0.05))
                elif i == first:
                    side, twin = x, y
                elif i == second and case.better == cases[first].better:
                    side, twin = y, x
                elif i == second:
                    side, twin = x, y
                else:
                    twin = side
                values["new"][case.id][r] = side
                values["new~same"][case.id][r] = twin
        swapped = {**values, "new": values["new~same"], "new~same": values["new"]}
        got = grade(grid_of(values, cases=cases), STRICT).twin_checks[0]
        back = grade(grid_of(swapped, cases=cases), STRICT).twin_checks[0]
        assert (back.n_rounds, back.n_better, back.n_worse) == (
            got.n_rounds,
            got.n_worse,
            got.n_better,
        )
        ties += got.n_rounds - got.n_better - got.n_worse
    assert ties > 0


# Six cases to draw a grid of one to six from, and how many grids to draw.
SWAP_SIX = (
    *SWAP_CASES,
    Case(id="c2", metric="m2", unit="s", kind="time"),
    Case(id="r2", metric="r2", unit="1/s", better="higher"),
)
SWAP_ROUND_GRIDS = 60


def test_swapping_a_side_and_its_twin_in_one_round_turns_that_round_alone(
    grid_of: GridBuilder,
) -> None:
    # In each round every case, at random, reads the same on the side and the
    # twin, reads x and y or y and x so that two such cases cancel exactly,
    # leans by a small random factor, or has no value on the twin. Swapping
    # the side and its twin in round r turns the score of round r on its own
    # the other way and moves the counts of the whole grid by that round and
    # no other.
    rng = random.Random(SWAP_SEED + 1)
    seen: set[tuple[int, int, int]] = set()
    for _ in range(SWAP_ROUND_GRIDS):
        cases = SWAP_SIX[: rng.randint(1, 6)]
        values = exact(8, cases)
        for r in range(8):
            x, y = rng.uniform(0.5, 2.0), rng.uniform(0.5, 2.0)
            for case in cases:
                side = rng.uniform(0.5, 2.0)
                pick = rng.random()
                twin: float | None
                if pick < 0.3:
                    twin = side
                elif pick < 0.6:
                    side, twin = (x, y) if rng.random() < 0.5 else (y, x)
                elif pick < 0.7:
                    twin = None
                else:
                    twin = side * math.exp(rng.uniform(-0.05, 0.05))
                values["new"][case.id][r] = side
                values["new~same"][case.id][r] = twin
        grid = grid_of(values, cases=cases)
        whole = grade(grid, STRICT).twin_checks[0]
        for r in range(8):
            alone = grade(grid.keeping([r + 1]), STRICT).twin_checks[0]
            seen.add((alone.n_rounds, alone.n_better, alone.n_worse))
            turned = {name: {c: list(v) for c, v in per.items()} for name, per in values.items()}
            for case in cases:
                turned["new"][case.id][r] = values["new~same"][case.id][r]
                turned["new~same"][case.id][r] = values["new"][case.id][r]
            back = grade(grid_of(turned, cases=cases), STRICT).twin_checks[0]
            assert (back.n_rounds, back.n_better, back.n_worse) == (
                whole.n_rounds,
                whole.n_better - alone.n_better + alone.n_worse,
                whole.n_worse - alone.n_worse + alone.n_better,
            )
    assert {(1, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 0)} <= seen


@pytest.mark.parametrize(
    ("sides", "twin", "check"),
    [
        # 8 rounds of 8 one way: 2/256, doubled for two sides.
        (2, [1.01] * 8, ("s0", 8, 8, 0, 2 / 256, 4 / 256)),
        # 7 one way and 1 the other: 18/256, doubled to about 0.14.
        (2, [1.01] * 7 + [0.99], ("s0", 8, 7, 1, 18 / 256, 36 / 256)),
        # 7 one way and 1 tie: 2/128 over the 7 untied rounds, doubled.
        (2, [1.01] * 7 + [1.0], ("s0", 8, 7, 0, 2 / 128, 4 / 128)),
        # Three sides: 8 of 8 gives 6/256, and 7 untied with 1 tie gives 6/128.
        (3, [1.01] * 8, ("s0", 8, 8, 0, 2 / 256, 6 / 256)),
        (3, [1.01] * 7 + [1.0], ("s0", 8, 7, 0, 2 / 128, 6 / 128)),
    ],
)
def test_at_eight_rounds_the_twin_note_needs_every_untied_round_to_agree(
    grid_of: GridBuilder,
    sides: int,
    twin: list[float],
    check: tuple[str, int, int, int, float, float],
) -> None:
    names = [f"s{i}" for i in range(sides)]
    values: Values = {}
    for name in names:
        values[name] = {"matmul": [1.0] * 8}
        values[f"{name}~same"] = {"matmul": [1.0] * 8}
    values["s0~same"] = {"matmul": twin}
    grading = grade(grid_of(values, subjects=names[:-1], baseline=names[-1]), STRICT)
    assert grading.twin_family_size() == sides
    assert check_of(grading.twin_checks[0]) == check
    noted = check[5] < 0.05
    assert [c.side for c in grading.twin_differs()] == (["s0"] if noted else [])
    # At 8 rounds the note comes only when no untied round leans the other way.
    assert (min(check[2], check[3]) == 0) == noted


def test_at_eight_rounds_a_side_beside_one_whose_eight_rounds_all_agree_keeps_its_raw_p_value(
    grid_of: GridBuilder,
) -> None:
    # s1 leans 8 of 8 (2/256) and s0 7 one way and 1 the other (18/256): the correction
    # doubles the smaller and leaves s0 at its raw 18/256, about 0.07, so only s1 is noted.
    values: Values = {
        "s0": {"matmul": [1.0] * 8},
        "s0~same": {"matmul": [1.01] * 7 + [0.99]},
        "s1": {"matmul": [1.0] * 8},
        "s1~same": {"matmul": [1.01] * 8},
    }
    grading = grade(grid_of(values, subjects=["s0"], baseline="s1"), STRICT)
    assert [check_of(c) for c in grading.twin_checks] == [
        ("s0", 8, 7, 1, 18 / 256, 18 / 256),
        ("s1", 8, 8, 0, 2 / 256, 4 / 256),
    ]
    assert [c.side for c in grading.twin_differs()] == ["s1"]


@pytest.mark.parametrize("unusable", [0.0, math.inf, math.nan])
def test_a_round_whose_only_value_is_unusable_is_not_scored(
    grid_of: GridBuilder, unusable: float
) -> None:
    # The twin of new reads a value that is not a finite number above zero in
    # round 1 and 1 percent above new in the other seven: round 1 is not
    # scored, so 7 of 7.
    grading = grade(
        grid_of(
            entries([1.0] * 8, [2.0] * 8, new_twin=[unusable] + [1.01] * 7, old_twin=[2.0] * 8)
        ),
        STRICT,
    )
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 7, 7, 0, 2 / 128, 4 / 128),
        ("old", 8, 0, 0, 1.0, 1.0),
    ]


def test_a_side_scored_in_two_rounds_counts_in_the_correction(grid_of: GridBuilder) -> None:
    # The twin of old ran in two rounds, reading above old in both: p = 2/4.
    # Two sides are tested, so the 2/64 of new doubles to 0.0625: no note.
    grading = grade(
        grid_of(
            entries(
                [1.0] * 8,
                [2.0] * 8,
                new_twin=[1.0] * 2 + [1.01] * 6,
                old_twin=[2.02, 2.02] + [None] * 6,
            )
        ),
        STRICT,
    )
    assert [check_of(c) for c in grading.twin_checks] == [
        ("new", 8, 6, 0, 2 / 64, 4 / 64),
        ("old", 2, 2, 0, 0.5, 0.5),
    ]
    assert grading.twin_family_size() == 2
    assert grading.twin_differs() == ()


def test_a_floor_from_fewer_than_eight_rounds_is_reported_provisional(
    grid_of: GridBuilder,
) -> None:
    grid = grid_of(entries([1.0] * 6, [2.125] * 6, new_twin=[1.0 / 1.0625] * 6, old_twin=[2.0] * 6))
    grading = grade(grid, STRICT)
    assert grading.provisional()
    assert not grade(
        grid_of(entries(NEW, OLD, new_twin=NEW_TWIN, old_twin=OLD_TWIN)), STRICT
    ).provisional()


@pytest.mark.parametrize(
    "rule",
    [
        STRICT,
        Rule("r", floor_scope="case"),
        Rule("r", floor_scope="side"),
        Rule("r", floor_scope="experiment"),
        Rule("r", bar="twice_experiment_max"),
    ],
    ids=["group", "case", "side", "experiment", "twice_experiment_max"],
)
def test_a_zero_in_a_resource_case_touches_no_other_case_under_any_scope(
    grid_of: GridBuilder, rule: Rule
) -> None:
    faults = resource_case("res/faults_major")
    zeros = [0.0] * R16
    values = {
        "new": {"matmul": [1.0] * R16, "res/faults_major": zeros},
        "new~same": {"matmul": [1.0 / 1.0625] * R16, "res/faults_major": zeros},
        "old": {"matmul": [2.125] * R16, "res/faults_major": zeros},
        "old~same": {"matmul": [2.0] * R16, "res/faults_major": zeros},
    }
    grading = grade(grid_of(values, cases=(MATMUL, faults)), rule)
    assert only(grading, "matmul").outcome == "better"
    assert only(grading, "res/faults_major").reason == "nonpositive_value"


def test_a_zero_in_a_twin_round_reaches_every_case_of_its_group_under_the_case_scope(
    grid_of: GridBuilder,
) -> None:
    second = Case(id="b", metric="time", unit="s", kind="time")
    values = {
        "new": {"matmul": NEW, "b": NEW},
        "new~same": {"matmul": [0.0, *NEW_TWIN[1:]], "b": NEW_TWIN},
        "old": {"matmul": [2.0] * R16, "b": [2.0] * R16},
        "old~same": {"matmul": [2.125] * R16, "b": [2.125] * R16},
    }
    grading = grade(grid_of(values, cases=(MATMUL, second)), Rule("r", floor_scope="case"))
    assert only(grading, "matmul").reason == "nonpositive_value"
    assert only(grading, "b").reason == "nonpositive_value"
