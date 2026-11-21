# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The passwords that Redis and Valkey commands give, as the shown command and the hashes hide them.

A command of ``redis-cli``, ``valkey-cli``, ``redis-benchmark`` or
``valkey-benchmark``, and the text of ``memtier_benchmark --command``, gives a
password in ``AUTH [user] password``, in ``HELLO protover AUTH user password``,
in ``MIGRATE ... AUTH password`` and ``AUTH2 user password``, and in ``CONFIG
SET masterauth`` or ``requirepass``. Each password is hidden whole, the user name
is shown, and the hash of a command is the same whatever its password. A setting
that names a file shows its path. Every value is made up; each password is a
word of small letters that no command writes by itself.
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


# The arguments of MIGRATE that copy the keys named after KEYS: no key before the options.
MIGRATE_COPY = ("redis-cli", "MIGRATE", "127.0.0.1", "6380", "", "0", "5000", "COPY")


def typed(args: tuple[str, ...], password: str) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password) for arg in args)


# (the arguments of a command with `{pw}` where its password stands, the arguments shown)
FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "config set masterauth": (
        ("redis-cli", "CONFIG", "SET", "masterauth", PW),
        ("redis-cli", "CONFIG", "SET", "masterauth", H),
    ),
    "config set requirepass": (
        ("redis-cli", "CONFIG", "SET", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", "requirepass", H),
    ),
    "auth": (("redis-cli", "AUTH", PW), ("redis-cli", "AUTH", H)),
    "auth with a user": (
        ("redis-cli", "AUTH", "made-up-user", PW),
        ("redis-cli", "AUTH", "made-up-user", H),
    ),
    "auth in small letters": (("redis-cli", "auth", PW), ("redis-cli", "auth", H)),
    "hello": (
        ("redis-cli", "HELLO", "3", "AUTH", "made-up-user", PW),
        ("redis-cli", "HELLO", "3", "AUTH", "made-up-user", H),
    ),
    "hello and a name": (
        ("redis-cli", "HELLO", "3", "AUTH", "made-up-user", PW, "SETNAME", "bench"),
        ("redis-cli", "HELLO", "3", "AUTH", "made-up-user", H, "SETNAME", "bench"),
    ),
    "migrate auth": (
        ("redis-cli", "MIGRATE", "127.0.0.1", "6380", "made-up-key", "0", "5000", "AUTH", PW),
        ("redis-cli", "MIGRATE", "127.0.0.1", "6380", "made-up-key", "0", "5000", "AUTH", H),
    ),
    "migrate auth2": (
        (*MIGRATE_COPY, "AUTH2", "made-up-user", PW, "KEYS", "a", "b"),
        (*MIGRATE_COPY, "AUTH2", "made-up-user", H, "KEYS", "a", "b"),
    ),
    "user and pass": (
        ("redis-cli", "--user", "made-up-user", "--pass", PW, "PING"),
        ("redis-cli", "--user", "made-up-user", "--pass", H, "PING"),
    ),
    "pass glued": (
        ("redis-cli", "--user", "made-up-user", f"--pass={PW}", "PING"),
        ("redis-cli", "--user", "made-up-user", f"--pass={H}", "PING"),
    ),
    "valkey-cli auth after its options": (
        ("valkey-cli", "-h", "127.0.0.1", "-p", "6379", "-t", "5", "AUTH", PW),
        ("valkey-cli", "-h", "127.0.0.1", "-p", "6379", "-t", "5", "AUTH", H),
    ),
    "valkey-cli config set masterauth": (
        ("valkey-cli", "CONFIG", "SET", "masterauth", PW),
        ("valkey-cli", "CONFIG", "SET", "masterauth", H),
    ),
    "redis-benchmark auth after its options": (
        ("redis-benchmark", "-c", "50", "-P", "4", "-n", "10", "AUTH", PW),
        ("redis-benchmark", "-c", "50", "-P", "4", "-n", "10", "AUTH", H),
    ),
    "redis-benchmark quoted command": (
        ("redis-benchmark", "-n", "10", f"AUTH {PW}"),
        ("redis-benchmark", "-n", "10", f"AUTH {H}"),
    ),
    "valkey-benchmark user and pass": (
        ("valkey-benchmark", "--user", "made-up-user", "--pass", PW, "-t", "get"),
        ("valkey-benchmark", "--user", "made-up-user", "--pass", H, "-t", "get"),
    ),
    "memtier authenticate": (
        ("memtier_benchmark", "--authenticate", PW),
        ("memtier_benchmark", "--authenticate", H),
    ),
    "memtier authenticate glued": (
        ("memtier_benchmark", f"--authenticate={PW}"),
        ("memtier_benchmark", f"--authenticate={H}"),
    ),
    "memtier command auth": (
        ("memtier_benchmark", "--command", f"AUTH {PW}"),
        ("memtier_benchmark", "--command", f"AUTH {H}"),
    ),
    "memtier command glued auth with a user": (
        ("memtier_benchmark", f"--command=AUTH made-up-user {PW}"),
        ("memtier_benchmark", f"--command=AUTH made-up-user {H}"),
    ),
    "memtier command config set": (
        ("memtier_benchmark", "--command", f"CONFIG SET masterauth {PW}", "-n", "10"),
        ("memtier_benchmark", "--command", f"CONFIG SET masterauth {H}", "-n", "10"),
    ),
    "memtier command hello": (
        ("memtier_benchmark", "--command", f"HELLO 3 AUTH made-up-user {PW}"),
        ("memtier_benchmark", "--command", f"HELLO 3 AUTH made-up-user {H}"),
    ),
    # The options before the command that take a value: a repeat count and a database number.
    "a repeat count before auth": (
        ("redis-cli", "-r", "3", "AUTH", PW),
        ("redis-cli", "-r", "3", "AUTH", H),
    ),
    "a database number before auth": (
        ("redis-benchmark", "--dbnum", "2", "AUTH", PW),
        ("redis-benchmark", "--dbnum", "2", "AUTH", H),
    ),
    "a user name before auth": (
        ("redis-cli", "--user", "made-up-user", "AUTH", PW),
        ("redis-cli", "--user", "made-up-user", "AUTH", H),
    ),
    "a certificate before auth": (
        ("redis-cli", "--tls", "--cert", "certs/c.crt", "AUTH", PW),
        ("redis-cli", "--tls", "--cert", "certs/c.crt", "AUTH", H),
    ),
    "a key pattern before auth": (
        ("redis-cli", "--pattern", "made-up:*", "AUTH", PW),
        ("redis-cli", "--pattern", "made-up:*", "AUTH", H),
    ),
    "a seed before auth": (
        ("valkey-benchmark", "--seed", "7", "AUTH", PW),
        ("valkey-benchmark", "--seed", "7", "AUTH", H),
    ),
    # CONFIG SET takes several settings, each name followed by its value.
    "config set of a password after another setting": (
        ("redis-cli", "CONFIG", "SET", "masteruser", "made-up-user", "masterauth", PW),
        ("redis-cli", "CONFIG", "SET", "masteruser", "made-up-user", "masterauth", H),
    ),
    "config set of a password before another setting": (
        ("redis-cli", "CONFIG", "SET", "requirepass", PW, "maxmemory", "100mb"),
        ("redis-cli", "CONFIG", "SET", "requirepass", H, "maxmemory", "100mb"),
    ),
    "config set of two passwords": (
        ("valkey-cli", "CONFIG", "SET", "requirepass", PW, "primaryauth", PW),
        ("valkey-cli", "CONFIG", "SET", "requirepass", H, "primaryauth", H),
    ),
    "memtier command config set of several settings": (
        ("memtier_benchmark", "--command", f"CONFIG SET masteruser made-up-user masterauth {PW}"),
        ("memtier_benchmark", "--command", f"CONFIG SET masteruser made-up-user masterauth {H}"),
    ),
    # A value that starts with a dash is a word of the command as any other.
    "config set of a password after a setting of a value below zero": (
        ("redis-cli", "CONFIG", "SET", "slowlog-log-slower-than", "-1", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", "slowlog-log-slower-than", "-1", "requirepass", H),
    ),
    "memtier command config set after a value below zero": (
        ("memtier_benchmark", "--command", f"CONFIG SET list-max-listpack-size -2 masterauth {PW}"),
        ("memtier_benchmark", "--command", f"CONFIG SET list-max-listpack-size -2 masterauth {H}"),
    ),
    "config set of a password after a value of two dashes": (
        ("redis-cli", "CONFIG", "SET", "made-up-setting", "--", "masterauth", PW),
        ("redis-cli", "CONFIG", "SET", "made-up-setting", "--", "masterauth", H),
    ),
    # The rules of ACL SETUSER that add or remove a password, or the hash of one.
    "acl setuser adds a password": (
        ("redis-cli", "ACL", "SETUSER", "made-up-user", "on", f">{PW}", "~*", "+@all"),
        ("redis-cli", "ACL", "SETUSER", "made-up-user", "on", f">{H}", "~*", "+@all"),
    ),
    "acl setuser removes a password": (
        ("valkey-cli", "ACL", "SETUSER", "made-up-user", f"<{PW}"),
        ("valkey-cli", "ACL", "SETUSER", "made-up-user", f"<{H}"),
    ),
    "acl setuser adds and removes the hash of a password": (
        ("redis-cli", "acl", "setuser", "made-up-user", f"#{PW}", f"!{PW}", "nopass"),
        ("redis-cli", "acl", "setuser", "made-up-user", f"#{H}", f"!{H}", "nopass"),
    ),
    "memtier command acl setuser": (
        ("memtier_benchmark", "--command", f"ACL SETUSER made-up-user on >{PW} +@read"),
        ("memtier_benchmark", "--command", f"ACL SETUSER made-up-user on >{H} +@read"),
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_redis_password_is_hidden_in_the_shown_command(name: str, password: str) -> None:
    args, shown = FORMS[name]

    assert model.public_command((*LEAD, *typed(args, password))) == SHOWN_LEAD + shlex.join(shown)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_redis_password_is_hidden_inside_sh_c(name: str, password: str) -> None:
    # Inside a shell text the words keep their quotes as typed, the password replaced.
    args, _shown = FORMS[name]
    text = shlex.join(typed(args, password))

    assert model.public_command((*LEAD, "sh", "-c", text + " && echo done")) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", text.replace(password, H) + " && echo done"])
    )


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_a_redis_password_is_hidden_in_one_text(name: str, password: str) -> None:
    # One text is shown as its words joined by single spaces.
    args, shown = FORMS[name]

    assert model.public_words(shlex.join(typed(args, password))) == " ".join(
        arg for arg in shown if arg
    )


@pytest.mark.parametrize("name", list(FORMS))
def test_the_hash_of_a_redis_command_is_the_same_whatever_its_password(name: str) -> None:
    args, _shown = FORMS[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)
    texts = [
        model.hashed_argv(("sh", "-c", shlex.join(typed(args, password)) + "; true"))
        for password in PASSWORDS
    ]

    assert first == second
    assert texts[0] == texts[1]
    assert not any(password in arg for password in PASSWORDS for arg in (*first, *texts[0]))


# The user names, and the words a command writes that are no password.
SHOWN_FORMS: dict[str, tuple[str, ...]] = {
    "config set masteruser": ("redis-cli", "CONFIG", "SET", "masteruser", "made-up-user"),
    "set of a key": ("redis-cli", "SET", "made-up-key", "made-up-value"),
    "get of a key named auth": ("redis-cli", "GET", "auth"),
    "a key named auth before the arguments of migrate": (
        ("redis-cli", "MIGRATE", "127.0.0.1", "6380", "auth", "0", "5000")
    ),
    "auth in an other program": ("made-up-tool", "AUTH", "made-up-word"),
    "auth after the command": ("redis-cli", "PING", "AUTH", "made-up-word"),
    "a set with an expiry in memtier": (
        ("memtier_benchmark", "--command", "set __key__ __data__ EX 60", "-n", "10")
    ),
    "a set glued in memtier": ("memtier_benchmark", "--command=set __key__ __data__ EX 60"),
    "a key file": ("redis-cli", "CONFIG", "SET", "tls-key-file", "certs/redis.key"),
    "a certificate file": ("redis-cli", "CONFIG", "SET", "tls-cert-file", "certs/redis.crt"),
    "a certificate authority file": (
        ("redis-cli", "CONFIG", "SET", "tls-ca-cert-file", "certs/ca.crt")
    ),
    "a certificate folder": ("valkey-cli", "CONFIG", "SET", "tls-ca-cert-dir", "certs"),
    "a client key file": ("redis-cli", "CONFIG", "SET", "tls-client-key-file", "certs/c.key"),
    "config set of two ordinary settings": (
        ("redis-cli", "CONFIG", "SET", "maxmemory", "100mb", "maxmemory-policy", "allkeys-lru")
    ),
    "config set of a value below zero and a user name": (
        ("redis-cli", "CONFIG", "SET", "slowlog-log-slower-than", "-1", "masteruser", "made-up")
    ),
    "acl setuser with no password": (
        ("redis-cli", "ACL", "SETUSER", "made-up-user", "on", "nopass", "~made-up:*", "+@read")
    ),
    "acl deluser": ("redis-cli", "ACL", "DELUSER", "made-up-user"),
}


@pytest.mark.parametrize("name", list(SHOWN_FORMS))
def test_a_user_name_and_an_ordinary_word_are_shown(name: str) -> None:
    args = SHOWN_FORMS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(args)
    assert model.hashed_argv(args) == list(args)


def test_a_different_expiry_in_memtier_is_a_different_command() -> None:
    one = ("memtier_benchmark", "--command", "set __key__ __data__ EX 60")
    two = ("memtier_benchmark", "--command", "set __key__ __data__ EX 120")

    assert model.hashed_argv(one) != model.hashed_argv(two)


def test_a_setting_that_ends_in_a_password_word_is_hidden() -> None:
    args = ("redis-cli", "CONFIG", "SET", "tls-key-file-pass", "zqmkiwi")

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(
        ["redis-cli", "CONFIG", "SET", "tls-key-file-pass", H]
    )


@pytest.mark.parametrize("path", ["~/certs/redis.key", "/made-up/certs/redis.key"])
def test_a_rooted_key_file_keeps_only_its_name(path: str) -> None:
    args = ("redis-cli", "CONFIG", "SET", "tls-key-file", path)

    assert model.public_command((*LEAD, *args)) == (
        SHOWN_LEAD + "redis-cli CONFIG SET tls-key-file redis.key"
    )


# A password hidden after `AUTH` whose command ends there: the next command is shown.
@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("redis-cli AUTH zqmkiwi; redis-cli PING", f"redis-cli AUTH {H}; redis-cli PING"),
        ("redis-cli AUTH zqmkiwi ; redis-cli PING", f"redis-cli AUTH {H} ; redis-cli PING"),
        ("redis-cli AUTH zqmkiwi\nredis-cli PING", f"redis-cli AUTH {H}\nredis-cli PING"),
        (
            "redis-cli AUTH made-up-user zqmkiwi && redis-cli PING",
            f"redis-cli AUTH made-up-user {H} && redis-cli PING",
        ),
        # A `)` or a backquote written apart closes the command, so no user name comes first.
        (
            "( redis-cli AUTH zqmkiwi ) && redis-cli PING",
            f"( redis-cli AUTH {H} ) && redis-cli PING",
        ),
        ("echo ` redis-cli AUTH zqmkiwi ` done", f"echo ` redis-cli AUTH {H} ` done"),
    ],
)
def test_auth_ends_with_its_command(text: str, shown: str) -> None:
    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", shown]
    )


