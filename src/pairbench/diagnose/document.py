# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``diagnostics.json``: writing and reading the diagnostics document.

The document is the JSON form of ``pairbench.model.Diagnostics``, schema id
``pairbench/diagnostics/v1``, with ``holds_names`` near its top: it holds
names from the user's code (function names, shared-object names, stacks),
which no results document holds. It is written whole under another name in
the run folder and then put in place of ``diagnostics.json`` in one step, so
a reader never finds half a document. It, and every file the explain step
writes beside it, is readable and writable by its owner only.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from pairbench.errors import Refusal
from pairbench.model import FILE_DIAGNOSTICS, PRIVATE_FILE_MODE, Diagnostics


def diagnostics_text(document: Diagnostics) -> str:
    """Return the text of ``diagnostics.json``: the document as indented JSON and one newline."""
    return json.dumps(document.to_json(), indent=2, ensure_ascii=False) + "\n"


def _open_private(path: Path) -> int:
    """Open ``path`` for writing, emptied, readable and writable by its owner only.

    The file is made with ``PRIVATE_FILE_MODE`` and set to it after opening,
    whatever the umask and whether it existed. A file this process may not
    change the mode of keeps its mode.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    change = getattr(os, "fchmod", None)
    if callable(change):
        with contextlib.suppress(PermissionError):
            change(descriptor, PRIVATE_FILE_MODE)
    return descriptor


def create_private(path: Path) -> None:
    """Leave ``path`` empty and readable and writable by its owner only, for a tool to write into.

    A tool that opens its output with ``fopen(path, "w")``, as ``perf stat -o``
    does, makes a new file with the umask's mode but keeps the mode of a file
    that is already there.
    """
    os.close(_open_private(path))


def write_text(path: Path, text: str) -> None:
    """Write a file whole under another name in its folder, then put it in place in one step.

    The file is readable and writable by its owner only, whatever the umask,
    also when it takes the place of a file with another mode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    descriptor = _open_private(partial)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def write_diagnostics(document: Diagnostics, folder: Path) -> Path:
    """Write ``diagnostics.json`` into a run folder and return its path."""
    path = Path(folder) / FILE_DIAGNOSTICS
    write_text(path, diagnostics_text(document))
    return path


def read_diagnostics(path: Path) -> Diagnostics:
    """Read a diagnostics document from a file, with ``Diagnostics.from_json``.

    A file that cannot be read, is not UTF-8, nests too deeply or holds no
    JSON object is refused with ``E_USAGE``; so is a document the model
    refuses.
    """
    name = Path(path).name
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise Refusal(
            "E_USAGE", f"cannot read the diagnostics document {name}: {error.strerror}"
        ) from None
    except UnicodeDecodeError:
        raise Refusal("E_USAGE", f"{name} is not a diagnostics document: it is not UTF-8") from None
    try:
        data = json.loads(text)
    except RecursionError:
        raise Refusal(
            "E_USAGE", f"{name} is not a diagnostics document: it nests too deeply"
        ) from None
    except ValueError as error:
        raise Refusal("E_USAGE", f"{name} is not a diagnostics document: {error}") from None
    if not isinstance(data, dict):
        raise Refusal("E_USAGE", f"{Path(path).name} is not a diagnostics document")
    return Diagnostics.from_json(data)
