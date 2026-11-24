# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pool checks of a read in the matching mode of the text format.

The runs of one ``MatchingRead`` pool unless one is a copy of another. Three
checks look for copies, in this order, and nothing else refuses a pool of
such runs: not two runs of one file, not runs that time other cases, not a
side or a unit that one run names and another does not.

1. Identical written rows (``identical_written_rows``): two runs whose lists
   of five-field lines are equal.
2. A written stretch (``written_stretch``): a run whose list of five-field
   lines is a stretch of another run's, its last line whole or torn.
3. The copy checks of ``pairbench.analyse`` over the kept rows of each run,
   compared by side, case, value and where each round begins, two NaN values
   equal (``identical_rows``, ``truncated_copy``). They take each pair of runs
   in index order and compare its rows in the order of the text, then in
   the order the rows ran, as the run's pass-order and ``sides=`` lines in
   this mode give it, and as those of its lines without a tab give it, then
   in the order a text capture of each run, or of the one part of it that
   holds every kept row of it, holds them, and then in those orders again
   with the rows whose value is not finite left out, as a strict and as a
   lenient text capture leave them out, before the next pair; a form is
   compared only where its rows differ, for a run of the pair, from those of
   a form compared before, and a pair is listed once, at the first form that
   finds a copy. Then the parts of one run that text
   captures read as runs of their own (``_parts``) are compared in the same
   forms, with each other and with the runs of one part, a pair of two runs
   refused before left out; such a refusal's ``detail`` gives the line on
   which each part begins under ``lines``. So a copy that is refused when its
   runs are read as text captures is refused here too, but for one that text
   captures find only with the rows whose value is zero or less, which this
   mode reads as malformed, two runs without a row a text capture keeps,
   which text captures find identical, and a text capture that a line this
   mode alone takes for a banner splits into two runs.

The first two compare ``MatchingRun.pool_rows``: every line of a run that
splits on tabs into five fields, the banner left out, each field stripped,
compared as text and numbered from 0 in that list. A run without such a line
is left out of them, and a run without a kept row is left out of the third.
Each refusal's ``detail`` names its check under ``check``.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterator, Sequence
from typing import Any

from pairbench.capture.matching import MatchingRead, MatchingRow, MatchingRun, PoolRow
from pairbench.errors import EXIT_ANALYSIS, Refusal
from pairbench.stats.analyse import _is_copy, _Row, _same_run

__all__ = [
    "CHECK_IDENTICAL_ROWS",
    "CHECK_IDENTICAL_WRITTEN_ROWS",
    "CHECK_TRUNCATED_COPY",
    "CHECK_WRITTEN_STRETCH",
    "first_refusal",
    "pool_refusals",
]

CHECK_IDENTICAL_WRITTEN_ROWS = "identical_written_rows"
CHECK_WRITTEN_STRETCH = "written_stretch"
CHECK_IDENTICAL_ROWS = "identical_rows"
CHECK_TRUNCATED_COPY = "truncated_copy"


def _refuse(code: str, message: str, **detail: Any) -> Refusal:
    return Refusal(code, message, exit_code=EXIT_ANALYSIS, detail=detail)


def _written(read: MatchingRead) -> list[tuple[int, tuple[PoolRow, ...]]]:
    """Return the index and the five-field lines of every run that holds such a line."""
    return [(run.index, run.pool_rows) for run in read.runs if run.pool_rows]


def _identical_written(written: Sequence[tuple[int, tuple[PoolRow, ...]]]) -> Iterator[Refusal]:
    """Yield, for each run whose lines repeat an earlier run's, a refusal naming the earliest."""
    first_with: dict[tuple[PoolRow, ...], int] = {}
    for index, rows in written:
        earlier = first_with.setdefault(rows, index)
        if earlier != index:
            yield _refuse(
                "E_POOL_IDENTICAL_ROWS",
                f"the runs {earlier} and {index} hold the same {len(rows)} rows as written",
                check=CHECK_IDENTICAL_WRITTEN_ROWS,
                runs=[earlier, index],
                rows=len(rows),
            )


