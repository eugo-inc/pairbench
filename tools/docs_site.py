# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Build the documentation site from the pages in ``docs/`` and check what was built.

The pages stay Markdown files in ``docs/``, readable as they are. The site is an
Astro project with Starlight in ``site/``. One build runs three steps:

1. prepare: copy every page the navigation (``site/navigation.json``) lists into
   ``site/src/content/docs/latest/``, with the page's title and description in
   its front matter, its links made into addresses of the site, an anchor for
   every config key and flag on the reference pages, a link to its Markdown
   copy, and its structured data (schema.org JSON-LD: the software and the
   organisation that publishes it on the home page, an article on every other
   page, and the breadcrumbs of the sidebar);
   write ``site/src/generated/site.json`` with the sidebar and the tags that name
   the share image. Before it removes or writes anything it checks the pages, the
   pages generated from the code, the version, that ``site/public/share.png``
   holds what ``tools/share_image.py`` draws, that each link written
   ``[text](target)`` or as a reference link (``[text][label]`` with its definition
   ``[label]: target``) names a page of the site or a file of the repository, and
   that each anchor such a link names is one the text gives: the id of a
   heading, an id written in the page, or the anchor of a config key or flag, on
   a page of the site or in a Markdown file of the repository, and a line,
   ``#L<n>``, or a range of lines, ``#L<a>-L<b>``, of any other file of the
   repository, or of a Markdown file shown as plain text, ``?plain=1``. A link
   to a file of the repository by its address on the forge, the ``Source``
   address of ``pyproject.toml`` followed by ``/blob/main/``, ``/tree/main/``,
   ``/blame/main/`` or ``/raw/main/``, or by the same owner and name on the
   forge's host of raw files followed by ``/main/``, must name a file or folder
   the repository has, and its anchor is checked the same way; a blame or raw
   page shows a file only, and a raw file has no anchor. So must such an address
   written as an autolink, ``<address>``, bare, with its scheme or starting with
   ``www.`` wherever the site shows it as a link, in quotes or brackets too, such
   as the ``src`` of an image, or as the ``href`` of a link written in HTML. A
   page that names a repository of the project other than its public one, of the
   same owner with a name that starts with the project's, by its address on the
   forge, on its host of raw files, on its interface for programs, of its
   archives or of its pages, or by its ssh address, and in code too, is refused.
   In a git checkout the repository has the files git
   tracks and the folders that hold them, so a link to a file a build leaves,
   such as one in ``site/dist/``, is refused; a checkout that holds ``.git``
   where git is missing, cannot start or refuses to read it is refused, and a
   copy without ``.git`` is checked by the files it holds. A build these checks
   refuse removes, writes and installs nothing.
2. Astro builds the pages, the search index and the sitemap into ``site/dist/``.
   A warning or an error in its output fails the build.
3. finish: write the Markdown copy of every page beside it, the llms files,
   ``robots.txt``, and the base folder's page with its Markdown page and its own
   ``llms.txt`` and ``llms-full.txt``; copy the latest pages to the folder of the
   release; then check every link, anchor and asset of the built site, the
   anchors Starlight adds and a link written in HTML among them, that the share
   image it publishes holds what ``tools/share_image.py`` draws, and that
   nothing is fetched from another host. A link to another host is not followed.

A refused share image is refused with its cause: an extra chunk, a bad checksum,
another row filter, data after the end and the like.

Usage::

    python3 tools/docs_site.py build     # prepare, install the packages if needed, Astro, finish
    python3 tools/docs_site.py llms      # write the repository's llms.txt
    python3 tools/docs_site.py llms --check
    python3 tools/docs_site.py check     # check a site already built in site/dist

Only the standard library is used. Node, npm and the packages of ``site/`` are
needed for the Astro step alone; ``npm ci`` installs the packages from the
lockfile. git is needed in a git checkout, to read which files git tracks.
"""

from __future__ import annotations

import argparse
import functools
import html.parser
import json
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tomllib
import types
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

REPO = Path(__file__).resolve().parent.parent
SITE = "site"
DOCS = "docs"
DIST = "dist"
NAVIGATION = "site/navigation.json"
ASTRO_CONFIG = "site/astro.config.mjs"
CONTENT = "site/src/content/docs"
GENERATED = "site/src/generated"
LLMS = "llms.txt"
LLMS_FULL = "llms-full.txt"
LATEST = "latest"
SOURCE = "https://github.com/eugo-inc/pairbench"
DESCRIPTION_LIMIT = 160
VERSION_META = "pairbench-version"
# The pages generated from the code, each with the script that writes it.
GENERATED_PAGES = {"reference/python-names.md": "tools/api_reference.py"}
# The image a social site or a chat shows beside a shared page. Its script draws it into
# the folder Astro copies to the base of the site as it is; every page names it by its
# address, its size and its alt text.
SHARE_IMAGE = "share.png"
SHARE_SOURCE = "site/public/share.png"
SHARE_TOOL = "tools/share_image.py"
TOOLS = Path(__file__).resolve().parent
# The structured data of the pages, in schema.org terms: the vocabulary, the licence's
# address, the page that describes the software, and the characters of JSON escaped inside
# a script element.
SCHEMA = "https://schema.org"
LICENSE_ADDRESS = "https://www.apache.org/licenses/LICENSE-2.0"
# The systems the software runs on, the ones its package classifiers name.
OPERATING_SYSTEMS = "Linux, macOS"
# The organisation that publishes the software: the package's author, the citation's author
# and the holder of the copyright in NOTICE and in the licence header. The home page defines
# it at the root of the host.
PUBLISHER = "Eugo, Inc."
HOME_PAGE = "index.md"
# The marks of the site, as the content files of the pages name them; the same files as
# docs/readme/mark-light.svg and mark-dark.svg.
MARKS = {"light": "site/src/assets/mark-light.svg", "dark": "site/src/assets/mark-dark.svg"}
# The buttons of the home page's hero: their text, the page or address they lead to, their
# kind and their icon. A page is named by its file under docs/.
HERO_ACTIONS = (
    ("Quick start", "quickstart.md", "primary", "right-arrow"),
    ("Install", "install.md", "secondary", None),
    ("Source", SOURCE, "minimal", "external"),
)
# The badges of the home page, drawn by the build from the package's own metadata into
# BADGES under the base folder: each its file, its label and its colour. Nothing is fetched.
BADGES = "badges"
BADGE_COLOURS = {"version": "#7c3aed", "python": "#048196", "licence": "#4b5066"}
BADGE_LABEL_COLOUR = "#1c2135"
# The width of a badge's text, in pixels per character at its size: the text is drawn to
# exactly that width, so the badge does not depend on the fonts of the reader's machine.
BADGE_CHARACTER = 6.4
BADGE_PAD = 7.0
# Starlight's components a page may use, each written in the page as plain Markdown between
# two comment lines that a reader of the file does not see:
#
#   <!-- steps --> ... <!-- /steps -->  an ordered list, shown as numbered steps;
#   <!-- tabs --> ... <!-- /tabs -->    tabs, each opened by a line that holds only its label
#                                       in bold, **label**;
#   <!-- cards --> ... <!-- /cards -->  a grid of cards, each opened by a heading ### Title,
#                                       optionally followed by a line <!-- icon: NAME -->.
#
# A page that holds one is written for Starlight as MDX, with the components imported.
COMPONENT_IMPORT = (
    "import { Card, CardGrid, Steps, TabItem, Tabs } from '@astrojs/starlight/components';"
)
MARKER = re.compile(r"^<!--\s*(/?)(steps|tabs|cards)\s*-->$")
COMMENT_LINE = re.compile(r"^<!--.*-->$")
ICON_LINE = re.compile(r"^<!--\s*icon:\s*([a-z0-9-]+)\s*-->$")
OPENING = {"steps": "<Steps>", "tabs": "<Tabs>", "cards": "<CardGrid>"}
CLOSING = {"steps": "</Steps>", "tabs": "</Tabs>", "cards": "</CardGrid>"}
TAB_LABEL = re.compile(r"^\*\*([^*]+)\*\*$")
CARD_TITLE = re.compile(r"^### (.+)$")
SCRIPT_SAFE = str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"})

# Crawlers of search engines are covered by the first group; these are named so
# that a reader of the file sees that answer engines and AI crawlers may read too.
AI_CRAWLERS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-SearchBot",
    "Claude-User",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "Applebot-Extended",
    "Amazonbot",
    "CCBot",
    "Meta-ExternalAgent",
    "DuckAssistBot",
    "MistralAI-User",
    "cohere-ai",
)

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FRONT_LINE = re.compile(r"^([a-z_]+):\s*(.*)$")
TITLE = re.compile(r"^# (.+)$")
FENCE = re.compile(r"^\s*(```|~~~)")
# A link written [text](target): the target bare or in angle brackets, then an optional title
# in double quotes, single quotes or parentheses. Spaces and tabs, with at most one line break,
# may stand around the target inside the parentheses.
LINK = re.compile(
    r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]\((?P<lead>[ \t]*(?:\n[ \t]*)?)"
    r"(?P<target><[^<>\n]*>|[^()\s]+)"
    r"(?P<title>\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?(?P<tail>[ \t]*(?:\n[ \t]*)?)\)"
)
# The definition of a reference link, [label]: target, on a line of its own after at most three
# spaces; the target is on the same line or the next, ends at a space or the end of its line, and
# the end of its line or a title follows it. A footnote's [^label]: is no link.
DEFINITION = re.compile(
    r"^(?P<label> {0,3}\[(?!\^)[^\[\]]+\]:[ \t]*(?:\n[ \t]*)?)(?P<target><[^<>\n]*>|\S+(?!\S))"
    r"(?=[ \t]*(?:$|[\"'(]))",
    re.MULTILINE,
)
CODE_SPAN = re.compile(r"(`+).+?\1")
# An address written as a link of its own: an autolink, <https://...>; a bare address, with its
# scheme or starting with www. and none, which GitHub Flavored Markdown shows as a link; and the
# href of a link written in HTML. Schemes and attribute names are read in any capitals. A bare
# address is read where the site's renderer shows it as a link: one with its scheme after
# anything but a letter, and one that starts with www. after anything but a letter, a digit or a
# colon; so it is read in quotes and brackets too, as in the src of an image or an href without
# quotes written in HTML. It ends at a space, a bracket, a parenthesis or a quote; a full stop,
# comma or other mark that ends a sentence after it is no part of it. One may follow a
# parenthesis, but not the "](" that opens the target of a link, which is read as the link.
ADDRESS_AUTOLINK = re.compile(r"<(https?://[^<>\s]+)>", re.IGNORECASE)
BARE_ADDRESS = re.compile(
    r"(?<!\]\()(?:(?<![A-Za-z])https?://|(?<![A-Za-z0-9:])www\.)[^\s<>()\[\]\"'`]+",
    re.IGNORECASE,
)
HREF = re.compile(r"\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
SENTENCE_MARKS = ".,:;!?*_~"
ADDRESS_LINE = re.compile(r"^const (SITE|BASE) = '([^']*)';$", re.MULTILINE)
KEY_CELL = re.compile(r"`([a-z_]+(?:\.[A-Za-z_]+)+)`")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
# The address of a repository on its forge, and the anchor of a line of a file the forge shows,
# #L<n>, or of a range of its lines, #L<a>-L<b>, each number in the digits 0 to 9.
SOURCE_FORM = re.compile(r"https://[^/\s?#]+/[^/\s?#]+/[^/\s?#]+/?")
LINE_ANCHOR = re.compile(r"L([0-9]+)(?:-L([0-9]+))?")
# The pages on which the forge shows a file or a folder of a branch: a file, a folder, a file's
# lines with the commit that last changed each, and a file's bytes alone; the host that serves a
# file's bytes for each forge; and the one branch a link to the repository by its address names.
FORGE_PAGES = frozenset({"blob", "tree", "blame", "raw"})
RAW_HOSTS = {"github.com": "raw.githubusercontent.com"}
BRANCH = "main"
# Hosts whose scripts, fonts or counters a page must never load.
TRACKERS = re.compile(
    r"googletagmanager|google-analytics|fonts\.googleapis|fonts\.gstatic|plausible\.io|"
    r"cdn\.jsdelivr|unpkg\.com|cdnjs\.|segment\.(com|io)|hotjar|clarity\.ms|intercom",
    re.IGNORECASE,
)
DATE = re.compile(r"\b(19|20)\d\d-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b")


class SiteError(Exception):
    """The site cannot be built as it stands; the message says what to fix."""


# --- the settings ---------------------------------------------------------------------


@dataclass(frozen=True)
class Address:
    """The address the site is built for: ``site`` is the host, ``base`` the folder."""

    site: str
    base: str

    @property
    def root(self) -> str:
        """The full address of the base folder, such as ``https://host/docs/x/``."""
        return self.site + self.base


