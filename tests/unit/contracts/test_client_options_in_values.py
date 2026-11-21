# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A value that a later client reads is read with that client's options.

An ordinary name's value read before the program word names a client
(``env 'MADE_UP_FLAGS=-a VALUE' redis-benchmark``, ``REDIS_ARGS="-a VALUE"
redis-benchmark $REDIS_ARGS`` in a shell text, ``MADE_UP_FLAGS="-pVALUE"
mysql``) is read with the options of the client that a later word of the same
command names: its password option hides the password, spaced or glued, in the
shown command and in every published hash alike, and the words after it stay.
A value before a program that is no client, or before a client of another
command (after ``;``, ``|`` or a line break), is read as it stands.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench.model import hashed_argv, public_command, public_words

# Made-up passwords.
SECRET = "kiwi7zq"
OTHER = "plum4zq"
BENCH = "./made-up-bench"

# Each row: an argument list with ``VALUE`` where the password stands, the command the shared
# files show, and the list every published hash reads.
HIDDEN = {
    "env-spaced": (
        ["env", "MADE_UP_FLAGS=-a VALUE", "redis-benchmark"],
        "env 'MADE_UP_FLAGS=-a <hidden>' redis-benchmark",
        ["env", "MADE_UP_FLAGS=-a <hidden>", "redis-benchmark"],
    ),
    "env-spaced-later-words": (
        ["env", "MADE_UP_FLAGS=-a VALUE -n 8", "redis-benchmark", "-q"],
        "env 'MADE_UP_FLAGS=-a <hidden> -n 8' redis-benchmark -q",
        ["env", "MADE_UP_FLAGS=-a <hidden> -n 8", "redis-benchmark", "-q"],
    ),
    "env-glued-mysql": (
        ["env", "MADE_UP_FLAGS=-pVALUE", "mysql"],
        "env 'MADE_UP_FLAGS=-p<hidden>' mysql",
        ["env", "MADE_UP_FLAGS=-p<hidden>", "mysql"],
    ),
    "env-glued-mysql-later-words": (
        ["env", "MADE_UP_FLAGS=-pVALUE --port 3307", "mysql"],
        "env 'MADE_UP_FLAGS=-p<hidden> --port 3307' mysql",
        ["env", "MADE_UP_FLAGS=-p<hidden> --port 3307", "mysql"],
    ),
    "env-glued-redis": (
        ["env", "MADE_UP_FLAGS=-aVALUE", "redis-cli", "ping"],
        "env 'MADE_UP_FLAGS=-a<hidden>' redis-cli ping",
        ["env", "MADE_UP_FLAGS=-a<hidden>", "redis-cli", "ping"],
    ),
    "env-two-names": (
        ["env", "MADE_UP_FLAGS=-a VALUE", "MADE_UP_MODE=fast", "redis-benchmark"],
        "env 'MADE_UP_FLAGS=-a <hidden>' MADE_UP_MODE=fast redis-benchmark",
        ["env", "MADE_UP_FLAGS=-a <hidden>", "MADE_UP_MODE=fast", "redis-benchmark"],
    ),
    "client-after-a-path": (
        ["env", "MADE_UP_FLAGS=-pVALUE", "/made/up/bin/mysql"],
        "env 'MADE_UP_FLAGS=-p<hidden>' mysql",
        ["env", "MADE_UP_FLAGS=-p<hidden>", "/made/up/bin/mysql"],
    ),
    "docker-e": (
        ["docker", "run", "-e", "REDIS_ARGS=-a VALUE", "made-up/image", "redis-benchmark"],
        "docker run -e 'REDIS_ARGS=-a <hidden>' made-up/image redis-benchmark",
        ["docker", "run", "-e", "REDIS_ARGS=-a <hidden>", "made-up/image", "redis-benchmark"],
    ),
    "docker-env-glued": (
        ["docker", "run", "--env=REDIS_ARGS=-a VALUE", "made-up/image", "redis-benchmark"],
        "docker run '--env=REDIS_ARGS=-a <hidden>' made-up/image redis-benchmark",
        ["docker", "run", "--env=REDIS_ARGS=-a <hidden>", "made-up/image", "redis-benchmark"],
    ),
}


def _with(argv: list[str], value: str) -> list[str]:
    return [word.replace("VALUE", value) for word in argv]


