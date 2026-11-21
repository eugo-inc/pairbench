# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The passwords a Redis or Valkey server and a Sentinel are given, as the shown command hides them.

A replica gives its primary a password in ``--masterauth`` (``--primaryauth`` in
Valkey), also glued after ``=``, after a config file or after ``--replicaof``,
and in a variable named ``MASTERAUTH`` or ``PRIMARYAUTH``. A Sentinel is given
the password of a master in ``SENTINEL SET master auth-pass PASSWORD`` and the
password of the other Sentinels in ``SENTINEL CONFIG SET sentinel-pass
PASSWORD``, commands read in any case; a server started as a Sentinel takes the
same settings as a line of its config after ``--sentinel`` (``--sentinel
auth-pass master PASSWORD``). A server's ``--user NAME RULE ...`` is a ``user``
line of its config, whose rules give passwords and their hashes as ``ACL
SETUSER`` does (``>PASSWORD``, ``<PASSWORD``, ``#HASH``, ``!HASH``): each keeps
only its first character. Each password is hidden whole, each user name and
master name is shown, and the hash of the command is the same whatever its
password. Every value is made up; each password is a word of small letters
that no command writes by itself.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
H = model.HIDDEN
# Two made-up passwords: a command with one is hashed as the command with the other is.
PASSWORDS = ("zqmkiwi", "zqmplum")
PW = "{pw}"
SENTINEL_CLI = ("redis-cli", "-p", "26379")


def typed(args: tuple[str, ...], password: str) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password) for arg in args)


