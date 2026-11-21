# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The commands hyperfine runs around the ones it times hide a client's password, glued or not.

hyperfine runs the value of ``-s`` / ``--setup``, ``-p`` / ``--prepare``,
``-C`` / ``--conclude``, ``-c`` / ``--cleanup`` and ``--reference`` as a command,
in its shell or, after ``-N`` or ``--shell=none``, split into words. That value
may follow the option as the next word or be glued to it (``--setup=TEXT``,
``-sTEXT``, ``-NpTEXT`` or ``-SsTEXT`` after options that take no value in one
group, and ``-s=TEXT`` or ``-Ns=TEXT``, whose ``=`` hyperfine's parser takes off
the text), and it is read the same way each time: the first word names a
client, so the client's password option hides its value in the shown command
and in the hash, wherever the option stands and whatever the password. So it is
where hyperfine starts the command that ``ssh``, ``watch`` or ``parallel`` is
given in words of their own, whose shell takes the quotes off the glued text. An
ordinary glued option of hyperfine, and a command with nothing to hide, shows
as typed. Every value is made up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model
from pairbench.model import HIDDEN

# Two made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango42", "plum4grape19")

# Each option whose value is a command, and what glues a value to it.
GLUED: dict[str, str] = {
    "-s": "-s",
    "--setup": "--setup=",
    "-p": "-p",
    "--prepare": "--prepare=",
    "-C": "-C",
    "--conclude": "--conclude=",
    "-c": "-c",
    "--cleanup": "--cleanup=",
    "--reference": "--reference=",
}
# Each command, with ``{s}`` for the password, and the command as shown and hashed.
TEXTS: dict[str, tuple[str, str]] = {
    "redis-cli -a": ("redis-cli -a {s} FLUSHALL", f"redis-cli -a {HIDDEN} FLUSHALL"),
    "mysql -p": ("mysql -p{s} -e made-up-query", f"mysql -p{HIDDEN} -e made-up-query"),
    "an operator after it": (
        "redis-cli -a {s} FLUSHALL && true",
        f"redis-cli -a {HIDDEN} FLUSHALL && true",
    ),
}
# Each place of the option: the words before it and the words after it.
PLACES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "in a shell": (("hyperfine",), ("./bench-old",)),
    "after -N": (("hyperfine", "-N"), ("./bench-old",)),
    "after --shell=none": (("hyperfine", "--shell=none"), ("./bench-old",)),
    "after -i": (("hyperfine", "-i"), ("./bench-old",)),
    "after the commands": (("hyperfine", "./bench-old"), ()),
}


def glued(option: str, text: str, place: str) -> list[str]:
    before, after = PLACES[place]
    return [*before, GLUED[option] + text, *after]


def spaced(option: str, text: str, place: str) -> list[str]:
    before, after = PLACES[place]
    return [*before, option, text, *after]


ROWS = [
    (option, text, place) for option in sorted(GLUED) for text in sorted(TEXTS) for place in PLACES
]


@pytest.mark.parametrize(("option", "text", "place"), ROWS)
def test_a_glued_command_hides_the_password_of_its_client(
    option: str, text: str, place: str
) -> None:
    typed, hidden = TEXTS[text]
    expected = glued(option, hidden, place)
    for password in PASSWORDS:
        argv = glued(option, typed.replace("{s}", password), place)
        shown = model.public_command(["pairbench", "run", "--", *argv])

        assert shown == "pairbench run -- " + shlex.join(expected)
        assert model.hashed_argv(argv) == expected
        assert [at for at in range(len(password) - 5) if password[at : at + 6] in shown] == []


# The short options whose glued text hyperfine's parser also takes after an ``=``.
GLUED_WITH_EQUALS: dict[str, str] = {"-s": "-s=", "-p": "-p=", "-C": "-C=", "-c": "-c="}
EQUALS_ROWS = [
    (option, text, place)
    for option in sorted(GLUED_WITH_EQUALS)
    for text in sorted(TEXTS)
    for place in PLACES
]


