# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The notes for coding agents at the root: what they point at must exist and agree.

``CLAUDE.md`` pulls in ``AGENTS.md`` and names the skill, the wording rules, the schema
folder and the verdict words. ``.claude/skills/pairbench`` is a link to the skill that ships
in the wheel, so an agent working in this repository loads the same skill a user gets.
"""

from __future__ import annotations

import os
import re
import typing
from pathlib import Path

from pairbench.model import Verdict

ROOT = Path(__file__).resolve().parents[3]
NOTES = ROOT / "CLAUDE.md"
SKILL_LINK = ROOT / ".claude" / "skills" / "pairbench"
SKILL_LINK_TARGET = "../../skills/pairbench"
SKILL = ROOT / "skills" / "pairbench"
SETUP_HEADING = "## Set up, test and lint"


def _notes() -> str:
    return NOTES.read_text(encoding="utf-8")


def test_the_notes_pull_in_agents_md_first() -> None:
    assert _notes().splitlines()[0] == "@AGENTS.md"
    assert (ROOT / "AGENTS.md").is_file()


def test_every_path_the_notes_name_exists() -> None:
    named = re.findall(r"`((?:skills|src)/[^`\s]+)`", _notes())
    assert named, "the notes name no repository paths"
    assert [path for path in named if not (ROOT / path).exists()] == []


def test_the_setup_section_the_notes_cite_is_in_agents_md() -> None:
    assert '"Set up, test and lint"' in _notes()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    assert SETUP_HEADING in agents


def test_the_notes_list_every_verdict_word_and_no_other() -> None:
    sentence = re.search(r"own words: (.+?), with the case", _notes(), re.S)
    assert sentence is not None
    listed = {word.strip() for word in re.split(r",|\bor\b", " ".join(sentence[1].split()))}
    assert listed - {""} == set(typing.get_args(Verdict))


def test_the_claude_skill_folder_is_a_link_to_the_shipped_skill() -> None:
    assert SKILL_LINK.is_symlink()
    assert os.readlink(SKILL_LINK) == SKILL_LINK_TARGET
    assert SKILL_LINK.resolve() == SKILL.resolve()
    assert (SKILL_LINK / "SKILL.md").is_file()


AGENT_PAGE = ROOT / "docs" / "agents.md"
FOLDER_TABLE_HEADER = "| Product | Project folder | Personal folder |"
FOLDER = re.compile(r"^`[.~][^`\s]*/skills/`$")
PRODUCTS = 3


def test_the_skill_table_gives_both_folders_for_every_product() -> None:
    lines = AGENT_PAGE.read_text(encoding="utf-8").splitlines()
    start = lines.index(FOLDER_TABLE_HEADER) + 2
    rows = []
    for line in lines[start:]:
        if not line.startswith("| "):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    assert len(rows) == PRODUCTS
    for product, project, personal in rows:
        assert FOLDER.match(project), product
        assert FOLDER.match(personal) and personal.startswith("`~/"), product
