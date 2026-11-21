# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides that differ only in a secret of a glued name or of ``secret set`` are one side.

``plan`` refuses them with ``E_SAME_SIDE``, as it refuses two sides that differ
only in any other hidden credential, and prints neither secret. Two sides that
differ in the value of an ordinary sibling of those names are two sides.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
# Two made-up secrets, and two made-up ordinary values.
OLD, NEW = "kiwi7zq", "plum4zq"

# Each form, with ``{v}`` where the value stands; words are joined by ``|``.
SECRET_FORMS = {
    "password-hash-variable": "env|PASSWDHASH={v}|true",
    "password-text-option": "true|--passwdtext|{v}",
    "glued-auth-option": "true|--masterauth={v}",
    "secret-body": "true|secret|set|MADE_UP_NAME|--body|{v}",
    "secret-short-body": "true|secret|set|MADE_UP_NAME|-b|{v}",
    "secrets-name-and-value": "true|secrets|set|MADE_UP_NAME={v}",
}
ORDINARY_FORMS = {
    "master-port-variable": "env|MASTER_PORT={v}|true",
    "variable-body": "true|variable|set|MADE_UP_NAME|--body|{v}",
    "plaintext-option": "true|--plaintext|{v}",
}


def _side(form: str, value: str) -> str:
    return " ".join(shlex.quote(word) for word in form.format(v=value).split("|"))


def _plan(cli: Cli, form: str, one: str, two: str) -> Any:
    return cli("plan", "--side", f"a=cmd:{_side(form, one)}", "--side", f"b=cmd:{_side(form, two)}")


@pytest.mark.parametrize("form", list(SECRET_FORMS.values()), ids=list(SECRET_FORMS))
def test_plan_refuses_sides_that_differ_only_in_such_a_secret(cli: Cli, form: str) -> None:
    result = _plan(cli, form, OLD, NEW)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for secret in (OLD, NEW):
        assert secret not in result.out
        assert secret not in result.err


@pytest.mark.parametrize("form", list(ORDINARY_FORMS.values()), ids=list(ORDINARY_FORMS))
def test_plan_takes_sides_that_differ_in_an_ordinary_sibling_as_two(cli: Cli, form: str) -> None:
    result = _plan(cli, form, "alpha", "beta")

    assert result.code == EXIT_OK, result.err
    assert result.err == ""
