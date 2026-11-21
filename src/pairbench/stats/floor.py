# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Pairing, the per-pair quantities and the noise floor.

A subject value and a baseline value are a pair only when they come from the
same round. A round in which either value is missing is not a pair and is
counted as unpaired; values are never guessed or carried over.

The noise floor of a side on a case is how far the side sits from its twin:
``abs(median(t) - 1)`` with ``t_i = X_i / X~same_i`` over the rounds both have
a value, or the absolute median of the per-round percent differences under the
scale ``percent``. Rounds whose ``t_i`` lies outside the Tukey fences are
named, never dropped, and the interquartile range of ``t_i`` divided by its
median is recorded beside the floor as its spread. Every median and quartile
is ``pairbench.model.quantile``: linear interpolation between closest ranks.
A side so far from its twin that its floor is no finite number has no floor
(``far_apart``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pairbench.errors import Refusal
from pairbench.model import Scale, quantile, ratio_fault

# The value of the graded statistic that means no difference, per scale.
NEUTRAL: dict[str, float] = {"ratio": 1.0, "percent": 0.0}
# A floor computed from fewer rounds than this is provisional.
PROVISIONAL_BELOW = 8
# The Tukey fences lie this many interquartile ranges beyond the quartiles.
TUKEY_FACTOR = 1.5


def median(values: Sequence[float]) -> float:
    """Return the median: with an even count, the mean of the two middle values."""
    return quantile(values, 0.5)


def usable_ratio(ratio: float) -> float | None:
    """Return a ratio of two positive values when every figure made from it is a finite number.

    The ratio, its inverse (the speed-up where lower is better) and its
    percent difference ``100 * (ratio - 1)`` must each be a finite number,
    and the ratio must be above zero: two positive values give zero only when
    their ratio is too small for a float. Otherwise the values are too far
    apart and the result is ``None``.
    """
    return None if ratio_fault(ratio) is not None else ratio


def writable_floor(value: float, scale: Scale) -> bool:
    """Whether a floor or a bar, in the unit of the scale, is a finite number as a percentage.

    Reports write floors and bars as percentages, so a fraction is usable
    only when a hundred times it is still a finite number.
    """
    return math.isfinite(value * 100.0 if scale == "ratio" else value)


@dataclass(frozen=True)
class Pairs:
    """The pairs of two lineup entries on one case.

    ``rounds`` are the paired rounds in ascending order, and ``a_values`` and
    ``b_values`` the two entries' values in those rounds. ``n_unpaired``
    counts the rounds considered in which either value is missing.
    """

    case: str
    a: str
    b: str
    rounds: tuple[int, ...]
    a_values: tuple[float, ...]
    b_values: tuple[float, ...]
    n_unpaired: int


def pair_rounds(
    a: Mapping[int, float], b: Mapping[int, float], rounds: Iterable[int]
) -> tuple[list[int], list[float], list[float]]:
    """Return the rounds, out of ``rounds``, in which both entries have a value, and the values."""
    paired_rounds: list[int] = []
    a_values: list[float] = []
    b_values: list[float] = []
    for r in rounds:
        x = a.get(r)
        if x is None:
            continue
        y = b.get(r)
        if y is None:
            continue
        paired_rounds.append(r)
        a_values.append(x)
        b_values.append(y)
    return paired_rounds, a_values, b_values


def _field(obs: Any, name: str) -> Any:
    if isinstance(obs, Mapping):
        return obs[name]
    return getattr(obs, name)


def paired(observations: Iterable[Any], a: str, b: str) -> dict[str, Pairs]:
    """Pair two lineup entries round by round, for every case either of them has.

    ``observations`` are ``pairbench.model.Observation`` records, or mappings
    with the keys ``round``, ``name``, ``case`` and ``value``, of one capture:
    the round is the pairing key. To pair across several captures, number
    their rounds apart first. Observations of warm-up launches (round 0) are
    left out. The rounds considered are those in which any observation was
    given; a round in which either entry lacks a value for a case is not a
    pair for that case and is counted in ``n_unpaired``.

    The same round, entry and case given twice is refused (``E_GRID``).
    """
    if a == b:
        raise Refusal("E_USAGE", f"paired needs two different entries, got {a!r} twice")
    values: dict[tuple[str, str], dict[int, float]] = {}
    rounds: set[int] = set()
    cases: dict[str, None] = {}
    for obs in observations:
        r = _field(obs, "round")
        if r < 1:
            continue
        rounds.add(r)
        name = _field(obs, "name")
        if name not in (a, b):
            continue
        case = _field(obs, "case")
        cell = values.setdefault((name, case), {})
        if r in cell:
            raise Refusal(
                "E_GRID",
                f"round {r} holds two values of case {case!r} for {name!r}: a duplicated cell",
                detail={"duplicated": [[r, name, case]]},
            )
        cell[r] = float(_field(obs, "value"))
        cases[case] = None
    ordered = sorted(rounds)
    out: dict[str, Pairs] = {}
    for case in cases:
        got, a_values, b_values = pair_rounds(
            values.get((a, case), {}), values.get((b, case), {}), ordered
        )
        out[case] = Pairs(
            case=case,
            a=a,
            b=b,
            rounds=tuple(got),
            a_values=tuple(a_values),
            b_values=tuple(b_values),
            n_unpaired=len(ordered) - len(got),
        )
    return out


def per_pair(a_values: Sequence[float], b_values: Sequence[float], scale: Scale) -> list[float]:
    """Return the per-pair quantity of every pair under a scale.

    ``ratio``: ``a_i / b_i``. ``percent``: ``100.0 * (a_i - b_i) / b_i``,
    evaluated in exactly that order.
    """
    if scale == "ratio":
        return [x / y for x, y in zip(a_values, b_values, strict=True)]
    if scale == "percent":
        return [100.0 * (x - y) / y for x, y in zip(a_values, b_values, strict=True)]
    raise ValueError(f"a scale is ratio or percent: {scale!r}")


def sign_counts(
    a_values: Sequence[float], b_values: Sequence[float], quantities: Sequence[float], scale: Scale
) -> tuple[int, int]:
    """Count the pairs on each side of no difference: ``(n_lower, n_higher)``.

    Under scale ``ratio`` a pair is lower when ``a_i < b_i`` and a tie when
    the two values are equal exactly, so a ratio that rounds to 1.0 is never
    taken for a tie. Under scale ``percent`` the sign of ``d_i`` decides and
    a tie is ``d_i == 0.0``. Ties are not trials.
    """
    lower = higher = 0
    if scale == "ratio":
        for x, y in zip(a_values, b_values, strict=True):
            if x < y:
                lower += 1
            elif x > y:
                higher += 1
    else:
        for d in quantities:
            if d < 0.0:
                lower += 1
            elif d > 0.0:
                higher += 1
    return lower, higher


@dataclass(frozen=True)
class FloorStat:
    """A side's noise floor on one case, or on a set of cases.

    ``value`` is in the unit of the scale (a fraction under ``ratio``,
    percent under ``percent``). It is ``None`` when there is no floor: no
    round shared with the twin, or a value of zero or less in a shared round,
    which ``nonpositive`` then says. ``n`` is the number of rounds the floor
    was computed from (the fewest among the cases of a set), ``None`` for a
    floor the caller supplied. ``ratio`` is the median of ``t_i`` and
    ``n_lower`` and ``n_higher`` count the rounds below and above the twin;
    a set of cases has none of these three. ``far_apart`` says the side and
    its twin are so far apart that the floor is no finite number; ``value``
    is then ``None``.
    """

    value: float | None
    n: int | None
    spread: float | None = None
    outlier_rounds: tuple[int, ...] = ()
    nonpositive: bool = False
    ratio: float | None = None
    n_lower: int = 0
    n_higher: int = 0
    far_apart: bool = False

    @property
    def provisional(self) -> bool:
        """Whether the floor was computed from fewer than eight rounds."""
        return self.value is not None and self.n is not None and self.n < PROVISIONAL_BELOW


NO_FLOOR = FloorStat(value=None, n=0)


def tukey_outliers(rounds: Sequence[int], t: Sequence[float]) -> tuple[int, ...]:
    """Name the rounds whose ``t_i`` lies outside the Tukey fences.

    The fences lie 1.5 interquartile ranges below the first quartile and
    above the third. The rounds are named; none is dropped.
    """
    if not t:
        return ()
    q1, q3 = quantile(t, 0.25), quantile(t, 0.75)
    reach = TUKEY_FACTOR * (q3 - q1)
    low, high = q1 - reach, q3 + reach
    return tuple(r for r, x in zip(rounds, t, strict=True) if x < low or x > high)


def spread_of(t: Sequence[float]) -> float:
    """Return the interquartile range of ``t_i`` divided by its median."""
    return (quantile(t, 0.75) - quantile(t, 0.25)) / median(t)


def case_floor(
    side: Mapping[int, float], twin: Mapping[int, float], rounds: Iterable[int], scale: Scale
) -> FloorStat:
    """Return the noise floor of a side on one case, from its twin.

    Only the rounds both have a value count. A value of zero or less on the
    side or on its twin in one of those rounds leaves the side without a
    floor (``nonpositive``); no round is left out to keep one. A side so far
    from its twin that the median of ``t_i`` is no usable ratio
    (``usable_ratio``), or that the floor is no finite number as a
    percentage, has no floor either (``far_apart``); the rounds below and
    above the twin are still counted. A spread that is no finite number is
    not given.
    """
    shared, x, y = pair_rounds(side, twin, rounds)
    if not shared:
        return NO_FLOOR
    if any(v <= 0 for v in x) or any(v <= 0 for v in y):
        return FloorStat(value=None, n=len(shared), nonpositive=True)
    t = [a / b for a, b in zip(x, y, strict=True)]
    middle = median(t)
    if scale == "ratio":
        value = abs(middle - 1.0)
        quantities = t
    else:
        quantities = per_pair(x, y, scale)
        value = abs(median(quantities))
    lower, higher = sign_counts(x, y, quantities, scale)
    ratio = usable_ratio(middle)
    if ratio is None or not writable_floor(value, scale):
        return FloorStat(
            value=None,
            n=len(shared),
            ratio=ratio,
            n_lower=lower,
            n_higher=higher,
            far_apart=True,
        )
    spread = spread_of(t)
    return FloorStat(
        value=value,
        n=len(shared),
        spread=spread if math.isfinite(spread) else None,
        outlier_rounds=tukey_outliers(shared, t),
        ratio=middle,
        n_lower=lower,
        n_higher=higher,
    )


def combine_floors(stats: Iterable[FloorStat]) -> FloorStat:
    """Return the floor of a set of cases: the largest floor among them.

    A member that met a value of zero or less in a shared round leaves the
    whole set without a floor (``nonpositive``). Members with no shared round add nothing. ``n``
    is the fewest rounds among the members that count, so the set is
    provisional when any of them is; ``spread`` is the largest spread and
    ``outlier_rounds`` the rounds any member names. A member whose floor is
    no finite number leaves the largest none either, so the set has no floor
    (``far_apart``).
    """
    members = list(stats)
    if any(s.nonpositive for s in members):
        return FloorStat(
            value=None,
            n=min((s.n for s in members if s.n is not None), default=0),
            nonpositive=True,
        )
    if any(s.far_apart for s in members):
        return FloorStat(
            value=None,
            n=min((s.n for s in members if s.n is not None), default=0),
            far_apart=True,
        )
    counted = [s for s in members if s.value is not None]
    if not counted:
        return NO_FLOOR
    if len(counted) == 1:
        only = counted[0]
        return FloorStat(
            value=only.value,
            n=only.n,
            spread=only.spread,
            outlier_rounds=only.outlier_rounds,
        )
    spreads = [s.spread for s in counted if s.spread is not None]
    ns = [s.n for s in counted if s.n is not None]
    return FloorStat(
        value=max(s.value for s in counted if s.value is not None),
        n=min(ns) if ns else None,
        spread=max(spreads) if spreads else None,
        outlier_rounds=tuple(sorted({r for s in counted for r in s.outlier_rounds})),
    )


def supplied_floor(value: float | None, scale: Scale) -> FloorStat | None:
    """Return a floor the caller supplied, or ``None`` when none was supplied for the side.

    A supplied floor that is no finite number as a percentage
    (``writable_floor``) is no floor: the side is then too far apart
    (``far_apart``), as a measured floor of that size would be.
    """
    if value is None:
        return None
    if not writable_floor(float(value), scale):
        return FloorStat(value=None, n=None, far_apart=True)
    return FloorStat(value=float(value), n=None)
