# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The verdict rule, applied to the plain values of an experiment.

``grade`` takes a ``Grid``: the values of every lineup entry on every case,
round by round, the recorded positions, the twins and the cases. It returns
every comparison of every subject with the baseline, graded under a
``pairbench.model.Rule``, and every side compared with its own twin. It works
on numbers only, so the analysis of captures and the simulation of error
rates grade by the same code.

Every option of the rule is honoured:

* ``scale``: the median of the per-round ratios, or of the per-round percent
  differences ``100 * (S - B) / B``; floors, bars and gaps are in the unit of
  the scale;
* ``floor_scope``: the floor of the case's group, of the case alone, the
  largest of the side, or the largest of the experiment;
* ``bar``: the sum of both floors, twice the larger, or twice the experiment
  floor; ``bar_round_digits`` rounds each floor first;
* ``require_both_floors``, ``p_source``, ``alpha``, ``p_inclusive``,
  ``gap_inclusive``, ``tie`` and ``min_rounds``.

A comparison that cannot be graded is no verdict, with every reason that
applies listed in the order of ``REASONS_NO_VERDICT`` and the first of them
as the main reason. Values so far apart that the comparison's ratio, the
statistic it grades, a floor it uses or its bar is no finite number give the
reason ``too_far_apart``; that number is then left unset. A ratio counts as
a finite number only when it is above zero and its inverse and its percent
difference are finite numbers too (``stats.floor.usable_ratio``), and a
floor or a bar only when it is a finite number as a percentage. A median of
a side's values that is no finite number is left unset too and changes no
verdict. After the table, a verdict is downgraded to unresolved
when one side ran first more than three times as often as the other
(``order_unbalanced``), or when the verdict changes once the disturbed
rounds are set aside (``sensitive_to_disturbed_rounds``). Setting rounds
aside can never produce or upgrade a verdict.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from pairbench.model import (
    REASONS_NO_VERDICT,
    REASONS_UNRESOLVED,
    Case,
    FloorMode,
    Floors,
    NotComputed,
    Outcome,
    PlanRow,
    Reason,
    Rule,
    count_balance,
    direction_outcome,
    exact_alpha,
    min_rounds,
)
from pairbench.stats.floor import (
    NEUTRAL,
    FloorStat,
    case_floor,
    combine_floors,
    median,
    pair_rounds,
    per_pair,
    sign_counts,
    supplied_floor,
    usable_ratio,
    writable_floor,
)
from pairbench.stats.holm import holm, holm_exact
from pairbench.stats.signtest import sign_test

# The outcomes the table gives that are verdicts. The downgrades act on these.
VERDICT_OUTCOMES: frozenset[str] = frozenset({"better", "worse", "higher", "lower", "tie"})
# A side whose combined check against its own twin has a p-value below
# this, once corrected with Holm's method across the sides of the run that
# have one, gets a loud note. The check compares the exact corrected
# fraction with exactly 1/20.
TWIN_NOTE_ALPHA = 0.05
# One side running first more than this many times as often as the other
# downgrades a verdict.
UNBALANCED_FACTOR = 3

_EMPTY: Mapping[int, float] = {}


def group_key(case: Case) -> tuple[str, ...]:
    """Return the floor group of a case.

    A case that names a group belongs to it. Every other case belongs to the
    group of all cases that share its metric and its role, primary or
    secondary.
    """
    if case.group is not None:
        return ("group", case.group)
    return ("metric", case.metric, "primary" if case.primary else "secondary")


def is_significant(p: float | Fraction, rule: Rule) -> bool:
    """Say whether a p-value is significant: ``p < alpha``, or ``p <= alpha`` when inclusive.

    A ``Fraction`` is compared exactly with ``exact_alpha(rule.alpha)``, so
    ``0.05`` means exactly ``1/20``; every p-value a verdict is decided on is
    one. A float is compared as a float with the float alpha.
    """
    if isinstance(p, Fraction):
        alpha = exact_alpha(rule.alpha)
        return p <= alpha if rule.p_inclusive else p < alpha
    return p <= rule.alpha if rule.p_inclusive else p < rule.alpha


def is_outside(gap: float, bar: float, rule: Rule) -> bool:
    """Say whether a gap lies outside the bar: ``gap > bar``, or ``gap >= bar`` when inclusive."""
    return gap >= bar if rule.gap_inclusive else gap > bar


