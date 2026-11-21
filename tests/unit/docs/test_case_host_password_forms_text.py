# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages list the forms of a password before a host that a case id shows.

A ``::`` joins the parts of a name (``test_dep[Module::Name@1.23]``), so a password before a host
that starts with a ``:`` shows where a user, or a value pytest joins to it with ``-``, stands
right before it; with nothing there it is hidden, and so is a name that starts with ``::`` before
an ``@`` and a host or a version with a dot. A password before a host is hidden only where the id
writes it as ``user:password@host``; with a ``/`` between the user and the password, with the
host in brackets, or with the host in a pair of parentheses after the name of a network, it
shows. The security policy lists both among the known limits of the shown command, the case-id
paragraph of the policy and the config page point to the first, and each example shows what the
pages say. Every value is made up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model
from pairbench.api import CaseNames
from pairbench.errors import EXIT_USAGE, Refusal

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
LIMITS_HEADING = "## Known limits of the shown command"
COLON_LIMIT = (
    "**A password that starts with a `:` before a host after a user in a case id.** A `::` joins "
    "the parts of a name, as in `test_dep[Module::Name@1.23]`, so a password before a host that "
    "starts with a `:` shows where a letter, a digit, `_`, `.`, `+`, `%` or `-` stands right "
    "before it, as a user or a value that pytest joins to it with `-` does: "
    "`test_db[bob::made-up@db.example:6379]` and `test_db[5432-::made-up@db.example:6379]` show "
    "as written. With nothing of that kind before it, such a password is hidden: "
    "`test_db[::made-up@db.example:6379]` shows `test_db[:<hidden>@db.example:6379]`. So is a "
    "name that starts with `::` before an `@` and a host or a version that holds a dot: "
    "`test_dep[::Name@1.23]` shows `test_dep[:<hidden>@1.23]`, so two such ids that differ only "
    "in that name are refused with `E_USAGE` in one launch and read as one case across launches "
    "or sides."
)
OTHER_FORMS_LIMIT = (
    "**A password before a host written in another form in a case id.** A password before a "
    "host is hidden where the id writes it as `user:password@host`, with a host that holds a dot "
    "or is followed by a port right after the `@`. Written another way, it shows as written: with "
    "a `/` between the user and the password (`test_db[bob/made-up@db.example:1521/orcl]`), with "
    "the host in brackets (`test_db[bob:made-up@[::1]:6379]`), or with the host in a pair of "
    "parentheses after the name of a network (`test_db[bob:made-up@tcp(db.example:3306)/app]`)."
)
# The case-id paragraph of the policy, right after its sentence on a colon written as ``%3A``.
SECURITY_POINTER = (
    "A password before a host that starts with a colon is hidden with no user before it "
    "(`query[::made-up@db.example:6379]` shows `query[:<hidden>@db.example:6379]`), but shows "
    "after a user, as a `::` joins the parts of a name: `query[bob::made-up@db.example:6379]` "
    "shows as written."
)
# The config page, right after its sentence on a colon written as ``%3A``.
CONFIG_POINTER = (
    "A password that starts with a `:` is hidden with no user before it "
    "(`test_db[::made-up@db.example:6379]` shows `test_db[:<hidden>@db.example:6379]`), but "
    "shows after a user, as a `::` joins the parts of a name: "
    "`test_db[bob::made-up@db.example:6379]` shows as written, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say."
)
# Every id the pages give as shown as written.
SHOWN_AS_WRITTEN = (
    "test_dep[Module::Name@1.23]",
    "test_db[bob::made-up@db.example:6379]",
    "test_db[5432-::made-up@db.example:6379]",
    "query[bob::made-up@db.example:6379]",
    "test_db[bob/made-up@db.example:1521/orcl]",
    "test_db[bob:made-up@[::1]:6379]",
    "test_db[bob:made-up@tcp(db.example:3306)/app]",
)
# Every id the pages give as hidden, and what each shows: one ``:`` and no user for comparison,
# a password that starts with a ``:`` and no user, and a name that starts with ``::``.
HIDDEN = (
    ("test_db[:made-up@db.example:6379]", "test_db[:<hidden>@db.example:6379]"),
    ("test_db[::made-up@db.example:6379]", "test_db[:<hidden>@db.example:6379]"),
    ("query[::made-up@db.example:6379]", "query[:<hidden>@db.example:6379]"),
    ("test_dep[::Name@1.23]", "test_dep[:<hidden>@1.23]"),
)
# Two ids of one launch that differ only in a name that starts with ``::``: refused.
NAMES_REFUSED = ("test_dep[::Name@1.23]", "test_dep[::Other@1.23]")
# A made-up key, where the ids came from and the advice the refusal gives.
KEY = bytes(range(32))
WHERE = "side 'new'"
ADVICE = "give them other names"


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


@pytest.mark.parametrize("entry", [COLON_LIMIT, OTHER_FORMS_LIMIT], ids=["colon", "other-forms"])
def test_the_security_policy_lists_the_limit(repo_root: Path, entry: str) -> None:
    assert f"- {entry}" in limits(repo_root)


def test_the_case_id_paragraph_points_to_a_password_that_starts_with_a_colon(
    repo_root: Path,
) -> None:
    assert SECURITY_POINTER in limits(repo_root)


def test_the_config_page_points_to_a_password_that_starts_with_a_colon(repo_root: Path) -> None:
    assert CONFIG_POINTER in joined(repo_root, CONFIG)


@pytest.mark.parametrize("case", SHOWN_AS_WRITTEN)
def test_each_example_the_pages_give_shows_as_written(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize(("typed", "shown"), HIDDEN)
def test_each_example_the_pages_give_as_hidden_shows_what_they_say(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


def test_two_names_that_start_with_a_double_colon_and_differ_only_there_are_refused() -> None:
    assert model.public_case(NAMES_REFUSED[0]) == model.public_case(NAMES_REFUSED[1])
    with pytest.raises(Refusal) as caught:
        CaseNames(KEY).names(list(NAMES_REFUSED), WHERE, ADVICE)

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert "differ only in a hidden secret" in caught.value.message
    assert "Other" not in caught.value.message
