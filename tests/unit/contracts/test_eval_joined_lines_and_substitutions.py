# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An ``eval`` after a line continuation or in a command substitution is read as its shell reads it.

A backslash before a line break joins two lines, so an ``eval`` on the next line
still starts its command, and a client glued to the line break (``&&\\`` then
``redis-cli``) is a word of its own: the AUTH password a ``memtier_benchmark``
command gives in escaped single quotes, and a client's password option, are
hidden in the shown command and in the hash. In ``$( )``, ``<( )`` and
``"$( )"`` the text is read as the shell text it is, so a credential assigned at
the start of an ``eval`` text there loses only its value, and the program after
it still tells two commands apart; a value in escaped double quotes inside
``"$( )"`` is hidden too. Ordinary words across a line continuation or in a
substitution are shown as typed. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Where a command stands after a line continuation, ``X`` being the command.
PLACES: dict[str, str] = {
    "after && and a continuation": "redis-cli FLUSHALL && \\\n  X",
    "after ; and a continuation": "true; \\\n  X",
    "after | and a continuation": "true | \\\n  X",
    "after || and a continuation": "true || \\\n  X",
    "after { and a continuation": "{ \\\n  X; }",
    "after then and a continuation": "if true; then \\\n  X; fi",
    "after a continuation at the start": "\\\n  X",
    "glued to && and a continuation": "true &&\\\nX",
    "glued to ; and a continuation": "true;\\\nX",
}

# A command that gives a password, with ``{v}`` the password.
SECRET_COMMANDS = {
    "an eval of a text in single quotes": ("eval 'memtier_benchmark --command '\\''AUTH {v}'\\'''"),
    "an eval of words with escaped quotes": "eval memtier_benchmark --command \\'AUTH {v}\\'",
    "a builtin eval": "builtin eval 'memtier_benchmark --command '\\''AUTH {v}'\\'''",
    "a client's password option": "redis-cli -a {v} PING",
    "a memtier AUTH command": "memtier_benchmark --command 'AUTH {v}'",
}

# Shell texts that give a password in a substitution or across a continuation.
SECRET_TEXTS = {
    "a continuation in the middle of a command": "redis-cli \\\n  -a {v} PING",
    "a continuation inside a password": "redis-cli -a {v}\\\nx PING",
    "an eval in double quotes in $( )": (
        'x="$(eval "PGPASSWORD=\\"made {v}\\" psql -h db.example")"'
    ),
    "sh -c in double quotes in $( )": 'x="$(sh -c "PGPASSWORD=\\"made {v}\\" psql")"',
    "an option in escaped double quotes in $( )": 'x="$(mytool "--password=\\"made {v}\\"")"',
    "a token option in sh -c in $( )": 'x="$(sh -c "tool --token=\\"made {v}\\"")"',
    "an eval in double quotes in $( ) after echo": (
        'echo "$(eval "API_TOKEN=\\"made {v}\\" psql")"'
    ),
}

