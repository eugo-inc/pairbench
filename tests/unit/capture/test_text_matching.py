# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The matching reading mode of the text format, and its two-sided view.

``pairbench.read_text_matching`` reads one or more inputs as one text, keeps every row it
can read with its run, its pass order and its line, counts what it cannot read, refuses
nothing and prints nothing. ``two_sided`` keeps the rows of two sides that a pass-order line
of their run orders, and ``capture`` gives that view to the analysis. Every value here is
made up.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.errors import Refusal

DEFAULT = "made-up default order"


def row(side: str, round_: object, case: str, value: object, suite: str = "s") -> str:
    """One data row of the text format."""
    return f"{suite}\t{side}\t{round_}\t{case}\t{value}"


def text(*lines: str) -> str:
    return "\n".join(lines)


def read(inputs: Any, default_order: str = DEFAULT) -> Any:
    return pairbench.read_text_matching(inputs, default_order=default_order)


def kept(result: Any) -> list[tuple[Any, ...]]:
    """The kept rows as (run, round, side, case, value, suite, pass order, from a line)."""
    return [
        (r.run, r.round, r.side, r.case, r.value, r.suite, r.pass_order, r.order_from_line)
        for r in result.rows
    ]


def view_rows(view: Any) -> list[tuple[Any, ...]]:
    """The rows of a view as (run, round, side, value, order)."""
    return [(v.row.run, v.row.round, v.row.side, v.row.value, v.order) for v in view.rows]


def cells(capture: Any) -> list[tuple[Any, ...]]:
    """The observations of a capture as (round, side, case, value, position)."""
    return sorted((o.round, o.name, o.case, o.value, o.pos) for o in capture.observations)


# ---------------------------------------------------------------------------
# Several inputs, runs and banners
# ---------------------------------------------------------------------------


def test_several_inputs_are_read_as_one_text_in_the_order_given(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text(
        text("## host", "pass_order=new old", row("new", 1, "c1", 110), row("old", 1, "c1", 100))
        + "\n",
        encoding="utf-8",
    )
    second.write_text(
        text(row("new", 2, "c1", 111), row("old", 2, "c1", 101)) + "\n", encoding="utf-8"
    )

    result = read([first, second])

    assert kept(result) == [
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 1, "old", "c1", 100.0, "s", "new old", True),
        (0, 2, "new", "c1", 111.0, "s", "new old", True),
        (0, 2, "old", "c1", 101.0, "s", "new old", True),
    ]
    # One newline joins the inputs, so the end of the first file leaves a blank line 5.
    assert [r.line for r in result.rows] == [3, 4, 6, 7]
    assert result.run_count == 1
    assert result.runs[0].banner_line == 1
    in_memory = read([first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8")])
    assert in_memory == result


def test_a_first_input_without_a_banner_is_run_0_with_the_first_banner() -> None:
    no_banner = text(row("new", 2, "c1", 111), row("old", 2, "c1", 101))
    with_banner = text(
        "## host", "pass_order=new old", row("new", 1, "c1", 110), row("old", 1, "c1", 100)
    )
    later = text("## host", row("new", 3, "c1", 112))

    result = read([no_banner, with_banner, later])

    assert kept(result) == [
        (0, 2, "new", "c1", 111.0, "s", DEFAULT, False),
        (0, 2, "old", "c1", 101.0, "s", DEFAULT, False),
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 1, "old", "c1", 100.0, "s", "new old", True),
        (1, 3, "new", "c1", 112.0, "s", DEFAULT, False),
    ]
    assert result.run_count == 2
    assert [run.banner_line for run in result.runs] == [3, 7]


def test_a_line_that_starts_with_the_banner_once_stripped_opens_a_run() -> None:
    result = read(
        text(
            "## host",
            "pass_order=new old",
            row("new", 1, "c1", 110),
            "   ## host",
            row("new", 1, "c1", 111),
            "## hostX",
            row("new", 1, "c1", 112),
            "## host\tx",
            row("new", 1, "c1", 113),
        )
    )

    assert kept(result) == [
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (1, 1, "new", "c1", 111.0, "s", DEFAULT, False),
        (2, 1, "new", "c1", 112.0, "s", DEFAULT, False),
        (3, 1, "new", "c1", 113.0, "s", DEFAULT, False),
    ]
    assert result.run_count == 4
    assert [run.banner_line for run in result.runs] == [1, 4, 6, 8]
    assert result.malformed_rows == 0


def test_rows_above_the_first_banner_share_run_0_and_the_banner_resets_their_order() -> None:
    result = read(
        text(
            "pass_order=new old",
            row("new", 1, "c1", 110),
            row("old", 1, "c1", 100),
            "## host",
            row("new", 2, "c1", 111),
            row("old", 2, "c1", 101),
        )
    )

    assert kept(result) == [
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 1, "old", "c1", 100.0, "s", "new old", True),
        (0, 2, "new", "c1", 111.0, "s", DEFAULT, False),
        (0, 2, "old", "c1", 101.0, "s", DEFAULT, False),
    ]
    assert result.run_count == 1
    assert result.runs[0].metadata == (("pass_order", "new old"),)


