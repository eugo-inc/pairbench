# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The simple text input format, read by the built-in capture reader ``text``.

A file holds one or more runs. Each line is one of:

* a run banner: exactly ``## host``, or ``## host`` followed by a space. It
  begins a new run. Lines before the first banner form a run of their own,
  which then has index 0, only when they hold a data row; otherwise they
  form no run, their metadata belongs to no run, and their comments and
  malformed lines (a title or a column header, say) are counted in the first
  run. A file without a banner is one run;
* a section marker: any other line whose first non-blank characters are
  ``##``. It is ignored and not counted;
* a comment: any other line whose first non-blank character is ``#``. It is
  ignored and counted, whatever it holds;
* metadata: a line without a tab that holds ``=``, read as ``key=value`` and
  kept verbatim. ``unit`` names the unit of the values (default ``ns``),
  ``better`` is ``lower`` (default) or ``higher``, ``sides`` declares the side
  names, ``pass_order`` gives the order in which the sides ran for the rows
  that follow it, and ``twin=NAME:SIDE`` declares ``NAME`` a twin of ``SIDE``;
* a data row: exactly five tab-separated fields, ``suite``, ``side``,
  ``round``, ``case`` and ``value``. A row with another number of fields, or
  whose round or value does not parse, is malformed: it is counted, reported
  and skipped. A value that parses as a number and is zero or less is kept.
  A round is any integer, 0 and below included: round numbers are labels
  that pair the rows of a round.

Each run becomes one ``Capture`` whose sides are of kind ``rows``, with a
lineup record and an end record that says ``complete``. A capture numbers
its rounds 1, 2, 3 and on in the order of the run's round numbers
(``model.round_numbers``), which keeps the order and the pairing: rounds
written 3 to 18 are the capture's rounds 1 to 16, and a number no row holds
is no round. Rounds written 1, 2, 3 keep their numbers. A case is of kind
``time`` when the unit is a unit of time. The suite is kept on each
observation and changes neither the case id nor the floor group.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pairbench.api import API_VERSION, note_line
from pairbench.capture.reader import read_bytes
from pairbench.errors import Refusal
from pairbench.model import (
    NOTE_MALFORMED_ROWS,
    Better,
    Capture,
    Case,
    Header,
    Lineup,
    Note,
    ReaderInfo,
    Side,
    Source,
    kind_of_unit,
    round_numbers,
    sha256_hex,
    validate_side_name,
)

DEFAULT_UNIT = "ns"
DEFAULT_BETTER = "lower"
TEXT_BETTER: dict[str, Better] = {"lower": "lower", "higher": "higher"}
BANNER = "## host"
METRIC = "value"


@dataclass
class _Run:
    """What the lines of one run said, before it becomes a capture."""

    metadata: list[tuple[str, str]] = field(default_factory=list)
    order: tuple[str, ...] | None = None
    rows: list[tuple[str, str, int, str, float]] = field(default_factory=list)
    positions: dict[tuple[int, str], int] = field(default_factory=dict)
    malformed: int = 0
    comments: int = 0

    def has_content(self) -> bool:
        return bool(self.metadata or self.rows or self.malformed)


def is_banner(line: str) -> bool:
    """Say whether a line begins a new run."""
    return line == BANNER or line.startswith(BANNER + " ")