def rounded(value: float, rule: Rule) -> float:
    """Return a floor as it enters the bar: rounded to ``bar_round_digits`` when that is set."""
    return value if rule.bar_round_digits is None else round(value, rule.bar_round_digits)


def is_zero_floor(value: float, rule: Rule) -> bool:
    """Say whether a floor is exactly zero, as measured or as rounded for the bar."""
    return value == 0.0 or rounded(value, rule) == 0.0


def form_bar(
    rule: Rule, subject: float | None, baseline: float | None, experiment: float | None
) -> float | None:
    """Return the bar a gap must exceed, or ``None`` when it cannot be formed.

    ``sum_of_both``: the subject's floor plus the baseline's. ``twice_larger``:
    twice the larger of the two. ``twice_experiment_max``: twice the
    experiment floor. A missing floor adds nothing.
    """
    if rule.bar == "twice_experiment_max":
        return None if experiment is None else 2.0 * rounded(experiment, rule)
    present = [rounded(v, rule) for v in (subject, baseline) if v is not None]
    if not present:
        return None
    if rule.bar == "sum_of_both":
        return sum(present)
    return 2.0 * max(present)


def table(
    rule: Rule, statistic: float, gap: float, bar: float, p: float | Fraction, better: str
) -> tuple[Outcome, Reason | None]:
    """Grade one comparison by the verdict table of the rule.

    Outside the bar and significant: the direction of the statistic, judged
    by ``better`` (``direction_outcome``). Outside and not significant:
    unresolved (``not_significant``). Inside the bar: a tie, or unresolved
    (``inside_noise``) as the rule's ``tie`` option says.
    """
    significant = is_significant(p, rule)
    neutral = NEUTRAL[rule.scale]
    if is_outside(gap, bar, rule) and statistic != neutral:
        if not significant:
            return "unresolved", "not_significant"
        return direction_outcome("lower" if statistic < neutral else "higher", better), None
    if rule.tie == "never":
        return "unresolved", "inside_noise"
    if rule.tie == "inside" or not significant:
        return "tie", None
    return "unresolved", "inside_noise"


def in_order(reasons: Iterable[str], order: Sequence[str]) -> tuple[Reason, ...]:
    """Return the reasons that apply, each once, in the order given."""
    found = set(reasons)
    return tuple(r for r in order if r in found)  # type: ignore[misc]


def is_unbalanced(order_split: tuple[int, int]) -> bool:
    """Say whether one side ran first more than three times as often as the other."""
    first, second = order_split
    return max(first, second) > UNBALANCED_FACTOR * min(first, second)


@dataclass(frozen=True)
class Grid:
    """The plain values of an experiment.

    ``rounds`` are the rounds analysed, ascending; several captures pooled
    are numbered across the captures. ``values`` maps ``(entry, case)`` to
    the entry's value in each round. ``positions`` maps ``(round, entry)``
    to the position the entry ran in, or ``None`` where no order was
    recorded. ``twins`` maps a side to its twin entry. ``disturbed`` names
    the rounds set aside as disturbed.
    """

    rounds: tuple[int, ...]
    values: Mapping[tuple[str, str], Mapping[int, float]]
    positions: Mapping[tuple[int, str], int | None]
    subjects: tuple[str, ...]
    baseline: str
    twins: Mapping[str, str]
    cases: tuple[Case, ...]
    disturbed: tuple[int, ...] = ()

    def of(self, entry: str, case: str) -> Mapping[int, float]:
        """Return the values of one entry on one case, by round."""
        return self.values.get((entry, case), _EMPTY)

    def keeping(self, rounds: Iterable[int]) -> Grid:
        """Return the same grid restricted to the rounds given."""
        keep = set(rounds)
        return dataclasses.replace(self, rounds=tuple(r for r in self.rounds if r in keep))


@dataclass(frozen=True)
class GradedSensitivity:
    """The comparison repeated without the disturbed rounds, or why it was not repeated."""

    rounds_set_aside: tuple[int, ...] = ()
    ratio: float | None = None
    outcome: Outcome | None = None
    agrees: bool | None = None
    not_computed: NotComputed | None = None


