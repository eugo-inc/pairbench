# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each page that gives a driver's status says what ``pairbench doctor`` reports.

A driver without a fixture from a real run reports ``experimental``. The driver
table, the driver's guide, the changelog, the showcase pages, the driver's own
docstring and the third-party notices say so for exactly those drivers.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from pairbench import api, registry

# The drivers that have no fixture from a run of the real tool.
EXPERIMENTAL = {"vllm-bench"}

# "`name` (experimental)", the link around the name optional.
MARKED = re.compile(r"`([a-z][a-z-]*)`(?:\]\([^)\s]*\))? \(experimental\)")
# "the `name` driver is experimental", "... driver, which is experimental",
# "... driver is marked experimental", "The name driver, experimental, ...".
CALLED = re.compile(
    r"`?([a-z][a-z-]*)`?(?:\]\([^)\s]*\))? driver"
    r"(?: is| is marked|, which is|,) experimental",
    re.IGNORECASE,
)
STATUS_ROW = re.compile(r"^\| \[`([a-z][a-z-]*)`\]\([^)]*\) \|.*\| ([a-z]+) \|$")
UPSTREAM = "## Test fixtures derived from an upstream sample"
SIDECAR = ".provenance.json"


def _drivers() -> list[str]:
    return sorted(registry.names(api.GROUP_DRIVERS))


def _status(name: str) -> str:
    driver: Any = registry.driver(name)
    if isinstance(driver, api.Diagnosable):
        return driver.doctor().status
    return "ok"


def _flat(text: str) -> str:
    """The text with every run of white space as one blank, so a wrapped sentence is one line."""
    return " ".join(text.split())


def _named(pattern: re.Pattern[str], text: str) -> set[str]:
    drivers = set(_drivers())
    return {name.lower() for name in pattern.findall(_flat(text))} & drivers


def _description(page: str) -> str:
    match = re.search(r'^description: "(.*)"$', page, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_doctor_marks_exactly_these_drivers_experimental() -> None:
    marked = {name for name in _drivers() if _status(name) == "experimental"}
    assert marked == EXPERIMENTAL


def test_the_driver_table_gives_each_driver_the_status_doctor_reports(repo_root: Path) -> None:
    text = (repo_root / "docs" / "guides" / "index.md").read_text(encoding="utf-8")
    shown = {
        match.group(1): match.group(2)
        for line in text.splitlines()
        if (match := STATUS_ROW.match(line))
    }
    assert shown == {
        name: "experimental" if name in EXPERIMENTAL else "tested" for name in _drivers()
    }


def test_a_driver_guide_calls_the_driver_experimental_exactly_when_doctor_does(
    repo_root: Path,
) -> None:
    wrong = []
    for name in _drivers():
        page = (repo_root / "docs" / "guides" / f"{name}.md").read_text(encoding="utf-8")
        experimental = name in EXPERIMENTAL
        if ("experimental" in _description(page).lower()) is not experimental:
            wrong.append(f"{name}: description")
        if ("> **Experimental.**" in page) is not experimental:
            wrong.append(f"{name}: banner")
        if ("experimental" in page.lower()) is not experimental:
            wrong.append(f"{name}: page")
    assert wrong == []


def test_the_changelog_marks_exactly_the_experimental_drivers(repo_root: Path) -> None:
    text = (repo_root / "docs" / "changelog.md").read_text(encoding="utf-8")
    assert _named(MARKED, text) == EXPERIMENTAL


def test_no_page_calls_a_driver_experimental_that_doctor_reports_ok(
    repo_root: Path, kit: Any
) -> None:
    called = {}
    for path in kit.documents(repo_root):
        text = path.read_text(encoding="utf-8")
        named = (_named(MARKED, text) | _named(CALLED, text)) - EXPERIMENTAL
        if named:
            called[path.relative_to(repo_root).as_posix()] = sorted(named)
    assert called == {}


def test_a_driver_docstring_calls_the_driver_experimental_exactly_when_doctor_does() -> None:
    wrong = []
    for name in _drivers():
        module = inspect.getmodule(type(registry.driver(name)))
        assert module is not None
        experimental = "experimental" in (module.__doc__ or "").lower()
        if experimental is not (name in EXPERIMENTAL):
            wrong.append(name)
    assert wrong == []


def test_the_fixtures_listed_as_from_an_upstream_sample_are_synthetic(repo_root: Path) -> None:
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = text.split(UPSTREAM, 1)[1].split("\n## ", 1)[0]
    listed = re.findall(r"^\| `(tests/fixtures/[^`]+)` \|", section, re.MULTILINE)
    assert listed
    real = []
    for pattern in listed:
        files = [p for p in sorted(repo_root.glob(pattern)) if not p.name.endswith(SIDECAR)]
        assert files, pattern
        for path in files:
            sidecar = path.with_name(path.name + SIDECAR)
            if not json.loads(sidecar.read_text(encoding="utf-8"))["synthetic"]:
                real.append(path.relative_to(repo_root).as_posix())
    assert real == []
