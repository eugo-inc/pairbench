# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Flame graphs, written with the standard library: one self-contained SVG file per graph.

The writer is made for this package from folded stacks. A frame is a box
whose width is its share of samples: the root, ``all``, spans the whole
width at the bottom, and every frame sits on the frame that called it.
Children are laid out in the order of their names, so two writes from the
same stacks are equal byte for byte. The file holds no date and no random id.

The graph is interactive where the viewer runs its script: a click on a
frame zooms to it, the control ``Reset zoom`` leads back to the full view,
typing marks the frames whose names hold the typed text (Backspace removes a
letter, Escape clears it) and says what share of samples they cover, and
pointing at a frame shows its full name with its share. A viewer that strips
scripts from pictures shows the graph without the interaction. The script
finds its own graph and reads names from the graph's text; no name is ever
written into the script.

Nothing in the file points outside it: no address, no outside script, font
or style sheet. Every name is escaped before it is written, and so are the
characters that would let a name read as a reference (``=``, ``(``, ``)``
and ``@``); a character XML cannot hold becomes U+FFFD.

The difference graph shows the subject's stacks: the subject sets the
widths. Each frame is coloured by the change in its share of samples, the
subject's share minus the baseline's share of the same stack prefix: red
where the subject has the larger share, blue where the baseline has it,
paler for a smaller change. The text shown for a frame gives both shares.
Stacks only the baseline has cannot be drawn there; they are listed under
the graph with their shares.
"""

from __future__ import annotations

import html
import re
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Final

from pairbench.diagnose.folded import Stack, stack_text

WIDTH: Final = 1200
PAD: Final = 10
ROW: Final = 16
TOP: Final = 66
CHAR_WIDTH: Final = 7.2
INNER: Final = WIDTH - 2 * PAD
# The most stacks only the baseline has that the difference graph lists by name.
LIST_MAX: Final = 100
HIT: Final = "#e040fb"
ROOT_FILL: Final = "#c8c8c8"
HOLDS_NAMES: Final = "This graph holds names from the user's code."
INSTRUMENT_WORDS: Final[Mapping[str, str]] = {
    "stacks": (
        "Stacks sampled by perf record, read back with perf script: native and Python frames."
    ),
    "pystacks": (
        "Stacks sampled by the pystacks sampler of pairbench: Python frames only; time in "
        "native code shows in the Python function that called it."
    ),
}

_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_REFERENCE_CHARACTERS = {"=": "&#61;", "(": "&#40;", ")": "&#41;", "@": "&#64;"}


def escape(text: str) -> str:
    """Escape a name for the text or an attribute of the file.

    The markup characters become entities, and so do ``=``, ``(``, ``)``
    and ``@``, so that no name can read as an attribute, an address or an
    import. A character XML cannot hold becomes U+FFFD.
    """
    escaped = html.escape(_NOT_XML.sub("�", text), quote=True)
    return "".join(_REFERENCE_CHARACTERS.get(char, char) for char in escaped)


def fit(name: str, width: float) -> str:
    """Return the text a frame of this width shows: the name, shortened with ``..`` when narrow."""
    room = int((width - 6) // CHAR_WIDTH)
    if room < 3:
        return ""
    return name if len(name) <= room else name[: room - 2] + ".."


def fill_of(name: str) -> str:
    """Return the colour of a frame of the plain graph: a warm colour fixed by the name."""
    value = zlib.crc32(name.encode("utf-8", "surrogatepass"))
    red = 200 + value % 56
    green = 90 + (value >> 8) % 140
    blue = 40 + (value >> 16) % 50
    return f"#{red:02x}{green:02x}{blue:02x}"


def change_fill(change: float, largest: float) -> str:
    """Return the colour of a frame of the difference graph for a change in share.

    Red where the subject has the larger share, blue where the baseline has
    it, grey for no change; the larger the change against the largest change
    of the graph, the stronger the colour.
    """
    strength = min(1.0, abs(change) / largest) if largest > 0 else 0.0
    pale = round(235 - 180 * strength)
    if change > 0 and strength > 0:
        return f"#ff{pale:02x}{pale:02x}"
    if change < 0 and strength > 0:
        return f"#{pale:02x}{pale:02x}ff"
    return "#ebebeb"


@dataclass
class _Node:
    name: str
    count: int = 0
    children: dict[str, _Node] = field(default_factory=dict)


def _tree(stacks: Mapping[Stack, int]) -> _Node:
    root = _Node("all")
    for stack, count in stacks.items():
        root.count += count
        node = root
        for name in stack:
            node = node.children.setdefault(name, _Node(name))
            node.count += count
    return root


def _walk(root: _Node) -> Iterator[tuple[_Node, Stack, int, int]]:
    """Yield each frame with its stack prefix, its first sample and its depth, parents first."""
    pending: list[tuple[_Node, Stack, int, int]] = [(root, (), 0, 0)]
    while pending:
        node, path, start, depth = pending.pop()
        yield node, path, start, depth
        offset = start
        placed: list[tuple[_Node, Stack, int, int]] = []
        for name in sorted(node.children):
            child = node.children[name]
            placed.append((child, (*path, name), offset, depth + 1))
            offset += child.count
        pending.extend(reversed(placed))


def _count_at(root: _Node, path: Stack) -> int:
    node = root
    for name in path:
        found = node.children.get(name)
        if found is None:
            return 0
        node = found
    return node.count


def _depth(root: _Node) -> int:
    return max((depth for _n, _p, _s, depth in _walk(root)), default=0)


def _percent(share: float) -> str:
    return f"{share * 100:.2f}%"


_STYLE = (
    "<style>"
    "text{font-family:monospace;font-size:12px;fill:#000}"
    ".pb-title{font-size:15px;font-weight:bold}"
    ".pb-ctl{cursor:pointer;fill:#1f4e9c}"
    "g.f{cursor:pointer}"
    "g.f rect{stroke:#fff;stroke-width:0.5}"
    "</style>"
)

_SCRIPT = """<script type="text/ecmascript"><![CDATA[
(function () {
  var me = document.currentScript;
  var root = (me && me.ownerSVGElement) || document.documentElement;
  var PAD = __PAD__, INNER = __INNER__, CHAR = __CHAR__, HIT = "__HIT__";
  var frames = [];
  var groups = root.querySelectorAll("g.f");
  for (var i = 0; i < groups.length; i++) {
    var g = groups[i];
    var rect = g.querySelector("rect");
    var label = g.querySelector("title").textContent;
    frames.push({
      g: g, rect: rect, text: g.querySelector("text"), label: label,
      name: label.split("\\n")[0], fill: rect.getAttribute("fill"),
      s: +g.getAttribute("data-s"), n: +g.getAttribute("data-n"), d: +g.getAttribute("data-d")
    });
  }
  var reset = root.querySelector(".pb-reset");
  var search = root.querySelector(".pb-search");
  var matched = root.querySelector(".pb-matched");
  var details = root.querySelector(".pb-details");
  if (!frames.length) { return; }
  var total = frames[0].n;
  var view = {s: 0, n: total, d: 0};
  var query = "";
  function fit(name, width) {
    var room = Math.floor((width - 6) / CHAR);
    if (room < 3) { return ""; }
    return name.length <= room ? name : name.slice(0, room - 2) + "..";
  }
  function draw() {
    for (var i = 0; i < frames.length; i++) {
      var f = frames[i];
      var inside = f.d >= view.d && f.s >= view.s && f.s + f.n <= view.s + view.n;
      var above = f.d < view.d && f.s <= view.s && f.s + f.n >= view.s + view.n;
      if (!inside && !above) { f.g.style.display = "none"; continue; }
      f.g.style.display = "";
      var x = inside ? PAD + (f.s - view.s) / view.n * INNER : PAD;
      var w = inside ? f.n / view.n * INNER : INNER;
      f.rect.setAttribute("x", x.toFixed(2));
      f.rect.setAttribute("width", w.toFixed(2));
      f.text.setAttribute("x", (x + 3).toFixed(2));
      f.text.textContent = fit(f.name, w);
      f.g.style.opacity = above ? "0.6" : "";
    }
    reset.style.opacity = view.d === 0 ? "0.5" : "1";
  }
  function mark() {
    var q = query.toLowerCase();
    var hits = [];
    for (var i = 0; i < frames.length; i++) {
      var f = frames[i];
      var hit = q !== "" && f.d > 0 && f.name.toLowerCase().indexOf(q) >= 0;
      f.rect.setAttribute("fill", hit ? HIT : f.fill);
      if (hit) { hits.push([f.s, f.s + f.n]); }
    }
    hits.sort(function (a, b) { return a[0] - b[0]; });
    var covered = 0, end = -1;
    for (var j = 0; j < hits.length; j++) {
      var lo = Math.max(hits[j][0], end), hi = hits[j][1];
      if (hi > lo) { covered += hi - lo; }
      if (hi > end) { end = hi; }
    }
    search.textContent = q ? "Search: " + query + " (Escape clears)"
      : "Search: type to mark frames";
    matched.textContent = q
      ? "Matched: " + (100 * covered / total).toFixed(2) + "% of samples" : "";
  }
  frames.forEach(function (f) {
    f.g.addEventListener("click", function () { view = {s: f.s, n: f.n, d: f.d}; draw(); });
    f.g.addEventListener("mouseover", function () {
      details.textContent = f.label.split("\\n").join("  |  ");
    });
    f.g.addEventListener("mouseout", function () { details.textContent = ""; });
  });
  reset.addEventListener("click", function () { view = {s: 0, n: total, d: 0}; draw(); });
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) { return; }
    if (e.key === "Escape") { query = ""; }
    else if (e.key === "Backspace") { query = query.slice(0, -1); }
    else if (e.key && e.key.length === 1) { query += e.key; }
    else { return; }
    if (e.preventDefault) { e.preventDefault(); }
    mark();
  });
  draw();
})();
]]></script>"""


def _script() -> str:
    return (
        _SCRIPT.replace("__PAD__", str(PAD))
        .replace("__INNER__", str(INNER))
        .replace("__CHAR__", repr(CHAR_WIDTH))
        .replace("__HIT__", HIT)
    )


def _text(x: float, y: float, words: str, cls: str = "", anchor: str = "") -> str:
    attrs = f' class="{cls}"' if cls else ""
    attrs += f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x:.2f}" y="{y:.2f}"{attrs}>{escape(words)}</text>'


def _frames(
    root: _Node, labels: Mapping[Stack, str], fills: Mapping[Stack, str], depth: int
) -> list[str]:
    out: list[str] = []
    total = root.count
    for node, path, start, level in _walk(root):
        x = PAD + start / total * INNER
        width = node.count / total * INNER
        y = TOP + (depth - level) * ROW
        out.append(
            f'<g class="f" data-s="{start}" data-n="{node.count}" data-d="{level}">'
            f"<title>{escape(labels[path])}</title>"
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{ROW - 1}" '
            f'fill="{fills[path]}"/>'
            f'<text x="{x + 3:.2f}" y="{y + 12:.2f}">{escape(fit(node.name, width))}</text>'
            "</g>"
        )
    return out


def _document(height: int, body: list[str], with_script: bool) -> str:
    head = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{WIDTH}" '
        f'height="{height}" viewBox="0 0 {WIDTH} {height}">\n'
        "<!-- pairbench flame graph. This file holds names from the user's code. -->\n"
    )
    parts = [
        head,
        _STYLE,
        "\n",
        f'<rect x="0" y="0" width="{WIDTH}" height="{height}" fill="#fff"/>\n',
    ]
    parts.extend(line + "\n" for line in body)
    if with_script:
        parts.append(_script() + "\n")
    parts.append("</svg>\n")
    return "".join(parts)


def _header(title: str, instrument: str) -> list[str]:
    words = INSTRUMENT_WORDS.get(instrument, f"Stacks sampled by instrument {instrument}.")
    return [
        _text(PAD, 18, title, "pb-title"),
        _text(PAD, 36, f"{words} {HOLDS_NAMES}"),
        _text(PAD, 54, "Reset zoom", "pb-ctl pb-reset"),
        _text(WIDTH / 2, 54, "", "pb-matched", "middle"),
        _text(WIDTH - PAD, 54, "Search: type to mark frames", "pb-ctl pb-search", "end"),
    ]


def flame_svg(stacks: Mapping[Stack, int], *, side: str, instrument: str) -> str:
    """Return the flame graph of one side's stacks as the text of an SVG file."""
    root = _tree(stacks)
    body = _header(f"Flame graph of side {side}", instrument)
    if not root.count:
        body.append(_text(PAD, TOP + 12, "No samples were taken."))
        return _document(TOP + 30, body, with_script=False)
    depth = _depth(root)
    labels: dict[Stack, str] = {}
    fills: dict[Stack, str] = {}
    for node, path, _start, _level in _walk(root):
        share = node.count / root.count
        labels[path] = f"{node.name}\n{node.count} samples, {_percent(share)} of samples"
        fills[path] = ROOT_FILL if not path else fill_of(node.name)
    body.extend(_frames(root, labels, fills, depth))
    bottom = TOP + (depth + 1) * ROW
    body.append(_text(PAD, bottom + 16, "", "pb-details"))
    return _document(bottom + 26, body, with_script=True)


