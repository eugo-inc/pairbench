# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A nested shell text in a bracket, or with a redirection after it, is read as its shell reads it.

A shell takes the quotes off a word of a shell text, so ``'tool ...')``, the
end of ``(sh -c 'tool ...')``, gives the nested shell the text ``tool ...``
and closes the bracket after it; ``'tool ...'>out.txt`` gives it the same
text and redirects what it writes. Each password and credential the nested
text holds is hidden in the shown command and in the hash, which is the same
whatever the password, also when a credential word glued with ``=`` follows
it in the same nested text; the bracket or the redirection is shown after the
nested text's closing quote, as typed. A nested text with no bracket, with no
later credential word, in braces or in a bracket with no nested shell is hidden
too, and ordinary words in such a text stay shown. Every value is made up.
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

# Each command, with ``{v}`` where its password goes, and the command as shown, with ``<q>``
# where such a quote stands.
ROWS: dict[str, tuple[list[str], str]] = {
    "curl -u, then a credential glued with =": (
        ["sh", "-c", "(sh -c 'curl -u made-up:{v} http://127.0.0.1:9/ || true; true --token=x')"],
        (
            "sh -c '(sh -c <q>curl -u made-up:<hidden> http://127.0.0.1:9/ || "
            "true; true --token=<hidden><q>)'"
        ),
    ),
    "redis-cli -a": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --token=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "mysql -p": (
        ["sh", "-c", "(sh -c 'mysql -p{v} -e select1; true --token=x')"],
        ("sh -c '(sh -c <q>mysql -p<hidden> -e select1; true --token=<hidden><q>)'"),
    ),
    "--api-key": (
        ["sh", "-c", "(sh -c 'tool --api-key {v}; true --token=x')"],
        ("sh -c '(sh -c <q>tool --api-key <hidden>; true --token=<hidden><q>)'"),
    ),
    "the remote command of ssh": (
        ["ssh", "made-up-host", "(sh -c 'redis-cli -a {v} PING; true --token=x')"],
        ("ssh made-up-host '(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "docker exec": (
        [
            "docker",
            "exec",
            "made-up-ctr",
            "sh",
            "-c",
            "(sh -c 'redis-cli -a {v} PING; true --token=x')",
        ],
        (
            "docker exec made-up-ctr sh -c '(sh -c <q>redis-cli -a <hidden> "
            "PING; true --token=<hidden><q>)'"
        ),
    ),
    "a later --password=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --password=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --password=<hidden><q>)'"),
    ),
    "a later PGPASSWORD=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true PGPASSWORD=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true PGPASSWORD=<hidden><q>)'"),
    ),
    "bash -lc and bash -c": (
        ["bash", "-lc", "(bash -c 'redis-cli -a {v} PING; true --token=x')"],
        ("bash -lc '(bash -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "a command before the nested shell": (
        ["sh", "-c", "(cd made-up; sh -c 'redis-cli -a {v} PING; true --token=x')"],
        ("sh -c '(cd made-up; sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "exec": (
        ["sh", "-c", "(exec sh -c 'redis-cli -a {v} PING; true --token=x')"],
        ("sh -c '(exec sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "bash -c in the bracket": (
        ["sh", "-c", "(bash -c 'redis-cli -a {v} PING; true --token=x')"],
        ("sh -c '(bash -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "a blank after the bracket": (
        ["sh", "-c", "( sh -c 'redis-cli -a {v} PING; true --token=x')"],
        ("sh -c '( sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "the nested text in double quotes": (
        ["sh", "-c", '(sh -c "redis-cli -a {v} PING; true --token=x")'],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)'"),
    ),
    "&& in the nested text": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING && true --token=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING && true --token=<hidden><q>)'"),
    ),
    "a later API_TOKEN=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; API_TOKEN=x y')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; API_TOKEN=<hidden> y<q>)'"),
    ),
    "a later --auth=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; y --auth=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; y --auth=<hidden><q>)'"),
    ),
    "a later --key=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; y --key=x')"],
        "sh -c '(sh -c <q>redis-cli -a <hidden> PING; y --key=<hidden><q>)'",
    ),
    "a later --secret=": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; y --secret=x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; y --secret=<hidden><q>)'"),
    ),
    "a later header glued with =": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; y --header=Authorization:x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; y --header=Authorization: <hidden><q>)'"),
    ),
    "a remote command of ssh written in quotes": (
        ["ssh", "made-up-host", "'(sh -c \"redis-cli -a {v} PING; true --token=x\")'"],
        (
            "ssh made-up-host ''\"'\"'(sh -c \"redis-cli -a <hidden> PING; "
            "true --token=<hidden>\")'\"'\"''"
        ),
    ),
    "a remote command of ssh written in quotes, no later credential word": (
        ["ssh", "made-up-host", "'(sh -c \"redis-cli -a {v} PING\")'"],
        "ssh made-up-host ''\"'\"'(sh -c \"redis-cli -a <hidden> PING\")'\"'\"''",
    ),
    "ssh in a shell text": (
        ["sh", "-c", "ssh made-up-host '(sh -c \"redis-cli -a {v} PING; true --token=x\")'"],
        (
            "sh -c 'ssh made-up-host <q>(sh -c \"redis-cli -a <hidden> PING; "
            "true --token=<hidden>\")<q>'"
        ),
    ),
    "docker exec in a shell text": (
        [
            "sh",
            "-c",
            "docker exec made-up-ctr sh -c '(sh -c \"redis-cli -a {v} PING; true --token=x\")'",
        ],
        (
            "sh -c 'docker exec made-up-ctr sh -c <q>(sh -c \"redis-cli -a "
            "<hidden> PING; true --token=<hidden>\")<q>'"
        ),
    ),
    "two brackets deep": (
        ["sh", "-c", "(sh -c '(sh -c \"redis-cli -a {v} PING; true --token=x\")')"],
        ("sh -c '(sh -c \"(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)\")'"),
    ),
    "a redirection after the nested text": (
        ["sh", "-c", "sh -c 'redis-cli -a {v} PING; true --token=x'>out.txt"],
        ("sh -c 'sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>>out.txt'"),
    ),
    "a redirection after the bracket": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --token=x')>out.txt"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>)>out.txt'"),
    ),
    "a redirection in the bracket": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --token=x'>out.txt)"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>>out.txt)'"),
    ),
    "the bracket closes right after the password": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v}')"],
        "sh -c '(sh -c <q>redis-cli -a <hidden><q>)'",
    ),
    "the command of memtier_benchmark in a bracket": (
        ["sh", "-c", "(memtier_benchmark --command 'AUTH {v}')"],
        "sh -c '(memtier_benchmark --command <q>AUTH <hidden><q>)'",
    ),
    "an option and its value in one quote in a bracket": (
        ["sh", "-c", "(tool '--token {v}')"],
        "sh -c '(tool <q>--token <hidden><q>)'",
    ),
    "an option and its value in one quote, redirected": (
        ["sh", "-c", "tool '--token {v}'>out.txt"],
        "sh -c 'tool <q>--token <hidden><q>>out.txt'",
    ),
    "no bracket": (
        ["sh", "-c", "x; sh -c 'curl -u made-up:{v} http://127.0.0.1:9/ || true; true --token=x'"],
        (
            "sh -c 'x; sh -c <q>curl -u made-up:<hidden> http://127.0.0.1:9/ "
            "|| true; true --token=<hidden><q>'"
        ),
    ),
    "no later credential word": (
        ["sh", "-c", "(sh -c 'curl -u made-up:{v} http://127.0.0.1:9/ || true')"],
        ("sh -c '(sh -c <q>curl -u made-up:<hidden> http://127.0.0.1:9/ || true<q>)'"),
    ),
    "a brace group": (
        ["sh", "-c", "{ sh -c 'redis-cli -a {v} PING; true --token=x'; }"],
        ("sh -c '{ sh -c <q>redis-cli -a <hidden> PING; true --token=<hidden><q>; }'"),
    ),
    "a bracket with no nested shell": (
        ["sh", "-c", "(redis-cli -a {v} PING; true --token=x)"],
        "sh -c '(redis-cli -a <hidden> PING; true --token=<hidden>)'",
    ),
    "a later credential option with a blank": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --token x')"],
        ("sh -c '(sh -c <q>redis-cli -a <hidden> PING; true --token <hidden><q>)'"),
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def filled(words: list[str], value: str) -> list[str]:
    return [word.replace("{v}", value) for word in words]