@pytest.mark.parametrize(("argv", "shown", "hashed"), list(HIDDEN.values()), ids=list(HIDDEN))
def test_a_password_option_a_later_client_reads_is_hidden(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    for value in (SECRET, OTHER):
        assert public_command(_with(argv, value)) == shown
        assert hashed_argv(_with(argv, value)) == hashed


# Each row: a shell text with ``VALUE`` where the password stands, the text as the shared
# files show it and every published hash reads it, and the words ``public_words`` shows, joined
# by single spaces.
TEXTS = {
    "quoted-spaced": (
        'REDIS_ARGS="-a VALUE" redis-benchmark $REDIS_ARGS -n 8',
        'REDIS_ARGS="-a <hidden>" redis-benchmark $REDIS_ARGS -n 8',
        "REDIS_ARGS=-a <hidden> redis-benchmark $REDIS_ARGS -n 8",
    ),
    "double-quoted-glued": (
        'MADE_UP_FLAGS="-pVALUE" mysql',
        'MADE_UP_FLAGS="-p<hidden>" mysql',
        "MADE_UP_FLAGS=-p<hidden> mysql",
    ),
    "single-quoted-glued": (
        "MADE_UP_FLAGS='-pVALUE' mysql",
        "MADE_UP_FLAGS='-p<hidden>' mysql",
        "MADE_UP_FLAGS=-p<hidden> mysql",
    ),
    "unquoted-glued": (
        "MADE_UP_FLAGS=-pVALUE mysql",
        "MADE_UP_FLAGS=-p<hidden> mysql",
        "MADE_UP_FLAGS=-p<hidden> mysql",
    ),
    "env-quoted-whole": (
        "env 'MADE_UP_FLAGS=-a VALUE' redis-benchmark",
        "env 'MADE_UP_FLAGS=-a <hidden>' redis-benchmark",
        "env MADE_UP_FLAGS=-a <hidden> redis-benchmark",
    ),
    "after-an-earlier-command": (
        'true && REDIS_ARGS="-a VALUE" redis-cli $REDIS_ARGS ping',
        'true && REDIS_ARGS="-a <hidden>" redis-cli $REDIS_ARGS ping',
        "true && REDIS_ARGS=-a <hidden> redis-cli $REDIS_ARGS ping",
    ),
}


@pytest.mark.parametrize(("text", "shown", "words"), list(TEXTS.values()), ids=list(TEXTS))
def test_a_password_option_a_later_client_reads_in_a_shell_text_is_hidden(
    text: str, shown: str, words: str
) -> None:
    for value in (SECRET, OTHER):
        typed = text.replace("VALUE", value)
        assert public_command(["sh", "-c", typed]) == shlex.join(["sh", "-c", shown])
        assert hashed_argv(["sh", "-c", typed]) == ["sh", "-c", shown]
        assert public_words(typed) == words


def test_the_words_after_the_password_still_tell_two_sides_apart() -> None:
    one = ["env", f"MADE_UP_FLAGS=-a {SECRET} -n 8", "redis-benchmark"]
    two = ["env", f"MADE_UP_FLAGS=-a {SECRET} -n 16", "redis-benchmark"]
    assert hashed_argv(one) != hashed_argv(two)
    text = 'REDIS_ARGS="-a {s} -n {n}" redis-benchmark $REDIS_ARGS'
    assert hashed_argv(["sh", "-c", text.format(s=SECRET, n=8)]) != hashed_argv(
        ["sh", "-c", text.format(s=SECRET, n=16)]
    )


# Each row: an argument list read as it stands, where no client of the same command reads
# the value: a program that is no client, a client of the next or of an earlier command, and
# an option the client reads as no password.
SHOWN = {
    "no-client": ["env", "MADE_UP_FLAGS=-a VALUE", BENCH],
    "no-client-glued": ["env", "MADE_UP_FLAGS=-pVALUE", BENCH],
    "client-of-the-next-command": ["env", "MADE_UP_FLAGS=-a VALUE", BENCH, ";", "redis-cli"],
    "mysql-spaced-p": ["env", "MADE_UP_FLAGS=-p VALUE", "mysql"],
    "a-command-text-of-its-own": [
        "hyperfine",
        "MADE_UP_FLAGS='-a VALUE' ./made-up-bench",
        "redis-benchmark",
    ],
    "an-option-the-client-takes-no-password-with": [
        "env",
        "MADE_UP_FLAGS=-n VALUE",
        "redis-benchmark",
    ],
}


@pytest.mark.parametrize("argv", list(SHOWN.values()), ids=list(SHOWN))
def test_a_value_no_later_client_reads_as_a_password_is_shown(argv: list[str]) -> None:
    typed = _with(argv, SECRET)
    assert public_command(typed) == shlex.join(typed)
    assert hashed_argv(typed) == typed
    assert hashed_argv(typed) != hashed_argv(_with(argv, OTHER))


SHOWN_TEXTS = {
    "client-after-a-semicolon": "MADE_UP_FLAGS='-a VALUE' ./made-up-bench; redis-cli ping",
    "client-after-a-pipe": "MADE_UP_FLAGS='-a VALUE' ./made-up-bench | redis-cli ping",
    "client-after-and": "MADE_UP_FLAGS='-a VALUE' ./made-up-bench && redis-cli ping",
    "client-before": "redis-cli ping; MADE_UP_FLAGS='-a VALUE' ./made-up-bench",
    "client-on-the-next-line": "MADE_UP_FLAGS='-a VALUE' ./made-up-bench\nredis-cli ping",
}


@pytest.mark.parametrize("text", list(SHOWN_TEXTS.values()), ids=list(SHOWN_TEXTS))
def test_a_value_before_a_client_of_another_command_is_shown(text: str) -> None:
    typed = text.replace("VALUE", SECRET)
    assert public_command(["sh", "-c", typed]) == shlex.join(["sh", "-c", typed])
    assert hashed_argv(["sh", "-c", typed]) == ["sh", "-c", typed]
    assert hashed_argv(["sh", "-c", typed]) != hashed_argv(
        ["sh", "-c", text.replace("VALUE", OTHER)]
    )


# Each row: a page, a command it gives as typed with ``VALUE`` where the password stands, and
# what the page says the shared files show of it.
PAGE_EXAMPLES = (
    (
        "docs/reference/config.md",
        ["env", "MADE_UP_FLAGS=-a VALUE -n 8", "redis-benchmark"],
        "`env 'MADE_UP_FLAGS=-a <hidden> -n 8' redis-benchmark`",
    ),
    (
        "docs/reference/config.md",
        ["sh", "-c", 'REDIS_ARGS="-a VALUE" redis-benchmark $REDIS_ARGS'],
        "`sh -c 'REDIS_ARGS=\"-a <hidden>\" redis-benchmark $REDIS_ARGS'`",
    ),
    (
        "docs/reference/config.md",
        ["sh", "-c", "MADE_UP_FLAGS=-pVALUE mysql"],
        "`MADE_UP_FLAGS=-p<hidden> mysql`",
    ),
)
# Each row: a form the security policy lists as a known limit, with ``password`` where the
# password stands, and the argument list that runs it.
LIMIT_EXAMPLES = (
    (
        "`REDIS_ARGS='-a password'; redis-benchmark $REDIS_ARGS`",
        ["sh", "-c", "REDIS_ARGS='-a password'; redis-benchmark $REDIS_ARGS"],
    ),
    (
        "`env 'REDIS_ARGS=-a password' ./run-redis.sh`",
        ["env", "REDIS_ARGS=-a password", "./run-redis.sh"],
    ),
    (
        "`CMD='AUTH password'; memtier_benchmark --command \"$CMD\"`",
        ["sh", "-c", "CMD='AUTH password'; memtier_benchmark --command \"$CMD\""],
    ),
)
LIMIT_TITLE = "**A client's option in a variable another command reads.**"


def _plain(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.mark.parametrize(("page", "argv", "shown"), PAGE_EXAMPLES)
def test_the_config_reference_shows_what_the_shared_files_show(
    repo_root: Path, page: str, argv: list[str], shown: str
) -> None:
    assert shown in _plain(repo_root / page)
    words = shown.strip("`")
    for value in (SECRET, OTHER):
        typed = _with(argv, value)
        got = public_command(typed)
        assert got is not None
        assert words in got
        assert value not in got


@pytest.mark.parametrize(("words", "argv"), LIMIT_EXAMPLES)
def test_the_security_policy_lists_a_form_that_still_shows_its_password(
    repo_root: Path, words: str, argv: list[str]
) -> None:
    section = _plain(repo_root / "SECURITY.md").split("## Known limits of the shown command", 1)[1]
    section = section.split(" ## ", 1)[0]
    assert LIMIT_TITLE in section
    assert words in section
    typed = [word.replace("password", SECRET) for word in argv]
    assert public_command(typed) == shlex.join(typed)
    assert hashed_argv(typed) == typed
