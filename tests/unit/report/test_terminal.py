# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The terminal report: tables, change words, noise, starred p, reasons, footer, findings."""

from __future__ import annotations

import copy
from typing import Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import ReportOptions, delegate
from pairbench.model import REASONS, Diagnostics, Results
from pairbench.report import REASON_WORDS, case_label
from pairbench.report.terminal import TerminalReporter, findings_text

EMPTY = {
    "n_rounds": 0,
    "n_unpaired": 0,
    "n_untied": 0,
    "n_lower": 0,
    "n_higher": 0,
    "subject_median": None,
    "baseline_median": None,
    "ratio": None,
    "statistic": None,
    "gap": None,
    "floor": {
        "source": "twins",
        "unit": "fraction",
        "subject": None,
        "baseline": None,
        "mode": "NONE",
    },
    "bar": None,
    "p_raw": None,
    "p_raw_fraction": None,
    "p_corrected": None,
    "verdict": "NO VERDICT",
    "outcome": "no_verdict",
    "reason": "too_few_rounds",
    "reasons": ["too_few_rounds"],
    "order_split": [0, 0],
    "sensitivity": {"rounds_set_aside": [], "ratio": None, "outcome": None, "agrees": None},
}

# The terminal report of the example results document of the format.
EXAMPLE_TERMINAL = """\
new against old (baseline)

case    new     old     change        noise  p        verdict
matmul  1.92 s  2.41 s  1.25x faster  ±1.8%  0.0010*  FASTER

Refused, E_GRID (experiment): a made-up refusal

Exact two-sided sign test over 16 paired rounds.
* corrected for testing 2 cases at once.
Rule: strict.
Machine state: quiet.
Baseline: old.
Positive control old~twice: ok.
"""

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


def terminal(results: Results, **options: Any) -> str:
    return pairbench.render(results, "terminal", options=ReportOptions(**options))


def lines_of(text: str) -> list[str]:
    return text.splitlines()


def test_the_example_document(example_results: dict[str, Any]) -> None:
    assert terminal(Results.from_json(example_results)) == EXAMPLE_TERMINAL


@pytest.mark.parametrize(
    ("ratio", "case", "change"),
    [
        (1 / 1.26, ("time-case", "s", "lower", "time", True), "1.26x faster"),
        (1.04, ("time-case", "s", "lower", "time", True), "1.04x slower"),
        (1.26, ("count-case", "count", "lower", "count", True), "1.26x higher"),
        (1 / 1.04, ("rate-case", "tokens/s", "higher", "other", True), "1.04x lower"),
    ],
)
def test_the_change_is_the_larger_of_the_ratio_and_its_inverse_with_a_word(
    build: Any, ratio: float, case: tuple[str, str, str, str, bool], change: str
) -> None:
    results = build(comparisons=[{"case": case[0], "ratio": ratio}], cases=(case,))
    row = next(line for line in lines_of(terminal(results)) if line.startswith(case[0]))
    assert f"  {change}  " in row


def test_a_time_case_where_higher_is_better_never_says_faster_beside_slower(build: Any) -> None:
    case = ("throughput", "ns", "higher", "time", True)
    results = build(
        comparisons=[{"case": "throughput", "ratio": 0.8, "verdict": "SLOWER", "outcome": "worse"}],
        cases=(case,),
    )
    row = next(line for line in lines_of(terminal(results)) if line.startswith("throughput"))
    assert "  1.25x lower  " in row
    assert "faster" not in row


def test_noise_is_the_bar_and_verbose_adds_each_sides_floor(build: Any) -> None:
    results = build()
    assert "  ±1.8%  0.0010*  FASTER" in terminal(results)
    assert "  ±1.8% (new 1.1%, old 0.7%)  0.0010*  FASTER" in terminal(results, verbose=True)


def test_p_is_the_corrected_value_with_a_star_that_points_at_the_footer(build: Any) -> None:
    text = terminal(build(comparisons=[{"p_raw": 0.0003, "p_corrected": 0.0227}]))
    assert "  0.023*  FASTER" in text
    assert "* corrected for testing 2 cases at once.\n" in text
    assert "0.00030" not in text


RAW_RULE = {
    "name": "made-up-raw",
    "fields": {"name": "made-up-raw", "p_source": "raw"},
    "family_size": 2,
    "plain": "corrected for testing 2 cases at once",
}


RAW_NOTE = (
    "No p-value is corrected: rule made-up-raw grades each case on its own p-value and does "
    "not correct for testing 2 cases at once, so a p-value here can be smaller than the "
    "corrected one, which results.json keeps as p_corrected."
)


