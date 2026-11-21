# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Results documents for the chart tests, built in code from the shared example.

Every value is made up. The document has two sides with twins, two primary
cases (one whose name is unsafe in a file name), two resource cases, three
same-against-same rows and a series for every lineup entry, with round 3
set aside as disturbed on the first case.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pairbench.model import Results


def comparison_like(
    base: dict[str, Any],
    case: str,
    ratio: float | None,
    verdict: str,
    outcome: str,
    medians: tuple[float | None, float | None],
    *,
    primary: bool = True,
    reason: str | None = None,
    subject: str = "new",
) -> dict[str, Any]:
    """Return a copy of a comparison with the given case, ratio, verdict and medians."""
    made = copy.deepcopy(base)
    made.update(
        case=case,
        subject=subject,
        ratio=ratio,
        statistic=ratio,
        verdict=verdict,
        outcome=outcome,
        subject_median=medians[0],
        baseline_median=medians[1],
        primary=primary,
        reason=reason,
        reasons=[] if reason is None else [reason],
    )
    return made


def resource_case_json(case: str, unit: str) -> dict[str, Any]:
    """Return the case record of a resource case."""
    return {
        "id": case,
        "metric": case.removeprefix("res/"),
        "unit": unit,
        "better": "none",
        "kind": "count" if unit == "count" else "other",
        "primary": False,
        "group": case,
    }


def build_chart_document(example: dict[str, Any]) -> dict[str, Any]:
    """Extend the shared example results into a document every chart has data for."""
    doc = copy.deepcopy(example)
    side = doc["sides"][0]
    doc["sides"] = [
        dict(side, name="new"),
        dict(side, name="new~same", role="twin", twin_of="new"),
        dict(side, name="old", role="baseline"),
        dict(side, name="old~same", role="twin", twin_of="old"),
    ]
    case = doc["cases"][0]
    doc["cases"] = [
        dict(case, id="matmul"),
        dict(case, id="c32/ttft_ms", metric="ttft_ms", unit="ms"),
        resource_case_json("res/cores", "cores"),
        resource_case_json("res/rss_peak", "bytes"),
    ]
    base = doc["comparisons"][0]
    doc["comparisons"] = [
        comparison_like(base, "matmul", 0.8, "FASTER", "better", (1.92, 2.4)),
        comparison_like(base, "c32/ttft_ms", 1.25, "SLOWER", "worse", (12.5, 10.0)),
        comparison_like(base, "res/cores", 8.0, "HIGHER", "higher", (8.0, 1.0), primary=False),
        comparison_like(base, "res/rss_peak", 0.5, "LOWER", "lower", (1.0e9, 2.0e9), primary=False),
    ]
    doc["same_vs_same"] = [
        {"side": "new", "case": "matmul", "ratio": 1.004, "floor": 0.004, "p_raw": 0.8, "n": 16},
        {"side": "old", "case": "matmul", "ratio": 0.993, "floor": 0.007, "p_raw": 0.6, "n": 16},
        {"side": "new", "case": "c32/ttft_ms", "ratio": 1.02, "floor": 0.02, "p_raw": 0.4, "n": 16},
    ]
    doc["series"] = [
        {
            "case": "matmul",
            "name": "new",
            "values": [1.92, 1.91, 2.2, 1.93],
            "disturbed_rounds": [3],
        },
        {
            "case": "matmul",
            "name": "new~same",
            "values": [1.93, 1.92, 2.3, 1.92],
            "disturbed_rounds": [3],
        },
        {
            "case": "matmul",
            "name": "old",
            "values": [2.41, 2.4, 2.6, 2.42],
            "disturbed_rounds": [3],
        },
        {
            "case": "matmul",
            "name": "old~same",
            "values": [2.4, None, 2.7, 2.41],
            "disturbed_rounds": [3],
        },
        {
            "case": "c32/ttft_ms",
            "name": "new",
            "values": [12.5, 12.6, 12.4],
            "disturbed_rounds": [],
        },
        {"case": "c32/ttft_ms", "name": "old", "values": [10.0, 10.1, 9.9], "disturbed_rounds": []},
    ]
    return doc


@pytest.fixture
def chart_document(example_results: dict[str, Any]) -> dict[str, Any]:
    """A results document, as a dict, that every chart has data for."""
    return build_chart_document(example_results)


@pytest.fixture
def chart_results(chart_document: dict[str, Any]) -> Results:
    """The document of ``chart_document`` as ``Results``."""
    return Results.from_json(chart_document)