def read_address(repo: Path = REPO) -> Address:
    """The ``SITE`` and ``BASE`` constants of the site's Astro config."""
    text = (repo / ASTRO_CONFIG).read_text(encoding="utf-8")
    found = dict(ADDRESS_LINE.findall(text))
    if set(found) != {"SITE", "BASE"}:
        raise SiteError(f"{ASTRO_CONFIG} must hold one line each: const SITE = '...'; const BASE")
    site, base = found["SITE"], found["BASE"]
    if not re.fullmatch(r"https://[a-z0-9.-]+", site):
        raise SiteError(f"SITE must be https://HOST with no path: {site!r}")
    if not re.fullmatch(r"(/[a-z0-9-]+)+/", base):
        raise SiteError(f"BASE must start and end with '/': {base!r}")
    return Address(site, base)


def read_version(repo: Path = REPO) -> str:
    """The version of the package, from ``pyproject.toml``."""
    with (repo / "pyproject.toml").open("rb") as file:
        version: str = tomllib.load(file)["project"]["version"]
    return version


def read_source(repo: Path = REPO) -> str:
    """The address of the repository on its forge, ``https://HOST/OWNER/NAME``: ``Source``
    under ``[project.urls]`` in ``pyproject.toml``."""
    with (repo / "pyproject.toml").open("rb") as file:
        urls = tomllib.load(file)["project"].get("urls", {})
    source = urls.get("Source") if isinstance(urls, dict) else None
    if not isinstance(source, str) or not SOURCE_FORM.fullmatch(source):
        raise SiteError(
            "pyproject.toml must give the repository's address under [project.urls]: "
            'Source = "https://HOST/OWNER/NAME"'
        )
    return source.rstrip("/")


def version_folder(version: str) -> str:
    """The folder of a release's documentation: the major and minor parts, ``0.1``."""
    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        raise SiteError(f"the version must start with MAJOR.MINOR: {version!r}")
    return f"{int(parts[0])}.{int(parts[1])}"


# --- the navigation -------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One page of the navigation: its file under ``docs/``, its sidebar label, its section."""

    page: str
    label: str
    section: str
    section_slug: str


@dataclass(frozen=True)
class Section:
    label: str
    slug: str
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class Link:
    """A link of the llms files that is not a page of the site."""

    title: str
    target: str
    description: str


@dataclass(frozen=True)
class Navigation:
    title: str
    summary: str
    details: str
    sections: tuple[Section, ...]
    links: tuple[Link, ...]

    @property
    def entries(self) -> list[Entry]:
        """Every page, in the order of the sidebar."""
        return [entry for section in self.sections for entry in section.entries]


def load_navigation(repo: Path = REPO) -> Navigation:
    """Read ``site/navigation.json``: the one list of the site's pages and their order."""
    data = json.loads((repo / NAVIGATION).read_text(encoding="utf-8"))
    sections = []
    for section in data["sections"]:
        entries = tuple(
            Entry(item["page"], item["label"], section["label"], section["slug"])
            for item in section["pages"]
        )
        sections.append(Section(section["label"], section["slug"], entries))
    links = tuple(Link(i["title"], i["target"], i["description"]) for i in data["links"])
    navigation = Navigation(data["title"], data["summary"], data["details"], tuple(sections), links)
    pages = [entry.page for entry in navigation.entries]
    if len(pages) != len(set(pages)):
        raise SiteError(f"{NAVIGATION} lists a page twice")
    return navigation


def slug(page: str) -> str:
    """The address of a page below the version folder: ``guides/wall.md`` -> ``guides/wall``."""
    stem = page[: -len(".md")]
    if stem == "index":
        return ""
    return stem[: -len("/index")] if stem.endswith("/index") else stem


def page_path(address: Address, page: str, folder: str = LATEST) -> str:
    """The path of a page's web address on the host, ending in ``/``."""
    tail = slug(page)
    return f"{address.base}{folder}/" + (f"{tail}/" if tail else "")


def markdown_path(address: Address, page: str, folder: str = LATEST) -> str:
    """The path of a page's Markdown copy: the page's folder plus ``index.md``."""
    return page_path(address, page, folder) + "index.md"


# --- the pages ------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """A page read from ``docs/``: the title is its first heading, the rest its body."""

    path: str
    title: str
    description: str
    body: str
    meta: dict[str, str] = field(default_factory=dict)


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """The front matter of a Markdown text as plain ``key: value`` pairs, and the rest."""
    found = FRONT_MATTER.match(text)
    if not found:
        return {}, text
    meta: dict[str, str] = {}
    for line in found.group(1).splitlines():
        parsed = FRONT_LINE.match(line)
        if not parsed:
            raise SiteError(f"front matter line is not 'key: value': {line!r}")
        key, value = parsed.groups()
        if value.startswith('"'):
            value = json.loads(value)
        elif ": " in value or value.startswith(("'", "[", "{", "&", "*", "!", "|", ">", "#")):
            raise SiteError(f"front matter value of {key} must be written in double quotes")
        meta[key] = value
    return meta, text[found.end() :]


def is_page(path: Path) -> bool:
    """A Markdown file is a page of the site when it opens with front matter."""
    return path.suffix == ".md" and FRONT_MATTER.match(path.read_text(encoding="utf-8")) is not None


def read_page(repo: Path, page: str) -> Page:
    """Read one page; refuse one without a description or without a first heading."""
    path = repo / DOCS / page
    if not path.is_file():
        raise SiteError(f"the navigation lists docs/{page}, which does not exist")
    meta, rest = front_matter(path.read_text(encoding="utf-8"))
    description = meta.get("description", "").strip()
    if not description:
        raise SiteError(f"docs/{page} has no description in its front matter")
    if len(description) > DESCRIPTION_LIMIT:
        raise SiteError(f"docs/{page}: the description is longer than {DESCRIPTION_LIMIT}")
    lines = rest.lstrip("\n").split("\n")
    title = TITLE.match(lines[0])
    if not title:
        raise SiteError(f"docs/{page} does not open with a '# ' heading after its front matter")
    body = "\n".join(lines[1:]).strip("\n") + "\n"
    return Page(page, title.group(1).strip(), description, body, meta)


def site_pages(repo: Path = REPO) -> list[str]:
    """Every Markdown file under ``docs/`` that is a page, as paths below ``docs/``."""
    docs = repo / DOCS
    return sorted(p.relative_to(docs).as_posix() for p in docs.rglob("*.md") if is_page(p))


def stray_files(repo: Path = REPO) -> list[str]:
    """Markdown files without front matter in a folder that holds pages.

    A folder of the site holds only pages, so a file there without front matter is a page
    that forgot its front matter, not a file the site may leave out.
    """
    docs = repo / DOCS
    folders = {(docs / page).parent for page in site_pages(repo)}
    return sorted(
        p.relative_to(docs).as_posix()
        for folder in folders
        for p in folder.glob("*.md")
        if not is_page(p)
    )


# --- links ----------------------------------------------------------------------------


def _code_spans(line: str) -> list[tuple[int, int]]:
    return [found.span() for found in CODE_SPAN.finditer(line)]


