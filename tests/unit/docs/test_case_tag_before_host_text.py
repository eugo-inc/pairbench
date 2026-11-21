# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a tag before a host in a case id.

A word after a ``:`` with an ``@`` and a host after it, with a user before the ``:`` or none, is
read as a password before a host, a tag or a version as much as a password, so an image tag
written that way is hidden, and two ids that differ only in that tag read the same: refused
within one launch, read as one case across launches or sides. The security policy lists it among
the known limits of the shown command, with two ways to name such a case that keep its tags, an
image name glued to its tag that is credential-like as the exception, and a way to name such an
image, and the config page points to it. A password before a host with no user is hidden when
its word is a tag or a version, as the pages promise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
# Two such ids in different launches or on different sides are not refused: they are one case.
CROSS = (
    "Two such ids in different launches, or on different sides, are read as one case, as an id "
    "whose secret alone differs from one launch or side to the next is, so the rounds of both "
    "tags count toward one verdict."
)
# An image name that is credential-like loses its tag as any such name loses its value.
CREDENTIAL = (
    "A credential-like name glued to its value with `:` loses the value, an image's name too: "
    "`test_tag[auth:latest]` shows `test_tag[auth:<hidden>]`, and "
    "`test_tag[registry.example:5000/api-key:latest]` shows "
    "`test_tag[registry.example:5000/api-key:<hidden>]`, though a tag that is a whole number "
    "right after a `/` shows, as a benchmark's named argument does "
    "(`test_tag[registry.example:5000/api-key:3]`). Join the tag of such an image to its name "
    "with `-` (`test_tag[auth-latest]`), which shows as written."
)
LIMIT = (
    "**A tag before a host in a case id.** A word after a `:`, with an `@` and a host that holds "
    "a dot or is followed by a port after it, is read as a password before a host, a tag or a "
    "version as much as a password, as an address with no user name writes one, so an image tag "
    "written that way is hidden: `test_tag[:latest@registry.example:5000]` shows "
    "`test_tag[:<hidden>@registry.example:5000]`, and so does "
    "`test_tag[:stable@registry.example:5000]`, so two such ids of one launch read the same and "
    f"are refused with `E_USAGE`. {CROSS} A name before the `:` is read as the user "
    "(`test_tag[app:latest@registry.example:5000]` shows "
    "`test_tag[app:<hidden>@registry.example:5000]`). Name such a case as an image reference "
    "writes it, the registry first (`test_tag[registry.example:5000/app:latest]`), or with no "
    "`@` and host after the tag (`test_tag[app:latest]`): written either way, `latest` and "
    "`stable` show as written and stay two cases while the image's name is not credential-like. "
    f"{CREDENTIAL}"
)
CONFIG = "docs/reference/config.md"
POINTER = (
    "An image tag written before a host with no user is hidden as such a password too: "
    "`test_tag[:latest@registry.example:5000]` shows "
    "`test_tag[:<hidden>@registry.example:5000]`, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say."
)
# The limit's examples: each id as typed, and the id the results show.
HIDDEN = (
    ("test_tag[:latest@registry.example:5000]", "test_tag[:<hidden>@registry.example:5000]"),
    ("test_tag[:stable@registry.example:5000]", "test_tag[:<hidden>@registry.example:5000]"),
    ("test_tag[app:latest@registry.example:5000]", "test_tag[app:<hidden>@registry.example:5000]"),
)
# The two ways the limit gives to name such a case, each with a second tag: each id shows as
# written, so the two ids of each way stay two.
ADVISED = (
    ("test_tag[registry.example:5000/app:latest]", "test_tag[registry.example:5000/app:stable]"),
    ("test_tag[app:latest]", "test_tag[app:stable]"),
)
# Image names that are credential-like: glued to a tag with ``:``, the name gives the tag as its
# value and the tag is hidden, written either way the limit gives.
CREDENTIAL_NAMES = (
    "auth",
    "api-key",
    "token-service",
    "secret-store",
    "password",
    "db-password",
    "credentials",
    "password-manager",
)
CREDENTIAL_HIDDEN = tuple(
    (f"{prefix}{name}:{tag}]", f"{prefix}{name}:<hidden>]")
    for prefix in ("test_tag[", "test_tag[registry.example:5000/")
    for name in CREDENTIAL_NAMES
    for tag in ("latest", "stable")
)
# The same names joined to their tag with ``-``, as the limit advises: each shows as written.
DASH_JOINED = tuple(
    (f"{prefix}{name}-latest]", f"{prefix}{name}-stable]")
    for prefix in ("test_tag[", "test_tag[registry.example:5000/")
    for name in CREDENTIAL_NAMES
)
# The examples the limit gives of a credential-like image name, and what each shows.
CREDENTIAL_EXAMPLES = (
    ("test_tag[auth:latest]", "test_tag[auth:<hidden>]"),
    (
        "test_tag[registry.example:5000/api-key:latest]",
        "test_tag[registry.example:5000/api-key:<hidden>]",
    ),
    ("test_tag[auth-latest]", "test_tag[auth-latest]"),
    # A whole-number tag right after a ``/``, read as a benchmark's named argument.
    (
        "test_tag[registry.example:5000/api-key:3]",
        "test_tag[registry.example:5000/api-key:3]",
    ),
)
# A password before a host with no user whose word looks like a tag or a version: the pages
# promise it hidden, as any other such password.
PROMISED = (
    ("test_db[:stable@db.example:6379]", "test_db[:<hidden>@db.example:6379]"),
    ("test_db[:3.12@db.example:6379]", "test_db[:<hidden>@db.example:6379]"),
    ("test_db[:made-up-pw@registry.example:5000]", "test_db[:<hidden>@registry.example:5000]"),
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
    assert f"- {LIMIT}" in limits(repo_root)


def test_the_config_page_points_to_the_limit(repo_root: Path) -> None:
    assert POINTER in joined(repo_root, CONFIG)


@pytest.mark.parametrize(("typed", "shown"), HIDDEN)
def test_the_limit_s_example_hides_the_tag(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


@pytest.mark.parametrize("pair", ADVISED)
def test_each_way_the_limit_gives_shows_both_tags_as_written(pair: tuple[str, str]) -> None:
    assert [model.public_case(case) for case in pair] == list(pair)


@pytest.mark.parametrize(("typed", "shown"), PROMISED)
def test_a_password_with_no_user_is_hidden_when_its_word_is_a_tag(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


def test_the_limit_says_ids_of_different_launches_or_sides_are_one_case(repo_root: Path) -> None:
    assert CROSS in limits(repo_root)


def test_the_limit_names_a_credential_like_image_name(repo_root: Path) -> None:
    assert CREDENTIAL in limits(repo_root)


@pytest.mark.parametrize(("typed", "shown"), CREDENTIAL_EXAMPLES)
def test_the_limit_s_credential_name_examples_show_what_it_says(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


@pytest.mark.parametrize(("typed", "shown"), CREDENTIAL_HIDDEN)
def test_a_credential_like_image_name_hides_its_tag(typed: str, shown: str) -> None:
    assert model.public_case(typed) == shown


@pytest.mark.parametrize("pair", DASH_JOINED)
def test_a_tag_joined_with_a_dash_to_a_credential_like_name_shows(pair: tuple[str, str]) -> None:
    assert [model.public_case(case) for case in pair] == list(pair)