def _stretch_at(short: Sequence[PoolRow], long: Sequence[PoolRow]) -> tuple[int, bool] | None:
    """Return where ``short`` first sits in ``long`` as a stretch, and whether its last row is torn.

    ``short`` sits at row ``p`` of ``long`` when every row of ``short`` but its
    last equals the rows of ``long`` from ``p`` on, and ``long`` has a row
    where the last row of ``short`` falls; a row of one sits where it equals
    that row. The last row is torn when it differs from that row. A stretch
    as long as ``long`` whose last row is whole is ``long`` itself, and is no
    match here.
    """
    width = len(short)
    for at in range(len(long) - width + 1):
        if width == 1:
            if short[0] != long[at]:
                continue
            torn = False
        else:
            if tuple(short[:-1]) != tuple(long[at : at + width - 1]):
                continue
            torn = short[-1] != long[at + width - 1]
        if not torn and width == len(long):
            return None
        return at, torn
    return None


def _written_stretches(written: Sequence[tuple[int, tuple[PoolRow, ...]]]) -> Iterator[Refusal]:
    """Yield a refusal for each pair of runs whose lines one holds as a stretch of the other's.

    The original runs over the runs in order, and for each the copy does,
    so the first refusal is the first match of that scan. A pair is reported
    once, at its first match.
    """
    reported: set[frozenset[int]] = set()
    for original, long in written:
        for copy, short in written:
            pair = frozenset((original, copy))
            if copy == original or len(short) > len(long) or pair in reported:
                continue
            found = _stretch_at(short, long)
            if found is None:
                continue
            at, torn = found
            reported.add(pair)
            shape = "torn" if torn else "whole"
            yield _refuse(
                "E_POOL_TRUNCATED_COPY",
                f"the rows of run {copy} are a stretch of run {original}'s from its row {at}, "
                f"its last row {shape}",
                check=CHECK_WRITTEN_STRETCH,
                copy_run=copy,
                original_run=original,
                copy_rows=len(short),
                original_rows=len(long),
                start_row=at,
                last_row=at + len(short) - 1,
                torn=torn,
                rows_matched=len(short) - 1,
            )


# The value a kept row holds as NaN in the copy checks, so that two NaN values compare
# equal there. No kept row holds it: a value of zero or less is a malformed row.
_NAN_STAND_IN = -1.0


def _kept_row(row: MatchingRow) -> _Row:
    """Return a kept row in the form the copy checks of ``analyse`` compare.

    That is round, side, case and value. A NaN value, however it is written,
    is given as one stand-in value, so that two NaN values compare equal.
    """
    value = _NAN_STAND_IN if math.isnan(row.value) else row.value
    return (row.round, row.side, row.case, value)


def _by_run(read: MatchingRead) -> dict[int, list[MatchingRow]]:
    by_run: dict[int, list[MatchingRow]] = {}
    for row in read.rows:
        by_run.setdefault(row.run, []).append(row)
    return dict(sorted(by_run.items()))


# The metadata lines of a run as one reading takes them: each split at its first ``=``,
# with its line number.
_Metadata = Sequence[tuple[str, str, int]]


def _metadata_with_lines(run: MatchingRun) -> list[tuple[str, str, int]]:
    """Return every metadata line of a run, split at its first ``=``, with its line number.

    These are the lines the matching mode reads as metadata, a line with a
    tab at either end included: such a line counts as the same line without
    the tab, since the key and the text after the ``=`` are read stripped of
    the white space around them.
    """
    return [
        (key, written, line)
        for (key, written), line in zip(run.metadata, run.metadata_lines, strict=True)
    ]


# The byte-order mark, which this mode reads as part of the first line of an input.
_MARK = "\ufeff"


def _inputs(read: MatchingRead) -> list[int]:
    """Return the numbers of the lines on which the inputs of a read begin, in order."""
    return sorted(set(read.input_lines or (1,)))


def _end_of_input(inputs: Sequence[int], line: int) -> int:
    """Return the line on which the first input that begins below ``line`` begins."""
    at = bisect_right(inputs, line)
    return inputs[at] if at < len(inputs) else 1 << 62


def _own_lines(read: MatchingRead, run: MatchingRun, inputs: Sequence[int] | None = None) -> range:
    """Return the numbers of the lines of a run that a text capture of the run reads.

    A run opened by a banner holds, in a text capture, the lines below the banner up to the
    end of the input the banner stands in: the text reader reads each file on its own, and
    the lines of a file above its first banner form no run, or a run of their own when they
    hold a data row. In the matching mode a run also holds the lines above the first banner
    and those of a later input above its first banner; a text capture of the run holds none
    of them. A run without a banner, in a text that holds none, keeps every line. ``inputs``
    is ``_inputs`` of the read, or ``None`` to work it out.
    """
    if run.banner_line is None:
        return range(1, 1 << 62)
    inputs = _inputs(read) if inputs is None else inputs
    return range(run.banner_line + 1, _end_of_input(inputs, run.banner_line))


