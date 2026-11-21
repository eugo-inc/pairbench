# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The exact two-sided sign test with probability one half.

The tail and the power of two are Python integers, so the arithmetic is exact
for any number of pairs. The tail is summed term by term, each binomial
coefficient made from the one before it, so a test of many pairs takes time
in proportion to the shorter tail. The single floating-point operation is
the final division. The p-value is kept both as a float and as the fraction
``[min(2 * tail, 2 ** n), 2 ** n]``, which is not reduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class SignTest:
    """The result of one sign test.

    ``n_lower`` and ``n_higher`` count the pairs on each side of no
    difference; ties are not trials and are counted in neither. ``n`` is
    their sum. ``p`` is the two-sided p-value and ``fraction`` the same value
    as an exact fraction ``(numerator, denominator)``, with the denominator
    ``2 ** n``.
    """

    n_lower: int
    n_higher: int
    n: int
    p: float
    fraction: tuple[int, int]


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} is a whole number of zero or more: {value!r}")
    return value


@lru_cache(maxsize=4096)
def _sign_test(n_lower: int, n_higher: int) -> SignTest:
    n = n_lower + n_higher
    k = min(n_lower, n_higher)
    # comb(n, i + 1) = comb(n, i) * (n - i) / (i + 1), and the division is exact.
    tail = 0
    term = 1
    for i in range(k + 1):
        tail += term
        term = term * (n - i) // (i + 1)
    whole = 1 << n
    p = min(1.0, (2 * tail) / whole)
    return SignTest(
        n_lower=n_lower,
        n_higher=n_higher,
        n=n,
        p=p,
        fraction=(min(2 * tail, whole), whole),
    )


def sign_test(n_lower: int, n_higher: int) -> SignTest:
    """Return the exact two-sided sign test of ``n_lower`` against ``n_higher`` pairs.

    ``k = min(n_lower, n_higher)``, ``tail = sum(comb(n, i) for i in 0..k)``
    and ``p = min(1, 2 * tail / 2 ** n)``. No pair at all gives 1.0. Twelve
    against none gives 2/4096; ten against two gives 158/4096.
    """
    return _sign_test(_count(n_lower, "n_lower"), _count(n_higher, "n_higher"))
