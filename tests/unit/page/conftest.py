# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Documents and a run folder for the report page tests, built in code. Every value is made up."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

# A small SVG picture that points nowhere outside itself.
CHART_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
    "<text x='1' y='20'>made-up chart</text></svg>"
)
# A small flame graph with a script of its own, as the explain step writes one.
FLAME_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="180">'
    "<script><![CDATA[document.addEventListener('keydown', function (e) { return e; });]]>"
    "</script><g><title>made_up_function (25.0%)</title><rect width='10' height='16'/>"
    "<text>made_up_function</text></g></svg>"
)


def build_page_document(example: dict[str, Any]) -> dict[str, Any]:
    """Extend the shared example results with a baseline, twins and a resource case."""
    doc = copy.deepcopy(example)
    side = doc["sides"][0]
    doc["sides"] = [
        dict(side, name="new"),
        dict(side, name="new~same", role="twin", twin_of="new"),
        dict(side, name="old", role="baseline"),
    ]
    doc["cases"].append(
        {
            "id": "res/cores",
            "metric": "cores",
            "unit": "cores",
            "better": "none",
            "kind": "other",
            "primary": False,
            "group": "res/cores",
        }
    )
    resource = copy.deepcopy(doc["comparisons"][0])
    resource.update(
        case="res/cores",
        primary=False,
        ratio=8.0,
        statistic=8.0,
        subject_median=8.0,
        baseline_median=1.0,
        verdict="HIGHER",
        outcome="higher",
    )
    doc["comparisons"].append(resource)
    return doc


@pytest.fixture
def page_document(example_results: dict[str, Any]) -> dict[str, Any]:
    """A results document, as a dict, with a baseline side, a twin and a resource case."""
    return build_page_document(example_results)


@pytest.fixture
def run_folder(tmp_path: Path) -> Path:
    """A run folder that holds two chart files and one flame graph."""
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "verdict.svg").write_text(CHART_SVG, encoding="utf-8")
    (tmp_path / "charts" / "rounds.matmul.svg").write_text(CHART_SVG, encoding="utf-8")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "new.flame.svg").write_text(FLAME_SVG, encoding="utf-8")
    (tmp_path / "profiles" / "new.folded").write_text("made_up_function 1\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def with_files(page_document: dict[str, Any]) -> dict[str, Any]:
    """The page document listing the files of ``run_folder`` under ``artifacts``."""
    page_document["artifacts"]["charts"] = ["charts/verdict.svg", "charts/rounds.matmul.svg"]
    page_document["artifacts"]["profiles"] = ["profiles/new.folded", "profiles/new.flame.svg"]
    return page_document
