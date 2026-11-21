# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Simulate how often the default rule gives each outcome, and write the table.

Each simulated experiment has two sides, ``new`` and ``old``, each with a
twin, run under the ``rotate-reverse`` schedule and graded by the same code
an analysis uses (``pairbench.stats.rules.grade``) under the default rule.
The settings cover 8, 16 and 24 rounds, 1, 4 and 10 primary cases, noise of
1, 3 and 10 percent, and a true difference of none, or one, two and four
times the noise, under two noise models:

1. independent: each value is a base value times independent log-normal
   noise;
2. drift: the same, with one more log-normal term shared by every launch of
   a round. Pairing removes it.

Usage::

    python tools/error_rates.py [--experiments N] [--seed S] [--out PATH] [--data PATH]

It writes two files from the same counts: a Markdown page,
``docs/method/error-rates.md`` by default, and a data file,
``src/pairbench/report/error_rates.json`` by default, which the plan of a
serving experiment and the report of a serving run read
(``pairbench.report.odds``). The page can be written again from the data file
alone (``render_data``). The run is seeded: the same seed and count give the
same files.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pairbench  # noqa: F401
except ImportError:  # run from a source tree without an installed package
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pairbench.model import STRICT, Case, Rule, rotate_reverse
from pairbench.report import odds
from pairbench.stats.rules import Grid, grade

ROUNDS: tuple[int, ...] = (8, 16, 24)
CASES: tuple[int, ...] = (1, 4, 10)
NOISE: tuple[float, ...] = (0.01, 0.03, 0.10)
DIFFERENCES: tuple[int, ...] = (0, 1, 2, 4)
MODELS: tuple[str, ...] = ("independent", "drift")
DRIFT_FACTOR = 2.0
"""The standard deviation of the shared drift term, as a multiple of the noise."""

DEFAULT_SEED = 12345
DEFAULT_EXPERIMENTS = 1500
ENTRIES: tuple[str, ...] = ("new", "new~same", "old", "old~same")
TWINS: Mapping[str, str] = {"new": "new~same", "old": "old~same"}
OUTCOMES: tuple[str, ...] = odds.OUTCOMES
ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "method" / "error-rates.md"
DATA = ROOT / "src" / "pairbench" / "report" / odds.DATA_FILE


@dataclass(frozen=True, order=True)
class Cell:
    """One setting of the simulation."""

    model: str
    rounds: int
    cases: int
    noise: float
    difference: int

    @property
    def key(self) -> str:
        """The text that seeds this setting's generator."""
        return f"{self.model}/{self.rounds}/{self.cases}/{self.noise}/{self.difference}"


@dataclass
class Tally:
    """What the experiments of one setting gave.

    ``outcomes`` counts every primary comparison by outcome; ``any_verdict``
    counts the experiments in which at least one comparison was ``better``
    or ``worse``.
    """

    experiments: int = 0
    comparisons: int = 0
    outcomes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(OUTCOMES, 0))
    any_verdict: int = 0

    def share(self, outcome: str) -> float:
        """Return the share of comparisons with this outcome."""
        return self.outcomes[outcome] / self.comparisons if self.comparisons else 0.0

    @property
    def verdict_rate(self) -> float:
        """The share of experiments with at least one ``better`` or ``worse`` comparison."""
        return self.any_verdict / self.experiments if self.experiments else 0.0


def all_cells() -> list[Cell]:
    """Return every setting, in the order of the page."""
    return [
        Cell(model, rounds, cases, noise, difference)
        for model in MODELS
        for difference in DIFFERENCES
        for rounds in ROUNDS
        for cases in CASES
        for noise in NOISE
    ]


def _cases(n: int) -> tuple[Case, ...]:
    return tuple(Case(id=f"case{i}", metric="time", unit="s", kind="time") for i in range(n))


def _positions(rounds: int) -> dict[tuple[int, str], int | None]:
    positions: dict[tuple[int, str], int | None] = {}
    for r in range(1, rounds + 1):
        for pos, name in enumerate(rotate_reverse(ENTRIES, r), start=1):
            positions[(r, name)] = pos
    return positions