# (the arguments of a command with `{pw}` where its password stands, the arguments shown)
FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "masterauth": (("redis-server", "--masterauth", PW), ("redis-server", "--masterauth", H)),
    "masterauth glued": (
        ("redis-server", f"--masterauth={PW}"),
        ("redis-server", "--masterauth=" + H),
    ),
    "masterauth after a config file": (
        ("redis-server", "redis.conf", "--masterauth", PW),
        ("redis-server", "redis.conf", "--masterauth", H),
    ),
    "masterauth after replicaof": (
        ("redis-server", "--replicaof", "127.0.0.1", "6380", "--masterauth", PW),
        ("redis-server", "--replicaof", "127.0.0.1", "6380", "--masterauth", H),
    ),
    "masterauth after masteruser": (
        ("redis-server", "--masteruser", "made-up-user", "--masterauth", PW),
        ("redis-server", "--masteruser", "made-up-user", "--masterauth", H),
    ),
    "masterauth before the port": (
        ("redis-server", "--masterauth", PW, "--port", "6380"),
        ("redis-server", "--masterauth", H, "--port", "6380"),
    ),
    "primaryauth": (("valkey-server", "--primaryauth", PW), ("valkey-server", "--primaryauth", H)),
    "primaryauth glued": (
        ("valkey-server", f"--primaryauth={PW}"),
        ("valkey-server", "--primaryauth=" + H),
    ),
    "primaryauth after primaryuser": (
        ("valkey-server", "valkey.conf", "--primaryuser", "made-up-user", "--primaryauth", PW),
        ("valkey-server", "valkey.conf", "--primaryuser", "made-up-user", "--primaryauth", H),
    ),
    "a MASTERAUTH variable": (
        ("env", f"MASTERAUTH={PW}", "./bench"),
        ("env", "MASTERAUTH=" + H, "./bench"),
    ),
    "a PRIMARYAUTH variable": (
        ("env", f"PRIMARYAUTH={PW}", "./bench"),
        ("env", "PRIMARYAUTH=" + H, "./bench"),
    ),
    "a variable that ends in MASTERAUTH": (
        ("env", f"REDIS_MASTERAUTH={PW}", "./bench"),
        ("env", "REDIS_MASTERAUTH=" + H, "./bench"),
    ),
    "sentinel set auth-pass": (
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-pass", PW),
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-pass", H),
    ),
    "sentinel set auth-pass in small letters": (
        (*SENTINEL_CLI, "sentinel", "set", "mymaster", "AUTH-PASS", PW),
        (*SENTINEL_CLI, "sentinel", "set", "mymaster", "AUTH-PASS", H),
    ),
    "sentinel set auth-user before auth-pass": (
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "SET",
            "mymaster",
            "auth-user",
            "made-up-user",
            "auth-pass",
            PW,
        ),
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-user", "made-up-user", "auth-pass", H),
    ),
    "sentinel set auth-pass before auth-user": (
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "SET",
            "mymaster",
            "auth-pass",
            PW,
            "auth-user",
            "made-up-user",
        ),
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-pass", H, "auth-user", "made-up-user"),
    ),
    "sentinel set auth-pass before quorum": (
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-pass", PW, "quorum", "2"),
        (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "auth-pass", H, "quorum", "2"),
    ),
    "sentinel set of a master named set": (
        (*SENTINEL_CLI, "SENTINEL", "SET", "set", "auth-pass", PW),
        (*SENTINEL_CLI, "SENTINEL", "SET", "set", "auth-pass", H),
    ),
    "valkey-cli sentinel set": (
        ("valkey-cli", "-p", "26379", "SENTINEL", "SET", "mymaster", "auth-pass", PW),
        ("valkey-cli", "-p", "26379", "SENTINEL", "SET", "mymaster", "auth-pass", H),
    ),
    "sentinel config set sentinel-pass": (
        (*SENTINEL_CLI, "SENTINEL", "CONFIG", "SET", "sentinel-pass", PW),
        (*SENTINEL_CLI, "SENTINEL", "CONFIG", "SET", "sentinel-pass", H),
    ),
    "sentinel config set sentinel-user before sentinel-pass": (
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "CONFIG",
            "SET",
            "sentinel-user",
            "made-up-user",
            "sentinel-pass",
            PW,
        ),
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "CONFIG",
            "SET",
            "sentinel-user",
            "made-up-user",
            "sentinel-pass",
            H,
        ),
    ),
    "sentinel config set sentinel-pass before sentinel-user": (
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "CONFIG",
            "SET",
            "sentinel-pass",
            PW,
            "sentinel-user",
            "made-up-user",
        ),
        (
            *SENTINEL_CLI,
            "SENTINEL",
            "CONFIG",
            "SET",
            "sentinel-pass",
            H,
            "sentinel-user",
            "made-up-user",
        ),
    ),
    "sentinel set in the command of memtier": (
        ("memtier_benchmark", "--command", f"SENTINEL SET mymaster auth-pass {PW}"),
        ("memtier_benchmark", "--command", f"SENTINEL SET mymaster auth-pass {H}"),
    ),
    "redis-sentinel with an auth-pass line": (
        ("redis-sentinel", "sentinel.conf", "--sentinel", "auth-pass", "mymaster", PW),
        ("redis-sentinel", "sentinel.conf", "--sentinel", "auth-pass", "mymaster", H),
    ),
    "redis-server as a sentinel with an auth-pass line": (
        ("redis-server", "sentinel.conf", "--sentinel", "--sentinel", "auth-pass", "mymaster", PW),
        ("redis-server", "sentinel.conf", "--sentinel", "--sentinel", "auth-pass", "mymaster", H),
    ),
    "valkey-sentinel with an auth-pass line": (
        ("valkey-sentinel", "sentinel.conf", "--sentinel", "auth-pass", "mymaster", PW),
        ("valkey-sentinel", "sentinel.conf", "--sentinel", "auth-pass", "mymaster", H),
    ),
    "valkey-server as a sentinel with an auth-pass line": (
        ("valkey-server", "sentinel.conf", "--sentinel", "--sentinel", "auth-pass", "mymaster", PW),
        ("valkey-server", "sentinel.conf", "--sentinel", "--sentinel", "auth-pass", "mymaster", H),
    ),
    "a sentinel-pass line": (
        ("redis-sentinel", "sentinel.conf", "--sentinel", "sentinel-pass", PW, "--port", "26380"),
        ("redis-sentinel", "sentinel.conf", "--sentinel", "sentinel-pass", H, "--port", "26380"),
    ),
    "an auth-user line before an auth-pass line": (
        (
            *("redis-sentinel", "sentinel.conf", "--sentinel", "auth-user", "mymaster"),
            *("made-up-user", "--sentinel", "auth-pass", "mymaster", PW),
        ),
        (
            *("redis-sentinel", "sentinel.conf", "--sentinel", "auth-user", "mymaster"),
            *("made-up-user", "--sentinel", "auth-pass", "mymaster", H),
        ),
    ),
    # A server's `--user` gives a user name and that user's rules, as a `user` line of its
    # config does: a rule that gives a password or its hash keeps its first character.
    "a user line with a password rule": (
        ("redis-server", "--user", "worker", "+@list", "~jobs:*", "on", f">{PW}"),
        ("redis-server", "--user", "worker", "+@list", "~jobs:*", "on", ">" + H),
    ),
    "a user line of a sentinel before the port": (
        (
            *("redis-sentinel", "sentinel.conf", "--user", "sentinel-user", f">{PW}"),
            *("+client", "on", "--port", "26380"),
        ),
        (
            *("redis-sentinel", "sentinel.conf", "--user", "sentinel-user", ">" + H),
            *("+client", "on", "--port", "26380"),
        ),
    ),
    "a user line that removes a password": (
        ("valkey-server", "--user", "worker", "on", f"<{PW}"),
        ("valkey-server", "--user", "worker", "on", "<" + H),
    ),
    "a user line with the hash of a password": (
        ("valkey-sentinel", "sentinel.conf", "--user", "worker", "on", f"#{PW}"),
        ("valkey-sentinel", "sentinel.conf", "--user", "worker", "on", "#" + H),
    ),
    "a user line that removes the hash of a password": (
        ("redis-server", "--user", "worker", f"!{PW}", "on"),
        ("redis-server", "--user", "worker", "!" + H, "on"),
    ),
    "a server option in the place of the user name": (
        ("redis-server", "--user", "--requirepass", PW),
        ("redis-server", "--user", "--requirepass", H),
    ),
    "masterauth in the place of the user name": (
        ("redis-server", "--user", "--masterauth", PW, "--port", "7000"),
        ("redis-server", "--user", "--masterauth", H, "--port", "7000"),
    ),
    "masterauth after a user line": (
        ("redis-server", "--user", "made-up-user", "on", "nopass", "--masterauth", PW),
        ("redis-server", "--user", "made-up-user", "on", "nopass", "--masterauth", H),
    ),
    "a second user line": (
        ("redis-server", "--user", "made-up-user", "on", "nopass", "--user", "worker", f">{PW}"),
        ("redis-server", "--user", "made-up-user", "on", "nopass", "--user", "worker", ">" + H),
    ),
    # The passwords the server already hides by their names stay hidden.
    "requirepass": (("redis-server", "--requirepass", PW), ("redis-server", "--requirepass", H)),
    "tls-key-file-pass": (
        ("redis-server", "--tls-key-file-pass", PW),
        ("redis-server", "--tls-key-file-pass", H),
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_server_password_is_hidden_in_the_shown_command(name: str, password: str) -> None:
    args, shown = FORMS[name]

    assert model.public_command((*LEAD, *typed(args, password))) == SHOWN_LEAD + shlex.join(shown)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_server_password_is_hidden_inside_sh_c(name: str, password: str) -> None:
    # Inside a shell text the words keep their quotes as typed, the password replaced.
    args, _shown = FORMS[name]
    text = shlex.join(typed(args, password))

    assert model.public_command((*LEAD, "sh", "-c", text + " && echo done")) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", text.replace(password, H) + " && echo done"])
    )


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_server_password_is_hidden_in_one_text(name: str, password: str) -> None:
    # One text is shown as its words joined by single spaces.
    args, shown = FORMS[name]

    assert model.public_words(shlex.join(typed(args, password))) == " ".join(shown)


