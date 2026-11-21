# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The figures of a results document and the texts every report writes.

``figures`` is a flat map from a stable key to ``{"value": ..., "text": ...}``.
The value is the number as the analysis computed it; rounding happens only
when the text is formed. The verdict figure is the one figure whose value is
a word: the outcome (``better``, ``worse``, ``higher``, ``lower``, ``tie``,
``unresolved`` or ``no_verdict``), with the display word as its text.

A figure whose number is absent from the comparison, or is no finite number,
is left out of the map. It is never written as an empty text, so a document
that names it is refused when it is filled. So is a key under which two
different figures would be written.

The text functions of this module are the one place where a report turns a
number into text: the terminal report, the markdown report and the figures
use the same forms.
"""

from __future__ import annotations

import dataclasses
import math

from pairbench.model import (
    FIGURE_LAUNCH_COST_MEDIAN,
    FIGURE_LAUNCH_COST_SPREAD,
    Case,
    Comparison,
    Figure,
    Results,
    figure_key,
    median_key,
    p_written,
)

# How many significant digits a median is written with.
MEDIAN_DIGITS = 3
# How many significant digits a p-value is written with.
P_DIGITS = 2
# A ratio, a percentage, a floor or a bar of this size or more is written in
# the short form: three significant digits and an exponent, ``2.5e+07x``.
SHORT_FROM = 1e6
# A number is written in fixed notation when its exponent, after rounding to
# its significant digits, lies in this range, and in the short form
# otherwise: ``0.000123`` and ``2410000000``, but ``1.23e-05`` and
# ``1.00e+15``. Beyond it, fixed notation would show the digits of the
# binary number past the ones that were kept.
FIXED_EXPONENTS = range(-4, 15)


def _short(value: float) -> str:
    """Write a number with three significant digits, with an exponent when it is far from 1."""
    return f"{value:.3g}"


def ratio_text(ratio: float, decimals: int = 2) -> str:
    """Write a ratio with two decimals and ``x``: ``0.80x``.

    ``decimals`` sets how many decimals the fixed form has. A ratio of a
    million or more, or one above zero and below the step of those decimals
    (``0.01`` for two), is written in the short form: ``2.5e+07x``,
    ``0.0099x``, ``1e-10x``.
    """
    size = abs(ratio)
    if size >= SHORT_FROM or 0 < size < 10.0**-decimals:
        return f"{_short(ratio)}x"
    return f"{ratio:.{decimals}f}x"


def percent_text(percent: float) -> str:
    """Write a signed percentage with one decimal: ``-20.3%``, ``+5.0%``.

    A value that rounds to zero is written ``0.0%``, without a sign, and a
    value of a million or more in the short form, ``+1e+08%``.
    """
    if abs(percent) >= SHORT_FROM:
        return f"{percent:+.3g}%"
    text = f"{percent:+.1f}"
    if text in ("+0.0", "-0.0"):
        text = "0.0"
    return f"{text}%"


def p_text(p: float) -> str:
    """Write a p-value with two significant digits: ``0.0010``, ``0.23``, ``3.0e-05``.

    The form is Python's general format with the trailing zeros kept, so the
    text always shows two significant digits. A p-value below
    ``model.P_SMALLEST_WRITTEN`` is written as the bound ``< 1e-300``; its
    float can be zero.
    """
    return p_written(p, f"#.{P_DIGITS}g")


def _as_percent(value: float, unit: str) -> float:
    """Return a floor, a bar or a gap in percent; ``unit`` is ``fraction`` or ``percent``."""
    return value * 100.0 if unit == "fraction" else value


def _percent_number(value: float) -> str:
    """Write a percentage without its sign: one decimal, or the short form from a million on."""
    return _short(value) if abs(value) >= SHORT_FROM else f"{value:.1f}"


def writable_percent(value: float | None, unit: str) -> float | None:
    """Return a floor or a bar that is a finite number as a percentage, or ``None``.

    Floors and bars are written as percentages, so one whose percentage is no
    finite number has no text; every report shows it as missing.
    """
    if value is None or not math.isfinite(_as_percent(value, unit)):
        return None
    return value


def floor_or(value: float | None, unit: str, missing: str) -> str:
    """Write a floor as ``floor_text`` does, or ``missing`` when it has no text."""
    shown = writable_percent(value, unit)
    return missing if shown is None else floor_text(shown, unit)


def bar_text(bar: float, unit: str) -> str:
    """Write the bar a gap must exceed, as a percentage with ``±``: ``±1.8%``.

    A bar of a million percent or more is written in the short form: ``±1e+06%``.
    """
    return f"±{_percent_number(_as_percent(bar, unit))}%"


def floor_text(floor: float, unit: str) -> str:
    """Write a noise floor as a percentage: ``1.1%``.

    A floor of a million percent or more is written in the short form: ``2.5e+10%``.
    """
    return f"{_percent_number(_as_percent(floor, unit))}%"


def number_text(value: float, digits: int = MEDIAN_DIGITS) -> str:
    """Write a number with a given count of significant digits.

    The form is fixed notation while the exponent lies in
    ``FIXED_EXPONENTS``: ``1.9234`` gives ``1.92``, ``2410000000`` gives
    ``2410000000`` and ``0.0005`` gives ``0.000500``. Beyond it the number
    has the short form, the digits and an exponent: ``1e300`` gives
    ``1.00e+300`` and ``0.0000123`` gives ``1.23e-05``. Zero is written
    ``0``, and a value that is no finite number as Python writes it.
    """
    if value == 0:
        return "0"
    if not math.isfinite(value):
        return str(value)
    short = format(value, f".{digits - 1}e")
    exponent = int(short.partition("e")[2])
    if exponent not in FIXED_EXPONENTS:
        return short
    rounded = float(short)
    decimals = digits - 1 - exponent
    if decimals > 0:
        return f"{rounded:.{decimals}f}"
    return f"{round(rounded, decimals):.0f}"


def median_text(value: float, unit: str) -> str:
    """Write a median with three significant digits and its unit: ``1.92 s``."""
    number = number_text(value)
    return f"{number} {unit}" if unit else number


def statistic_text(statistic: float, scale: str) -> str:
    """Write the graded statistic in the form of its scale.

    Under scale ``ratio`` it is a ratio (``0.80x``); under scale ``percent``
    it is the median of the per-round percent differences (``-20.3%``).
    """
    return percent_text(statistic) if scale == "percent" else ratio_text(statistic)


def speedup_of(ratio: float, better: str) -> float | None:
    """Return the speed-up of a subject: above 1 always means the subject is better.

    Where lower is better it is the inverse of the ratio, where higher is
    better the ratio itself. A case whose ``better`` is ``none`` has no
    better side, and a ratio of zero or less has no inverse: both give
    ``None``.
    """
    if ratio <= 0 or better not in ("lower", "higher"):
        return None
    return 1.0 / ratio if better == "lower" else ratio


def change_text(ratio: float, kind: str, *, better: str = "lower") -> str:
    """Write the change of a subject against the baseline in words.

    The number is the larger of the ratio and its inverse. For a case of
    kind ``time`` where lower is better the word is ``faster`` or
    ``slower``; for every other case it says which way the number moved,
    ``higher`` or ``lower``: ``1.26x faster``, ``1.04x higher``. A time case
    where higher is better is not a run time, so it moves higher or lower
    and never reads ``faster`` beside a slower verdict. A ratio of exactly 1
    has no word, and a ratio of zero or less has no inverse and is written as
    it is.
    """
    if ratio <= 0:
        return ratio_text(ratio)
    if ratio == 1:
        return ratio_text(1.0)
    timed = kind == "time" and better != "higher"
    if ratio < 1:
        return f"{ratio_text(1.0 / ratio)} {'faster' if timed else 'lower'}"
    return f"{ratio_text(ratio)} {'slower' if timed else 'higher'}"


def _comparison_figures(comparison: Comparison, case: Case | None) -> dict[str, Figure]:
    """Return the figures of one comparison, keyed by their figure names."""
    better = case.better if case is not None else "lower"
    unit = comparison.floor.unit
    out: dict[str, Figure] = {}
    if comparison.ratio is not None:
        out["ratio"] = Figure(value=comparison.ratio, text=ratio_text(comparison.ratio))
    if comparison.statistic is not None:
        text = statistic_text(comparison.statistic, comparison.scale)
        out["statistic"] = Figure(value=comparison.statistic, text=text)
    if comparison.ratio is not None:
        # The analysis leaves out a ratio whose inverse or percent is no finite
        # number; a document made elsewhere may still hold one.
        speedup = speedup_of(comparison.ratio, better)
        if speedup is not None and math.isfinite(speedup):
            out["speedup"] = Figure(value=speedup, text=ratio_text(speedup))
        percent = 100.0 * (comparison.ratio - 1.0)
        if math.isfinite(percent):
            out["percent"] = Figure(value=percent, text=percent_text(percent))
    if comparison.p_raw is not None:
        out["p"] = Figure(value=comparison.p_raw, text=p_text(comparison.p_raw))
    if comparison.p_corrected is not None:
        out["p_corrected"] = Figure(
            value=comparison.p_corrected, text=p_text(comparison.p_corrected)
        )
    # Bars and floors are written as percentages; one whose percentage is no
    # finite number, such as a floor a caller supplied, has no figure.
    bar = writable_percent(comparison.bar, unit)
    if bar is not None:
        out["bar"] = Figure(value=bar, text=bar_text(bar, unit))
    for name, floor in (
        ("floor_subject", comparison.floor.subject),
        ("floor_baseline", comparison.floor.baseline),
    ):
        if floor is not None and writable_percent(floor.value, unit) is not None:
            out[name] = Figure(value=floor.value, text=floor_text(floor.value, unit))
    out["n"] = Figure(value=comparison.n_untied, text=str(comparison.n_untied))
    out["verdict"] = Figure(value=comparison.outcome, text=comparison.verdict)
    return out


class _FigureMap:
    """A figures map that leaves out every key whose figure is not one figure.

    A key is left out when two different things would be written under it:
    names may hold dots, so case ``a.b`` with subject ``c`` and case ``a``
    with subject ``b.c`` give the same key; or when one side's median on a
    case differs between the comparisons that hold it. A document that
    names such a key is then refused when it is filled, never given one of
    the two numbers.
    """

    def __init__(self) -> None:
        self.figures: dict[str, Figure] = {}
        self._sources: dict[str, tuple[str, ...]] = {}
        self._left_out: set[str] = set()

    def put(self, key: str, source: tuple[str, ...], figure: Figure) -> None:
        """Write a figure under a key; ``source`` names what the figure belongs to."""
        if key in self._left_out:
            return
        if key not in self.figures:
            self.figures[key] = figure
            self._sources[key] = source
        elif self._sources[key] != source or self.figures[key] != figure:
            self._left_out.add(key)
            del self.figures[key]


def figures_of(results: Results) -> dict[str, Figure]:
    """Return the figures map of a results document.

    Per comparison: the figures of ``model.FIGURE_NAMES`` whose numbers it
    holds, under ``<case>.<subject>_vs_<baseline>.<name>``, and the median of
    each side under ``<case>.<side>.median``. A run that measured the cost
    of a launch adds ``launch_cost.median`` and ``launch_cost.spread``, in
    seconds. Keys come in the order of the comparisons. A key under which
    two different figures would be written is left out.
    """
    cases = {case.id: case for case in results.cases}
    out = _FigureMap()
    for comparison in results.comparisons:
        case = cases.get(comparison.case)
        unit = case.unit if case is not None else ""
        source = ("comparison", comparison.case, comparison.subject, comparison.baseline)
        for name, figure in _comparison_figures(comparison, case).items():
            key = figure_key(comparison.case, comparison.subject, comparison.baseline, name)
            out.put(key, source, figure)
        for side, median in (
            (comparison.subject, comparison.subject_median),
            (comparison.baseline, comparison.baseline_median),
        ):
            if median is not None:
                out.put(
                    median_key(comparison.case, side),
                    ("median", comparison.case, side),
                    Figure(value=median, text=median_text(median, unit)),
                )
    cost = results.launch_cost
    if cost is not None:
        out.put(
            FIGURE_LAUNCH_COST_MEDIAN,
            ("launch_cost",),
            Figure(value=cost.median_s, text=median_text(cost.median_s, "s")),
        )
        out.put(
            FIGURE_LAUNCH_COST_SPREAD,
            ("launch_cost",),
            Figure(value=cost.spread_s, text=median_text(cost.spread_s, "s")),
        )
    return out.figures


def with_figures(results: Results) -> Results:
    """Return the results with ``figures`` filled from the document; nothing else changes.

    The map is built again from the comparisons and the cost of a launch,
    so a map the document already held is replaced.
    """
    return dataclasses.replace(results, figures=figures_of(results))


__all__ = [
    "FIXED_EXPONENTS",
    "MEDIAN_DIGITS",
    "P_DIGITS",
    "SHORT_FROM",
    "bar_text",
    "change_text",
    "figures_of",
    "floor_or",
    "floor_text",
    "median_text",
    "number_text",
    "p_text",
    "percent_text",
    "ratio_text",
    "speedup_of",
    "statistic_text",
    "with_figures",
    "writable_percent",
]
