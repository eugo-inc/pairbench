# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The text input format: runs, comments, metadata, pass order, twins, malformed rows, project."""

from __future__ import annotations

from pathlib import Path

import pytest

import pairbench
from pairbench import registry
from pairbench.capture.text import TextReader, project
from pairbench.errors import EXIT_ANALYSIS, EXIT_USAGE, Refusal
from pairbench.model import NOTE_MALFORMED_ROWS, Capture

EXAMPLE = (
    "## host\n"
    "unit=ns\n"
    "sides=new old\n"
    "pass_order=new old\n"
    "suite\tnew\t1\tmatmul\t1920000000\n"
    "suite\told\t1\tmatmul\t2410000000\n"
    "pass_order=old new\n"
    "suite\told\t2\tmatmul\t2395000000\n"
    "suite\tnew\t2\tmatmul\t1911000000\n"
)


def _read(tmp_path: Path, text: str, name: str = "rows.txt") -> list[Capture]:
    path = tmp_path / name
    path.write_text(text)
    return TextReader().read(path)


def _positions(capture: Capture) -> dict[tuple[int, str], int | None]:
    return {(x.round, x.name): x.pos for x in capture.launches}


def _values(capture: Capture) -> dict[tuple[int, str, str], float]:
    return {(o.round, o.name, o.case): o.value for o in capture.observations}


def test_the_example_of_the_format(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, EXAMPLE)
    assert [s.name for s in capture.sides] == ["new", "old"]
    assert [s.role for s in capture.sides] == ["subject", "baseline"]
    assert {s.kind for s in capture.sides} == {"rows"}
    assert _positions(capture) == {(1, "new"): 1, (1, "old"): 2, (2, "old"): 1, (2, "new"): 2}
    assert _values(capture) == {
        (1, "new", "matmul"): 1920000000,
        (1, "old", "matmul"): 2410000000,
        (2, "old", "matmul"): 2395000000,
        (2, "new", "matmul"): 1911000000,
    }
    (case,) = capture.cases
    assert (case.id, case.unit, case.kind, case.better, case.primary) == (
        "matmul",
        "ns",
        "time",
        "lower",
        True,
    )
    assert {o.suite for o in capture.observations} == {"suite"}
    assert capture.complete
    assert capture.lineup is not None
    assert capture.lineup.names == ("new", "old")
    assert capture.capture_id.startswith("text-")
    assert capture.source is not None
    info = capture.source.reader
    assert info is not None
    assert info.reader == "text"
    assert info.run_index == 0
    assert info.metadata == (
        ("unit", "ns"),
        ("sides", "new old"),
        ("pass_order", "new old"),
        ("pass_order", "old new"),
    )
    assert info.sides_declared == ("new", "old")
    assert info.sides_observed == ("new", "old")
    assert (info.malformed_rows, info.comments, info.one_sided_keys) == (0, 0, 0)


def test_comments_are_counted_and_section_markers_are_not(tmp_path: Path) -> None:
    text = (
        "# a comment\n"
        "## host\n"
        "## a section marker\n"
        "   ## an indented section marker\n"
        "# a comment with = in it\n"
        "  # an indented comment\twith a tab\tand\tfive\tfields\n"
        "#\tnew\t1\tmatmul\t5\n"
        "a\tnew\t1\tmatmul\t5\n"
        "a\told\t1\tmatmul\t6\n"
    )
    (capture,) = _read(tmp_path, text)
    assert capture.source is not None
    info = capture.source.reader
    assert info is not None
    assert info.comments == 4
    assert info.malformed_rows == 0
    assert info.metadata == ()
    assert len(capture.observations) == 2


def test_malformed_rows_are_counted_reported_and_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (
        "## host\n"
        "a\tnew\t1\tmatmul\t5\n"
        "a\told\t1\tmatmul\t6\n"
        "a\tnew\t2\tmatmul\n"
        "a\tnew\t2\tmatmul\t5\textra\n"
        "a\tnew\tx\tmatmul\t5\n"
        "a\tnew\t2\tmatmul\tfast\n"
        "a\tnew\t2\tmatmul\tnan\n"
        "a\tnew\t2\tmatmul\tinf\n"
        "a\tnew\t1.5\tmatmul\t5\n"
        "a line with no tab and no equals sign\n"
    )
    (capture,) = _read(tmp_path, text, name="bad.txt")
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.malformed_rows == 8
    assert len(capture.observations) == 2
    assert [(n.code, n.message) for n in capture.notes] == [
        (NOTE_MALFORMED_ROWS, "8 malformed rows skipped in run 0 of bad.txt")
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "pairbench: note: malformed_rows: 8 malformed rows skipped in run 0 of bad.txt\n"
    )


