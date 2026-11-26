# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Draw the share image of the documentation site: ``site/public/share.png``.

A page shared on a social site or in a chat shows this image beside its title. It holds
a band of the site's accent gradient along its top, the mark of the site (the four tiles of
``docs/readme/mark-dark.svg``, in the order of two alternating rounds), the name pairbench
and one line on what it does, on the dark ground of the site, with the maker's logo in the top
right corner, drawn from ``docs/readme/eugo-logo.svg`` as the README's banner nests it: its
outlines, each filled with its own gradient. The mark is drawn as its file draws it: a soft
shadow straight down under all four tiles, each tile shaded from top to bottom in its own
colour, and a faint white line just inside each tile's edge that fades out before the middle of
the tile.

The drawing uses only the standard library and arithmetic that gives the same result on
every machine: the letters are strokes of a small built-in font, made of straight pieces
and of arcs whose points come from square roots, never from the system's fonts or its
trigonometry; the logo's curves are cut into straight pieces by de Casteljau's construction,
which only adds and multiplies. The shadow is blurred by three passes of a box filter, whose
widths come from a square root and whose sums are whole numbers, never by the exponential of a
Gaussian. The build copies the committed file as it is, once ``is_current`` finds it
is the file this script writes, up to how its rows are compressed; ``is_current`` says
exactly what it accepts and what it refuses, and ``refusal`` names why a file is refused.

Usage::

    python3 tools/share_image.py          # write site/public/share.png
    python3 tools/share_image.py --check  # exit 1, naming the cause, when the file differs
