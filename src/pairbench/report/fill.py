# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Filling the figure tokens of a document from results.

A token is ``{{fig:KEY}}`` or ``{{fig:KEY|FORMAT}}``; with several results
files, ``{{fig:NAME/KEY}}``. ``KEY`` is a key of the ``figures`` map of a
results document. Without a format the token becomes the figure's text; with
one, the figure's value written with that Python format specification.

Text outside the tokens is never changed. Every token is read before
anything is refused, so a refusal names every problem the document has:

* a format applied to a figure whose value is not a number, or a format
  Python cannot apply to the value, is a usage error (``E_USAGE``, exit 2);
* a key that no results document holds is ``E_FIGURE_MISSING`` (exit 7).
  Every missing key is listed, not only the first. When a missing key names
  a case with the mark a run adds to a name whose cut dropped words (' +'
  and eight hex digits), the message says that the mark is made with each
  run's own key.

A document with problems of both kinds is refused as a usage error first.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pairbench.errors import Refusal
from pairbench.model import Figure, Results

# A token: ``{{fig:`` and everything up to the first ``}}`` on the same line.
TOKEN = re.compile(r"\{\{fig:(.*?)\}\}")
# The mark a run adds to a case name whose cut dropped words, as a key holds it.
MARKED_CASE = re.compile(r" \+[0-9a-f]{8}(?=[./]|$)")
MARK_HINT = (
    "; the mark ' +' and eight hex digits at the end of a case name is made with each run's "
    "own key, so the results of another run or another compare name that case otherwise: fill "
    "from the results the document's figures came from, or from one compare of all their "
    "captures"
)


@dataclass(frozen=True)
class Token:
    """One token of a document, split into its parts.

    ``name`` is the results name, the empty text where the token carries
    none. ``key`` is the figure key and ``format`` the format specification,
    or ``None`` where the token has no ``|``.
    """

    text: str
    name: str
    key: str
    format: str | None

    @property
    def shown(self) -> str:
        """The figure the token names, as a refusal lists it: ``NAME/KEY`` or ``KEY``."""
        return f"{self.name}/{self.key}" if self.name else self.key


def parse_token(inner: str, names: Mapping[str, object]) -> Token:
    """Split the text inside ``{{fig:...}}`` into results name, key and format.

    The format is split off at the last ``|``. The text before the first
    ``/`` is a results name only when a results document was given under
    that name; otherwise the whole text is the key, because a case id may
    hold ``/``.
    """
    body, bar, spec = inner.rpartition("|")
    if not bar:
        body, spec = inner, ""
    head, slash, rest = body.partition("/")
    if slash and head and head in names:
        name, key = head, rest
    else:
        name, key = "", body
    return Token(text=f"{{{{fig:{inner}}}}}", name=name, key=key, format=spec if bar else None)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _formatted(token: Token, figure: Figure) -> str | None:
    """Return the text of a token, or ``None`` when its format cannot be applied."""
    if token.format is None:
        return figure.text
    if not _is_number(figure.value):
        return None
    try:
        return format(figure.value, token.format)
    except (ValueError, TypeError, OverflowError, MemoryError):
        # A width or a precision too large to write is a format that cannot be applied.
        return None


def fill_text(template: str, results: Mapping[str, Results]) -> str:
    """Fill every figure token of a template and return the document.

    ``results`` maps a results name to its document; the entry under the
    empty name serves the tokens that carry no name. A token whose figure is
    missing is never replaced by an empty text: the document is refused,
    every missing key listed in the message and under ``detail["missing"]``.
    A format that cannot be applied is refused as a usage error, every such
    token listed under ``detail["formats"]``.
    """
    missing: list[str] = []
    bad_formats: list[str] = []
    texts: dict[str, str] = {}
    for found in TOKEN.finditer(template):
        token = parse_token(found.group(1), results)
        if token.text in texts:
            continue
        document = results.get(token.name)
        figure = None if document is None else document.figures.get(token.key)
        if figure is None:
            if token.shown not in missing:
                missing.append(token.shown)
            continue
        text = _formatted(token, figure)
        if text is None:
            if token.text not in bad_formats:
                bad_formats.append(token.text)
            continue
        texts[token.text] = text
    if bad_formats:
        raise Refusal(
            "E_USAGE",
            "a format can be applied only to a figure whose value is a number, and only "
            f"a format Python accepts for it: {', '.join(bad_formats)}",
            detail={"formats": bad_formats},
        )
    if missing:
        count = "1 figure is" if len(missing) == 1 else f"{len(missing)} figures are"
        hint = MARK_HINT if any(MARKED_CASE.search(key) for key in missing) else ""
        raise Refusal(
            "E_FIGURE_MISSING",
            f"{count} missing from the results: {', '.join(missing)}{hint}",
            detail={"missing": missing},
        )
    return TOKEN.sub(lambda found: texts[found.group(0)], template)


def is_current(filled: str, output: Path) -> bool:
    """Say whether an existing output file holds exactly the filled text.

    This is the comparison of ``fill --check``: the text is compared byte for
    byte with the file, encoded as UTF-8. A file that does not exist is not
    current.
    """
    try:
        held = output.read_bytes()
    except FileNotFoundError:
        return False
    return held == filled.encode("utf-8")


__all__ = ["TOKEN", "Token", "fill_text", "is_current", "parse_token"]
