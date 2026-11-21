# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Builders of made-up results documents for the tests of the figures and the writer."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.model import Results

Build = Callable[..., Results]


def _case(case_id: str, unit: str, better: str, kind: str, primary: bool) -> dict[str, Any]:
    return {
        "id": case_id,
        "metric": case_id.rpartition("/")[2],
        "unit": unit,
        "better": better,
        "kind": kind,
        "primary": primary,
        "group": case_id if case_id.startswith("res/") else None,
    }


@pytest.fixture
def build(example_results: dict[str, Any]) -> Build:
    """Return a function that builds a results document from the example of the format.

    ``comparisons`` replaces the comparison list with copies of the example
    comparison, each updated with the keys given; ``cases`` adds case records
    as ``(id, unit, better, kind, primary)``; every other keyword replaces a
    top-level key.
    """
    base = example_results["comparisons"][0]

    def make(
        *,
        comparisons: list[dict[str, Any]] | None = None,
        cases: tuple[tuple[str, str, str, str, bool], ...] = (),
        **top: Any,
    ) -> Results:
        doc = copy.deepcopy(example_results)
        if comparisons is not None:
            doc["comparisons"] = [{**copy.deepcopy(base), **c} for c in comparisons]
        doc["cases"] = doc["cases"] + [_case(*row) for row in cases]
        doc.update(top)
        return Results.from_json(doc)

    return make
