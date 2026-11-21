# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A Redis name that starts with ``>`` or ``<`` in an argument list is the name the program gets.

No shell reads an argument list, so ``>made-up-user`` there is no redirection:
the client gets it as the user name of ``ACL SETUSER`` or ``HELLO ... AUTH``,
or as the name of a ``CONFIG SET`` setting, and the password after it is
hidden, in the shown command and in the hash, which is the same whatever the
password. The word may have been meant for a shell all the same, so the
password of either reading is hidden: such a word in the place of a name of
``CONFIG SET`` leaves the turn of names and values unknown, as a word a shell
may split does, and after such a user name of ``HELLO`` the word after the
password is hidden too; a redirection whose file is the next word stands for
no user there, and that file, the password as typed, is hidden. Where a shell
reads the words, as in the text after ``sh -c``, the word is a redirection and
is read as the shell reads it. Every value is made up; each password is a word
of small letters that no command writes by itself.
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


def typed(args: tuple[str, ...], password: str) -> tuple[str, ...]:
    return tuple(arg.replace(PW, password) for arg in args)


# (the arguments with `{pw}` where the password stands, the arguments as shown and hashed)
NAME_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "an acl user that starts with >": (
        ("redis-cli", "ACL", "SETUSER", ">made-up-user", f">{PW}"),
        ("redis-cli", "ACL", "SETUSER", ">made-up-user", f">{H}"),
    ),
    "an acl user that starts with <": (
        ("redis-cli", "ACL", "SETUSER", "<made-up-user", f">{PW}"),
        ("redis-cli", "ACL", "SETUSER", "<made-up-user", f">{H}"),
    ),
    "an acl user that starts with > on valkey": (
        ("valkey-cli", "ACL", "SETUSER", ">made-up-user", "on", f">{PW}"),
        ("valkey-cli", "ACL", "SETUSER", ">made-up-user", "on", f">{H}"),
    ),
    "a hello user that starts with >": (
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-user", PW),
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-user", H),
    ),
    "a hello user that starts with <": (
        ("redis-cli", "HELLO", "3", "AUTH", "<made-up-user", PW),
        ("redis-cli", "HELLO", "3", "AUTH", "<made-up-user", H),
    ),
    "a migrate user that starts with >": (
        ("redis-cli", "MIGRATE", "made-up-host", "6379", "", "0", "5000", "AUTH2", ">u", PW),
        ("redis-cli", "MIGRATE", "made-up-host", "6379", "", "0", "5000", "AUTH2", ">u", H),
    ),
    "a config setting name that starts with >": (
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "1", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "1", "requirepass", H),
    ),
    "a config setting name that starts with <": (
        ("redis-cli", "CONFIG", "SET", "<made-up-name", "1", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", "<made-up-name", "1", "requirepass", H),
    ),
    "a config word that starts with > before a secret name": (
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "requirepass", H),
    ),
    "an acl user that is a redirection standing alone": (
        ("redis-cli", "ACL", "SETUSER", ">", "made-up-file", f">{PW}"),
        ("redis-cli", "ACL", "SETUSER", ">", "made-up-file", f">{H}"),
    ),
    "a hello user with a word between it and the password": (
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-file", "zqmword", PW),
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-file", H, H),
    ),
    "a hello user that gives one descriptor to another": (
        ("redis-cli", "HELLO", "3", "AUTH", "2>&1", "zqmword", PW),
        ("redis-cli", "HELLO", "3", "AUTH", "2>&1", H, H),
    ),
    "a hello user that is a redirection standing alone": (
        ("redis-cli", "HELLO", "3", "AUTH", ">", "zqmword", "made-up-user", PW),
        ("redis-cli", "HELLO", "3", "AUTH", ">", H, "made-up-user", H),
    ),
    "a config setting name that gives one descriptor to another": (
        ("redis-cli", "CONFIG", "SET", "2>&1", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", "2>&1", "requirepass", H),
    ),
    "a server acl user that starts with >": (
        ("redis-server", "--user", ">made-up-user", f">{PW}"),
        ("redis-server", "--user", ">made-up-user", f">{H}"),
    ),
    "a sentinel master that starts with >": (
        ("redis-server", "--sentinel", "auth-pass", ">made-up-master", PW),
        ("redis-server", "--sentinel", "auth-pass", ">made-up-master", H),
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(NAME_FORMS))
def test_a_name_that_looks_like_a_redirection_keeps_the_password_after_it_hidden(
    name: str, password: str
) -> None:
    args, shown = NAME_FORMS[name]
    argv = typed(args, password)

    assert model.public_command((*LEAD, *argv)) == SHOWN_LEAD + shlex.join(shown)
    assert model.hashed_argv(argv) == list(shown)


@pytest.mark.parametrize("name", list(NAME_FORMS))
def test_the_hash_of_such_a_name_form_is_the_same_whatever_its_password(name: str) -> None:
    args, _shown = NAME_FORMS[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)

    assert first == second
    assert not any(password in arg for password in PASSWORDS for arg in first)


# (the arguments, as shown and hashed): no password, or a redirection that a shell reads or
# that stands alone, each shown and hashed as listed.
KEPT_FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "acl rules with no password after a user that starts with >": (
        ("redis-cli", "ACL", "SETUSER", ">made-up-user", "on", "+@all"),
        ("redis-cli", "ACL", "SETUSER", ">made-up-user", "on", "+@all"),
    ),
    "an ordinary config setting after a name that starts with >": (
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "1", "maxmemory", "100mb"),
        ("redis-cli", "CONFIG", "SET", ">made-up-name", "1", "maxmemory", "100mb"),
    ),
    "a hello option after the password of a user that starts with >": (
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-user", "zqmkiwi", "SETNAME", "made-up-name"),
        ("redis-cli", "HELLO", "3", "AUTH", ">made-up-user", H, H, "made-up-name"),
    ),
    "a redirection with its file before the client's command": (
        ("redis-cli", "-n", "1", ">out", "AUTH", "zqmkiwi"),
        ("redis-cli", "-n", "1", ">out", "AUTH", H),
    ),
    "a hello user read by a shell after a redirection": (
        ("sh", "-c", "redis-cli HELLO 3 AUTH >out made-up-user zqmkiwi"),
        ("sh", "-c", f"redis-cli HELLO 3 AUTH >out made-up-user {H}"),
    ),
    "a config setting read by a shell after a redirection": (
        ("sh", "-c", "redis-cli CONFIG SET >out requirepass zqmkiwi"),
        ("sh", "-c", f"redis-cli CONFIG SET >out requirepass {H}"),
    ),
}


@pytest.mark.parametrize("name", list(KEPT_FORMS))
def test_other_redirection_forms_show_and_hash_as_listed(name: str) -> None:
    args, shown = KEPT_FORMS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(shown)
    assert model.hashed_argv(args) == list(shown)
