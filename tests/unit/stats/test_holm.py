# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Holm correction: four known answers, as constants."""

from __future__ import annotations

import math

import pytest

from pairbench.stats.holm import holm


@pytest.mark.parametrize(
    ("raw", "adjusted"),
    [
        ([0.01, 0.04, 0.5], [0.03, 0.08, 0.5]),
        ([0.01, 0.012, 0.5], [0.03, 0.03, 0.5]),
        ([0.01, 0.04, 0.03], [0.03, 0.06, 0.06]),
        ([0.03125, 0.03125, 0.21875], [0.09375, 0.09375, 0.21875]),
    ],
)
def test_the_known_answers(raw: list[float], adjusted: list[float]) -> None:
    assert holm(raw) == pytest.approx(adjusted, abs=1e-15)


def test_the_running_maximum_keeps_a_larger_raw_value_from_a_smaller_adjustment() -> None:
    # Without the monotone step, 0.04 would be adjusted to 1 * 0.04.
    assert holm([0.04, 0.01, 0.03]) == pytest.approx([0.06, 0.03, 0.06], abs=1e-15)


def test_values_come_back_in_the_order_given() -> None:
    assert holm([0.5, 0.01]) == pytest.approx([0.5, 0.02], abs=1e-15)


def test_an_adjusted_value_never_exceeds_one() -> None:
    assert holm([0.6, 0.7]) == [1.0, 1.0]


def test_one_value_is_unchanged_and_none_gives_none() -> None:
    assert holm([0.2]) == [0.2]
    assert holm([]) == []


@pytest.mark.parametrize("bad", [-0.1, 1.5, math.nan, math.inf, True, "0.1"])
def test_a_value_that_is_no_p_value_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="p-value"):
        holm([0.1, bad])  # type: ignore[list-item]