# Shell texts that assign a credential before a program, ``{p}`` the program.
ASSIGNED_TEXTS = {
    "an eval in $( )": "x=$(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')",
    "an eval in $( ) with no blank in the value": (
        "x=$(eval 'PGPASSWORD='\\''{v}'\\'' {p} -h db.example')"
    ),
    "an eval in double quotes and $( )": (
        "x=\"$(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')\""
    ),
    "an eval in <( )": "cat <(eval 'PGPASSWORD='\\''{v}'\\'' {p} -h db.example')",
    "an eval in $( ) after echo": "echo $(eval 'API_TOKEN='\\''{v}'\\'' {p} -h db.example')",
    "an eval in a subshell": "(eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example')",
    "an eval in $( ) with a value in double quotes": (
        "x=$(eval 'PGPASSWORD='\"'\"'made {v}'\"'\"' {p} -h db.example')"
    ),
    "an eval in double quotes in $( ) with escaped double quotes": (
        'x="$(eval "PGPASSWORD=\\"made {v}\\" {p} -h db.example")"'
    ),
    "an eval after && and a continuation": ("true && \\\n eval 'PGPASSWORD={v} {p} -h db.example'"),
    "an eval after a continuation at the start": ("\\\neval 'PGPASSWORD={v} {p} -h db.example'"),
    "an assignment glued to && and a continuation": ("true &&\\\nPGPASSWORD={v} {p} -h db.example"),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def assert_hidden(commands: list[list[str]]) -> None:
    shown = [model.public_command(words) for words in commands]
    hashed = [json.dumps(model.hashed_argv(words)) for words in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


@pytest.mark.parametrize("form", sorted(SECRET_COMMANDS))
@pytest.mark.parametrize("place", sorted(PLACES))
def test_a_password_after_a_line_continuation_is_hidden(place: str, form: str) -> None:
    text = PLACES[place].replace("X", SECRET_COMMANDS[form])

    assert_hidden([["sh", "-c", text.replace("{v}", value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(SECRET_TEXTS))
def test_a_password_in_a_substitution_or_across_a_continuation_is_hidden(form: str) -> None:
    assert_hidden([["sh", "-c", SECRET_TEXTS[form].format(v=value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(ASSIGNED_TEXTS))
def test_the_program_after_a_credential_in_a_substitution_tells_two_commands_apart(
    form: str,
) -> None:
    for value in VALUES:
        old = ["sh", "-c", ASSIGNED_TEXTS[form].format(v=value, p="psql")]
        new = ["sh", "-c", ASSIGNED_TEXTS[form].format(v=value, p="pgbench")]

        assert pieces(model.public_command(old), value) == []
        assert pieces(json.dumps(model.hashed_argv(old)), value) == []
        assert model.public_command(old) != model.public_command(new)
        assert model.hashed_argv(old) != model.hashed_argv(new)


# Commands as typed, with ``{v}`` the password, and as shown.
SHOWN = {
    "an eval after && and a continuation": (
        ["sh", "-c", "true && \\\n  eval 'memtier_benchmark --command '\\''AUTH {v}'\\'''"],
        "sh -c 'true && \\\n  eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"'",
    ),
    "a client glued to && and a continuation": (
        ["sh", "-c", "true &&\\\nredis-cli -a {v} PING"],
        "sh -c 'true &&\\\nredis-cli -a <hidden> PING'",
    ),
    "an assignment in an eval after a continuation": (
        ["sh", "-c", "true && \\\n eval 'PGPASSWORD={v} psql -h db.example'"],
        "sh -c 'true && \\\n eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"''",
    ),
    "an assignment in an eval in $( )": (
        ["sh", "-c", "x=$(eval 'PGPASSWORD='\\''made {v}'\\'' psql -h db.example')"],
        "sh -c 'x=$(eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"')'",
    ),
    "an assignment in an eval in a subshell": (
        ["sh", "-c", "(eval 'PGPASSWORD='\\''made {v}'\\'' psql -h db.example')"],
        "sh -c '(eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"')'",
    ),
    "an assignment in an eval in double quotes in $( )": (
        ["sh", "-c", 'x="$(eval "PGPASSWORD=\\"made {v}\\" psql -h db.example")"'],
        "sh -c 'x=\"$(eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"')\"'",
    ),
}


@pytest.mark.parametrize("row", sorted(SHOWN))
def test_a_continuation_or_a_substitution_is_shown_with_its_value_hidden(row: str) -> None:
    words, shown = SHOWN[row]

    for value in VALUES:
        assert model.public_command([word.replace("{v}", value) for word in words]) == shown


# Ordinary words across a line continuation and in a substitution.
SHOWN_AS_TYPED = {
    "an argument after a continuation": ["sh", "-c", "echo a \\\n  b"],
    "options after a continuation": ["sh", "-c", "./bench --n 5 \\\n  --threads 4"],
    "eval as an option's value across continuations": [
        "sh",
        "-c",
        "./bench \\\n  --mode eval \\\n  --n 5",
    ],
    "a program glued to && and a continuation": ["sh", "-c", "true &&\\\n./bench --n 5"],
    "an ordinary eval after a continuation": ["sh", "-c", "true && \\\n  eval 'echo hi'"],
    "an ordinary assignment in an eval after a continuation": [
        "sh",
        "-c",
        "true && \\\n  eval 'FOO=1 ./bench --n 5'",
    ],
    "a code text before a continuation": ["sh", "-c", "python3 -c 'print(1)' && \\\n  ./bench"],
    "an ordinary eval in a subshell": ["sh", "-c", "(eval 'ls -a data')"],
    "an ordinary eval in $( )": ["sh", "-c", "x=$(eval 'echo hi')"],
    "an ordinary eval in <( )": ["sh", "-c", "cat <(eval 'echo hi')"],
    "an ordinary eval in backquotes": ["sh", "-c", "x=`eval 'echo hi'`"],
    "words in double quotes in $( )": ["sh", "-c", 'x="$(echo "a b")"'],
    "an eval in double quotes in $( )": ["sh", "-c", 'x="$(eval "echo \\"a b\\"")"'],
    "escaped double quotes in $( )": ["sh", "-c", 'x="$(echo "label=\\"made x\\"")"'],
    "sh -c in double quotes in $( )": ["sh", "-c", 'x="$(sh -c "./bench --n 5")"'],
    "a code text in $( )": ["sh", "-c", "x=$(python3 -c 'print(\"a b\")')"],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_across_a_continuation_or_in_a_substitution_are_shown_as_typed(
    row: str,
) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
