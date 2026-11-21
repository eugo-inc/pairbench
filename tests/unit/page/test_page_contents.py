# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the report page holds, in which order, with and without charts and diagnostics."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import ReportOptions
from pairbench.model import Diagnostics, Results
from pairbench.page.html import HOW_TO_DRAW, HtmlReporter, render_page

SECTIONS = [
    "Verdict",
    "Controls",
    "Charts",
    "Diagnostics",
    "Flame graphs",
    "Same against same",
    "Refusals and notes",
    "How to reproduce",
]


def headings(page: str) -> list[str]:
    return re.findall(r"<h2>([^<]*)</h2>", page)


def cells(page: str) -> list[list[str]]:
    """Return the cells of every table row of a page, as written."""
    return [
        re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row)
        for row in re.findall(r"<tr>(.*?)</tr>", page, flags=re.DOTALL)
    ]


def test_the_page_is_the_reporter_named_html() -> None:
    reporter = registry.reporter("html")
    assert isinstance(reporter, HtmlReporter)
    assert (reporter.name, reporter.api_version) == ("html", 1)


def test_the_public_render_gives_the_page_with_what_it_was_handed(
    page_document: dict[str, Any], example_diagnostics: dict[str, Any], tmp_path: Path
) -> None:
    results = Results.from_json(page_document)
    document = Diagnostics.from_json(example_diagnostics)
    page = pairbench.render(results, "html", diagnostics=document, folder=tmp_path)
    assert page == render_page(results, ReportOptions(diagnostics=document, folder=tmp_path))
    assert page == render_page(results, ReportOptions(diagnostics=document, folder=tmp_path))


def test_the_contents_come_in_their_fixed_order(
    page_document: dict[str, Any], example_diagnostics: dict[str, Any]
) -> None:
    results = Results.from_json(page_document)
    for options in (
        ReportOptions(),
        ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics)),
    ):
        page = render_page(results, options)
        assert headings(page) == SECTIONS
        positions = [page.index(f"<h2>{name}</h2>") for name in SECTIONS]
        assert positions == sorted(positions)
        assert page.startswith("<!DOCTYPE html>\n")
        assert page.endswith("</html>\n")


def test_the_verdict_table_shows_each_primary_case_against_the_baseline(
    page_document: dict[str, Any],
) -> None:
    page = render_page(Results.from_json(page_document), ReportOptions())
    assert "<h3>new against old</h3>" in page
    assert ["case", "new median", "old median", "change", "noise", "p", "verdict"] in cells(page)
    assert [
        "matmul",
        "1.92 s",
        "2.41 s",
        "1.25x faster",
        "±1.8%",
        "0.0010*",
        "FASTER",
    ] in cells(page)
    verdict = page[page.index("<h2>Verdict</h2>") : page.index("<h2>Controls</h2>")]
    assert not any(row[:1] == ["res/cores"] for row in cells(verdict))
    assert "Secondary cases are shown with --all." in page


def test_the_footer_facts_are_always_there(page_document: dict[str, Any]) -> None:
    page_document["machine_state"]["degraded"] = [
        {"name": "census", "status": "unavailable", "message": "a made-up reason"}
    ]
    page_document["notes"] = [
        {"code": "floor_provisional", "message": "a made-up floor note"},
        {"code": "launch_cost_share", "message": "a made-up launch-cost note"},
        {"code": "unbalanced", "message": "a made-up other note"},
    ]
    page = render_page(Results.from_json(page_document), ReportOptions())
    footer = page[page.index("Test: the sign test") : page.index("<h3>Sides</h3>")]
    for fact in (
        "Test: the sign test on 16 paired rounds.",
        "* p is corrected: corrected for testing 2 cases at once.",
        "Rule: strict.",
        "Machine state: quiet.",
        "Baseline: old.",
        "Positive control: ok.",
        "Check census: unavailable: a made-up reason",
        "a made-up floor note",
        "a made-up launch-cost note",
        "Rounds: 16 completed of 16 planned; 82 launches.",
    ):
        assert fact in footer, fact
    assert "a made-up other note" not in footer


