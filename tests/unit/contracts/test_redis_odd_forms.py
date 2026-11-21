# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Less common ways of writing a Redis or Valkey password, as the shown command hides them.

After ``AUTH``, a word followed by a word that reads as an option (``--raw``,
``-e``), or a redirection or a comment given as an argument (``'>out.log'``,
``'2>&1'``, ``'#'``), is the password: the client is passed that next word as
the password, so it is hidden too unless it is a long option. ``--askpass`` is a switch, and
``--show-pushes``, ``-X``, ``--lru-test``, ``--cursor`` and ``--top`` take a
value, so the command after them starts where the client starts it. The rules
of ``ACL SETUSER`` written as one quoted word lose all after the first rule that
gives a password, and a name and value of ``CONFIG SET`` written as one word
lose the value. Each password is hidden
in the shown command, inside ``sh -c`` and in the hash, which is the same
whatever the password. Every value is made up; each password is a word of
small letters that no command writes by itself.
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


# (the arguments with `{pw}` where the password stands, the arguments shown, the text of those
# arguments after `sh -c` as shown)
FORMS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "a redirection given as an argument after the password": (
        ("redis-cli", "AUTH", PW, ">out.log"),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "a descriptor redirection given as an argument": (
        ("redis-cli", "AUTH", PW, "2>&1"),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "an input redirection given as an argument": (
        ("valkey-cli", "AUTH", PW, "<made-up.txt"),
        ("valkey-cli", "AUTH", H, H),
        f"valkey-cli AUTH {H} {H}",
    ),
    "a long option after the password": (
        ("redis-cli", "AUTH", PW, "--raw"),
        ("redis-cli", "AUTH", H, "--raw"),
        f"redis-cli AUTH {H} --raw",
    ),
    "a short option after the password": (
        ("redis-cli", "AUTH", PW, "-e"),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "a password that starts with a dash after a user name": (
        ("redis-cli", "AUTH", "made-up-user", "-" + PW),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "a password that starts like a redirection after a user name": (
        ("redis-cli", "AUTH", "made-up-user", ">" + PW),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "a comment sign given as an argument after the password": (
        ("redis-cli", "AUTH", PW, "#", "log", "in"),
        ("redis-cli", "AUTH", H, H, "log", "in"),
        f"redis-cli AUTH {H} {H} log in",
    ),
    "a comment given as one argument after the password": (
        ("valkey-cli", "AUTH", PW, "#log"),
        ("valkey-cli", "AUTH", H, H),
        f"valkey-cli AUTH {H} {H}",
    ),
    "a password that starts with a comment sign after a user name": (
        ("redis-cli", "AUTH", "made-up-user", "#" + PW),
        ("redis-cli", "AUTH", H, H),
        f"redis-cli AUTH {H} {H}",
    ),
    "askpass before the command": (
        ("redis-cli", "--askpass", "AUTH", PW),
        ("redis-cli", "--askpass", "AUTH", H),
        f"redis-cli --askpass AUTH {H}",
    ),
    "askpass of the cluster manager before the command": (
        ("redis-cli", "--cluster-from-askpass", "AUTH", PW),
        ("redis-cli", "--cluster-from-askpass", "AUTH", H),
        f"redis-cli --cluster-from-askpass AUTH {H}",
    ),
    "show-pushes": (
        ("redis-cli", "--show-pushes", "yes", "AUTH", PW),
        ("redis-cli", "--show-pushes", "yes", "AUTH", H),
        f"redis-cli --show-pushes yes AUTH {H}",
    ),
    "the tag of the last argument read from the input": (
        ("redis-cli", "-X", "made-up-tag", "AUTH", PW),
        ("redis-cli", "-X", "made-up-tag", "AUTH", H),
        f"redis-cli -X made-up-tag AUTH {H}",
    ),
    "lru-test": (
        ("redis-cli", "--lru-test", "100", "AUTH", PW),
        ("redis-cli", "--lru-test", "100", "AUTH", H),
        f"redis-cli --lru-test 100 AUTH {H}",
    ),
    "cursor": (
        ("redis-cli", "--cursor", "0", "AUTH", PW),
        ("redis-cli", "--cursor", "0", "AUTH", H),
        f"redis-cli --cursor 0 AUTH {H}",
    ),
    "top": (
        ("redis-cli", "--top", "5", "AUTH", PW),
        ("redis-cli", "--top", "5", "AUTH", H),
        f"redis-cli --top 5 AUTH {H}",
    ),
    "show-pushes of valkey-cli": (
        ("valkey-cli", "--show-pushes", "no", "AUTH", PW),
        ("valkey-cli", "--show-pushes", "no", "AUTH", H),
        f"valkey-cli --show-pushes no AUTH {H}",
    ),
    "acl rules in one word": (
        ("redis-cli", "ACL", "SETUSER", "made-up-user", f"on >{PW} ~* +@all"),
        ("redis-cli", "ACL", "SETUSER", "made-up-user", f"on >{H}"),
        f"redis-cli ACL SETUSER made-up-user 'on >{H}'",
    ),
    "acl rules in one word with a hash and a removal": (
        ("redis-cli", "ACL", "SETUSER", "made-up-user", f"on #{PW} <{PW} +@all"),
        ("redis-cli", "ACL", "SETUSER", "made-up-user", f"on #{H}"),
        f"redis-cli ACL SETUSER made-up-user 'on #{H}'",
    ),
    "a config setting and its value in one word": (
        ("redis-cli", "CONFIG", "SET", f"requirepass {PW}"),
        ("redis-cli", "CONFIG", "SET", f"requirepass {H}"),
        f"redis-cli CONFIG SET 'requirepass {H}'",
    ),
    "a second config setting and its value in one word": (
        ("valkey-cli", "config", "set", "maxmemory", "100mb", f"masterauth {PW}"),
        ("valkey-cli", "config", "set", "maxmemory", "100mb", f"masterauth {H}"),
        f"valkey-cli config set maxmemory 100mb 'masterauth {H}'",
    ),
    "a config setting in one word before a password setting": (
        ("redis-cli", "CONFIG", "SET", f"requirepass {PW}", "masterauth", PW),
        ("redis-cli", "CONFIG", "SET", f"requirepass {H}", "masterauth", H),
        f"redis-cli CONFIG SET 'requirepass {H}' masterauth {H}",
    ),
    "an ordinary config setting in one word before a password setting": (
        ("redis-cli", "CONFIG", "SET", "maxmemory 100mb", "requirepass", PW),
        ("redis-cli", "CONFIG", "SET", "maxmemory 100mb", "requirepass", H),
        f"redis-cli CONFIG SET 'maxmemory 100mb' requirepass {H}",
    ),
}
# The one text of each form whose words show apart from its quotes, as `public_words` shows it.
# A redirection quoted in the text is an argument, as in the argument list.
ONE_TEXT: dict[str, str] = {
    "a redirection given as an argument after the password": f"redis-cli AUTH {H} {H}",
    "a descriptor redirection given as an argument": f"redis-cli AUTH {H} {H}",
    "an input redirection given as an argument": f"valkey-cli AUTH {H} {H}",
    "a password that starts like a redirection after a user name": f"redis-cli AUTH {H} {H}",
    "a comment sign given as an argument after the password": f"redis-cli AUTH {H} {H} log in",
    "a comment given as one argument after the password": f"valkey-cli AUTH {H} {H}",
    "a password that starts with a comment sign after a user name": f"redis-cli AUTH {H} {H}",
    "a long option after the password": f"redis-cli AUTH {H} --raw",
    "a short option after the password": f"redis-cli AUTH {H} {H}",
    "a password that starts with a dash after a user name": f"redis-cli AUTH {H} {H}",
    "askpass before the command": f"redis-cli --askpass AUTH {H}",
    "show-pushes": f"redis-cli --show-pushes yes AUTH {H}",
    "the tag of the last argument read from the input": f"redis-cli -X made-up-tag AUTH {H}",
    "lru-test": f"redis-cli --lru-test 100 AUTH {H}",
    "cursor": f"redis-cli --cursor 0 AUTH {H}",
    "top": f"redis-cli --top 5 AUTH {H}",
    "acl rules in one word": f"redis-cli ACL SETUSER made-up-user on >{H}",
    "a config setting and its value in one word": f"redis-cli CONFIG SET requirepass {H}",
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_an_odd_form_of_a_password_is_hidden_in_the_shown_command(name: str, password: str) -> None:
    args, shown, _text = FORMS[name]

    assert model.public_command((*LEAD, *typed(args, password))) == SHOWN_LEAD + shlex.join(shown)


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(FORMS))
def test_an_odd_form_of_a_password_is_hidden_inside_sh_c(name: str, password: str) -> None:
    args, _shown, text = FORMS[name]
    typed_text = shlex.join(typed(args, password))

    assert model.public_command((*LEAD, "sh", "-c", typed_text + " && echo done")) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", text + " && echo done"])
    )


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(ONE_TEXT))
def test_an_odd_form_of_a_password_is_hidden_in_one_text(name: str, password: str) -> None:
    args, _shown, _text = FORMS[name]

    assert model.public_words(shlex.join(typed(args, password))) == ONE_TEXT[name]


# (a text with `{pw}`, as `public_words` shows it): a redirection written bare is read as the
# shell reads it, and the file it names shows; escaped, it is an argument.
REDIRECTED_TEXTS: dict[str, tuple[str, str]] = {
    "a bare redirection after the password": (
        f"redis-cli AUTH {PW} >out.log",
        f"redis-cli AUTH {H} >out.log",
    ),
    "a bare descriptor redirection after the password": (
        f"redis-cli AUTH {PW} 2>&1",
        f"redis-cli AUTH {H} 2>&1",
    ),
    "an escaped redirection sign before the password": (
        f"redis-cli AUTH made-up-user \\>{PW}",
        f"redis-cli AUTH made-up-user {H}",
    ),
}


@pytest.mark.parametrize("password", PASSWORDS)
@pytest.mark.parametrize("name", list(REDIRECTED_TEXTS))
def test_a_redirection_in_one_text_is_read_as_the_shell_reads_it(name: str, password: str) -> None:
    text, shown = REDIRECTED_TEXTS[name]

    assert model.public_words(text.replace(PW, password)) == shown


@pytest.mark.parametrize("name", list(FORMS))
def test_the_hash_of_an_odd_form_is_the_same_whatever_its_password(name: str) -> None:
    args, _shown, _text = FORMS[name]
    first, second = (model.hashed_argv(typed(args, password)) for password in PASSWORDS)
    texts = [
        model.hashed_argv(("sh", "-c", shlex.join(typed(args, password)) + "; true"))
        for password in PASSWORDS
    ]

    assert first == second
    assert texts[0] == texts[1]
    assert not any(password in arg for password in PASSWORDS for arg in (*first, *texts[0]))


# Commands with no password, each shown as typed.
SHOWN_FORMS: dict[str, tuple[str, ...]] = {
    "askpass alone": ("redis-cli", "--askpass", "PING"),
    "a value of show-pushes before a command": (
        "redis-cli",
        "--show-pushes",
        "yes",
        "GET",
        "made-up-key",
    ),
    "an option after a command other than auth": (
        "redis-cli",
        "GET",
        "made-up-key",
        "--raw",
    ),
    "a redirection given as an argument after a command other than auth": (
        "redis-cli",
        "ECHO",
        "made-up-word",
        ">out.log",
    ),
    "a comment sign given as an argument after a command other than auth": (
        "redis-cli",
        "ECHO",
        "made-up-word",
        "#",
        "made-up-note",
    ),
    "acl rules in one word with no password": (
        "redis-cli",
        "ACL",
        "SETUSER",
        "made-up-user",
        "on ~* +@all",
    ),
    "an ordinary config setting and its value in one word": (
        "redis-cli",
        "CONFIG",
        "SET",
        "maxmemory 100mb",
    ),
    "a config value in one word after a name": (
        "redis-cli",
        "CONFIG",
        "SET",
        "save",
        "900 1",
    ),
}


@pytest.mark.parametrize("name", list(SHOWN_FORMS))
def test_a_command_with_no_password_is_shown_as_typed(name: str) -> None:
    args = SHOWN_FORMS[name]

    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(args)
    assert model.public_words(shlex.join(args)) == " ".join(args)
