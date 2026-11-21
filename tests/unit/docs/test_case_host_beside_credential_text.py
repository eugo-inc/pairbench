# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a password before a host beside a credential in a case id.

In a part of a case id that also gives a credential-like name a value with ``=`` after the
host, the value of that name is hidden and the password before the host shows, also where
pytest joins the name and its value to the host with ``-``. The security policy lists it among
the known limits of the shown command, and the pages that say a password before a host is
hidden in a case id name the exception. The same id without the credential, or with the
credential in a part of its own, hides both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A password before a host beside a credential in a case id.** In a part of a case id that "
    "also gives a credential-like name a value with `=` after the host, the value of that name is "
    "hidden and the password before the host shows: "
    "`test_db[bob:password@db.example:5432?sslmode=require&token=made-up]` shows "
    "`test_db[bob:password@db.example:5432?sslmode=require&token=<hidden>]`, and the password "
    "shows too where pytest joins such a name and its value to the host with `-`, as in "
    "`test_db[bob:password@db.example:5432-token=made-up]`."
)
ADVICE = "In a case id, keep a password before a host out of a part that gives a credential a value"
POINTERS = (
    (
        "docs/reference/config.md",
        "In a part that also gives a credential-like name a value with `=` after the host, the "
        "password before the host shows, as the "
        "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say.",
    ),
    (
        "docs/guides/index.md",
        "So does a password before a host where the same part of the id gives a credential-like "
        "name a value with `=` after the host.",
    ),
)
# The limit's examples, and the ids they give.
SHOWN = (
    (
        "test_db[bob:password@db.example:5432?sslmode=require&token=made-up]",
        "test_db[bob:password@db.example:5432?sslmode=require&token=<hidden>]",
    ),
    (
        "test_db[bob:password@db.example:5432-token=made-up]",
        "test_db[bob:password@db.example:5432-token=<hidden>]",
    ),
)
# The same password with no credential in its part: it is hidden.
HIDDEN = (
    (
        "test_db[bob:password@db.example:5432?sslmode=require]",
        "test_db[bob:<hidden>@db.example:5432?sslmode=require]",
    ),
    (
        "test_db[bob:password@db.example:5432,token=made-up]",
        "test_db[bob:<hidden>@db.example:5432,token=<hidden>]",
    ),
)


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


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


@pytest.mark.parametrize(("page", "sentence"), POINTERS)
def test_each_page_on_a_case_id_names_the_exception(
    repo_root: Path, page: str, sentence: str
) -> None:
    assert sentence in joined(repo_root, page)


@pytest.mark.parametrize(("typed", "shown"), SHOWN)
def test_the_limit_s_example_shows_its_password(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


@pytest.mark.parametrize(("typed", "shown"), HIDDEN)
def test_the_password_without_a_credential_in_its_part_is_hidden(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown
