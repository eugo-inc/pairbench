# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pool checks of captures that are runs of one file.

A capture read by a reader that splits a file into runs is one run of that
file: two different runs of one file pool, one run read twice is refused
with ``E_POOL_SAME``, by its path or by the bytes of its file. Captures whose
source names no run are refused by the path or the bytes alone.
"""

from __future__ import annotations

import dataclasses

import pairbench
from pairbench.capture.pool import shared_source
from pairbench.errors import EXIT_ANALYSIS
from pairbench.model import Capture, ReaderInfo, Source
from pairbench.stats.selftest import synthetic_capture

FILE_HASH = "f" * 64
OTHER_HASH = "e" * 64


def _jittered(entry: str, case: str, round_: int, u: float) -> float:
    side = 2.0 if entry.startswith("new") else 1.0
    return side * (1.0 + round_ / 64) * (1.0 + u / 1000)


def _run(
    ident: str,
    seed: int,
    *,
    path: str = "runs.txt",
    sha256: str = FILE_HASH,
    run: int | None = 0,
    reader: str = "text",
) -> Capture:
    info = None if run is None else ReaderInfo(reader=reader, run_index=run)
    capture = synthetic_capture(_jittered, capture_id=ident, seed=seed)
    return dataclasses.replace(capture, source=Source(path=path, sha256=sha256, reader=info))


def _found(captures: list[Capture]) -> list[tuple[str, int, str]]:
    return [(r.code, r.exit_code, r.message) for r in pairbench.check_pool(captures)]


def test_two_runs_of_one_file_pool() -> None:
    first, second = _run("text-a", 1, run=0), _run("text-b", 2, run=1)
    assert _found([first, second]) == []
    assert shared_source(first, second) is None
    assert pairbench.analyse([first, second]).comparisons[0].n_rounds == 32


def test_one_run_read_twice_from_one_file_is_refused() -> None:
    first, second = _run("text-a", 1, run=1), _run("text-b", 2, run=1)
    assert _found([first, second]) == [
        (
            "E_POOL_SAME",
            EXIT_ANALYSIS,
            "the captures text-a and text-b were read from the same file",
        )
    ]
    assert shared_source(first, second) == "file path"


def test_one_run_of_two_files_with_the_same_bytes_is_refused() -> None:
    first = _run("text-a", 1, path="a.txt", run=0)
    second = _run("text-b", 2, path="b.txt", run=0)
    assert _found([first, second]) == [
        (
            "E_POOL_SAME",
            EXIT_ANALYSIS,
            "the captures text-a and text-b were read from files with the same bytes",
        )
    ]
    assert shared_source(first, second) == "file hash"


def test_different_runs_of_two_files_with_the_same_bytes_pool() -> None:
    first = _run("text-a", 1, path="a.txt", run=0)
    second = _run("text-b", 2, path="b.txt", run=1)
    assert _found([first, second]) == []
    assert shared_source(first, second) is None


def test_captures_that_name_no_run_are_refused_by_their_file() -> None:
    first, second = _run("cap-a", 1, run=None), _run("cap-b", 2, run=None)
    assert _found([first, second]) == [
        ("E_POOL_SAME", EXIT_ANALYSIS, "the captures cap-a and cap-b were read from the same file")
    ]
    assert shared_source(first, second) == "file path"


def test_a_run_and_a_capture_that_names_no_run_of_one_file_are_refused() -> None:
    first, second = _run("text-a", 1, run=1), _run("cap-b", 2, run=None)
    assert _found([first, second]) == [
        ("E_POOL_SAME", EXIT_ANALYSIS, "the captures text-a and cap-b were read from the same file")
    ]
    assert shared_source(first, second) == "file path"


def test_runs_of_one_file_read_by_two_readers_are_refused() -> None:
    first = _run("text-a", 1, run=0)
    second = _run("other-b", 2, run=1, reader="made-up-reader")
    assert _found([first, second]) == [
        (
            "E_POOL_SAME",
            EXIT_ANALYSIS,
            "the captures text-a and other-b were read from the same file",
        )
    ]
    assert shared_source(first, second) == "file path"


def test_two_runs_of_one_file_with_identical_rows_are_refused_for_their_rows() -> None:
    first, second = _run("text-a", 1, run=0), _run("text-b", 1, run=1)
    assert _found([first, second]) == [
        (
            "E_POOL_IDENTICAL_ROWS",
            EXIT_ANALYSIS,
            "the captures text-a and text-b hold identical observation rows",
        )
    ]


def test_each_run_given_twice_is_refused_once_per_pair() -> None:
    first, second = _run("text-a", 1, run=0), _run("text-b", 2, run=1)
    assert _found([first, second, first, second]) == [
        ("E_POOL_SAME", EXIT_ANALYSIS, "the capture text-a is given twice"),
        ("E_POOL_SAME", EXIT_ANALYSIS, "the capture text-b is given twice"),
    ]
