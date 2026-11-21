# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Known answers of the pure rules that live in ``pairbench.model``.

Each rule exists once, in the model. This file holds its known answers as
constants; the modules that use a rule call it and hold no second copy.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
import shlex
import statistics
from pathlib import Path
from typing import Any

import pytest

from pairbench import model
from pairbench.errors import Refusal
from pairbench.model import (
    DiscardThresholds,
    Plan,
    PlanRow,
    RoundWitness,
    Side,
    Witness,
)

# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------

TWO = ("A", "B")
THREE = ("A", "B", "C")


def _orders(lineup: tuple[str, ...], rounds: int) -> list[str]:
    return ["".join(model.rotate_reverse(lineup, r)) for r in range(1, rounds + 1)]


def test_the_schedule_of_two_entries() -> None:
    assert _orders(TWO, 4) == ["AB", "BA", "BA", "AB"]


def test_the_schedule_of_three_entries() -> None:
    assert _orders(THREE, 6) == ["ABC", "BCA", "CAB", "CBA", "ACB", "BAC"]


def test_the_schedule_repeats_after_twice_the_lineup_length() -> None:
    assert _orders(THREE, 12)[6:] == ["ABC", "BCA", "CAB", "CBA", "ACB", "BAC"]


def test_the_schedule_of_an_empty_lineup_is_empty() -> None:
    assert model.rotate_reverse((), 1) == ()


def test_rounds_are_numbered_from_one() -> None:
    with pytest.raises(ValueError, match="rounds are numbered from 1"):
        model.rotate_reverse(TWO, 0)


def test_the_schedule_name() -> None:
    assert model.SCHEDULE == "rotate-reverse"


# ---------------------------------------------------------------------------
# Plan rows and balance
# ---------------------------------------------------------------------------


def _lineup() -> tuple[Side, ...]:
    new = Side(name="new", kind="cmd", role="subject")
    old = Side(name="old", kind="cmd", role="baseline")
    return (new, new.twin(), old, old.twin())


def _plan(rounds: int) -> Plan:
    lineup = _lineup()
    rows = model.plan_rows(lineup, rounds)
    pairs = model.compared_pairs(lineup)
    return Plan(
        rows=rows,
        rounds_requested=rounds,
        rounds_planned=rounds,
        lineup=tuple(s.name for s in lineup),
        balance=model.count_balance(rows, pairs),
        launches=len(rows) + 2,
    )


def test_plan_rows_follow_the_schedule_and_carry_the_twin_relation() -> None:
    rows = model.plan_rows(_lineup(), 2)
    assert rows == (
        PlanRow(round=1, pos=1, name="new", side="new", twin_of=None),
        PlanRow(round=1, pos=2, name="new~same", side="new", twin_of="new"),
        PlanRow(round=1, pos=3, name="old", side="old", twin_of=None),
        PlanRow(round=1, pos=4, name="old~same", side="old", twin_of="old"),
        PlanRow(round=2, pos=1, name="new~same", side="new", twin_of="new"),
        PlanRow(round=2, pos=2, name="old", side="old", twin_of=None),
        PlanRow(round=2, pos=3, name="old~same", side="old", twin_of="old"),
        PlanRow(round=2, pos=4, name="new", side="new", twin_of=None),
    )


def test_the_compared_pairs_are_subject_with_baseline_and_each_side_with_its_twin() -> None:
    assert model.compared_pairs(_lineup()) == (
        ("new", "old"),
        ("new", "new~same"),
        ("old", "old~same"),
    )


@pytest.mark.parametrize("rounds", [8, 16, 24])
def test_two_sides_with_twins_are_balanced_on_every_pair(rounds: int) -> None:
    plan = _plan(rounds)
    half = rounds // 2
    assert [(p.a, p.b, p.a_first, p.b_first, p.position_sum) for p in plan.balance] == [
        ("new", "old", half, half, 0),
        ("new", "new~same", half, half, 0),
        ("old", "old~same", half, half, 0),
    ]
    assert plan.is_balanced() is True


@pytest.mark.parametrize(("rounds", "first", "second"), [(12, 7, 5), (20, 11, 9)])
def test_two_sides_with_twins_are_uneven_on_the_twin_pairs(
    rounds: int, first: int, second: int
) -> None:
    plan = _plan(rounds)
    by_pair = {(p.a, p.b): (p.a_first, p.b_first) for p in plan.balance}
    assert by_pair[("new", "old")] == (rounds // 2, rounds // 2)
    assert by_pair[("new", "new~same")] == (first, second)
    assert by_pair[("old", "old~same")] == (first, second)
    assert plan.is_balanced() is False


def test_balance_fails_one_round_before_the_balanced_count() -> None:
    assert _plan(8).is_balanced() is True
    assert _plan(7).is_balanced() is False


def test_the_smallest_balanced_count_is_found_by_search() -> None:
    assert _plan(3).balanced_step() == 8


def test_the_smallest_balanced_count_without_twins() -> None:
    new = Side(name="new", kind="cmd", role="subject")
    old = Side(name="old", kind="cmd", role="baseline")
    rows = model.plan_rows((new, old), 1)
    plan = Plan(
        rows=rows,
        rounds_requested=1,
        rounds_planned=1,
        lineup=("new", "old"),
        balance=model.count_balance(rows, model.compared_pairs((new, old))),
        launches=4,
    )
    assert plan.balanced_step() == 2


def test_one_entry_alone_is_balanced_after_one_round() -> None:
    only = Side(name="only", kind="cmd", role="baseline")
    rows = model.plan_rows((only,), 3)
    plan = Plan(
        rows=rows,
        rounds_requested=3,
        rounds_planned=3,
        lineup=("only",),
        balance=model.count_balance(rows, model.compared_pairs((only,))),
        launches=4,
    )
    assert plan.balance == ()
    assert plan.is_balanced() is True
    assert plan.balanced_step() == 1


def test_pairs_that_are_even_do_not_make_a_plan_balanced_when_positions_are_not() -> None:
    rows = (
        PlanRow(round=1, pos=1, name="new", side="new"),
        PlanRow(round=1, pos=2, name="old", side="old"),
        PlanRow(round=1, pos=3, name="other", side="other"),
        PlanRow(round=2, pos=1, name="old", side="old"),
        PlanRow(round=2, pos=2, name="new", side="new"),
        PlanRow(round=2, pos=3, name="other", side="other"),
    )
    balance = model.count_balance(rows, (("new", "old"),))
    assert [(p.a_first, p.b_first, p.position_sum, p.balanced) for p in balance] == [
        (1, 1, 0, True)
    ]
    plan = Plan(
        rows=rows,
        rounds_requested=2,
        rounds_planned=2,
        lineup=("new", "old", "other"),
        balance=balance,
        launches=6,
    )
    assert plan.is_balanced() is False


def test_a_plan_row_is_numbered_from_one() -> None:
    with pytest.raises(ValueError, match=r"PlanRow\.round: expected at least 1"):
        PlanRow(round=0, pos=1, name="new", side="new")
    with pytest.raises(ValueError, match=r"PlanRow\.pos: expected at least 1"):
        PlanRow(round=1, pos=0, name="new", side="new")


def test_the_plan_table_has_the_five_columns() -> None:
    assert _plan(1).to_tsv() == (
        "round\tpos\tname\tside\ttwin_of\n"
        "1\t1\tnew\tnew\t\n"
        "1\t2\tnew~same\tnew\tnew\n"
        "1\t3\told\told\t\n"
        "1\t4\told~same\told\told\n"
    )


def test_a_round_without_both_of_a_pair_is_not_counted() -> None:
    rows = (
        PlanRow(round=1, pos=1, name="new", side="new"),
        PlanRow(round=1, pos=2, name="old", side="old"),
        PlanRow(round=2, pos=1, name="old", side="old"),
    )
    (pair,) = model.count_balance(rows, [("new", "old")])
    assert (pair.a_first, pair.b_first, pair.position_sum) == (1, 0, -1)


# ---------------------------------------------------------------------------
# The fewest rounds that can give a verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cases", "rounds"), [(1, 6), (2, 7), (4, 8), (10, 9), (35, 11), (100, 12)]
)
def test_the_fewest_rounds_for_a_number_of_cases(cases: int, rounds: int) -> None:
    assert model.min_rounds(cases) == rounds
    assert model.min_rounds(cases, 0.05) == rounds


@pytest.mark.parametrize(
    ("cases", "alpha", "rounds"),
    [(1, 0.5, 3), (4, 0.25, 6), (2, 0.125, 6), (1, 0.25, 4)],
)
def test_the_bound_is_strict_where_it_is_met_exactly(cases: int, alpha: float, rounds: int) -> None:
    assert cases * 2.0 ** (1 - (rounds - 1)) == alpha
    assert model.min_rounds(cases, alpha) == rounds


def test_eight_rounds_hold_for_at_most_six_cases() -> None:
    assert model.min_rounds(6) == 8
    assert model.min_rounds(7) == 9


def test_the_fewest_rounds_follow_alpha() -> None:
    assert model.min_rounds(1, 0.01) == 8


@pytest.mark.parametrize(("cases", "alpha"), [(0, 0.05), (1, 0.0), (1, 1.0)])
def test_the_fewest_rounds_refuse_what_makes_no_sense(cases: int, alpha: float) -> None:
    with pytest.raises(ValueError):
        model.min_rounds(cases, alpha)


# ---------------------------------------------------------------------------
# The trapezoid integral
# ---------------------------------------------------------------------------


def test_ten_twenty_and_thirty_watts_over_one_second_are_twenty_joules() -> None:
    assert model.trapezoid([0.0, 0.5, 1.0], [10.0, 20.0, 30.0]) == 20.0


def test_fewer_than_two_samples_integrate_to_zero() -> None:
    assert model.trapezoid([], []) == 0.0
    assert model.trapezoid([3.0], [50.0]) == 0.0


def test_uneven_sample_times_are_weighted_by_their_step() -> None:
    assert model.trapezoid([0.0, 1.0, 4.0], [2.0, 4.0, 4.0]) == 15.0


def test_the_integral_refuses_times_that_decrease_or_differ_in_length() -> None:
    with pytest.raises(ValueError, match="must not decrease"):
        model.trapezoid([0.0, 1.0, 0.5], [1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="differ in length"):
        model.trapezoid([0.0, 1.0], [1.0])


# ---------------------------------------------------------------------------
# The quantile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        ([1.0, 2.0, 3.0, 4.0], 0.25, 1.75),
        ([1.0, 2.0, 3.0, 4.0], 0.5, 2.5),
        ([1.0, 2.0, 3.0, 4.0], 0.75, 3.25),
        ([3.0, 1.0, 2.0], 0.5, 2.0),
        ([10.0, 20.0, 30.0, 40.0, 50.0], 0.9, 46.0),
        ([10.0, 20.0, 30.0, 40.0, 50.0], 0.0, 10.0),
        ([10.0, 20.0, 30.0, 40.0, 50.0], 1.0, 50.0),
        ([7.0], 0.9, 7.0),
    ],
)
def test_the_quantile_interpolates_between_closest_ranks(
    values: list[float], q: float, expected: float
) -> None:
    assert model.quantile(values, q) == pytest.approx(expected, abs=1e-12)


def test_the_median_of_an_even_count_is_half_the_sum_of_the_two_middle_values() -> None:
    # (0.1 + 0.7) / 2 and 0.1 + (0.7 - 0.1) * 0.5 differ in the last bit.
    assert model.quantile([0.7, 0.1], 0.5) == 0.39999999999999997
    # A quartile keeps the interpolation.
    assert model.quantile([0.1, 0.7], 0.25) == 0.1 + (0.7 - 0.1) * 0.25


def test_the_median_equals_the_standard_library_median_bit_for_bit() -> None:
    rng = random.Random(4817)
    for _ in range(500):
        values = [rng.uniform(0.001, 1000.0) for _ in range(2 * rng.randint(1, 20))]
        assert model.quantile(values, 0.5) == statistics.median(values), values


@pytest.mark.parametrize(
    ("values", "q", "expected"),
    [
        # The two middle values add up to more than the largest float.
        ([1.6e308, 1.7e308], 0.5, 1.65e308),
        ([1.7e308, 1.7e308, 1.7e308, 1.7e308], 0.5, 1.7e308),
        # Their difference is more than the largest float.
        ([-1.7e308, 1.7e308], 0.5, 0.0),
        ([-1.6e308, 1.6e308], 0.25, -0.8e308),
    ],
)
def test_the_quantile_of_values_near_the_largest_float_is_a_finite_number(
    values: list[float], q: float, expected: float
) -> None:
    assert model.quantile(values, q) == pytest.approx(expected, rel=1e-15)


@pytest.mark.parametrize(
    ("ratio", "fault"),
    [
        (1.0, None),
        (1e300, None),
        (float("inf"), "large"),
        (float("nan"), "large"),
        (0.0, "zero"),
        (5e-324, "inverse"),
        (1e307, "percent"),
    ],
)
def test_the_ratio_fault_names_the_figure_of_a_ratio_that_is_no_finite_number(
    ratio: float, fault: str | None
) -> None:
    assert model.ratio_fault(ratio) == fault


