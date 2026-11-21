# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Builders shared by the statistics tests: plain grids of made-up values."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import pytest

from pairbench.model import Case, rotate_reverse
from pairbench.stats.rules import Grid

TIME_CASE = Case(id="matmul", metric="time", unit="s", kind="time")

GridBuilder = Callable[..., Grid]


def build_grid(
    values: Mapping[str, Mapping[str, Sequence[float | None]]],
    *,
    subjects: Sequence[str] = ("new",),
    baseline: str = "old",
    cases: Sequence[Case] = (TIME_CASE,),
    twins: Mapping[str, str] | None = None,
    positions: Mapping[tuple[int, str], int | None] | None = None,
    order: bool = True,
    disturbed: Sequence[int] = (),
) -> Grid:
    """Build a grid from per-entry, per-case lists of values, round 1 first.

    ``None`` in a list leaves that round without a value. Twins default to
    every entry named ``<side>~same`` that has values. Positions default to
    the ``rotate-reverse`` schedule over the entries in the order given;
    ``order=False`` records none.
    """
    entries = list(values)
    rounds = max(len(v) for per_case in values.values() for v in per_case.values())
    table: dict[tuple[str, str], dict[int, float]] = {}
    for entry, per_case in values.items():
        for case, row in per_case.items():
            table[(entry, case)] = {i: v for i, v in enumerate(row, start=1) if v is not None}
    if twins is None:
        twins = {e.removesuffix("~same"): e for e in entries if e.endswith("~same")}
    if positions is None:
        positions = {}
        for r in range(1, rounds + 1):
            for pos, name in enumerate(rotate_reverse(entries, r), start=1):
                positions[(r, name)] = pos if order else None
    return Grid(
        rounds=tuple(range(1, rounds + 1)),
        values=table,
        positions=positions,
        subjects=tuple(subjects),
        baseline=baseline,
        twins=dict(twins),
        cases=tuple(cases),
        disturbed=tuple(disturbed),
    )


@pytest.fixture
def grid_of() -> GridBuilder:
    """Return the grid builder."""
    return build_grid
