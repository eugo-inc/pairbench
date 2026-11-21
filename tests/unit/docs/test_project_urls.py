# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every address of the project points at its repository, its documentation site or its package.

The package metadata, the citation, the README, ``llms.txt``, ``AGENTS.md``, the
contributing, security and notices files, the documentation pages, the showcases
and the agent skill may link to any other software. A link to the project
itself, its repository, its documentation, its package, or any other repository
or page of the same organisation, is one of three addresses: the repository on
GitHub, the documentation site, or the package's page on the package index. No
page links to a hosted pipeline run or shows a badge made from one, since the
repository's pipeline need not run in public.

The rule is written once for any project; the tests of its logic run it on a
made-up project, and the test of the tree runs it on this one.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

REPOSITORY = "https://github.com/eugo-inc/pairbench"
DOCS_ADDRESS = "https://eugo.io/docs/pairbench/"
PACKAGE_PAGE = "https://pypi.org/project/pairbench/"
# The documentation and the changelog in the package metadata, and the citation's address.
DOCUMENTATION_ADDRESSES = 3
FILES = (
    "pyproject.toml",
    "CITATION.cff",
    "README.md",
    "llms.txt",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
)
# The folders whose every document the rule covers.
FOLDERS = ("docs", "showcases", "skills")
URL = re.compile(r"https?://[^\s<>()\[\]{}\"'`|\\]+")
# A GitHub address without a web scheme: a clone address over SSH, a bare
# ``github.com/OWNER/REPO``, or a bare ``OWNER.github.io`` site.
GITHUB_CLONE = ("ssh://git@github.com/", "git@github.com:", "github.com/")
BARE = re.compile(
    r"(?<![\w.@/:-])(?:ssh://git@github\.com/|git@github\.com:|github\.com/|[\w-]+\.github\.io\b)"
    r"[^\s<>()\[\]{}\"'`|\\]*"
)
TRAILING = ".,;:!?*"
GITHUB_HOSTS = frozenset({"github.com", "www.github.com", "raw.githubusercontent.com"})
# The package index, its test instance included; a package's page is under ``/project/``.
PACKAGE_INDEX_SUFFIX = "pypi.org"
PAGES_SUFFIX = ".github.io"
# What a hosted pipeline run or a badge made from one looks like.
HOSTED_RUN = re.compile(r"github\.com/[^/]+/[^/]+/actions\b|badge\.svg|shields\.io", re.IGNORECASE)


def _path(url: str) -> list[str]:
    return [part.lower() for part in urlsplit(url).path.split("/") if part]


@dataclass(frozen=True)
class AddressRule:
    """The three addresses a project may be linked by, and how to tell its other addresses."""

    repository: str
    docs_address: str
    package_page: str

    @property
    def organisation(self) -> str:
        return _path(self.repository)[0]

    @property
    def project(self) -> str:
        return _path(self.repository)[1]

    @property
    def site(self) -> str:
        return (urlsplit(self.docs_address).hostname or "").lower()

    def is_project(self, url: str) -> bool:
        """Whether an address belongs to the project or its organisation."""
        host = (urlsplit(url).hostname or "").lower()
        path = _path(url)
        owner = path[0] if path else ""
        repo = path[1] if len(path) > 1 else ""
        if host in GITHUB_HOSTS:
            return owner == self.organisation or repo.startswith(self.project)
        if host.endswith(PAGES_SUFFIX):
            return host.startswith(self.organisation) or owner.startswith(self.project)
        if host == PACKAGE_INDEX_SUFFIX or host.endswith("." + PACKAGE_INDEX_SUFFIX):
            return owner == "project" and repo.startswith(self.project)
        return host == self.site or host.endswith("." + self.site)

    def allowed(self, url: str) -> bool:
        """Whether a project address is the repository, the documentation site or the package."""
        repository = re.escape(self.repository) + r"(?:\.git)?(?:[/#?].*)?$"
        package = re.escape(self.package_page.rstrip("/")) + r"(?:[/#?].*)?$"
        return (
            bool(re.match(repository, url))
            or url.startswith(self.docs_address)
            or bool(re.match(package, url))
        )


