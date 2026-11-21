# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Findings from fixed templates: the wording list and a known answer for each finding id."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pairbench.diagnose import findings
from pairbench.diagnose.folded import Profile
from pairbench.model import FINDING_IDS, CounterRow, Finding, ResourceRow, Results, forbidden_words

VERDICT = {"higher": "HIGHER", "lower": "LOWER", "tie": "TIE", "no_verdict": "NO VERDICT"}


def _results(
    example: dict[str, Any], rows: list[tuple[str, float | None, float | None, str]]
) -> Results:
    base = Results.from_json(example)
    template = base.comparisons[0]
    made = tuple(
        dataclasses.replace(
            template,
            case=case,
            primary=False,
            subject_median=own,
            baseline_median=other,
            outcome=outcome,  # type: ignore[arg-type]
            verdict=VERDICT[outcome],  # type: ignore[arg-type]
            n_rounds=20,
        )
        for case, own, other, outcome in rows
    )
    return dataclasses.replace(base, comparisons=(template, *made))


def _by_id(found: list[Finding]) -> dict[str, Finding]:
    return {f.id: f for f in found}


def test_every_finding_id_has_one_template() -> None:
    assert sorted(findings.TEMPLATES) == sorted(FINDING_IDS)


@pytest.mark.parametrize("finding_id", FINDING_IDS)
def test_every_template_uses_descriptive_words_only(finding_id: str) -> None:
    assert forbidden_words(findings.TEMPLATES[finding_id]) == ()


def test_cores_used(example_results: dict[str, Any]) -> None:
    results = _results(example_results, [("res/cores", 7.8, 1.0, "higher")])
    found = _by_id(findings.resource_findings(results, "new", "old"))
    assert found["cores_used"] == Finding(
        id="cores_used",
        text="new used 7.8 cores against 1.0 for old (median of 20 rounds).",
        evidence={
            "case": "res/cores",
            "subject_median": 7.8,
            "baseline_median": 1.0,
            "n_rounds": 20,
        },
    )


def test_cpu_time_split(example_results: dict[str, Any]) -> None:
    results = _results(
        example_results, [("res/user", 1.5, 0.5, "higher"), ("res/sys", 0.25, 0.125, "higher")]
    )
    found = _by_id(findings.resource_findings(results, "new", "old"))
    assert found["cpu_time_split"].text == (
        "new spent 1.500 s in user mode and 0.250 s in the kernel, against 0.500 s and "
        "0.125 s for old (median of 20 rounds)."
    )
    assert found["cpu_time_split"].evidence == {
        "cases": ("res/user", "res/sys"),
        "subject_medians": {"res/user": 1.5, "res/sys": 0.25},
        "baseline_medians": {"res/user": 0.5, "res/sys": 0.125},
        "n_rounds": 20,
    }


def test_peak_memory(example_results: dict[str, Any]) -> None:
    results = _results(example_results, [("res/rss_peak", 104857600.0, 52428800.0, "higher")])
    found = _by_id(findings.resource_findings(results, "new", "old"))
    assert found["peak_memory"].text == (
        "new reached a peak resident memory of 100.0 MiB against 50.0 MiB for old "
        "(median of 20 rounds)."
    )


def test_context_switches(example_results: dict[str, Any]) -> None:
    results = _results(
        example_results,
        [("res/ctx_voluntary", 12.0, 30.0, "lower"), ("res/ctx_involuntary", 3.5, 2.0, "tie")],
    )
    found = _by_id(findings.resource_findings(results, "new", "old"))
    assert found["context_switches"].text == (
        "new had 12 voluntary and 3.5 involuntary context switches, against 30 and 2 for old "
        "(median of 20 rounds)."
    )


