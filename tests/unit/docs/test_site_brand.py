# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The look of the documentation site: its mark, its badges, its components and its footer.

The mark of the site is the mark of the README: the site's copies are the same files. The
mark, the favicon and the README's banners give the tiles a shadow from a filter whose region
is the mark's own 64-unit square, so the shadow is never cut by the edge of a smaller region,
and each file's ids are its own, so two of them on one page do not take each other's
gradients. The badges of the home page are drawn by the build from ``pyproject.toml`` and
fetch nothing. A page marks Starlight's components with comment lines and stays plain
Markdown in ``docs/``; the build writes it as MDX. The footer names the maker by the home
page of the host, the one address of the host outside the site that the check lets a page
link.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

MARKS = ("mark-light.svg", "mark-dark.svg")
# The files that draw the mark in the mark's 64-unit space: the two marks and the favicon.
MARK_DRAWINGS = (
    "docs/readme/mark-light.svg",
    "docs/readme/mark-dark.svg",
    "site/public/favicon.svg",
)
BANNERS = ("docs/readme/banner-light.svg", "docs/readme/banner-dark.svg")
# The shadow's filter: its region is the whole 64 by 64 drawing in the drawing's own units, and
# it works on the colours as they are written, in sRGB.
SHADOW_FILTER = (
    'filterUnits="userSpaceOnUse" x="0" y="0" width="64" height="64" '
    'color-interpolation-filters="sRGB"'
)
FILTER = re.compile(r'<filter id="([^"]+)" ([^>]*)>')
ID = re.compile(r'\bid="([^"]+)"')
REFERENCE = re.compile(r"url\(([^)]*)\)")
# The one id of a banner that is not the mark's or its own drawing's: its title.
BANNER_PREFIX = "banner-"
BANNER_TITLE_ID = "title"
FOOTER = "site/src/components/Footer.astro"
MAKER_LINE = 'pairbench is made by <a href="https://eugo.io/">Eugo</a>'
SITE = "https://made-up.example"
BASE = "/docs/tool/"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
LINK_PAGE = '<!doctype html><html><body><a href="{href}">x</a></body></html>'


@pytest.mark.parametrize("name", MARKS)
def test_the_site_shows_the_mark_of_the_readme(repo_root: Path, name: str) -> None:
    readme = (repo_root / "docs" / "readme" / name).read_bytes()

    assert (repo_root / "site" / "src" / "assets" / name).read_bytes() == readme


@pytest.mark.parametrize("name", MARK_DRAWINGS)
def test_the_shadow_of_the_mark_has_the_whole_drawing_as_its_region(
    repo_root: Path, name: str
) -> None:
    text = (repo_root / name).read_text(encoding="utf-8")

    filters = FILTER.findall(text)

    assert [rest for _, rest in filters] == [SHADOW_FILTER]
    assert f'filter="url(#{filters[0][0]})"' in text


def test_the_light_and_the_dark_mark_share_no_id(repo_root: Path) -> None:
    light, dark = (
        set(ID.findall((repo_root / "docs" / "readme" / name).read_text(encoding="utf-8")))
        for name in MARKS
    )

    assert light
    assert dark
    assert light & dark == set()


@pytest.mark.parametrize("name", BANNERS)
def test_a_banner_nests_the_mark_with_its_shadow_under_ids_of_its_own(
    repo_root: Path, name: str
) -> None:
    text = (repo_root / name).read_text(encoding="utf-8")
    ids = ID.findall(text)

    assert len(ids) == len(set(ids))
    assert [i for i in ids if not i.startswith(BANNER_PREFIX)] == [BANNER_TITLE_ID]
    assert [rest for _, rest in FILTER.findall(text)] == [SHADOW_FILTER]
    assert {ref.removeprefix("#") for ref in REFERENCE.findall(text)} <= set(ids)


@pytest.mark.parametrize("name", BANNERS)
def test_a_banner_draws_its_letters_as_outlines_and_loads_nothing(
    repo_root: Path, name: str
) -> None:
    text = (repo_root / name).read_text(encoding="utf-8")

    assert "<text" not in text
    assert "href" not in text
    assert "@import" not in text
    assert re.findall(r"https?://[^\"' ]+", text) == [SVG_NAMESPACE]
    assert [ref for ref in REFERENCE.findall(text) if not ref.startswith("#")] == []


