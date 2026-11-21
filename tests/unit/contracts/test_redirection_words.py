# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A redirection is no word of a command, so a client keeps the option that takes its password.

A shell takes a redirection (``2>&1``, ``>out``, ``> out``, ``<<<text``)
out of a command's words before the program runs, and ``>|``, which writes
over a file, is a redirection too, not a pipe. So the option before a
redirection still takes the word after it, ``sshpass`` reads its options
after one, and the word after one can be a client's own command
(``AUTH``). The shown command and the published hashes read every form
alike: two passwords give one shown command and one hash. A redirection
word in an argument list that no shell reads is passed over too, as it was
most likely meant for a shell. In quotes such a word is an argument, and
where an option that takes a password stands before a redirection with a
file glued to it outside a shell text, the word is hidden as the value, so a
password that looks like a redirection is still hidden; ordinary arguments
around a redirection stay shown. Outside a shell text, a redirection that
stands alone or gives one descriptor to another, and the file after one,
are hidden as well where they stand as a value, and the option still takes
the next word. A rule of ``ACL SETUSER`` that gives a password (``>VALUE``)
and an option given as the file of a redirection (``> -a VALUE``) are read
as the words they look like, as the text holds them either way.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model
from pairbench.model import HIDDEN
from pairbench.sides.identity import argv_sha256

# Two made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
SHOWN_LEAD = "pairbench run -- "