def written_addresses(text: str) -> list[str]:
    """The addresses a Markdown text writes as links of their own outside code: each autolink,
    ``<address>``, each bare address, ``www.`` ones with no scheme among them, without the marks
    that end a sentence after it, and the ``href`` of each link written in HTML that has a
    scheme. A relative ``href`` is left to the check of the built site."""
    found: list[str] = []
    block: list[str] = []

    def outside(match: re.Match[str], spans: list[tuple[int, int]]) -> bool:
        return not any(start <= match.start() < end for start, end in spans)

    def flush() -> None:
        joined = "\n".join(block)
        spans = _code_spans(joined)
        for pattern in (ADDRESS_AUTOLINK, BARE_ADDRESS):
            for match in pattern.finditer(joined):
                if outside(match, spans):
                    found.append(match.group(match.lastindex or 0).rstrip(SENTENCE_MARKS))
        for match in HREF.finditer(joined):
            target = match.group(1) if match.group(1) is not None else match.group(2)
            if outside(match, spans) and SCHEME.match(target):
                found.append(target)
        block.clear()

    for _index, line, prose in prose_lines(text):
        if prose and line.strip():
            block.append(line)
            continue
        flush()
    flush()
    return found


def prose_lines(text: str) -> Iterator[tuple[int, str, bool]]:
    """Each line of a Markdown text with its index and whether it is prose (outside fences)."""
    fenced: str | None = None
    for index, line in enumerate(text.split("\n")):
        opening = FENCE.match(line)
        if opening and (fenced is None or opening.group(1) == fenced):
            fenced = None if fenced else opening.group(1)
            yield index, line, False
            continue
        yield index, line, fenced is None


def _changed(target: str, change: Callable[[str], str]) -> str:
    """A link's target passed to ``change``, kept in its angle brackets when it has them."""
    if target.startswith("<") and target.endswith(">"):
        return f"<{change(target[1:-1])}>"
    return change(target)


def rewrite_links(text: str, change: Callable[[str], str]) -> str:
    """Pass the target of every Markdown link outside code to ``change``: each link written
    ``[text](target)`` and each definition ``[label]: target`` of a reference link.

    A link's text may run over several lines of one paragraph."""
    out: list[str] = []
    block: list[str] = []

    def outside_code(
        text: str, pattern: re.Pattern[str], write: Callable[[re.Match[str]], str]
    ) -> str:
        spans = _code_spans(text)

        def replace(found: re.Match[str]) -> str:
            if any(start <= found.start() < end for start, end in spans):
                return found.group(0)
            return write(found)

        return pattern.sub(replace, text)

    def flush() -> None:
        if not block:
            return
        joined = outside_code(
            "\n".join(block),
            LINK,
            lambda found: (
                f"[{found['text']}]({found['lead']}{_changed(found['target'], change)}"
                f"{found['title'] or ''}{found['tail']})"
            ),
        )
        joined = outside_code(
            joined,
            DEFINITION,
            lambda found: found["label"] + _changed(found["target"], change),
        )
        out.append(joined)
        block.clear()

    for _index, line, prose in prose_lines(text):
        if prose and line.strip():
            block.append(line)
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out)


@dataclass(frozen=True)
class Linker:
    """Turns a link written in a page of ``docs/`` into an address the site serves."""

    repo: Path
    address: Address
    pages: frozenset[str]
    folder: str = LATEST
    markdown: bool = False

    def target(self, page: str, written: str) -> str:
        if written.startswith("#") or SCHEME.match(written):
            return written
        path, _, fragment = written.partition("#")
        path, mark, query = path.partition("?")
        anchor = (f"?{query}" if mark else "") + (f"#{fragment}" if fragment else "")
        joined = posixpath.normpath(posixpath.join(DOCS, posixpath.dirname(page), path))
        if joined.startswith("../") or joined == "..":
            raise SiteError(f"docs/{page}: the link {written!r} leaves the repository")
        if joined.startswith(f"{DOCS}/") and joined.endswith(".md"):
            linked = joined[len(DOCS) + 1 :]
            if linked not in self.pages:
                raise SiteError(f"docs/{page}: the link {written!r} names no page of the site")
            if self.markdown:
                return self.address.site + markdown_path(self.address, linked, self.folder) + anchor
            return page_path(self.address, linked, self.folder) + anchor
        local = self.repo / joined
        if local.is_file():
            return f"{SOURCE}/blob/main/{joined}{anchor}"
        if local.is_dir():
            return f"{SOURCE}/tree/main/{joined}{anchor}"
        raise SiteError(f"docs/{page}: the link {written!r} names nothing in the repository")

    def rewrite(self, page: str, text: str) -> str:
        return rewrite_links(text, lambda written: self.target(page, written))


# --- anchors of the reference pages ---------------------------------------------------


def _anchor_cells(text: str, start: str, ids: Callable[[str, str], list[str]]) -> str:
    """Put an empty element with an id at the start of the first cell of table rows.

    ``ids(section, first_cell)`` gives the ids of a row; ``section`` is the text of
    the last ``## `` heading. Rows before the heading ``start`` are left alone.
    """
    out: list[str] = []
    section = ""
    seen: set[str] = set()
    started = not start
    for _index, line, prose in prose_lines(text):
        if prose and line.startswith("## "):
            section = line[3:].strip()
            started = started or line.strip() == start
        if prose and started and line.startswith("| `"):
            cells = line.split("|")
            fresh = [i for i in ids(section, cells[1]) if i not in seen]
            seen.update(fresh)
            spans = "".join(f'<span id="{i}"></span>' for i in fresh)
            if spans:
                cells[1] = f" {spans}{cells[1].lstrip()}"
                line = "|".join(cells)
        out.append(line)
    return "\n".join(out)


def config_anchors(text: str) -> str:
    """An anchor per config key on the config page: the key itself, ``run.rounds``."""
    return _anchor_cells(text, "## Keys", lambda _section, cell: KEY_CELL.findall(cell))


def flag_anchors(text: str) -> str:
    """An anchor per flag on the commands page: the command, two dashes, the flag."""

    def ids(section: str, cell: str) -> list[str]:
        command = section.split()[0] if section else ""
        if not command.isidentifier():
            return []
        return [f"{command}--{flag[2:]}" for flag in FLAG.findall(cell)]

    return _anchor_cells(text, "", ids)


ANCHORS: dict[str, Callable[[str], str]] = {
    "reference/config.md": config_anchors,
    "reference/commands.md": flag_anchors,
}


# --- the anchors a page has, read from its text ---------------------------------------

HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*)>")
TAG = re.compile(r"</?[A-Za-z][^<>]*>")
INLINE_LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\[\]]*\])*)\](?:\([^()]*\)|\[[^\[\]]*\])")
UNDERSCORES = re.compile(r"(?<![A-Za-z0-9\\])(_+)(?=\S)(.+?)(?<=\S)\1(?![A-Za-z0-9])")
ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
WRITTEN_ID = re.compile(r"""\bid=(?:"([^"]+)"|'([^']+)')""")
# The id Starlight gives the top of every page.
PAGE_IDS = frozenset({"_top"})


def _inline_text(text: str) -> str:
    """The text a reader sees of a line of Markdown outside code: no tags, the text of a
    link, no underscores of emphasis, escapes undone, entities read."""
    text = AUTOLINK.sub(r"\1", text)
    text = TAG.sub("", text)
    text = INLINE_LINK.sub(r"\1", text)
    text = UNDERSCORES.sub(r"\2", text)
    return html.unescape(ESCAPED.sub(r"\1", text))


def _code_text(span: str) -> str:
    """The text of a code span: the backticks off, and one space off each end when both
    ends have one."""
    ticks = len(span) - len(span.lstrip("`"))
    inner = span[ticks:-ticks]
    if inner.startswith(" ") and inner.endswith(" ") and inner.strip(" "):
        inner = inner[1:-1]
    return inner


def heading_text(heading: str) -> str:
    """The text content of a heading's Markdown, as the site reads it to give the id."""
    out: list[str] = []
    last = 0
    for start, end in _code_spans(heading):
        out.append(_inline_text(heading[last:start]))
        out.append(_code_text(heading[start:end]))
        last = end
    out.append(_inline_text(heading[last:]))
    return "".join(out)


def _slug_base(text: str) -> str:
    """Lower case, letters, marks, numbers, ``_``, ``-`` and spaces kept, each space a ``-``."""
    kept = (
        c
        for c in text.lower()
        if c in " -" or unicodedata.category(c)[0] in "LMN" or unicodedata.category(c) == "Pc"
    )
    return "".join(kept).replace(" ", "-")


def page_anchors(text: str) -> frozenset[str]:
    """The anchors of a page, read from its Markdown: the id the site gives each heading,
    and each id written in the page's HTML outside code.

    A heading's id is its text in lower case, with every character but letters, marks,
    numbers, ``_``, ``-`` and spaces left out and each space made a ``-``; a second heading
    of the same id gets ``-1``, a third ``-2``.
    """
    found: set[str] = set()
    seen: dict[str, int] = {}
    for _index, line, prose in prose_lines(text):
        if not prose:
            continue
        spans = _code_spans(line)
        for written in WRITTEN_ID.finditer(line):
            if not any(start <= written.start() < end for start, end in spans):
                found.add(written.group(1) or written.group(2))
        heading = HEADING.match(line)
        if not heading:
            continue
        base = _slug_base(heading_text(heading.group(2) or ""))
        slug = base
        while slug in seen:
            seen[base] += 1
            slug = f"{base}-{seen[base]}"
        seen[slug] = 0
        found.add(slug)
    return frozenset(found)


def site_anchors(page: Page) -> frozenset[str]:
    """The anchors of a page of the site: those of its body, with the anchors the
    reference pages get, and the top of the page."""
    body = ANCHORS[page.path](page.body) if page.path in ANCHORS else page.body
    return page_anchors(without_card_titles(body)) | PAGE_IDS


