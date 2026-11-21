# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Findings: sentences made by code from fixed templates, each with its numbers.

There is one template per finding id of ``pairbench.model.FINDING_IDS``. A
finding describes how a subject and the baseline differ, in descriptive
words only; it never names a cause. A finding is made only when every number
of its template exists: a skipped instrument gives no finding and no
placeholder.

The resource findings come from the comparisons of the ``res/`` cases in the
results and are made only when at least one of their cases came out
``higher`` or ``lower``, or gave no verdict for a value of zero or less while
its two medians differ. The counter findings come from the ``counters``
launches. The stack findings come from the ``stacks`` or ``pystacks``
launches and are made only when the subject and the baseline were sampled by
the same instrument; the object findings need ``stacks`` on both.

A finding's text holds names the user chose: side names, function names and
shared-object names. A text in which such a name reads as one of the words a
finding never uses is not made; its finding id is added to the ``left_out``
list the caller passes, so the caller can say so in a note.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from pairbench.diagnose.folded import Profile
from pairbench.model import (
    CASE_RES_CORES,
    CASE_RES_CTX_INVOLUNTARY,
    CASE_RES_CTX_VOLUNTARY,
    CASE_RES_FAULTS_MAJOR,
    CASE_RES_FAULTS_MINOR,
    CASE_RES_RSS_PEAK,
    CASE_RES_SYS,
    CASE_RES_USER,
    COUNTER_EVENTS,
    RESOURCE_CASES,
    Comparison,
    CounterRow,
    Finding,
    ResourceRow,
    Results,
    forbidden_words,
)

# The fixed template of each finding id.
TEMPLATES: Final[Mapping[str, str]] = {
    "cores_used": (
        "{subject} used {subject_value} cores against {baseline_value} for {baseline} "
        "(median of {n_rounds} rounds)."
    ),
    "cpu_time_split": (
        "{subject} spent {subject_user} s in user mode and {subject_sys} s in the kernel, "
        "against {baseline_user} s and {baseline_sys} s for {baseline} "
        "(median of {n_rounds} rounds)."
    ),
    "peak_memory": (
        "{subject} reached a peak resident memory of {subject_value} MiB against "
        "{baseline_value} MiB for {baseline} (median of {n_rounds} rounds)."
    ),
    "context_switches": (
        "{subject} had {subject_voluntary} voluntary and {subject_involuntary} involuntary "
        "context switches, against {baseline_voluntary} and {baseline_involuntary} for "
        "{baseline} (median of {n_rounds} rounds)."
    ),
    "page_faults": (
        "{subject} had {subject_major} major and {subject_minor} minor page faults, against "
        "{baseline_major} and {baseline_minor} for {baseline} (median of {n_rounds} rounds)."
    ),
    "instructions": (
        "{subject} retired {subject_value} instructions against {baseline_value} for "
        "{baseline}, a ratio of {ratio}."
    ),
    "instructions_per_cycle": (
        "{subject} ran {subject_value} instructions per cycle against {baseline_value} "
        "for {baseline}."
    ),
    "cache_misses": (
        "{subject} had {subject_value} cache misses against {baseline_value} for "
        "{baseline}, a ratio of {ratio}."
    ),
    "branch_misses": (
        "{subject} had {subject_value} branch misses against {baseline_value} for "
        "{baseline}, a ratio of {ratio}."
    ),
    "top_function_share": (
        "The function with the largest share of samples on {subject} is {function}, "
        "with {subject_share} of samples against {baseline_share} on {baseline} "
        "(instrument {instrument})."
    ),
    "top_object_share": (
        "The shared object with the largest share of samples on {subject} is {object}, "
        "with {subject_share} of samples against {baseline_share} on {baseline}."
    ),
    "objects_on_one_side": (
        "{subject_count} shared objects were loaded by {subject} and not by {baseline}, "
        "and {baseline_count} by {baseline} and not by {subject}: {names}."
    ),
    "objects_differ": (
        "{count} shared objects have the same name on {subject} and {baseline} and a "
        "build id that differs: {names}."
    ),
}

# The counted events whose finding compares one count.
_COUNT_FINDINGS: Final[Mapping[str, str]] = {
    "instructions": "instructions",
    "cache_misses": "cache-misses",
    "branch_misses": "branch-misses",
}
# How many names a sentence lists before it says how many more there are.
NAMES_SHOWN: Final = 5
_MIB: Final = 1024.0 * 1024.0
# The reason a case gets when one of its values is zero or less.
_NONPOSITIVE: Final = "nonpositive_value"


