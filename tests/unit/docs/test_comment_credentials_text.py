# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config page says a comment is shown as typed but for the credential forms inside it.

Each example the page gives of a password in a shell comment, typed and as
shown, is what ``public_command`` shows for it. The page reads the words of a
comment with a client's options only when the command right before the comment
is the client's, and the security policy lists a client's option in a comment
after another command as a known limit, whose example shows whole.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
CLIENT_SENTENCE = (
    "When the command right before the comment is a client's command, the words of the comment "
    "are read as words given to that client:"
)
LIMIT = (
    "**A client's option in a comment after another command.** The words of a comment are read "
    "with a client's options only when the command right before the comment is a client's "
    "command. After a pipe or an operator that starts another command, a client's password "
    "option in the comment is read as a word of that command, so the password shows: "
    "`sh -c 'redis-cli PING | grep PONG # -a password'` shows whole. A credential form that the "
    "argument of any program hides, such as `--token password`, is hidden in any comment."
)
# The limit's example, which shows whole, and forms beside it: (typed, shown).
LIMIT_EXAMPLES = (
    (
        "sh -c 'redis-cli PING | grep PONG # -a password'",
        "sh -c 'redis-cli PING | grep PONG # -a password'",
    ),
    (
        "sh -c 'redis-cli PING && redis-cli INFO # -a password'",
        "sh -c 'redis-cli PING && redis-cli INFO # -a <hidden>'",
    ),
    (
        "sh -c 'redis-cli PING | grep PONG # --token password'",
        "sh -c 'redis-cli PING | grep PONG # --token <hidden>'",
    ),
)
SENTENCE = (
    "A word that starts with `#` outside quotes starts a comment, which ends the command before "
    "it too and is shown as typed, except for every credential form inside it."
)
# Each example as the page types it, and as the page says it is shown.
EXAMPLES = (
    ("sh -c 'redis-cli PING # -a VALUE'", "sh -c 'redis-cli PING # -a <hidden>'"),
    ("sh -c 'redis-cli PING #AUTH VALUE'", "sh -c 'redis-cli PING #AUTH <hidden>'"),
    ("sh -c './bench # --token VALUE'", "sh -c './bench # --token <hidden>'"),
)


def page(repo_root: Path) -> str:
    """The config page, joined on one line."""
    return " ".join((repo_root / CONFIG_PAGE).read_text(encoding="utf-8").split())


def test_the_page_says_a_comment_hides_its_credential_forms(repo_root: Path) -> None:
    assert SENTENCE in page(repo_root)


@pytest.mark.parametrize(("typed", "shown"), EXAMPLES)
def test_each_comment_example_is_what_the_code_shows(
    repo_root: Path, typed: str, shown: str
) -> None:
    text = page(repo_root)

    assert f"`{typed}`" in text
    assert f"`{shown}`" in text
    assert model.public_command(shlex.split(typed)) == shown


def test_the_page_reads_a_comment_with_the_client_of_the_command_right_before_it(
    repo_root: Path,
) -> None:
    assert CLIENT_SENTENCE in page(repo_root)


def test_the_security_policy_lists_a_client_option_in_a_comment_after_another_command(
    repo_root: Path,
) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = " ".join(text.split(f"\n{LIMITS_HEADING}\n", 1)[1].split("\n## ", 1)[0].split())

    assert LIMIT in section


@pytest.mark.parametrize(("typed", "shown"), LIMIT_EXAMPLES)
def test_a_comment_after_another_command_is_read_as_the_policy_says(typed: str, shown: str) -> None:
    words = shlex.split(typed)

    assert model.public_command(words) == shown
    assert model.hashed_argv(words) == shlex.split(shown)
