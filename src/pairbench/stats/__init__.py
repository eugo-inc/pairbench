# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Statistics: the sign test, the correction for several cases, pairing and the verdict rule.

This part is pure. It takes observations and returns numbers: it reads no
file and starts no process, and it imports only ``pairbench.model`` and
``pairbench.errors``.

The primitives are public, so that a caller can assemble an analysis of its
own: ``sign_test(n_lower, n_higher)``, ``holm(pvalues)``,
``paired(observations, a, b)`` and ``min_rounds(n_cases, alpha)``.
"""

from __future__ import annotations

from pairbench.model import min_rounds
from pairbench.stats.floor import Pairs, paired
from pairbench.stats.holm import holm
from pairbench.stats.signtest import SignTest, sign_test

__all__ = ["Pairs", "SignTest", "holm", "min_rounds", "paired", "sign_test"]