def test_the_quantile_refuses_no_values_and_a_q_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        model.quantile([], 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        model.quantile([1.0], 1.5)


# ---------------------------------------------------------------------------
# The decision on disturbed rounds
# ---------------------------------------------------------------------------

THRESHOLDS = DiscardThresholds()
QUIET = Witness(busy_cores=0.25, busy_cores_cache=0.0, gpu_other_processes=0, gpu_throttle_events=0)

# sha256 of the canonical JSON of the default thresholds and the rounds set aside:
# {"rounds":[...],"thresholds":{"max_busy_cores":2.0,"max_gpu_other_processes":0,
# "max_gpu_throttle_events":0}}
HASH_NO_ROUND = "76d1f9b8cd2dbbf9305f1a462a2569570bf9ae9839d00f3a67a704203edb87ff"
HASH_ROUND_2 = "9dd282fa11f134a689df334991a7c6033189628a16a910a7c77f2bc6912b5706"
HASH_ROUNDS_1_3 = "30bf8aca3f8bb7c666b0d636cb4deffbf1618498caeb4231b88e32ec41eb96aa"


def test_the_default_thresholds() -> None:
    assert (
        THRESHOLDS.max_busy_cores,
        THRESHOLDS.max_gpu_other_processes,
        THRESHOLDS.max_gpu_throttle_events,
    ) == (2.0, 0, 0)


@pytest.mark.parametrize(
    ("witness", "over"),
    [
        (QUIET, ()),
        (Witness(busy_cores=2.0), ()),
        (Witness(busy_cores=2.5), ("busy_cores",)),
        (Witness(gpu_other_processes=1), ("gpu_other_processes",)),
        (Witness(gpu_throttle_events=1), ("gpu_throttle_events",)),
        (
            Witness(busy_cores=9.0, gpu_other_processes=2, gpu_throttle_events=3),
            ("busy_cores", "gpu_other_processes", "gpu_throttle_events"),
        ),
        (Witness(busy_cores_cache=64.0), ()),
    ],
)
def test_a_witness_above_its_threshold_is_named(witness: Witness, over: tuple[str, ...]) -> None:
    assert model.exceeded(witness, THRESHOLDS) == over


def test_a_witness_that_does_not_apply_exceeds_nothing() -> None:
    assert model.exceeded(Witness(), THRESHOLDS) == ()


@pytest.mark.parametrize("name", ["busy_cores", "gpu_other_processes", "gpu_throttle_events"])
def test_a_witness_whose_probe_failed_counts_as_exceeding(name: str) -> None:
    assert model.exceeded(Witness(failed=(name,)), THRESHOLDS) == (name,)
    assert model.exceeded(QUIET.with_failed(name), THRESHOLDS) == (name,)


def test_the_cache_witness_has_no_threshold_even_when_its_probe_failed() -> None:
    assert model.exceeded(Witness(failed=("busy_cores_cache",)), THRESHOLDS) == ()


def test_a_failed_witness_holds_no_value_and_a_known_name() -> None:
    with pytest.raises(ValueError, match="a failed witness has no value: busy_cores"):
        Witness(busy_cores=1.0, failed=("busy_cores",))
    with pytest.raises(ValueError, match="not a witness: made_up"):
        Witness(failed=("made_up",))
    assert QUIET.with_failed("busy_cores").busy_cores is None


# A launch that cannot report its own CPU time, counted with its own load in.
WITH_LAUNCH_UNDER = Witness(busy_cores=1.5, includes_launch=("busy_cores",))
WITH_LAUNCH_OVER = Witness(busy_cores=3.5, includes_launch=("busy_cores",))


def test_a_witness_with_the_launch_in_it_is_not_disturbed_at_or_under_its_threshold() -> None:
    assert model.exceeded(WITH_LAUNCH_UNDER, THRESHOLDS) == ()
    assert model.undecided(WITH_LAUNCH_UNDER, THRESHOLDS) == ()
    at = Witness(busy_cores=2.0, includes_launch=("busy_cores",))
    assert model.undecided(at, THRESHOLDS) == ()


def test_a_witness_with_the_launch_in_it_is_undecided_above_its_threshold() -> None:
    # Not exceeding, so the round is kept, and not a pass.
    assert model.exceeded(WITH_LAUNCH_OVER, THRESHOLDS) == ()
    assert model.undecided(WITH_LAUNCH_OVER, THRESHOLDS) == ("busy_cores",)
    both = dataclasses.replace(WITH_LAUNCH_OVER, gpu_other_processes=1)
    assert model.exceeded(both, THRESHOLDS) == ("gpu_other_processes",)
    assert model.undecided(both, THRESHOLDS) == ("busy_cores",)


def test_undecided_is_kept_apart_from_a_failed_probe() -> None:
    assert model.undecided(Witness(failed=("busy_cores",)), THRESHOLDS) == ()
    assert model.undecided(Witness(busy_cores=3.5), THRESHOLDS) == ()
    assert model.undecided(QUIET, THRESHOLDS) == ()
    failed = WITH_LAUNCH_OVER.with_failed("busy_cores")
    assert failed.includes_launch == ()
    assert model.exceeded(failed, THRESHOLDS) == ("busy_cores",)


def test_the_cache_witness_with_the_launch_in_it_decides_nothing() -> None:
    cache = Witness(busy_cores_cache=64.0, includes_launch=("busy_cores_cache",))
    assert model.exceeded(cache, THRESHOLDS) == ()
    assert model.undecided(cache, THRESHOLDS) == ()


@pytest.mark.parametrize(
    ("values", "words"),
    [
        ({"includes_launch": ("busy_cores",)}, "a witness with the launch in it has a value"),
        (
            {"busy_cores": 1.0, "includes_launch": ("gpu_other_processes",)},
            "only the busy-core witnesses can hold the launch",
        ),
        (
            {"busy_cores": 1.0, "includes_launch": ("busy_cores", "busy_cores")},
            "a witness with the launch in it is named once",
        ),
        ({"includes_launch": ("made_up",)}, "not a witness: made_up"),
    ],
)
def test_a_witness_with_the_launch_in_it_is_refused_when_malformed(
    values: dict[str, object], words: str
) -> None:
    with pytest.raises(ValueError, match=words):
        Witness(**values)  # type: ignore[arg-type]


def test_an_undecided_launch_sets_no_round_aside() -> None:
    witnesses = [
        RoundWitness(round=1, name="new", witness=WITH_LAUNCH_OVER),
        RoundWitness(round=1, name="old", witness=QUIET),
    ]
    decision = model.set_aside(THRESHOLDS, witnesses)
    assert decision.rounds == ()
    assert decision.sha256 == HASH_NO_ROUND


def test_a_witness_with_no_includes_launch_key_holds_none() -> None:
    assert Witness.from_json({"busy_cores": 0.5}).includes_launch == ()
    written = WITH_LAUNCH_OVER.to_json()
    assert written["includes_launch"] == ["busy_cores"]
    assert Witness.from_json(written) == WITH_LAUNCH_OVER


def test_one_disturbed_launch_marks_its_whole_round() -> None:
    witnesses = [
        RoundWitness(round=1, name="new", witness=QUIET),
        RoundWitness(round=1, name="old", witness=QUIET),
        RoundWitness(round=2, name="new", witness=QUIET),
        RoundWitness(round=2, name="old", witness=Witness(busy_cores=3.5)),
    ]
    decision = model.set_aside(THRESHOLDS, witnesses)
    assert decision.rounds == (2,)
    assert decision.sha256 == HASH_ROUND_2


def test_no_disturbed_launch_sets_no_round_aside() -> None:
    decision = model.set_aside(THRESHOLDS, [RoundWitness(round=1, name="new", witness=QUIET)])
    assert decision.rounds == ()
    assert decision.sha256 == HASH_NO_ROUND


def test_a_failed_probe_marks_its_round_and_a_missing_witness_does_not() -> None:
    witnesses = [
        RoundWitness(round=1, name="new", witness=Witness(failed=("gpu_other_processes",))),
        RoundWitness(round=2, name="new", witness=Witness()),
        RoundWitness(round=3, name="new", witness=Witness(gpu_throttle_events=2)),
    ]
    decision = model.set_aside(THRESHOLDS, witnesses)
    assert decision.rounds == (1, 3)
    assert decision.sha256 == HASH_ROUNDS_1_3


def test_the_decision_takes_a_type_without_any_measurement_field() -> None:
    measured = {"value", "values", "timing", "run_s", "launch_s", "energy", "rc", "case", "seq"}
    for cls in (Witness, RoundWitness, DiscardThresholds):
        names = {f.name for f in dataclasses.fields(cls)}
        assert names & measured == set(), cls.__name__
    assert [f.name for f in dataclasses.fields(Witness)] == [
        "busy_cores",
        "busy_cores_cache",
        "gpu_other_processes",
        "gpu_throttle_events",
        "failed",
        "includes_launch",
    ]
    assert [f.name for f in dataclasses.fields(RoundWitness)] == ["round", "name", "witness"]


def test_the_decision_of_a_capture_does_not_change_when_measured_values_are_altered() -> None:
    def capture(scale: float) -> model.Capture:
        rows = [
            (1, "new", "matmul", 1.5 * scale),
            (1, "old", "matmul", 3.0 * scale),
            (2, "new", "matmul", 1.25 * scale),
            (2, "old", "matmul", 2.75 * scale),
        ]
        made = model.Capture.from_rows(rows, sides=["new", "old"])
        launches = tuple(
            dataclasses.replace(
                launch,
                witness={"busy_cores": 3.0 if launch.round == 2 else 0.5},
                timing={"run_s": 10.0 * scale},
            )
            for launch in made.launches
        )
        assert made.lineup is not None
        lineup = dataclasses.replace(made.lineup, discard_thresholds=THRESHOLDS)
        return dataclasses.replace(made, launches=launches, lineup=lineup)

    first = capture(1.0).set_aside()
    second = capture(1000.0).set_aside()
    assert first is not None
    assert first.rounds == (2,)
    assert first.sha256 == HASH_ROUND_2
    assert second == first


def test_a_capture_without_recorded_thresholds_has_no_decision() -> None:
    made = model.Capture.from_rows([(1, "new", "matmul", 1.5)], sides=["new"])
    assert made.set_aside() is None


# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------


def test_the_canonical_json_text_has_sorted_keys_and_no_spaces() -> None:
    assert model.canonical_json({"b": [1, 2.0], "a": {"d": None, "c": "x"}}) == (
        '{"a":{"c":"x","d":null},"b":[1,2.0]}'
    )
    assert model.canonical_json({"t": THRESHOLDS}) == (
        '{"t":{"max_busy_cores":2.0,"max_gpu_other_processes":0,"max_gpu_throttle_events":0}}'
    )


def test_sha256_of_a_text() -> None:
    assert model.sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_a_fingerprint_is_the_hash_of_identity_and_launch_settings() -> None:
    # sha256 of {"identity":{"image_id":"sha256:aaaa"},"launch":{"args":[],"env":{}}}
    assert model.fingerprint_of({"image_id": "sha256:aaaa"}, {"args": [], "env": {}}) == (
        "f9802e13d663db37e8b4e18dc48cde5b47d7ee4e2540936e50bc303b6ad51804"
    )


def test_a_fingerprint_does_not_depend_on_key_order_and_follows_every_value() -> None:
    one = model.fingerprint_of({"a": 1, "b": 2}, {"env": {"X": "1", "Y": "2"}})
    two = model.fingerprint_of({"b": 2, "a": 1}, {"env": {"Y": "2", "X": "1"}})
    other = model.fingerprint_of({"a": 1, "b": 2}, {"env": {"X": "1", "Y": "3"}})
    assert one == two
    assert one != other


def test_the_hash_of_a_config() -> None:
    # sha256 of {"rule":{"name":"strict"}}
    assert model.config_sha256({"rule": {"name": "strict"}}) == (
        "0fddffb15a6ae8cf83987129f4846bf5e6e2f742447314591eb7442851ddbfdb"
    )


def test_hashes_of_several_captures_are_folded_in_order() -> None:
    assert model.combine_hashes([]) is None
    assert model.combine_hashes([None, None]) is None
    assert model.combine_hashes(["aa"]) == "aa"
    # sha256 of "aa\nbb" and of "aa\n"
    assert model.combine_hashes(["aa", "bb"]) == (
        "80c0d5c7137871baa75af2038f350bf60a4d45a131a653d0eb93f3cda3d28609"
    )
    assert model.combine_hashes(["aa", None]) == (
        "d9cd8155764c3543f10fad8a480d743137466f8d55213c8eaefcd12f06d43a80"
    )
    assert model.combine_hashes(["bb", "aa"]) != model.combine_hashes(["aa", "bb"])


# ---------------------------------------------------------------------------
# Credentials, durations and names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["HF_TOKEN", "api_key", "MY_SECRET_VALUE", "DbPassword", "AWS_CREDENTIAL_FILE"]
)
def test_a_name_that_looks_like_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is True


@pytest.mark.parametrize("name", ["OMP_NUM_THREADS", "PATH", "HOME", "CUDA_VISIBLE_DEVICES"])
def test_a_name_that_does_not_look_like_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "token",
        "api_token",
        "access_token",
        "HF_TOKEN",
        "auth-token",
        "AUTHTOKEN",
        "HfToken",
        "API_TOKENS",
        "KEY",
        "API_KEY",
        "ACCESS_KEY",
        "PRIVATE_KEY",
        "SECRET_KEY",
        "MY_KEY",
        "X_API_KEY",
        "MADEUP_SECRET_ACCESS_KEY",
        "KEY2",
        "apiKey",
        "APIKey",
        "APIKEY",
        "API_KEYS",
        "MYPASSWORD",
        "APP_CREDENTIALS",
        "client.secret",
    ],
)
def test_a_name_with_a_word_of_a_secret_looks_like_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "sort-key",
        "SORT_KEY",
        "sortKey",
        "partition_key",
        "max-tokens",
        "num_tokens",
        "output-tokens",
        "maxTokens",
        "MAX_NEW_TOKENS",
        "tokens",
        "tokenizer",
        "TOKENIZERS_PARALLELISM",
        "keyword",
    ],
)
def test_a_count_of_tokens_or_a_key_that_orders_data_does_not_look_like_a_credential(
    name: str,
) -> None:
    assert model.looks_like_credential(name) is False


def test_credential_values_are_redacted_and_other_values_are_kept() -> None:
    assert model.redact_env({"HF_TOKEN": "made-up-value", "OMP_NUM_THREADS": "4"}) == {
        "HF_TOKEN": "<redacted>",
        "OMP_NUM_THREADS": "4",
    }


def test_a_count_of_tokens_is_kept_and_a_key_is_redacted() -> None:
    assert model.redact_env({"MAX_TOKENS": "512", "MY_API_KEY": "made-up-value"}) == {
        "MAX_TOKENS": "512",
        "MY_API_KEY": "<redacted>",
    }


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("90s", 90.0),
        ("10m", 600.0),
        ("1h30m", 5400.0),
        ("250ms", 0.25),
        ("1.5h", 5400.0),
        ("15", 15.0),
        (" 2m ", 120.0),
        (15, 15.0),
        (0.5, 0.5),
        ("0", 0.0),
    ],
)
def test_a_duration_in_seconds(text: str | float, seconds: float) -> None:
    assert model.parse_duration(text) == pytest.approx(seconds, abs=1e-12)


@pytest.mark.parametrize(
    "text",
    ["", "ten", "10 m", "10x", "m", "-5", "1h 30m", "1e400", True, "\u0663", "\u0663s", "1\u06f0m"],
)
def test_what_is_not_a_duration(text: object) -> None:
    with pytest.raises(ValueError, match="not a duration"):
        model.parse_duration(text)  # type: ignore[arg-type]


def test_the_clock_reasons_that_are_not_counted() -> None:
    # GPU idle, the applications clocks setting and the display clock setting.
    assert model.CLOCK_REASONS_NOT_COUNTED == 0x103


@pytest.mark.parametrize(
    ("before", "mask", "events"),
    [
        (0x0, 0x4, 1),
        (0x4, 0x4, 0),
        (0x4, 0xC, 1),
        (0xC, 0x4, 0),
        (0x0, 0x103, 0),
        (0x0, 0x1 | 0x8 | 0x400, 2),
        (0x0, 0x800, 1),
        (0x8, 0x0, 0),
        (0x103, 0x107, 1),
    ],
)
def test_clock_events_count_the_reasons_that_turn_on(before: int, mask: int, events: int) -> None:
    assert model.clock_events(before, mask) == events


def test_clock_events_of_a_run_of_readings() -> None:
    # One reason held for three readings, dropped, then back: two events.
    masks = [0x4, 0x4, 0x4, 0x0, 0x4]
    before, total = 0, 0
    for mask in masks:
        total += model.clock_events(before, mask)
        before = mask
    assert total == 2


@pytest.mark.parametrize(
    ("outcome", "kind", "word"),
    [
        ("better", "time", "FASTER"),
        ("worse", "time", "SLOWER"),
        ("better", "rate", "BETTER"),
        ("worse", "efficiency", "WORSE"),
        ("tie", "time", "TIE"),
        ("unresolved", "count", "UNRESOLVED"),
        ("no_verdict", "other", "NO VERDICT"),
    ],
)
def test_the_display_word_of_an_outcome(outcome: str, kind: str, word: str) -> None:
    assert model.verdict_word(outcome, kind) == word


def test_figure_keys() -> None:
    assert model.figure_key("matmul", "new", "old", "ratio") == "matmul.new_vs_old.ratio"
    assert model.figure_key("c32/ttft_ms_median", "new", "old", "statistic") == (
        "c32/ttft_ms_median.new_vs_old.statistic"
    )
    assert model.median_key("matmul", "new") == "matmul.new.median"
    with pytest.raises(ValueError, match="not a figure name: made_up"):
        model.figure_key("matmul", "new", "old", "made_up")


def test_the_figure_names() -> None:
    assert model.FIGURE_NAMES == (
        "ratio",
        "statistic",
        "speedup",
        "percent",
        "p",
        "p_corrected",
        "bar",
        "floor_subject",
        "floor_baseline",
        "n",
        "verdict",
    )


def test_load_level_labels_and_case_ids() -> None:
    assert model.level_label(32) == "c32"
    assert model.level_label(32, "concurrency") == "c32"
    assert model.level_label(32, "rate") == "r32"
    assert model.case_id("c32", "ttft_ms_median") == "c32/ttft_ms_median"
    assert model.case_id("r8", "tokens_per_joule[gpu]") == "r8/tokens_per_joule[gpu]"
    assert model.case_id("", "energy_j[gpu]") == "energy_j[gpu]"
    with pytest.raises(ValueError, match="a load level counts one of concurrency, rate"):
        model.level_label(32, "made_up")


@pytest.mark.parametrize("name", ["", "a~b", "new~same", "a=b", "a b", "a\tb", ".", ".."])
def test_a_side_name_that_is_refused(name: str) -> None:
    with pytest.raises(Refusal) as caught:
        model.validate_side_name(name)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


@pytest.mark.parametrize("name", ["\udcff", "new\udcfe", "\ud800x"])
def test_a_side_name_that_is_not_utf8_text_is_refused(name: str) -> None:
    with pytest.raises(Refusal) as caught:
        model.validate_side_name(name)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert caught.value.message.endswith("is refused: it is not UTF-8 text")
    with pytest.raises(Refusal) as built:
        model.Side.parse(f"{name}=cmd:true")
    assert built.value.code == "E_USAGE"


@pytest.mark.parametrize(
    "name", ["new", "v2.0", "pip-install", "side_1", "...", ".new", "v.", "neu-ü", "中"]
)
def test_a_side_name_that_is_accepted(name: str) -> None:
    assert model.validate_side_name(name) == name


@pytest.mark.parametrize(
    ("name", "taken"),
    [
        ("new", True),
        ("...", True),
        (".new", True),
        (".", False),
        ("..", False),
        ("a~b", False),
        ("a b", False),
    ],
)
def test_the_side_name_pattern_takes_what_the_check_takes(name: str, taken: bool) -> None:
    assert (re.search(model.SIDE_NAME_PATTERN, name) is not None) is taken


def test_the_schemas_state_the_side_name_pattern() -> None:
    folder = Path(model.__file__).parent / "results" / "schema"
    config = json.loads((folder / "config.v1.schema.json").read_text(encoding="utf-8"))
    capture = json.loads((folder / "capture.v1.schema.json").read_text(encoding="utf-8"))
    assert model.SIDE_NAME_PATTERN in _patterns(config)
    assert model.SIDE_NAME_PATTERN in _patterns(capture)


def _patterns(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["pattern"]] if isinstance(node.get("pattern"), str) else []
        return own + [p for value in node.values() for p in _patterns(value)]
    if isinstance(node, list):
        return [p for value in node for p in _patterns(value)]
    return []


def test_the_reserved_twin_suffix() -> None:
    assert model.TWIN_SUFFIX == "~same"


# ---------------------------------------------------------------------------
# The command line a capture keeps and the command a results document shows
# ---------------------------------------------------------------------------

ARGV = (
    "/made/up/bin/pairbench",
    "run",
    "--side",
    "new=image:registry.example/org/app:2.0",
    "--side=old=venv:/made/up/home/venv",
    "--set",
    "launch.env.API_TOKEN=made-up-secret",
    "--set=launch.env.OMP_NUM_THREADS=4",
    "--set",
    "sides.new.launch.env.MY_KEY=made-up-secret",
    "--set",
    "launch.workdir=/made/up/home/work",
    "--lock",
    "/made/up/locks/a b.lock",
    "--out=/made/up/home/runs/r1",
    "--config",
    "~/c.toml",
    "--rounds",
    "8",
    "--",
    "python",
    "/made/up/home/bench.py",
    "--data=/made/up/data/x",
    "API_TOKEN=made-up-secret",
    "level=3",
)


def test_a_capture_keeps_the_command_line_with_credential_values_redacted() -> None:
    assert model.redact_argv(ARGV) == (
        "/made/up/bin/pairbench",
        "run",
        "--side",
        "new=image:registry.example/org/app:2.0",
        "--side=old=venv:/made/up/home/venv",
        "--set",
        "launch.env.API_TOKEN=<redacted>",
        "--set=launch.env.OMP_NUM_THREADS=4",
        "--set",
        "sides.new.launch.env.MY_KEY=<redacted>",
        "--set",
        "launch.workdir=/made/up/home/work",
        "--lock",
        "/made/up/locks/a b.lock",
        "--out=/made/up/home/runs/r1",
        "--config",
        "~/c.toml",
        "--rounds",
        "8",
        "--",
        "python",
        "/made/up/home/bench.py",
        "--data=/made/up/data/x",
        "API_TOKEN=made-up-secret",
        "level=3",
    )


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("launch.env.HF_TOKEN=made-up-secret", "launch.env.HF_TOKEN=<redacted>"),
        ("sides.new.env.DB_PASSWORD=made-up-secret", "sides.new.env.DB_PASSWORD=<redacted>"),
        (
            "sides.new.serve.env.API_KEY=made-up-secret",
            "sides.new.serve.env.API_KEY=<redacted>",
        ),
        ('launch.env={HF_TOKEN="x"}', "launch.env=<redacted>"),
        ('launch.env={OMP_NUM_THREADS="4"}', 'launch.env={OMP_NUM_THREADS="4"}'),
        ("launch.env.OMP_NUM_THREADS=4", "launch.env.OMP_NUM_THREADS=4"),
        ("launch.cpus=4-7", "launch.cpus=4-7"),
        ("launch.env_pass=HF_TOKEN", "launch.env_pass=HF_TOKEN"),
        ("made_up.env.HF_TOKEN=x", "made_up.env.HF_TOKEN=x"),
        ("no-equals-sign", "no-equals-sign"),
    ],
)
def test_the_value_of_a_set_flag_that_sets_a_credential_is_redacted(given: str, kept: str) -> None:
    assert model.redact_argv(["pairbench", "run", "--set", given]) == (
        "pairbench",
        "run",
        "--set",
        kept,
    )
    assert model.redact_argv(["pairbench", "run", f"--set={given}"]) == (
        "pairbench",
        "run",
        f"--set={kept}",
    )


def test_the_workload_is_kept_as_typed_in_a_capture() -> None:
    argv = ("pairbench", "run", "--", "tool", "--set", "launch.env.API_TOKEN=made-up")
    assert model.redact_argv(argv) == argv


def test_the_command_a_results_document_shows() -> None:
    assert model.public_command(ARGV) == (
        "pairbench run --side 'new=image:<hidden>' '--side=old=venv:<hidden>' "
        "--set 'launch.env.API_TOKEN=<hidden>' '--set=launch.env.OMP_NUM_THREADS=<hidden>' "
        "--set 'sides.new.launch.env.MY_KEY=<hidden>' --set 'launch.workdir=<hidden>' "
        "--lock 'a b.lock' --out=r1 --config c.toml --rounds 8 "
        "-- python bench.py --data=x 'API_TOKEN=<hidden>' level=3"
    )


def test_the_command_shown_holds_no_path_no_reference_and_no_value_of_the_environment() -> None:
    for include in (False, True):
        shown = model.public_command(ARGV, include_image_refs=include)
        assert shown is not None
        for private in ("/made/up", "made-up-secret", "~", "venv:/"):
            assert private not in shown, private
    assert "registry.example" not in str(model.public_command(ARGV))


@pytest.mark.parametrize(
    ("arg", "shown"),
    [
        ("--env=MY_TOKEN=made-up-secret", "--env=MY_TOKEN=<hidden>"),
        ("-eMY_TOKEN=made-up-secret", "-eMY_TOKEN=<hidden>"),
        ("--api-key=made-up-secret", "--api-key=<hidden>"),
        ("--header=X_API_KEY=made-up-secret", "--header=X_API_KEY=<hidden>"),
        ("-I/made/up/project/include", "-Iinclude"),
        ("-o/made/up/out.json", "-oout.json"),
        ("-L~/made/up/lib", "-Llib"),
        ("--prefix=/made/up/prefix", "--prefix=prefix"),
        ("--env=PATH=/made/up/bin", "--env=PATH=bin"),
        ("-O2", "-O2"),
        ("--level=3", "--level=3"),
        ("-e", "-e"),
    ],
)
def test_a_value_glued_to_an_option_is_hidden_or_cut_as_a_separate_one_is(
    arg: str, shown: str
) -> None:
    command = model.public_command(["pairbench", "run", "--", "tool", arg])
    assert command == shlex.join(["pairbench", "run", "--", "tool", shown])