# A part of a run's kept rows: the line on which it begins, the lines a text capture of it
# reads, and its rows in the order of the text.
_Part = tuple[int, range, list[MatchingRow]]


def _parts(inputs: Sequence[int], run: MatchingRun, rows: Sequence[MatchingRow]) -> list[_Part]:
    """Return the parts of a run's kept rows that text captures read as runs of their own.

    The text reader reads each file on its own, and opens a run at each banner. So the
    kept rows of a run fall into a part per input they stand in, and, in the input that
    holds the run's banner, a part above the banner and one below it. Such a run is a
    first input without a banner and the inputs after it up to the first banner, the lines
    of a later input above its first banner and the run before them, an input that begins
    with a byte-order mark and a banner, which this mode reads as a malformed row, or the
    rows above the first banner and those below it. Each part is given by the line on
    which it begins, the lines a text capture of it reads, and its rows in the order of the
    text. ``inputs`` is ``_inputs`` of the read.
    """
    banner = run.banner_line
    parts: dict[int, list[MatchingRow]] = {}
    for row in rows:
        begin = inputs[bisect_right(inputs, row.line) - 1]
        if banner is not None and begin <= banner < row.line:
            begin = banner
        parts.setdefault(begin, []).append(row)
    out: list[_Part] = []
    for begin, held in parts.items():
        end = _end_of_input(inputs, begin)
        if banner is not None and begin < banner < end:
            end = banner
        out.append((begin, range(begin, end), held))
    return out


def _held_of(
    read: MatchingRead, run: MatchingRun, parts: Sequence[_Part], inputs: Sequence[int]
) -> range:
    """Return the lines a text capture of the kept rows of a run reads, given their parts.

    Where the rows fall into one part (``_parts``), those are the lines of that part: the
    text capture that holds them is the one of the input, or of the stretch of it above or
    below the run's banner, that they stand in, wherever the run's banner stands. Where they
    fall into several, they are those of ``_own_lines``.
    """
    if len(parts) == 1:
        ((_begin, lines, _held),) = parts
        return lines
    return _own_lines(read, run, inputs)


def _held_lines(read: MatchingRead, run: MatchingRun, rows: Sequence[MatchingRow]) -> range:
    """Return the numbers of the lines a text capture of the kept rows ``rows`` of a run reads,
    as ``_held_of`` gives them."""
    inputs = _inputs(read)
    return _held_of(read, run, _parts(inputs, run, rows), inputs)


class _Lines:
    """The metadata lines of a run in one reading, and what the order of its rows takes from
    them.

    That is, read once, so that the rows of each part of a run are ordered without reading
    every line of the run again: the lines whose text before the first ``=`` is
    ``pass_order`` once stripped, spaces or a tab around that text included, by line
    number, with the names of the text after the ``=``, split on white space; the sides of
    the one ``sides=`` line, none where ``sides=`` lines differ; and the twin of each
    ``twin=NAME:SIDE`` line, the first such line of a twin counting. Each key and text is
    taken stripped of the white space around it.
    """

    __slots__ = ("banner", "declared", "orders", "starts", "twins")

    def __init__(self, run: MatchingRun, metadata: _Metadata) -> None:
        self.banner = run.banner_line
        found = {
            line: written.split() for key, written, line in metadata if key.strip() == "pass_order"
        }
        self.starts = sorted(found)
        self.orders = [found[line] for line in self.starts]
        declared = {written.strip() for key, written, _line in metadata if key.strip() == "sides"}
        self.declared: list[str] = declared.pop().split() if len(declared) == 1 else []
        self.twins: dict[str, str] = {}
        for key, written, _line in metadata:
            if key.strip() == "twin":
                twin, colon, of = written.strip().partition(":")
                if colon and twin and of:
                    self.twins.setdefault(twin, of)

    def order_at(self, line: int) -> list[str] | None:
        """Return the pass order in force for a row on ``line``, or ``None`` where none is.

        That is the order of the last pass-order line above the row. The banner of the run
        sets none, so a row below it is not ordered by a line above it.
        """
        at = bisect_left(self.starts, line) - 1
        if at < 0:
            return None
        if self.banner is not None and self.starts[at] < self.banner < line:
            return None
        return self.orders[at]

    def lineup(self, rows: Sequence[MatchingRow]) -> dict[str, int]:
        """Return the place of each side of the rows ``rows`` of the run in its lineup.

        The sides of its one ``sides=`` line come first, then the other sides in the order
        the rows first name them, and each twin of a ``twin=NAME:SIDE`` line right after
        its side. A side that is left over comes last.
        """
        names = dict.fromkeys([*self.declared, *(row.side for row in rows)])
        lineup: list[str] = []
        for name in names:
            if name in self.twins:
                continue
            lineup.append(name)
            lineup += [twin for twin, of in self.twins.items() if of == name]
        lineup += [name for name in names if name not in lineup]
        return {name: place for place, name in enumerate(dict.fromkeys(lineup))}


