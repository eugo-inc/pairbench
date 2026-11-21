# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The markdown report: the table, the further sections, escaping and what it never shows."""

from __future__ import annotations

import copy
from typing import Any

import pairbench
from pairbench import registry
from pairbench.api import ReportOptions
from pairbench.model import Diagnostics, Results
from pairbench.report.markdown import MarkdownReporter, md

A64 = "a" * 64
B64 = "b" * 64

# The markdown report of the example results document of the format.
EXAMPLE_MARKDOWN = (
    "\n".join(
        [
            "# pairbench results",
            "",
            "## new against old (baseline)",
            "",
            "| case | new | old | change | noise | p | verdict |",
            "|---|---|---|---|---|---|---|",
            "| matmul | 1.92 s | 2.41 s | 1.25x faster | ±1.8% | 0.0010\\* | FASTER |",
            "",
            "- Exact two-sided sign test over 16 paired rounds.",
            "- \\* corrected for testing 2 cases at once.",
            "- Rule: strict.",
            "- Machine state: quiet.",
            "- Baseline: old.",
            "- Positive control old\\~twice: ok.",
            "",
            "## Sides",
            "",
            "| side | role | kind | identity | fingerprint |",
            "|---|---|---|---|---|",
            f"| new | subject | image | image ID sha256:{A64}; digests sha256:{B64} | {A64} |",
            "",
            "## Same against same",
            "",
            "| side | case | ratio | floor | p | rounds |",
            "|---|---|---|---|---|---|",
            "| new | matmul | 1.00x | 0.4% | 0.80 | 16 |",
            "",
            "## Positive control",
            "",
            "OK: entry old\\~twice, the work run twice in one start (repeat); "
            "tolerance ±10.0% of the expected value.",
            "",
            "| case | expected | read | p | rounds | passed |",
            "|---|---|---|---|---|---|",
            "| matmul | 2.00x | 2.01x | 3.0e-05 | 16 | yes |",
            "",
            "## Cost of a launch",
            "",
            "Median 0.000500 s over 20 launches of the empty command true; first to third "
            "quartile 0.000400 s to 0.000700 s, least 0.000300 s. It is an upper bound on what "
            "the tool adds to a wall value of a command side.",
            "",
            "## All rounds and without disturbed rounds",
            "",
            "| case | subject | all rounds | without disturbed rounds | rounds set aside |",
            "|---|---|---|---|---|",
            "| matmul | new | 0.80x FASTER | 0.80x FASTER | none |",
            "",
            "## Resource comparisons",
            "",
            "No resource figure was recorded.",
            "",
            "## Diagnostics and report page",
            "",
            "- Explain step: written.",
            "- Diagnostics: diagnostics.json. It holds names from the user's code and is not "
            "part of this file.",
            "- Charts: drawn.",
            "- Report page: report.html.",
            "",
            "## Refusals and notes",
            "",
            "- Refused, E\\_GRID (experiment): a made-up refusal",
            "",
            "## How to reproduce",
            "",
            "```",
            "pairbench run --side new=image:<hidden> --side old=image:<hidden> -- bench.py",
            "```",
            "",
            "- Tool: pairbench 0.1.0.",
            f"- Config hash: {B64}.",
            "- Machine: Linux 0.0, arch-a, cpu-model-a.",
            "- GPU: gpu-model-a, driver 0.0.",
            "- Engine: docker 0.0.",
            "- Rounds: 16 completed of 16 planned, warm-up launches per side: 1, "
            "launches in all: 82.",
        ]
    )
    + "\n"
)

# The section headings of the markdown report, in their order.
SECTIONS = [
    "## Sides",
    "## Same against same",
    "## Positive control",
    "## Cost of a launch",
    "## All rounds and without disturbed rounds",
    "## Resource comparisons",
    "## Diagnostics and report page",
    "## Refusals and notes",
    "## How to reproduce",
]

