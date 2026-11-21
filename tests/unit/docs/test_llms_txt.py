# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The llms files list every page of the navigation, in order, with its title and description."""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

import pytest

ITEM = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<target>[^)\s]+)\): (?P<description>.+)$")
LATEST = "https://eugo.io/docs/pairbench/latest/"
ELSEWHERE = (
    "skills/pairbench/SKILL.md",
    "https://github.com/eugo-inc/pairbench",
    "https://pypi.org/project/pairbench/",
)
STALE = "llms.txt is out of date: run python3 tools/docs_site.py llms\n"


def items(text: str) -> list[tuple[str, str, str]]:
    found = (ITEM.match(line) for line in text.splitlines())
    return [(m["title"], m["target"], m["description"]) for m in found if m]


def test_the_repository_llms_txt_is_what_the_generator_writes(
    repo_root: Path, docs_site: ModuleType
) -> None:
    written = (repo_root / "llms.txt").read_text(encoding="utf-8")

    assert written == docs_site.repository_llms(repo_root)


def test_the_repository_llms_txt_lists_the_pages_of_the_navigation_in_order(
    repo_root: Path, docs_site: ModuleType
) -> None:
    entries = docs_site.load_navigation(repo_root).entries
    targets = [t for _, t, _ in items((repo_root / "llms.txt").read_text(encoding="utf-8"))]

    assert targets[: len(entries)] == [f"docs/{entry.page}" for entry in entries]
    assert targets[len(entries) :] == list(ELSEWHERE)


def test_each_line_of_llms_txt_carries_the_title_and_description_of_its_page(
    repo_root: Path, docs_site: ModuleType
) -> None:
    build = docs_site.load_build(repo_root)
    listed = items((repo_root / "llms.txt").read_text(encoding="utf-8"))

    for title, target, description in listed[: len(build.pages)]:
        page = build.pages[target.removeprefix("docs/")]
        assert (title, description) == (page.title, page.description)


def test_every_relative_link_of_llms_txt_names_a_file_of_the_repository(repo_root: Path) -> None:
    targets = [t for _, t, _ in items((repo_root / "llms.txt").read_text(encoding="utf-8"))]
    relative = [t for t in targets if not t.startswith("https://")]

    assert len(relative) >= 40
    assert [t for t in relative if not (repo_root / t).is_file()] == []


def test_the_site_llms_txt_links_the_markdown_copy_of_every_page(
    repo_root: Path, docs_site: ModuleType
) -> None:
    build = docs_site.load_build(repo_root)
    text = docs_site.llms_text(build, site=True)
    targets = [t for _, t, _ in items(text)]

    assert targets[:2] == [f"{LATEST}index.md", f"{LATEST}install/index.md"]
    pages = targets[: len(build.navigation.entries)]
    assert all(t.startswith(LATEST) and t.endswith("/index.md") for t in pages)
    assert f"[llms-full.txt]({LATEST}llms-full.txt)" in text
    assert "https://github.com/eugo-inc/pairbench/blob/main/skills/pairbench/SKILL.md" in targets


def test_each_section_has_its_own_llms_txt_with_only_its_pages(
    repo_root: Path, docs_site: ModuleType
) -> None:
    build = docs_site.load_build(repo_root)

    for section in build.navigation.sections:
        text = docs_site.llms_text(build, site=True, sections=[section])
        assert text.startswith(f"# pairbench: {section.label}\n")
        assert len(items(text)) == len(section.entries)


def test_the_llms_check_fails_on_a_stale_file_and_says_how_to_fix_it(
    docs_site: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(docs_site, "repository_llms", lambda repo: "# not the list\n")

    code = docs_site.main(["llms", "--check"])

    captured = capsys.readouterr()
    assert (code, captured.out, captured.err) == (1, "", STALE)


def test_the_llms_check_passes_on_the_committed_file(
    docs_site: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = docs_site.main(["llms", "--check"])

    captured = capsys.readouterr()
    assert (code, captured.out, captured.err) == (0, "", "")