"""

from __future__ import annotations

import argparse
import functools
import itertools
import math
import re
import struct
import sys
import zlib
from array import array
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = "site/public/share.png"
WIDTH = 1200
HEIGHT = 630
NAME = "pairbench"
LINE = "Tells real benchmark differences from noise"
ALT = (
    f"The name {NAME} in white beside its mark of four rounded tiles in violet and blue, above "
    f"the line “{LINE}”, on a dark background under a violet-to-blue band, with the maker's "
    "logo in the top right corner."
)

Point = tuple[float, float]
Stroke = list[Point]
Colour = tuple[int, int, int]
# The colour of a layer at a pixel, given its column and its row.
Paint = Callable[[int, int], Colour]

# The dark palette of the site: its ground, its text, a softer text, and the stops of its
# gradient, each a colour and the share of the width where it falls, in hundredths.
BACKGROUND: Colour = (0x16, 0x0F, 0x3D)
NAME_COLOUR: Colour = (0xFF, 0xFF, 0xFF)
LINE_COLOUR: Colour = (0xD6, 0xD3, 0xEE)
GRADIENT: tuple[tuple[Colour, int], ...] = (
    ((0x8E, 0x45, 0xFF), 0),
    ((0x6A, 0x5C, 0xFF), 45),
    ((0x2A, 0xA6, 0xFF), 100),
)
BAND_HEIGHT = 10

# The mark of ``docs/readme/mark-dark.svg``, in its 64-unit space. Each tile is shaded from
# its top colour to its bottom one.
VIOLET: tuple[Colour, Colour] = ((0xB2, 0x6B, 0xFF), (0xA2, 0x4B, 0xFF))
AZURE: tuple[Colour, Colour] = ((0x4D, 0xB6, 0xFF), (0x2A, 0xA6, 0xFF))
MARK_UNITS = 64.0
TILE = 26.0
TILE_RADIUS = 7.0
# The shadow: black, straight down by its offset, blurred with its standard deviation, and
# cut to the mark's 64 units, the region of the file's filter.
SHADOW: Colour = (0x00, 0x00, 0x00)
SHADOW_OPACITY = 0.55
SHADOW_OFFSET = 1.2
SHADOW_DEVIATION = 1.2
# The highlight: a white line one unit wide, half a unit inside each tile's edge, at its
# opacity at the top, fading to nothing over its share of the line's height.
HIGHLIGHT: Colour = (0xFF, 0xFF, 0xFF)
HIGHLIGHT_OPACITY = 0.22
HIGHLIGHT_WIDTH = 1.0
HIGHLIGHT_REACH = 0.45
# The box passes that blur the shadow, and the whole steps of coverage the blur sums.
BLUR_PASSES = 3
COVER_STEPS = 1024
# The maker's logo: the file that draws it, its width in the image, and its distance from the
# top and from the right edge, in pixels. Each curve of its outlines is drawn as
# ``CURVE_PIECES`` straight pieces, and each row of pixels is crossed by ``SAMPLES`` lines.
LOGO = REPO / "docs" / "readme" / "eugo-logo.svg"
LOGO_WIDTH = 160.0
LOGO_TOP = 40.0
LOGO_RIGHT = 44.0
CURVE_PIECES = 8
SAMPLES = 16

# --- directions without trigonometry -------------------------------------------------------

_R2 = math.sqrt(2.0)
_R3 = math.sqrt(3.0)
_R6 = math.sqrt(6.0)
# The cosine and sine of 0, 15, 30, 45, 60, 75 and 90 degrees, from square roots alone.
_FIRST_QUADRANT: tuple[Point, ...] = (
    (1.0, 0.0),
    ((_R6 + _R2) / 4.0, (_R6 - _R2) / 4.0),
    (_R3 / 2.0, 0.5),
    (_R2 / 2.0, _R2 / 2.0),
    (0.5, _R3 / 2.0),
    ((_R6 - _R2) / 4.0, (_R6 + _R2) / 4.0),
    (0.0, 1.0),
)
STEP_DEGREES = 15
PIECES_PER_STEP = 4


def direction(degrees: int) -> Point:
    """The unit vector at an angle that is a multiple of 15 degrees, counter-clockwise."""
    if degrees % STEP_DEGREES:
        raise ValueError(f"an angle must be a multiple of {STEP_DEGREES} degrees: {degrees}")
    turn = degrees % 360
    quadrant, rest = divmod(turn, 90)
    x, y = _FIRST_QUADRANT[rest // STEP_DEGREES]
    for _ in range(quadrant):
        x, y = -y, x
    return x, y


def _between(a: Point, b: Point, t: float) -> Point:
    """A point on the unit circle between two unit vectors, by a normalised straight mix."""
    x = a[0] + (b[0] - a[0]) * t
    y = a[1] + (b[1] - a[1]) * t
    length = math.sqrt(x * x + y * y)
    return x / length, y / length


def arc(cx: float, cy: float, rx: float, ry: float, start: int, end: int) -> Stroke:
    """The points of an elliptical arc from ``start`` to ``end`` degrees, counter-clockwise
    when ``end`` is larger, clockwise when it is smaller."""
    sign = 1 if end >= start else -1
    angles = list(range(start, end + sign, sign * STEP_DEGREES))
    points: Stroke = []
    for first, second in itertools.pairwise(angles):
        a, b = direction(first), direction(second)
        for piece in range(PIECES_PER_STEP):
            ux, uy = _between(a, b, piece / PIECES_PER_STEP)
            points.append((cx + rx * ux, cy + ry * uy))
    ux, uy = direction(angles[-1])
    points.append((cx + rx * ux, cy + ry * uy))
    return points


def line(*points: Point) -> Stroke:
    return list(points)


# --- the font ------------------------------------------------------------------------------
# Units: the baseline is y = 0, the height of a small letter is 5, of a tall one 7.5, and a
# descender goes down to -2.5. Each glyph is its width and its strokes.

X = 5.0
TALL = 7.5
DOWN = -2.5
R = X / 2


def _bowl() -> Stroke:
    return arc(R, R, R, R, 0, 360)


GLYPHS: dict[str, tuple[float, list[Stroke]]] = {
    "a": (X, [_bowl(), line((X, 0.0), (X, X))]),
    "b": (X, [_bowl(), line((0.0, 0.0), (0.0, TALL))]),
    "c": (X, [arc(R, R, R, R, 45, 315)]),
    "d": (X, [_bowl(), line((X, 0.0), (X, TALL))]),
    "e": (X, [line((0.0, R), (X, R)), arc(R, R, R, R, 0, 315)]),
    "f": (
        3.5,
        [
            line((1.25, 0.0), (1.25, 5.75)),
            arc(3.0, 5.75, 1.75, 1.75, 180, 45),
            line((0.0, X), (3.25, X)),
        ],
    ),
    "h": (X, [line((0.0, 0.0), (0.0, TALL)), arc(R, R, R, R, 180, 0), line((X, R), (X, 0.0))]),
    "i": (0.0, [line((0.0, 0.0), (0.0, X)), line((0.0, 7.0), (0.0, 7.0))]),
    "k": (
        4.25,
        [
            line((0.0, 0.0), (0.0, TALL)),
            line((4.0, X), (0.0, 1.5)),
            line((1.45, 2.7), (4.25, 0.0)),
        ],
    ),
    "l": (0.0, [line((0.0, 0.0), (0.0, TALL))]),
    "m": (
        8.0,
        [
            line((0.0, 0.0), (0.0, X)),
            arc(2.0, 3.0, 2.0, 2.0, 180, 0),
            line((4.0, 3.0), (4.0, 0.0)),
            arc(6.0, 3.0, 2.0, 2.0, 180, 0),
            line((8.0, 3.0), (8.0, 0.0)),
        ],
    ),
    "n": (X, [line((0.0, 0.0), (0.0, X)), arc(R, R, R, R, 180, 0), line((X, R), (X, 0.0))]),
    "o": (X, [_bowl()]),
    "p": (X, [_bowl(), line((0.0, DOWN), (0.0, X))]),
    "r": (3.5, [line((0.0, 0.0), (0.0, X)), arc(R, R, R, R, 180, 60)]),
    "s": (
        3.9,
        [
            arc(1.95, 3.75, 1.95, 1.25, 30, 270),
            arc(1.95, 1.25, 1.95, 1.25, 90, -150),
        ],
    ),
    "T": (5.5, [line((0.0, TALL), (5.5, TALL)), line((2.75, 0.0), (2.75, TALL))]),
    " ": (1.0, []),
}
GAP = 1.75


def text_width(text: str) -> float:
    """The width of a line of text in font units, from the first stroke to the last."""
    widths = [GLYPHS[letter][0] for letter in text]
    return sum(widths) + GAP * (len(text) - 1)


def text_strokes(text: str, left: float, baseline: float, unit: float) -> list[Stroke]:
    """The strokes of a line of text in pixels, its first letter at ``left``."""
    strokes: list[Stroke] = []
    pen = 0.0
    for letter in text:
        width, glyph = GLYPHS[letter]
        for stroke in glyph:
            strokes.append([(left + (pen + x) * unit, baseline - y * unit) for x, y in stroke])
        pen += width + GAP
    return strokes


# --- drawing -------------------------------------------------------------------------------


class Layer:
    """How much of each pixel one colour covers, from 0 to 1."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.cover = array("d", bytes(8 * width * height))

    def _put(self, x: int, y: int, amount: float) -> None:
        index = y * self.width + x
        if amount > self.cover[index]:
            self.cover[index] = amount

    def strokes(self, strokes: Iterable[Stroke], thickness: float) -> None:
        """Draw strokes with round ends, ``thickness`` pixels wide, smoothed at the edges."""
        half = thickness / 2
        for stroke in strokes:
            pairs = list(itertools.pairwise(stroke)) or [(stroke[0], stroke[0])]
            for a, b in pairs:
                self._segment(a, b, half)

    def _segment(self, a: Point, b: Point, half: float) -> None:
        reach = half + 1.0
        x0 = max(0, math.floor(min(a[0], b[0]) - reach))
        x1 = min(self.width - 1, math.ceil(max(a[0], b[0]) + reach))
        y0 = max(0, math.floor(min(a[1], b[1]) - reach))
        y1 = min(self.height - 1, math.ceil(max(a[1], b[1]) + reach))
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        for y in range(y0, y1 + 1):
            py = y + 0.5
            for x in range(x0, x1 + 1):
                px = x + 0.5
                t = 0.0
                if length > 0.0:
                    t = ((px - a[0]) * dx + (py - a[1]) * dy) / length
                    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                ex, ey = px - (a[0] + t * dx), py - (a[1] + t * dy)
                amount = half + 0.5 - math.sqrt(ex * ex + ey * ey)
                if amount > 0.0:
                    self._put(x, y, 1.0 if amount > 1.0 else amount)

    def rounded_box(
        self, left: float, top: float, width: float, height: float, radius: float
    ) -> None:
        """Fill a box with rounded corners, smoothed at the edges."""
        cx, cy = left + width / 2, top + height / 2
        hx, hy = width / 2 - radius, height / 2 - radius
        for y in range(max(0, int(top) - 1), min(self.height, int(top + height) + 2)):
            for x in range(max(0, int(left) - 1), min(self.width, int(left + width) + 2)):
                qx = abs(x + 0.5 - cx) - hx
                qy = abs(y + 0.5 - cy) - hy
                ox, oy = max(qx, 0.0), max(qy, 0.0)
                inside = min(max(qx, qy), 0.0)
                distance = math.sqrt(ox * ox + oy * oy) + inside - radius
                amount = 0.5 - distance
                if amount > 0.0:
                    self._put(x, y, 1.0 if amount > 1.0 else amount)

    def rounded_ring(
        self, left: float, top: float, width: float, height: float, radius: float, thickness: float
    ) -> None:
        """Draw the outline of a box with rounded corners, a line ``thickness`` pixels wide
        centred on the box's edge, smoothed at its sides."""
        half = thickness / 2
        cx, cy = left + width / 2, top + height / 2
        hx, hy = width / 2 - radius, height / 2 - radius
        reach = int(half) + 2
        for y in range(max(0, int(top) - reach), min(self.height, int(top + height) + reach + 1)):
            for x in range(
                max(0, int(left) - reach), min(self.width, int(left + width) + reach + 1)
            ):
                qx = abs(x + 0.5 - cx) - hx
                qy = abs(y + 0.5 - cy) - hy
                ox, oy = max(qx, 0.0), max(qy, 0.0)
                inside = min(max(qx, qy), 0.0)
                distance = math.sqrt(ox * ox + oy * oy) + inside - radius
                amount = half + 0.5 - abs(distance)
                if amount > 0.0:
                    self._put(x, y, 1.0 if amount > 1.0 else amount)

    def fade(self, top: float, height: float, opacity: float, reach: float) -> None:
        """Scale the cover of every row for a line ``height`` pixels high from ``top``: by
        ``opacity`` down to the top, then in a straight line to nothing at ``reach`` of the
        height, and nothing below."""
        end = reach * height
        for y in range(self.height):
            down = y + 0.5 - top
            scale = opacity if down <= 0.0 else opacity * (1.0 - down / end) if down < end else 0.0
            start = y * self.width
            for index in range(start, start + self.width):
                if self.cover[index] > 0.0:
                    self.cover[index] *= scale

    def fill(self, contours: Sequence[Sequence[Point]]) -> None:
        """Fill closed outlines by the nonzero rule, smoothed at their edges: each row of pixels
        is crossed by ``SAMPLES`` lines, and each pixel is covered by the share of those lines'
        length inside the outlines that lies in it."""
        edges = []
        for contour in contours:
            for (xa, ya), (xb, yb) in itertools.pairwise([*contour, contour[0]]):
                if ya == yb:
                    continue
                winding = 1 if yb > ya else -1
                if ya > yb:
                    xa, ya, xb, yb = xb, yb, xa, ya
                edges.append((ya, yb, xa, (xb - xa) / (yb - ya), winding))
        if not edges:
            return
        edges.sort()
        xs = [x for contour in contours for x, _y in contour]
        x0, x1 = max(0, math.floor(min(xs))), min(self.width, math.ceil(max(xs)) + 1)
        y0 = max(0, math.floor(edges[0][0]))
        y1 = min(self.height, math.ceil(max(edge[1] for edge in edges)) + 1)
        start, active = 0, []
        for y in range(y0, y1):
            row = [0.0] * (x1 - x0)
            for sample in range(SAMPLES):
                line_y = y + (sample + 0.5) / SAMPLES
                while start < len(edges) and edges[start][0] <= line_y:
                    active.append(edges[start])
                    start += 1
                active = [edge for edge in active if edge[1] > line_y]
                crossings = sorted(
                    (edge[2] + (line_y - edge[0]) * edge[3], edge[4]) for edge in active
                )
                winding = 0
                for (xa, turn), (xb, _turn) in itertools.pairwise(crossings):
                    winding += turn
                    if winding:
                        _span(row, xa - x0, xb - x0)
            for column, value in enumerate(row):
                if value > 0.0:
                    self._put(x0 + column, y, min(1.0, value / SAMPLES))