RESOURCE = {
    "case": "res/cores",
    "primary": False,
    "subject_median": 7.8,
    "baseline_median": 1.0,
    "ratio": 7.8,
    "statistic": 7.8,
    "p_raw": 0.0005,
    "p_corrected": None,
    "verdict": "HIGHER",
    "outcome": "higher",
    "sensitivity": {"rounds_set_aside": [], "ratio": 7.8, "outcome": "higher", "agrees": True},
}
LOWER = {
    **RESOURCE,
    "case": "res/rss_peak",
    "subject_median": 500.0,
    "baseline_median": 1000.0,
    "ratio": 0.5,
    "statistic": 0.5,
    "verdict": "LOWER",
    "outcome": "lower",
    "sensitivity": {"rounds_set_aside": [], "ratio": 0.5, "outcome": "lower", "agrees": True},
}
RESOURCE_CASES = (
    ("res/cores", "cores", "none", "other", False),
    ("res/rss_peak", "bytes", "none", "other", False),
)


def markdown(results: Results, **options: Any) -> str:
    return pairbench.render(results, "markdown", options=ReportOptions(**options))


def section(text: str, heading: str) -> list[str]:
    """Return the lines of one section, from its heading to the next heading of its level or
    a higher one."""
    lines = text.splitlines()
    start = lines.index(heading)
    level = len(heading) - len(heading.lstrip("#"))

    def ends(line: str) -> bool:
        marks = len(line) - len(line.lstrip("#"))
        return 0 < marks <= level and line[marks:].startswith(" ")

    end = next((i for i in range(start + 1, len(lines)) if ends(lines[i])), len(lines))
    return lines[start:end]


def test_the_example_document(example_results: dict[str, Any]) -> None:
    assert markdown(Results.from_json(example_results)) == EXAMPLE_MARKDOWN


def test_the_sections_come_in_order(example_results_every_key: dict[str, Any]) -> None:
    text = markdown(Results.from_json(example_results_every_key))
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## new against old (baseline)", *SECTIONS]


def test_texts_from_a_run_are_escaped(build: Any) -> None:
    name = "<b>a|b</b>*_~`[x]"
    results = build(comparisons=[{"case": name}], cases=((name, "s", "lower", "time", True),))
    text = markdown(results)
    assert "| \\<b\\>a\\|b\\</b\\>\\*\\_\\~\\`\\[x\\] | 1.92 s |" in text
    assert "<b>" not in text
    assert md("a\nb  c") == "a b c"


def test_control_characters_from_a_run_are_shown_as_question_marks(
    build: Any, example_results: dict[str, Any]
) -> None:
    name = "a\x1b[2Jb\x00c\x07d"
    run = {**example_results["run"], "command": "pairbench run -- echo \x1b[31mred"}
    notes = [{"code": "explain_failed", "message": "a made-up \x1b]0;title\x07 note"}]
    results = build(
        comparisons=[{"case": name}],
        cases=((name, "s", "lower", "time", True),),
        notes=notes,
        run=run,
    )
    text = markdown(results)
    for control in ("\x1b", "\x00", "\x07"):
        assert control not in text
    assert "| a?\\[2Jb?c?d | 1.92 s |" in text
    assert "- Note explain\\_failed: a made-up ?\\]0;title? note" in text
    assert "pairbench run -- echo ?[31mred" in text


def test_the_command_is_the_recorded_command_as_it_stands(
    build: Any, example_results: dict[str, Any]
) -> None:
    # A command as the analysis records it: hosts hidden, paths cut, and the image
    # reference of a side kept whole, as report.include_image_refs asks. Cleaning it again
    # would cut the path of that reference to new.tar.
    command = (
        "pairbench run --side 'new=image:oci-archive:/made/up/new.tar' "
        "-- curl 'https://<hidden>/api/t/x' 'https://<hidden>/q?x=1' "
        "'postgres://<hidden>@<hidden>/db' 'BM_Vec<int>/8'"
    )
    run = {**example_results["run"], "command": command}
    rows = section(markdown(build(run=run)), "## How to reproduce")
    assert rows[2:5] == ["```", command, "```"]


def test_same_against_same_floors_in_percent_are_shown_as_they_are(
    build: Any, example_results: dict[str, Any]
) -> None:
    rows = [{**example_results["same_vs_same"][0], "floor": 0.4, "unit": "percent"}]
    lines = section(markdown(build(same_vs_same=rows)), "## Same against same")
    assert lines[4] == "| new | matmul | 1.00x | 0.4% | 0.80 | 16 |"