@pytest.mark.parametrize("name", list(FORMS))
def test_the_hash_of_a_server_command_is_the_same_whatever_its_password(name: str) -> None:
    args, _shown = FORMS[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)
    texts = [
        model.hashed_argv(("sh", "-c", shlex.join(typed(args, password)) + "; true"))
        for password in PASSWORDS
    ]

    assert first == second
    assert texts[0] == texts[1]
    assert not any(password in arg for password in PASSWORDS for arg in (*first, *texts[0]))


# The user names, the master names and the settings that are no password.
SHOWN_FORMS: dict[str, tuple[str, ...]] = {
    "masteruser": ("redis-server", "--masteruser", "made-up-user", "--port", "6380"),
    "primaryuser": ("valkey-server", "--primaryuser", "made-up-user", "--port", "6380"),
    "replicaof": ("redis-server", "redis.conf", "--replicaof", "127.0.0.1", "6380"),
    "a server started as a sentinel": (
        "redis-server",
        "sentinel.conf",
        "--sentinel",
        "--port",
        "26380",
    ),
    "a monitor line": (
        (
            "redis-sentinel",
            "sentinel.conf",
            "--sentinel",
            "monitor",
            "mymaster",
            "127.0.0.1",
            "6379",
            "2",
        )
    ),
    "an auth-user line": (
        "redis-sentinel",
        "sentinel.conf",
        "--sentinel",
        "auth-user",
        "mymaster",
        "made-up-user",
    ),
    "a sentinel-user line": (
        "redis-sentinel",
        "sentinel.conf",
        "--sentinel",
        "sentinel-user",
        "made-up-user",
    ),
    "sentinel set auth-user": (
        *SENTINEL_CLI,
        "SENTINEL",
        "SET",
        "mymaster",
        "auth-user",
        "made-up-user",
    ),
    "sentinel set quorum": (*SENTINEL_CLI, "SENTINEL", "SET", "mymaster", "quorum", "2"),
    "sentinel config set sentinel-user": (
        (*SENTINEL_CLI, "SENTINEL", "CONFIG", "SET", "sentinel-user", "made-up-user")
    ),
    "sentinel config set announce-ip": (
        (*SENTINEL_CLI, "SENTINEL", "CONFIG", "SET", "announce-ip", "127.0.0.1")
    ),
    "sentinel config get": (*SENTINEL_CLI, "SENTINEL", "CONFIG", "GET", "sentinel-user"),
    "sentinel monitor": (
        *SENTINEL_CLI,
        "SENTINEL",
        "MONITOR",
        "mymaster",
        "127.0.0.1",
        "6379",
        "2",
    ),
    "a sentinel line of an other program": (
        ("made-up-tool", "--sentinel", "auth-pass", "mymaster", "made-up-word")
    ),
    "sentinel set in an other program": (
        ("made-up-tool", "SENTINEL", "SET", "mymaster", "auth-pass", "made-up-word")
    ),
    "a user line with no password": (
        ("redis-server", "--user", "made-up-user", "on", "nopass", "~*", "+@all")
    ),
    "a user line before the port": (
        ("valkey-server", "--user", "made-up-user", "on", "resetpass", "--port", "6380")
    ),
    "the user of a client": ("redis-cli", "--user", "made-up-user", "PING"),
    "a user option of an other program": ("made-up-tool", "--user", "made-up-user", ">made-up"),
    "a switch that turns auth off": ("made-up-tool", "--no-auth", "made-up-word"),
    "a NOAUTH variable": ("env", "NOAUTH=1", "./bench"),
    "a MASTERUSER variable": ("env", "MASTERUSER=made-up-user", "./bench"),
}