def _span(row: list[float], left: float, right: float) -> None:
    """Add to a row of pixels the length of a line from ``left`` to ``right`` in each."""
    left, right = max(0.0, left), min(float(len(row)), right)
    if right <= left:
        return
    first, last = int(left), int(right)
    if first == last:
        row[first] += right - left
        return
    row[first] += first + 1 - left
    for column in range(first + 1, min(last, len(row))):
        row[column] += 1.0
    if last < len(row):
        row[last] += right - last


def box_widths(deviation: float, passes: int = BLUR_PASSES) -> list[int]:
    """The odd widths, in pixels, of the box passes whose blur together has the variance of a
    Gaussian of the given standard deviation, as near as odd widths come: some passes of one
    width and the rest two wider. Only a square root and plain arithmetic are used."""
    variance = 12.0 * deviation * deviation
    lower = int(math.sqrt(variance / passes + 1.0))
    if lower % 2 == 0:
        lower -= 1
    narrow = round(
        (variance - passes * lower * lower - 4 * passes * lower - 3 * passes) / (-4 * lower - 4)
    )
    narrow = max(0, min(passes, narrow))
    return [lower] * narrow + [lower + 2] * (passes - narrow)


def _box_pass(values: list[int], width: int) -> list[int]:
    """The sums of a box ``width`` values wide centred on each value, with nothing beyond
    the ends: whole numbers, so the same on every machine."""
    half = width // 2
    count = len(values)
    out = [0] * count
    total = sum(values[: min(half, count)])
    for index in range(count):
        if index + half < count:
            total += values[index + half]
        if index - half - 1 >= 0:
            total -= values[index - half - 1]
        out[index] = total
    return out