def test_the_charts_and_the_profiles_are_listed_by_name(
    build: Any, example_results: dict[str, Any]
) -> None:
    artifacts = {
        **example_results["artifacts"],
        "charts": ["charts/verdict.svg"],
        "profiles": ["profiles/new.flame.svg"],
    }
    rows = section(markdown(build(artifacts=artifacts)), "## Diagnostics and report page")
    assert rows[2:] == [
        "- Explain step: written.",
        "- Diagnostics: diagnostics.json. It holds names from the user's code and is not "
        "part of this file.",
        "- Charts: drawn.",
        "- Chart: charts/verdict.svg",
        "- Report page: report.html.",
        "- Profile: profiles/new.flame.svg",
        "",
    ]


def test_a_rule_that_grades_raw_p_values_shows_the_raw_p_of_every_table(build: Any) -> None:
    rule = {
        "name": "made-up-raw",
        "fields": {"name": "made-up-raw", "p_source": "raw"},
        "family_size": 2,
        "plain": "corrected for testing 2 cases at once",
    }
    primary = {**RESOURCE, "primary": True, "p_raw": 0.0003, "p_corrected": 0.0227}
    results = build(
        comparisons=[{"p_raw": 0.0003, "p_corrected": 0.0227}, primary],
        cases=RESOURCE_CASES,
        rule=rule,
    )
    text = markdown(results)
    rows = section(text, "## Resource comparisons")
    assert (
        "| res/cores | new | old | 7.80 cores | 1.00 cores | 7.80x higher | 0.00030 | HIGHER |"
        in (rows)
    )
    assert "0.023" not in text
    assert "* corrected for testing" not in text
    assert (
        "- No p-value is corrected: rule made-up-raw grades each case on its own p-value and "
        "does not correct for testing 2 cases at once, so a p-value here can be smaller than the "
        "corrected one, which results.json keeps as p\\_corrected.\n"
    ) in text


def test_the_resource_comparisons_say_higher_and_lower(build: Any) -> None:
    results = build(comparisons=[{}, RESOURCE, LOWER], cases=RESOURCE_CASES)
    rows = section(markdown(results), "## Resource comparisons")
    assert rows[2:] == [
        "| case | subject | baseline | subject median | baseline median | change | p | verdict |",
        "|---|---|---|---|---|---|---|---|",
        "| res/cores | new | old | 7.80 cores | 1.00 cores | 7.80x higher | 0.00050 | HIGHER |",
        "| res/rss\\_peak | new | old | 500 bytes | 1000 bytes | 2.00x lower | 0.00050 | LOWER |",
        "",
    ]
    # The verdict table shows them only with --all; the resource section always.
    assert "res/cores" not in section(markdown(results), "## new against old (baseline)")[0:8]


def test_a_failed_positive_control_lists_what_it_read(
    build: Any, example_results: dict[str, Any]
) -> None:
    controls = copy.deepcopy(example_results["controls"])
    controls["positive"].update(status="failed", via="factor")
    controls["positive"]["cases"][0].update(ratio=1.5, p_raw=0.0001, passed=False)
    notes = [{"code": "positive_control_failed", "message": "a made-up control note"}]
    rows = section(markdown(build(controls=controls, notes=notes)), "## Positive control")
    assert rows == [
        "## Positive control",
        "",
        "FAILED: entry old\\~twice, the work asked to double itself (factor); "
        "tolerance ±10.0% of the expected value.",
        "",
        "Every comparison of this run is NO VERDICT.",
        "",
        "| case | expected | read | p | rounds | passed |",
        "|---|---|---|---|---|---|",
        "| matmul | 2.00x | 1.50x | 0.00010 | 16 | no |",
        "",
        "- a made-up control note",
        "",
    ]


def test_a_control_that_did_not_run(build: Any) -> None:
    not_run = {
        "positive": {
            "status": "not_run",
            "entry": None,
            "via": "repeat",
            "tolerance": 0.1,
            "cases": [],
        }
    }
    notes = [{"code": "positive_control_cannot_repeat", "message": "a made-up reason"}]
    rows = section(markdown(build(controls=not_run, notes=notes)), "## Positive control")
    assert rows == ["## Positive control", "", "Not run.", "", "- a made-up reason", ""]


