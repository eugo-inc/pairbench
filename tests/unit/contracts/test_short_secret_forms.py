# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Short forms at the edge of two rules of the shown command, each hidden as long ones are.

A rule of ``ACL SETUSER`` that holds a password of one character
(``>k``) loses it as a longer one does, while the rule ``>`` alone holds
none and shows. A key written with ``/`` whose part at an end is three small
letters with no vowel (``xkq``) reads as no word of a path, so the key is
hidden whole, while a part of two letters (``ab``) shows, as the security
policy says, and a path made of such parts shows as typed. Every value is made
up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
H = model.HIDDEN
# Two made-up passwords of one character: a command with one is hashed as with the other.
PASSWORDS = ("k", "q")
PW = "{pw}"
# A made-up key written with `/` at either end of a part.
KEY = "EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw"
USER = ("redis-cli", "ACL", "SETUSER", "made-up-user")

# (the arguments with `{pw}` where the password stands, the arguments shown)
ACL_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a password of one character": (
        (*USER, "on", f">{PW}", "+@all"),
        (*USER, "on", f">{H}", "+@all"),
    ),
    "a removal, a hash and a hash removal of one character": (
        (*USER, "on", f"<{PW}", f"#{PW}", f"!{PW}"),
        (*USER, "on", f"<{H}", f"#{H}", f"!{H}"),
    ),
    "a password of one character in rules written as one word": (
        (*USER, f"on >{PW} ~* +@all"),
        (*USER, f"on >{H}"),
    ),
}
# Commands that show as typed: a rule with no password, and paths whose parts read as words.
SHOWN: dict[str, tuple[str, ...]] = {
    "a password rule with no password": (*USER, "on", ">", "+@all"),
    "a path with a part of three letters and no vowel": ("./bench", "data/xkq/out.json"),
}
# (the arguments, the arguments shown): a key with `/` and a part at an end.
KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "three letters before the key": (("./bench", f"xkq/{KEY}"), ("./bench", H)),
    "three letters after the key": (("./bench", f"{KEY}/xkq"), ("./bench", H)),
    "three letters before the key as the value of an option": (
        ("./bench", "--key", f"xkq/{KEY}"),
        ("./bench", "--key", H),
    ),
    "two letters before the key": (("./bench", f"ab/{KEY}"), ("./bench", f"ab/{H}")),
}


def typed(args: tuple[str, ...], password: str) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password) for arg in args)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ACL_RULES))
def test_an_acl_password_of_one_character_is_hidden(name: str, password: str) -> None:
    args, shown = ACL_RULES[name]
    text = shlex.join(typed(args, password))

    assert model.public_command((*LEAD, *typed(args, password))) == SHOWN_LEAD + shlex.join(shown)
    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", shlex.join(shown)]
    )


@pytest.mark.parametrize("name", list(ACL_RULES))
def test_the_hash_of_an_acl_password_of_one_character_is_the_same_whatever_it_is(
    name: str,
) -> None:
    args, shown = ACL_RULES[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)

    assert first == second == list(shown)


@pytest.mark.parametrize("name", list(SHOWN))
def test_a_form_with_no_secret_shows_as_typed(name: str) -> None:
    args = SHOWN[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(args)
    assert model.hashed_argv(args) == list(args)


@pytest.mark.parametrize("name", list(KEYS))
def test_a_key_with_a_part_that_reads_as_no_word_is_hidden_whole(name: str) -> None:
    args, shown = KEYS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(shown)
    assert model.hashed_argv(args) == list(shown)
