# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy and the results reference state the known limit of the hashes.

A published hash covers paths and hosts as typed, so that two sides which differ in one stay
apart. So a reader who knows the rest of a side's command can confirm a guessed user name,
host or path by hashing the guess. Both pages say so in one paragraph, with the way to avoid
it: keep such values out of the side's command, run it from a neutral folder, and pass values
through ``launch.env_pass``. The security policy says it under a heading of known limits.
"""

from __future__ import annotations

from pathlib import Path

import pytest

COVERS = "A published hash covers paths and hosts as typed"
GUESS = (
    "so a reader who knows the rest of a side's command can confirm a guessed user name, "
    "host or path by hashing the guess."
)
AVOID = (
    "To avoid it, keep such values out of the side's command: run it from a neutral folder, "
    "and pass values to it through `launch.env_pass`, which no hash covers."
)
SECURITY = "SECURITY.md"
RESULTS = "docs/reference/results-schema.md"
LIMITS_HEADING = "## Known limits of the hashes"


def paragraphs(path: Path) -> list[str]:
    """Each paragraph or list item of a page, its lines joined into one."""
    found: list[str] = []
    for block in path.read_text(encoding="utf-8").split("\n\n"):
        items: list[str] = []
        for line in block.splitlines():
            if line.lstrip().startswith("- ") or not items:
                items.append(line.strip().removeprefix("- "))
            else:
                items[-1] += " " + line.strip()
        found += items
    return found


@pytest.mark.parametrize("page", [SECURITY, RESULTS])
def test_a_page_states_the_known_limit_of_the_hashes_in_one_paragraph(
    repo_root: Path, page: str
) -> None:
    holding = [text for text in paragraphs(repo_root / page) if COVERS in text]

    assert len(holding) == 1
    assert f"{COVERS}, {GUESS}" in holding[0]
    assert AVOID in holding[0]


def test_the_security_policy_states_it_under_its_known_limits(repo_root: Path) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = text.split(LIMITS_HEADING + "\n", 1)

    assert len(section) == 2
    assert COVERS in section[1].split("\n## ", 1)[0]
