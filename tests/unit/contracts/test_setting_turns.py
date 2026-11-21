# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A word a shell may split leaves the names of ``CONFIG SET`` without their turn.

``CONFIG SET`` takes names and values in turn, and ``SENTINEL SET`` does so
after the name of the primary, so only a word in a name's place names a
setting; ``MIGRATE`` reads ``AUTH`` and ``AUTH2`` after five fixed arguments.
In a shell text a word that a shell may make no word or several of
(``$NAME``, ``$(...)``, a text in backquotes, ``"$@"``) leaves the place of
every word after it unknown, so a credential setting's name hides the next
word in either place, and ``AUTH`` of ``MIGRATE`` is read after any count of
words. A word in quotes that a shell keeps as one word (``"$(...)"``,
``"$X"``) keeps the turn. The shown command and the published
hashes read every form alike: two passwords give one shown command and one
hash.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model
from pairbench.model import HIDDEN
from pairbench.sides.identity import argv_sha256

# Two made-up passwords that hold no credential word, so only the setting's name hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
SHOWN_LEAD = "pairbench run -- "

# Each form: its argument list with ``{s}`` for the password, and the list as shown and hashed.
HIDDEN_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a-name-from-a-command-in-backquotes": (
        ("sh", "-c", "redis-cli CONFIG SET `echo a b` requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET `echo a b` requirepass {HIDDEN}"),
    ),
    "a-name-from-a-command-in-backquotes-one-word": (
        ("sh", "-c", "redis-cli CONFIG SET `echo 1` requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET `echo 1` requirepass {HIDDEN}"),
    ),
    "a-name-from-a-command": (
        ("sh", "-c", "redis-cli CONFIG SET $(echo 1) requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET $(echo 1) requirepass {HIDDEN}"),
    ),
    "a-name-from-a-parameter": (
        ("sh", "-c", "redis-cli CONFIG SET $NAME requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET $NAME requirepass {HIDDEN}"),
    ),
    "a-value-from-a-command": (
        ("sh", "-c", "redis-cli CONFIG SET maxmemory $(echo 1) requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET maxmemory $(echo 1) requirepass {HIDDEN}"),
    ),
    "a-name-glued-to-a-command": (
        ("sh", "-c", "redis-cli CONFIG SET a$(echo 1) requirepass {s}"),
        ("sh", "-c", f"redis-cli CONFIG SET a$(echo 1) requirepass {HIDDEN}"),
    ),
    "the-parameters-in-double-quotes": (
        ("sh", "-c", 'redis-cli CONFIG SET "$@" requirepass {s}', "_", "a", "b"),
        ("sh", "-c", f'redis-cli CONFIG SET "$@" requirepass {HIDDEN}', "_", "a", "b"),
    ),
    "the-parameters-in-braces-in-double-quotes": (
        ("sh", "-c", 'redis-cli CONFIG SET "${@}" requirepass {s}', "_", "a"),
        ("sh", "-c", f'redis-cli CONFIG SET "${{@}}" requirepass {HIDDEN}', "_", "a"),
    ),
    "a-whole-list-in-double-quotes": (
        ("bash", "-c", 'redis-cli CONFIG SET "${ITEMS[@]}" requirepass {s}'),
        ("bash", "-c", f'redis-cli CONFIG SET "${{ITEMS[@]}}" requirepass {HIDDEN}'),
    ),
    "a-parameter-of-the-text": (
        ("sh", "-c", "redis-cli CONFIG SET $1 requirepass {s}", "_", "a b"),
        ("sh", "-c", f"redis-cli CONFIG SET $1 requirepass {HIDDEN}", "_", "a b"),
    ),
    "a-sentinel-setting-after-a-command": (
        ("sh", "-c", "redis-cli SENTINEL SET mymaster $(echo 1) auth-pass {s}"),
        ("sh", "-c", f"redis-cli SENTINEL SET mymaster $(echo 1) auth-pass {HIDDEN}"),
    ),
    "a-host-and-port-from-a-command-before-the-auth-of-migrate": (
        ("sh", "-c", "redis-cli MIGRATE $(echo h 6379) '' 0 5000 AUTH {s}"),
        ("sh", "-c", f"redis-cli MIGRATE $(echo h 6379) '' 0 5000 AUTH {HIDDEN}"),
    ),
    "a-parameter-before-the-auth2-of-migrate": (
        ("sh", "-c", "redis-cli MIGRATE $NODE '' 0 5000 AUTH2 made-up-user {s}"),
        ("sh", "-c", f"redis-cli MIGRATE $NODE '' 0 5000 AUTH2 made-up-user {HIDDEN}"),
    ),
    "a-client-named-again-before-an-operator": (
        ("sh", "-c", "redis-cli CONFIG SET $X a redis-cli CONFIG SET maxmemory requirepass {s}"),
        (
            "sh",
            "-c",
            f"redis-cli CONFIG SET $X a redis-cli CONFIG SET maxmemory requirepass {HIDDEN}",
        ),
    ),
    "a-password-glued-to-an-operator-of-a-remote-text": (
        (
            "ssh",
            "host",
            "redis-cli",
            "CONFIG",
            "SET",
            "$X",
            "a",
            "requirepass",
            "{s};",
            "redis-cli",
            "CONFIG",
            "SET",
            "maxmemory",
            "requirepass",
            "lazyfree-lazy-eviction",
            "yes",
        ),
        (
            "ssh",
            "host",
            "redis-cli",
            "CONFIG",
            "SET",
            "$X",
            "a",
            "requirepass",
            f"{HIDDEN};",
            "redis-cli",
            "CONFIG",
            "SET",
            "maxmemory",
            "requirepass",
            "lazyfree-lazy-eviction",
            "yes",
        ),
    ),
    "a-remote-command-of-ssh": (
        ("ssh", "host", "redis-cli CONFIG SET `echo a b` masterauth {s}"),
        ("ssh", "host", f"redis-cli CONFIG SET `echo a b` masterauth {HIDDEN}"),
    ),
}

