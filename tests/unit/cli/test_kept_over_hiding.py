# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Six forms where the shown command hides more than the secret, kept on purpose.

Each hides a word that is no secret, because the rule that hides it cannot tell that word from
the secret it is there for; narrowing it would show the secret in the other reading.

- An ordinary value read with a client's options: ``-a WORD`` in a variable is hidden when a
  later word of the same command names a client, whatever that word is an argument of, since
  the variable may be read by that client. Two sides that differ only in that word are one
  side, and ``--allow-identical`` compares them.
- The word after an Authorization scheme word that is a credential's whole value
  (``env AUTH=basic PROGRAM``, ``--auth bearer PROGRAM``) is hidden, since it is the token in
  ``--auth Bearer TOKEN``. The typed comparison reads it as typed, so two programs there are
  two sides, with one note.
- After ``secret set``, the words up to the secret's value are its name and value, so an option
  before the name and its value are hidden too: ``gh secret set --repo org/x NAME``. Two sides
  that differ only in that option's value are one side.
- A bare credential value in a program's text runs to the end of its word, since a password may
  hold ``)``, ``;`` or ``&``: in ``python3 -c 'API_KEY=V)run()'`` the ``)run()`` after the value
  is hidden with it. Two sides that differ only there are one side.
- A credential value glued to its name in the text of ``node -e`` or ``perl -e`` hides the rest
  of the text, since Perl and JavaScript end a string where a reading as Python's does not:
  in ``node -e "API_KEY='V';run()"`` the ``;run()`` after the value is hidden with it. Two
  sides that differ only there are one side.
- In an ssh argument list, after a word its shell may split (``$X``), a command that ends at an
  operator glued to a word leaves the next client's settings in an unknown turn, so a credential
  setting's name read as a value hides the word after it:
  ``CONFIG SET maxmemory requirepass WORD``. Two sides that differ only in that word are one side.