def test_a_launch_cost_that_was_not_measured_and_its_notes(build: Any) -> None:
    notes = [
        {"code": "launch_cost_not_measured", "message": "a made-up note on the cost"},
        {"code": "launch_cost_share", "message": "a made-up share note"},
    ]
    rows = section(markdown(build(launch_cost=None, notes=notes)), "## Cost of a launch")
    assert rows == [
        "## Cost of a launch",
        "",
        "Not measured.",
        "",
        "- a made-up note on the cost",
        "- a made-up share note",
        "",
    ]


def test_rounds_set_aside_beside_all_rounds(build: Any) -> None:
    disturbed = {
        "verdict": "UNRESOLVED",
        "outcome": "unresolved",
        "reason": "sensitive_to_disturbed_rounds",
        "reasons": ["sensitive_to_disturbed_rounds"],
        "sensitivity": {
            "rounds_set_aside": [3, 4],
            "ratio": 0.99,
            "outcome": "tie",
            "agrees": False,
        },
    }
    rows = section(
        markdown(build(comparisons=[disturbed])), "## All rounds and without disturbed rounds"
    )
    assert rows[4] == "| matmul | new | 0.80x UNRESOLVED | 0.99x TIE | 3, 4 |"


def test_the_states_of_the_explain_step_and_the_charts(build: Any) -> None:
    results = build(
        diagnostics={"status": "skipped", "reason": "mode_auto_no_difference"},
        plots={"status": "not_drawn", "reason": "extra_missing"},
        artifacts={
            "capture": "capture.jsonl",
            "markdown": "results.md",
            "plan": None,
            "charts": [],
            "profiles": [],
        },
    )
    rows = section(markdown(results), "## Diagnostics and report page")
    assert rows == [
        "## Diagnostics and report page",
        "",
        "- Explain step: skipped, no primary case came out better or worse.",
        "- Charts: not drawn, the optional extra plot is not installed.",
        "",
    ]


def test_findings_are_those_from_resource_figures_and_counters(
    build: Any, diagnostics: Diagnostics
) -> None:
    text = markdown(build(), diagnostics=diagnostics)
    assert section(text, "### Findings from resource figures and counters") == [
        "### Findings from resource figures and counters",
        "",
        "- new used 7.8 cores against 1.0 for old (median of 20 rounds).",
        "- new counted 0.50x the instructions of old.",
        "",
        "The full diagnostics, with names from the user's code: diagnostics.json",
        "",
    ]
    for name in ("markerfunctionname", "libmarkerobject.so", "made_up_function", "libmade-up.so"):
        assert name not in text


def test_an_image_reference_column_only_when_a_side_has_one(
    example_results_every_key: dict[str, Any],
) -> None:
    rows = section(markdown(Results.from_json(example_results_every_key)), "## Sides")
    assert rows[2] == "| side | role | kind | image | identity | fingerprint |"
    assert rows[4].startswith("| new | subject | image | registry.example/org/app:2.0 | image ID ")


def test_the_command_is_fenced_longer_than_any_backtick_run_in_it(
    build: Any, example_results: dict[str, Any]
) -> None:
    run = {**example_results["run"], "command": "pairbench run -- sh -c 'echo ```x```'"}
    rows = section(markdown(build(run=run)), "## How to reproduce")
    assert rows[2:5] == ["````", "pairbench run -- sh -c 'echo ```x```'", "````"]


def test_a_command_that_was_not_recorded(build: Any, example_results: dict[str, Any]) -> None:
    run = {**example_results["run"], "command": None}
    rows = section(markdown(build(run=run)), "## How to reproduce")
    assert rows[2] == "The command line was not recorded."


def test_the_document_with_only_required_keys(
    example_results_required_only: dict[str, Any],
) -> None:
    text = markdown(Results.from_json(example_results_required_only))
    assert section(text, "## Cost of a launch")[2] == "Not measured."
    assert section(text, "## Positive control")[2] == "Not run."
    assert section(text, "## How to reproduce")[2] == "The command line was not recorded."


def test_a_document_without_comparisons(build: Any) -> None:
    text = markdown(build(comparisons=[]))
    assert text.splitlines()[2] == "No comparison to show."
    assert "- Exact two-sided sign test; no comparison to show." in text


def test_the_reporter_is_registered_under_its_name() -> None:
    reporter = registry.reporter("markdown")
    assert isinstance(reporter, MarkdownReporter)
    assert reporter.api_version == 1
