# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench.check_pool``: the pool checks of an analysis, run on their own.

Each refusal the analysis of a pool raises is the first refusal ``check_pool``
returns, with the same text code, exit code, scope, message and detail;
``check_pool`` returns every refusal it finds and raises none of them.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

import pytest

import pairbench
from pairbench.errors import Refusal
from pairbench.model import STRICT, Capture, CpuRecord, Source
from pairbench.stats.analyse import analyse_captures
from pairbench.stats.selftest import MATMUL, synthetic_capture


def _jittered(entry: str, case: str, round_: int, u: float) -> float:
    side = 2.0 if entry.startswith("new") else 1.0
    return side * (1.0 + round_ / 64) * (1.0 + u / 1000)


def _plain(entry: str, case: str, round_: int, u: float) -> float:
    return (2.0 if entry.startswith("new") else 1.0) * (1.0 + round_ / 64)


def _capture(ident: str, seed: int = 1, value: Any = _jittered, **options: Any) -> Capture:
    return synthetic_capture(value, capture_id=ident, seed=seed, **options)


def _two() -> tuple[Capture, Capture]:
    return _capture("synthetic-a", 1), _capture("synthetic-b", 2)


def _sides(cap: Capture, name: str, **changes: Any) -> Capture:
    sides = tuple(dataclasses.replace(s, **changes) if s.name == name else s for s in cap.sides)
    return dataclasses.replace(cap, sides=sides)


def _other_machine(cap: Capture) -> Capture:
    assert cap.machine is not None
    return dataclasses.replace(
        cap, machine=dataclasses.replace(cap.machine, cpu=CpuRecord(model="cpu-model-b"))
    )


def _same_file() -> list[Capture]:
    a, b = _two()
    return [
        dataclasses.replace(a, source=Source(path="runs.txt", sha256="f" * 64)),
        dataclasses.replace(b, source=Source(path="runs.txt", sha256="f" * 64)),
    ]


def _same_bytes() -> list[Capture]:
    a, b = _two()
    return [
        dataclasses.replace(a, source=Source(path="a.jsonl", sha256="e" * 64)),
        dataclasses.replace(b, source=Source(path="b.jsonl", sha256="e" * 64)),
    ]


def _same_id() -> list[Capture]:
    return [
        _capture("synthetic-a"),
        dataclasses.replace(_capture("synthetic-a", seed=9), source=None),
    ]


def _identical_rows() -> list[Capture]:
    return [_capture("synthetic-a", 1, _plain), _capture("synthetic-b", 2, _plain)]


def _truncated() -> list[Capture]:
    return [
        _capture("synthetic-a", value=_plain, rounds=16),
        _capture("synthetic-b", value=_plain, rounds=8),
    ]


def _fingerprint() -> list[Capture]:
    a, b = _two()
    return [a, _sides(b, "new", fingerprint="0" * 64)]


def _other_sides() -> list[Capture]:
    return [_capture("synthetic-a"), _capture("synthetic-b", 2, subjects=("new", "other"))]


def _other_cases() -> list[Capture]:
    return [
        _capture("synthetic-a"),
        _capture("synthetic-b", 2, cases=(dataclasses.replace(MATMUL, unit="ms"),)),
    ]


def _machines() -> list[Capture]:
    a, b = _two()
    return [a, _other_machine(b)]


def _mixed_purpose() -> list[Capture]:
    return [_capture("synthetic-a", subjects=()), _capture("synthetic-b", 2)]


POOLS: dict[str, Callable[[], list[Capture]]] = {
    "same-file": _same_file,
    "same-bytes": _same_bytes,
    "same-id": _same_id,
    "identical-rows": _identical_rows,
    "truncated-copy": _truncated,
    "fingerprint": _fingerprint,
    "other-sides": _other_sides,
    "other-cases": _other_cases,
    "other-machine": _machines,
    "mixed-purpose": _mixed_purpose,
}

FIRST_CODE: dict[str, str] = {
    "same-file": "E_POOL_SAME",
    "same-bytes": "E_POOL_SAME",
    "same-id": "E_POOL_SAME",
    "identical-rows": "E_POOL_IDENTICAL_ROWS",
    "truncated-copy": "E_POOL_TRUNCATED_COPY",
    "fingerprint": "E_POOL_SIDE_DRIFT",
    "other-sides": "E_POOL_SIDE_DRIFT",
    "other-cases": "E_POOL_CASES",
    "other-machine": "E_POOL_MACHINE",
    "mixed-purpose": "E_POOL_MIXED_PURPOSE",
}


def _raised(captures: Sequence[Capture]) -> Refusal:
    with pytest.raises(Refusal) as caught:
        analyse_captures(tuple(captures), rule=STRICT)
    return caught.value


def _shape(refusal: Refusal) -> tuple[str, int, str, str, dict[str, Any]]:
    return refusal.code, refusal.exit_code, refusal.scope, refusal.message, refusal.detail


