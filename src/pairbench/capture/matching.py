# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The matching reading mode of the text input format, and its two-sided view.

The matching mode reads one or more inputs of the text format as one text and
returns every row it keeps, with its run, its pass order and the line it came
from, instead of a capture per run. It refuses no row and prints nothing: what
it cannot read it counts. The rules it reads by are given on the reference
page of the text format, in the section on the matching mode.

The result types below are frozen. A read is a ``MatchingRead``: its kept
rows (``MatchingRow``) in the order of the text, and one ``MatchingRun`` per
run. ``MatchingRead.two_sided`` gives a ``MatchingView`` of two of its sides,
and ``MatchingView.capture`` gives that view as a capture, which
``pairbench.analyse`` takes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pairbench.capture.reader import read_bytes
from pairbench.capture.text import _CELL_NOTE_END, _row
from pairbench.errors import Refusal
from pairbench.model import (
    NOTE_VALUE_NOT_FINITE,
    Capture,
    Case,
    Note,
    canonical_json,
    kind_of_unit,
    sha256_hex,
)

__all__ = [
    "MatchingRead",
    "MatchingRow",
    "MatchingRun",
    "MatchingView",
    "PoolRow",
    "ViewRow",
]

PoolRow = tuple[str, str, str, str, str]
"""One line of a run that splits on tabs into five fields, each with the white space around
it removed: suite, side, round, case and value, as written."""

ViewOrder = Literal["first, second", "second, first"]
"""Which of the two sides of a view its pass-order line names first."""

BANNER = "## host"
PASS_ORDER = "pass_order="
FIRST_SECOND: ViewOrder = "first, second"
SECOND_FIRST: ViewOrder = "second, first"


@dataclass(frozen=True)
class MatchingRow:
    """One row the matching mode kept.

    ``run`` is the index of its run, from 0 across the whole text. ``round`` is
    the round label as the integer written. ``side``, ``case`` and ``suite``
    are the fields exactly as written. ``value`` is the value as it parsed: a
    number above zero, infinity or NaN. ``pass_order`` is the text of the
    pass-order line in force for the row, or the default order the caller
    gave; ``order_from_line`` says which. ``line`` is the number of the row's
    line in the text the inputs make together, counted from 1.
    """

    run: int
    round: int
    side: str
    case: str
    value: float
    suite: str
    pass_order: str
    order_from_line: bool
    line: int


@dataclass(frozen=True)
class MatchingRun:
    """One run of a read in the matching mode.

    ``index`` counts the runs from 0: there are as many runs as banners, or
    one when the text holds no banner. ``banner_line`` is the number of the
    line that opened the run, or ``None`` for a run 0 of a text without a
    banner.
    ``metadata`` holds the run's metadata lines in order, each split at its
    first ``=`` into the text before it and the text after it, so that the two
    joined by ``=`` give the line as written, and ``metadata_lines`` gives the
    line number of each. ``malformed_rows`` and
    ``kept_rows`` count the run's malformed and kept rows.

    ``pool_rows`` lists every line of the run that splits on tabs into exactly
    five fields, the banner line left out, in the order of the text: kept
    rows, malformed rows, comments and lines of blanks alike. Each field has
    the white space around it removed. The rows are numbered from 0 by their
    place in the list, and ``pool_row_lines`` gives the line number of each.
    """

    index: int
    banner_line: int | None
    metadata: tuple[tuple[str, str], ...]
    metadata_lines: tuple[int, ...]
    malformed_rows: int
    kept_rows: int
    pool_rows: tuple[PoolRow, ...]
    pool_row_lines: tuple[int, ...]

    @property
    def has_pool_rows(self) -> bool:
        """Whether the run holds a line that splits on tabs into five fields."""
        return bool(self.pool_rows)