def without_card_titles(body: str) -> str:
    """A body without the headings that open a card: on the site each is a card's title,
    which is no heading and has no anchor."""
    lines: list[str] = []
    cards = False
    for line, fenced in _lines_outside_code(body):
        marker = None if fenced else MARKER.match(line.strip())
        if marker and marker.group(2) == "cards":
            cards = not marker.group(1)
        if not (cards and not fenced and CARD_TITLE.match(line.strip())):
            lines.append(line)
    return "\n".join(lines)


def line_count(data: bytes) -> int:
    """The lines of a file as the forge numbers them: one for each line break, and one more for
    text after the last line break."""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def line_anchor_refusal(fragment: str, name: str, lines: int) -> str | None:
    """What is wrong with the anchor ``fragment`` of the file ``name`` of ``lines`` lines, shown
    as plain text, or ``None``: its anchors are its lines, ``L<n>``, and the ranges of them,
    ``L<a>-L<b>``, each line from 1 to the last, the first of a range no later than its end."""
    found = LINE_ANCHOR.fullmatch(fragment)
    if found is None:
        return (
            f"names an anchor that {name} does not have; the anchors of a file that is not "
            "Markdown are its lines, #L<n>, and ranges of them, #L<a>-L<b>"
        )
    # A line is read as a number only when it has no more digits than the last line, so a
    # number longer than Python reads is refused as a line past the end, not read.
    named = [(digits or found.group(1)).lstrip("0") or "0" for digits in found.groups()]
    for line in named:
        if len(line) > len(str(lines)) or not 1 <= int(line) <= lines:
            has = "has no lines" if lines == 0 else f"has lines 1 to {lines}"
            return f"names line {line}, and {name} {has}"
    first, last = (int(line) for line in named)
    if last < first:
        return "names a range that ends before it starts"
    return None


CANNOT_TELL = "so the build cannot tell which files git tracks"
WITHOUT_GIT = "or build from a copy without .git"


def tracked_paths(repo: Path) -> frozenset[str] | None:
    """The files git tracks in the checkout ``repo``, read from its index, and the folders that
    hold them. ``None`` when ``repo`` is no git checkout (it has no ``.git``); then the files
    ``repo`` holds stand in for them. git reads the checkout at ``repo`` whatever repository or
    index the environment names.

    A checkout where git cannot answer, because git is missing, cannot start or refuses to read
    it (as it does a checkout another user owns), is refused: the files it holds would let a
    link to a file git does not track pass. git's own words are printed above the refusal."""
    if not (repo / ".git").exists():
        return None
    git = shutil.which("git")
    if git is None:
        raise SiteError(
            f"the checkout holds .git and git is not on the search path, {CANNOT_TELL}: "
            f"install git, {WITHOUT_GIT}"
        )
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    try:
        done = subprocess.run(
            [git, "ls-files", "-z"], cwd=repo, env=env, stdout=subprocess.PIPE, check=False
        )
    except OSError as error:
        raise SiteError(
            f"git could not start ({error.strerror}) in a checkout that holds .git, "
            f"{CANNOT_TELL}: check that git runs, {WITHOUT_GIT}"
        ) from None
    if done.returncode != 0:
        ended = (
            f"was stopped by {signal_words(-done.returncode)}"
            if done.returncode < 0
            else f"failed with exit code {done.returncode}"
        )
        raise SiteError(
            f"git ls-files {ended} in a checkout that holds .git, {CANNOT_TELL}: fix what git "
            f"printed above, {WITHOUT_GIT}"
        )
    found: set[str] = set()
    for name in done.stdout.split(b"\0"):
        parts = os.fsdecode(name).split("/") if name else []
        found.update("/".join(parts[:end]) for end in range(1, len(parts) + 1))
    return frozenset(found)