def test_a_time_case_where_higher_is_better_moves_lower_not_faster(
    page_document: dict[str, Any],
) -> None:
    for case in page_document["cases"]:
        if case["id"] == "matmul":
            case["better"] = "higher"
    page = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[3] == "1.25x lower"


def test_a_rule_that_grades_raw_p_values_shows_the_raw_p_without_a_star(
    page_document: dict[str, Any],
) -> None:
    page_document["rule"] = {
        "name": "made-up-raw",
        "fields": {"name": "made-up-raw", "p_source": "raw"},
        "family_size": 2,
        "plain": "corrected for testing 2 cases at once",
    }
    for comparison in page_document["comparisons"]:
        if comparison["case"] == "matmul":
            comparison.update(p_raw=0.0003, p_corrected=0.0227)
    page_document["figures"].pop("matmul.new_vs_old.p", None)
    page = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[5] == "0.00030"
    assert "* p is corrected" not in page
    assert (
        "No p-value is corrected: rule made-up-raw grades each case on its own p-value and does "
        "not correct for testing 2 cases at once, so a p-value here can be smaller than the "
        "corrected one, which results.json keeps as p_corrected."
    ) in page


def test_a_figure_text_of_the_results_is_shown_as_it_is(page_document: dict[str, Any]) -> None:
    page_document["figures"]["matmul.new_vs_old.bar"] = {"value": 0.0991, "text": "±9.9%"}
    page_document["figures"]["matmul.new.median"] = {"value": 1.92, "text": "1.9200 s"}
    page = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    assert row == ["matmul", "1.9200 s", "2.41 s", "1.25x faster", "±9.9%", "0.0010*", "FASTER"]


def test_a_comparison_without_a_verdict_shows_the_reason_in_words(
    page_document: dict[str, Any],
) -> None:
    page_document["comparisons"][0].update(
        verdict="NO VERDICT",
        outcome="no_verdict",
        reason="nonpositive_value",
        reasons=["nonpositive_value"],
        p_corrected=None,
    )
    page = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[-2:] == ["no p-value", "NO VERDICT &#40;a value of zero or less was recorded)"]


def test_medians_too_far_apart_are_named_in_the_reason_on_the_page(
    page_document: dict[str, Any],
) -> None:
    page_document["comparisons"][0].update(
        verdict="NO VERDICT",
        outcome="no_verdict",
        reason="too_far_apart",
        reasons=["too_far_apart"],
        subject_median=1e300,
        baseline_median=1e-10,
        ratio=None,
        statistic=None,
        gap=None,
        bar=None,
    )
    page = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[-1] == (
        "NO VERDICT &#40;the medians 1e+300 and 1e-10 are too far apart for their ratio to be "
        "a finite number)"
    )


def test_the_display_options_filter_what_is_shown(page_document: dict[str, Any]) -> None:
    results = Results.from_json(page_document)
    every = render_page(results, ReportOptions(all_cases=True))
    assert any(r[:1] == ["res/cores"] and len(r) == 7 for r in cells(every))
    assert "Secondary cases are shown with --all." not in every
    none = render_page(results, ReportOptions(cases=("conv*",)))
    assert "No comparison is shown." in none
    verbose = render_page(results, ReportOptions(verbose=True))
    assert [
        "case",
        "new median",
        "old median",
        "change",
        "noise",
        "p",
        "verdict",
        "new floor",
        "old floor",
    ] in cells(verbose)
    row = next(r for r in cells(verbose) if r[:1] == ["matmul"] and len(r) == 9)
    assert row[-2:] == ["1.1%", "0.7%"]