def _row(fields: Sequence[str]) -> tuple[str, str, int, str, float] | None:
    """Read the five fields of a data row, or return ``None`` for a malformed row.

    A round is any integer and a value a finite number.
    """
    suite, side, round_text, case, value_text = fields
    try:
        round_ = int(round_text)
        value = float(value_text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return suite, side, round_, case, value


def _split(text: str, name: str) -> list[_Run]:
    runs: list[_Run] = []
    current = _Run()
    seen_banner = False
    for number, line in enumerate(text.splitlines(), start=1):
        if is_banner(line):
            if seen_banner or current.rows:
                runs.append(current)
                current = _Run()
            else:
                # Lines above the first banner that hold no data row form no
                # run: their metadata is dropped, and their comments and
                # malformed lines are counted in the first run.
                current = _Run(comments=current.comments, malformed=current.malformed)
            seen_banner = True
            continue
        stripped = line.lstrip()
        if stripped.startswith("##"):
            continue
        if stripped.startswith("#"):
            current.comments += 1
            continue
        if not line.strip():
            continue
        if "\t" not in line and "=" in line:
            key, _, value = line.partition("=")
            current.metadata.append((key, value))
            if key.strip() == "pass_order":
                current.order = tuple(value.split())
            continue
        fields = line.split("\t")
        row = _row(fields) if len(fields) == 5 else None
        if row is None:
            current.malformed += 1
            continue
        _suite, side, round_, case, _value = row
        try:
            validate_side_name(side)
        except Refusal as exc:
            raise Refusal("E_USAGE", f"line {number} of {name}: {exc.message}") from exc
        if not case:
            raise Refusal("E_USAGE", f"line {number} of {name}: a data row needs a case")
        if current.order is not None and side in current.order:
            pos = current.order.index(side) + 1
            known = current.positions.setdefault((round_, side), pos)
            if known != pos:
                raise Refusal(
                    "E_USAGE",
                    f"line {number} of {name}: side {side!r} ran at two positions in round "
                    f"{round_}",
                )
        current.rows.append(row)
    if seen_banner or current.has_content():
        runs.append(current)
    return runs


def _one_value(run: _Run, key: str, default: str, name: str, index: int) -> str:
    values = {value.strip() for k, value in run.metadata if k.strip() == key}
    if len(values) > 1:
        raise Refusal(
            "E_USAGE",
            f"run {index} of {name} gives {key}= more than one value: {', '.join(sorted(values))}",
        )
    return values.pop() if values else default


def _capture(run: _Run, index: int, path: Path, file_sha256: str) -> Capture:
    name = path.name
    unit = _one_value(run, "unit", DEFAULT_UNIT, name, index)
    better_text = _one_value(run, "better", DEFAULT_BETTER, name, index)
    if better_text not in TEXT_BETTER:
        raise Refusal(
            "E_USAGE", f"run {index} of {name}: better= is lower or higher, not {better_text!r}"
        )
    better = TEXT_BETTER[better_text]
    declared_texts = {value.strip() for k, value in run.metadata if k.strip() == "sides"}
    if len(declared_texts) > 1:
        raise Refusal("E_USAGE", f"run {index} of {name} declares sides= more than once")
    declared = tuple(declared_texts.pop().split()) if declared_texts else ()
    for side in declared:
        validate_side_name(side)
    twins: dict[str, str] = {}
    for key, value in run.metadata:
        if key.strip() != "twin":
            continue
        twin, colon, of = value.strip().partition(":")
        if not colon or not twin or not of:
            raise Refusal("E_USAGE", f"run {index} of {name}: a twin is declared as twin=NAME:SIDE")
        if twins.get(twin, of) != of:
            raise Refusal("E_USAGE", f"run {index} of {name}: {twin!r} is declared twice as a twin")
        twins[validate_side_name(twin)] = validate_side_name(of)

    observed = tuple(dict.fromkeys(side for _, side, _, _, _ in run.rows))
    names = [*declared, *(side for side in observed if side not in declared)]
    sides = [side for side in names if side not in twins]
    if not sides:
        raise Refusal("E_USAGE", f"run {index} of {name} holds no side")

    cells: dict[tuple[int, str, str], str] = {}
    for suite, side, round_, case, _value in run.rows:
        cell = (round_, side, case)
        if cell in cells:
            raise Refusal(
                "E_GRID",
                f"run {index} of {name}: side {side!r}, round {round_}, case {case!r} "
                "is given twice",
                detail={"duplicated": [list(cell)]},
            )
        cells[cell] = suite
    numbers = round_numbers(round_ for _, _, round_, _, _ in run.rows)
    cells = {(numbers[round_], side, case): suite for (round_, side, case), suite in cells.items()}
    positions = {
        (numbers[round_], side): pos
        for (round_, side), pos in run.positions.items()
        if round_ in numbers
    }
    case_ids = tuple(dict.fromkeys(case for _, _, _, case, _ in run.rows))
    cases = [
        Case(id=case, metric=METRIC, unit=unit, better=better, kind=kind_of_unit(unit))
        for case in case_ids
    ]
    capture = Capture.from_rows(
        [(numbers[round_], side, case, value) for _, side, round_, case, value in run.rows],
        sides=sides,
        twins=twins or None,
        positions=positions or None,
        cases=cases,
        unit=unit,
    )

    per_key: dict[tuple[int, str], int] = {}
    for round_, _side, case in cells:
        per_key[(round_, case)] = per_key.get((round_, case), 0) + 1
    one_sided = sum(1 for count in per_key.values() if count == 1)

    capture_id = "text-" + sha256_hex(f"{file_sha256}:{index}")[:12]
    notes: list[Note] = []
    if run.malformed:
        message = (
            f"{run.malformed} malformed row{'s' if run.malformed != 1 else ''} skipped "
            f"in run {index} of {name}"
        )
        notes.append(Note(code=NOTE_MALFORMED_ROWS, message=message))
        print(note_line(NOTE_MALFORMED_ROWS, message), file=sys.stderr)
    info = ReaderInfo(
        reader=TextReader.name,
        run_index=index,
        metadata=tuple(run.metadata),
        sides_declared=declared,
        sides_observed=observed,
        malformed_rows=run.malformed,
        comments=run.comments,
        one_sided_keys=one_sided,
    )
    return dataclasses.replace(
        capture,
        capture_id=capture_id,
        header=dataclasses.replace(capture.header, capture_id=capture_id),
        observations=tuple(
            dataclasses.replace(o, suite=cells[(o.round, o.name, o.case)])
            for o in capture.observations
        ),
        notes=(*capture.notes, *notes),
        source=Source(
            path=str(path.resolve()),
            sha256=file_sha256,
            reader=info,
            round_labels=_labels(numbers),
        ),
    )


def _labels(numbers: Mapping[int, int]) -> tuple[int, ...]:
    """The labels of the rounds numbered 1, 2, 3 and on, or none when they are those numbers."""
    labels = tuple(sorted(numbers, key=numbers.__getitem__))
    return () if labels == tuple(range(1, len(labels) + 1)) else labels


class TextReader:
    """The ``CaptureReader`` of the simple text input format: one capture per run."""

    name: str = "text"
    api_version: int = API_VERSION

    def sniff(self, path: Path, head: bytes) -> bool:
        """Say whether the head of a file holds a run banner or a data row of this format."""
        try:
            text = head.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        for line in text.splitlines():
            if is_banner(line):
                return True
            fields = line.split("\t")
            if len(fields) == 5 and _row(fields) is not None:
                return True
        return False

    def read(self, path: Path) -> list[Capture]:
        """Read every run of a file, each as one capture."""
        data = read_bytes(path)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise Refusal("E_USAGE", f"{path.name} is not UTF-8 text: {exc}") from exc
        file_sha256 = hashlib.sha256(data).hexdigest()
        runs = _split(text, path.name)
        if not runs:
            raise Refusal("E_USAGE", f"{path.name} holds no run")
        return [_capture(run, index, path, file_sha256) for index, run in enumerate(runs)]


def project(capture: Capture, a: str, b: str) -> Capture:
    """Return a two-sided view of a run of several sides.

    Only rounds whose recorded order names both sides are kept, and in each
    the relative order of the two is kept: the one that ran first has
    position 1 and the other position 2. The kept rounds are numbered from 1
    in their order. ``b`` is the baseline, unless ``a`` is a twin of ``b``,
    and ``a`` is the baseline when ``b`` is a twin of ``a``. Naming the same
    side twice, a name that is no entry of the capture, the positive
    control, and a twin whose side is not the other one are refused with
    ``E_USAGE``.
    """
    if a == b:
        raise Refusal("E_USAGE", f"a two-sided view names the side {a!r} twice")
    found: dict[str, Side] = {}
    for wanted in (a, b):
        try:
            found[wanted] = capture.side(wanted)
        except KeyError:
            raise Refusal("E_USAGE", f"{wanted!r} is no side of this capture") from None
    side_a, side_b = found[a], found[b]
    if side_b.twin_of == a:
        pair = (side_a.with_role("baseline"), side_b)
    elif side_a.twin_of == b:
        pair = (side_b.with_role("baseline"), side_a)
    elif any(s.role in ("twin", "control") for s in (side_a, side_b)):
        raise Refusal(
            "E_USAGE", f"a two-sided view takes two sides, or a side and its own twin: {a!r}, {b!r}"
        )
    else:
        pair = (side_a.with_role("subject"), side_b.with_role("baseline"))
    names = (pair[0].name, pair[1].name)

    position = {
        (x.round, x.name): x.pos
        for x in capture.launches
        if x.phase == "round" and x.name in names and x.pos is not None
    }
    kept = sorted({r for (r, _name) in position if (r, a) in position and (r, b) in position})
    renumber = {old: new for new, old in enumerate(kept, start=1)}

    def new_pos(round_: int, name: str) -> int:
        other = names[1] if name == names[0] else names[0]
        return 1 if position[(round_, name)] < position[(round_, other)] else 2

    launches = tuple(
        dataclasses.replace(x, round=renumber[x.round], pos=new_pos(x.round, x.name))
        for x in capture.launches
        if x.phase == "round" and x.name in names and x.round in renumber
    )
    seqs = {x.seq for x in launches}
    observations = tuple(
        dataclasses.replace(o, round=renumber[o.round], pos=new_pos(o.round, o.name))
        for o in capture.observations
        if o.seq in seqs and o.name in names and o.round in renumber
    )
    lineup = Lineup(
        names=names,
        rounds=len(kept),
        schedule=None,
        cases=capture.lineup.cases if capture.lineup is not None else capture.cases,
        discard_thresholds=(
            capture.lineup.discard_thresholds if capture.lineup is not None else None
        ),
    )
    end = (
        dataclasses.replace(
            capture.end, rounds_completed=len(kept), sha256_of_preceding=None, discard_sha256=None
        )
        if capture.end is not None
        else None
    )
    capture_id = f"{capture.capture_id}:{a}:{b}"
    # The view keeps the label of each round it keeps, also when the capture
    # holds no labels of its own because its rounds were labelled 1, 2, 3.
    source = capture.source if capture.source is not None else Source()
    labels = _labels({source.round_label(r): renumber[r] for r in kept})
    return dataclasses.replace(
        capture,
        capture_id=capture_id,
        header=Header(
            capture_id=capture_id,
            tool_version=capture.header.tool_version,
            started_at=capture.header.started_at,
            argv=capture.header.argv,
            config=capture.header.config,
            seeds=capture.header.seeds,
        ),
        sides=pair,
        lineup=lineup,
        launches=launches,
        observations=observations,
        end=end,
        source=(
            dataclasses.replace(source, round_labels=labels)
            if capture.source is not None or labels
            else None
        ),
    )