def _host(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def repository_link(source: str, written: str) -> tuple[str, str, str, str, bool] | None:
    """For a link to a file or folder of the repository by its address on the forge, such as
    ``{source}/blob/main/README.md?plain=1#L3``, or on the forge's host of raw files, such as
    ``https://raw.githubusercontent.com/OWNER/NAME/main/README.md``: the branch it names, the
    path in the repository, the anchor, the page that shows it (``blob``, ``tree``, ``blame``
    or ``raw``) and whether that page shows the file as plain text. ``None`` for a link to
    anything else. The host, the owner and the name are read in any capitals, the host with or
    without ``www.``, and a branch may be named in full, ``refs/heads/main``, on the raw host."""
    try:
        link, home = urlsplit(written), urlsplit(source)
    except ValueError:
        return None
    if link.scheme.lower() not in {"http", "https"}:
        return None
    host, home_host = _host(link.hostname), _host(home.hostname)
    owner = home.path.strip("/").lower().split("/")
    parts = link.path.split("/")[1:]
    if [p.lower() for p in parts[:2]] != owner:
        return None
    if host == home_host and len(parts) >= 4 and parts[2] in FORGE_PAGES:
        page, branch, rest = parts[2], parts[3], parts[4:]
    elif host == RAW_HOSTS.get(home_host) and len(parts) >= 3:
        page, branch, rest = "raw", parts[2], parts[3:]
        if [p.lower() for p in parts[2:4]] == ["refs", "heads"] and len(parts) >= 5:
            branch, rest = parts[4], parts[5:]
    else:
        return None
    path = unquote("/".join(rest))
    plain = page == "blame" or parse_qs(link.query).get("plain") == ["1"]
    joined = posixpath.normpath(path) if path else "."
    return unquote(branch), joined, link.fragment, page, plain


# An address of a repository on a host of the forge, or its ssh address, ``git@HOST:OWNER/NAME``:
# the host and what follows it, and the repository's name. The forms it is read in: on the forge
# or a host under it, such as its interface for programs, ``api.HOST/repos/OWNER/NAME``, or the
# host of its archives, ``codeload.HOST/OWNER/NAME``; on the forge's host of raw files; and on
# the host of the pages the forge serves for an owner, ``OWNER.PAGES/NAME``.
REPOSITORY_ON = r"(?<![\w.-])(?:www\.)?((?:{forms})/([\w.-]+))"
ON_FORGE = r"(?:[\w-]+\.)*{host}(?:/repos)?[/:]{owner}"
ON_RAW_HOST = r"{host}[/:]{owner}"
ON_PAGES = r"{owner}\.{host}"
PAGES_HOSTS = {"github.com": "github.io"}


def other_repository(source: str, text: str) -> str | None:
    """Where ``text`` first names a repository of the project on the forge other than its public
    one, ``source``: one of the same owner whose name starts with the project's, such as
    ``NAME-next`` or ``NAME.wiki``, by its address on the forge, on a host under it, on its host
    of raw files or on the host of its pages, or by its ssh address, in any capitals and with or
    without ``.git``, in code too; ``None`` when it names none."""
    home = urlsplit(source)
    host = _host(home.hostname)
    owner, name = home.path.strip("/").split("/")[:2]
    on = {"owner": re.escape(owner)}
    forms = [ON_FORGE.format(host=re.escape(host), **on)]
    if raw := RAW_HOSTS.get(host):
        forms.append(ON_RAW_HOST.format(host=re.escape(raw), **on))
    if pages := PAGES_HOSTS.get(host):
        forms.append(ON_PAGES.format(host=re.escape(pages), **on))
    pattern = re.compile(REPOSITORY_ON.format(forms="|".join(forms)), re.IGNORECASE)
    for found in pattern.finditer(text):
        named = found.group(2).rstrip(".").lower().removesuffix(".git")
        if named != name.lower() and named.startswith(name.lower()):
            return found.group(1).rstrip(".")
    return None


def check_anchors(build: Build) -> None:
    """Refuse a link to an anchor that the file it names does not have, wherever the text
    tells: the page itself, another page of the site, a Markdown file of the repository by its
    headings, and any other file of the repository by its lines, ``#L<n>``, and ranges of them,
    ``#L<a>-L<b>``, or a Markdown file's when the link asks for it as plain text,
    ``?plain=1``. Refuse a link to a file of the repository by its address on the forge,
    ``SOURCE/blob/main/PATH``, ``SOURCE/tree/main/PATH``, ``SOURCE/blame/main/PATH`` or
    ``SOURCE/raw/main/PATH`` with ``SOURCE`` as ``pyproject.toml`` gives it, or on the forge's
    host of raw files, that names another branch or a path the repository does not have, a
    folder on a blame or raw page, or an anchor on a raw page; its anchor is checked as a
    relative link's is, and so is such an address written as an autolink, ``<address>``,
    bare, with its scheme or starting with ``www.`` wherever the site shows it as a link, or as
    the ``href`` of a link written in HTML. Refuse a page that names a repository of the
    project other than its public one, anywhere in its text. In a git checkout the repository
    has the files git tracks and the folders that hold them, so a link, by its path or by its
    address, to a file a build leaves is refused. The anchor of a folder, and a link to another
    host or to a repository of another project, are not checked here."""
    anchors = {path: site_anchors(page) for path, page in build.pages.items()}
    headings: dict[str, frozenset[str]] = {}
    lines: dict[str, int] = {}
    tracked: list[frozenset[str] | None] = []

    def has(joined: str) -> bool:
        if joined == ".":
            return True
        if not tracked:
            tracked.append(tracked_paths(build.repo))
        return (build.repo / joined).exists() if tracked[0] is None else joined in tracked[0]

    def refusal(joined: str, fragment: str, plain: bool) -> str | None:
        local = build.repo / joined
        if not local.is_file():
            return None
        if joined.endswith(".md") and not plain:
            if joined not in headings:
                headings[joined] = page_anchors(local.read_text(encoding="utf-8"))
            if fragment in headings[joined]:
                return None
            return f"names an anchor that {joined} does not have"
        if joined not in lines:
            lines[joined] = line_count(local.read_bytes())
        return line_anchor_refusal(fragment, joined, lines[joined])

    def relative(page: str, written: str) -> str | None:
        path, hashed, fragment = written.partition("#")
        path, _, query = path.partition("?")
        plain = parse_qs(query).get("plain") == ["1"]
        if not path:
            mine = f"{DOCS}/{page}"
            if not hashed or fragment in anchors[page]:
                return None
            return f"names an anchor that {mine} does not have"
        joined = posixpath.normpath(posixpath.join(DOCS, posixpath.dirname(page), path))
        linked = joined.removeprefix(f"{DOCS}/")
        if joined.startswith(f"{DOCS}/") and linked in anchors:
            if not hashed or fragment in anchors[linked]:
                return None
            return f"names an anchor that {joined} does not have"
        if joined.startswith("../") or joined == "..":
            return None
        if not has(joined):
            return "names nothing in the repository"
        return refusal(joined, fragment, plain) if hashed else None

    def addressed(found: tuple[str, str, str, str, bool]) -> str | None:
        branch, joined, fragment, shown, plain = found
        if branch != BRANCH:
            return (
                f"names the branch {branch!r}; a link to a file of the repository by its "
                f"address names {BRANCH}"
            )
        if joined.startswith(("../", "/")) or joined == ".." or not has(joined):
            return "names nothing in the repository"
        if shown in {"blame", "raw"} and not (build.repo / joined).is_file():
            return f"names the folder {joined}, which the forge shows on a tree page only"
        if shown == "raw" and fragment:
            return f"names an anchor of the raw file {joined}, and a raw file has none"
        return refusal(joined, fragment, plain) if fragment else None

    for page in build.pages.values():
        text = "\n".join([*page.meta.values(), page.title, page.body])
        named = other_repository(build.source, text)
        if named:
            raise SiteError(
                f"docs/{page.path}: {named} names a repository of the project other than its "
                f"public one, {build.source}"
            )

        def check(written: str, page: str = page.path, alone: bool = False) -> str:
            if alone or SCHEME.match(written):
                address = written if SCHEME.match(written) else f"http://{written}"
                found = repository_link(build.source, address)
                wrong = addressed(found) if found else None
            else:
                wrong = relative(page, written)
            if wrong:
                raise SiteError(f"docs/{page}: the link {written!r} {wrong}")
            return written

        rewrite_links(page.body, check)
        for written in written_addresses(page.body):
            check(written, alone=True)


# --- prepare --------------------------------------------------------------------------


@dataclass(frozen=True)
class Build:
    """What every step needs: the repository, the address, the version, the pages and the
    address of the repository on its forge."""

    repo: Path
    address: Address
    version: str
    navigation: Navigation
    pages: dict[str, Page]
    source: str

    @property
    def folder(self) -> str:
        return version_folder(self.version)

    @property
    def dist(self) -> Path:
        return self.repo / SITE / DIST

    def linker(self, *, folder: str = LATEST, markdown: bool = False) -> Linker:
        return Linker(self.repo, self.address, frozenset(self.pages), folder, markdown)


def load_build(repo: Path = REPO) -> Build:
    """Read the settings, the navigation and every page it lists, and check them."""
    navigation = load_navigation(repo)
    listed = [entry.page for entry in navigation.entries]
    unlisted = sorted(set(site_pages(repo)) - set(listed))
    if unlisted:
        raise SiteError(f"pages that the navigation does not list: {', '.join(unlisted)}")
    stray = stray_files(repo)
    if stray:
        raise SiteError(f"pages without front matter: docs/{', docs/'.join(stray)}")
    pages = {page: read_page(repo, page) for page in listed}
    return Build(repo, read_address(repo), read_version(repo), navigation, pages, read_source(repo))


def check_generated_pages(repo: Path) -> None:
    """Refuse a page generated from the code that differs from what the code gives now."""
    for page, script in GENERATED_PAGES.items():
        tool = _load_tool(repo / script)
        expected = str(tool.render(repo))
        written = (repo / DOCS / page).read_text(encoding="utf-8")
        if written != expected:
            raise SiteError(f"docs/{page} is out of date: run python3 {script}")


def _load_tool(path: Path) -> types.ModuleType:
    import importlib.util

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise SiteError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


@functools.cache
def _share_tool() -> types.ModuleType:
    return _load_tool(TOOLS / Path(SHARE_TOOL).name)


def check_share_image(repo: Path) -> None:
    """Refuse a share image that differs from what its script draws, naming how it differs."""
    tool = _load_tool(repo / SHARE_TOOL)
    cause = tool.refusal(repo / SHARE_SOURCE)
    if cause:
        raise SiteError(f"{SHARE_SOURCE} {cause}: run python3 {SHARE_TOOL}")


def share_head(build: Build) -> list[dict[str, object]]:
    """The tags every page names the share image with: its address, its size and its alt
    text, for Open Graph readers and for X cards."""
    tool = _share_tool()
    image = f"{build.address.root}{SHARE_IMAGE}"
    tags = [
        ("property", "og:image", image),
        ("property", "og:image:width", str(tool.WIDTH)),
        ("property", "og:image:height", str(tool.HEIGHT)),
        ("property", "og:image:alt", str(tool.ALT)),
        ("name", "twitter:image", image),
        ("name", "twitter:image:alt", str(tool.ALT)),
    ]
    return [{"tag": "meta", "attrs": {key: name, "content": value}} for key, name, value in tags]


def _absolute(build: Build, page: str) -> str:
    """The full address of a page in the latest folder."""
    return build.address.site + page_path(build.address, page)


def _breadcrumbs(build: Build, page: Page) -> list[dict[str, object]]:
    """The trail to a page, as the sidebar shows it: the home page; then the page's
    section, when the section has a page of its own that is not this one; then the page
    by its sidebar label. The home page's trail is the home page alone."""
    trail = [(build.navigation.title, _absolute(build, HOME_PAGE))]
    if page.path != HOME_PAGE:
        entry = next(e for e in build.navigation.entries if e.page == page.path)
        section_page = f"{entry.section_slug}/index.md"
        if section_page in build.pages and section_page != page.path:
            trail.append((entry.section, _absolute(build, section_page)))
        trail.append((entry.label, _absolute(build, page.path)))
    return [
        {"@type": "ListItem", "position": position, "name": name, "item": item}
        for position, (name, item) in enumerate(trail, start=1)
    ]


def structured_data(build: Build, page: Page) -> dict[str, object]:
    """What a page says of itself in schema.org terms, for search and answer engines.

    The home page describes the software, its source code and the organisation that
    publishes them, at the root of the host; every other page is a technical article about
    the software. Every page carries its breadcrumbs, and names the publisher by the
    identifier of the organisation the home page defines. Each address is the page's address
    in the latest folder, so a release's copy of a page says the same.
    """
    home = _absolute(build, HOME_PAGE)
    url = _absolute(build, page.path)
    software = f"{home}#software"
    organization = f"{build.address.site}/#organization"
    publisher = {"@id": organization}
    name, summary = build.navigation.title, build.navigation.summary
    nodes: list[dict[str, object]]
    if page.path == HOME_PAGE:
        nodes = [
            {
                "@type": "SoftwareApplication",
                "@id": software,
                "name": name,
                "description": summary,
                "url": home,
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": OPERATING_SYSTEMS,
                "softwareVersion": build.version,
                "license": LICENSE_ADDRESS,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "publisher": publisher,
            },
            {
                "@type": "SoftwareSourceCode",
                "@id": f"{home}#source",
                "name": name,
                "description": summary,
                "codeRepository": SOURCE,
                "programmingLanguage": "Python",
                "license": LICENSE_ADDRESS,
                "targetProduct": {"@id": software},
                "publisher": publisher,
            },
            {
                "@type": "Organization",
                "@id": organization,
                "name": PUBLISHER,
                "url": f"{build.address.site}/",
            },
        ]
    else:
        nodes = [
            {
                "@type": "TechArticle",
                "@id": f"{url}#article",
                "headline": page.title,
                "description": page.description,
                "url": url,
                "inLanguage": "en",
                "about": {"@id": software},
                "publisher": publisher,
            }
        ]
    trail = {
        "@type": "BreadcrumbList",
        "@id": f"{url}#breadcrumb",
        "itemListElement": _breadcrumbs(build, page),
    }
    return {"@context": SCHEMA, "@graph": [*nodes, trail]}


def structured_data_text(build: Build, page: Page) -> str:
    """The structured data of a page as the text of its script element: JSON in which no
    character can end the element or open markup."""
    text = json.dumps(structured_data(build, page), ensure_ascii=False, separators=(",", ":"))
    return text.translate(SCRIPT_SAFE)


def uses_components(body: str) -> bool:
    """Whether a page's body opens a region of one of Starlight's components."""
    return any(
        MARKER.match(line) and not MARKER.match(line).group(1)  # type: ignore[union-attr]
        for line, fenced in _lines_outside_code(body)
        if not fenced
    )


def _lines_outside_code(body: str) -> Iterator[tuple[str, bool]]:
    """Each line of a body, with whether it is inside a fenced code block or its fence."""
    fenced = False
    for line in body.split("\n"):
        if FENCE.match(line):
            yield line, True
            fenced = not fenced
            continue
        yield line, fenced


def _mdx_prose(line: str) -> str:
    """A line of prose made safe for MDX: braces outside code spans are escaped."""
    spans = _code_spans(line)
    out = []
    for at, char in enumerate(line):
        inside = any(start <= at < end for start, end in spans)
        out.append("\\" + char if char in "{}" and not inside else char)
    return "".join(out)


def mdx_body(body: str) -> str:
    """A body that marks Starlight's components, written as MDX: each marked region becomes
    its component, every other comment line is left out, and braces in prose are escaped.
    A region left open, or closed without being opened, is refused."""
    out: list[str] = []
    open_regions: list[str] = []
    item_open = False

    def close_item(margin: str) -> None:
        nonlocal item_open
        if item_open:
            out.extend(
                ["", margin + ("</TabItem>" if open_regions[-1] == "tabs" else "</Card>"), ""]
            )
            item_open = False

    for line, fenced in _lines_outside_code(body):
        if fenced:
            out.append(line)
            continue
        bare = line.strip()
        # A component inside a list item keeps the item's indentation.
        margin = line[: len(line) - len(line.lstrip())]
        marker = MARKER.match(bare)
        if marker:
            closing, name = marker.groups()
            if closing:
                if not open_regions or open_regions[-1] != name:
                    raise SiteError(f"<!-- /{name} --> closes no open {name} region")
                if name != "steps":
                    close_item(margin)
                open_regions.pop()
                out.extend(["", margin + CLOSING[name], ""])
            else:
                open_regions.append(name)
                out.extend(["", margin + OPENING[name], ""])
            continue
        region = open_regions[-1] if open_regions else None
        icon = ICON_LINE.match(bare)
        if region == "cards" and icon and item_open and out[-2].lstrip().startswith("<Card "):
            out[-2] = out[-2][:-1] + f' icon="{icon.group(1)}">'
            continue
        if COMMENT_LINE.match(bare):
            continue
        label = TAB_LABEL.match(bare)
        title = CARD_TITLE.match(bare)
        if region == "tabs" and label:
            close_item(margin)
            out.extend(["", f"{margin}<TabItem label={json.dumps(label.group(1))}>", ""])
            item_open = True
            continue
        if region == "cards" and title:
            close_item(margin)
            out.extend(["", f"{margin}<Card title={json.dumps(title.group(1))}>", ""])
            item_open = True
            continue
        out.append(_mdx_prose(line))
    if open_regions:
        raise SiteError(f"<!-- {open_regions[-1]} --> is never closed")
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")
    return f"{COMPONENT_IMPORT}\n\n{text}\n"


def without_markers(body: str) -> str:
    """A body with the comment lines that mark Starlight's components left out, for the
    Markdown copy of a page."""
    lines = [
        line
        for line, fenced in _lines_outside_code(body)
        if fenced or not (MARKER.match(line.strip()) or ICON_LINE.match(line.strip()))
    ]
    return "\n".join(lines)


def content_name(build: Build, page: Page) -> str:
    """The name of a page's copy under the content folder: ``.mdx`` when it uses Starlight's
    components, its own name otherwise."""
    if uses_components(page.body):
        return page.path[: -len(".md")] + ".mdx"
    return page.path


@dataclass(frozen=True)
class Badge:
    """A badge of the home page: its file under the badges folder, its label and its value."""

    name: str
    label: str
    value: str

    @property
    def alt(self) -> str:
        return f"{self.label} {self.value}"


def read_badges(repo: Path = REPO) -> list[Badge]:
    """The version, the Python versions and the licence, read from ``pyproject.toml``: the
    version, the minor versions its classifiers name, and its licence expression."""
    with (repo / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]
    prefix = "Programming Language :: Python :: "
    pythons = [
        c.removeprefix(prefix)
        for c in project.get("classifiers", [])
        if c.startswith(prefix) and re.fullmatch(r"\d+\.\d+", c.removeprefix(prefix))
    ]
    if not pythons:
        raise SiteError("pyproject.toml names no Python minor version in its classifiers")
    return [
        Badge("version", "version", str(project["version"])),
        Badge("python", "python", " | ".join(pythons)),
        Badge("licence", "licence", str(project["license"])),
    ]


def _badge_text(x: float, width: float, text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<text x="{x:.1f}" y="14" textLength="{width:.1f}" lengthAdjust="spacingAndGlyphs">'
        f"{escaped}</text>"
    )


def badge_svg(badge: Badge) -> str:
    """A badge as SVG: its label on the dark part, its value on its colour, the text in white
    in a font every system has, drawn to a width that depends on the text alone."""
    label_text = len(badge.label) * BADGE_CHARACTER
    value_text = len(badge.value) * BADGE_CHARACTER
    label = label_text + 2 * BADGE_PAD
    value = value_text + 2 * BADGE_PAD
    width = label + value
    colour = BADGE_COLOURS[badge.name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}" height="20" '
        f'viewBox="0 0 {width:.1f} 20" role="img" aria-label="{badge.alt}">'
        f"<title>{badge.alt}</title>"
        f'<clipPath id="r"><rect width="{width:.1f}" height="20" rx="4"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label:.1f}" height="20" fill="{BADGE_LABEL_COLOUR}"/>'
        f'<rect x="{label:.1f}" width="{value:.1f}" height="20" fill="{colour}"/></g>'
        '<g fill="#ffffff" font-family="Verdana,\'DejaVu Sans\',sans-serif" font-size="11">'
        f"{_badge_text(BADGE_PAD, label_text, badge.label)}"
        f"{_badge_text(label + BADGE_PAD, value_text, badge.value)}</g></svg>\n"
    )


