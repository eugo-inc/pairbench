# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""plan words the round count of a one-side experiment plainly and in good grammar.

With one side no verdict is sought, so no round count is refused as too few for one.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

NO_CASE = "# primary cases: none can get a verdict, as no subject is compared"
ROUND_COUNT = (
    "# the round count of 10 holds for up to 1 primary case; more raise it after warm-up, "
    "although no case gets a verdict"
)


def test_one_side_on_auto_rounds_says_no_case_gets_a_verdict(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    got = cli("plan", "--side", "old=cmd:true", "--rounds", "auto")
    assert got.code == EXIT_OK
    header = [line for line in got.out.splitlines() if line.startswith("# ")]
    assert header.index(NO_CASE) + 1 == header.index(ROUND_COUNT)
    assert "primary cases;" not in got.out
    assert got.err == ""


def test_one_side_on_two_rounds_is_planned_as_no_verdict_is_sought(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    got = cli("plan", "--side", "old=cmd:true", "--rounds", "2")
    assert got.code == EXIT_OK
    assert got.err == ""
    header = [line for line in got.out.splitlines() if line.startswith("# ")]
    assert "# rounds: requested 2, planned 2" in header
    assert NO_CASE in header
