# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The documentation site, built from a clean copy of the repository, holds what it promises.

The copy holds the files git tracks or would track, as an archive of a commit does, and
under ``docs/`` only the pages of the site, the files beside them and the README's
template. The site is built twice, in two folders, and the two builds must be identical.
The tests need Node.js and npm, and skip visibly without them. With no installed packages
in ``site/node_modules``, the build installs them from the lockfile.
"""

from __future__ import annotations

import filecmp
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pairbench.cli.main import COMMANDS
from pairbench.errors import (
    CODES,
    CONFIG_PAGE,
    EXIT_CODES,
    SHARED_COMMAND_ANCHOR,
    docs_address,
    section_address,
)
from pairbench.model import CONFIG_KEYS, TOOL_VERSION

from .conftest import load_tool
from .test_project_files import (
    LANGUAGE_TAG_PARSER_SCRIPTS,
    LANGUAGE_TAG_PARSER_TAG,
    SEARCH_PROGRAM_CRATES,
    SEARCH_PROGRAMS,
    crates_listed,
    search_program_crates,
    search_programs,
)
from .test_reference_pages import SAME_FLAGS_AS, parser_flags, parser_subcommands
from .test_share_image import ALT, HEIGHT, WIDTH

pytestmark = [pytest.mark.needs_tool("node"), pytest.mark.needs_tool("npm")]

REPO = Path(__file__).resolve().parents[3]
ROOT = "https://eugo.io/docs/pairbench/"
BASE = "/docs/pairbench/"
LATEST = f"{ROOT}latest/"
FOLDER = "0.1"
BUILD_TIMEOUT_S = 600
AI_CRAWLERS = ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended")
LLMS_LINE = (
    f"> Every page is listed in {LATEST}llms.txt; all of them are in one file at "
    f"{LATEST}llms-full.txt."
)
ITEM = re.compile(r"^- \[[^\]]+\]\(([^)\s]+)\): .+$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
# What the Markdown page at the base address links to: the latest pages and their lists.
BASE_LINKS = [LATEST, f"{LATEST}llms.txt", f"{LATEST}llms-full.txt"]
BASE_ALTERNATE = f'<link rel="alternate" type="text/markdown" href="{BASE}index.md">'
NOINDEX = '<meta name="robots" content="noindex"/>'
# What every built page says of the share image, and the card that shows it large.
SHARE = f"{ROOT}share.png"
SHARE_IMAGE = "site/public/share.png"
SHARE_TAGS = sorted(
    [
        ("og:image", SHARE),
        ("og:image:width", str(WIDTH)),
        ("og:image:height", str(HEIGHT)),
        ("og:image:alt", ALT),
        ("twitter:image", SHARE),
        ("twitter:image:alt", ALT),
        ("twitter:card", "summary_large_image"),
    ]
)
SHARE_KEYS = frozenset(key for key, _ in SHARE_TAGS)
# The pages of the site: one per navigation entry in each of two folders, the base page and
# the 404 page; the site has more than this many.
PAGES_AT_LEAST = 40
# The structured data of every page: one script of JSON-LD in the head.
LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)
CONTEXT = "https://schema.org"
PUBLISHER = {"@id": "https://eugo.io/#organization"}
LICENSE = "https://www.apache.org/licenses/LICENSE-2.0"
HOME = "index.md"
HOME_APPLICATION = {
    "@type": "SoftwareApplication",
    "name": "pairbench",
    "url": LATEST,
    "applicationCategory": "DeveloperApplication",
    "operatingSystem": "Linux, macOS",
    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
    "license": LICENSE,
    "publisher": PUBLISHER,
}
# The organisation every publisher names, as the home page defines it: no logo, since the
# repository holds none.
HOME_ORGANIZATION = {
    "@type": "Organization",
    "@id": "https://eugo.io/#organization",
    "name": "Eugo, Inc.",
    "url": "https://eugo.io/",
}
# The home page of each folder defines the organisation; no other page does.
ORGANIZATION_PAGES = [f"{FOLDER}/index.html", "latest/index.html"]
HOME_SOURCE = {
    "@type": "SoftwareSourceCode",
    "name": "pairbench",
    "codeRepository": "https://github.com/eugo-inc/pairbench",
    "programmingLanguage": "Python",
    "license": LICENSE,
    "publisher": PUBLISHER,
}
# The breadcrumbs of a few pages, as the sidebar gives them: a section with a page of its
# own sits between the home page and the pages under it.
BREADCRUMBS = {
    "index.md": [("pairbench", LATEST)],
    "install.md": [("pairbench", LATEST), ("Install", f"{LATEST}install/")],
    "method/index.md": [("pairbench", LATEST), ("How pairbench decides", f"{LATEST}method/")],
    "method/error-rates.md": [
        ("pairbench", LATEST),
        ("Method", f"{LATEST}method/"),
        ("Simulated error rates", f"{LATEST}method/error-rates/"),
    ],
    "guides/wall.md": [
        ("pairbench", LATEST),
        ("Guides", f"{LATEST}guides/"),
        ("wall", f"{LATEST}guides/wall/"),
    ],
    "changelog.md": [("pairbench", LATEST), ("Changelog", f"{LATEST}changelog/")],
}
# The id of a heading below the page's title.
HEADING_ID = re.compile(r'<h[2-6]\b[^>]*\bid="([^"]+)"')
# What the structured data never claims: questions and answers, ratings, reviews or dates.
NOT_CLAIMED_TYPES = frozenset({"FAQPage", "Question", "Answer", "Review", "AggregateRating"})
NOT_CLAIMED_KEYS = frozenset({"aggregateRating", "review", "reviews", "mainEntity"})
FETCHED = re.compile(r"<(script|link|img|iframe|source)\b[^>]*\b(src|href)=\"(https?:)?//", re.I)


def tracked(repo: Path) -> list[str]:
    done = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"needs a git checkout of the repository: {done.stderr.strip()}")
    return [name for name in done.stdout.split("\0") if name]


def kept(repo: Path, name: str, docs_site: ModuleType) -> bool:
    """Whether a clean copy keeps a file: under docs/, only what the site and README use."""
    if not name.startswith("docs/"):
        return True
    path = repo / name
    if name.startswith("docs/readme/"):
        return True
    folders = {(repo / "docs" / page).parent for page in docs_site.site_pages(repo)}
    return path.parent in folders and (path.suffix != ".md" or docs_site.is_page(path))


def build_copy(repo: Path, dest: Path, docs_site: ModuleType) -> tuple[Path, str]:
    """Copy the repository to ``dest`` as a clean archive would hold it, and build the site."""
    for name in tracked(repo):
        source = repo / name
        if source.is_file() and kept(repo, name, docs_site):
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    installed = repo / "site" / "node_modules"
    if installed.is_dir():
        (dest / "site" / "node_modules").symlink_to(installed, target_is_directory=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH")}
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    done = subprocess.run(
        [sys.executable, "tools/docs_site.py", "build"],
        cwd=dest,
        env=env,
        capture_output=True,
        text=True,
        timeout=BUILD_TIMEOUT_S,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return dest / "site" / "dist", done.stdout


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_tool(REPO, "docs_site")


@pytest.fixture(scope="module")
def built(tool: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_copy(REPO, tmp_path_factory.mktemp("first"), tool)[0]


@pytest.fixture(scope="module")
def build(tool: ModuleType) -> object:
    return tool.load_build(REPO)


def read(dist: Path, path: str) -> str:
    return (dist / path).read_text(encoding="utf-8")


def page_file(slug: str, folder: str = "latest") -> str:
    return f"{folder}/{slug}/index.html" if slug else f"{folder}/index.html"


def ids(text: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', text))


class _Meta(HTMLParser):
    """The name or property and the content of every meta tag of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        key = values.get("property") or values.get("name")
        if tag == "meta" and key:
            self.found.append((key, values.get("content", "")))


