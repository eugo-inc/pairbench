# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Holm correction for testing several cases at once.

``holm`` corrects floats, and its values are the ones the results write.
``holm_exact`` corrects exact fractions, and its values are the ones a
verdict is decided on.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from fractions import Fraction


def holm(pvalues: Sequence[float]) -> list[float]:
    """Return the Holm-adjusted p-values, in the order the values were given.

    The values are sorted ascending, ties kept in the order given, and
    ``adj[i] = max(adj[i - 1], min(1, (m - i) * p[i]))`` for ``i = 0 .. m - 1``,
    with ``adj[-1] = 0``. The running maximum keeps the adjusted values in
    the order of the raw ones. ``[0.01, 0.04, 0.5]`` gives ``[0.03, 0.08, 0.5]``.
    """
    values = list(pvalues)
    for p in values:
        if isinstance(p, bool) or not isinstance(p, int | float):
            raise ValueError(f"a p-value is a number: {p!r}")
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"a p-value lies from 0 to 1: {p!r}")
    m = len(values)
    order = sorted(range(m), key=lambda i: (values[i], i))
    adjusted = [0.0] * m
    previous = 0.0
    for rank, index in enumerate(order):
        previous = max(previous, min(1.0, (m - rank) * values[index]))
        adjusted[index] = previous
    return adjusted


def holm_exact(pvalues: Sequence[Fraction]) -> list[Fraction]:
    """Return the Holm-adjusted p-values of exact fractions, in the order given.

    The same steps as ``holm``, each exact: the values are sorted ascending
    by their exact value, ties kept in the order given, and
    ``adj[i] = max(adj[i - 1], min(1, (m - i) * p[i]))``. No step rounds, so
    comparing an adjusted value with alpha gives the same answer at any
    number of rounds. ``[1/100, 1/25, 1/2]`` gives ``[3/100, 2/25, 1/2]``.
    """
    values = list(pvalues)
    for p in values:
        if not isinstance(p, Fraction):
            raise ValueError(f"an exact p-value is a Fraction: {p!r}")
        if not 0 <= p <= 1:
            raise ValueError(f"a p-value lies from 0 to 1: {p!r}")
    m = len(values)
    order = sorted(range(m), key=lambda i: (values[i], i))
    adjusted = [Fraction(0)] * m
    previous = Fraction(0)
    for rank, index in enumerate(order):
        previous = max(previous, min(Fraction(1), (m - rank) * values[index]))
        adjusted[index] = previous
    return adjusted