class _RunMetadata:
    """The metadata lines of one run in each reading the forms of its kept rows take.

    ``every`` holds the lines the matching mode reads as metadata, and ``untabbed`` those
    but one that holds a tab, wherever it stands. ``reader`` holds those, in the order of
    the text, as the text reader reads them: a byte-order mark that begins an input, which
    this mode keeps as part of the first line, is taken off the key of that line, as the
    text reader takes it off a file. Each is read once for the run, and its parts share it.
    """

    __slots__ = ("every", "every_lines", "reader", "reader_lines", "run", "untabbed")

    def __init__(self, run: MatchingRun, inputs: Sequence[int]) -> None:
        every = _metadata_with_lines(run)
        untabbed = [entry for entry in every if "\t" not in entry[0] + entry[1]]
        starts = set(inputs)
        self.run = run
        self.every_lines = every
        self.every = _Lines(run, every)
        self.untabbed = self.every if len(untabbed) == len(every) else _Lines(run, untabbed)
        self.reader = sorted(
            (
                (
                    key[1:] if line in starts and key.startswith(_MARK) else key,
                    written,
                    line,
                )
                for key, written, line in untabbed
            ),
            key=lambda entry: entry[2],
        )
        self.reader_lines = [line for _key, _written, line in self.reader]

    def text_reader_metadata(self, own: range) -> list[tuple[str, str, int]]:
        """Return the metadata lines of the run that a text capture of the lines ``own`` reads.

        That is every metadata line among them but one that holds a tab: the text reader
        reads a line with a tab as a row, and such a line, a tab at either end of it, is a
        malformed row there.
        """
        low = bisect_left(self.reader_lines, own.start)
        return self.reader[low : bisect_left(self.reader_lines, own.stop, low)]


def _ordered(
    run: MatchingRun, rows: Sequence[MatchingRow], metadata: _Metadata | None = None
) -> list[MatchingRow]:
    """Return the kept rows of a run in the order they ran, as its metadata lines give it.

    The lines are ``metadata``, or every line the matching mode reads as
    metadata when it is ``None``. The order is by round, then by the
    position a pass-order line gives the side in that round, then by the
    side's place in the lineup, and by the order of the text within one
    round and side. A side's position in a round is its place in the
    pass-order line in force for its rows of that round, counted from 1. In
    the matching mode's own lines, a pass-order line with a tab at either
    end orders the rows below it as the same line without the tab does, and
    ``pass_order = new old`` orders the rows below it too, though it sets no
    order on the rows of the read. A round in which those lines give a side
    two positions gives no side a position, and a side without one sorts as
    if at the position one past the size of the lineup. The default order
    gives no position. The lines are read as ``_Lines`` reads them.
    """
    lines = _metadata_with_lines(run) if metadata is None else metadata
    return _ordered_by(_Lines(run, lines), rows)


def _ordered_by(lines: _Lines, rows: Sequence[MatchingRow]) -> list[MatchingRow]:
    """Return the kept rows ``rows`` of a run in the order ``_ordered`` gives, from the
    metadata lines ``lines``."""
    positions: dict[tuple[int, str], int] = {}
    contradicted: set[int] = set()
    for row in rows:
        named = lines.order_at(row.line)
        if named is not None and row.side in named:
            position = named.index(row.side) + 1
            if positions.setdefault((row.round, row.side), position) != position:
                contradicted.add(row.round)
    lineup = lines.lineup(rows)
    unplaced = len(lineup) + 1

    def place(numbered: tuple[int, MatchingRow]) -> tuple[int, int, int, int]:
        line, row = numbered
        position = positions.get((row.round, row.side))
        if position is None or row.round in contradicted:
            position = unplaced
        return (row.round, position, lineup[row.side], line)

    return [row for _, row in sorted(enumerate(rows), key=place)]