def _decimal(value: float, places: int) -> str:
    """Write a value with a fixed number of decimals; a small value keeps two significant digits."""
    if value != 0 and abs(value) < 10.0**-places:
        return f"{value:.2g}"
    text = f"{value:.{places}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def _count(value: float) -> str:
    """Write a count: a whole number as it is, a median between two counts with one decimal."""
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _names(names: Sequence[str]) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    more = len(names) - NAMES_SHOWN
    return f"{shown}, and {more} more" if more > 0 else shown


def _add(
    out: list[Finding],
    left_out: list[str] | None,
    finding_id: str,
    evidence: Mapping[str, Any],
    **words: Any,
) -> None:
    """Add a finding to ``out``, or its id to ``left_out`` when its text would use a word
    findings never use (such a word can only come from a name the user chose)."""
    text = TEMPLATES[finding_id].format(**words)
    if forbidden_words(text):
        if left_out is not None:
            left_out.append(finding_id)
        return
    out.append(Finding(id=finding_id, text=text, evidence=evidence))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rows of the document
# ---------------------------------------------------------------------------


def resource_rows(results: Results, sides: Iterable[str] | None = None) -> tuple[ResourceRow, ...]:
    """Return the resource rows: one per ``res/`` comparison of the results.

    ``sides`` limits the rows to comparisons whose subject and baseline are
    among them. Rows follow the order of the comparisons in the results.
    """
    wanted = None if sides is None else set(sides)
    return tuple(
        ResourceRow(
            case=c.case,
            subject=c.subject,
            baseline=c.baseline,
            subject_median=c.subject_median,
            baseline_median=c.baseline_median,
            outcome=c.outcome,
        )
        for c in results.comparisons
        if c.case in RESOURCE_CASES
        and (wanted is None or (c.subject in wanted and c.baseline in wanted))
    )


def counter_rows(
    subject: str,
    baseline: str,
    subject_counts: Mapping[str, float] | None,
    baseline_counts: Mapping[str, float] | None,
) -> tuple[CounterRow, ...]:
    """Return one row per counted event for a subject against the baseline.

    A side whose ``counters`` launch did not run gives ``None``; when
    neither side ran it there are no rows. An event a side's machine did not
    count has the value ``None`` on that side: it is left out and named. The
    ratio is the subject's count over the baseline's, and ``None`` where one
    is missing, the baseline's is zero, or the quotient is too large for a
    number.
    """
    if subject_counts is None and baseline_counts is None:
        return ()
    rows: list[CounterRow] = []
    for event in COUNTER_EVENTS:
        own = None if subject_counts is None else subject_counts.get(event)
        other = None if baseline_counts is None else baseline_counts.get(event)
        ratio = own / other if own is not None and other else None
        if ratio is not None and not math.isfinite(ratio):
            ratio = None
        rows.append(
            CounterRow(
                event=event,
                subject=subject,
                baseline=baseline,
                subject_value=own,
                baseline_value=other,
                ratio=ratio,
            )
        )
    return tuple(rows)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _comparisons(results: Results, subject: str, baseline: str) -> dict[str, Comparison]:
    return {
        c.case: c
        for c in results.comparisons
        if c.case in RESOURCE_CASES and c.subject == subject and c.baseline == baseline
    }


def _differs(c: Comparison) -> bool:
    """Say whether a case differs: it came out ``higher`` or ``lower``, or a value of zero
    or less gave it no verdict while its two medians differ."""
    if c.outcome in ("higher", "lower"):
        return True
    zero = c.reason == _NONPOSITIVE or _NONPOSITIVE in c.reasons
    return c.outcome == "no_verdict" and zero and c.subject_median != c.baseline_median


def _medians(found: Mapping[str, Comparison], *cases: str) -> list[tuple[float, float]] | None:
    """Return the medians of the cases, or ``None`` unless every one exists and one differs."""
    picked = [found.get(case) for case in cases]
    if any(c is None or c.subject_median is None or c.baseline_median is None for c in picked):
        return None
    if not any(c is not None and _differs(c) for c in picked):
        return None
    return [(c.subject_median, c.baseline_median) for c in picked if c is not None]  # type: ignore[misc]


def _evidence(found: Mapping[str, Comparison], *cases: str) -> dict[str, Any]:
    if len(cases) == 1:
        c = found[cases[0]]
        return {
            "case": c.case,
            "subject_median": c.subject_median,
            "baseline_median": c.baseline_median,
            "n_rounds": c.n_rounds,
        }
    return {
        "cases": list(cases),
        "subject_medians": {case: found[case].subject_median for case in cases},
        "baseline_medians": {case: found[case].baseline_median for case in cases},
        "n_rounds": found[cases[0]].n_rounds,
    }