def test_a_run_without_rows_keeps_its_index_and_nothing_is_refused() -> None:
    result = read(text("## host", "x=1", "## host", row("new", 1, "c1", 110)))

    assert kept(result) == [(1, 1, "new", "c1", 110.0, "s", DEFAULT, False)]
    assert result.run_count == 2
    assert result.runs[0].metadata == (("x", "1"),)
    assert (result.runs[0].kept_rows, result.runs[1].kept_rows) == (0, 1)


@pytest.mark.parametrize(
    ("given", "runs"),
    [
        ("", 1),
        (text("unit=ns", "x=1"), 1),
        (text("# a made-up comment", "", "\t"), 1),
        (text("## host", "x=1"), 1),
        (text("## host", "## host", "## host"), 3),
    ],
)
def test_a_text_without_data_rows_reads_as_zero_rows(given: str, runs: int) -> None:
    result = read(given)

    assert result.rows == ()
    assert (result.kept_rows, result.malformed_rows, result.run_count) == (0, 0, runs)
    assert [run.index for run in result.runs] == list(range(runs))


def test_the_run_count_is_the_banners_or_one_and_every_index_stays_below_it() -> None:
    no_banner = read(text(row("new", 1, "c1", 110), "garbage", "x=1"))
    metadata_only = read(text("unit=ns", "x=1"))

    assert no_banner.run_count == 1
    assert {r.run for r in no_banner.rows} == {0}
    assert no_banner.runs[0].malformed_rows == 1
    assert metadata_only.run_count == 1
    assert metadata_only.runs[0].metadata == (("unit", "ns"), ("x", "1"))
    assert metadata_only.runs[0].banner_line is None


# ---------------------------------------------------------------------------
# Metadata and the pass order
# ---------------------------------------------------------------------------


def test_a_line_without_a_tab_once_stripped_that_holds_an_equals_sign_is_metadata() -> None:
    result = read(
        text(
            "## host",
            "\tpass_order=old new",
            row("old", 1, "c1", 100),
            row("new", 1, "c1", 110),
            "# a=1",
            "  #\tnot\ta\trow\tx",
        )
    )

    assert kept(result) == [
        (0, 1, "old", "c1", 100.0, "s", "old new", True),
        (0, 1, "new", "c1", 110.0, "s", "old new", True),
    ]
    assert result.runs[0].metadata == (("\tpass_order", "old new"),)
    assert result.malformed_rows == 0


def test_a_pass_order_line_starts_exactly_with_the_key_and_equals_sign() -> None:
    result = read(
        text(
            "## host",
            " pass_order = old new",
            row("old", 1, "c1", 100),
            "  pass_order=old new  ",
            row("old", 2, "c1", 101),
        )
    )

    assert kept(result) == [
        (0, 1, "old", "c1", 100.0, "s", DEFAULT, False),
        (0, 2, "old", "c1", 101.0, "s", "old new", True),
    ]
    assert result.runs[0].metadata == ((" pass_order ", " old new"), ("  pass_order", "old new  "))


def test_each_row_carries_the_pass_order_text_as_written() -> None:
    result = read(
        text(
            "## host",
            "pass_order=new  old",
            row("new", 1, "c1", 110),
            "pass_order=new old",
            row("new", 2, "c1", 111),
            "pass_order=new",
            row("new", 3, "c1", 112),
            "pass_order=new old mid",
            row("new", 4, "c1", 113),
        )
    )

    assert [(r.pass_order, r.order_from_line) for r in result.rows] == [
        ("new  old", True),
        ("new old", True),
        ("new", True),
        ("new old mid", True),
    ]


