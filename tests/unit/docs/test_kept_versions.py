# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A kept version keeps its own badges, icon, share image and search, and no link to nothing.

The made-up site documents 9.8.7 and keeps 9.7. The pages of 9.7 name the files of the base
folder as its own release built them: the badge, the icon, the share image and the search
index. The build gives 9.7 its own copies of them in ``9.7/_base/``, taken once from the built
site of 9.7 (``--saved SITE``) or from the published site when its latest pages are 9.7's,
and points the pages at them. A link of a kept page to a latest page the build does not
hold points at the kept version's own copy of that page.
"""

from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from .test_docs_site import BASE, EXIT_OK, EXIT_REFUSED, SITE, address, write
from .test_earlier_versions import files, finished

__all__ = ["address"]

ROOT = f"{SITE}{BASE}"
# The search script of a Starlight page, cut to what names the index: the script of the
# search's interface it loads, the address of the pages' results and the folder of the index.
SEARCH = (
    'const u=()=>import("./ui.js");'
    "new t({element:`#starlight__search`,baseUrl:`" + BASE + "`,bundlePath:`" + BASE + "`"
    ".replace(/\\/$/,``)+`/pagefind/`,showImages:!1});\n"
)
# The script of the search's interface, which loads the search script in its turn.
SEARCH_UI = 'import{t as e}from"./Search.js";\n'
# The two scripts as a kept version has them: the search script loads the version's own
# index, and both are at addresses of their own, which no build served with other contents.
OWN_SEARCH = SEARCH.replace("bundlePath:`" + BASE + "`", "bundlePath:`" + BASE + "9.7/_base/`")
OWN_SEARCH = OWN_SEARCH.replace("./ui.js", "./ui.own.js")
OWN_SEARCH_UI = SEARCH_UI.replace("./Search.js", "./Search.own.js")
VERSION_META = '<meta name="pairbench-version" content="{}">'


def kept_page(
    tail: str, *, own: str = "", latest: str = "latest/", search: str = "Search.js"
) -> str:
    """A page of 9.7.1 as its release built it, at ``9.7/<tail>``: its canonical address, its
    social card's address and structured data name the latest page; its icon, share image and
    badge are files of the base folder; its search script is its own folder's."""
    files_at = f"{BASE}{own}"
    return (
        f"<html><head>{VERSION_META.format('9.7.1')}"
        f'<link rel="canonical" href="{ROOT}{latest}{tail}">'
        f'<meta property="og:url" content="{ROOT}{latest}{tail}">'
        f'<link rel="shortcut icon" href="{files_at}favicon.svg" type="image/svg+xml">'
        f'<meta property="og:image" content="{SITE}{files_at}share.png">'
        '<script type="application/ld+json">{"url":"' + f"{ROOT}{latest}{tail}" + '"}</script>'
        "</head><body><header>"
        f'<div class="title-wrapper sl-flex"><a href="{BASE}" class="site-title">tool</a></div>'
        f'<site-search></site-search><script type="module" src="{BASE}9.7/_astro/{search}">'
        "</script></header>"
        f'<img src="{files_at}badges/version.svg" alt="version 9.7.1">'
        f'<a href="{BASE}9.7/install/">Install</a></body></html>'
    )


# The pages of 9.7: the home page and the install page, which the latest pages still have,
# and a page that the latest pages have no more.
KEPT_TAILS = ("", "install/", "oldfaq/")
FRAGMENT = (
    b'pagefind_dcd{"url":"/latest/install/","content":"Install the tool, as of 9.7",'
    b'"meta":{"image":"' + BASE.encode() + b'badges/version.svg","image_alt":"version 9.7.1"}}'
)
OWN_FRAGMENT = FRAGMENT.replace(b'"/latest/', b'"/9.7/').replace(
    BASE.encode() + b"badges/", BASE.encode() + b"9.7/_base/badges/"
)
# The files of the base folder of 9.7's built site that its pages name, with made-up contents.
OWN_FILES = {
    "badges/version.svg": b"<svg><title>version 9.7.1</title></svg>\n",
    "favicon.svg": b"<svg><title>the icon of 9.7</title></svg>\n",
    "share.png": b"made-up share image of 9.7\n",
    "pagefind/pagefind.js": b"// the search of 9.7\n",
    "pagefind/fragment/en_1.pf_fragment": gzip.compress(FRAGMENT, mtime=0),
}
# What the built site of 9.8.7 holds at the same addresses: never what a 9.7 page shows.
CURRENT_FILES = {
    "badges/version.svg": "<svg><title>version 9.8.7</title></svg>\n",
    "favicon.svg": "<svg><title>the icon of 9.8</title></svg>\n",
}


