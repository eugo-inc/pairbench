# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Builders of made-up results and diagnostics documents for the tests of the reports."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.model import Diagnostics, Results

Build = Callable[..., Results]


def case_record(case_id: str, unit: str, better: str, kind: str, primary: bool) -> dict[str, Any]:
    """Return a case record of a results document."""
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
        doc["cases"] = doc["cases"] + [case_record(*row) for row in cases]
        doc.update(top)
        return Results.from_json(doc)

    return make


@pytest.fixture
def diagnostics(example_diagnostics: dict[str, Any]) -> Diagnostics:
    """The example diagnostics document, with a finding that names a function and one more
    finding made from counters."""
    doc = copy.deepcopy(example_diagnostics)
    doc["findings"].append(
        {
            "id": "top_function_share",
            "text": "markerfunctionname has a share of samples of 25% on new.",
            "evidence": {"side": "new", "share": 0.25},
        }
    )
    doc["findings"].append(
        {
            "id": "top_object_share",
            "text": "libmarkerobject.so has a share of samples of 50% on new.",
            "evidence": {"side": "new", "share": 0.5},
        }
    )
    doc["findings"].append(
        {
            "id": "instructions",
            "text": "new counted 0.50x the instructions of old.",
            "evidence": {"subject_value": 1000, "baseline_value": 2000},
        }
    )
    doc["stacks"][0]["top_functions"][0]["name"] = "markerfunctionname"
    doc["stacks"][0]["top_objects"][0]["name"] = "libmarkerobject.so"
    return Diagnostics.from_json(doc)
