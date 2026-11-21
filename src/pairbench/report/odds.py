# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""How often a round count catches a real difference, read from the simulated error rates.

``tools/error_rates.py`` simulates the default rule and writes two files from the
same counts: the page ``docs/method/error-rates.md`` and the data file
``error_rates.json`` beside this module. This module reads the data file and
words the line that the plan of a serving experiment and the report of a
serving run print. No figure of that line is written here: every one is a
count of the data file turned into a percentage the way the page shows it.

In every simulated experiment the side ``new`` is the slower one, so the right
verdict is ``worse`` (SLOWER) and ``better`` (FASTER) is the wrong direction.
A share is the share of all primary comparisons of one setting; a range runs
over the two noise models and the three noise levels of a round count, a
number of primary cases and a true difference.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from importlib import resources
from typing import Any

DATA_FILE = "error_rates.json"
"""The data file the error-rate tool writes, beside this module."""

ERROR_RATES_PAGE = "https://eugo.io/docs/pairbench/latest/method/error-rates/"
"""The address of the error-rate page that the line links to."""

OUTCOMES: tuple[str, ...] = ("better", "worse", "tie", "unresolved", "no_verdict")
"""Every outcome a simulated comparison can have, in the order of the page."""

CAUGHT = "worse"
"""The right verdict: the simulated ``new`` side is the slower one."""

WRONG = "better"
"""The verdict in the wrong direction."""

TWICE = 2
FOUR_TIMES = 4
"""The two true differences the line states, as multiples of the noise."""

_NUMBER_WORDS: Mapping[int, str] = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}


def percent_text(share: float) -> str:
    """Return a share as the page shows it: a percentage with one decimal, ``38.7``."""
    return f"{100.0 * share:.1f}"


def whole_percent(text: str) -> int:
    """Return a percentage as the page shows it, rounded half up to a whole number."""
    return int(Decimal(text).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Setting:
    """The counts of one simulated setting.

    ``outcomes`` counts the primary comparisons by outcome; ``any_verdict``
    counts the experiments in which at least one comparison was ``better`` or
    ``worse``.
    """

    model: str
    rounds: int
    cases: int
    noise: float
    difference: int
    experiments: int
    comparisons: int
    outcomes: Mapping[str, int]
    any_verdict: int

    def share(self, outcome: str) -> float:
        """Return the share of comparisons with this outcome."""
        return self.outcomes[outcome] / self.comparisons if self.comparisons else 0.0

    @property
    def verdict_rate(self) -> float:
        """The share of experiments with at least one ``better`` or ``worse`` comparison."""
        return self.any_verdict / self.experiments if self.experiments else 0.0


@dataclass(frozen=True)
class Span:
    """The lowest and highest share, as the page shows them, of one group of settings.

    ``judged`` is ``False`` when no comparison of the group could get a
    verdict: every one was NO VERDICT, as with too few rounds for the cases.
    """

    low: str
    high: str
    judged: bool = True

    def text(self) -> str:
        """Return the range in whole percent: ``33 to 39``, or ``100`` when both ends agree."""
        low, high = whole_percent(self.low), whole_percent(self.high)
        return str(low) if low == high else f"{low} to {high}"

    def about(self) -> str | None:
        """Return ``one in three`` when the middle of the range is at most one half, else None.

        The count is the inverse of the middle of the range, rounded half up.
        """
        middle = (Decimal(self.low) + Decimal(self.high)) / 200
        if middle <= 0 or middle > Decimal("0.5"):
            return None
        count = int((1 / middle).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return f"one in {_NUMBER_WORDS.get(count, str(count))}"


@dataclass(frozen=True)
class ErrorRates:
    """What the error-rate tool wrote: its seed, its count, the rule and every setting."""

    seed: int
    experiments: int
    rule: str
    alpha: float
    settings: tuple[Setting, ...]

    @property
    def rounds(self) -> tuple[int, ...]:
        """The simulated round counts, smallest first."""
        return tuple(sorted({s.rounds for s in self.settings}))

    @property
    def cases(self) -> tuple[int, ...]:
        """The simulated numbers of primary cases, smallest first."""
        return tuple(sorted({s.cases for s in self.settings}))

    def group(self, rounds: int, cases: int, difference: int) -> tuple[Setting, ...]:
        """Return the settings of a round count, a number of cases and a true difference."""
        return tuple(
            s
            for s in self.settings
            if s.rounds == rounds and s.cases == cases and s.difference == difference
        )

    def caught(self, rounds: int, cases: int, difference: int) -> Span | None:
        """Return the range of the share caught in the right direction, or None without a row."""
        group = self.group(rounds, cases, difference)
        if not group:
            return None
        shares = [s.share(CAUGHT) for s in group]
        judged = any(s.outcomes["no_verdict"] < s.comparisons for s in group)
        return Span(percent_text(min(shares)), percent_text(max(shares)), judged)

    def with_difference(self) -> tuple[Setting, ...]:
        """Return the settings with a real difference."""
        return tuple(s for s in self.settings if s.difference > 0)

    def wrong_direction(self) -> int:
        """Return how many comparisons with a real difference read the wrong direction."""
        return sum(s.outcomes[WRONG] for s in self.with_difference())

    def wrong_direction_most(self) -> str:
        """Return the largest share in the wrong direction of a setting with a real difference."""
        return percent_text(max((s.share(WRONG) for s in self.with_difference()), default=0.0))

    def false_verdict_most(self) -> str:
        """Return the largest share of experiments with any verdict when there is no difference."""
        rates = [s.verdict_rate for s in self.settings if s.difference == 0]
        return percent_text(max(rates, default=0.0))

    def alpha_percent(self) -> str:
        """Return the rule's alpha in percent: ``5``."""
        return f"{100.0 * self.alpha:g}"


def _int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} is not a count")
    return value


def _setting(raw: Any, index: int) -> Setting:
    where = f"{DATA_FILE}: settings[{index}]"
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} is not an object")
    try:
        outcomes = {o: _int(raw[o], f"{where}.{o}") for o in OUTCOMES}
        setting = Setting(
            model=str(raw["model"]),
            rounds=_int(raw["rounds"], f"{where}.rounds"),
            cases=_int(raw["cases"], f"{where}.cases"),
            noise=float(raw["noise"]),
            difference=_int(raw["difference"], f"{where}.difference"),
            experiments=_int(raw["experiments"], f"{where}.experiments"),
            comparisons=_int(raw["comparisons"], f"{where}.comparisons"),
            outcomes=outcomes,
            any_verdict=_int(raw["any_verdict"], f"{where}.any_verdict"),
        )
    except KeyError as missing:
        raise ValueError(f"{where} has no {missing}") from None
    if sum(outcomes.values()) != setting.comparisons:
        raise ValueError(f"{where}: the outcomes do not add up to the comparisons")
    if setting.any_verdict > setting.experiments:
        raise ValueError(f"{where}: more experiments with a verdict than experiments")
    return setting


