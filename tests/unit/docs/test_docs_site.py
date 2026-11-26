# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The site generator: its checks of a built site, its anchors and its addresses."""

from __future__ import annotations

import html
import itertools
import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType

import pytest

from .conftest import load_tool
from .test_share_image import ALT, HEIGHT, LOGO, REFUSED, REMEDY, WIDTH, chunk

SITE = "https://docs.example.org"
# The switch that keeps Astro from sending usage data, as npm ci and the Astro build get it.
TELEMETRY = ("ASTRO_TELEMETRY_DISABLED", "1")
# The build script of the site's package: the site's own build, with that switch.
SITE_BUILD_SCRIPT = "python3 ../tools/docs_site.py build"
BASE = "/tool/"
CANONICAL = f'<link rel="canonical" href="{SITE}{BASE}latest/a/">'
GOOD_PAGE = (
    f"<html><head>{CANONICAL}</head><body>"
    f'<h2 id="here">Here</h2><a href="{BASE}latest/a/#here">here</a>'
    '<a href="https://other.example.org/page/">another site</a>'
    "</body></html>"
)


# The Markdown page at the base address of a made-up site, for a made-up tool.
BASE_MARKDOWN = (
    "# tool documentation\n"
    "\n"
    "> The tool says whether a thing is so.\n"
    "\n"
    "- [Latest pages](https://docs.example.org/tool/latest/): every page of tool 9.8.7; the "
    "Markdown copy of a page is at its address plus `index.md`.\n"
    "- [llms.txt](https://docs.example.org/tool/latest/llms.txt): the list of the pages, each "
    "with a line on what it holds.\n"
    "- [llms-full.txt](https://docs.example.org/tool/latest/llms-full.txt): every page in one "
    "file.\n"
)
MARKDOWN_ALTERNATE = '<link rel="alternate" type="text/markdown" href="/tool/index.md">'
# The share image of the made-up site: its address, and what every page says of it.
SHARE = f"{SITE}{BASE}share.png"
ELSEWHERE = "https://cdn.example.org/share.png"
SHARE_TAGS = [
    ("og:image", SHARE),
    ("og:image:width", str(WIDTH)),
    ("og:image:height", str(HEIGHT)),
    ("og:image:alt", ALT),
    ("twitter:image", SHARE),
    ("twitter:image:alt", ALT),
]
# What the build says of a share image in site/public that its script would not write, and of
# the one the built site publishes, after the cause: how to write the image, and then the site.
SOURCE_IMAGE = "site/public/share.png"
CUT_SHORT_IMAGE = (
    f"{SOURCE_IMAGE} is cut short (it ends before its IEND chunk): run python3 tools/share_image.py"
)
PUBLISHED_REMEDY = f"{REMEDY}, then python3 tools/docs_site.py build"
EXIT_OK = 0
EXIT_REFUSED = 1
# Chunks a PNG file can hold beside its pixels, with made-up contents: text, international
# text and Exif data (a big-endian TIFF header and an empty directory).
PLANTED = {
    b"tEXt": b"Comment\x00made-up text",
    b"iTXt": b"Comment\x00\x00\x00\x00\x00made-up text",
    b"eXIf": b"MM\x00\x2a\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00",
}
# The committed share image: the signature and the IHDR chunk take its first 33 bytes, the
# IEND chunk its last 12.
HEADER_END = 33
END_LENGTH = 12
# The settings of the made-up site, as its Astro config holds them.
ASTRO_CONFIG = f"const SITE = '{SITE}';\nconst BASE = '{BASE}';\n"

# The structured data of a made-up site of four pages in two sections: the home page and one
# more page in the first section, and in the second a section page and one page under it.
LATEST = f"{SITE}{BASE}latest/"
ORGANIZATION = {"@id": f"{SITE}/#organization"}
# The organisation that publishes the software: the package's author, the citation's author
# and the holder of the copyright in NOTICE and in the licence header.
PUBLISHER_NAME = "Eugo, Inc."
# The organisation at the root of the host, as the home page defines it: the name, address
# and logo the home page of the host gives the same organisation, and profiles of it.
ORGANIZATION_NODE = {
    "@type": "Organization",
    "@id": f"{SITE}/#organization",
    "name": "Eugo",
    "url": "https://eugo.io",
    "logo": "https://eugo.io/eugo-search-logo.png",
    "sameAs": [
        "https://www.youtube.com/@eugo-inc",
        "https://github.com/eugo-inc",
    ],
}
# How many nodes of the made-up site name the publisher: the software and its source on the
# home page, and the article on each of the three other pages.
PUBLISHER_REFERENCES = 5
# The systems the software runs on, as the package classifiers name them and as the
# structured data writes them.
OPERATING_SYSTEMS = "Linux, macOS"
SYSTEM_CLASSIFIERS = {
    "Operating System :: POSIX :: Linux": "Linux",
    "Operating System :: MacOS": "macOS",
}
SUMMARY = "The tool says whether a thing is so."
LICENSE = "https://www.apache.org/licenses/LICENSE-2.0"
SOURCE = "https://github.com/eugo-inc/pairbench"
HOME_GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "SoftwareApplication",
            "@id": f"{LATEST}#software",
            "name": "tool",
            "description": SUMMARY,
            "url": LATEST,
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": OPERATING_SYSTEMS,
            "softwareVersion": "9.8.7",
            "license": LICENSE,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "publisher": ORGANIZATION,
        },
        {
            "@type": "SoftwareSourceCode",
            "@id": f"{LATEST}#source",
            "name": "tool",
            "description": SUMMARY,
            "codeRepository": SOURCE,
            "programmingLanguage": "Python",
            "license": LICENSE,
            "targetProduct": {"@id": f"{LATEST}#software"},
            "publisher": ORGANIZATION,
        },
        ORGANIZATION_NODE,
        {
            "@type": "BreadcrumbList",
            "@id": f"{LATEST}#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "tool", "item": LATEST},
            ],
        },
    ],
}
WALL = f"{LATEST}guides/wall/"
WALL_GRAPH = {
    "@context": "https://schema.org",
    "@graph": [
        {
            "@type": "TechArticle",
            "@id": f"{WALL}#article",
            "headline": "Time a whole command",
            "description": "How the wall driver times a command & what it reads.",
            "url": WALL,
            "inLanguage": "en",
            "about": {"@id": f"{LATEST}#software"},
            "publisher": ORGANIZATION,
        },
        {
            "@type": "BreadcrumbList",
            "@id": f"{WALL}#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "tool", "item": LATEST},
                {"@type": "ListItem", "position": 2, "name": "Guides", "item": f"{LATEST}guides/"},
                {"@type": "ListItem", "position": 3, "name": "wall", "item": WALL},
            ],
        },
    ],
}
# The names and addresses of the breadcrumbs of the two other pages: a page of the first
# section and a section page sit right under the home page.
OTHER_CRUMBS = {
    "install.md": [("tool", LATEST), ("Install", f"{LATEST}install/")],
    "guides/index.md": [("tool", LATEST), ("Choose a driver", f"{LATEST}guides/")],
}
LD_JSON = {"tag": "script", "attrs": {"type": "application/ld+json"}}


def write(dist: Path, name: str, text: str) -> None:
    path = dist / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def address(docs_site: ModuleType) -> object:
    return docs_site.Address(SITE, BASE)


def small_build(docs_site: ModuleType, repo: Path, address: object) -> object:
    """A build of a made-up site with no pages, its latest folder made."""
    navigation = docs_site.Navigation(
        "tool", "The tool says whether a thing is so.", "More about the tool.", (), ()
    )
    build = docs_site.Build(repo, address, "9.8.7", navigation, {}, SOURCE)
    (build.dist / "latest").mkdir(parents=True)
    return build


def paged_build(docs_site: ModuleType, repo: Path, address: object) -> object:
    """A build of a made-up site of four pages in two sections."""

    def entry(page: str, label: str, section: str) -> object:
        return docs_site.Entry(page, label, section, section.lower())

    start = (entry("index.md", "Home", "Start"), entry("install.md", "Install", "Start"))
    guides = (
        entry("guides/index.md", "Choose a driver", "Guides"),
        entry("guides/wall.md", "wall", "Guides"),
    )
    sections = (
        docs_site.Section("Start", "start", start),
        docs_site.Section("Guides", "guides", guides),
    )
    navigation = docs_site.Navigation("tool", SUMMARY, "More about the tool.", sections, ())
    descriptions = {
        "index.md": ("tool", SUMMARY),
        "install.md": ("Install the tool", "How to install the tool."),
        "guides/index.md": ("Choose a driver", "Which driver reads a benchmark."),
        "guides/wall.md": (
            "Time a whole command",
            "How the wall driver times a command & what it reads.",
        ),
    }
    pages = {
        path: docs_site.Page(path, title, description, "Body.\n")
        for path, (title, description) in descriptions.items()
    }
    return docs_site.Build(repo, address, "9.8.7", navigation, pages, SOURCE)


def check(docs_site: ModuleType, dist: Path, address: object, page: str) -> list[str]:
    write(dist, "latest/a/index.html", page)
    return list(docs_site.check_site(dist, address))


def test_a_site_whose_links_resolve_has_no_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    assert check(docs_site, tmp_path, address, GOOD_PAGE) == []


def test_a_link_to_an_anchor_that_does_not_exist_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace("#here", "#gone")

    assert check(docs_site, tmp_path, address, page) == [
        f"latest/a/index.html: a link to an anchor that does not exist: {BASE}latest/a/#gone"
    ]


def test_a_link_to_a_page_that_does_not_exist_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace(f"{BASE}latest/a/#here", f"{BASE}latest/b/")

    assert check(docs_site, tmp_path, address, page) == [
        f"latest/a/index.html: a link to nothing: {BASE}latest/b/"
    ]


def test_a_link_to_the_root_of_the_host_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace(f"{BASE}latest/a/#here", "/a/")

    assert check(docs_site, tmp_path, address, page) == [
        f"latest/a/index.html: an address outside {BASE}: /a/"
    ]


def test_a_script_or_a_font_from_another_host_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace(
        "</head>",
        '<script src="https://cdn.example.org/x.js"></script>'
        '<link rel="stylesheet" href="https://fonts.example.org/f.css"></head>',
    )

    assert check(docs_site, tmp_path, address, page) == [
        "latest/a/index.html: fetches from another host: https://cdn.example.org/x.js",
        "latest/a/index.html: fetches from another host: https://fonts.example.org/f.css",
    ]


def test_a_date_in_a_page_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace("<h2", "<p>Updated 2031-02-03</p><h2")

    assert check(docs_site, tmp_path, address, page) == [
        "latest/a/index.html: holds a date: 2031-02-03"
    ]


def test_a_page_without_one_canonical_link_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace(CANONICAL, "")

    assert check(docs_site, tmp_path, address, page) == ["latest/a/index.html: 0 canonical links"]


