# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare writes very large and very small numbers in their short form."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

# Per case: the value of side new, the value of side old.
VALUES = {
    "big": (1e300, 2e300),
    "small": (1e-10, 3e-10),
    "far": (1e-10, 1.0),
    # Two middle values whose sum is beyond the largest float.
    "huge": (1.6e308, 1.7e308),
}
# Per case: the texts of the median of new, the median of old and the change.
TEXTS = {
    "big": ("1.00e+300 s", "2.00e+300 s", "2.00x faster"),
    "small": ("1.00e-10 s", "3.00e-10 s", "3.00x faster"),
    "far": ("1.00e-10 s", "1.00 s", "1e+10x faster"),
    "huge": ("1.60e+308 s", "1.70e+308 s", "1.06x faster"),
}


def text_capture(folder: Path) -> Path:
    """Sixteen rounds in alternating pass order, one value per side and case."""
    lines = ["## host", "unit=s", "better=lower", "sides=new old"]
    for r in range(1, 17):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        for side in order:
            for case, (new, old) in VALUES.items():
                lines.append(f"s\t{side}\t{r}\t{case}\t{(new if side == 'new' else old)!r}")
    path = folder / "rows.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_terminal_report_writes_far_out_medians_and_changes_short(
    cli: Cli, tmp_path: Path
) -> None:
    rows = text_capture(tmp_path)
    got = cli("compare", str(rows), "--reader", "text")
    assert got.code == EXIT_OK
    lines = {line.split()[0]: line.split() for line in got.out.splitlines() if line.strip()}
    for case, (new, old, change) in TEXTS.items():
        words = lines[case]
        assert " ".join(words[1:7]) == f"{new} {old} {change}"
    assert max(len(line) for line in got.out.splitlines()) < 200


def test_the_figures_hold_the_short_form(cli: Cli, tmp_path: Path) -> None:
    rows = text_capture(tmp_path)
    got = cli("compare", str(rows), "--reader", "text", "--json")
    assert got.code == EXIT_OK
    figures = json.loads(got.out)["figures"]
    for case, (new, old, _) in TEXTS.items():
        assert figures[f"{case}.new.median"]["text"] == new
        assert figures[f"{case}.old.median"]["text"] == old
    assert figures["far.new_vs_old.ratio"]["text"] == "1e-10x"
    assert figures["far.new_vs_old.speedup"]["text"] == "1e+10x"