# Each form: its argument list with ``{s}`` for the password, and the list as shown and hashed.
HIDDEN_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a-redirection-that-writes-over-a-file": (
        ("sh", "-c", "redis-benchmark -n 1000 >|out -a {s}"),
        ("sh", "-c", f"redis-benchmark -n 1000 >|out -a {HIDDEN}"),
    ),
    "a-redirection-that-writes-over-a-file-standing-alone": (
        ("sh", "-c", "redis-benchmark -n 1000 >| out -a {s}"),
        ("sh", "-c", f"redis-benchmark -n 1000 >| out -a {HIDDEN}"),
    ),
    "a-redirection-of-a-descriptor-that-writes-over-a-file": (
        ("sh", "-c", "redis-benchmark -n 1000 2>|out -a {s}"),
        ("sh", "-c", f"redis-benchmark -n 1000 2>|out -a {HIDDEN}"),
    ),
    "a-redirection-that-writes-over-a-file-in-a-remote-command": (
        ("ssh", "made-up-host", "redis-benchmark -n 1000 >|out -a {s}"),
        ("ssh", "made-up-host", f"redis-benchmark -n 1000 >|out -a {HIDDEN}"),
    ),
    "a-redirection-before-the-options-of-sshpass": (
        ("sh", "-c", "sshpass -P assword 2>&1 -p {s} ./bench"),
        ("sh", "-c", f"sshpass -P assword 2>&1 -p {HIDDEN} ./bench"),
    ),
    "a-redirection-standing-alone-before-the-options-of-sshpass": (
        ("sh", "-c", "sshpass > out -p {s} ./bench"),
        ("sh", "-c", f"sshpass > out -p {HIDDEN} ./bench"),
    ),
    "a-text-given-as-input-before-the-options-of-sshpass": (
        ("bash", "-c", "sshpass -P assword <<<y -p {s} ./bench"),
        ("bash", "-c", f"sshpass -P assword <<<y -p {HIDDEN} ./bench"),
    ),
    "a-redirection-before-the-command-of-a-client": (
        ("sh", "-c", "redis-cli -n 1 2>&1 AUTH {s}"),
        ("sh", "-c", f"redis-cli -n 1 2>&1 AUTH {HIDDEN}"),
    ),
    "a-redirection-between-the-user-name-and-the-password": (
        ("sh", "-c", "redis-cli AUTH made-up-user >out {s}"),
        ("sh", "-c", f"redis-cli AUTH made-up-user >out {HIDDEN}"),
    ),
    "a-redirection-between-an-option-and-its-value": (
        ("sh", "-c", "redis-cli -a 2>&1 {s} PING"),
        ("sh", "-c", f"redis-cli -a 2>&1 {HIDDEN} PING"),
    ),
    "a-redirection-standing-alone-between-an-option-and-its-value": (
        ("sh", "-c", "redis-cli -a > out {s} PING"),
        ("sh", "-c", f"redis-cli -a > out {HIDDEN} PING"),
    ),
    "a-redirection-between-a-setting-and-its-value": (
        ("sh", "-c", "redis-cli CONFIG SET requirepass > out {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET requirepass > out {HIDDEN}"),
    ),
    "a-redirection-among-the-words-of-a-remote-command": (
        ("ssh", "made-up-host", "redis-cli", "-n", "1", ">", "out", "AUTH", "{s}"),
        ("ssh", "made-up-host", "redis-cli", "-n", "1", ">", "out", "AUTH", HIDDEN),
    ),
    "a-redirection-in-an-argument-list-before-the-options-of-sshpass": (
        ("sshpass", "-P", "assword", "2>&1", "-p", "{s}", "./bench"),
        ("sshpass", "-P", "assword", "2>&1", "-p", HIDDEN, "./bench"),
    ),
    "a-redirection-in-an-argument-list-before-the-command-of-a-client": (
        ("redis-cli", "-n", "1", ">", "out", "AUTH", "{s}"),
        ("redis-cli", "-n", "1", ">", "out", "AUTH", HIDDEN),
    ),
    "a-redirection-of-a-descriptor-between-an-option-and-its-value": (
        ("redis-cli", "-a", "2>&1", "{s}", "PING"),
        ("redis-cli", "-a", HIDDEN, HIDDEN, "PING"),
    ),
    "a-redirection-standing-alone-in-an-argument-list-as-the-value-of-an-option": (
        ("redis-cli", "-a", ">", "{s}"),
        ("redis-cli", "-a", HIDDEN, HIDDEN),
    ),
    "a-redirection-standing-alone-in-an-argument-list-after-the-command-of-a-client": (
        ("redis-cli", "AUTH", ">", "{s}"),
        ("redis-cli", "AUTH", HIDDEN, HIDDEN),
    ),
    "an-option-given-as-the-file-of-a-redirection": (
        ("sh", "-c", "redis-cli > -a {s}"),
        ("sh", "-c", f"redis-cli > -a {HIDDEN}"),
    ),
    "an-option-given-as-the-file-of-a-redirection-after-a-hidden-value": (
        ("sh", "-c", "redis-cli -a {s} > -a {s}"),
        ("sh", "-c", f"redis-cli -a {HIDDEN} > -a {HIDDEN}"),
    ),
    "an-option-given-as-the-file-of-a-redirection-in-an-argument-list": (
        ("redis-cli", ">", "-a", "{s}"),
        ("redis-cli", ">", "-a", HIDDEN),
    ),
    "an-access-rule-after-a-redirection": (
        ("sh", "-c", "redis-cli ACL SETUSER made-up-user on >out.log >{s}"),
        ("sh", "-c", f"redis-cli ACL SETUSER made-up-user on >{HIDDEN} >{HIDDEN}"),
    ),
    "an-access-rule-after-a-redirection-of-a-descriptor": (
        ("sh", "-c", "redis-cli ACL SETUSER made-up-user on 2>err >{s}"),
        ("sh", "-c", f"redis-cli ACL SETUSER made-up-user on 2>err >{HIDDEN}"),
    ),
    "an-access-rule-after-a-redirection-standing-alone-in-an-argument-list": (
        ("redis-cli", "ACL", "SETUSER", "made-up-user", "on", ">", ">{s}"),
        ("redis-cli", "ACL", "SETUSER", "made-up-user", "on", ">", f">{HIDDEN}"),
    ),
    "a-quoted-password-that-looks-like-a-redirection": (
        ("sh", "-c", "redis-cli -a '>{s}' PING"),
        ("sh", "-c", f"redis-cli -a {HIDDEN} PING"),
    ),
    "a-password-that-looks-like-a-redirection": (
        ("redis-cli", "-a", ">{s}", "PING"),
        ("redis-cli", "-a", HIDDEN, "PING"),
    ),
    "a-password-of-sshpass-that-looks-like-a-redirection": (
        ("sshpass", "-p", "2>{s}", "ssh", "made-up-host", "true"),
        ("sshpass", "-p", HIDDEN, "ssh", "made-up-host", "true"),
    ),
    "a-password-that-looks-like-a-redirection-to-a-descriptor": (
        ("redis-cli", "--pass", ">&{s}", "PING"),
        ("redis-cli", "--pass", HIDDEN, "PING"),
    ),
    "a-password-that-looks-like-a-redirection-in-a-remote-command": (
        ("ssh", "made-up-host", "redis-cli", "-a", ">{s}", "PING"),
        ("ssh", "made-up-host", "redis-cli", "-a", HIDDEN, "PING"),
    ),
}


def typed(words: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in words]


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_a_redirection_a_shell_reads_keeps_the_client_and_hides_its_password(name: str) -> None:
    words, hidden = HIDDEN_FORMS[name]
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(hidden)
        )
        assert model.hashed_argv(argv) == list(hidden)


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_two_passwords_around_a_redirection_give_one_hash(name: str) -> None:
    words, _hidden = HIDDEN_FORMS[name]
    one, two = (typed(words, password) for password in PASSWORDS)

    assert argv_sha256(one) == argv_sha256(two)