def test_page_faults(example_results: dict[str, Any]) -> None:
    results = _results(
        example_results,
        [
            ("res/faults_major", 0.0, 0.0, "no_verdict"),
            ("res/faults_minor", 1500.0, 900.0, "higher"),
        ],
    )
    found = _by_id(findings.resource_findings(results, "new", "old"))
    assert found["page_faults"].text == (
        "new had 0 major and 1500 minor page faults, against 0 and 900 for old "
        "(median of 20 rounds)."
    )


def _zero(results: Results, case: str) -> Results:
    """Give the comparison of a case the reason a value of zero or less gives."""
    return dataclasses.replace(
        results,
        comparisons=tuple(
            dataclasses.replace(c, reason="nonpositive_value", reasons=("nonpositive_value",))
            if c.case == case
            else c
            for c in results.comparisons
        ),
    )


def test_a_zero_that_gives_no_verdict_is_quoted_when_the_medians_differ(
    example_results: dict[str, Any],
) -> None:
    results = _results(
        example_results,
        [
            ("res/faults_major", 5.0, 0.0, "no_verdict"),
            ("res/faults_minor", 900.0, 900.0, "tie"),
        ],
    )
    found = _by_id(findings.resource_findings(_zero(results, "res/faults_major"), "new", "old"))
    assert found["page_faults"].text == (
        "new had 5 major and 900 minor page faults, against 0 and 900 for old "
        "(median of 20 rounds)."
    )


def test_a_zero_on_both_sides_is_no_difference(example_results: dict[str, Any]) -> None:
    results = _results(
        example_results,
        [
            ("res/faults_major", 0.0, 0.0, "no_verdict"),
            ("res/faults_minor", 900.0, 900.0, "tie"),
        ],
    )
    assert findings.resource_findings(_zero(results, "res/faults_major"), "new", "old") == []


def test_a_side_name_that_holds_a_word_findings_never_use_leaves_the_finding_out(
    example_results: dict[str, Any],
) -> None:
    base = _results(example_results, [("res/cores", 7.8, 1.0, "higher")])
    results = dataclasses.replace(
        base, comparisons=tuple(dataclasses.replace(c, subject="causes") for c in base.comparisons)
    )
    left_out: list[str] = []
    assert findings.resource_findings(results, "causes", "old", left_out=left_out) == []
    assert left_out == ["cores_used"]


def test_a_function_name_that_holds_a_word_findings_never_use_leaves_the_finding_out() -> None:
    own = dataclasses.replace(
        SUBJECT,
        stacks={("main", "explains"): 6, ("main", "nap"): 2},
        leaves={("explains", "libnew.so"): 6, ("nap", "libc.so.6"): 2},
    )
    left_out: list[str] = []
    found = _by_id(findings.stack_findings("new", "old", own, BASELINE, left_out=left_out))
    assert left_out == ["top_function_share"]
    assert sorted(found) == ["objects_differ", "objects_on_one_side", "top_object_share"]


def test_an_object_name_that_holds_a_word_findings_never_use_leaves_the_finding_out() -> None:
    own = dataclasses.replace(SUBJECT, objects={**SUBJECT.objects, "due to.so": ("dd",)})
    left_out: list[str] = []
    found = _by_id(findings.stack_findings("new", "old", own, BASELINE, left_out=left_out))
    assert left_out == ["objects_on_one_side"]
    assert "objects_on_one_side" not in found
    assert "objects_differ" in found


def test_a_resource_case_without_a_difference_gives_no_finding(
    example_results: dict[str, Any],
) -> None:
    results = _results(
        example_results,
        [("res/cores", 1.0, 1.0, "tie"), ("res/rss_peak", None, 5.0, "no_verdict")],
    )
    assert findings.resource_findings(results, "new", "old") == []


def test_a_finding_that_needs_two_cases_is_made_only_when_both_exist(
    example_results: dict[str, Any],
) -> None:
    results = _results(example_results, [("res/user", 1.5, 0.5, "higher")])
    assert findings.resource_findings(results, "new", "old") == []