@dataclass(frozen=True)
class Graded:
    """One case compared between a subject and the baseline, graded.

    ``subject_floor`` and ``baseline_floor`` are the floors the rule used,
    after its scope; ``None`` where the side has no twin, or no supplied
    floor. ``p_corrected`` is set for a primary comparison in the
    correction family only.
    """

    case: Case
    subject: str
    baseline: str
    n_rounds: int
    n_unpaired: int
    n_untied: int
    n_lower: int
    n_higher: int
    subject_median: float | None
    baseline_median: float | None
    ratio: float | None
    statistic: float | None
    gap: float | None
    subject_floor: FloorStat | None
    baseline_floor: FloorStat | None
    source: Literal["twins", "supplied"]
    mode: FloorMode
    bar: float | None
    p_raw: float | None
    p_fraction: tuple[int, int] | None
    p_corrected: float | None
    outcome: Outcome
    reason: Reason | None
    reasons: tuple[Reason, ...]
    order_split: tuple[int, int]
    sensitivity: GradedSensitivity = field(default_factory=GradedSensitivity)


@dataclass(frozen=True)
class TwinRow:
    """A side compared with its own twin on one case. ``floor`` is in the unit of the scale."""

    side: str
    case: str
    ratio: float | None
    floor: float | None
    p_raw: float | None
    n: int


@dataclass(frozen=True)
class TwinSideCheck:
    """A side compared with its own twin over its primary cases combined, round by round.

    In each round the side's score is the median over the primary cases on
    which the side and its twin both have a finite value above zero: each
    gives the log of the side's value over its twin's, turned so that a
    positive score means the side looks better by the case's better
    direction. An odd number of cases gives the log in the middle and an even
    number the mean of the two in the middle, so one case gives its own log
    and two give their mean. ``n_rounds`` counts the rounds scored,
    ``n_better`` and ``n_worse`` the rounds whose score lies above and below
    zero; a score of zero is a tie. The order of the cases and the sign of a
    score are found exactly, so swapping a side and its twin in one round
    turns that round's score the other way and leaves the others, and
    swapping them in every round swaps ``n_better`` and ``n_worse``.
    ``p_raw`` is the exact sign test of those rounds, ``None`` when at most
    one round was scored, and ``p_fraction`` the same value as an exact
    fraction ``(numerator, denominator)``; ``p_corrected`` is ``p_raw``
    corrected with Holm's method across the sides that have one, and
    ``p_corrected_exact`` the same correction of the exact fractions, which
    the note is decided on.
    """

    side: str
    n_rounds: int
    n_better: int
    n_worse: int
    p_raw: float | None
    p_corrected: float | None = None
    p_fraction: tuple[int, int] | None = None
    p_corrected_exact: Fraction | None = None


@dataclass(frozen=True)
class Grading:
    """Every comparison of an experiment, graded, and what the notes of the results need.

    ``family_size`` is the number of comparisons in the correction family:
    the primary comparisons that have a p-value. ``tests`` is the number of
    subjects times the number of primary cases, the ``m`` of the fewest
    rounds that can give a verdict; ``needed`` is that fewest number.
    ``busy`` says more than half of the rounds were disturbed.
    ``twin_checks`` holds one combined check per side that has a twin, in
    the order of ``Grid.twins``.
    """

    comparisons: tuple[Graded, ...]
    same_vs_same: tuple[TwinRow, ...]
    family_size: int
    tests: int
    needed: int
    busy: bool = False
    twin_checks: tuple[TwinSideCheck, ...] = ()

    def twin_family_size(self) -> int:
        """Return the number of sides the correction of the twin note covers."""
        return sum(1 for check in self.twin_checks if check.p_raw is not None)

    def twin_differs(self) -> tuple[TwinSideCheck, ...]:
        """Return the sides whose combined check has a corrected p-value below 0.05.

        The exact corrected fraction is compared with exactly 1/20; a check
        built without one compares its float.
        """
        return tuple(check for check in self.twin_checks if _twin_note_due(check))

    def provisional(self) -> bool:
        """Say whether a comparison used a floor computed from fewer than eight rounds."""
        return any(
            f is not None and f.provisional
            for c in self.comparisons
            for f in (c.subject_floor, c.baseline_floor)
        )

    def one_sided(self) -> tuple[Graded, ...]:
        """Return the comparisons graded with the floor of one side only."""
        return tuple(c for c in self.comparisons if c.mode == "ONE-SIDED" and c.bar is not None)


@dataclass
class _Measured:
    case: Case
    subject: str
    n_rounds: int
    n_unpaired: int
    n_lower: int
    n_higher: int
    subject_median: float | None
    baseline_median: float | None
    ratio: float | None
    statistic: float | None
    gap: float | None
    p_raw: float | None
    p_fraction: tuple[int, int] | None
    order_split: tuple[int, int]
    order_missing: bool
    nonpositive: bool
    p_corrected: float | None = None
    p_corrected_exact: Fraction | None = None
    far_apart: bool = False

    def p_exact(self) -> Fraction | None:
        """Return the raw p-value as an exact fraction, or ``None`` without one."""
        return None if self.p_fraction is None else Fraction(*self.p_fraction)