def experiment(cell: Cell, rng: random.Random, cases: Sequence[Case]) -> Grid:
    """Draw the values of one experiment of a setting.

    ``new`` and its twin are slower than ``old`` by the factor
    ``1 + difference * noise``; every value carries log-normal noise whose
    logarithm has the standard deviation ``noise``. Under the drift model
    every launch of a round shares one more log-normal term whose logarithm
    has the standard deviation ``DRIFT_FACTOR * noise``.
    """
    shift = math.log1p(cell.difference * cell.noise)
    values: dict[tuple[str, str], dict[int, float]] = {
        (e, c.id): {} for e in ENTRIES for c in cases
    }
    for r in range(1, cell.rounds + 1):
        drift = rng.gauss(0.0, DRIFT_FACTOR * cell.noise) if cell.model == "drift" else 0.0
        for case in cases:
            for entry in ENTRIES:
                own = shift if entry.startswith("new") else 0.0
                values[(entry, case.id)][r] = math.exp(own + drift + rng.gauss(0.0, cell.noise))
    return Grid(
        rounds=tuple(range(1, cell.rounds + 1)),
        values=values,
        positions=_positions(cell.rounds),
        subjects=("new",),
        baseline="old",
        twins=TWINS,
        cases=tuple(cases),
    )


def simulate(cell: Cell, experiments: int, seed: int, rule: Rule = STRICT) -> Tally:
    """Grade ``experiments`` experiments of one setting and count their outcomes."""
    rng = random.Random(f"{seed}/{cell.key}")
    cases = _cases(cell.cases)
    tally = Tally()
    for _ in range(experiments):
        graded = grade(experiment(cell, rng, cases), rule)
        tally.experiments += 1
        verdict = False
        for comparison in graded.comparisons:
            tally.comparisons += 1
            tally.outcomes[comparison.outcome] += 1
            verdict = verdict or comparison.outcome in ("better", "worse")
        tally.any_verdict += verdict
    return tally


def run(
    experiments: int, seed: int, cells: Iterable[Cell] | None = None, *, progress: bool = False
) -> dict[Cell, Tally]:
    """Simulate every setting, or the ones given."""
    chosen = list(all_cells() if cells is None else cells)
    out: dict[Cell, Tally] = {}
    for i, cell in enumerate(chosen, start=1):
        out[cell] = simulate(cell, experiments, seed)
        if progress:
            print(f"{i}/{len(chosen)} {cell.key}", file=sys.stderr, flush=True)
    return out


def over_alpha(results: Mapping[Cell, Tally], alpha: float = STRICT.alpha) -> list[Cell]:
    """Return the settings with no true difference whose experiments give a verdict too often."""
    return [
        cell
        for cell, tally in sorted(results.items())
        if cell.difference == 0 and tally.verdict_rate > alpha
    ]


def _percent(value: float) -> str:
    return odds.percent_text(value)


def _page_order(cell: Cell) -> tuple[int, int, int, int, int]:
    return (
        MODELS.index(cell.model),
        DIFFERENCES.index(cell.difference),
        ROUNDS.index(cell.rounds),
        CASES.index(cell.cases),
        NOISE.index(cell.noise),
    )


def data_text(results: Mapping[Cell, Tally], experiments: int, seed: int) -> str:
    """Write the data file: the seed, the count, the rule and the counts of every setting.

    One setting per line, in the order of the page, so a change reads as a
    change of lines.
    """
    settings = [
        odds.Setting(
            model=cell.model,
            rounds=cell.rounds,
            cases=cell.cases,
            noise=cell.noise,
            difference=cell.difference,
            experiments=tally.experiments,
            comparisons=tally.comparisons,
            outcomes=dict(tally.outcomes),
            any_verdict=tally.any_verdict,
        )
        for cell, tally in sorted(results.items(), key=lambda item: _page_order(item[0]))
    ]
    head = {"seed": seed, "experiments": experiments, "rule": STRICT.name, "alpha": STRICT.alpha}
    lines = ["{"]
    lines += [f"  {json.dumps(key)}: {json.dumps(value)}," for key, value in head.items()]
    rows = [json.dumps(row) for row in odds.settings_rows(settings)]
    lines.append('  "settings": [')
    lines += [f"    {row}{',' if i < len(rows) - 1 else ''}" for i, row in enumerate(rows)]
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def results_of(rates: odds.ErrorRates) -> dict[Cell, Tally]:
    """Return the tallies a data file holds, by setting."""
    return {
        Cell(s.model, s.rounds, s.cases, s.noise, s.difference): Tally(
            experiments=s.experiments,
            comparisons=s.comparisons,
            outcomes={o: s.outcomes[o] for o in OUTCOMES},
            any_verdict=s.any_verdict,
        )
        for s in rates.settings
    }


def render_data(rates: odds.ErrorRates) -> str:
    """Write the page from a data file alone."""
    return render(results_of(rates), rates.experiments, rates.seed)


