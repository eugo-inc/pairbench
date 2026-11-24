# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What pooling several captures needs at the level of files.

``load_captures`` reads every file of a list, each with the reader named or
the one that recognises it, and keeps where each capture came from.
``shared_source`` says what makes two captures one and the same: the same
capture id, or the same file path or file hash and, for runs a reader split
a file into, the same run. The analysis decides
what that means for a pool and refuses it; nothing here refuses a pool.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pairbench.model import Capture, shared_file

Shared = Literal["capture id", "file path", "file hash"]


def load_captures(
    paths: Sequence[Path | str], *, reader: str | None = None, strict: bool = True
) -> list[Capture]:
    """Read the captures of every file, in the order given, each file's runs in file order.

    ``strict=False`` reads each file with the lenient mode of the text reader,
    as ``pairbench.load_capture`` does.
    """
    from pairbench import load_capture

    out: list[Capture] = []
    for path in paths:
        out += load_capture(path, reader=reader, strict=strict)
    return out


def shared_source(a: Capture, b: Capture) -> Shared | None:
    """Say what two captures share that makes them one capture given twice, or ``None``.

    The capture id is compared first, then the file path and then the hash
    of the file's bytes, as the captures' sources record them. Two different
    runs of one file, as the reader that split it names them, share no file
    (``pairbench.model.shared_file``).
    """
    if a.capture_id == b.capture_id:
        return "capture id"
    return shared_file(a.source, b.source)