@dataclass(frozen=True)
class MatchingRead:
    """What a read in the matching mode returns.

    ``rows`` holds the kept rows in the order of the text. ``runs`` holds one
    record per run, in index order, a run without rows included; a text
    without a banner, an empty one included, is one run.
    ``default_order`` is the pass-order text the caller gave for rows that no
    pass-order line orders. ``sha256`` is the hash of the text the inputs make
    together, encoded as UTF-8. ``input_lines`` gives, for each input in the
    order given, the number of the line of that text on which it begins: one
    past the last line for an input that adds no line, as an empty last input
    does. A read built without it is read as one input.
    """

    rows: tuple[MatchingRow, ...]
    runs: tuple[MatchingRun, ...]
    default_order: str
    sha256: str
    input_lines: tuple[int, ...] = ()

    @property
    def run_count(self) -> int:
        """The number of runs."""
        return len(self.runs)

    @property
    def kept_rows(self) -> int:
        """The number of kept rows."""
        return len(self.rows)

    @property
    def malformed_rows(self) -> int:
        """The number of malformed rows over every run."""
        return sum(run.malformed_rows for run in self.runs)

    def two_sided(self, first: str, second: str) -> MatchingView:
        """Return the two-sided view of the sides ``first`` and ``second``.

        A row of either side is kept when the pass-order line in force for it
        names both sides, the names split on white space; the row's order is
        ``"first, second"`` when that line names ``first`` before ``second``,
        and ``"second, first"`` otherwise. A row whose order is the default
        order, or whose line does not name both sides, is left out and
        counted. The rows of every other side are left out. Naming one side
        twice, or a name that is not a text, is refused with ``E_USAGE``.
        """
        if not isinstance(first, str) or not isinstance(second, str):
            raise Refusal("E_USAGE", "a two-sided view names its two sides as texts")
        if first == second:
            raise Refusal("E_USAGE", f"a two-sided view names the side {first!r} twice")
        kept: list[ViewRow] = []
        no_order = other = 0
        for row in self.rows:
            if row.side not in (first, second):
                other += 1
                continue
            names = row.pass_order.split() if row.order_from_line else []
            if first not in names or second not in names:
                no_order += 1
                continue
            order = FIRST_SECOND if names.index(first) < names.index(second) else SECOND_FIRST
            kept.append(ViewRow(row=row, order=order))
        return MatchingView(
            read=self,
            first=first,
            second=second,
            rows=tuple(kept),
            left_out_no_order=no_order,
            left_out_other_sides=other,
        )


@dataclass(frozen=True)
class ViewRow:
    """One row a two-sided view keeps, with the order its pass-order line gives the two sides."""

    row: MatchingRow
    order: ViewOrder


@dataclass(frozen=True)
class MatchingView:
    """A two-sided view of a read in the matching mode.

    ``rows`` holds the kept rows of the sides ``first`` and ``second`` in the
    order of the text. ``left_out_no_order`` counts the rows of the two sides
    left out because no pass-order line of their run named both sides before
    them; ``left_out_other_sides`` counts the rows of every other side.
    """

    read: MatchingRead
    first: str
    second: str
    rows: tuple[ViewRow, ...]
    left_out_no_order: int
    left_out_other_sides: int

    def capture(self, *, unit: str = "ns", better: Literal["lower", "higher"] = "lower") -> Capture:
        """Return the view as one capture, for ``pairbench.analyse``.

        A round of the capture is a run index and a round label together: the
        same label in two runs makes two rounds. The capture numbers its
        rounds 1, 2, 3 and on in the order of run index, then label. A cell,
        one side in one round on one case, given more than once takes the
        value of its last row, whatever pass order each row carries. A round
        that holds kept rows of one side only gives no pair and is left out.
        The order of a round is the order of the rows that give its cells: the
        side their lines name first ran first. A round whose cells come from
        rows of both orders, as when a reversed pass stops inside a round or
        gives only some of its cells, has no recorded order, and
        ``pairbench.analyse`` reads it as it reads any round whose order was
        not recorded. ``second`` is the baseline. Every case is measured in
        ``unit``, and ``better`` says which direction is better; the metadata
        of the runs is not consulted.

        A cell whose value is not finite is a missing cell: its side keeps its
        place in the round, the cell has no value, and the capture holds one
        ``value_not_finite`` note for it, which names the side, the round by
        its label and the index of its run, the capture's number of the round
        when it is not the label, and the case; this call prints nothing. A view with no
        round that holds both sides, a side name that a capture cannot hold
        (one with ``~`` or ``=``, say), and a unit or a direction that is not
        one, a unit that is not UTF-8 text included, are refused with
        ``E_USAGE``. A case id that ends like the mark a
        run adds to a name whose cut dropped words (`` +`` and eight hex
        digits) is kept, and ``pairbench.analyse`` refuses the capture that
        holds it with ``E_USAGE``.
        """
        if not isinstance(unit, str) or not unit:
            raise Refusal("E_USAGE", "a unit is a text that is not empty")
        try:
            unit.encode("utf-8")
        except UnicodeEncodeError:
            raise Refusal("E_USAGE", f"the unit {unit!r} is not UTF-8 text") from None
        if better not in ("lower", "higher"):
            raise Refusal("E_USAGE", f"better is lower or higher, not {better!r}")
        return _view_capture(self, unit, better)