def test_an_id_used_twice_is_a_problem(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    page = GOOD_PAGE.replace("</body>", '<p id="here">again</p></body>')

    assert check(docs_site, tmp_path, address, page) == [
        "latest/a/index.html: ids used twice: here"
    ]


def test_the_base_address_holds_the_list_of_every_page_in_one_file_too(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = small_build(docs_site, tmp_path, address)

    docs_site.write_llms(build)

    dist = tmp_path / "site" / "dist"
    assert (dist / "llms-full.txt").read_text(encoding="utf-8") == (
        dist / "latest" / "llms-full.txt"
    ).read_text(encoding="utf-8")
    assert (dist / "llms.txt").read_text(encoding="utf-8") == (
        dist / "latest" / "llms.txt"
    ).read_text(encoding="utf-8")


def test_the_base_address_has_a_markdown_page_that_points_to_the_latest_pages(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = small_build(docs_site, tmp_path, address)

    docs_site.write_base(build)

    dist = tmp_path / "site" / "dist"
    assert (dist / "index.md").read_text(encoding="utf-8") == BASE_MARKDOWN
    assert MARKDOWN_ALTERNATE in (dist / "index.html").read_text(encoding="utf-8")


def _meta(page: str) -> list[tuple[str, str]]:
    """The name or property and the content of every meta tag of a page."""
    found = re.findall(r'<meta (?:name|property)="([^"]+)" content="([^"]*)">', page)
    return [(key, html.unescape(content)) for key, content in found]


def test_every_page_names_the_share_image_by_its_address_size_and_alt_text(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = small_build(docs_site, tmp_path, address)
    head = docs_site.share_head(build)
    named = [
        (e["attrs"].get("property", e["attrs"].get("name")), e["attrs"]["content"]) for e in head
    ]

    assert [e["tag"] for e in head] == ["meta"] * len(SHARE_TAGS)
    assert named == SHARE_TAGS
    shown = _meta(docs_site.base_page(build))
    assert [pair for pair in shown if pair in SHARE_TAGS] == SHARE_TAGS
    assert ("twitter:card", "summary_large_image") in shown


def test_a_share_image_that_is_not_in_the_site_or_is_on_another_host_is_a_problem(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path, address: object
) -> None:
    tags = (
        f'<meta property="og:image" content="{SHARE}">'
        f'<meta name="twitter:image" content="{ELSEWHERE}">'
    )
    page = GOOD_PAGE.replace("</head>", f"{tags}</head>")

    assert check(docs_site, tmp_path, address, page) == [
        f"latest/a/index.html: a link to nothing: {SHARE}",
        f"latest/a/index.html: fetches from another host: {ELSEWHERE}",
    ]
    shutil.copy2(repo_root / SOURCE_IMAGE, tmp_path / "share.png")
    assert check(docs_site, tmp_path, address, page) == [
        f"latest/a/index.html: fetches from another host: {ELSEWHERE}",
    ]


@pytest.fixture(scope="module")
def drawn() -> bytes:
    """The rows the share image's script draws, each led by its filter byte."""
    rows: bytes = load_tool(Path(__file__).resolve().parents[3], "share_image").render()
    return rows


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_the_check_of_a_built_site_refuses_a_published_share_image_and_names_the_cause(
    docs_site: ModuleType, tmp_path: Path, address: object, drawn: bytes, case: str
) -> None:
    make, cause = REFUSED[case]
    (tmp_path / "share.png").write_bytes(make(drawn))

    assert docs_site.check_site(tmp_path, address) == [f"share.png {cause}: {PUBLISHED_REMEDY}"]


def staged_script(repo_root: Path, repo: Path) -> None:
    """Put the share image's script, and the maker's logo it draws, in a repository of its own."""
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "site" / "public").mkdir(parents=True, exist_ok=True)
    (repo / LOGO).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "tools" / "share_image.py", repo / "tools" / "share_image.py")
    shutil.copy2(repo_root / LOGO, repo / LOGO)


def staged_image(repo_root: Path, repo: Path) -> Path:
    """A repository of its own that holds the share image's script, the logo it draws and the
    committed image."""
    staged_script(repo_root, repo)
    shutil.copy2(repo_root / SOURCE_IMAGE, repo / SOURCE_IMAGE)
    return repo / SOURCE_IMAGE


def test_the_build_refuses_a_share_image_its_generator_would_not_draw(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    image = staged_image(repo_root, tmp_path)
    docs_site.check_share_image(tmp_path)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.check_share_image(tmp_path)
    assert str(raised.value) == CUT_SHORT_IMAGE


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_the_build_names_why_it_refuses_a_share_image(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    drawn: bytes,
    case: str,
) -> None:
    make, cause = REFUSED[case]
    staged_image(repo_root, tmp_path).write_bytes(make(drawn))
    monkeypatch.setattr(docs_site, "REPO", tmp_path)
    monkeypatch.setattr(docs_site, "load_build", lambda repo: paged_build(docs_site, repo, address))
    monkeypatch.setattr(docs_site, "check_generated_pages", lambda repo: None)

    assert docs_site.main(["prepare"]) == EXIT_REFUSED
    assert capsys.readouterr() == ("", f"docs_site: {SOURCE_IMAGE} {cause}: {REMEDY}\n")
    assert [f for f in (docs_site.CONTENT, docs_site.GENERATED) if (tmp_path / f).exists()] == []


def test_the_build_writes_nothing_when_the_share_image_is_out_of_date(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged_script(repo_root, tmp_path)
    (tmp_path / "site/public/share.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(docs_site, "load_build", lambda repo: paged_build(docs_site, repo, address))
    monkeypatch.setattr(docs_site, "check_generated_pages", lambda repo: None)

    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.prepare(tmp_path)
    assert str(raised.value) == CUT_SHORT_IMAGE
    assert [f for f in (docs_site.CONTENT, docs_site.GENERATED) if (tmp_path / f).exists()] == []


@pytest.mark.parametrize("place", ["before the pixels", "after the pixels"])
@pytest.mark.parametrize("kind", sorted(PLANTED))
def test_the_build_refuses_a_share_image_with_a_chunk_beside_its_pixels(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path, kind: bytes, place: str
) -> None:
    staged_script(repo_root, tmp_path)
    image = tmp_path / "site/public/share.png"
    shutil.copy2(repo_root / "site/public/share.png", image)
    committed = image.read_bytes()
    head, rows, end = (
        committed[:HEADER_END],
        committed[HEADER_END:-END_LENGTH],
        committed[-END_LENGTH:],
    )
    planted = chunk(kind, PLANTED[kind])
    docs_site.check_share_image(tmp_path)

    assert (head[12:16], rows[4:8], end[4:8]) == (b"IHDR", b"IDAT", b"IEND")
    if place == "before the pixels":
        image.write_bytes(head + planted + rows + end)
    else:
        image.write_bytes(head + rows + planted + end)
    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.check_share_image(tmp_path)
    assert str(raised.value) == (
        f"{SOURCE_IMAGE} has an extra chunk ({kind.decode()}): run python3 tools/share_image.py"
    )


def astro_stand_in(docs_site: ModuleType, build: object) -> Path:
    """What the Astro step leaves in site/dist for the made-up site: a page with its one
    canonical link for every page, the folder of assets, and the share image copied from
    site/public as it is."""
    dist: Path = build.dist  # type: ignore[attr-defined]
    for page in build.pages:  # type: ignore[attr-defined]
        tail = docs_site.slug(page)
        folder = dist / "latest" / tail if tail else dist / "latest"
        address = SITE + docs_site.page_path(build.address, page)  # type: ignore[attr-defined]
        write(folder, "index.html", f'<html><head><link rel="canonical" href="{address}"></head>')
    (dist / "_astro").mkdir()
    shutil.copy2(build.repo / SOURCE_IMAGE, dist / "share.png")  # type: ignore[attr-defined]
    return dist


@pytest.mark.parametrize("planted", [False, True])
def test_the_finish_step_and_the_check_refuse_a_published_share_image_with_a_text_chunk(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    planted: bool,
) -> None:
    staged_image(repo_root, tmp_path)
    write(tmp_path, "site/astro.config.mjs", ASTRO_CONFIG)
    monkeypatch.setattr(docs_site, "REPO", tmp_path)
    monkeypatch.setattr(docs_site, "load_build", lambda repo: paged_build(docs_site, repo, address))
    monkeypatch.setattr(docs_site, "check_generated_pages", lambda repo: None)
    assert docs_site.main(["prepare"]) == EXIT_OK
    dist = astro_stand_in(docs_site, paged_build(docs_site, tmp_path, address))
    published = dist / "share.png"
    image = published.read_bytes()
    if planted:
        text = chunk(b"tEXt", PLANTED[b"tEXt"])
        published.write_bytes(image[:HEADER_END] + text + image[HEADER_END:])
    problem = f"share.png has an extra chunk (tEXt): {PUBLISHED_REMEDY}"

    finished = docs_site.main(["finish"])
    finish_streams = capsys.readouterr()
    checked = docs_site.main(["check"])
    check_streams = capsys.readouterr()

    if planted:
        assert (finished, finish_streams) == (
            EXIT_REFUSED,
            ("", f"docs_site: the built site has problems:\n{problem}\n"),
        )
        assert (checked, check_streams) == (EXIT_REFUSED, ("", f"{problem}\n"))
    else:
        assert (finished, finish_streams) == (EXIT_OK, ("", ""))
        assert (checked, check_streams) == (EXIT_OK, ("", ""))


# A copy of what the build reads, as a repository of its own: the pages, the site's settings,
# the package's settings and source, the two scripts the checks run, the share image, and the
# files of the repository the pages link, whose links the build checks.
BUILD_INPUTS = (
    "docs",
    "src",
    "site/navigation.json",
    "site/astro.config.mjs",
    SOURCE_IMAGE,
    "pyproject.toml",
    "tools/share_image.py",
    "tools/api_reference.py",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "showcases",
)
GENERATED_PAGE = "docs/reference/python-names.md"
# A stand-in for npm that writes the folder it runs in and its arguments to a file, and does
# nothing else.
NPM_STAND_IN = '#!/bin/sh\nprintf "%s %s\\n" "$(pwd -P)" "$*" >> "{calls}"\n'


def copy_build_inputs(repo_root: Path, repo: Path) -> None:
    for name in BUILD_INPUTS:
        source, target = repo_root / name, repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, target)


def plant_text(repo: Path) -> None:
    image = repo / SOURCE_IMAGE
    data = image.read_bytes()
    image.write_bytes(data[:HEADER_END] + chunk(b"tEXt", PLANTED[b"tEXt"]) + data[HEADER_END:])


def add_line(repo: Path) -> None:
    with (repo / GENERATED_PAGE).open("a", encoding="utf-8") as page:
        page.write("A line the script does not write.\n")


def set_version(version: str) -> Callable[[Path], None]:
    """Spoil a copy with ``version`` as the version of the package."""

    def spoil(repo: Path) -> None:
        path = repo / "pyproject.toml"
        text = path.read_text(encoding="utf-8")
        new = re.sub(r'(?m)^version = "[^"]*"$', f'version = "{version}"', text)
        path.write_text(new, encoding="utf-8")

    return spoil


drop_minor = set_version("1")


FAQ = "docs/faq.md"


def add_to_faq(text: str) -> Callable[[Path], None]:
    """Spoil a copy with ``text`` at the end of the FAQ page, after a blank line."""

    def spoil(repo: Path) -> None:
        with (repo / FAQ).open("a", encoding="utf-8") as page:
            page.write(f"\n{text}")

    return spoil


def link_from_faq(target: str) -> Callable[[Path], None]:
    """Spoil a copy with a link from the FAQ page to ``target``."""
    return add_to_faq(f"Read [the missing part]({target}).\n")


# Made-up files planted in a copy: a file of three lines, each ended by a line break; a file of
# three lines whose last has none; and a Markdown file of three lines.
MADE_UP_FILE = "tools/made_up.py"
UNENDED_FILE = "tools/made_up_unended.py"
MADE_UP_MARKDOWN = "made_up.md"
MADE_UP_FILES = {
    MADE_UP_FILE: "one = 1\ntwo = 2\nthree = 3\n",
    UNENDED_FILE: "one = 1\ntwo = 2\nthree = 3",
    MADE_UP_MARKDOWN: "# Made up\n\nA line.\n",
}
# The address of another repository on the forge, made up, and of a repository of its project
# beside it.
OTHER_SOURCE = "https://github.com/made-up-owner/made-up-name"
OTHER_PROJECT = f"{OTHER_SOURCE}-dev"
SOURCE_LINE = f'Source = "{SOURCE}"\n'
# The repository's address on the forge's host of raw files, and written bare with www.
RAW_SOURCE = "https://raw.githubusercontent.com/eugo-inc/pairbench"
WWW_SOURCE = "www.github.com/eugo-inc/pairbench"


def plant_files(repo: Path) -> None:
    for name, text in MADE_UP_FILES.items():
        write(repo, name, text)


def link_to_planted(target: str) -> Callable[[Path], None]:
    """Spoil a copy with the made-up files and a link from the FAQ page to ``target``."""

    def spoil(repo: Path) -> None:
        plant_files(repo)
        link_from_faq(target)(repo)

    return spoil


def text_with_planted(text: str) -> Callable[[Path], None]:
    """Spoil a copy with the made-up files and ``text`` at the end of the FAQ page."""

    def spoil(repo: Path) -> None:
        plant_files(repo)
        add_to_faq(text)(repo)

    return spoil


def give_source(line: str) -> Callable[[Path], None]:
    """Change the line of ``pyproject.toml`` that gives the repository's address to ``line``."""

    def change(repo: Path) -> None:
        path = repo / "pyproject.toml"
        text = path.read_text(encoding="utf-8")
        assert SOURCE_LINE in text
        path.write_text(text.replace(SOURCE_LINE, line), encoding="utf-8")

    return change


def link_from_another_source(target: str) -> Callable[[Path], None]:
    """Spoil a copy whose ``pyproject.toml`` names another repository with a link to ``target``."""

    def spoil(repo: Path) -> None:
        give_source(f'Source = "{OTHER_SOURCE}"\n')(repo)
        link_to_planted(target)(repo)

    return spoil


def text_from_another_source(text: str) -> Callable[[Path], None]:
    """Spoil a copy whose ``pyproject.toml`` names another repository with ``text`` at the end
    of the FAQ page."""

    def spoil(repo: Path) -> None:
        give_source(f'Source = "{OTHER_SOURCE}"\n')(repo)
        add_to_faq(text)(repo)

    return spoil


def faq_line_from_another_source(start: str, new: str) -> Callable[[Path], None]:
    """Spoil a copy whose ``pyproject.toml`` names another repository with ``new`` in place of
    the one line of the FAQ page that starts with ``start``."""

    def spoil(repo: Path) -> None:
        give_source(f'Source = "{OTHER_SOURCE}"\n')(repo)
        page = repo / FAQ
        lines = page.read_text(encoding="utf-8").splitlines(keepends=True)
        (at,) = [n for n, line in enumerate(lines) if line.startswith(start)]
        lines[at] = f"{new}\n"
        page.write_text("".join(lines), encoding="utf-8")

    return spoil


GIT = shutil.which("git")
# Files a git checkout of a copy holds and git does not track: a page a build leaves, and a
# made-up file beside the tracked ones.
BUILT_PAGE = "site/dist/index.html"
UNTRACKED_FILE = "tools/made_up_untracked.py"
UNTRACKED_FILES = {BUILT_PAGE: "<p>A page a build wrote.</p>\n", UNTRACKED_FILE: "one = 1\n"}


def run_git(folder: Path, *words: str) -> None:
    """Run git in ``folder`` apart from the settings of the user and the machine."""
    assert GIT is not None
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run([GIT, *words], cwd=folder, env=env, check=True, capture_output=True)


def make_checkout(folder: Path) -> None:
    """Make ``folder`` a git checkout that tracks every file it holds; skip without git."""
    if GIT is None:
        pytest.skip("needs git, to make a git checkout of a copy")
    run_git(folder, "-c", "init.defaultBranch=main", "init", "--quiet")
    run_git(folder, "add", "--all")


def link_in_checkout(target: str) -> Callable[[Path], None]:
    """Spoil a copy, made a git checkout with the made-up files tracked and the files of
    ``UNTRACKED_FILES`` beside them, with a link from the FAQ page to ``target``."""

    def spoil(repo: Path) -> None:
        plant_files(repo)
        make_checkout(repo)
        for name, text in UNTRACKED_FILES.items():
            write(repo, name, text)
        link_from_faq(target)(repo)

    return spoil


MADE_UP_LINES = f"{MADE_UP_FILE} has lines 1 to 3"
# A line number longer than Python reads into a number by default.
LONG_LINE = "7" * 5000
NOT_MARKDOWN_ANCHORS = (
    "the anchors of a file that is not Markdown are its lines, #L<n>, and ranges of them, "
    "#L<a>-L<b>"
)
SOURCE_REMEDY = (
    "pyproject.toml must give the repository's address under [project.urls]: "
    'Source = "https://HOST/OWNER/NAME"'
)


# The builds that are refused before anything is installed: what is wrong, and what the build
# says of it.
REFUSED_BEFORE_INSTALL = {
    "a link to a page the site does not have": (
        link_from_faq("guides/no-such-page.md"),
        "docs/faq.md: the link 'guides/no-such-page.md' names no page of the site",
    ),
    "a link to an anchor another page does not have": (
        link_from_faq("concepts.md#no-such-part"),
        "docs/faq.md: the link 'concepts.md#no-such-part' names an anchor that "
        "docs/concepts.md does not have",
    ),
    "a link to an anchor its own page does not have": (
        link_from_faq("#no-such-part"),
        "docs/faq.md: the link '#no-such-part' names an anchor that docs/faq.md does not have",
    ),
    "a link to an anchor a Markdown file of the repository does not have": (
        link_from_faq("../SECURITY.md#no-such-part"),
        "docs/faq.md: the link '../SECURITY.md#no-such-part' names an anchor that SECURITY.md "
        "does not have",
    ),
    "a Markdown file without front matter beside the pages": (
        lambda repo: write(repo, "docs/guides/notes.md", "# Notes\n"),
        "pages without front matter: docs/guides/notes.md",
    ),
    "a generated page that differs from what its script writes": (
        add_line,
        f"{GENERATED_PAGE} is out of date: run python3 tools/api_reference.py",
    ),
    "a share image with a text chunk": (
        plant_text,
        f"{SOURCE_IMAGE} has an extra chunk (tEXt): {REMEDY}",
    ),
    "a version without its minor part": (
        drop_minor,
        "the version must start with MAJOR.MINOR: '1'",
    ),
    "a version without its patch part": (
        set_version("1.2"),
        "the version must start with MAJOR.MINOR.PATCH: '1.2'",
    ),
    "a reference link to a page the site does not have": (
        add_to_faq("Read [the missing part][gone].\n\n[gone]: guides/no-such-page.md\n"),
        "docs/faq.md: the link 'guides/no-such-page.md' names no page of the site",
    ),
    "a reference link to an anchor its own page does not have": (
        add_to_faq("Read [the missing part][gone].\n\n[gone]: #no-such-part 'A title'\n"),
        "docs/faq.md: the link '#no-such-part' names an anchor that docs/faq.md does not have",
    ),
    "a link with a title in single quotes to a page the site does not have": (
        add_to_faq("Read [the missing part](guides/no-such-page.md 'A title').\n"),
        "docs/faq.md: the link 'guides/no-such-page.md' names no page of the site",
    ),
    "a line anchor past the end of a file of the repository": (
        link_to_planted(f"../{MADE_UP_FILE}#L4"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L4' names line 4, and {MADE_UP_LINES}",
    ),
    "a line anchor far past the end of a file of the repository": (
        link_to_planted(f"../{MADE_UP_FILE}#L999999"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L999999' names line 999999, and {MADE_UP_LINES}",
    ),
    "a line anchor with more digits than a number is read from": (
        link_to_planted(f"../{MADE_UP_FILE}#L{LONG_LINE}"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L{LONG_LINE}' names line {LONG_LINE}, and "
        f"{MADE_UP_LINES}",
    ),
    "a line anchor written with digits that are not ASCII": (
        link_to_planted(f"../{MADE_UP_FILE}#L\u0663"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L\u0663' names an anchor that {MADE_UP_FILE} "
        f"does not have; {NOT_MARKDOWN_ANCHORS}",
    ),
    "a line anchor of line zero": (
        link_to_planted(f"../{MADE_UP_FILE}#L0"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L0' names line 0, and {MADE_UP_LINES}",
    ),
    "a line anchor past the end of a file whose last line has no line break": (
        link_to_planted(f"../{UNENDED_FILE}#L4"),
        f"docs/faq.md: the link '../{UNENDED_FILE}#L4' names line 4, and {UNENDED_FILE} has "
        "lines 1 to 3",
    ),
    "a range whose end is past the end of the file": (
        link_to_planted(f"../{MADE_UP_FILE}#L2-L4"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L2-L4' names line 4, and {MADE_UP_LINES}",
    ),
    "a range whose start is past the end of the file": (
        link_to_planted(f"../{MADE_UP_FILE}#L4-L5"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L4-L5' names line 4, and {MADE_UP_LINES}",
    ),
    "a reversed range": (
        link_to_planted(f"../{MADE_UP_FILE}#L3-L2"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L3-L2' names a range that ends before it starts",
    ),
    "an anchor that is no line of a file that is not Markdown": (
        link_to_planted(f"../{MADE_UP_FILE}#three"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#three' names an anchor that {MADE_UP_FILE} "
        f"does not have; {NOT_MARKDOWN_ANCHORS}",
    ),
    "a line anchor that names its range in another form": (
        link_to_planted(f"../{MADE_UP_FILE}#L1-2"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L1-2' names an anchor that {MADE_UP_FILE} "
        f"does not have; {NOT_MARKDOWN_ANCHORS}",
    ),
    "a link by its address to a file the repository does not have": (
        link_to_planted(f"{SOURCE}/blob/main/no_such_file.py"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "an autolink to a file the repository does not have": (
        add_to_faq(f"Read <{SOURCE}/blob/main/no_such_file.py>.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address of a file the repository does not have": (
        add_to_faq(f"Read {SOURCE}/blob/main/no_such_file.py, then the guide.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address of a line past the end, at the end of a sentence": (
        text_with_planted(f"The rule is at {SOURCE}/blob/main/{MADE_UP_FILE}#L4.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{MADE_UP_FILE}#L4' names line 4, and "
        f"{MADE_UP_LINES}",
    ),
    "a link by its address to a folder the repository does not have": (
        link_to_planted(f"{SOURCE}/tree/main/no_such_folder"),
        f"docs/faq.md: the link '{SOURCE}/tree/main/no_such_folder' names nothing in the "
        "repository",
    ),
    "a link by its address in other capitals, with www, to a file the repository does not have": (
        link_to_planted("https://www.GitHub.com/Eugo-Inc/PairBench/blob/main/no_such_file.py"),
        "docs/faq.md: the link 'https://www.GitHub.com/Eugo-Inc/PairBench/blob/main/"
        "no_such_file.py' names nothing in the repository",
    ),
    # The copy is the folder "repo", so this path names a file that is there, by a way out of the
    # repository and back in.
    "a link by its address that leaves the repository": (
        link_to_planted(f"{SOURCE}/blob/main/../repo/{MADE_UP_FILE}"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/../repo/{MADE_UP_FILE}' names nothing in the "
        "repository",
    ),
    "a link by its address to a branch other than main": (
        link_to_planted(f"{SOURCE}/blob/made-up-branch/{MADE_UP_FILE}"),
        f"docs/faq.md: the link '{SOURCE}/blob/made-up-branch/{MADE_UP_FILE}' names the branch "
        "'made-up-branch'; a link to a file of the repository by its address names main",
    ),
    "a link by its address to a line past the end of a file": (
        link_to_planted(f"{SOURCE}/blob/main/{MADE_UP_FILE}#L4"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{MADE_UP_FILE}#L4' names line 4, and "
        f"{MADE_UP_LINES}",
    ),
    "a link by its address to a range whose end is past the end of a file": (
        link_to_planted(f"{SOURCE}/blob/main/{MADE_UP_FILE}#L1-L4"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{MADE_UP_FILE}#L1-L4' names line 4, and "
        f"{MADE_UP_LINES}",
    ),
    "a link by its address to an anchor a Markdown file does not have": (
        link_to_planted(f"{SOURCE}/blob/main/SECURITY.md#no-such-part"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/SECURITY.md#no-such-part' names an anchor "
        "that SECURITY.md does not have",
    ),
    "a link by its address to a line of a Markdown file as the forge renders it": (
        link_to_planted(f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}#L1"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{MADE_UP_MARKDOWN}#L1' names an anchor "
        f"that {MADE_UP_MARKDOWN} does not have",
    ),
    "a link by its address to a line past the end of a Markdown file shown as plain text": (
        link_to_planted(f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}?plain=1#L4"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{MADE_UP_MARKDOWN}?plain=1#L4' names line "
        f"4, and {MADE_UP_MARKDOWN} has lines 1 to 3",
    ),
    "a link by the address pyproject.toml gives to a file the repository does not have": (
        link_from_another_source(f"{OTHER_SOURCE}/blob/main/no_such_file.py"),
        f"docs/faq.md: the link '{OTHER_SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "in a git checkout, a link by its address to a page a build leaves": (
        link_in_checkout(f"{SOURCE}/blob/main/{BUILT_PAGE}"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{BUILT_PAGE}' names nothing in the repository",
    ),
    "in a git checkout, a link by its address to a folder that holds no file git tracks": (
        link_in_checkout(f"{SOURCE}/tree/main/site/dist"),
        f"docs/faq.md: the link '{SOURCE}/tree/main/site/dist' names nothing in the repository",
    ),
    "in a git checkout, a link by its address to a line of a file git does not track": (
        link_in_checkout(f"{SOURCE}/blob/main/{UNTRACKED_FILE}#L1"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/{UNTRACKED_FILE}#L1' names nothing in the "
        "repository",
    ),
    "in a git checkout, a link by its path to a file git does not track": (
        link_in_checkout(f"../{UNTRACKED_FILE}"),
        f"docs/faq.md: the link '../{UNTRACKED_FILE}' names nothing in the repository",
    ),
    "in a git checkout, a link by its path to a line of a page a build leaves": (
        link_in_checkout(f"../{BUILT_PAGE}#L1"),
        f"docs/faq.md: the link '../{BUILT_PAGE}#L1' names nothing in the repository",
    ),
    "a pyproject.toml without the repository's address": (
        give_source(""),
        SOURCE_REMEDY,
    ),
    "a pyproject.toml whose repository address has no owner": (
        give_source('Source = "https://github.com/pairbench"\n'),
        SOURCE_REMEDY,
    ),
    "a line anchor written with leading zeros past the end of a file": (
        link_to_planted(f"../{MADE_UP_FILE}#L004"),
        f"docs/faq.md: the link '../{MADE_UP_FILE}#L004' names line 4, and {MADE_UP_LINES}",
    ),
    "a bare address right after a parenthesis": (
        add_to_faq(f"Read the rule ({SOURCE}/blob/main/no_such_file.py) first.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address with its scheme in capitals": (
        add_to_faq("Read HTTPS://github.com/eugo-inc/pairbench/blob/main/no_such_file.py.\n"),
        "docs/faq.md: the link 'HTTPS://github.com/eugo-inc/pairbench/blob/main/no_such_file.py' "
        "names nothing in the repository",
    ),
    "an autolink with its scheme in capitals": (
        add_to_faq("Read <HTTPS://github.com/eugo-inc/pairbench/blob/main/no_such_file.py>.\n"),
        "docs/faq.md: the link 'HTTPS://github.com/eugo-inc/pairbench/blob/main/no_such_file.py' "
        "names nothing in the repository",
    ),
    "a bare address that starts with www and has no scheme": (
        add_to_faq(f"Read {WWW_SOURCE}/blob/main/no_such_file.py today.\n"),
        f"docs/faq.md: the link '{WWW_SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a link written in HTML by its address, in double quotes": (
        add_to_faq(f'Read <a href="{SOURCE}/blob/main/no_such_file.py">the rule</a>.\n'),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a link written in HTML by its address, in single quotes over two lines": (
        add_to_faq(f"Read <a class='x'\nHREF='{SOURCE}/tree/main/no_such_folder'>them</a>.\n"),
        f"docs/faq.md: the link '{SOURCE}/tree/main/no_such_folder' names nothing in the "
        "repository",
    ),
    "a link by its address to the blame page of a file the repository does not have": (
        link_from_faq(f"{SOURCE}/blame/main/no_such_file.py"),
        f"docs/faq.md: the link '{SOURCE}/blame/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a link by its address to the raw page of a file the repository does not have": (
        link_from_faq(f"{SOURCE}/raw/main/no_such_file.py"),
        f"docs/faq.md: the link '{SOURCE}/raw/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a raw address of a file the repository does not have": (
        add_to_faq(f"Read <{RAW_SOURCE}/main/no_such_file.py>.\n"),
        f"docs/faq.md: the link '{RAW_SOURCE}/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a raw address of a branch other than main by its full name": (
        link_to_planted(f"{RAW_SOURCE}/refs/heads/made-up-branch/{MADE_UP_FILE}"),
        f"docs/faq.md: the link '{RAW_SOURCE}/refs/heads/made-up-branch/{MADE_UP_FILE}' names the "
        "branch 'made-up-branch'; a link to a file of the repository by its address names main",
    ),
    "a blame page of a line past the end of a file": (
        link_to_planted(f"{SOURCE}/blame/main/{MADE_UP_FILE}#L4"),
        f"docs/faq.md: the link '{SOURCE}/blame/main/{MADE_UP_FILE}#L4' names line 4, and "
        f"{MADE_UP_LINES}",
    ),
    "a blame page of a line past the end of a Markdown file": (
        link_to_planted(f"{SOURCE}/blame/main/{MADE_UP_MARKDOWN}#L4"),
        f"docs/faq.md: the link '{SOURCE}/blame/main/{MADE_UP_MARKDOWN}#L4' names line 4, and "
        f"{MADE_UP_MARKDOWN} has lines 1 to 3",
    ),
    "an anchor on the raw page of a file": (
        link_to_planted(f"{SOURCE}/raw/main/{MADE_UP_FILE}#L1"),
        f"docs/faq.md: the link '{SOURCE}/raw/main/{MADE_UP_FILE}#L1' names an anchor of the raw "
        f"file {MADE_UP_FILE}, and a raw file has none",
    ),
    "the raw page of a folder": (
        link_to_planted(f"{SOURCE}/raw/main/tools"),
        f"docs/faq.md: the link '{SOURCE}/raw/main/tools' names the folder tools, which the forge "
        "shows on a tree page only",
    ),
    "the blame page of a folder": (
        link_to_planted(f"{SOURCE}/blame/main/tools"),
        f"docs/faq.md: the link '{SOURCE}/blame/main/tools' names the folder tools, which the "
        "forge shows on a tree page only",
    ),
    "a link with spaces inside its parentheses to a page the site does not have": (
        add_to_faq("Read [the missing part]( guides/no-such-page.md ).\n"),
        "docs/faq.md: the link 'guides/no-such-page.md' names no page of the site",
    ),
    "a link whose target starts the next line inside its parentheses": (
        add_to_faq("Read [the missing part](\n  guides/no-such-page.md 'A title'\n).\n"),
        "docs/faq.md: the link 'guides/no-such-page.md' names no page of the site",
    ),
    "a definition whose target is on the next line, to an anchor its own page does not have": (
        add_to_faq("Read [the missing part][gone].\n\n[gone]:\n  #no-such-part\n"),
        "docs/faq.md: the link '#no-such-part' names an anchor that docs/faq.md does not have",
    ),
    "a link by its path to a line past the end of a Markdown file shown as plain text": (
        link_to_planted(f"../{MADE_UP_MARKDOWN}?plain=1#L4"),
        f"docs/faq.md: the link '../{MADE_UP_MARKDOWN}?plain=1#L4' names line 4, and "
        f"{MADE_UP_MARKDOWN} has lines 1 to 3",
    ),
    "a link to another repository of the project": (
        text_from_another_source(f"Read [the notes]({OTHER_PROJECT}/blob/main/README.md).\n"),
        "docs/faq.md: github.com/made-up-owner/made-up-name-dev names a repository of the "
        f"project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project in a block of code": (
        text_from_another_source(f"```sh\ngit clone {OTHER_PROJECT}.git\n```\n"),
        "docs/faq.md: github.com/made-up-owner/made-up-name-dev.git names a repository of the "
        f"project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project in code, by its ssh address": (
        text_from_another_source("Run `git clone git@github.com:made-up-owner/made-up-name_x`.\n"),
        "docs/faq.md: github.com:made-up-owner/made-up-name_x names a repository of the project "
        f"other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project in other capitals, on the raw host": (
        text_from_another_source(
            "See https://RAW.githubusercontent.com/Made-Up-Owner/Made-Up-Name.Wiki/main/a.md.\n"
        ),
        "docs/faq.md: RAW.githubusercontent.com/Made-Up-Owner/Made-Up-Name.Wiki names a "
        f"repository of the project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project by its address on the forge's interface for programs": (
        text_from_another_source(
            "See https://api.github.com/repos/made-up-owner/made-up-name-dev/releases.\n"
        ),
        "docs/faq.md: api.github.com/repos/made-up-owner/made-up-name-dev names a repository of "
        f"the project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project by the address of its archive": (
        text_from_another_source(
            "Get https://codeload.github.com/made-up-owner/made-up-name-dev/zip/refs/heads/main.\n"
        ),
        "docs/faq.md: codeload.github.com/made-up-owner/made-up-name-dev names a repository of "
        f"the project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project by the address of its pages": (
        text_from_another_source("See https://Made-Up-Owner.github.io/made-up-name-dev/.\n"),
        "docs/faq.md: Made-Up-Owner.github.io/made-up-name-dev names a repository of the project "
        f"other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project in the description of a page": (
        faq_line_from_another_source(
            "description: ",
            'description: "Answers kept at github.com/made-up-owner/made-up-name-dev."',
        ),
        "docs/faq.md: github.com/made-up-owner/made-up-name-dev names a repository of the "
        f"project other than its public one, {OTHER_SOURCE}",
    ),
    "another repository of the project in the title of a page": (
        faq_line_from_another_source(
            "# Frequently asked questions",
            "# Frequently asked questions of github.com/made-up-owner/made-up-name-dev",
        ),
        "docs/faq.md: github.com/made-up-owner/made-up-name-dev names a repository of the "
        f"project other than its public one, {OTHER_SOURCE}",
    ),
    "a bare address in italics written with underscores": (
        add_to_faq(f"Read _{SOURCE}/blob/main/no_such_file.py_ first.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address that starts with www, in italics written with underscores": (
        add_to_faq(f"Read _{WWW_SOURCE}/blob/main/no_such_file.py_ first.\n"),
        f"docs/faq.md: the link '{WWW_SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address in double quotes": (
        add_to_faq(f'The rule is at "{SOURCE}/blob/main/no_such_file.py".\n'),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "a bare address in square brackets": (
        add_to_faq(f"Read [{SOURCE}/tree/main/no_such_folder] first.\n"),
        f"docs/faq.md: the link '{SOURCE}/tree/main/no_such_folder' names nothing in the "
        "repository",
    ),
    "a link written in HTML by its address, with no quotes": (
        add_to_faq(f"Read <a href={SOURCE}/blob/main/no_such_file.py>the rule</a>.\n"),
        f"docs/faq.md: the link '{SOURCE}/blob/main/no_such_file.py' names nothing in the "
        "repository",
    ),
    "an image written in HTML by its address": (
        add_to_faq(f'<img src="{SOURCE}/raw/main/no_such_file.png" alt="A part">\n'),
        f"docs/faq.md: the link '{SOURCE}/raw/main/no_such_file.png' names nothing in the "
        "repository",
    ),
}


@pytest.fixture
def npm_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a stand-in for npm first on the search path; the file it writes its calls to."""
    folder = tmp_path / "bin"
    folder.mkdir()
    calls = tmp_path / "npm-calls.txt"
    npm = folder / "npm"
    npm.write_text(NPM_STAND_IN.format(calls=calls), encoding="utf-8")
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    return calls


# What the content folders hold before a build, as an earlier build left them: a copy of a page
# and the settings it wrote. A refused build leaves them as they are.
EARLIER_BUILD = {
    "site/src/content/docs/latest/index.md": "---\n{}\n---\n\nA page an earlier build wrote.\n",
    "site/src/generated/site.json": '{"title": "an earlier build"}\n',
}


@pytest.mark.parametrize("case", sorted(REFUSED_BEFORE_INSTALL))
def test_a_build_that_is_refused_never_starts_the_install(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    npm_calls: Path,
    case: str,
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    for name, text in EARLIER_BUILD.items():
        write(repo, name, text)
    spoil, message = REFUSED_BEFORE_INSTALL[case]
    spoil(repo)
    monkeypatch.setattr(docs_site, "REPO", repo)

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capsys.readouterr() == ("", f"docs_site: {message}\n")
    assert not npm_calls.exists()
    assert not (repo / "site" / "node_modules").exists()
    # Nothing was removed or written: the content folders hold what the earlier build left.
    left = {
        str(p.relative_to(repo))
        for folder in (docs_site.CONTENT, docs_site.GENERATED)
        for p in (repo / folder).rglob("*")
        if p.is_file()
    }
    assert left == set(EARLIER_BUILD)
    assert {name: (repo / name).read_text(encoding="utf-8") for name in left} == EARLIER_BUILD


# Links to the made-up files that the first step lets pass, and the target it writes for Astro:
# a line and a range of a file by its path or by its address, the last line with a line break
# after it and without one, a range of one line, a folder and the top of the repository by their
# address, a heading of a Markdown file, a line of one shown as plain text by its address and by
# its path, the address in other capitals, links that name no file of a repository, lines written
# with leading zeros, and a file's blame page and raw page on the forge and on its raw host.
PASSING_LINKS = {
    f"../{MADE_UP_FILE}": f"{SOURCE}/blob/main/{MADE_UP_FILE}",
    f"../{MADE_UP_FILE}#L1": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L1",
    f"../{MADE_UP_FILE}#L3": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L3",
    f"../{UNENDED_FILE}#L3": f"{SOURCE}/blob/main/{UNENDED_FILE}#L3",
    f"../{MADE_UP_FILE}#L1-L3": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L1-L3",
    f"../{MADE_UP_FILE}#L2-L2": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L2-L2",
    f"{SOURCE}/blob/main/{MADE_UP_FILE}#L2-L3": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L2-L3",
    f"{SOURCE}/blob/main/{UNENDED_FILE}#L3": f"{SOURCE}/blob/main/{UNENDED_FILE}#L3",
    f"{SOURCE}/tree/main/tools": f"{SOURCE}/tree/main/tools",
    f"{SOURCE}/tree/main/tools/": f"{SOURCE}/tree/main/tools/",
    f"{SOURCE}/tree/main": f"{SOURCE}/tree/main",
    f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}#made-up": f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}"
    "#made-up",
    f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}?plain=1#L3": f"{SOURCE}/blob/main/"
    f"{MADE_UP_MARKDOWN}?plain=1#L3",
    f"https://www.GitHub.com/Eugo-Inc/PairBench/blob/main/{MADE_UP_FILE}#L3": "https://www."
    f"GitHub.com/Eugo-Inc/PairBench/blob/main/{MADE_UP_FILE}#L3",
    f"{OTHER_SOURCE}/blob/main/no_such_file.py": f"{OTHER_SOURCE}/blob/main/no_such_file.py",
    f"{SOURCE}/issues": f"{SOURCE}/issues",
    f"../{MADE_UP_FILE}#L003": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L003",
    f"{SOURCE}/blob/main/{MADE_UP_FILE}#L01-L03": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L01-L03",
    f"../{MADE_UP_MARKDOWN}?plain=1#L3": f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}?plain=1#L3",
    f"{SOURCE}/blame/main/{MADE_UP_FILE}#L2": f"{SOURCE}/blame/main/{MADE_UP_FILE}#L2",
    f"{SOURCE}/blame/main/{MADE_UP_MARKDOWN}#L3": f"{SOURCE}/blame/main/{MADE_UP_MARKDOWN}#L3",
    f"{SOURCE}/raw/main/{MADE_UP_FILE}": f"{SOURCE}/raw/main/{MADE_UP_FILE}",
    f"{RAW_SOURCE}/main/{MADE_UP_FILE}": f"{RAW_SOURCE}/main/{MADE_UP_FILE}",
    f"{RAW_SOURCE}/refs/heads/main/{MADE_UP_FILE}": f"{RAW_SOURCE}/refs/heads/main/{MADE_UP_FILE}",
}


def faq_links(targets: Iterable[str]) -> str:
    return "".join(f"Read [a part]({target}).\n" for target in targets)


def test_the_first_step_lets_a_link_to_a_line_or_a_file_the_repository_has_pass(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    plant_files(repo)
    add_to_faq(faq_links(PASSING_LINKS))(repo)

    docs_site.prepare(repo)

    written = (repo / docs_site.CONTENT / docs_site.LATEST / "faq.md").read_text(encoding="utf-8")
    assert written.endswith(f"\n\n{faq_links(PASSING_LINKS.values())}")


# Addresses written as links of their own that the first step lets pass and leaves as they are:
# an autolink and bare addresses of what the repository has, one after a parenthesis and one with
# www and no scheme among them, a link written in HTML by its address, and addresses in code.
ALONE_PASSING = (
    f"Read <{SOURCE}/blob/main/{MADE_UP_FILE}#L3> and {SOURCE}/tree/main/tools.\n"
    f"See {SOURCE}/blob/main/{MADE_UP_FILE}#L1-L3, or {OTHER_SOURCE}/blob/main/no_such_file.py.\n"
    f"Not `{SOURCE}/blob/main/no_such_file.py` in code.\n"
    f"Read it ({SOURCE}/blob/main/{MADE_UP_FILE}#L2) and {WWW_SOURCE}/tree/main/tools.\n"
    f'Read <a href="{SOURCE}/blob/main/{MADE_UP_FILE}#L1">the rule</a>, not '
    f'`<a href="{SOURCE}/blob/main/no_such_file.py">` in code.\n'
    "\n"
    "```text\n"
    f"{SOURCE}/blob/main/no_such_file.py\n"
    "```\n"
)


def test_the_first_step_lets_an_address_written_alone_pass_when_the_repository_has_it(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    text_with_planted(ALONE_PASSING)(repo)

    docs_site.prepare(repo)

    written = (repo / docs_site.CONTENT / docs_site.LATEST / "faq.md").read_text(encoding="utf-8")
    assert written.endswith(f"\n\n{ALONE_PASSING}")


# Bare addresses the site's renderer shows as links after any mark but a letter, and those with
# www. after any mark but a letter, a digit or a colon, to what the repository has; then the
# forms it shows as no link, to what the repository does not have: an address glued to a
# letter, and one with www. glued to a letter, a digit or a colon.
MARKED_PASSING = (
    f'Read _{SOURCE}/blob/main/{MADE_UP_FILE}#L3_, "{SOURCE}/tree/main/tools" and '
    f"[{WWW_SOURCE}/blob/main/{MADE_UP_FILE}].\n"
    f"Read <a href={SOURCE}/blob/main/{MADE_UP_FILE}>the rule</a> and "
    f"'_{WWW_SOURCE}/tree/main/tools_'.\n"
    f'<img src="{SOURCE}/raw/main/{MADE_UP_FILE}" alt="A part">\n'
    f"Not links: x{SOURCE}/blob/main/no_such_file.py, x{WWW_SOURCE}/blob/main/no_such_file.py,\n"
    f"1{WWW_SOURCE}/blob/main/no_such_file.py and :{WWW_SOURCE}/blob/main/no_such_file.py.\n"
)


def test_the_first_step_reads_a_bare_address_wherever_the_site_shows_it_as_a_link(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    text_with_planted(MARKED_PASSING)(repo)

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{MARKED_PASSING}")


# A line of prose that starts like the definition of a reference link but holds words after its
# first, which CommonMark reads as no definition.
NOT_A_DEFINITION = "[Note]: don't run it on a shared machine.\n"


def test_the_first_step_reads_no_definition_where_words_follow_the_target(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    add_to_faq(NOT_A_DEFINITION)(repo)

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{NOT_A_DEFINITION}")


def test_a_link_by_its_address_to_a_repository_pyproject_does_not_give_is_not_checked(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    link_from_another_source(f"{SOURCE}/blob/main/no_such_file.py")(repo)

    docs_site.prepare(repo)

    written = (repo / docs_site.CONTENT / docs_site.LATEST / "faq.md").read_text(encoding="utf-8")
    assert written.endswith(f"\n\nRead [the missing part]({SOURCE}/blob/main/no_such_file.py).\n")


def faq_written(docs_site: ModuleType, repo: Path) -> str:
    return (repo / docs_site.CONTENT / docs_site.LATEST / "faq.md").read_text(encoding="utf-8")


# Text that names the repository pyproject.toml gives, or a repository that is not of its project:
# the repository with and without .git, by its address and its ssh address, its owner's page,
# another repository of the owner whose name does not start with the project's, a repository of
# another owner named for the project, and the repository by the addresses of its pages, its
# releases on the forge's interface for programs and its archive, and the owner's pages.
OTHER_REPOSITORIES = (
    f"Clone {OTHER_SOURCE}.git or `git@github.com:made-up-owner/made-up-name.git`.\n"
    f"See {OTHER_SOURCE}, https://github.com/made-up-owner,\n"
    "https://github.com/made-up-owner/another-name and\n"
    "https://github.com/someone-else/made-up-name-dev.\n"
    "Its pages are https://made-up-owner.github.io/made-up-name/, its releases\n"
    "https://api.github.com/repos/made-up-owner/made-up-name/releases, its archive\n"
    "https://codeload.github.com/made-up-owner/made-up-name/zip/refs/heads/main, and\n"
    "https://made-up-owner.github.io/ the owner's.\n"
    f"Its home is {OTHER_SOURCE}. Clone it from {OTHER_SOURCE}.git.\n"
)


def test_the_first_step_lets_a_page_name_the_public_repository_and_others_not_of_its_project(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    text_from_another_source(OTHER_REPOSITORIES)(repo)

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{OTHER_REPOSITORIES}")


# Links that hold spaces or a line break around their target inside the parentheses, and a
# definition whose target is on the next line, to the made-up files; and what the first step
# writes for Astro in their place.
SPACED_LINKS = (
    f"Read [a part]( ../{MADE_UP_FILE}#L2 ) and [a part](\n  ../{MADE_UP_FILE}#L3 'A title'\n).\n"
    "\n"
    f"[a label]:\n  ../{MADE_UP_MARKDOWN}#made-up\n"
)
SPACED_WRITTEN = (
    f"Read [a part]( {SOURCE}/blob/main/{MADE_UP_FILE}#L2 ) and [a part](\n"
    f"  {SOURCE}/blob/main/{MADE_UP_FILE}#L3 'A title'\n).\n"
    "\n"
    f"[a label]:\n  {SOURCE}/blob/main/{MADE_UP_MARKDOWN}#made-up\n"
)


def test_the_first_step_reads_a_target_with_spaces_or_a_line_break_around_it(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    text_with_planted(SPACED_LINKS)(repo)

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{SPACED_WRITTEN}")


# Links that the first step lets pass in a git checkout, and the target it writes for Astro: a
# line of a file git tracks and a heading of a Markdown file it tracks, by path and by address; a
# folder that holds a file git tracks beside files it does not, another folder written with its
# slash, and the top of the repository.
TRACKED_LINKS = {
    f"../{MADE_UP_FILE}#L2": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L2",
    f"../{MADE_UP_MARKDOWN}#made-up": f"{SOURCE}/blob/main/{MADE_UP_MARKDOWN}#made-up",
    f"{SOURCE}/blob/main/{MADE_UP_FILE}#L3": f"{SOURCE}/blob/main/{MADE_UP_FILE}#L3",
    f"{SOURCE}/tree/main/site": f"{SOURCE}/tree/main/site",
    f"{SOURCE}/tree/main/tools/": f"{SOURCE}/tree/main/tools/",
    f"{SOURCE}/tree/main": f"{SOURCE}/tree/main",
}


def test_in_a_git_checkout_the_first_step_lets_a_link_to_what_git_tracks_pass(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    plant_files(repo)
    make_checkout(repo)
    for name, text in UNTRACKED_FILES.items():
        write(repo, name, text)
    add_to_faq(faq_links(TRACKED_LINKS))(repo)
    # A git hook that runs the build names an index of its own; git reads the checkout's.
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "no-such-index"))

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{faq_links(TRACKED_LINKS.values())}")


# What git prints when it refuses a checkout owned by another user, with a made-up path.
GIT_REFUSAL = "fatal: detected dubious ownership in repository at '/made-up/checkout'"
CANNOT_TELL = "so the build cannot tell which files git tracks"
# Stand-ins for a git that cannot answer in a checkout that holds .git, each writing its
# arguments to a file first: one that refuses the checkout, as git does with one owned by
# another user, and one whose interpreter is missing, so it cannot start; and no git at all.
# What the build prints on stderr for each.
GIT_FAILURES = {
    "refuses": (
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{{calls}}"\necho "{GIT_REFUSAL}" >&2\nexit 128\n',
        f"{GIT_REFUSAL}\n"
        f"docs_site: git ls-files failed with exit code 128 in a checkout that holds .git, "
        f"{CANNOT_TELL}: fix what git printed above, or build from a copy without .git\n",
    ),
    "cannot start": (
        "#!/no/such/interpreter\n",
        "docs_site: git could not start (No such file or directory) in a checkout that holds "
        f".git, {CANNOT_TELL}: check that git runs, or build from a copy without .git\n",
    ),
    "missing": (
        None,
        f"docs_site: the checkout holds .git and git is not on the search path, {CANNOT_TELL}: "
        "install git, or build from a copy without .git\n",
    ),
}


@pytest.mark.parametrize("case", sorted(GIT_FAILURES))
def test_where_git_cannot_answer_in_a_checkout_the_build_is_refused_and_says_why(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    case: str,
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    plant_files(repo)
    (repo / ".git").mkdir()
    for name, text in UNTRACKED_FILES.items():
        write(repo, name, text)
    add_to_faq(faq_links([f"../{BUILT_PAGE}"]))(repo)
    script, said = GIT_FAILURES[case]
    folder, calls = tmp_path / "bin", tmp_path / "git-calls.txt"
    folder.mkdir()
    (folder / "npm").write_text(NPM_STAND_IN.format(calls=tmp_path / "npm-calls.txt"))
    (folder / "npm").chmod(0o755)
    if script is not None:
        (folder / "git").write_text(script.format(calls=calls), encoding="utf-8")
        (folder / "git").chmod(0o755)
    # The search path holds the stand-ins alone, so no other git is found.
    monkeypatch.setenv("PATH", str(folder))
    monkeypatch.setattr(docs_site, "REPO", repo)

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capfd.readouterr() == ("", said)
    assert not (tmp_path / "npm-calls.txt").exists()
    if case == "refuses":
        assert calls.read_text(encoding="utf-8") == "ls-files -z\n"


def test_a_copy_without_git_inside_a_git_checkout_is_checked_by_the_files_it_holds(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    make_checkout(outer)
    repo = outer / "repo"
    copy_build_inputs(repo_root, repo)
    plant_files(repo)
    add_to_faq(faq_links(PASSING_LINKS))(repo)

    docs_site.prepare(repo)

    assert faq_written(docs_site, repo).endswith(f"\n\n{faq_links(PASSING_LINKS.values())}")


def test_the_links_are_written_with_the_address_pyproject_gives(
    docs_site: ModuleType, repo_root: Path
) -> None:
    assert docs_site.read_source(repo_root) == SOURCE
    assert docs_site.SOURCE == SOURCE


# What the module's docstring and the contributing guide say of the links each step checks: the
# first, before it removes or writes anything, the links written [text](target) and the
# reference links, the lines of a file they name, a Markdown file's among them when it is shown
# as plain text, the links to a file of the repository by its address on each page of the forge
# that shows one and on its host of raw files, as a link, an autolink, bare or in HTML, the
# names of the project's other repositories, and what it does where git cannot answer; the
# third, on the built site, every link, those written in HTML among them.
STEP_ONE_LINKS = "each link written `[text](target)` or as a reference link"
STEP_ONE_LINES = (
    "a line, `#L<n>`, or a range of lines, `#L<a>-L<b>`, of any other file of the repository, "
    "or of a Markdown file shown as plain text, `?plain=1`."
)
STEP_ONE_ADDRESSES = (
    "A link to a file of the repository by its address on the forge, the `Source` address of "
    "`pyproject.toml` followed by `/blob/main/`, `/tree/main/`, `/blame/main/` or `/raw/main/`, "
    "or by the same owner and name on the forge's host of raw files followed by `/main/`, must "
    "name a file or folder the repository has, and its anchor is checked the same way; a blame "
    "or raw page shows a file only, and a raw file has no anchor. So must such an address "
    "written as an autolink, `<address>`, bare, with its scheme or starting with `www.` "
    "wherever the site shows it as a link, in quotes or brackets too, such as the `src` of an "
    "image, or as the `href` of a link written in HTML."
)
STEP_ONE_PROJECT = (
    "A page that names a repository of the project other than its public one, of the same "
    "owner with a name that starts with the project's, by its address on the forge, on its host "
    "of raw files, on its interface for programs, of its archives or of its pages, or by its ssh "
    "address, and in code too, is refused."
)
STEP_ONE_TRACKED = (
    "In a git checkout the repository has the files git tracks and the folders that hold them, "
    "so a link to a file a build leaves, such as one in `site/dist/`, is refused; a checkout "
    "that holds `.git` where git is missing, cannot start or refuses to read it is refused, and "
    "a copy without `.git` is checked by the files it holds."
)
STEP_THREE_LINKS = "a link written in HTML among them"
CONTRIBUTING = "CONTRIBUTING.md"
# The forms of a link the contributing guide names: those the first step reads, and those it
# leaves to the third, with their count.
LINK_FORMS_NAMED = (
    "`[text](target)`",
    '`[text](target "title")`',
    "`[text](target 'title')`",
    "`[text](target (title))`",
    "`[text](<target>)`",
    "`[text][label]`",
    "`[label][]`",
    "`[label]`",
    "`[label]: target`",
    "holds the target on that line or the next",
    "spaces or one line break around the target inside the parentheses",
    "`README.md?plain=1#L3`",
    "It leaves two forms as they are: a bare target that holds a space or a parenthesis, and a "
    "relative link written in HTML.",
)
# What the contributing guide says the documentation build runs, none of which ships in the site.
BUILD_RUNS = "The build runs Node.js, npm and, in a git checkout, git; none of the three ships"
# A link to an anchor the FAQ page does not have, in each form the first step leaves to the third.
LEFT_TO_THE_BUILT_SITE = {
    "a link written in HTML": '<a href="#no-such-part">the missing part</a>',
    "a link written in HTML in single quotes": "<a href='#no-such-part'>the missing part</a>",
}
# Each form of a link the first step reads, and what it writes when it puts "/made-up/" before
# each target: a title in double quotes, single quotes or parentheses, a target in angle
# brackets, spaces, tabs or one line break around the target inside the parentheses, and the
# definition of a reference link, with or without a title, at most three spaces in, its target on
# its line or the next. A footnote, code, a line four spaces in and a target after a blank line
# are left as they are.
LINK_FORMS = {
    "[text](a.md)": "[text](/made-up/a.md)",
    '[text](a.md "A title")': '[text](/made-up/a.md "A title")',
    "[text](a.md 'A title')": "[text](/made-up/a.md 'A title')",
    "[text](a.md (A title))": "[text](/made-up/a.md (A title))",
    "[text](<a.md>)": "[text](</made-up/a.md>)",
    "[text](<a.md> 'A title')": "[text](</made-up/a.md> 'A title')",
    "[text][label]\n\n[label]: a.md": "[text][label]\n\n[label]: /made-up/a.md",
    "[label][] and [label]\n\n[Label]: a.md#part": (
        "[label][] and [label]\n\n[Label]: /made-up/a.md#part"
    ),
    "[label]: a.md 'A title'": "[label]: /made-up/a.md 'A title'",
    '   [label two]:  a.md "A title"': '   [label two]:  /made-up/a.md "A title"',
    "[label]: <a.md> (A title)": "[label]: </made-up/a.md> (A title)",
    "[one]: a.md\n[two]: b.md": "[one]: /made-up/a.md\n[two]: /made-up/b.md",
    "[^note]: a.md": "[^note]: a.md",
    "    [label]: a.md": "    [label]: a.md",
    "[text]( a.md )": "[text]( /made-up/a.md )",
    "[text](\ta.md\t'A title' )": "[text](\t/made-up/a.md\t'A title' )",
    "[text](\n  <a.md> 'A title'\n)": "[text](\n  </made-up/a.md> 'A title'\n)",
    "[label]:\n  a.md 'A title'": "[label]:\n  /made-up/a.md 'A title'",
    "[label]:  \n<a.md>": "[label]:  \n</made-up/a.md>",
    "[text](\n\na.md)": "[text](\n\na.md)",
    "[label]:\n\na.md": "[label]:\n\na.md",
    "`[label]: a.md` and `[text](a.md)`": "`[label]: a.md` and `[text](a.md)`",
    "```\n[label]: a.md\n[text](a.md)\n```": "```\n[label]: a.md\n[text](a.md)\n```",
}


@pytest.mark.parametrize("written", sorted(LINK_FORMS))
def test_the_first_step_changes_the_target_of_each_form_of_link_it_reads(
    docs_site: ModuleType, written: str
) -> None:
    changed = docs_site.rewrite_links(written, lambda target: f"/made-up/{target}")

    assert changed == LINK_FORMS[written]


# A reference link and a link with a title in single quotes as a page writes them, and as the
# first step writes them for Astro and into the Markdown copy of the page: each target is the
# address of the page it names.
PLANTED_LINKS = (
    "Read [the commands][the-commands] and [the commands](reference/commands.md 'The list').\n"
    "\n"
    "[the-commands]: reference/commands.md#run\n"
)
WRITTEN_FOR_ASTRO = (
    "Read [the commands][the-commands] and "
    "[the commands](/docs/pairbench/latest/reference/commands/ 'The list').\n"
    "\n"
    "[the-commands]: /docs/pairbench/latest/reference/commands/#run\n"
)
WRITTEN_IN_THE_COPY = (
    "Read [the commands][the-commands] and "
    "[the commands](https://eugo.io/docs/pairbench/latest/reference/commands/index.md "
    "'The list').\n"
    "\n"
    "[the-commands]: https://eugo.io/docs/pairbench/latest/reference/commands/index.md#run\n"
)


def test_the_first_step_makes_reference_links_and_quoted_titles_addresses_of_the_site(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    add_to_faq(PLANTED_LINKS)(repo)

    build = docs_site.prepare(repo)

    written = (repo / docs_site.CONTENT / docs_site.LATEST / "faq.md").read_text(encoding="utf-8")
    assert written.endswith(f"\n\n{WRITTEN_FOR_ASTRO}")
    assert docs_site.markdown_copy(build, build.pages["faq.md"]).endswith(
        f"\n\n{WRITTEN_IN_THE_COPY}"
    )


def test_the_docstring_and_the_contributing_guide_say_which_links_each_step_checks(
    docs_site: ModuleType, repo_root: Path
) -> None:
    texts = {
        "tools/docs_site.py": (docs_site.__doc__ or "").replace("``", "`"),
        CONTRIBUTING: (repo_root / CONTRIBUTING).read_text(encoding="utf-8"),
    }
    missing = [
        f"{name}: {phrase}"
        for name, text in texts.items()
        for phrase in (
            STEP_ONE_LINKS,
            STEP_ONE_LINES,
            STEP_ONE_ADDRESSES,
            STEP_ONE_PROJECT,
            STEP_ONE_TRACKED,
            STEP_THREE_LINKS,
        )
        if phrase not in " ".join(text.split())
    ]

    assert missing == []


def test_the_contributing_guide_names_each_form_of_link_and_the_step_that_checks_it(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / CONTRIBUTING).read_text(encoding="utf-8").split())

    assert [form for form in LINK_FORMS_NAMED if form not in text] == []


def test_the_contributing_guide_says_what_the_documentation_build_runs(repo_root: Path) -> None:
    text = " ".join((repo_root / CONTRIBUTING).read_text(encoding="utf-8").split())

    assert BUILD_RUNS in text


@pytest.mark.parametrize("case", sorted(LEFT_TO_THE_BUILT_SITE))
def test_the_first_step_leaves_a_relative_link_written_in_html_to_the_built_site(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path, case: str
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    with (repo / FAQ).open("a", encoding="utf-8") as page:
        page.write(f"\n{LEFT_TO_THE_BUILT_SITE[case]}\n")

    docs_site.prepare(repo)

    written = repo / docs_site.CONTENT / docs_site.LATEST / "faq.md"
    assert "#no-such-part" in written.read_text(encoding="utf-8")


# A page's text, and the anchors the build reads from it before the install: the id the site
# gives each heading (a second heading of the same text gets "-1"), and each id written in its
# HTML outside code.
ANCHOR_SOURCE = (
    'Some prose with an id in it: <span id="in-prose"></span>.\n'
    "\n"
    "## Sides and twins\n"
    "\n"
    "## The `run.rounds` key\n"
    "\n"
    "### A [linked](other.md) heading\n"
    "\n"
    "## Sides and twins\n"
    "\n"
    '## <span id="tool.name"></span>Name `tool.name`\n'
    "\n"
    "```\n"
    "## Not a heading\n"
    '<span id="in-code"></span>\n'
    "```\n"
    "\n"
    '| <span id="a.key"></span>`a.key` | a value |\n'
    "\n"
    "#### E_MADE_UP\n"
    "\n"
    "## `made_up_` and *more*, 2 or 3!\n"
    "\n"
    "## Before &amp; after &amp;\n"
    "\n"
    "## An _emphasised_ word and a \\_kept\\_ one ##\n"
)
ANCHOR_IDS = frozenset(
    {
        "in-prose",
        "sides-and-twins",
        "the-runrounds-key",
        "a-linked-heading",
        "sides-and-twins-1",
        "tool.name",
        "name-toolname",
        "a.key",
        "e_made_up",
        "made_up_-and-more-2-or-3",
        "before--after-",
        "an-emphasised-word-and-a-_kept_-one",
    }
)


def test_the_anchors_of_a_page_are_its_heading_ids_and_the_ids_in_its_html(
    docs_site: ModuleType,
) -> None:
    assert docs_site.page_anchors(ANCHOR_SOURCE) == ANCHOR_IDS


def test_every_link_of_the_pages_names_an_anchor_its_page_has(
    docs_site: ModuleType, repo_root: Path
) -> None:
    assert docs_site.check_anchors(docs_site.load_build(repo_root)) is None


def test_a_build_the_checks_pass_installs_the_packages_it_lacks(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    npm_calls: Path,
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    monkeypatch.setattr(docs_site, "REPO", repo)
    astro = repo / "site" / "node_modules" / ".bin" / "astro"

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capsys.readouterr() == ("", f"docs_site: {astro} is missing: run npm ci in site/\n")
    assert npm_calls.read_text(encoding="utf-8") == f"{(repo / 'site').resolve()} ci\n"


# Stand-ins for an npm whose install fails, and what the build prints on stderr after what npm
# printed: an npm that says why and ends with a made-up exit code, two stopped by a signal, and
# one whose interpreter is missing, so it cannot start.
NEXT_STEP = "then run npm ci in site/ and python3 tools/docs_site.py build"
AGAIN = "run npm ci in site/ again, then python3 tools/docs_site.py build"
FAILED_INSTALLS = {
    "exit code": (
        '#!/bin/sh\necho "npm error a made-up cause" >&2\nexit 7\n',
        "npm error a made-up cause\n"
        "docs_site: npm ci in site/ failed with exit code 7: fix what npm printed above, "
        f"{NEXT_STEP}\n",
    ),
    "signal": (
        "#!/bin/sh\nkill -KILL $$\n",
        f"docs_site: npm ci in site/ was stopped by signal SIGKILL (9): {AGAIN}\n",
    ),
    "signal to end": (
        "#!/bin/sh\nkill -TERM $$\n",
        f"docs_site: npm ci in site/ was stopped by signal SIGTERM (15): {AGAIN}\n",
    ),
    "no start": (
        "#!/no/such/interpreter\n",
        "docs_site: npm ci in site/ could not start (No such file or directory): check that npm "
        "runs, then run python3 tools/docs_site.py build\n",
    ),
}


@pytest.mark.parametrize("case", sorted(FAILED_INSTALLS))
def test_a_failed_install_names_the_step_its_exit_and_the_next_step(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    case: str,
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    script, said = FAILED_INSTALLS[case]
    npm = tmp_path / "bin" / "npm"
    write(tmp_path, "bin/npm", script)
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{npm.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(docs_site, "REPO", repo)

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capfd.readouterr() == ("", said)


def test_an_astro_that_cannot_start_names_the_step_and_the_next_step(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    write(repo, "site/node_modules/.bin/astro", "A file that is no program.\n")
    monkeypatch.setattr(docs_site, "REPO", repo)

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capfd.readouterr() == (
        "",
        "docs_site: astro build in site/ could not start (Permission denied): run npm ci in "
        "site/, then python3 tools/docs_site.py build\n",
    )


def test_an_astro_stopped_by_a_signal_names_the_signal_and_the_next_step(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    copy_build_inputs(repo_root, repo)
    astro = repo / "site/node_modules/.bin/astro"
    write(repo, "site/node_modules/.bin/astro", "#!/bin/sh\nkill -KILL $$\n")
    astro.chmod(0o755)
    monkeypatch.setattr(docs_site, "REPO", repo)

    assert docs_site.main(["build"]) == EXIT_REFUSED
    assert capfd.readouterr() == (
        "",
        "docs_site: astro build in site/ was stopped by signal SIGKILL (9): run python3 "
        "tools/docs_site.py build again\n",
    )


# Signals by their number, and how a refusal names each: by its name and its number, or by its
# number alone when it has no name.
SIGNAL_WORDS = {9: "signal SIGKILL (9)", 15: "signal SIGTERM (15)", 99: "signal 99"}


@pytest.mark.parametrize("number", sorted(SIGNAL_WORDS))
def test_a_signal_is_named_with_its_number(docs_site: ModuleType, number: int) -> None:
    assert docs_site.signal_words(number) == SIGNAL_WORDS[number]


def test_the_software_runs_on_the_systems_the_package_names(repo_root: Path) -> None:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        classifiers = tomllib.load(handle)["project"]["classifiers"]
    named = [
        SYSTEM_CLASSIFIERS.get(c, c) for c in classifiers if c.startswith("Operating System ::")
    ]

    assert ", ".join(named) == OPERATING_SYSTEMS


def test_the_home_page_describes_the_software_and_its_source(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = paged_build(docs_site, tmp_path, address)

    assert docs_site.structured_data(build, build.pages["index.md"]) == HOME_GRAPH


def references(value: object) -> list[str]:
    """The identifier of every node a JSON value names by its identifier alone."""
    if isinstance(value, dict):
        if set(value) == {"@id"}:
            return [str(value["@id"])]
        return [ref for inner in value.values() for ref in references(inner)]
    if isinstance(value, list):
        return [ref for inner in value for ref in references(inner)]
    return []


def test_every_node_a_page_names_is_defined_on_the_home_page_or_that_page(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = paged_build(docs_site, tmp_path, address)
    home = {
        node["@id"] for node in docs_site.structured_data(build, build.pages["index.md"])["@graph"]
    }
    publishers: list[str] = []
    named: list[str] = []
    for path, page in build.pages.items():
        graph = docs_site.structured_data(build, page)["@graph"]
        own = {node["@id"] for node in graph}
        publishers += [node["publisher"]["@id"] for node in graph if "publisher" in node]
        named += [f"{path}: {ref}" for ref in references(graph) if ref not in home | own]
        organizations = [node for node in graph if node["@type"] == "Organization"]
        assert organizations == ([ORGANIZATION_NODE] if path == "index.md" else []), path

    assert len(publishers) == PUBLISHER_REFERENCES
    assert set(publishers) == {ORGANIZATION["@id"]}
    assert ORGANIZATION["@id"] in home
    assert named == []


def test_the_publisher_is_the_author_of_the_package_and_the_citation_and_holds_the_copyright(
    docs_site: ModuleType, repo_root: Path
) -> None:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        authors = tomllib.load(handle)["project"]["authors"]
    header = (repo_root / "tools" / "docs_site.py").read_text(encoding="utf-8").splitlines()[1]
    notice = (repo_root / "NOTICE").read_text(encoding="utf-8").splitlines()
    citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8").splitlines()
    cited = citation[citation.index("authors:") + 1 :]

    assert docs_site.PUBLISHER == PUBLISHER_NAME
    assert [author["name"] for author in authors] == [PUBLISHER_NAME]
    assert header.endswith(f", {PUBLISHER_NAME}")
    assert [line.split(" ", 2)[2] for line in notice if line.startswith("Copyright ")] == [
        PUBLISHER_NAME
    ]
    assert list(itertools.takewhile(lambda line: line.startswith(" "), cited)) == [
        f'  - name: "{PUBLISHER_NAME}"'
    ]


def test_another_page_is_an_article_with_the_breadcrumbs_of_the_sidebar(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = paged_build(docs_site, tmp_path, address)

    assert docs_site.structured_data(build, build.pages["guides/wall.md"]) == WALL_GRAPH
    for page, crumbs in OTHER_CRUMBS.items():
        graph = docs_site.structured_data(build, build.pages[page])["@graph"]
        trail = next(node for node in graph if node["@type"] == "BreadcrumbList")
        items = trail["itemListElement"]
        assert [(item["name"], item["item"]) for item in items] == crumbs, page
        assert [item["position"] for item in items] == list(range(1, len(crumbs) + 1))


def test_every_page_carries_its_structured_data_in_a_script_that_cannot_end_early(
    docs_site: ModuleType, tmp_path: Path, address: object
) -> None:
    build = paged_build(docs_site, tmp_path, address)
    page = build.pages["guides/wall.md"]
    hostile = docs_site.Page(page.path, page.title, "Ends </script><b>here</b> & more.", "Body.\n")
    text = docs_site.structured_data_text(build, hostile)
    front = json.loads(docs_site.site_page_text(build, page).split("\n---\n", 1)[0][4:])
    scripts = [entry for entry in front["head"] if entry["tag"] == "script"]

    assert [c for c in "<>&" if c in text] == []
    assert json.loads(text)["@graph"][0]["description"] == "Ends </script><b>here</b> & more."
    assert scripts == [{**LD_JSON, "content": docs_site.structured_data_text(build, page)}]
    assert json.loads(scripts[0]["content"]) == WALL_GRAPH


def test_a_warning_from_astro_fails_the_build(docs_site: ModuleType) -> None:
    assert docs_site.WARNING.search("12:00:00 [WARN] [content] a duplicate id")
    assert docs_site.WARNING.search("(!) Some chunks are larger")
    assert docs_site.WARNING.search("12:00:00 [build] Complete!") is None


def test_a_warning_in_the_output_of_astro_stops_the_build(
    docs_site: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "site" / "node_modules" / ".bin" / "astro"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    printed = "12:00:00 [WARN] [content] a duplicate id\n12:00:00 [build] Complete!\n"

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=printed, stderr="")

    monkeypatch.setattr(docs_site.subprocess, "run", run)

    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.astro_build(tmp_path)
    assert str(raised.value) == (
        "astro build printed warnings:\n12:00:00 [WARN] [content] a duplicate id"
    )


@pytest.mark.parametrize("outside", [None, "0", ""], ids=["unset", "zero", "empty"])
def test_the_environment_turns_astro_telemetry_off(
    docs_site: ModuleType, monkeypatch: pytest.MonkeyPatch, outside: str | None
) -> None:
    name, value = TELEMETRY
    if outside is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, outside)

    assert docs_site._environment()[name] == value


def test_npm_ci_and_the_astro_build_run_with_astro_telemetry_off(
    docs_site: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, value = TELEMETRY
    monkeypatch.setenv(name, "0")
    binary = tmp_path / "site" / "node_modules" / ".bin" / "astro"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    seen: list[tuple[list[str], str | None]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        seen.append(([Path(args[0]).name, *args[1:]], env.get(name)))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(docs_site.shutil, "which", lambda program: f"/made-up/bin/{program}")
    monkeypatch.setattr(docs_site.subprocess, "run", run)

    docs_site.install(tmp_path)
    docs_site.astro_build(tmp_path)

    assert seen == [(["npm", "ci"], value), (["astro", "build"], value)]


def test_the_site_package_builds_through_the_site_tool(repo_root: Path) -> None:
    manifest = json.loads((repo_root / "site" / "package.json").read_text(encoding="utf-8"))
    tool = SITE_BUILD_SCRIPT.split()[1]

    assert manifest["scripts"] == {"build": SITE_BUILD_SCRIPT}
    assert (repo_root / "site" / tool).resolve() == (repo_root / "tools" / "docs_site.py")


def test_the_build_refuses_a_markdown_file_without_front_matter_beside_the_pages(
    docs_site: ModuleType, repo_root: Path, tmp_path: Path
) -> None:
    shutil.copytree(repo_root / "docs", tmp_path / "docs")
    (tmp_path / "site").mkdir()
    for name in ("site/navigation.json", "site/astro.config.mjs", "pyproject.toml"):
        shutil.copy2(repo_root / name, tmp_path / name)
    docs_site.load_build(tmp_path)
    (tmp_path / "docs" / "guides" / "notes.md").write_text("# Notes\n", encoding="utf-8")

    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.load_build(tmp_path)
    assert str(raised.value) == "pages without front matter: docs/guides/notes.md"


@pytest.mark.parametrize(
    ("page", "path", "markdown"),
    [
        ("index.md", "/tool/latest/", "/tool/latest/index.md"),
        ("guides/index.md", "/tool/latest/guides/", "/tool/latest/guides/index.md"),
        ("guides/wall.md", "/tool/latest/guides/wall/", "/tool/latest/guides/wall/index.md"),
    ],
)
def test_each_page_has_a_predictable_address_and_markdown_copy(
    docs_site: ModuleType, address: object, page: str, path: str, markdown: str
) -> None:
    assert docs_site.page_path(address, page) == path
    assert docs_site.markdown_path(address, page) == markdown


@pytest.mark.parametrize(("version", "folder"), [("0.1.0", "0.1"), ("12.03.4rc1", "12.3")])
def test_a_release_folder_is_the_major_and_minor_version(
    docs_site: ModuleType, version: str, folder: str
) -> None:
    assert docs_site.version_folder(version) == folder


def test_config_keys_and_flags_get_their_own_anchors(docs_site: ModuleType) -> None:
    config = "## Keys\n\n| Key | Default |\n|---|---|\n| `run.rounds` | `auto` |\n"
    commands = "## run\n\n| Flag | Key |\n|---|---|\n| `--rounds N` | `run.rounds` |\n"

    assert '<span id="run.rounds"></span>' in docs_site.config_anchors(config)
    assert '<span id="run--rounds"></span>' in docs_site.flag_anchors(commands)


def test_a_front_matter_value_with_a_colon_must_be_quoted(docs_site: ModuleType) -> None:
    with pytest.raises(docs_site.SiteError, match="must be written in double quotes"):
        docs_site.front_matter("---\ndescription: one: two\n---\n# A\n")

    meta, rest = docs_site.front_matter('---\ndescription: "one: two"\n---\n# A\n')
    assert (meta, rest) == ({"description": "one: two"}, "# A\n")
