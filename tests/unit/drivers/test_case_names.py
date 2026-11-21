# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Benchmark names whose cut drops words, as gbench and nvbench read them.

The two drivers name the names their tool gives before they add ``/cpu_time``.
With the names of the run (``DriverContext.case_names``) a name whose cut
drops words that hold no '/' ends with the run's mark, ' +' and eight hex
digits, and the mark stands before ``/cpu_time``; two names that differ in
such a word get two marks, a skipped name is named with its mark, and a later
read gives each name the same mark. Without the names of a run such a name is
refused. Every folder, word and key here is made up.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import CaseNames, DriverContext
from pairbench.drivers.base import NOTE_CASE_SKIPPED
from pairbench.drivers.gbench import GbenchDriver
from pairbench.drivers.nvbench import NvbenchDriver
from pairbench.errors import EXIT_USAGE, Refusal

MakeCtx = Callable[..., DriverContext]

# A made-up key of 32 bytes.
KEY = bytes(range(32))
GB_FAST = "BM_Read /made/up/in.bin Zqfast x/y"
GB_SLOW = "BM_Read /made/up/in.bin Zqslow x/y"
GB_FAST_ELSEWHERE = "BM_Read /made/up/old/in.bin Zqfast x/y"
# The names KEY gives them.
GB_FAST_NAME = "BM_Read y +5a549880"
GB_SLOW_NAME = "BM_Read y +1d96a24e"
NV_FAST = "Device=0 Path=/made/up/a.bin Zqfast x/y"
NV_SLOW = "Device=0 Path=/made/up/a.bin Zqslow x/y"
NV_FAST_NAME = "bench/Device=0 Path=y +6ea86a25"
NV_SLOW_NAME = "bench/Device=0 Path=y +f76693db"
HIDDEN_WORDS = ("Zqfast", "Zqslow", "made/up")
# Two made-up secrets, and names that differ only in them.
SECRETS = ("zq-made-up-kiwi7", "zq-made-up-pear3")
GB_SECRET = "BM_Read/token={}"
NV_SECRET = "Device=0 token={}"
GB_ADVICE = (
    "give each benchmark a name that differs outside its paths, absolute or climbing with '..', "
    "and outside its secrets"
)
NV_ADVICE = (
    "give each state a name that differs outside its paths, absolute or climbing with '..', "
    "and outside its secrets"
)


def _ctx(make_ctx: MakeCtx, names: CaseNames) -> DriverContext:
    return dataclasses.replace(make_ctx(), case_names=names)


def _gbench(folder: Path, *names: str, skipped: tuple[str, ...] = ()) -> None:
    entries: list[dict[str, Any]] = []
    for name in names:
        entry: dict[str, Any] = {
            "name": name,
            "run_name": name,
            "run_type": "iteration",
            "repetitions": 1,
            "repetition_index": 0,
            "threads": 1,
            "iterations": 10,
            "real_time": 2.0,
            "cpu_time": 1.0,
            "time_unit": "ms",
        }
        if name in skipped:
            entry["error_occurred"] = True
        entries.append(entry)
    (folder / "gbench.json").write_text(json.dumps({"benchmarks": entries}), encoding="utf-8")


def _nvbench(folder: Path, *states: str, skipped: tuple[str, ...] = ()) -> None:
    doc = {
        "benchmarks": [
            {
                "name": "bench",
                "states": [
                    {
                        "name": state,
                        "summaries": [
                            {
                                "tag": "nv/cold/time/gpu/mean",
                                "data": [{"name": "value", "type": "float64", "value": "0.5"}],
                            }
                        ],
                        "is_skipped": state in skipped,
                    }
                    for state in states
                ],
            }
        ]
    }
    (folder / "nvbench.json").write_text(json.dumps(doc), encoding="utf-8")


def _folders(tmp_path: Path) -> tuple[Path, Path]:
    first, later = tmp_path / "1", tmp_path / "2"
    first.mkdir()
    later.mkdir()
    return first, later


