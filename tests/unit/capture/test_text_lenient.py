# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The lenient mode of the text reader, and what the analysis makes of what it reads.

A value that is not a finite number is a missing cell: its side keeps its launch, the cell
has no observation, the capture and the results hold one ``value_not_finite`` note for it,
``refusals`` stays empty, and its round counts in ``n_unpaired``. A round whose order
contradicts itself is read with its order not recorded. The strict mode, the default, skips
such a value as a malformed row and refuses such an order. Every value here is made up.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.capture.pool import load_captures
from pairbench.capture.text import TextReader, project
from pairbench.errors import Refusal
from pairbench.model import Capture, Note, rotate_reverse

Cli = Callable[..., Any]

NOTE = "pairbench: note: "
ENTRIES = ("new", "old", "newagain", "oldagain")


def _value(side: str, label: int) -> float:
    """``new`` reads half of ``old``; a twin is one percent above and below its side in turn."""
    base = (1.0 if side.startswith("new") else 2.0) * (1.0 + label / 64)
    if side.endswith("again"):
        return base * (1.01 if label % 2 else 0.99)
    return base


def _run(
    labels: Sequence[int],
    *,
    missing: Sequence[tuple[int, str, str]] = (),
    order: bool = True,
    contradicted: Sequence[int] = (),
) -> str:
    """A run of four entries over the rounds labelled ``labels``, in a rotating order.

    ``missing`` maps ``(label, side)`` cells to the text written in place of the value; a
    round in ``contradicted`` gives ``new`` a second position in a second row of the case
    ``extra``.
    """
    written = {(label, side): text for label, side, text in missing}
    lines = ["## host", "unit=s", "sides=new old", "twin=newagain:new", "twin=oldagain:old"]
    for i, label in enumerate(labels, start=1):
        ran = tuple(rotate_reverse(ENTRIES, i))
        if order:
            lines.append("pass_order=" + " ".join(ran))
        for side in ran:
            text = written.get((label, side), repr(_value(side, label)))
            lines.append(f"s\t{side}\t{label}\tmatmul\t{text}")
        if label in contradicted:
            lines.append("pass_order=" + " ".join(reversed(ran)))
            lines.append(f"s\tnew\t{label}\textra\t{_value('new', label)!r}")
    return "\n".join(lines) + "\n"


def _write(tmp_path: Path, text: str, name: str = "rows.txt") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _lenient(tmp_path: Path, text: str, name: str = "rows.txt") -> Capture:
    (capture,) = pairbench.load_capture(_write(tmp_path, text, name), reader="text", strict=False)
    return capture


def _observed(capture: Capture) -> set[tuple[int, str, str]]:
    return {(o.round, o.name, o.case) for o in capture.observations}


def _launches(capture: Capture) -> dict[tuple[int, str], int | None]:
    return {(x.round, x.name): x.pos for x in capture.launches}


def _cell(ident: str, side: str, label: int, case: str = "matmul", number: int = 0) -> str:
    numbered = f" (the capture's round {number})" if number else ""
    return (
        f"the value of {side} in round {label}{numbered} on the case {case!r} of the capture "
        f"{ident} is not a finite number; the cell is read as missing"
    )


def _cell_notes(notes: Sequence[Any]) -> list[str]:
    return [n.message for n in notes if n.code == "value_not_finite"]


TWELVE = tuple(range(1, 13))
TWO_MISSING = ((3, "new", "NaN"), (5, "old", "-inf"))


# ---------------------------------------------------------------------------
# The strict mode: a malformed row, and a refusal
# ---------------------------------------------------------------------------


def test_strict_skips_a_value_that_is_not_finite_as_a_malformed_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "## host\na\tnew\t1\tm\t5\na\told\t1\tm\tnan\na\told\t1\tk\t6\na\tnew\t1\tk\tinf\n"
    (capture,) = TextReader().read(_write(tmp_path, text))
    assert _observed(capture) == {(1, "new", "m"), (1, "old", "k")}
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.malformed_rows == 2
    assert capture.source.reader.missing_cells == ()
    assert [n.code for n in capture.notes] == ["malformed_rows"]
    assert capsys.readouterr().err == (
        f"{NOTE}malformed_rows: 2 malformed rows skipped in run 0 of rows.txt\n"
    )