def flame_diff_svg(
    subject_stacks: Mapping[Stack, int],
    baseline_stacks: Mapping[Stack, int],
    *,
    subject: str,
    baseline: str,
    instrument: str,
) -> str:
    """Return the difference graph of a subject against the baseline as the text of an SVG file.

    Both sides' stacks come from the same instrument. The subject's stacks
    set the widths; a frame's colour is the change in its share of samples.
    """
    own, other = _tree(subject_stacks), _tree(baseline_stacks)
    body = _header(f"Difference graph of side {subject} against side {baseline}", instrument)
    legend = [
        f"Widths are the samples of {subject}. Red: the frame has a larger share of samples "
        f"on {subject} than on {baseline}.",
        f"Blue: the frame has a larger share of samples on {baseline}. Grey: the same share. "
        "A paler colour is a smaller change.",
    ]
    y = TOP
    if own.count:
        depth = _depth(own)
        changes: dict[Stack, float] = {}
        labels: dict[Stack, str] = {}
        for node, path, _start, _level in _walk(own):
            own_share = node.count / own.count
            other_count = _count_at(other, path) if path else other.count
            other_share = other_count / other.count if other.count else 0.0
            changes[path] = own_share - other_share if path else 0.0
            change = 100 * changes[path]
            labels[path] = (
                f"{node.name}\n{subject}: {_percent(own_share)} of samples ({node.count})\n"
                f"{baseline}: {_percent(other_share)} of samples ({other_count})\n"
                f"change: {change:+.2f} percentage points"
            )
        largest = max((abs(v) for p, v in changes.items() if p), default=0.0)
        fills = {p: (ROOT_FILL if not p else change_fill(v, largest)) for p, v in changes.items()}
        body.extend(_frames(own, labels, fills, depth))
        y = TOP + (depth + 1) * ROW
        body.append(_text(PAD, y + 16, "", "pb-details"))
        y += 26
    else:
        body.append(_text(PAD, TOP + 12, f"No samples were taken on {subject}."))
        y = TOP + 26
    for line in legend:
        y += 16
        body.append(_text(PAD, y, line))
    body.append(
        f'<rect x="{WIDTH - PAD - 120}" y="{y - 26}" width="12" height="12" '
        f'fill="{change_fill(1.0, 1.0)}"/>'
    )
    body.append(_text(WIDTH - PAD - 104, y - 16, f"larger on {subject}"))
    body.append(
        f'<rect x="{WIDTH - PAD - 120}" y="{y - 10}" width="12" height="12" '
        f'fill="{change_fill(-1.0, 1.0)}"/>'
    )
    body.append(_text(WIDTH - PAD - 104, y, f"larger on {baseline}"))
    only = sorted(
        ((count, stack_text(stack)) for stack, count in baseline_stacks.items() if count),
        key=lambda item: (-item[0], item[1]),
    )
    only = [(c, t) for c, t in only if not subject_stacks.get(tuple(t.split(";")), 0)]
    y += 26
    if only:
        body.append(
            _text(PAD, y, f"Stacks only {baseline} has, not drawn above, largest share first:")
        )
        for count, text in only[:LIST_MAX]:
            y += 16
            share = count / other.count
            room = int((INNER - 90) // CHAR_WIDTH)
            shown = text if len(text) <= room else ".." + text[len(text) - room + 2 :]
            body.append(
                f"<g><title>{escape(text)}</title>"
                + _text(PAD, y, f"{_percent(share):>8}  {shown}")
                + "</g>"
            )
        if len(only) > LIST_MAX:
            y += 16
            body.append(
                _text(
                    PAD,
                    y,
                    f"and {len(only) - LIST_MAX} more stacks only {baseline} has: "
                    "see the difference file.",
                )
            )
    else:
        body.append(_text(PAD, y, f"{baseline} has no stack that {subject} does not have."))
    return _document(y + 14, body, with_script=bool(own.count))
