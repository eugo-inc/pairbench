# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say that a password before a host is hidden with no user before its colon.

The config page and SECURITY.md say that a case id hides a password before a host when no user
stands before the colon, as an address with no user name writes it, and that a colon written as
``%3A`` is part of the user name, as it is in an address, so such an id shows as written; the
advice says to write that colon as a colon. Each example the pages give shows what they say.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
SECURITY_PAGE = "SECURITY.md"
CONFIG_TEXT = (
    "It is hidden with no user before its `:` too, as an address with no user name writes it: "
    "`test_db[:made-up@db.example:6379]` shows `test_db[:<hidden>@db.example:6379]`. A `:` "
    "written as `%3A` is part of the user name, as it is in an address, so "
    "`test_db[bob%3Amade-up@db.example]` shows as written."
)
SECURITY_TEXT = (
    "A password before a host is hidden with no user before its colon too, as an address with no "
    "user name writes it (`query[:made-up@db.example:6379]` shows "
    "`query[:<hidden>@db.example:6379]`), but a colon written as `%3A` is part of the user name, "
    "as it is in an address, so `query[bob%3Amade-up@db.example]` shows as written."
)
ADVICE = (
    "In a case id, keep a password before a host out of a part that gives a credential a value, "
    "write the colon before such a password as a colon rather than as `%3A`, and write a case "
    "pattern"
)
# Each example the pages give of a hidden password, and what it shows.
HIDDEN = {
    "test_db[:made-up@db.example:6379]": "test_db[:<hidden>@db.example:6379]",
    "query[:made-up@db.example:6379]": "query[:<hidden>@db.example:6379]",
}
# Each example the pages give of an id shown as written.
SHOWN_AS_WRITTEN = (
    "test_db[bob%3Amade-up@db.example]",
    "query[bob%3Amade-up@db.example]",
)


def page(repo_root: Path, name: str) -> str:
    return " ".join((repo_root / name).read_text(encoding="utf-8").split())


def test_the_config_page_says_an_empty_user_hides_the_password(repo_root: Path) -> None:
    assert CONFIG_TEXT in page(repo_root, CONFIG_PAGE)


def test_security_says_an_empty_user_hides_the_password(repo_root: Path) -> None:
    assert SECURITY_TEXT in page(repo_root, SECURITY_PAGE)


def test_security_advises_a_plain_colon(repo_root: Path) -> None:
    assert ADVICE in page(repo_root, SECURITY_PAGE)


@pytest.mark.parametrize(("case", "shown"), list(HIDDEN.items()))
def test_each_hidden_example_shows_what_the_pages_say(case: str, shown: str) -> None:
    assert model.public_case(case) == shown


@pytest.mark.parametrize("case", SHOWN_AS_WRITTEN)
def test_each_percent_encoded_colon_shows_as_written(case: str) -> None:
    assert model.public_case(case) == case
