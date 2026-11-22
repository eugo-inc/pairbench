# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Draw the share image of the documentation site: ``site/public/share.png``.

A page shared on a social site or in a chat shows this image beside its title. It holds
a band of the site's accent gradient along its top, the mark of the site (the four tiles of
``docs/readme/mark-dark.svg``, in the order of two alternating rounds), the name pairbench
and one line on what it does, on the dark ground of the site.

The drawing uses only the standard library and arithmetic that gives the same result on
every machine: the letters are strokes of a small built-in font, made of straight pieces
and of arcs whose points come from square roots, never from the system's fonts or its
trigonometry. The build copies the committed file as it is, once ``is_current`` finds it
is the file this script writes, up to how its rows are compressed; ``is_current`` says
exactly what it accepts and what it refuses, and ``refusal`` names why a file is refused.

Usage::

    python3 tools/share_image.py          # write site/public/share.png
    python3 tools/share_image.py --check  # exit 1, naming the cause, when the file differs
"""

from __future__ import annotations

import argparse
import itertools
import math
import struct
import sys
import zlib
from array import array
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = "site/public/share.png"
WIDTH = 1200
HEIGHT = 630
NAME = "pairbench"
LINE = "Tells real benchmark differences from noise"
ALT = (
    f"The name {NAME} in white beside its mark of four rounded tiles in violet and teal, above "
    f"the line “{LINE}”, on a dark background under a violet-to-teal band."
)

Point = tuple[float, float]
Stroke = list[Point]
Colour = tuple[int, int, int]

# The dark palette of the site: its ground, its text, a softer text, its two accents, and the
# two ends of its gradient.
BACKGROUND: Colour = (0x08, 0x0D, 0x17)
NAME_COLOUR: Colour = (0xF2, 0xF3, 0xF8)
LINE_COLOUR: Colour = (0xA9, 0xB0, 0xC3)
VIOLET: Colour = (0xA1, 0x42, 0xFF)
TEAL: Colour = (0x22, 0xC7, 0xE0)
GRADIENT: tuple[Colour, Colour] = ((0xA0, 0x3F, 0xFF), (0x00, 0x82, 0x94))
BAND_HEIGHT = 10

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


def gradient(x: int, width: int = WIDTH) -> Colour:
    """The colour of the gradient at a column: each channel goes from the first end to the
    second in a straight line, rounded to the nearest whole value, the same on every machine."""
    (r0, g0, b0), (r1, g1, b1) = GRADIENT
    last = width - 1
    return (
        (r0 * (last - x) + r1 * x + last // 2) // last,
        (g0 * (last - x) + g1 * x + last // 2) // last,
        (b0 * (last - x) + b1 * x + last // 2) // last,
    )


def compose(width: int, height: int, layers: Sequence[tuple[Layer, Colour | None]]) -> bytes:
    """The rows of the image, each led by the byte of PNG's filter 0, layers drawn in order.
    A layer whose colour is ``None`` is drawn in the colour of the gradient at each column."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            r, g, b = BACKGROUND
            index = y * width + x
            for layer, colour in layers:
                amount = layer.cover[index]
                if amount > 0.0:
                    lr, lg, lb = gradient(x, width) if colour is None else colour
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
    # the edges and 4 apart; violet at the top left and the bottom right, teal at the others.
    scale = icon / 64
    violet = Layer(WIDTH, HEIGHT)
    teal = Layer(WIDTH, HEIGHT)
    for column, row in ((0, 0), (1, 0), (0, 1), (1, 1)):
        tiles = violet if column == row else teal
        x, y = left + (4 + 30 * column) * scale, icon_top + (4 + 30 * row) * scale
        tiles.rounded_box(x, y, 26 * scale, 26 * scale, 7 * scale)
    name = Layer(WIDTH, HEIGHT)
    name.strokes(text_strokes(NAME, left + icon + gap, name_baseline, name_unit), 1.15 * name_unit)
    tagline = Layer(WIDTH, HEIGHT)
    tagline.strokes(
        text_strokes(LINE, (WIDTH - line_width) / 2, line_baseline, line_unit), 0.85 * line_unit
    )
    layers: list[tuple[Layer, Colour | None]] = [
        (band, None),
        (violet, VIOLET),
        (teal, TEAL),
        (name, NAME_COLOUR),
        (tagline, LINE_COLOUR),
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