def test_the_controls_show_the_positive_control_the_launch_cost_and_the_environment(
    page_document: dict[str, Any],
) -> None:
    page = render_page(Results.from_json(page_document), ReportOptions())
    controls = page[page.index("<h2>Controls</h2>") : page.index("<h2>Charts</h2>")]
    assert (
        "State: ok; entry old~twice, made by repeat; tolerance ±10.0% of the expected ratio."
        in controls
    )
    assert ["matmul", "2.00x", "2.01x", "3.0e-05", "16", "yes"] in cells(controls)
    assert (
        "Median 0.000500 s, spread 0.000300 s &#40;third quartile less the first), from 20 "
        "launches of the empty command true."
    ) in controls
    assert "The size of the environment was not varied." in controls
    del page_document["launch_cost"]
    page_document["env_pad"] = {"varied": True, "min": 0, "max": 4096}
    again = render_page(Results.from_json(page_document), ReportOptions())
    assert "The cost of a launch was not measured in this run." in again
    assert (
        "The size of the environment was varied from round to round, from 0 to 4096 bytes." in again
    )


def test_without_charts_the_page_exists_and_says_how_to_get_them(
    page_document: dict[str, Any],
) -> None:
    page_document["plots"] = {"status": "not_drawn", "reason": "extra_missing"}
    page = render_page(Results.from_json(page_document), ReportOptions())
    charts = page[page.index("<h2>Charts</h2>") : page.index("<h2>Diagnostics</h2>")]
    assert (
        "Charts were not drawn: the plot extra is not installed. To draw the charts, install "
        "pairbench[plot] and run pairbench report --plots on in the run folder."
    ) in charts
    assert HOW_TO_DRAW == (
        "To draw the charts, install pairbench[plot] and run pairbench report --plots on "
        "in the run folder."
    )
    assert "<img" not in page
    assert ["matmul", "1.92 s", "2.41 s", "1.25x faster", "±1.8%", "0.0010*", "FASTER"] in cells(
        page
    )


def test_each_state_of_the_charts_is_said_in_words(page_document: dict[str, Any]) -> None:
    how = (
        " To draw the charts, install pairbench[plot] and run pairbench report --plots on in "
        "the run folder."
    )
    expected = {
        ("off", None): "Charts were turned off for this run." + how,
        ("not_drawn", "failed"): "Charts were not drawn: drawing them failed &#40;see the notes)."
        + how,
        ("interrupted", None): "Drawing the charts was interrupted." + how,
        ("pending", None): "Charts had not been drawn when these results were written." + how,
        ("drawn", None): "No chart had data to draw &#40;see the notes)." + how,
    }
    for (status, reason), words in expected.items():
        page_document["plots"] = {"status": status, "reason": reason}
        page = render_page(Results.from_json(page_document), ReportOptions())
        assert words in page, status


def test_charts_listed_but_not_reachable_are_named(
    with_files: dict[str, Any], tmp_path: Path
) -> None:
    results = Results.from_json(with_files)
    without_folder = render_page(results, ReportOptions())
    assert (
        "The charts of this run are files in the run folder: charts/verdict.svg, "
        "charts/rounds.matmul.svg. This page was made without the run folder; pairbench "
        "report --format html in the run folder embeds them."
    ) in without_folder
    empty_folder = render_page(results, ReportOptions(folder=tmp_path))
    assert "Chart charts/verdict.svg is not shown: it is missing." in empty_folder
    assert "Chart charts/rounds.matmul.svg is not shown: it is missing." in empty_folder
    assert (
        "To draw the charts again, run pairbench report --plots on in the run folder."
        in empty_folder
    )


def test_the_diagnostics_section_shows_the_document_when_given(
    page_document: dict[str, Any], example_diagnostics: dict[str, Any]
) -> None:
    results = Results.from_json(page_document)
    page = render_page(
        results, ReportOptions(diagnostics=Diagnostics.from_json(example_diagnostics))
    )
    section = page[page.index("<h2>Diagnostics</h2>") : page.index("<h2>Flame graphs</h2>")]
    assert ["res/cores", "new", "8.00 cores", "old", "1.00 cores", "HIGHER"] in cells(section)
    assert "new used 7.8 cores against 1.0 for old &#40;median of 20 rounds)." in section
    assert [
        "stacks",
        "old",
        "skipped",
        "the system does not permit it: the kernel setting perf_event_paranoid forbids it",
        "",
    ] in cells(section)
    assert ["instructions", "new", "1000", "old", "2000", "0.50x"] in cells(section)
    assert ["made_up_function", "libmade-up.so", "25.0%"] in cells(section)
    assert ["libmade-up.so", "50.0%"] in cells(section)
    assert ["new", "libmade-up.so"] in cells(section)
    assert ["libother-made-up.so", "new: aa11; old: bb22"] in cells(section)