def from_data(data: Any) -> ErrorRates:
    """Read the data file's document. A document that is not one is a ``ValueError``."""
    if not isinstance(data, Mapping):
        raise ValueError(f"{DATA_FILE} is not an object")
    try:
        settings = data["settings"]
        if not isinstance(settings, list):
            raise ValueError(f"{DATA_FILE}: settings is not a list")
        return ErrorRates(
            seed=_int(data["seed"], f"{DATA_FILE}: seed"),
            experiments=_int(data["experiments"], f"{DATA_FILE}: experiments"),
            rule=str(data["rule"]),
            alpha=float(data["alpha"]),
            settings=tuple(_setting(raw, i) for i, raw in enumerate(settings)),
        )
    except KeyError as missing:
        raise ValueError(f"{DATA_FILE} has no {missing}") from None


@lru_cache(maxsize=1)
def error_rates() -> ErrorRates:
    """Return the simulated error rates the package carries."""
    text = resources.files(__package__).joinpath(DATA_FILE).read_text(encoding="utf-8")
    return from_data(json.loads(text))


# ---------------------------------------------------------------------------
# The line
# ---------------------------------------------------------------------------


def _cases_words(cases: int) -> str:
    return f"{cases} primary case" + ("" if cases == 1 else "s")


def _caught_words(span: Span) -> str:
    return f"{span.text()} percent of the time"


def _miss_words(rates: ErrorRates) -> str:
    if rates.wrong_direction() == 0:
        return (
            "a miss reads TIE or UNRESOLVED, and no verdict in the wrong direction appears "
            "in the simulated experiments"
        )
    return (
        "a miss reads TIE or UNRESOLVED, or the wrong direction for up to "
        f"{rates.wrong_direction_most()} percent of the metrics in the simulated experiments"
    )


def _no_row(rounds_words: str, missing: Sequence[str]) -> str:
    return (
        f"real differences caught at {rounds_words}: the error-rate page has no row for "
        f"{' or for '.join(missing)} ({ERROR_RATES_PAGE})"
    )


def _known(rates: ErrorRates, rounds: int, cases: int, more_rounds: int | None) -> str:
    twice = rates.caught(rounds, cases, TWICE)
    four = rates.caught(rounds, cases, FOUR_TIMES)
    head = f"real differences caught at {rounds} rounds with {_cases_words(cases)}"
    if twice is None or four is None:
        return _no_row(f"{rounds} rounds", [f"a true difference of {TWICE} times the noise"])
    if not twice.judged:
        return (
            f"{head}: none, as {rounds} rounds are too few for a verdict on "
            f"{_cases_words(cases)} ({ERROR_RATES_PAGE})"
        )
    about = twice.about()
    unit = "metric" if cases > 1 else "run"
    parts = [
        f"{head}: a true difference of twice the noise is caught {_caught_words(twice)}"
        + (f" (about {about.replace('one', f'one {unit}', 1)})" if about else "")
        + f", four times the noise {_caught_words(four)}"
    ]
    if more_rounds is not None and more_rounds > rounds:
        more = rates.caught(more_rounds, cases, TWICE)
        if more is not None and more.judged:
            parts.append(
                f"with --rounds {more_rounds}, twice the noise is caught {_caught_words(more)}"
            )
    parts.append(_miss_words(rates))
    return "; ".join(parts) + f" ({ERROR_RATES_PAGE})"