@pytest.mark.parametrize(("option", "text", "place"), EQUALS_ROWS)
def test_a_command_glued_after_an_equals_sign_hides_the_password_of_its_client(
    option: str, text: str, place: str
) -> None:
    before, after = PLACES[place]
    typed, hidden = TEXTS[text]
    expected = [*before, GLUED_WITH_EQUALS[option] + hidden, *after]
    for password in PASSWORDS:
        argv = [*before, GLUED_WITH_EQUALS[option] + typed.replace("{s}", password), *after]
        shown = model.public_command(["pairbench", "run", "--", *argv])

        assert shown == "pairbench run -- " + shlex.join(expected)
        assert model.hashed_argv(argv) == expected
        assert [at for at in range(len(password) - 5) if password[at : at + 6] in shown] == []


@pytest.mark.parametrize(("option", "text", "place"), ROWS)
def test_a_glued_command_reads_as_the_same_command_written_apart(
    option: str, text: str, place: str
) -> None:
    typed, hidden = TEXTS[text]
    argv = spaced(option, typed.replace("{s}", PASSWORDS[0]), place)

    assert model.public_command(argv) == shlex.join(spaced(option, hidden, place))
    assert model.hashed_argv(argv) == spaced(option, hidden, place)


# The words before and after hyperfine's options where a runner of a command text gives
# hyperfine its options as words of their own: the remote command of ``ssh`` and the commands
# of ``watch`` and ``parallel``, which a shell runs once the runner joins their words.
RUNNERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ssh": (("ssh", "made-up-host", "hyperfine"), ("./bench-old",)),
    "ssh with an option": (("ssh", "-p", "2222", "made-up-host", "hyperfine"), ("./bench-old",)),
    "ssh after -N": (("ssh", "made-up-host", "hyperfine", "-N"), ("./bench-old",)),
    "watch": (("watch", "hyperfine"), ("./bench-old",)),
    "watch with an interval": (("watch", "-n", "5", "hyperfine"), ("./bench-old",)),
    "parallel": (("parallel", "hyperfine"), ("./bench-old", ":::", "1")),
}
# What glues a text to each option, with an ``=`` after a short one too.
RUNNER_GLUES = sorted({*GLUED.values(), *GLUED_WITH_EQUALS.values()})
RUNNER_ROWS = [
    (glue, text, runner) for glue in RUNNER_GLUES for text in sorted(TEXTS) for runner in RUNNERS
]


@pytest.mark.parametrize(("glue", "text", "runner"), RUNNER_ROWS)
def test_a_glued_command_in_the_words_of_a_runner_hides_the_password_of_its_client(
    glue: str, text: str, runner: str
) -> None:
    before, after = RUNNERS[runner]
    typed, hidden = TEXTS[text]
    expected = [*before, f"{glue}'{hidden}'", *after]
    for password in PASSWORDS:
        argv = [*before, f"{glue}'{typed.replace('{s}', password)}'", *after]
        shown = model.public_command(["pairbench", "run", "--", *argv])

        assert shown == "pairbench run -- " + shlex.join(expected)
        assert model.hashed_argv(argv) == expected
        assert [at for at in range(len(password) - 5) if password[at : at + 6] in shown] == []


def test_hyperfine_named_by_its_path_in_the_words_of_ssh_reads_its_glued_texts() -> None:
    for password in PASSWORDS:
        argv = [
            "ssh",
            "made-up-host",
            "/usr/bin/hyperfine",
            f"--setup='redis-cli -a {password} FLUSHALL'",
            "./bench",
        ]

        assert model.public_command(argv) == (
            "ssh made-up-host hyperfine "
            "'--setup='\"'\"'redis-cli -a <hidden> FLUSHALL'\"'\"'' ./bench"
        )
        assert model.hashed_argv(argv) == [
            "ssh",
            "made-up-host",
            "/usr/bin/hyperfine",
            "--setup='redis-cli -a <hidden> FLUSHALL'",
            "./bench",
        ]