@pytest.mark.parametrize(
    ("args", "shown"),
    [
        (("--sort-key=name",), ("--sort-key=name",)),
        (("--sort-key", "name"), ("--sort-key", "name")),
        (("--max-tokens=512",), ("--max-tokens=512",)),
        (("--max-tokens", "512"), ("--max-tokens", "512")),
        (("--data=prompt_tokens=8,output_tokens=8",), ("--data=prompt_tokens=8,output_tokens=8",)),
        (("--api-key=abc",), ("--api-key=<hidden>",)),
        (("--access_key", "abc"), ("--access_key", "<hidden>")),
        (("--token=abc",), ("--token=<hidden>",)),
        (("HF_TOKEN=abc",), ("HF_TOKEN=<hidden>",)),
        (("--password", "abc"), ("--password", "<hidden>")),
    ],
)
def test_the_value_of_an_option_is_hidden_only_when_its_name_says_secret(
    args: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    command = model.public_command(["pairbench", "run", "--", "tool", *args])
    assert command == shlex.join(["pairbench", "run", "--", "tool", *shown])
    words = model.public_words(shlex.join(["tool", *args]))
    assert words == " ".join(["tool", *shown])


def test_a_set_flag_that_sets_a_count_of_tokens_keeps_its_value_in_a_capture() -> None:
    argv = ("pairbench", "run", "--set", "launch.env.MAX_TOKENS=512")
    assert model.redact_argv(argv) == argv


def test_an_image_reference_is_shown_only_on_request_and_only_for_an_image() -> None:
    shown = model.public_command(ARGV, include_image_refs=True)
    assert shown is not None
    assert "--side new=image:registry.example/org/app:2.0 " in shown
    assert "'--side=old=venv:<hidden>'" in shown
    serving = model.public_command(
        ["pairbench", "run", "--side", "srv=serve:myorg/server:2.0"], include_image_refs=True
    )
    assert serving == "pairbench run --side srv=serve:myorg/server:2.0"
    command = ["pairbench", "run", "--side", "c=cmd:/made/up/bin/tool --flag"]
    assert model.public_command(command, include_image_refs=True) == (
        "pairbench run --side 'c=cmd:<hidden>'"
    )


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        ((), None),
        (("pairbench", "plan"), "pairbench plan"),
        (("pairbench", "run", "--side", "nonsense"), "pairbench run --side '<hidden>'"),
        (("pairbench", "run", "--set", "nonsense"), "pairbench run --set '<hidden>'"),
        (("pairbench", "run", "--side"), "pairbench run --side"),
        (("pairbench", "compare", "/a/b/capture.jsonl"), "pairbench compare capture.jsonl"),
        (("pairbench", "compare", "runs/capture.jsonl"), "pairbench compare runs/capture.jsonl"),
        (("pairbench", "run", "--lock", "/"), "pairbench run --lock /"),
        (("pairbench", "run", "--lock", "/a/b/"), "pairbench run --lock b"),
        (
            ("pairbench", "run", "--", "tool", "--side", "x=image:reg/app:1"),
            "pairbench run -- tool --side x=image:reg/app:1",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "python /srv/x/bench.py --fast"),
            "pairbench run -- sh -c 'python bench.py --fast'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--path=a:/srv/x/lib"),
            "pairbench run -- tool --path=a:lib",
        ),
        (
            ("pairbench", "run", "--", "tool", "--path=a:~/lib/x"),
            "pairbench run -- tool --path=a:x",
        ),
        (
            ("pairbench", "run", "--", "tool", "--token", "made-up-1", "--fast"),
            "pairbench run -- tool --token '<hidden>' --fast",
        ),
        (
            ("pairbench", "run", "--", "tool", "--api-key", "made-up-2", "-v"),
            "pairbench run -- tool --api-key '<hidden>' -v",
        ),
        (
            ("pairbench", "run", "--", "tool", "-PASSWORD", "made-up-3"),
            "pairbench run -- tool -PASSWORD '<hidden>'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--token", "--fast"),
            "pairbench run -- tool --token --fast",
        ),
        (
            ("pairbench", "run", "--", "tool", "--model", "file:///made/up/home/m.gguf"),
            "pairbench run -- tool --model file://m.gguf",
        ),
        (
            ("pairbench", "run", "--", "tool", "--label=run of ~madeup-user/proj"),
            "pairbench run -- tool '--label=run of proj'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--msg=copy /made/up/some one/x now"),
            "pairbench run -- tool '--msg=copy x now'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "tool --token made-up-4 /made/up/home/x"),
            "pairbench run -- sh -c 'tool --token <hidden> x'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "tool --token 'made up 5' --fast"),
            "pairbench run -- sh -c 'tool --token <hidden> --fast'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", 'tool --api-key "made up 6" -v'),
            "pairbench run -- sh -c 'tool --api-key <hidden> -v'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "tool --token 'made up 7"),
            "pairbench run -- sh -c 'tool --token <hidden>'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "tool --token --fast"),
            "pairbench run -- sh -c 'tool --token --fast'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "API_TOKEN=made-up-8 ./bench --n 3"),
            "pairbench run -- sh -c 'API_TOKEN=<hidden> ./bench --n 3'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "env 'API_KEY=made up 15' ./bench"),
            shlex.join(["pairbench", "run", "--", "sh", "-c", "env 'API_KEY=<hidden>' ./bench"]),
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "sh -c 'tool --password made-up-9 -q'"),
            shlex.join(
                ["pairbench", "run", "--", "sh", "-c", "sh -c 'tool --password <hidden> -q'"]
            ),
        ),
        (
            ("pairbench", "run", "--", "tool", "-H", "Authorization: Bearer made-up-10"),
            "pairbench run -- tool -H 'Authorization: <hidden>'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--header", "X-Api-Key: made-up-11"),
            "pairbench run -- tool --header 'X-Api-Key: <hidden>'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--header=Proxy-Authorization:made-up-12"),
            "pairbench run -- tool '--header=Proxy-Authorization: <hidden>'",
        ),
        (
            ("pairbench", "run", "--", "tool", "-H", "Content-Type: text/plain"),
            "pairbench run -- tool -H 'Content-Type: text/plain'",
        ),
        (
            (
                "pairbench",
                "run",
                "--",
                "sh",
                "-c",
                "curl -H 'Authorization: Bearer made-up-13' https://example.org/x",
            ),
            shlex.join(
                [
                    "pairbench",
                    "run",
                    "--",
                    "sh",
                    "-c",
                    "curl -H 'Authorization: <hidden>' https://<hidden>/x",
                ]
            ),
        ),
        (
            ("pairbench", "run", "--", "tool", "--db", "postgres://madeup:made-up-14@db.example/x"),
            "pairbench run -- tool --db 'postgres://<hidden>@<hidden>/x'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--db", "postgres://madeup:made@up-15@db.example/x"),
            "pairbench run -- tool --db 'postgres://<hidden>@<hidden>/x'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--db", "postgres://madeup:made'up-18@db.example/x"),
            "pairbench run -- tool --db 'postgres://<hidden>@<hidden>/x'",
        ),
        (
            ("pairbench", "run", "--", "tool", "--db", 'postgres://madeup:made"up-19@db.example/x'),
            "pairbench run -- tool --db 'postgres://<hidden>@<hidden>/x'",
        ),
        (
            (
                "pairbench",
                "run",
                "--",
                "sh",
                "-c",
                "tool --db 'postgres://madeup:made-up-20@db.ex'",
            ),
            shlex.join(
                ["pairbench", "run", "--", "sh", "-c", "tool --db 'postgres://<hidden>@<hidden>'"]
            ),
        ),
        (
            ("pairbench", "run", "--", "curl", "-HAuthorization: Bearer made-up-16"),
            "pairbench run -- curl '-HAuthorization: <hidden>'",
        ),
        (
            (
                "pairbench",
                "run",
                "--",
                "sh",
                "-c",
                "curl -HX-Api-Key:made-up-17 https://example.org",
            ),
            "pairbench run -- sh -c 'curl -HX-Api-Key: <hidden>'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "./bench -I/made/up/dir/include -o/made/up/out"),
            "pairbench run -- sh -c './bench -Iinclude -oout'",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "make -C/made/up/dir"),
            "pairbench run -- sh -c 'make -Cdir'",
        ),
        (
            ("pairbench", "run", "--", "tool", "-I~madeup-user/include"),
            "pairbench run -- tool -Iinclude",
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "cc '-I/made/up/a b/include' x.c"),
            shlex.join(["pairbench", "run", "--", "sh", "-c", "cc '-Iinclude' x.c"]),
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "echo it's --token made-up-21 -HCookie:made-up"),
            shlex.join(
                [
                    "pairbench",
                    "run",
                    "--",
                    "sh",
                    "-c",
                    "echo it's --token <hidden> -HCookie: <hidden>",
                ]
            ),
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", 'echo "a --token made-up-22 /made/up/dir/x'),
            shlex.join(["pairbench", "run", "--", "sh", "-c", 'echo "a --token <hidden> x']),
        ),
        (
            ("pairbench", "run", "--", "sh", "-c", "tool API_KEY='made up 23"),
            "pairbench run -- sh -c 'tool API_KEY=<hidden>'",
        ),
    ],
)
def test_a_command_line_and_what_is_shown_of_it(argv: tuple[str, ...], shown: str | None) -> None:
    assert model.public_command(argv) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("sh -c 'tool --token made-up-1'", "sh -c tool --token <hidden>"),
        ("tool --token 'made up 2", "tool --token <hidden>"),
        ("echo it's --token made-up-24", "echo it's --token <hidden>"),
        ("tool --token 'made up 3' -v", "tool --token <hidden> -v"),
        ("curl -H 'Authorization: Bearer made-up-4' x", "curl -H Authorization: <hidden> x"),
        ("/made/up/v1/bench --n 1", "bench --n 1"),
        ("sh -c 'make -C/made/up/dir'", "sh -c make -Cdir"),
    ],
)
def test_a_command_written_as_one_text_is_shown_as_a_command_line_is(text: str, shown: str) -> None:
    assert model.public_words(text) == shown


@pytest.mark.parametrize(
    ("args", "shown"),
    [
        (("curl", "-u", "madeup:made-up-1", "x"), "curl -u 'madeup:<hidden>' x"),
        (("curl", "--user", "madeup:made-up-2", "x"), "curl --user 'madeup:<hidden>' x"),
        (("curl", "--user=madeup:made-up-3", "x"), "curl '--user=madeup:<hidden>' x"),
        (("curl", "-umadeup:made-up-4", "x"), "curl '-umadeup:<hidden>' x"),
        (("curl", "-U", "madeup:made-up-5", "x"), "curl -U 'madeup:<hidden>' x"),
        (("curl", "--proxy-user", "madeup:made-up-6"), "curl --proxy-user 'madeup:<hidden>'"),
        (("curl", "-u", ":made-up-7", "x"), "curl -u ':<hidden>' x"),
        (("curl", "--auth", "madeup:made-up-8", "x"), "curl --auth '<hidden>' x"),
        (("sh", "-c", "curl -u madeup:made-up-9 x"), "sh -c 'curl -u madeup:<hidden> x'"),
        (("sh", "-c", "curl -umadeup:made-up-10 x"), "sh -c 'curl -umadeup:<hidden> x'"),
        (("curl", "-u", "madeup", "x"), "curl -u madeup x"),
        (("tool", "-u", "-v"), "tool -u -v"),
        (("curl", "--cert", "client.pem:made-up-20", "x"), "curl --cert 'client.pem:<hidden>' x"),
        (("curl", "--cert=client.pem:made-up-21"), "curl '--cert=client.pem:<hidden>'"),
        (("curl", "--proxy-cert", "p.pem:made-up-22"), "curl --proxy-cert 'p.pem:<hidden>'"),
        (("curl", "--cert", "client.pem", "x"), "curl --cert client.pem x"),
    ],
)
def test_the_password_given_to_a_user_option_is_hidden(args: tuple[str, ...], shown: str) -> None:
    assert model.public_command(("pairbench", "run", "--", *args)) == "pairbench run -- " + shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("curl -u madeup:made-up-11 x", "curl -u madeup:<hidden> x"),
        ("curl --user=madeup:made-up-12 x", "curl --user=madeup:<hidden> x"),
        ("curl -U madeup:made-up-13", "curl -U madeup:<hidden>"),
    ],
)
def test_the_password_given_to_a_user_option_is_hidden_in_one_text(text: str, shown: str) -> None:
    assert model.public_words(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        # A quoted word of several words is read word by word, also when a
        # credential-like name is given a value after other words in it.
        (
            'echo "--token made-up-1 password=made-up-2"',
            'echo "--token <hidden> password=<hidden>"',
        ),
        (
            "sh -c 'tool --token made-up-3 API_KEY=made-up-4'",
            "sh -c 'tool --token <hidden> API_KEY=<hidden>'",
        ),
        ("tool 'API_KEY=made up 5' -v", "tool 'API_KEY=<hidden>' -v"),
        # Names that hold an authentication word, and a short word for a password.
        ("curl -H 'Authentication: made-up-6' x", "curl -H 'Authentication: <hidden>' x"),
        ("tool --auth-header 'Bearer made-up-7' -v", "tool --auth-header <hidden> -v"),
        ("tool --authenticate=made-up-8 -v", "tool --authenticate=<hidden> -v"),
        ("tool --pw made-up-9 -v", "tool --pw <hidden> -v"),
    ],
)
def test_a_credential_among_the_words_of_one_argument_is_hidden(text: str, shown: str) -> None:
    assert model.public_command(("pairbench", "run", "--", "sh", "-c", text)) == shlex.join(
        ["pairbench", "run", "--", "sh", "-c", shown]
    )