def test_the_default_order_holds_from_each_banner_and_after_an_empty_pass_order_line() -> None:
    result = read(
        text(
            "## host",
            row("new", 1, "c1", 110),
            "pass_order=new old",
            row("new", 2, "c1", 111),
            "pass_order=",
            row("new", 3, "c1", 112),
            "pass_order=old new",
            row("new", 4, "c1", 113),
            "pass_order=   ",
            row("new", 5, "c1", 114),
            "## host",
            row("new", 6, "c1", 115),
        ),
        default_order="first ran first",
    )

    assert [(r.run, r.pass_order, r.order_from_line) for r in result.rows] == [
        (0, "first ran first", False),
        (0, "new old", True),
        (0, "first ran first", False),
        (0, "old new", True),
        (0, "first ran first", False),
        (1, "first ran first", False),
    ]
    assert result.default_order == "first ran first"


# ---------------------------------------------------------------------------
# Values, cells, cases and sides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "-0.0", "-5", "-inf", "-1e999"])
def test_a_value_at_or_below_zero_is_malformed(value: str) -> None:
    result = read(text("## host", row("new", 1, "c1", value), row("new", 2, "c1", 110)))

    assert kept(result) == [(0, 2, "new", "c1", 110.0, "s", DEFAULT, False)]
    assert result.runs[0].malformed_rows == 1
    assert result.malformed_rows == 1


@pytest.mark.parametrize(
    ("value", "nan"),
    [("nan", True), ("NaN", True), ("-nan", True), ("inf", False), ("Infinity", False),
     ("1e999", False)],
)  # fmt: skip
def test_a_value_that_is_not_finite_and_not_below_zero_is_kept(value: str, nan: bool) -> None:
    result = read(text("## host", row("new", 1, "c1", value)))

    (kept_row,) = result.rows
    assert math.isnan(kept_row.value) is nan
    if not nan:
        assert kept_row.value == math.inf
    assert result.malformed_rows == 0


def test_a_cell_given_twice_keeps_both_rows_and_the_view_takes_the_later() -> None:
    result = read(
        text(
            "## host",
            "pass_order=new old",
            row("new", 1, "c1", 500),
            row("new", 1, "c1", 110),
            row("old", 1, "c1", 100),
        )
    )

    assert kept(result) == [
        (0, 1, "new", "c1", 500.0, "s", "new old", True),
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 1, "old", "c1", 100.0, "s", "new old", True),
    ]
    capture = result.two_sided("new", "old").capture()
    assert cells(capture) == [(1, "new", "c1", 110.0, 1), (1, "old", "c1", 100.0, 2)]


def test_a_forward_and_a_reversed_pass_may_reuse_round_numbers() -> None:
    result = read(
        text(
            "pass_order=new old",
            row("new", 1, "c1", 110),
            row("old", 1, "c1", 100),
            "pass_order=old new",
            row("old", 1, "c1", 101),
            row("new", 1, "c1", 90),
        )
    )

    assert kept(result) == [
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 1, "old", "c1", 100.0, "s", "new old", True),
        (0, 1, "old", "c1", 101.0, "s", "old new", True),
        (0, 1, "new", "c1", 90.0, "s", "old new", True),
    ]
    view = result.two_sided("new", "old")
    assert [v.order for v in view.rows] == [
        "first, second",
        "first, second",
        "second, first",
        "second, first",
    ]
    # One round, one pair: the later row of each cell, in the order of the last row.
    assert cells(view.capture()) == [(1, "new", "c1", 90.0, 2), (1, "old", "c1", 101.0, 1)]