def _ran_in_order(
    run: MatchingRun, rows: Sequence[MatchingRow], metadata: _Metadata | None = None
) -> tuple[_Row, ...]:
    """Return the kept rows of a run, as ``_kept_row`` gives them, in the order ``_ordered``
    gives."""
    return tuple(map(_kept_row, _ordered(run, rows, metadata)))


def _in_the_order_they_ran(read: MatchingRead) -> list[tuple[int, tuple[_Row, ...]]]:
    """Return the index and the kept rows of every run that kept a row, in the order they ran."""
    return [(index, _ran_in_order(read.runs[index], rows)) for index, rows in _by_run(read).items()]


def _held_in_order(
    metadata: _RunMetadata, rows: Sequence[MatchingRow], own: range
) -> list[MatchingRow]:
    """Return the rows of ``rows`` among the lines ``own`` in the order a text capture of those
    lines holds them: the order they ran, as the metadata lines the text reader reads there
    give it."""
    lines = _Lines(metadata.run, metadata.text_reader_metadata(own))
    return _ordered_by(lines, [row for row in rows if row.line in own])


def _text_capture_rows(
    read: MatchingRead,
    run: MatchingRun,
    rows: Sequence[MatchingRow],
    own: range | None = None,
) -> list[MatchingRow]:
    """Return the rows of ``rows`` that a text capture of the run reads, in the order it
    holds them (``_held_in_order``), over the lines ``own``, or else those of
    ``_held_lines``."""
    own = _held_lines(read, run, rows) if own is None else own
    return _held_in_order(_RunMetadata(run, _inputs(read)), rows, own)


def _as_a_text_capture_holds(
    read: MatchingRead, run: MatchingRun, rows: Sequence[MatchingRow]
) -> tuple[_Row, ...]:
    """Return the kept rows of a run in the order a text capture of it holds its rows.

    That is the order they ran, as the lines the text reader reads as metadata give it,
    over the rows a text capture of the run reads (``_text_capture_rows``): a pass-order or
    ``sides=`` line with a tab at either end counts for nothing there, and neither does a
    line outside the part of the run that holds the rows, where they fall into one part,
    or else outside the lines below the run's banner up to the end of its input.
    """
    return tuple(map(_kept_row, _text_capture_rows(read, run, rows)))


def _in_the_order_text_captures_hold(read: MatchingRead) -> list[tuple[int, tuple[_Row, ...]]]:
    """Return the index and the kept rows of every run that kept one, as text captures hold them."""
    return [
        (index, _as_a_text_capture_holds(read, read.runs[index], rows))
        for index, rows in _by_run(read).items()
    ]


# The forms in which the copy checks compare the kept rows of a run, in their order: in the
# order of the text, in the order they ran as every metadata line of the run gives it, in
# that order as the run's lines without a tab give it, and in the order a text capture of
# the run holds them, every kept row; then the rows whose value is finite in the first three
# of those orders, as a strict text capture holds them, which reads a row whose value is not
# finite as malformed, so that such a row names no side and gives no position, and as a
# lenient text capture holds them, which orders its rows with such a row and then leaves the
# row out.
_Forms = tuple[tuple[_Row, ...], ...]


# A run that kept a row, as the copy checks take it: its index, its metadata lines, its kept
# rows in the order of the text, and their parts (``_parts``).
_Kept = tuple[int, _RunMetadata, list[MatchingRow], list[_Part]]


def _kept_runs(read: MatchingRead) -> list[_Kept]:
    """Return every run that kept a row, in index order, each with its lines read once."""
    inputs = _inputs(read)
    return [
        (
            index,
            _RunMetadata(read.runs[index], inputs),
            rows,
            _parts(inputs, read.runs[index], rows),
        )
        for index, rows in _by_run(read).items()
    ]


