# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every page the build writes has a version picker in its header.

The picker lists the latest pages and every version folder the built site holds, newest
first, each a link to that version's home page, the one the page documents marked. The
made-up site documents 9.8.7 and keeps 9.7 and 0.10 of the published site.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

import pytest

from .test_docs_site import BASE, EXIT_OK, EXIT_REFUSED, SITE, address, write
from .test_earlier_versions import files, finished, published_site

__all__ = ["address"]


def built_page(tail: str) -> str:
    """A page as Astro writes it, cut to its canonical link and its header's title."""
    return (
        f'<html><head><link rel="canonical" href="{SITE}{BASE}latest/{tail}"></head><body>'
        f'<header><div class="title-wrapper sl-flex"><a href="{BASE}" class="site-title">tool'
        "</a></div><site-search></site-search></header></body></html>"
    )


def picker(here: str) -> str:
    """The picker of a page of the version ``here``: the latest pages, then 9.8, 9.7 and 0.10."""
    items = "".join(
        f'<li><a href="{BASE}{folder}/"'
        + (' aria-current="true"' if folder == here else "")
        + f">{folder}</a></li>"
        for folder in ("latest", "9.8", "9.7", "0.10")
    )
    return (
        f'<details class="pb-versions"><summary><span class="sr-only">Version: </span>{here}'
        f"</summary><ul>{items}</ul></details>"
    )


def with_picker(docs_site: ModuleType, tail: str, here: str) -> str:
    page = built_page(tail)
    page = page.replace("</head>", f"{docs_site.PICKER_STYLE}</head>")
    return page.replace("tool</a></div>", f"tool</a>{picker(here)}</div>")


TAILS = ("", "install/")


def test_the_pages_the_build_writes_name_every_version_in_their_header(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    for tail in TAILS:
        write(dist, f"latest/{tail}index.html", built_page(tail))
    write(dist, "404.html", built_page(""))
    site = published_site(tmp_path)

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    built = files(dist)
    for tail in TAILS:
        assert built[f"latest/{tail}index.html"].decode() == with_picker(docs_site, tail, "latest")
        assert built[f"9.8/{tail}index.html"].decode() == with_picker(docs_site, tail, "9.8")
    assert built["404.html"].decode() == with_picker(docs_site, "", "latest").replace(
        f'<link rel="canonical" href="{SITE}{BASE}latest/">', ""
    )
    assert "pb-versions" not in built["index.html"].decode()
    assert docs_site.check_site(dist, address) == []


def test_the_pages_of_a_build_without_a_published_site_name_its_own_version_and_latest(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    write(dist, "latest/install/index.html", built_page("install/"))

    code = docs_site.main(["finish"])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert (dist / "latest/install/index.html").read_text(encoding="utf-8") == (
        built_page("install/")
        .replace("</head>", f"{docs_site.PICKER_STYLE}</head>")
        .replace(
            "tool</a></div>",
            'tool</a><details class="pb-versions"><summary><span class="sr-only">Version: '
            f'</span>latest</summary><ul><li><a href="{BASE}latest/" aria-current="true">latest'
            f'</a></li><li><a href="{BASE}9.8/">9.8</a></li></ul></details></div>',
        )
    )


def test_a_page_that_has_a_picker_gets_the_new_one_in_its_place(docs_site: ModuleType) -> None:
    old = with_picker(docs_site, "install/", "9.7").replace("0.10", "0.9")

    page = docs_site.with_picker(old, "9.7/install/index.html", BASE, ["9.8", "0.10", "9.7"], "9.7")

    assert page == with_picker(docs_site, "install/", "9.7")


def test_a_page_without_a_header_is_left_as_it_is(docs_site: ModuleType) -> None:
    page = f'<html><head><meta http-equiv="refresh" content="0; url={BASE}latest/"></head></html>'

    assert docs_site.with_picker(page, "index.html", BASE, ["9.8"], "latest") == page


def test_the_build_refuses_a_header_without_the_title_the_picker_goes_beside(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    dist = tmp_path / "repo" / "site" / "dist"
    write(dist, "latest/install/index.html", built_page("install/").replace("title-wrapper", "x"))

    code = docs_site.main(["finish"])

    assert (code, capsys.readouterr()) == (
        EXIT_REFUSED,
        (
            "",
            "docs_site: latest/install/index.html has a header without one title wrapper, the "
            "place of the version picker: build the site with the Starlight that "
            "site/package-lock.json pins\n",
        ),
    )


def test_the_picker_style_uses_the_site_s_own_colours_and_loads_nothing(
    docs_site: ModuleType,
) -> None:
    style = docs_site.PICKER_STYLE

    assert re.fullmatch(r"<style data-pb-versions>[^<]*</style>", style)
    assert set(re.findall(r"var\((--[a-z0-9-]+)\)", style)) == {
        "--sl-text-sm",
        "--sl-color-gray-2",
        "--sl-color-gray-5",
        "--sl-color-bg-nav",
        "--sl-color-white",
        "--sl-color-text-accent",
    }
    assert [word for word in ("url(", "@import", "//") if word in style] == []


def test_the_kept_pages_get_the_picker_of_this_build_in_place_of_their_own(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    dist = tmp_path / "repo" / "site" / "dist"
    site = published_site(tmp_path)
    searchless = "<site-search></site-search>"
    for tail in TAILS:
        old = with_picker(docs_site, tail, "9.7").replace("0.10", "9.6")
        write(site, f"9.7/{tail}index.html", old.replace(searchless, ""))

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    for tail in TAILS:
        assert (dist / f"9.7/{tail}index.html").read_text(encoding="utf-8") == with_picker(
            docs_site, tail, "9.7"
        ).replace(searchless, "")
    assert (dist / "0.10/index.html").read_bytes() == (site / "0.10/index.html").read_bytes()