def _two_passes(reversed_rounds: int, *, c2: str = "read", cut_last: bool = False) -> str:
    """A forward pass of 12 rounds under ``new old``, then a reversed pass under ``old new``.

    The reversed pass writes rounds 1 to ``reversed_rounds``. With ``c2="fail"`` its c2
    values are not numbers, so those rows are malformed and c2 keeps its forward values. With
    ``cut_last`` its last round stops after its first row.
    """
    lines = ["## host", "pass_order=new old"]
    for label in range(1, 13):
        lines += [
            row("new", label, "c1", 90 + label),
            row("old", label, "c1", 100 + label),
            row("new", label, "c2", 50 + label),
            row("old", label, "c2", 60 + label),
        ]
    lines.append("pass_order=old new")
    for label in range(1, reversed_rounds + 1):
        c2_old, c2_new = (61 + label, 51 + label) if c2 == "read" else ("error", "error")
        rows = [
            row("old", label, "c1", 101 + label),
            row("new", label, "c1", 91 + label),
            row("old", label, "c2", c2_old),
            row("new", label, "c2", c2_new),
        ]
        lines += rows[:1] if cut_last and label == reversed_rounds else rows
    return text(*lines)


def _positions(capture: Any) -> dict[int, tuple[Any, Any]]:
    """The position of new and of old in each round of a capture."""
    by = {(o.round, o.name): o.pos for o in capture.observations}
    rounds = sorted({o.round for o in capture.observations})
    return {r: (by.get((r, "new")), by.get((r, "old"))) for r in rounds}


def test_a_round_whose_cells_come_from_rows_of_two_orders_has_no_order() -> None:
    # Every c2 value comes from the forward pass, every c1 value of rounds 1 to 6 from the
    # reversed pass: rounds 1 to 6 have no single order.
    capture = read(_two_passes(6, c2="fail")).two_sided("new", "old").capture()

    assert _positions(capture) == {
        **dict.fromkeys(range(1, 7), (None, None)),
        **dict.fromkeys(range(7, 13), (1, 2)),
    }
    with pytest.raises(Refusal) as caught:
        pairbench.analyse(capture, floors=pairbench.Floors(0.01))
    assert (caught.value.code, caught.value.exit_code) == ("E_ORDER_NOT_VARIED", 6)
    assert caught.value.message == "new ran before old in every one of 6 rounds"


def test_a_reversed_pass_cut_inside_a_round_leaves_that_round_without_an_order() -> None:
    capture = read(_two_passes(6, cut_last=True)).two_sided("new", "old").capture()

    assert _positions(capture) == {
        **dict.fromkeys(range(1, 6), (2, 1)),
        6: (None, None),
        **dict.fromkeys(range(7, 13), (1, 2)),
    }
    results = pairbench.analyse(capture, floors=pairbench.Floors(0.01))
    graded = [(c.case, c.outcome, "order_not_recorded" in c.reasons) for c in results.comparisons]
    assert graded == [("c1", "no_verdict", True), ("c2", "no_verdict", True)]


def test_a_round_whose_cells_all_come_from_one_pass_keeps_that_order() -> None:
    capture = read(_two_passes(6)).two_sided("new", "old").capture()

    assert _positions(capture) == {
        **dict.fromkeys(range(1, 7), (2, 1)),
        **dict.fromkeys(range(7, 13), (1, 2)),
    }
    results = pairbench.analyse(capture, floors=pairbench.Floors(0.01))
    assert [(c.case, c.outcome, c.order_split) for c in results.comparisons] == [
        ("c1", "better", (6, 6)),
        ("c2", "better", (6, 6)),
    ]


def test_an_empty_case_is_a_case_like_any_other() -> None:
    result = read(text("## host", row("new", 1, "", 110)))

    assert kept(result) == [(0, 1, "new", "", 110.0, "s", DEFAULT, False)]
    assert result.malformed_rows == 0


SIDES = ["x y", "x=y", "", "~a", ".", "..", " new"]


def test_no_side_name_is_checked() -> None:
    result = read(text("## host", *(row(side, 1, "c1", 110 + i) for i, side in enumerate(SIDES))))

    assert [r.side for r in result.rows] == SIDES
    assert [r.value for r in result.rows] == [110.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0]
    assert result.malformed_rows == 0


@pytest.mark.parametrize("name", ["x y", ""])
def test_a_view_leaves_out_a_side_that_no_pass_order_line_can_name(name: str) -> None:
    result = read(
        text(
            "## host",
            f"pass_order={name} old",
            row(name, 1, "c1", 110),
            row("old", 1, "c1", 100),
        )
    )

    view = result.two_sided(name, "old")

    assert view.rows == ()
    assert (view.left_out_no_order, view.left_out_other_sides) == (2, 0)


