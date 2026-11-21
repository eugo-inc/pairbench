# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A rule of ``ACL SETUSER`` with a backslash hides its password wherever the rule stands.

``ssh`` joins the words after its host and hands them to a shell on the other
machine, and ``watch`` and ``parallel`` hand their command to a shell the same
way. That shell takes the backslash off ``\\>VALUE``, ``\\<VALUE`` or
``\\#VALUE``, so the client gets a rule that gives a password or its hash: its
value is hidden in the shown command and in the hash, which is the same
whatever the password. So does a program in front of ``ssh``, ``watch`` or
``parallel`` (``timeout``, ``nohup``, ``sudo``, ``nice``), a shell text in a
word that ``ssh``, ``watch`` or ``parallel`` hands on (``sh -c '...'``), and
``hyperfine -N``, which splits its command into words with no shell and takes
the backslash off too. No rule starts with a backslash, so a rule typed with one
is hidden where no shell takes it off as well (``watch -x``, ``parallel -q``,
``env -S``, ``tmux`` given several words, a client run with no shell): the
client refuses such a rule, and hiding it shows no less of a working command.
Ordinary escaped words, a user name with a backslash and rules that give no
password stay shown as typed. Every value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")
# The rule's words, ``{v}`` the password.
RULE = ["redis-cli", "ACL", "SETUSER", "app", "on"]