def badges_html(build: Build) -> str:
    """The badges as the hero shows them under its tagline: images of the site's own files.
    A repository without ``pyproject.toml`` has no package to describe, and no badges."""
    if not (build.repo / "pyproject.toml").is_file():
        return ""
    images = "".join(
        f'<img src="{build.address.base}{BADGES}/{badge.name}.svg" alt="{badge.alt}" height="20">'
        for badge in read_badges(build.repo)
    )
    return f'<span class="pb-badges">{images}</span>'


def write_badges(build: Build) -> None:
    """Write the badges into the badges folder of the built site, when there is a package."""
    if not (build.repo / "pyproject.toml").is_file():
        return
    folder = build.dist / BADGES
    folder.mkdir(parents=True, exist_ok=True)
    for badge in read_badges(build.repo):
        (folder / f"{badge.name}.svg").write_text(badge_svg(badge), encoding="utf-8")


def hero(build: Build, page: Page) -> dict[str, object]:
    """The hero of the home page: its title, its description as the tagline, the mark in the
    light and the dark theme, and its buttons."""
    depth = len(Path(LATEST, page.path).parent.parts) + 2
    up = "../" * depth
    actions = []
    for text, target, variant, icon in HERO_ACTIONS:
        link = target if "://" in target else page_path(build.address, target)
        action: dict[str, object] = {"text": text, "link": link, "variant": variant}
        if icon:
            action["icon"] = icon
        actions.append(action)
    return {
        "title": page.title,
        "tagline": f"{page.description}{badges_html(build)}",
        "image": {
            "alt": "",
            "light": up + MARKS["light"].removeprefix("site/src/"),
            "dark": up + MARKS["dark"].removeprefix("site/src/"),
        },
        "actions": actions,
    }


def site_page_text(build: Build, page: Page) -> str:
    """The copy of a page Starlight reads: JSON front matter, then the body; the body as MDX
    when the page uses Starlight's components, and the home page with its hero."""
    body = build.linker().rewrite(page.path, page.body)
    if page.path in ANCHORS:
        body = ANCHORS[page.path](body)
    head = [
        {
            "tag": "link",
            "attrs": {
                "rel": "alternate",
                "type": "text/markdown",
                "href": markdown_path(build.address, page.path),
            },
        },
        {"tag": "meta", "attrs": {"name": VERSION_META, "content": build.version}},
        {
            "tag": "script",
            "attrs": {"type": "application/ld+json"},
            "content": structured_data_text(build, page),
        },
    ]
    meta: dict[str, object] = {"title": page.title, "description": page.description, "head": head}
    if page.path == HOME_PAGE:
        meta["template"] = "splash"
        meta["hero"] = hero(build, page)
    if uses_components(page.body):
        body = mdx_body(body)
    return f"---\n{json.dumps(meta, ensure_ascii=False)}\n---\n\n{body}"


def sidebar(build: Build) -> list[dict[str, object]]:
    """The Starlight sidebar: one group per section, one link per page, in order."""
    groups: list[dict[str, object]] = []
    for section in build.navigation.sections:
        items = []
        for entry in section.entries:
            tail = slug(entry.page)
            items.append({"label": entry.label, "slug": f"{LATEST}/{tail}" if tail else LATEST})
        groups.append({"label": section.label, "items": items})
    return groups