@pytest.mark.parametrize("name", list(SHOWN_FORMS))
def test_a_user_name_a_master_name_and_an_ordinary_setting_are_shown(name: str) -> None:
    args = SHOWN_FORMS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(args)
    assert model.hashed_argv(args) == list(args)


# Shell texts where a server's user line ends before a word that only looks like a rule: the
# ``)`` or backquote that closes the command, glued to its last rule, ends the line.
SHOWN_TEXTS: dict[str, str] = {
    "a user line in a command substitution": (
        "x=$(redis-server --user made-up-user on) ./bench '>out.log'"
    ),
    "a user line in backquotes": "x=`redis-server --user made-up-user on` ./bench '>out.log'",
}


@pytest.mark.parametrize("name", list(SHOWN_TEXTS))
def test_a_word_after_the_end_of_a_user_line_is_shown(name: str) -> None:
    text = SHOWN_TEXTS[name]

    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", text]
    )
    assert model.public_words(text) == " ".join(shlex.split(text))
    assert model.hashed_argv(("sh", "-c", text)) == ["sh", "-c", text]


# A text of several lines given to a program as one argument, where a server's ``--user`` ends
# a line: the next line is a command of its own, whose password is hidden.
LINE_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "a client on the line after a user option": (
        ("made-up-tool", "redis-server --user\nredis-cli -a {pw} PING"),
        ("made-up-tool", f"redis-server --user\nredis-cli -a {H} PING"),
    ),
    "AUTH on the line after a user option of a hyperfine command": (
        ("hyperfine", "-N", "redis-server --user\nredis-cli AUTH {pw}"),
        ("hyperfine", "-N", f"redis-server --user\nredis-cli AUTH {H}"),
    ),
}


@pytest.mark.parametrize("name", list(LINE_FORMS))
def test_a_user_option_at_the_end_of_a_line_takes_no_word_of_the_next(name: str) -> None:
    args, shown = LINE_FORMS[name]
    hashes = [model.hashed_argv(typed(args, password)) for password in PASSWORDS]

    for password in PASSWORDS:
        assert model.public_command((*LEAD, *typed(args, password))) == (
            SHOWN_LEAD + shlex.join(shown)
        )
    assert hashes[0] == hashes[1]
    assert not any(password in arg for password in PASSWORDS for arg in hashes[0])


@pytest.mark.parametrize("name", ["MASTERAUTH", "PRIMARYAUTH", "masterauth", "REDIS_MASTERAUTH"])
def test_the_password_a_replica_gives_its_primary_is_a_credential(name: str) -> None:
    assert model.looks_like_credential(name) is True


@pytest.mark.parametrize("name", ["MASTERUSER", "PRIMARYUSER", "NOAUTH", "no-auth", "DISABLEAUTH"])
def test_a_user_name_and_a_switch_are_no_credential(name: str) -> None:
    assert model.looks_like_credential(name) is False