def test_strict_refuses_a_side_left_with_no_row_in_a_round(tmp_path: Path) -> None:
    (capture,) = TextReader().read(_write(tmp_path, _run(TWELVE, missing=TWO_MISSING)))
    with pytest.raises(Refusal) as caught:
        pairbench.analyse(capture)
    assert (caught.value.code, caught.value.exit_code) == ("E_GRID", 6)
    assert caught.value.message.endswith("does not match its lineup: missing 3 new, 5 old")


def test_strict_refuses_a_side_at_two_positions_in_a_round(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        TextReader().read(_write(tmp_path, _run(TWELVE, contradicted=(4,))))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "line 27 of rows.txt: side 'new' ran at two positions in round 4"


def test_the_strict_mode_is_the_default() -> None:
    assert inspect.signature(TextReader().read).parameters["strict"].default is True
    assert inspect.signature(pairbench.load_capture).parameters["strict"].default is True


# ---------------------------------------------------------------------------
# Missing cells
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written", ["nan", "NaN", "NAN", "inf", "-inf", "Infinity", "-INF", "1e999"]
)
def test_every_form_of_a_value_that_is_not_finite_is_a_missing_cell(
    tmp_path: Path, written: str
) -> None:
    capture = _lenient(
        tmp_path, f"## host\npass_order=new old\na\tnew\t1\tm\t{written}\na\told\t1\tm\t6\n"
    )
    assert _observed(capture) == {(1, "old", "m")}
    assert _launches(capture) == {(1, "new"): 1, (1, "old"): 2}
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.missing_cells == ((1, "new", "m"),)
    assert capture.source.reader.malformed_rows == 0


def test_a_missing_cell_keeps_its_launch_and_gets_one_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    assert len(capture.launches) == 48
    assert len(capture.observations) == 46
    assert (3, "new", "matmul") not in _observed(capture)
    assert (5, "old", "matmul") not in _observed(capture)
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.missing_cells == ((3, "new", "matmul"), (5, "old", "matmul"))
    ident = capture.capture_id
    messages = [_cell(ident, "new", 3), _cell(ident, "old", 5)]
    assert [(n.code, n.message) for n in capture.notes] == [
        ("value_not_finite", message) for message in messages
    ]
    assert capsys.readouterr().err == "".join(
        f"{NOTE}value_not_finite: {message}\n" for message in messages
    )


def test_a_round_whose_every_value_is_missing_stays_a_round(tmp_path: Path) -> None:
    gone = tuple((7, side, "nan") for side in ENTRIES)
    capture = _lenient(tmp_path, _run(TWELVE, missing=gone))
    assert capture.lineup is not None and capture.lineup.rounds == 12
    assert {x.round for x in capture.launches} == set(TWELVE)
    assert not any(o.round == 7 for o in capture.observations)
    results = pairbench.analyse(capture)
    comparison = results.comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (11, 1)
    assert len(_cell_notes(results.notes)) == 4
    assert results.refusals == ()


def test_the_analysis_notes_each_missing_cell_and_counts_its_round_unpaired(
    tmp_path: Path,
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    results = pairbench.analyse(capture)
    comparison = results.comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (10, 2)
    assert (comparison.outcome, comparison.reason) == ("better", None)
    ident = capture.capture_id
    assert [(n.code, n.message) for n in results.notes] == [
        ("value_not_finite", _cell(ident, "new", 3)),
        ("value_not_finite", _cell(ident, "old", 5)),
    ]
    assert results.refusals == ()


def test_a_missing_cell_of_a_twin_leaves_its_round_out_of_the_floor(tmp_path: Path) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=((4, "newagain", "nan"),)))
    results = pairbench.analyse(capture)
    (row,) = [r for r in results.same_vs_same if r.side == "new"]
    assert row.n == 11
    comparison = results.comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (12, 0)


def test_a_missing_cell_is_named_by_the_label_the_file_gave_its_round(tmp_path: Path) -> None:
    labels = tuple(range(40, 52))
    capture = _lenient(tmp_path, _run(labels, missing=((43, "new", "nan"),)))
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.missing_cells == ((43, "new", "matmul"),)
    expected = [_cell(capture.capture_id, "new", 43, number=4)]
    assert _cell_notes(pairbench.analyse(capture).notes) == expected