def read(inputs: str | Path | Sequence[str | Path], *, default_order: str) -> MatchingRead:
    """Read inputs of the text format in the matching mode; see ``pairbench.read_text_matching``."""
    if not isinstance(default_order, str):
        raise Refusal("E_USAGE", "the default order is a text")
    if isinstance(inputs, str | Path):
        given: list[object] = [inputs]
    elif isinstance(inputs, Sequence) and not isinstance(inputs, bytes | bytearray):
        given = list(inputs)
    else:
        raise Refusal("E_USAGE", "the matching mode reads a Path, a text or a list of them")
    if not given:
        raise Refusal("E_USAGE", "the matching mode reads one input or more")
    texts = [_input_text(item) for item in given]
    text = "\n".join(texts)
    starts: list[int] = []
    offset = 0
    for written in texts:
        starts.append(offset)
        offset += len(written) + 1
    return _read_text(text, default_order, starts)


def _input_text(item: object) -> str:
    """The text of one input: a ``Path`` is read as a UTF-8 file, a ``str`` is the text."""
    if isinstance(item, str):
        return item
    if not isinstance(item, Path):
        raise Refusal("E_USAGE", f"an input is a Path or a text, not {type(item).__name__}")
    data = read_bytes(item)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal("E_USAGE", f"{item.name} is not UTF-8 text: {exc}") from exc


@dataclass
class _RunLines:
    """What the lines of one run said, while the text is read."""

    banner_line: int | None = None
    metadata: list[tuple[str, str]] = field(default_factory=list)
    metadata_lines: list[int] = field(default_factory=list)
    malformed: int = 0
    kept: int = 0
    pool_rows: list[PoolRow] = field(default_factory=list)
    pool_row_lines: list[int] = field(default_factory=list)

    def freeze(self, index: int) -> MatchingRun:
        return MatchingRun(
            index=index,
            banner_line=self.banner_line,
            metadata=tuple(self.metadata),
            metadata_lines=tuple(self.metadata_lines),
            malformed_rows=self.malformed,
            kept_rows=self.kept,
            pool_rows=tuple(self.pool_rows),
            pool_row_lines=tuple(self.pool_row_lines),
        )


def _input_lines(text: str, starts: Sequence[int]) -> tuple[int, ...]:
    """Return the number of the line of ``text`` on which each input begins.

    ``starts`` gives the place of the first character of each input in ``text``. The
    newline that joins two inputs ends a line, so every input begins a line, or begins
    one past the last line when it adds none.
    """
    begins: list[int] = []
    lines = text.splitlines(keepends=True)
    number, offset = 1, 0
    for start in starts:
        while number <= len(lines) and offset < start:
            offset += len(lines[number - 1])
            number += 1
        begins.append(number)
    return tuple(begins)


def _read_text(text: str, default_order: str, starts: Sequence[int] = (0,)) -> MatchingRead:
    runs = [_RunLines()]
    rows: list[MatchingRow] = []
    order, from_line = default_order, False
    banners = 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        current = runs[-1]
        if stripped.startswith(BANNER):
            banners += 1
            if banners > 1:
                current = _RunLines()
                runs.append(current)
            current.banner_line = number
            order, from_line = default_order, False
            continue
        fields = line.split("\t")
        if len(fields) == 5:
            current.pool_rows.append(
                (
                    fields[0].strip(),
                    fields[1].strip(),
                    fields[2].strip(),
                    fields[3].strip(),
                    fields[4].strip(),
                )
            )
            current.pool_row_lines.append(number)
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" not in stripped and "=" in stripped:
            key, _, written = line.partition("=")
            current.metadata.append((key, written))
            current.metadata_lines.append(number)
            if stripped.startswith(PASS_ORDER):
                named = stripped[len(PASS_ORDER) :].strip()
                order, from_line = (named, True) if named else (default_order, False)
            continue
        row = _row(fields, strict=False) if len(fields) == 5 else None
        if row is None or row[4] <= 0:
            current.malformed += 1
            continue
        suite, side, round_, case, value = row
        current.kept += 1
        rows.append(
            MatchingRow(
                run=len(runs) - 1,
                round=round_,
                side=side,
                case=case,
                value=value,
                suite=suite,
                pass_order=order,
                order_from_line=from_line,
                line=number,
            )
        )
    return MatchingRead(
        rows=tuple(rows),
        runs=tuple(run.freeze(index) for index, run in enumerate(runs)),
        default_order=default_order,
        sha256=hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(),
        input_lines=_input_lines(text, starts),
    )