RULE = AddressRule(REPOSITORY, DOCS_ADDRESS, PACKAGE_PAGE)
EXAMPLE = AddressRule(
    "https://github.com/example-org/exampletool",
    "https://example.org/docs/exampletool/",
    "https://pypi.org/project/exampletool/",
)


def scanned(repo_root: Path, kit: Any) -> list[Path]:
    """The files the rule covers: the named project files and every document of the folders."""
    named = [repo_root / name for name in FILES]
    pages = [
        path for path in kit.documents(repo_root) if path.relative_to(repo_root).parts[0] in FOLDERS
    ]
    return named + pages


def credited_page(url: str, name: str) -> bool:
    """Whether an address is the credited page (``CREDITED_PAGE``), in a document that credits it.

    The page is the one other page of the organisation a document may link, and only the
    documents of ``CREDITED_IN`` name it.
    """
    address = url.split("#", 1)[0].rstrip("/")
    return address == f"https://{CREDITED_PAGE}" and name in CREDITED_IN


def _web(address: str) -> str:
    """An address found without a web scheme, written as the web address it names."""
    for start in GITHUB_CLONE:
        if address.startswith(start):
            return "https://github.com/" + address[len(start) :]
    return "https://" + address


def urls(text: str) -> Iterator[tuple[int, str]]:
    """Every web address in a text, with its line number.

    A GitHub address written as a clone address or without a scheme, and a
    ``github.io`` site without a scheme, are given as the web address they name.
    """
    for number, line in enumerate(text.splitlines(), start=1):
        found = [(match.start(), match.group(0)) for match in URL.finditer(line)]
        found += [(match.start(), _web(match.group(0))) for match in BARE.finditer(line)]
        for _start, url in sorted(found):
            yield number, url.rstrip(TRAILING)


def offenders(repo_root: Path, kit: Any) -> list[str]:
    found = []
    for path in scanned(repo_root, kit):
        name = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8")
        for number, url in urls(text):
            if RULE.is_project(url) and not RULE.allowed(url) and not credited_page(url, name):
                found.append(f"{name}:{number}: {url}")
    return found


