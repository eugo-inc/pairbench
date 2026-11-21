# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A rule of ``ACL SETUSER`` that gives a password hides the rest of its argument, blanks and all.

A rule that starts with ``>`` or ``<`` gives a password, and one that starts
with ``#`` or ``!`` gives its hash. A password can hold blanks when the
argument is quoted, so from the first such rule to the end of the argument
everything is hidden: ``'>made up'`` shows ``'><hidden>'``, and so does ``'>
made up'`` with a blank right after the ``>``. The rules before it are shown.
This holds for ``redis-cli`` and ``valkey-cli`` given the rule as an
argument, in the text after ``sh -c`` in single or double quotes, and in the
command of ``memtier_benchmark --command``, in the shown command and in the
hash, which is the same whatever the password. Every value is made up.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Each command with its password, and the command as shown.
ROWS: dict[str, tuple[Callable[[str], list[str]], str]] = {
    "a password with a blank in its own argument": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", "on", f">{v} {v}x"],
        "redis-cli ACL SETUSER app on '><hidden>'",
    ),
    "a password to remove with a blank": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", f"<{v} {v}x"],
        "redis-cli ACL SETUSER app '<<hidden>'",
    ),
    "a blank right after the rule": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", "on", f"> {v}"],
        "redis-cli ACL SETUSER app on '><hidden>'",
    ),
    "in single quotes after sh -c": (
        lambda v: ["sh", "-c", f"redis-cli ACL SETUSER app on '>{v} {v}x'"],
        "sh -c 'redis-cli ACL SETUSER app on '\"'\"'><hidden>'\"'\"''",
    ),
    "in double quotes after sh -c": (
        lambda v: ["sh", "-c", f'redis-cli ACL SETUSER app on ">{v} {v}x"'],
        "sh -c 'redis-cli ACL SETUSER app on \"><hidden>\"'",
    ),
    "in the command of memtier_benchmark": (
        lambda v: ["memtier_benchmark", "--command", f"ACL SETUSER app on '>{v} {v}x'"],
        "memtier_benchmark --command 'ACL SETUSER app on '\"'\"'><hidden>'\"'\"''",
    ),
    "valkey-cli": (
        lambda v: ["valkey-cli", "ACL", "SETUSER", "app", "on", f">{v} {v}x"],
        "valkey-cli ACL SETUSER app on '><hidden>'",
    ),
    "rules and a password with a blank in one argument": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", f"on >{v} {v}x"],
        "redis-cli ACL SETUSER app 'on ><hidden>'",
    ),
    # The rules after a password in one argument are hidden with it.
    "rules after the password in one argument": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", f"on >{v} ~* +@all"],
        "redis-cli ACL SETUSER app 'on ><hidden>'",
    ),
    "a hash with a blank": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", "on", f"#{v} {v}x"],
        "redis-cli ACL SETUSER app on '#<hidden>'",
    ),
    "a hash to remove with a blank": (
        lambda v: ["redis-cli", "ACL", "SETUSER", "app", "on", f"!{v} {v}x"],
        "redis-cli ACL SETUSER app on '!<hidden>'",
    ),
    # A password in the other forms, or in an argument of its own, is hidden whole.
    "a user and a password with a blank": (
        lambda v: ["redis-cli", "AUTH", "app", f"{v} {v}x"],
        "redis-cli AUTH app '<hidden>'",
    ),
    "a password setting with a blank": (
        lambda v: ["redis-cli", "CONFIG", "SET", "requirepass", f"{v} {v}x"],
        "redis-cli CONFIG SET requirepass '<hidden>'",
    ),
    "a password option with a blank": (
        lambda v: ["redis-cli", "-a", f"{v} {v}x", "PING"],
        "redis-cli -a '<hidden>' PING",
    ),
    "two passwords in their own arguments": (
        lambda v: [
            "redis-cli",
            "ACL",
            "SETUSER",
            "app",
            "reset",
            "on",
            f">{v}",
            f">{v}y",
            "~*",
            "+@all",
        ],
        "redis-cli ACL SETUSER app reset on '><hidden>' '><hidden>' '~*' +@all",
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


@pytest.mark.parametrize("row", sorted(ROWS))
def test_an_acl_password_rule_hides_the_rest_of_its_argument(row: str) -> None:
    make, shown = ROWS[row]
    commands = [make(value) for value in VALUES]

    assert [model.public_command(words) for words in commands] == [shown, shown]
    first, second = (json.dumps(model.hashed_argv(words)) for words in commands)
    assert first == second
    for words, value in zip(commands, VALUES, strict=True):
        assert pieces(model.public_command(words), value) == []
        assert pieces(json.dumps(model.hashed_argv(words)), value) == []


# Rules that give no password are shown, and so is a rule character with nothing after it.
SHOWN_AS_TYPED = {
    "rules with no password": ["redis-cli", "ACL", "SETUSER", "app", "on", "nopass", "~*", "+@all"],
    "a rule character alone": ["redis-cli", "ACL", "SETUSER", "app", "on", ">"],
    "rules before the password in one argument": [
        "redis-cli",
        "ACL",
        "SETUSER",
        "app",
        "on ~* +@all",
    ],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_acl_rules_with_no_password_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
