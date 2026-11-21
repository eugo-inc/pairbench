# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The verdict rule: every option of the rule object, the table, the reasons and the downgrades.

Values are dyadic and floors are supplied where a test sits on a boundary, so
that equality is exact.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

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


def test_each_side_against_its_twin(grid_of: GridBuilder) -> None:
    grid = grid_of(entries(NEW, OLD, new_twin=NEW_TWIN, old_twin=OLD_TWIN))
    grading = grade(grid, STRICT)
    rows = {(r.side, r.case): r for r in grading.same_vs_same}
    assert set(rows) == {("new", "matmul"), ("old", "matmul")}
    new = rows[("new", "matmul")]
    assert (new.ratio, new.floor, new.n) == (1.0625, 0.0625, 16)
    assert new.p_raw == 2 / 65536
    assert grading.twin_differs() == (rows[("new", "matmul")], rows[("old", "matmul")])


def test_a_side_against_its_twin_over_one_pair_has_no_p_value(grid_of: GridBuilder) -> None:
    grading = grade(grid_of(entries([1.0625], [2.125], new_twin=[1.0], old_twin=[2.0])), STRICT)
    assert [(r.side, r.n, r.floor, r.p_raw) for r in grading.same_vs_same] == [
        ("new", 1, 0.0625, None),
        ("old", 1, 0.0625, None),
    ]
    assert grading.twin_differs() == ()


def test_a_side_differs_from_its_twin_only_below_five_percent(grid_of: GridBuilder) -> None:
    # The twin reads below its side in 12 rounds and above it in 4: p = 5034/65536.
    near = grade(
        grid_of(entries(NEW, OLD, new_twin=[1.0] * 12 + [1.125] * 4, old_twin=OLD)), STRICT
    )
    assert [(r.side, r.p_raw) for r in near.same_vs_same] == [("new", 5034 / 65536), ("old", 1.0)]
    assert near.twin_differs() == ()
    # 13 against 3: p = 1394/65536.
    far = grade(grid_of(entries(NEW, OLD, new_twin=[1.0] * 13 + [1.125] * 3, old_twin=OLD)), STRICT)
    assert [(r.side, r.p_raw) for r in far.twin_differs()] == [("new", 1394 / 65536)]


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
