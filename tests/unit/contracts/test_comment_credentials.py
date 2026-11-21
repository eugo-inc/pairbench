# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A shell comment is shown as typed, except for every credential form inside it, which is hidden.

The shell drops a comment, but a password typed in one stays in the text.
The words of a comment on the line of a client's command are read as words
given to that client: ``sh -c 'redis-cli -h HOST PING # -a VALUE'`` shows
``# -a <hidden>``, and so does ``#AUTH VALUE``, the client's command glued
to the ``#``. A form that the argument of any program hides (``--token
VALUE``, ``API_KEY=VALUE``, a client named in the comment) is hidden too, and
the other words of the comment are shown. A ``#`` inside a word or inside
quotes starts no comment, and the reading there is the one the rest of the
command has. A comment on a line of its own, or after a program that is not
a client, is read with no client. The shown command, the hash and
``public_words`` are the same whatever the value. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up values, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")
H = model.HIDDEN

# Each shell text with ``{v}`` for the value: the text as ``public_command`` shows it after
# ``sh -c``, and as ``public_words`` shows it.
HIDDEN_IN_A_COMMENT: dict[str, tuple[str, str, str]] = {
    "a password option": (
        "redis-cli -h made-up-host PING # -a {v}",
        f"redis-cli -h made-up-host PING # -a {H}",
        f"redis-cli -h made-up-host PING # -a {H}",
    ),
    "the client's command glued to the comment sign": (
        "redis-cli -h made-up-host PING #AUTH {v}",
        f"redis-cli -h made-up-host PING #AUTH {H}",
        f"redis-cli -h made-up-host PING #AUTH {H}",
    ),
    "the client's command with a user name": (
        "redis-cli PING # AUTH app {v}",
        f"redis-cli PING # AUTH app {H}",
        f"redis-cli PING # AUTH app {H}",
    ),
    "valkey-cli": (
        "valkey-cli PING #AUTH {v}",
        f"valkey-cli PING #AUTH {H}",
        f"valkey-cli PING #AUTH {H}",
    ),
    "a password glued to its option": (
        "mysql -e made-up-query # -p{v}",
        f"mysql -e made-up-query # -p{H}",
        f"mysql -e made-up-query # -p{H}",
    ),
    "after an operator in the comment": (
        "redis-cli PING # made-up note; -a {v}",
        f"redis-cli PING # made-up note; -a {H}",
        f"redis-cli PING # made-up note; -a {H}",
    ),
    "after a second comment sign": (
        "redis-cli PING # made-up note # -a {v}",
        f"redis-cli PING # made-up note # -a {H}",
        f"redis-cli PING # made-up note # -a {H}",
    ),
    "in a comment that a line break ends": (
        "redis-cli PING # -a {v}\n./bench",
        f"redis-cli PING # -a {H}\n./bench",
        f"redis-cli PING # -a {H} ./bench",
    ),
    "after a password that starts with the comment sign": (
        "redis-cli AUTH #{v} -a {v}",
        f"redis-cli AUTH {H} -a {H}",
        f"redis-cli AUTH {H} -a {H}",
    ),
    "in a nested shell text": (
        "bash -c \"sh -c 'redis-cli PING # -a {v}'\"",
        f"bash -c \"sh -c 'redis-cli PING # -a {H}'\"",
        f"bash -c sh -c 'redis-cli PING # -a {H}'",
    ),
    # These forms are hidden by the reading of any program; they stay hidden.
    "a long password option": (
        "redis-cli -h made-up-host PING # --pass {v}",
        f"redis-cli -h made-up-host PING # --pass {H}",
        f"redis-cli -h made-up-host PING # --pass {H}",
    ),
    "a credential-like name after a client": (
        "redis-cli -h made-up-host PING # API_KEY={v}",
        f"redis-cli -h made-up-host PING # API_KEY={H}",
        f"redis-cli -h made-up-host PING # API_KEY={H}",
    ),
    "a token option after a program": (
        "./bench # --token {v}",
        f"./bench # --token {H}",
        f"./bench # --token {H}",
    ),
    "a credential-like name after a program": (
        "./bench # API_KEY={v}",
        f"./bench # API_KEY={H}",
        f"./bench # API_KEY={H}",
    ),
    "a client named in the comment": (
        "./bench # redis-cli AUTH {v}",
        f"./bench # redis-cli AUTH {H}",
        f"./bench # redis-cli AUTH {H}",
    ),
    "a comment after a token": (
        "./bench --token {v} # made-up note",
        f"./bench --token {H} # made-up note",
        f"./bench --token {H} # made-up note",
    ),
    "a comment after the password": (
        "redis-cli AUTH {v}  # log in\n./bench",
        f"redis-cli AUTH {H}  # log in\n./bench",
        f"redis-cli AUTH {H} # log in ./bench",
    ),
    "a password that starts with the comment sign": (
        "redis-cli AUTH #{v}",
        f"redis-cli AUTH {H}",
        f"redis-cli AUTH {H}",
    ),
    "a password option's value that starts with the comment sign": (
        "redis-cli -a #{v} PING",
        f"redis-cli -a {H} PING",
        f"redis-cli -a {H} PING",
    ),
    # A ``#`` inside a word or inside quotes starts no comment.
    "a comment sign inside the password": (
        "redis-cli -a ab#{v} PING",
        f"redis-cli -a {H} PING",
        f"redis-cli -a {H} PING",
    ),
    "a comment sign inside a word before the option": (
        "redis-cli PING x# -a {v}",
        f"redis-cli PING x# -a {H}",
        f"redis-cli PING x# -a {H}",
    ),
    "a comment sign inside quotes": (
        "redis-cli PING '# -a {v}'",
        f"redis-cli PING '# -a {H}'",
        f"redis-cli PING # -a {H}",
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def hashed(words: list[str]) -> str:
    return json.dumps(model.hashed_argv(words))


@pytest.mark.parametrize("row", sorted(HIDDEN_IN_A_COMMENT))
def test_a_credential_in_a_comment_is_hidden_shown_and_hashed(row: str) -> None:
    typed, shown, words_shown = HIDDEN_IN_A_COMMENT[row]
    texts = [typed.replace("{v}", value) for value in VALUES]
    commands = [["sh", "-c", text] for text in texts]

    assert [model.public_command(words) for words in commands] == [
        shlex.join(["sh", "-c", shown])
    ] * 2
    assert [model.public_words(text) for text in texts] == [words_shown] * 2
    assert hashed(commands[0]) == hashed(commands[1])
    for words, text, value in zip(commands, texts, VALUES, strict=True):
        assert pieces(model.public_command(words), value) == []
        assert pieces(model.public_words(text), value) == []
        assert pieces(hashed(words), value) == []


# Commands given as words, with ``{v}`` for the value, and each as shown: a ``#`` that no
# shell reads is an argument.
WORDS_WITH_A_COMMENT_SIGN: dict[str, tuple[list[str], str]] = {
    "a user and a password that starts with the comment sign": (
        ["redis-cli", "AUTH", "{v}", "#note"],
        f"redis-cli AUTH '{H}' '{H}'",
    ),
    "a hash rule glued to the password": (
        ["redis-server", "--user", "app", "on", "#{v}{v}"],
        f"redis-server --user app on '#{H}'",
    ),
    "a comment sign of its own after the password": (
        ["redis-cli", "AUTH", "{v}", "#", "log", "in"],
        f"redis-cli AUTH '{H}' '{H}' log in",
    ),
    "a password option after a comment sign": (
        ["redis-cli", "PING", "#", "-a", "{v}"],
        f"redis-cli PING '#' -a '{H}'",
    ),
}


@pytest.mark.parametrize("row", sorted(WORDS_WITH_A_COMMENT_SIGN))
def test_a_comment_sign_in_a_command_given_as_words_is_an_argument(row: str) -> None:
    typed, shown = WORDS_WITH_A_COMMENT_SIGN[row]
    commands = [[word.replace("{v}", value) for word in typed] for value in VALUES]

    assert [model.public_command(words) for words in commands] == [shown, shown]
    assert hashed(commands[0]) == hashed(commands[1])
    for words, value in zip(commands, VALUES, strict=True):
        assert pieces(hashed(words), value) == []


# Shell texts whose comment holds no credential form, and each as ``public_words`` shows it.
SHOWN_AS_TYPED = {
    "a note": ("redis-cli PING # made-up note", "redis-cli PING # made-up note"),
    "an option with no value": ("redis-cli PING # -a", "redis-cli PING # -a"),
    "a comment sign inside double quotes": (
        'redis-cli PING "#AUTH made-up-note"',
        "redis-cli PING #AUTH made-up-note",
    ),
    "a comment after a program that is not a client": (
        "./bench # -a made-up-note",
        "./bench # -a made-up-note",
    ),
    "a comment on a line of its own": (
        "redis-cli PING\n# -a made-up-note",
        "redis-cli PING # -a made-up-note",
    ),
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_a_comment_with_no_credential_form_is_shown_as_typed(row: str) -> None:
    text, words_shown = SHOWN_AS_TYPED[row]

    assert model.public_command(["sh", "-c", text]) == shlex.join(["sh", "-c", text])
    assert model.public_words(text) == words_shown