@pytest.mark.parametrize("name", sorted(POOLS))
def test_the_first_refusal_returned_is_the_one_the_analysis_raises(
    name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    captures = POOLS[name]()
    found = pairbench.check_pool(captures)
    assert capsys.readouterr() == ("", "")
    assert found, name
    assert all(isinstance(one, Refusal) for one in found)
    assert found[0].code == FIRST_CODE[name]
    assert found[0].exit_code == 6
    assert _shape(found[0]) == _shape(_raised(captures))


def test_captures_that_pool_give_no_refusal() -> None:
    assert pairbench.check_pool(list(_two())) == []


def test_one_capture_and_none_give_no_refusal() -> None:
    assert pairbench.check_pool([_capture("synthetic-a")]) == []
    assert pairbench.check_pool([]) == []


def test_mixed_machines_that_are_allowed_are_not_listed() -> None:
    captures = _machines()
    assert [r.code for r in pairbench.check_pool(captures)] == ["E_POOL_MACHINE"]
    assert pairbench.check_pool(captures, allow_mixed_machines=True) == []


def test_every_refusal_is_listed_not_only_the_first() -> None:
    a = _capture("synthetic-a")
    b = _other_machine(_capture("synthetic-b", 2, cases=(dataclasses.replace(MATMUL, unit="ms"),)))
    found = pairbench.check_pool([a, b])
    assert [(r.code, r.message) for r in found] == [
        (
            "E_POOL_CASES",
            "the cases matmul differ between the captures synthetic-a and synthetic-b",
        ),
        ("E_POOL_MACHINE", "the CPU or GPU identity differs between the pooled captures"),
    ]
    assert _shape(found[0]) == _shape(_raised([a, b]))


def test_a_capture_with_other_sides_gives_one_side_drift_and_the_rest_are_checked() -> None:
    a = _capture("synthetic-a")
    other = _capture("synthetic-b", 2, subjects=("new", "other"))
    drift = _sides(_capture("synthetic-c", 3), "new", fingerprint="0" * 64)
    found = pairbench.check_pool([a, other, drift])
    assert [(r.code, r.message) for r in found] == [
        (
            "E_POOL_SIDE_DRIFT",
            "the captures synthetic-a and synthetic-b hold different sides",
        ),
        (
            "E_POOL_SIDE_DRIFT",
            "the fingerprint of new differs between the captures synthetic-a and synthetic-c",
        ),
    ]
    assert _shape(found[0]) == _shape(_raised([a, other, drift]))


def test_every_pair_given_twice_is_listed() -> None:
    a = _capture("synthetic-a")
    found = pairbench.check_pool([a, a, a])
    assert [(r.code, r.message) for r in found] == [
        ("E_POOL_SAME", "the capture synthetic-a is given twice"),
    ] * 3


@pytest.mark.parametrize(
    ("given", "message"),
    [
        pytest.param(
            lambda: _capture("synthetic-a"), "check_pool takes a list of captures", id="one"
        ),
        pytest.param(lambda: ["capture.jsonl"], "check_pool takes captures", id="path"),
    ],
)
def test_what_is_no_list_of_captures_is_refused_with_e_usage(
    given: Callable[[], Any], message: str
) -> None:
    with pytest.raises(Refusal) as caught:
        pairbench.check_pool(given())
    assert (caught.value.code, caught.value.exit_code, caught.value.message) == (
        "E_USAGE",
        2,
        message,
    )


def test_a_capture_with_other_sides_is_still_checked_for_its_cases_and_its_machine() -> None:
    a = _capture("synthetic-a")
    other = _other_machine(
        _capture(
            "synthetic-b",
            2,
            subjects=("new", "other"),
            cases=(dataclasses.replace(MATMUL, unit="ms"),),
        )
    )
    found = pairbench.check_pool([a, other])
    assert [(r.code, r.message) for r in found] == [
        ("E_POOL_SIDE_DRIFT", "the captures synthetic-a and synthetic-b hold different sides"),
        (
            "E_POOL_CASES",
            "the cases matmul differ between the captures synthetic-a and synthetic-b",
        ),
        ("E_POOL_MACHINE", "the CPU or GPU identity differs between the pooled captures"),
    ]
    assert _shape(found[0]) == _shape(_raised([a, other]))


def test_an_incomplete_capture_is_refused_by_the_analysis_before_the_later_checks() -> None:
    a = _capture("synthetic-a")
    b = dataclasses.replace(_other_machine(_capture("synthetic-b", 2)), end=None)
    found = pairbench.check_pool([a, b])
    assert [r.code for r in found] == ["E_POOL_MACHINE"]
    raised = _raised([a, b])
    assert (raised.code, raised.message) == (
        "E_CAPTURE_INCOMPLETE",
        "the capture synthetic-b has no end record",
    )
    with pytest.raises(Refusal) as caught:
        analyse_captures((a, b), rule=STRICT, allow_incomplete=True)
    assert _shape(found[0]) == _shape(caught.value)


def test_the_entries_after_the_first_follow_the_order_of_the_captures() -> None:
    a = _capture("synthetic-a")
    other = _capture("synthetic-b", 2, subjects=("new", "other"))
    drift = _sides(_capture("synthetic-c", 3), "new", fingerprint="0" * 64)
    given = [r.message for r in pairbench.check_pool([a, other, drift])]
    swapped = [r.message for r in pairbench.check_pool([a, drift, other])]
    assert sorted(given) == sorted(swapped)
    reversed_ = [r.message for r in pairbench.check_pool([other, a, drift])]
    assert reversed_ == [
        "the captures synthetic-b and synthetic-a hold different sides",
        "the captures synthetic-b and synthetic-c hold different sides",
    ]
