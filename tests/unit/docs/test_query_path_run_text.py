# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the paths in the query of an address that a path before them runs over.

Inside an address the shown command cuts a path and reads the rest of the address after it, up
to the first ``;``, blank, quote, comma or bracket, cutting there only the paths that start at
one ``/``, at two ``/`` or at ``~``. So a relative path that climbs out of its folder, a
``file:`` address with two ``/`` or more and a path that starts with three ``/`` or more show
their folders in the query or the fragment of an address where such a rest runs over them. The
security policy lists the forms among the known limits of the shown command and gives the
remedy, and the config reference points to it. Each example of the entry is read through the
shown command here, and so is each form the entry names, kept and cut, so a change to the code
or to the entry that parts them fails a row.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A path in the query of an address that a path before it runs over.** Inside an address, "
    "the shown command cuts a path and reads the rest of the address after it, up to the first "
    "`;`, blank, quote, comma or bracket, cutting there only the paths that start at one `/`, at "
    "two `/` or at `~`. So a relative path that climbs out of its folder with `..`, a `file:` "
    "address with two `/` or more and a path that starts with three `/` or more show their "
    "folders in the query or the fragment of an address where such a rest runs over them. The "
    "path of the address runs over its query and its fragment when no host name and no port "
    "stand right before it: with no host, after a host in brackets with no port, after an empty "
    "port, in a `unix://` address with no user and no host in brackets, and in a `file://` "
    "address: `psql 'postgresql:///db?sslrootcert=../../made/up/ca.pem'` shows whole, and "
    "`psql 'postgresql://db.example:/db?sslrootcert=file:///made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>:/db?sslrootcert=file:///made/up/ca.pem'`. So does a path "
    "before it in the same query or fragment that starts at `/` or `~` or holds `../`, and a "
    "`file:` address whose `#` comes before it: "
    "`psql 'postgresql://db.example/db?a=/made/up&sslrootcert=../made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?a=/up&sslrootcert=../made/up/ca.pem'`. After a host name or "
    "a port with no such path before it, and after a `;`, a climbing path and a `file:` address "
    "are cut: `psql 'postgresql://db.example/db?sslrootcert=../made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?sslrootcert=ca.pem'`. A path that starts with three `/` or "
    "more shows whole there too: "
    "`psql 'postgresql://db.example/db?sslrootcert=///made/up/ca.pem'` shows "
    "`psql 'postgresql://<hidden>/db?sslrootcert=///made/up/ca.pem'`. A case id cuts these "
    "paths: `test_conn[postgresql:///db?sslrootcert=../../made/up/ca.pem]` shows "
    "`test_conn[postgresql:///db?sslrootcert=ca.pem]`."
)
ADVICE = (
    "In the query of an address, start a path at one `/` rather than with `..`, `file:` or "
    "three `/` (`?sslrootcert=/made/up/ca.pem` shows `?sslrootcert=/ca.pem`)."
)
POINTER = (
    "docs/reference/config.md",
    "In the query of an address in the shown command, a climbing path and a `file:` address "
    "show their folders where a path before them runs over them, and a path that starts with "
    "three `/` shows whole, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say; a case id cuts "
    "them.",
)
# The entry's examples of the shown command: a command as typed and as it shows.
EXAMPLES = (
    (
        "psql 'postgresql:///db?sslrootcert=../../made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=../../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example:/db?sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>:/db?sslrootcert=file:///made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=/made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up&sslrootcert=../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?sslrootcert=///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=///made/up/ca.pem'",
    ),
)
# The entry's example of a case id.
CASE_EXAMPLE = (
    "test_conn[postgresql:///db?sslrootcert=../../made/up/ca.pem]",
    "test_conn[postgresql:///db?sslrootcert=ca.pem]",
)
# The advice's example, as the query of an address with no host.
ADVICE_EXAMPLE = (
    "psql 'postgresql:///db?sslrootcert=/made/up/ca.pem'",
    "psql 'postgresql:///db?sslrootcert=/ca.pem'",
)
# Each form the entry names as one whose folders show: where the rest of the address starts,
# and what stands in it.
KEPT = (
    # the path of an address with four '/', and no host
    (
        "psql 'sqlite:////made/up/db.sqlite?cert=../made/up/ca.pem'",
        "psql 'sqlite:///db.sqlite?cert=../made/up/ca.pem'",
    ),
    # a host in brackets with no port
    (
        "psql 'postgresql://[fd00::1]/db?sslrootcert=./../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=./../made/up/ca.pem'",
    ),
    # a unix:// address with no user
    (
        "psql 'unix://made/up.sock?sslrootcert=data/../../made/up/ca.pem'",
        "psql 'unix:///up.sock?sslrootcert=data/../../made/up/ca.pem'",
    ),
    # a file:// address with a host
    (
        "psql 'file://db.example/made/up/db?sslrootcert=../made/up/ca.pem'",
        "psql 'file://db?sslrootcert=../made/up/ca.pem'",
    ),
    # the fragment of an address with no host
    (
        "psql 'postgresql:///db#../made/up/ca.pem'",
        "psql 'postgresql:///db#../made/up/ca.pem'",
    ),
    # a path before it that starts at '//', at '~' or holds '../'
    (
        "psql 'postgresql://db.example/db?a=//made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up&sslrootcert=../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=~/made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=up&sslrootcert=../made/up/ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=../made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=up&sslrootcert=../made/up/ca.pem'",
    ),
    # a file: address whose '#' comes before it
    (
        "psql 'postgresql://db.example/db?a=file:///made/up#../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=file://up#../made/up/ca.pem'",
    ),
    # file://localhost in the rest of an address with no host
    (
        "psql 'postgresql:///db?sslrootcert=file://localhost/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=file:///made/up/ca.pem'",
    ),
    # a path that starts with three '/' after a ';'
    (
        "psql 'postgresql://db.example/db?a=b;sslrootcert=///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=b;sslrootcert=///made/up/ca.pem'",
    ),
)
# The nearest forms the entry names as cut: a host name, a port or a user before the path of the
# address with no path before it, a host in brackets after unix://, a ';', a file: address with
# no '#' before it; and the paths the rest of an address cuts: one or two '/', '~' and file:/.
CUT = (
    (
        "psql 'postgresql://db.example:5432/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>:5432/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://bench@db.example/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>@<hidden>/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://[fd00::1]:5432/db?sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>:5432/db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db#k=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db#k=ca.pem'",
    ),
    (
        "psql 'unix://bench@made/up.sock?sslrootcert=../made/up/ca.pem'",
        "psql 'unix://<hidden>@<hidden>/up.sock?sslrootcert=ca.pem'",
    ),
    (
        "psql 'unix://[fd00::1]/db?sslrootcert=../made/up/ca.pem'",
        "psql 'unix:///[fd00::1]ca.pem'",
    ),
    (
        "psql 'postgresql:///db?a=b;sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql:///db?a=b;sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=/made/up;sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=/up;sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=made/up&sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?a=file:///made/up&sslrootcert=../made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?a=file://ca.pem'",
    ),
    (
        "psql 'postgresql://db.example/db?sslrootcert=file:///made/up/ca.pem'",
        "psql 'postgresql://<hidden>/db?sslrootcert=file://ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=//made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=/ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=~/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=ca.pem'",
    ),
    (
        "psql 'postgresql:///db?sslrootcert=file:/made/up/ca.pem'",
        "psql 'postgresql:///db?sslrootcert=file:/ca.pem'",
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


def shown(typed: str) -> str:
    """The shown command of a command typed as a shell reads it."""
    return model.public_command(shlex.split(typed))


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


def test_the_config_reference_points_to_the_limit(repo_root: Path) -> None:
    page, sentence = POINTER
    assert sentence in joined(repo_root, page)


@pytest.mark.parametrize(("typed", "expected"), EXAMPLES)
def test_each_example_of_the_limit_is_in_it_and_shows_as_it_says(typed: str, expected: str) -> None:
    said = f"`{typed}` shows whole" if expected == typed else f"`{typed}` shows `{expected}`"
    assert said in LIMIT
    assert shown(typed) == expected


def test_the_case_id_example_is_in_the_limit_and_cut() -> None:
    typed, expected = CASE_EXAMPLE
    assert f"`{typed}` shows `{expected}`" in LIMIT
    assert model.public_case(typed) == expected


def test_the_advice_s_example_is_cut() -> None:
    typed, expected = ADVICE_EXAMPLE
    assert shown(typed) == expected


@pytest.mark.parametrize(("typed", "expected"), KEPT)
def test_a_form_the_limit_names_shows_its_folders(typed: str, expected: str) -> None:
    assert shown(typed) == expected


@pytest.mark.parametrize(("typed", "expected"), CUT)
def test_a_form_the_limit_names_as_cut_shows_no_folder(typed: str, expected: str) -> None:
    assert shown(typed) == expected
