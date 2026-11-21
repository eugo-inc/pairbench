# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config page says a Redis name that looks like a redirection in an argument list is a name.

Each example the page gives, typed and as shown, is what ``public_command``
shows for it, and the sentence says the password of either reading is hidden.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
SENTENCE = (
    "In an argument list, a word that looks like a redirection where a Redis command takes a user "
    "or setting name is that name, as the client gets it, and the password of either reading is "
    "hidden:"
)
AFTER = "after such a user name of `HELLO` the word after the password is hidden as well."
# Each example as the page types it, and as the page says it is shown.
EXAMPLES = (
    (
        "redis-cli ACL SETUSER '>NAME' '>VALUE'",
        "redis-cli ACL SETUSER '>NAME' '><hidden>'",
    ),
    (
        "redis-cli HELLO 3 AUTH '>NAME' VALUE",
        "redis-cli HELLO 3 AUTH '>NAME' '<hidden>'",
    ),
    (
        "redis-cli CONFIG SET '<NAME' 1 requirepass VALUE",
        "redis-cli CONFIG SET '<NAME' 1 requirepass '<hidden>'",
    ),
)


def page(repo_root: Path) -> str:
    """The config page, joined on one line."""
    return " ".join((repo_root / CONFIG_PAGE).read_text(encoding="utf-8").split())


def test_the_page_says_such_a_word_is_a_name(repo_root: Path) -> None:
    text = page(repo_root)

    assert SENTENCE in text
    assert AFTER in text


@pytest.mark.parametrize(("typed", "shown"), EXAMPLES)
def test_each_example_is_what_the_code_shows(repo_root: Path, typed: str, shown: str) -> None:
    text = page(repo_root)

    assert f"`{typed}` shows `{shown}`" in text
    assert model.public_command(shlex.split(typed)) == shown