@pytest.mark.parametrize(
    ("args", "shown"),
    [
        (("env", "DB_PASSWORD=made up 1", "true"), ("env", "DB_PASSWORD=<hidden>", "true")),
        (("tool", "--api-key=made up 2", "-v"), ("tool", "--api-key=<hidden>", "-v")),
        (
            ("docker", "run", "-e", "X_TOKEN=made up 3", "img"),
            ("docker", "run", "-e", "X_TOKEN=<hidden>", "img"),
        ),
        (
            ("docker", "run", "--env=MY_TOKEN=made up 4", "img"),
            ("docker", "run", "--env=MY_TOKEN=<hidden>", "img"),
        ),
        (("bench", "-eMY_TOKEN=made up 5"), ("bench", "-eMY_TOKEN=<hidden>")),
        (("tool", "--password", "made up 6"), ("tool", "--password", "<hidden>")),
        (("sh", "-c", "HF_TOKEN=made\\ up\\ 7 true"), ("sh", "-c", "HF_TOKEN=<hidden> true")),
        # The text after -c is a command: only the value of the name is hidden.
        (("sh", "-c", "API_KEY=made-up-8 ./bench -v"), ("sh", "-c", "API_KEY=<hidden> ./bench -v")),
        (("bash", "-lc", "API_KEY=made-up-9 ./bench"), ("bash", "-lc", "API_KEY=<hidden> ./bench")),
        (("curl", "--user=someuser:made up 10", "x"), ("curl", "--user=someuser:<hidden>", "x")),
        (("curl", "-usomeuser:made up 11", "x"), ("curl", "-usomeuser:<hidden>", "x")),
        # A client's password option with its value glued to it.
        (("mysql", "-pmade up 12", "shop"), ("mysql", "-p<hidden>", "shop")),
        (("redis-cli", "-amade up 13", "ping"), ("redis-cli", "-a<hidden>", "ping")),
        (("sshpass", "-pmade up 14", "ssh", "h"), ("sshpass", "-p<hidden>", "ssh", "h")),
        (
            ("ab", "-Abench:made up 15", "http://localhost/"),
            ("ab", "-Abench:<hidden>", "http://localhost/"),
        ),
        (
            ("env", "mysqladmin", "-pmade up 16", "status"),
            ("env", "mysqladmin", "-p<hidden>", "status"),
        ),
        (("tool", "--label=a b", "-v"), ("tool", "--label=a b", "-v")),
        (("mysql", "-eSELECT 1", "shop"), ("mysql", "-eSELECT 1", "shop")),
    ],
)
def test_a_credential_value_that_holds_spaces_is_hidden_to_the_end_of_its_argument(
    args: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    command = model.public_command(("pairbench", "run", "--", *args))
    assert command == shlex.join(("pairbench", "run", "--", *shown))
    assert "made" not in command
    words = model.public_words(shlex.join(args))
    assert words == " ".join(shown)
    assert "made" not in words


@pytest.mark.parametrize(
    ("code", "shown"),
    [
        (
            "import os; os.environ['API_KEY']='made-up-1'",
            "import os; os.environ['API_KEY']='<hidden>'",
        ),
        (
            'import os; os.environ["API_KEY"] = "made-up-2"',
            'import os; os.environ["API_KEY"] = "<hidden>"',
        ),
        ("API_KEY = 'made-up-3'", "API_KEY = '<hidden>'"),
        ("API_KEY := made-up-4", "API_KEY := <hidden>"),
        (
            'import json; print(json.dumps({"api_key": "made-up-5"}))',
            'import json; print(json.dumps({"api_key": "<hidden>"}))',
        ),
        ("x = {'password': 'made up 6'}", "x = {'password': '<hidden>'}"),
        (
            "import os; os.environ.setdefault('HF_TOKEN', 'made-up-7')",
            "import os; os.environ.setdefault('HF_TOKEN', '<hidden>')",
        ),
        ('os.putenv("HF_TOKEN","made-up-8")', 'os.putenv("HF_TOKEN","<hidden>")'),
        ("settings.api_key = 'made-up-9'", "settings.api_key = '<hidden>'"),
        ("if API_KEY == 'made-up-10': pass", "if API_KEY == '<hidden>': pass"),
        ("api_key: str = 'made-up-11'", "api_key: <hidden>"),
        (
            "def f(api_key: str = 'made-up-14'): pass",
            "def f(api_key: <hidden> = '<hidden>'): pass",
        ),
        ("x: API_KEY = 'made-up-12'", "x: API_KEY = '<hidden>'"),
        # A quoted value ends at its closing quote, and the statement after it stays.
        ("db_password='made-up-13';x=1", "db_password='<hidden>';x=1"),
        ("requests.get(u, auth=('madeup', 'made-up-15'))", "requests.get(u, auth=<hidden>"),
        ("api_keys = ['made-up-16', 'made-up-17']", "api_keys = <hidden>"),
        ("$ENV{API_KEY}='made-up-18'", "$ENV{API_KEY}='<hidden>'"),
        ("os.environ['API_KEY']=\\\n'made-up-19'", "os.environ['API_KEY']=\\\n'<hidden>'"),
        # A value of several pieces is hidden whole: a call with a default, a
        # sum, an alternative and a call on a part of it.
        ("API_KEY = os.getenv('X', 'made-up-20')", "API_KEY = <hidden>"),
        ("API_KEY = os.environ.get('X', 'made-up-21').strip()", "API_KEY = <hidden>"),
        ("api_key = 'made' + '-up-22'", "api_key = '<hidden>'"),
        ("api_key = x or 'made-up-23'", "api_key = <hidden>"),
        ("api_key = 'a''made-up-24'", "api_key = '<hidden>'"),
        ("api_key = x if y else 'made-up-25'", "api_key = <hidden>"),
        ("d = {'token': os.getenv('T', 'made-up-26'), 'n': 2}", "d = {'token': <hidden>, 'n': 2}"),
        ("x = {'sort_key': 'a', 'max_tokens': 8}", "x = {'sort_key': 'a', 'max_tokens': 8}"),
        # An option and its value written as two quoted texts of a list.
        (
            'subprocess.run(["tool", "--password", "made-up-27", "--token", "made-up-28"])',
            'subprocess.run(["tool", "--password", "<hidden>", "--token", "<hidden>"])',
        ),
        ("args = ['-api-key', 'made-up-29']", "args = ['-api-key', '<hidden>']"),
        (
            'args = ["--max-tokens", "64", "--monkey-patch", "x"]',
            'args = ["--max-tokens", "64", "--monkey-patch", "x"]',
        ),
        # A value written on the next line of a table, a call or a list.
        ('d = {"api_key":\n    "made-up-30"}', 'd = {"api_key":\n    "<hidden>"}'),
        (
            "os.environ.setdefault('HF_TOKEN',\n    'made-up-31')",
            "os.environ.setdefault('HF_TOKEN',\n    '<hidden>')",
        ),
        ('args = ["--token",\n    "made-up-32"]', 'args = ["--token",\n    "<hidden>"]'),
        ('args = ["--max-tokens",\n    "64"]', 'args = ["--max-tokens",\n    "64"]'),
        (
            "os.environ.setdefault('OMP_NUM_THREADS',\n    '4')",
            "os.environ.setdefault('OMP_NUM_THREADS',\n    '4')",
        ),
        (
            "os.environ.setdefault('OMP_NUM_THREADS', '4')",
            "os.environ.setdefault('OMP_NUM_THREADS', '4')",
        ),
        ("print('a', 'b'); n = 3", "print('a', 'b'); n = 3"),
    ],
)
def test_a_credential_given_a_value_in_the_text_of_a_program_is_hidden(
    code: str, shown: str
) -> None:
    assert model.public_command(("pairbench", "run", "--", "python", "-c", code)) == shlex.join(
        ["pairbench", "run", "--", "python", "-c", shown]
    )
    nested = shlex.join(["python", "-c", code])
    assert model.public_words(nested) == f"python -c {shown}"
    # Inside ``sh -c`` the program is quoted for the shell; a value that is
    # hidden may take more of the text with it, but no value is shown.
    in_shell = model.public_command(("pairbench", "run", "--", "sh", "-c", nested))
    assert in_shell is not None
    if shown == code:
        assert in_shell == shlex.join(["pairbench", "run", "--", "sh", "-c", nested])
    else:
        assert "made" not in in_shell
        assert model.HIDDEN in in_shell


@pytest.mark.parametrize(
    ("arg", "shown"),
    [
        ("https://made-up.example:8443/v1/models", "https://<hidden>:8443/v1/models"),
        ("http://made-up.example/x?q=1", "http://<hidden>/x?q=1"),
        ("postgres://madeup:made-up-1@db.example:5432/x", "postgres://<hidden>@<hidden>:5432/x"),
        ("--url=https://10.1.2.3/v1", "--url=https://<hidden>/v1"),
        ("-xhttp://made-up.example:3128", "-xhttp://<hidden>:3128"),
        ("-Jssh://madeup@made-up.example", "-Jssh://<hidden>@<hidden>"),
        ("-xhttp://madeup:made-up-pw@made-up.example:3128", "-xhttp://<hidden>@<hidden>:3128"),
        ("-xhttp://madeup:made-up-pw@localhost:3128", "-xhttp://<hidden>@localhost:3128"),
        ("http://[fd00::1]:8000/v1", "http://<hidden>:8000/v1"),
        ("http://[fe80::1%25eth0]:8000/v1", "http://<hidden>:8000/v1"),
        ("http://[fd00::1]/v1/models", "http://<hidden>/v1/models"),
        ("http://[fd00::1]//v1/models", "http://<hidden>//v1/models"),
        ("http://made-up.example:/v1/models", "http://<hidden>:/v1/models"),
        # A character no host name holds ends the address: the absolute path after it is cut.
        ("http://made-up+/v1/models", "http://<hidden>"),
        ("http://made-up.example,/made/up/home/data.csv", "http://<hidden>"),
        ("-xhttp://made-up-token@made-up.example:3128", "-xhttp://<hidden>@<hidden>:3128"),
        ("http://localhost:8000/v1", "http://localhost:8000/v1"),
        ("http://LOCALHOST:8000/v1", "http://LOCALHOST:8000/v1"),
        ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8000/v1"),
        ("http://[::1]:8000/v1", "http://[::1]:8000/v1"),
        ("http://[::1]/v1/models", "http://[::1]/v1/models"),
        ("http://0.0.0.0:8000", "http://0.0.0.0:8000"),
        ("file:///made/up/home/m.gguf", "file://m.gguf"),
        ("-mfile:///made/up/home/m.gguf", "-mfile://m.gguf"),
        # A file address names a path on a machine: what stands before the path goes with it.
        ("file://localhost/made/up/home/m.gguf", "file://m.gguf"),
        ("file://made-up-host/made/up/home/m.gguf", "file://m.gguf"),
        ("file://made-up-host:/made/up/home/m.gguf", "file://m.gguf"),
        ("file://[fd00::1]/made/up/home/m.gguf", "file://m.gguf"),
        ("file://[::1]/made/up/home/m.gguf", "file://m.gguf"),
        ("file:////made-up-host/share/home/m.gguf", "file://m.gguf"),
        ("FILE:///made/up/home/m.gguf", "FILE://m.gguf"),
        ("-mfile://made-up-host/made/up/home/m.gguf", "-mfile://m.gguf"),
        ("plain-text-without-an-address", "plain-text-without-an-address"),
    ],
)
def test_the_host_of_an_address_is_hidden_unless_it_is_a_loopback_name(
    arg: str, shown: str
) -> None:
    assert model.public_command(("pairbench", "run", "--", "tool", arg)) == shlex.join(
        ["pairbench", "run", "--", "tool", shown]
    )
    nested = model.public_command(("pairbench", "run", "--", "sh", "-c", f"tool {arg} -q"))
    assert nested == shlex.join(["pairbench", "run", "--", "sh", "-c", f"tool {shown} -q"])
    # A case named after the text of a command shows its words as the command does.
    assert model.public_words(f"tool {arg} -q") == f"tool {shown} -q"
    assert model.public_words(f"sh -c 'tool {arg} -q'") == f"sh -c tool {shown} -q"


# Shell texts whose hidden value is followed by an operator, glued or spaced: the value ends at
# the operator, and the operator and the next command are shown.
SHELL_OPERATOR_TEXTS = (
    ("tool --api-key=made-up-1&& ls", "tool --api-key=<hidden>&& ls"),
    ("tool --api-key=made-up-2; ls", "tool --api-key=<hidden>; ls"),
    ("tool --api-key=made-up-3|ls", "tool --api-key=<hidden>|ls"),
    ("tool --api-key=made-up-4||ls", "tool --api-key=<hidden>||ls"),
    ("tool --api-key=made-up-5&ls", "tool --api-key=<hidden>&ls"),
    ("API_TOKEN=made-up-6&&ls -la", "API_TOKEN=<hidden>&&ls -la"),
    ("tool --token made-up-7;ls", "tool --token <hidden>;ls"),
    ("curl -u bench:made-up-8&&ls", "curl -u bench:<hidden>&&ls"),
    ("redis-cli -amade-up-9||ls", "redis-cli -a<hidden>||ls"),
    ("redis-cli -a made-up-10|ls", "redis-cli -a <hidden>|ls"),
    ("tool --token=made-up-31&& ls -l", "tool --token=<hidden>&& ls -l"),
    ("API_KEY=made-up-32&& ls -l", "API_KEY=<hidden>&& ls -l"),
    ("curl -H Authorization:made-up-11&&ls", "curl -H Authorization: <hidden>&&ls"),
    ("curl -H Authorization: Bearer made-up-12 && ls", "curl -H Authorization: <hidden> && ls"),
    ("curl http://made-up.example&&ls", "curl http://<hidden>&&ls"),
    ("curl http://made-up.example;/made/up/home/bin/tool", "curl http://<hidden>;tool"),
    ("curl http://localhost;/made/up/home/bin/tool", "curl http://localhost;tool"),
    # The next command is read afresh: an option there takes no value from the one before.
    ("redis-cli -a made-up-13; tool -a 2", "redis-cli -a <hidden>; tool -a 2"),
    # A client's own command ends at the operator, so a later ``set`` starts a setting.
    ("redis-cli && set password made-up-38", "redis-cli && set password <hidden>"),
    ("redis-cli -h db;set password made-up-39", "redis-cli -h db;set password <hidden>"),
    # A setting ends at the operator too.
    (
        "git config --global github.token made-up-40; ls -l",
        "git config --global github.token <hidden>; ls -l",
    ),
    # A redirection to a descriptor ends no command.
    ("redis-cli 2>&1 -a made-up-14", "redis-cli 2>&1 -a <hidden>"),
    # An escaped operator is part of the word.
    ("tool --api-key=made\\|up-15 -q", "tool --api-key=<hidden> -q"),
    # A text with no hidden value is shown as typed.
    ("make all&& ls; true|cat", "make all&& ls; true|cat"),
)


@pytest.mark.parametrize(("text", "shown"), SHELL_OPERATOR_TEXTS)
def test_a_hidden_value_ends_at_a_shell_operator(text: str, shown: str) -> None:
    for shell in (("sh", "-c"), ("bash", "-lc"), ("dash", "-e", "-c")):
        argv = ("pairbench", "run", "--", *shell, text)
        assert model.public_command(argv) == shlex.join([*argv[:-1], shown])
    # The command text of a hyperfine case is a shell text too.
    assert model.public_words(text) == shown


@pytest.mark.parametrize(
    ("text", "in_shell", "as_words"),
    [
        # An operator inside quotes is part of the value.
        ("tool '--api-key=made|up-16&&x'", "tool '--api-key=<hidden>'", "tool --api-key=<hidden>"),
        (
            'tool --api-key="made;up-17" -q',
            "tool --api-key=<hidden> -q",
            "tool --api-key=<hidden> -q",
        ),
        # A line break ends a command, as an operator does.
        (
            "tool --api-key=made-up-18\nls",
            "tool --api-key=<hidden>\nls",
            "tool --api-key=<hidden> ls",
        ),
        ("tool --token\nls -la", "tool --token\nls -la", "tool --token ls -la"),
        (
            "curl -H X-Api-Key: made-up-19\nls",
            "curl -H X-Api-Key: <hidden>\nls",
            "curl -H X-Api-Key: <hidden> ls",
        ),
        # A quoted header glued to an operator keeps the operator and the next command.
        (
            "curl -H 'Authorization: Bearer made-up-25'&& ls -l",
            "curl -H 'Authorization: <hidden>'&& ls -l",
            "curl -H Authorization: <hidden>&& ls -l",
        ),
        (
            "curl -H 'X-Api-Key: made-up-26'; ls -l",
            "curl -H 'X-Api-Key: <hidden>'; ls -l",
            "curl -H X-Api-Key: <hidden>; ls -l",
        ),
        (
            'curl -H "Authorization: Bearer made-up-27"|ls -l',
            'curl -H "Authorization: <hidden>"|ls -l',
            "curl -H Authorization: <hidden>|ls -l",
        ),
        (
            "curl --header='Authorization: Bearer made-up-29'&& ls -l",
            "curl --header='Authorization: <hidden>'&& ls -l",
            "curl --header=Authorization: <hidden>&& ls -l",
        ),
        # A header written with escaped spaces ends at the operator too.
        (
            "curl -H Authorization:\\ Bearer\\ made-up-28&& ls -l",
            "curl -H 'Authorization: <hidden>'&& ls -l",
            "curl -H Authorization: <hidden>&& ls -l",
        ),
        # With a space after the closing quote.
        (
            "curl -H 'Authorization: Bearer made-up-30' && ls -l",
            "curl -H 'Authorization: <hidden>' && ls -l",
            "curl -H Authorization: <hidden> && ls -l",
        ),
        # A shell text inside a shell text is read the same way.
        (
            "sh -c 'tool --api-key=made-up-20&& ls'",
            "sh -c 'tool --api-key=<hidden>&& ls'",
            "sh -c tool --api-key=<hidden>&& ls",
        ),
    ],
)
def test_an_operator_in_quotes_or_a_line_break_in_a_shell_text(
    text: str, in_shell: str, as_words: str
) -> None:
    argv = ("pairbench", "run", "--", "sh", "-c", text)
    assert model.public_command(argv) == shlex.join([*argv[:-1], in_shell])
    assert model.public_words(text) == as_words


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        # An argument of one word that is no shell text is one value, operators and all.
        (("tool", "--api-key=made|up-21&&x"), ("tool", "--api-key=<hidden>")),
        (("tool", "API_TOKEN=made-up-22;x"), ("tool", "API_TOKEN=<hidden>")),
        (("tool", "--token", "made-up-23;x"), ("tool", "--token", "<hidden>")),
        (("python", "-c", "API_KEY='made-up-24'|x"), ("python", "-c", "API_KEY=<hidden>")),
        (("tool", "http://made-up.example;/made/up/home/bin/tool"), ("tool", "http://<hidden>")),
        (("tool", "http://localhost;/made/up/home/bin/tool"), ("tool", "http://<hidden>")),
    ],
)
def test_a_value_of_one_word_outside_a_shell_text_runs_to_its_end(
    argv: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    lead = ("pairbench", "run", "--")
    assert model.public_command((*lead, *argv)) == shlex.join([*lead, *shown])


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        # In an argument of several words a value ends at its word, and the separator after it
        # is shown.
        (
            ("tool", "--cmd", "run --api-key=made-up-33; ls"),
            ("tool", "--cmd", "run --api-key=<hidden>; ls"),
        ),
        (("tool", "--cmd", "x; API_KEY=made-up-34 y"), ("tool", "--cmd", "x; API_KEY=<hidden> y")),
        # Unless its first word gives a credential a value: that value is the rest of it.
        (("tool", "DB_PASSWORD=made up-35; ls"), ("tool", "DB_PASSWORD=<hidden>")),
        (("tool", "--api-key=made up-36&& ls"), ("tool", "--api-key=<hidden>")),
        (("mysql", "-pmade up-37; ls"), ("mysql", "-p<hidden>")),
    ],
)
def test_an_argument_of_several_words_outside_a_shell_text(
    argv: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    lead = ("pairbench", "run", "--")
    assert model.public_command((*lead, *argv)) == shlex.join([*lead, *shown])


@pytest.mark.parametrize(
    ("argv", "shown"),
    [
        # A header of several cookies given to the program as one argument: no shell reads it.
        (
            ("curl", "-H", "Cookie: a=1; sessionid=made-up-41", "http://localhost/x"),
            ("curl", "-H", "Cookie: <hidden>", "http://localhost/x"),
        ),
        # An operator inside a word of an argument that no shell reads is part of the value.
        (
            ("tool", "--opts", "--x 1 --password made&up-42 --y 2"),
            ("tool", "--opts", "--x 1 --password <hidden> --y 2"),
        ),
        (
            ("tool", "--opts", "--x 1 --token=made|up-43 --y 2"),
            ("tool", "--opts", "--x 1 --token=<hidden> --y 2"),
        ),
        (("tool", "x DB_PASSWORD=made;up-44 y"), ("tool", "x DB_PASSWORD=<hidden> y")),
        # In a shell text an operator in a quoted word is part of it: the shell reads it so.
        (
            ("sh", "-c", "curl -H 'Cookie: a=1; sessionid=made-up-45' http://localhost/x && ls"),
            ("sh", "-c", "curl -H 'Cookie: <hidden>' http://localhost/x && ls"),
        ),
        (
            ("sh", "-c", "env -S 'tool HF_TOKEN=made&up-46 -q' && ls"),
            ("sh", "-c", "env -S 'tool HF_TOKEN=<hidden> -q' && ls"),
        ),
        (
            ("sh", "-c", 'curl -H "X-Api-Key: made-up-47 | made-up-48" http://localhost/x; ls'),
            ("sh", "-c", 'curl -H "X-Api-Key: <hidden>" http://localhost/x; ls'),
        ),
        # Unless the quoted word is the text after -c of a shell: that text is a shell text.
        (
            ("bash", "-c", "sh -c 'tool HF_TOKEN=made-up-49&ls'"),
            ("bash", "-c", "sh -c 'tool HF_TOKEN=<hidden>&ls'"),
        ),
        # So is a command text that a shell runs, as the remote command of ssh.
        (
            ("sh", "-c", "ssh host 'tool HF_TOKEN=made-up-46&ls -q' && ls"),
            ("sh", "-c", "ssh host 'tool HF_TOKEN=<hidden>&ls -q' && ls"),
        ),
    ],
)
def test_an_operator_no_shell_reads_ends_no_hidden_value(
    argv: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    lead = ("pairbench", "run", "--")
    assert model.public_command((*lead, *argv)) == shlex.join([*lead, *shown])


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ('tool -H "X-Api-Key: made-up-50 & made-up-51" -q', "tool -H X-Api-Key: <hidden> -q"),
        (
            "curl -H 'Cookie: a=1; sessionid=made-up-52' http://localhost/x",
            "curl -H Cookie: <hidden> http://localhost/x",
        ),
    ],
)
def test_an_operator_in_a_quoted_word_of_a_hyperfine_text_ends_no_hidden_value(
    text: str, shown: str
) -> None:
    assert model.public_words(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (
            "curl https://bench:made;up-53@made-up.example/x -q",
            "curl https://<hidden>@<hidden>/x -q",
        ),
        (
            "curl https://bench:made&&up-54@made-up.example/x; ls",
            "curl https://<hidden>@<hidden>/x; ls",
        ),
        ("curl https://bench:made|up-55@localhost/x", "curl https://<hidden>@localhost/x"),
        # An address with no user part still ends at the operator.
        ("curl https://made-up.example;ls", "curl https://<hidden>;ls"),
    ],
)
def test_the_user_part_of_an_address_is_hidden_whole_in_every_shell_text(
    text: str, shown: str
) -> None:
    # The text after ``sh -c`` and the command text of a hyperfine case show the same.
    argv = ("pairbench", "run", "--", "sh", "-c", text)
    assert model.public_command(argv) == shlex.join([*argv[:-1], shown])
    assert model.public_words(text) == shown


