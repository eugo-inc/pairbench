# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An ``eval`` named in any way a shell runs it is read as an ``eval``, and so is a ``trap`` text.

A shell runs ``eval`` after ``builtin`` and ``command``, with the options they take before the
command they run (``command -p``, ``command --``, ``builtin --``), after ``coproc`` and in the
group or subshell it runs, its name before it or none, and quoted or escaped (``\\eval``,
``"eval"``, ``'eval'``, ``e\\val``), as it runs ``eval`` itself. Each spelling is read as an
``eval``, so the AUTH password a ``memtier_benchmark`` command gives in escaped single quotes
there is hidden in the shown command and in the hash, and a credential assigned at the start of
its text loses only its value, the program after it still telling two commands apart. The
action of ``trap`` is a shell text the shell runs later, read as any shell text is, an ``eval``
in it too, and a client named with a backslash (``\\redis-cli``) is the client. Ordinary words
in each of these places are shown as typed. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# A memtier AUTH command in an eval text in single quotes, its quotes escaped as the shell
# needs them inside, with ``{v}`` the password.
TEXT = "'memtier_benchmark --command '\\''AUTH {v}'\\'''"

# The spellings of an eval that a shell runs as one, each before the eval's words.
NAMES = {
    "command -p": "command -p eval",
    "command --": "command -- eval",
    "command -p --": "command -p -- eval",
    "builtin --": "builtin -- eval",
    "builtin command": "builtin command eval",
    "command builtin": "command builtin eval",
    "coproc": "coproc eval",
    "a backslash before it": "\\eval",
    "a backslash inside it": "e\\val",
    "double quotes": '"eval"',
    "single quotes": "'eval'",
    "a backslash before it in a subshell": "(\\eval",
}

# The commands ``coproc`` runs with an eval in them, ``{t}`` the eval's words: a group in
# braces and a subshell, each with the coprocess's name before it or none.
COPROC_FORMS = {
    "a group": "coproc { eval {t}; }",
    "a named group": "coproc W { eval {t}; }",
    "a subshell": "coproc (eval {t})",
    "a named subshell": "coproc W (eval {t})",
}

# Shell texts that give a password in a trap's action, in ``command -p eval`` or to ``\redis-cli``.
SECRET_TEXTS = {
    "a trap of an eval of words with escaped double quotes": (
        "trap 'eval memtier_benchmark --command \\\"AUTH {v}\\\"' EXIT"
    ),
    "a trap of an eval in double quotes": (
        "trap \"eval 'memtier_benchmark --command '\\\\''AUTH {v}'\\\\'''\" EXIT; true"
    ),
    "a trap of an eval after --": (
        "trap -- 'eval memtier_benchmark --command \\\"AUTH {v}\\\"' INT"
    ),
    "command -p eval of words with escaped quotes": (
        "command -p eval memtier_benchmark --command \\'AUTH {v}\\'"
    ),
    "a client named with a backslash": "\\redis-cli -a {v} PING",
    "a client named with a backslash after &&": "true && \\redis-cli -a {v} PING",
}

# Shell texts that assign a credential before a program, ``{p}`` the program.
ASSIGNED_TEXTS = {
    "command -p eval": "command -p eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'",
    "coproc eval": "coproc eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'",
    "a quoted eval": "\"eval\" 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'",
    "builtin and a quoted eval": (
        "builtin \"eval\" 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'"
    ),
    "builtin command -p eval": (
        "builtin command -p eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'"
    ),
    "coproc and a named group": (
        "coproc W {{ eval 'PGPASSWORD='\\''made {v}'\\'' {p} -h db.example'; }}"
    ),
    "a trap": "trap 'PGPASSWORD={v} {p} -h db.example' EXIT",
    "a trap of an eval": "trap 'eval PGPASSWORD={v} {p} -h db.example' EXIT",
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


@pytest.mark.parametrize("shell", ["sh", "bash"])
@pytest.mark.parametrize("name", sorted(NAMES))
def test_a_password_in_an_eval_named_any_way_is_hidden(name: str, shell: str) -> None:
    text = f"{NAMES[name]} {TEXT}" + (")" if NAMES[name].startswith("(") else "")

    assert_hidden([[shell, "-c", text.replace("{v}", value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(COPROC_FORMS))
def test_a_password_in_an_eval_that_coproc_runs_in_a_group_or_subshell_is_hidden(
    form: str,
) -> None:
    text = COPROC_FORMS[form].replace("{t}", TEXT)

    assert_hidden([["bash", "-c", text.replace("{v}", value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(SECRET_TEXTS))
def test_a_password_in_a_trap_or_after_an_escaped_name_is_hidden(form: str) -> None:
    assert_hidden([["sh", "-c", SECRET_TEXTS[form].format(v=value)] for value in VALUES])


@pytest.mark.parametrize("form", sorted(ASSIGNED_TEXTS))
def test_the_program_after_a_credential_in_such_a_text_tells_two_commands_apart(
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
    "command -p eval": (
        ["sh", "-c", "command -p eval " + TEXT],
        "sh -c 'command -p eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"'",
    ),
    "a quoted eval": (
        ["sh", "-c", '"eval" ' + TEXT],
        "sh -c '\"eval\" \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"'",
    ),
    "a trap": (
        ["sh", "-c", "trap 'PGPASSWORD={v} psql -h db.example' EXIT"],
        "sh -c 'trap '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"' EXIT'",
    ),
    "a client named with a backslash": (
        ["sh", "-c", "\\redis-cli -a {v} PING"],
        "sh -c '\\redis-cli -a <hidden> PING'",
    ),
}


@pytest.mark.parametrize("row", sorted(SHOWN))
def test_such_a_command_is_shown_with_its_value_hidden(row: str) -> None:
    words, shown = SHOWN[row]

    for value in VALUES:
        assert model.public_command([word.replace("{v}", value) for word in words]) == shown


# Ordinary words in the same places, shown and hashed as typed.
SHOWN_AS_TYPED = {
    "command -v eval": ["sh", "-c", "command -v eval"],
    "command -V eval": ["sh", "-c", "command -V eval"],
    "an ordinary eval after command -p": ["sh", "-c", "command -p eval 'echo a b'"],
    "an ordinary eval in double quotes": ["sh", "-c", '"eval" echo a b'],
    "an ordinary eval after a backslash": ["sh", "-c", "\\eval 'echo a b'"],
    "an ordinary coproc": ["bash", "-c", "coproc cat; echo hi >&${COPROC[1]}"],
    "an ordinary named group of coproc": ["bash", "-c", "coproc W { cat; }"],
    "an ordinary eval in a group of coproc": ["bash", "-c", "coproc W { eval 'echo a b'; }"],
    "an ordinary eval in a subshell of coproc": ["bash", "-c", "coproc (eval 'echo a b')"],
    "a trap reset": ["sh", "-c", "trap - EXIT"],
    "a trap that ignores a signal": ["sh", "-c", "trap '' INT"],
    "a trap listing": ["sh", "-c", "trap -p"],
    "a trap with one signal": ["sh", "-c", "trap EXIT"],
    "an ordinary trap": ["sh", "-c", "trap 'rm -f out.txt' EXIT INT TERM; ./bench --n 5"],
    "a trap with a number": ["sh", "-c", "trap 'echo done' 0"],
    "a program that is no client after a backslash": ["sh", "-c", "\\ls -a data"],
    "a trap given as words": ["trap", "echo hi", "EXIT"],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_in_these_places_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
