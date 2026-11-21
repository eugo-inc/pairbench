# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each check that did not pass is said once in every report.

Every check runs once before the locks and once at the short recheck after
them, and a pooled run holds the checks of each capture, so one entry of
``machine_state.degraded`` can come more than once. The terminal report, the
markdown report and the report page say each entry once, in the order first
seen. Entries of one check that differ in status or reason are each said.
"""

from __future__ import annotations

from typing import Any

import pytest

import pairbench
from pairbench.api import ReportOptions
from pairbench.model import Degraded

ENGINE = {
    "name": "census",
    "status": "unavailable",
    "message": "no container engine could be reached",
}
QUIET_ONE = {"name": "quiet", "status": "fail", "message": "a made-up first reading"}
QUIET_TWO = {"name": "quiet", "status": "fail", "message": "a made-up second reading"}
PLUGIN_ONE = {"name": "plugin", "status": "degraded", "message": "a made-up plug-in reason"}
PLUGIN_TWO = {"name": "plugin", "status": "unavailable", "message": "another made-up reason"}
ENGINE_DEGRADED = {
    "name": "census",
    "status": "degraded",
    "message": "no container engine could be reached",
}

# How each report writes one entry: the terminal and markdown reports in a
# footer sentence, the page in a fact.
TERMINAL = "Check {name}: {status} ({message})."
MARKDOWN = "- Check {name}: {status} ({message})."
PAGE = "Check {name}: {status}: {message}"

FORMS = (("terminal", TERMINAL), ("markdown", MARKDOWN), ("html", PAGE))

# The entries of machine_state.degraded, and the entries each report says, in order.
ROWS = (
    pytest.param([ENGINE, ENGINE], [ENGINE], id="the-same-entry-from-two-phases"),
    pytest.param(
        [ENGINE, ENGINE, ENGINE, ENGINE], [ENGINE], id="the-same-entry-from-two-pooled-captures"
    ),
    pytest.param(
        [QUIET_ONE, ENGINE, QUIET_TWO, ENGINE],
        [QUIET_ONE, ENGINE, QUIET_TWO],
        id="two-readings-of-one-check-are-both-said",
    ),
    pytest.param([PLUGIN_ONE, PLUGIN_TWO], [PLUGIN_ONE, PLUGIN_TWO], id="two-plug-in-checks"),
    pytest.param(
        [ENGINE, ENGINE_DEGRADED, ENGINE],
        [ENGINE, ENGINE_DEGRADED],
        id="one-check-with-two-statuses",
    ),
    pytest.param([ENGINE], [ENGINE], id="one-entry"),
    pytest.param([], [], id="no-entry"),
)


def _state(entries: list[dict[str, str]]) -> dict[str, Any]:
    return {"status": "unknown", "gates": [], "degraded": entries}


@pytest.mark.parametrize(("entries", "said"), ROWS)
def test_the_helper_gives_each_entry_once_in_the_order_first_seen(
    build: Any, entries: list[dict[str, str]], said: list[dict[str, str]]
) -> None:
    from pairbench.report import degraded_checks

    results = build(machine_state=_state(entries))

    assert degraded_checks(results) == tuple(Degraded.from_json(e) for e in said)


@pytest.mark.parametrize(("fmt", "form"), FORMS)
@pytest.mark.parametrize(("entries", "said"), ROWS)
def test_each_report_says_each_entry_once_in_the_order_first_seen(
    build: Any,
    fmt: Any,
    form: str,
    entries: list[dict[str, str]],
    said: list[dict[str, str]],
) -> None:
    results = build(machine_state=_state(entries))

    text = pairbench.render(results, fmt, options=ReportOptions())

    lines = [form.format(**e) for e in said]
    for line in lines:
        assert text.count(line) == 1, line
    assert [text.index(line) for line in lines] == sorted(text.index(line) for line in lines)
    assert text.count("Check ") == len(said)


def test_the_census_without_an_engine_is_one_exact_line_in_each_report(build: Any) -> None:
    results = build(machine_state=_state([ENGINE, ENGINE]))

    terminal = pairbench.render(results, "terminal").splitlines()
    markdown = pairbench.render(results, "markdown").splitlines()
    page = pairbench.render(results, "html")

    line = "Check census: unavailable (no container engine could be reached)."
    assert terminal.count(line) == 1
    assert markdown.count(f"- {line}") == 1
    assert page.count("Check census: unavailable: no container engine could be reached") == 1