def resource_findings(
    results: Results, subject: str, baseline: str, *, left_out: list[str] | None = None
) -> list[Finding]:
    """Return the findings made from the resource comparisons of a subject against the baseline.

    The id of a finding whose text would use a word findings never use is
    added to ``left_out``.
    """
    found = _comparisons(results, subject, baseline)
    out: list[Finding] = []
    pair = {"subject": subject, "baseline": baseline}

    medians = _medians(found, CASE_RES_CORES)
    if medians:
        (own, other) = medians[0]
        _add(
            out,
            left_out,
            "cores_used",
            _evidence(found, CASE_RES_CORES),
            subject_value=_decimal(own, 1),
            baseline_value=_decimal(other, 1),
            n_rounds=found[CASE_RES_CORES].n_rounds,
            **pair,
        )
    medians = _medians(found, CASE_RES_USER, CASE_RES_SYS)
    if medians:
        (own_user, other_user), (own_sys, other_sys) = medians
        _add(
            out,
            left_out,
            "cpu_time_split",
            _evidence(found, CASE_RES_USER, CASE_RES_SYS),
            subject_user=_decimal(own_user, 3),
            subject_sys=_decimal(own_sys, 3),
            baseline_user=_decimal(other_user, 3),
            baseline_sys=_decimal(other_sys, 3),
            n_rounds=found[CASE_RES_USER].n_rounds,
            **pair,
        )
    medians = _medians(found, CASE_RES_RSS_PEAK)
    if medians:
        (own, other) = medians[0]
        _add(
            out,
            left_out,
            "peak_memory",
            _evidence(found, CASE_RES_RSS_PEAK),
            subject_value=_decimal(own / _MIB, 1),
            baseline_value=_decimal(other / _MIB, 1),
            n_rounds=found[CASE_RES_RSS_PEAK].n_rounds,
            **pair,
        )
    medians = _medians(found, CASE_RES_CTX_VOLUNTARY, CASE_RES_CTX_INVOLUNTARY)
    if medians:
        (own_v, other_v), (own_i, other_i) = medians
        _add(
            out,
            left_out,
            "context_switches",
            _evidence(found, CASE_RES_CTX_VOLUNTARY, CASE_RES_CTX_INVOLUNTARY),
            subject_voluntary=_count(own_v),
            subject_involuntary=_count(own_i),
            baseline_voluntary=_count(other_v),
            baseline_involuntary=_count(other_i),
            n_rounds=found[CASE_RES_CTX_VOLUNTARY].n_rounds,
            **pair,
        )
    medians = _medians(found, CASE_RES_FAULTS_MAJOR, CASE_RES_FAULTS_MINOR)
    if medians:
        (own_major, other_major), (own_minor, other_minor) = medians
        _add(
            out,
            left_out,
            "page_faults",
            _evidence(found, CASE_RES_FAULTS_MAJOR, CASE_RES_FAULTS_MINOR),
            subject_major=_count(own_major),
            subject_minor=_count(own_minor),
            baseline_major=_count(other_major),
            baseline_minor=_count(other_minor),
            n_rounds=found[CASE_RES_FAULTS_MAJOR].n_rounds,
            **pair,
        )
    return out


def counter_findings(
    rows: Sequence[CounterRow], *, left_out: list[str] | None = None
) -> list[Finding]:
    """Return the findings made from the counter rows of one subject against the baseline.

    The id of a finding whose text would use a word findings never use is
    added to ``left_out``.
    """
    by_event = {row.event: row for row in rows}
    out: list[Finding] = []
    if not rows:
        return out
    subject, baseline = rows[0].subject, rows[0].baseline
    pair = {"subject": subject, "baseline": baseline}
    for finding_id in ("instructions", "instructions_per_cycle", "cache_misses", "branch_misses"):
        if finding_id == "instructions_per_cycle":
            ins, cyc = by_event.get("instructions"), by_event.get("cycles")
            if ins is None or cyc is None:
                continue
            values = (ins.subject_value, cyc.subject_value, ins.baseline_value, cyc.baseline_value)
            if any(v is None for v in values) or not cyc.subject_value or not cyc.baseline_value:
                continue
            own = ins.subject_value / cyc.subject_value  # type: ignore[operator]
            other = ins.baseline_value / cyc.baseline_value  # type: ignore[operator]
            _add(
                out,
                left_out,
                finding_id,
                {
                    "events": ["instructions", "cycles"],
                    "subject_values": {
                        "instructions": ins.subject_value,
                        "cycles": cyc.subject_value,
                    },
                    "baseline_values": {
                        "instructions": ins.baseline_value,
                        "cycles": cyc.baseline_value,
                    },
                    "subject_ipc": own,
                    "baseline_ipc": other,
                },
                subject_value=_decimal(own, 2),
                baseline_value=_decimal(other, 2),
                **pair,
            )
            continue
        row = by_event.get(_COUNT_FINDINGS[finding_id])
        if row is None or row.subject_value is None or row.ratio is None:
            continue
        _add(
            out,
            left_out,
            finding_id,
            {
                "event": row.event,
                "subject_value": row.subject_value,
                "baseline_value": row.baseline_value,
                "ratio": row.ratio,
            },
            subject_value=_count(row.subject_value),
            baseline_value=_count(row.baseline_value),  # type: ignore[arg-type]
            ratio=_decimal(row.ratio, 2),
            **pair,
        )
    return out