def kept_folder(site: Path) -> None:
    for tail in KEPT_TAILS:
        write(site, f"9.7/{tail}index.html", kept_page(tail))
    write(site, "9.7/_astro/Search.js", SEARCH)
    write(site, "9.7/_astro/ui.js", SEARCH_UI)
    write(site, "9.7.md", "# tool 9.7\n")


def saved_site(tmp_path: Path, version: str = "9.7.1") -> Path:
    """The built site of 9.7.1 as its release left it."""
    site = tmp_path / f"saved-{version}"
    kept_folder(site)
    write(site, "latest/index.html", f"<html><head>{VERSION_META.format(version)}</head></html>")
    for name, data in OWN_FILES.items():
        (site / name).parent.mkdir(parents=True, exist_ok=True)
        (site / name).write_bytes(data)
    return site


def published(tmp_path: Path) -> Path:
    """The site as it is published: the latest pages of 9.8 and the folder of 9.7, copied in
    from 9.7's built site without its base files."""
    site = tmp_path / "published"
    kept_folder(site)
    write(site, "latest/index.html", f"<html><head>{VERSION_META.format('9.8.0')}</head></html>")
    return site


def current_base(dist: Path) -> None:
    for name, text in CURRENT_FILES.items():
        write(dist, name, text)


# The version picker of a 9.7 page: the latest pages, then 9.8 and 9.7, which it marks.
PICKER = (
    '<details class="pb-versions"><summary><span class="sr-only">Version: </span>9.7</summary>'
    f'<ul><li><a href="{BASE}latest/">latest</a></li><li><a href="{BASE}9.8/">9.8</a></li>'
    f'<li><a href="{BASE}9.7/" aria-current="true">9.7</a></li></ul></details>'
)


def expected_page(docs_site: ModuleType, tail: str) -> str:
    """A 9.7 page as the build keeps it: the base files are its own copies, the latest
    address of a page the build does not hold is the kept version's own page, and its header
    has the version picker."""
    latest = "latest/" if tail != "oldfaq/" else "9.7/"
    page = kept_page(tail, own="9.7/_base/", latest=latest, search="Search.own.js")
    page = page.replace("</head>", f"{docs_site.PICKER_STYLE}</head>")
    return page.replace("tool</a></div>", f"tool</a>{PICKER}</div>")