def _forms(
    read: MatchingRead, kept: Sequence[_Kept] | None = None
) -> list[tuple[int, _Forms, tuple[int, ...]]]:
    """Return the index, the forms and the kinds of the forms of every run that kept a row.

    The kind of a form is the place of the first of the run's forms that equals it, so
    that a pair of runs is compared in a form only where it was not compared in the same
    rows before. ``kept`` is ``_kept_runs`` of the read, or ``None`` to work it out.
    """
    kept = _kept_runs(read) if kept is None else kept
    inputs = _inputs(read)
    return [
        (index, *_forms_of(metadata, rows, _held_of(read, metadata.run, parts, inputs)))
        for index, metadata, rows, parts in kept
    ]


def _forms_of(
    metadata: _RunMetadata, rows: Sequence[MatchingRow], own: range
) -> tuple[_Forms, tuple[int, ...]]:
    """Return the forms of the kept rows ``rows`` of a run, and the kind of each form.

    ``metadata`` gives the metadata lines of the run, and a text capture of the rows reads
    the lines ``own``.
    """
    finite = [row for row in rows if math.isfinite(row.value)]
    ran = _ordered_by(metadata.every, rows)
    ran_finite = _ordered_by(metadata.every, finite)
    if metadata.untabbed is metadata.every:
        plain, plain_finite = ran, ran_finite
    else:
        plain = _ordered_by(metadata.untabbed, rows)
        plain_finite = _ordered_by(metadata.untabbed, finite)
    if metadata.text_reader_metadata(own) == metadata.every_lines and all(
        row.line in own for row in rows
    ):
        # A text capture of the rows reads every line of the run this mode reads, so it
        # holds the rows in the order they ran.
        held, held_finite = ran, ran_finite
    else:
        held = _held_in_order(metadata, rows, own)
        held_finite = _held_in_order(metadata, finite, own)
    forms: _Forms = (
        tuple(map(_kept_row, rows)),
        tuple(map(_kept_row, ran)),
        tuple(map(_kept_row, plain)),
        tuple(map(_kept_row, held)),
        tuple(map(_kept_row, finite)),
        tuple(map(_kept_row, ran_finite)),
        tuple(map(_kept_row, plain_finite)),
        tuple(map(_kept_row, held_finite)),
        tuple(_kept_row(row) for row in held if math.isfinite(row.value)),
    )
    first: dict[tuple[_Row, ...], int] = {}
    kinds = tuple(first.setdefault(form, k) for k, form in enumerate(forms))
    return forms, kinds


# A unit the copy checks of the parts compare: the index of its run, the line on which it
# begins, its forms and the kinds of its forms.
_Unit = tuple[int, int, _Forms, tuple[int, ...]]


def _units(
    kept: Sequence[_Kept], run_forms: Sequence[tuple[int, _Forms, tuple[int, ...]]]
) -> tuple[list[_Unit], set[int]]:
    """Return the runs and the parts of runs that text captures read as runs, in their order,
    and the indices of the runs that give several parts.

    ``kept`` is ``_kept_runs`` of the read. A run whose kept rows fall into one part
    (``_parts``) is one unit, with its forms as ``run_forms``, the result of ``_forms``,
    gives them; a run whose rows fall into several gives a unit per part, whose forms read
    the metadata lines of the run as the run's forms do. When no run gives several, there
    is nothing to compare, and the list is empty.
    """
    split = {index for index, _metadata, _rows, parts in kept if len(parts) > 1}
    if not split:
        return [], split
    forms = {index: (got, kinds) for index, got, kinds in run_forms}
    units: list[_Unit] = []
    for index, metadata, _rows, parts in kept:
        if index not in split:
            ((begin, _lines, _held),) = parts
            units.append((index, begin, *forms[index]))
            continue
        for begin, lines, held in parts:
            units.append((index, begin, *_forms_of(metadata, held, lines)))
    return units, split


def _part_copies(
    kept: Sequence[_Kept],
    run_forms: Sequence[tuple[int, _Forms, tuple[int, ...]]],
    refused: set[frozenset[int]],
) -> Iterator[Refusal]:
    """Yield, per pair of units in their order, identical kept rows or a truncated copy.

    The units are those of ``_units``, and a pair is compared only where one of them is a
    part of a run that gives several, and, for two runs, where the copy checks of the runs
    did not refuse the pair; the rows are compared in the forms of ``_copies``.
    """
    units, split = _units(kept, run_forms)
    for k, (first, first_line, one, my_kinds) in enumerate(units):
        for second, second_line, two, their_kinds in units[k + 1 :]:
            if first not in split and second not in split:
                continue
            if first != second and frozenset((first, second)) in refused:
                continue
            found = next(
                (
                    refusal
                    for mine, theirs in _compared((one, my_kinds), (two, their_kinds))
                    for refusal in [_copy(first, second, mine, theirs, (first_line, second_line))]
                    if refusal is not None
                ),
                None,
            )
            if found is not None:
                yield found