def meta(text: str) -> list[tuple[str, str]]:
    parser = _Meta()
    parser.feed(text)
    parser.close()
    return parser.found


def entry_slug(page: str) -> str:
    return page.removesuffix(".md").removesuffix("index").rstrip("/")


def latest_address(page: str) -> str:
    tail = entry_slug(page)
    return LATEST + (f"{tail}/" if tail else "")


def graph(text: str) -> list[dict[str, Any]]:
    """The nodes of the one block of structured data of a page."""
    blocks = LD_JSON.findall(text)
    assert len(blocks) == 1
    data = json.loads(blocks[0])
    assert data["@context"] == CONTEXT
    nodes: list[dict[str, Any]] = data["@graph"]
    return nodes


def node(nodes: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    found = [n for n in nodes if n["@type"] == kind]
    assert len(found) == 1, kind
    return found[0]


def walk(value: object) -> Iterator[tuple[str | None, object]]:
    """Every key and value of a JSON value, nested ones included."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key, inner
            yield from walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield None, inner
            yield from walk(inner)


def test_the_copy_holds_no_markdown_file_the_site_does_not_publish(
    tool: ModuleType, tmp_path: Path
) -> None:
    left_out = [n for n in tracked(REPO) if n.endswith(".md") and not kept(REPO, n, tool)]

    assert all(n.startswith("docs/") for n in left_out)
    assert [n for n in left_out if tool.is_page(REPO / n)] == []


def test_the_site_built_from_a_clean_copy_passes_its_own_checks(
    built: Path, tool: ModuleType
) -> None:
    assert tool.check_site(built, tool.read_address(REPO)) == []
    assert (built / "latest" / "index.html").is_file()
    assert (built / FOLDER / "index.html").is_file()


def test_two_builds_in_two_folders_give_the_same_files(
    built: Path, tool: ModuleType, tmp_path: Path
) -> None:
    again, _ = build_copy(REPO, tmp_path / "second", tool)
    first = sorted(p.relative_to(built).as_posix() for p in built.rglob("*") if p.is_file())
    second = sorted(p.relative_to(again).as_posix() for p in again.rglob("*") if p.is_file())

    assert first == second
    _, differ, errors = filecmp.cmpfiles(built, again, first, shallow=False)
    assert (differ, errors) == ([], [])


def test_llms_txt_lists_the_markdown_copy_of_every_page_in_navigation_order(
    built: Path, build: object
) -> None:
    entries = build.navigation.entries  # type: ignore[attr-defined]
    targets = ITEM.findall(read(built, "latest/llms.txt"))
    expected = [f"{LATEST}{e.page.removesuffix('index.md').removesuffix('.md')}" for e in entries]

    assert [t.removesuffix("index.md").removesuffix("/") for t in targets[: len(entries)]] == [
        e.removesuffix("/") for e in expected
    ]
    assert read(built, "llms.txt") == read(built, "latest/llms.txt")
    for section in build.navigation.sections:  # type: ignore[attr-defined]
        assert len(ITEM.findall(read(built, f"latest/{section.slug}/llms.txt"))) == len(
            section.entries
        )
    full = read(built, "latest/llms-full.txt")
    for entry in entries:
        assert f"\n# {build.pages[entry.page].title}\n" in full  # type: ignore[attr-defined]


def test_every_page_has_its_markdown_copy_and_links_it(built: Path, build: object) -> None:
    for entry in build.navigation.entries:  # type: ignore[attr-defined]
        page = build.pages[entry.page]  # type: ignore[attr-defined]
        slug = entry.page.removesuffix(".md").removesuffix("index").rstrip("/")
        folder = f"latest/{slug}" if slug else "latest"
        copy = read(built, f"{folder}/index.md")
        beside = read(built, f"latest/{slug}.md" if slug else "latest.md")
        markdown = f"{BASE}{folder}/index.md"
        link = f'<link rel="alternate" type="text/markdown" href="{markdown}"/>'

        assert copy == beside
        assert copy.split("\n\n")[:3] == [LLMS_LINE, f"# {page.title}", f"> {page.description}"]
        assert f"pairbench {TOOL_VERSION}." in copy
        assert link in read(built, page_file(slug))


def test_every_page_carries_its_description_canonical_link_and_version(
    built: Path, build: object
) -> None:
    for entry in build.navigation.entries:  # type: ignore[attr-defined]
        page = build.pages[entry.page]  # type: ignore[attr-defined]
        slug = entry.page.removesuffix(".md").removesuffix("index").rstrip("/")
        latest = LATEST + (f"{slug}/" if slug else "")
        for folder in ("latest", FOLDER):
            text = read(built, page_file(slug, folder))
            described = re.findall(r'<meta name="description" content="([^"]*)"/>', text)
            assert [html.unescape(d) for d in described] == [page.description]
            assert f'<link rel="canonical" href="{latest}"/>' in text
            assert f'<meta name="pairbench-version" content="{TOOL_VERSION}"/>' in text


def test_the_sitemap_and_robots_txt_are_built_for_the_address(built: Path) -> None:
    robots = read(built, "robots.txt")
    sitemap = read(built, "sitemap-0.xml")

    assert f"<loc>{LATEST}</loc>" in sitemap
    assert f"/{FOLDER}/" not in sitemap
    assert f"Sitemap: {ROOT}sitemap-index.xml" in robots
    assert f"{LATEST}llms.txt" in robots
    for crawler in AI_CRAWLERS:
        assert f"User-agent: {crawler}\nAllow: {BASE}\n" in robots


def test_the_base_address_sends_the_reader_to_the_latest_pages(built: Path) -> None:
    text = read(built, "index.html")

    assert f'<meta http-equiv="refresh" content="0; url={BASE}latest/">' in text
    assert f'<link rel="canonical" href="{LATEST}">' in text


def test_the_base_address_has_both_llms_files_and_a_markdown_page(
    built: Path, build: object
) -> None:
    summary = build.navigation.summary  # type: ignore[attr-defined]
    text = read(built, "index.md")
    links = MARKDOWN_LINK.findall(text)
    files = [
        built / (path + "index.html" if path.endswith("/") else path)
        for path in (link.removeprefix(ROOT) for link in links)
    ]

    assert read(built, "llms-full.txt") == read(built, "latest/llms-full.txt")
    assert text.split("\n\n")[:2] == ["# pairbench documentation", f"> {summary}"]
    assert links == BASE_LINKS
    assert [path.relative_to(built).as_posix() for path in files if not path.is_file()] == []
    assert BASE_ALTERNATE in read(built, "index.html")


def test_a_real_404_page_names_no_address_of_its_own(built: Path) -> None:
    text = read(built, "404.html")

    assert "<title>Page not found | pairbench</title>" in text
    assert 'rel="canonical"' not in text
    assert 'property="og:url"' not in text


def test_the_404_page_asks_search_engines_not_to_index_it(built: Path) -> None:
    assert NOINDEX in read(built, "404.html")


def test_every_page_names_the_share_image_and_the_image_is_in_the_site(built: Path) -> None:
    pages = sorted(built.rglob("*.html"))
    wrong = [
        path.relative_to(built).as_posix()
        for path in pages
        if sorted(pair for pair in meta(path.read_text(encoding="utf-8")) if pair[0] in SHARE_KEYS)
        != SHARE_TAGS
    ]
    image = built / SHARE.removeprefix(ROOT)
    share = load_tool(REPO, "share_image")

    assert len(pages) > PAGES_AT_LEAST
    assert {"index.html", "404.html", "latest/index.html", f"{FOLDER}/index.html"} <= {
        path.relative_to(built).as_posix() for path in pages
    }
    assert wrong == []
    assert image.read_bytes() == (REPO / SHARE_IMAGE).read_bytes()
    assert share.size(image.read_bytes()) == (WIDTH, HEIGHT)


def test_every_page_carries_one_block_of_structured_data_and_no_other_page_does(
    built: Path, build: object
) -> None:
    entries = build.navigation.entries  # type: ignore[attr-defined]
    folders = ("latest", FOLDER)
    pages = [page_file(entry_slug(e.page), folder) for e in entries for folder in folders]
    for name in pages:
        assert graph(read(built, name)), name
    carrying = sorted(
        path.relative_to(built).as_posix()
        for path in built.rglob("*.html")
        if LD_JSON.search(path.read_text(encoding="utf-8"))
    )

    assert carrying == sorted(pages)
    assert LD_JSON.findall(read(built, "404.html")) == []
    assert LD_JSON.findall(read(built, "index.html")) == []


def test_the_home_page_describes_the_software_and_its_source(built: Path, build: object) -> None:
    nodes = graph(read(built, page_file("")))
    application = node(nodes, "SoftwareApplication")
    source = node(nodes, "SoftwareSourceCode")
    summary = build.navigation.summary  # type: ignore[attr-defined]

    assert {key: application.get(key) for key in HOME_APPLICATION} == HOME_APPLICATION
    assert {key: source.get(key) for key in HOME_SOURCE} == HOME_SOURCE
    assert (application["description"], source["description"]) == (summary, summary)
    assert [n["@type"] for n in nodes if n["@type"] == "TechArticle"] == []
    assert node(nodes, "Organization") == HOME_ORGANIZATION


def references(value: object) -> list[str]:
    """The identifier of every node a JSON value names by its identifier alone."""
    if isinstance(value, dict):
        if set(value) == {"@id"}:
            return [str(value["@id"])]
        return [ref for inner in value.values() for ref in references(inner)]
    if isinstance(value, list):
        return [ref for inner in value for ref in references(inner)]
    return []


def test_every_publisher_and_named_node_is_defined_on_the_home_page_or_its_own_page(
    built: Path,
) -> None:
    home = {n["@id"] for n in graph(read(built, page_file("")))}
    publishers: list[str] = []
    named: list[str] = []
    defining: list[str] = []
    for path in sorted(built.rglob("*.html")):
        name = path.relative_to(built).as_posix()
        for block in LD_JSON.findall(path.read_text(encoding="utf-8")):
            nodes = json.loads(block)["@graph"]
            own = {n["@id"] for n in nodes}
            publishers += [n["publisher"]["@id"] for n in nodes if "publisher" in n]
            named += [f"{name}: {ref}" for ref in references(nodes) if ref not in home | own]
            if any(n["@type"] == "Organization" for n in nodes):
                defining.append(name)

    assert len(publishers) > PAGES_AT_LEAST
    assert set(publishers) == {HOME_ORGANIZATION["@id"]}
    assert HOME_ORGANIZATION["@id"] in home
    assert named == []
    assert defining == ORGANIZATION_PAGES


def test_every_other_page_is_an_article_of_the_publisher(built: Path, build: object) -> None:
    for entry in build.navigation.entries:  # type: ignore[attr-defined]
        if entry.page == HOME:
            continue
        page = build.pages[entry.page]  # type: ignore[attr-defined]
        article = node(graph(read(built, page_file(entry_slug(entry.page)))), "TechArticle")
        assert (article["headline"], article["description"]) == (page.title, page.description)
        assert (article["url"], article["publisher"]) == (latest_address(entry.page), PUBLISHER)


def test_the_breadcrumbs_of_every_page_follow_the_sidebar(built: Path, build: object) -> None:
    trails: dict[str, list[tuple[str, str]]] = {}
    for entry in build.navigation.entries:  # type: ignore[attr-defined]
        nodes = graph(read(built, page_file(entry_slug(entry.page))))
        items = node(nodes, "BreadcrumbList")["itemListElement"]
        trail = [(item["name"], item["item"]) for item in items]
        trails[entry.page] = trail
        assert [item["position"] for item in items] == list(range(1, len(items) + 1))
        assert trail[0] == ("pairbench", LATEST)
        if entry.page != HOME:
            assert trail[-1] == (entry.label, latest_address(entry.page))

    assert {page: trails[page] for page in BREADCRUMBS} == BREADCRUMBS


def test_the_structured_data_claims_no_questions_ratings_reviews_or_dates(built: Path) -> None:
    claimed: list[str] = []
    for path in built.rglob("*.html"):
        for block in LD_JSON.findall(path.read_text(encoding="utf-8")):
            for key, value in walk(json.loads(block)):
                if key in NOT_CLAIMED_KEYS or (key or "").lower().startswith("date"):
                    claimed.append(f"{path.relative_to(built)}: {key}")
                if key == "@type" and value in NOT_CLAIMED_TYPES:
                    claimed.append(f"{path.relative_to(built)}: {value}")

    assert claimed == []


def test_a_versioned_page_carries_the_structured_data_of_its_latest_page(
    built: Path, build: object
) -> None:
    for entry in build.navigation.entries:  # type: ignore[attr-defined]
        slug = entry_slug(entry.page)
        latest = LD_JSON.findall(read(built, page_file(slug)))
        versioned = LD_JSON.findall(read(built, page_file(slug, FOLDER)))
        assert (len(latest), versioned) == (1, latest), entry.page


def test_every_address_in_the_structured_data_is_a_built_latest_page(built: Path) -> None:
    addresses: set[str] = set()
    for path in built.rglob("*.html"):
        for block in LD_JSON.findall(path.read_text(encoding="utf-8")):
            addresses |= {
                value
                for _, value in walk(json.loads(block))
                if isinstance(value, str) and value.startswith(ROOT)
            }
    wrong = [a for a in sorted(addresses) if not a.startswith(LATEST)]
    files = {a: built / (a.removeprefix(ROOT).split("#", 1)[0] + "index.html") for a in addresses}

    assert len(addresses) > PAGES_AT_LEAST
    assert wrong == []
    assert [a for a, file in sorted(files.items()) if not file.is_file()] == []


def test_every_text_code_and_exit_code_has_its_anchor_where_the_refusal_points(
    built: Path,
) -> None:
    for folder in ("latest", FOLDER):
        found = ids(read(built, f"{folder}/reference/exit-codes/index.html"))
        assert {code.lower() for code in CODES} <= found
        assert {f"exit-code-{code}" for code in EXIT_CODES} <= found
    address = docs_address("E_USAGE", TOOL_VERSION)
    path, _, anchor = address.removeprefix(ROOT).partition("#")
    assert anchor in ids(read(built, f"{path}index.html"))


def test_the_note_after_a_run_points_at_a_section_the_config_page_has(built: Path) -> None:
    for folder in ("latest", FOLDER):
        assert SHARED_COMMAND_ANCHOR in ids(read(built, f"{folder}/reference/config/index.html"))
    address = section_address(CONFIG_PAGE, SHARED_COMMAND_ANCHOR, TOOL_VERSION)
    path, _, anchor = address.removeprefix(ROOT).partition("#")
    assert anchor in ids(read(built, f"{path}index.html"))


def test_every_config_key_command_and_flag_has_its_anchor(built: Path) -> None:
    config = ids(read(built, "latest/reference/config/index.html"))
    commands = ids(read(built, "latest/reference/commands/index.html"))

    assert sorted(set(CONFIG_KEYS) - config) == []
    assert sorted(set(COMMANDS) - commands) == []
    subcommands = {f"{c}-{s}" for c in COMMANDS for s in parser_subcommands(c)}
    assert sorted(subcommands - commands) == []
    missing: list[str] = []
    for command in COMMANDS:
        for flag in parser_flags(command):
            names = {f"{command}--{flag[2:]}", f"{SAME_FLAGS_AS.get(command, command)}--{flag[2:]}"}
            if not names & commands:
                missing.append(f"{command} {flag}")
    assert missing == []


def test_the_anchors_the_build_reads_from_a_page_are_the_anchors_of_the_built_page(
    built: Path, build: object, tool: ModuleType
) -> None:
    # Before the install the build reads each page's anchors from its text: every one of them
    # must be an id of the built page, and every heading of the built page must be one of them.
    wrong: dict[str, tuple[list[str], list[str]]] = {}
    pages = build.pages.values()  # type: ignore[attr-defined]
    for page in pages:
        text = read(built, page_file(entry_slug(page.path)))
        read_ids = tool.site_anchors(page)
        headings = {i for i in HEADING_ID.findall(text) if not i.startswith("starlight__")}
        if read_ids - ids(text) or headings - read_ids:
            wrong[page.path] = (sorted(read_ids - ids(text)), sorted(headings - read_ids))
    assert len(pages) >= PAGES_AT_LEAST // 2
    assert wrong == {}


def test_every_crate_the_search_programs_name_is_in_the_third_party_notices(
    built: Path,
) -> None:
    programs = search_programs(built)
    named: dict[str, str] = {}
    for program in programs:
        named.update(search_program_crates((built / program).read_bytes()))

    assert programs == sorted(SEARCH_PROGRAMS)
    assert named == SEARCH_PROGRAM_CRATES
    assert sorted(set(named.items()) - crates_listed(REPO)) == []


def test_the_language_tag_parser_is_in_the_search_scripts_the_third_party_notices_name(
    built: Path,
) -> None:
    holding = sorted(
        path.relative_to(built).as_posix()
        for path in (built / "pagefind").glob("*.js")
        if LANGUAGE_TAG_PARSER_TAG in path.read_text(encoding="utf-8")
    )

    assert holding == sorted(LANGUAGE_TAG_PARSER_SCRIPTS)


def test_every_public_python_name_has_its_anchor(built: Path) -> None:
    found = ids(read(built, "latest/reference/python-names/index.html"))
    names = load_tool(REPO, "api_reference").anchors(REPO)

    assert len(names) >= 60
    assert [name for name in names if name not in found] == []


def test_the_site_shows_no_dates_editors_or_edit_links(built: Path) -> None:
    shown: list[str] = []
    for path in built.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for words in ("Last updated", "Edit page", "Contributors", "datetime="):
            if words in text:
                shown.append(f"{path.relative_to(built)}: {words}")

    assert shown == []


def test_the_set_up_notes_name_the_node_version_the_pinned_astro_asks_for() -> None:
    package = REPO / "site" / "node_modules" / "astro" / "package.json"
    if not package.is_file():
        pytest.skip("needs the site's packages installed in site/node_modules (npm ci in site/)")
    wanted = json.loads(package.read_text(encoding="utf-8"))["engines"]["node"]
    lowest = re.findall(r">=\s*(\d+\.\d+\.\d+)", wanted)[-1]

    for name in ("CONTRIBUTING.md", "AGENTS.md"):
        text = " ".join((REPO / name).read_text(encoding="utf-8").split())
        assert f"Node.js {lowest} or newer" in text, name


def test_nothing_on_the_site_is_fetched_from_another_host(built: Path) -> None:
    found: list[str] = []
    for path in built.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in FETCHED.finditer(text):
            tag = match.group(0)
            if 'rel="canonical"' in tag or 'rel="sitemap"' in tag:
                continue
            found.append(f"{path.relative_to(built)}: {tag}")

    assert found == []