# Addresses whose host is empty (``scheme:///`` or ``scheme:////``): what follows is a local path,
# cut to its last part as a bare absolute path is, and the address keeps its empty host.
EMPTY_HOST_ADDRESSES = (
    ("sqlite:////made/up/home/db.sqlite", "sqlite:///db.sqlite"),
    ("sqlite:///made/up/home/x.db", "sqlite:///x.db"),
    ("duckdb:///made/up/home/x.duckdb", "duckdb:///x.duckdb"),
    ("unix:///made/up/home/s.sock", "unix:///s.sock"),
    ("redis+socket:///made/up/home/r.sock", "redis+socket:///r.sock"),
    ("SQLite:///made/up/home/x.db", "SQLite:///x.db"),
    ("https:///made/up/home/x", "https:///x"),
    ("sqlite:///made/up/home/dir/", "sqlite:///dir"),
    # Nothing to cut: one part only, no path, or no host at all.
    ("sqlite:///x.db", "sqlite:///x.db"),
    ("sqlite:///:memory:", "sqlite:///:memory:"),
    ("sqlite://", "sqlite://"),
    ("sqlite:///", "sqlite:///"),
    ("sqlite:////", "sqlite:////"),
)


@pytest.mark.parametrize(("address", "shown"), EMPTY_HOST_ADDRESSES)
def test_the_local_path_of_an_address_with_an_empty_host_is_cut(address: str, shown: str) -> None:
    assert model.public_text(f"open {address} now") == f"open {shown} now"
    assert model.public_text(shown) == shown
    assert model.public_case(f"test_open[{address}]") == f"test_open[{shown}]"
    assert model.public_case(f"BM_Open/{address}") == f"BM_Open/{shown}"
    assert model.public_case(f"test_open[{shown}]") == f"test_open[{shown}]"
    for spelled in ("{}", "--db={}", "DATABASE_URL={}"):
        argv = ("pairbench", "run", "--", "tool", spelled.format(address))
        assert model.public_command(argv) == shlex.join([*argv[:4], spelled.format(shown)])
    nested = model.public_command(("pairbench", "run", "--", "sh", "-c", f"tool --db {address} -q"))
    assert nested == shlex.join(["pairbench", "run", "--", "sh", "-c", f"tool --db {shown} -q"])
    assert model.public_words(f"tool --db {address} -q") == f"tool --db {shown} -q"
    # A second cleaning of the shown command changes nothing.
    once = model.public_command(("tool", address))
    assert once is not None
    assert model.public_command(shlex.split(once)) == once


@pytest.mark.parametrize(
    ("address", "command", "text"),
    [
        (
            "https://made-up.example/v1/chat/completions",
            "https://<hidden>/v1/chat/completions",
            "https://made-up.example/v1/chat/completions",
        ),
        (
            "s3://made-up-bucket/made/up/key",
            "s3://<hidden>/made/up/key",
            "s3://made-up-bucket/made/up/key",
        ),
        (
            "postgres://madeup@made-up.example/made/up/db",
            "postgres://<hidden>@<hidden>/made/up/db",
            "postgres://<hidden>@made-up.example/made/up/db",
        ),
    ],
)
def test_an_address_with_a_host_keeps_its_path(address: str, command: str, text: str) -> None:
    assert model.public_command(("tool", address)) == shlex.join(["tool", command])
    assert model.public_text(f"open {address}") == f"open {text}"


@pytest.mark.parametrize(
    ("arg", "shown"),
    [
        # A file address with a host and no path names a machine: the host is hidden.
        ("file://made-up-host", "file://<hidden>"),
        ("file://made-up-host:8000", "file://<hidden>:8000"),
        ("file://made-up-host:", "file://<hidden>:"),
        ("file://made-up-host?part=1", "file://<hidden>?part=1"),
        ("file://made-up-host#top", "file://<hidden>#top"),
        ("file://made-up-host;echo", "file://<hidden>;echo"),
        # A closing bracket or brace after the host ends it, as in a list or a shell default.
        ("file://made-up-host]", "file://<hidden>]"),
        ("[file://made-up-host]", "[file://<hidden>]"),
        ("${STORE:-file://made-up-host}", "${STORE:-file://<hidden>}"),
        ("file://[fd00::1]", "file://<hidden>"),
        ("file://hôst.example", "file://<hidden>"),
        ("file://~madeup", "file://<hidden>"),
        ("FILE://made-up-host", "FILE://<hidden>"),
        ("--storage=file://made-up-host", "--storage=file://<hidden>"),
        ("-mfile://made-up-host", "-mfile://<hidden>"),
        ("file://madeup@made-up-host", "file://<hidden>@<hidden>"),
        # Typed with no path before it, a file name is read as the host it stands for.
        ("file://m.gguf", "file://<hidden>"),
        ("file://localhost", "file://localhost"),
        ("file://LOCALHOST", "file://LOCALHOST"),
        ("file://127.0.0.1:8000", "file://127.0.0.1:8000"),
        ("file://[::1]", "file://[::1]"),
        ("file://", "file://"),
        ("file://.", "file://."),
        # With a path, the address shows its last part: the host went with the path's folders.
        ("file:///made/up/home/m.gguf", "file://m.gguf"),
        ("file://made-up-host/made/up/home/m.gguf", "file://m.gguf"),
        ("file://made-up-host/", "file:///"),
        ("file://./.benchmarks", "file://.benchmarks"),
        ("--benchmark-storage=file://./.benchmarks", "--benchmark-storage=file://.benchmarks"),
        # A host part no host name has is not read as a host: SECURITY.md lists these as limits.
        # A comma ends the host before it, so only the folders after the comma show.
        ("file://h:x/made/up/y", "file://h:x/made/up/y"),
        ("file://a,b/made/up/c", "file://<hidden>,b/made/up/c"),
    ],
)
def test_the_host_of_a_file_address_with_no_path_is_hidden(arg: str, shown: str) -> None:
    assert model.public_command(("pairbench", "run", "--", "tool", arg)) == shlex.join(
        ["pairbench", "run", "--", "tool", shown]
    )
    nested = model.public_command(("pairbench", "run", "--", "sh", "-c", f"tool {arg} -q"))
    assert nested == shlex.join(["pairbench", "run", "--", "sh", "-c", f"tool {shown} -q"])
    assert model.public_words(f"tool {arg} -q") == f"tool {shown} -q"
    assert model.public_words(f"sh -c 'tool {arg} -q'") == f"sh -c tool {shown} -q"


# Characters that no host name holds and that start no port, path or user part: each ends the
# host of a ``file://`` address before it, also a character outside ASCII.
ENDS_A_FILE_HOST = (",", "!", "=", "+", "$", "(", "[", "{", "*", "^", "\\", "\uff0c", "\u2014")
# What may follow that character: nothing, a letter, or a second file address with a host.
AFTER_THE_END = (
    ("", ""),
    ("x", "x"),
    ("file://other-made-up-host", "file://<hidden>"),
)