def test_the_scan_reads_every_file_the_rule_names(repo_root: Path, kit: Any) -> None:
    files = [path.relative_to(repo_root).as_posix() for path in scanned(repo_root, kit)]
    assert [name for name in FILES if not (repo_root / name).is_file()] == []
    for page in (
        "docs/index.md",
        "docs/readme/README.in.md",
        "docs/showcases.md",
        "showcases/numpy-pip-vs-conda/README.md",
        "showcases/gpu-kernel/pairbench.toml",
        "skills/pairbench/SKILL.md",
        "skills/pairbench/references/wording.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        assert page in files


def test_every_project_address_is_one_the_rule_allows(repo_root: Path, kit: Any) -> None:
    assert offenders(repo_root, kit) == []


def test_the_package_metadata_and_the_citation_give_the_repository(repo_root: Path) -> None:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        project_urls = tomllib.load(handle)["project"]["urls"]
    assert project_urls
    assert [url for url in project_urls.values() if not RULE.allowed(url)] == []
    citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8")
    assert f'repository-code: "{REPOSITORY}"' in citation.splitlines()


def test_the_citation_gives_the_documentation(repo_root: Path) -> None:
    citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8")

    assert f'url: "{DOCS_ADDRESS}latest/"' in citation.splitlines()


def test_every_documentation_address_of_the_metadata_is_a_page_of_the_site(
    repo_root: Path, kit: Any
) -> None:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        project_urls = tomllib.load(handle)["project"]["urls"]
    citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8")
    addresses = [url for url in project_urls.values() if url.startswith(DOCS_ADDRESS)]
    addresses += [url for _, url in urls(citation) if url.startswith(DOCS_ADDRESS)]
    pages = [kit.linked_file(repo_root, url) for url in addresses]

    assert len(addresses) == DOCUMENTATION_ADDRESSES
    assert [url for url, page in zip(addresses, pages, strict=True) if page is None] == []
    assert [page for page in pages if page is not None and not page.is_file()] == []


def test_no_page_links_to_a_hosted_pipeline_run(repo_root: Path, kit: Any) -> None:
    found = [
        f"{path.relative_to(repo_root).as_posix()}:{number}: {url}"
        for path in scanned(repo_root, kit)
        for number, url in urls(path.read_text(encoding="utf-8"))
        if HOSTED_RUN.search(url)
    ]
    assert found == []


def test_the_credited_page_passes_only_in_the_document_that_credits_it() -> None:
    showcase = "showcases/numpy-pip-vs-conda/README.md"
    page = f"https://{CREDITED_PAGE}"
    assert credited_page(page, showcase)
    assert credited_page(page + "/#numpy", showcase)
    assert not credited_page(page, "showcases/gpu-kernel/README.md")
    assert not credited_page("https://example.com/pricing", showcase)


def test_the_rule_reads_the_organisation_project_and_site_of_this_project() -> None:
    assert (RULE.organisation, RULE.project, RULE.site) == ("eugo-inc", "pairbench", "eugo.io")
    assert RULE.is_project(REPOSITORY)
    assert RULE.allowed(REPOSITORY)
    assert RULE.allowed(REPOSITORY + "/tree/main/showcases/gpu-kernel")
    assert RULE.allowed(DOCS_ADDRESS + "reference/environment/#pairbench_config")


@pytest.mark.parametrize(
    "suffix",
    ["", "/", ".git", "/tree/main/showcases", "/blob/main/LICENSE", "#readme"],
)
def test_the_repository_and_its_pages_pass(suffix: str) -> None:
    url = EXAMPLE.repository + suffix
    assert EXAMPLE.is_project(url)
    assert EXAMPLE.allowed(url)


@pytest.mark.parametrize("suffix", ["", "guides/lines/", "reference/config/#run"])
def test_the_documentation_site_and_its_pages_pass(suffix: str) -> None:
    url = EXAMPLE.docs_address + suffix
    assert EXAMPLE.is_project(url)
    assert EXAMPLE.allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example-org/exampletool-next",
        "https://github.com/example-org/exampletool-next/tree/main/docs",
        "https://github.com/example-org/another-tool",
        "https://github.com/made-up-owner/exampletool",
        "https://raw.githubusercontent.com/example-org/exampletool-old/main/README.md",
        "https://example-org.github.io/exampletool/",
        "https://example.org/exampletool/",
        "https://docs.example.org/exampletool/",
        "http://github.com/example-org/exampletool",
        "http://example.org/docs/exampletool/",
    ],
)
def test_another_address_of_the_project_is_found(url: str) -> None:
    assert EXAMPLE.is_project(url)
    assert not EXAMPLE.allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/sharkdp/hyperfine",
        "https://docs.github.com/en/actions/reference/variables-reference",
        "https://pypi.org/project/numpy/",
        "https://pypi.org/user/example-org/",
        "https://docs.python.org/3.13/using/cmdline.html",
        "https://example.com/docs/exampletool/",
    ],
)
def test_an_address_of_other_software_is_not_the_project_s(url: str) -> None:
    assert not EXAMPLE.is_project(url)
    assert not RULE.is_project(url)


@pytest.mark.parametrize("suffix", ["", "0.1.0/", "#files"])
def test_the_package_index_page_of_the_project_passes(suffix: str) -> None:
    url = EXAMPLE.package_page + suffix
    assert EXAMPLE.is_project(url)
    assert EXAMPLE.allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://pypi.org/project/exampletool-next/",
        "https://pypi.org/project/ExampleTool-Old/",
        "https://test.pypi.org/project/exampletool/",
        "http://pypi.org/project/exampletool/",
    ],
)
def test_another_package_index_page_of_the_project_is_found(url: str) -> None:
    assert EXAMPLE.is_project(url)
    assert not EXAMPLE.allowed(url)


def test_the_package_index_page_this_project_links_is_its_own() -> None:
    assert RULE.package_page == "https://pypi.org/project/pairbench/"
    assert RULE.allowed("https://pypi.org/project/pairbench/")


def test_a_hosted_run_and_a_badge_are_found() -> None:
    assert HOSTED_RUN.search(REPOSITORY + "/actions/workflows/ci.yml")
    assert HOSTED_RUN.search(REPOSITORY + "/actions/workflows/ci.yml/badge.svg")
    assert HOSTED_RUN.search("https://img.shields.io/pypi/v/exampletool")
    assert not HOSTED_RUN.search("https://docs.github.com/en/actions/reference/variables-reference")