def prepare(repo: Path = REPO) -> Build:
    """Check the pages, the generated pages, the version, the share image, the page each
    link names and the anchors the pages' text gives, then write the copies of the pages
    and the generated settings that Astro reads. Nothing is removed or written before every
    check has passed."""
    build = load_build(repo)
    check_generated_pages(repo)
    version_folder(build.version)
    check_share_image(repo)
    texts = {path: site_page_text(build, page) for path, page in build.pages.items()}
    check_anchors(build)
    content = repo / CONTENT
    generated = repo / GENERATED
    for folder in (content, generated):
        if folder.exists():
            shutil.rmtree(folder)
    for path, text in texts.items():
        target = content / LATEST / content_name(build, build.pages[path])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    generated.mkdir(parents=True)
    settings = {
        "title": build.navigation.title,
        "description": build.navigation.summary,
        "version": build.version,
        "sidebar": sidebar(build),
        "head": share_head(build),
    }
    (generated / "site.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return build


# --- Markdown copies and llms files ---------------------------------------------------


def llms_address(build: Build, name: str = LLMS, folder: str = LATEST) -> str:
    return f"{build.address.root}{folder}/{name}"


def markdown_copy(build: Build, page: Page, folder: str = LATEST) -> str:
    """A page as Markdown: a line pointing to the llms files, the title, the description,
    the version and the page's address, then the body with every link made absolute."""
    body = build.linker(folder=folder, markdown=True).rewrite(page.path, page.body)
    body = without_markers(body)
    web = build.address.site + page_path(build.address, page.path, folder)
    return (
        f"> Every page is listed in {llms_address(build, LLMS, folder)}; all of them are in "
        f"one file at {llms_address(build, LLMS_FULL, folder)}.\n\n"
        f"# {page.title}\n\n"
        f"> {page.description}\n\n"
        f"pairbench {build.version}. Web page: {web}\n\n"
        f"{body}"
    )


def _item(title: str, target: str, description: str) -> str:
    return f"- [{title}]({target}): {description}"


def llms_text(build: Build, *, site: bool, sections: Iterable[Section] | None = None) -> str:
    """The llms file: every page of the navigation, in order, with its description.

    With ``site`` the links point at the Markdown copies on the site; otherwise at
    the pages in the repository, for readers of the repository's ``llms.txt``.
    """
    navigation = build.navigation
    chosen = tuple(sections) if sections is not None else navigation.sections
    whole = sections is None
    title = navigation.title if whole else f"{navigation.title}: {chosen[0].label}"
    lines = [f"# {title}", "", f"> {navigation.summary}", ""]
    if whole:
        lines += [navigation.details, ""]
    if whole and not site:
        lines += [
            f"The documentation is published at {build.address.root}{LATEST}/, where every "
            f"page also has a Markdown copy. This list links the pages in the repository.",
            "",
        ]
    if site:
        parts = ", ".join(
            f"[{s.label}]({llms_address(build, f'{s.slug}/{LLMS}')})" for s in navigation.sections
        )
        lines += [
            f"The documentation of pairbench {build.version}. Each section has its own list: "
            f"{parts}. Every page in one file: [llms-full.txt]"
            f"({llms_address(build, LLMS_FULL)}).",
            "",
        ]
    for section in chosen:
        lines += [f"## {section.label}", ""]
        for entry in section.entries:
            page = build.pages[entry.page]
            if site:
                target = build.address.site + markdown_path(build.address, entry.page)
            else:
                target = f"{DOCS}/{entry.page}"
            lines.append(_item(page.title, target, page.description))
        lines.append("")
    if whole:
        lines += ["## Elsewhere", ""]
        for link in navigation.links:
            target = link.target
            if site and not SCHEME.match(target):
                target = f"{SOURCE}/blob/main/{target}"
            lines.append(_item(link.title, target, link.description))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def llms_full(build: Build) -> str:
    """Every page's Markdown copy, in the order of the navigation, in one file."""
    head = [
        f"# {build.navigation.title} {build.version}: every page",
        "",
        f"> {build.navigation.summary}",
        "",
        f"The list of the pages: {llms_address(build)}",
    ]
    parts = ["\n".join(head) + "\n"]
    for entry in build.navigation.entries:
        copy = markdown_copy(build, build.pages[entry.page])
        parts.append(copy.split("\n\n", 1)[1])
    return "\n---\n\n".join(parts)


def robots(build: Build) -> str:
    """``robots.txt``: every crawler may read the documentation; where the lists are."""
    base = build.address.base
    lines = [
        "# The pairbench documentation. Every page is also served as Markdown; the list of",
        f"# the pages is {llms_address(build)} and all of them are in one",
        f"# file at {llms_address(build, LLMS_FULL)}.",
        "# This file speaks for the documentation's folder; a host that serves other folders",
        "# merges these groups into the robots.txt at its root.",
        "",
        "User-agent: *",
        f"Allow: {base}",
        "",
    ]
    for crawler in AI_CRAWLERS:
        lines += [f"User-agent: {crawler}", f"Allow: {base}", ""]
    lines.append(f"Sitemap: {build.address.root}sitemap-index.xml")
    return "\n".join(lines) + "\n"


def _head_html(head: Iterable[dict[str, object]]) -> str:
    """Head entries as the tags they stand for, one to a line."""
    lines = []
    for entry in head:
        attrs = entry["attrs"]
        assert isinstance(attrs, dict)
        written = " ".join(f'{key}="{html.escape(str(value))}"' for key, value in attrs.items())
        lines.append(f"<{entry['tag']} {written}>\n")
    return "".join(lines)


def base_page(build: Build) -> str:
    """The page at the base address: it sends the reader to the latest documentation."""
    latest = f"{build.address.base}{LATEST}/"
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{build.navigation.title} documentation</title>\n"
        f'<link rel="canonical" href="{build.address.root}{LATEST}/">\n'
        f'<link rel="alternate" type="text/markdown" href="{build.address.base}index.md">\n'
        f'<meta http-equiv="refresh" content="0; url={latest}">\n'
        f'<meta name="robots" content="noindex">\n'
        f"{_head_html(share_head(build))}"
        '<meta name="twitter:card" content="summary_large_image">\n'
        "</head>\n<body>\n"
        f'<p>The documentation is at <a href="{latest}">{latest}</a>.</p>\n'
        "</body>\n</html>\n"
    )


def base_markdown(build: Build) -> str:
    """The Markdown page at the base address, for a reader that asks the base folder for
    Markdown: what the tool is, and where the latest pages and the llms files are."""
    navigation = build.navigation
    return (
        f"# {navigation.title} documentation\n\n"
        f"> {navigation.summary}\n\n"
        f"- [Latest pages]({build.address.root}{LATEST}/): every page of {navigation.title} "
        f"{build.version}; the Markdown copy of a page is at its address plus `index.md`.\n"
        f"- [llms.txt]({llms_address(build)}): the list of the pages, each with a line on "
        "what it holds.\n"
        f"- [llms-full.txt]({llms_address(build, LLMS_FULL)}): every page in one file.\n"
    )


def write_base(build: Build) -> None:
    """Write the base folder's pages: the one that sends a browser to the latest pages, and
    its Markdown page."""
    (build.dist / "index.html").write_text(base_page(build), encoding="utf-8")
    (build.dist / "index.md").write_text(base_markdown(build), encoding="utf-8")


def write_copies(build: Build) -> None:
    """Write each page's Markdown copy at ``page/index.md`` and at ``page.md``."""
    latest = build.dist / LATEST
    for entry in build.navigation.entries:
        text = markdown_copy(build, build.pages[entry.page])
        tail = slug(entry.page)
        folder = latest / tail if tail else latest
        (folder / "index.md").write_text(text, encoding="utf-8")
        beside = (latest / f"{tail}.md") if tail else build.dist / f"{LATEST}.md"
        beside.write_text(text, encoding="utf-8")


def write_llms(build: Build) -> None:
    """Write the llms files in the latest folder, and the same two whole lists at the base
    address, where readers look for them first."""
    latest = build.dist / LATEST
    whole = llms_text(build, site=True)
    full = llms_full(build)
    for folder in (latest, build.dist):
        (folder / LLMS).write_text(whole, encoding="utf-8")
        (folder / LLMS_FULL).write_text(full, encoding="utf-8")
    for section in build.navigation.sections:
        folder = latest / section.slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / LLMS).write_text(llms_text(build, site=True, sections=[section]), "utf-8")


ATTRIBUTE_PATH = re.compile(r"""(?<=["'(])(/[^"'()\s]*)""")


def copy_release(build: Build) -> None:
    """Copy the latest pages to the release's folder, with its own copy of the assets.

    Links inside the copy point into the copy; the canonical links and the page
    addresses of the social cards keep pointing at the latest pages.
    """
    base = build.address.base
    latest = f"{base}{LATEST}/"
    target = build.dist / build.folder
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(build.dist / LATEST, target)
    shutil.copytree(build.dist / "_astro", target / "_astro")
    own = f"{base}{build.folder}/"

    def local(found: re.Match[str]) -> str:
        path = found.group(1)
        if path.startswith(latest):
            return own + path[len(latest) :]
        if path.startswith(f"{base}_astro/"):
            return f"{own}_astro/" + path[len(f"{base}_astro/") :]
        return path

    for path in sorted(target.rglob("*")):
        if path.suffix in (".html", ".css"):
            text = path.read_text(encoding="utf-8")
            path.write_text(ATTRIBUTE_PATH.sub(local, text), encoding="utf-8")
        elif path.suffix in (".md", ".txt"):
            text = path.read_text(encoding="utf-8")
            text = text.replace(build.address.site + latest, build.address.site + own)
            path.write_text(text, encoding="utf-8")
    copy = build.dist / f"{build.folder}.md"
    home = (build.dist / f"{LATEST}.md").read_text(encoding="utf-8")
    copy.write_text(home.replace(build.address.site + latest, build.address.site + own), "utf-8")


OWN_ADDRESS = re.compile(r'<link rel="canonical"[^>]*>|<meta property="og:url"[^>]*>')


def without_address(page: str) -> str:
    """The page a host serves for any missing address, without a canonical address of its
    own: it has none."""
    return OWN_ADDRESS.sub("", page)


def finish(repo: Path = REPO) -> Build:
    """Write what Astro does not, copy the release's folder and check the whole site."""
    build = load_build(repo)
    if not (build.dist / LATEST).is_dir():
        raise SiteError(f"no built pages in {build.dist / LATEST}: run the Astro step first")
    write_copies(build)
    write_llms(build)
    (build.dist / "robots.txt").write_text(robots(build), encoding="utf-8")
    write_base(build)
    write_badges(build)
    copy_release(build)
    missing = build.dist / "404.html"
    if missing.is_file():
        missing.write_text(without_address(missing.read_text(encoding="utf-8")), encoding="utf-8")
    problems = check_site(build.dist, build.address)
    if problems:
        raise SiteError("the built site has problems:\n" + "\n".join(problems))
    return build


# --- checking the built site ----------------------------------------------------------

RESOURCE_TAGS = {
    "script": "src",
    "img": "src",
    "source": "src",
    "iframe": "src",
    "audio": "src",
    "video": "src",
    "embed": "src",
}
FETCHED_RELS = {
    "stylesheet",
    "preload",
    "modulepreload",
    "prefetch",
    "preconnect",
    "dns-prefetch",
    "icon",
    "shortcut",
    "manifest",
}
# The meta tags whose content is the address of an image a social site or a chat fetches.
IMAGE_META = frozenset({"og:image", "og:image:url", "og:image:secure_url", "twitter:image"})