def test_a_banner_that_splits_into_five_fields_opens_a_run_and_is_no_row() -> None:
    result = read(
        text(
            "pass_order=new old",
            row("new", 1, "c1", 110),
            "## host\ta\tb\tc\td",
            row("new", 2, "c1", 111),
            "## host\ta\tb\tc\td",
            row("new", 3, "c1", 112),
        )
    )

    assert kept(result) == [
        (0, 1, "new", "c1", 110.0, "s", "new old", True),
        (0, 2, "new", "c1", 111.0, "s", DEFAULT, False),
        (1, 3, "new", "c1", 112.0, "s", DEFAULT, False),
    ]
    assert result.malformed_rows == 0
    assert [run.pool_rows for run in result.runs] == [
        (("s", "new", "1", "c1", "110"), ("s", "new", "2", "c1", "111")),
        (("s", "new", "3", "c1", "112"),),
    ]
    view = result.two_sided("new", "old")
    assert view_rows(view) == [(0, 1, "new", 110.0, "first, second")]
    assert view.left_out_no_order == 2


CHECKED_METADATA = (
    "unit=ns",
    "unit=ms",
    "better=up",
    "sides=new old",
    "sides=old new",
    "sides=new new",
    "twin=z",
    "twin=z:new",
)


def test_metadata_the_strict_reader_checks_changes_nothing() -> None:
    rows = (
        "pass_order=new z",
        row("new", 1, "c1", 110),
        row("z", 1, "c1", 100),
    )
    plain = read(text("## host", *rows))
    checked = read(text("## host", *CHECKED_METADATA, *rows))

    assert kept(checked) == kept(plain)
    assert kept(checked) == [
        (0, 1, "new", "c1", 110.0, "s", "new z", True),
        (0, 1, "z", "c1", 100.0, "s", "new z", True),
    ]
    assert checked.runs[0].metadata == (
        *(tuple(line.split("=", 1)) for line in CHECKED_METADATA),
        ("pass_order", "new z"),
    )
    view = checked.two_sided("new", "z")
    assert view_rows(view) == [
        (0, 1, "new", 110.0, "first, second"),
        (0, 1, "z", 100.0, "first, second"),
    ]
    assert [s.role for s in view.capture().sides] == ["subject", "baseline"]


def test_a_byte_order_mark_belongs_to_the_first_line(tmp_path: Path) -> None:
    lines = text(
        "﻿## host",
        "pass_order=new old",
        row("new", 1, "c1", 110),
        "## host",
        row("new", 2, "c1", 111),
    )
    file = tmp_path / "marked.txt"
    file.write_bytes(lines.encode("utf-8"))

    for result in (read(lines), read(file)):
        assert kept(result) == [
            (0, 1, "new", "c1", 110.0, "s", "new old", True),
            (0, 2, "new", "c1", 111.0, "s", DEFAULT, False),
        ]
        assert result.run_count == 1
        assert result.runs[0].malformed_rows == 1
        assert result.runs[0].banner_line == 4
        assert result.runs[0].metadata == (("pass_order", "new old"),)


def test_malformed_rows_are_counted_and_nothing_is_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = read(
        text(
            "## host",
            row("new", 1, "c1", "abc"),
            row("new", 1, "c1", 110),
            row("old", 1, "c1", 100),
            "## host",
            row("new", 2, "c1", "nope"),
            row("new", 2, "c1", "-1"),
        )
    )

    assert [run.malformed_rows for run in result.runs] == [1, 2]
    assert (result.malformed_rows, result.kept_rows) == (3, 2)
    assert [run.kept_rows for run in result.runs] == [2, 0]
    assert capsys.readouterr() == ("", "")


# ---------------------------------------------------------------------------
# How lines are classified
# ---------------------------------------------------------------------------


def test_a_carriage_return_ends_a_line() -> None:
    result = read("## host\rpass_order=new old\r\n" + row("new", 1, "c1", 110) + "\r")

    assert kept(result) == [(0, 1, "new", "c1", 110.0, "s", "new old", True)]
    assert result.rows[0].line == 3