class _Floors:
    """The floors of every side the rule may use, computed once per grading."""

    def __init__(self, grid: Grid, rule: Rule, supplied: Floors | None) -> None:
        self.grid = grid
        self.rule = rule
        self.supplied = supplied
        self.by_case: dict[tuple[str, str], FloorStat] = {}
        if supplied is None:
            for side, twin in grid.twins.items():
                for case in grid.cases:
                    self.by_case[(side, case.id)] = case_floor(
                        grid.of(side, case.id), grid.of(twin, case.id), grid.rounds, rule.scale
                    )
        self._scoped: dict[tuple[str, tuple[str, ...]], FloorStat] = {}
        self._experiment: FloorStat | None = None
        self._experiment_done = False

    def group(self, side: str, case: Case) -> FloorStat:
        """Return the floor of a side over the group of a case; a value of zero or less wins."""
        key = group_key(case)
        cached = self._scoped.get((side, key))
        if cached is None:
            members = [c for c in self.grid.cases if group_key(c) == key]
            cached = combine_floors(self.by_case[(side, c.id)] for c in members)
            self._scoped[(side, key)] = cached
        return cached

    def used(self, side: str, case: Case) -> FloorStat | None:
        """Return the floor the rule uses for a side on a case, or ``None`` when it has none.

        A value of zero or less in a round a side shares with its twin leaves
        the side without a floor for the group of that case, under every
        scope. The floors of a whole side and of the experiment are the
        largest over the cases that still have one, so such a value touches
        no case of another group.
        """
        if self.supplied is not None:
            return supplied_floor(self.supplied.for_side(side), self.rule.scale)
        if side not in self.grid.twins:
            return None
        own = self.group(side, case)
        if own.nonpositive:
            return own
        scope = self.rule.floor_scope
        if scope == "case":
            return self.by_case[(side, case.id)]
        if scope == "group":
            return own
        if scope == "experiment":
            return self.experiment()
        key = ("side",)
        cached = self._scoped.get((side, key))
        if cached is None:
            cached = combine_floors(
                f for (s, _), f in self.by_case.items() if s == side and not f.nonpositive
            )
            self._scoped[(side, key)] = cached
        return cached

    def experiment(self) -> FloorStat | None:
        """Return the experiment floor: the largest over every side and case, or ``None``.

        A case whose floor a value of zero or less took away is left out of it.
        """
        if not self._experiment_done:
            self._experiment_done = True
            if self.supplied is not None:
                names = (*self.grid.subjects, self.grid.baseline)
                given = [v for v in (self.supplied.for_side(n) for n in names) if v is not None]
                self._experiment = supplied_floor(max(given), self.rule.scale) if given else None
            elif self.grid.twins:
                self._experiment = combine_floors(
                    f for f in self.by_case.values() if not f.nonpositive
                )
        return self._experiment


def _twin_note_due(check: TwinSideCheck) -> bool:
    """Say whether a side's corrected check against its twin lies below 0.05."""
    if check.p_corrected_exact is not None:
        return check.p_corrected_exact < exact_alpha(TWIN_NOTE_ALPHA)
    return check.p_corrected is not None and check.p_corrected < TWIN_NOTE_ALPHA


def _present(stat: FloorStat | None) -> bool:
    return stat is not None and (stat.value is not None or stat.nonpositive or stat.far_apart)


def _finite(value: float) -> float | None:
    """Return a number, or ``None`` when it is no finite number."""
    return value if math.isfinite(value) else None


def _usable(stat: FloorStat | None) -> float | None:
    return None if stat is None else stat.value


def _plan_rows(grid: Grid) -> dict[str, tuple[PlanRow, ...]]:
    """Return, per lineup entry, a plan row for every round in which its position is recorded."""
    rows: dict[str, list[PlanRow]] = {}
    for (r, entry), pos in grid.positions.items():
        if pos is not None:
            rows.setdefault(entry, []).append(PlanRow(round=r, pos=pos, name=entry, side=entry))
    return {entry: tuple(found) for entry, found in rows.items()}


