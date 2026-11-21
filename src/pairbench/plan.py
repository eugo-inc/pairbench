# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The plan of a run: the round count, the rows of every round, the launches and the plan text.

``build_plan`` picks the round count from the run settings and lays out the
rows with ``model.plan_rows``: the lineup (every side followed by its twin)
under the ``rotate-reverse`` schedule, and the positive control as one more
row at the end of every round. The control changes neither the balance nor
any round count. ``format_plan`` returns what the plan command prints: a
header of ``#`` lines, then the tab-separated table of ``Plan.to_tsv``. The
header of a serving experiment also says how often its round count catches a
real difference, from the simulated error rates (``pairbench.report.odds``).

A round count is balanced when ``Plan.is_balanced`` says so, counting over
the rows. The schedule repeats after twice the lineup's length, so whether a
count is balanced depends only on where it falls within that period; the
period is counted once per plan and every chosen count is a count the rows
confirm.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from math import comb

from pairbench import registry
from pairbench.api import SideLookup, note_line
from pairbench.errors import Refusal
from pairbench.model import (
    ENERGY_SCOPE,
    KIND_FILE,
    NOTE_IDENTITY_UNCHECKED,
    Experiment,
    PairBalance,
    Plan,
    PlanRow,
    Rule,
    compared_pairs,
    count_balance,
    min_rounds,
    plan_rows,
    planned_launches,
    public_path,
    public_text,
)
from pairbench.report.odds import odds_line

AUTO_MARGIN = 4
"""``--rounds auto`` asks for this many rounds above the fewest that can give a verdict."""

SERVING_ROUNDS = 8
"""What ``--rounds auto`` resolves to for an experiment of serving sides."""

SERVING_MORE_ROUNDS = 16
"""The round count the plan of a serving experiment offers as the next step up."""

CONTROL_RUNS = 2
"""A launch of the positive control runs the baseline's workload twice."""

MOST_CASES_SHOWN = 10**9
"""The plan text names a count of primary cases up to this; above it, it says more than this."""

GLOB_CHARACTERS = frozenset("*?[")
"""A primary-case pattern with none of these names one case: the plan can count it."""

SCOPED_CASE_END = f"[{ENERGY_SCOPE}]"
"""The brackets that end an energy case id, as in ``tokens_per_joule[gpu]``: not a glob."""


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


def _layout(
    experiment: Experiment, rounds: int
) -> tuple[tuple[PlanRow, ...], tuple[PairBalance, ...]]:
    lineup = experiment.lineup()
    rows = plan_rows(lineup, rounds, experiment.control())
    return rows, count_balance(rows, compared_pairs(lineup))


def _plan(
    experiment: Experiment,
    rounds: int,
    *,
    requested: int | None = None,
    launches: int = 0,
    estimate_s: float | None = None,
) -> Plan:
    rows, balance = _layout(experiment, rounds)
    control = experiment.control()
    return Plan(
        rows=rows,
        rounds_requested=requested,
        rounds_planned=rounds,
        lineup=tuple(s.name for s in experiment.lineup()),
        balance=balance,
        launches=launches,
        estimate_s=estimate_s,
        explain_launches=experiment.explain_launches(),
        control=control.name if control is not None else None,
    )


class _Balance:
    """Which round counts are balanced for one experiment's lineup."""

    def __init__(self, experiment: Experiment) -> None:
        self.experiment = experiment
        self.period = 2 * len(experiment.lineup())
        self._within = {
            rounds: _plan(experiment, rounds).is_balanced() for rounds in range(1, self.period + 1)
        }

    def balanced(self, rounds: int) -> bool:
        """Say whether ``rounds`` rounds are balanced."""
        if rounds < 1:
            return False
        return self._within[(rounds - 1) % self.period + 1]

    def at_least(self, rounds: int) -> int:
        """Return the smallest balanced count that is ``rounds`` or more."""
        count = max(1, rounds)
        while not self.balanced(count):
            count += 1
        return count

    def at_most(self, rounds: int, floor: int) -> int | None:
        """Return the largest balanced count from ``floor`` to ``rounds``, or ``None``."""
        count = rounds
        while count >= max(1, floor):
            if self.balanced(count):
                return count
            count -= 1
        return None


# ---------------------------------------------------------------------------
# What a verdict needs
# ---------------------------------------------------------------------------