def blurred_shadow(source: Layer, box: tuple[int, int, int, int], deviation: float) -> Layer:
    """A layer of a shadow: the cover of ``source`` blurred by box passes along the rows and
    then the columns, at ``SHADOW_OPACITY``, inside a box of pixels (its first column, first
    row, and the column and row after its last) and nothing outside it.

    The cover is counted in ``COVER_STEPS`` whole steps and the passes add whole numbers; the
    sums are divided once, at the end."""
    x0, y0, x1, y1 = box
    widths = box_widths(deviation)
    grid = [
        [int(source.cover[y * source.width + x] * COVER_STEPS + 0.5) for x in range(x0, x1)]
        for y in range(y0, y1)
    ]
    for width in widths:
        grid = [_box_pass(row, width) for row in grid]
    columns = [list(column) for column in zip(*grid, strict=True)]
    for width in widths:
        columns = [_box_pass(column, width) for column in columns]
    divisor = COVER_STEPS * math.prod(widths) ** 2
    shadow = Layer(source.width, source.height)
    for column, values in enumerate(columns):
        for row, value in enumerate(values):
            if value:
                index = (y0 + row) * source.width + x0 + column
                shadow.cover[index] = SHADOW_OPACITY * value / divisor
    return shadow


def shade(ends: tuple[Colour, Colour], tops: Sequence[float], height: float) -> Paint:
    """The paint of tiles shaded from top to bottom: at a row, the tile whose top is the last
    one at or above the row's middle, its colour mixed from its two ends in a straight line
    from its top to its bottom, rounded to the nearest whole value."""
    (r0, g0, b0), (r1, g1, b1) = ends

    def paint(x: int, y: int) -> Colour:
        middle = y + 0.5
        top = max([tops[0], *(edge for edge in tops if edge <= middle)])
        t = (middle - top) / height
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        return (
            int(r0 + (r1 - r0) * t + 0.5),
            int(g0 + (g1 - g0) * t + 0.5),
            int(b0 + (b1 - b0) * t + 0.5),
        )

    return paint


