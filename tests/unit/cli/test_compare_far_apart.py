# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare on values so far apart that a figure of their ratio is no finite number.

The case gets NO VERDICT with the reason too_far_apart and none of the
figures made from its ratio; every other case is judged and written. The
captures are made-up text captures.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

# A ratio that is a finite number but whose speed-up (1 / ratio) or percent
# (100 * (ratio - 1)) is not, and a ratio that underflows to zero. The first
# is a benchmark that prints the largest double as its "no result" value.
FAR_PAIRS = [
    pytest.param(1.0, 1.7976931348623157e308, id="speedup-of-a-tiny-ratio-overflows"),
    pytest.param(1e307, 1.0, id="percent-of-a-huge-ratio-overflows"),
    pytest.param(5e-324, 1.0, id="speedup-of-the-smallest-number-overflows"),
    pytest.param(1e-30, 1e300, id="ratio-underflows-to-zero"),
]
# The reason of case edge in plain words: each names the figure that is no
# finite number, or the ratio that cannot be told from zero. The median of
# sixteen copies of the largest double is that double, though the two middle
# values add up past it.
REASON_WORDS = {
    (1.0, 1.7976931348623157e308): (
        "the medians 1 and 1.8e+308 are too far apart for the inverse of their ratio to be a "
        "finite number"
    ),
    (1e307, 1.0): (
        "the medians 1e+307 and 1 are too far apart for their difference in percent to be a "
        "finite number"
    ),
    (5e-324, 1.0): (
        "the medians 4.94e-324 and 1 are too far apart for the inverse of their ratio to be a "
        "finite number"
    ),
    (1e-30, 1e300): (
        "the medians 1e-30 and 1e+300 are too far apart for their ratio to be told from zero"
    ),
}
# The figures a comparison has only when its ratio is usable.
RATIO_FIGURES = frozenset({"ratio", "statistic", "speedup", "percent"})


def text_capture(folder: Path, edge_new: float, edge_old: float) -> Path:
    """Sixteen rounds in alternating pass order: case edge, and case plain at 2.0 against 1.0."""
    lines = ["## host", "unit=s", "better=lower", "sides=new old"]
    for r in range(1, 17):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        for side in order:
            edge, plain = (edge_new, 2.0) if side == "new" else (edge_old, 1.0)
            lines += [f"s\t{side}\t{r}\tedge\t{edge!r}", f"s\t{side}\t{r}\tplain\t{plain!r}"]
    path = folder / "rows.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(("edge_new", "edge_old"), FAR_PAIRS)
def test_compare_gives_no_verdict_to_a_ratio_without_finite_figures_and_writes_the_rest(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edge_new: float,
    edge_old: float,
) -> None:
    monkeypatch.chdir(tmp_path)
    rows = text_capture(tmp_path, edge_new, edge_old)

    printed = cli("compare", str(rows), "--reader", "text", "--json")

    assert printed.code == EXIT_OK
    document = json.loads(printed.out)
    edge, plain = document["comparisons"]
    assert (edge["case"], edge["verdict"], edge["outcome"], edge["reason"]) == (
        "edge",
        "NO VERDICT",
        "no_verdict",
        "too_far_apart",
    )
    assert (edge["ratio"], edge["statistic"], edge["gap"]) == (None, None, None)
    assert (plain["case"], plain["ratio"], plain["reason"]) == ("plain", 2.0, "no_floor")
    figures = document["figures"]
    shown = {key.rsplit(".", 1)[1] for key in figures if key.startswith("edge.new_vs_old.")}
    assert RATIO_FIGURES.isdisjoint(shown)
    assert figures["edge.new_vs_old.verdict"] == {"value": "no_verdict", "text": "NO VERDICT"}
    assert figures["plain.new_vs_old.ratio"] == {"value": 2.0, "text": "2.00x"}
    assert figures["plain.new_vs_old.speedup"] == {"value": 0.5, "text": "0.50x"}


@pytest.mark.parametrize(("edge_new", "edge_old"), FAR_PAIRS)
def test_compare_writes_both_reports_of_a_ratio_without_finite_figures(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    edge_new: float,
    edge_old: float,
) -> None:
    monkeypatch.chdir(tmp_path)
    rows = text_capture(tmp_path, edge_new, edge_old)

    shown = cli("compare", str(rows), "--reader", "text", "--out", "out")

    assert shown.code == EXIT_OK
    edge_line = next(line for line in shown.out.splitlines() if line.startswith("edge "))
    assert edge_line.endswith(f"NO VERDICT ({REASON_WORDS[(edge_new, edge_old)]})")
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [c["reason"] for c in written["comparisons"]] == ["too_far_apart", "no_floor"]
    markdown = (tmp_path / "out" / "results.md").read_text(encoding="utf-8")
    assert REASON_WORDS[(edge_new, edge_old)] in " ".join(markdown.split())