# Forms whose words a shell keeps one word each, so the names keep their turn and stay shown.
KEPT_FORMS: dict[str, tuple[str, ...]] = {
    "a-command-in-double-quotes": (
        "sh",
        "-c",
        'redis-cli CONFIG SET "$(echo {v})" requirepass maxmemory 100mb',
    ),
    "a-parameter-in-double-quotes": (
        "sh",
        "-c",
        'redis-cli CONFIG SET "$NAME{v}" requirepass maxmemory 100mb',
    ),
    "the-parameters-in-single-quotes": (
        "sh",
        "-c",
        "redis-cli CONFIG SET '$@{v}' requirepass maxmemory 100mb",
    ),
    "a-whole-list-in-single-quotes": (
        "bash",
        "-c",
        "redis-cli CONFIG SET '${ITEMS[@]}{v}' requirepass maxmemory 100mb",
    ),
    "no-credential-setting-after-a-command": (
        "sh",
        "-c",
        "redis-cli CONFIG SET $(echo {v}) maxmemory 100mb",
    ),
}
VALUES = ("5", "7")


def typed(words: tuple[str, ...], password: str) -> list[str]:
    return [word.replace("{s}", password) for word in words]


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_a_credential_setting_after_a_word_a_shell_may_split_hides_its_value(name: str) -> None:
    words, hidden = HIDDEN_FORMS[name]
    for password in PASSWORDS:
        argv = typed(words, password)

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(hidden)
        )
        assert model.hashed_argv(argv) == list(hidden)


@pytest.mark.parametrize("name", sorted(HIDDEN_FORMS))
def test_two_passwords_after_a_word_a_shell_may_split_give_one_hash(name: str) -> None:
    words, _hidden = HIDDEN_FORMS[name]
    one, two = (typed(words, password) for password in PASSWORDS)

    assert argv_sha256(one) == argv_sha256(two)


@pytest.mark.parametrize("name", sorted(KEPT_FORMS))
def test_a_word_a_shell_keeps_whole_keeps_the_turn_of_the_names(name: str) -> None:
    hashes = set()
    for value in VALUES:
        argv = [word.replace("{v}", value) for word in KEPT_FORMS[name]]

        assert model.public_command(("pairbench", "run", "--", *argv)) == (
            SHOWN_LEAD + shlex.join(argv)
        )
        assert model.hashed_argv(argv) == argv
        hashes.add(argv_sha256(argv))
    assert len(hashes) == len(VALUES)
