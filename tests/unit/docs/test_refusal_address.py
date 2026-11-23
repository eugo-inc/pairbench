# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every exit code and text code has its own entry with cause and fix, and a refusal names it."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pairbench.errors import (
    CODES,
    CODES_PAGE,
    DOCS_ADDRESS,
    EXIT_CODES,
    docs_address,
    docs_line,
)
from pairbench.model import TOOL_VERSION
from pairbench.report import odds

PAGE = "docs/reference/exit-codes.md"
USAGE_ADDRESS = "https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_usage"
POOL_ADDRESS = "https://eugo.io/docs/pairbench/12.3/reference/exit-codes/#e_pool_same"
COMPARE_STDERR = (
    "E_USAGE: compare needs capture files or --side NAME=file:GLOB\n"
    f"pairbench: see {USAGE_ADDRESS}\n"
)
HEADING = re.compile(r"^### (.+)$", re.MULTILINE)
TABLE_ROW = re.compile(r"^\| `(E_[A-Z_]+)` \| ([0-9]+(?: or [0-9]+)?) \|", re.MULTILINE)


def entries(text: str) -> dict[str, str]:
    """The ``###`` entries of the page: heading -> the text below it, up to the next heading."""
    parts = re.split(r"^#{2,3} ", text, flags=re.MULTILINE)
    found: dict[str, str] = {}
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        found[heading.strip()] = body
    return found


def test_the_address_of_a_text_code_names_its_entry_in_the_release_folder() -> None:
    assert docs_address("E_USAGE", "0.2.0") == USAGE_ADDRESS
    assert docs_address("E_POOL_SAME", "12.3.4rc1") == POOL_ADDRESS
    assert docs_line("E_USAGE", "0.2.7") == f"pairbench: see {USAGE_ADDRESS}"


def test_a_code_outside_the_table_has_no_address() -> None:
    with pytest.raises(ValueError, match=r"^text code is not in the table: E_MADE_UP$"):
        docs_address("E_MADE_UP", "0.1.0")


def test_the_address_is_the_site_setting_and_the_page_is_in_the_navigation(
    repo_root: Path, docs_site: ModuleType
) -> None:
    address = docs_site.read_address(repo_root)
    pages = [entry.page for entry in docs_site.load_navigation(repo_root).entries]

    assert address.root == DOCS_ADDRESS
    assert PAGE.removeprefix("docs/") in pages
    assert docs_site.slug(PAGE.removeprefix("docs/")) + "/" == CODES_PAGE
    assert docs_site.version_folder(docs_site.read_version(repo_root)) in docs_address(
        "E_USAGE", TOOL_VERSION
    )


def test_the_error_rate_link_is_the_latest_page_under_the_site_setting(
    repo_root: Path, docs_site: ModuleType
) -> None:
    page = "method/error-rates.md"
    pages = [entry.page for entry in docs_site.load_navigation(repo_root).entries]
    root = docs_site.read_address(repo_root).root
    link = odds.ERROR_RATES_PAGE

    assert page in pages
    assert link == f"{root}{docs_site.LATEST}/{docs_site.slug(page)}/"


@pytest.mark.parametrize("code", sorted(CODES))
def test_every_text_code_has_an_entry_with_its_exit_code_cause_and_fix(
    repo_root: Path, code: str
) -> None:
    text = (repo_root / PAGE).read_text(encoding="utf-8")
    exits = dict(TABLE_ROW.findall(text))[code]
    paragraphs = [p for p in entries(text).get(code, "").strip().split("\n\n") if p]

    assert exits.split(" ")[0] == str(CODES[code].exit_code)
    assert paragraphs[:1] == [f"Exit code {exits}."]
    assert [p.split(" ")[0] for p in paragraphs[1:3]] == ["**Cause.**", "**Fix.**"]


@pytest.mark.parametrize("exit_code", sorted(EXIT_CODES))
def test_every_exit_code_has_an_entry_with_its_cause_and_fix(
    repo_root: Path, exit_code: int
) -> None:
    body = entries((repo_root / PAGE).read_text(encoding="utf-8")).get(f"Exit code {exit_code}")
    paragraphs = [p for p in (body or "").strip().split("\n\n") if p]

    assert [p.split(" ")[0] for p in paragraphs[:2]] == ["**Cause.**", "**Fix.**"]
    assert all(len(p.split()) > 2 for p in paragraphs[:2])


def test_the_page_has_an_entry_for_nothing_else(repo_root: Path) -> None:
    headings = HEADING.findall((repo_root / PAGE).read_text(encoding="utf-8"))
    expected = [f"Exit code {code}" for code in sorted(EXIT_CODES)] + list(CODES)

    assert headings == expected


def test_a_refusal_prints_the_address_of_its_entry_after_its_line(
    repo_root: Path, tmp_path: Path
) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH")}
    env["PYTHONPATH"] = str(repo_root / "src")

    done = subprocess.run(
        [sys.executable, "-m", "pairbench", "compare"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert (done.returncode, done.stdout, done.stderr) == (2, "", COMPARE_STDERR)
