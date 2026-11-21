# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A small example library, revision b: ``dedupe`` keeps what it has seen in a list."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable


def dedupe(items: Iterable[Hashable]) -> list[Hashable]:
    """Return the items in their first order, each once."""
    out: list[Hashable] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def word_counts(text: str) -> dict[str, int]:
    """Return how often each lower-cased word occurs in ``text``."""
    return dict(Counter(text.lower().split()))
