# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Pairing, the per-pair quantities and the noise floor, with dyadic values so equality is exact."""

from __future__ import annotations

import pytest

from pairbench.errors import Refusal
from pairbench.model import Observation
from pairbench.stats.floor import (
    NO_FLOOR,
    FloorStat,
    case_floor,
    combine_floors,
    paired,
    per_pair,
    sign_counts,
    spread_of,
    supplied_floor,
    tukey_outliers,
)


def _obs(round_: int, name: str, case: str, value: float, seq: int = 1) -> Observation:
    return Observation(seq=seq, round=round_, pos=1, name=name, case=case, value=value)


def test_a_round_missing_either_value_is_not_a_pair_and_is_counted_unpaired() -> None:
    rows = [
        _obs(1, "new", "matmul", 2.0),
        _obs(1, "old", "matmul", 4.0),
        _obs(2, "new", "matmul", 3.0),
        _obs(3, "old", "matmul", 8.0),
        _obs(3, "new", "matmul", 1.0),
        _obs(0, "new", "matmul", 99.0),
        _obs(2, "new~same", "matmul", 3.0),
    ]
    pairs = paired(rows, "new", "old")
    assert list(pairs) == ["matmul"]
    got = pairs["matmul"]
    assert got.rounds == (1, 3)
    assert got.a_values == (2.0, 1.0)
    assert got.b_values == (4.0, 8.0)
    assert got.n_unpaired == 1


def test_pairing_accepts_mappings_and_counts_every_round_seen() -> None:
    rows = [
        {"round": 1, "name": "a", "case": "x", "value": 1.0},
        {"round": 1, "name": "b", "case": "x", "value": 2.0},
        {"round": 2, "name": "c", "case": "x", "value": 2.0},
    ]
    got = paired(rows, "a", "b")["x"]
    assert got.rounds == (1,)
    assert got.n_unpaired == 1


def test_a_duplicated_cell_is_refused_with_e_grid() -> None:
    rows = [_obs(1, "a", "x", 1.0), _obs(1, "a", "x", 2.0, seq=2)]
    with pytest.raises(Refusal) as caught:
        paired(rows, "a", "b")
    assert caught.value.code == "E_GRID"
    assert caught.value.exit_code == 6
    assert caught.value.detail["duplicated"] == [[1, "a", "x"]]


def test_pairing_an_entry_with_itself_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        paired([], "a", "a")
    assert caught.value.code == "E_USAGE"


def test_per_pair_quantities_under_both_scales() -> None:
    assert per_pair([3.0, 1.0], [2.0, 4.0], "ratio") == [1.5, 0.25]
    assert per_pair([3.0, 1.0], [2.0, 4.0], "percent") == [50.0, -75.0]
    with pytest.raises(ValueError, match="scale"):
        per_pair([1.0], [1.0], "log")  # type: ignore[arg-type]


def test_the_percent_difference_is_evaluated_in_the_order_written() -> None:
    # 100.0 * (S - B) / B exactly; any other order of the same operations rounds differently.
    assert per_pair([1.1, 1.3], [1.0, 1.2], "percent") == [10.000000000000009, 8.333333333333341]


def test_a_tie_is_an_exactly_equal_pair_and_is_no_trial() -> None:
    a = [1.0, 2.0, 2.0, 5.0]
    b = [2.0, 2.0, 1.0, 5.0]
    assert sign_counts(a, b, per_pair(a, b, "ratio"), "ratio") == (1, 1)
    assert sign_counts(a, b, per_pair(a, b, "percent"), "percent") == (1, 1)


def test_under_the_ratio_scale_the_values_decide_the_sign_not_the_ratio() -> None:
    a = [1.9999999999999998]
    b = [1.9999999999999996]
    assert sign_counts(a, b, [1.0], "ratio") == (0, 1)


# Eight rounds against a twin that reads 1.0 in each: sorted t is
# 1, 1, 1.0625, 1.0625, 1.125, 1.125, 1.25, 3. The median is 1.09375, the
# quartiles 1.046875 and 1.15625, the fences 0.8828125 and 1.3203125.
SIDE = {1: 1.0, 2: 1.125, 3: 1.0625, 4: 1.25, 5: 1.0, 6: 1.125, 7: 3.0, 8: 1.0625}
TWIN = dict.fromkeys(range(1, 9), 1.0)


def test_the_floor_of_a_case_is_the_distance_of_the_median_twin_ratio_from_one() -> None:
    floor = case_floor(SIDE, TWIN, range(1, 9), "ratio")
    assert floor.value == 0.09375
    assert floor.n == 8
    assert floor.ratio == 1.09375
    assert floor.outlier_rounds == (7,)
    assert floor.spread == 0.1
    assert (floor.n_lower, floor.n_higher) == (0, 6)
    assert not floor.provisional
    assert not floor.nonpositive