def test_the_results_with_missing_cells_are_valid_against_the_schema(tmp_path: Path) -> None:
    from pairbench.results import load_schema

    jsonschema = pytest.importorskip("jsonschema", reason="needs the jsonschema package")
    capture = _lenient(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    document = json.loads(pairbench.render(pairbench.analyse(capture), "json"))
    jsonschema.validate(document, load_schema("results"))
    assert [n["code"] for n in document["notes"]] == ["value_not_finite"] * 2
    assert document["refusals"] == []


def test_pooled_lenient_captures_list_the_cells_of_each(tmp_path: Path) -> None:
    first = _write(tmp_path, _run(TWELVE, missing=((2, "new", "nan"),)), "a.txt")
    second = _write(tmp_path, _run(TWELVE[:-1], missing=((6, "old", "inf"),)), "b.txt")
    a, b = load_captures([first, second], reader="text", strict=False)
    results = pairbench.analyse([a, b])
    assert _cell_notes(results.notes) == [
        _cell(a.capture_id, "new", 2),
        _cell(b.capture_id, "old", 6),
    ]
    comparison = results.comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (21, 2)


def test_a_two_sided_view_keeps_the_missing_cells_of_its_sides_and_rounds(tmp_path: Path) -> None:
    missing = ((3, "new", "nan"), (5, "newagain", "nan"), (8, "old", "nan"))
    capture = _lenient(tmp_path, _run(TWELVE, missing=missing))
    view = project(capture, "new", "old")
    assert view.source is not None and view.source.reader is not None
    assert view.source.reader.missing_cells == ((3, "new", "matmul"), (8, "old", "matmul"))
    assert _cell_notes(view.notes) == [
        _cell(view.capture_id, "new", 3),
        _cell(view.capture_id, "old", 8),
    ]
    assert _cell_notes(pairbench.analyse(view).notes) == _cell_notes(view.notes)


def test_a_view_of_a_capture_read_again_notes_the_cells_a_view_of_the_text_notes(
    tmp_path: Path,
) -> None:
    # Labels 40 to 51 are the capture's rounds 1 to 12; round 44 gives a side two positions,
    # so a two-sided view leaves it out and numbers the rounds after it one lower.
    missing = ((42, "new", "nan"), (44, "old", "nan"), (46, "oldagain", "inf"), (49, "old", "nan"))
    capture = _lenient(tmp_path, _run(tuple(range(40, 52)), missing=missing, contradicted=(44,)))
    ident = capture.capture_id
    assert _cell_notes(capture.notes) == [
        _cell(ident, "new", 42, number=3),
        _cell(ident, "old", 44, number=5),
        _cell(ident, "oldagain", 46, number=7),
        _cell(ident, "old", 49, number=10),
    ]
    written = tmp_path / "capture.jsonl"
    written.write_text("".join(json.dumps(record) + "\n" for record in capture.to_records()))
    (again,) = pairbench.load_capture(written)
    assert again.source is not None and again.source.reader is None
    assert again.notes == capture.notes
    pair, twin = f"{ident}:new:old", f"{ident}:new:newagain"
    for read in (capture, again):
        assert _cell_notes(project(read, "new", "old").notes) == [
            _cell(pair, "new", 42, number=3),
            _cell(pair, "old", 49, number=9),
        ]
        assert _cell_notes(project(read, "new", "newagain").notes) == [
            _cell(twin, "new", 42, number=3)
        ]
        view = project(read, "new", "old")
        assert _cell_notes(pairbench.analyse(view, allow_incomplete=True).notes) == [
            _cell(pair, "new", 42, number=3),
            _cell(pair, "old", 49, number=9),
        ]


def test_a_capture_read_again_prints_the_note_of_each_missing_cell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=((3, "new", "nan"), (6, "old", "inf"))))
    written = tmp_path / "capture.jsonl"
    written.write_text("".join(json.dumps(record) + "\n" for record in capture.to_records()))
    capsys.readouterr()
    pairbench.load_capture(written)
    out, err = capsys.readouterr()
    ident = capture.capture_id
    assert out == ""
    assert err == (
        f"{NOTE}value_not_finite: {_cell(ident, 'new', 3)}\n"
        f"{NOTE}value_not_finite: {_cell(ident, 'old', 6)}\n"
    )


