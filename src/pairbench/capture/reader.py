# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The built-in capture reader ``jsonl``: reads the ``capture.jsonl`` a run writes.

What it accepts and what it leaves out:

* a last line that is not complete JSON is left out and the capture's source
  says ``torn``. Every other line must be one JSON object that is a capture
  record; a line that is not is refused with ``E_USAGE``;
* an ``end`` record is kept only when it is the one end record of the file,
  stands on its last line and carries the hash of every byte before that
  line. Otherwise every end record is dropped and the capture comes back
  without one, so the analysis treats it as incomplete. A file that holds
  more after its end record, even a torn line, keeps no end record.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pairbench.api import API_VERSION, note_line
from pairbench.errors import Refusal
from pairbench.model import NOTE_VALUE_NOT_FINITE, Capture, End, Source

# A first line too long to read whole from the head of a file still starts this way.
_HEADER_START: Final = re.compile(rb'\s*\{\s*"t"\s*:\s*"header"')


def read_bytes(path: Path) -> bytes:
    """Return the bytes of a file, or refuse with ``E_USAGE`` naming the file by its last part."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise Refusal("E_USAGE", f"cannot read {path.name}: {exc.strerror or exc}") from exc


def _lines(data: bytes) -> list[tuple[int, bytes]]:
    """Split a file into its non-blank lines, each with the offset where it starts."""
    out: list[tuple[int, bytes]] = []
    start = 0
    for piece in data.split(b"\n"):
        if piece.strip():
            out.append((start, piece))
        start += len(piece) + 1
    return out


def parse_records(data: bytes, name: str) -> tuple[list[Mapping[str, Any]], bool]:
    """Return the records of a capture file and whether its last line was torn.

    ``name`` is the last part of the file's path, for the messages. An end
    record that cannot be trusted is left out, as the module says.
    """
    lines = _lines(data)
    parsed: list[tuple[int, Mapping[str, Any]]] = []
    torn = False
    for number, (start, piece) in enumerate(lines, start=1):
        last = number == len(lines)
        try:
            value = json.loads(piece)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            if last:
                torn = True
                continue
            raise Refusal("E_USAGE", f"line {number} of {name} is not JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise Refusal("E_USAGE", f"line {number} of {name} is not a capture record")
        parsed.append((start, value))
    ends = [i for i, (_, value) in enumerate(parsed) if value.get("t") == End.RECORD]
    keep_end = False
    if len(ends) == 1 and ends[0] == len(parsed) - 1 and not torn:
        start, value = parsed[ends[0]]
        keep_end = value.get("sha256_of_preceding") == hashlib.sha256(data[:start]).hexdigest()
    records = [
        value for i, (_, value) in enumerate(parsed) if i not in ends or (keep_end and i == ends[0])
    ]
    return records, torn


class JsonlReader:
    """The ``CaptureReader`` of ``capture.jsonl``. One file holds one capture."""

    name: str = "jsonl"
    api_version: int = API_VERSION

    def sniff(self, path: Path, head: bytes) -> bool:
        """Say whether the file starts with the header record of a capture."""
        first, newline, _ = head.partition(b"\n")
        if not newline:
            return bool(_HEADER_START.match(head))
        try:
            value = json.loads(first)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return False
        return isinstance(value, dict) and value.get("t") == "header"

    def read(self, path: Path) -> list[Capture]:
        """Read the capture of a file; its source holds the path, the file's hash and ``torn``.

        Each ``value_not_finite`` note the capture holds, one per missing cell of a text file
        read leniently, is printed on standard error, as it was when the text was read.
        """
        data = read_bytes(path)
        records, torn = parse_records(data, path.name)
        source = Source(
            path=str(path.resolve()),
            sha256=hashlib.sha256(data).hexdigest(),
            torn=torn,
        )
        capture = Capture.from_records(records, source=source)
        for note in capture.notes:
            if note.code == NOTE_VALUE_NOT_FINITE:
                print(note_line(note.code, note.message), file=sys.stderr)
        return [capture]