def _every_count(rates: ErrorRates, rounds: int) -> str:
    """What a round count catches for every number of primary cases the page has."""
    clauses: dict[int, list[str]] = {TWICE: [], FOUR_TIMES: []}
    for difference, words in clauses.items():
        for cases in rates.cases:
            span = rates.caught(rounds, cases, difference)
            if span is None:
                continue
            if not span.judged:
                words.append(f"none with {cases} (too few rounds)")
            else:
                words.append(f"{span.text()} percent with {cases}")
    return (
        "a true difference of twice the noise is caught "
        + ", ".join(clauses[TWICE])
        + "; four times the noise "
        + ", ".join(clauses[FOUR_TIMES])
        + f"; {_miss_words(rates)} ({ERROR_RATES_PAGE})"
    )


def _by_cases(rates: ErrorRates, rounds: int) -> str:
    """The line when the number of primary cases is not known yet: every count the page has."""
    return (
        f"real differences caught at {rounds} rounds depend on the number of primary cases, "
        f"known after warm-up: {_every_count(rates, rounds)}"
    )


def _cases_off_the_page(rates: ErrorRates, rounds: int, cases: int) -> str:
    """The line for a number of primary cases the page has no row for, at a round count it has.

    It says so, then gives what the page has at that round count for the
    numbers of primary cases it simulates: a reader of a TIE sees what the
    round count can miss, with no figure the page does not hold.
    """
    return (
        f"real differences caught at {rounds} rounds with {_cases_words(cases)}: the error-rate "
        f"page has no row for {_cases_words(cases)}; for the numbers of primary cases it has, "
        f"{_every_count(rates, rounds)}"
    )


def odds_line(
    rounds: Sequence[int],
    cases: int | None,
    *,
    subjects: int = 1,
    rule: str,
    more_rounds: int | None = None,
    rates: ErrorRates | None = None,
) -> str:
    """Return how often ``rounds`` catch a real difference, in one line.

    ``rounds`` holds the round counts of the comparisons, one count when they
    agree. ``cases`` is the number of primary cases, ``None`` when it is not
    known yet. ``subjects`` counts the sides compared with the baseline.
    ``more_rounds`` names the next round count to offer; the line then says
    what it catches too. A round count, a number of cases, a number of
    subjects or a rule the simulation has no row for is said, not guessed;
    for a number of cases alone, the line also gives what the round count
    catches for the numbers of cases the simulation has.
    """
    rates = error_rates() if rates is None else rates
    counts = sorted(set(rounds))
    if not counts:
        return _no_row("no round", ["a run without paired rounds"])
    rounds_words = (
        f"{counts[0]} rounds" if len(counts) == 1 else f"{counts[0]} to {counts[-1]} rounds"
    )
    if rule != rates.rule:
        return (
            f"real differences caught at {rounds_words}: the error-rate page simulates the "
            f"rule {rates.rule} and has no row for the rule {rule} ({ERROR_RATES_PAGE})"
        )
    if subjects != 1:
        return (
            f"real differences caught at {rounds_words}: the error-rate page simulates one "
            f"side against the baseline and has no row for {subjects} sides compared with it "
            f"({ERROR_RATES_PAGE})"
        )
    missing: list[str] = []
    if len(counts) > 1:
        missing.append(f"a mix of {rounds_words}")
    elif counts[0] not in rates.rounds:
        missing.append(rounds_words)
    if cases is not None and cases not in rates.cases:
        if not missing:
            return _cases_off_the_page(rates, counts[0], cases)
        missing.append(_cases_words(cases))
    if missing:
        head = rounds_words if cases is None else f"{rounds_words} with {_cases_words(cases)}"
        return _no_row(head, missing)
    if cases is None:
        return _by_cases(rates, counts[0])
    return _known(rates, counts[0], cases, more_rounds)


def sentence(line: str) -> str:
    """Return a line as a sentence of a report: a capital first letter and a full stop."""
    return line[:1].upper() + line[1:] + "."


def settings_rows(settings: Iterable[Setting]) -> list[dict[str, Any]]:
    """Return the settings as the rows of the data file, in the order given."""
    return [
        {
            "model": s.model,
            "rounds": s.rounds,
            "cases": s.cases,
            "noise": s.noise,
            "difference": s.difference,
            "experiments": s.experiments,
            "comparisons": s.comparisons,
            **{o: s.outcomes[o] for o in OUTCOMES},
            "any_verdict": s.any_verdict,
        }
        for s in settings
    ]


__all__ = [
    "CAUGHT",
    "DATA_FILE",
    "ERROR_RATES_PAGE",
    "FOUR_TIMES",
    "OUTCOMES",
    "TWICE",
    "WRONG",
    "ErrorRates",
    "Setting",
    "Span",
    "error_rates",
    "from_data",
    "odds_line",
    "percent_text",
    "sentence",
    "settings_rows",
    "whole_percent",
]
