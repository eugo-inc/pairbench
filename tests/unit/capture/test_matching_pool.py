# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pool checks of a read in the matching mode: copies are refused, nothing else is.

The reads here are built from the result types, run by run: each run is the
list of its five-field lines as written, and a line whose round is an integer
and whose value is a number above zero, or NaN, is also one of its kept rows.
Every value is made up.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.capture import matching_pool
from pairbench.capture.matching import MatchingRead, MatchingRow, MatchingRun, PoolRow
from pairbench.capture.text import TextReader
from pairbench.errors import Refusal
from pairbench.model import round_numbers
from pairbench.stats.analyse import _rows

EXIT_ANALYSIS = 6
EXIT_USAGE = 2
IDENTICAL = "E_POOL_IDENTICAL_ROWS"
TRUNCATED = "E_POOL_TRUNCATED_COPY"
DEFAULT_ORDER = "first ran first"


def _value(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isnan(value) or value > 0 else None


def _round(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _read(
    *runs: Sequence[PoolRow], metadata: Sequence[Sequence[tuple[str, str]]] = ()
) -> MatchingRead:
    """Build a read whose run ``k`` holds the five-field lines ``runs[k]``, each after a banner.

    The metadata lines of run ``k``, ``metadata[k]``, sit between its banner and its rows.
    """
    rows: list[MatchingRow] = []
    built: list[MatchingRun] = []
    line = 0
    for index, lines in enumerate(runs):
        line += 1
        banner = line
        written = tuple(metadata[index]) if index < len(metadata) else ()
        metadata_lines = tuple(range(line + 1, line + 1 + len(written)))
        line += len(written)
        numbers: list[int] = []
        kept = malformed = 0
        for suite, side, round_text, case, value_text in lines:
            line += 1
            numbers.append(line)
            round_, value = _round(round_text), _value(value_text)
            if round_ is None or value is None:
                malformed += 1
                continue
            kept += 1
            rows.append(
                MatchingRow(
                    run=index,
                    round=round_,
                    side=side,
                    case=case,
                    value=value,
                    suite=suite,
                    pass_order=DEFAULT_ORDER,
                    order_from_line=False,
                    line=line,
                )
            )
        built.append(
            MatchingRun(
                index=index,
                banner_line=banner,
                metadata=written,
                metadata_lines=metadata_lines,
                malformed_rows=malformed,
                kept_rows=kept,
                pool_rows=tuple(lines),
                pool_row_lines=tuple(numbers),
            )
        )
    return MatchingRead(
        rows=tuple(rows), runs=tuple(built), default_order=DEFAULT_ORDER, sha256="0" * 64
    )


def _r(side: str, round_: str, case: str, value: str, suite: str = "s") -> PoolRow:
    return (suite, side, round_, case, value)


# A run of two rounds of one case, and its rows one by one.
X0 = _r("new", "1", "c1", "110")
X1 = _r("old", "1", "c1", "100")
X2 = _r("new", "2", "c1", "111")
X3 = _r("old", "2", "c1", "101")
X = [X0, X1, X2, X3]
# X stopped inside the value of its third row.
CUT_X = [X0, X1, _r("new", "2", "c1", "11")]
# A line of four tabs: five empty fields.
BLANK: PoolRow = ("", "", "", "", "")


def _check(read: Any) -> list[Refusal]:
    found: list[Refusal] = pairbench.check_matching_pool(read)
    return found


def _first(read: MatchingRead) -> Refusal | None:
    try:
        pairbench.refuse_matching_pool(read)
    except Refusal as refusal:
        return refusal
    return None


def _shown(refusals: Sequence[Refusal]) -> list[tuple[str, int, dict[str, Any]]]:
    return [(r.code, r.exit_code, r.detail) for r in refusals]


def _stretch(
    copy: int,
    original: int,
    copy_rows: int,
    original_rows: int,
    start: int,
    torn: bool,
) -> tuple[str, int, dict[str, Any]]:
    return (
        TRUNCATED,
        EXIT_ANALYSIS,
        {
            "check": "written_stretch",
            "copy_run": copy,
            "original_run": original,
            "copy_rows": copy_rows,
            "original_rows": original_rows,
            "start_row": start,
            "last_row": start + copy_rows - 1,
            "torn": torn,
            "rows_matched": copy_rows - 1,
        },
    )


def _same_written(earlier: int, later: int, rows: int) -> tuple[str, int, dict[str, Any]]:
    return (
        IDENTICAL,
        EXIT_ANALYSIS,
        {"check": "identical_written_rows", "runs": [earlier, later], "rows": rows},
    )


def _same_kept(first: int, second: int) -> tuple[str, int, dict[str, Any]]:
    return (IDENTICAL, EXIT_ANALYSIS, {"check": "identical_rows", "runs": [first, second]})


def _copy_kept(first: int, second: int) -> tuple[str, int, dict[str, Any]]:
    return (TRUNCATED, EXIT_ANALYSIS, {"check": "truncated_copy", "runs": [first, second]})


def _same_part(
    first: int, second: int, first_line: int, second_line: int
) -> tuple[str, int, dict[str, Any]]:
    detail = {
        "check": "identical_rows",
        "runs": [first, second],
        "lines": [first_line, second_line],
    }
    return (IDENTICAL, EXIT_ANALYSIS, detail)


def _answer(read: MatchingRead) -> tuple[str, int, dict[str, Any]] | None:
    first = _first(read)
    every = _check(read)
    if first is None:
        assert every == []
        return None
    assert every, "the raised refusal is the first of the list"
    assert (first.code, first.exit_code, first.scope, first.message, first.detail) == (
        every[0].code,
        every[0].exit_code,
        every[0].scope,
        every[0].message,
        every[0].detail,
    )
    return (first.code, first.exit_code, first.detail)


# ---------------------------------------------------------------------------
# Nothing but a copy is refused
# ---------------------------------------------------------------------------


def test_runs_that_differ_in_cases_sides_units_and_case_marks_pool() -> None:
    read = _read(
        [X0, X1],
        [_r("new", "1", "c2", "210"), _r("old", "1", "c2", "200")],
        [_r("mid", "1", "c1", "310")],
        [_r("neu", "1", "c1", "410"), _r("old", "1", "c1", "400")],
        [_r("new", "1", "t +1a2b3c4d", "510"), _r("old", "1", "t +1a2b3c4d", "500")],
        metadata=[[("unit", "ms")]],
    )
    assert _check(read) == []
    assert _answer(read) is None


def test_runs_with_no_row_pool_and_one_run_alone_pools() -> None:
    assert _answer(_read([], [], [])) is None
    assert _answer(_read(X)) is None


def test_runs_whose_lines_all_are_malformed_and_differ_pool() -> None:
    read = _read([_r("new", "x", "c1", "110")], [_r("new", "y", "c1", "110")])
    assert read.kept_rows == 0
    assert _answer(read) is None


def test_two_runs_without_kept_rows_are_not_identical_rows() -> None:
    read = _read([_r("new", "1", "c1", "abc")], [_r("new", "1", "c1", "-5")])
    assert _answer(read) is None


def test_an_argument_that_is_not_a_read_is_refused_as_usage() -> None:
    with pytest.raises(Refusal) as caught:
        _check([X])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    with pytest.raises(Refusal) as caught:
        pairbench.refuse_matching_pool(None)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


# ---------------------------------------------------------------------------
# The copy checks of the analysis, over the kept rows
# ---------------------------------------------------------------------------


def test_runs_that_differ_only_in_suite_are_identical_rows() -> None:
    read = _read([X0, X1], [_r("new", "1", "c1", "110", "t"), _r("old", "1", "c1", "100", "t")])
    assert _shown(_check(read)) == [_same_kept(0, 1)]
    assert _answer(read) == _same_kept(0, 1)


def test_a_copy_with_its_rounds_relabelled_is_identical_rows() -> None:
    relabelled = [
        _r("new", "5", "c1", "110"),
        _r("old", "5", "c1", "100"),
        _r("new", "6", "c1", "111"),
        _r("old", "6", "c1", "101"),
    ]
    read = _read(X, relabelled)
    assert _shown(_check(read)) == [_same_kept(0, 1)]


def test_a_copy_with_a_value_written_another_way_is_identical_rows() -> None:
    read = _read([X1, X0], [_r("old", "1", "c1", "1e2"), X0])
    assert _shown(_check(read)) == [_same_kept(0, 1)]


def test_a_relabelled_stretch_is_a_truncated_copy() -> None:
    read = _read(X, [_r("new", "7", "c1", "110"), _r("old", "7", "c1", "100")])
    assert _shown(_check(read)) == [_copy_kept(0, 1)]
    assert _answer(read) == _copy_kept(0, 1)


def test_a_four_tab_line_counts_in_the_written_rows_only() -> None:
    with_blank = [X0, X1, BLANK, X2, X3]
    read = _read(with_blank, X)
    assert read.runs[0].kept_rows == read.runs[1].kept_rows == 4
    assert _shown(_check(read)) == [_same_kept(0, 1)]
    assert _shown(_check(_read(with_blank, with_blank))) == [
        _same_written(0, 1, 5),
        _same_kept(0, 1),
    ]


# ---------------------------------------------------------------------------
# Identical written rows
# ---------------------------------------------------------------------------


def test_a_run_given_twice_is_identical_written_rows() -> None:
    read = _read(X, X)
    assert _answer(read) == _same_written(0, 1, 4)
    assert _shown(_check(read)) == [_same_written(0, 1, 4), _same_kept(0, 1)]


def test_identical_runs_are_found_before_a_cut_short_copy_between_them() -> None:
    read = _read(X, CUT_X, X)
    assert _answer(read) == _same_written(0, 2, 4)
    assert _shown(_check(read)) == [
        _same_written(0, 2, 4),
        _stretch(1, 0, 3, 4, 0, True),
        _stretch(1, 2, 3, 4, 0, True),
        _copy_kept(0, 1),
        _same_kept(0, 2),
        _copy_kept(1, 2),
    ]


def test_a_run_without_rows_keeps_its_index() -> None:
    assert _answer(_read([], X, X)) == _same_written(1, 2, 4)
    assert _answer(_read(X, [], X)) == _same_written(0, 2, 4)


def test_each_repeat_is_paired_with_the_earliest_run_that_holds_its_rows() -> None:
    other = [_r("new", "1", "c1", "910"), _r("old", "1", "c1", "900")]
    read = _read(other, X, X, other, X)
    found = [r.detail for r in _check(read) if r.detail["check"] == "identical_written_rows"]
    assert found == [
        {"check": "identical_written_rows", "runs": [1, 2], "rows": 4},
        {"check": "identical_written_rows", "runs": [0, 3], "rows": 2},
        {"check": "identical_written_rows", "runs": [1, 4], "rows": 4},
    ]


# ---------------------------------------------------------------------------
# A written stretch, its last row whole or torn
# ---------------------------------------------------------------------------


def test_a_two_row_run_whose_second_row_differs_is_torn() -> None:
    read = _read(X, [X1, _r("new", "2", "c1", "999")])
    assert _answer(read) == _stretch(1, 0, 2, 4, 1, True)
    assert _shown(_check(read)) == [_stretch(1, 0, 2, 4, 1, True), _copy_kept(0, 1)]


@pytest.mark.parametrize(
    "torn_row",
    [
        _r("new", "2", "c1", "111", "t"),
        _r("mid", "2", "c1", "111"),
        _r("new", "2", "c2", "111"),
        _r("new", "9", "c1", "111"),
        _r("new", "2", "c1", "abc"),
    ],
    ids=["suite", "side", "case", "round", "malformed"],
)
def test_a_last_row_that_differs_in_any_field_is_torn(torn_row: PoolRow) -> None:
    assert _answer(_read(X, [X1, torn_row])) == _stretch(1, 0, 2, 4, 1, True)


def test_a_two_row_run_whose_first_row_is_the_last_row_of_the_other_is_no_stretch() -> None:
    assert _answer(_read(X, [X3, _r("new", "3", "c1", "5")])) is None


def test_a_two_row_run_whose_second_row_follows_is_a_whole_stretch() -> None:
    read = _read(X, [X1, X2])
    assert _answer(read) == _stretch(1, 0, 2, 4, 1, False)


def test_two_equal_two_row_runs_are_identical_written_rows() -> None:
    assert _answer(_read([X0, X1], [X0, X1])) == _same_written(0, 1, 2)


def test_runs_of_one_length_that_differ_in_the_last_row_are_listed_once() -> None:
    read = _read([X0, X1], [X0, _r("old", "1", "c1", "99")])
    assert _answer(read) == _stretch(1, 0, 2, 2, 0, True)
    stretches = [r for r in _check(read) if r.detail["check"] == "written_stretch"]
    assert len(stretches) == 1


def test_a_one_row_run_is_a_whole_stretch_and_never_torn() -> None:
    assert _answer(_read(X, [X2])) == _stretch(1, 0, 1, 4, 2, False)
    assert _answer(_read(X, [_r("new", "2", "c1", "5")])) is None


def test_the_first_start_row_wins_even_when_torn() -> None:
    a, b, c = X0, X1, _r("old", "1", "c1", "120")
    assert _answer(_read([a, b, a, c], [a, c])) == _stretch(1, 0, 2, 4, 0, True)


def test_a_malformed_five_field_row_above_the_stretch_moves_every_index_by_one() -> None:
    copy = [X0, _r("old", "1", "c1", "99")]
    assert _answer(_read(X, copy)) == _stretch(1, 0, 2, 4, 0, True)
    malformed = _r("new", "1", "c1", "abc")
    assert _answer(_read([malformed, *X], copy)) == _stretch(1, 0, 2, 5, 1, True)
    assert _answer(_read([BLANK, *X], copy)) == _stretch(1, 0, 2, 5, 1, True)


def test_the_original_is_scanned_in_run_order_before_the_copy() -> None:
    a = [_r("new", "1", "a", "11"), _r("new", "2", "a", "12"), _r("new", "3", "a", "13")]
    b = [_r("new", "1", "b", "21"), _r("new", "2", "b", "22"), _r("new", "3", "b", "23")]
    read = _read(b[:2], a, a[1:], b)
    assert _answer(read) == _stretch(2, 1, 2, 3, 1, False)


def test_a_stretch_is_found_before_the_copy_checks_of_the_kept_rows() -> None:
    read = _read(X, CUT_X)
    assert _shown(_check(read)) == [_stretch(1, 0, 3, 4, 0, True), _copy_kept(0, 1)]


# ---------------------------------------------------------------------------
# From texts read in the matching mode
# ---------------------------------------------------------------------------


def _text(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _from(*texts: str) -> MatchingRead:
    read: MatchingRead = pairbench.read_text_matching(list(texts), default_order=DEFAULT_ORDER)
    return read


RUN = _text("## host", "pass_order=new old", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100")


def test_two_texts_with_the_same_bytes_are_identical_written_rows() -> None:
    read = _from(RUN, RUN)
    assert _shown(_check(read)) == [_same_written(0, 1, 2), _same_kept(0, 1)]


def test_one_text_that_holds_a_run_twice_is_identical_written_rows() -> None:
    assert _answer(_from(RUN + RUN)) == _same_written(0, 1, 2)


def test_two_texts_with_the_same_bytes_and_no_row_pool() -> None:
    only_metadata = _text("## host", "unit=ms", "x=1")
    assert _answer(_from(only_metadata, only_metadata)) is None
    assert _answer(_from("")) is None


def test_runs_of_texts_that_differ_in_all_but_copies_pool() -> None:
    read = _from(
        RUN,
        _text("## host", "unit=ms", "s\tnew\t1\tc2\t210", "s\told\t1\tc2\t200"),
        _text("## host", "s\tmid\t1\tc1\t310"),
        _text("## host", "s\tneu\t1\tt +1a2b3c4d\t410", "s\told\t1\tt +1a2b3c4d\t400"),
    )
    assert read.run_count == 4
    assert _answer(read) is None


def test_a_run_of_another_suite_from_a_text_is_identical_rows() -> None:
    other = _text("## host", "pass_order=new old", "t\tnew\t1\tc1\t110", "t\told\t1\tc1\t100")
    assert _shown(_check(_from(RUN, other))) == [_same_kept(0, 1)]


def test_runs_that_differ_only_in_spaces_around_their_fields_are_identical_written_rows() -> None:
    spaced = _text(
        "## host", "pass_order=new old", " s \t new \t 1 \t c1 \t 110 ", "s\told\t 1\tc1\t100 "
    )
    assert _answer(_from(RUN, spaced)) == _same_written(0, 1, 2)


def test_a_banner_of_five_fields_is_no_written_row() -> None:
    banner = _text(
        "## host\ta\tb\tc\td", "pass_order=new old", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"
    )
    assert _answer(_from(RUN, banner)) == _same_written(0, 1, 2)


def test_a_comment_and_a_four_tab_line_from_a_text_are_written_rows() -> None:
    commented = _text(
        "## host", "# note\ta\tb\tc\td", "s\tnew\t1\tc1\t110", "\t\t\t\t", "s\told\t1\tc1\t100"
    )
    read = _from(RUN, commented)
    assert read.runs[1].pool_rows[0] == ("# note", "a", "b", "c", "d")
    assert read.runs[1].pool_rows[2] == BLANK
    # The comment is row 0, so the first row of run 0 sits at row 1; the line of four
    # tabs is row 2, where the second row of run 0 falls, which makes that row torn.
    assert _shown(_check(read)) == [_stretch(0, 1, 2, 4, 1, True), _same_kept(0, 1)]


def test_a_malformed_row_from_a_text_moves_every_index_by_one() -> None:
    long = _text(
        "## host",
        "s\tnew\t1\tc1\tabc",
        "s\tnew\t1\tc1\t110",
        "s\told\t1\tc1\t100",
        "s\tnew\t2\tc1\t111",
        "s\told\t2\tc1\t101",
    )
    cut = _text("## host", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t10")
    assert _answer(_from(long, cut)) == _stretch(1, 0, 2, 5, 1, True)


def test_a_torn_row_that_repeats_a_cell_is_refused_by_the_written_stretch_alone() -> None:
    copy = _text("## host", "s\tnew\t1\tc1\t110", "s\tnew\t1\tc1\t100")
    read = _from(_text("## host", *("\t".join(row) for row in X)), copy)
    assert read.runs[1].kept_rows == 2
    assert _shown(_check(read)) == [_stretch(1, 0, 2, 4, 0, True)]


def test_files_are_compared_by_their_runs(tmp_path: Path) -> None:
    one = tmp_path / "one.txt"
    one.write_text(RUN, encoding="utf-8")
    assert _answer(_from_paths(one, one)) == _same_written(0, 1, 2)
    two = tmp_path / "two.txt"
    two.write_text(
        RUN + _text("## host", "s\tnew\t2\tc1\t120", "s\told\t2\tc1\t130"), encoding="utf-8"
    )
    assert _answer(_from_paths(two)) is None


def test_one_file_without_a_banner_given_twice_is_one_run_and_is_refused(tmp_path: Path) -> None:
    rows = tmp_path / "rows.txt"
    rows.write_text(_text("s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"), encoding="utf-8")
    read = _from_paths(rows, rows)
    assert (read.run_count, read.kept_rows) == (1, 4)
    assert _answer(read) == _same_part(0, 0, 1, 4)


def _from_paths(*paths: Path) -> MatchingRead:
    read: MatchingRead = pairbench.read_text_matching(list(paths), default_order=DEFAULT_ORDER)
    return read


# ---------------------------------------------------------------------------
# NaN values in the copy checks of the kept rows
# ---------------------------------------------------------------------------

# A run whose first row holds NaN. The NaN sits above the last row: without the rule that
# two NaN values are equal, the torn-row check would still take a copy whose last row holds
# NaN for a torn copy, so only a NaN above the last row tests the rule.
NAN_RUN = _text("## host", "pass_order=new old", "s\tnew\t1\tc1\tnan", "s\told\t1\tc1\t100")


def test_a_copy_with_nan_that_differs_only_in_suite_is_identical_rows() -> None:
    other = _text("## host", "pass_order=new old", "t\tnew\t1\tc1\tnan", "t\told\t1\tc1\t100")
    assert _shown(_check(_from(NAN_RUN, other))) == [_same_kept(0, 1)]


def test_a_copy_with_nan_and_its_rounds_relabelled_is_identical_rows() -> None:
    other = _text("## host", "pass_order=new old", "s\tnew\t5\tc1\tnan", "s\told\t5\tc1\t100")
    assert _shown(_check(_from(NAN_RUN, other))) == [_same_kept(0, 1)]


@pytest.mark.parametrize("spelling", ["NaN", "-nan", "NAN"])
def test_a_copy_with_nan_written_another_way_is_identical_rows(spelling: str) -> None:
    other = _text(
        "## host", "pass_order=new old", f"s\tnew\t1\tc1\t{spelling}", "s\told\t1\tc1\t100"
    )
    assert _shown(_check(_from(NAN_RUN, other))) == [_same_kept(0, 1)]


def test_a_one_row_copy_of_a_nan_row_in_another_suite_is_a_truncated_copy() -> None:
    cut = _text("## host", "t\tnew\t1\tc1\tnan")
    assert _shown(_check(_from(NAN_RUN, cut))) == [_copy_kept(0, 1)]


def test_a_nan_row_against_a_number_is_a_copy_as_for_text_captures(tmp_path: Path) -> None:
    # A text capture leaves the NaN row out, so the rest of the run is a stretch of the other.
    other = _text("## host", "pass_order=new old", "t\tnew\t1\tc1\t110", "t\told\t1\tc1\t100")

    assert _text_pool(tmp_path, NAN_RUN, other)[0] == TRUNCATED
    assert _answer(_from(NAN_RUN, other)) == _copy_kept(0, 1)


# Two rounds that alternate their order; the copies below differ from it in one value that
# is not finite, which a text capture leaves out.
TWO_ROUNDS = _text(
    "## host",
    "pass_order=new old",
    "s\tnew\t1\tc\t90",
    "s\told\t1\tc\t100",
    "pass_order=old new",
    "s\told\t2\tc\t101",
    "s\tnew\t2\tc\t91",
)


@pytest.mark.parametrize(
    ("copy", "code", "found"),
    [
        pytest.param(
            TWO_ROUNDS.replace("\t90\n", "\tnan\n"), TRUNCATED, _copy_kept(0, 1), id="first-nan"
        ),
        pytest.param(
            TWO_ROUNDS.replace("\t90\n", "\tinf\n"), TRUNCATED, _copy_kept(0, 1), id="first-inf"
        ),
        pytest.param(
            TWO_ROUNDS.replace("\t100\n", "\t100\ns\tnew\t1\tc\tinf\n"),
            IDENTICAL,
            _same_kept(0, 1),
            id="inserted-inf",
        ),
    ],
)
def test_a_copy_that_differs_only_by_a_value_that_is_not_finite_stays_refused(
    tmp_path: Path, copy: str, code: str, found: tuple[str, int, dict[str, Any]]
) -> None:
    assert _text_pool(tmp_path, TWO_ROUNDS, copy) == [code]
    assert _answer(_from(TWO_ROUNDS, copy)) == found


# ---------------------------------------------------------------------------
# The kept rows in the order of the text, and in the order the rows ran
# ---------------------------------------------------------------------------

ROWS_RAN = _text(
    "## host",
    "pass_order=new old",
    "s\tnew\t1\tc1\t110",
    "s\told\t1\tc1\t100",
    "s\tnew\t2\tc1\t111",
    "s\told\t2\tc1\t101",
)


def test_a_copy_with_the_rows_of_each_round_swapped_is_identical_rows() -> None:
    swapped = _text(
        "## host",
        "pass_order=new old",
        "s\told\t1\tc1\t100",
        "s\tnew\t1\tc1\t110",
        "s\told\t2\tc1\t101",
        "s\tnew\t2\tc1\t111",
    )
    assert _shown(_check(_from(ROWS_RAN, swapped))) == [_same_kept(0, 1)]


def test_a_copy_whose_reversed_pass_is_written_in_another_order_is_identical_rows() -> None:
    def run(*second_round: str) -> list[str]:
        return [
            "## host",
            "pass_order=new old",
            "s\tnew\t1\tc1\t110",
            "s\told\t1\tc1\t100",
            "pass_order=old new",
            *second_round,
        ]

    text = _text(
        *run("s\told\t2\tc1\t101", "s\tnew\t2\tc1\t111"),
        *run("s\tnew\t2\tc1\t111", "s\told\t2\tc1\t101"),
    )
    read = _from(text)
    assert _shown(_check(read)) == [_same_kept(0, 1)]
    first = _first(read)
    assert first is not None
    assert _shown([first]) == [_same_kept(0, 1)]


def test_a_copy_with_its_rounds_written_in_another_order_is_identical_rows() -> None:
    later_first = _text(
        "## host",
        "pass_order=new old",
        "s\tnew\t2\tc1\t111",
        "s\told\t2\tc1\t101",
        "s\tnew\t1\tc1\t110",
        "s\told\t1\tc1\t100",
    )
    assert _shown(_check(_from(ROWS_RAN, later_first))) == [_same_kept(0, 1)]


def test_a_cut_copy_of_rows_written_against_their_order_is_still_a_truncated_copy() -> None:
    # In the order the rows ran the copy is no stretch; in the order of the text it is.
    against = _text(
        "## host",
        "pass_order=new old",
        "s\told\t1\tc1\t100",
        "s\tnew\t1\tc1\t110",
        "s\told\t2\tc1\t101",
        "s\tnew\t2\tc1\t111",
    )
    cut = _text(
        "## host",
        "pass_order=new old",
        "t\told\t1\tc1\t100",
        "t\tnew\t1\tc1\t110",
        "t\told\t2\tc1\t101",
    )
    assert _shown(_check(_from(against, cut))) == [_copy_kept(0, 1)]


def test_a_swapped_copy_without_a_line_that_fixes_the_order_of_its_sides_pools() -> None:
    unordered = _text(
        "## host",
        "s\tnew\t1\tc1\t110",
        "s\told\t1\tc1\t100",
        "s\tnew\t2\tc1\t111",
        "s\told\t2\tc1\t101",
    )
    swapped = _text(
        "## host",
        "s\told\t1\tc1\t100",
        "s\tnew\t1\tc1\t110",
        "s\told\t2\tc1\t101",
        "s\tnew\t2\tc1\t111",
    )
    assert _answer(_from(unordered, swapped)) is None


def _swapped(head: str) -> tuple[str, str]:
    """A run of two rounds below ``head``, and its copy with the rows of each round swapped."""
    ran = _text("## host", head, X_ROWS[0], X_ROWS[1], X_ROWS[2], X_ROWS[3])
    swapped = _text("## host", head, X_ROWS[1], X_ROWS[0], X_ROWS[3], X_ROWS[2])
    return ran, swapped


X_ROWS = ["s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100", "s\tnew\t2\tc1\t111", "s\told\t2\tc1\t101"]


def _swapped_rows() -> list[str]:
    """The rows of ``X_ROWS`` with the two rows of each round written the other way."""
    return [X_ROWS[1], X_ROWS[0], X_ROWS[3], X_ROWS[2]]


def _text_pool(tmp_path: Path, *texts: str) -> list[str]:
    """The text codes ``check_pool`` gives for the runs of ``texts`` read as text captures."""
    captures = []
    for k, written in enumerate(texts):
        path = tmp_path / f"{k}.txt"
        path.write_text(written, encoding="utf-8")
        captures += pairbench.load_capture(path)
    return [refusal.code for refusal in pairbench.check_pool(captures)]


@pytest.mark.parametrize("head", [" pass_order = new old", "pass_order =new old"])
def test_a_swapped_copy_under_a_pass_order_the_text_reader_trims_is_identical_rows(
    head: str, tmp_path: Path
) -> None:
    # The matching mode reads such a line as metadata that sets no order; the text
    # reader trims its key, and the order of the rows a text capture holds follows it.
    ran, swapped = _swapped(head)
    read = pairbench.read_text_matching([ran, swapped], default_order=DEFAULT_ORDER)

    assert [row.order_from_line for row in read.rows] == [False] * 8
    assert _text_pool(tmp_path, ran, swapped) == [IDENTICAL]
    assert _answer(read) == _same_kept(0, 1)


def _refusals_in_full(read: MatchingRead) -> list[tuple[str, int, str, dict[str, Any]]]:
    return [(r.code, r.exit_code, r.message, r.detail) for r in _check(read)]


@pytest.mark.parametrize(
    ("head", "without_the_tab"),
    [
        ("\tpass_order=new old", "pass_order=new old"),
        ("pass_order=new old\t", "pass_order=new old"),
        ("\tsides=new old", "sides=new old"),
        ("sides=new old\t", "sides=new old"),
    ],
)
def test_a_swapped_copy_under_a_line_with_a_tab_at_an_end_is_refused_as_without_the_tab(
    head: str, without_the_tab: str, tmp_path: Path
) -> None:
    # The matching mode strips such a line and reads it as metadata, and the order the
    # rows ran follows it as it follows the same line without the tab. The text reader
    # reads such a line as a malformed row, so text captures of the two runs pool.
    ran, swapped = _swapped(head)
    read = pairbench.read_text_matching([ran, swapped], default_order=DEFAULT_ORDER)
    plain = pairbench.read_text_matching(
        list(_swapped(without_the_tab)), default_order=DEFAULT_ORDER
    )

    assert _text_pool(tmp_path, ran, swapped) == []
    assert _shown(_check(read)) == [_same_kept(0, 1)]
    assert _answer(read) == _same_kept(0, 1)
    assert _refusals_in_full(read) == _refusals_in_full(plain)


@pytest.mark.parametrize("head", ["\tpass_order=new old", "pass_order=new old\t"])
def test_a_pass_order_with_a_tab_at_an_end_orders_the_rows_of_the_read(head: str) -> None:
    read = pairbench.read_text_matching(list(_swapped(head)), default_order=DEFAULT_ORDER)

    assert {row.pass_order for row in read.rows} == {"new old"}
    assert all(row.order_from_line for row in read.rows)


# Runs in which a line with a tab at either end, read as metadata in the matching mode,
# undoes the order an earlier line gives the sides, and the copy of each with the rows of
# every round swapped: a sides= line that differs from the run's other one, an empty
# pass-order line, and a pass-order line that gives a side a second position in a round.
# The text reader reads such a line as a malformed row, and text captures of the two runs
# are identical rows in the order they hold them.
_SWAP_ROUND_1 = ["s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"]
_SWAP_ROUND_1_C2 = ["s\tnew\t1\tc2\t210", "s\told\t1\tc2\t200"]
UNDONE_BY_A_TAB_EDGED_LINE = [
    (
        _text("## host", "sides=new old", "\tsides=old new", *X_ROWS),
        _text("## host", "sides=new old", "\tsides=old new", *_swapped_rows()),
    ),
    (
        _text("## host", "pass_order=new old", "\tpass_order=", *X_ROWS),
        _text("## host", "pass_order=new old", "\tpass_order=", *_swapped_rows()),
    ),
    (
        _text(
            "## host",
            "pass_order=new old",
            *_SWAP_ROUND_1,
            "\tpass_order=old new",
            *_SWAP_ROUND_1_C2,
        ),
        _text(
            "## host",
            "pass_order=new old",
            *_SWAP_ROUND_1[::-1],
            "\tpass_order=old new",
            *_SWAP_ROUND_1_C2[::-1],
        ),
    ),
]


@pytest.mark.parametrize(
    ("ran", "swapped"),
    UNDONE_BY_A_TAB_EDGED_LINE,
    ids=["sides_that_differ", "empty_pass_order", "second_position"],
)
def test_a_copy_that_text_captures_refuse_is_refused_whatever_a_tab_edged_line_says(
    ran: str, swapped: str, tmp_path: Path
) -> None:
    read = pairbench.read_text_matching([ran, swapped], default_order=DEFAULT_ORDER)

    assert _text_pool(tmp_path, ran, swapped) == [IDENTICAL]
    assert _shown(_check(read)) == [_same_kept(0, 1)]
    assert _answer(read) == _same_kept(0, 1)


def test_the_kept_rows_of_each_pair_are_compared_in_every_order_before_the_next_pair(
    tmp_path: Path,
) -> None:
    # Run 1 is run 0 with each round written the other way; run 2 is run 0 in another
    # suite. The pair (0, 2) is a copy in the order of the text, the pair (0, 1) only in
    # the order the rows ran, and the pair (0, 1) comes first, as for text captures.
    ran, swapped = _swapped("pass_order=new old")
    other = ran.replace("s\t", "t\t")
    texts = (ran, swapped, other)
    captures = []
    for k, written in enumerate(texts):
        path = tmp_path / f"{k}.txt"
        path.write_text(written, encoding="utf-8")
        captures += pairbench.load_capture(path)
    named = [refusal.detail["captures"] for refusal in pairbench.check_pool(captures)]
    order = {capture.capture_id: k for k, capture in enumerate(captures)}

    read = _from(*texts)

    assert [[order[c] for c in pair] for pair in named] == [[0, 1], [0, 2], [1, 2]]
    assert _shown(_check(read)) == [_same_kept(0, 1), _same_kept(0, 2), _same_kept(1, 2)]
    assert _answer(read) == _same_kept(0, 1)


def test_a_pair_found_in_the_order_of_the_text_is_not_listed_again() -> None:
    other = ROWS_RAN.replace("s\t", "t\t")
    assert _shown(_check(_from(ROWS_RAN, other))) == [_same_kept(0, 1)]


# Runs the strict reader also reads: a pass order that names sides the run does not hold,
# so that a position passes the size of the lineup; a round whose rows give a side two
# positions; a sides= line; and a twin.
ORDER_TEXTS = [
    _text(
        "## host",
        "pass_order=a b c new old",
        "s\tmid\t1\tc1\t310",
        "s\told\t1\tc1\t100",
        "s\tnew\t1\tc1\t110",
        "s\tnew\t2\tc1\t111",
        "s\tmid\t2\tc1\t311",
        "s\told\t2\tc1\t101",
    ),
    _text(
        "## host",
        "pass_order=old new",
        "s\tnew\t1\tc1\t110",
        "s\told\t1\tc1\t100",
        "pass_order=new old",
        "s\told\t1\tc2\t200",
        "s\tnew\t1\tc2\t210",
        "s\told\t2\tc1\t101",
        "s\tnew\t2\tc1\t111",
    ),
    _text(
        "## host",
        "sides=old new",
        "s\tnew\t3\tc1\t112",
        "s\told\t3\tc1\t102",
        "s\tnew\t1\tc1\t110",
        "s\told\t1\tc1\t100",
    ),
    _text(
        "## host",
        "twin=again:new",
        "s\told\t1\tc1\t100",
        "s\tagain\t1\tc1\t109",
        "s\tnew\t1\tc1\t110",
        "pass_order=again old new",
        "s\tnew\t2\tc1\t111",
        "s\told\t2\tc1\t101",
        "s\tagain\t2\tc1\t108",
    ),
]


# A line the text reader reads otherwise than the matching mode: a pass-order line with
# spaces around its key orders the rows of a text capture, and the rows in the order they
# ran, though it sets no order on the rows of the read.
SPACED_KEY_LINES = [
    _text(
        "## host",
        "pass_order=old new",
        " pass_order = new old",
        "s\told\t1\tc1\t100",
        "s\tnew\t1\tc1\t110",
        "pass_order =old new",
        "s\tnew\t2\tc1\t111",
        "s\told\t2\tc1\t101",
    ),
]


# Lines with a tab at either end, which the matching mode strips and reads as metadata and
# the text reader reads as malformed rows, and the order the rows ran under them: round,
# side, case and value. Each line orders the rows as the same line without the tab does.
TAB_EDGED_LINES = [
    (
        _text(
            "## host",
            "pass_order=new old",
            "\tpass_order=old new",
            "s\tnew\t1\tc1\t110",
            "s\told\t1\tc1\t100",
            "pass_order=old new\t",
            "s\tnew\t2\tc1\t111",
            "s\told\t2\tc1\t101",
        ),
        [
            (1, "old", "c1", 100),
            (1, "new", "c1", 110),
            (2, "old", "c1", 101),
            (2, "new", "c1", 111),
        ],
    ),
    (
        _text(
            "## host",
            "\tsides=old new",
            "s\tnew\t1\tc1\t110",
            "s\told\t1\tc1\t100",
            "sides=old new\t",
            "s\told\t2\tc1\t101",
            "s\tnew\t2\tc1\t111",
        ),
        [
            (1, "old", "c1", 100),
            (1, "new", "c1", 110),
            (2, "old", "c1", 101),
            (2, "new", "c1", 111),
        ],
    ),
    (
        _text(
            "## host",
            "twin=again:new\t",
            "s\tagain\t1\tc1\t109",
            "s\told\t1\tc1\t100",
            "s\tnew\t1\tc1\t110",
        ),
        [(1, "old", "c1", 100), (1, "new", "c1", 110), (1, "again", "c1", 109)],
    ),
]


# Runs whose rows no pass-order line orders, read with a default order that names their
# sides: the default order gives no position, as a text capture of them has none.
DEFAULT_ORDER_TEXTS = [
    _text("## host", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"),
    _text("## host", "pass_order=", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"),
]


@pytest.mark.parametrize(
    ("text", "default_order"),
    [
        *((text, DEFAULT_ORDER) for text in ORDER_TEXTS),
        *((text, "old new") for text in DEFAULT_ORDER_TEXTS),
        *((text, DEFAULT_ORDER) for text in SPACED_KEY_LINES),
    ],
    ids=[
        "extra_sides",
        "two_positions",
        "sides_line",
        "twin",
        "no_line",
        "empty_line",
        "spaced_key",
    ],
)
def test_the_order_the_rows_ran_is_the_order_of_the_rows_of_a_text_capture(
    text: str, default_order: str, tmp_path: Path
) -> None:
    path = tmp_path / "run.txt"
    path.write_text(text, encoding="utf-8")
    (capture,) = TextReader().read(path, strict=False)
    read = pairbench.read_text_matching(text, default_order=default_order)
    ((index, ran),) = matching_pool._in_the_order_they_ran(read)
    numbers = round_numbers(row[0] for row in ran)
    assert index == 0
    assert [(numbers[r], side, case, value) for r, side, case, value in ran] == list(_rows(capture))


@pytest.mark.parametrize(
    "text",
    [*ORDER_TEXTS, *SPACED_KEY_LINES, *(text for text, _ran in TAB_EDGED_LINES)],
    ids=[
        "extra_sides",
        "two_positions",
        "sides_line",
        "twin",
        "spaced_key",
        "tab_at_an_end",
        "sides_with_a_tab",
        "twin_with_a_tab",
    ],
)
def test_the_order_a_text_capture_holds_is_the_order_of_the_rows_of_a_text_capture(
    text: str, tmp_path: Path
) -> None:
    path = tmp_path / "run.txt"
    path.write_text(text, encoding="utf-8")
    (capture,) = TextReader().read(path, strict=False)
    read = pairbench.read_text_matching(text, default_order=DEFAULT_ORDER)
    ((index, held),) = matching_pool._in_the_order_text_captures_hold(read)
    numbers = round_numbers(row[0] for row in held)
    assert index == 0
    assert [(numbers[r], side, case, value) for r, side, case, value in held] == list(
        _rows(capture)
    )


@pytest.mark.parametrize(
    ("text", "ran"), TAB_EDGED_LINES, ids=["tab_at_an_end", "sides_with_a_tab", "twin_with_a_tab"]
)
def test_a_line_with_a_tab_at_an_end_orders_the_rows_as_the_line_without_the_tab(
    text: str, ran: list[tuple[int, str, str, float]], tmp_path: Path
) -> None:
    without_tabs = _text(*(line.strip("\t") for line in text.splitlines()))
    path = tmp_path / "run.txt"
    path.write_text(without_tabs, encoding="utf-8")
    (capture,) = TextReader().read(path, strict=False)
    read = pairbench.read_text_matching(text, default_order=DEFAULT_ORDER)
    plain = pairbench.read_text_matching(without_tabs, default_order=DEFAULT_ORDER)

    ((index, got),) = matching_pool._in_the_order_they_ran(read)

    assert index == 0
    assert list(got) == ran
    assert matching_pool._in_the_order_they_ran(plain) == [(0, got)]
    numbers = round_numbers(row[0] for row in got)
    assert [(numbers[r], side, case, value) for r, side, case, value in got] == list(_rows(capture))


def test_a_pass_order_above_the_banner_does_not_order_the_rows_below_it() -> None:
    # Run 0 holds the rows above its banner and below it; the text reader starts a run at
    # the banner, and its pass order with it.
    read = pairbench.read_text_matching(
        _text(
            "pass_order=old new",
            "s\tnew\t1\tc1\t110",
            "s\told\t1\tc1\t100",
            "## host",
            "s\tnew\t2\tc1\t111",
            "s\told\t2\tc1\t101",
        ),
        default_order=DEFAULT_ORDER,
    )

    ((index, ran),) = matching_pool._in_the_order_they_ran(read)

    assert index == 0
    assert [(r, side) for r, side, _case, _value in ran] == [
        (1, "old"),
        (1, "new"),
        (2, "new"),
        (2, "old"),
    ]


# Two rounds without a pass order: the rows of a run as written, and a copy whose second
# round is written the other way. A text capture without a ``sides=`` line puts ``new``
# first in its lineup, as its first row names it, so it holds both in one order.
_UNORDERED = [
    "s\tnew\t1\tc1\t110",
    "s\told\t1\tc1\t100",
    "s\told\t2\tc1\t101",
    "s\tnew\t2\tc1\t111",
]
_UNORDERED_COPY = [*_UNORDERED[:2], _UNORDERED[3], _UNORDERED[2]]
# A round of a side ``t`` and two others, and the next round written in another order.
_TWIN_ROUND = ["s\tt\t1\tc1\t1", "s\told\t1\tc1\t2", "s\tnew\t1\tc1\t3"]
_TWIN_ROUND_2 = ["s\tt\t2\tc1\t4", "s\told\t2\tc1\t5", "s\tnew\t2\tc1\t6"]
_TWIN_ROUND_SWAPPED = [_TWIN_ROUND_2[0], _TWIN_ROUND_2[2], _TWIN_ROUND_2[1]]


@pytest.mark.parametrize(
    ("texts", "refused"),
    [
        (
            (_text("sides=old new", "## host", *_UNORDERED), _text("## host", *_UNORDERED_COPY)),
            (0, 1),
        ),
        (
            (_text("## host", *_UNORDERED), _text("sides=old new", "## host", *_UNORDERED_COPY)),
            (0, 1),
        ),
        (
            (_text("## host", *_UNORDERED), _text("sides=old new\n", "## host", *_UNORDERED_COPY)),
            (0, 1),
        ),
        (
            (
                _text("## host", *_UNORDERED).rstrip("\n"),
                "sides=old new\n## host\n" + "\n".join(_UNORDERED_COPY),
            ),
            (0, 1),
        ),
        (
            (
                _text("## host", *_TWIN_ROUND, *_TWIN_ROUND_SWAPPED),
                "",
                _text("twin=t:new", "## host", *_TWIN_ROUND, *_TWIN_ROUND_2),
            ),
            (0, 1),
        ),
    ],
    ids=[
        "above_the_first_banner",
        "above_a_later_banner",
        "after_a_blank_line",
        "without_a_last_newline",
        "twin_after_an_empty_input",
    ],
)
def test_a_line_above_the_banner_of_its_input_orders_no_text_capture(
    texts: tuple[str, ...], refused: tuple[int, int], tmp_path: Path
) -> None:
    # The text reader drops the metadata above the first banner of a file, so a text
    # capture of each run holds the rows of the copy in the order of the original.
    read = _from(*texts)

    assert _text_pool(tmp_path, *[t for t in texts if t]) == [IDENTICAL]
    assert _shown(_check(read)) == [_same_kept(*refused)]
    assert _answer(read) == _same_kept(*refused)


def test_the_input_lines_of_a_read_give_the_line_each_input_begins_on() -> None:
    read = pairbench.read_text_matching(
        ["## host\nx=1\n", "", "## host", "a\r", "b\r\nc"], default_order=DEFAULT_ORDER
    )

    assert read.input_lines == (1, 4, 5, 6, 7)


# Two rounds under ``pass_order=old mid new`` and then none, a value of ``old`` that is not
# finite in place of the first row it gives. The lenient text reader names ``old`` in its
# lineup, and gives it its position, from that row as well, and leaves the row out after.
_NAN_FIRST = [
    "## host",
    "pass_order=old mid new",
    "s\tmid\t1\tc\t21",
    "s\told\t1\tc\t22",
    "s\tnew\t1\tc\t23",
    "pass_order=",
    "s\tnew\t2\tc\t24",
    "s\told\t2\tc\t25",
    "s\tmid\t2\tc\t26",
]


@pytest.mark.parametrize("spelling", ["nan", "inf"])
def test_a_copy_with_a_value_not_finite_in_place_of_a_first_row_is_refused_as_lenient(
    spelling: str, tmp_path: Path
) -> None:
    original = _text(*_NAN_FIRST)
    copy = _text(*[line.replace("\t22", f"\t{spelling}") for line in _NAN_FIRST])
    captures = []
    for k, written in enumerate((original, copy)):
        path = tmp_path / f"{k}.txt"
        path.write_text(written, encoding="utf-8")
        captures += pairbench.load_capture(path, strict=False)

    read = _from(original, copy)

    assert [r.code for r in pairbench.check_pool(captures)][:1] == [TRUNCATED]
    assert _shown(_check(read)) == [_copy_kept(0, 1)]
    assert _answer(read) == _copy_kept(0, 1)


# A run and its copy with every line written in the reverse order. The copy's own lines give
# its rounds other positions, through a pass-order line with a tab at its end and a line
# above the banner, so it is a copy only in the order the run's lines without a tab give.
_FORWARD = _text(
    " sides = old ghost new",
    "x=1",
    "## host a",
    " pass_order = ",
    "s\tnew\t1\tc1\t8147",
    "s\told\t1\tc1\t73541",
    "pass_order=new ghost old\t",
    "s\tnew\t2\tc1\t41731",
    "s\told\t2\tc1\t93710",
    "s\tnew\t3\tc1\t68342",
    "s\told\t3\tc1\t53444",
    "pass_order=old new ghost",
    "# file 0",
)
_REVERSED = _text(
    " sides = old ghost new",
    "x=1",
    "## host a",
    "pass_order=old new ghost",
    "s\told\t3\tc1\t53444",
    "s\tnew\t3\tc1\t68342",
    "s\told\t2\tc1\t93710",
    "s\tnew\t2\tc1\t41731",
    "pass_order=new ghost old\t",
    "s\told\t1\tc1\t73541",
    "s\tnew\t1\tc1\t8147",
    " pass_order = ",
    "# file 1",
)


def test_a_copy_in_the_order_the_lines_without_a_tab_give_is_identical_rows(
    tmp_path: Path,
) -> None:
    read = _from(_FORWARD, _REVERSED)

    assert _text_pool(tmp_path, _FORWARD, _REVERSED) == []
    assert _shown(_check(read)) == [_same_kept(0, 1)]


def test_a_form_whose_rows_were_compared_before_is_not_compared_again() -> None:
    # Ordinary runs: no tab, no line above a banner, every value finite. A text capture
    # holds the rows in the order they ran, and leaving out the rows that are not finite
    # leaves them all, so only the order of the text and the order they ran are compared.
    ran, swapped = _swapped("pass_order=new old")
    other = ran.replace("\t110", "\t120")

    forms = matching_pool._forms(_from(ran, swapped, other))

    assert [kinds for _index, _forms, kinds in forms] == [
        (0, 0, 0, 0, 0, 0, 0, 0, 0),
        (0, 1, 1, 1, 0, 1, 1, 1, 1),
        (0, 0, 0, 0, 0, 0, 0, 0, 0),
    ]
    compared = list(matching_pool._compared(forms[0][1:], forms[1][1:]))
    assert compared == [(forms[0][1][0], forms[1][1][0]), (forms[0][1][1], forms[1][1][1])]


# ---------------------------------------------------------------------------
# The parts of one run that text captures read as runs of their own
# ---------------------------------------------------------------------------

_MARK = b"\xef\xbb\xbf"

# Three rounds under alternating pass-order lines, ten lines in all with the banner.
_ROUNDS = [
    "pass_order=old new",
    "s\told\t1\tc\t104",
    "s\tnew\t1\tc\t111",
    "pass_order=new old",
    "s\tnew\t2\tc\t113",
    "s\told\t2\tc\t106",
    "pass_order=old new",
    "s\told\t3\tc\t112",
    "s\tnew\t3\tc\t119",
]
_MARKED_RUN = _text("## host", *_ROUNDS)
# The same rounds labelled 4, 5 and 6.
_MARKED_RELABELLED = _text(
    "## host",
    *[
        line.replace("\t1\tc", "\t4\tc").replace("\t2\tc", "\t5\tc").replace("\t3\tc", "\t6\tc")
        for line in _ROUNDS
    ],
)


def _text_pool_bytes(tmp_path: Path, *written: bytes) -> list[str]:
    """The text codes ``check_pool`` gives for the runs of files holding ``written``."""
    captures = []
    for k, data in enumerate(written):
        path = tmp_path / f"t{k}.txt"
        path.write_bytes(data)
        captures += pairbench.load_capture(path)
    return [refusal.code for refusal in pairbench.check_pool(captures)]


def _paths(tmp_path: Path, *written: bytes) -> list[Path]:
    paths = []
    for k, data in enumerate(written):
        path = tmp_path / f"m{k}.txt"
        path.write_bytes(data)
        paths.append(path)
    return paths


@pytest.mark.parametrize("copy", [_MARKED_RUN, _MARKED_RELABELLED], ids=["same", "relabelled"])
@pytest.mark.parametrize(
    "marks", [(False, True), (True, False), (True, True)], ids=["second", "first", "both"]
)
def test_a_copy_in_a_file_that_begins_with_a_byte_order_mark_is_refused(
    marks: tuple[bool, bool], copy: str, tmp_path: Path
) -> None:
    # This mode reads the marked banner as a malformed row, so the marked file joins the
    # run before it; the text reader takes the mark off and reads the file as a run of its
    # own. The two files are two parts of one run, and they are compared as runs are.
    written = [
        (_MARK if marked else b"") + text.encode("utf-8")
        for marked, text in zip(marks, (_MARKED_RUN, copy), strict=True)
    ]
    read = pairbench.read_text_matching(_paths(tmp_path, *written), default_order=DEFAULT_ORDER)

    same_bytes = written[0] == written[1]
    assert _text_pool_bytes(tmp_path, *written)[:1] == ["E_POOL_SAME" if same_bytes else IDENTICAL]
    assert (read.run_count, read.kept_rows, read.input_lines) == (1, 12, (1, 12))
    assert read.runs[0].banner_line == {(False, True): 1, (True, False): 12}.get(marks)
    assert _answer(read) == _same_part(0, 0, 1, 12)
    first = _first(read)
    assert first is not None
    assert first.message == (
        "the parts of the runs 0 and 0 that begin on the lines 1 and 12 hold identical rows"
    )


@pytest.mark.parametrize(
    ("texts", "runs", "lines"),
    [
        ((_text(*_ROUNDS), _MARKED_RELABELLED.removeprefix("## host\n")), 1, [1, 11]),
        ((_text(*_ROUNDS, "## host", *_ROUNDS),), 1, [1, 10]),
        ((_MARKED_RUN, _text(*_ROUNDS, "## host", "s\tnew\t1\tc\t9")), 2, [1, 12]),
    ],
    ids=["two_inputs_without_a_banner", "rows_above_the_first_banner", "above_a_later_banner"],
)
def test_the_parts_of_one_run_that_text_captures_read_as_two_are_compared(
    texts: tuple[str, ...], runs: int, lines: list[int], tmp_path: Path
) -> None:
    read = _from(*texts)

    assert _text_pool(tmp_path, *texts)[:1] == [IDENTICAL]
    assert read.run_count == runs
    assert _answer(read) == _same_part(0, 0, *lines)


def test_a_part_of_a_run_and_another_run_are_named_by_their_runs(tmp_path: Path) -> None:
    # The rows above the first banner are written new first in each round, under lines that
    # say old ran first; run 1 holds them written old first. Neither run is a stretch of the
    # other in any order, but the part above the banner, in the order its rows ran, is run 1.
    above = [
        line
        for k in range(0, len(_ROUNDS), 3)
        for line in (_ROUNDS[k], *sorted(_ROUNDS[k + 1 : k + 3], key=lambda row: "new" not in row))
    ]
    below = [line.replace("\tc\t1", "\tc\t2") for line in _ROUNDS]
    texts = (_text(*above, "## host", *below), _text("## host", *_ROUNDS))
    read = _from(*texts)

    assert IDENTICAL in _text_pool(tmp_path, *texts)
    assert read.run_count == 2
    assert _shown(_check(read)) == [_same_part(0, 1, 1, 21)]


def test_a_byte_order_mark_comes_off_a_pass_order_line_that_begins_an_input(
    tmp_path: Path,
) -> None:
    # The copy has no banner, so its rows join the run before it in this mode, and it swaps
    # the rows of each round under a marked pass-order line. Only the text reader reads
    # that line as one, and it gives the copy's rows the original's order.
    original = _text(
        "## host",
        "pass_order=new old",
        "s\tnew\t1\tc\t31",
        "s\told\t1\tc\t32",
        "s\tnew\t2\tc\t33",
        "s\told\t2\tc\t34",
        "pass_order=",
    )
    copy = _text(
        "pass_order=new old",
        "s\told\t1\tc\t32",
        "s\tnew\t1\tc\t31",
        "s\told\t2\tc\t34",
        "s\tnew\t2\tc\t33",
    )
    written = [original.encode("utf-8"), _MARK + copy.encode("utf-8")]
    read = pairbench.read_text_matching(_paths(tmp_path, *written), default_order=DEFAULT_ORDER)

    assert _text_pool_bytes(tmp_path, *written)[:1] == [IDENTICAL]
    assert read.run_count == 1
    assert _answer(read) == _same_part(0, 0, 1, 9)


@pytest.mark.parametrize(
    ("texts", "marks"),
    [
        (
            (
                _text("## host", "pass_order=new old", "s\tnew\t1\tc1\t110", "s\told\t1\tc1\t100"),
                _text("s\tnew\t2\tc1\t111", "s\told\t2\tc1\t101"),
            ),
            (False, False),
        ),
        (
            (
                _text(
                    "pass_order=new old",
                    "s\tnew\t1\tc1\t110",
                    "s\told\t1\tc1\t100",
                    "## host",
                    "pass_order=new old",
                    "s\tnew\t2\tc1\t111",
                    "s\told\t2\tc1\t101",
                ),
            ),
            (False,),
        ),
        (
            (_MARKED_RUN, _text("## host", *[r.replace("\tc\t1", "\tc\t3") for r in _ROUNDS])),
            (False, True),
        ),
    ],
    ids=["a_later_input_without_a_banner", "rows_above_the_first_banner", "a_marked_file"],
)
def test_parts_of_one_run_that_are_no_copy_pool(
    texts: tuple[str, ...], marks: tuple[bool, ...], tmp_path: Path
) -> None:
    written = [
        (_MARK if marked else b"") + text.encode("utf-8")
        for marked, text in zip(marks, texts, strict=True)
    ]
    read = pairbench.read_text_matching(_paths(tmp_path, *written), default_order=DEFAULT_ORDER)

    assert _text_pool_bytes(tmp_path, *written) == []
    assert read.run_count == 1
    assert _answer(read) is None


# A header file: a banner and a ``sides=`` line, and no row.
_HEADER = _text("## host", "sides=old new")
# Rows written old first in each round under a line that puts new first in the lineup.
_LINEUP_FIRST = [
    "sides=new old",
    *[
        f"s\t{side}\t{r}\tc\t{value + r}"
        for r in range(1, 7)
        for side, value in (("old", 10), ("new", 20))
    ],
]
# The rows as a text capture of their own file holds them: new first in each round.
_IN_LINEUP = [
    f"s\t{side}\t{r}\tc\t{value + r}"
    for r in range(1, 7)
    for side, value in (("new", 20), ("old", 10))
]
_COPY_IN_LINEUP = _text("## host", *_IN_LINEUP)
_OTHER_IN_LINEUP = _text("## host", *[line.replace("\tc\t2", "\tc\t4") for line in _IN_LINEUP])


def _one_part_layouts(copy: str) -> dict[str, tuple[bytes, ...]]:
    """Layouts in which every kept row of run 0 stands outside the input of its banner."""
    return {
        "a_header_and_a_file_without_a_banner": (
            _HEADER.encode(),
            _text(*_LINEUP_FIRST).encode(),
            copy.encode(),
        ),
        "a_header_and_a_file_that_begins_with_a_mark": (
            _HEADER.encode(),
            _MARK + _text("## host", *_LINEUP_FIRST).encode(),
            copy.encode(),
        ),
        "rows_above_a_banner_followed_by_metadata_only": (
            _text(*_LINEUP_FIRST, "## host", "sides=old new").encode(),
            copy.encode(),
        ),
    }


@pytest.mark.parametrize("layout", list(_one_part_layouts(_COPY_IN_LINEUP)))
def test_a_run_whose_rows_all_stand_outside_its_banners_input_is_compared_as_they_are_held(
    layout: str, tmp_path: Path
) -> None:
    # Run 0 holds the rows of one part, which is not the part below its banner. A text
    # capture of that part orders its rows by the part's own lines, and so holds the copy.
    written = _one_part_layouts(_COPY_IN_LINEUP)[layout]
    read = pairbench.read_text_matching(_paths(tmp_path, *written), default_order=DEFAULT_ORDER)

    assert _text_pool_bytes(tmp_path, *written)[:1] == [IDENTICAL]
    assert (read.run_count, read.kept_rows) == (2, 24)
    assert _answer(read) == _same_kept(0, 1)


@pytest.mark.parametrize("layout", list(_one_part_layouts(_OTHER_IN_LINEUP)))
def test_a_run_whose_rows_all_stand_outside_its_banners_input_and_no_copy_pools(
    layout: str, tmp_path: Path
) -> None:
    written = _one_part_layouts(_OTHER_IN_LINEUP)[layout]
    read = pairbench.read_text_matching(_paths(tmp_path, *written), default_order=DEFAULT_ORDER)

    assert not {IDENTICAL, TRUNCATED} & set(_text_pool_bytes(tmp_path, *written))
    assert (read.run_count, read.kept_rows) == (2, 24)
    assert _answer(read) is None


class _Counted(tuple[Any, ...]):
    """A tuple that counts the items read from it."""

    reads = 0

    def __iter__(self) -> Iterator[Any]:
        for item in super().__iter__():
            self.reads += 1
            yield item


def _counted(files: int) -> tuple[MatchingRead, list[_Counted]]:
    """A read of ``files`` texts without a banner, one run, its metadata and inputs counted.

    Each text holds four rounds, each under a pass-order line, with values of its own.
    """
    texts = [
        _text(
            *[
                line
                for r in range(1, 5)
                for line in (
                    "pass_order=new old" if r % 2 else "pass_order=old new",
                    f"s\tnew\t{r}\tc\t{100 * k + r + 0.5}",
                    f"s\told\t{r}\tc\t{100 * k + r + 0.25}",
                )
            ]
        )
        for k in range(1, files + 1)
    ]
    read = _from(*texts)
    metadata = [_Counted(run.metadata) for run in read.runs]
    inputs = _Counted(read.input_lines)
    runs = tuple(
        dataclasses.replace(run, metadata=counted)
        for run, counted in zip(read.runs, metadata, strict=True)
    )
    return dataclasses.replace(read, runs=runs, input_lines=inputs), [*metadata, inputs]


@pytest.mark.parametrize("files", [20, 40])
def test_the_lines_of_a_run_are_read_as_often_however_many_parts_it_has(files: int) -> None:
    # The parts of one run are compared with each other, and each is ordered by the
    # metadata lines of the whole run; those lines are read once for the run, not once for
    # each part, so the work grows with the lines and not with their square.
    read, counted = _counted(files)

    assert (read.run_count, len(read.input_lines), len(read.runs[0].metadata)) == (
        1,
        files,
        4 * files,
    )
    assert _check(read) == []
    assert [c.reads <= 2 * len(c) for c in counted] == [True, True]