@pytest.mark.parametrize("end", ENDS_A_FILE_HOST)
@pytest.mark.parametrize(("after", "after_shown"), AFTER_THE_END)
def test_a_character_no_host_name_holds_ends_the_host_of_a_file_address(
    end: str, after: str, after_shown: str
) -> None:
    arg = f"file://made-up-host{end}{after}"
    shown = f"file://<hidden>{end}{after_shown}"
    assert model.public_command(("tool", arg)) == shlex.join(["tool", shown])
    assert model.public_command(("tool", f"--store={arg}")) == shlex.join(
        ["tool", f"--store={shown}"]
    )
    assert model.public_words(shlex.join(["tool", arg, "-q"])) == f"tool {shown} -q"


@pytest.mark.parametrize(
    ("arg", "shown"),
    [
        ("file://made-up-host:8000,", "file://<hidden>:8000,"),
        ("file://[fd00::1],x", "file://<hidden>,x"),
        (
            "file://made-up-host,file://made-up-host,file://made-up-host",
            "file://<hidden>," * 2 + "file://<hidden>",
        ),
        ("file://localhost,file://made-up-host", "file://localhost,file://<hidden>"),
        ("file://m.gguf=1", "file://<hidden>=1"),
    ],
)
def test_the_host_before_a_character_no_host_name_holds_is_hidden_with_its_port(
    arg: str, shown: str
) -> None:
    assert model.public_command(("tool", arg)) == shlex.join(["tool", shown])


def test_the_name_a_file_address_shows_after_its_path_is_cut_is_kept_by_every_cleaner() -> None:
    """The cut form of a path address reads as a file name, not as a host, once it is cut."""
    cut = "file://m.gguf"
    command = model.public_command(("pairbench", "run", "--", "tool", "file:///made/up/m.gguf"))
    assert command == "pairbench run -- tool file://m.gguf"
    assert model.public_text(f"model {cut}") == f"model {cut}"
    assert model.public_case(f"test_load[{cut}]/8") == f"test_load[{cut}]/8"


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("lock /made/up/locks/a.lock timed out", "lock a.lock timed out"),
        ("cannot read '/made/up/home/x.jsonl': denied", "cannot read 'x.jsonl': denied"),
        ("out=/made/up/home/runs/r1 is not empty", "out=r1 is not empty"),
        ("folder ~/runs/r1 exists", "folder r1 exists"),
        ("(/made/up/a/b, /made/up/c/d)", "(b, d)"),
        ("case c32/ttft_ms_median is new", "case c32/ttft_ms_median is new"),
        ("see https://example.org/docs/page", "see https://example.org/docs/page"),
        ("file runs/r1/capture.jsonl", "file runs/r1/capture.jsonl"),
        ("ratio 1/2 and a / b", "ratio 1/2 and a / b"),
        ("nothing to cut", "nothing to cut"),
        ("model file:///made/up/home/m.gguf", "model file://m.gguf"),
        ("model file://localhost/made/up/home/m.gguf", "model file://m.gguf"),
        ("model file://made-up-host/made/up/home/m.gguf", "model file://m.gguf"),
        ("model file://[::1]/made/up/home/m.gguf", "model file://m.gguf"),
        ("model File://made-up-host:/made/up/home/m.gguf", "model File://m.gguf"),
        ("x file:///made/up/a.bin,rel/dir/b.bin", "x file://a.bin,rel/dir/b.bin"),
        ("(file:///made/up/a.bin)/rel/b", "(file://a.bin)b"),
        ("model file://<hidden>/made/up/home/m.gguf", "model file://m.gguf"),
        ("model file://<hidden>@<hidden>:/made/up/home/m.gguf", "model file://m.gguf"),
        ("model file://hôst.example/made/up/home/m.gguf", "model file://m.gguf"),
        ("model file:///made/up/dir/", "model file://dir"),
        ("a run of ~madeup-user/proj/x", "a run of x"),
        ("copy /made/up/some one/x to b", "copy x to b"),
        ("python /made/up/x/bench.py --fast", "python bench.py --fast"),
        ("cp /made/up/a/b /made/up/c/d", "cp b d"),
        ("cc -I/made/up/include x.c", "cc -Iinclude x.c"),
        ("cc -I~madeup-user/include x.c", "cc -Iinclude x.c"),
        ("ssh to sftp://madeup:made-up@host.example/x", "ssh to sftp://<hidden>@host.example/x"),
        ("open sftp://madeup:made'up@host.example/x", "open sftp://<hidden>@host.example/x"),
        ("proxy -xhttp://madeup:made-up@host.example", "proxy -xhttp://<hidden>@host.example"),
        ("ratio -1/2 and -v/--verbose", "ratio -1/2 and -v/--verbose"),
        ("BM_copy/8/64 and test_x[a/b]", "BM_copy/8/64 and test_x[a/b]"),
        ("unknown config key: workload.key", "unknown config key: workload.key"),
        ("see https://example.org/a@b", "see https://example.org/a@b"),
        ("read ~madeup@corp.example/data/x.csv failed", "read x.csv failed"),
        ("cc -I~madeup@corp.example/include x.c", "cc -Iinclude x.c"),
        ("copy //made/up/share/x.bin now", "copy x.bin now"),
        ("x=//made/up/y", "x=y"),
        ("// a comment", "// a comment"),
        ("tool -1/made/up/x", "tool -1x"),
        ("ratio -1/2/3 and -1/abs", "ratio -1/2/3 and -1/abs"),
        ("case BM_Vec<int>/8 has no rounds", "case BM_Vec<int>/8 has no rounds"),
        ("case BM_Vec<int>/8/cpu_time", "case BM_Vec<int>/8/cpu_time"),
        ("tool >/made/up/out 2>/dev/null", "tool >out 2>null"),
        ("tr a b <in.txt>/made/up/home/out", "tr a b <in.txt>out"),
        ("cat <in>/made/up/x", "cat <in>x"),
        ("BM_Vec<int> wrote >/made/up/out", "BM_Vec<int> wrote >out"),
        ("case BM_Seq<Queue, int>/8/cpu_time", "case BM_Seq<Queue, int>/8/cpu_time"),
        ("case BM_X<std::vector<int>>/8", "case BM_X<std::vector<int>>/8"),
        ("cannot reach https://<hidden>/v1/models", "cannot reach https://<hidden>/v1/models"),
        ("open postgres://<hidden>@<hidden>/db/x", "open postgres://<hidden>@<hidden>/db/x"),
        ("cannot reach http://[::1]/v1/models", "cannot reach http://[::1]/v1/models"),
        ("cannot reach http://[fd00::1]:/v1/models", "cannot reach http://[fd00::1]:/v1/models"),
        ("https://<hidden>/v1 wrote /made/up/out", "https://<hidden>/v1 wrote out"),
        ("curl http://<hidden>>/made/up/out", "curl http://<hidden>>out"),
        ("see http://made-up.example'/made/up/x", "see http://made-up.example'x"),
        ("curl http://made-up.example|/made/up/home/x", "curl http://made-up.example|x"),
        ("curl http://made-up.example&&/made/up/home/x", "curl http://made-up.example&&x"),
        ("curl http://made-up.example;/made/up/home/x", "curl http://made-up.example;x"),
        ("(curl http://made-up.example)/made/up/home/x", "(curl http://made-up.example)x"),
        ("x=`curl http://made-up.example`/made/up/home/x", "x=`curl http://made-up.example`x"),
        ("get http://made-up.example,/made/up/home/x", "get http://made-up.example,x"),
        ("get http://made-up.example:8000,/made/up/home/x", "get http://made-up.example:8000,x"),
        ("get http://<hidden>;/made/up/home/x", "get http://<hidden>;x"),
    ],
)
def test_a_free_text_is_shown_with_absolute_paths_cut_to_their_last_part(
    text: str, shown: str
) -> None:
    assert model.public_text(text) == shown
    assert model.public_text(shown) == shown