# Each command, with ``{v}`` where the password goes.
COMMANDS: dict[str, list[str]] = {
    "ssh, a password to add": ["ssh", "made-up-host", *RULE, "\\>{v}"],
    "ssh, a password to remove": ["ssh", "made-up-host", *RULE, "\\<{v}"],
    "ssh, a hash to add": ["ssh", "made-up-host", *RULE, "\\#{v}"],
    "ssh with a port": ["ssh", "-p", "2222", "made-up-host", *RULE, "\\>{v}"],
    "ssh with a terminal": ["ssh", "-t", "made-up-host", *RULE, "\\>{v}"],
    "ssh, a user line of redis-server": [
        "ssh",
        "made-up-host",
        "redis-server",
        "--user",
        "app",
        "on",
        "\\>{v}",
    ],
    "watch": ["watch", *RULE, "\\>{v}"],
    "watch with a time": ["watch", "-n", "1", *RULE, "\\>{v}"],
    "watch with a glued time": ["watch", "-n1", *RULE, "\\>{v}"],
    "parallel": ["parallel", *RULE, "\\>{v}", ":::", "a"],
    "a shell text, watch and the rule in single quotes": [
        "sh",
        "-c",
        "watch redis-cli ACL SETUSER app on '\\>{v}'",
    ],
    "a shell text, watch and the rule in double quotes": [
        "sh",
        "-c",
        'watch redis-cli ACL SETUSER app on "\\>{v}"',
    ],
    "a shell text, ssh after an operator": [
        "sh",
        "-c",
        "true || ssh made-up-host redis-cli ACL SETUSER app on '\\>{v}'",
    ],
    "timeout before ssh": ["timeout", "5", "ssh", "made-up-host", *RULE, "\\>{v}"],
    "nohup before ssh": ["nohup", "ssh", "made-up-host", *RULE, "\\>{v}"],
    "sudo before watch": ["sudo", "watch", *RULE, "\\>{v}"],
    "nice before parallel": ["nice", "-n", "5", "parallel", *RULE, "\\>{v}", ":::", "a"],
    "a shell text, timeout before ssh after an operator": [
        "sh",
        "-c",
        "true || timeout 5 ssh made-up-host redis-cli ACL SETUSER app on '\\>{v}'",
    ],
    "a shell text in one word that ssh hands on": [
        "ssh",
        "made-up-host",
        "sh",
        "-c",
        "'redis-cli ACL SETUSER app on \\>{v}'",
    ],
    "a login shell text in one word that ssh hands on": [
        "ssh",
        "made-up-host",
        "bash",
        "-lc",
        "'redis-cli ACL SETUSER app on \\<{v}'",
    ],
    "a shell text in one word that watch hands on": [
        "watch",
        "sh",
        "-c",
        "'redis-cli ACL SETUSER app on \\>{v}'",
    ],
    "a shell text in one word that parallel hands on": [
        "parallel",
        "sh",
        "-c",
        "'redis-cli ACL SETUSER app on \\>{v}'",
        ":::",
        "a",
    ],
    "two backslashes through two shells": [
        "sh",
        "-c",
        'sh -c "redis-cli ACL SETUSER app on \\\\>{v}"',
    ],
    "hyperfine -N": ["hyperfine", "-N", "redis-cli ACL SETUSER app on \\>{v}"],
    "hyperfine with no shell, a password to remove": [
        "hyperfine",
        "--shell=none",
        "redis-cli ACL SETUSER app on \\<{v}",
    ],
    "hyperfine -S none": ["hyperfine", "-S", "none", "redis-cli ACL SETUSER app on \\>{v}"],
    "watch -x runs the client with no shell": ["watch", "-x", *RULE, "\\>{v}"],
    "parallel -q runs the client with no shell": ["parallel", "-q", *RULE, "\\>{v}", ":::", "a"],
    "a client run with no shell": [*RULE, "\\>{v}"],
    "env -S splits its text with no shell": ["env", "-S", "redis-cli ACL SETUSER app on \\>{v}"],
    "tmux given several words": ["tmux", "new", *RULE, "\\>{v}"],
    "a shell text in which watch -x runs the client": [
        "sh",
        "-c",
        "watch -x redis-cli ACL SETUSER app on '\\>{v}'",
    ],
    "a shell text whose client gets the backslash": [
        "sh",
        "-c",
        "redis-cli ACL SETUSER app on '\\>{v}'",
    ],
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


def filled(words: list[str], value: str) -> list[str]:
    return [word.replace("{v}", value) for word in words]


@pytest.mark.parametrize("row", sorted(COMMANDS))
def test_a_rule_a_shell_is_handed_hides_its_password_shown_and_hashed(row: str) -> None:
    commands = [filled(COMMANDS[row], value) for value in VALUES]
    shown = [model.public_command(command) for command in commands]
    hashed = [json.dumps(model.hashed_argv(command)) for command in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


@pytest.mark.parametrize("value", VALUES)
def test_a_run_s_shown_command_and_side_hash_hide_a_rule_after_ssh_s_double_dash(
    value: str,
) -> None:
    workload = ["ssh", "made-up-host", "--", *RULE, f"\\>{value}"]
    typed = ["pairbench", "run", "--side", "old=cmd:./bench {workload}", "--", *workload]

    assert model.public_command(typed).endswith(
        "-- ssh made-up-host -- redis-cli ACL SETUSER app on '\\><hidden>'"
    )
    assert model.hashed_argv(["env", *workload])[-1] == "\\><hidden>"


# Each command with ``{v}`` for the password, and the command as shown (``<q>`` a single quote).
QUOTE = "'\"'\"'"
ROWS: dict[str, tuple[list[str], str]] = {
    "ssh": (
        ["ssh", "made-up-host", *RULE, "\\>{v}"],
        "ssh made-up-host redis-cli ACL SETUSER app on '\\><hidden>'",
    ),
    "watch": (["watch", *RULE, "\\#{v}"], "watch redis-cli ACL SETUSER app on '\\#<hidden>'"),
    "a shell text, watch and the rule in single quotes": (
        ["sh", "-c", "watch redis-cli ACL SETUSER app on '\\>{v}'"],
        "sh -c 'watch redis-cli ACL SETUSER app on <q>\\><hidden><q>'",
    ),
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_a_rule_a_shell_is_handed_is_shown_with_its_value_hidden(row: str) -> None:
    words, shown = ROWS[row]

    for value in VALUES:
        assert model.public_command(filled(words, value)) == shown.replace("<q>", QUOTE)


# Ordinary escaped words, each shown as typed.
SHOWN_AS_TYPED: dict[str, list[str]] = {
    "a user name with a backslash": ["redis-cli", "ACL", "SETUSER", "\\>app", "on", "+@all"],
    "escaped words of another program after hyperfine -N": ["hyperfine", "-N", "echo a \\> b"],
    "a value of SET after hyperfine -N": ["hyperfine", "-N", "redis-cli SET k \\>v"],
    "a value of SET after watch -x": ["watch", "-x", "redis-cli", "SET", "k", "\\>v"],
    "a value of SET in a shell text": ["sh", "-c", "redis-cli SET k '\\>v'"],
    "a value of SET after ssh": ["ssh", "made-up-host", "redis-cli", "SET", "k", "\\>v"],
    "escaped words of another program after ssh": ["ssh", "made-up-host", "echo", "a", "\\>", "b"],
    "a pattern of grep after ssh": ["ssh", "made-up-host", "grep", "\\>x", "f"],
    "rules with no password after ssh": [
        "ssh",
        "made-up-host",
        *RULE,
        "\\~pat",
        "\\&chan",
        "\\+get",
    ],
}


@pytest.mark.parametrize("row", sorted(SHOWN_AS_TYPED))
def test_ordinary_words_handed_to_a_shell_are_shown_as_typed(row: str) -> None:
    words = SHOWN_AS_TYPED[row]

    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