def test_the_resource_rows_are_the_comparisons_of_the_resource_cases(
    example_results: dict[str, Any],
) -> None:
    results = _results(example_results, [("res/cores", 7.8, 1.0, "higher")])
    assert findings.resource_rows(results) == (
        ResourceRow(
            case="res/cores",
            subject="new",
            baseline="old",
            subject_median=7.8,
            baseline_median=1.0,
            outcome="higher",
        ),
    )
    assert findings.resource_rows(results, sides=("other",)) == ()


COUNTS_NEW = {"instructions": 3000.0, "cycles": 1000.0, "cache-misses": 40.0, "branch-misses": 7.0}
COUNTS_OLD = {"instructions": 1500.0, "cycles": 1000.0, "cache-misses": 80.0, "branch-misses": 0.0}


def test_the_counter_rows_name_an_event_that_was_not_counted() -> None:
    rows = {r.event: r for r in findings.counter_rows("new", "old", COUNTS_NEW, COUNTS_OLD)}
    assert len(rows) == 10
    assert rows["instructions"] == CounterRow(
        event="instructions",
        subject="new",
        baseline="old",
        subject_value=3000.0,
        baseline_value=1500.0,
        ratio=2.0,
    )
    assert (rows["branch-misses"].ratio, rows["page-faults"].subject_value) == (None, None)
    assert findings.counter_rows("new", "old", None, None) == ()
    one_side = {r.event: r for r in findings.counter_rows("new", "old", COUNTS_NEW, None)}
    assert (one_side["instructions"].subject_value, one_side["instructions"].ratio) == (
        3000.0,
        None,
    )


def test_a_ratio_too_large_for_a_number_is_left_out() -> None:
    rows = findings.counter_rows("new", "old", {"instructions": 1e308}, {"instructions": 0.5})
    assert rows[0] == CounterRow(
        event="instructions",
        subject="new",
        baseline="old",
        subject_value=1e308,
        baseline_value=0.5,
        ratio=None,
    )


def test_instructions_ipc_and_cache_misses() -> None:
    found = _by_id(
        findings.counter_findings(findings.counter_rows("new", "old", COUNTS_NEW, COUNTS_OLD))
    )
    assert found["instructions"].text == (
        "new retired 3000 instructions against 1500 for old, a ratio of 2.00."
    )
    assert found["instructions_per_cycle"].text == (
        "new ran 3.00 instructions per cycle against 1.50 for old."
    )
    assert (
        found["cache_misses"].text == "new had 40 cache misses against 80 for old, a ratio of 0.50."
    )
    assert "branch_misses" not in found
    assert found["instructions"].evidence == {
        "event": "instructions",
        "subject_value": 3000.0,
        "baseline_value": 1500.0,
        "ratio": 2.0,
    }


def test_branch_misses() -> None:
    rows = findings.counter_rows("new", "old", {"branch-misses": 9.0}, {"branch-misses": 3.0})
    found = _by_id(findings.counter_findings(rows))
    assert list(found) == ["branch_misses"]
    assert (
        found["branch_misses"].text == "new had 9 branch misses against 3 for old, a ratio of 3.00."
    )


def test_no_counter_finding_without_the_counters_of_both_sides() -> None:
    assert findings.counter_findings(findings.counter_rows("new", "old", COUNTS_NEW, None)) == []


def test_a_counter_finding_for_a_side_name_with_a_word_findings_never_use_is_left_out() -> None:
    left_out: list[str] = []
    rows = findings.counter_rows("explains", "old", COUNTS_NEW, COUNTS_OLD)
    assert findings.counter_findings(rows, left_out=left_out) == []
    assert left_out == ["instructions", "instructions_per_cycle", "cache_misses"]


