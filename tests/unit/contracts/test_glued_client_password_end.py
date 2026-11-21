# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A password glued to a client's option ends at the end of its word.

``redis-cli -aVALUE PING``, ``mysql -pVALUE DB`` and ``sshpass -pVALUE ssh
HOST`` hide the value glued to the option, and the next word is the client's
next argument, shown as it is, also when the value holds a word that names a
credential. The password written as the next argument is hidden too.
Each form is checked in the shown command, inside ``sh -c`` and in the hash,
which is the same whatever the password. Every value is made up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
H = model.HIDDEN
# Two made-up passwords, each holding a word that names a credential. No word of a form needs
# quotes, so its text after `sh -c` is its words joined by blanks.
PASSWORDS = ("made_up_token", "made_up_secret")
PW = "{pw}"

# (the arguments with `{pw}` where the password stands, the arguments shown)
FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "redis-cli": (("redis-cli", f"-a{PW}", "PING"), ("redis-cli", f"-a{H}", "PING")),
    "valkey-cli": (("valkey-cli", f"-a{PW}", "PING"), ("valkey-cli", f"-a{H}", "PING")),
    "redis-benchmark before an option": (
        ("redis-benchmark", f"-a{PW}", "-n", "1000"),
        ("redis-benchmark", f"-a{H}", "-n", "1000"),
    ),
    "redis-cli after a spaced password": (
        ("redis-cli", "-a", PW, f"-a{PW}", "PING"),
        ("redis-cli", "-a", H, f"-a{H}", "PING"),
    ),
    "mysql": (("mysql", f"-p{PW}", "made_up_db"), ("mysql", f"-p{H}", "made_up_db")),
    "sshpass": (
        ("sshpass", f"-p{PW}", "ssh", "made-up-host"),
        ("sshpass", f"-p{H}", "ssh", "made-up-host"),
    ),
    "a long option with =": (
        ("redis-cli", f"--pass={PW}", "PING"),
        ("redis-cli", f"--pass={H}", "PING"),
    ),
    "the password as the next argument": (
        ("redis-cli", "-a", PW, "PING"),
        ("redis-cli", "-a", H, "PING"),
    ),
}


def typed(args: tuple[str, ...], password: str) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password) for arg in args)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_the_word_after_a_glued_client_password_shows(name: str, password: str) -> None:
    args, shown = FORMS[name]
    text = shlex.join(typed(args, password))

    assert model.public_command((*LEAD, *typed(args, password))) == SHOWN_LEAD + shlex.join(shown)
    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", " ".join(shown)]
    )


@pytest.mark.parametrize("name", list(FORMS))
def test_the_hash_of_a_glued_client_password_is_the_same_whatever_it_is(name: str) -> None:
    args, shown = FORMS[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)
    texts = [
        model.hashed_argv(("sh", "-c", shlex.join(typed(args, password)))) for password in PASSWORDS
    ]

    assert first == second == list(shown)
    assert texts[0] == texts[1] == ["sh", "-c", " ".join(shown)]