@pytest.mark.parametrize("row", sorted(ROWS))
def test_a_nested_shell_text_hides_its_passwords_shown_and_hashed(row: str) -> None:
    words, shown = ROWS[row]
    commands = [filled(words, value) for value in VALUES]
    expected = shown.replace("<q>", QUOTE)

    assert [model.public_command(command) for command in commands] == [expected, expected]
    first, second = (json.dumps(model.hashed_argv(command)) for command in commands)
    assert first == second
    for command, value in zip(commands, VALUES, strict=True):
        assert pieces(model.public_command(command), value) == []
        assert pieces(json.dumps(model.hashed_argv(command)), value) == []


# Ordinary words in a nested shell text in a bracket, or with a redirection after it.
SHOWN_AS_TYPED = {
    "an output file glued with =": [
        "sh",
        "-c",
        "(sh -c 'redis-cli -p 6379 PING; true --out=made-up.txt')",
    ],
    "a count glued with =": ["sh", "-c", "(sh -c 'redis-benchmark -n 1000; true --threads=4')"],
    "an ordinary variable": ["sh", "-c", "(sh -c 'redis-benchmark -n 1000; X=1 true')"],
    "a name glued with =": ["sh", "-c", "(sh -c 'tool --name=made-up; true --threads=4')"],
    "quoted words in a bracket": ["sh", "-c", "(echo 'a b')"],
    "a redirection after the nested text": [
        "sh",
        "-c",
        "sh -c 'echo made-up; true --threads=4'>out.txt",
    ],
    "a redirection of standard error after the bracket": [
        "sh",
        "-c",
        "(sh -c 'echo made-up')2>err.txt",
    ],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_of_a_nested_shell_text_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
