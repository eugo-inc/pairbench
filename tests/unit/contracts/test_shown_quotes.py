# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A text shown with a value hidden splits into words as the typed text does.

A credential's value hidden to the end of a quoted text takes the quote that
closes the text with it, unless the quote is closed after ``<hidden>``
again: ``print('--token=...')`` shows ``print('--token=<hidden>'``, and the
text of ``python3 -c "token='...'"`` run by ``hyperfine``, ``ssh`` or
``sh -c`` keeps its closing ``"``. A quote right after a quoted value that
nothing closes is the end of the text around the value, not the start of
another piece of it. So every quoted word of the shown command, and every
quoted word inside it, splits as a shell splits it.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

# Made-up passwords that hold no credential word.
PASSWORDS = ("kiwi7mango", "plum4grape")

# Each form: its arguments with ``{s}`` for the password, the command as shown with the first
# password, and the words of the text of its last argument as a shell splits them.
FORMS: dict[str, tuple[tuple[str, ...], str, list[str]]] = {
    "single-quoted-text-after-an-option": (
        ("python3", "-c", "print('--token={s}')"),
        "python3 -c 'print('\"'\"'--token=<hidden>'\"'\"''",
        ["print(--token=<hidden>"],
    ),
    "double-quoted-text-after-an-option": (
        ("python3", "-c", 'print("--token={s}")'),
        "python3 -c 'print(\"--token=<hidden>\"'",
        ["print(--token=<hidden>"],
    ),
    "query-in-a-single-quoted-text": (
        ("python3", "-c", "print('?x=1&token={s}')"),
        "python3 -c 'print('\"'\"'?x=1&token=<hidden>'\"'\"''",
        ["print(?x=1&token=<hidden>"],
    ),
    "python-text-in-a-shell-text": (
        ("sh", "-c", 'python3 -c \'import os; os.environ["API_KEY"]="{s}"\''),
        "sh -c 'python3 -c '\"'\"'import os; os.environ[\"API_KEY\"]=\"<hidden>\"'\"'\"''",
        ["python3", "-c", 'import os; os.environ["API_KEY"]="<hidden>"'],
    ),
    "python-text-in-a-hyperfine-command": (
        ("hyperfine", "python3 -c \"token='{s}'\""),
        "hyperfine 'python3 -c \"token=<hidden>\"'",
        ["python3", "-c", "token=<hidden>"],
    ),
    "python-text-after-another-statement": (
        ("sh", "-c", "python3 -c \"print('hi'); token='{s}'\""),
        "sh -c 'python3 -c \"print('\"'\"'hi'\"'\"'); token=<hidden>\"'",
        ["python3", "-c", "print('hi'); token=<hidden>"],
    ),
    "python-text-in-an-ssh-command": (
        ("ssh", "made-up-host", "python3 -c \"token='{s}'\""),
        "ssh made-up-host 'python3 -c \"token=<hidden>\"'",
        ["python3", "-c", "token=<hidden>"],
    ),
}


def typed(form: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in form]


def unsplit(words: list[str]) -> list[str]:
    """Return each word holding a quote that a shell cannot split, at any depth."""
    bad: list[str] = []
    for word in words:
        if not any(quote in word for quote in "'\""):
            continue
        try:
            inner = shlex.split(word)
        except ValueError:
            bad.append(word)
            continue
        if inner != [word]:
            bad += unsplit(inner)
    return bad


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of either password that the text holds."""
    return [
        password[at : at + 6]
        for password in PASSWORDS
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


@pytest.mark.parametrize("name", sorted(FORMS))
def test_the_shown_command_closes_the_quote_the_hidden_value_took(name: str) -> None:
    form, shown, _words = FORMS[name]
    argv = typed(form, PASSWORDS[0])

    assert model.public_command(argv) == shown
    assert pieces(shown) == []


@pytest.mark.parametrize("name", sorted(FORMS))
def test_the_shown_command_splits_into_the_words_it_hashes(name: str) -> None:
    form, _shown, words = FORMS[name]
    argv = typed(form, PASSWORDS[0])
    split = shlex.split(model.public_command(argv))

    assert split == model.hashed_argv(argv)
    assert shlex.split(split[-1]) == words
    assert unsplit(split) == []


@pytest.mark.parametrize("name", sorted(FORMS))
def test_two_passwords_give_one_shown_command(name: str) -> None:
    form, _shown, _words = FORMS[name]
    one, other = (typed(form, password) for password in PASSWORDS)

    assert model.public_command(one) == model.public_command(other)
    assert model.hashed_argv(one) == model.hashed_argv(other)
