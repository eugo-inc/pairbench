# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""hyperfine reads its glued texts wherever it starts a command in the words of a runner.

``ssh``, ``watch`` and ``parallel`` join their words with blanks into one command
that a shell runs, so a command starts there as in any shell text: at the first
word, after an operator (``&&``, ``;``, ``|``) or a ``(``, after the assignments
that lead it, after the options of ``env``, ``taskset``, ``numactl``, ``chrt``,
``stdbuf``, ``ionice``, ``time`` or ``sshpass``, and after the host of a nested
``ssh``. Where ``hyperfine`` starts such a command, the text glued to its
``--setup``, ``-s``, ``--prepare``, ``--cleanup`` or ``--conclude`` is read as the
command it is, so the password of a client there is hidden in the shown command,
in the hash and in the hash of a side whose words lead the workload, as it is
when ``hyperfine`` is the first word. An option of another program after a
separator is that program's own, and ordinary glued texts show as typed. Every
value is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model
from pairbench.model import HIDDEN, Side

# Two made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango42", "plum4grape19")
TYPED = "redis-cli -a {s} FLUSHALL"
HIDDEN_TEXT = f"redis-cli -a {HIDDEN} FLUSHALL"

# The runner's own words before its command, and its words after it.
RUNNERS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ssh": (("ssh", "made-up-host"), ()),
    "watch": (("watch",), ()),
    "parallel": (("parallel",), (":::", "1")),
}
# The words before hyperfine in the runner's command, and the words after the timed command.
LEADS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "env": (("env",), ()),
    "env with an assignment": (("env", "LC_ALL=C"), ()),
    "an assignment": (("LC_ALL=C",), ()),
    "taskset with a CPU list": (("taskset", "-c", "0"), ()),
    "taskset with a mask": (("taskset", "0x3"), ()),
    "numactl": (("numactl", "-C", "1"), ()),
    "chrt": (("chrt", "-f", "1"), ()),
    "stdbuf": (("stdbuf", "-oL"), ()),
    "ionice": (("ionice", "-c", "3"), ()),
    "time": (("time",), ()),
    "sshpass": (("sshpass", "-e"), ()),
    "cd and &&": (("cd", "made-up-dir", "&&"), ()),
    "cd and && in one word": (("cd made-up-dir &&",), ()),
    "a ;": (("true", ";"), ()),
    "a ; glued to a word": (("cd", "made-up-dir;"), ()),
    "a pipe": (("true", "|"), ()),
    "a ||": (("true", "||"), ()),
    "a subshell": (("(",), (")",)),
    "a nested ssh": (("ssh", "made-up-inner"), ()),
    "a nested ssh with an option": (("ssh", "-p", "2222", "made-up-inner"), ()),
    "a nested watch": (("watch",), ()),
    "taskset after a nested ssh": (("ssh", "made-up-inner", "taskset", "-c", "0"), ()),
}
# What glues the text to each option of hyperfine that runs a command.
GLUES = ("--setup=", "-s", "-s=", "-Ns", "--prepare=", "--cleanup=", "--conclude=")


def command(runner: str, lead: str, glued: str) -> list[str]:
    before, after = RUNNERS[runner]
    leads, closes = LEADS[lead]
    return [*before, *leads, "hyperfine", glued, "./bench-old", *closes, *after]


ROWS = [(glue, lead, runner) for glue in GLUES for lead in LEADS for runner in RUNNERS]


@pytest.mark.parametrize(("glue", "lead", "runner"), ROWS)
def test_a_glued_text_after_a_command_start_in_a_runner_s_words_hides_the_password(
    glue: str, lead: str, runner: str
) -> None:
    expected = command(runner, lead, f"{glue}'{HIDDEN_TEXT}'")
    for password in PASSWORDS:
        argv = command(runner, lead, f"{glue}'{TYPED.format(s=password)}'")
        shown = model.public_command(["pairbench", "run", "--", *argv])

        assert shown == "pairbench run -- " + shlex.join(expected)
        assert model.hashed_argv(argv) == expected


