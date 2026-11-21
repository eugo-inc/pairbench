# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A text in backquotes is read as the shell runs it, with its layer of backslashes taken off.

Inside backquotes the shell takes the backslash off before a backslash, a
backquote or a ``$``, and inside backquotes in double quotes before a double
quote too, before it runs the text. So ``x="`eval "tool \\\\"AUTH V\\\\""`"``
runs ``eval "tool \\"AUTH V\\""``, as ``x="$(eval "tool \\"AUTH V\\"")"`` does.
An ``eval``, a ``sh -c`` or a client inside backquotes is read the same way:
the AUTH password a ``memtier_benchmark`` command gives, a client's password
option and a credential assigned before a program are hidden in the shown
command and in the hash, and the program after a hidden credential still
tells two commands apart. The text an ``eval`` runs is read with its programs'
code, so ``eval python3 -c \\"token = \\'V\\'\\"`` hides the value as
``python3 -c "token = 'V'"`` does. Ordinary texts in backquotes are shown as
typed. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Texts that give a password, as written inside ``$( )``, with ``{v}`` the password.
SECRET_INNERS = {
    "memtier AUTH in escaped double quotes in an eval": (
        'eval "memtier_benchmark --command \\"AUTH {v}\\""'
    ),
    "memtier AUTH in single quotes in an eval": ("eval \"memtier_benchmark --command 'AUTH {v}'\""),
    "redis-cli -a in escaped double quotes in an eval": 'eval "redis-cli -a \\"{v}\\" PING"',
    "redis-cli -a with a blank in an eval": 'eval "redis-cli -a \\"made {v}\\" PING"',
    "PGPASSWORD in escaped double quotes in an eval": (
        'eval "PGPASSWORD=\\"{v}\\" psql -h db.example"'
    ),
    "PGPASSWORD with a blank in an eval": 'eval "PGPASSWORD=\\"made {v}\\" psql -h db.example"',
    "a token option in an eval": 'eval "./bench --token \\"{v}\\""',
    "memtier AUTH in sh -c": 'sh -c "memtier_benchmark --command \\"AUTH {v}\\""',
    "PGPASSWORD with a blank in sh -c": 'sh -c "PGPASSWORD=\\"made {v}\\" psql -h db.example"',
}

# Where the text stands: in backquotes in double quotes, and in backquotes alone.
PLACES = {
    "backquotes in double quotes": 'x="`{text}`"',
    "backquotes": "x=`{text}`",
}

# Texts that assign a credential before a program, ``{p}`` the program.
ASSIGNED_TEXTS = {
    "an eval in backquotes in double quotes": (
        'x="`eval "PGPASSWORD=\\\\"made {v}\\\\" {p} -h db.example"`"'
    ),
    "an eval in backquotes in double quotes with no blank in the value": (
        'x="`eval "PGPASSWORD=\\\\"{v}\\\\" {p} -h db.example"`"'
    ),
    "an eval in backquotes": 'x=`eval "PGPASSWORD=\\\\"made {v}\\\\" {p} -h db.example"`',
    "an eval of a single-quoted text in backquotes": (
        "x=`eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'`"
    ),
}

# Code an eval runs, in words with escaped quotes, ``{v}`` the value.
CODE_TEXTS = {
    "a python3 assignment": "eval python3 -c \\\"token = \\'{v}\\'\\\"",
    "a python3 keyword argument": "eval python3 -c \\\"connect\\(password=\\'{v}\\'\\)\\\"",
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def in_backquotes(text: str, place: str) -> str:
    """Write a text of ``$( )`` in backquotes, with a backslash before each of its backslashes."""
    return PLACES[place].format(text=text.replace("\\", "\\\\"))


def assert_hidden(commands: list[list[str]]) -> None:
    shown = [model.public_command(words) for words in commands]
    hashed = [json.dumps(model.hashed_argv(words)) for words in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


@pytest.mark.parametrize("place", sorted(PLACES))
@pytest.mark.parametrize("form", sorted(SECRET_INNERS))
def test_a_password_in_backquotes_is_hidden(form: str, place: str) -> None:
    text = in_backquotes(SECRET_INNERS[form], place)

    assert_hidden([["sh", "-c", text.replace("{v}", value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(ASSIGNED_TEXTS))
def test_the_program_after_a_credential_in_backquotes_tells_two_commands_apart(form: str) -> None:
    for value in VALUES:
        old = ["sh", "-c", ASSIGNED_TEXTS[form].format(v=value, p="psql")]
        new = ["sh", "-c", ASSIGNED_TEXTS[form].format(v=value, p="pgbench")]

        assert pieces(model.public_command(old), value) == []
        assert pieces(json.dumps(model.hashed_argv(old)), value) == []
        assert model.public_command(old) != model.public_command(new)
        assert model.hashed_argv(old) != model.hashed_argv(new)


@pytest.mark.parametrize("form", sorted(CODE_TEXTS))
def test_code_in_an_eval_of_words_with_escaped_quotes_is_hidden(form: str) -> None:
    assert_hidden([["sh", "-c", CODE_TEXTS[form].format(v=value)] for value in VALUES])


# Commands as typed, with ``{v}`` the password, and as shown.
SHOWN = {
    "memtier AUTH in an eval in backquotes in double quotes": (
        ["sh", "-c", 'x="`eval "memtier_benchmark --command \\\\"AUTH {v}\\\\""`"'],
        "sh -c 'x=\"`eval '\"'\"'memtier_benchmark --command \"AUTH <hidden>\"'\"'\"'`\"'",
    ),
    "a credential with a blank in an eval in backquotes in double quotes": (
        ["sh", "-c", 'x="`eval "PGPASSWORD=\\\\"made {v}\\\\" psql -h db.example"`"'],
        "sh -c 'x=\"`eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"'`\"'",
    ),
    "code in an eval of words with escaped quotes": (
        ["sh", "-c", "eval python3 -c \\\"token = \\'{v}\\'\\\""],
        "sh -c 'eval \"python3 -c \\\"token = '\"'\"'<hidden>'\"'\"'\\\"\"'",
    ),
}


@pytest.mark.parametrize("row", sorted(SHOWN))
def test_a_text_in_backquotes_is_shown_with_its_value_hidden(row: str) -> None:
    words, shown = SHOWN[row]

    for value in VALUES:
        assert model.public_command([word.replace("{v}", value) for word in words]) == shown


# Ordinary texts in backquotes, escaped quotes, backquotes and ``$`` among them.
SHOWN_AS_TYPED = {
    "an eval of escaped double quotes in backquotes in double quotes": [
        "sh",
        "-c",
        'x="`eval "echo \\\\"a b\\\\""`"',
    ],
    "an eval of a label in backquotes": ["sh", "-c", 'x=`eval "./bench --label \\\\"a b\\\\""`'],
    "a label in backquotes in double quotes": ["sh", "-c", 'x="`./bench --label \\\\"a b\\\\"`"'],
    "words in double quotes in backquotes": ["sh", "-c", 'x=`echo "a b"`'],
    "backquotes in backquotes": ["sh", "-c", "x=`echo \\`date\\``"],
    "an escaped $ in backquotes": ["sh", "-c", "x=`echo \\$HOME`"],
    "a user name in an eval in backquotes": [
        "sh",
        "-c",
        'x="`eval "PGUSER=\\\\"bob\\\\" psql -h db.example"`"',
    ],
    "an eval of python3 code with escaped quotes": [
        "sh",
        "-c",
        "eval python3 -c \\\"print\\(\\'a b\\'\\)\\\"",
    ],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_texts_in_backquotes_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