def test_without_the_document_the_diagnostics_section_says_where_it_is(
    page_document: dict[str, Any],
) -> None:
    page = render_page(Results.from_json(page_document), ReportOptions())
    section = page[page.index("<h2>Diagnostics</h2>") : page.index("<h2>Flame graphs</h2>")]
    assert ["res/cores", "new", "8.00 cores", "old", "1.00 cores", "HIGHER"] in cells(section)
    assert (
        "The explain step wrote the diagnostics document. It is not part of this page; it is "
        "diagnostics.json in the run folder."
    ) in section
    page_document["diagnostics"] = {"status": "skipped", "reason": "mode_auto_no_difference"}
    skipped = render_page(Results.from_json(page_document), ReportOptions())
    assert (
        "The explain step was skipped: under explain mode auto it runs only when a primary "
        "case came out better or worse."
    ) in skipped


def test_the_same_against_same_rows_name_each_twin(page_document: dict[str, Any]) -> None:
    page = render_page(Results.from_json(page_document), ReportOptions())
    assert ["new", "new~same", "matmul", "1.004x", "0.4%", "0.80", "16"] in cells(page)
    page_document["same_vs_same"] = []
    assert "This run had no twins." in render_page(
        Results.from_json(page_document), ReportOptions()
    )


def test_far_out_numbers_on_the_page_have_the_short_form(page_document: dict[str, Any]) -> None:
    page_document["same_vs_same"][0]["ratio"] = 0.0004
    page_document["comparisons"][0].update(subject_median=1e300, baseline_median=1e-10)
    page = render_page(Results.from_json(page_document), ReportOptions())
    assert ["new", "new~same", "matmul", "0.0004x", "0.4%", "0.80", "16"] in cells(page)
    assert "1.00e+300 s" in page
    assert "1.00e-10 s" in page
    assert "0000000000" not in page


def test_refusals_notes_and_how_to_reproduce(page_document: dict[str, Any]) -> None:
    page_document["notes"] = [{"code": "unbalanced", "message": "a made-up note"}]
    page = render_page(Results.from_json(page_document), ReportOptions())
    assert ["E_GRID", "experiment", "a made-up refusal"] in cells(page)
    assert "<li>unbalanced: a made-up note</li>" in page
    reproduce = page[page.index("<h2>How to reproduce</h2>") :]
    assert (
        "<p>Command: <code>pairbench run --side new&#61;image:&lt;hidden&gt; --side "
        "old&#61;image:&lt;hidden&gt; -- bench.py</code></p>"
    ) in reproduce
    assert f"Config hash: {'b' * 64}." in reproduce
    assert ["cap-000001", "a" * 64, "16"] in cells(reproduce)
    assert "<li>diagnostics document: diagnostics.json</li>" in reproduce


def _secondary_board(page_document: dict[str, Any]) -> dict[str, Any]:
    """The page document with matmul made a secondary case graded on its uncorrected p."""
    for case in page_document["cases"]:
        if case["id"] == "matmul":
            case["primary"] = False
    for comparison in page_document["comparisons"]:
        if comparison["case"] == "matmul":
            comparison.update(primary=False, p_raw=0.0003, p_corrected=None)
    page_document["figures"].pop("matmul.new_vs_old.p", None)
    page_document["figures"].pop("matmul.new_vs_old.p_corrected", None)
    return page_document