# A redirection after the password of `AUTH` gives the shell a file, so it is no user name:
# the word before it is the password. Each row holds the text and how it shows.
REDIRECTIONS: dict[str, tuple[str, str]] = {
    "glued": ("redis-cli AUTH {pw} >/dev/null", f"redis-cli AUTH {H} >null"),
    "apart": ("redis-cli AUTH {pw} > /dev/null", f"redis-cli AUTH {H} > null"),
    "descriptor": ("redis-cli AUTH {pw} 2>&1", f"redis-cli AUTH {H} 2>&1"),
    "both streams": ("redis-cli AUTH {pw} &>made-up.log", f"redis-cli AUTH {H} &>made-up.log"),
    "input": ("redis-cli AUTH {pw} </dev/null", f"redis-cli AUTH {H} <null"),
    "with a user": (
        "redis-cli AUTH made-up-user {pw} >/dev/null",
        f"redis-cli AUTH made-up-user {H} >null",
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(REDIRECTIONS))
def test_a_redirection_after_an_auth_password_is_no_user_name(name: str, password: str) -> None:
    text, shown = REDIRECTIONS[name]
    typed_text = text.format(pw=password)

    assert model.public_command((*LEAD, "sh", "-c", typed_text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", shown]
    )
    assert model.public_words(typed_text) == shown


@pytest.mark.parametrize("name", list(REDIRECTIONS))
def test_the_hash_of_auth_before_a_redirection_is_the_same_whatever_its_password(
    name: str,
) -> None:
    text, _shown = REDIRECTIONS[name]
    first, second = (
        model.hashed_argv(("sh", "-c", text.format(pw=password))) for password in PASSWORDS
    )

    assert first == second == ["sh", "-c", text.replace("{pw}", H)]


# A `)` or a backquote that ends a command after a hidden setting value: the next word shows, and
# so does the `)` or backquote.
@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (
            "(redis-cli CONFIG SET requirepass zqmkiwi) ./bench 64",
            f"(redis-cli CONFIG SET requirepass {H}) ./bench 64",
        ),
        (
            # A text in backquotes is a command of its own, so its closing backquote stays.
            "echo `redis-cli CONFIG SET requirepass zqmkiwi` ./bench 64",
            f"echo `redis-cli CONFIG SET requirepass {H}` ./bench 64",
        ),
        (
            "(redis-cli CONFIG SET requirepass zqmkiwi ) ./bench 64",
            f"(redis-cli CONFIG SET requirepass {H} ) ./bench 64",
        ),
        (
            "echo `redis-cli CONFIG SET requirepass zqmkiwi ` ./bench 64",
            f"echo `redis-cli CONFIG SET requirepass {H} ` ./bench 64",
        ),
    ],
    ids=["bracket glued", "backquote glued", "bracket alone", "backquote alone"],
)
def test_a_command_closed_after_a_hidden_setting_value_shows_the_next_word(
    text: str, shown: str
) -> None:
    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", shown]
    )


def test_a_long_option_glued_after_a_setting_keeps_its_name_across_a_line_break() -> None:
    args = ("gh", "secret", "set", "MY_TOKEN", "--body=zqmkiwi\nzqmplum")

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(
        ["gh", "secret", "set", "MY_TOKEN", f"--body={H}"]
    )


def test_set_as_the_value_of_an_option_starts_a_setting() -> None:
    # Only the client's command, its first word that is no option and no value of one, writes
    # a key; `set` as the value of `-n` is a word of a setting, as it is anywhere else.
    args = ("redis-cli", "-n", "set", "api_key", "zqmkiwi")

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(
        ["redis-cli", "-n", "set", "api_key", H]
    )