def test_the_footer_names_the_maker(repo_root: Path) -> None:
    assert MAKER_LINE in (repo_root / FOOTER).read_text(encoding="utf-8")


def _check(docs_site: ModuleType, dist: Path, href: str) -> list[str]:
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(LINK_PAGE.format(href=href), encoding="utf-8")
    return list(docs_site.check_site(dist, docs_site.Address(SITE, BASE)))


@pytest.mark.parametrize("href", [f"{SITE}/", f"{SITE}/#about"])
def test_a_link_to_the_home_page_of_the_host_passes(
    docs_site: ModuleType, tmp_path: Path, href: str
) -> None:
    assert _check(docs_site, tmp_path, href) == []


@pytest.mark.parametrize("href", [f"{SITE}/other/", f"{SITE}/?page=1", f"{SITE}/docs/"])
def test_another_address_of_the_host_outside_the_site_is_refused(
    docs_site: ModuleType, tmp_path: Path, href: str
) -> None:
    assert _check(docs_site, tmp_path, href) == [f"index.html: an address outside {BASE}: {href}"]


def test_an_image_from_the_home_page_of_the_host_is_refused(
    docs_site: ModuleType, tmp_path: Path
) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text(
        f'<!doctype html><html><body><img src="{SITE}/" alt=""></body></html>', encoding="utf-8"
    )

    assert docs_site.check_site(tmp_path, docs_site.Address(SITE, BASE)) == [
        f"index.html: an address outside {BASE}: {SITE}/"
    ]


# --- badges ------------------------------------------------------------------------------


