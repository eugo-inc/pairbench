# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""No published document breaks the public-text rules.

Every document is public. It says what the tool does and never where an
idea came from; it holds no history, no names of people, no ticket ids, no
dates of events, no measured performance number, no word of praise that
claims more than the tool does, and no address of the documentation other
than the one the site is built for.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

# Phrases no document may hold, matched without regard to case.
FORBIDDEN = {
    "history": re.compile(
        r"\b(previously|used to|we found|ported from|adapted from|formerly|no longer|"
        r"originally|until recently)\b",
        re.IGNORECASE,
    ),
    "praise": re.compile(
        r"\b(fastest|zero[- ]overhead|no overhead|blazing|the\s+only\s+tool|no\s+other\s+tool)\b",
        re.IGNORECASE,
    ),
    "todo with a name": re.compile(r"\bTODO\s*\("),
    "attribution": re.compile(
        r"(co-authored[-]by|generated\s(with|by)|noreply\@)",
        re.IGNORECASE,
    ),
    # A home folder of a machine; the neutral home a kept run is made with is no machine's.
    "a machine path": re.compile(r"(/opt/|/home/(?!user(?![\w/-]|\.\w))|/Users/)"),
    "a date": re.compile(r"\b(19|20)\d\d-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b"),
    "a driver branch id": re.compile(r"\bR\d{3}\b"),
    "a device id": re.compile(r"GPU-(?!0{8}-)[0-9a-f]{8}-[0-9a-f]{4}", re.IGNORECASE),
    "a hardware address": re.compile(r"\b[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}\b", re.I),
}

# The documentation's address, as the site's configuration sets it.
SITE = re.compile(r"^const SITE = '([^']*)';$", re.MULTILINE)
BASE = re.compile(r"^const BASE = '([^']*)';$", re.MULTILINE)
SITE_CONFIG = "site/astro.config.mjs"
# A project site on a hosting service's own domain.
HOSTED_PAGES = re.compile(r"\b[\w-]+\.(github|gitlab)\.io\b")

# A public page links only to files this repository holds: a relative link, read from the
# page's folder, names a file or folder that is there, and so does an address of the
# repository's files on GitHub; an address under the site root names a page the site builds.
# The check reads the documents written in Markdown or plain text, and the agents' guide for
# this repository. A link to any other address is not followed.
LINKED_SUFFIXES = frozenset({".md", ".txt"})
CLAUDE_FILE = "CLAUDE.md"
WEB = "https://"
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
# Where the made-up page of the link check's own test links on GitHub.
REPOSITORY_BLOB = "https://github.com/eugo-inc/pairbench/blob/main/"

# A number that reads like a measured result: a verdict line or a noise bar.
RESULT_LIKE = re.compile(r"\d+\.\d+x (faster|slower|higher|lower)|±\s?\d", re.IGNORECASE)
MADE_UP = re.compile(r"made[- ]up", re.IGNORECASE)


def test_the_scan_finds_the_documents(repo_root: Path, kit: Any) -> None:
    found = {path.relative_to(repo_root).as_posix() for path in kit.documents(repo_root)}

    for name in (
        "README.md",
        "AGENTS.md",
        "llms.txt",
        "site/navigation.json",
        "docs/index.md",
        "docs/readme/README.in.md",
    ):
        assert name in found


@pytest.mark.parametrize("rule", sorted(FORBIDDEN))
def test_no_document_holds_a_forbidden_phrase(repo_root: Path, kit: Any, rule: str) -> None:
    pattern = FORBIDDEN[rule]
    hits: list[str] = []
    for path in kit.documents(repo_root):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits.append(f"{path.relative_to(repo_root)}:{number}: {match.group(0)!r}")
    assert hits == []


def site_root(repo_root: Path) -> str:
    text = (repo_root / SITE_CONFIG).read_text(encoding="utf-8")
    site, base = SITE.search(text), BASE.search(text)
    assert site is not None and base is not None
    return site.group(1) + base.group(1)


def linked_pages(repo_root: Path, kit: Any) -> list[Path]:
    """Every public page the link check reads."""
    found = [path for path in kit.documents(repo_root) if path.suffix in LINKED_SUFFIXES]
    if (repo_root / CLAUDE_FILE).is_file():
        found.append(repo_root / CLAUDE_FILE)
    return sorted(found)


def unheld_targets(repo_root: Path, kit: Any, page: Path) -> list[str]:
    """The link targets of a page that name no file of this repository or no page of its site."""
    root = site_root(repo_root)
    unheld: list[str] = []
    for target in kit.links(page.read_text(encoding="utf-8")):
        if target.startswith("#"):
            continue
        if target.startswith(WEB):
            linked = kit.linked_file(repo_root, target)
            if linked is None and target.startswith(root):
                unheld.append(target)
                continue
        elif SCHEME.match(target):
            linked = None
        else:
            linked = page.parent / target.split("#", 1)[0]
        if linked is not None and not linked.exists():
            unheld.append(target)
    return unheld