def test_a_kept_version_gets_its_own_files_and_links_from_its_saved_site(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    current_base(dist)
    saved = saved_site(tmp_path)

    code = docs_site.main(
        ["finish", "--published", str(published(tmp_path)), "--saved", str(saved)]
    )

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    built = files(dist)
    for tail in KEPT_TAILS:
        assert built[f"9.7/{tail}index.html"].decode() == expected_page(docs_site, tail)
    assert built["9.7/_astro/Search.own.js"].decode() == OWN_SEARCH
    assert built["9.7/_astro/ui.own.js"].decode() == OWN_SEARCH_UI
    assert [name for name in built if name in ("9.7/_astro/Search.js", "9.7/_astro/ui.js")] == []
    own = {name: data for name, data in OWN_FILES.items() if not name.endswith(".pf_fragment")}
    for name, data in own.items():
        assert built[f"9.7/_base/{name}"] == data
    fragment = built["9.7/_base/pagefind/fragment/en_1.pf_fragment"]
    assert gzip.decompress(fragment) == OWN_FRAGMENT
    assert fragment == gzip.compress(OWN_FRAGMENT, mtime=0)
    for name, text in CURRENT_FILES.items():
        assert built[name] == text.encode()
    assert docs_site.check_site(dist, address) == []


def test_a_kept_folder_given_back_as_published_stays_as_it_is(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    first = docs_site.main(
        ["finish", "--published", str(published(tmp_path)), "--saved", str(saved_site(tmp_path))]
    )
    again = tmp_path / "again"
    shutil.copytree(dist, again)
    once = files(dist / "9.7")

    second = docs_site.main(["finish", "--published", str(again)])

    assert (first, second, capsys.readouterr()) == (EXIT_OK, EXIT_OK, ("", ""))
    assert files(dist / "9.7") == once


def test_the_published_site_gives_its_own_files_to_the_version_its_latest_pages_are(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    current_base(dist)

    code = docs_site.main(["finish", "--published", str(saved_site(tmp_path))])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    built = files(dist)
    assert built["9.7/install/index.html"].decode() == expected_page(docs_site, "install/")
    assert built["9.7/_base/badges/version.svg"] == OWN_FILES["badges/version.svg"]
    assert gzip.decompress(built["9.7/_base/pagefind/fragment/en_1.pf_fragment"]) == OWN_FRAGMENT


def test_a_kept_page_names_itself_canonical_only_for_a_page_the_latest_pages_lack(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    write(dist, "9.7/oldfaq/index.html", f'<link rel="canonical" href="{ROOT}9.7/oldfaq/">')
    write(dist, "9.7/install/index.html", f'<link rel="canonical" href="{ROOT}9.7/install/">')
    write(dist, "9.7/index.html", f'<link rel="canonical" href="{ROOT}9.7/install/">')

    assert docs_site.check_site(dist, address) == [
        f"9.7/index.html: the canonical link is not a latest page: {ROOT}9.7/install/",
        f"9.7/install/index.html: the canonical link is not a latest page: {ROOT}9.7/install/",
    ]


NEEDS_SAVED = (
    "9.7/ in the published site has no _base/badges/version.svg, its own copy of a file its "
    "pages name: give the built site of 9.7 with --saved SITE"
)


def own_refusal(case: str, tmp_path: Path) -> tuple[list[str], str]:
    """Spoil the sources of the own files one way: the options to give and what the build
    says."""
    site = published(tmp_path)
    if case == "no source":
        return ["--published", str(site)], NEEDS_SAVED
    if case == "no published site":
        saved = saved_site(tmp_path)
        return ["--saved", str(saved)], (
            "--saved needs --published FOLDER: a saved site gives the own files of a version "
            "the published site keeps"
        )
    if case == "a saved site that is not a folder":
        given = tmp_path / "absent"
        return ["--published", str(site), "--saved", str(given)], (
            f"the saved site {given} is not a folder: give the folder of an earlier release's "
            "built site"
        )
    if case == "a saved site without its version":
        saved = saved_site(tmp_path)
        write(saved, "latest/index.html", "<html></html>")
        return ["--published", str(site), "--saved", str(saved)], (
            f"the saved site {saved} holds no latest/index.html that names its version: give "
            "the folder of an earlier release's built site"
        )
    if case == "a saved site of a version not kept":
        saved = saved_site(tmp_path, "9.6.2")
        return ["--published", str(site), "--saved", str(saved)], (
            f"the saved site {saved} documents 9.6, which the published site does not keep: "
            "copy its 9.6/ and 9.6.md into the published site first"
        )
    if case == "a saved site of the version built":
        saved = saved_site(tmp_path, "9.8.1")
        return ["--published", str(site), "--saved", str(saved)], (
            f"the saved site {saved} documents 9.8, the version this build documents: give "
            "the built sites of earlier versions"
        )
    if case == "two saved sites of one version":
        one, other = saved_site(tmp_path), saved_site(tmp_path, "9.7.0")
        return ["--published", str(site), "--saved", str(one), "--saved", str(other)], (
            f"two saved sites document 9.7: {one} and {other}: give one"
        )
    if case == "a saved site without a file the pages name":
        saved = saved_site(tmp_path)
        (saved / "favicon.svg").unlink()
        return ["--published", str(site), "--saved", str(saved)], (
            f"the saved site {saved} has no favicon.svg, which the pages of 9.7/ name: give the "
            "built site of 9.7 as it was built"
        )
    if case == "a published site without a file the pages name":
        given = saved_site(tmp_path)
        (given / "favicon.svg").unlink()
        return ["--published", str(given)], (
            f"the published site {given} has no favicon.svg, which the pages of 9.7/ name: give "
            "the built site of 9.7 as it was built"
        )
    if case == "a link among the own files":
        saved = saved_site(tmp_path)
        os.symlink(saved / "favicon.svg", saved / "pagefind" / "copy.svg")
        return ["--published", str(site), "--saved", str(saved)], (
            f"pagefind/copy.svg in the saved site {saved} is a link: a version's own files are "
            "files and folders"
        )
    if case == "a linked own file":
        saved = saved_site(tmp_path)
        (saved / "share.png").unlink()
        os.symlink(saved / "favicon.svg", saved / "share.png")
        return ["--published", str(site), "--saved", str(saved)], (
            f"share.png in the saved site {saved} is a link: a version's own files are files "
            "and folders"
        )
    if case == "a named pipe among the own files":
        saved = saved_site(tmp_path)
        os.mkfifo(saved / "badges" / "pipe")
        return ["--published", str(site), "--saved", str(saved)], (
            f"badges/pipe in the saved site {saved} is not a file or a folder: a version's own "
            "files are files and folders"
        )
    if case == "a fragment of another form":
        saved = saved_site(tmp_path)
        fragment = saved / "pagefind/fragment/en_1.pf_fragment"
        fragment.write_bytes(gzip.compress(b'pagefind_dcd{"hash":{"url":"/latest/"}}', mtime=0))
        return ["--published", str(site), "--saved", str(saved)], (
            f"{saved}/pagefind/fragment/en_1.pf_fragment is not the search fragment of one page "
            "under latest/: give the built site as it was built"
        )
    if case in ("a saved site that is the built folder", "a saved site in the built folder"):
        dist = tmp_path / "repo" / "site" / "dist"
        shutil.rmtree(dist)
        given = dist if case.endswith("is the built folder") else dist / "saved"
        shutil.copytree(saved_site(tmp_path), given)
        return ["--published", str(site), "--saved", str(given)], (
            f"the saved site {given} is the built folder or inside it, which the build "
            "replaces: give a copy of it outside site/dist"
        )
    if case == "a saved site of another release of the version":
        saved = saved_site(tmp_path, "9.7.0")
        return ["--published", str(site), "--saved", str(saved)], (
            f"the saved site {saved} documents 9.7.0, and 9.7/ in the published site holds the "
            "pages of 9.7.1: give the built site of 9.7.1"
        )
    if case == "a published site of another release of the version":
        given = saved_site(tmp_path, "9.7.0")
        return ["--published", str(given)], (
            f"the published site {given} documents 9.7.0, and 9.7/ in the published site holds "
            "the pages of 9.7.1: give the built site of 9.7.1"
        )
    if case == "a fragment of a page the kept folder lacks":
        saved = saved_site(tmp_path)
        fragment = saved / "pagefind/fragment/en_1.pf_fragment"
        fragment.write_bytes(gzip.compress(FRAGMENT.replace(b"/install/", b"/gone/"), mtime=0))
        return ["--published", str(site), "--saved", str(saved)], (
            f"{fragment} is the search fragment of latest/gone/, a page that 9.7/ in the "
            "published site does not hold: give the built site of 9.7 as it was built"
        )
    if case == "a kept page without the place of the picker":
        write(site, "9.7/odd.html", "<html><head></head><body><header>x</header></body></html>")
        return ["--published", str(site), "--saved", str(saved_site(tmp_path))], (
            "9.7/odd.html in the published site has a header without one title wrapper, the "
            "place of the version picker: give the version folders as the builds wrote them"
        )
    if case == "a search index elsewhere":
        write(
            site, "9.7/_astro/Search.js", SEARCH.replace("bundlePath:`" + BASE, "bundlePath:`/x/")
        )
        saved = saved_site(tmp_path)
        return ["--published", str(site), "--saved", str(saved)], (
            "9.7/ in the published site has a search, and no script of 9.7/_astro/ names its "
            "index in the base folder or in 9.7/_base/"
        )
    raise AssertionError(case)


OWN_REFUSALS = (
    "no source",
    "no published site",
    "a saved site that is not a folder",
    "a saved site without its version",
    "a saved site of a version not kept",
    "a saved site of the version built",
    "two saved sites of one version",
    "a saved site without a file the pages name",
    "a published site without a file the pages name",
    "a link among the own files",
    "a linked own file",
    "a named pipe among the own files",
    "a fragment of another form",
    "a search index elsewhere",
    "a saved site that is the built folder",
    "a saved site in the built folder",
    "a saved site of another release of the version",
    "a published site of another release of the version",
    "a fragment of a page the kept folder lacks",
    "a kept page without the place of the picker",
)


@pytest.mark.parametrize("case", OWN_REFUSALS)
def test_the_finish_step_refuses_a_kept_version_without_its_own_files_before_it_writes(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    options, message = own_refusal(case, tmp_path)
    before = files(dist)

    code = docs_site.main(["finish", *options])

    assert (code, capsys.readouterr()) == (EXIT_REFUSED, ("", f"docs_site: {message}\n"))
    assert files(dist) == before


@pytest.mark.parametrize("case", OWN_REFUSALS)
def test_the_build_refuses_a_kept_version_without_its_own_files_before_it_prepares(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    options, message = own_refusal(case, tmp_path)
    steps: list[str] = []
    monkeypatch.setattr(docs_site, "prepare", lambda repo: steps.append("prepare"))
    monkeypatch.setattr(docs_site, "install", lambda repo: steps.append("install"))
    monkeypatch.setattr(docs_site, "astro_build", lambda repo: steps.append("astro") or "")

    code = docs_site.main(["build", *options])

    assert (code, capsys.readouterr()) == (EXIT_REFUSED, ("", f"docs_site: {message}\n"))
    assert steps == []


def test_the_build_gives_the_saved_sites_to_the_finish_step(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    (dist.parent / "node_modules").mkdir()
    monkeypatch.setattr(docs_site, "prepare", lambda repo: None)
    monkeypatch.setattr(docs_site, "astro_build", lambda repo: "")
    saved = saved_site(tmp_path)

    code = docs_site.main(["build", "--published", str(published(tmp_path)), "--saved", str(saved)])

    assert (code, capsys.readouterr()) == (EXIT_OK, (f"built {dist}\n", ""))
    assert (dist / "9.7/_base/favicon.svg").read_bytes() == OWN_FILES["favicon.svg"]


def test_a_kept_page_names_the_latest_page_again_once_the_build_holds_it_again(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published(tmp_path)
    write(site, "9.7/install/index.html", kept_page("install/", latest="9.7/"))
    saved = saved_site(tmp_path)

    code = docs_site.main(["finish", "--published", str(site), "--saved", str(saved)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    page = (dist / "9.7/install/index.html").read_text(encoding="utf-8")
    assert page == expected_page(docs_site, "install/")
    assert f"{ROOT}9.7/install/" not in page


def test_a_kept_address_with_dot_segments_names_the_own_copy_of_the_file_it_resolves_to(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published(tmp_path)
    dotted = f'<img src="{BASE}badges/./x/../version.svg" alt="">'
    write(
        site, "9.7/install/index.html", kept_page("install/").replace("</body>", dotted + "</body>")
    )

    code = docs_site.main(
        ["finish", "--published", str(site), "--saved", str(saved_site(tmp_path))]
    )

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    page = (dist / "9.7/install/index.html").read_text(encoding="utf-8")
    assert page == expected_page(docs_site, "install/").replace(
        "</body>", f'<img src="{BASE}9.7/_base/badges/version.svg" alt=""></body>'
    )


def test_a_kept_address_that_climbs_out_of_its_own_file_stays_and_is_refused(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published(tmp_path)
    climbing = f"{BASE}badges/../../../share.png"
    page = kept_page("install/").replace("</body>", f'<img src="{climbing}" alt=""></body>')
    write(site, "9.7/install/index.html", page)

    code = docs_site.main(
        ["finish", "--published", str(site), "--saved", str(saved_site(tmp_path))]
    )

    assert (code, capsys.readouterr()) == (
        EXIT_REFUSED,
        (
            "",
            "docs_site: the built site has problems:\n"
            f"9.7/install/index.html: an address outside {BASE}: {climbing}\n",
        ),
    )
    assert f'<img src="{climbing}"' in (dist / "9.7/install/index.html").read_text("utf-8")
