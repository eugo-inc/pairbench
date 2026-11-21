# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A quoted word before a closing bracket or a glued redirection is read as the word alone.

In a shell text, ``'...')`` closes a subshell after the quoted word and
``'...'>out.txt`` redirects after it, also with the number of a descriptor in
front of the redirection (``'...')2>&1``, ``'...'2>&1``); the shell passes the
program the quoted word with its quotes taken off. So the word is read as it is read with no
bracket and no redirection: every password and credential it holds is hidden,
in the shown command and in the hash, whatever the word is an argument of (an
ordinary program, ``python3 -c``, ``perl -e``, ``env -S``), also when a
credential word glued with ``=`` comes later in the same word. The bracket and
the redirection are shown after the closing quote as typed, and ordinary words
stay shown. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Each shell text, with ``{v}`` where its password goes; each is hidden as it stands, in a
# bracket and with a redirection glued after it.
WORDS: dict[str, str] = {
    "an ordinary program's option and its value in one quote, then --token=": (
        "mytool '--api-key {v} --token=x'"
    ),
    "python3 -c running a client, then a credential string": (
        'python3 -c \'import os; os.system("redis-cli -a {v} PING"); x="--token=y"\''
    ),
    "perl -e running a client, then a credential string": (
        'perl -e \'system("mysql -p{v} -e made-up"); $x="--password=y"\''
    ),
    "env -S, then --token=": "env -S 'true --api-key {v} --token=x'",
    "a client's command in one quote, then PGPASSWORD=": (
        "mytool --extra 'redis-cli -a {v} PING; true PGPASSWORD=x'"
    ),
    "curl -u in one quote, then --secret=": (
        "mytool --extra 'curl -u made-up:{v} http://127.0.0.1:9/ --secret=x'"
    ),
    "the word in double quotes, then --key=": 'mytool "--password {v} --key=x"',
}

# How each text is wrapped: the text inside a bracket, with a redirection glued after it,
# and both, with what the wrap puts before and after the text.
WRAPS: dict[str, tuple[str, str]] = {
    "a bracket": ("(", ")"),
    "a glued redirection": ("", ">out.txt"),
    "a glued redirection of standard error": ("", " 2>&1"),
    "a bracket and a pipe": ("(", ")|cat"),
    "a bracket after another command": ("x; (", ")"),
    "a function body in a bracket": ("f() (", ")"),
    "a bracket and a numbered redirection of standard error": ("(", ")2>&1"),
    "a bracket and a numbered redirection to a file": ("(", ")1>out.txt"),
    "a bracket and a descriptor of two digits": ("(", ")10>lock"),
    "a bracket and a named descriptor": ("(", "){fd}>lock"),
    "a bracket and a descriptor closed": ("(", ")3>&-"),
    "a bracket and a numbered redirection of standard input": ("(", ")0<in.txt"),
    "a bracket and a redirection and a pipe": ("(", ")2>&1|cat"),
    "two brackets and a numbered redirection": ("((", "))2>&1"),
    "a bracket after a case pattern and a numbered redirection": ("case x in x) (", ")2>&1;; esac"),
    "a numbered redirection glued to the closing quote": ("", "2>&1"),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def shown_text(text: str) -> str:
    """Return the shell text as the shown command shows it, its quotes taken off."""
    return shlex.split(model.public_command(["sh", "-c", text]))[2]


def hashed_text(text: str) -> str:
    """Return the shell text as the hash takes it in."""
    return model.hashed_argv(["sh", "-c", text])[2]


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("row", sorted(WORDS))
def test_a_wrapped_word_hides_what_the_word_alone_hides(row: str, wrap: str) -> None:
    before, after = WRAPS[wrap]
    for value in VALUES:
        text = WORDS[row].replace("{v}", value)
        wrapped = before + text + after

        assert shown_text(wrapped) == before + shown_text(text) + after
        assert hashed_text(wrapped) == before + hashed_text(text) + after
        assert pieces(model.public_command(["sh", "-c", wrapped]), value) == []
        assert pieces(json.dumps(model.hashed_argv(["sh", "-c", wrapped])), value) == []


# Each command, with ``{v}`` where its password goes, and the command as shown.
ROWS: dict[str, tuple[list[str], str]] = {
    "a quoted option and its value in a bracket, then --token=": (
        ["sh", "-c", "(mytool '--api-key {v} --token=x')"],
        "sh -c '(mytool '\"'\"'--api-key <hidden> --token=<hidden>'\"'\"')'",
    ),
    "a quoted option and its value with a redirection, then --token=": (
        ["sh", "-c", "mytool '--api-key {v} --token=x'>out.txt"],
        "sh -c 'mytool '\"'\"'--api-key <hidden> --token=<hidden>'\"'\"'>out.txt'",
    ),
    "env -S in a bracket, then --token=": (
        ["sh", "-c", "(env -S 'true --api-key {v} --token=x')"],
        "sh -c '(env -S '\"'\"'true --api-key <hidden> --token=<hidden>'\"'\"')'",
    ),
    "a quoted option and its value in a bracket with a numbered redirection, then --token=": (
        ["sh", "-c", "(true '--api-key {v} --token=x')2>&1"],
        "sh -c '(true '\"'\"'--api-key <hidden> --token=<hidden>'\"'\"')2>&1'",
    ),
    "a nested shell text in a bracket with a numbered redirection": (
        ["sh", "-c", "(sh -c 'redis-cli -a {v} PING; true --token=x')9>lock"],
        "sh -c '(sh -c '\"'\"'redis-cli -a <hidden> PING; true --token=<hidden>'\"'\"')9>lock'",
    ),
    "a quoted option and its value with a numbered redirection glued, then --token=": (
        ["sh", "-c", "mytool '--api-key {v} --token=x'2>&1"],
        "sh -c 'mytool '\"'\"'--api-key <hidden> --token=<hidden>'\"'\"'2>&1'",
    ),
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_a_quoted_word_before_a_closer_is_shown_hidden_and_hashed_alike(row: str) -> None:
    words, shown = ROWS[row]
    commands = [[word.replace("{v}", value) for word in words] for value in VALUES]

    assert [model.public_command(command) for command in commands] == [shown, shown]
    first, second = (json.dumps(model.hashed_argv(command)) for command in commands)
    assert first == second


# Ordinary quoted words before a bracket or a redirection.
SHOWN_AS_TYPED = {
    "quoted words in a bracket": ["sh", "-c", "(echo 'hello world')"],
    "an option glued with = in one quote in a bracket": ["sh", "-c", "(./bench '--out=x y')"],
    "a quoted option and a count before a redirection": [
        "sh",
        "-c",
        "./bench '--threads 4' '--rounds 8'>out.txt",
    ],
    "a quoted ordinary option in a bracket": ["sh", "-c", "(./bench '--name made-up --out=x')"],
    "a program's text in a bracket": ["sh", "-c", "(python3 -c 'print(1)')"],
    "quoted words in a bracket with a numbered redirection": [
        "sh",
        "-c",
        "(echo 'hello world')2>&1",
    ],
    "a quoted ordinary option in a bracket with a numbered redirection": [
        "sh",
        "-c",
        "(./bench '--name made-up --out=x')2>err.txt",
    ],
    "an option glued with = in one quote with a numbered redirection": [
        "sh",
        "-c",
        "./bench '--out=x y'2>&1",
    ],
    "a substitution in a quoted word before a bracket": ["sh", "-c", "(echo 'a b'$(date))2>&1"],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_quoted_words_before_a_closer_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
