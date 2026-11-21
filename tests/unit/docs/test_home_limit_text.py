# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a home folder under another folder among the known limits.

A path whose last part is a home folder right under ``/home`` or ``/Users`` shows
``<hidden>``, while one under any other folder, such as ``/var/home``, shows its name as an
ordinary last part, as does a file named after its user and a ``~NAME`` glued to a short
option. The security policy says so with those examples and the advice to write one's own
home folder as ``~``; the examples and the advice behave as the entry says. The config
reference and the results page say what such a path shows, with examples that behave so.
"""

from __future__ import annotations

from pathlib import Path

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
NEXT_HEADING = "## Known limits of the hashes"
LIMIT = (
    "- **A home folder under another folder.** A path whose last part is a home folder shows\n"
    "  `<hidden>` in its place when that folder is right under `/home` or `/Users`, at the root"
    " or\n"
    "  reached by climbing with `..`, or is written `~made-up-user`. A home folder kept under"
    " any\n"
    "  other folder is read as an ordinary folder, so its name shows as the last part:\n"
    "  `tool /var/home/user` shows `tool user`. So does a file named after its user\n"
    "  (`tool ../made-up-user.txt` shows `tool made-up-user.txt`), and so does a home written\n"
    "  `~made-up-user` glued to a short option, which is read as part of the option\n"
    "  (`tool -d~made-up-user` shows as typed). Write your own home folder as `~`, which shows as\n"
    "  typed, or name a file inside it, and give an option its folder as a word of its own.\n"
)
CONFIG = "docs/reference/config.md"
CONFIG_TEXT = (
    "a path whose last part is a home folder, the folder right under `/home` or `/Users`"
    " (`/home/user` or `../home/user`, also as the last path of a list such as"
    " `/usr/bin:/home/user`) or a home written `~made-up-user`, cut to `<hidden>`, as that"
    " folder is named after its user,"
)
RESULTS_PAGE = "docs/reference/results-schema.md"
RESULTS_PAGE_TEXT = (
    "A path whose last part is a home folder, the folder right under `/home` or `/Users` or a"
    " home written `~made-up-user`, shows `<hidden>` in place of that folder's name"
    " (`../home/user` shows `<hidden>`), while the hashes take it as typed."
)
LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
# A made-up name for the folder of a user.
USER = "made-up-user"


def limits_text(root: Path) -> str:
    text = (root / SECURITY).read_text(encoding="utf-8")
    start = text.index(LIMITS_HEADING)
    return text[start : text.index(NEXT_HEADING, start)]


def test_the_known_limits_list_a_home_folder_under_another_folder(repo_root: Path) -> None:
    assert LIMIT in limits_text(repo_root)


def test_the_examples_of_the_limit_show_as_the_entry_says() -> None:
    assert model.public_command((*LEAD, "tool", "/var/home/user")) == SHOWN_LEAD + "tool user"
    assert model.public_command((*LEAD, "tool", "../made-up-user.txt")) == (
        SHOWN_LEAD + "tool made-up-user.txt"
    )
    assert model.public_command((*LEAD, "tool", f"-d~{USER}")) == SHOWN_LEAD + f"tool '-d~{USER}'"


def test_a_home_folder_right_under_home_shows_hidden_as_the_entry_says() -> None:
    for home in ("/home", "/Users", "../home"):
        path = f"{home}/{USER}"
        assert model.public_command((*LEAD, "tool", path)) == SHOWN_LEAD + "tool '<hidden>'", path
    assert model.public_command((*LEAD, "sh", "-c", "tool ~made-up-user")) == (
        SHOWN_LEAD + "sh -c 'tool <hidden>'"
    )


def test_the_advice_of_the_limit_keeps_the_name_out() -> None:
    assert model.public_command((*LEAD, "sh", "-c", "tool ~")) == SHOWN_LEAD + "sh -c 'tool ~'"
    assert model.public_command((*LEAD, "tool", "-d", f"~{USER}")) == (
        SHOWN_LEAD + "tool -d '<hidden>'"
    )
    assert model.public_command((*LEAD, "tool", "/var/home/made-up-user/x.csv")) == (
        SHOWN_LEAD + "tool x.csv"
    )


def one_line(root: Path, page: str) -> str:
    return " ".join((root / page).read_text(encoding="utf-8").split())


def test_the_reference_pages_say_what_a_home_folder_shows(repo_root: Path) -> None:
    assert CONFIG_TEXT in one_line(repo_root, CONFIG)
    assert RESULTS_PAGE_TEXT in one_line(repo_root, RESULTS_PAGE)


def test_the_examples_of_the_reference_pages_show_and_hash_as_they_say() -> None:
    for path in ("/home/user", "../home/user", "/usr/bin:/home/user", f"~{USER}"):
        assert model.public_command((*LEAD, "tool", path)) == SHOWN_LEAD + "tool '<hidden>'", path
        assert model.hashed_argv(("tool", path)) == ["tool", path], path
