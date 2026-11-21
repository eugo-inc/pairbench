# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``memtier_benchmark -a`` shows its user, and a data store's key is no header.

``memtier_benchmark --authenticate USER:PASSWORD`` and ``-a USER:PASSWORD`` show the user
and hide the password; a password alone is hidden whole, and so is the whole value after
``--authenticate=``. An argument of a data store's client that is one word with no blank,
as ``auth:`` in ``--key-prefix auth:``, is a key and is shown as typed, while the same word
sent as a header by ``curl``, a header text with a blank in it, and a word of a shell text
or of a command written as one text are read as a header. Each form is checked in the shown
command, inside ``sh -c`` and in the hash. Every value is made up.
"""

from __future__ import annotations

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
# Two made-up passwords that need no quotes in a shell text, and two made-up users.
PASSWORDS = ("made_up_pw_one", "made_up_pw_two")
USERS = ("made-up-user", "other-made-up-user")
PW = "{pw}"
USER = "{user}"

# (the arguments with `{user}` and `{pw}` where they stand, the shown command, the shown
# `sh -c` command)
CREDENTIALS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "--authenticate user:password": (
        ("memtier_benchmark", "--authenticate", f"{USER}:{PW}", "--ratio", "1:1"),
        "memtier_benchmark --authenticate '{user}:<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark --authenticate {user}:<hidden> --ratio 1:1'",
    ),
    "-a user:password": (
        ("memtier_benchmark", "-a", f"{USER}:{PW}", "--ratio", "1:1"),
        "memtier_benchmark -a '{user}:<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark -a {user}:<hidden> --ratio 1:1'",
    ),
    "-auser:password": (
        ("memtier_benchmark", f"-a{USER}:{PW}", "--ratio", "1:1"),
        "memtier_benchmark '-a{user}:<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark -a{user}:<hidden> --ratio 1:1'",
    ),
}
# Forms whose user is hidden with the password, or that hold no user.
WHOLE: dict[str, tuple[tuple[str, ...], str, str]] = {
    "--authenticate password": (
        ("memtier_benchmark", "--authenticate", PW, "--ratio", "1:1"),
        "memtier_benchmark --authenticate '<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark --authenticate <hidden> --ratio 1:1'",
    ),
    "-a password": (
        ("memtier_benchmark", "-a", PW, "--ratio", "1:1"),
        "memtier_benchmark -a '<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark -a <hidden> --ratio 1:1'",
    ),
    "-apassword": (
        ("memtier_benchmark", f"-a{PW}", "--ratio", "1:1"),
        "memtier_benchmark '-a<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark -a<hidden> --ratio 1:1'",
    ),
    "-a :password": (
        ("memtier_benchmark", "-a", f":{PW}", "--ratio", "1:1"),
        "memtier_benchmark -a '<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark -a <hidden> --ratio 1:1'",
    ),
    "--authenticate=user:password": (
        ("memtier_benchmark", f"--authenticate={USERS[0]}:{PW}", "--ratio", "1:1"),
        "memtier_benchmark '--authenticate=<hidden>' --ratio 1:1",
        "sh -c 'memtier_benchmark --authenticate=<hidden> --ratio 1:1'",
    ),
}

# Arguments of a data store's client shown as typed, in the shown command and the hash.
KEYS: dict[str, tuple[str, ...]] = {
    "--key-prefix auth:": ("memtier_benchmark", "--key-prefix", "auth:", "--ratio", "1:1"),
    "--key-prefix=auth:": ("memtier_benchmark", "--key-prefix=auth:", "--ratio", "1:1"),
    "redis-cli GET auth:": ("redis-cli", "GET", "auth:"),
    "valkey-cli GET Cookie:": ("valkey-cli", "GET", "Cookie:"),
}
# (the arguments with `{pw}`, the shown command): the same word where it is a header still.
HEADERS: dict[str, tuple[tuple[str, ...], str]] = {
    "curl -H 'auth: password'": (
        ("curl", "-H", f"auth: {PW}", "http://localhost/x"),
        "curl -H 'auth: <hidden>' http://localhost/x",
    ),
    "a header text with a blank given to redis-cli": (
        ("redis-cli", "SET", "k", f"Authorization: Bearer {PW}"),
        "redis-cli SET k 'Authorization: <hidden>'",
    ),
    "a header text with two blanks given to memtier": (
        ("memtier_benchmark", "--key-prefix", f"auth: Bearer {PW}"),
        "memtier_benchmark --key-prefix 'auth: <hidden>'",
    ),
    "a program that is no data store's client": (
        ("./bench", "--prefix", f"auth:{PW}", "64"),
        "./bench --prefix 'auth: <hidden>' 64",
    ),
}
# The same word alone, as an argument of a program that is no data store's client.
NO_CLIENT = (("./bench", "--prefix", "auth:", "64"), "./bench --prefix 'auth: <hidden>' 64")
# (the `sh -c` text with `{pw}`, the shown command): a word of a shell text is read as a
# header still, so the words after it up to the end of its command are hidden.
SHELL_HEADERS: dict[str, tuple[str, str]] = {
    "memtier key prefix in a shell text": (
        f"memtier_benchmark --key-prefix auth: {PW} --ratio 1:1",
        "sh -c 'memtier_benchmark --key-prefix auth: <hidden>'",
    ),
    "redis-cli header text in a shell text": (
        f'redis-cli SET k "Authorization: Bearer {PW}" && echo done',
        "sh -c 'redis-cli SET k \"Authorization: <hidden>\" && echo done'",
    ),
}
# (a command written as one text, with `{pw}`, and the text shown): a header word there is
# read as in a shell text, so it is shown with `<hidden>` in the place of its value and of the
# words after it up to the end of its command.
ONE_TEXT_HEADERS: dict[str, tuple[str, str]] = {
    "memtier key prefix in one text": (
        f"memtier_benchmark --key-prefix auth: {PW} --ratio 1:1",
        "memtier_benchmark --key-prefix auth: <hidden>",
    ),
    "memtier key prefix glued in one text": (
        f"memtier_benchmark --key-prefix=auth: --ratio {PW}",
        "memtier_benchmark --key-prefix=auth: <hidden>",
    ),
    "redis-cli key in one text before an other command": (
        f"redis-cli SET auth: {PW} PX 100 && ./bench --quick",
        "redis-cli SET auth: <hidden> && ./bench --quick",
    ),
}


def typed(args: tuple[str, ...], password: str, user: str = USERS[0]) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password).replace(USER, user) for arg in args)


def shell_text(args: tuple[str, ...]) -> str:
    return " ".join(args)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(CREDENTIALS))
def test_the_user_of_memtier_credentials_is_shown(name: str, password: str) -> None:
    args, shown, in_shell = CREDENTIALS[name]
    for user in USERS:
        argv = typed(args, password, user)

        assert model.public_command((*LEAD, *argv)) == SHOWN_LEAD + shown.replace(USER, user)
        assert model.public_command(
            (*LEAD, "sh", "-c", shell_text(argv))
        ) == SHOWN_LEAD + in_shell.replace(USER, user)


@pytest.mark.parametrize("name", list(CREDENTIALS))
def test_the_hash_of_memtier_credentials_tells_users_apart_but_not_passwords(name: str) -> None:
    args, _, _ = CREDENTIALS[name]
    hashes = {
        user: [model.hashed_argv(typed(args, password, user)) for password in PASSWORDS]
        for user in USERS
    }
    texts = {
        user: [
            model.hashed_argv(("sh", "-c", shell_text(typed(args, password, user))))
            for password in PASSWORDS
        ]
        for user in USERS
    }

    for user in USERS:
        assert hashes[user][0] == hashes[user][1]
        assert texts[user][0] == texts[user][1]
        assert any(f"{user}:{model.HIDDEN}" in word for word in hashes[user][0])
    assert hashes[USERS[0]][0] != hashes[USERS[1]][0]
    assert texts[USERS[0]][0] != texts[USERS[1]][0]


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(WHOLE))
def test_a_memtier_password_alone_or_after_an_equals_sign_is_hidden_whole(
    name: str, password: str
) -> None:
    args, shown, in_shell = WHOLE[name]
    argv = typed(args, password)

    assert model.public_command((*LEAD, *argv)) == SHOWN_LEAD + shown
    assert model.public_command((*LEAD, "sh", "-c", shell_text(argv))) == SHOWN_LEAD + in_shell
    assert model.hashed_argv(argv) == model.hashed_argv(typed(args, PASSWORDS[0]))
    assert password not in " ".join(model.hashed_argv(argv))
    assert USERS[0] not in " ".join(model.hashed_argv(argv))


def test_a_long_option_after_memtier_a_is_no_value_of_it() -> None:
    args = ("memtier_benchmark", "-a", "--ratio", "1:1")

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + " ".join(args)
    assert model.hashed_argv(args) == list(args)


@pytest.mark.parametrize("name", list(KEYS))
def test_a_key_of_a_data_store_client_is_shown_as_typed(name: str) -> None:
    args = KEYS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + " ".join(args)
    assert model.hashed_argv(args) == list(args)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(HEADERS))
def test_the_same_word_as_a_header_is_hidden(name: str, password: str) -> None:
    args, shown = HEADERS[name]
    argv = typed(args, password)

    assert model.public_command((*LEAD, *argv)) == SHOWN_LEAD + shown
    assert model.hashed_argv(argv) == model.hashed_argv(typed(args, PASSWORDS[0]))
    assert password not in " ".join(model.hashed_argv(argv))


def test_a_lone_header_word_of_a_program_that_is_no_client_is_read_as_a_header() -> None:
    args, shown = NO_CLIENT

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shown


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(SHELL_HEADERS))
def test_a_header_word_in_a_shell_text_hides_the_rest_of_its_command(
    name: str, password: str
) -> None:
    text, shown = SHELL_HEADERS[name]

    assert model.public_command((*LEAD, "sh", "-c", text.replace(PW, password))) == (
        SHOWN_LEAD + shown
    )
    assert model.hashed_argv(("sh", "-c", text.replace(PW, password))) == model.hashed_argv(
        ("sh", "-c", text.replace(PW, PASSWORDS[0]))
    )


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ONE_TEXT_HEADERS))
def test_a_header_word_in_one_text_shows_that_the_rest_of_its_command_is_hidden(
    name: str, password: str
) -> None:
    text, shown = ONE_TEXT_HEADERS[name]

    assert model.public_words(text.replace(PW, password)) == shown
