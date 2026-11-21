# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every page has a short description, opens with a direct answer and uses one term per idea."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import pairbench
import pairbench.stats

REPO = Path(__file__).resolve().parents[3]
PAGES = sorted(
    p.relative_to(REPO / "docs").as_posix()
    for p in (REPO / "docs").rglob("*.md")
    if p.read_text("utf-8").startswith("---\n")
)
DESCRIPTION_LIMIT = 160
FRONT = re.compile(r"\A---\ndescription: \"(?P<description>[^\"\n]+)\"\n---\n\n(?P<rest>.*)", re.S)
OPENING_SENTENCES = 2
SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9`(\[])")
NOT_A_PARAGRAPH = re.compile(r"^(\||- |\* |\d+\. |>|```|~~~|#|<|!\[)")
GUIDE_VERBS = ("Compare", "Build", "Choose", "Run", "Read", "Use", "Add", "Give", "Drive")
API_PAGE = "reference/python-names.md"
HOME_PAGE = "index.md"
# What the first sentence of the home page names: what kind of tool pairbench is, under
# which licence, and the question it answers.
WHAT_IT_IS = ("open-source", "Apache-2.0", "Python", "command-line", "real or noise")

# One term per idea: the term the pages use, and the words that would name the same idea.
SYNONYMS = {
    "config file": ("configuration file", "settings file"),
    "noise floor": ("noise threshold", "noise level", "noise band"),
    "side": ("variant", "contender", "candidate"),
    "twin": ("clone", "doppelganger"),
    "text code": ("error code", "error id"),
    "exit code": ("return code",),
    "p-value": ("p value",),
    "load tool": ("load generator",),
    "machine check": ("machine gate", "health check"),
}


def page_text(page: str) -> str:
    return (REPO / "docs" / page).read_text(encoding="utf-8")


def split_page(page: str) -> tuple[str, str, str]:
    """The description, the title and the body of a page."""
    found = FRONT.match(page_text(page))
    assert found is not None, f"{page}: front matter is not one quoted description"
    title, _, body = found["rest"].partition("\n")
    return found["description"], title, body


def prose(body: str) -> str:
    """The text of a page outside fenced blocks, with code spans and link targets removed."""
    kept: list[str] = []
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(line)
    text = re.sub(r"`[^`]*`", "CODE", "\n".join(kept))
    text = re.sub(r"\]\([^)]*\)", "]", text)
    return re.sub(r"<[^>]+>", "", text)


def sentences(paragraph: str) -> list[str]:
    plain = " ".join(prose(paragraph).split())
    plain = re.sub(r"\b(e\.g|i\.e|etc|vs)\.", r"\1", plain)
    return SENTENCE_END.split(plain)


def test_the_test_sees_every_page_of_the_navigation() -> None:
    assert len(PAGES) >= 48
    assert {"index.md", "reference/exit-codes.md", API_PAGE} <= set(PAGES)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_a_short_description_in_its_front_matter(page: str) -> None:
    description, _, _ = split_page(page)

    assert 0 < len(description) <= DESCRIPTION_LIMIT
    assert description == description.strip()
    assert "](" not in description


@pytest.mark.parametrize("page", PAGES)
def test_every_page_opens_with_its_title_and_a_short_direct_answer(page: str) -> None:
    _, title, body = split_page(page)
    first = body.strip("\n").split("\n\n")[0]

    assert title.startswith("# ")
    assert re.search(r"^# ", prose(body), re.MULTILINE) is None
    assert NOT_A_PARAGRAPH.match(first) is None
    assert 1 <= len(sentences(first)) <= OPENING_SENTENCES


@pytest.mark.parametrize("page", [p for p in PAGES if p.startswith("guides/")])
def test_every_guide_title_is_a_task_or_a_question(page: str) -> None:
    _, title, _ = split_page(page)
    words = title.removeprefix("# ")

    assert words.startswith(GUIDE_VERBS) or words.endswith("?")


LIST_START = re.compile(r"^\s*1[.)]\s")
NOT_PROSE = re.compile(r"^\s*(\||#|>|<)")