# Shell texts that hand hyperfine to a runner in words, behind a program that starts a command.
SHELL_TEXTS: dict[str, tuple[str, str]] = {
    "env": (
        "ssh made-up-host env hyperfine \"--setup='redis-cli -a {s} FLUSHALL'\" ./bench",
        f"ssh made-up-host env hyperfine \"--setup='redis-cli -a {HIDDEN} FLUSHALL'\" ./bench",
    ),
    "taskset": (
        "ssh made-up-host taskset -c 0 hyperfine \"--setup='redis-cli -a {s} FLUSHALL'\" ./bench",
        "ssh made-up-host taskset -c 0 hyperfine "
        f"\"--setup='redis-cli -a {HIDDEN} FLUSHALL'\" ./bench",
    ),
    "a separator": (
        "watch cd made-up-dir '&&' hyperfine \"-s'redis-cli -a {s} FLUSHALL'\" ./bench",
        f"watch cd made-up-dir '&&' hyperfine \"-s'redis-cli -a {HIDDEN} FLUSHALL'\" ./bench",
    ),
}


@pytest.mark.parametrize("text", sorted(SHELL_TEXTS))
def test_a_glued_text_in_a_runner_s_words_in_a_shell_text_hides_the_password(text: str) -> None:
    typed, hidden = SHELL_TEXTS[text]
    for password in PASSWORDS:
        argv = ["sh", "-c", typed.format(s=password)]

        assert model.hashed_argv(argv) == ["sh", "-c", hidden]
        assert model.public_command(argv) == shlex.join(["sh", "-c", hidden])


# Heads of a ``cmd`` side that lead the workload with a runner and a program in front of hyperfine.
HEADS: dict[str, list[str]] = {
    "taskset": ["ssh", "made-up-host", "taskset", "-c", "0", "hyperfine", "{workload}"],
    "env with an assignment": ["ssh", "made-up-host", "env", "LC_ALL=C", "hyperfine", "{workload}"],
    "a separator": ["watch", "cd", "made-up-dir", "&&", "hyperfine", "{workload}"],
}


@pytest.mark.parametrize("head", sorted(HEADS))
def test_a_glued_text_after_a_side_s_head_hides_the_password_in_the_side_s_hash(
    head: str,
) -> None:
    words = HEADS[head]
    hashed = []
    for password in PASSWORDS:
        workload = [f"--setup='{TYPED.format(s=password)}'", "./bench-old"]
        sides = [Side.command(name, words) for name in ("old", "new")]
        hashed.append(model.hashed_command(words, workload, model.hashed_workload(workload, sides)))

        assert [
            at for at in range(len(password) - 5) if password[at : at + 6] in json.dumps(hashed)
        ] == []
    assert hashed[0] == hashed[1] == [*words[:-1], f"--setup='{HIDDEN_TEXT}'", "./bench-old"]


# Ordinary commands in a runner's words: glued texts with nothing to hide, and the options of a
# program that a separator starts after hyperfine, which are that program's own.
ORDINARY: tuple[tuple[str, ...], ...] = (
    ("ssh", "made-up-host", "taskset", "-c", "0", "hyperfine", "--setup=make", "./bench"),
    ("ssh", "made-up-host", "env", "LC_ALL=C", "hyperfine", "-s'echo made up'", "./bench"),
    ("ssh", "made-up-host", "taskset", "-c", "0", "hyperfine", "-n", "made-up-name", "./bench"),
    ("ssh", "made-up-host", "taskset", "-c", "0", "hyperfine", "--export-json", "out.json", "x"),
    ("watch", "time", "hyperfine", "--prepare=sync", "./bench"),
    ("parallel", "cd", "made-up-dir", "&&", "hyperfine", "--cleanup=sync", "./bench", ":::", "1"),
    ("ssh", "made-up-host", "taskset", "-c", "0", "made-up-tool", "--setup=x", "./bench"),
    ("ssh", "made-up-host", "hyperfine", "./bench", ";", "ls", "--setup=x y"),
    ("ssh", "made-up-host", "./bench", "-c", "hyperfine", "-smake"),
    ("ssh", "made-up-host", "nice", "hyperfine", "--setup=make", "./bench"),
)


@pytest.mark.parametrize("argv", ORDINARY, ids=" ".join)
def test_an_ordinary_command_in_a_runner_s_words_shows_as_typed(argv: tuple[str, ...]) -> None:
    assert model.public_command(list(argv)) == shlex.join(argv)
    assert model.hashed_argv(list(argv)) == list(argv)