@pytest.mark.parametrize(
    ("text", "url"),
    [
        (
            "git clone git@github.com:example-org/exampletool-next.git",
            "https://github.com/example-org/exampletool-next.git",
        ),
        (
            "pip install git+ssh://git@github.com/example-org/exampletool-next",
            "https://github.com/example-org/exampletool-next",
        ),
        (
            "The source is at github.com/example-org/exampletool-next.",
            "https://github.com/example-org/exampletool-next",
        ),
        (
            "See example-org.github.io/exampletool/ for more.",
            "https://example-org.github.io/exampletool/",
        ),
    ],
)
def test_an_address_without_a_web_scheme_is_read_too(text: str, url: str) -> None:
    assert [found for _, found in urls(text)] == [url]
    assert EXAMPLE.is_project(url)
    assert not EXAMPLE.allowed(url)


def test_an_address_with_a_web_scheme_is_read_once() -> None:
    text = (
        "https://github.com/example-org/exampletool and git+https://github.com/example-org/x "
        "and https://docs.github.com/en/actions and https://example-org.github.io/exampletool/"
    )
    assert [url for _, url in urls(text)] == [
        "https://github.com/example-org/exampletool",
        "https://github.com/example-org/x",
        "https://docs.github.com/en/actions",
        "https://example-org.github.io/exampletool/",
    ]


def test_an_address_ends_where_the_markdown_around_it_ends() -> None:
    text = f"See [the source]({REPOSITORY}/tree/main/src), or <{DOCS_ADDRESS}>.\n`{REPOSITORY}`."
    assert [url for _, url in urls(text)] == [
        f"{REPOSITORY}/tree/main/src",
        DOCS_ADDRESS,
        REPOSITORY,
    ]


# The one page of the organisation outside the documentation site that the project names, and
# where: the NumPy showcase credits that page, once, for the names of the operations it times.
# The two tests that check this name it once each.
CREDITED_PAGE = "eugo.io/benchmarks"
CREDITED_IN = {
    "showcases/numpy-pip-vs-conda/README.md": 1,
    "tests/unit/docs/test_project_urls.py": 1,
    "tests/unit/docs/test_showcases.py": 1,
}
# Folders that hold no file of the project: version control, installed packages, caches, built
# and generated output, and what a showcase run writes. Matched by name at any depth.
NOT_PROJECT_FOLDERS = frozenset(
    {
        ".git",
        ".claude",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "node_modules",
        ".astro",
        "pairbench-runs",
        ".deps",
        ".build",
    }
)
# The same, matched by their place in the repository.
NOT_PROJECT_PATHS = frozenset(
    {"build", "dist", "site/dist", "site/src/content/docs", "site/src/generated"}
)


def project_files(repo_root: Path) -> list[Path]:
    """Every file of the repository that holds text, outside the folders above."""
    found = []
    for folder, names, files in os.walk(repo_root):
        here = Path(folder)
        names[:] = sorted(
            name
            for name in names
            if name not in NOT_PROJECT_FOLDERS
            and not name.endswith(".egg-info")
            and (here / name).relative_to(repo_root).as_posix() not in NOT_PROJECT_PATHS
            and not (here.parent.name == "showcases" and name == "models")
        )
        for name in sorted(files):
            path = here / name
            if path.is_file() and not path.is_symlink():
                found.append(path)
    return found


def _count(path: Path) -> int:
    try:
        return path.read_bytes().decode("utf-8").count(CREDITED_PAGE)
    except UnicodeDecodeError:
        return 0


def test_the_credited_page_is_named_once_in_the_whole_repository(repo_root: Path) -> None:
    found = {}
    for path in project_files(repo_root):
        count = _count(path)
        if count:
            found[path.relative_to(repo_root).as_posix()] = count
    assert found == CREDITED_IN


def test_the_scan_for_the_credited_page_reads_files_outside_the_documents(
    repo_root: Path, kit: Any
) -> None:
    read = {path.relative_to(repo_root).as_posix() for path in project_files(repo_root)}
    documents = {path.relative_to(repo_root).as_posix() for path in kit.documents(repo_root)}
    others = {
        "LICENSE",
        "pyproject.toml",
        "src/pairbench/__init__.py",
        "tests/unit/docs/test_project_urls.py",
    }
    assert others <= read
    assert documents <= read