def _share_of(counts: Mapping[Any, int], key: Any, total: int) -> float:
    return counts.get(key, 0) / total if total else 0.0


def stack_findings(
    subject: str,
    baseline: str,
    subject_profile: Profile,
    baseline_profile: Profile,
    *,
    left_out: list[str] | None = None,
) -> list[Finding]:
    """Return the findings made from the sampled stacks of a subject and the baseline.

    Nothing is made unless both were sampled by the same instrument and the
    subject has samples. The object findings need ``stacks`` on both sides
    and a list of loaded objects on both. The id of a finding whose text
    would use a word findings never use is added to ``left_out``.
    """
    out: list[Finding] = []
    if subject_profile.instrument != baseline_profile.instrument or not subject_profile.samples:
        return out
    pair = {"subject": subject, "baseline": baseline}
    total_own, total_other = subject_profile.samples, baseline_profile.samples

    leaf, count = sorted(
        subject_profile.leaves.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or "")
    )[0]
    own_share = count / total_own
    other_share = _share_of(baseline_profile.leaves, leaf, total_other)
    _add(
        out,
        left_out,
        "top_function_share",
        {
            "function": leaf[0],
            "object": leaf[1],
            "instrument": subject_profile.instrument,
            "subject_share": own_share,
            "baseline_share": other_share,
            "subject_samples": total_own,
            "baseline_samples": total_other,
        },
        function=leaf[0],
        subject_share=_percent(own_share),
        baseline_share=_percent(other_share),
        instrument=subject_profile.instrument,
        **pair,
    )
    if subject_profile.instrument != "stacks":
        return out

    def by_object(profile: Profile) -> dict[str, int]:
        counts: dict[str, int] = {}
        for (_name, obj), n in profile.leaves.items():
            if obj is not None:
                counts[obj] = counts.get(obj, 0) + n
        return counts

    own_objects, other_objects = by_object(subject_profile), by_object(baseline_profile)
    if own_objects:
        obj, n = sorted(own_objects.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        own_share = n / total_own
        other_share = _share_of(other_objects, obj, total_other)
        _add(
            out,
            left_out,
            "top_object_share",
            {
                "object": obj,
                "subject_share": own_share,
                "baseline_share": other_share,
                "subject_samples": total_own,
                "baseline_samples": total_other,
            },
            object=obj,
            subject_share=_percent(own_share),
            baseline_share=_percent(other_share),
            **pair,
        )
    if not subject_profile.objects or not baseline_profile.objects:
        return out
    own_loaded, other_loaded = set(subject_profile.objects), set(baseline_profile.objects)
    own_only, other_only = sorted(own_loaded - other_loaded), sorted(other_loaded - own_loaded)
    if own_only or other_only:
        _add(
            out,
            left_out,
            "objects_on_one_side",
            {"subject_only": own_only, "baseline_only": other_only},
            subject_count=len(own_only),
            baseline_count=len(other_only),
            names=_names([*own_only, *other_only]),
            **pair,
        )
    differ = sorted(
        name
        for name in own_loaded & other_loaded
        if subject_profile.objects[name] != baseline_profile.objects[name]
    )
    if differ:
        _add(
            out,
            left_out,
            "objects_differ",
            {
                "objects": differ,
                "subject_build_ids": {n: list(subject_profile.objects[n]) for n in differ},
                "baseline_build_ids": {n: list(baseline_profile.objects[n]) for n in differ},
            },
            count=len(differ),
            names=_names(differ),
            **pair,
        )
    return out