def test_a_note_read_from_a_file_prints_with_its_control_characters_escaped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=((3, "new", "nan"),)))
    shown = _cell(capture.capture_id, "new", 3)
    capsys.readouterr()
    forged = Note(code="value_not_finite", message="x\x1b[2J\r\npairbench: E_USAGE: made-up")
    written = tmp_path / "capture.jsonl"
    records = dataclasses.replace(capture, notes=(*capture.notes, forged)).to_records()
    written.write_text("".join(json.dumps(record) + "\n" for record in records))
    pairbench.load_capture(written)
    assert capsys.readouterr().err == (
        f"{NOTE}value_not_finite: {shown}\n"
        f"{NOTE}value_not_finite: x\\x1b[2J\\r\\npairbench: E_USAGE: made-up\n"
    )


def test_a_cell_note_whose_names_hold_the_words_of_the_note_reads_back(tmp_path: Path) -> None:
    case = "mat'mul of the capture x\" in round 2"
    text = _run(TWELVE, missing=((3, "new", "nan"),)).replace("\tmatmul\t", f"\t{case}\t")
    capture = _lenient(tmp_path, text)
    written = tmp_path / "capture.jsonl"
    written.write_text("".join(json.dumps(record) + "\n" for record in capture.to_records()))
    (again,) = pairbench.load_capture(written)
    view = f"{capture.capture_id}:new:old"
    for read in (capture, again):
        assert _cell_notes(project(read, "new", "old").notes) == [_cell(view, "new", 3, case)]
        assert _cell_notes(project(read, "old", "oldagain").notes) == []


def test_a_note_of_the_code_that_reads_no_cell_stays_in_the_view(tmp_path: Path) -> None:
    capture = _lenient(tmp_path, _run(TWELVE))
    odd = Note(code="value_not_finite", message="a value of a plug-in is not a finite number")
    view = project(dataclasses.replace(capture, notes=(*capture.notes, odd)), "new", "old")
    assert view.notes[-1] == odd


_END = " is not a finite number; the cell is read as missing"


@pytest.mark.parametrize(
    "middle",
    [
        pytest.param("new in round 3 on the case {[]}", id="unhashable-literal"),
        pytest.param("new in round 3 on the case {[1]: 2}", id="unhashable-key"),
        pytest.param("new in round " + "9" * 5000 + " on the case 'matmul'", id="long-round"),
        pytest.param(
            "new in round 3 (the capture's round " + "9" * 5000 + ") on the case 'matmul'",
            id="long-number",
        ),
        pytest.param("new in round 3 on the case '\\d'", id="invalid-escape"),
        pytest.param("new in round 3 on the case " + "(" * 400 + "'a'" + ")" * 400, id="deep"),
        pytest.param("new in round 3 on the case 'a' 'b'", id="two-literals"),
        pytest.param("new in round 3 on the case b'matmul'", id="bytes"),
    ],
)
def test_a_note_of_the_code_that_does_not_read_cleanly_stays_and_raises_nothing(
    tmp_path: Path, middle: str
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE))
    odd = Note(
        code="value_not_finite",
        message=f"the value of {middle} of the capture {capture.capture_id}{_END}",
    )
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        view = project(dataclasses.replace(capture, notes=(*capture.notes, odd)), "new", "old")
    assert [str(w.message) for w in seen] == []
    assert view.notes[-1] == odd


