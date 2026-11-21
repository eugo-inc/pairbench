# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An ``eval`` after a reserved word of a shell is read as one at the start of a command.

After ``{``, ``!``, ``if``, ``then``, ``else``, ``elif``, ``while``, ``until``,
``do``, ``time`` (and its ``-p``) and in the body of a function, the next word
starts a command, so an ``eval`` there runs the shell text its words make: the
AUTH password a ``memtier_benchmark`` command gives in escaped single quotes is
hidden in the shown command and in the hash, and a credential assigned at the
start of the text loses only its value, so the program after it still tells two
commands apart. A credential's value that closes the quotes it stands in to
quote itself one level down (``'PGPASSWORD='\\''VALUE'\\'' psql'``) keeps the
program after it too. Ordinary words after these reserved words are shown as
typed. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Where an ``eval`` stands, ``X`` being the ``eval`` and its words.
PLACES: dict[str, str] = {
    "in braces": "{ X; }",
    "after then": "if true; then X; fi",
    "after else": "if false; then :; else X; fi",
    "after elif and then": "if false; then :; elif true; then X; fi",
    "after do": "for i in 1 2; do X; done",
    "as the test of if": "if X; then :; fi",
    "as the test of while": "while X; do :; done",
    "as the test of until": "until X; do :; done",
    "after !": "! X",
    "after time": "time X",
    "after time -p": "time -p X",
    "in the body of a function": "f() { X; }",
    "in the body of a function that function names": "function f { X; }",
    "in braces after an operator": "true || { X; }",
}

# The ``eval`` of an AUTH command in escaped single quotes, with ``{v}`` its password.
AUTH_EVALS = {
    "a text in single quotes": "eval 'memtier_benchmark --command '\\''AUTH {v}'\\'''",
    "words with escaped quotes": "eval memtier_benchmark --command \\'AUTH {v}\\'",
}

# The ``eval`` of a credential assigned before a program, ``{p}`` the program.
ASSIGNED_EVALS = {
    "a value with no quotes": "eval 'PGPASSWORD={v} {p} -h db.example'",
    "a value in escaped single quotes": "eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'",
    "a value in double quotes in single quotes": (
        "eval 'PGPASSWORD='\"'\"'made {v}'\"'\"' {p} -h db.example'"
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def command(place: str, form: str, value: str, program: str = "psql") -> list[str]:
    return ["sh", "-c", PLACES[place].replace("X", form.format(v=value, p=program))]


@pytest.mark.parametrize("form", sorted(AUTH_EVALS))
@pytest.mark.parametrize("place", sorted(PLACES))
def test_an_auth_password_in_an_eval_after_a_reserved_word_is_hidden(place: str, form: str) -> None:
    commands = [command(place, AUTH_EVALS[form], value) for value in VALUES]
    shown = [model.public_command(words) for words in commands]
    hashed = [json.dumps(model.hashed_argv(words)) for words in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


@pytest.mark.parametrize("form", sorted(ASSIGNED_EVALS))
@pytest.mark.parametrize("place", sorted(PLACES))
def test_the_program_after_a_credential_assigned_in_an_eval_tells_two_commands_apart(
    place: str, form: str
) -> None:
    for value in VALUES:
        old = command(place, ASSIGNED_EVALS[form], value, "psql")
        new = command(place, ASSIGNED_EVALS[form], value, "pgbench")

        assert pieces(model.public_command(old), value) == []
        assert pieces(json.dumps(model.hashed_argv(old)), value) == []
        assert model.public_command(old) != model.public_command(new)
        assert model.hashed_argv(old) != model.hashed_argv(new)


# The ``eval`` of a credential's value in escaped single quotes, as shown.
SHOWN = {
    "at the start of a text": (
        ["sh", "-c", "eval 'PGPASSWORD='\\''made {v}'\\'' psql -h db.example'"],
        "sh -c 'eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"''",
    ),
    "in braces": (
        ["sh", "-c", "{ eval 'memtier_benchmark --command '\\''AUTH {v}'\\'''; }"],
        "sh -c '{ eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"; }'",
    ),
    "after then": (
        ["sh", "-c", "if true; then eval 'PGPASSWORD={v} psql -h db.example'; fi"],
        "sh -c 'if true; then eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"'; fi'",
    ),
}


@pytest.mark.parametrize("row", sorted(SHOWN))
def test_an_eval_after_a_reserved_word_is_shown_with_its_value_hidden(row: str) -> None:
    words, shown = SHOWN[row]

    for value in VALUES:
        assert model.public_command([word.replace("{v}", value) for word in words]) == shown


# Ordinary words after the reserved words, and the options of ``time``.
SHOWN_AS_TYPED = {
    "a command in braces": ["sh", "-c", "{ echo hi; }"],
    "a command after then": ["sh", "-c", "if true; then ./bench --n 5; fi"],
    "a command after time -p": ["sh", "-c", "time -p ./bench --threads 4"],
    "a command after time -o and its file": ["sh", "-c", "time -o out.txt ./bench"],
    "time with a format, as its own program": ["time", "-f", "%e", "./bench", "--n", "5"],
    "a function that function names": ["sh", "-c", "function f { ./bench --n 5; }; f"],
    "a command after !": ["sh", "-c", "! ./bench --n 5"],
    "an ordinary eval in braces": ["sh", "-c", "{ eval 'FOO=1 ./bench --n 5'; }"],
    "then as an argument": ["sh", "-c", "echo then eval 'x y'"],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_after_a_reserved_word_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