def _order(
    grid: Grid, rows: Mapping[str, tuple[PlanRow, ...]], subject: str, got: Sequence[int]
) -> tuple[tuple[int, int], bool]:
    """Count how often the subject and the baseline ran first over the paired rounds.

    The second value says a paired round lacks the position of either side.
    """
    paired_rounds = set(got)
    missing = any(
        grid.positions.get((r, subject)) is None or grid.positions.get((r, grid.baseline)) is None
        for r in got
    )
    kept = [
        row
        for entry in (subject, grid.baseline)
        for row in rows.get(entry, ())
        if row.round in paired_rounds
    ]
    balance = count_balance(kept, [(subject, grid.baseline)])[0]
    return (balance.a_first, balance.b_first), missing


def _measure(
    grid: Grid,
    rule: Rule,
    subject: str,
    case: Case,
    nonpositive: bool,
    rows: Mapping[str, tuple[PlanRow, ...]],
) -> _Measured:
    s_values = grid.of(subject, case.id)
    b_values = grid.of(grid.baseline, case.id)
    rounds = grid.rounds
    got, xs, ys = pair_rounds(s_values, b_values, rounds)
    s_all = [s_values[r] for r in rounds if r in s_values]
    b_all = [b_values[r] for r in rounds if r in b_values]
    (first, second), missing = _order(grid, rows, subject, got)
    measured = _Measured(
        case=case,
        subject=subject,
        n_rounds=len(got),
        n_unpaired=len(rounds) - len(got),
        n_lower=0,
        n_higher=0,
        subject_median=_finite(median(s_all)) if s_all else None,
        baseline_median=_finite(median(b_all)) if b_all else None,
        ratio=None,
        statistic=None,
        gap=None,
        p_raw=None,
        p_fraction=None,
        order_split=(first, second),
        order_missing=missing,
        nonpositive=nonpositive,
    )
    if nonpositive or not got:
        return measured
    ratios = per_pair(xs, ys, "ratio")
    ratio = median(ratios)
    quantities = ratios if rule.scale == "ratio" else per_pair(xs, ys, rule.scale)
    statistic = ratio if rule.scale == "ratio" else median(quantities)
    measured.ratio = usable_ratio(ratio)
    if measured.ratio is not None if rule.scale == "ratio" else math.isfinite(statistic):
        measured.statistic = statistic
        measured.gap = abs(statistic - NEUTRAL[rule.scale])
    measured.far_apart = measured.ratio is None or measured.statistic is None
    measured.n_lower, measured.n_higher = sign_counts(xs, ys, quantities, rule.scale)
    if len(got) > 1:
        test = sign_test(measured.n_lower, measured.n_higher)
        measured.p_raw = test.p
        measured.p_fraction = test.fraction
    return measured


def _nonpositive_cases(grid: Grid) -> set[str]:
    """Return the cases on which a subject or the baseline recorded a value of zero or less."""
    found: set[str] = set()
    rounds = set(grid.rounds)
    for case in grid.cases:
        for side in (*grid.subjects, grid.baseline):
            values = grid.of(side, case.id)
            if any(v <= 0 for r, v in values.items() if r in rounds):
                found.add(case.id)
                break
    return found


