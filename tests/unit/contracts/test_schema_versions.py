# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Within a schema version, a field that lists its values may gain one and never loses one.

The values below are those of version 1 of the results document, written out as
constants. A value may be added to the shipped schema; removing or renaming one
needs a new schema version, and then this file changes with it.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pairbench.results import load_schema

RESULTS_V1 = "pairbench/results/v1"

OUTCOMES_V1 = ("better", "worse", "higher", "lower", "tie", "unresolved", "no_verdict")

REASONS_V1 = (
    "inside_noise",
    "not_significant",
    "order_unbalanced",
    "sensitive_to_disturbed_rounds",
    "positive_control_failed",
    "nonpositive_value",
    "too_far_apart",
    "single_measurement",
    "order_not_recorded",
    "too_few_rounds",
    "no_floor",
    "one_sided_floor",
    "zero_floor",
    "side_failed",
    "more_than_one_node",
)


def _lost(schema: dict[str, Any]) -> list[str]:
    """The version 1 values the schema does not list, field by field."""
    comparison = schema["$defs"]["Comparison"]["properties"]
    listed = {
        "outcome": set(comparison["outcome"]["enum"]),
        "reason": set(comparison["reason"]["enum"]),
        "reasons": set(comparison["reasons"]["items"]["enum"]),
    }
    recorded = {"outcome": OUTCOMES_V1, "reason": REASONS_V1, "reasons": REASONS_V1}
    return [
        f"{field}: {value}"
        for field, values in recorded.items()
        for value in values
        if value not in listed[field]
    ]


def test_the_results_schema_keeps_every_version_1_outcome_and_reason() -> None:
    schema = load_schema("results")
    assert schema["properties"]["schema"]["const"] == RESULTS_V1
    assert _lost(schema) == []


def test_a_value_removed_from_the_schema_is_seen() -> None:
    schema = copy.deepcopy(load_schema("results"))
    reason = schema["$defs"]["Comparison"]["properties"]["reason"]
    reason["enum"] = [value for value in reason["enum"] if value != "zero_floor"]
    assert _lost(schema) == ["reason: zero_floor"]


@pytest.mark.parametrize("added", ["made_up_reason"])
def test_a_value_added_to_the_schema_is_allowed(added: str) -> None:
    schema = copy.deepcopy(load_schema("results"))
    schema["$defs"]["Comparison"]["properties"]["reason"]["enum"].append(added)
    assert _lost(schema) == []