def test_the_link_check_reads_every_kind_of_public_page(repo_root: Path, kit: Any) -> None:
    read = {path.relative_to(repo_root).as_posix() for path in linked_pages(repo_root, kit)}

    assert {
        "README.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "llms.txt",
        "skills/pairbench/SKILL.md",
        "skills/pairbench/references/wording.md",
        "docs/method/verdicts.md",
        "docs/readme/README.in.md",
        "showcases/gpu-kernel/README.md",
    } <= read


def test_every_public_page_links_only_to_files_the_repository_holds(
    repo_root: Path, kit: Any
) -> None:
    hits = [
        f"{page.relative_to(repo_root).as_posix()} -> {target}"
        for page in linked_pages(repo_root, kit)
        for target in unheld_targets(repo_root, kit, page)
    ]
    assert hits == []


def test_the_link_check_finds_each_link_to_what_the_repository_does_not_hold(
    repo_root: Path, kit: Any, tmp_path: Path
) -> None:
    root = site_root(repo_root)
    (tmp_path / "made-up-present.md").write_text("# Made up\n", encoding="utf-8")
    page = tmp_path / "made-up-page.md"
    page.write_text(
        "[present](made-up-present.md#part) and [absent](made-up-absent.md#part),\n"
        "[here](#part), [elsewhere](https://example.org/made-up-absent.md),\n"
        "[mail](mailto:made-up@example.org),\n"
        f"[held]({REPOSITORY_BLOB}README.md) and [not held]({REPOSITORY_BLOB}made-up-absent.md),\n"
        f"[a page]({root}latest/method/verdicts/) and [no page]({root}latest/made-up-absent/).\n"
        "```\n[in code](made-up-in-code.md)\n```\n",
        encoding="utf-8",
    )

    assert unheld_targets(repo_root, kit, page) == [
        "made-up-absent.md#part",
        f"{REPOSITORY_BLOB}made-up-absent.md",
        f"{root}latest/made-up-absent/",
    ]


def test_the_site_is_built_for_its_address(repo_root: Path) -> None:
    assert site_root(repo_root) == "https://eugo.io/docs/pairbench/"


def test_every_address_of_the_documentation_is_under_the_site_root(
    repo_root: Path, kit: Any
) -> None:
    root = site_root(repo_root)
    host_docs = root.split("/docs/", 1)[0] + "/docs/"
    outside: list[str] = []
    for path in kit.documents(repo_root):
        for found in re.findall(re.escape(host_docs) + r"[^\s)>\]\"'`]*", path.read_text("utf-8")):
            if not found.startswith(root):
                outside.append(f"{path.relative_to(repo_root)}: {found}")
    assert outside == []


def test_no_document_points_at_a_project_site_of_a_hosting_service(
    repo_root: Path, kit: Any
) -> None:
    holding = [
        path.relative_to(repo_root).as_posix()
        for path in kit.documents(repo_root)
        if HOSTED_PAGES.search(path.read_text(encoding="utf-8"))
    ]

    assert holding == []


def test_a_document_that_shows_result_like_numbers_says_they_are_made_up(
    repo_root: Path, kit: Any
) -> None:
    unmarked: list[str] = []
    for path in kit.documents(repo_root):
        if path.suffix != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        if RESULT_LIKE.search(text) and not MADE_UP.search(text):
            unmarked.append(path.relative_to(repo_root).as_posix())
    assert unmarked == []


def test_the_patterns_find_what_they_are_for() -> None:
    # The samples are put together at run time, so this file itself holds none
    # of the shapes it looks for.
    samples = {
        "history": "this flag " + "previously" + " did more",
        "praise": "the " + "fastest" + " way",
        "todo with a name": "TO" + "DO(x): finish",
        "attribution": "Co-" + "Authored-By: x",
        "a machine path": "/" + "home/x/bench",
        "a date": "on " + "-".join(["2001", "02", "03"]),
        "a driver branch id": "driver R" + "1" * 3,
        "a device id": "GPU-" + "1" * 8 + "-" + "a" * 4,
        "a hardware address": ":".join(["0a"] * 6),
    }
    for rule, sample in samples.items():
        assert FORBIDDEN[rule].search(sample), rule
    assert sorted(samples) == sorted(FORBIDDEN)
    assert not FORBIDDEN["a device id"].search("GPU-" + "-".join(["0" * 8, "0" * 4, "0" * 4]))
    # The neutral home a kept run is made with names no machine; any other home does.
    neutral_home = "/" + "home/user"
    for allowed in (f"HOME={neutral_home}", f"`HOME={neutral_home}`,", f'HOME = "{neutral_home}"'):
        assert not FORBIDDEN["a machine path"].search(allowed), allowed
    for other in ("/userx", "/user/x", "/user-x", "/user.x", "/x", "/"):
        sample = "/" + "home" + other
        assert FORBIDDEN["a machine path"].search(sample), sample
    assert RESULT_LIKE.search("1.23x faster   ±4.5%")
    assert not RESULT_LIKE.search("2.0x is the expected value")


def test_prose_leaves_code_blocks_out(kit: Any) -> None:
    text = "one\n```\ntwo\n```\nthree\n"

    assert [line for _number, line in kit.prose(text)] == ["one", "three"]
