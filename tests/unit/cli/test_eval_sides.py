# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides whose ``eval`` assigns a credential before two programs are two sides.

The ``eval`` stands in a command substitution, in a subshell or after a line
continuation, and its text assigns a credential in escaped quotes before the
program. ``plan`` takes the two programs as two sides; two sides that differ only
in the password are one side, refused with ``E_SAME_SIDE``, and neither password
is printed. Every value is made up.
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
# Two made-up passwords.
OLD, NEW = "kiwi7mango42", "plum4grape19"

# Each shell text, ``{v}`` the password and ``{p}`` the program.
TEXTS = {
    "an eval in a command substitution": (
        "x=$(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')"
    ),
    "an eval in double quotes and a command substitution": (
        "x=\"$(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')\""
    ),
    "an eval in escaped double quotes in a command substitution": (
        'x="$(eval "PGPASSWORD=\\"made {v}\\" {p} -h db.example")"'
    ),
    "an eval in a process substitution": (
        "cat <(eval 'PGPASSWORD='\\''{v}'\\'' {p} -h db.example')"
    ),
    "an eval in a subshell": "(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')",
    "an eval after a line continuation": "true && \\\n  eval 'PGPASSWORD={v} {p} -h db.example'",
}


def _side(text: str, value: str, program: str) -> str:
    return shlex.join(["sh", "-c", text.format(v=value, p=program)])


@pytest.mark.parametrize("form", sorted(TEXTS))
def test_plan_takes_two_programs_after_a_credential_in_an_eval_as_two_sides(
    cli: Cli, form: str
) -> None:
    result = cli(
        "plan",
        "--side",
        f"a=cmd:{_side(TEXTS[form], OLD, 'psql')}",
        "--side",
        f"b=cmd:{_side(TEXTS[form], OLD, 'pgbench')}",
    )

    assert result.code == EXIT_OK, result.err
    assert result.err == ""
    assert OLD not in result.out


@pytest.mark.parametrize("form", sorted(TEXTS))
def test_plan_refuses_two_sides_that_differ_only_in_the_password_in_an_eval(
    cli: Cli, form: str
) -> None:
    result = cli(
        "plan",
        "--side",
        f"a=cmd:{_side(TEXTS[form], OLD, 'psql')}",
        "--side",
        f"b=cmd:{_side(TEXTS[form], NEW, 'psql')}",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for secret in (OLD, NEW):
        assert secret not in result.out
        assert secret not in result.err