def test_a_blank_line_is_skipped_and_never_counted() -> None:
    result = read(text("## host", "", "   ", "\t", "\t \t", "\t\t\t\t", " \x0b\x0c "))

    assert (result.kept_rows, result.malformed_rows) == (0, 0)
    assert result.runs[0].metadata == ()
    # A blank line of four tabs splits into five fields, so it counts in the pool rows.
    assert result.runs[0].pool_rows == (("", "", "", "", ""),)
    assert result.runs[0].pool_row_lines == (6,)


def test_a_line_starting_with_a_hash_once_stripped_is_a_comment_whatever_it_holds() -> None:
    result = read(text("## host", "# x=1", "  #\ts\tnew\t1\t110", "## section", "#"))

    assert (result.kept_rows, result.malformed_rows, result.run_count) == (0, 0, 1)
    assert result.runs[0].metadata == ()
    assert result.runs[0].pool_rows == (("#", "s", "new", "1", "110"),)


@pytest.mark.parametrize(
    "line",
    [
        "x=1\ty",  # holds a tab once stripped: a candidate row of two fields
        "garbage",  # no tab and no equals sign
        "s\tnew\t1\tc1",  # four fields
        "s\tnew\t1\tc1\t110\t",  # six fields, the last empty
        "\ts\tnew\t1\tc1\t110",  # six fields, the first empty
        row("new", "1.5", "c1", 110),  # the round is no integer
        row("new", "", "c1", 110),
        row("new", 1, "c1", ""),
        row("new", 1, "c1", "1,5"),
    ],
)
def test_a_candidate_row_that_does_not_read_is_malformed(line: str) -> None:
    result = read(text("## host", line))

    assert (result.kept_rows, result.malformed_rows) == (0, 1)
    assert result.runs[0].metadata == ()


@pytest.mark.parametrize(
    ("round_text", "value_text", "round_", "value"),
    [
        (" 1", " 110 ", 1, 110.0),
        ("+1", "+110", 1, 110.0),
        ("1_0", "1_10", 10, 110.0),
        ("-3", "1e2", -3, 100.0),
        ("0", "0.5", 0, 0.5),
    ],
)
def test_the_round_and_the_value_parse_as_written(
    round_text: str, value_text: str, round_: int, value: float
) -> None:
    result = read(text("## host", row("new", round_text, "c1", value_text)))

    ((parsed_round, parsed_value),) = [(r.round, r.value) for r in result.rows]
    assert (parsed_round, parsed_value) == (round_, value)
    assert type(parsed_round) is int
    assert type(parsed_value) is float


def test_suite_side_and_case_are_kept_unstripped() -> None:
    result = read(text("## host", "  t \t new \t1\t c1 \t110"))

    ((suite, side, case),) = [(r.suite, r.side, r.case) for r in result.rows]
    assert (suite, side, case) == ("  t ", " new ", " c1 ")
    assert result.runs[0].pool_rows == (("t", "new", "1", "c1", "110"),)


def test_every_field_of_a_pool_row_has_the_white_space_around_it_removed() -> None:
    result = read(text("## host", " t \t new \t 1 \t c1 \t 110 ", "s\t\t 2\t c2\t abc "))

    assert result.runs[0].pool_rows == (("t", "new", "1", "c1", "110"), ("s", "", "2", "c2", "abc"))


def test_the_pool_rows_hold_every_five_field_line_but_the_banner() -> None:
    result = read(
        text(
            "## host\ta\tb\tc\td",
            row("new", 1, "c1", 110),
            row("new", 1, "c1", "abc"),
            "# a\tcomment\twith\tfour\ttabs",
            "\t\tx=1\t\t",
            "\t\t\t\t",
            "s\tnew\t1",
        )
    )

    run = result.runs[0]
    assert run.pool_rows == (
        ("s", "new", "1", "c1", "110"),
        ("s", "new", "1", "c1", "abc"),
        ("# a", "comment", "with", "four", "tabs"),
        ("", "", "x=1", "", ""),
        ("", "", "", "", ""),
    )
    assert run.pool_row_lines == (2, 3, 4, 5, 6)
    assert run.has_pool_rows
    assert not read(text("## host", "x=1")).runs[0].has_pool_rows


