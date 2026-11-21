# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a command that ``ssh``, ``watch`` or ``parallel`` joins as a limit.

``ssh`` joins the words after its host and hands them to a shell on the other machine, and
``watch`` and ``parallel`` hand their command to a shell the same way, while each of those words
is read as a text of its own. So a quote that one word opens and a later word closes is not read
as that shell reads it, nor is a client's command that one word with blanks starts and a later
word goes on, and the limit's examples show their password. The same command given as one word
is hidden, as the limit says.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A command that `ssh`, `watch` or `parallel` joins from its words.** `ssh` joins the words "
    "after its host with blanks and hands what it joined to a shell on the other machine, and "
    "`watch` and `parallel` hand their command to a shell the same way. Each of those words is "
    "read as a text of its own, so a quote that one word opens and a later word closes is not "
    "read as that shell reads it: "
    "`ssh made-up-host memtier_benchmark --command \\'AUTH password\\'` shows the password. Nor "
    "is a client's command that one word with blanks starts and a later word goes on: "
    "`ssh made-up-host 'redis-cli -a' password` and `watch 'redis-cli -a' password` show the "
    "password. Given as one word, as in "
    "`ssh made-up-host \"memtier_benchmark --command 'AUTH password'\"`, the password is hidden."
)
# The limit's examples, which show their password.
SHOWN = (
    "ssh made-up-host memtier_benchmark --command \\'AUTH password\\'",
    "ssh made-up-host 'redis-cli -a' password",
    "watch 'redis-cli -a' password",
)
# The same command given as one word, and as it is shown.
ONE_WORD = (
    "ssh made-up-host \"memtier_benchmark --command 'AUTH password'\"",
    "ssh made-up-host 'memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"''",
)
# The remote command given in parts that each hold their own quotes, which is hidden too.
IN_PARTS = (
    ("ssh", "made-up-host", "memtier_benchmark", "--command", "'AUTH password'"),
    ("ssh", "made-up-host", "memtier_benchmark", "--command", "'AUTH <hidden>'"),
)


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


@pytest.mark.parametrize("example", SHOWN)
def test_the_limit_s_example_shows_its_password(example: str) -> None:
    args = shlex.split(example)

    shown = model.public_command(args)

    assert shown is not None and "<hidden>" not in shown
    assert "password" in shown
    assert "password" in " ".join(model.hashed_argv(args))


@pytest.mark.parametrize(("typed", "shown"), [ONE_WORD])
def test_the_command_given_as_one_word_is_hidden(typed: str, shown: str) -> None:
    args = shlex.split(typed)

    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


def test_a_part_that_holds_its_own_quotes_is_hidden() -> None:
    typed, shown = IN_PARTS

    assert model.public_command(typed) == shlex.join(shown)
    assert model.hashed_argv(typed) == list(shown)