class _Page(html.parser.HTMLParser):
    """The ids of a page and every address it names, with the tag and whether it is fetched."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.refs: list[tuple[str, str, bool]] = []
        self.canonical: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "a" and "name" in values:
            self.ids.append(values["name"])
        if tag == "a" and "href" in values:
            self.refs.append((tag, values["href"], False))
        if tag == "link" and "href" in values:
            rels = set(values.get("rel", "").lower().split())
            if "canonical" in rels:
                self.canonical.append(values["href"])
            self.refs.append((tag, values["href"], bool(rels & FETCHED_RELS)))
        attribute = RESOURCE_TAGS.get(tag)
        if attribute and attribute in values:
            self.refs.append((tag, values[attribute], True))
        if "srcset" in values:
            for part in values["srcset"].split(","):
                if part.strip():
                    self.refs.append((tag, part.split()[0], True))
        if tag == "meta" and values.get("http-equiv", "").lower() == "refresh":
            _, _, url = values.get("content", "").partition("url=")
            if url:
                self.refs.append((tag, url.strip(), False))
        named = values.get("property") or values.get("name")
        if tag == "meta" and named in IMAGE_META and values.get("content"):
            self.refs.append((tag, values["content"], True))


def _parse(path: Path) -> _Page:
    parser = _Page()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def _file_for(dist: Path, address: Address, path: str) -> Path | None:
    """The built file an address path names, or ``None`` when it names none."""
    if not path.startswith(address.base):
        return None
    rest = path[len(address.base) :]
    if rest == "" or rest.endswith("/"):
        rest += "index.html"
    candidate = dist / rest
    return candidate if candidate.is_file() else None


def _page_address(dist: Path, address: Address, path: Path) -> str:
    relative = path.relative_to(dist).as_posix()
    if relative.endswith("index.html"):
        relative = relative[: -len("index.html")]
    return address.root + relative


def check_site(dist: Path, address: Address) -> list[str]:
    """Every problem of a built site: a link, anchor or asset that does not resolve, an
    address outside the base folder, anything fetched from another host, a page without
    one canonical link, a date in a page, a share image it publishes that its script would
    not write. A share image that is not there is a problem of each page that names it."""
    problems: list[str] = []
    image = dist / SHARE_IMAGE
    if image.exists():
        cause = _share_tool().refusal(image)
        if cause:
            problems.append(
                f"{SHARE_IMAGE} {cause}: run python3 {SHARE_TOOL}, then python3 "
                "tools/docs_site.py build"
            )
    parsed: dict[Path, _Page] = {}

    def page(path: Path) -> _Page:
        if path not in parsed:
            parsed[path] = _parse(path)
        return parsed[path]

    htmls = sorted(dist.rglob("*.html"))
    for path in htmls:
        name = path.relative_to(dist).as_posix()
        here = page(path)
        duplicated = sorted({i for i in here.ids if here.ids.count(i) > 1})
        if duplicated:
            problems.append(f"{name}: ids used twice: {', '.join(duplicated)}")
        if name not in ("index.html", "404.html") and len(here.canonical) != 1:
            problems.append(f"{name}: {len(here.canonical)} canonical links")
        for canonical in here.canonical:
            if not canonical.startswith(f"{address.root}{LATEST}/") and name != "404.html":
                problems.append(f"{name}: the canonical link is not a latest page: {canonical}")
        base_url = _page_address(dist, address, path)
        for tag, ref, fetched in here.refs:
            problem = _check_ref(dist, address, base_url, tag, ref, fetched, page)
            if problem:
                problems.append(f"{name}: {problem}")
    for path in sorted(dist.rglob("*")):
        if path.suffix not in (".html", ".css", ".js", ".md", ".txt", ".xml", ".json"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.relative_to(dist).as_posix()
        if TRACKERS.search(text):
            problems.append(f"{name}: names a host of scripts, fonts or counters")
        if path.suffix == ".css":
            for url in re.findall(r"url\(\s*['\"]?([^'\")]+)", text):
                if url.startswith(("http:", "https:", "//")):
                    problems.append(f"{name}: a style loads {url}")
            if re.search(r"@import\s+(url\()?['\"]?(https?:)?//", text):
                problems.append(f"{name}: a style imports from another host")
        if path.suffix in (".html", ".md", ".txt", ".xml") and DATE.search(text):
            problems.append(f"{name}: holds a date: {DATE.search(text).group(0)}")  # type: ignore[union-attr]
        if path.suffix in (".md", ".txt"):
            for target in re.findall(r"\]\((https?://[^)\s]+)\)", text):
                problem = _check_ref(dist, address, address.root, "md", target, False, page)
                if problem:
                    problems.append(f"{name}: {problem}")
    return problems


def _check_ref(
    dist: Path,
    address: Address,
    base_url: str,
    tag: str,
    ref: str,
    fetched: bool,
    page: Callable[[Path], _Page],
) -> str | None:
    if ref.startswith("//"):
        return f"an address without a scheme: {ref}"
    if ref.startswith(("mailto:", "data:")):
        return None
    full = urljoin(base_url, ref)
    parts = urlsplit(full)
    if parts.scheme not in ("http", "https"):
        return f"an address of another kind: {ref}"
    if f"{parts.scheme}://{parts.netloc}" != address.site:
        if fetched or tag not in ("a", "md"):
            return f"fetches from another host: {ref}"
        return None
    if not fetched and tag in ("a", "md") and parts.path == "/" and not parts.query:
        # The home page of the organisation that makes the tool, at the root of the host:
        # the line under every page names it, and it is not part of the site.
        return None
    if not parts.path.startswith(address.base):
        return f"an address outside {address.base}: {ref}"
    target = _file_for(dist, address, parts.path)
    if target is None:
        return f"a link to nothing: {ref}"
    if parts.fragment and target.suffix == ".html" and parts.fragment not in page(target).ids:
        return f"a link to an anchor that does not exist: {ref}"
    return None


# --- Astro ----------------------------------------------------------------------------

WARNING = re.compile(r"\[(WARN|ERROR)\]|^\s*\(!\)|\bwarning\b", re.IGNORECASE | re.MULTILINE)


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    env["npm_config_update_notifier"] = "false"
    env["npm_config_fund"] = "false"
    env["npm_config_audit"] = "false"
    env.setdefault("NO_COLOR", "1")
    return env


def signal_words(number: int) -> str:
    """A signal by its name and its number, ``signal SIGTERM (15)``, or by its number alone,
    ``signal 99``, when it has no name."""
    try:
        return f"signal {signal.Signals(number).name} ({number})"
    except ValueError:
        return f"signal {number}"


def install(repo: Path = REPO) -> None:
    """Install the site's packages from the lockfile, exactly as locked. An install that fails
    is refused with the step, how npm ended and what to run next; npm's own output, printed
    above the refusal, says why."""
    npm = shutil.which("npm")
    if npm is None:
        raise SiteError("npm is needed to install the site's packages; install Node.js")
    step = f"npm ci in {SITE}/"
    rerun = f"then run {step} and python3 tools/docs_site.py build"
    try:
        done = subprocess.run([npm, "ci"], cwd=repo / SITE, env=_environment(), check=False)
    except OSError as error:
        raise SiteError(
            f"{step} could not start ({error.strerror}): check that npm runs, "
            "then run python3 tools/docs_site.py build"
        ) from None
    if done.returncode < 0:
        raise SiteError(
            f"{step} was stopped by {signal_words(-done.returncode)}: run {step} again, then "
            "python3 tools/docs_site.py build"
        )
    if done.returncode != 0:
        raise SiteError(
            f"{step} failed with exit code {done.returncode}: fix what npm printed above, {rerun}"
        )


def astro_build(repo: Path = REPO) -> str:
    """Run ``astro build``; a warning or an error in its output fails the build."""
    binary = repo / SITE / "node_modules" / ".bin" / "astro"
    if not binary.exists():
        raise SiteError(f"{binary} is missing: run npm ci in {SITE}/")
    out = repo / SITE / DIST
    if out.exists():
        shutil.rmtree(out)
    try:
        done = subprocess.run(
            [str(binary), "build"],
            cwd=repo / SITE,
            env=_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise SiteError(
            f"astro build in {SITE}/ could not start ({error.strerror}): run npm ci in {SITE}/, "
            "then python3 tools/docs_site.py build"
        ) from None
    log = done.stdout + done.stderr
    if done.returncode < 0:
        raise SiteError(
            f"astro build in {SITE}/ was stopped by {signal_words(-done.returncode)}: run "
            "python3 tools/docs_site.py build again"
        )
    if done.returncode != 0:
        raise SiteError(f"astro build failed:\n{log}")
    flagged = [line for line in log.splitlines() if WARNING.search(line)]
    if flagged:
        raise SiteError("astro build printed warnings:\n" + "\n".join(flagged))
    return log


def build_site(repo: Path = REPO, *, quiet: bool = False) -> Build:
    """The whole build: prepare, whose checks refuse a build before anything is installed;
    install the packages when they are missing; then Astro and finish."""
    prepare(repo)
    if not (repo / SITE / "node_modules").is_dir():
        install(repo)
    log = astro_build(repo)
    if not quiet:
        print(log, end="")
    return finish(repo)


# --- the repository's llms.txt --------------------------------------------------------


def repository_llms(repo: Path = REPO) -> str:
    """The repository's ``llms.txt``: the same list as the site's, linking the files here."""
    return llms_text(load_build(repo), site=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docs_site.py", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="prepare, install if needed, run Astro, finish")
    commands.add_parser("prepare", help="copy the pages for Astro")
    commands.add_parser("finish", help="write the copies and llms files, and check the site")
    commands.add_parser("check", help="check a site already built")
    llms = commands.add_parser("llms", help="write the repository's llms.txt")
    llms.add_argument("--check", action="store_true", help="exit 1 when llms.txt differs")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build = build_site(REPO)
            print(f"built {build.dist}")
        elif args.command == "prepare":
            prepare(REPO)
        elif args.command == "finish":
            finish(REPO)
        elif args.command == "check":
            problems = check_site(REPO / SITE / DIST, read_address(REPO))
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0
        elif args.command == "llms":
            text = repository_llms(REPO)
            path = REPO / LLMS
            if args.check:
                if path.read_text(encoding="utf-8") != text:
                    print(
                        f"{LLMS} is out of date: run python3 tools/docs_site.py llms",
                        file=sys.stderr,
                    )
                    return 1
                return 0
            path.write_text(text, encoding="utf-8")
    except SiteError as error:
        print(f"docs_site: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