def _view_capture(view: MatchingView, unit: str, better: Literal["lower", "higher"]) -> Capture:
    """The capture of a view; see ``MatchingView.capture``."""
    first, second = view.first, view.second
    Round = tuple[int, int]
    cells: dict[tuple[Round, str, str], ViewRow] = {}
    sides_in: dict[Round, set[str]] = {}
    for view_row in view.rows:
        row = view_row.row
        key = (row.run, row.round)
        cells[(key, row.side, row.case)] = view_row
        sides_in.setdefault(key, set()).add(row.side)
    paired = sorted(key for key, names in sides_in.items() if len(names) == 2)
    if not paired:
        raise Refusal(
            "E_USAGE",
            f"the two-sided view of {first!r} and {second!r} holds no round with both sides",
        )
    numbers = {key: number for number, key in enumerate(paired, start=1)}
    # The orders of the rows that give each round's cells: a round with two has no order.
    orders: dict[Round, set[ViewOrder]] = {}
    for (key, _side, _case), view_row in cells.items():
        orders.setdefault(key, set()).add(view_row.order)
    positions: dict[tuple[int, str], int] = {}
    for key, number in numbers.items():
        if len(orders[key]) != 1:
            continue
        first_pos = 1 if orders[key] == {FIRST_SECOND} else 2
        positions[(number, first)] = first_pos
        positions[(number, second)] = 3 - first_pos
    kept = [
        (numbers[key], side, case, view_row.row.value)
        for (key, side, case), view_row in cells.items()
        if key in numbers
    ]
    case_ids = list(dict.fromkeys(case for _number, _side, case, _value in kept))
    capture = Capture.from_rows(
        [
            (number, side, case, value if math.isfinite(value) else 1.0)
            for number, side, case, value in kept
        ],
        sides=[first, second],
        positions=positions,
        cases=[
            Case(id=case, metric="value", unit=unit, better=better, kind=kind_of_unit(unit))
            for case in case_ids
        ],
        unit=unit,
    )
    capture_id = (
        "matching-"
        + sha256_hex(canonical_json([view.read.sha256, first, second, unit, better]))[:12]
    )
    missing = [
        (number, side, case) for number, side, case, value in kept if not math.isfinite(value)
    ]
    rounds = {number: key for key, number in numbers.items()}
    notes = tuple(
        _missing_cell_note(capture_id, rounds[number], number, side, case)
        for number, side, case in missing
    )
    absent = set(missing)
    return dataclasses.replace(
        capture,
        capture_id=capture_id,
        header=dataclasses.replace(capture.header, capture_id=capture_id),
        observations=tuple(
            o for o in capture.observations if (o.round, o.name, o.case) not in absent
        ),
        notes=(*capture.notes, *notes),
    )


def _missing_cell_note(
    capture_id: str, round_: tuple[int, int], number: int, side: str, case: str
) -> Note:
    """The note of one missing cell of a view's capture.

    It names the side, the round by its label and the index of its run, as the
    text gives them, the capture's number of the round when it is not the
    label, and the case.
    """
    run, label = round_
    numbered = f" (the capture's round {number})" if number != label else ""
    return Note(
        code=NOTE_VALUE_NOT_FINITE,
        message=(
            f"the value of {side} in round {label} of run {run}{numbered} on the case "
            f"{case!r} of the capture {capture_id}{_CELL_NOTE_END}"
        ),
    )
