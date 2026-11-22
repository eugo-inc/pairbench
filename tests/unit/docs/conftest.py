# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the documentation tests share: the documents of the repository and how to read them."""

from __future__ import annotations

import functools
import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

# The documents the public-text rules hold, by where they live. Under docs/,
# they are the pages of the site and the README's template.
DOCUMENT_ROOTS = ("docs/readme", "skills", "showcases")
DOCUMENT_FILES = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CITATION.cff",
    "THIRD_PARTY_NOTICES.md",
    "llms.txt",
    "site/navigation.json",
    "site/astro.config.mjs",
    "site/package.json",
    "site/src/pages/404.astro",
    "site/src/components/Footer.astro",
    "site/src/styles/brand.css",
    "site/src/content/i18n/en.json",
    "tools/docs_site.py",
    "tools/api_reference.py",
    "tools/share_image.py",
    "tools/launch_cost.py",
    "tools/hash_inputs.py",
    "src/pairbench/mcp/__init__.py",
    "src/pairbench/mcp/library.py",
    "src/pairbench/mcp/server.py",
)
TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".toml", ".yml", ".yaml", ".py", ".sh", ".lock", ".cff", ".json", ".cfg"}
)
SKIPPED_PARTS = frozenset({"__pycache__"})

# A page of the site is a Markdown file under docs/ that opens with front matter.
FRONT_MATTER = "---\n"

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(```|~~~)")


def documents(repo_root: Path) -> list[Path]:
    """Every document the public-text rules hold, as paths under the repository."""
    found: list[Path] = []
    for name in DOCUMENT_FILES:
        path = repo_root / name
        if path.is_file():
            found.append(path)
    found += site_pages(repo_root)
    for root in DOCUMENT_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(base).parts
            if SKIPPED_PARTS.intersection(relative[:-1]):
                continue
            if path.is_file() and (path.suffix in TEXT_SUFFIXES or path.name == "expected"):
                found.append(path)
    return found


def prose(text: str) -> Iterator[tuple[int, str]]:
    """The lines of a Markdown text outside fenced code blocks, with their numbers."""
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def links(text: str) -> list[str]:
    """The targets of the Markdown links and images of a text, outside code blocks."""
    found: list[str] = []
    for _number, line in prose(text):
        unquoted = re.sub(r"`[^`]*`", "", line)
        found += LINK.findall(unquoted)
        found += IMAGE.findall(unquoted)
    return found


def is_page(path: Path) -> bool:
    """Whether a Markdown file is a page of the site: it opens with front matter."""
    with path.open(encoding="utf-8") as handle:
        return handle.read(len(FRONT_MATTER)) == FRONT_MATTER


def site_pages(repo_root: Path) -> list[Path]:
    """Every Markdown page the documentation site publishes."""
    docs = repo_root / "docs"
    return sorted(path for path in docs.rglob("*.md") if is_page(path))


# Where a file of the repository is read on GitHub: the README and the package metadata
# link there, and to the pages of the documentation site.
REPOSITORY_FILES = (
    "https://github.com/eugo-inc/pairbench/blob/main/",
    "https://github.com/eugo-inc/pairbench/tree/main/",
)


@functools.cache
def page_sources(repo_root: Path) -> dict[str, Path]:
    """The web address of every page of the documentation site, with the file under
    ``docs/`` it is built from."""
    tool = load_tool(repo_root, "docs_site")
    address = tool.read_address(repo_root)
    return {
        address.site + tool.page_path(address, page): repo_root / "docs" / page
        for page in tool.site_pages(repo_root)
    }


def linked_file(repo_root: Path, target: str) -> Path | None:
    """The file of the repository a link written from the root names, or ``None``.

    A relative target names its path; the address of a page of the documentation site
    names the page under ``docs/`` it is built from; a GitHub address of the repository's
    files names the file or folder at its path. Any other address names nothing here.
    """
    path = target.split("#", 1)[0]
    if not path.startswith("https://"):
        return repo_root / path
    sources = page_sources(repo_root)
    if path in sources:
        return sources[path]
    for start in REPOSITORY_FILES:
        if path.startswith(start):
            return repo_root / path[len(start) :]
    return None


class Kit:
    """The helpers above, handed to a test as one fixture."""

    documents = staticmethod(documents)
    prose = staticmethod(prose)
    links = staticmethod(links)
    site_pages = staticmethod(site_pages)
    linked_file = staticmethod(linked_file)


@pytest.fixture(scope="session")
def kit() -> Kit:
    return Kit()


def load_tool(repo_root: Path, name: str) -> ModuleType:
    """Load a script under tools/ as a module."""
    path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"pairbench_tool_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def docs_site(repo_root: Path) -> ModuleType:
    """The generator of the documentation site, ``tools/docs_site.py``."""
    return load_tool(repo_root, "docs_site")


@pytest.fixture(scope="session")
def api_reference(repo_root: Path) -> ModuleType:
    """The generator of the page of public Python names, ``tools/api_reference.py``."""
    return load_tool(repo_root, "api_reference")
