# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The charts of a run: the verdicts, each case round by round, the noise and the resources.

The charts are drawn from the results document and, when it is given, the
diagnostics document. They never read a capture, so ``pairbench report``
can draw them again later from the run folder. matplotlib, which the
``plot`` extra brings, is imported only inside the functions that draw, and
every chart is drawn on a canvas that writes SVG and needs no display.

Every chart is one SVG file under ``charts/`` in the run folder:

* text is written as text, so it can be searched and read aloud;
* a case or side name is written as character data, never as markup, and
  the characters ``=``, ``(`` and ``@`` in text are written as character
  references, so no run text can read as an address;
* nothing in a file makes a viewer fetch anything (``model.points_outside``
  finds nothing in it);
* sizes are fixed by the data, the ids inside the file come from a fixed
  salt and the file holds no date, so two draws from the same documents in
  the same environment are equal byte for byte.

This module also holds the texts the charts and the report page share: a
ratio, the change in words, the noise band, a p-value and a median. A text
that the results already carry as a figure is taken from there.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pairbench import model
from pairbench.api import Notify, no_notes
from pairbench.model import (
    NOTE_CHARTS_NOT_DRAWN,
    Case,
    Diagnostics,
    Results,
)
from pairbench.results.figures import (
    bar_text,
    floor_text,
    median_text,
    number_text,
    p_text,
    ratio_text,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# The extra that brings matplotlib, as a user installs it.
PLOT_EXTRA: Final = "pairbench[plot]"
# The most round-by-round charts a run draws, unless told otherwise.
MAX_ROUND_CHARTS: Final = 12
# The salt of the ids matplotlib writes into a file: fixed, so a redraw is byte-equal.
HASH_SALT: Final = "pairbench"

NOT_DRAWN_MESSAGE: Final = (
    "charts were not drawn: the plot extra is not installed; "
    f"install {PLOT_EXTRA} and run pairbench report --plots on in the run folder to draw them"
)

# Settings every chart is drawn with, on top of matplotlib's defaults.
_SETTINGS: Final[dict[str, Any]] = {
    "svg.fonttype": "none",
    "svg.hashsalt": HASH_SALT,
    "text.parse_math": False,
    "text.usetex": False,
    "axes.formatter.use_mathtext": False,
    "font.size": 10.0,
}
# What matplotlib would write into the file's metadata: nothing, and no date.
_NO_METADATA: Final[dict[str, Any]] = {"Date": None, "Creator": None, "Format": None, "Type": None}

# Colours. Each mark also carries a word or a shape, so colour is never the only cue.
INK: Final = "#000000"
BAND: Final = "#c8c8c8"
PALETTE: Final[tuple[str, ...]] = (
    "#0072b2",
    "#d55e00",
    "#009e73",
    "#cc79a7",
    "#e69f00",
    "#56b4e9",
    "#7f7f7f",
    "#8c564b",
)
OUTCOME_COLOURS: Final[dict[str, str]] = {
    "better": "#009e73",
    "worse": "#d55e00",
    "higher": "#0072b2",
    "lower": "#0072b2",
    "tie": "#555555",
    "unresolved": "#e69f00",
    "no_verdict": "#7f7f7f",
}

# Factors a ratio axis may mark on each side of 1.
_FACTORS: Final[tuple[float, ...]] = (
    1.01,
    1.02,
    1.05,
    1.1,
    1.25,
    1.5,
    2.0,
    3.0,
    5.0,
    10.0,
    100.0,
    1000.0,
)
# A ratio axis shows at least 1/1.25 to 1.25, and a margin beyond the farthest mark.
SMALLEST_REACH: Final = 1.25
# A ratio axis reaches at most from 1e-100 to 1e100, so its ends and its scale stay finite.
LARGEST_REACH: Final = 1e100
_MARGIN: Final = 1.15
_MOST_TICKS_PER_SIDE: Final = 3


# ---------------------------------------------------------------------------
# Texts shared by the charts and the report page
# ---------------------------------------------------------------------------


def change_text(ratio: float | None, kind: str, *, better: str = "lower") -> str:
    """Write the change of a subject against the baseline in words.

    The number is the larger of the ratio and its inverse. For a case of
    kind ``time`` where lower is better the word is ``faster`` or
    ``slower``; for every other case, a time case where higher is better
    among them, it says which way the number moved, ``higher`` or ``lower``:
    ``1.26x faster``, ``1.04x higher``. A ratio of exactly 1 has no word. A
    ratio of zero or less has no inverse and is written as it is, and a
    missing ratio is ``no ratio``.
    """
    if ratio is None or not math.isfinite(ratio):
        return "no ratio"
    if ratio <= 0:
        return ratio_text(ratio)
    if ratio == 1:
        return ratio_text(1.0)
    timed = kind == "time" and better != "higher"
    if ratio < 1:
        return f"{ratio_text(1.0 / ratio)} {'faster' if timed else 'lower'}"
    return f"{ratio_text(ratio)} {'slower' if timed else 'higher'}"


def as_percent(value: float, unit: str) -> float:
    """Return a floor or a bar in percent; ``unit`` is ``fraction`` or ``percent``."""
    return value * 100.0 if unit == "fraction" else value


def figure_text(results: Results, key: str) -> str | None:
    """Return the text of a figure of the results, or ``None`` when the results do not carry it."""
    figure = results.figures.get(key)
    return None if figure is None else figure.text


def case_of(results: Results, case: str) -> Case | None:
    """Return the record of a case of the results, or ``None`` when the results do not hold it."""
    return next((c for c in results.cases if c.id == case), None)


def kind_of(results: Results, case: str) -> str:
    """Return the kind of a case: ``time``, ``count`` or ``other`` (also when it is not known)."""
    record = case_of(results, case)
    if record is not None:
        return record.kind
    if case in model.RESOURCE_CASES:
        return model.resource_case(case).kind
    return "other"


def better_of(results: Results, case: str) -> str:
    """Return which way a case is better: ``lower``, ``higher`` or ``none``.

    A case the results do not hold is taken as ``lower``.
    """
    record = case_of(results, case)
    if record is not None:
        return record.better
    if case in model.RESOURCE_CASES:
        return model.resource_case(case).better
    return "lower"


def unit_of(results: Results, case: str) -> str:
    """Return the unit of a case, or an empty text when it is not known."""
    record = case_of(results, case)
    if record is not None:
        return record.unit
    return model.RESOURCE_CASES.get(case, "")


# ---------------------------------------------------------------------------
# The ratio axis: logarithmic and centred at 1
# ---------------------------------------------------------------------------


def log_limits(values: Iterable[float]) -> tuple[float, float]:
    """Return the ends of a ratio axis that is logarithmic and centred at 1.

    The ends are ``1/h`` and ``h``, so a ratio and its inverse sit equally
    far from the centre line: ``2x faster`` and ``2x slower`` alike. ``h``
    reaches past the farthest positive value by a margin, is at least
    ``SMALLEST_REACH`` and at most ``LARGEST_REACH``; a value beyond that
    lies off the axis. Values of zero or less and values that are not
    finite are left out.
    """
    reach = max(
        (abs(math.log(v)) for v in values if math.isfinite(v) and v > 0),
        default=0.0,
    )
    wanted = max(reach * _MARGIN, math.log(SMALLEST_REACH))
    high = math.exp(min(wanted, math.log(LARGEST_REACH)))
    return 1.0 / high, high


def log_ticks(high: float) -> list[tuple[float, str]]:
    """Return the marks of a ratio axis that ends at ``1/high`` and ``high``, with their texts.

    The marks are 1 and, on each side, the same factors: at most three of
    ``_FACTORS`` that fit and lie far enough from 1 to be read apart from
    it, always the largest. ``2x`` above 1 has ``0.5x`` below it.
    """
    reach = math.log(high)
    fitting = [f for f in _FACTORS if reach / 3 <= math.log(f) <= reach * (1 + 1e-9)]
    if not fitting:
        fitting = [f for f in _FACTORS if math.log(f) <= reach * (1 + 1e-9)][-1:]
    if len(fitting) > _MOST_TICKS_PER_SIDE:
        last = len(fitting) - 1
        picks = sorted({round(i * last / (_MOST_TICKS_PER_SIDE - 1)) for i in range(3)})
        fitting = [fitting[i] for i in picks]
    below = [(1.0 / f, f"{1.0 / f:.3g}x") for f in reversed(fitting)]
    above = [(f, f"{f:g}x") for f in fitting]
    return [*below, (1.0, "1x"), *above]


def band_of(bar: float | None, unit: str) -> tuple[float, float] | None:
    """Return the noise band around a ratio of 1: from ``1 - bar`` to ``1 + bar``.

    The bar is a fraction, or a percentage when ``unit`` is ``percent``, and
    a percentage is divided by 100: a bar of 1.8 in percent and one of 0.018
    as a fraction give the same band. A missing or negative bar gives no
    band. A bar of 1 or more reaches zero; the lower end is then zero or
    less, and a drawing starts the band at the end of its axis.
    """
    if bar is None or not math.isfinite(bar) or bar < 0:
        return None
    fraction = bar / 100.0 if unit == "percent" else bar
    return 1.0 - fraction, 1.0 + fraction


def drawable_ratio(ratio: float | None) -> float | None:
    """Return a ratio a log axis can show, or ``None`` for one that is missing or not above 0."""
    if ratio is None or not math.isfinite(ratio) or ratio <= 0:
        return None
    return ratio


# ---------------------------------------------------------------------------
# Drawing: matplotlib is imported here, inside functions only
# ---------------------------------------------------------------------------


@contextmanager
def drawing() -> Iterator[None]:
    """Apply the settings every chart is drawn and written with, then restore the old ones."""
    import matplotlib
    import matplotlib.style

    settings: Any = _SETTINGS
    with matplotlib.style.context("default"), matplotlib.rc_context(settings):
        yield


def new_figure(width: float, height: float) -> Figure:
    """Return an empty figure of a fixed size in inches on a canvas that writes SVG."""
    from matplotlib.backends.backend_svg import FigureCanvasSVG
    from matplotlib.figure import Figure

    figure = Figure(figsize=(width, height), layout="constrained")
    FigureCanvasSVG(figure)
    return figure


def plain_number(value: float, _position: int | None = None) -> str:
    """Write a number on a value axis without exponent markup: ``1.92``, ``2.41e+09``."""
    return f"{value:.6g}"


# A linear value axis draws values up to this size as they are. When a value
# is larger, every value is divided by AXIS_DIVISOR first, so the axis, its
# margins and its ticks stay finite numbers; the tick labels still give the
# values themselves.
AXIS_AS_IS: Final = 1e300
AXIS_DIVISOR: Final = 1e20


def axis_divisor(values: Iterable[float | None]) -> float:
    """Return what a linear value axis divides its values by: 1, or ``AXIS_DIVISOR``."""
    largest = max((abs(v) for v in values if v is not None and math.isfinite(v)), default=0.0)
    return AXIS_DIVISOR if largest > AXIS_AS_IS else 1.0


def axis_number(divisor: float) -> Callable[[float, int | None], str]:
    """Return the tick label writer of a linear value axis divided by ``divisor``.

    A label gives the value a tick stands for, as ``plain_number`` writes it.
    A tick in the margin beyond the float range gets no label.
    """

    def write(value: float, _position: int | None = None) -> str:
        real = float(value) * divisor
        return plain_number(real) if math.isfinite(real) else ""

    return write


def whole_number(value: float, _position: int | None = None) -> str:
    """Write a round number on the round axis: ``3``."""
    return f"{value:.0f}"


_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>\s*", re.IGNORECASE)
_TEXT_ELEMENT = re.compile(r"(<text\b[^>]*>)(.*?)(</text>)", re.DOTALL)
_MARKUP = re.compile(r"(<[^>]*>)")
_AS_REFERENCES = str.maketrans({"=": "&#61;", "(": "&#40;", "@": "&#64;"})
# Characters an XML document may not hold. A run name can carry one; it is
# written as the replacement character, so the file stays well-formed.
_NOT_IN_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _as_character_data(element: re.Match[str]) -> str:
    """Write ``=``, ``(`` and ``@`` in the character data of one text element as references."""
    opening, body, closing = element.groups()
    parts = _MARKUP.split(body)
    body = "".join(p if p.startswith("<") else p.translate(_AS_REFERENCES) for p in parts)
    return f"{opening}{body}{closing}"


def finish_svg(text: str) -> str:
    """Make the SVG text matplotlib wrote ready to keep.

    The document type line, which names an address, is removed. In every
    text element the characters ``=``, ``(`` and ``@`` are written as
    character references, so a run name such as ``src=x`` or ``url(x)``
    cannot read as a reference to a file. matplotlib has already written
    ``<``, ``>`` and ``&`` as references. A character that XML does not
    allow, such as a control character in a run name, becomes the
    replacement character ``U+FFFD``, so the file stays well-formed. A
    result that still points outside itself is refused.
    """
    text = _NOT_IN_XML.sub("\ufffd", text)
    text = _DOCTYPE.sub("", text, count=1)
    text = _TEXT_ELEMENT.sub(_as_character_data, text)
    outside = model.points_outside(text)
    if outside:
        raise ValueError(f"a chart points outside itself: {', '.join(outside)}")
    return text


def svg_of(figure: Figure) -> bytes:
    """Write a figure as SVG with text kept as text and no metadata, and return the bytes."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="svg", metadata=_NO_METADATA)
    return finish_svg(buffer.getvalue().decode("utf-8")).encode("utf-8")


# ---------------------------------------------------------------------------
# All charts of a run
# ---------------------------------------------------------------------------


def _write(out: Path, pieces: Sequence[tuple[str, bytes]]) -> list[Path]:
    """Write the drawn charts under ``out``; on any failure remove what this call wrote."""
    written: list[Path] = []
    try:
        for file, content in pieces:
            path = out / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written.append(path)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written


def draw_charts(
    results: Results,
    *,
    out: Path,
    diagnostics: Diagnostics | None = None,
    max_round_charts: int = MAX_ROUND_CHARTS,
    note: Notify = no_notes,
) -> list[Path]:
    """Draw the charts of a run into ``out`` and return the paths of the files, in order.

    The order is: the verdict chart, the round-by-round chart of each
    primary case, the noise chart, the resource chart. Each file is named by
    ``model.chart_file`` under ``out``.

    Without the ``plot`` extra nothing is drawn, the answer is an empty list
    and one note (``NOTE_CHARTS_NOT_DRAWN``) names the extra. At most
    ``max_round_charts`` round-by-round charts are drawn, in the order of
    the results; how many more were not drawn is a note
    (``NOTE_ROUND_CHARTS_LEFT_OUT``). A chart whose data is absent is not
    drawn, and the reason is a note (``NOTE_CHART_WITHOUT_DATA``); when no
    chart has data the answer is an empty list too, and only the note code
    tells it from a missing extra.

    Every chart is drawn before any file is written. A failure raises and
    leaves no file of this call behind; the caller records the charts as not
    drawn.
    """
    try:
        import matplotlib  # noqa: F401  (a missing extra shows here, as an ImportError)
    except ImportError:
        note(NOTE_CHARTS_NOT_DRAWN, NOT_DRAWN_MESSAGE)
        return []
    from pairbench.charts import noise, resources, rounds, verdict

    pieces: list[tuple[str, bytes]] = [
        *verdict.draw_all(results, note),
        *rounds.draw_all(results, max_round_charts, note),
        *noise.draw_all(results, note),
        *resources.draw_all(results, diagnostics, note),
    ]
    return _write(Path(out), pieces)


__all__ = [
    "AXIS_AS_IS",
    "AXIS_DIVISOR",
    "HASH_SALT",
    "LARGEST_REACH",
    "MAX_ROUND_CHARTS",
    "NOT_DRAWN_MESSAGE",
    "PLOT_EXTRA",
    "SMALLEST_REACH",
    "as_percent",
    "axis_divisor",
    "axis_number",
    "band_of",
    "bar_text",
    "better_of",
    "case_of",
    "change_text",
    "draw_charts",
    "drawable_ratio",
    "drawing",
    "figure_text",
    "finish_svg",
    "floor_text",
    "kind_of",
    "log_limits",
    "log_ticks",
    "median_text",
    "new_figure",
    "number_text",
    "p_text",
    "plain_number",
    "ratio_text",
    "svg_of",
    "unit_of",
    "whole_number",
]
