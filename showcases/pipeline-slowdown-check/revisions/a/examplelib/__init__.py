# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A small example library, revision a."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable


def dedupe(items: Iterable[Hashable]) -> list[Hashable]:
    """Return the items in their first order, each once."""
    seen: set[Hashable] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def word_counts(text: str) -> dict[str, int]:
    """Return how often each lower-cased word occurs in ``text``."""
    return dict(Counter(text.lower().split()))