def test_a_rule_that_grades_raw_p_values_shows_the_raw_p_without_a_star(build: Any) -> None:
    text = terminal(build(comparisons=[{"p_raw": 0.0003, "p_corrected": 0.0227}], rule=RAW_RULE))
    assert "  0.00030  FASTER" in text
    assert "0.023" not in text
    assert "* corrected for testing" not in text
    assert RAW_NOTE in " ".join(text.split())


def test_a_rule_that_grades_raw_p_values_on_one_case_says_the_corrected_p_is_the_same(
    build: Any,
) -> None:
    rule = {**RAW_RULE, "family_size": 1, "plain": "one case tested"}
    text = terminal(build(comparisons=[{"p_raw": 0.0003, "p_corrected": 0.0003}], rule=rule))
    assert "  0.00030  FASTER" in text
    assert (
        "No p-value is corrected: rule made-up-raw grades each case on its own p-value; with "
        "one case tested, the corrected p-value is the same."
    ) in " ".join(text.split())


def test_a_case_without_a_verdict_shows_its_reason_in_plain_words(build: Any) -> None:
    text = terminal(build(comparisons=[EMPTY]))
    assert (
        "matmul  -    -    -       -      -  NO VERDICT (too few paired rounds for a verdict)"
        in (lines_of(text))
    )


def test_one_measurement_has_no_p_value(build: Any) -> None:
    single = {
        **EMPTY,
        "n_rounds": 1,
        "n_untied": 1,
        "n_lower": 1,
        "subject_median": 1.92,
        "baseline_median": 2.41,
        "ratio": 0.797,
        "reason": "single_measurement",
        "reasons": ["single_measurement"],
    }
    row = lines_of(terminal(build(comparisons=[single])))[3]
    assert row == (
        "matmul  1.92 s  2.41 s  1.25x faster  -      -  NO VERDICT (one measurement, no p-value)"
    )


def test_an_unresolved_case_shows_its_reason(build: Any) -> None:
    unresolved = {
        "verdict": "UNRESOLVED",
        "outcome": "unresolved",
        "reason": "inside_noise",
        "reasons": ["inside_noise"],
    }
    assert "UNRESOLVED (the difference is significant but lies inside the noise)" in terminal(
        build(comparisons=[unresolved])
    )


FAR_APART = {
    **EMPTY,
    "n_rounds": 16,
    "n_untied": 16,
    "n_higher": 16,
    "subject_median": 1e300,
    "baseline_median": 1e-10,
    "reason": "too_far_apart",
    "reasons": ["too_far_apart"],
}


def test_medians_too_far_apart_are_named_in_the_reason(build: Any) -> None:
    text = terminal(build(comparisons=[FAR_APART]))
    assert (
        "NO VERDICT (the medians 1e+300 and 1e-10 are too far apart for their ratio to be a "
        "finite number)"
    ) in text


def test_a_side_too_far_from_its_twin_is_the_reason_when_the_ratio_is_finite(build: Any) -> None:
    text = terminal(build(comparisons=[{**FAR_APART, "ratio": 2.0, "statistic": 2.0}]))
    assert (
        "NO VERDICT (a side and its twin are too far apart for the noise floor to be a finite "
        "number)"
    ) in text


def test_every_reason_has_plain_words() -> None:
    assert set(REASON_WORDS) == set(REASONS)
    assert all(words and "_" not in words for words in REASON_WORDS.values())


def test_the_footer_is_printed_when_there_is_no_comparison(build: Any) -> None:
    text = terminal(build(comparisons=[]))
    assert text == (
        "No comparison to show.\n"
        "\n"
        "Refused, E_GRID (experiment): a made-up refusal\n"
        "\n"
        "Exact two-sided sign test; no comparison to show.\n"
        "* corrected for testing 2 cases at once.\n"
        "Rule: strict.\n"
        "Machine state: quiet.\n"
        "Baseline: none.\n"
        "Positive control old~twice: ok.\n"
    )


def test_one_table_per_subject_in_the_order_they_appear(build: Any) -> None:
    results = build(
        comparisons=[
            {"subject": "newer", "ratio": 0.5, "subject_median": 1.2},
            {"subject": "new"},
        ]
    )
    text = terminal(results)
    headings = [line for line in lines_of(text) if line.endswith("(baseline)")]
    assert headings == ["newer against old (baseline)", "new against old (baseline)"]
    assert "case    newer   old     change        noise  p        verdict" in text
    assert "matmul  1.20 s  2.41 s  2.00x faster  ±1.8%  0.0010*  FASTER" in text