def test_a_value_of_zero_or_less_is_kept(tmp_path: Path) -> None:
    text = "## host\na\tnew\t1\tmatmul\t0\na\told\t1\tmatmul\t-2.5\n"
    (capture,) = _read(tmp_path, text)
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.malformed_rows == 0
    assert _values(capture) == {(1, "new", "matmul"): 0.0, (1, "old", "matmul"): -2.5}
    assert capture.notes == ()


def test_the_same_cell_twice_is_refused(tmp_path: Path) -> None:
    text = "## host\na\tnew\t1\tmatmul\t5\nb\tnew\t1\tmatmul\t6\n"
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, text)
    assert caught.value.code == "E_GRID"
    assert caught.value.exit_code == EXIT_ANALYSIS


def test_the_suite_does_not_change_the_case(tmp_path: Path) -> None:
    text = "## host\nfirst\tnew\t1\tmatmul\t5\nsecond\told\t1\tmatmul\t6\n"
    (capture,) = _read(tmp_path, text)
    assert [c.id for c in capture.cases] == ["matmul"]
    assert {(o.name, o.suite) for o in capture.observations} == {
        ("new", "first"),
        ("old", "second"),
    }


def test_each_banner_begins_a_run(tmp_path: Path) -> None:
    text = (
        "## host\nunit=ms\na\tnew\t1\tmatmul\t5\na\told\t1\tmatmul\t6\n"
        "## host second machine\nunit=s\na\tnew\t1\tfft\t7\na\told\t1\tfft\t8\n"
    )
    first, second = _read(tmp_path, text)
    assert first.source is not None and second.source is not None
    assert first.source.reader is not None and second.source.reader is not None
    assert (first.source.reader.run_index, second.source.reader.run_index) == (0, 1)
    assert first.capture_id != second.capture_id
    assert [c.id for c in first.cases] == ["matmul"]
    assert [c.unit for c in second.cases] == ["s"]


def test_rows_before_the_first_banner_form_run_zero(tmp_path: Path) -> None:
    text = "a\tnew\t1\tmatmul\t5\na\told\t1\tmatmul\t6\n## host\na\tnew\t1\tfft\t7\n"
    first, second = _read(tmp_path, text)
    assert [c.id for c in first.cases] == ["matmul"]
    assert [c.id for c in second.cases] == ["fft"]


def test_lines_before_the_first_banner_without_a_data_row_form_no_run(tmp_path: Path) -> None:
    text = (
        "## fingerprints\n"
        "tool.version=1\n"
        "# made-up preamble\n"
        "## host\n"
        "a\tnew\t1\tmatmul\t5\n"
        "a\told\t1\tmatmul\t6\n"
    )
    (capture,) = _read(tmp_path, text)
    assert [s.name for s in capture.sides] == ["new", "old"]
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.run_index == 0
    assert capture.source.reader.metadata == ()
    assert capture.source.reader.comments == 1


@pytest.mark.parametrize(
    "preamble",
    ["suite\tside\tround\tcase\tvalue\n", "Made-up title of a table\n", "a\tnew\tx\tmatmul\t5\n"],
)
def test_a_malformed_line_before_the_first_banner_forms_no_run_and_is_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], preamble: str
) -> None:
    text = preamble + "## host\npass_order=new old\na\tnew\t1\tmatmul\t5\na\told\t1\tmatmul\t6\n"
    (capture,) = _read(tmp_path, text, name="titled.txt")
    assert [s.name for s in capture.sides] == ["new", "old"]
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.run_index == 0
    assert capture.source.reader.malformed_rows == 1
    assert len(capture.observations) == 2
    assert [(n.code, n.message) for n in capture.notes] == [
        (NOTE_MALFORMED_ROWS, "1 malformed row skipped in run 0 of titled.txt")
    ]
    assert capsys.readouterr().err == (
        "pairbench: note: malformed_rows: 1 malformed row skipped in run 0 of titled.txt\n"
    )