def _markdown_row(markdown: str, case: str) -> list[str]:
    for line in markdown.splitlines():
        row = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if row[:1] == [case]:
            return row
    raise AssertionError(f"no markdown row for {case}")


def test_a_secondary_row_shows_the_p_value_it_was_graded_on_as_results_md_does(
    page_document: dict[str, Any],
) -> None:
    results = Results.from_json(_secondary_board(page_document))
    page = render_page(results, ReportOptions(all_cases=True))
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    markdown = pairbench.render(results, "markdown", options=ReportOptions(all_cases=True))
    assert row[5] == "0.00030"
    assert row[5] == _markdown_row(markdown, "matmul")[5]
    footer = page[page.index("Test: the sign test") : page.index("<h3>Sides</h3>")]
    assert "A p-value without a star is uncorrected: the case is secondary." in footer


def test_the_secondary_sentence_is_left_out_when_every_row_shown_is_primary(
    page_document: dict[str, Any],
) -> None:
    page = render_page(Results.from_json(page_document), ReportOptions())
    assert "without a star" not in page


def test_a_reason_names_the_correction_only_where_the_row_shows_a_corrected_p(
    page_document: dict[str, Any],
) -> None:
    unresolved = {
        "verdict": "UNRESOLVED",
        "outcome": "unresolved",
        "reason": "not_significant",
        "reasons": ["not_significant"],
    }
    for comparison in page_document["comparisons"]:
        if comparison["case"] == "matmul":
            comparison.update(unresolved)
    primary = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(primary) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[-1] == (
        "UNRESOLVED &#40;the difference lies outside the noise but is not significant after "
        "the correction)"
    )
    secondary = render_page(
        Results.from_json(_secondary_board(page_document)), ReportOptions(all_cases=True)
    )
    row = next(r for r in cells(secondary) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[-1] == (
        "UNRESOLVED &#40;the difference lies outside the noise but is not significant)"
    )
    for case in page_document["cases"]:
        case["primary"] = case["id"] == "matmul"
    for comparison in page_document["comparisons"]:
        comparison["primary"] = comparison["case"] == "matmul"
    page_document["rule"] = {
        "name": "made-up-raw",
        "fields": {"name": "made-up-raw", "p_source": "raw"},
        "family_size": 1,
        "plain": "no correction",
    }
    raw = render_page(Results.from_json(page_document), ReportOptions())
    row = next(r for r in cells(raw) if r[:1] == ["matmul"] and len(r) == 7)
    assert row[-1] == (
        "UNRESOLVED &#40;the difference lies outside the noise but is not significant)"
    )


@pytest.mark.parametrize(
    ("verdict", "outcome", "reason", "words"),
    [
        (
            "UNRESOLVED",
            "unresolved",
            "not_significant",
            "the difference lies outside the noise but is not significant",
        ),
        (
            "UNRESOLVED",
            "unresolved",
            "inside_noise",
            "the difference is significant but lies inside the noise",
        ),
        ("NO VERDICT", "no_verdict", "too_few_rounds", "too few paired rounds for a verdict"),
        (
            "NO VERDICT",
            "no_verdict",
            "no_floor",
            "neither side has a twin, so there is no noise floor",
        ),
    ],
)
def test_a_secondary_row_gives_its_reason_in_the_words_of_results_md(
    page_document: dict[str, Any], verdict: str, outcome: str, reason: str, words: str
) -> None:
    board = _secondary_board(page_document)
    for comparison in board["comparisons"]:
        if comparison["case"] == "matmul":
            comparison.update(verdict=verdict, outcome=outcome, reason=reason, reasons=[reason])
    results = Results.from_json(board)
    page = render_page(results, ReportOptions(all_cases=True))
    row = next(r for r in cells(page) if r[:1] == ["matmul"] and len(r) == 7)
    markdown = pairbench.render(results, "markdown", options=ReportOptions(all_cases=True))
    assert html.unescape(row[-1]) == f"{verdict} ({words})"
    assert html.unescape(row[-1]) == _markdown_row(markdown, "matmul")[-1]
