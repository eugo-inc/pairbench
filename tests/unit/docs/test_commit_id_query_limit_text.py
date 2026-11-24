# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy names where a commit id's length in a query stays shown.

Hexadecimal of a commit id's length is hidden in a query when it follows a
``?``, ``&``, ``#`` or ``=`` and a ``.`` joins it to a path after it. The
limit is found in the section on the shown command, and each form it gives
is run through the cleaner with a made-up value and shows the value, as the
policy says; the form the policy gives as the way to hide such a value is
run too.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A commit id's length joined to a path in a query in another way.** Hexadecimal of 40 "
    "characters, the length of a commit id, shows on its own. In the query or the fragment of an "
    "address it is hidden when it follows a `?`, `&`, `#` or `=` and a `.` joins it to a path "
    "after it, as the config reference says. These forms of it there are read as a commit id and "
    "show: after another character, such as a `:`, a `!` or a percent escape; glued to a `-`, a "
    "`_` or a `~`; or joined to the path by a percent escape. With `<id>` for the 40 characters, "
    "`curl 'https://made-up.example/x?:<id>./../b'` shows "
    "`curl 'https://<hidden>/x?:<id>./../b'`, and so do `?!<id>./../b`, `?k=a:<id>./../b`, "
    "`?k=%20<id>./../b`, `?<id>-./../b`, `?<id>_./../b`, `?<id>~./b`, `?<id>%2e./b` and "
    "`?<id>.%2Fb`. So does such a value followed by only `./` at the end of an address that has a "
    "`&` and no `?`, which is cut as a path before the value is read: "
    "`curl 'postgresql:///db&<id>./'` shows `curl 'postgresql:///db&<id>.'`. Give a secret value "
    "after a credential's name: `curl 'https://made-up.example/x?token=<id>./../b'` shows "
    "`curl 'https://<hidden>/x?token=<hidden>'`."
)
# A made-up value of a commit id's length, put where the policy writes `<id>`.
HEX = "0badc0de" * 5
# The query of each form the policy gives after `https://made-up.example/x`, as typed: each
# shows the value.
QUERIES = (
    f"?:{HEX}./../b",
    f"?!{HEX}./../b",
    f"?k=a:{HEX}./../b",
    f"?k=%20{HEX}./../b",
    f"?{HEX}-./../b",
    f"?{HEX}_./../b",
    f"?{HEX}~./b",
    f"?{HEX}%2e./b",
    f"?{HEX}.%2Fb",
)


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def test_the_security_policy_names_where_a_commit_id_s_length_shows(repo_root: Path) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = plain(text.split(f"\n{LIMITS_HEADING}\n", 1)[1].split("\n## ", 1)[0])

    assert LIMIT in section


@pytest.mark.parametrize("query", QUERIES)
def test_each_form_shows_the_value(query: str) -> None:
    argv = ["curl", f"https://made-up.example/x{query}"]

    assert model.public_command(argv) == shlex.join(["curl", f"https://{model.HIDDEN}/x{query}"])


# An address with a `&` and no `?` that ends in the value and `./`, and how it shows: cut as a
# path, with the value.
CUT = (
    (f"postgresql:///db&{HEX}./", f"postgresql:///db&{HEX}."),
    (f"file:///a/b&{HEX}./", f"file://b&{HEX}."),
)


@pytest.mark.parametrize(("value", "shown"), CUT)
def test_an_address_cut_as_a_path_shows_the_value(value: str, shown: str) -> None:
    assert model.public_command(["curl", value]) == shlex.join(["curl", shown])


def test_the_value_after_a_credential_s_name_is_hidden() -> None:
    argv = ["curl", f"https://made-up.example/x?token={HEX}./../b"]

    assert model.public_command(argv) == shlex.join(
        ["curl", f"https://{model.HIDDEN}/x?token={model.HIDDEN}"]
    )