def test_compare_reads_a_file_whose_column_header_stands_above_the_first_banner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pairbench.cli.main import main

    monkeypatch.chdir(tmp_path)
    lines = ["suite\tside\tround\tcase\tvalue", "## host", "unit=s"]
    for r in range(1, 9):
        order = ("new", "old") if r % 2 else ("old", "new")
        lines.append("pass_order=" + " ".join(order))
        lines += [f"a\t{side}\t{r}\tmatmul\t{1.0 + r / 64 + (side == 'old')}" for side in order]
    rows = tmp_path / "titled.txt"
    rows.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["compare", str(rows), "--reader", "text"]) == 0
    captured = capsys.readouterr()
    assert "E_USAGE" not in captured.err
    assert (
        "pairbench: note: malformed_rows: 1 malformed row skipped in run 0 of titled.txt\n"
    ) in captured.err


def test_rounds_numbered_from_zero_all_pair(tmp_path: Path) -> None:
    rows = "".join(
        f"a\t{side}\t{round_}\tmatmul\t{5 + round_}\n"
        for round_ in range(8)
        for side in ("new", "old")
    )
    (capture,) = _read(tmp_path, "## host\npass_order=new old\n" + rows)
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.malformed_rows == 0
    assert capture.notes == ()
    # The file's rounds 0 to 7 are the capture's rounds 1 to 8, in order.
    assert sorted({o.round for o in capture.observations}) == [1, 2, 3, 4, 5, 6, 7, 8]
    assert _values(capture)[(1, "new", "matmul")] == 5.0
    assert _values(capture)[(8, "old", "matmul")] == 12.0
    assert len(project(capture, "new", "old").observations) == 16


def test_negative_round_numbers_keep_their_order_and_pairing(tmp_path: Path) -> None:
    text = (
        "## host\npass_order=old new\n"
        "a\tnew\t-2\tm\t5\na\told\t-2\tm\t6\n"
        "a\told\t3\tm\t7\na\tnew\t3\tm\t8\n"
    )
    (capture,) = _read(tmp_path, text)
    assert _values(capture) == {
        (1, "new", "m"): 5.0,
        (1, "old", "m"): 6.0,
        (2, "old", "m"): 7.0,
        (2, "new", "m"): 8.0,
    }
    assert _positions(capture) == {(1, "old"): 1, (1, "new"): 2, (2, "old"): 1, (2, "new"): 2}


def test_rounds_from_one_are_kept_as_written(tmp_path: Path) -> None:
    text = "## host\na\tnew\t1\tm\t5\na\told\t1\tm\t6\na\tnew\t2\tm\t7\na\told\t2\tm\t8\n"
    (capture,) = _read(tmp_path, text)
    assert sorted({o.round for o in capture.observations}) == [1, 2]


def test_rounds_from_any_number_are_numbered_from_one_in_their_order(tmp_path: Path) -> None:
    rows = "".join(
        f"a\t{side}\t{label}\tm\t{value}\n"
        for label, value in ((3, 5), (10, 6), (4, 7))
        for side in ("new", "old")
    )
    (capture,) = _read(tmp_path, "## host\n" + rows)
    assert _values(capture) == {
        (1, "new", "m"): 5.0,
        (1, "old", "m"): 5.0,
        (2, "new", "m"): 7.0,
        (2, "old", "m"): 7.0,
        (3, "new", "m"): 6.0,
        (3, "old", "m"): 6.0,
    }


def test_a_round_one_side_lacks_is_refused_with_the_label_the_file_gave_it(
    tmp_path: Path,
) -> None:
    rows = "".join(
        f"a\t{side}\t{label}\tm\t{label}\n"
        for label in (10, 20, 30, 40, 50, 60, 70, 80)
        for side in ("new", "old")
        if (label, side) != (30, "old")
    )
    (capture,) = _read(tmp_path, "## host\n" + rows)
    assert capture.source is not None
    assert capture.source.round_labels == (10, 20, 30, 40, 50, 60, 70, 80)
    with pytest.raises(Refusal) as caught:
        pairbench.analyse([capture])
    assert (caught.value.code, caught.value.exit_code) == ("E_GRID", EXIT_ANALYSIS)
    assert caught.value.message.endswith("does not match its lineup: missing 30 old")
    assert caught.value.detail["missing"] == [[30, "old"]]