def test_gbench_marks_two_names_cut_alike_before_cpu_time(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _gbench(tmp_path, GB_FAST, GB_SLOW)
    samples = GbenchDriver().read(_ctx(make_ctx, CaseNames(KEY)), tmp_path)
    assert [s.case for s in samples] == [
        GB_FAST_NAME,
        f"{GB_FAST_NAME}/cpu_time",
        GB_SLOW_NAME,
        f"{GB_SLOW_NAME}/cpu_time",
    ]


def test_gbench_gives_each_name_the_same_mark_in_a_later_read(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    names = CaseNames(KEY)
    first, later = _folders(tmp_path)
    _gbench(first, GB_FAST)
    # The later read lists another name first and the first one under another folder.
    _gbench(later, GB_SLOW, GB_FAST_ELSEWHERE)
    GbenchDriver().read(_ctx(make_ctx, names), first)
    samples = GbenchDriver().read(_ctx(make_ctx, names), later)
    assert [s.case for s in samples][::2] == [GB_SLOW_NAME, GB_FAST_NAME]


def test_gbench_names_a_skipped_name_with_its_mark(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any
) -> None:
    names = CaseNames(KEY)
    first, later = _folders(tmp_path)
    _gbench(first, GB_FAST, GB_SLOW, skipped=(GB_SLOW,))
    _gbench(later, GB_FAST, GB_SLOW)
    samples = GbenchDriver().read(_ctx(make_ctx, names), first)
    assert [s.case for s in samples] == [GB_FAST_NAME, f"{GB_FAST_NAME}/cpu_time"]
    assert notes.seen == [
        (
            NOTE_CASE_SKIPPED,
            "side 'new': Google Benchmark reported an error or a skip for "
            f"{GB_SLOW_NAME!r}; the case is missing from this launch",
        )
    ]
    samples = GbenchDriver().read(_ctx(make_ctx, names), later)
    assert [s.case for s in samples][::2] == [GB_FAST_NAME, GB_SLOW_NAME]


def test_nvbench_marks_two_states_cut_alike(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _nvbench(tmp_path, NV_FAST, NV_SLOW)
    samples = NvbenchDriver().read(_ctx(make_ctx, CaseNames(KEY)), tmp_path)
    assert [s.case for s in samples] == [NV_FAST_NAME, NV_SLOW_NAME]


def test_nvbench_names_a_skipped_state_with_its_mark(
    make_ctx: MakeCtx, tmp_path: Path, notes: Any
) -> None:
    names = CaseNames(KEY)
    first, later = _folders(tmp_path)
    _nvbench(first, NV_FAST, NV_SLOW, skipped=(NV_FAST,))
    _nvbench(later, NV_SLOW, NV_FAST)
    samples = NvbenchDriver().read(_ctx(make_ctx, names), first)
    assert [s.case for s in samples] == [NV_SLOW_NAME]
    assert notes.seen == [
        (
            NOTE_CASE_SKIPPED,
            f"side 'new': NVBench skipped {NV_FAST_NAME!r}; the case is missing from this launch",
        )
    ]
    samples = NvbenchDriver().read(_ctx(make_ctx, names), later)
    assert [s.case for s in samples] == [NV_SLOW_NAME, NV_FAST_NAME]


@pytest.mark.parametrize(
    ("write", "driver", "raw", "shown", "file", "advice"),
    [
        pytest.param(
            _gbench, GbenchDriver, GB_FAST, "BM_Read y", "gbench.json", GB_ADVICE, id="gb"
        ),
        pytest.param(
            _nvbench,
            NvbenchDriver,
            NV_FAST,
            "bench/Device=0 Path=y",
            "nvbench.json",
            NV_ADVICE,
            id="nv",
        ),
    ],
)
def test_without_the_names_of_a_run_a_name_that_needs_a_mark_is_refused(
    make_ctx: MakeCtx,
    tmp_path: Path,
    write: Callable[..., None],
    driver: Callable[[], Any],
    raw: str,
    shown: str,
    file: str,
    advice: str,
) -> None:
    write(tmp_path, raw)
    with pytest.raises(Refusal) as caught:
        driver().read(make_ctx(), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert caught.value.message == (
        f"{file}: the cut of the case read as {shown!r} drops words that hold no '/', so its "
        "name needs the mark a run makes with its own key, and this read has none; read it in "
        f"a run, or {advice}"
    )
    assert not any(word in caught.value.message for word in HIDDEN_WORDS)


def test_gbench_refuses_two_names_that_differ_only_in_a_hidden_secret(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _gbench(tmp_path, *(GB_SECRET.format(secret) for secret in SECRETS))
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(_ctx(make_ctx, CaseNames(KEY)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert caught.value.message == (
        "gbench.json: two different cases have the name 'BM_Read/token=<hidden>' once absolute "
        "paths and paths that climb with '..' are cut and secrets hidden, as the results show "
        f"it, and differ only in a hidden secret; {GB_ADVICE}"
    )
    assert not any(secret[3:] in caught.value.message for secret in SECRETS)


def test_nvbench_refuses_two_states_that_differ_only_in_a_hidden_secret(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    _nvbench(tmp_path, *(NV_SECRET.format(secret) for secret in SECRETS))
    with pytest.raises(Refusal) as caught:
        NvbenchDriver().read(_ctx(make_ctx, CaseNames(KEY)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert caught.value.message == (
        "nvbench.json: two different cases have the name 'bench/Device=0 token=<hidden>' once "
        "absolute paths and paths that climb with '..' are cut and secrets hidden, as the "
        f"results show it, and differ only in a hidden secret; {NV_ADVICE}"
    )
    assert not any(secret[3:] in caught.value.message for secret in SECRETS)


def test_gbench_refuses_a_name_that_ends_like_a_mark(make_ctx: MakeCtx, tmp_path: Path) -> None:
    _gbench(tmp_path, "BM_Read +1a2b3c4d")
    with pytest.raises(Refusal) as caught:
        GbenchDriver().read(_ctx(make_ctx, CaseNames(KEY)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert caught.value.message == (
        "gbench.json: the case read as 'BM_Read +1a2b3c4d' ends like the mark pairbench adds to "
        "a name whose cut dropped words, ' +' and eight hex digits; give it a name that does not "
        "end so"
    )