def gradient(x: int, width: int = WIDTH) -> Colour:
    """The colour of the gradient at a column: between the two stops around the column, each
    channel goes from the first stop's to the second's in a straight line, rounded to the
    nearest whole value. Only whole numbers are used, so it is the same on every machine."""
    last = width - 1
    # The pair of stops whose columns, as hundredths of the last column, hold the column: the
    # last pair when the column is past the end of every other.
    pairs = list(itertools.pairwise(GRADIENT))
    (start, at), (end, until) = next(
        (pair for pair in pairs if x * 100 <= pair[1][1] * last), pairs[-1]
    )
    left, right = at * last, until * last
    span = right - left
    step = x * 100 - left
    return (
        (start[0] * (span - step) + end[0] * step + span // 2) // span,
        (start[1] * (span - step) + end[1] * step + span // 2) // span,
        (start[2] * (span - step) + end[2] * step + span // 2) // span,
    )


# --- the maker's logo ----------------------------------------------------------------------

# A gradient of the logo file: its line, from (x1, y1) to (x2, y2) in shares of the bounds of the
# outline it fills, and its stops, each its place along that line and its colour.
LogoGradient = tuple[tuple[float, float, float, float], tuple[tuple[float, Colour], ...]]


def _hex(text: str) -> Colour:
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


@functools.cache
def logo() -> tuple[tuple[float, float, float, float], tuple[tuple[str, LogoGradient], ...]]:
    """The logo file, read once: its view box, then each of its outlines (the commands of an
    SVG path, every point given whole) with the gradient that fills it."""
    text = LOGO.read_text(encoding="utf-8")
    view = re.search(r'viewBox="([^"]+)"', text)
    gradients: dict[str, LogoGradient] = {}
    for ident, attributes, body in re.findall(
        r'<linearGradient id="([^"]+)"([^>]*)>(.*?)</linearGradient>', text
    ):
        line = tuple(
            float(re.findall(rf'\b{name}="([^"]+)"', attributes)[0])
            for name in ("x1", "y1", "x2", "y2")
        )
        stops = tuple(
            (float(at), _hex(colour))
            for at, colour in re.findall(
                r'<stop offset="([^"]+)" stop-color="(#[0-9a-f]{6})"/>', body
            )
        )
        gradients[ident] = (line[0], line[1], line[2], line[3]), stops
    paths = re.findall(r'<path fill="url\(#([^)]+)\)" d="([^"]+)"/>', text)
    if view is None or not paths or any(ident not in gradients for ident, _ in paths):
        raise SystemExit(f"{LOGO} must have a viewBox and paths filled with its own gradients")
    left, top, width, height = (float(n) for n in view.group(1).split())
    return (left, top, width, height), tuple((d, gradients[ident]) for ident, d in paths)


def _bezier(points: Sequence[Point], t: float) -> Point:
    """The point at ``t`` of a Bézier curve, by de Casteljau's construction."""
    row = list(points)
    while len(row) > 1:
        row = [
            (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for a, b in itertools.pairwise(row)
        ]
    return row[0]


def outline_contours(d: str, place: Callable[[float, float], Point]) -> list[list[Point]]:
    """The closed contours of an SVG path of M, L, Q, C and Z commands with absolute points,
    each point put in the image by ``place``, its curves drawn as ``CURVE_PIECES`` straight
    pieces each."""
    contours: list[list[Point]] = []
    current: list[Point] = []
    for op, numbers in re.findall(r"([MLQCZ])([^MLQCZ]*)", d):
        values = [float(n) for n in numbers.split()]
        points = [place(x, y) for x, y in zip(values[0::2], values[1::2], strict=True)]
        if op == "M":
            if len(current) > 2:
                contours.append(current)
            current = [points[0]]
        elif op == "L":
            current += points
        elif op in ("Q", "C"):
            ends = [current[-1], *points]
            current += [_bezier(ends, piece / CURVE_PIECES) for piece in range(1, CURVE_PIECES + 1)]
        else:
            if len(current) > 2:
                contours.append(current)
            current = []
    if len(current) > 2:
        contours.append(current)
    return contours


def along(gradient: LogoGradient, box: tuple[float, float, float, float]) -> Paint:
    """The paint of a logo gradient over the bounds (left, top, width, height) of the outline it
    fills, as SVG lays a gradient in the units of those bounds: at a pixel, how far along the line
    its middle lies, then the colour mixed from the two stops around that place, rounded to
    the nearest whole value."""
    (x1, y1, x2, y2), stops = gradient
    left, top, width, height = box
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy

    def paint(x: int, y: int) -> Colour:
        u, v = (x + 0.5 - left) / width, (y + 0.5 - top) / height
        t = min(max(((u - x1) * dx + (v - y1) * dy) / length, stops[0][0]), stops[-1][0])
        (at, first), (until, second) = next(
            (pair for pair in itertools.pairwise(stops) if t <= pair[1][0]),
            (stops[-2], stops[-1]),
        )
        share = (t - at) / (until - at) if until > at else 0.0
        return (
            int(first[0] + (second[0] - first[0]) * share + 0.5),
            int(first[1] + (second[1] - first[1]) * share + 0.5),
            int(first[2] + (second[2] - first[2]) * share + 0.5),
        )

    return paint


def logo_layers() -> list[tuple[Layer, Paint]]:
    """The maker's logo in the top right corner, ``LOGO_WIDTH`` pixels wide: a layer for each
    outline of its file, in that outline's gradient."""
    (view_left, view_top, view_width, _), outlines = logo()
    scale = LOGO_WIDTH / view_width
    left, top = WIDTH - LOGO_RIGHT - LOGO_WIDTH, LOGO_TOP

    def place(x: float, y: float) -> Point:
        return left + (x - view_left) * scale, top + (y - view_top) * scale

    layers: list[tuple[Layer, Paint]] = []
    for d, gradient in outlines:
        contours = outline_contours(d, place)
        xs = [x for contour in contours for x, _y in contour]
        ys = [y for contour in contours for _x, y in contour]
        layer = Layer(WIDTH, HEIGHT)
        layer.fill(contours)
        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        layers.append((layer, along(gradient, box)))
    return layers


def compose(
    width: int, height: int, layers: Sequence[tuple[Layer, Colour | Paint | None]]
) -> bytes:
    """The rows of the image, each led by the byte of PNG's filter 0, layers drawn in order.
    A layer whose colour is ``None`` is drawn in the colour of the gradient at each column,
    and a layer whose colour is a paint in the colour the paint gives at each pixel."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            r, g, b = BACKGROUND
            index = y * width + x
            for layer, colour in layers:
                amount = layer.cover[index]
                if amount > 0.0:
                    if colour is None:
                        lr, lg, lb = gradient(x, width)
                    elif callable(colour):
                        lr, lg, lb = colour(x, y)
                    else:
                        lr, lg, lb = colour
                    r = int(r + (lr - r) * amount + 0.5)
                    g = int(g + (lg - g) * amount + 0.5)
                    b = int(b + (lb - b) * amount + 0.5)
            rows += bytes((r, g, b))
    return bytes(rows)


def render() -> bytes:
    """The image as rows of RGB pixels, each row led by its filter byte."""
    name_unit, line_unit = 13.0, 4.6
    icon = 168.0
    gap = 44.0
    name_width = text_width(NAME) * name_unit
    row_width = icon + gap + name_width
    left = (WIDTH - row_width) / 2
    icon_top = 150.0
    name_baseline = icon_top + icon / 2 + X * name_unit / 2
    line_width = text_width(LINE) * line_unit
    line_baseline = 470.0

    band = Layer(WIDTH, HEIGHT)
    band.rounded_box(0, 0, WIDTH, BAND_HEIGHT, 0)
    # The mark on its 64-unit grid: four tiles of 26 units with a radius of 7, 4 units in from
    # the edges and 4 apart; violet at the top left and the bottom right, azure at the others.
    scale = icon / MARK_UNITS
    tile, radius = TILE * scale, TILE_RADIUS * scale
    violet = Layer(WIDTH, HEIGHT)
    azure = Layer(WIDTH, HEIGHT)
    lowered = Layer(WIDTH, HEIGHT)
    tops = [icon_top + (4 + 30 * row) * scale for row in (0, 1)]
    # The highlights of each row of tiles, faded down from the top of their own line.
    highlights = [Layer(WIDTH, HEIGHT) for _ in tops]
    inset = HIGHLIGHT_WIDTH / 2 * scale
    for column, row in ((0, 0), (1, 0), (0, 1), (1, 1)):
        tiles = violet if column == row else azure
        x, y = left + (4 + 30 * column) * scale, tops[row]
        tiles.rounded_box(x, y, tile, tile, radius)
        lowered.rounded_box(x, y + SHADOW_OFFSET * scale, tile, tile, radius)
        highlights[row].rounded_ring(
            x + inset,
            y + inset,
            tile - 2 * inset,
            tile - 2 * inset,
            radius - inset,
            HIGHLIGHT_WIDTH * scale,
        )
    for top, highlight in zip(tops, highlights, strict=True):
        highlight.fade(top + inset, tile - 2 * inset, HIGHLIGHT_OPACITY, HIGHLIGHT_REACH)
    # The shadow's region is the mark's square: the pixels whose middles lie inside it.
    region = (
        math.ceil(left - 0.5),
        math.ceil(icon_top - 0.5),
        math.ceil(left + icon - 0.5),
        math.ceil(icon_top + icon - 0.5),
    )
    shadow = blurred_shadow(lowered, region, SHADOW_DEVIATION * scale)
    name = Layer(WIDTH, HEIGHT)
    name.strokes(text_strokes(NAME, left + icon + gap, name_baseline, name_unit), 1.15 * name_unit)
    tagline = Layer(WIDTH, HEIGHT)
    tagline.strokes(
        text_strokes(LINE, (WIDTH - line_width) / 2, line_baseline, line_unit), 0.85 * line_unit
    )
    layers: list[tuple[Layer, Colour | Paint | None]] = [
        (band, None),
        (shadow, SHADOW),
        (violet, shade(VIOLET, tops, tile)),
        (azure, shade(AZURE, tops, tile)),
        *((highlight, HIGHLIGHT) for highlight in highlights),
        (name, NAME_COLOUR),
        (tagline, LINE_COLOUR),
        *logo_layers(),
    ]
    return compose(WIDTH, HEIGHT, layers)


# --- PNG -----------------------------------------------------------------------------------

SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Eight bits per sample, colour type 2 (RGB), standard compression, filter and no interlace.
HEADER_LAYOUT = ">IIBBBBB"
HEADER = struct.pack(HEADER_LAYOUT, WIDTH, HEIGHT, 8, 2, 0, 0, 0)
HEADER_FIELDS = (
    "width",
    "height",
    "bit depth",
    "colour type",
    "compression method",
    "filter method",
    "interlace method",
)
# A row of the image: its filter byte, then three samples of eight bits for each pixel.
ROW_LENGTH = 1 + WIDTH * 3
# The four bytes of a chunk's length, the four of its type, and the four of its CRC.
CHUNK_FRAME = 12
PLAIN_CHUNKS = (b"IHDR", b"IDAT", b"IEND")
# What the check prints after a refusal's cause: how to write the file it wants.
REMEDY = "run python3 tools/share_image.py"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(rows: bytes) -> bytes:
    """A PNG file of the rows: a header, the compressed rows and an end, nothing else."""
    return (
        SIGNATURE
        + _chunk(b"IHDR", HEADER)
        + _chunk(b"IDAT", zlib.compress(rows, 9))
        + _chunk(b"IEND", b"")
    )


def _chunk_at(data: bytes, at: int) -> tuple[bytes, bytes, bool, int] | None:
    """The chunk that starts at an offset of a PNG file: its type, its data, whether its CRC
    is the CRC of its type and data, and the offset after it. ``None`` when the file ends
    before the chunk does."""
    if at + CHUNK_FRAME > len(data):
        return None
    (length,) = struct.unpack(">I", data[at : at + 4])
    end = at + CHUNK_FRAME + length
    if end > len(data):
        return None
    kind, body = data[at + 4 : at + 8], data[at + 8 : end - 4]
    (crc,) = struct.unpack(">I", data[end - 4 : end])
    return kind, body, crc == zlib.crc32(kind + body), end


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """The chunks of a PNG file in order, each its type and its data. ``ValueError`` when
    the file does not start with the PNG signature, when a chunk is cut short and when a
    chunk's CRC is not the CRC of its type and data."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG file")
    found: list[tuple[bytes, bytes]] = []
    at = len(SIGNATURE)
    while at < len(data):
        read = _chunk_at(data, at)
        if read is None:
            raise ValueError("a chunk is cut short")
        kind, body, matches, at = read
        if not matches:
            raise ValueError(f"the CRC of a {kind!r} chunk does not match")
        found.append((kind, body))
    return found


def pixels(data: bytes) -> bytes:
    """The rows a PNG file holds: its IDAT data joined and decompressed, each row led by
    its filter byte as the file has it. The rows of one image saved with another row filter
    are other bytes. ``ValueError`` when the compressed stream does not end where the IDAT
    data ends."""
    stream = zlib.decompressobj()
    rows = stream.decompress(b"".join(body for kind, body in chunks(data) if kind == b"IDAT"))
    if not stream.eof or stream.unused_data:
        raise ValueError("the compressed rows do not end where the IDAT data ends")
    return rows


def size(data: bytes) -> tuple[int, int]:
    """The width and height a PNG file declares."""
    header = dict(chunks(data))[b"IHDR"]
    width, height = struct.unpack(">II", header[:8])
    return width, height


def kind_name(kind: bytes) -> str:
    """A chunk's type as a message shows it: its four letters, or its bytes in hexadecimal
    when they are not four ASCII letters, so no byte of the file reaches a terminal as is."""
    if len(kind) == 4 and kind.isascii() and kind.isalpha():
        return kind.decode("ascii")
    return f"0x{kind.hex()}"


def header_change(header: bytes) -> str:
    """How a header differs from the one this script writes, field by field."""
    if len(header) != len(HEADER):
        return f"of {len(header)} bytes, not {len(HEADER)}"
    found = struct.unpack(HEADER_LAYOUT, header)
    wanted = struct.unpack(HEADER_LAYOUT, HEADER)
    return "; ".join(
        f"{name} {value}, not {want}"
        for name, value, want in zip(HEADER_FIELDS, found, wanted, strict=True)
        if value != want
    )


def _layout_refusal(data: bytes) -> str | list[tuple[bytes, bytes]]:
    """The chunks of a file up to its IEND chunk, or why they are not the ones this script
    writes. Reading stops at IEND: what follows it is data after the end, whatever it is."""
    if not data.startswith(SIGNATURE):
        return "is not a PNG file"
    found: list[tuple[bytes, bytes]] = []
    at = len(SIGNATURE)
    while not found or found[-1][0] != b"IEND":
        read = _chunk_at(data, at)
        if read is None:
            return "is cut short (it ends before its IEND chunk)"
        kind, body, matches, at = read
        if not matches:
            return f"has a bad checksum (in its {kind_name(kind)} chunk)"
        found.append((kind, body))
    if at < len(data):
        return "has data after the end (after its IEND chunk)"
    kinds = [kind for kind, _ in found]
    extra = [kind for kind in kinds if kind not in PLAIN_CHUNKS]
    if extra:
        return f"has an extra chunk ({kind_name(extra[0])})"
    if kinds[0] != b"IHDR":
        return f"has another header (its first chunk is {kind_name(kinds[0])}, not IHDR)"
    if kinds.count(b"IHDR") > 1:
        return "has an extra chunk (a second IHDR)"
    if b"IDAT" not in kinds:
        return "has no rows (no IDAT chunk)"
    if found[-1][1]:
        return "has data in its IEND chunk"
    if found[0][1] != HEADER:
        return f"has another header ({header_change(found[0][1])})"
    return found


def _rows_refusal(stream: bytes) -> str | None:
    """Why the joined IDAT data of a file with this script's header are not the rows it
    writes, or ``None`` when they are."""
    rows_stream = zlib.decompressobj()
    try:
        rows = rows_stream.decompress(stream)
    except zlib.error:
        return "has compressed rows that do not decompress"
    if not rows_stream.eof:
        return "has compressed rows cut short (their zlib stream does not end)"
    if rows_stream.unused_data:
        return "has trailing compressed data (bytes after the end of the zlib stream of its rows)"
    if len(rows) != HEIGHT * ROW_LENGTH:
        return "has rows of another length than its header gives"
    if any(rows[::ROW_LENGTH]):
        return "has another row filter (this script writes filter 0, None, on every row)"
    if rows != render():
        return "is out of date (its pixels are not the ones this script draws)"
    return None


def refusal(path: Path) -> str | None:
    """Why a file is not the PNG this script writes, as the check's message says it after the
    file's name; ``None`` when it is. ``is_current`` gives the rule.

    The file is read from its start and the first cause found is named: a missing file, not
    a PNG file, a file cut short, a bad checksum, data after the end, an extra chunk, another
    header, no rows, data in IEND, compressed rows that do not decompress or are cut short,
    trailing compressed data, rows of another length, another row filter; and last, pixels
    that are not the ones this script draws, the one cause that makes the file out of date.
    """
    if not path.is_file():
        return "is missing"
    layout = _layout_refusal(path.read_bytes())
    if isinstance(layout, str):
        return layout
    return _rows_refusal(b"".join(body for kind, body in layout if kind == b"IDAT"))


def is_current(path: Path) -> bool:
    """Whether a file is the PNG this script writes, up to how its rows are compressed.

    It must hold exactly the chunks IHDR, one or more IDAT and IEND, in that order, each
    with the CRC of its type and data, and nothing after IEND. The IHDR must be this
    script's header: its width and height, eight bits per sample, RGB, no interlace. The
    IEND must be empty. The IDAT data, joined, must be one zlib stream with nothing after
    its end, and it must decompress to the rows this script draws, each led by the filter
    byte 0 (None).

    So the same rows compressed by another zlib compressor or at another level, or split
    across several IDAT chunks, are accepted. The same pixels saved with another row filter
    are refused, as are any other chunk (text, Exif data, a time or a colour profile),
    another header, an IEND that holds data, a wrong CRC, a chunk cut short, and bytes after
    IEND or after the end of the compressed rows.
    """
    return refusal(path) is None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="share_image.py", description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the file differs")
    args = parser.parse_args(argv)
    path = REPO / OUTPUT
    if args.check:
        cause = refusal(path)
        if cause:
            print(f"{OUTPUT} {cause}: {REMEDY}", file=sys.stderr)
            return 1
        return 0
    path.write_bytes(png(render()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