def _compared(
    one: tuple[_Forms, tuple[int, ...]], two: tuple[_Forms, tuple[int, ...]]
) -> Iterator[tuple[tuple[_Row, ...], tuple[_Row, ...]]]:
    """Yield the forms of two runs that the copy checks compare, in their order.

    A form that leaves a run without a row is not compared, and neither is one whose rows,
    for both runs, are those of a form compared before.
    """
    (mine_all, my_kinds), (theirs_all, their_kinds) = one, two
    seen: set[tuple[int, int]] = set()
    pairs = zip(my_kinds, their_kinds, strict=True)
    for mine, theirs, kinds in zip(mine_all, theirs_all, pairs, strict=True):
        if not (mine and theirs) or kinds in seen:
            continue
        seen.add(kinds)
        yield mine, theirs


def _copy(
    first: int,
    second: int,
    one: Sequence[_Row],
    two: Sequence[_Row],
    lines: tuple[int, int] | None = None,
) -> Refusal | None:
    """Return the refusal of two runs' kept rows as ``analyse`` gives it, or ``None``.

    That is identical rows, or else a truncated copy. ``lines`` gives, for two parts of
    runs, the line on which each part begins.
    """
    runs = [first, second]
    if lines is None:
        both, extra = f"the runs {first} and {second}", {}
    else:
        both = (
            f"the parts of the runs {first} and {second} that begin on the lines "
            f"{lines[0]} and {lines[1]}"
        )
        extra = {"lines": list(lines)}
    if len(one) == len(two) and _same_run(one, two, 0, len(one)):
        return _refuse(
            "E_POOL_IDENTICAL_ROWS",
            f"{both} hold identical rows",
            check=CHECK_IDENTICAL_ROWS,
            runs=runs,
            **extra,
        )
    if _is_copy(one, two) or _is_copy(two, one):
        return _refuse(
            "E_POOL_TRUNCATED_COPY",
            f"the rows of one of {both} are a stretch of the other's, "
            "its last row whole or cut short",
            check=CHECK_TRUNCATED_COPY,
            runs=runs,
            **extra,
        )
    return None


def _copies(runs: Sequence[tuple[int, _Forms, tuple[int, ...]]]) -> Iterator[Refusal]:
    """Yield, per pair of runs in index order, identical kept rows or a truncated copy.

    The rows of a pair are compared in the order of the text, then in the
    order the rows ran, then in the order a text capture of each run holds
    them where that differs for a run of the pair, then in those orders with
    the rows whose value is not finite left out, before the next pair; a form
    that leaves a run without a row is not compared. A pair is refused at
    most once.
    """
    for k, (first, one, my_kinds) in enumerate(runs):
        for second, two, their_kinds in runs[k + 1 :]:
            found = next(
                (
                    refusal
                    for mine, theirs in _compared((one, my_kinds), (two, their_kinds))
                    for refusal in [_copy(first, second, mine, theirs)]
                    if refusal is not None
                ),
                None,
            )
            if found is not None:
                yield found


def _refusals(read: MatchingRead) -> Iterator[Refusal]:
    if not isinstance(read, MatchingRead):
        raise Refusal("E_USAGE", "the matching pool check takes a read in the matching mode")
    written = _written(read)
    yield from _identical_written(written)
    yield from _written_stretches(written)
    kept = _kept_runs(read)
    run_forms = _forms(read, kept)
    refused: set[frozenset[int]] = set()
    for refusal in _copies(run_forms):
        refused.add(frozenset(refusal.detail["runs"]))
        yield refusal
    yield from _part_copies(kept, run_forms, refused)


def pool_refusals(read: MatchingRead) -> list[Refusal]:
    """Return every refusal the pool checks of ``read`` find, in the order they run."""
    return list(_refusals(read))


def first_refusal(read: MatchingRead) -> Refusal | None:
    """Return the first refusal the pool checks of ``read`` find, or ``None`` when its runs pool."""
    return next(_refusals(read), None)