def _grade_one(
    m: _Measured,
    grid: Grid,
    rule: Rule,
    floors: _Floors,
    *,
    needed: int,
    control_failed: bool,
    assume_interleaved: bool,
) -> Graded:
    case = m.case
    fs = floors.used(m.subject, case)
    fb = floors.used(grid.baseline, case)
    fe = floors.experiment() if rule.bar == "twice_experiment_max" else None
    reasons: set[str] = set()
    if control_failed:
        reasons.add("positive_control_failed")
    nonpositive_floor = any(f is not None and f.nonpositive for f in (fs, fb, fe))
    if m.nonpositive or nonpositive_floor:
        reasons.add("nonpositive_value")
    if m.far_apart or any(f is not None and f.far_apart for f in (fs, fb, fe)):
        reasons.add("too_far_apart")
    if m.n_rounds == 1:
        reasons.add("single_measurement")
    if m.order_missing and not assume_interleaved:
        reasons.add("order_not_recorded")
    if m.n_rounds < needed:
        reasons.add("too_few_rounds")
    s_present, b_present = _present(fs), _present(fb)
    if not s_present and not b_present:
        reasons.add("no_floor")
    elif s_present != b_present and rule.require_both_floors:
        reasons.add("one_sided_floor")
    zero_candidates = [_usable(fs), _usable(fb)]
    if rule.bar == "twice_experiment_max":
        zero_candidates.append(_usable(fe))
    if any(v is not None and is_zero_floor(v, rule) for v in zero_candidates):
        reasons.add("zero_floor")
    s_value, b_value = _usable(fs), _usable(fb)
    usable = (s_value is not None) + (b_value is not None)
    mode: FloorMode = "TWO-SIDED" if usable == 2 else "ONE-SIDED" if usable == 1 else "NONE"
    bar: float | None = None
    # A rule that needs both floors forms no bar from one, also when the other
    # floor is present but lost to a value of zero or less.
    both_or_allowed = usable == 2 or not rule.require_both_floors
    if not reasons & {"no_floor", "one_sided_floor"} and usable and both_or_allowed:
        bar = form_bar(rule, s_value, b_value, _usable(fe))
        if bar is not None and not writable_floor(bar, rule.scale):
            bar = None
            reasons.add("too_far_apart")
    # The verdict is decided on the exact fraction: the Holm-corrected one, or
    # the raw one. The floats written to the results are not compared.
    corrected = case.primary and rule.p_source == "corrected"
    p_used = m.p_corrected_exact if corrected else m.p_exact()
    outcome: Outcome
    reason: Reason | None
    listed: tuple[Reason, ...]
    if reasons:
        listed = in_order(reasons, REASONS_NO_VERDICT)
        outcome, reason = "no_verdict", listed[0]
    elif bar is None or p_used is None or m.statistic is None or m.gap is None:
        listed = in_order(("too_few_rounds",), REASONS_NO_VERDICT)
        outcome, reason = "no_verdict", listed[0]
    else:
        outcome, reason = table(rule, m.statistic, m.gap, bar, p_used, case.better)
        unbalanced = is_unbalanced(m.order_split)
        if outcome in VERDICT_OUTCOMES and unbalanced:
            outcome, reason = "unresolved", "order_unbalanced"
            listed = ("order_unbalanced",)
        elif outcome == "unresolved":
            extra = [r for r in (reason, "order_unbalanced" if unbalanced else None) if r]
            listed = in_order(extra, REASONS_UNRESOLVED)
        else:
            listed = ()
    return Graded(
        case=case,
        subject=m.subject,
        baseline=grid.baseline,
        n_rounds=m.n_rounds,
        n_unpaired=m.n_unpaired,
        n_untied=m.n_lower + m.n_higher,
        n_lower=m.n_lower,
        n_higher=m.n_higher,
        subject_median=m.subject_median,
        baseline_median=m.baseline_median,
        ratio=m.ratio,
        statistic=m.statistic,
        gap=m.gap,
        subject_floor=fs,
        baseline_floor=fb,
        source="supplied" if floors.supplied is not None else "twins",
        mode=mode,
        bar=bar,
        p_raw=m.p_raw,
        p_fraction=m.p_fraction,
        p_corrected=m.p_corrected,
        outcome=outcome,
        reason=reason,
        reasons=listed,
        order_split=m.order_split,
    )


def needed_rounds(rule: Rule, tests: int) -> int:
    """Return the fewest paired rounds a comparison needs: the rule's own, or ``min_rounds``."""
    if rule.min_rounds is not None:
        return rule.min_rounds
    return min_rounds(max(1, tests), rule.alpha)


def grade(
    grid: Grid,
    rule: Rule,
    *,
    floors: Floors | None = None,
    control_failed: bool = False,
    assume_interleaved: bool = False,
    repeat: bool = True,
) -> Grading:
    """Grade every comparison of an experiment under a rule.

    Every subject is compared with the baseline on every case, in the order
    of ``grid.subjects`` and ``grid.cases``. The correction family is every
    primary comparison that has a p-value; secondary comparisons are graded
    with the uncorrected p-value. ``floors`` replaces the twin-derived floors
    with supplied ones. ``control_failed`` gives every comparison no verdict
    (``positive_control_failed``). ``assume_interleaved`` grades pairs whose
    order was not recorded. With ``repeat``, the comparisons are graded again
    without the disturbed rounds, where enough rounds remain, and a verdict
    that changes is downgraded.
    """
    primary = sum(1 for c in grid.cases if c.primary)
    tests = len(grid.subjects) * primary
    needed = needed_rounds(rule, tests)
    nonpositive = _nonpositive_cases(grid)
    rows = _plan_rows(grid)
    measured = [
        _measure(grid, rule, subject, case, case.id in nonpositive, rows)
        for subject in grid.subjects
        for case in grid.cases
    ]
    family = [m for m in measured if m.case.primary and m.p_raw is not None]
    adjusted = holm([m.p_raw for m in family if m.p_raw is not None])
    exact = holm_exact([p for p in (m.p_exact() for m in family) if p is not None])
    for m, p, p_exact in zip(family, adjusted, exact, strict=True):
        m.p_corrected = p
        m.p_corrected_exact = p_exact
    floor_set = _Floors(grid, rule, floors)
    graded = [
        _grade_one(
            m,
            grid,
            rule,
            floor_set,
            needed=needed,
            control_failed=control_failed,
            assume_interleaved=assume_interleaved,
        )
        for m in measured
    ]
    twins = _twin_rows(grid, rule, floor_set)
    busy = False
    if repeat:
        graded, busy = _with_sensitivity(
            graded,
            grid,
            rule,
            needed=needed,
            floors=floors,
            control_failed=control_failed,
            assume_interleaved=assume_interleaved,
        )
    return Grading(
        comparisons=tuple(graded),
        same_vs_same=twins,
        family_size=len(family),
        tests=tests,
        needed=needed,
        busy=busy,
        twin_checks=_twin_checks(grid),
    )


