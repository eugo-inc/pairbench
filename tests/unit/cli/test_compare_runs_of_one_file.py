# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare pools the different runs of one text file, and refuses one run given twice."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK

from .conftest import refusal_text

Cli = Callable[..., Any]

ROUNDS = 16
NAMES = ("new", "newtwin", "old", "oldtwin")
# The bytes of the file ``_two_runs`` writes are fixed, so the id of each run, ``text-`` and
# the first twelve hex digits of the SHA-256 of the file's hash, a colon and the run's index,
# is fixed too.
RUN_0 = "text-43d6c89f5bb7"
RUN_1 = "text-4b732b82e9f5"


def _run(lines: list[str], step: float) -> None:
    lines += ["## host", "unit=s", "sides=new old", "twin=newtwin:new", "twin=oldtwin:old"]
    for r in range(1, ROUNDS + 1):
        order = NAMES if r % 2 else tuple(reversed(NAMES))
        lines.append("pass_order=" + " ".join(order))
        turn = (0.001 + r / 100000) * (1 if r % 2 else -1)
        new, old = 1.0 + r * step, 2.0 + r * step
        values = {"new": new, "newtwin": new + turn, "old": old, "oldtwin": old - turn}
        lines += [f"s\t{side}\t{r}\tfast\t{values[side]!r}" for side in order]


def _two_runs(folder: Path) -> Path:
    """Two runs of one experiment in one file, with different values in each."""
    lines: list[str] = []
    _run(lines, 0.001)
    _run(lines, 0.002)
    path = folder / "runs.txt"
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


@pytest.mark.parametrize("mode", [(), ("--lenient",)], ids=["strict", "lenient"])
def test_two_runs_of_one_file_pool(mode: tuple[str, ...], cli: Cli, tmp_path: Path) -> None:
    got = cli("compare", str(_two_runs(tmp_path)), "--reader", "text", *mode, "--json")
    assert got.code == EXIT_OK
    assert "E_POOL" not in got.err
    document = json.loads(got.out)
    run = document["run"]
    assert run["pooled"] is True
    assert [(c["capture_id"], c["rounds"]) for c in run["captures"]] == [
        (RUN_0, ROUNDS),
        (RUN_1, ROUNDS),
    ]
    assert run["captures"][0]["sha256"] == run["captures"][1]["sha256"]
    assert document["refusals"] == []
    rows = [
        (c["case"], c["subject"], c["baseline"], c["n_rounds"], c["n_lower"], c["verdict"])
        for c in document["comparisons"]
    ]
    assert rows == [("fast", "new", "old", 2 * ROUNDS, 2 * ROUNDS, "FASTER")]
    # Every one of the 32 paired rounds is lower: p = 2 / 2**32.
    assert [c["p_raw_fraction"] for c in document["comparisons"]] == [[2, 2**32]]


def test_one_run_given_twice_is_refused(cli: Cli, tmp_path: Path) -> None:
    path = _two_runs(tmp_path)
    got = cli("compare", str(path), str(path), "--reader", "text")
    assert got.code == EXIT_ANALYSIS
    assert got.out == ""
    assert got.err == refusal_text(f"E_POOL_SAME: the capture {RUN_0} is given twice")


def test_one_run_of_two_files_with_the_same_bytes_is_refused(cli: Cli, tmp_path: Path) -> None:
    path = _two_runs(tmp_path)
    copy = tmp_path / "copy.txt"
    shutil.copyfile(path, copy)
    got = cli("compare", str(path), str(copy), "--reader", "text")
    assert got.code == EXIT_ANALYSIS
    assert got.out == ""
    assert got.err == refusal_text(f"E_POOL_SAME: the capture {RUN_0} is given twice")
