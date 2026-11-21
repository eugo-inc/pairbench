# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Reports of a results document: what the terminal and the markdown report share.

A report reads a ``Results`` document and, when it is given one, the
diagnostics document. It never reads a capture and computes no number: every
number comes from the documents and is turned into text by the forms of
``pairbench.results.figures``. Of the findings it shows only those made from
resource figures and counters, so no report of this package prints a
function name or a shared-object name.

This module holds the view both reports are drawn from: the tables (one per
subject against the baseline), the plain words of every reason, and the
facts of the footer that is always printed. The footer of a serving run also
says how often its round count catches a real difference, from the simulated
error rates the package carries (``pairbench.report.odds``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pairbench.model import (
    FILE_DIAGNOSTICS,
    KIND_SERVE,
    METRIC_ENERGY_J,
    METRIC_MEAN_POWER_W,
    METRIC_TOKENS_PER_JOULE,
    NOTE_LAUNCH_COST_SHARE,
    REASON_TOO_FAR_APART,
    RES_PREFIX,
    STARTUP_PREFIX,
    STRICT,
    Case,
    Comparison,
    Diagnostics,
    Finding,
    Results,
    RuleInfo,
    case_matches,
    driver_text,
    grades_raw_p,
    raw_p_note,
    too_far_apart_words,
    verdict_word,
)
from pairbench.report.odds import odds_line, sentence
from pairbench.results.figures import (
    bar_text,
    change_text,
    floor_text,
    median_text,
    p_text,
    ratio_text,
    writable_percent,
)

# What a cell shows when the document holds no number for it.
NONE_SHOWN = "-"
# The mark beside a corrected p-value; the footer says what it means.
STAR = "*"
# The footer sentence when a shown row is secondary and so has no star.
SECONDARY_P_FACT = "A p-value without a star is uncorrected: the case is secondary."

# Every reason of a comparison in plain words.
REASON_WORDS: Mapping[str, str] = {
    "inside_noise": "the difference is significant but lies inside the noise",
    "not_significant": "the difference lies outside the noise but is not significant",
    "order_unbalanced": "one side ran first more than three times as often as the other",
    "sensitive_to_disturbed_rounds": "the outcome changes when disturbed rounds are set aside",
    "positive_control_failed": "the positive control failed, so no verdict of this run holds",
    "nonpositive_value": "a value of zero or less was recorded",
    "too_far_apart": (
        "the values are too far apart for a figure made from them to be a finite number"
    ),
    "single_measurement": "one measurement, no p-value",
    "order_not_recorded": "the order the sides ran in was not recorded",
    "too_few_rounds": "too few paired rounds for a verdict",
    "no_floor": "neither side has a twin, so there is no noise floor",
    "one_sided_floor": "only one side has a twin, so the noise floor is one-sided",
    "zero_floor": "a noise floor is exactly zero",
    "side_failed": "a side failed on its own account",
    "more_than_one_node": "the sides did not all run on one node",
}

# Why the comparison without disturbed rounds was not computed, in plain words.
NOT_COMPUTED_WORDS: Mapping[str, str] = {
    "too_few_rounds": "too few rounds would remain",
    "too_many_disturbed": "more than half of the rounds are disturbed",
}

# The labels of the identity a results document shows for a side.
IDENTITY_LABELS: Mapping[str, str] = {
    "image_id": "image ID",
    "digests": "digests",
    "platform": "platform",
    "python_version": "Python",
    "packages_sha256": "packages",
    "executable_sha256": "executable",
    "argv_sha256": "command",
    "args_sha256": "arguments",
    "files_sha256": "files",
    "identify_sha256": "identify output",
}

# How the positive control doubled the work, in plain words.
VIA_WORDS: Mapping[str, str] = {
    "repeat": "the work run twice in one start",
    "factor": "the work asked to double itself",
}

# The label of a case whose values cover the GPU alone, and of a start-up case.
ENERGY_LABEL = "GPU-only power"
WARM_START_LABEL = "warm start"
# The metrics of the energy cases: a case is one of them alone or under a load level.
ENERGY_METRICS = (METRIC_ENERGY_J, METRIC_MEAN_POWER_W, METRIC_TOKENS_PER_JOULE)


def reason_words(reason: str) -> str:
    """Return a reason of a comparison in plain words."""
    return REASON_WORDS.get(reason, reason.replace("_", " "))


def case_label(case: str) -> str:
    """Return a case id as a report shows it, with the label it carries.

    An energy case, ``energy_j[gpu]``, ``mean_power_w[gpu]`` or
    ``tokens_per_joule[gpu]`` alone or under a load level, is labelled
    ``GPU-only power``; a start-up case of a serving side ``warm start``.
    Any other case is shown as it is, also one whose name holds ``[gpu]``.
    """
    if case.rpartition("/")[2] in ENERGY_METRICS:
        return f"{case} ({ENERGY_LABEL})"
    if case.startswith(STARTUP_PREFIX):
        return f"{case} ({WARM_START_LABEL})"
    return case


@dataclass(frozen=True)
class Row:
    """One row of a verdict table, every cell as text."""

    case: str
    subject: str
    baseline: str
    change: str
    noise: str
    p: str
    verdict: str


@dataclass(frozen=True)
class Table:
    """The verdict table of one subject against the baseline."""

    subject: str
    baseline: str
    rows: tuple[Row, ...]


def cases_of(results: Results) -> dict[str, Case]:
    """Return the case records of a results document by id."""
    return {case.id: case for case in results.cases}


def shown_comparisons(
    results: Results,
    *,
    cases: Sequence[str] = (),
    all_cases: bool = False,
) -> tuple[Comparison, ...]:
    """Return the comparisons a report shows, in the order of the document.

    Primary cases are shown, and secondary cases too with ``all_cases``.
    ``cases`` narrows that set to the case ids its patterns match. Neither
    changes what was tested: the family stays the one the document records.
    """
    return tuple(
        c
        for c in results.comparisons
        if (c.primary or all_cases) and (not cases or case_matches(c.case, cases))
    )


def _kind(case: Case | None) -> str:
    return case.kind if case is not None else "other"


def _median(value: float | None, case: Case | None) -> str:
    if value is None:
        return NONE_SHOWN
    return median_text(value, case.unit if case is not None else "")


def change_cell(comparison: Comparison, case: Case | None) -> str:
    """Return the change of a comparison in words: ``1.26x faster``, ``1.04x lower``."""
    if comparison.ratio is None:
        return NONE_SHOWN
    better = case.better if case is not None else "lower"
    return change_text(comparison.ratio, _kind(case), better=better)


def noise_cell(comparison: Comparison, *, verbose: bool = False) -> str:
    """Return the bar a gap must exceed, ``±1.8%``; verbose adds each side's own floor."""
    unit = comparison.floor.unit
    shown = writable_percent(comparison.bar, unit)
    bar = NONE_SHOWN if shown is None else bar_text(shown, unit)
    if not verbose:
        return bar
    floors = []
    for side, floor in (
        (comparison.subject, comparison.floor.subject),
        (comparison.baseline, comparison.floor.baseline),
    ):
        value = None if floor is None else writable_percent(floor.value, unit)
        floors.append(f"{side} {NONE_SHOWN if value is None else floor_text(value, unit)}")
    return f"{bar} ({', '.join(floors)})"


def graded_on_raw_p(results: Results) -> bool:
    """Whether the rule of the results grades every case on its uncorrected p-value."""
    return grades_raw_p(results.rule)


def p_cell(comparison: Comparison, *, raw: bool = False) -> str:
    """Return the p-value a row shows: the one the case was graded on.

    A primary case shows its corrected p-value with a star that points at
    the footer. A secondary case is graded with its uncorrected p-value and
    shows that one, without a star. Under a rule that grades every case on
    its uncorrected p-value (``raw``), every case shows that one, without a
    star.
    """
    if comparison.primary and not raw:
        if comparison.p_corrected is None:
            return NONE_SHOWN
        return f"{p_text(comparison.p_corrected)}{STAR}"
    return NONE_SHOWN if comparison.p_raw is None else p_text(comparison.p_raw)


def comparison_reason_words(comparison: Comparison) -> str:
    """Return the main reason of a comparison in plain words.

    Values too far apart for a finite ratio name the two medians when the
    comparison holds them (``pairbench.model.too_far_apart_words``).
    """
    reason = comparison.reason or ""
    if reason == REASON_TOO_FAR_APART:
        return too_far_apart_words(comparison)
    return reason_words(reason)


def verdict_cell(comparison: Comparison) -> str:
    """Return the verdict of a comparison, with its reason in plain words when it has one."""
    if comparison.reason is None:
        return comparison.verdict
    return f"{comparison.verdict} ({comparison_reason_words(comparison)})"


def row_of(
    comparison: Comparison, case: Case | None, *, verbose: bool = False, raw: bool = False
) -> Row:
    """Return the row of one comparison."""
    return Row(
        case=case_label(comparison.case),
        subject=_median(comparison.subject_median, case),
        baseline=_median(comparison.baseline_median, case),
        change=change_cell(comparison, case),
        noise=noise_cell(comparison, verbose=verbose),
        p=p_cell(comparison, raw=raw),
        verdict=verdict_cell(comparison),
    )


def tables(
    results: Results, comparisons: Iterable[Comparison], *, verbose: bool = False
) -> tuple[Table, ...]:
    """Return one table per subject against the baseline, subjects in the order they appear."""
    cases = cases_of(results)
    raw = graded_on_raw_p(results)
    grouped: dict[tuple[str, str], list[Row]] = {}
    for comparison in comparisons:
        key = (comparison.subject, comparison.baseline)
        row = row_of(comparison, cases.get(comparison.case), verbose=verbose, raw=raw)
        grouped.setdefault(key, []).append(row)
    return tuple(
        Table(subject=subject, baseline=baseline, rows=tuple(rows))
        for (subject, baseline), rows in grouped.items()
    )


def baseline_name(results: Results) -> str | None:
    """Return the name of the baseline: the side whose role says so, else the one compared with."""
    for side in results.sides:
        if side.role == "baseline":
            return side.name
    for comparison in results.comparisons:
        return comparison.baseline
    return None


def rounds_fact(comparisons: Sequence[Comparison]) -> str:
    """Return the footer fact that names the test and the number of paired rounds."""
    counts = sorted({c.n_rounds for c in comparisons})
    if not counts:
        return "Exact two-sided sign test; no comparison to show."
    if len(counts) == 1:
        rounds = "1 paired round" if counts[0] == 1 else f"{counts[0]} paired rounds"
    else:
        rounds = f"{counts[0]} to {counts[-1]} paired rounds"
    return f"Exact two-sided sign test over {rounds}."


def serving_odds_fact(results: Results) -> str | None:
    """Say how often the round count of a serving run catches a real difference, or ``None``.

    A serving run is one whose sides are all serving sides. The sentence is
    ``pairbench.report.odds.odds_line`` for the run's paired rounds, its
    number of primary cases and of subjects, and its rule, counted over every
    primary comparison of the document whatever a report shows. A run with no
    primary comparison has none.
    """
    from pairbench.plan import SERVING_MORE_ROUNDS  # the plan module imports this package

    if not results.sides or any(side.kind != KIND_SERVE for side in results.sides):
        return None
    primary = [c for c in results.comparisons if c.primary]
    if not primary:
        return None
    return sentence(
        odds_line(
            [c.n_rounds for c in primary],
            len({c.case for c in primary}),
            subjects=len({c.subject for c in primary}),
            rule=_rule_as_graded(results.rule),
            more_rounds=SERVING_MORE_ROUNDS,
        )
    )


def _rule_as_graded(rule: RuleInfo) -> str:
    """The rule's name, or, for a rule named ``strict`` whose recorded fields differ from
    those of the default rule, a name that says so: the simulation graded the default."""
    default = STRICT.to_json()
    if rule.name == STRICT.name and any(
        key in default and default[key] != value for key, value in rule.fields.items()
    ):
        return f"{rule.name} with other settings"
    return rule.name


def control_fact(results: Results) -> str:
    """Return the state of the positive control in one sentence."""
    control = results.controls.positive
    if control.status == "not_run":
        return "Positive control: not run."
    entry = control.entry or NONE_SHOWN
    if control.status == "ok":
        return f"Positive control {entry}: ok."
    failed = [
        row.case if row.ratio is not None else f"{row.case} (no ratio could be read)"
        for row in control.cases
        if not row.passed
    ]
    return (
        f"Positive control {entry}: failed on {', '.join(failed)}; "
        "every comparison of this run is NO VERDICT."
    )


def floor_facts(comparisons: Sequence[Comparison]) -> list[str]:
    """Return the footer facts on noise floors that were supplied, provisional or one-sided."""
    facts: list[str] = []
    if any(c.floor.source == "supplied" for c in comparisons):
        facts.append("Noise floors were supplied by the caller, not measured from twins.")
    provisional = [
        f"{side} on {c.case}"
        for c in comparisons
        for side, floor in ((c.subject, c.floor.subject), (c.baseline, c.floor.baseline))
        if floor is not None and floor.provisional
    ]
    if provisional:
        facts.append(
            "Provisional noise floor, from too few rounds: "
            + ", ".join(dict.fromkeys(provisional))
            + "."
        )
    one_sided = [c.case for c in comparisons if c.floor.mode == "ONE-SIDED"]
    if one_sided:
        facts.append("One-sided noise floor: " + ", ".join(dict.fromkeys(one_sided)) + ".")
    return facts


def sensitivity_facts(results: Results, comparisons: Sequence[Comparison]) -> list[str]:
    """Return what the comparisons read without the disturbed rounds, where rounds were set aside.

    Where the repeat was not computed, the fact says why.
    """
    cases = cases_of(results)
    facts: list[str] = []
    for c in comparisons:
        s = c.sensitivity
        where = f"{c.case} ({c.subject} against {c.baseline})"
        if s.not_computed is not None:
            facts.append(
                f"Without disturbed rounds, {where}: not computed, "
                f"{NOT_COMPUTED_WORDS.get(s.not_computed, s.not_computed)}."
            )
        elif s.rounds_set_aside:
            ratio = NONE_SHOWN if s.ratio is None else ratio_text(s.ratio)
            word = (
                NONE_SHOWN
                if s.outcome is None
                else verdict_word(s.outcome, _kind(cases.get(c.case)))
            )
            agrees = "agrees" if s.agrees else "differs"
            facts.append(
                f"Without disturbed rounds {rounds_list(s.rounds_set_aside)}, {where}: "
                f"{ratio} {word}, {agrees}."
            )
    return facts


def rounds_list(rounds: Sequence[int]) -> str:
    """Return a list of round numbers as text: ``3, 4``."""
    return ", ".join(str(r) for r in rounds)


def driver_fact(results: Results) -> str | None:
    """Return which driver read the values and the versions of the tool it wraps, when known.

    Sides read by different drivers, or by different versions of one tool,
    are named one by one (``pairbench.model.driver_text``).
    """
    return driver_text(results)


def energy_fact(results: Results) -> str | None:
    """Return what the energy cases cover, when power was sampled."""
    if results.energy is None:
        return None
    return f"{ENERGY_LABEL}: it leaves out {', '.join(results.energy.excludes)}."


def raw_p_fact(results: Results) -> str:
    """The footer sentence of a rule that grades every case on its uncorrected p-value.

    It says why the p-value shown can be smaller than the corrected one that
    the results keep.
    """
    return raw_p_note(results.rule, results.comparisons)


def footer(results: Results, comparisons: Sequence[Comparison]) -> list[str]:
    """Return the facts of the footer that is always printed, one sentence each.

    The test and the number of paired rounds; for a serving run, how often
    its round count catches a real difference; the family size in plain
    words; the rule; the machine state; the baseline; the state of the
    positive control; every degraded check; a floor that was supplied,
    provisional or one-sided; what the comparisons read without disturbed
    rounds; the launch-cost note when it applies; the driver and the tool
    versions; what the energy cases cover.
    """
    facts = [rounds_fact(comparisons)]
    odds = serving_odds_fact(results)
    if odds is not None:
        facts.append(odds)
    if graded_on_raw_p(results):
        facts.append(raw_p_fact(results))
    else:
        facts.append(f"{STAR} {results.rule.plain}.")
        if any(not c.primary for c in comparisons):
            facts.append(SECONDARY_P_FACT)
    facts.append(f"Rule: {results.rule.name}.")
    facts.append(f"Machine state: {results.machine_state.status}.")
    facts.append(f"Baseline: {baseline_name(results) or 'none'}.")
    facts.append(control_fact(results))
    for check in results.machine_state.degraded:
        facts.append(f"Check {check.name}: {check.status} ({check.message}).")
    facts.extend(floor_facts(comparisons))
    facts.extend(sensitivity_facts(results, comparisons))
    for note in results.notes:
        if note.code == NOTE_LAUNCH_COST_SHARE:
            facts.append(note.message)
    for fact in (driver_fact(results), energy_fact(results)):
        if fact is not None:
            facts.append(fact)
    return facts


def resource_comparisons(results: Results) -> tuple[Comparison, ...]:
    """Return the comparisons of the resource cases, those under ``res/``."""
    return tuple(c for c in results.comparisons if c.case.startswith(RES_PREFIX))


def shareable_findings(diagnostics: Diagnostics) -> tuple[Finding, ...]:
    """Return the findings a report may show: made from resource figures and counters alone."""
    return diagnostics.shareable_findings()


def diagnostics_file(results: Results | None) -> str:
    """Return where the full diagnostics are, as a name in the run folder."""
    if results is not None and results.artifacts.diagnostics:
        return results.artifacts.diagnostics
    return FILE_DIAGNOSTICS


__all__ = [
    "ENERGY_LABEL",
    "ENERGY_METRICS",
    "IDENTITY_LABELS",
    "NONE_SHOWN",
    "NOT_COMPUTED_WORDS",
    "REASON_WORDS",
    "SECONDARY_P_FACT",
    "STAR",
    "VIA_WORDS",
    "WARM_START_LABEL",
    "Row",
    "Table",
    "baseline_name",
    "case_label",
    "cases_of",
    "change_cell",
    "comparison_reason_words",
    "control_fact",
    "diagnostics_file",
    "driver_fact",
    "energy_fact",
    "floor_facts",
    "footer",
    "graded_on_raw_p",
    "noise_cell",
    "p_cell",
    "raw_p_fact",
    "reason_words",
    "resource_comparisons",
    "rounds_fact",
    "rounds_list",
    "row_of",
    "sensitivity_facts",
    "serving_odds_fact",
    "shareable_findings",
    "shown_comparisons",
    "tables",
    "verdict_cell",
]
