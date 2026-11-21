# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say that a case id hides a password before a host with text around it.

The config page and SECURITY.md say that the password before a host in a case id is hidden up
to the ``@``, with the text before the user and after the host kept, as in the id pytest gives
a test with two parameters, and what such a password cannot hold. Each example the pages give
shows what they say it shows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
SECURITY_PAGE = "SECURITY.md"
CONFIG_TEXT = (
    "A password before a host is hidden up to the `@`, and the text before its user and after "
    "its host is kept, as where pytest joins it to another value with `-`: "
    "`test_db[bob:made-up@db.example:5432-ro]` shows `test_db[bob:<hidden>@db.example:5432-ro]`, "
    'and `test_db[{"dsn":"bob:made-up@db.example"}]` shows '
    '`test_db[{"dsn":"bob:<hidden>@db.example"}]`; such a password holds no `@`, quote or angle '
    "bracket."
)
SECURITY_TEXT = (
    "a password before a host that holds a dot or is followed by a port, written without a "
    "scheme, up to the `@` before the host, with the text before the user and after the host "
    "kept (`query[bench:made-up@db.example]` shows `query[bench:<hidden>@db.example]`, and "
    "`query[bench:made-up@db.example:5432-ro]`, as pytest joins two values with a dash, shows "
    "`query[bench:<hidden>@db.example:5432-ro]`; such a password holds no `@`, quote or angle "
    "bracket)"
)
# Each example of the pages and what it shows.
EXAMPLES = {
    "test_db[bob:made-up@db.example:5432-ro]": "test_db[bob:<hidden>@db.example:5432-ro]",
    'test_db[{"dsn":"bob:made-up@db.example"}]': 'test_db[{"dsn":"bob:<hidden>@db.example"}]',
    "query[bench:made-up@db.example]": "query[bench:<hidden>@db.example]",
    "query[bench:made-up@db.example:5432-ro]": "query[bench:<hidden>@db.example:5432-ro]",
}


def page(repo_root: Path, name: str) -> str:
    return " ".join((repo_root / name).read_text(encoding="utf-8").split())


def test_the_config_page_says_the_text_around_the_host_is_kept(repo_root: Path) -> None:
    assert CONFIG_TEXT in page(repo_root, CONFIG_PAGE)


def test_security_says_the_text_around_the_host_is_kept(repo_root: Path) -> None:
    assert SECURITY_TEXT in page(repo_root, SECURITY_PAGE)


@pytest.mark.parametrize(("case", "shown"), list(EXAMPLES.items()))
def test_each_example_shows_what_the_pages_say(case: str, shown: str) -> None:
    assert model.public_case(case) == shown