# ---------------------------------------------------------------------------
# Inputs the call refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("inputs", "default_order"),
    [([], DEFAULT), ([b"## host"], DEFAULT), ("## host", None), (3, DEFAULT)],
)
def test_inputs_that_are_not_paths_or_texts_are_refused(inputs: Any, default_order: Any) -> None:
    with pytest.raises(Refusal) as caught:
        pairbench.read_text_matching(inputs, default_order=default_order)

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_a_file_that_is_not_utf8_or_cannot_be_read_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"## host\n\xff\n")

    for given in (bad, tmp_path / "absent.txt"):
        with pytest.raises(Refusal) as caught:
            read([given])
        assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


# ---------------------------------------------------------------------------
# The two-sided view
# ---------------------------------------------------------------------------


def test_a_view_keeps_a_row_when_the_line_before_it_names_both_sides() -> None:
    result = read(
        text(
            "pass_order=new old",
            row("new", 1, "c1", 110),
            "pass_order=old",
            row("old", 1, "c1", 100),
            "pass_order=new old",
            row("new", 2, "c1", 111),
            row("old", 2, "c1", 101),
            row("mid", 2, "c1", 120),
        )
    )

    view = result.two_sided("new", "old")

    assert view_rows(view) == [
        (0, 1, "new", 110.0, "first, second"),
        (0, 2, "new", 111.0, "first, second"),
        (0, 2, "old", 101.0, "first, second"),
    ]
    assert (view.left_out_no_order, view.left_out_other_sides) == (1, 1)
    # Round 1 gives no pair, so the capture holds round 2 alone.
    assert cells(view.capture()) == [(1, "new", "c1", 111.0, 1), (1, "old", "c1", 101.0, 2)]


def test_a_view_never_uses_the_default_order_even_when_it_names_both_sides() -> None:
    result = read(
        text("## host", row("new", 1, "c1", 110), row("old", 1, "c1", 100)),
        default_order="new old",
    )

    view = result.two_sided("new", "old")

    assert view.rows == ()
    assert view.left_out_no_order == 2
    with pytest.raises(Refusal) as caught:
        view.capture()
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_a_pass_order_line_never_counts_for_a_later_run() -> None:
    result = read(
        text(
            "## host",
            "pass_order=old new",
            row("old", 1, "c1", 100),
            row("new", 1, "c1", 110),
            "## host",
            row("new", 1, "c1", 112),
            row("old", 1, "c1", 102),
        ),
        default_order="new old",
    )

    view = result.two_sided("new", "old")

    assert view_rows(view) == [
        (0, 1, "old", 100.0, "second, first"),
        (0, 1, "new", 110.0, "second, first"),
    ]
    assert view.left_out_no_order == 2


def test_the_order_label_says_which_side_the_line_names_first() -> None:
    result = read(
        text(
            "## host", "pass_order=old mid new", row("new", 1, "c1", 110), row("old", 1, "c1", 100)
        )
    )

    assert [v.order for v in result.two_sided("new", "old").rows] == [
        "second, first",
        "second, first",
    ]
    assert [v.order for v in result.two_sided("old", "new").rows] == [
        "first, second",
        "first, second",
    ]


def test_the_same_round_label_in_two_runs_makes_two_rounds_of_the_capture() -> None:
    result = read(
        text(
            "## host",
            "pass_order=new old",
            row("new", 1, "c1", 110),
            row("old", 1, "c1", 100),
            "## host",
            "pass_order=old new",
            row("old", 1, "c1", 101),
            row("new", 1, "c1", 111),
        )
    )

    capture = result.two_sided("new", "old").capture()

    assert cells(capture) == [
        (1, "new", "c1", 110.0, 1),
        (1, "old", "c1", 100.0, 2),
        (2, "new", "c1", 111.0, 2),
        (2, "old", "c1", 101.0, 1),
    ]
    assert capture.lineup is not None
    assert capture.lineup.rounds == 2


def _rounds(count: int, *, nan_round: int | None = None) -> str:
    lines = ["## host"]
    for label in range(1, count + 1):
        order = ("new", "old") if label % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        for side in order:
            value = (110 if side == "new" else 220) + label
            if side == "new" and label == nan_round:
                lines.append(row(side, label, "c1", "nan"))
            else:
                lines.append(row(side, label, "c1", value))
    return text(*lines)


