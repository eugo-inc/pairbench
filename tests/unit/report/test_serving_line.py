# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The report of a serving run says, beside its verdicts, how often its round count catches a
real difference. Every value of the documents is made up; the line comes from the data file."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from pairbench.api import ReportOptions
from pairbench.model import STRICT, Results, RuleInfo
from pairbench.page.html import render_page, text
from pairbench.report.markdown import markdown_text
from pairbench.report.terminal import terminal_text

from .conftest import Build

LINK = "https://eugo.io/docs/pairbench/latest/method/error-rates/"
LINE_AT_8_ROUNDS = (
    "Real differences caught at 8 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 33 to 39 percent of the time (about one metric in three), four times the "
    "noise 92 to 98 percent of the time; with --rounds 16, twice the noise is caught 83 to 88 "
    "percent of the time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction "
    f"appears in the simulated experiments ({LINK})."
)
LINE_AT_16_ROUNDS = (
    "Real differences caught at 16 rounds with 4 primary cases: a true difference of twice the "
    "noise is caught 83 to 88 percent of the time, four times the noise 100 percent of the "
    "time; a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction appears in "
    f"the simulated experiments ({LINK})."
)
CASES = ("c32/ttft_ms_median", "c32/itl_ms_median", "c32/output_tokens_per_s", "c32/other_ms")
FINGERPRINT = "0" * 64


def _side(name: str, role: str, twin_of: str | None = None, kind: str = "serve") -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "role": role,
        "twin_of": twin_of,
        "control_of": None,
        "identity": {},
        "fingerprint": FINGERPRINT,
    }


def _sides(kind: str = "serve") -> list[dict[str, Any]]:
    return [
        _side("new", "subject", kind=kind),
        _side("new~same", "twin", "new", kind=kind),
        _side("old", "baseline", kind=kind),
        _side("old~same", "twin", "old", kind=kind),
    ]


def _serving_run(
    build: Build,
    *,
    rounds: int = 8,
    cases: tuple[str, ...] = CASES,
    kind: str = "serve",
    secondary: tuple[str, ...] = (),
) -> Any:
    comparisons = [
        {"case": case, "n_rounds": rounds, "verdict": "TIE", "outcome": "tie"} for case in cases
    ]
    comparisons += [
        {"case": case, "primary": False, "n_rounds": rounds, "verdict": "TIE", "outcome": "tie"}
        for case in secondary
    ]
    records = tuple((case, "ms", "lower", "time", True) for case in cases)
    records += tuple((case, "ms", "lower", "time", False) for case in secondary)
    return build(comparisons=comparisons, cases=records, sides=_sides(kind))


def test_the_terminal_report_of_a_serving_run_says_what_8_rounds_catch(build: Build) -> None:
    lines = terminal_text(_serving_run(build), ReportOptions()).splitlines()
    test = lines.index("Exact two-sided sign test over 8 paired rounds.")
    assert lines[test + 1] == LINE_AT_8_ROUNDS
    assert lines.count(LINE_AT_8_ROUNDS) == 1


def test_the_terminal_report_of_a_serving_run_says_what_16_rounds_catch(build: Build) -> None:
    lines = terminal_text(_serving_run(build, rounds=16), ReportOptions()).splitlines()
    test = lines.index("Exact two-sided sign test over 16 paired rounds.")
    assert lines[test + 1] == LINE_AT_16_ROUNDS


def test_the_markdown_report_of_a_serving_run_holds_the_line_beside_its_verdicts(
    build: Build,
) -> None:
    lines = markdown_text(_serving_run(build), ReportOptions()).splitlines()
    test = lines.index("- Exact two-sided sign test over 8 paired rounds.")
    assert lines[test + 1] == f"- {LINE_AT_8_ROUNDS}"


def test_the_report_page_of_a_serving_run_holds_the_line(build: Build) -> None:
    page = render_page(_serving_run(build), ReportOptions())
    assert f"<li>{text(LINE_AT_8_ROUNDS)}</li>" in page


def test_the_line_counts_the_primary_cases_of_the_run_and_not_the_shown_ones(
    build: Build,
) -> None:
    results = _serving_run(build, secondary=("c32/requests_per_s",))
    shown = terminal_text(results, ReportOptions(cases=("c32/ttft_ms_median",), all_cases=True))
    assert LINE_AT_8_ROUNDS in shown.splitlines()


def test_a_board_without_a_row_on_the_page_is_said_in_the_report(build: Build) -> None:
    text = terminal_text(_serving_run(build, cases=CASES[:3]), ReportOptions())
    assert (
        "Real differences caught at 8 rounds with 3 primary cases: the error-rate page has no "
        "row for 3 primary cases; for the numbers of primary cases it has, a true difference of "
        "twice the noise is caught 41 to 51 percent with 1, 33 to 39 percent with 4, none with "
        "10 (too few rounds); four times the noise 93 to 98 percent with 1, 92 to 98 percent with "
        "4, none with 10 (too few rounds); a miss reads TIE or UNRESOLVED, and no verdict in the "
        f"wrong direction appears in the simulated experiments ({LINK})."
    ) in text.splitlines()


def test_the_default_rule_with_every_field_recorded_keeps_the_line(build: Build) -> None:
    recorded = RuleInfo(
        name=STRICT.name,
        fields=STRICT.to_json(),
        family_size=4,
        plain="corrected for testing 4 cases at once",
    )
    results = dataclasses.replace(_serving_run(build), rule=recorded)
    read_back = Results.from_json(json.loads(json.dumps(results.to_json())))
    for each in (results, read_back):
        assert LINE_AT_8_ROUNDS in terminal_text(each, ReportOptions()).splitlines()


def test_a_rule_named_strict_with_other_settings_has_no_row_in_the_report(build: Build) -> None:
    changed = RuleInfo(
        name="strict",
        fields={"name": "strict", "alpha": 0.1},
        family_size=4,
        plain="corrected for testing 4 cases at once",
    )
    results = dataclasses.replace(_serving_run(build), rule=changed)
    text = terminal_text(results, ReportOptions())
    assert (
        "Real differences caught at 8 rounds: the error-rate page simulates the rule strict and "
        f"has no row for the rule strict with other settings ({LINK})."
    ) in text.splitlines()


def test_a_run_that_is_not_serving_has_no_odds_line(build: Build) -> None:
    for report in (
        terminal_text(_serving_run(build, kind="image"), ReportOptions()),
        markdown_text(_serving_run(build, kind="image"), ReportOptions()),
        render_page(_serving_run(build, kind="image"), ReportOptions()),
    ):
        assert "Real differences caught" not in report


def test_a_serving_run_without_a_primary_comparison_has_no_odds_line(build: Build) -> None:
    results = _serving_run(build, cases=(), secondary=("c32/requests_per_s",))
    assert "Real differences caught" not in terminal_text(results, ReportOptions(all_cases=True))
