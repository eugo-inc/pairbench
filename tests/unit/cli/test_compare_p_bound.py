# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare writes a p-value below the float range as a bound, never as zero."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pairbench
from pairbench.errors import EXIT_OK
from pairbench.mcp import server
from pairbench.model import NOTE_TWIN_DIFFERS, Results
from pairbench.stats.selftest import synthetic_capture

Cli = Callable[..., Any]

# All pairs agreeing in this many rounds give an exact p-value of 2 / 2**1200,
# far below the smallest float, which is about 5e-324.
ROUNDS = 1200
BOUND = "< 1e-300"


def text_capture(folder: Path) -> Path:
    """Rounds in alternating pass order in which new always reads half of old."""
    lines = ["## host", "unit=s", "better=lower", "sides=new old"]
    for r in range(1, ROUNDS + 1):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        for side in order:
            lines.append(f"s\t{side}\t{r}\tfast\t{1.0 if side == 'new' else 2.0!r}")
    path = folder / "rows.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_terminal_report_writes_the_bound(cli: Cli, tmp_path: Path) -> None:
    got = cli("compare", str(text_capture(tmp_path)), "--reader", "text")
    assert got.code == EXIT_OK
    row = next(line for line in got.out.splitlines() if line.startswith("fast "))
    assert f"  {BOUND}*  " in row
    assert " 0.0" not in row


def test_the_figures_keep_the_value_and_write_the_bound(cli: Cli, tmp_path: Path) -> None:
    got = cli("compare", str(text_capture(tmp_path)), "--reader", "text", "--json")
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    figures = document["figures"]
    for name in ("p", "p_corrected"):
        assert figures[f"fast.new_vs_old.{name}"] == {"value": 0.0, "text": BOUND}
    assert document["comparisons"][0]["p_raw_fraction"] == [2, 2**ROUNDS]


def test_the_explanation_says_the_bound(cli: Cli, tmp_path: Path) -> None:
    got = cli("compare", str(text_capture(tmp_path)), "--reader", "text", "--json")
    results = Results.from_json(json.loads(got.out))
    words = server.explain_comparison(results, results.comparisons[0])
    assert (
        f"The exact sign test gives p {BOUND} (the exact fraction is p_raw_fraction in the results)"
    ) in words
    assert "p = 0" not in words


def drifting_twin(entry: str, case: str, round_: int, u: float) -> float:
    """new reads twice old; every twin reads 1 percent above its side in every round."""
    side = 2.0 if entry.startswith("new") else 1.0
    return side * 1.01 if entry.endswith("~same") else side


def test_the_note_of_a_twin_that_differs_says_the_bound() -> None:
    results = pairbench.analyse(synthetic_capture(drifting_twin, rounds=ROUNDS))
    notes = [n.message for n in results.notes if n.code == NOTE_TWIN_DIFFERS]
    assert notes
    assert all(f"more often than chance (p {BOUND})" in message for message in notes)