@pytest.mark.parametrize(
    "case",
    [
        "BM_made_up<int>/8",
        "BM_made_up<int>/8/cpu_time",
        "BM_made_up<std::vector<int>>/1024/threads:4",
        "BM_made_up(x)/8",
        "BM_made_up[a]/8/16",
        "BM_made_up{a}/8",
        "made_up<T>/Device=0 T=I32",
        "made_up<T>/Device=0 T=I32/cpu_time",
        "test_made_up_div[1/2]",
        "c32/ttft_ms_median",
        "cpu_core/cycles/",
        "fetch[https://example.org/a/b]",
        "a // b",
        "run //-x",
        "run //",
        "x//y",
        "x///",
        "a/b/c",
        "k=///",
        "[////]",
        "BM_made_up#/8/cpu_time",
        "BM_made_up?/8/real_time",
        "BM_made_up&/8/cpu_time",
        "x postgresql:///db?c=https://h.example/a/b",
        "x postgresql:///db?c=k://made/up/x",
    ],
)
def test_a_case_id_that_holds_no_path_is_shown_as_it_is(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize(
    ("case", "shown"),
    [
        (
            "tests/test_io.py::test_read[/made/up/home/data.csv]",
            "tests/test_io.py::test_read[data.csv]",
        ),
        ("test_write[~madeup/out.csv]", "test_write[out.csv]"),
        ("test_write[~madeup@corp.example/a/out.csv]", "test_write[out.csv]"),
        ("BM_Read//made/up/home/x.bin", "BM_Read/x.bin"),
        ("//made/up/home/x.bin", "x.bin"),
        ("run //made/up/home/x.bin", "run x.bin"),
        ("run\t///made/up/home/x.bin", "run\tx.bin"),
        ("BM_Load/path:/made/up/home/y.bin", "BM_Load/path:y.bin"),
        ("made_up/Device=0 File=/made/up/home/a.bin", "made_up/Device=0 File=a.bin"),
        ("/made/up/a/bench", "bench"),
        ("read file:///made/up/a/x.bin", "read file://x.bin"),
        ("test_load[file://localhost/made/up/a/x.bin]", "test_load[file://x.bin]"),
        ("test_load[file://made-up-host/made/up/a/x.bin]", "test_load[file://x.bin]"),
        ("test_load[FILE:///made/up/a/x.bin]", "test_load[FILE://x.bin]"),
        ("test_load[file:///made/up/a/x.bin]/8", "test_load[file://x.bin]/8"),
        ("test_load[file://x.bin]/8", "test_load[file://x.bin]/8"),
        ("test_load[file://hôst/made/up/a/x.bin]/8", "test_load[file://x.bin]/8"),
        ("test_load[file:///made/up/dir/]", "test_load[file://dir]"),
        ("test_read[/made/up/a dir/b.csv]", "test_read[b.csv]"),
        (
            "fetch[postgres://madeup:made-up@db.example/x]",
            "fetch[postgres://<hidden>@db.example/x]",
        ),
        ("fetch[-xhttp://madeup:made-up@db.example/x]", "fetch[-xhttp://<hidden>@db.example/x]"),
    ],
)
def test_an_absolute_path_in_a_case_id_is_cut_where_a_value_starts(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# A path that starts with three "/" or more after one of = , ; [ ( { @ or a quote, or with two or
# more after the "/" that ends a part of a name, and its last part: such a path is cut whole,
# here, in the rest of an address and in the query of an address with no host.
SLASH_RUNS = [
    ("test_read[///made/up/home/x.bin]", "test_read[x.bin]"),
    ("test_read[////made/up/home/x.bin]", "test_read[x.bin]"),
    ("made_up/File=///made/up/home/a.bin", "made_up/File=a.bin"),
    ("made_up/File=////made/up/home/a.bin", "made_up/File=a.bin"),
    ("f(///made/up/home/x.bin)", "f(x.bin)"),
    ("f(////made/up/home/x.bin)", "f(x.bin)"),
    ("a,///made/up/home/x.bin", "a,x.bin"),
    ("a,////made/up/home/x.bin", "a,x.bin"),
    ("a;///made/up/home/x.bin", "a;x.bin"),
    ("a;////made/up/home/x.bin", "a;x.bin"),
    ("{///made/up/home/x.bin}", "{x.bin}"),
    ("{////made/up/home/x.bin}", "{x.bin}"),
    ("@///made/up/home/x.bin", "@x.bin"),
    ("@////made/up/home/x.bin", "@x.bin"),
    ("'///made/up/home/x.bin'", "'x.bin'"),
    ("'////made/up/home/x.bin'", "'x.bin'"),
    ('"///made/up/home/x.bin"', '"x.bin"'),
    ('"////made/up/home/x.bin"', '"x.bin"'),
    ("BM_Read///made/up/home/x.bin", "BM_Read/x.bin"),
    ("BM_Read////made/up/home/x.bin", "BM_Read/x.bin"),
    ("BM_made_up<int>///made/up/home/x.bin", "BM_made_up<int>/x.bin"),
    ("https://made.example///made/up/home/x.bin", "https://made.example//x.bin"),
    ("x postgresql:///db?host=///made/up/home/s", "x postgresql:///db?host=/s"),
    ("x postgresql:///db?host=////made/up/home/s", "x postgresql:///db?host=/s"),
    ("x unix:///s.sock?db=0&p=///made/up/home/x", "x unix:///s.sock?db=0&p=/x"),
    ("get https://h.example/p?next=///made/up/home/d", "get https://h.example/p?next=/d"),
    (
        "get https://h.example/p?a=/x/y&next=///made/up/home/d",
        "get https://h.example/p?a=/y&next=/d",
    ),
    ("get https://h.example:/p?next=///made/up/home/d", "get https://h.example:/p?next=/d"),
]


@pytest.mark.parametrize(("case", "shown"), SLASH_RUNS)
def test_a_path_that_starts_with_a_run_of_slashes_after_a_mark_is_cut_whole(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# A path that starts with one or two "/" after the same marks, and what it shows: two "/" there
# start the path at the second, the first read as the "/" that ends a part of a name, so it stays.
FEW_SLASHES = [
    ("f(/made/up/home/x.bin)", "f(x.bin)"),
    ("{/made/up/home/x.bin}", "{x.bin}"),
    ("@/made/up/home/x.bin", "@x.bin"),
    ("a;/made/up/home/x.bin", "a;x.bin"),
    ("test_read[//made/up/home/x.bin]", "test_read[/x.bin]"),
    ("made_up/File=//made/up/home/a.bin", "made_up/File=/a.bin"),
    ("f(//made/up/home/x.bin)", "f(/x.bin)"),
    ("a,//made/up/home/x.bin", "a,/x.bin"),
    ("a;//made/up/home/x.bin", "a;/x.bin"),
    ("{//made/up/home/x.bin}", "{/x.bin}"),
    ("@//made/up/home/x.bin", "@/x.bin"),
    ("'//made/up/home/x.bin'", "'/x.bin'"),
    ('"//made/up/home/x.bin"', '"/x.bin"'),
    ("https://made.example//made/up/home/x.bin", "https://made.example//x.bin"),
    ("x postgresql:///db?host=//made/up/home/s", "x postgresql:///db?host=/s"),
    ("x unix:///s.sock?db=0&p=//made/up/home/x", "x unix:///s.sock?db=0&p=/x"),
    ("get https://h.example/p?next=//made/up/home/d", "get https://h.example/p?next=//d"),
]


@pytest.mark.parametrize(("case", "shown"), FEW_SLASHES)
def test_a_path_that_starts_with_one_or_two_slashes_after_a_mark_shows_its_last_part(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown


# Slashes after ":" start an address, as ":" is no mark a run of "/" starts a path after: an
# address with no host has its local path cut, and one with a host keeps its path.
@pytest.mark.parametrize(
    ("case", "shown"),
    [
        ("k:///made/up/home/x.bin", "k:///x.bin"),
        ("k://made/up/home/x.bin", "k://made/up/home/x.bin"),
        ("http://made.example/x", "http://made.example/x"),
        ("file:////made/up/a/x.bin", "file://x.bin"),
    ],
)
def test_slashes_after_a_colon_start_an_address(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# A local address nested in the query or the fragment of an address, with or without a host
# before it, and a path right after the "?", "&" or "#" of an address: each is cut as it is in
# an address with a host, so its folders go.
NESTED_ADDRESSES = [
    (
        "test_conn[postgresql:///db?sslrootcert=file:///made/up/home/ca.pem]",
        "test_conn[postgresql:///db?sslrootcert=file://ca.pem]",
    ),
    ("x sqlite:///db.sqlite?vfs=file:///made/up/home/v", "x sqlite:///db.sqlite?vfs=file://v"),
    ("x unix:///s.sock?u=file://localhost/made/up/home/x", "x unix:///s.sock?u=file://x"),
    ("x redis:///0?a=b&c=file:////made/up/home/x", "x redis:///0?a=b&c=file://x"),
    ("x mysql:///db#file:///made/up/home/x", "x mysql:///db#file://x"),
    (
        "x postgresql:///db?c=sqlite:////made/up/home/db.sqlite?mode=ro",
        "x postgresql:///db?c=sqlite:///db.sqlite?mode=ro",
    ),
    (
        "x postgresql://h.example:/db?c=file:///made/up/home/x",
        "x postgresql://h.example:/db?c=file://x",
    ),
    (
        "get https://h.example/p?a=/x/y&next=file:///made/up/home/d",
        "get https://h.example/p?a=/y&next=file://d",
    ),
    ("x unix://h.example/s.sock?u=file:///made/up/home/x", "x unix:///s.sock?u=file://x"),
    (
        "x postgresql:///db?c=file:///made/up/a dir/x.pem tail",
        "x postgresql:///db?c=file://x.pem tail",
    ),
    ("x postgresql:///db?a=file:///made/up/a/x&b=/made/up/b/y", "x postgresql:///db?a=file://y"),
    ("x postgresql://h.example/db#/made/up/home/ca.pem", "x postgresql://h.example/db#/ca.pem"),
    ("x postgresql://h.example/db#~/made/up/ca.pem", "x postgresql://h.example/db#ca.pem"),
    ("x postgresql://h.example/db?/made/up/home/ca.pem", "x postgresql://h.example/db?/ca.pem"),
    (
        "x postgresql://h.example/db?a=b&/made/up/home/ca.pem",
        "x postgresql://h.example/db?a=b&/ca.pem",
    ),
    ("test_ui[https://h.example/#/made/up/list]", "test_ui[https://h.example/#/list]"),
]


@pytest.mark.parametrize(("case", "shown"), NESTED_ADDRESSES)
def test_a_local_address_or_path_nested_in_an_address_is_cut_to_its_last_part(
    case: str, shown: str
) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# Query and fragment tails that nest a local address, each shown the same after an address with
# no host as after one with a host.
NESTED_TAILS = [
    "?sslrootcert=file:///made/up/home/ca.pem",
    "?a=b&c=file:////made/up/home/x",
    "?a=b;c=file://localhost/made/up/home/x",
    "#file:///made/up/home/x",
    "?a=file:///made/up/a/x&b=/made/up/b/y",
    "?c=file:///made/up/a dir/x.pem tail",
]


@pytest.mark.parametrize("tail", NESTED_TAILS)
def test_a_nested_local_address_shows_the_same_with_and_without_a_host(tail: str) -> None:
    empty = model.public_case("x postgresql:///db" + tail)
    host = model.public_case("x postgresql://h.example/db" + tail)
    assert empty.removeprefix("x postgresql:///db") == host.removeprefix(
        "x postgresql://h.example/db"
    )
    assert "made/up" not in empty


# A "?", "&" or "#" outside an address joins the parts of a name: the parts after it are kept,
# and a path later in the id is still cut to its last part.
JOINED_THEN_PATH = [
    ("BM_made_up&/b/c tail k=/made/up/a dir/x.bin", "BM_made_up&/b/c tail k=x.bin"),
    ("BM_made_up?/8/real_time x=/made/up/home/x.bin,x", "BM_made_up?/8/real_time x=x.bin,x"),
    ("x &/b/c/cpu_time k=///made/up/x&x=1", "x &/b/c/cpu_time k=x&x=1"),
    (
        "BM_made_up#/8/cpu_time test_read[/made/up/home/a.csv]",
        "BM_made_up#/8/cpu_time test_read[a.csv]",
    ),
]


@pytest.mark.parametrize(("case", "shown"), JOINED_THEN_PATH)
def test_a_mark_that_joins_a_name_leaves_a_later_path_to_be_cut(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# A relative path that climbs out of its folder in the query or the fragment of an address: with
# no host, four '/', an empty port, a unix address, a user, an IPv6 host or no path before it,
# after an earlier path in the same query, with more than one '/' after its last '..', and inside
# a bracket, parentheses, quotes or braces. Each is cut to its last part, as it is outside an
# address.
CLIMBS_IN_ADDRESSES = [
    (
        "x postgresql:///db?sslrootcert=../../made/up/home/ca.pem",
        "x postgresql:///db?sslrootcert=ca.pem",
    ),
    (
        "test_conn[mysql://h.example:/db?ssl-ca=../made/up/home/ca.pem]",
        "test_conn[mysql://h.example:/db?ssl-ca=ca.pem]",
    ),
    ("x unix://sock.example/db?k=./../made/up/home/k.pem", "x unix:///db?k=k.pem"),
    ("x unix:///s.sock?k=../made/up/home/k.pem", "x unix:///s.sock?k=k.pem"),
    ("x redis:///0#../../made/up/home/y", "x redis:///0#y"),
    (
        "x postgresql:////srv/db?sslrootcert=data/../../made/up/home/ca.pem",
        "x postgresql:///db?sslrootcert=ca.pem",
    ),
    (
        "x postgresql:///db?a=1&sslrootcert=../made/up/home/ca.pem",
        "x postgresql:///db?a=1&sslrootcert=ca.pem",
    ),
    ("x https://h.example:/p?next=../../made/up/home/x", "x https://h.example:/p?next=x"),
    ("x sqlite:///db.sqlite?vfs=../made/up/home/v", "x sqlite:///db.sqlite?vfs=v"),
    ("x postgresql:///db?../made/up/home/ca.pem", "x postgresql:///db?ca.pem"),
    ("x postgresql:///db?a=b&../made/up/home/ca.pem", "x postgresql:///db?a=b&ca.pem"),
    ("x postgresql:///db#k=../made/up/home/ca.pem", "x postgresql:///db#k=ca.pem"),
    (
        "x postgresql:///db?sslrootcert=../made/up/home/ca.pem&z=1",
        "x postgresql:///db?sslrootcert=ca.pem&z=1",
    ),
    (
        "x postgresql://h.example/db?k=/a/x&k2=../made/up/home/ca.pem",
        "x postgresql://h.example/db?k=/x&k2=ca.pem",
    ),
    (
        "x postgresql://h.example/db?k=../x&z=1&k2=../made/up/home/ca.pem",
        "x postgresql://h.example/db?k=x&z=1&k2=ca.pem",
    ),
    (
        "x postgresql://h.example/db?k=~/a/x&k2=../made/up/home/ca.pem",
        "x postgresql://h.example/db?k=x&k2=ca.pem",
    ),
    (
        "x postgresql://h.example/db?k=/a/x#../made/up/home/ca.pem",
        "x postgresql://h.example/db?k=/x#ca.pem",
    ),
    (
        "x postgresql://u@h.example/db?k=/a/x&k2=./../made/up/home/ca.pem",
        "x postgresql://<hidden>@h.example/db?k=/x&k2=ca.pem",
    ),
    (
        "x postgresql://[fd00::1]/db?k=/a/x&k2=../made/up/home/ca.pem",
        "x postgresql://[fd00::1]/db?k=/x&k2=ca.pem",
    ),
    (
        "x postgresql://h.example?k=/a/x&k2=../made/up/home/ca.pem",
        "x postgresql://h.example?k=/x&k2=ca.pem",
    ),
    (
        "x postgresql:///db?sslrootcert=..//made/up/home/ca.pem",
        "x postgresql:///db?sslrootcert=ca.pem",
    ),
    (
        "x postgresql:///db?sslrootcert=../..///made/up/home/ca.pem",
        "x postgresql:///db?sslrootcert=ca.pem",
    ),
    (
        "f(postgresql:///db?sslrootcert=../made/up/home/ca.pem)",
        "f(postgresql:///db?sslrootcert=ca.pem)",
    ),
    (
        "x 'postgresql:///db?sslrootcert=../made/up/home/ca.pem' y",
        "x 'postgresql:///db?sslrootcert=ca.pem' y",
    ),
    (
        "x {postgresql:///db?sslrootcert=../made/up/home/ca.pem} y",
        "x {postgresql:///db?sslrootcert=ca.pem} y",
    ),
    (
        "test_conn[postgresql:///db?sslrootcert=../../made/up/home/ca.pem]/cpu_time x",
        "test_conn[postgresql:///db?sslrootcert=ca.pem]/cpu_time x",
    ),
]


@pytest.mark.parametrize(("case", "shown"), CLIMBS_IN_ADDRESSES)
def test_a_climbing_path_in_an_address_is_cut_to_its_last_part(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


# Query and fragment tails that hold a climbing path, each shown the same after an address with no
# host as after one with a host.
CLIMB_TAILS = [
    "?sslrootcert=../../made/up/home/ca.pem",
    "?a=b&c=./../made/up/home/x",
    "#data/../../made/up/home/x",
    "?a=/x/y&c=../made/up/home/x",
]


@pytest.mark.parametrize("tail", CLIMB_TAILS)
def test_a_climbing_path_shows_the_same_with_and_without_a_host(tail: str) -> None:
    empty = model.public_case("x postgresql:///db" + tail)
    host = model.public_case("x postgresql://h.example/db" + tail)
    assert empty.removeprefix("x postgresql:///db") == host.removeprefix(
        "x postgresql://h.example/db"
    )
    assert "made/up" not in empty


# A relative path in an address that stays inside its folder, and a path of '..' parts alone, with
# or without a host before it: the first is kept as typed, the second shows its last '..'.
INSIDE_ITS_FOLDER = [
    ("x postgresql:///db?k=a/../b", "x postgresql:///db?k=a/../b"),
    ("x postgresql:///db?k=a/../b/c.pem&z=1", "x postgresql:///db?k=a/../b/c.pem&z=1"),
    ("x postgresql://h.example/db?k=/a/x&k2=a/../b", "x postgresql://h.example/db?k=/x&k2=a/../b"),
    (
        "x postgresql://h.example/db?k=/a/x&k2=data/../x.csv",
        "x postgresql://h.example/db?k=/x&k2=data/../x.csv",
    ),
    ("x postgresql:///db?k=data/x.csv", "x postgresql:///db?k=data/x.csv"),
    ("x postgresql:///db#a/./b", "x postgresql:///db#a/./b"),
    ("x postgresql:///db?k=../&z=1", "x postgresql:///db?k=..&z=1"),
    ("x postgresql:///db?k=../..#f", "x postgresql:///db?k=..#f"),
    ("x postgresql://h.example/db?k=../&z=1", "x postgresql://h.example/db?k=..&z=1"),
    ("x postgresql://h.example/db?k=/a/x&k2=../&z=1", "x postgresql://h.example/db?k=/x&k2=..&z=1"),
    ("x postgresql:///db?k=..", "x postgresql:///db?k=.."),
]


@pytest.mark.parametrize(("case", "shown"), INSIDE_ITS_FOLDER)
def test_a_path_in_an_address_that_climbs_no_folder_keeps_its_parts(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
    assert model.public_case(shown) == shown


def test_a_refusal_a_note_and_a_failed_check_are_shown_without_absolute_paths() -> None:
    refusal = Refusal("E_LOCK", "the lock /made/up/locks/a.lock timed out")
    assert refusal.message == "the lock /made/up/locks/a.lock timed out"
    assert model.RefusalEntry.of(refusal).to_json() == {
        "code": "E_LOCK",
        "scope": "experiment",
        "message": "the lock a.lock timed out",
    }
    note = model.Note(code="identity_not_checked", message="no socket at /made/up/run/e.sock")
    assert note.for_results() == model.Note(
        code="identity_not_checked", message="no socket at e.sock"
    )
    assert note.message == "no socket at /made/up/run/e.sock"
    gate = model.GateRecord(
        name="census",
        mode="warn",
        status="unavailable",
        detail={"message": "cannot reach /made/up/run/e.sock"},
    )
    shown = gate.degraded()
    assert shown is not None
    assert shown.message == "cannot reach e.sock"


def test_the_marks_of_what_was_hidden_and_what_was_redacted() -> None:
    assert (model.HIDDEN, model.REDACTED) == ("<hidden>", "<redacted>")
