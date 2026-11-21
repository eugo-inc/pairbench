# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``)`` or backquote that closes a command after a hidden value in a shell text is shown.

In a shell text a ``)`` or backquote glued to the end of a word, outside
quotes and not escaped, closes a command: it is shell syntax and no part of
the value, so the shown command and the hash keep it after ``<hidden>``, and
the word after it is read as a word of the enclosing command, never as a
password of the closed one. One escaped by a backslash or inside quotes is
part of the value and is hidden with it, and so is one in an argument given
on its own, where no shell reads it. Every value is made up; each password is
a word of small letters that no command writes by itself.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG = "docs/reference/config.md"
LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
H = model.HIDDEN
# Two made-up passwords: a text with one is hashed as the text with the other is.
PASSWORDS = ("zqmkiwi", "zqmplum")

# (the shell text with `{pw}` where the password stands, the text as shown and hashed)
CLOSED: dict[str, tuple[str, str]] = {
    "auth in brackets": (
        "(redis-cli AUTH {pw}) && ./bench",
        f"(redis-cli AUTH {H}) && ./bench",
    ),
    "auth in backquotes before a word": (
        "echo `redis-cli AUTH {pw}` done",
        f"echo `redis-cli AUTH {H}` done",
    ),
    "auth in a command substitution before a word": (
        "echo $(redis-cli AUTH {pw}) done",
        f"echo $(redis-cli AUTH {H}) done",
    ),
    "auth in backquotes inside a test": (
        "[ `redis-cli AUTH {pw}` = OK ] && ./bench",
        f"[ `redis-cli AUTH {H}` = OK ] && ./bench",
    ),
    "auth in backquotes given to a name before a command": (
        "x=`redis-cli AUTH {pw}` ./bench",
        f"x=`redis-cli AUTH {H}` ./bench",
    ),
    "auth with a user name in brackets": (
        "(redis-cli AUTH made-up-user {pw}) && ./bench",
        f"(redis-cli AUTH made-up-user {H}) && ./bench",
    ),
    "auth with a quoted password in brackets": (
        "(redis-cli AUTH '{pw}') && ./bench",
        f"(redis-cli AUTH {H}) && ./bench",
    ),
    "two brackets after auth": (
        "(redis-cli AUTH {pw}))",
        f"(redis-cli AUTH {H}))",
    ),
    "a client password option in brackets": (
        "(redis-cli PING -a {pw}) && ./bench",
        f"(redis-cli PING -a {H}) && ./bench",
    ),
    "a client password glued to its option in brackets": (
        "(redis-cli PING -a{pw}) && ./bench",
        f"(redis-cli PING -a{H}) && ./bench",
    ),
    "a credential option in brackets": (
        "(./bench --token {pw}) && ./bench",
        f"(./bench --token {H}) && ./bench",
    ),
    "a credential option given with = in brackets": (
        "(./bench --token={pw}) && ./bench",
        f"(./bench --token={H}) && ./bench",
    ),
    "a credential option in brackets before a separator": (
        "(./bench --token {pw}); ./bench",
        f"(./bench --token {H}); ./bench",
    ),
    "a credential option in a command substitution at the end": (
        "echo $(./bench --token {pw})",
        f"echo $(./bench --token {H})",
    ),
    "a profile after a credential setting in brackets": (
        "(aws configure set aws_secret_access_key {pw} --profile made-up) && ./bench",
        f"(aws configure set aws_secret_access_key {H} --profile {H}) && ./bench",
    ),
    "a profile after a credential setting in backquotes": (
        "echo `aws configure set aws_secret_access_key {pw} --profile made-up` done",
        f"echo `aws configure set aws_secret_access_key {H} --profile {H}` done",
    ),
    "a config setting in brackets": (
        "(redis-cli CONFIG SET requirepass {pw}) && ./bench",
        f"(redis-cli CONFIG SET requirepass {H}) && ./bench",
    ),
    "a config setting and its value in one word in brackets": (
        "(redis-cli CONFIG SET 'requirepass {pw}') && ./bench",
        f"(redis-cli CONFIG SET 'requirepass {H}') && ./bench",
    ),
    "an escaped bracket before the closing one": (
        "(./bench --token {pw}\\)) && ./bench",
        f"(./bench --token {H}) && ./bench",
    ),
    "a quoted bracket before the closing one": (
        "(./bench --token '{pw})') && ./bench",
        f"(./bench --token {H}) && ./bench",
    ),
    "an escaped separator at the end of a value": (
        "./bench --token {pw}\\;",
        f"./bench --token {H}",
    ),
}
# Shell texts with no password, each shown and hashed as typed.
TYPED: dict[str, str] = {
    "auth alone in brackets": "( redis-cli AUTH ) && ./bench",
    "auth alone in backquotes": "echo ` redis-cli AUTH ` done",
}
# Arguments given on their own, where no shell reads a bracket: it is hidden with the value.
ARGUMENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "auth": (("redis-cli", "AUTH", "{pw})"), ("redis-cli", "AUTH", H)),
    "auth after a user name": (
        ("redis-cli", "AUTH", "made-up-user", "{pw}`"),
        ("redis-cli", "AUTH", "made-up-user", H),
    ),
    "a credential option": (("./bench", "--token", "{pw})"), ("./bench", "--token", H)),
    "a client password glued to its option": (
        ("redis-cli", "-a{pw})", "PING"),
        ("redis-cli", f"-a{H}", "PING"),
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(CLOSED))
def test_the_bracket_that_closes_a_command_after_a_hidden_value_shows(
    name: str, password: str
) -> None:
    text, shown = CLOSED[name]

    assert model.public_command((*LEAD, "sh", "-c", text.format(pw=password))) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", shown])
    )


@pytest.mark.parametrize("name", list(CLOSED))
def test_the_hash_keeps_the_closing_bracket_and_hides_the_password(name: str) -> None:
    text, shown = CLOSED[name]
    first, second = (
        model.hashed_argv(("sh", "-c", text.format(pw=password))) for password in PASSWORDS
    )

    assert first == second == ["sh", "-c", shown]


@pytest.mark.parametrize("name", list(TYPED))
def test_a_bracket_with_no_value_before_it_shows_as_typed(name: str) -> None:
    text = TYPED[name]

    assert model.public_command((*LEAD, "sh", "-c", text)) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", text])
    )
    assert model.hashed_argv(("sh", "-c", text)) == ["sh", "-c", text]


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ARGUMENTS))
def test_a_bracket_in_an_argument_is_hidden_with_the_value(name: str, password: str) -> None:
    args, shown = ARGUMENTS[name]
    typed = tuple(arg.format(pw=password) for arg in args)

    assert model.public_command((*LEAD, *typed)) == SHOWN_LEAD + shlex.join(shown)
    assert model.hashed_argv(typed) == list(shown)


# The examples of the config reference: (the shell text, the command as the page shows it).
PAGE_EXAMPLES = (
    ("(redis-cli AUTH zqmkiwi) && ./bench", f"sh -c '(redis-cli AUTH {H}) && ./bench'"),
    ("echo $(redis-cli AUTH zqmkiwi) done", f"sh -c 'echo $(redis-cli AUTH {H}) done'"),
)


@pytest.mark.parametrize(("text", "shown"), PAGE_EXAMPLES)
def test_the_config_reference_shows_the_closing_bracket_as_the_code_does(
    repo_root: Path, text: str, shown: str
) -> None:
    page = " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())

    assert f"`{shown}`" in page
    assert model.public_command(("sh", "-c", text)) == shown
