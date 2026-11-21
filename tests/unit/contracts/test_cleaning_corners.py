# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Corners of the cleaning of a command: operators in quoted words, deep shell texts, glued words.

An operator in a quoted word ends a command only when a shell reads that word as a
shell text of its own; in any other quoted word it is part of the value it stands in,
and the value is hidden with it. A shell text in double quotes is read as the next
shell gets it, with its escapes taken out, and quoted shell texts are read
``SHELL_DEPTH`` shells deep: an operator deeper than that ends nothing, so the value
before it is hidden to its end. Two addresses written with no blank between them are
read one after the other. A word of a setting command is judged as a setting name
only when it is an operand written as a name.
"""

from __future__ import annotations

import json
import re
import shlex

import pytest

from pairbench.model import hashed_argv, public_command, public_words

# Two made-up pairs of a value's two parts, on either side of an operator.
PARTS = ("made-up-part-1", "made-up-part-2")
OTHER_PARTS = ("made-up-part-3", "made-up-part-4")

# How many shells deep a quoted shell text is read.
SHELL_DEPTH = 8

# Commands with an operator in a quoted word that no shell reads as a shell text, with ``{a}``
# and ``{b}`` for the parts of the value on either side of the operator, and the shown
# command, which is also what the hash is taken over.
PART_OF_THE_VALUE: dict[str, tuple[tuple[str, ...], str]] = {
    "a setting in single quotes in a shell text": (
        ("bash", "-c", "tool --config './bench token = {a}|{b}'"),
        """bash -c 'tool --config '"'"'./bench token = <hidden>'"'"''""",
    ),
    "a quoted word that names a shell but is an argument of a program": (
        ("sh", "-c", "tool \"bash -c 'curl password={a}|{b}'\""),
        """sh -c 'tool "bash -c '"'"'curl password=<hidden>'"'"'"'""",
    ),
    "a header in double quotes in the command text of a runner": (
        ("hyperfine", 'curl -H "redis-cli token = {a}&&{b}"'),
        """hyperfine 'curl -H "redis-cli token = <hidden>"'""",
    ),
    "a quoted word after an operator that follows a shell's -c": (
        ("sh", "-c", "sh -c ; 'tool token = {a}|{b}'"),
        """sh -c 'sh -c ; '"'"'tool token = <hidden>'"'"''""",
    ),
    # The next shell gets ``--config "token = A&&B"``: the operator stands between quotes.
    # The value is hidden to the end of the text. The double quote that opened the text after
    # the first ``-c`` is given back, so that text splits as typed; the escaped quotes inside
    # it are not.
    "a setting between escaped quotes in a shell text in double quotes": (
        ("sh", "-c", 'sh -c "./bench-old --config \\"token = {a}&&{b}\\""'),
        """sh -c 'sh -c "./bench-old --config \\"token = <hidden>"'""",
    ),
    "a setting between escaped quotes three shells deep": (
        ("sh", "-c", 'bash -c "dash -c \\"./bench-old --config \\\\\\"token = {a};{b}\\\\\\"\\""'),
        """sh -c 'bash -c "dash -c \\"./bench-old --config \\\\\\"token = <hidden>"'""",
    ),
}

# Commands with an operator that ends a command of a shell text inside double quotes, with
# ``{a}`` for the value before it and ``{tail}`` for the command after it, and the shown
# command with ``ls -l`` as that command.
ENDS_A_COMMAND: dict[str, tuple[tuple[str, ...], str]] = {
    # The next shell gets ``sh -c "echo it's"; ./bench-old ...``: the quote of ``it's`` stands
    # between double quotes and opens nothing.
    "an operator after an escaped quote that holds a single quote": (
        ("sh", "-c", 'bash -c "sh -c \\"echo it\'s\\"; ./bench-old password: {a}&&{tail}"'),
        """sh -c 'bash -c "sh -c \\"echo it'"'"'s\\"; ./bench-old password: <hidden>&&ls -l"'""",
    ),
    "an operator between escaped quotes in a shell text inside a shell text": (
        ("sh", "-c", 'bash -c "dash -c \\"./bench-old --token={a};{tail}\\""'),
        """sh -c 'bash -c "dash -c \\"./bench-old --token=<hidden>;ls -l\\""'""",
    ),
}

# A command nested two and three shells deep, each in double quotes, and what is shown of it.
NESTED_SHOWN = {
    2: """sh -c 'sh -c "sh -c \\"tool password: <hidden>;ls -l\\""'""",
    3: """sh -c 'sh -c "sh -c \\"sh -c \\\\\\"tool password: <hidden>;ls -l\\\\\\"\\""'""",
}

# Two addresses written with no blank between them: the second starts where the first ends,
# so the first host is hidden whole and what follows it is read as its path.
GLUED: dict[str, tuple[tuple[str, ...], str, list[str]]] = {
    "two addresses": (
        ("curl", "https://made-up-one.examplehttps://made-up-two.example/v1"),
        "curl 'https://<hidden>://made-up-two.example/v1'",
        ["curl", "https://made-up-one.examplehttps://made-up-two.example/v1"],
    ),
    "two addresses with user parts": (
        ("curl", "https://u:{a}@made-up-one.examplehttps://u:{b}@made-up-two.example/v1"),
        "curl 'https://<hidden>@<hidden>://<hidden>@made-up-two.example/v1'",
        ["curl", "https://<hidden>@made-up-one.examplehttps://<hidden>@made-up-two.example/v1"],
    ),
    "two addresses in a shell text": (
        ("sh", "-c", "curl https://made-up-one.examplehttps://made-up-two.example/v1 && ls"),
        "sh -c 'curl https://<hidden>://made-up-two.example/v1 && ls'",
        ["sh", "-c", "curl https://made-up-one.examplehttps://made-up-two.example/v1 && ls"],
    ),
}

# Commands written as one text, as a runner such as hyperfine takes them, with an operator
# that ends a command after user parts of addresses, and how each is shown.
WORDS_AFTER_USER_PARTS = {
    "an operator after two user parts": (
        "curl https://u:a@made-up-one.example/ https://u:b@made-up-two.example/"
        " -H Authorization: Bearer {a} ; ls -l",
        "curl https://<hidden>@<hidden>/ https://<hidden>@<hidden>/"
        " -H Authorization: <hidden> ; ls -l",
    ),
    "an operator right after a user part": (
        "curl -H Authorization: Bearer {a} https://u:b@;ls -l",
        "curl -H Authorization: <hidden>;ls -l",
    ),
}

# Commands of a setting command whose options and words are no setting name, the shown
# command and the hashed one.
SETTING_WORDS: dict[str, tuple[tuple[str, ...], str, list[str]]] = {
    "a password flag before an option of the setting command": (
        ("mysql_config_editor", "set", "--password", "--host=made-up-host"),
        "mysql_config_editor set --password --host=made-up-host",
        ["mysql_config_editor", "set", "--password", "--host=made-up-host"],
    ),
    "a password option before another option": (
        ("npm", "config", "set", "--password", "{a}", "--registry", "made-up-registry"),
        "npm config set --password '<hidden>' --registry made-up-registry",
        ["npm", "config", "set", "--password", "<hidden>", "--registry", "made-up-registry"],
    ),
    "an option after a name given its value": (
        ("npm", "config", "set", "//registry.example/:_authToken={a}", "--location=project"),
        "npm config set ':_authToken=<hidden>' --location=project",
        ["npm", "config", "set", "//registry.example/:_authToken=<hidden>", "--location=project"],
    ),
    "a setting after a name given its value": (
        ("npm", "config", "set", "_authToken={a}", "registry=made-up-registry"),
        "npm config set '_authToken=<hidden>' registry=made-up-registry",
        ["npm", "config", "set", "_authToken=<hidden>", "registry=made-up-registry"],
    ),
}


def _filled(argv: tuple[str, ...], parts: tuple[str, str], tail: str = "ls -l") -> tuple[str, ...]:
    a, b = parts
    return tuple(word.replace("{a}", a).replace("{b}", b).replace("{tail}", tail) for word in argv)


def _nested(depth: int, text: str) -> str:
    """Return ``text`` run by ``depth`` shells, each given it in double quotes after ``-c``."""
    for _ in range(depth):
        text = 'sh -c "' + re.sub(r'([\\"$`])', r"\\\1", text) + '"'
    return text


def _hash(argv: tuple[str, ...]) -> str:
    return json.dumps(hashed_argv(argv))


@pytest.mark.parametrize("name", list(PART_OF_THE_VALUE))
def test_an_operator_in_a_word_no_shell_reads_is_hidden_with_the_value(name: str) -> None:
    argv = _filled(PART_OF_THE_VALUE[name][0], PARTS)
    shown = PART_OF_THE_VALUE[name][1]
    assert public_command(argv) == shown
    assert hashed_argv(argv) == shlex.split(shown)
    for part in PARTS:
        assert part not in public_command(argv)
        assert part not in _hash(argv)


@pytest.mark.parametrize("name", list(PART_OF_THE_VALUE))
def test_values_that_differ_after_such_an_operator_give_one_hash(name: str) -> None:
    one = _filled(PART_OF_THE_VALUE[name][0], PARTS)
    other = _filled(PART_OF_THE_VALUE[name][0], (PARTS[0], OTHER_PARTS[1]))
    assert _hash(one) == _hash(other)
    assert public_command(one) == public_command(other)


@pytest.mark.parametrize("name", list(ENDS_A_COMMAND))
def test_an_operator_of_a_shell_text_in_double_quotes_ends_the_value(name: str) -> None:
    argv = _filled(ENDS_A_COMMAND[name][0], PARTS)
    shown = ENDS_A_COMMAND[name][1]
    assert public_command(argv) == shown
    assert hashed_argv(argv) == shlex.split(shown)
    assert PARTS[0] not in _hash(argv)


@pytest.mark.parametrize("name", list(ENDS_A_COMMAND))
def test_commands_after_that_operator_still_tell_two_sides_apart(name: str) -> None:
    one = _filled(ENDS_A_COMMAND[name][0], PARTS, tail="ls -l")
    other = _filled(ENDS_A_COMMAND[name][0], PARTS, tail="ls -a")
    assert _hash(one) != _hash(other)


@pytest.mark.parametrize("depth", sorted(NESTED_SHOWN))
def test_an_operator_two_and_three_shells_deep_ends_the_value(depth: int) -> None:
    argv = ("sh", "-c", _nested(depth, f"tool password: {PARTS[0]};ls -l"))
    assert public_command(argv) == NESTED_SHOWN[depth]
    assert hashed_argv(argv) == shlex.split(NESTED_SHOWN[depth])


# Commands run by many shells, with ``{a}`` for a value and ``{tail}`` for the command after
# the operator that ends it, and two such commands. After ``password:`` a value runs to the end
# of its line; after ``API_KEY=`` it runs to the next blank.
DEEP_COMMANDS = {
    "a value after a header-like name": ("tool password: {a};{tail}", ("ls -l", "ls -a")),
    "an assignment": ("API_KEY={a};{tail}", ("ls", "pwd")),
}


def _deep(depth: int, name: str, value: str, tail: int = 0) -> tuple[str, ...]:
    inner, tails = DEEP_COMMANDS[name]
    return ("sh", "-c", _nested(depth, inner.format(a=value, tail=tails[tail])))


@pytest.mark.parametrize("name", list(DEEP_COMMANDS))
def test_an_operator_as_deep_as_the_shells_read_ends_the_value(name: str) -> None:
    argv = _deep(SHELL_DEPTH, name, PARTS[0])
    hidden = _deep(SHELL_DEPTH, name, "<hidden>")
    assert public_command(argv) == shlex.join(hidden)
    assert hashed_argv(argv) == list(hidden)
    assert _hash(argv) != _hash(_deep(SHELL_DEPTH, name, PARTS[0], tail=1))


@pytest.mark.parametrize("name", list(DEEP_COMMANDS))
def test_an_operator_deeper_than_the_shells_read_is_hidden_with_the_value(name: str) -> None:
    argv = _deep(SHELL_DEPTH + 1, name, PARTS[0])
    other = _deep(SHELL_DEPTH + 1, name, OTHER_PARTS[0])
    other_tail = _deep(SHELL_DEPTH + 1, name, PARTS[0], tail=1)
    for text in (public_command(argv), _hash(argv)):
        assert PARTS[0] not in text
        assert ";" + DEEP_COMMANDS[name][1][0] not in text
    assert _hash(argv) == _hash(other) == _hash(other_tail)
    assert public_command(argv) == public_command(other) == public_command(other_tail)


@pytest.mark.parametrize("name", list(GLUED))
def test_an_address_glued_to_another_is_read_before_it(name: str) -> None:
    argv, shown, hashed = GLUED[name]
    argv = _filled(argv, PARTS)
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed


@pytest.mark.parametrize("name", list(WORDS_AFTER_USER_PARTS))
def test_an_operator_after_user_parts_ends_a_command_of_a_runner_text(name: str) -> None:
    text, shown = WORDS_AFTER_USER_PARTS[name]
    assert public_words(text.replace("{a}", PARTS[0])) == shown


@pytest.mark.parametrize("name", list(SETTING_WORDS))
def test_an_option_or_a_given_value_of_a_setting_command_is_no_setting_name(name: str) -> None:
    argv, shown, hashed = SETTING_WORDS[name]
    argv = _filled(argv, PARTS)
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed
