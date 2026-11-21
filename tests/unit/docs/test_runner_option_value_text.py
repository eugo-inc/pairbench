# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists an option of ``parallel`` or ``watch`` given its value apart.

In the words of ``parallel``, and of ``watch`` but for ``-n`` and ``--interval``, an option is
read as one word, so the value of an option written in the next word is read as the first word
of the command, ``hyperfine`` after it starts no command, and a client's password in a text
glued to one of its text options shows and is in the hash. With ``--`` after the option the
shown command hides it and the hash keeps it; glued to its value, or with the text as a word of
its own, the option leaves it hidden in both. The security policy lists it among the known
limits of the shown command, and the config reference says so where it lists the texts read
after ``hyperfine`` in those words.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**An option of `parallel` or `watch` given its value in the next word.** In the words of "
    "`parallel`, and of `watch` but for `-n` and `--interval`, an option is read as one word, so "
    "the value of an option written in the next word, as in `parallel -j 2` or `watch -q 3`, is "
    "read as the first word of the command. `hyperfine` after it starts no command, and a text "
    "glued to its `-s`, `-p`, `-c`, `-C`, `--setup`, `--prepare`, `--cleanup`, `--conclude` or "
    "`--reference` is read as any argument is, so a client's password in that text shows and is "
    "in the hash: "
    "`parallel -j 2 hyperfine \"--setup='redis-cli -a password FLUSHALL'\" ./bench ::: 1` and "
    "`watch -q 3 hyperfine \"--setup='redis-cli -a password FLUSHALL'\" ./bench` show the "
    "password. With `--` after such an option, as in "
    "`parallel -j 2 -- hyperfine \"--setup='redis-cli -a password FLUSHALL'\" ./bench ::: 1`, the "
    "shown command hides the password and the hash takes it as typed. Written as `-j2` or "
    "`--jobs=2`, or with the text as a word of its own after `--setup`, the password is hidden in "
    "both."
)
ADVICE = "Write an option of `parallel` or `watch` glued to its value (`-j2`, `--jobs=2`)."
POINTER = (
    "An option of `parallel`, or of `watch` but for `-n` and `--interval`, is read as one word, "
    "so the word after an option given its value in the next word (`parallel -j 2`) is read as "
    "the command, as the [known limits](../../SECURITY.md#known-limits-of-the-shown-command) "
    "say; glue such an option to its value (`parallel -j2`)."
)
TEXT = "'redis-cli -a password FLUSHALL'"
# The limit's examples, which show their password and keep it in the hash.
SHOWN = (
    f'parallel -j 2 hyperfine "--setup={TEXT}" ./bench ::: 1',
    f'watch -q 3 hyperfine "--setup={TEXT}" ./bench',
    f'watch --equexit 3 hyperfine "--setup={TEXT}" ./bench',
)
# Each text option of hyperfine the limit names, glued to its text after `parallel -j 2`.
GLUED = (
    "-s",
    "-p",
    "-c",
    "-C",
    "--setup=",
    "--prepare=",
    "--cleanup=",
    "--conclude=",
    "--reference=",
)
# With `--` after the option: hidden in the shown command, as typed in the hash.
AFTER_DASHES = f'parallel -j 2 -- hyperfine "--setup={TEXT}" ./bench ::: 1'
# The option glued to its value, or the text as a word of its own: hidden in both.
HIDDEN = (
    f'parallel -j2 hyperfine "--setup={TEXT}" ./bench ::: 1',
    f'parallel --jobs=2 hyperfine "--setup={TEXT}" ./bench ::: 1',
    f'parallel -j 2 hyperfine --setup "{TEXT}" ./bench ::: 1',
    f'watch -n 3 hyperfine "--setup={TEXT}" ./bench',
)


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


def test_the_config_reference_names_the_limit(repo_root: Path) -> None:
    assert POINTER in " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())


def shows_password(args: list[str]) -> tuple[bool, bool]:
    """Whether the shown command and the hashed words of a command hold its password."""
    shown = model.public_command(args)
    assert shown is not None
    return "-a password" in shown, "-a password" in " ".join(model.hashed_argv(args))


@pytest.mark.parametrize("example", SHOWN)
def test_the_limit_s_example_shows_its_password(example: str) -> None:
    assert shows_password(shlex.split(example)) == (True, True)


@pytest.mark.parametrize("option", GLUED)
def test_each_glued_text_option_shows_its_password(option: str) -> None:
    args = ["parallel", "-j", "2", "hyperfine", f"{option}{TEXT}", "./bench", ":::", "1"]

    assert shows_password(args) == (True, True)


def test_after_dashes_the_shown_command_hides_it_and_the_hash_keeps_it() -> None:
    assert shows_password(shlex.split(AFTER_DASHES)) == (False, True)


@pytest.mark.parametrize("command", HIDDEN)
def test_a_glued_value_or_a_text_of_its_own_hides_it_in_both(command: str) -> None:
    assert shows_password(shlex.split(command)) == (False, False)
