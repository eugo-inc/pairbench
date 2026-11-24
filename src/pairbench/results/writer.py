# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Writing and reading ``results.json`` and ``results.md``.

A run writes its results twice: once right after the analysis, with the
explain step and the charts still ``pending``, and once after them. Each
write forms both texts in memory first, then puts each file in place by
writing it whole under another name in the same folder and replacing the
final name in one step. A reader therefore finds the earlier document or the
later one, never half of one.

The two files hold what the results document holds and nothing else. The
writer asks the machine for nothing: no host, no user, no folder.
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pairbench.api import API_VERSION, ReportOptions
from pairbench.errors import Refusal, _first_surrogate, lone_surrogate, surrogate_place
from pairbench.model import (
    FILE_CAPTURE,
    FILE_MARKDOWN,
    FILE_PLAN,
    FILE_RESULTS,
    Results,
    public_case,
)

# The mode of a results file written for the first time: readable by all.
NEW_FILE_MODE = 0o644


def results_text(results: Results) -> str:
    """Return the text of ``results.json``: the document as JSON, indented, one newline at the end.

    Every number is finite; the model refuses any other. A document that holds a text or a
    key with a lone surrogate (``pairbench.errors.lone_surrogate``), which UTF-8 text cannot
    hold, is refused with ``E_USAGE``. The message names the place of the first such text
    and shows the text as the results show a case id (``pairbench.model.public_case``): its
    secret forms hidden and its paths cut, then escaped, at most 40 characters on each side
    of the surrogate, or no text where the cut leaves the surrogate out.
    """
    data = results.to_json()
    found = _first_surrogate(data)
    if found is not None:
        raise Refusal("E_USAGE", f"the results cannot be written: {_unwritable(data, found)}")
    return _json_text(data)


def _unwritable(data: object, found: tuple[str, str, bool]) -> str:
    """Say where ``data`` holds the text ``found`` with a lone surrogate, the text shown as
    ``results_text`` says."""
    place, text, is_key = found
    shown = lone_surrogate(public_case(text))
    if shown is None:
        return f"{surrogate_place(data)} holds a lone surrogate, which is not UTF-8 text"
    where = f"{place}: " if place else ""
    return f"{where}{'the key ' if is_key else ''}{shown}"


def results_text_as_held(results: Results) -> str:
    """Return the text ``results_text`` gives, a lone surrogate kept in it as it stands.

    Such a text is for a stream that can write the surrogate, as standard output under a C
    or POSIX locale writes one from U+DC80 to U+DCFF as the byte it stands for; no file
    pairbench writes holds it.
    """
    return _json_text(results.to_json())


def _json_text(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def read_results(path: Path) -> Results:
    """Read a results document from a file.

    A file that cannot be read, that is not JSON, that holds a text with a
    lone surrogate (``pairbench.errors.lone_surrogate``), that is nested
    deeper than the interpreter can follow, or that is no valid results
    document is refused with ``E_USAGE``; the message names the file by the
    last part of its path.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Refusal("E_USAGE", f"results file not found: {file.name}") from None
    except UnicodeDecodeError:
        raise Refusal("E_USAGE", f"results file is not UTF-8 text: {file.name}") from None
    except OSError as exc:
        raise Refusal(
            "E_USAGE", f"results file cannot be read: {file.name}: {exc.strerror}"
        ) from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refusal(
            "E_USAGE", f"results file is not JSON: {file.name}, line {exc.lineno}"
        ) from None
    except RecursionError:
        raise Refusal("E_USAGE", f"results file is nested too deeply: {file.name}") from None
    except ValueError as exc:
        raise Refusal("E_USAGE", f"results file is not JSON: {file.name}: {exc}") from None
    found = lone_surrogate(data)
    if found is not None:
        raise Refusal("E_USAGE", f"results file {file.name}: {found}")
    try:
        return Results.from_json(data)
    except RecursionError:
        raise Refusal("E_USAGE", f"results file is nested too deeply: {file.name}") from None


def _sync_folder(folder: Path) -> None:
    """Make the replacement of a file in a folder durable, where the platform allows it."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    with contextlib.suppress(OSError):
        handle = os.open(folder, flags)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def replace_file(path: Path, text: str) -> None:
    """Put a text in place of a file in one step.

    The text is written whole to a new file in the same folder, flushed to
    the disk, and then renamed over the final name. A file already there
    keeps its mode; a new one is readable by all. When anything fails the
    final name still holds what it held before, and the new file is removed.
    """
    data = text.encode("utf-8")
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = NEW_FILE_MODE
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    _sync_folder(path.parent)


def write_results(
    results: Results, folder: Path, *, profiles: Sequence[str] | None = None
) -> Results:
    """Write ``results.json`` and ``results.md`` into the run folder and return the results written.

    ``capture``, ``plan`` and ``markdown`` of ``artifacts`` name the files of
    the folder that exist: the capture and the plan when they are there, and
    the markdown report this call writes. ``html``, ``diagnostics`` and
    ``charts`` stay as the results name them. ``profiles`` of ``None`` keeps
    the ones the results name; otherwise it replaces them, each a name
    relative to the run folder.

    Both texts are formed before either file is touched. ``results.md`` is
    put in place first and ``results.json`` second, each in one step. The
    folder is made when it does not exist.
    """
    from pairbench.report.markdown import MarkdownReporter

    out = Path(folder)
    if out.exists() and not out.is_dir():
        raise Refusal("E_USAGE", f"the results folder {out.name} is a file, not a folder")
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _not_written(out, exc) from None
    artifacts = dataclasses.replace(
        results.artifacts,
        capture=FILE_CAPTURE if (out / FILE_CAPTURE).is_file() else None,
        plan=FILE_PLAN if (out / FILE_PLAN).is_file() else None,
        markdown=FILE_MARKDOWN,
        profiles=results.artifacts.profiles if profiles is None else tuple(profiles),
    )
    written = dataclasses.replace(results, artifacts=artifacts)
    markdown = MarkdownReporter().render(written, ReportOptions())
    document = results_text(written)
    try:
        replace_file(out / FILE_MARKDOWN, markdown)
        replace_file(out / FILE_RESULTS, document)
    except OSError as exc:
        # A folder the user may not write into is the user's to change; a
        # full disk or another failure of the system is passed on as it is.
        if isinstance(exc, PermissionError) or exc.errno == errno.EROFS:
            raise _not_written(out, exc) from None
        raise
    return written


def _not_written(out: Path, exc: OSError) -> Refusal:
    """A results folder that cannot be made or written, named by its own name only."""
    why = exc.strerror or type(exc).__name__
    return Refusal("E_USAGE", f"the results folder {out.name} cannot be written: {why}")


class JsonReporter:
    """The reporter ``json``: the results document unchanged, as ``results.json`` holds it."""

    name = "json"
    api_version = API_VERSION

    def render(self, results: Results, options: ReportOptions) -> str:
        """Return the results document as JSON. The display options change nothing."""
        return results_text(results)


__all__ = [
    "NEW_FILE_MODE",
    "JsonReporter",
    "read_results",
    "replace_file",
    "results_text",
    "results_text_as_held",
    "write_results",
]