def test_a_two_sided_view_keeps_the_labels_of_the_rounds_it_keeps(tmp_path: Path) -> None:
    rows = "".join(
        f"pass_order=new mid old\na\tnew\t{label}\tm\t1\na\tmid\t{label}\tm\t2\n"
        + (f"a\told\t{label}\tm\t3\n" if label != 30 else "")
        for label in (10, 20, 30, 40)
    )
    (capture,) = _read(tmp_path, "## host\n" + rows)
    view = project(capture, "new", "old")
    assert view.source is not None
    assert view.source.round_labels == (10, 20, 40)


def test_a_two_sided_view_of_rows_numbered_from_one_keeps_the_labels_of_its_rounds() -> None:
    # Rows labelled 1 to 4 need no labels of their own; old has no recorded
    # order in round 3, so the view keeps rounds 1, 2 and 4 as its 1, 2, 3.
    sides = ("new", "mid", "old")
    rows = [
        (label, side, "m", float(pos + 1))
        for label in range(1, 5)
        for pos, side in enumerate(sides)
    ]
    positions = {
        (label, side): pos + 1
        for label in range(1, 5)
        for pos, side in enumerate(sides)
        if (label, side) != (3, "old")
    }
    capture = Capture.from_rows(rows, sides=list(sides), positions=positions)
    assert capture.source is None
    view = project(capture, "new", "old")
    assert view.lineup is not None and view.lineup.rounds == 3
    assert view.source is not None
    assert view.source.round_labels == (1, 2, 4)


def test_a_data_row_whose_case_name_holds_an_equals_sign_stays_a_data_row(
    tmp_path: Path,
) -> None:
    (capture,) = _read(tmp_path, "## host\na\tnew\t1\tsize=4\t5\na\told\t1\tsize=4\t6\n")
    assert _values(capture) == {(1, "new", "size=4"): 5.0, (1, "old", "size=4"): 6.0}
    assert capture.source is not None and capture.source.reader is not None
    assert capture.source.reader.metadata == ()


def test_a_section_marker_that_is_not_a_banner_starts_no_run(tmp_path: Path) -> None:
    text = "## host\na\tnew\t1\tm\t5\n##host\n## hostname\na\told\t1\tm\t6\n"
    (capture,) = _read(tmp_path, text)
    assert len(capture.observations) == 2


def test_better_and_unit_set_the_cases(tmp_path: Path) -> None:
    text = "## host\nunit=ops\nbetter=higher\na\tnew\t1\trate\t5\na\told\t1\trate\t6\n"
    (capture,) = _read(tmp_path, text)
    (case,) = capture.cases
    assert (case.unit, case.better, case.kind) == ("ops", "higher", "other")


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_a_unit_of_time_gives_a_time_case(tmp_path: Path, unit: str) -> None:
    (capture,) = _read(tmp_path, f"## host\nunit={unit}\na\tnew\t1\tm\t5\n")
    assert capture.cases[0].kind == "time"


def test_a_better_that_is_neither_direction_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, "## host\nbetter=none\na\tnew\t1\tm\t5\n")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE


def test_two_units_in_one_run_are_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, "## host\nunit=s\nunit=ms\na\tnew\t1\tm\t5\n")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_twin_is_declared_with_a_metadata_line(tmp_path: Path) -> None:
    text = (
        "## host\ntwin=again:new\n"
        "pass_order=new again old\n"
        "a\tnew\t1\tm\t5\na\tagain\t1\tm\t5.1\na\told\t1\tm\t6\n"
    )
    (capture,) = _read(tmp_path, text)
    assert [(s.name, s.role, s.twin_of) for s in capture.sides] == [
        ("new", "subject", None),
        ("again", "twin", "new"),
        ("old", "baseline", None),
    ]
    assert _positions(capture) == {(1, "new"): 1, (1, "again"): 2, (1, "old"): 3}


def test_a_twin_of_an_absent_side_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, "## host\ntwin=again:gone\na\tnew\t1\tm\t5\na\tagain\t1\tm\t5\n")
    assert caught.value.code == "E_TWIN_ORPHAN"
    assert caught.value.exit_code == EXIT_ANALYSIS


def test_rows_before_any_pass_order_have_no_position(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, "## host\na\tnew\t1\tm\t5\na\told\t1\tm\t6\n")
    assert _positions(capture) == {(1, "new"): None, (1, "old"): None}
    assert not capture.order_recorded


def test_keys_that_hold_one_side_only_are_counted(tmp_path: Path) -> None:
    text = "## host\na\tnew\t1\tm\t5\na\told\t1\tm\t6\na\tnew\t2\tm\t5\na\told\t3\tk\t1\n"
    (capture,) = _read(tmp_path, text)
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.one_sided_keys == 2