def render(results: Mapping[Cell, Tally], experiments: int, seed: int) -> str:
    """Write the page: what was simulated, how, and the table of outcomes."""
    lines: list[str] = [
        "---",
        'description: "How often the default rule gives each outcome in simulated experiments,'
        ' with and without a true difference between two sides."',
        "---",
        "",
        "# How often does the default rule give a wrong verdict?",
        "",
        "The tables below answer it from simulated experiments: for each number of rounds,",
        "cases and noise, they show how often the default rule, `strict`, gives each outcome",
        "when two sides have no true difference and when they have one. This page is written",
        "by `tools/error_rates.py`.",
        "",
    ]
    flagged = over_alpha(results)
    if flagged:
        lines += [
            "> **The default rule is not frozen.** With no true difference, the share of",
            "> experiments with at least one FASTER or SLOWER verdict exceeds the rule's",
            f"> alpha of {STRICT.alpha} in {len(flagged)} setting"
            f"{'s' if len(flagged) != 1 else ''}:",
        ]
        for cell in flagged:
            lines.append(
                f"> {cell.model} noise, {cell.rounds} rounds, {cell.cases} cases, "
                f"{_percent(cell.noise)} percent noise: "
                f"{_percent(results[cell].verdict_rate)} percent."
            )
        lines.append("")
    lines += [
        "The same run writes the counts behind every share to a data file in the",
        "package, which the plan of a serving experiment and the report of a serving",
        "run read to say how often their round count catches a real difference.",
        "",
        "## How the experiments are made",
        "",
        "Each experiment has two sides, `new` and `old`, and a twin of each. The four",
        "entries run in the order of the `rotate-reverse` schedule, and every entry",
        "gives one value per case in every round. The values are graded by the code",
        "an analysis uses, under the default rule, with the twins as the noise floors.",
        "",
        f"* Seed: `{seed}`. The same seed and count give the same page.",
        f"* Simulated experiments per setting: {experiments}.",
        "* Rounds: " + ", ".join(str(r) for r in ROUNDS) + ".",
        "* Primary cases: " + ", ".join(str(c) for c in CASES) + ", one floor group.",
        "* Noise: " + ", ".join(_percent(n) for n in NOISE) + " percent: the logarithm of",
        "  every value has that standard deviation.",
        "* True difference: none, or one, two and four times the noise. `new` and its",
        "  twin are slower than `old` by the factor `1 + k * noise`.",
        "",
        "Two noise models:",
        "",
        "1. **Independent noise.** Each value is a base value times independent",
        "   log-normal noise.",
        "2. **Shared drift.** The same, with one more log-normal term shared by every",
        "   launch of a round, whose logarithm has a standard deviation of",
        f"   {DRIFT_FACTOR:g} times the noise. Pairing the launches of a round removes it.",
        "",
        "## Reading the table",
        "",
        "The outcome columns give the share of all primary comparisons, in percent.",
        "`new` is the slower side, so `worse` (SLOWER) is the right direction and",
        "`better` (FASTER) the wrong one. The last column gives the share of",
        "experiments in which at least one comparison was FASTER or SLOWER. With no",
        "true difference that is the false-verdict rate of an experiment as a whole,",
        f"held against the rule's alpha of {STRICT.alpha}.",
        "",
        "With 10 cases, 8 rounds are fewer than the rule needs to give any verdict,",
        "so those settings read NO VERDICT (`too_few_rounds`).",
    ]
    for model in MODELS:
        for difference in DIFFERENCES:
            title = (
                "no true difference"
                if difference == 0
                else (f"a true difference of {difference} times the noise")
            )
            lines += [
                "",
                f"## {model.capitalize()} noise, {title}",
                "",
                "| Rounds | Cases | Noise % | better | worse | tie | unresolved | no verdict "
                "| experiments with a verdict |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
            for rounds in ROUNDS:
                for cases in CASES:
                    for noise in NOISE:
                        cell = Cell(model, rounds, cases, noise, difference)
                        tally = results.get(cell)
                        if tally is None:
                            continue
                        shares = " | ".join(_percent(tally.share(o)) for o in OUTCOMES)
                        lines.append(
                            f"| {rounds} | {cases} | {_percent(noise)} | {shares} "
                            f"| {_percent(tally.verdict_rate)} |"
                        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the simulation and write the page and the data file.

    Returns 0, or 1 when the default is not frozen.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--experiments", type=int, default=DEFAULT_EXPERIMENTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=PAGE)
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args(argv)
    if args.experiments < 1:
        parser.error("--experiments is at least 1")
    results = run(args.experiments, args.seed, progress=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(results, args.experiments, args.seed), encoding="utf-8")
    args.data.parent.mkdir(parents=True, exist_ok=True)
    args.data.write_text(data_text(results, args.experiments, args.seed), encoding="utf-8")
    flagged = over_alpha(results)
    for cell in flagged:
        print(
            f"not frozen: {cell.key} gives a verdict in "
            f"{_percent(results[cell].verdict_rate)} percent of experiments",
            file=sys.stderr,
        )
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())
