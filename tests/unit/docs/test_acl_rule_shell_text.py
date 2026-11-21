# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config page says how a rule of ``ACL SETUSER`` typed with a backslash is read.

A shell takes off the backslash, in a shell text and in the words that ``ssh``, ``watch`` or
``parallel`` hands to a shell, so the rule gives a password there and the page's examples
show it hidden. No rule starts with a backslash, so the rule loses its value with no shell
between too, and an ordinary word or a user name with a backslash is shown as typed, as the
page says. Every value is made up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
TEXT = (
    "A shell takes off a backslash before a rule's first character, so a rule typed so in a "
    "shell text is read as the shell reads it: "
    "`sh -c 'redis-cli ACL SETUSER app on \\>VALUE'` shows "
    "`sh -c 'redis-cli ACL SETUSER app on \\><hidden>'`. So is a rule in the words that `ssh` "
    "hands to a shell on the other machine, or that `watch` or `parallel` hands to a shell: "
    "`ssh made-up-host redis-cli ACL SETUSER app on '\\>VALUE'` shows "
    "`ssh made-up-host redis-cli ACL SETUSER app on '\\><hidden>'`. So is a rule after a "
    "program in front of `ssh`, `watch` or `parallel` (`timeout 5 ssh ...`), in a shell text "
    "that one of their words holds (`ssh made-up-host sh -c '...'`), and after `hyperfine -N`, "
    "which splits its command into words with no shell and takes the backslash off too. No "
    "rule starts with a backslash, so a rule typed with one loses its value wherever it "
    "stands, also with no shell between, as after `watch -x` or `parallel -q`, where the "
    "client gets the backslash and refuses the rule. An ordinary word with a backslash keeps "
    "it (`redis-cli SET k '\\>v'`), and so does a user name."
)
# The page's examples, as typed and as shown.
EXAMPLES = (
    (
        "sh -c 'redis-cli ACL SETUSER app on \\>VALUE'",
        "sh -c 'redis-cli ACL SETUSER app on \\><hidden>'",
    ),
    (
        "ssh made-up-host redis-cli ACL SETUSER app on '\\>VALUE'",
        "ssh made-up-host redis-cli ACL SETUSER app on '\\><hidden>'",
    ),
)
# The forms the page names, each shown with the rule's value hidden.
HIDDEN_FORMS = (
    (
        "timeout 5 ssh made-up-host redis-cli ACL SETUSER app on '\\>VALUE'",
        "timeout 5 ssh made-up-host redis-cli ACL SETUSER app on '\\><hidden>'",
    ),
    (
        "ssh made-up-host sh -c \"'redis-cli ACL SETUSER app on \\>VALUE'\"",
        "ssh made-up-host sh -c ''\"'\"'redis-cli ACL SETUSER app on \\><hidden>'\"'\"''",
    ),
    (
        "hyperfine -N 'redis-cli ACL SETUSER app on \\>VALUE'",
        "hyperfine -N 'redis-cli ACL SETUSER app on \\><hidden>'",
    ),
    (
        "watch -x redis-cli ACL SETUSER app on '\\>VALUE'",
        "watch -x redis-cli ACL SETUSER app on '\\><hidden>'",
    ),
    (
        "parallel -q redis-cli ACL SETUSER app on '\\>VALUE' ::: a",
        "parallel -q redis-cli ACL SETUSER app on '\\><hidden>' ::: a",
    ),
)
# An ordinary word and a user name with a backslash, each shown as typed.
AS_TYPED = (
    "redis-cli SET k '\\>v'",
    "redis-cli ACL SETUSER '\\>app' on +@all",
)


def page_text(repo_root: Path) -> str:
    """The config page on one line."""
    return " ".join((repo_root / CONFIG_PAGE).read_text(encoding="utf-8").split())


def test_the_config_page_says_how_the_rule_is_read(repo_root: Path) -> None:
    assert TEXT in page_text(repo_root)


@pytest.mark.parametrize(("typed", "shown"), EXAMPLES)
def test_each_example_is_shown_as_the_page_says(typed: str, shown: str) -> None:
    assert model.public_command(shlex.split(typed)) == shown


@pytest.mark.parametrize(("typed", "shown"), HIDDEN_FORMS)
def test_each_form_the_page_names_hides_the_value(typed: str, shown: str) -> None:
    words = shlex.split(typed)

    assert model.public_command(words) == shown
    assert "VALUE" not in " ".join(model.hashed_argv(words))


@pytest.mark.parametrize("typed", AS_TYPED)
def test_an_ordinary_word_with_a_backslash_is_shown_as_typed(typed: str) -> None:
    words = shlex.split(typed)

    assert model.public_command(words) == typed
    assert model.hashed_argv(words) == words