def test_secondary_cases_only_with_all_and_a_describing_case_shows_higher(build: Any) -> None:
    results = build(
        comparisons=[{}, RESOURCE], cases=(("res/cores", "cores", "none", "other", False),)
    )
    assert "res/cores" not in terminal(results)
    text = terminal(results, all_cases=True)
    assert "res/cores  7.80 cores  1.00 cores  7.80x higher  ±1.8%  0.00050  HIGHER" in text
    assert "A p-value without a star is uncorrected: the case is secondary.\n" in text


def test_the_case_filter_narrows_the_display_and_never_the_family(build: Any) -> None:
    results = build(
        comparisons=[{}, {"case": "other-case"}],
        cases=(("other-case", "s", "lower", "time", True),),
    )
    text = terminal(results, cases=("other-*",))
    assert "other-case" in text
    assert "\nmatmul" not in text
    assert "* corrected for testing 2 cases at once.\n" in text


def test_degraded_checks_and_floor_stamps_are_in_the_footer(build: Any) -> None:
    supplied = {
        "floor": {
            "source": "supplied",
            "unit": "fraction",
            "subject": {
                "value": 0.01,
                "n": 4,
                "provisional": True,
                "spread": None,
                "outlier_rounds": [],
            },
            "baseline": None,
            "mode": "ONE-SIDED",
        }
    }
    results = build(
        comparisons=[supplied],
        machine_state={
            "status": "unknown",
            "gates": [],
            "degraded": [
                {"name": "census", "status": "unavailable", "message": "a made-up reason"}
            ],
        },
    )
    text = terminal(results)
    assert "Machine state: unknown.\n" in text
    assert "Check census: unavailable (a made-up reason).\n" in text
    assert "Noise floors were supplied by the caller, not measured from twins.\n" in text
    assert "Provisional noise floor, from too few rounds: new on matmul.\n" in text
    assert "One-sided noise floor: matmul.\n" in text


def test_the_comparison_without_disturbed_rounds_is_printed_beside_it(build: Any) -> None:
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
    not_computed = {
        "case": "other-case",
        "sensitivity": {
            "rounds_set_aside": [1, 2, 3],
            "ratio": None,
            "outcome": None,
            "agrees": None,
            "not_computed": "too_many_disturbed",
        },
    }
    results = build(
        comparisons=[disturbed, not_computed],
        cases=(("other-case", "s", "lower", "time", True),),
    )
    text = terminal(results)
    assert "Without disturbed rounds 3, 4, matmul (new against old): 0.99x TIE, differs.\n" in text
    assert (
        "Without disturbed rounds, other-case (new against old): not computed, "
        "more than half of the rounds are disturbed.\n"
    ) in text


def test_the_launch_cost_note_is_printed_when_it_applies(build: Any) -> None:
    notes = [
        {"code": "launch_cost_share", "message": "a made-up launch-cost note"},
        {"code": "floor_provisional", "message": "a made-up other note"},
    ]
    text = terminal(build(notes=notes))
    assert text.endswith("Positive control old~twice: ok.\na made-up launch-cost note\n")
    assert "a made-up other note" not in text
    assert "a made-up launch-cost note" not in terminal(build())


def test_the_state_of_the_positive_control(build: Any, example_results: dict[str, Any]) -> None:
    failed = copy.deepcopy(example_results["controls"])
    failed["positive"]["status"] = "failed"
    failed["positive"]["cases"][0].update(ratio=1.5, passed=False)
    text = terminal(build(controls=failed))
    assert (
        "Positive control old~twice: failed on matmul; every comparison of this run is "
        "NO VERDICT.\n"
    ) in text
    failed["positive"]["cases"][0].update(ratio=None, p_raw=None)
    assert (
        "Positive control old~twice: failed on matmul (no ratio could be read); every "
        "comparison of this run is NO VERDICT.\n"
    ) in terminal(build(controls=failed))
    not_run = {
        "positive": {
            "status": "not_run",
            "entry": None,
            "via": "repeat",
            "tolerance": 0.1,
            "cases": [],
        }
    }
    assert "Positive control: not run.\n" in terminal(build(controls=not_run))


def test_labels_driver_and_energy(build: Any, example_results_every_key: dict[str, Any]) -> None:
    results = build(
        comparisons=[{"case": "c32/energy_j[gpu]"}, {"case": "startup/ready_s"}],
        cases=(
            ("c32/energy_j[gpu]", "J", "lower", "other", True),
            ("startup/ready_s", "s", "lower", "time", True),
        ),
        provenance=example_results_every_key["provenance"],
        energy=example_results_every_key["energy"],
    )
    text = terminal(results)
    assert "c32/energy_j[gpu] (GPU-only power)  1.92 J" in text
    assert "startup/ready_s (warm start)        1.92 s" in text
    assert "Values read by driver lines, tool version 0.0.0.\n" in text
    assert (
        "GPU-only power: it leaves out cpu, memory, storage, cooling, power supply losses.\n"
    ) in text


