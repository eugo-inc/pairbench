# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The self-test controls, each one a unit test, and a self-test that never raises."""

from __future__ import annotations

import pytest

from pairbench.model import Capture
from pairbench.stats import selftest
from pairbench.stats.selftest import ControlResult, run_control, run_selftest, synthetic_capture
from pairbench.stats.signtest import SignTest, sign_test

IDS = (
    "K1", "K2", "K3", "K4",
    "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
    "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17",
)  # fmt: skip


@pytest.mark.parametrize("control_id", IDS)
def test_each_control_passes(control_id: str) -> None:
    got = run_control(control_id)
    assert got.id == control_id
    assert got.title
    assert got.passed, got.detail
    assert got.detail == "every value as expected"


def test_the_controls_run_in_their_fixed_order() -> None:
    results = run_selftest()
    assert tuple(r.id for r in results) == IDS
    assert all(isinstance(r, ControlResult) for r in results)


def test_a_control_whose_answer_is_wrong_fails_and_says_what_differed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selftest, "min_rounds", lambda m, alpha=0.05: 1)
    got = run_control("K4")
    assert not got.passed
    assert "min_rounds(1): expected 6, found 1" in got.detail


@pytest.mark.parametrize(
    ("wrong", "named"),
    [((0, 0), "sign test (0, 0)"), ((18, 6), "18 against 6")],
)
def test_the_sign_test_control_checks_every_known_answer(
    monkeypatch: pytest.MonkeyPatch, wrong: tuple[int, int], named: str
) -> None:
    real = sign_test

    def off_by_one(n_lower: int, n_higher: int) -> SignTest:
        if (n_lower, n_higher) == wrong:
            return real(n_lower + 1, n_higher)
        return real(n_lower, n_higher)

    monkeypatch.setattr(selftest, "sign_test", off_by_one)
    got = run_control("K1")
    assert not got.passed
    assert named in got.detail


def test_a_control_that_raises_is_reported_failed_and_the_self_test_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: object, **kwargs: object) -> object:
        raise ValueError("x")

    monkeypatch.setattr(selftest, "analyse_captures", broken)
    results = run_selftest()
    by_id = {r.id: r for r in results}
    assert tuple(by_id) == IDS
    assert not by_id["C1"].passed
    assert by_id["C1"].detail == "raised ValueError: x"
    assert by_id["K1"].passed


def test_an_unknown_control_id_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        run_control("C99")


def _flat(entry: str, case: str, round_: int, u: float) -> float:
    return 1.0 + u


def test_the_generator_is_seeded() -> None:
    a = synthetic_capture(_flat, seed=5, capture_id="x-a")
    b = synthetic_capture(_flat, seed=5, capture_id="x-a")
    c = synthetic_capture(_flat, seed=6, capture_id="x-a")
    assert a == b
    assert a.observations != c.observations


def test_the_generator_writes_a_capture_like_a_run_does() -> None:
    def double(entry: str, case: str, round_: int, u: float) -> float:
        return 2.0

    got = synthetic_capture(_flat, rounds=4, control=double, capture_id="x-b")
    assert got.complete
    assert got.lineup is not None
    assert got.lineup.names == ("new", "new~same", "old", "old~same")
    assert got.lineup.control == "old~twice"
    assert got.control is not None and got.control.control_of == "old"
    warm = [x for x in got.launches if x.phase == "warmup"]
    assert [x.name for x in warm] == ["new", "old"]
    rounds = [x for x in got.launches if x.phase == "round"]
    assert len(rounds) == 20
    assert {x.pos for x in rounds if x.name == "old~twice"} == {5}
    assert got.machine is not None and got.machine.cpu.model == "cpu-model-a"
    again = Capture.from_records(got.to_records(), source=got.source)
    assert again == got
