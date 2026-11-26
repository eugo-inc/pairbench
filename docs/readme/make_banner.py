# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Draw the README's banner, ``banner-light.svg`` and ``banner-dark.svg``, from the mark.

    python3 docs/readme/make_banner.py

The banner holds the wordmark, the mark (``mark-light.svg`` or ``mark-dark.svg``, nested as it
is) followed by the name, then one line on what the tool does and its five verdicts. Every
letter is a path: a page shows an SVG image without loading a web font, so the text is drawn
in Red Hat Display as outlines. The letters are shaped with HarfBuzz from the variable Red Hat
Display font the documentation site installs, at the weight each text asks for.

Needs ``pip install uharfbuzz fonttools brotli`` and the site's packages (``npm ci`` in
``site/``). After the mark files change, run this script again.
"""

from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONT = (
    REPO
    / "site/node_modules/@fontsource-variable/red-hat-display/files"
    / "red-hat-display-latin-wght-normal.woff2"
)
WIDTH = 1200
HEIGHT = 300
NAME = "pairbench"
LINE = "Tells real benchmark differences from noise"
VERDICTS = ("FASTER", "SLOWER", "TIE", "UNRESOLVED", "NO VERDICT")
TITLE = f"{NAME}: tells real benchmark differences from noise. Verdicts: {', '.join(VERDICTS)}"
# The weights of the name (as the site's header sets it) and of the verdicts' letters.
NAME_WEIGHT = 800
PILL_WEIGHT = 700


@dataclass(frozen=True)
class Theme:
    ground: str
    border: str
    ink: str
    muted: str
    # The stops of the gradient along the top, each a colour and its offset.
    rule: tuple[tuple[str, str], ...]
    # Each verdict's fill, border and text.
    verdicts: dict[str, tuple[str, str, str]]


THEMES = {
    "light": Theme(
        ground="#ffffff",
        border="#e6e4f0",
        ink="#160f3d",
        muted="#55566b",
        rule=(("#8e45ff", "0"), ("#6a5cff", ".45"), ("#2aa6ff", "1")),
        verdicts={
            "FASTER": ("#e5f3ff", "#1970bd", "#145c9c"),
            "SLOWER": ("#fdebef", "#c0264a", "#9d1c3b"),
            "TIE": ("#eeebff", "#6a5cff", "#4b3ccc"),
            "UNRESOLVED": ("#fdf4dc", "#a16207", "#854d0e"),
            "NO VERDICT": ("#f6f5fb", "#6f7089", "#55566b"),
        },
    ),
    "dark": Theme(
        ground="#160f3d",
        border="#352a7f",
        ink="#ffffff",
        muted="#d6d3ee",
        rule=(("#8e45ff", "0"), ("#6a5cff", ".45"), ("#2aa6ff", "1")),
        verdicts={
            "FASTER": ("#0d2a55", "#2aa6ff", "#7cc8ff"),
            "SLOWER": ("#33121c", "#ff6b81", "#ff8da1"),
            "TIE": ("#2d1b6e", "#a24bff", "#d9b8ff"),
            "UNRESOLVED": ("#33290d", "#f5c451", "#ffd479"),
            "NO VERDICT": ("#291f66", "#a9a4d6", "#d6d3ee"),
        },
    ),
}


class _PathPen:
    """Collects the outline HarfBuzz draws for one glyph as SVG path commands, placed at an
    origin and scaled from font units to pixels, with the y axis turned downwards."""

    def __init__(self, x: float, y: float, scale: float) -> None:
        self.x, self.y, self.scale = x, y, scale
        self.parts: list[str] = []

    def _point(self, point: tuple[float, float]) -> str:
        return f"{self.x + point[0] * self.scale:.2f} {self.y - point[1] * self.scale:.2f}"

    # The method names and arguments of a fontTools pen, which HarfBuzz calls.
    def moveTo(self, point: tuple[float, float]) -> None:
        self.parts.append(f"M{self._point(point)}")

    def lineTo(self, point: tuple[float, float]) -> None:
        self.parts.append(f"L{self._point(point)}")

    def qCurveTo(self, *points: tuple[float, float]) -> None:
        self.parts.append("Q" + " ".join(self._point(point) for point in points))

    def curveTo(self, *points: tuple[float, float]) -> None:
        self.parts.append("C" + " ".join(self._point(point) for point in points))

    def closePath(self) -> None:
        self.parts.append("Z")


class Letters:
    """Red Hat Display, shaped and drawn as outlines."""

    def __init__(self, font_file: Path) -> None:
        import uharfbuzz as hb
        from fontTools.ttLib import woff2

        if not font_file.is_file():
            raise SystemExit(f"{font_file} is missing: run npm ci in site/")
        plain = io.BytesIO()
        woff2.decompress(io.BytesIO(font_file.read_bytes()), plain)
        self._hb = hb
        self._face = hb.Face(hb.Blob(plain.getvalue()))
        self.units = self._face.upem

    def _font(self, weight: int) -> object:
        font = self._hb.Font(self._face)
        font.set_variations({"wght": weight})
        return font

    def width(self, text: str, size: float, weight: int, spacing: float = 0.0) -> float:
        """The advance of a text, in pixels, with ``spacing`` pixels added after each letter
        but the last."""
        font = self._font(weight)
        buffer = self._shaped(font, text)
        advance = sum(p.x_advance for p in buffer.glyph_positions) * size / self.units
        return advance + spacing * (len(buffer.glyph_positions) - 1)

    def ink(self, text: str, size: float, weight: int) -> tuple[float, float]:
        """How far the letters of a text reach above the baseline and below it, in pixels:
        the highest point as a positive number, the lowest as a negative one."""
        font = self._font(weight)
        buffer = self._shaped(font, text)
        heights = []
        for info in buffer.glyph_infos:
            extents = font.get_glyph_extents(info.codepoint)  # type: ignore[attr-defined]
            heights += [extents.y_bearing, extents.y_bearing + extents.height]
        return max(heights) * size / self.units, min(heights) * size / self.units

    def _shaped(self, font: object, text: str) -> object:
        buffer = self._hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        self._hb.shape(font, buffer, {"kern": True, "liga": True})
        return buffer

    def path(
        self, text: str, x: float, baseline: float, size: float, weight: int, spacing: float = 0.0
    ) -> str:
        """The path data of a text set from ``x`` on ``baseline``, with ``spacing`` pixels
        added after each letter."""
        font = self._font(weight)
        buffer = self._shaped(font, text)
        scale = size / self.units
        parts: list[str] = []
        pen_x = x
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            pen = _PathPen(
                pen_x + position.x_offset * scale, baseline - position.y_offset * scale, scale
            )
            font.draw_glyph_with_pen(info.codepoint, pen)  # type: ignore[attr-defined]
            parts.extend(pen.parts)
            pen_x += position.x_advance * scale + spacing
        return "".join(parts)


def nested_mark(theme_name: str, x: float, y: float, size: float) -> str:
    """The mark file of a theme, nested at a place and size, its ids made the banner's own."""
    text = (HERE / f"mark-{theme_name}.svg").read_text(encoding="utf-8")
    view = re.search(r'viewBox="([^"]+)"', text)
    inner = text.split(">", 1)[1].rsplit("</svg>", 1)[0].strip()
    inner = re.sub(r'id="([^"]+)"', r'id="banner-\1"', inner)
    inner = re.sub(r"url\(#([^)]+)\)", r"url(#banner-\1)", inner)
    box = view.group(1) if view else "0 0 64 64"
    place = f'x="{x:.2f}" y="{y:.2f}" width="{size:.2f}" height="{size:.2f}"'
    return f'<svg {place} viewBox="{box}">{inner}</svg>'