def test_a_declared_side_comes_first_and_undeclared_sides_follow(tmp_path: Path) -> None:
    text = "## host\nsides=old\na\tnew\t1\tm\t5\na\told\t1\tm\t6\n"
    (capture,) = _read(tmp_path, text)
    assert [(s.name, s.role) for s in capture.sides] == [("old", "subject"), ("new", "baseline")]
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.sides_declared == ("old",)
    assert capture.source.reader.sides_observed == ("new", "old")


def test_a_side_name_the_model_refuses_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, "## host\na\tnew~same\t1\tm\t5\n", name="names.txt")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert caught.value.message.startswith("line 2 of names.txt")


def test_a_side_at_two_positions_in_one_round_is_refused(tmp_path: Path) -> None:
    text = "## host\npass_order=new old\na\tnew\t1\tm\t5\npass_order=old new\na\tnew\t1\tk\t5\n"
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, text)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_run_without_a_side_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        _read(tmp_path, "## host\nunit=s\n")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_sniff_and_the_registry(tmp_path: Path) -> None:
    path = tmp_path / "rows.txt"
    path.write_text(EXAMPLE)
    reader = TextReader()
    assert reader.sniff(path, EXAMPLE.encode()) is True
    assert reader.sniff(path, b"a\tnew\t1\tm\t5\n") is True
    assert reader.sniff(path, b'{"t":"header"}\n') is False
    assert reader.sniff(path, b"\xff\xfe") is False
    assert isinstance(registry.capture_reader("text"), TextReader)
    (capture,) = pairbench.load_capture(path)
    assert capture.source is not None
    assert capture.source.reader is not None
    assert capture.source.reader.reader == "text"


THREE = (
    "## host\nunit=s\n"
    "pass_order=a b c\n"
    "x\ta\t1\tm\t1\nx\tb\t1\tm\t2\nx\tc\t1\tm\t3\n"
    "pass_order=c a\n"
    "x\tc\t2\tm\t3\nx\ta\t2\tm\t1\nx\tb\t2\tm\t2\n"
    "pass_order=b c a\n"
    "x\tb\t3\tm\t2\nx\tc\t3\tm\t3\nx\ta\t3\tm\t1\n"
)


def test_project_keeps_the_rounds_that_name_both_sides(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, THREE)
    view = project(capture, "a", "b")
    assert [(s.name, s.role) for s in view.sides] == [("a", "subject"), ("b", "baseline")]
    assert view.lineup is not None
    assert view.lineup.names == ("a", "b")
    assert view.lineup.rounds == 2
    assert _positions(view) == {(1, "a"): 1, (1, "b"): 2, (2, "b"): 1, (2, "a"): 2}
    assert _values(view) == {
        (1, "a", "m"): 1,
        (1, "b", "m"): 2,
        (2, "b", "m"): 2,
        (2, "a", "m"): 1,
    }
    assert view.end is not None
    assert view.end.rounds_completed == 2


def test_project_keeps_the_relative_order_of_the_two(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, THREE)
    view = project(capture, "c", "a")
    assert _positions(view) == {
        (1, "a"): 1,
        (1, "c"): 2,
        (2, "c"): 1,
        (2, "a"): 2,
        (3, "c"): 1,
        (3, "a"): 2,
    }


def test_project_refuses_one_side_named_twice(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, THREE)
    with pytest.raises(Refusal) as caught:
        project(capture, "a", "a")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE


def test_project_refuses_a_name_that_is_no_side(tmp_path: Path) -> None:
    (capture,) = _read(tmp_path, THREE)
    with pytest.raises(Refusal) as caught:
        project(capture, "a", "zz")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_project_of_a_side_and_its_twin(tmp_path: Path) -> None:
    text = (
        "## host\ntwin=again:new\npass_order=again new old\n"
        "a\tnew\t1\tm\t5\na\tagain\t1\tm\t5\na\told\t1\tm\t6\n"
    )
    (capture,) = _read(tmp_path, text)
    view = project(capture, "again", "new")
    assert [(s.name, s.role, s.twin_of) for s in view.sides] == [
        ("new", "baseline", None),
        ("again", "twin", "new"),
    ]
    assert _positions(view) == {(1, "again"): 1, (1, "new"): 2}