SUBJECT = Profile(
    "stacks",
    stacks={("main", "spin"): 6, ("main", "nap"): 2, ("main",): 2},
    leaves={("spin", "libnew.so"): 6, ("nap", "libc.so.6"): 2, ("main", "app"): 2},
    objects={"app": ("cc",), "libc.so.6": ("aa",), "libnew.so": ("11",)},
)
BASELINE = Profile(
    "stacks",
    stacks={("main", "spin"): 1, ("main", "nap"): 3},
    leaves={("spin", "libnew.so"): 1, ("nap", "libc.so.6"): 3},
    objects={"app": ("cc",), "libc.so.6": ("bb",), "libold.so": ("22",)},
)


def test_top_function_share() -> None:
    found = _by_id(findings.stack_findings("new", "old", SUBJECT, BASELINE))
    assert found["top_function_share"].text == (
        "The function with the largest share of samples on new is spin, with 60.0% of samples "
        "against 25.0% on old (instrument stacks)."
    )


def test_top_object_share() -> None:
    found = _by_id(findings.stack_findings("new", "old", SUBJECT, BASELINE))
    assert found["top_object_share"].text == (
        "The shared object with the largest share of samples on new is libnew.so, with 60.0% "
        "of samples against 25.0% on old."
    )


def test_objects_on_one_side() -> None:
    found = _by_id(findings.stack_findings("new", "old", SUBJECT, BASELINE))
    assert found["objects_on_one_side"].text == (
        "1 shared objects were loaded by new and not by old, and 1 by old and not by new: "
        "libnew.so, libold.so."
    )
    assert found["objects_on_one_side"].evidence == {
        "subject_only": ("libnew.so",),
        "baseline_only": ("libold.so",),
    }


def test_objects_differ() -> None:
    found = _by_id(findings.stack_findings("new", "old", SUBJECT, BASELINE))
    assert found["objects_differ"].text == (
        "1 shared objects have the same name on new and old and a build id that differs: libc.so.6."
    )


def test_stacks_of_two_instruments_give_no_finding() -> None:
    sampled = dataclasses.replace(BASELINE, instrument="pystacks", objects={})
    assert findings.stack_findings("new", "old", SUBJECT, sampled) == []


def test_python_frames_only_give_the_function_finding_alone() -> None:
    own = Profile("pystacks", stacks={("main", "spin"): 3}, leaves={("spin", None): 3})
    other = Profile("pystacks", stacks={("main", "nap"): 1}, leaves={("nap", None): 1})
    found = findings.stack_findings("new", "old", own, other)
    assert [f.id for f in found] == ["top_function_share"]
    assert found[0].text == (
        "The function with the largest share of samples on new is spin, with 100.0% of samples "
        "against 0.0% on old (instrument pystacks)."
    )


def test_a_subject_without_samples_gives_no_stack_finding() -> None:
    assert findings.stack_findings("new", "old", Profile("stacks"), BASELINE) == []


def test_a_long_list_of_names_says_how_many_more_there_are() -> None:
    own = dataclasses.replace(SUBJECT, objects={f"lib{i}.so": ("aa",) for i in range(7)})
    other = dataclasses.replace(BASELINE, objects={})
    found = _by_id(findings.stack_findings("new", "old", own, other))
    assert "objects_on_one_side" not in found
    other = dataclasses.replace(BASELINE, objects={"libz.so": ("aa",)})
    found = _by_id(findings.stack_findings("new", "old", own, other))
    assert found["objects_on_one_side"].text.endswith(
        "lib0.so, lib1.so, lib2.so, lib3.so, lib4.so, and 3 more."
    )


@pytest.mark.parametrize(
    ("value", "places", "text"),
    [(7.8, 1, "7.8"), (1.0, 1, "1.0"), (0.004, 1, "0.004"), (-0.04, 1, "-0.04"), (0.0, 3, "0.000")],
)
def test_how_a_number_is_written_in_a_finding(value: float, places: int, text: str) -> None:
    assert findings._decimal(value, places) == text


def test_the_code_of_a_finding_left_out_is_in_the_table_of_note_codes() -> None:
    from pairbench import model

    assert model.NOTE_FINDING_LEFT_OUT == "finding_left_out"