def _twin_rows(grid: Grid, rule: Rule, floor_set: _Floors) -> tuple[TwinRow, ...]:
    rows: list[TwinRow] = []
    for side, twin in grid.twins.items():
        for case in grid.cases:
            stat = floor_set.by_case.get((side, case.id))
            if stat is None:
                stat = case_floor(
                    grid.of(side, case.id), grid.of(twin, case.id), grid.rounds, rule.scale
                )
            n = stat.n or 0
            # One pair gives no p-value, as for a comparison. A side too far from
            # its twin for a floor still has its rounds below and above it counted.
            p = (
                sign_test(stat.n_lower, stat.n_higher).p
                if (stat.value is not None or stat.far_apart) and n > 1
                else None
            )
            rows.append(
                TwinRow(side=side, case=case.id, ratio=stat.ratio, floor=stat.value, p_raw=p, n=n)
            )
    return tuple(rows)


def _scorable(value: float) -> bool:
    """Say whether a value can enter a round's score: a finite number above zero."""
    return math.isfinite(value) and value > 0.0


# A float's fraction from math.frexp, times this, is a whole number.
_FRACTION_SCALE = float(2**53)


def _product(numbers: list[int]) -> int:
    """Multiply whole numbers in pairs, so that a long list stays quick to multiply."""
    while len(numbers) > 1:
        paired = [a * b for a, b in zip(numbers[::2], numbers[1::2], strict=False)]
        if len(numbers) % 2:
            paired.append(numbers[-1])
        numbers = paired
    return numbers[0] if numbers else 1


def _round_sign(terms: Sequence[tuple[float, float, str]]) -> int:
    """Return the sign of the mean of the turned logs of the ``(side, twin, better)`` values given.

    ``_median_sign`` hands it the middle value of a round, or its two middle
    values, so the sign is that of the round's median. The sign of the mean
    is that of the product of the turned quotients against 1: ``twin / side``
    where lower is better, ``side / twin`` where higher is. Each value is
    split into a whole number and a power of two, and the products are
    compared exactly, so swapping a side and its twin gives the opposite sign
    and a product of exactly 1 is a tie.
    """
    tops: list[int] = []
    bottoms: list[int] = []
    exponent = 0
    for side, twin, better in terms:
        top, bottom = (side, twin) if better == "higher" else (twin, side)
        top_fraction, top_exponent = math.frexp(top)
        bottom_fraction, bottom_exponent = math.frexp(bottom)
        tops.append(int(top_fraction * _FRACTION_SCALE))
        bottoms.append(int(bottom_fraction * _FRACTION_SCALE))
        exponent += top_exponent - bottom_exponent
    above, below = _product(tops), _product(bottoms)
    if exponent >= 0:
        above <<= exponent
    else:
        below <<= -exponent
    return (above > below) - (above < below)


def _turned(term: tuple[float, float, str]) -> Fraction:
    """Return the turned quotient of a ``(side, twin, better)`` value, exactly.

    It is ``twin / side`` where lower is better and ``side / twin`` where
    higher is, so it lies above 1 when the side looks better.
    """
    side, twin, better = term
    top, bottom = (side, twin) if better == "higher" else (twin, side)
    return Fraction(top) / Fraction(bottom)


