# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides that differ only in a piece of a hidden value are one side.

A credential's value can go on past the place where a first reading would end it: a string
joined with ``||`` in a program's text, the rest of a shell word after three quotes, which a
shell reads as an empty string and an opening quote, or what is glued after the backquote that
closes a value in a setting's text. ``plan`` refuses two sides that differ only in such a piece
with ``E_SAME_SIDE``, and neither piece reaches either stream.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.errors import EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
PIECES = ("kiwi7", "plum4")

# Each form: the side's shell text with ``{s}`` for the piece the two sides differ in.
FORMS = {
    "a string joined with || in a program's text": (
        """psql -c "ALTER ROLE app PASSWORD='made'||'{s}'\""""
    ),
    "three quotes in a shell's text": "API_KEY='''a'b''' {s}' ./bench-old",
    "letters after a closing backquote in a setting": "./bench-old --config '{password: `a`{s}}'",
}


@pytest.mark.parametrize("text", list(FORMS.values()), ids=list(FORMS))
def test_plan_refuses_two_sides_that_differ_only_in_a_piece_of_a_value(cli: Cli, text: str) -> None:
    one, two = (text.replace("{s}", piece) for piece in PIECES)
    result = cli(
        "plan",
        "--side",
        f"a=cmd:sh -c {shlex.quote(one)}",
        "--side",
        f"b=cmd:sh -c {shlex.quote(two)}",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for piece in PIECES:
        assert piece not in result.out + result.err