# Rows written out whole, as hyperfine is typed in a workload, with the command as shown.
WRITTEN: dict[str, tuple[tuple[str, ...], str]] = {
    "--setup=": (
        ("hyperfine", "--setup=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '--setup=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "--prepare=": (
        ("hyperfine", "--prepare=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '--prepare=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "--cleanup=": (
        ("hyperfine", "--cleanup=mysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '--cleanup=mysql -p<hidden> -e made-up-query' ./bench",
    ),
    "--conclude=": (
        ("hyperfine", "--conclude=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '--conclude=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-s glued": (
        ("hyperfine", "-sredis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-sredis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-p glued": (
        ("hyperfine", "-predis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-predis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-c glued": (
        ("hyperfine", "-cmysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '-cmysql -p<hidden> -e made-up-query' ./bench",
    ),
    "--setup= after -N": (
        ("hyperfine", "-N", "--setup=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine -N '--setup=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-C glued in a shell text": (
        ("sh", "-c", "hyperfine '-Credis-cli -a kiwi7mango42 FLUSHALL' ./bench"),
        "sh -c 'hyperfine '\"'\"'-Credis-cli -a <hidden> FLUSHALL'\"'\"' ./bench'",
    ),
    "a credential assigned before the program": (
        ("hyperfine", "--setup=PGPASSWORD=kiwi7mango42 psql -h db.example", "./bench"),
        "hyperfine '--setup=PGPASSWORD=<hidden> psql -h db.example' ./bench",
    ),
    "--reference=": (
        ("hyperfine", "--reference=redis-cli -a kiwi7mango42 PING", "./bench"),
        "hyperfine '--reference=redis-cli -a <hidden> PING' ./bench",
    ),
    "-p glued after -N in one group": (
        ("hyperfine", "-Npredis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-Npredis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-s glued after -i and -N in one group": (
        ("hyperfine", "-iNsmysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '-iNsmysql -p<hidden> -e made-up-query' ./bench",
    ),
    "-C glued after -i in one group": (
        ("hyperfine", "-iCredis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-iCredis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-s= glued": (
        ("hyperfine", "-s=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-s=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-c= glued": (
        ("hyperfine", "-c=mysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '-c=mysql -p<hidden> -e made-up-query' ./bench",
    ),
    "-s= glued after -N in one group": (
        ("hyperfine", "-Ns=redis-cli -a kiwi7mango42 FLUSHALL", "./bench"),
        "hyperfine '-Ns=redis-cli -a <hidden> FLUSHALL' ./bench",
    ),
    "-p= glued after -i and -N in one group": (
        ("hyperfine", "-iNp=mysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '-iNp=mysql -p<hidden> -e made-up-query' ./bench",
    ),
    "-C= glued after the commands": (
        ("hyperfine", "./bench", "-C=redis-cli -a kiwi7mango42 FLUSHALL"),
        "hyperfine ./bench '-C=redis-cli -a <hidden> FLUSHALL'",
    ),
    "-s= glued in a shell text, its text in quotes": (
        ("sh", "-c", "hyperfine -s='redis-cli -a kiwi7mango42 FLUSHALL' ./bench"),
        "sh -c 'hyperfine -s='\"'\"'redis-cli -a <hidden> FLUSHALL'\"'\"' ./bench'",
    ),
    "-c glued after -N in one group in a shell text": (
        ("sh", "-c", "hyperfine '-Ncredis-cli -a kiwi7mango42 FLUSHALL' ./bench"),
        "sh -c 'hyperfine '\"'\"'-Ncredis-cli -a <hidden> FLUSHALL'\"'\"' ./bench'",
    ),
    "-s glued after -S in one group": (
        ("hyperfine", "-Ssredis-cli -a kiwi7mango42 PING", "./bench"),
        "hyperfine '-Ssredis-cli -a <hidden> PING' ./bench",
    ),
    "-s= glued after -S in one group": (
        ("hyperfine", "-Ss=redis-cli -a kiwi7mango42 PING", "./bench"),
        "hyperfine '-Ss=redis-cli -a <hidden> PING' ./bench",
    ),
    "-p glued after -S in one group": (
        ("hyperfine", "-Spmysql -pkiwi7mango42 -e made-up-query", "./bench"),
        "hyperfine '-Spmysql -p<hidden> -e made-up-query' ./bench",
    ),
    "-s glued after -i and -S in one group": (
        ("hyperfine", "-iSsredis-cli -a kiwi7mango42 PING", "./bench"),
        "hyperfine '-iSsredis-cli -a <hidden> PING' ./bench",
    ),
    "-s glued after -S and -i in one group": (
        ("hyperfine", "-Sisredis-cli -a kiwi7mango42 PING", "./bench"),
        "hyperfine '-Sisredis-cli -a <hidden> PING' ./bench",
    ),
    "-s glued after -S in one group in a shell text": (
        ("sh", "-c", "hyperfine '-Ssredis-cli -a kiwi7mango42 PING' ./bench"),
        "sh -c 'hyperfine '\"'\"'-Ssredis-cli -a <hidden> PING'\"'\"' ./bench'",
    ),
    "--setup= glued in the words of ssh in a shell text": (
        (
            "sh",
            "-c",
            "ssh made-up-host hyperfine --setup=\"'redis-cli -a kiwi7mango42 FLUSHALL'\" ./bench",
        ),
        "sh -c 'ssh made-up-host hyperfine --setup=\"'\"'\"'redis-cli -a <hidden> FLUSHALL'\"'\"'\""
        " ./bench'",
    ),
}


@pytest.mark.parametrize("name", sorted(WRITTEN))
def test_a_glued_command_written_out_is_shown_with_its_password_hidden(name: str) -> None:
    form, shown = WRITTEN[name]
    for password in PASSWORDS:
        argv = [word.replace(PASSWORDS[0], password) for word in form]

        assert model.public_command(argv) == shown
        assert model.hashed_argv(argv) == shlex.split(shown)


# hyperfine's ordinary options glued to their values, and commands with nothing to hide.
ORDINARY: tuple[tuple[str, ...], ...] = (
    ("hyperfine", "--runs=5", "./bench"),
    ("hyperfine", "-w3", "./bench"),
    ("hyperfine", "-m5", "-M10", "./bench"),
    ("hyperfine", "--shell=bash", "./bench"),
    ("hyperfine", "-Sbash", "./bench"),
    ("hyperfine", "--export-json=out.json", "./bench"),
    ("hyperfine", "--command-name=convert", "./bench"),
    ("hyperfine", "-nconvert", "./bench"),
    ("hyperfine", "--style=basic", "./bench"),
    ("hyperfine", "--sort=command", "./bench-old", "./bench-new"),
    ("hyperfine", "--setup=make clean", "./bench"),
    ("hyperfine", "-smake clean", "./bench"),
    ("hyperfine", "--prepare=sync", "./bench"),
    ("hyperfine", "-csync", "./bench"),
    ("hyperfine", "-Cecho done", "./bench"),
    ("hyperfine", "--setup", "make clean", "./bench"),
    ("hyperfine", "-P", "threads", "1", "8", "./bench -t {threads}"),
    ("hyperfine", "-Ni", "./bench"),
    ("hyperfine", "-iN", "--runs=5", "./bench"),
    ("hyperfine", "-Nm5", "./bench"),
    ("hyperfine", "-Nn", "convert", "./bench"),
    ("hyperfine", "-Npmake clean", "./bench"),
    ("hyperfine", "-iCecho done", "./bench"),
    ("hyperfine", "-s=make clean", "./bench"),
    ("hyperfine", "-Ns=echo done", "./bench"),
    ("hyperfine", "-s=", "./bench"),
    ("hyperfine", "-w=3", "./bench"),
    ("hyperfine", "-r=5", "-m=2", "./bench"),
    ("hyperfine", "-Snone", "./bench"),
    ("hyperfine", "-S", "none", "./bench"),
    ("hyperfine", "-S", "bash", "./bench"),
    ("hyperfine", "-Ssmake clean", "./bench"),
    ("hyperfine", "-Sn", "convert", "./bench"),
    ("ssh", "made-up-host", "hyperfine", "--setup=make", "./bench"),
    ("ssh", "made-up-host", "hyperfine", "-N", "--prepare=sync", "./bench"),
    ("watch", "hyperfine", "-smake", "./bench"),
    ("parallel", "hyperfine", "--cleanup=sync", "./bench", ":::", "1"),
    ("ssh", "made-up-host", "made-up-tool", "--setup=x", "./bench"),
)


@pytest.mark.parametrize("argv", ORDINARY, ids=" ".join)
def test_an_ordinary_option_of_hyperfine_shows_as_typed(argv: tuple[str, ...]) -> None:
    assert model.public_command(list(argv)) == shlex.join(argv)
    assert model.hashed_argv(list(argv)) == list(argv)