def test_a_capture_written_and_read_again_keeps_the_note_of_each_missing_cell(
    tmp_path: Path,
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=((3, "new", "nan"), (6, "oldagain", "inf"))))
    written = tmp_path / "capture.jsonl"
    written.write_text("".join(json.dumps(record) + "\n" for record in capture.to_records()))
    (again,) = pairbench.load_capture(written)
    assert again.source is not None and again.source.reader is None
    ident = capture.capture_id
    expected = [_cell(ident, "new", 3), _cell(ident, "oldagain", 6)]
    assert _cell_notes(again.notes) == expected
    direct = pairbench.analyse(capture)
    reread = pairbench.analyse(again, allow_incomplete=True)
    for results in (direct, reread):
        assert _cell_notes(results.notes) == expected
        assert results.refusals == ()
    assert [(c.case, c.n_rounds, c.n_unpaired) for c in reread.comparisons] == [
        (c.case, c.n_rounds, c.n_unpaired) for c in direct.comparisons
    ]
    (old,) = [r for r in reread.same_vs_same if r.side == "old"]
    assert old.n == 11


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


def test_a_round_whose_order_contradicts_itself_is_read_as_not_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, contradicted=(4, 9)))
    launches = _launches(capture)
    assert {name: launches[(4, name)] for name in ENTRIES} == dict.fromkeys(ENTRIES)
    assert {name: launches[(9, name)] for name in ENTRIES} == dict.fromkeys(ENTRIES)
    assert all(pos is not None for (r, _), pos in launches.items() if r not in (4, 9))
    message = (
        "rounds 4, 9 of run 0 of rows.txt give a side two positions; their order was read as "
        "not recorded"
    )
    assert [(n.code, n.message) for n in capture.notes] == [("order_contradicted", message)]
    assert capsys.readouterr().err == f"{NOTE}order_contradicted: {message}\n"


def test_a_case_that_uses_a_round_of_unknown_order_gets_no_verdict(tmp_path: Path) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, contradicted=(4,)))
    results = pairbench.analyse(capture)
    comparison = results.comparison("matmul")
    assert (comparison.outcome, comparison.reason) == ("no_verdict", "order_not_recorded")
    assert sum(comparison.order_split) == 11
    interleaved = pairbench.analyse(capture, assume_interleaved=True).comparison("matmul")
    assert (interleaved.outcome, interleaved.reason) == ("better", None)


def test_a_case_whose_only_use_of_that_round_is_a_missing_cell_keeps_its_verdict(
    tmp_path: Path,
) -> None:
    capture = _lenient(tmp_path, _run(TWELVE, missing=((4, "new", "nan"),), contradicted=(4,)))
    comparison = pairbench.analyse(capture).comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (11, 1)
    assert (comparison.outcome, comparison.reason) == ("better", None)
    assert sum(comparison.order_split) == 11


def test_rows_without_a_pass_order_read_leniently_as_strictly(tmp_path: Path) -> None:
    text = _run(TWELVE, order=False)
    strict = TextReader().read(_write(tmp_path, text, "strict.txt"))[0]
    lenient = _lenient(tmp_path, text, "lenient.txt")
    assert set(_launches(strict).values()) == set(_launches(lenient).values()) == {None}
    for capture in (strict, lenient):
        comparison = pairbench.analyse(capture).comparison("matmul")
        assert (comparison.outcome, comparison.reason) == ("no_verdict", "order_not_recorded")
        assert comparison.order_split == (0, 0)


# The three rows of the table of the lenient mode on the text-format page: what each mode makes
# of the input, as (where the strict mode refuses or None, the notes and the verdict) per mode.
THREE_CASES = {
    "not-finite": (
        _run(TWELVE, missing=((3, "new", "nan"),)),
        ("analyse", "E_GRID", [], None),
        (None, None, ["value_not_finite"], ("better", None)),
    ),
    "two-positions": (
        _run(TWELVE, contradicted=(4,)),
        ("read", "E_USAGE", [], None),
        (None, None, ["order_contradicted"], ("no_verdict", "order_not_recorded")),
    ),
    "no-pass-order": (
        _run(TWELVE, order=False),
        (None, None, [], ("no_verdict", "order_not_recorded")),
        (None, None, [], ("no_verdict", "order_not_recorded")),
    ),
}