def list_starts_inside_paragraphs(body: str) -> list[str]:
    """The lines that a page shows as a new numbered list in the middle of a paragraph.

    A line that opens with ``1.`` or ``1)`` right after a line of running text starts a
    numbered list there, so a wrapped sentence must not put such a number at a line start.
    """
    found: list[str] = []
    fenced = False
    before = ""
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            before = ""
            continue
        if fenced:
            continue
        if LIST_START.match(line) and before.strip() and NOT_PROSE.match(before) is None:
            found.append(line.strip())
        before = line
    return found


def test_the_list_finder_finds_a_number_at_the_start_of_a_wrapped_line() -> None:
    wrapped = "- The quotient is above,\n  below or equal to\n  1. Swapping turns it over.\n"
    item = "- The quotient is above, below or equal to\n  1) Swapping turns it over.\n"
    listed = "Steps:\n\n1. Run it.\n2. Read it.\n\n| a |\n1. Run it.\n"

    assert list_starts_inside_paragraphs(wrapped) == ["1. Swapping turns it over."]
    assert list_starts_inside_paragraphs(item) == ["1) Swapping turns it over."]
    assert list_starts_inside_paragraphs(listed) == []


@pytest.mark.parametrize("page", PAGES)
def test_no_wrapped_line_of_a_page_starts_a_numbered_list(page: str) -> None:
    _, _, body = split_page(page)

    assert list_starts_inside_paragraphs(body) == []


def test_the_home_page_says_first_what_pairbench_is() -> None:
    _, _, body = split_page(HOME_PAGE)
    first = sentences(body.strip("\n").split("\n\n")[0])[0]

    assert first.startswith("pairbench is ")
    assert [words for words in WHAT_IT_IS if words not in first] == []


def test_the_sentence_counter_counts_sentences() -> None:
    assert len(sentences("One. Two `a.b` is [three](x.md). Four?")) == 3
    assert len(sentences("Use a config file, e.g. the one below.")) == 1


@pytest.mark.parametrize("term", sorted(SYNONYMS))
def test_one_term_names_one_idea_across_the_site(term: str) -> None:
    found: list[str] = []
    for page in PAGES:
        text = prose(split_page(page)[2]).lower()
        for other in SYNONYMS[term]:
            if re.search(rf"\b{re.escape(other)}s?\b", text):
                found.append(f"{page}: {other!r} where the pages say {term!r}")

    assert found == []


def test_every_exported_python_name_has_its_own_anchor() -> None:
    text = page_text(API_PAGE)
    names = [f"pairbench.{n}" for n in pairbench.__all__]
    names += [f"pairbench.stats.{n}" for n in pairbench.stats.__all__]
    names += ["pairbench.errors.Refusal"]

    assert [n for n in names if f'<span id="{n}"></span>' not in text] == []
    assert len(names) >= 40


def test_every_link_into_the_api_page_names_an_anchor_it_has() -> None:
    text = page_text(API_PAGE)
    links: list[str] = []
    for page in PAGES:
        links += re.findall(r"python-names\.md#([\w.]+)\)", page_text(page))

    assert len(links) >= 8
    assert [a for a in links if f'<span id="{a}"></span>' not in text] == []


def test_the_api_page_matches_the_source_and_carries_every_anchor(api_reference: object) -> None:
    text = page_text(API_PAGE)

    assert text == api_reference.render(REPO)  # type: ignore[attr-defined]
    missing = [
        a
        for a in api_reference.anchors(REPO)  # type: ignore[attr-defined]
        if f'<span id="{a}"></span>' not in text
    ]
    assert missing == []


COMPARISON_PAGE = "comparison.md"
READ_LINE = re.compile(r"^Read: (?P<read>.+?) at (?:commit )?`?(?P<version>[\w.]+)`?\.$", re.M)
LINK_TARGET = re.compile(r"\]\((?P<target>[^)\s]+)\)")
TOOLS_DESCRIBED = 5


def test_every_link_to_another_tool_s_documentation_is_to_the_version_read() -> None:
    text = (REPO / "docs" / COMPARISON_PAGE).read_text(encoding="utf-8")
    folded = re.sub(r"(?<=\S)\n(?=\S)", " ", text)
    reads = list(READ_LINE.finditer(folded))
    assert len(reads) == TOOLS_DESCRIBED
    for read in reads:
        targets = LINK_TARGET.findall(read["read"])
        assert targets, read["read"]
        assert [t for t in targets if read["version"] not in t] == [], read["version"]