def banner(letters: Letters, theme_name: str) -> str:
    """The banner of a theme: the wordmark, the line and the verdicts, each centred."""
    theme = THEMES[theme_name]
    # The wordmark: the mark, 1.1 times the size of the name high, a gap of 0.3 of that size,
    # then the name in extra bold with a letter spacing of -0.03 of that size, both centred on
    # the middle of the name's letters.
    name_size, line_size, pill_size = 88.0, 30.0, 16.0
    mark = 1.1 * name_size
    gap = 0.3 * name_size
    spacing = -0.03 * name_size
    name_width = letters.width(NAME, name_size, NAME_WEIGHT, spacing)
    left = (WIDTH - (mark + gap + name_width)) / 2
    baseline = 128.0
    top, bottom = letters.ink(NAME, name_size, NAME_WEIGHT)
    middle = baseline - (top + bottom) / 2
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title">',
        f'<title id="title">{TITLE}</title>',
        '<defs><linearGradient id="banner-rule" x1="0" y1="0" x2="1" y2="0">'
        + "".join(f'<stop offset="{at}" stop-color="{colour}"/>' for colour, at in theme.rule)
        + "</linearGradient>"
        '<clipPath id="banner-frame"><rect x="1" y="1" width="1198" height="298" rx="18"/>'
        "</clipPath></defs>",
        f'<rect x="1" y="1" width="1198" height="298" rx="18" fill="{theme.ground}" '
        f'stroke="{theme.border}" stroke-width="2"/>',
        '<rect x="0" y="0" width="1200" height="6" fill="url(#banner-rule)" '
        'clip-path="url(#banner-frame)"/>',
        nested_mark(theme_name, left, middle - mark / 2, mark),
        f'<path fill="{theme.ink}" '
        f'd="{letters.path(NAME, left + mark + gap, baseline, name_size, NAME_WEIGHT, spacing)}"/>',
    ]
    line_width = letters.width(LINE, line_size, 400)
    out.append(
        f'<path fill="{theme.muted}" '
        f'd="{letters.path(LINE, (WIDTH - line_width) / 2, 196, line_size, 400)}"/>'
    )
    pills = [letters.width(verdict, pill_size, PILL_WEIGHT) + 32 for verdict in VERDICTS]
    x = (WIDTH - sum(pills) - 12 * (len(pills) - 1)) / 2
    for verdict, pill in zip(VERDICTS, pills, strict=True):
        fill, stroke, ink = theme.verdicts[verdict]
        out.append(
            f'<rect x="{x:.2f}" y="226" width="{pill:.2f}" height="36" rx="18" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>'
        )
        out.append(
            f'<path fill="{ink}" d="{letters.path(verdict, x + 16, 250, pill_size, PILL_WEIGHT)}"/>'
        )
        x += pill + 12
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    letters = Letters(FONT)
    for theme_name in THEMES:
        (HERE / f"banner-{theme_name}.svg").write_text(banner(letters, theme_name), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