def test_the_floor_under_the_percent_scale_is_in_percent() -> None:
    floor = case_floor(SIDE, TWIN, range(1, 9), "percent")
    assert floor.value == 9.375
    assert floor.spread == 0.1
    assert floor.outlier_rounds == (7,)


def test_a_floor_from_fewer_than_eight_rounds_is_provisional() -> None:
    floor = case_floor(SIDE, TWIN, range(1, 8), "ratio")
    assert floor.n == 7
    assert floor.provisional


def test_only_rounds_both_have_count_and_none_gives_no_floor() -> None:
    assert case_floor({1: 2.0}, {2: 2.0}, (1, 2), "ratio") == NO_FLOOR
    assert NO_FLOOR.value is None
    assert not NO_FLOOR.provisional


def test_a_value_of_zero_or_less_in_a_shared_round_leaves_the_side_without_a_floor() -> None:
    twin = dict(TWIN)
    twin[4] = 0.0
    floor = case_floor(SIDE, twin, range(1, 9), "ratio")
    assert floor.value is None
    assert floor.nonpositive
    assert floor.n == 8


def test_a_value_of_zero_outside_the_shared_rounds_does_not_count() -> None:
    side = dict(SIDE)
    side[9] = -1.0
    floor = case_floor(side, TWIN, range(1, 10), "ratio")
    assert floor.value == 0.09375


def test_tukey_fences_and_spread() -> None:
    assert tukey_outliers((1, 2, 3, 4), (1.0, 1.0, 1.0, 1.0)) == ()
    assert tukey_outliers((), ()) == ()
    assert tukey_outliers((1, 2, 3, 4, 5), (1.0, 1.0, 1.0, 1.0, 2.0)) == (5,)
    assert spread_of([1.0, 1.0, 1.5, 2.0, 2.0]) == 1.0 / 1.5


def test_a_fence_lies_one_and_a_half_interquartile_ranges_beyond_a_quartile() -> None:
    # Sorted 1, 2, 3, 4 and a fifth value of at least 4: the quartiles are 2
    # and 4, so the upper fence is 4 + 1.5 * 2 = 7, and a value on it is inside.
    rounds = (1, 2, 3, 4, 5)
    assert tukey_outliers(rounds, (1.0, 2.0, 3.0, 4.0, 7.0)) == ()
    assert tukey_outliers(rounds, (1.0, 2.0, 3.0, 4.0, 8.0)) == (5,)


def test_the_floor_of_a_set_is_its_largest_member_with_the_fewest_rounds() -> None:
    a = FloorStat(value=0.25, n=8, spread=0.125, outlier_rounds=(3,))
    b = FloorStat(value=0.5, n=12, spread=0.0625, outlier_rounds=(5, 3))
    got = combine_floors([a, b, NO_FLOOR])
    assert got.value == 0.5
    assert got.n == 8
    assert got.spread == 0.125
    assert got.outlier_rounds == (3, 5)


def test_a_set_with_a_nonpositive_member_has_no_floor() -> None:
    a = FloorStat(value=0.25, n=8)
    bad = FloorStat(value=None, n=6, nonpositive=True)
    got = combine_floors([a, bad])
    assert got.value is None
    assert got.nonpositive
    assert combine_floors([NO_FLOOR]) == NO_FLOOR
    assert combine_floors([]) == NO_FLOOR


def test_a_set_with_one_member_keeps_its_floor_but_no_twin_counts() -> None:
    a = FloorStat(value=0.25, n=6, spread=0.5, outlier_rounds=(2,), ratio=1.25, n_higher=6)
    got = combine_floors([a])
    assert got == FloorStat(value=0.25, n=6, spread=0.5, outlier_rounds=(2,))
    assert got.provisional


def test_a_supplied_floor() -> None:
    assert supplied_floor(None, "ratio") is None
    got = supplied_floor(0.012, "ratio")
    assert got == FloorStat(value=0.012, n=None)
    assert got is not None and not got.provisional


# A fraction whose percentage is beyond the float range.
FRACTION_PAST_PERCENT = 1e307


def test_a_supplied_floor_with_no_finite_percentage_is_no_floor() -> None:
    assert supplied_floor(FRACTION_PAST_PERCENT, "ratio") == FloorStat(
        value=None, n=None, far_apart=True
    )
    # Under the percent scale the floor is already a percentage.
    assert supplied_floor(FRACTION_PAST_PERCENT, "percent") == FloorStat(
        value=FRACTION_PAST_PERCENT, n=None
    )
