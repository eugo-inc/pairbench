# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Benchmarks of the example library, read by the ``pytest-benchmark`` driver.

With ``PAIRBENCH_WORK_FACTOR=N`` each benchmarked call does N times the work.
"""

from __future__ import annotations

import os

from examplelib import dedupe, word_counts

FACTOR = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
ITEMS = [i % 500 for i in range(5_000)]
TEXT = " ".join(f"Word{i % 300}" for i in range(20_000))


def dedupe_all() -> None:
    for _ in range(FACTOR):
        dedupe(ITEMS)


def count_all() -> None:
    for _ in range(FACTOR):
        word_counts(TEXT)


def test_dedupe(benchmark):
    benchmark(dedupe_all)
    assert dedupe(ITEMS) == list(range(500))


def test_word_counts(benchmark):
    benchmark(count_all)
    assert word_counts(TEXT)["word0"] == 67