def test_the_view_as_a_capture_is_analysed() -> None:
    capture = read(_rounds(12)).two_sided("new", "old").capture(unit="ms")

    results = pairbench.analyse(capture, floors=pairbench.Floors(0.01))

    (comparison,) = results.comparisons
    assert (comparison.subject, comparison.baseline, comparison.case) == ("new", "old", "c1")
    assert comparison.outcome == "better"
    assert capture.cases[0].unit == "ms"


def test_a_value_that_is_not_finite_is_a_missing_cell_of_the_capture(
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture = read(_rounds(12, nan_round=3)).two_sided("new", "old").capture()

    assert capsys.readouterr() == ("", "")
    assert (3, "new", "c1") not in {(o.round, o.name, o.case) for o in capture.observations}
    assert [n.code for n in capture.notes if n.code == "value_not_finite"] == ["value_not_finite"]
    results = pairbench.analyse(capture, floors=pairbench.Floors(0.01))
    (comparison,) = results.comparisons
    assert comparison.n_unpaired == 1
    assert results.refusals == ()


@pytest.mark.parametrize(("first", "second"), [("new", "new"), (1, "old")])
def test_a_view_of_one_side_twice_or_of_a_name_that_is_no_text_is_refused(
    first: Any, second: Any
) -> None:
    with pytest.raises(Refusal) as caught:
        read(text("## host", row("new", 1, "c1", 110))).two_sided(first, second)

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_the_capture_refuses_a_side_name_a_capture_cannot_hold() -> None:
    result = read(
        text("## host", "pass_order=~a old", row("~a", 1, "c1", 110), row("old", 1, "c1", 100))
    )
    view = result.two_sided("~a", "old")

    assert len(view.rows) == 2
    with pytest.raises(Refusal) as caught:
        view.capture()
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_a_capture_with_a_case_that_ends_like_the_mark_of_a_run_is_refused_by_analyse() -> None:
    case = "t +1a2b3c4d"
    capture = (
        read(text("pass_order=new old", row("new", 1, case, 110), row("old", 1, case, 100)))
        .two_sided("new", "old")
        .capture()
    )

    assert {o.case for o in capture.observations} == {case}
    with pytest.raises(Refusal) as caught:
        pairbench.analyse(capture)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_the_capture_id_tells_apart_the_units_and_the_directions() -> None:
    view = read(_rounds(2)).two_sided("new", "old")

    ids = [
        view.capture(unit=unit, better=better).capture_id
        for unit, better in [("ns", "lower"), ("ms", "lower"), ("ns", "higher"), ("ms", "higher")]
    ]

    assert len(set(ids)) == 4
    assert all(capture_id.startswith("matching-") for capture_id in ids)
    assert view.capture(unit="ms", better="higher").capture_id == ids[3]


@pytest.mark.parametrize(
    ("unit", "better"), [("", "lower"), (3, "lower"), ("ns", "up"), ("ns\udcff", "lower")]
)
def test_the_capture_refuses_a_unit_or_a_direction_that_is_not_one(unit: Any, better: Any) -> None:
    view = read(_rounds(2)).two_sided("new", "old")

    with pytest.raises(Refusal) as caught:
        view.capture(unit=unit, better=better)

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


def test_the_note_of_a_missing_cell_names_its_run_and_its_round_label() -> None:
    nan_run = _rounds(4, nan_round=1)
    capture = read(_rounds(12) + "\n" + nan_run).two_sided("new", "old").capture()

    (note,) = [n for n in capture.notes if n.code == "value_not_finite"]

    assert note.message == (
        "the value of new in round 1 of run 1 (the capture's round 13) on the case 'c1' of the "
        f"capture {capture.capture_id} is not a finite number; the cell is read as missing"
    )


def test_the_note_of_a_missing_cell_gives_no_second_number_when_it_is_the_label() -> None:
    capture = read(_rounds(12, nan_round=3)).two_sided("new", "old").capture()

    (note,) = [n for n in capture.notes if n.code == "value_not_finite"]

    assert note.message == (
        "the value of new in round 3 of run 0 on the case 'c1' of the capture "
        f"{capture.capture_id} is not a finite number; the cell is read as missing"
    )