# A side that runs a client before the shared workload, with a redirection or a command
# substitution before it or around the parameters: the side's command, the workload with
# ``{s}`` for the password, and the workload as hashed. A parameter inside a substitution is
# read as a word of the command the substitution stands in, as the substitution may give it
# back, and as a word of the substitution's own command.
HANDED_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "a-redirection-before-the-parameters-of-sshpass": (
        ("sh", "-c", 'sshpass -P assword 2>&1 "$@"', "_"),
        ("-p", "{s}", "./bench"),
        ("-p", HIDDEN, "./bench"),
    ),
    "a-substitution-holding-operators-as-a-value-of-sshpass": (
        ("sh", "-c", 'sshpass -P $(echo 1; echo 2) "$@"', "_"),
        ("-p", "{s}", "./bench"),
        ("-p", HIDDEN, "./bench"),
    ),
    "a-substitution-holding-a-bracket-as-a-value-of-sshpass": (
        ("sh", "-c", "sshpass -P $(echo ')') \"$@\"", "_"),
        ("-p", "{s}", "./bench"),
        ("-p", HIDDEN, "./bench"),
    ),
    "a-substitution-inside-a-substitution-as-a-value-of-sshpass": (
        ("sh", "-c", 'sshpass -P $(echo $(echo 1)) "$@"', "_"),
        ("-p", "{s}", "./bench"),
        ("-p", HIDDEN, "./bench"),
    ),
    "a-redirection-that-writes-over-a-file-before-the-parameters": (
        ("sh", "-c", 'redis-benchmark -n 1000 >|out "$@"', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "a-redirection-before-the-command-in-the-parameters": (
        ("sh", "-c", 'redis-cli -n 1 >out "$@"', "_"),
        ("AUTH", "{s}"),
        ("AUTH", HIDDEN),
    ),
    "the-parameters-inside-a-substitution-in-the-words-of-a-client": (
        ("sh", "-c", 'redis-cli $(echo "$@")', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "the-parameters-inside-a-quoted-substitution-in-the-words-of-a-client": (
        ("sh", "-c", 'redis-cli "$(echo "$@")"', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
    "the-parameters-a-client-inside-a-substitution-takes": (
        ("sh", "-c", './bench --label "$(redis-cli "$@" get k)"', "_"),
        ("-a", "{s}"),
        ("-a", HIDDEN),
    ),
}


def handed_config(name: str, password: str) -> dict[str, object]:
    head, workload, _hidden = HANDED_FORMS[name]
    return {
        "sides": {"a": {"cmd": [*head, model.WORKLOAD_PLACEHOLDER]}},
        "workload": {"argv": typed(workload, password)},
    }


@pytest.mark.parametrize("name", sorted(HANDED_FORMS))
def test_a_client_before_a_redirection_hides_the_password_of_the_shared_workload(
    name: str,
) -> None:
    head, workload, hidden = HANDED_FORMS[name]
    for password in PASSWORDS:
        config = handed_config(name, password)

        assert model.hashed_argv([*head, *typed(workload, password)]) == [*head, *hidden]
        assert model.config_inputs(config)["workload"]["argv"] == list(hidden)
        assert model.public_command(
            ("pairbench", "run", "--", *typed(workload, password)), config=config
        ) == (SHOWN_LEAD + shlex.join(hidden))
    first, second = (handed_config(name, password) for password in PASSWORDS)
    assert model.config_sha256(first) == model.config_sha256(second)


# Ordinary arguments around a redirection, with ``{v}`` for a value that no client's password
# option takes: each is shown as typed, and two values give two hashes.
KEPT_FORMS: dict[str, tuple[str, ...]] = {
    "a-count-before-a-redirection-that-writes-over-a-file": ("sh", "-c", "./bench -n {v} >|out"),
    "an-option-after-a-redirection": ("sh", "-c", "./bench 2>&1 -p {v}"),
    "an-option-before-a-redirection-standing-alone": ("sh", "-c", "./bench -a {v} > out"),
    "a-pipe-after-a-redirection": ("sh", "-c", "./bench -n {v} 2>&1 | tee out"),
    "a-label-that-looks-like-a-redirection": ("./bench", "--label", ">x", "-p", "{v}"),
}
VALUES = ("5", "7")


@pytest.mark.parametrize("name", sorted(KEPT_FORMS))
def test_an_ordinary_argument_around_a_redirection_stays_shown(name: str) -> None:
    words = KEPT_FORMS[name]
    one, two = ([word.replace("{v}", value) for word in words] for value in VALUES)

    assert model.public_command(("pairbench", "run", "--", *one)) == SHOWN_LEAD + shlex.join(one)
    assert model.hashed_argv(one) == one
    assert argv_sha256(one) != argv_sha256(two)


def test_a_long_run_of_redirections_between_the_user_name_and_the_password_hides_it() -> None:
    # Each word looks past every redirection after it for the next word of its command.
    for password in PASSWORDS:
        text = "redis-cli AUTH made-up-user " + "2>&1 >out " * 500 + password
        hidden = "redis-cli AUTH made-up-user " + "2>&1 >out " * 500 + HIDDEN

        assert model.hashed_argv(["sh", "-c", text]) == ["sh", "-c", hidden]
