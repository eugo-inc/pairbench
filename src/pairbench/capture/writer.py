# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The writer of ``capture.jsonl``: append-only JSON Lines, flushed and synced after every record.

Each record is one line of compact JSON, written in the order of its fields
by ``record.to_json()``. After every line the file is synced to disk, so a run
that stops at any moment leaves every record written before it. A running
SHA-256 of every byte written is kept, and the ``end`` record carries the hash
of everything before it: a copy that lost its tail is detectable. Nothing is
written after the ``end`` record.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import TracebackType
from typing import Any

from pairbench.model import PRIVATE_FILE_MODE, End, EndStatus, Record


class CaptureWriter:
    """Appends the records of one run to a capture file that does not exist yet.

    The file is created when the writer is made; an existing file is never
    written over. ``write`` appends one record, ``end`` appends the ``end``
    record and closes the file. A record handed to ``write`` after the end,
    or after ``close``, is refused with ``ValueError``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, PRIVATE_FILE_MODE
        )
        change = getattr(os, "fchmod", None)
        if callable(change):
            change(self._fd, PRIVATE_FILE_MODE)
        self._hash = hashlib.sha256()
        self._ended = False

    def __enter__(self) -> CaptureWriter:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def ended(self) -> bool:
        """Whether the ``end`` record was written."""
        return self._ended

    @property
    def open(self) -> bool:
        """Whether records can still be written."""
        return self._fd is not None and not self._ended

    @property
    def sha256(self) -> str:
        """The SHA-256 of every byte written so far, as lower-case hex."""
        return self._hash.hexdigest()

    def write(self, record: Record) -> None:
        """Append one record, then sync the file to disk."""
        if isinstance(record, End):
            raise ValueError("the end record is written with end()")
        self._append(record.to_json())

    def end(
        self,
        status: EndStatus,
        rounds_completed: int,
        *,
        discard_sha256: str | None = None,
        finished_at: str | None = None,
    ) -> End:
        """Append the ``end`` record with the hash of every byte before it, and close the file."""
        record = End(
            status=status,
            rounds_completed=rounds_completed,
            sha256_of_preceding=self._hash.hexdigest(),
            discard_sha256=discard_sha256,
            finished_at=finished_at,
        )
        self._append(record.to_json())
        self._ended = True
        self.close()
        return record

    def close(self) -> None:
        """Close the file without an end record. Safe to call more than once."""
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)

    def _append(self, data: dict[str, Any]) -> None:
        if self._ended or self._fd is None:
            raise ValueError("the capture is closed: nothing is written after its end record")
        line = (json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        view = memoryview(line)
        while view:
            written = os.write(self._fd, view)
            view = view[written:]
        os.fsync(self._fd)
        self._hash.update(line)