def test_the_badges_come_from_the_package_metadata(repo_root: Path, docs_site: ModuleType) -> None:
    with (repo_root / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    badges = {badge.name: badge.value for badge in docs_site.read_badges(repo_root)}

    assert badges["version"] == project["version"]
    assert badges["licence"] == project["license"]
    assert badges["python"].split(" | ")[0] == project["requires-python"].removeprefix(">=")


def test_the_badges_read_the_minor_versions_of_the_classifiers(
    docs_site: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "9.8.7"\nlicense = "MIT"\nclassifiers = [\n'
        '  "Programming Language :: Python :: 3",\n'
        '  "Programming Language :: Python :: 3 :: Only",\n'
        '  "Programming Language :: Python :: 3.21",\n'
        '  "Programming Language :: Python :: 3.22",\n]\n',
        encoding="utf-8",
    )

    assert [(b.name, b.value) for b in docs_site.read_badges(tmp_path)] == [
        ("version", "9.8.7"),
        ("python", "3.21 | 3.22"),
        ("licence", "MIT"),
    ]


def test_a_package_without_a_minor_version_has_no_python_badge(
    docs_site: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "9.8.7"\nlicense = "MIT"\n', encoding="utf-8"
    )

    with pytest.raises(docs_site.SiteError, match="names no Python minor version"):
        docs_site.read_badges(tmp_path)


def test_a_badge_names_no_address_but_its_namespace(repo_root: Path, docs_site: ModuleType) -> None:
    for badge in docs_site.read_badges(repo_root):
        svg = docs_site.badge_svg(badge)
        assert re.findall(r"https?://[^\"' ]+", svg) == [SVG_NAMESPACE]
        assert f"<title>{badge.alt}</title>" in svg


def test_a_badge_is_as_wide_as_its_texts(docs_site: ModuleType) -> None:
    badge = docs_site.Badge("version", "version", "9.8.7")

    svg = docs_site.badge_svg(badge)

    # 7 and 5 characters of 6.4 pixels, each text with 7 pixels on either side.
    assert '<svg xmlns="http://www.w3.org/2000/svg" width="104.8" height="20"' in svg
    assert 'textLength="44.8"' in svg
    assert 'textLength="32.0"' in svg


# --- Starlight's components ----------------------------------------------------------------

MARKED = """Intro with {braces} and `{kept}`.

<!-- steps -->

1. **Install**:

   <!-- tabs -->

   **pip**

   ```
   pip install x {y}
   ```

   **uv**

   ```
   uv tool install x
   ```

   <!-- /tabs -->

2. Run it.

<!-- /steps -->

<!-- example -->
<!-- cards -->

### First
<!-- icon: rocket -->

One.

### Second

Two.

<!-- /cards -->
"""
MDX = """import { Card, CardGrid, Steps, TabItem, Tabs } from '@astrojs/starlight/components';

Intro with \\{braces\\} and `{kept}`.

<Steps>

1. **Install**:

   <Tabs>

   <TabItem label="pip">

   ```
   pip install x {y}
   ```

   </TabItem>

   <TabItem label="uv">

   ```
   uv tool install x
   ```

   </TabItem>

   </Tabs>

2. Run it.

</Steps>

<CardGrid>

<Card title="First" icon="rocket">

One.

</Card>

<Card title="Second">

Two.

</Card>

</CardGrid>
"""


def test_a_marked_page_is_written_as_mdx_with_its_components(docs_site: ModuleType) -> None:
    assert docs_site.uses_components(MARKED)
    assert docs_site.mdx_body(MARKED) == MDX


def test_the_markdown_copy_leaves_the_markers_out(docs_site: ModuleType) -> None:
    copy = docs_site.without_markers(MARKED)

    assert "<!-- steps -->" not in copy
    assert "<!-- icon: rocket -->" not in copy
    assert "<!-- example -->" in copy
    assert "### First" in copy


def test_a_marker_inside_code_marks_nothing(docs_site: ModuleType) -> None:
    text = "```\n<!-- steps -->\n```\n"

    assert not docs_site.uses_components(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("<!-- steps -->\n1. x\n", "<!-- steps --> is never closed"),
        ("<!-- /tabs -->\n", "<!-- /tabs --> closes no open tabs region"),
        ("<!-- tabs -->\n<!-- /steps -->\n", "<!-- /steps --> closes no open steps region"),
    ],
)
def test_a_region_left_open_or_closed_twice_is_refused(
    docs_site: ModuleType, text: str, message: str
) -> None:
    with pytest.raises(docs_site.SiteError, match=re.escape(message)):
        docs_site.mdx_body(text)


@pytest.mark.parametrize(("page", "name"), [("index.md", "index.mdx"), ("faq.md", "faq.md")])
def test_only_a_page_that_uses_a_component_is_written_as_mdx(
    repo_root: Path, docs_site: ModuleType, page: str, name: str
) -> None:
    build = docs_site.load_build(repo_root)

    assert docs_site.content_name(build, build.pages[page]) == name


def test_the_home_page_is_a_hero_with_the_mark_and_the_badges(
    repo_root: Path, docs_site: ModuleType
) -> None:
    build = docs_site.load_build(repo_root)
    page = build.pages["index.md"]

    hero = docs_site.hero(build, page)

    assert hero["title"] == page.title
    assert hero["image"] == {
        "alt": "",
        "light": "../../../assets/mark-light.svg",
        "dark": "../../../assets/mark-dark.svg",
    }
    assert [action["link"] for action in hero["actions"]] == [
        "/docs/pairbench/latest/quickstart/",
        "/docs/pairbench/latest/install/",
        "https://github.com/eugo-inc/pairbench",
    ]
    assert hero["tagline"].startswith(page.description)
    assert hero["tagline"].count('<img src="/docs/pairbench/badges/') == 3


def test_a_card_title_is_no_anchor_of_the_page(docs_site: ModuleType) -> None:
    page = docs_site.Page("made-up.md", "Made up", "A made-up page.", MARKED)

    anchors = docs_site.site_anchors(page)

    assert "first" not in anchors
    assert "second" not in anchors


def test_a_heading_outside_the_cards_keeps_its_anchor(docs_site: ModuleType) -> None:
    body = "## Before\n\n<!-- cards -->\n\n### Card\n\nText.\n\n<!-- /cards -->\n\n### After\n"
    page = docs_site.Page("made-up.md", "Made up", "A made-up page.", body)

    anchors = docs_site.site_anchors(page)

    assert {"before", "after"} <= anchors
    assert "card" not in anchors


def test_a_repository_without_a_package_has_no_badges(
    repo_root: Path, docs_site: ModuleType, tmp_path: Path
) -> None:
    build = docs_site.load_build(repo_root)
    elsewhere = type(build)(
        tmp_path, build.address, build.version, build.navigation, build.pages, build.source
    )

    assert docs_site.badges_html(elsewhere) == ""