def _tests(experiment: Experiment, primary_cases: int | None) -> int:
    """The number of tests the verdict corrects for: subjects times primary cases."""
    return max(1, len(experiment.subjects)) * max(1, primary_cases or 1)


def _least_rounds(rule: Rule, tests: int) -> int:
    """The fewest rounds that can give a verdict under ``rule`` for ``tests`` tests."""
    if rule.min_rounds is not None:
        return rule.min_rounds
    return min_rounds(tests, rule.alpha)


def _sign_p(agree: int, rounds: int) -> float:
    """The exact two-sided sign-test p-value of ``agree`` of ``rounds`` rounds in one direction."""
    tail = sum(comb(rounds, i) for i in range(rounds - agree + 1))
    return _p_of_tail(tail, rounds)


def _p_of_tail(tail: int, rounds: int) -> float:
    """The two-sided p-value whose one-sided tail holds ``tail`` of the ``2**rounds`` outcomes."""
    return min(1.0, (2 * tail) / (1 << rounds))


def _significant(p: float, tests: int, rule: Rule) -> bool:
    weight = tests if rule.p_source == "corrected" else 1
    return weight * p <= rule.alpha if rule.p_inclusive else weight * p < rule.alpha


def rounds_to_agree(rounds: int, tests: int, rule: Rule) -> int | None:
    """Return how many of ``rounds`` rounds must agree for a verdict, or ``None`` when none can.

    The sign test is exact and two-sided. Under a rule that corrects the
    p-value, the first of ``tests`` tests must be significant at ``alpha``
    divided by ``tests``. A rule that fixes the fewest rounds also needs that
    many.
    """
    if rounds < 1 or (rule.min_rounds is not None and rounds < rule.min_rounds):
        return None
    # The p-value falls as more rounds agree, so the counts that pass run from
    # some count up to all of the rounds. Walk down from all of them, adding
    # one binomial term to the tail at each step, and stop at the first count
    # that fails: one pass, with no tail summed twice.
    found = None
    term = tail = 1  # comb(rounds, 0): every round agrees
    for agree in range(rounds, rounds // 2, -1):
        if not _significant(_p_of_tail(tail, rounds), tests, rule):
            break
        found = agree
        disagree = rounds - agree + 1
        term = term * (rounds - disagree + 1) // disagree
        tail += term
    return found


def most_primary_cases(rounds: int, subjects: int, rule: Rule) -> int | None:
    """Return the largest number of primary cases ``rounds`` rounds can give a verdict for.

    ``n`` tests (subjects times primary cases) need the fewest rounds the
    rule fixes, or else ``min_rounds(n, alpha)``, under every source of
    p-value: the run and the analysis refuse fewer. Under a rule that
    corrects the p-value, all rounds agreeing must also pass ``alpha``
    divided among the tests. ``None`` means any number: a rule that compares
    raw p-values and fixes the fewest rounds. Zero means none.
    """
    if rounds < 1 or (rule.min_rounds is not None and rounds < rule.min_rounds):
        return 0
    if rule.p_source != "corrected" and rounds_to_agree(rounds, 1, rule) is None:
        return 0
    # All rounds agreeing gives the smallest p-value, 2 / 2**rounds. Both
    # bounds follow from it: min_rounds(n, alpha) is at most ``rounds`` while
    # n * 2 / 2**rounds stays below alpha, and a corrected p-value passes
    # while it stays below alpha, or reaches it under an inclusive rule.
    # Exact fractions keep the count right where a float would round it.
    limit = Fraction(rule.alpha) * (1 << (rounds - 1))
    bounds: list[int] = []
    if rule.min_rounds is None:
        bounds.append(math.ceil(limit) - 1)
    if rule.p_source == "corrected":
        bounds.append(math.floor(limit) if rule.p_inclusive else math.ceil(limit) - 1)
    if not bounds:
        return None
    return max(0, min(bounds)) // max(1, subjects)


def _is_auto(experiment: Experiment) -> bool:
    """Whether the round count follows from the number of primary cases."""
    run = experiment.run
    return (
        run.budget_s is None
        and run.rounds == "auto"
        and not run.quick
        and not experiment.is_serving
    )


def _auto_rounds(balance: _Balance, rule: Rule, tests: int) -> int:
    return balance.at_least(_least_rounds(rule, tests) + AUTO_MARGIN)


def auto_holds_for(experiment: Experiment, rule: Rule, rounds: int) -> int | None:
    """Return the largest number of primary cases for which ``--rounds auto`` plans ``rounds``.

    ``None`` means any number: the rule fixes the fewest rounds, so the count
    does not depend on the cases. Zero means the count is not the one auto
    plans even for one primary case.
    """
    if rule.min_rounds is not None:
        return None
    per_case = max(1, len(experiment.subjects))
    balance = _Balance(experiment)
    if _auto_rounds(balance, rule, per_case) != rounds:
        return 0
    low, high = 1, 2
    while _auto_rounds(balance, rule, per_case * high) == rounds:
        low, high = high, high * 2
    while high - low > 1:
        middle = (low + high) // 2
        if _auto_rounds(balance, rule, per_case * middle) == rounds:
            low = middle
        else:
            high = middle
    return low


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _entry_seconds(
    experiment: Experiment, launch_s: Mapping[str, float] | None
) -> dict[str, float] | None:
    """The estimated time of one launch of each side, or ``None`` when a side has none."""
    if launch_s is None:
        return None
    times: dict[str, float] = {}
    for side in experiment.sides:
        value = launch_s.get(side.name)
        if value is None or not math.isfinite(value) or value < 0:
            return None
        times[side.name] = float(value)
    return times


def _round_seconds(experiment: Experiment, times: Mapping[str, float]) -> float:
    total = sum(times[s.source] for s in experiment.lineup())
    control = experiment.control()
    if control is not None:
        total += CONTROL_RUNS * times[control.source]
    return total


def _warmup_seconds(experiment: Experiment, times: Mapping[str, float]) -> float:
    return experiment.run.warmups * sum(times[s.name] for s in experiment.sides)


def _estimate(
    experiment: Experiment, times: Mapping[str, float] | None, rounds: int
) -> float | None:
    if times is None:
        return None
    return _warmup_seconds(experiment, times) + rounds * _round_seconds(experiment, times)


def _duration(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.3g} s"
    if seconds < 7200:
        return f"{seconds / 60:.3g} min"
    return f"{seconds / 3600:.3g} h"


# ---------------------------------------------------------------------------
# The round count
# ---------------------------------------------------------------------------


def _check_settings(experiment: Experiment) -> None:
    run = experiment.run
    fixed = isinstance(run.rounds, int)
    if run.budget_s is not None:
        if fixed:
            raise Refusal("E_USAGE", "--budget and --rounds N cannot be given together")
        if run.quick:
            raise Refusal("E_USAGE", "--budget and --quick cannot be given together")
        if run.rounds_exact:
            raise Refusal("E_USAGE", "--budget and --rounds-exact cannot be given together")
        if run.warmups == 0:
            raise Refusal(
                "E_USAGE",
                "--budget needs a warm-up launch to time: it cannot be given with --warmups 0",
            )
    if run.rounds_exact and not fixed:
        raise Refusal("E_USAGE", "--rounds-exact needs a round count: give --rounds N")
    if run.quick and fixed:
        raise Refusal("E_USAGE", "--quick and --rounds N cannot be given together")
    if run.quick and run.rounds_exact:
        raise Refusal("E_USAGE", "--quick and --rounds-exact cannot be given together")
    if experiment.gates.wait_quiet and experiment.gates.mode == "off":
        raise Refusal(
            "E_USAGE",
            "--wait-quiet needs --gates warn or enforce: --gates off skips the checks before "
            "the run, the quiet wait among them",
        )


def _budget_rounds(
    experiment: Experiment,
    balance: _Balance,
    times: Mapping[str, float] | None,
    least: int,
) -> int:
    budget = experiment.run.budget_s
    assert budget is not None
    fewest = balance.at_least(least)
    if times is None:
        return fewest
    per_round = _round_seconds(experiment, times)
    left = budget - _warmup_seconds(experiment, times)
    if per_round <= 0:
        raise Refusal(
            "E_BUDGET",
            "the warm-up launches took no measurable time, so no round count can be fitted "
            "to the budget; give --rounds N instead",
        )
    fits = math.floor(left / per_round) if left >= 0 else 0
    chosen = balance.at_most(fits, fewest)
    if chosen is None:
        need = _warmup_seconds(experiment, times) + fewest * per_round
        # With no subject no verdict is sought: the count is the smallest balanced one.
        who = "a verdict needs" if experiment.subjects else "a balanced run needs"
        raise Refusal(
            "E_BUDGET",
            f"the budget of {_duration(budget)} fits {max(fits, 0)} rounds of about "
            f"{_duration(per_round)} each; {who} at least {fewest} balanced rounds, "
            f"about {_duration(need)} with the warm-up",
            detail={"budget_s": budget, "round_s": per_round, "rounds_needed": fewest},
        )
    return chosen


def build_plan(
    experiment: Experiment,
    *,
    primary_cases: int | None = None,
    launch_s: Mapping[str, float] | None = None,
) -> Plan:
    """Lay out the plan of a run. It starts, pulls and writes nothing.

    ``primary_cases`` is the number of primary cases once a warm-up has found
    them; without it the plan is made for one. ``launch_s`` gives the warm-up
    launch time of each side, for the estimate and for a time budget. The
    estimate counts the warm-up launches and every round, a launch of the
    positive control as two runs of the baseline's workload.
    """
    if any(s.kind == KIND_FILE for s in experiment.sides):
        raise Refusal(
            "E_USAGE", "sides that are result files are not planned: their files give the rounds"
        )
    _check_settings(experiment)
    run = experiment.run
    rule = registry.rule(experiment.rule.name)
    # With one side no subject is compared and no verdict is sought, so no
    # count of rounds is too few for one.
    least = _least_rounds(rule, _tests(experiment, primary_cases)) if experiment.subjects else 1
    balance = _Balance(experiment)
    times = _entry_seconds(experiment, launch_s)

    requested: int | None = None
    if run.budget_s is not None:
        rounds = _budget_rounds(experiment, balance, times, least)
    elif isinstance(run.rounds, int):
        requested = run.rounds
        rounds = run.rounds if run.rounds_exact else balance.at_least(run.rounds)
    elif run.quick:
        rounds = balance.at_least(1)
    elif experiment.is_serving:
        rounds = balance.at_least(SERVING_ROUNDS)
    else:
        rounds = _auto_rounds(balance, rule, _tests(experiment, primary_cases))

    if rounds < least and not run.allow_underpowered:
        raise Refusal(
            "E_TOO_FEW_ROUNDS",
            f"{rounds} rounds are planned and a verdict needs at least {least}; "
            "give more rounds or --allow-underpowered",
            detail={"rounds_planned": rounds, "rounds_needed": least},
        )

    control = experiment.control()
    launches = planned_launches(
        entries=len(experiment.lineup()),
        rounds=rounds,
        sides=len(experiment.sides),
        warmups=run.warmups,
        control=control is not None,
    )
    return _plan(
        experiment,
        rounds,
        requested=requested,
        launches=launches,
        estimate_s=_estimate(experiment, times, rounds),
    )


# ---------------------------------------------------------------------------
# The plan text
# ---------------------------------------------------------------------------


def _requested_text(experiment: Experiment, plan: Plan) -> str:
    run = experiment.run
    if run.budget_s is not None:
        return f"a budget of {_duration(run.budget_s)}"
    if plan.rounds_requested is not None:
        return f"{plan.rounds_requested}" + (" exactly" if run.rounds_exact else "")
    if run.quick:
        return "quick"
    return "auto"


def _differences(experiment: Experiment) -> list[str]:
    baseline = experiment.side(experiment.baseline)
    settings = experiment.launch.differences()
    lines: list[str] = []
    for side in experiment.sides:
        fields: list[str] = []
        if side.name != baseline.name:
            if side.kind != baseline.kind:
                fields.append("kind")
            keys = sorted(set(side.spec) | set(baseline.spec))
            fields += [k for k in keys if side.spec.get(k) != baseline.spec.get(k)]
        fields += [f"launch.{k}" for k in settings.get(side.name, ())]
        if fields:
            lines.append(f"{side.name}: {', '.join(fields)}")
    return lines


def _lookup_lines(lookups: Mapping[str, SideLookup]) -> list[str]:
    """One line per look-up; a path in it shows only its last part, as results do."""
    lines: list[str] = []
    for name, found in lookups.items():
        if found.status == "identified":
            shown = ", ".join(
                f"{k}={public_path(str(found.identity[k]))}" for k in sorted(found.identity)
            )
            text = f"side {name}: identified" + (f" ({shown})" if shown else "")
        elif found.status == "absent":
            text = f"side {name}: absent from this machine"
        else:
            text = note_line(NOTE_IDENTITY_UNCHECKED, f"side {name}: identity was not checked")
        if found.message:
            text += f"; {public_text(found.message)}"
        lines.append(text)
    return lines


def _twin_lines(experiment: Experiment, rule: Rule) -> list[str]:
    twinned = set(experiment.twinned())
    missing = [s.name for s in experiment.sides if s.name not in twinned]
    if not missing or not rule.require_both_floors:
        return []
    if not twinned:
        return [
            f"warning: no side has a twin, so rule {rule.name} cannot give a verdict; "
            "turn twins on with --same-vs-same on"
        ]
    return [
        f"warning: {', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no twin, so "
        f"rule {rule.name} gives no verdict to a comparison with "
        f"{'it' if len(missing) == 1 else 'them'}"
    ]


def _floors_block_every_verdict(experiment: Experiment, rule: Rule) -> str | None:
    """Say why no comparison can get a verdict for want of twins, or ``None``.

    Under a rule that needs both noise floors, a comparison needs a twin of its
    subject and of the baseline.
    """
    if not rule.require_both_floors:
        return None
    twinned = set(experiment.twinned())
    baseline = experiment.baseline
    if any(s in twinned and baseline in twinned for s in experiment.subjects):
        return None
    reasons = sorted(
        {
            "no_floor" if s not in twinned and baseline not in twinned else "one_sided_floor"
            for s in experiment.subjects
        }
    )
    if not twinned:
        who = "no side has a twin"
    else:
        missing = [s.name for s in experiment.sides if s.name not in twinned]
        who = f"{', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no twin"
    return (
        f"{who} and rule {rule.name} needs both noise floors; every verdict is NO VERDICT "
        f"({', '.join(reasons)})"
    )


def _verdict_lines(experiment: Experiment, rule: Rule, rounds: int) -> list[str]:
    """The lines that say whether a verdict can come and for how many primary cases."""
    if not experiment.subjects:
        baseline = experiment.baseline
        floor = (
            "; the run measures its noise floor against its twin"
            if baseline in experiment.twinned()
            else ""
        )
        return [
            f"verdict: none: the experiment has one side, {baseline}, so no subject is "
            "compared with it" + floor,
            "primary cases: none can get a verdict, as no subject is compared",
        ]
    tests = len(experiment.subjects)
    agree = rounds_to_agree(rounds, tests, rule)
    least = _least_rounds(rule, tests)
    blocked = _floors_block_every_verdict(experiment, rule)
    if blocked is not None:
        verdict = f"verdict: not reachable: {blocked}"
    elif agree is None or rounds < least:
        verdict = (
            f"verdict: not reachable at {rounds} rounds (a verdict needs at least {least}); "
            "every verdict is NO VERDICT (too_few_rounds)"
        )
    else:
        verdict = f"verdict: reachable; {agree} of {rounds} rounds must agree for one primary case"
    most = most_primary_cases(rounds, tests, rule)
    if most is None:
        cases = "primary cases: any number can get a verdict at this round count"
    elif most > MOST_CASES_SHOWN:
        cases = (
            f"primary cases: more than {MOST_CASES_SHOWN} primary cases can get a verdict "
            f"at {rounds} rounds"
        )
    elif most == 0:
        cases = f"primary cases: none can get a verdict at {rounds} rounds"
    else:
        cases = f"primary cases: at most {_cases(most)} can get a verdict at {rounds} rounds"
    return [verdict, cases]


def _cases(count: int) -> str:
    return f"{count} primary case" if count == 1 else f"{count} primary cases"


def _holds_line(experiment: Experiment, rule: Rule, rounds: int) -> str:
    """The line that says for how many primary cases ``--rounds auto`` keeps its count."""
    holds = auto_holds_for(experiment, rule, rounds)
    if holds is None:
        return f"the round count of {rounds} holds for any number of primary cases"
    line = (
        f"the round count of {rounds} holds for up to {_cases(holds)}; more raise it after warm-up"
    )
    # With no subject the count still grows with the cases, though none is compared.
    return line if experiment.subjects else line + ", although no case gets a verdict"


def _balance_lines(plan: Plan) -> list[str]:
    return [
        f"balance {p.a} / {p.b}: {p.a} first in {p.a_first}, {p.b} first in {p.b_first}, "
        f"positions differ by {p.position_sum} in sum"
        for p in plan.balance
    ]


def format_plan(
    plan: Plan,
    experiment: Experiment,
    *,
    lookups: Mapping[str, SideLookup] | None = None,
    primary_cases: int | None = None,
) -> str:
    """Return the text the plan command prints: a header of ``#`` lines, then the plan table.

    ``primary_cases`` is the number of primary cases once a warm-up has found
    them; the line on how often a serving experiment's round count catches a
    real difference is then worded for that number (``serving_odds_line``).
    """
    rule = registry.rule(experiment.rule.name)
    rounds = plan.rounds_planned
    header: list[str] = [f"lineup: {', '.join(plan.lineup)}"]
    if plan.control is not None:
        header.append(
            f"positive control: {plan.control}, last in every round at position "
            f"{len(plan.lineup) + 1}"
        )
    balanced = plan.is_balanced()
    rounds_line = f"rounds: requested {_requested_text(experiment, plan)}, planned {rounds}"
    if plan.rounds_requested is not None and plan.rounds_requested != rounds:
        rounds_line += " (rounded up to the next balanced count)"
    if not balanced:
        rounds_line += " (not balanced: the capture is stamped unbalanced)"
    header.append(rounds_line)
    warmups = experiment.run.warmups * len(experiment.sides)
    header.append(
        f"launches: {plan.launches} ({rounds} rounds of "
        f"{len(plan.lineup) + (1 if plan.control else 0)}, and {warmups} warm-up launches)"
    )
    if experiment.is_serving:
        header.append(f"server starts: {plan.launches} (every launch starts the server)")
        load_line = _serving_load_line(plan, experiment)
        if load_line is not None:
            header.append(load_line)
        header += _serving_timeout_lines(plan, experiment)
    header += _balance_lines(plan)

    header += _verdict_lines(experiment, rule, rounds)
    if _is_auto(experiment):
        header.append(_holds_line(experiment, rule, rounds))
    if experiment.run.budget_s is not None and plan.estimate_s is None:
        header.append(
            "the plan is made for one primary case; the time budget and the cases fix the "
            "round count after warm-up"
        )
    else:
        header.append(
            "the plan is made for one primary case; the round count is fixed after warm-up, "
            "once the cases are known"
        )
    header.append(
        f"estimated duration: {_duration(plan.estimate_s)}"
        if plan.estimate_s is not None
        else "estimated duration: not known before a warm-up launch is timed"
    )
    run_s = _run_seconds(plan, experiment)
    if plan.control is not None:
        cost = f", about {_duration(rounds * CONTROL_RUNS * run_s)}" if run_s is not None else ""
        header.append(
            f"positive control costs {rounds} launches{cost}; "
            "turn it off with --positive-control off"
        )
    else:
        header.append("positive control: off")
    if plan.explain_launches:
        cost = f", about {_duration(plan.explain_launches * run_s)}" if run_s is not None else ""
        header.append(
            f"explain launches: {plan.explain_launches}{cost}, after the analysis and counted "
            "on their own; turn them off with --explain off"
        )
    else:
        header.append("explain launches: none")
    differences = _differences(experiment)
    header.append(
        "sides differ in: " + ("; ".join(differences) if differences else "nothing declared")
    )
    header += _twin_lines(experiment, rule)
    if experiment.is_serving:
        more = _Balance(experiment).at_least(SERVING_MORE_ROUNDS)
        odds = serving_odds_line(plan, experiment, primary_cases=primary_cases)
        if odds is not None:
            header.append(odds)
        header.append(f"for {more} rounds, run again with --rounds {more}")
    if lookups:
        header += _lookup_lines(lookups)
    return "".join(f"# {line}\n" for line in header) + plan.to_tsv()


def known_primary_cases(experiment: Experiment, primary_cases: int | None = None) -> int | None:
    """Return the number of primary cases when the plan can know it, else ``None``.

    It is ``primary_cases`` when given. Without it, primary cases named one by
    one count one case each (``names_one_case``); a glob, or the driver's own
    choice, is known only once a warm-up has found the cases.
    """
    if primary_cases is not None:
        return primary_cases
    patterns = experiment.cases.primary
    if patterns and all(names_one_case(pattern) for pattern in patterns):
        return len(set(patterns))
    return None


def names_one_case(pattern: str) -> bool:
    """Say whether a primary-case pattern names one case as written.

    A pattern with no glob character does. So does one whose only brackets
    end it as the scope of an energy case, as ``c32/tokens_per_joule[gpu]``
    does: a pattern equal to a case id matches that case first
    (``model.case_matches``).
    """
    if pattern.endswith(SCOPED_CASE_END):
        pattern = pattern[: -len(SCOPED_CASE_END)]
    return not GLOB_CHARACTERS & set(pattern)


def serving_odds_line(
    plan: Plan, experiment: Experiment, *, primary_cases: int | None = None
) -> str | None:
    """Say how often the planned round count catches a real difference, or ``None``.

    The line is worded by ``pairbench.report.odds.odds_line`` for the
    experiment's number of primary cases (``known_primary_cases``), its
    subjects and its rule, and names what the next round count offered
    catches. There is none when no subject is compared or when missing
    twins leave every comparison without a verdict: the verdict line says so.
    """
    rule = registry.rule(experiment.rule.name)
    if not experiment.subjects or _floors_block_every_verdict(experiment, rule) is not None:
        return None
    return odds_line(
        [plan.rounds_planned],
        known_primary_cases(experiment, primary_cases),
        subjects=len(experiment.subjects),
        rule=rule.name,
        more_rounds=_Balance(experiment).at_least(SERVING_MORE_ROUNDS),
    )


def _serving_load_line(plan: Plan, experiment: Experiment) -> str | None:
    """Say how long the load of one serving launch runs, and of every launch of the rounds."""
    load = experiment.load
    if not load.levels:
        return None
    labels = ", ".join(load.labels())
    if load.level_duration_s is None:
        return (
            f"serving load per launch: levels {labels}; each level sends its number of "
            "prompts, so its length is not known before the run"
        )
    per_launch = len(load.levels) * load.level_duration_s
    launches = plan.rounds_planned * (len(plan.lineup) + (1 if plan.control is not None else 0))
    # A launch of the positive control runs the load twice.
    loads = plan.rounds_planned * (
        len(plan.lineup) + (CONTROL_RUNS if plan.control is not None else 0)
    )
    control = (
        ", counting the load twice in each launch of the positive control"
        if plan.control is not None
        else ""
    )
    return (
        f"serving load per launch: levels {labels} of {_duration(load.level_duration_s)} each, "
        f"about {_duration(per_launch)}; about {_duration(per_launch * loads)} for the "
        f"{launches} launches of the rounds{control}, besides the server starts"
    )


def _serving_timeout_lines(plan: Plan, experiment: Experiment) -> list[str]:
    """Warn of each side whose launch timeout is shorter than the serving load it must run.

    The timeout of a serving launch runs from the server start to the end of
    its load, so a timeout shorter than the load alone cannot be met. A
    launch of the positive control runs the load twice, under the baseline's
    settings.
    """
    load = experiment.load
    if not load.levels or load.level_duration_s is None:
        return []
    per_launch = len(load.levels) * load.level_duration_s
    lines: list[str] = []
    for side in experiment.sides:
        timeout = experiment.launch.for_side(side).timeout_s
        if timeout is None:
            continue
        if timeout < per_launch:
            lines.append(
                f"warning: launch.timeout of side {side.name} is {_duration(timeout)}, shorter "
                f"than its serving load of about {_duration(per_launch)}; its launches will "
                "time out"
            )
        elif (
            plan.control is not None
            and side.name == experiment.baseline
            and timeout < CONTROL_RUNS * per_launch
        ):
            lines.append(
                f"warning: launch.timeout of side {side.name} is {_duration(timeout)}, "
                f"shorter than the load of about {_duration(CONTROL_RUNS * per_launch)} that "
                "a launch of its positive control runs; those launches will time out"
            )
    return lines


def _run_seconds(plan: Plan, experiment: Experiment) -> float | None:
    """The estimated time of one run of a workload, as if every run took the same time.

    The plan keeps its estimate as one number; the runs it counts are the
    warm-up launches, one per entry of every round and two per launch of the
    positive control.
    """
    if plan.estimate_s is None:
        return None
    per_round = len(plan.lineup) + (CONTROL_RUNS if plan.control is not None else 0)
    runs = experiment.run.warmups * len(experiment.sides) + plan.rounds_planned * per_round
    return plan.estimate_s / runs if runs else None


__all__: Sequence[str] = (
    "build_plan",
    "format_plan",
    "known_primary_cases",
    "most_primary_cases",
    "names_one_case",
    "rounds_to_agree",
    "serving_odds_line",
)
