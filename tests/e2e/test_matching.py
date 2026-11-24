# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The installed command reads text capture files in the matching mode: compare --matching.

Every value below is made up.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK

from .conftest import Installed, read_json

ROUNDS = 10
MATCHING = ("--matching", "--subject", "new", "--baseline", "old")
DOCS_START = "pairbench: see https://eugo.io/docs/pairbench/"
COMMAND_NOTE_START = "pairbench: note: command_shown: "


def _row(side: str, round_: int, value: float) -> str:
    return f"s\t{side}\t{round_}\tc1\t{value}"


def _run(step: float) -> list[str]:
    lines = ["## host"]
    for r in range(1, ROUNDS + 1):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        lines += [_row(side, r, {"new": 200 + r, "old": 300 + r}[side] + step) for side in order]
    return lines


def _write(folder: Path, name: str, lines: Sequence[str]) -> Path:
    path = folder / name
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def test_two_files_whose_runs_differ_pool(installed: Installed, work: Path) -> None:
    first = _write(work, "a.txt", _run(0.0))
    second = _write(work, "b.txt", _run(0.25))

    done = installed.run("compare", first, second, *MATCHING, "--out", work / "out", cwd=work)

    assert done.code == EXIT_OK, done.err
    assert "NO VERDICT" in done.out
    note, command = done.err.splitlines()
    assert note.startswith("pairbench: note: view_without_twins: the case 'c1' has no noise floor")
    assert command.startswith(COMMAND_NOTE_START)
    assert "E_" not in done.err
    results = read_json(work / "out" / "results.json")
    assert [n["code"] for n in results["notes"]] == ["view_without_twins"]
    assert results["matching"] == {
        "runs": 2,
        "malformed_rows": 0,
        "kept_rows": 4 * ROUNDS,
        "left_out_rows": 0,
        "other_side_rows": 0,
        "refusal": None,
    }
    assert [
        (c["subject"], c["baseline"], c["n_rounds"], c["n_lower"], c["reasons"])
        for c in results["comparisons"]
    ] == [("new", "old", 2 * ROUNDS, 2 * ROUNDS, ["no_floor"])]
    assert results["refusals"] == []


def test_a_file_given_twice_is_refused_by_identical_written_rows(
    installed: Installed, work: Path
) -> None:
    path = _write(work, "a.txt", _run(0.0))

    done = installed.run("compare", path, path, *MATCHING, "--json", cwd=work)

    assert done.code == EXIT_ANALYSIS
    lines = done.err.splitlines()
    assert lines[0].startswith(COMMAND_NOTE_START)
    assert len(lines) == 3
    assert lines[1] == (
        f"E_POOL_IDENTICAL_ROWS: the runs 0 and 1 hold the same {2 * ROUNDS} rows as written"
    )
    assert lines[2].startswith(DOCS_START)
    assert lines[2].endswith("/reference/exit-codes/#e_pool_identical_rows")
    results = json.loads(done.out)
    assert [r["code"] for r in results["refusals"]] == ["E_POOL_IDENTICAL_ROWS"]
    assert results["matching"]["refusal"] == {
        "check": "identical_written_rows",
        "runs": [0, 1],
        "rows": 2 * ROUNDS,
    }
    assert results["comparisons"] == []


def test_rows_without_an_order_are_left_out_of_the_view(installed: Installed, work: Path) -> None:
    lines = _run(0.0)
    # Two rows before the run's first pass-order line, and two after a line that names one side.
    lines[1:1] = [_row("new", 1, 999), _row("old", 1, 1)]
    lines += ["pass_order=new", _row("new", ROUNDS + 1, 999), _row("old", ROUNDS + 1, 1)]
    path = _write(work, "a.txt", lines)

    done = installed.run("compare", path, *MATCHING, "--json", cwd=work)

    assert done.code == EXIT_OK, done.err
    results = json.loads(done.out)
    assert results["matching"]["left_out_rows"] == 4
    assert results["matching"]["kept_rows"] == 2 * ROUNDS + 4
    assert [(c["n_rounds"], c["subject_median"]) for c in results["comparisons"]] == [
        (ROUNDS, 205.5)
    ]


def test_a_copy_saved_with_a_byte_order_mark_is_refused(installed: Installed, work: Path) -> None:
    # The matching mode reads the marked banner as a malformed row, so both files are one
    # run; the two parts a text capture reads as two runs are compared, and refused.
    first = _write(work, "a.txt", _run(0.0))
    second = work / "b.txt"
    second.write_bytes(b"\xef\xbb\xbf" + first.read_bytes())

    done = installed.run("compare", first, second, *MATCHING, "--json", cwd=work)

    assert done.code == EXIT_ANALYSIS
    lines = done.err.splitlines()
    assert lines[0].startswith(COMMAND_NOTE_START)
    assert len(lines) == 3
    copy_line = 3 * ROUNDS + 3
    assert lines[1] == (
        "E_POOL_IDENTICAL_ROWS: the parts of the runs 0 and 0 that begin on the lines "
        f"1 and {copy_line} hold identical rows"
    )
    assert lines[2].endswith("/reference/exit-codes/#e_pool_identical_rows")
    results = json.loads(done.out)
    assert [r["code"] for r in results["refusals"]] == ["E_POOL_IDENTICAL_ROWS"]
    assert results["matching"]["runs"] == 1
    assert results["matching"]["kept_rows"] == 4 * ROUNDS
    assert results["matching"]["refusal"] == {
        "check": "identical_rows",
        "runs": [0, 0],
        "lines": [1, copy_line],
    }
    assert results["comparisons"] == []