@pytest.mark.parametrize(
    ("case", "label"),
    [
        ("energy_j[gpu]", "energy_j[gpu] (GPU-only power)"),
        ("mean_power_w[gpu]", "mean_power_w[gpu] (GPU-only power)"),
        ("c8/tokens_per_joule[gpu]", "c8/tokens_per_joule[gpu] (GPU-only power)"),
        ("test_matmul[gpu]", "test_matmul[gpu]"),
        ("tests/test_a.py::test_matmul[gpu]", "tests/test_a.py::test_matmul[gpu]"),
        ("bench[gpu]/wall", "bench[gpu]/wall"),
    ],
)
def test_only_the_energy_cases_are_labelled_gpu_only_power(case: str, label: str) -> None:
    assert case_label(case) == label


def test_the_findings_name_the_diagnostics_file_the_results_list(
    build: Any, diagnostics: Diagnostics, example_results: dict[str, Any]
) -> None:
    artifacts = {**example_results["artifacts"], "diagnostics": "diag/made-up.json"}
    text = terminal(build(artifacts=artifacts), diagnostics=diagnostics)
    assert text.endswith("Full diagnostics, with names from the user's code: diag/made-up.json\n")


def test_findings_from_resource_figures_and_counters_only(
    build: Any, diagnostics: Diagnostics
) -> None:
    text = terminal(build(), diagnostics=diagnostics)
    assert text.endswith(
        "Findings from resource figures and counters:\n"
        "  new used 7.8 cores against 1.0 for old (median of 20 rounds).\n"
        "  new counted 0.50x the instructions of old.\n"
        "Full diagnostics, with names from the user's code: diagnostics.json\n"
    )
    for name in ("markerfunctionname", "libmarkerobject.so", "made_up_function", "libmade-up.so"):
        assert name not in text


def test_findings_text_holds_the_same_lines_alone(diagnostics: Diagnostics) -> None:
    assert findings_text(diagnostics) == (
        "Findings from resource figures and counters:\n"
        "  new used 7.8 cores against 1.0 for old (median of 20 rounds).\n"
        "  new counted 0.50x the instructions of old.\n"
        "Full diagnostics, with names from the user's code: diagnostics.json\n"
    )
    assert "markerfunctionname" not in findings_text(diagnostics)
    assert delegate("findings") is findings_text


def test_no_finding_still_says_where_the_diagnostics_are(
    example_diagnostics: dict[str, Any],
) -> None:
    doc = copy.deepcopy(example_diagnostics)
    doc["findings"] = []
    assert findings_text(Diagnostics.from_json(doc)) == (
        "No finding from resource figures and counters.\n"
        "Full diagnostics, with names from the user's code: diagnostics.json\n"
    )


def test_control_characters_from_a_run_are_shown_as_question_marks(build: Any) -> None:
    results = build(
        comparisons=[{"case": "a\x1b[31mred"}],
        cases=(("a\x1b[31mred", "s", "lower", "time", True),),
    )
    text = terminal(results)
    assert "\x1b" not in text
    assert "a?[31mred" in text


def test_the_document_with_only_required_keys(
    example_results_required_only: dict[str, Any],
) -> None:
    text = terminal(Results.from_json(example_results_required_only))
    assert "Positive control: not run.\n" in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_the_reporter_is_registered_under_its_name() -> None:
    reporter = registry.reporter("terminal")
    assert isinstance(reporter, TerminalReporter)
    assert reporter.name == "terminal"
    assert reporter.api_version == 1


def test_the_report_shows_every_character_printable_escapes_as_a_mark() -> None:
    from pairbench.errors import ESCAPED_CHARACTERS
    from pairbench.report.terminal import plain

    controls = {*range(0x20), 0x7F, *range(0x80, 0xA0)}
    others = {0x2028, 0x2029, 0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F)}
    others |= {*range(0x2066, 0x206A), *range(0xD800, 0xE000)}
    assert controls | others == ESCAPED_CHARACTERS
    wrong = [
        f"U+{code:04X}"
        for code in range(0x110000)
        if plain(chr(code)) != ("?" if code in ESCAPED_CHARACTERS else chr(code))
    ]
    assert wrong == []
