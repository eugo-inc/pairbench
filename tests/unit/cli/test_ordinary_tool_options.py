# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides that differ in the value of a tool's ordinary key or token option are two sides.

``plan`` takes them as two, as it takes two sides that differ in any shown
value; two sides that differ only in a password after such an option are one
side, refused with ``E_SAME_SIDE``, and neither password is printed.
"""

from __future__ import annotations

import shlex
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
# Two made-up secrets.
OLD, NEW = "kiwi7zq", "plum4zq"

# Each form, with ``{v}`` where the value stands; words are joined by ``|``.
ORDINARY_FORMS = {
    "multi-key-get": "true|--multi-key-get|{v}",
    "key-id-range": "true|--key_id_range|{v}",
    "keyrange-num": "true|--keyrange_num|{v}",
    "keyrange-dist": "true|--keyrange_dist_a={v}",
    "merge-keys": "true|--merge_keys|{v}",
    "use-existing-keys": "true|--use_existing_keys={v}",
    "key-type": "true|--key-type|{v}",
    "keybits-option": "true|--keybits={v}",
    "keybits-variable": "env|KEYBITS={v}|true",
    "max-token-glued": "env|MAXTOKEN={v}|true",
    "max-token": "env|MAX_TOKEN={v}|true",
    "token-rate": "true|--token-rate|{v}",
    "token-file": "true|--token-file|{v}",
    "token-file-variable": "env|TOKEN_FILE={v}|true",
    "seed-token": "true|--seed-token|{v}",
    "token-healing": "true|--token-healing={v}",
    "axis-glued": "true|--axis=Key={v}",
    "axis-short-glued": "true|-aKey={v}",
}
SECRET_FORMS = {
    "password-after-keybits": "true|--keybits|4|--password|{v}",
    "password-after-token-rate": "true|--token-rate=4|--password={v}",
}


@pytest.fixture
def client(tmp_path: Path) -> str:
    """A made-up program named as a client whose ``-a`` takes a password, quoted."""
    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "redis-cli"
    program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return shlex.quote(str(program))


def _side(form: str, value: str) -> str:
    return " ".join(shlex.quote(word) for word in form.format(v=value).split("|"))


def _plan(cli: Cli, form: str, one: str, two: str) -> Any:
    return cli("plan", "--side", f"a=cmd:{_side(form, one)}", "--side", f"b=cmd:{_side(form, two)}")


@pytest.mark.parametrize("form", list(ORDINARY_FORMS.values()), ids=list(ORDINARY_FORMS))
def test_plan_takes_sides_that_differ_in_an_ordinary_option_as_two(cli: Cli, form: str) -> None:
    result = _plan(cli, form, "4", "8")

    assert result.code == EXIT_OK, result.err
    assert result.err == ""


@pytest.mark.parametrize("form", list(SECRET_FORMS.values()), ids=list(SECRET_FORMS))
def test_plan_refuses_sides_that_differ_only_in_a_password_beside_them(cli: Cli, form: str) -> None:
    result = _plan(cli, form, OLD, NEW)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for secret in (OLD, NEW):
        assert secret not in result.out
        assert secret not in result.err


def test_plan_refuses_client_sides_that_differ_only_in_a_password_glued_to_a(
    cli: Cli, client: str
) -> None:
    result = cli(
        "plan",
        "--side",
        f"a=cmd:{client} -aKey={OLD} ping",
        "--side",
        f"b=cmd:{client} -aKey={NEW} ping",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for secret in (OLD, NEW):
        assert secret not in result.out
        assert secret not in result.err
