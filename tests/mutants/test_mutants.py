# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The mutation list stays applicable to the source as it is.

The changes themselves are applied by ``run_mutants.py``; these tests only
check that every entry can still be applied: its text is found once, it
changes one line and its test exists.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# The changes the mutation job must always hold, named by their titles.
REQUIRED_TITLES = (
    "count ties as trials",
    "drop the reversal from the schedule",
    "turn < into <= in the significance check",
    "turn <= into < at the bar",
    "drop the monotone step in the correction",
    "let a failed probe pass the quiet check",
    "proceed without a lock after a lock error",
    "skip the twin fingerprint check",
    "allow a pull during a round",
    "let the decision to set a round aside read a measured value",
    "write a host name into the results",
    "accept a capture without an end record",
    "pool the same file twice",
    "treat a missing figure as empty text",
    "positive control",
    "launch-cost note",
    "report page without escaping",
    "make the owner-only pass do nothing",
    "narrow a file another user owns",
    "follow a link on the way down",
    "skip the owner-only pass after a timed launch",
    "skip the owner-only pass after a stopped timed launch",
    "open a file of the owner-only pass through a link",
    "drop the check of the opened file",
    "skip the hand-back of a stopped container launch",
    "skip the hand-back of a stopped serving launch",
    "skip the hand-back of a serving start cut short",
    "publish a sidecar that cannot be shared",
    "judge the twin note on the uncorrected p-value of a side",
    "score a twin round by the mean of its primary cases",
)


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_pb_{name}", HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MUTANTS = load("mutants").MUTANTS
RUNNER = load("run_mutants")


# The list holds from FEWEST to MOST changes.
FEWEST = 25
MOST = 45


def test_the_list_holds_from_twenty_five_to_forty_five_changes_with_unique_ids() -> None:
    ids = [m.id for m in MUTANTS]
    assert len(ids) == len(set(ids))
    assert FEWEST <= len(ids) <= MOST


def test_the_bound_on_the_list_leaves_room_for_the_next_change() -> None:
    assert len(MUTANTS) < MOST


@pytest.mark.parametrize("title", REQUIRED_TITLES)
def test_every_required_change_is_listed(title: str) -> None:
    assert [m.id for m in MUTANTS if title in m.title] != []


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.id for m in MUTANTS])
def test_each_change_applies_to_the_source_as_it_is(mutant: object) -> None:
    assert RUNNER.problems_of(mutant, ROOT) == []


def test_a_change_found_twice_or_of_two_lines_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "src" / "x.py"
    source.parent.mkdir()
    source.write_text("a = 1\na = 1\nb = 2\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("", encoding="utf-8")
    twice = MUTANTS[0].__class__("X1", "x", "src/x.py", "a = 1", "a = 2", "tests/test_x.py")
    two_lines = MUTANTS[0].__class__(
        "X2", "x", "src/x.py", "a = 1\nb = 2", "a = 3\nb = 4", "tests/test_x.py"
    )

    assert RUNNER.problems_of(twice, tmp_path) == [
        "the text to change is found 2 times in x.py, not once"
    ]
    assert RUNNER.problems_of(two_lines, tmp_path) == ["the change is not exactly one changed line"]


def test_only_a_failing_test_counts_as_a_caught_change() -> None:
    assert RUNNER.PYTEST_FAILED == 1
    assert RUNNER.failed_tests("FAILED tests/a.py::b - x\nok\n") == ["tests/a.py::b"]
