# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A rule of ``ACL SETUSER`` typed with a backslash in a shell text is read as the shell reads it.

In a shell text an unquoted ``>`` or ``<`` is a redirection and an unquoted
``#`` starts a comment, so a rule that gives a password or its hash is typed
there with a backslash before its first character: ``\\>VALUE``, ``\\<VALUE``,
``\\#VALUE`` or ``\\!VALUE``. The shell takes the backslash off and the client
gets the rule, so its value is hidden in the shown command and in the hash,
which is the same whatever the password; the backslash and the rule's first
character are shown as typed. This holds for ``redis-cli`` and ``valkey-cli``,
after an operator, and for a user line of ``redis-server --user``. Ordinary
rules, a redirection to a file and an escaped character that starts no rule
stay shown. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")
# How a single quote stands in a text the shown command puts in single quotes.
QUOTE = "'\"'\"'"

# Each command with ``{v}`` for the password, and the command as shown (``<q>`` a single quote).
ROWS: dict[str, tuple[list[str], str]] = {
    "a password to add": (
        ["sh", "-c", "redis-cli ACL SETUSER app on \\>{v}"],
        "sh -c 'redis-cli ACL SETUSER app on \\><hidden>'",
    ),
    "a password to remove": (
        ["sh", "-c", "redis-cli ACL SETUSER app on \\<{v}"],
        "sh -c 'redis-cli ACL SETUSER app on \\<<hidden>'",
    ),
    "a hash to add": (
        ["sh", "-c", "redis-cli ACL SETUSER app on \\#{v}"],
        "sh -c 'redis-cli ACL SETUSER app on \\#<hidden>'",
    ),
    "a hash to remove": (
        ["sh", "-c", "redis-cli ACL SETUSER app on \\!{v}"],
        "sh -c 'redis-cli ACL SETUSER app on \\!<hidden>'",
    ),
    "after an operator": (
        ["sh", "-c", "true || redis-cli ACL SETUSER app on \\>{v}"],
        "sh -c 'true || redis-cli ACL SETUSER app on \\><hidden>'",
    ),
    "two passwords and rules after them": (
        ["sh", "-c", "redis-cli ACL SETUSER app reset on \\>{v} \\>{v}x ~* +@all"],
        "sh -c 'redis-cli ACL SETUSER app reset on \\><hidden> \\><hidden> ~* +@all'",
    ),
    "valkey-cli in bash": (
        ["bash", "-c", "valkey-cli ACL SETUSER app on \\>{v} +@all"],
        "bash -c 'valkey-cli ACL SETUSER app on \\><hidden> +@all'",
    ),
    "a user line of redis-server": (
        ["sh", "-c", "redis-server --user app on \\>{v} '~*' +@all"],
        "sh -c 'redis-server --user app on \\><hidden> <q>~*<q> +@all'",
    ),
    "a user line of redis-server with a port after it": (
        ["sh", "-c", "redis-server --user app on \\#{v} --port 7000"],
        "sh -c 'redis-server --user app on \\#<hidden> --port 7000'",
    ),
}

# Ordinary commands of a shell text, each shown as typed.
SHOWN_AS_TYPED: dict[str, list[str]] = {
    "rules with no password": ["sh", "-c", "redis-cli ACL SETUSER app on nopass \\~\\* +@all"],
    "quoted rules and a redirection after a blank": [
        "sh",
        "-c",
        "redis-cli ACL SETUSER app on nopass '~*' '&*' +@all > out.txt",
    ],
    "an escaped file name after a redirection": ["sh", "-c", "redis-cli INFO > \\>out.txt"],
    "escaped characters of another program": ["sh", "-c", "echo \\>made \\#up"],
    "an error redirection after the rules": [
        "sh",
        "-c",
        "redis-cli ACL SETUSER app on nopass +@all 2>err.txt",
    ],
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def filled(words: list[str], value: str) -> list[str]:
    return [word.replace("{v}", value) for word in words]


@pytest.mark.parametrize("row", sorted(ROWS))
def test_an_escaped_rule_hides_its_password_shown_and_hashed(row: str) -> None:
    words, shown = ROWS[row]
    commands = [filled(words, value) for value in VALUES]
    expected = shown.replace("<q>", QUOTE)

    shown_texts = [model.public_command(command) for command in commands]
    hashed = [json.dumps(model.hashed_argv(command)) for command in commands]

    assert shown_texts == [expected, expected]
    assert hashed[0] == hashed[1]
    for value in VALUES:
        assert pieces(shown_texts[0] + hashed[0], value) == []


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_beside_a_rule_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
