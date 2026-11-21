# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the clients and client commands the shown command does not read.

A client's options and command are read where a word names a client the config reference
lists. A client named through a variable, an alias or a shell function, or one the reference
does not list, is read as any program is; a command given in an option of ``ssh``, or sent by
``--cluster call`` to each node, is not read as a client's command; and a word in the
``$'...'`` quotes of a shell is not read as a shell reads it: not as a client's option, a
password rule, a client's command or the text of an ``eval``. The security policy lists each
among the known limits of the shown command with its advice, which says to give a client the
config reference does not list its password with ``--pass``, and the forms the limits name as
hidden stay hidden.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
NAMED_ANOTHER_WAY = (
    "**A client named another way.** A client's options and command are read where a word names "
    "the client, as the config reference lists the clients. A client named through a variable, an "
    "alias or a shell function, as in `sh -c 'C=redis-cli; $C -a password PING'`, "
    "`sh -c 'alias r=redis-cli; r -a password PING'` or "
    "`sh -c 'r() { redis-cli \"$@\"; }; r -a password PING'`, and a client the config reference "
    "does not list, as in `keydb-cli -a password PING`, are read as any program is, so the "
    "password shows. A credential form that the argument of any program hides, such as "
    "`--pass password`, is hidden there too."
)
SSH_OPTION_OR_CLUSTER_CALL = (
    "**A command given in an option of `ssh` or to `--cluster call`.** The value of an option of "
    "`ssh`, such as `-o RemoteCommand=...`, is read as a value and not as a command, and the words "
    "that `redis-cli --cluster call` or `valkey-cli --cluster call` sends to each node after its "
    "address are not read as a Redis command. A client's password there shows: "
    "`ssh -o 'RemoteCommand=redis-cli -a password PING' made-up-host` and "
    "`redis-cli --cluster call made-up-host:7000 AUTH password` show whole, and so does a rule of "
    "`ACL SETUSER` such as `>password` in either. A credential form that the argument of any "
    "program hides, such as `--password password`, is hidden in the value of an option of `ssh`."
)
ANSI_C_QUOTES = (
    "**A word in `$'...'` quotes.** A shell reads a word in `$'...'` quotes with its backslash "
    "escapes turned into the characters they stand for; the shown command does not read such a "
    "word as the shell does. So in a shell text after `bash -c`, a client's password option in "
    "them, as in `redis-cli $'-a' password PING`, a rule of `ACL SETUSER`, as in "
    "`redis-cli ACL SETUSER app on $'>password'`, a client's command, as in "
    "`memtier_benchmark --command $'AUTH password'`, and the text of an `eval`, as in "
    "`eval $'memtier_benchmark --command \\'AUTH password\\''` or "
    "`eval $'true\\nredis-cli -a password PING'`, show the password. In plain quotes, as in "
    "`redis-cli '-a' password PING`, `redis-cli ACL SETUSER app on '>password'`, "
    "`memtier_benchmark --command 'AUTH password'` or "
    "`eval 'memtier_benchmark --command \"AUTH password\"'`, it is hidden, and so is a password "
    "that is itself the word in `$'...'` quotes, as in `redis-cli -a $'password' PING`."
)
ADVICE = (
    "Name a client by its own name where its command starts, give a client the config reference "
    "does not list its password with `--pass` or through `launch.env_pass`, give `ssh` its remote "
    "command after the host, give the client of `--cluster call` its password with `-a`, and "
    "write a client's option, command or password rule and the text of an `eval` in plain quotes "
    "rather than in `$'...'` quotes."
)
# Each limit's examples, which the shown command and the hash show as typed.
SHOWN_WHOLE = (
    ("sh", "-c", "C=redis-cli; $C -a password PING"),
    ("sh", "-c", "alias r=redis-cli; r -a password PING"),
    ("sh", "-c", 'r() { redis-cli "$@"; }; r -a password PING'),
    ("keydb-cli", "-a", "password", "PING"),
    ("ssh", "-o", "RemoteCommand=redis-cli -a password PING", "made-up-host"),
    ("ssh", "-o", "RemoteCommand=redis-cli ACL SETUSER app on >password", "made-up-host"),
    ("redis-cli", "--cluster", "call", "made-up-host:7000", "AUTH", "password"),
    (
        "redis-cli",
        "--cluster",
        "call",
        "made-up-host:7000",
        "ACL",
        "SETUSER",
        "app",
        "on",
        ">password",
    ),
    ("valkey-cli", "--cluster", "call", "made-up-host:7000", "AUTH", "password"),
    ("bash", "-c", "redis-cli ACL SETUSER app on $'>password'"),
    ("bash", "-c", "redis-cli $'-a' password PING"),
    ("bash", "-c", "memtier_benchmark --command $'AUTH password'"),
    ("bash", "-c", "eval $'memtier_benchmark --command \\'AUTH password\\''"),
    ("bash", "-c", "eval $'true\\nredis-cli -a password PING'"),
)
# The forms the limits and their advice name as hidden, and what the shown command shows.
HIDDEN = (
    (
        ("sh", "-c", "C=redis-cli; $C --pass password PING"),
        "sh -c 'C=redis-cli; $C --pass <hidden> PING'",
    ),
    (("keydb-cli", "--pass", "password", "PING"), "keydb-cli --pass '<hidden>' PING"),
    (
        ("ssh", "-o", "RemoteCommand=tool --password password", "made-up-host"),
        "ssh -o 'RemoteCommand=tool --password <hidden>' made-up-host",
    ),
    (
        ("ssh", "made-up-host", "redis-cli -a password PING"),
        "ssh made-up-host 'redis-cli -a <hidden> PING'",
    ),
    (
        ("redis-cli", "-a", "password", "--cluster", "call", "made-up-host:7000", "PING"),
        "redis-cli -a '<hidden>' --cluster call made-up-host:7000 PING",
    ),
    (
        ("bash", "-c", "redis-cli ACL SETUSER app on '>password'"),
        "bash -c 'redis-cli ACL SETUSER app on '\"'\"'><hidden>'\"'\"''",
    ),
    (
        ("bash", "-c", "redis-cli '-a' password PING"),
        "bash -c 'redis-cli '\"'\"'-a'\"'\"' <hidden> PING'",
    ),
    (
        ("bash", "-c", "memtier_benchmark --command 'AUTH password'"),
        "bash -c 'memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"''",
    ),
    (
        ("bash", "-c", "eval 'memtier_benchmark --command \"AUTH password\"'"),
        "bash -c 'eval '\"'\"'memtier_benchmark --command \"AUTH <hidden>\"'\"'\"''",
    ),
    (
        ("bash", "-c", "redis-cli -a $'password' PING"),
        "bash -c 'redis-cli -a <hidden> PING'",
    ),
)


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


@pytest.mark.parametrize("limit", [NAMED_ANOTHER_WAY, SSH_OPTION_OR_CLUSTER_CALL, ANSI_C_QUOTES])
def test_the_security_policy_lists_the_limit(repo_root: Path, limit: str) -> None:
    assert limit in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


@pytest.mark.parametrize("args", SHOWN_WHOLE)
def test_each_example_is_shown_and_hashed_as_typed(args: tuple[str, ...]) -> None:
    assert model.public_command(args) == shlex.join(args)
    assert model.hashed_argv(args) == list(args)


@pytest.mark.parametrize(("args", "shown"), HIDDEN)
def test_the_forms_named_as_hidden_hide_the_password(args: tuple[str, ...], shown: str) -> None:
    assert model.public_command(args) == shown
    assert "<hidden>" in " ".join(model.hashed_argv(args))