"""

from __future__ import annotations

import shlex
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import model
from pairbench.errors import EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

PYTHON = shlex.quote(sys.executable)
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
HIDDEN_NOTE = (
    "pairbench: note: sides_differ_in_hidden_value: sides 'a' and 'b' have the same fingerprint "
    "and differ only in a value the results hide; they are compared as two sides, and the "
    "results do not show the value\n"
)
FAST, SLOW = "fastmode", "slowmode"
REPO_A, REPO_B = "org/made-up-a", "org/made-up-b"
TAIL_A, TAIL_B = "zqalpha", "zqbravo"

# Each kept form, with ``{v}`` where the word stands; words are joined by ``|``.
LATER_CLIENT = "env|MADE_UP_OPTS=-a {v}|true|--backend|redis-cli"
SECRET_SET = "true|secret|set|--repo|{v}|MADE_UP_NAME"
SCHEME_FORMS = {
    "env-basic-program": "env|AUTH=basic|{v}",
    "auth-bearer-program": f"{PYTHON}|-c|pass|--auth|bearer|{{v}}",
}
# A made-up password, and the forms whose word after it, or after a setting name, is hidden.
PASSWORD = "kiwi7mango"
ONE_SIDE_FORMS = {
    "bare-value-in-a-program-text": f"sh|-c|python3 -c 'API_KEY={PASSWORD}){{v}}()'",
    "glued-value-in-a-node-text": f"node|-e|API_KEY='{PASSWORD}';{{v}}()",
    "setting-name-after-a-split-word-in-ssh": (
        "ssh|made-up-host|redis-cli|CONFIG|SET|$X|a;|redis-cli|CONFIG|SET|maxmemory|requirepass|"
        "{v}|yes"
    ),
}
# Each kept form as the shown command gives it.
SHOWN = (
    (
        ["env", "MADE_UP_OPTS=-a fastmode", "./made-up-serve", "--backend", "redis-cli"],
        "env 'MADE_UP_OPTS=-a <hidden>' ./made-up-serve --backend redis-cli",
    ),
    (["env", "AUTH=basic", "./made-up-bench"], "env 'AUTH=<hidden>' '<hidden>'"),
    (
        ["./made-up-tool", "--auth", "bearer", "./made-up-bench"],
        "./made-up-tool --auth '<hidden>' '<hidden>'",
    ),
    (
        ["gh", "secret", "set", "--repo", "org/made-up-a", "MADE_UP_NAME"],
        "gh secret set --repo '<hidden>' '<hidden>'",
    ),
    (
        ["sh", "-c", f"python3 -c 'API_KEY={PASSWORD})run()'"],
        "sh -c 'python3 -c '\"'\"'API_KEY=<hidden>'\"'\"''",
    ),
    (["node", "-e", f"API_KEY='{PASSWORD}';run()"], "node -e 'API_KEY=<hidden>'"),
    (
        [
            "ssh",
            "made-up-host",
            "redis-cli",
            "CONFIG",
            "SET",
            "$X",
            "a;",
            "redis-cli",
            "CONFIG",
            "SET",
            "maxmemory",
            "requirepass",
            "zqalpha",
            "yes",
        ],
        "ssh made-up-host redis-cli CONFIG SET '$X' 'a;' redis-cli CONFIG SET maxmemory "
        "requirepass '<hidden>' yes",
    ),
)


def _side(form: str, value: str) -> str:
    return " ".join(shlex.quote(word) for word in form.format(v=value).split("|"))


def _plan(cli: Cli, form: str, one: str, two: str, *extra: str) -> Any:
    return cli(
        "plan", "--side", f"a=cmd:{_side(form, one)}", "--side", f"b=cmd:{_side(form, two)}", *extra
    )


@pytest.fixture
def programs(tmp_path: Path) -> tuple[str, str]:
    """Two made-up programs whose paths differ only in their names."""
    folder = tmp_path / "programs"
    folder.mkdir()
    paths = []
    for name in (TAIL_A, TAIL_B):
        program = folder / name
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        paths.append(str(program))
    return paths[0], paths[1]


@pytest.mark.parametrize(("typed", "shown"), SHOWN)
def test_each_kept_form_is_shown_with_the_word_hidden(typed: list[str], shown: str) -> None:
    assert model.public_command(typed) == shown


def test_two_sides_that_differ_only_in_a_value_a_later_client_reads_are_one_side(
    cli: Cli,
) -> None:
    result = _plan(cli, LATER_CLIENT, FAST, SLOW)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for word in (FAST, SLOW):
        assert word not in result.out
        assert word not in result.err


def test_allow_identical_compares_the_two_sides_a_later_client_makes_one(cli: Cli) -> None:
    result = _plan(cli, LATER_CLIENT, FAST, SLOW, "--allow-identical")

    assert result.code == EXIT_OK, result.err
    for word in (FAST, SLOW):
        assert word not in result.out
        assert word not in result.err


def test_two_sides_that_differ_only_in_an_option_before_a_secret_name_are_one_side(
    cli: Cli,
) -> None:
    result = _plan(cli, SECRET_SET, REPO_A, REPO_B)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for word in (REPO_A, REPO_B):
        assert word not in result.out
        assert word not in result.err


@pytest.mark.parametrize("form", list(ONE_SIDE_FORMS.values()), ids=list(ONE_SIDE_FORMS))
def test_two_sides_that_differ_only_in_a_word_hidden_after_a_value_are_one_side(
    cli: Cli, form: str
) -> None:
    result = _plan(cli, form, TAIL_A, TAIL_B)

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    for word in (TAIL_A, TAIL_B, PASSWORD):
        assert word not in result.out
        assert word not in result.err


@pytest.mark.parametrize("form", list(SCHEME_FORMS.values()), ids=list(SCHEME_FORMS))
def test_two_programs_after_a_scheme_word_value_are_two_sides_with_one_note(
    cli: Cli, programs: tuple[str, str], form: str
) -> None:
    result = _plan(cli, form, *programs)

    assert result.code == EXIT_OK, result.err
    assert result.err.count(HIDDEN_NOTE) == 1
    for word in (TAIL_A, TAIL_B):
        assert word not in result.out
        assert word not in result.err
