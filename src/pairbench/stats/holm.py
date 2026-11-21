# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Holm correction for testing several cases at once."""

from __future__ import annotations

import math
from collections.abc import Sequence


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