@pytest.mark.parametrize("name", sorted(THREE_CASES))
@pytest.mark.parametrize("strict", [True, False], ids=["strict", "lenient"])
def test_each_mode_reads_the_three_lenient_inputs_as_the_page_says(
    tmp_path: Path, name: str, strict: bool
) -> None:
    text, in_strict, in_lenient = THREE_CASES[name]
    stage, code, notes, verdict = in_strict if strict else in_lenient
    path = _write(tmp_path, text)
    if stage == "read":
        with pytest.raises(Refusal) as caught:
            pairbench.load_capture(path, reader="text", strict=strict)
        assert caught.value.code == code
        return
    (capture,) = pairbench.load_capture(path, reader="text", strict=strict)
    if stage == "analyse":
        with pytest.raises(Refusal) as caught:
            pairbench.analyse(capture)
        assert caught.value.code == code
        return
    results = pairbench.analyse(capture)
    assert [n.code for n in results.notes] == notes
    comparison = results.comparison("matmul")
    assert (comparison.outcome, comparison.reason) == verdict
    assert results.refusals == ()


# ---------------------------------------------------------------------------
# Choosing the lenient mode
# ---------------------------------------------------------------------------


def test_the_text_reader_found_by_its_sniff_reads_leniently(tmp_path: Path) -> None:
    path = _write(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    (capture,) = pairbench.load_capture(path, strict=False)
    assert capture.source is not None and capture.source.reader is not None
    assert len(capture.source.reader.missing_cells) == 2


def test_a_reader_without_a_lenient_mode_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"t": "header"}\n', "capture.jsonl")
    for reader in ("jsonl", None):
        with pytest.raises(Refusal) as caught:
            pairbench.load_capture(path, reader=reader, strict=False)
        assert (caught.value.code, caught.value.exit_code, caught.value.message) == (
            "E_USAGE",
            2,
            "the capture reader jsonl has no lenient mode; only the text reader reads "
            "capture.jsonl leniently",
        )


def test_strict_is_true_or_false(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        pairbench.load_capture(tmp_path / "rows.txt", strict="no")  # type: ignore[arg-type]
    assert (caught.value.code, caught.value.message) == ("E_USAGE", "strict is true or false")


def test_compare_lenient_lists_the_missing_cells_and_exits_0(tmp_path: Path, cli: Cli) -> None:
    run = cli
    path = _write(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    strict = run("compare", str(path), "--reader", "text")
    assert strict.code == 6
    assert strict.err.splitlines()[-2].startswith("E_GRID: ")
    lenient = run("compare", str(path), "--reader", "text", "--lenient", "--json")
    assert lenient.code == 0
    document = json.loads(lenient.out)
    assert document["refusals"] == []
    assert [n["code"] for n in document["notes"]] == ["value_not_finite"] * 2
    lines = lenient.err.splitlines()
    assert [line.split(": the value")[0] for line in lines[:2]] == [f"{NOTE}value_not_finite"] * 2
    assert sum(line.startswith(f"{NOTE}value_not_finite") for line in lines) == 2
    assert not any(line.startswith("E_") for line in lines)


def test_a_side_whose_every_cell_of_a_case_is_missing_gets_no_verdict_on_it(
    tmp_path: Path,
) -> None:
    gone = tuple((label, "new", "nan") for label in TWELVE)
    capture = _lenient(tmp_path, _run(TWELVE, missing=gone))
    results = pairbench.analyse(capture)
    comparison = results.comparison("matmul")
    assert (comparison.n_rounds, comparison.n_unpaired) == (0, 12)
    assert comparison.outcome == "no_verdict"
    assert len(_cell_notes(results.notes)) == 12
    assert results.refusals == ()


def test_results_with_missing_cells_render_and_read_back(tmp_path: Path, cli: Cli) -> None:
    path = _write(tmp_path, _run(TWELVE, missing=TWO_MISSING))
    out = tmp_path / "out"
    result = cli("compare", str(path), "--reader", "text", "--lenient", "--out", str(out))
    assert result.code == 0
    read = pairbench.load_results(out / "results.json")
    assert read.refusals == ()
    assert [n.code for n in read.notes] == ["value_not_finite"] * 2
    assert read.comparison("matmul").outcome == "better"
    line = "Note value_not_finite: the value of new in round 3 on the case 'matmul'"
    assert line.replace("_", "\\_") in pairbench.render(read, "markdown")
    assert "Refused" not in result.out
    page = pairbench.render(read, "html")
    assert "value_not_finite" in page
    assert "FASTER" in page
