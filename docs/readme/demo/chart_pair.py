# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Keep a run's verdict chart for the README as a light and a dark file.

    python3 chart_pair.py RUN/charts/verdict.svg docs/readme

The light file is the chart as ``pairbench run`` drew it, byte for byte. The dark file is the
same chart with each colour replaced by one from a fixed map, and a default fill for text,
which the drawn chart leaves black.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Each colour the chart is drawn with, and its colour on a dark page. The outcome colours
# keep their hue and are lightened where they would read too dark.
DARK = {
    "#ffffff": "#0d1117",
    "#000000": "#d9dce6",
    "#c8c8c8": "#3a4256",
    "#555555": "#a9b1c4",
    "#7f7f7f": "#a9b1c4",
    "#0072b2": "#4fa3e0",
    "#009e73": "#2fc79c",
    "#d55e00": "#ff8a4c",
    "#e69f00": "#f5c451",
}
TEXT_FILL = '<style type="text/css">text{fill:#d9dce6}</style>'


COLOUR = re.compile("|".join(DARK))


def dark(light: str) -> str:
    """The dark form of a chart's SVG text: every colour mapped in one pass."""
    text = COLOUR.sub(lambda found: DARK[found.group(0)], light)
    return text.replace("<defs>", f"<defs>\n  {TEXT_FILL}", 1)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: chart_pair.py VERDICT_SVG OUT_FOLDER", file=sys.stderr)
        return 2
    light = Path(argv[1]).read_text(encoding="utf-8")
    out = Path(argv[2])
    (out / "chart-light.svg").write_text(light, encoding="utf-8")
    (out / "chart-dark.svg").write_text(dark(light), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