def _median_sign(terms: list[tuple[float, float, str]]) -> int:
    """Return the sign of the median turned log of a round's ``(side, twin, better)`` values.

    The values are put in order by their exact turned quotients. An odd
    number of them gives the sign of the one in the middle, and an even
    number the sign of the mean of the two in the middle. Swapping a side and
    its twin turns every quotient over and reverses the order, so the same
    values lie in the middle and the sign is the opposite.
    """
    ordered = sorted(terms, key=_turned)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return _round_sign(ordered[middle : middle + 1])
    return _round_sign(ordered[middle - 1 : middle + 1])


def _twin_checks(grid: Grid) -> tuple[TwinSideCheck, ...]:
    """Check each side against its twin over its primary cases combined, then correct.

    A round is scored by the median of the turned logs of the primary cases
    with a better direction on which both have a usable value; a round with
    none is not scored. The p-values of the sides that have one are
    corrected together with Holm's method.
    """
    judged = [c for c in grid.cases if c.primary and c.better in ("lower", "higher")]
    checks: list[TwinSideCheck] = []
    for side, twin in grid.twins.items():
        scored = better = worse = 0
        for r in grid.rounds:
            terms: list[tuple[float, float, str]] = []
            for case in judged:
                s = grid.of(side, case.id).get(r)
                t = grid.of(twin, case.id).get(r)
                if s is not None and t is not None and _scorable(s) and _scorable(t):
                    terms.append((s, t, case.better))
            if not terms:
                continue
            scored += 1
            sign = _median_sign(terms)
            if sign > 0:
                better += 1
            elif sign < 0:
                worse += 1
        # One round gives no p-value, as for a comparison.
        test = sign_test(worse, better) if scored > 1 else None
        checks.append(
            TwinSideCheck(
                side=side,
                n_rounds=scored,
                n_better=better,
                n_worse=worse,
                p_raw=None if test is None else test.p,
                p_fraction=None if test is None else test.fraction,
            )
        )
    tested = [i for i, check in enumerate(checks) if check.p_fraction is not None]
    adjusted = holm([p for p in (checks[i].p_raw for i in tested) if p is not None])
    exact = holm_exact(
        [Fraction(*f) for f in (checks[i].p_fraction for i in tested) if f is not None]
    )
    for i, p_corrected, p_exact in zip(tested, adjusted, exact, strict=True):
        checks[i] = dataclasses.replace(
            checks[i], p_corrected=p_corrected, p_corrected_exact=p_exact
        )
    return tuple(checks)


def _with_sensitivity(
    graded: list[Graded],
    grid: Grid,
    rule: Rule,
    *,
    needed: int,
    floors: Floors | None,
    control_failed: bool,
    assume_interleaved: bool,
) -> tuple[list[Graded], bool]:
    rounds = set(grid.rounds)
    aside = tuple(sorted(set(grid.disturbed) & rounds))
    if not aside:
        same = [
            dataclasses.replace(
                g,
                sensitivity=GradedSensitivity(ratio=g.ratio, outcome=g.outcome, agrees=True),
            )
            for g in graded
        ]
        return same, False
    busy = 2 * len(aside) > len(rounds)
    not_computed: NotComputed | None = None
    if busy:
        not_computed = "too_many_disturbed"
    elif len(rounds) - len(aside) < needed:
        not_computed = "too_few_rounds"
    if not_computed is not None:
        skipped = GradedSensitivity(rounds_set_aside=aside, not_computed=not_computed)
        return [dataclasses.replace(g, sensitivity=skipped) for g in graded], busy
    again = grade(
        grid.keeping(rounds - set(aside)),
        rule,
        floors=floors,
        control_failed=control_failed,
        assume_interleaved=assume_interleaved,
        repeat=False,
    )
    repeated = {(g.subject, g.case.id): g for g in again.comparisons}
    out: list[Graded] = []
    for g in graded:
        other = repeated[(g.subject, g.case.id)]
        agrees = other.outcome == g.outcome
        sensitivity = GradedSensitivity(
            rounds_set_aside=aside, ratio=other.ratio, outcome=other.outcome, agrees=agrees
        )
        if not agrees and g.outcome in VERDICT_OUTCOMES:
            out.append(
                dataclasses.replace(
                    g,
                    outcome="unresolved",
                    reason="sensitive_to_disturbed_rounds",
                    reasons=("sensitive_to_disturbed_rounds",),
                    sensitivity=sensitivity,
                )
            )
        else:
            out.append(dataclasses.replace(g, sensitivity=sensitivity))
    return out, busy
