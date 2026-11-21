# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare gives the note of a side that differs from its twin, on its combined check."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pairbench.errors import EXIT_OK
from pairbench.model import NOTE_TWIN_DIFFERS

Cli = Callable[..., Any]

ROUNDS = 16
# The twin of new reads 1 percent above it in all 16 rounds: p = 2/65536.
# The twin of old reads above and below it in turn: p = 1. Two sides are
# tested, so the p-value of new is doubled, and 4/65536 is written to three
# digits.
MESSAGE = (
    "new differs from an identical copy of itself more often than chance across its primary "
    "cases (p = 6.1e-05, corrected for testing 2 sides at once): the machine or the order is "
    "biasing the run"
)
# results.md writes the code with its underscore escaped.
MARKDOWN_LINE = f"- Note twin\\_differs: {MESSAGE}"
STDERR_LINE = f"pairbench: note: twin_differs: {MESSAGE}"


def rows_capture(
    folder: Path,
    rounds: int,
    values_of: Callable[[int], dict[str, float]],
    names: tuple[str, ...] = ("new", "newtwin", "old", "oldtwin"),
) -> Path:
    """Rows of two sides and their twins, in an order that reverses each round."""
    lines = [
        "## host",
        "unit=s",
        "better=lower",
        "sides=" + " ".join(names),
        "twin=newtwin:new",
        "twin=oldtwin:old",
    ]
    for r in range(1, rounds + 1):
        order = names if r % 2 else tuple(reversed(names))
        lines.append("pass_order=" + " ".join(order))
        values = values_of(r)
        for side in order:
            lines.append(f"s\t{side}\t{r}\tfast\t{values[side]!r}")
    path = folder / "rows.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def apart_in_turn(r: int) -> dict[str, float]:
    """The twin of new reads above it in every round; the twin of old above and below in turn."""
    return {
        "new": 1.0,
        "newtwin": 1.01,
        "old": 2.0,
        "oldtwin": 2.0 * (1.001 if r % 2 else 0.999),
    }


def twin_capture(folder: Path) -> Path:
    return rows_capture(folder, ROUNDS, apart_in_turn)


def test_the_twin_note_goes_to_the_results_and_to_standard_error(cli: Cli, tmp_path: Path) -> None:
    out = tmp_path / "out"
    got = cli(
        "compare", str(twin_capture(tmp_path)), "--reader", "text", "--json", "--out", str(out)
    )
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    assert [n["message"] for n in document["notes"] if n["code"] == NOTE_TWIN_DIFFERS] == [MESSAGE]
    rows = [(row["side"], row["p_raw"]) for row in document["same_vs_same"]]
    assert rows == [("new", 2 / 65536), ("old", 1.0)]
    assert all("p_corrected" not in row for row in document["same_vs_same"])
    checks = [
        (c["side"], c["n_rounds"], c["n_better"], c["n_worse"], c["p_raw"], c["p_corrected"])
        for c in document["twin_checks"]
    ]
    assert checks == [("new", 16, 16, 0, 2 / 65536, 4 / 65536), ("old", 16, 8, 8, 1.0, 1.0)]
    assert [line for line in got.err.splitlines() if NOTE_TWIN_DIFFERS in line] == [STDERR_LINE]
    assert STDERR_LINE not in got.out
    written = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert written["notes"] == document["notes"]
    markdown = (out / "results.md").read_text(encoding="utf-8").splitlines()
    assert [line for line in markdown if "twin\\_differs" in line] == [MARKDOWN_LINE]


# The twin of new reads 1 percent above it in rounds 1 to 7 and as new in
# round 8, and the twin of old reads 1 percent above it in rounds 1 to 6 and as
# old in rounds 7 and 8. The tied rounds are scored and dropped from the test:
# new has 7 of 7 untied rounds, p = 2/128, and old 6 of 6, p = 2/64. The
# correction doubles 2/128 and leaves 2/64, so both are 4/128, written to three
# digits, and both sides get the note.
TIED_ROUNDS = 8
TIED_MESSAGE = (
    "{side} differs from an identical copy of itself more often than chance across its "
    "primary cases (p = 0.0312, corrected for testing 2 sides at once): the machine or the "
    "order is biasing the run"
)


def test_compare_counts_tied_rounds_and_notes_six_one_way_rounds_beside_seven(
    cli: Cli, tmp_path: Path
) -> None:
    rows = rows_capture(
        tmp_path,
        TIED_ROUNDS,
        lambda r: {
            "new": 1.0,
            "newtwin": 1.01 if r <= 7 else 1.0,
            "old": 2.0,
            "oldtwin": 2.02 if r <= 6 else 2.0,
        },
    )
    got = cli("compare", str(rows), "--reader", "text", "--json", "--out", str(tmp_path / "out"))
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    checks = [
        (c["side"], c["n_rounds"], c["n_better"], c["n_worse"], c["p_raw"], c["p_corrected"])
        for c in document["twin_checks"]
    ]
    assert checks == [("new", 8, 7, 0, 2 / 128, 4 / 128), ("old", 8, 6, 0, 2 / 64, 4 / 128)]
    assert [n["message"] for n in document["notes"] if n["code"] == NOTE_TWIN_DIFFERS] == [
        TIED_MESSAGE.format(side="new"),
        TIED_MESSAGE.format(side="old"),
    ]
    assert [line for line in got.err.splitlines() if NOTE_TWIN_DIFFERS in line] == [
        f"pairbench: note: twin_differs: {TIED_MESSAGE.format(side=side)}"
        for side in ("new", "old")
    ]


def test_compare_lists_the_twin_checks_in_the_order_the_lineup_lists_the_twins(
    cli: Cli, tmp_path: Path
) -> None:
    # The lineup lists old and its twin before new and its twin.
    rows = rows_capture(tmp_path, ROUNDS, apart_in_turn, names=("old", "oldtwin", "new", "newtwin"))
    got = cli("compare", str(rows), "--reader", "text", "--json", "--out", str(tmp_path / "out"))
    assert got.code == EXIT_OK
    document = json.loads(got.out)
    checks = [
        (c["side"], c["n_rounds"], c["n_better"], c["n_worse"], c["p_raw"], c["p_corrected"])
        for c in document["twin_checks"]
    ]
    assert checks == [("old", 16, 8, 8, 1.0, 1.0), ("new", 16, 16, 0, 2 / 65536, 4 / 65536)]


# What the schema says of a document written without the combined checks.
SCHEMA_EMPTY_WORDS = (
    "A document written without twin_checks reads as holding none, and pairbench report "
    "--format json then gives an empty list."
)
PAGE_EMPTY_WORDS = (
    "A document written without `twin_checks` reads as holding none, and `pairbench report "
    "--format json` then gives an empty list."
)


def test_a_document_written_without_the_twin_checks_reports_none(cli: Cli, tmp_path: Path) -> None:
    out = tmp_path / "out"
    made = cli("compare", str(twin_capture(tmp_path)), "--reader", "text", "--out", str(out))
    assert made.code == EXIT_OK
    path = out / "results.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["twin_checks"]
    path.write_text(json.dumps(document), encoding="utf-8")
    got = cli("report", str(path), "--format", "json")
    assert got.code == EXIT_OK
    assert json.loads(got.out)["twin_checks"] == []
    root = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (root / "src/pairbench/results/schema/results.v1.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["twin_checks"]["description"].endswith(SCHEMA_EMPTY_WORDS)
    assert "p_corrected" not in schema["$defs"]["SameVsSame"]["properties"]
    page = " ".join((root / "docs/reference/results-schema.md").read_text(encoding="utf-8").split())
    assert PAGE_EMPTY_WORDS in page
