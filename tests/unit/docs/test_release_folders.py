# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every release has its own folder of pages, and the version picker lists each one.

A build writes the pages of its release twice: in the release's own folder, such as
``9.8.7/``, and in the folder of its minor version, ``9.8/``, the address the tool prints,
which holds the pages of the minor version's newest release. A release folder the published
site lacks is put together once from the built site of that release, ``--saved SITE``. The
picker lists the latest pages and every release folder, newest first; the folder of a minor
version marks the release whose pages it holds and is not listed a second time, so every
address a published site serves still serves. Later builds keep every folder with
``--published`` alone.
"""

from __future__ import annotations

import dataclasses
import os
import re
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from .test_docs_site import BASE, EXIT_OK, EXIT_REFUSED, SITE, address, paged_build, write
from .test_earlier_versions import files, finished
from .test_kept_versions import VERSION_META, published, saved_site

__all__ = ["address"]

PICKER = re.compile(r'<details class="pb-versions">.*?</details>', re.DOTALL)
MARKED = re.compile(r"<summary><span class=\"sr-only\">Version: </span>([^<]*)</summary>")
LISTED = re.compile(r'<li><a href="([^"]*)"')
TAILS = ("", "install/")


def header_page(tail: str, version: str = "9.8.7") -> str:
    """A latest page as Astro writes it, cut to its version, its canonical link and the title
    of its header."""
    return (
        f'<html><head>{VERSION_META.format(version)}<link rel="canonical" '
        f'href="{SITE}{BASE}latest/{tail}"></head><body><header>'
        f'<div class="title-wrapper sl-flex"><a href="{BASE}" class="site-title">tool</a></div>'
        "</header></body></html>"
    )


def latest_pages(dist: Path, version: str = "9.8.7") -> None:
    for tail in TAILS:
        write(dist, f"latest/{tail}index.html", header_page(tail, version))


def pickers(dist: Path) -> dict[str, tuple[str, list[str]]]:
    """The version each page with a header marks, and the folders its picker lists, by the
    folder of the page."""
    found: dict[str, tuple[str, list[str]]] = {}
    for path in sorted(dist.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        picker = PICKER.search(text)
        if picker is None:
            continue
        marked = MARKED.search(picker.group(0))
        assert marked is not None
        listed = [href.removeprefix(BASE).rstrip("/") for href in LISTED.findall(picker.group(0))]
        folder = path.relative_to(dist).parts[0]
        seen = (marked.group(1), listed)
        assert found.setdefault(folder, seen) == seen, path
    return found


def version_names(dist: Path) -> list[str]:
    return sorted(path.name for path in dist.iterdir() if path.name[0].isdigit())


def with_version(
    docs_site: ModuleType, monkeypatch: pytest.MonkeyPatch, address: object, version: str
) -> None:
    """Make the made-up repository a build of ``version``."""

    def load_build(repo: Path) -> object:
        return dataclasses.replace(paged_build(docs_site, repo, address), version=version)

    monkeypatch.setattr(docs_site, "load_build", load_build)


def first_build(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, int]:
    """The site of 9.8.7 built over a published site that keeps 9.7, which holds the pages of
    9.7.1, with the saved sites of 9.7.1, 9.7.0 and 9.8.1."""
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    latest_pages(dist)
    saved = [saved_site(tmp_path, version) for version in ("9.7.1", "9.7.0", "9.8.1")]
    options = ["--published", str(published(tmp_path))]
    for site in saved:
        options += ["--saved", str(site)]
    return dist, docs_site.main(["finish", *options])


ALL_RELEASES = ["latest", "9.8.7", "9.8.1", "9.7.1", "9.7.0"]


@pytest.mark.parametrize(
    ("version", "folder"),
    [
        ("0.1.0", "0.1.0"),
        ("12.03.4", "12.3.4"),
        ("1.2.3.dev0", "1.2.3"),
        ("2.13.4rc1", "2.13.4"),
        ("0.4.0+local", "0.4.0"),
    ],
)
def test_a_release_s_own_folder_is_its_major_minor_and_patch_version(
    docs_site: ModuleType, version: str, folder: str
) -> None:
    assert docs_site.release_folder(version) == folder


@pytest.mark.parametrize("version", ["0.1", "1.2rc1", "x.1.2", ""])
def test_a_version_without_a_patch_part_has_no_release_folder(
    docs_site: ModuleType, version: str
) -> None:
    with pytest.raises(docs_site.SiteError) as raised:
        docs_site.release_folder(version)

    assert str(raised.value) == f"the version must start with MAJOR.MINOR.PATCH: {version!r}"


def test_each_earlier_release_gets_its_own_folder_and_a_place_in_the_picker(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist, code = first_build(docs_site, repo_root, tmp_path, address, monkeypatch)

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert version_names(dist) == [
        "9.7",
        "9.7.0",
        "9.7.0.md",
        "9.7.1",
        "9.7.1.md",
        "9.7.md",
        "9.8",
        "9.8.1",
        "9.8.1.md",
        "9.8.7",
        "9.8.7.md",
        "9.8.md",
    ]
    assert pickers(dist) == {
        "latest": ("latest", ALL_RELEASES),
        "9.8.7": ("9.8.7", ALL_RELEASES),
        "9.8": ("9.8.7", ALL_RELEASES),
        "9.8.1": ("9.8.1", ALL_RELEASES),
        "9.7.1": ("9.7.1", ALL_RELEASES),
        "9.7": ("9.7.1", ALL_RELEASES),
        "9.7.0": ("9.7.0", ALL_RELEASES),
    }
    page = (dist / "9.7.0/index.html").read_text(encoding="utf-8")
    assert f'<a href="{BASE}9.7.0/install/">' in page
    assert f'href="{BASE}9.7.0/_base/favicon.svg"' in page
    assert f"{BASE}latest/install/" not in page
    assert '<meta name="pairbench-version" content="9.7.0">' in page
    assert (dist / "9.8.1/_astro/Search.own.js").is_file()
    assert docs_site.check_site(dist, address) == []


def test_the_next_patch_release_keeps_every_release_with_the_published_site_alone(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist, first = first_build(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = tmp_path / "published-9.8.7"
    shutil.copytree(dist, site)
    with_version(docs_site, monkeypatch, address, "9.8.8")
    latest_pages(dist, "9.8.8")

    second = docs_site.main(["finish", "--published", str(site)])

    assert (first, second, capsys.readouterr()) == (EXIT_OK, EXIT_OK, ("", ""))
    releases = ["latest", "9.8.8", *ALL_RELEASES[1:]]
    assert pickers(dist) == {
        "latest": ("latest", releases),
        "9.8.8": ("9.8.8", releases),
        "9.8": ("9.8.8", releases),
        "9.8.7": ("9.8.7", releases),
        "9.8.1": ("9.8.1", releases),
        "9.7.1": ("9.7.1", releases),
        "9.7": ("9.7.1", releases),
        "9.7.0": ("9.7.0", releases),
    }
    for name in ("9.8.7", "9.8.1", "9.7.1", "9.7", "9.7.0"):
        kept, before = files(dist / name), files(site / name)
        assert sorted(kept) == sorted(before)
        for path, data in kept.items():
            if not path.endswith(".html"):
                assert data == before[path], f"{name}/{path}"
                continue
            text, old = data.decode(), before[path].decode()
            assert PICKER.sub("", text) == PICKER.sub("", old), f"{name}/{path}"
    assert 'content="9.8.8"' in (dist / "9.8/index.html").read_text(encoding="utf-8")
    assert docs_site.check_site(dist, address) == []


def test_the_next_minor_release_keeps_the_old_minor_folder_out_of_the_picker(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist, first = first_build(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = tmp_path / "published-9.8.7"
    shutil.copytree(dist, site)
    with_version(docs_site, monkeypatch, address, "9.9.0")
    latest_pages(dist, "9.9.0")

    second = docs_site.main(["finish", "--published", str(site)])

    assert (first, second, capsys.readouterr()) == (EXIT_OK, EXIT_OK, ("", ""))
    releases = ["latest", "9.9.0", *ALL_RELEASES[1:]]
    assert pickers(dist)["9.8"] == ("9.8.7", releases)
    assert pickers(dist)["9.9"] == ("9.9.0", releases)
    assert 'content="9.8.7"' in (dist / "9.8/index.html").read_text(encoding="utf-8")
    assert version_names(dist)[-4:] == ["9.9", "9.9.0", "9.9.0.md", "9.9.md"]
    assert docs_site.check_site(dist, address) == []


def test_a_published_site_with_only_latest_pages_gives_the_release_s_folders_alone(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    latest_pages(dist)
    site = tmp_path / "published"
    write(site, "latest/index.html", header_page("", "9.8.7"))

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert version_names(dist) == ["9.8", "9.8.7", "9.8.7.md", "9.8.md"]
    assert pickers(dist) == {
        "latest": ("latest", ["latest", "9.8.7"]),
        "9.8.7": ("9.8.7", ["latest", "9.8.7"]),
        "9.8": ("9.8.7", ["latest", "9.8.7"]),
    }


def test_the_published_site_gives_the_release_its_latest_pages_document_a_folder(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    latest_pages(dist)
    site = saved_site(tmp_path, "9.8.1")
    shutil.rmtree(site / "9.7")
    (site / "9.7.md").unlink()

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert version_names(dist) == ["9.8", "9.8.1", "9.8.1.md", "9.8.7", "9.8.7.md", "9.8.md"]
    assert pickers(dist)["9.8.1"] == ("9.8.1", ["latest", "9.8.7", "9.8.1"])
    assert (dist / "9.8.1/_base/favicon.svg").is_file()


def test_a_minor_folder_whose_release_has_no_folder_is_listed_by_its_own_name(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    latest_pages(dist)
    site = tmp_path / "published"
    write(site, "latest/index.html", header_page("", "9.8.7"))
    for tail in TAILS:
        write(site, f"9.7/{tail}index.html", header_page(tail, "9.7.1"))

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert pickers(dist)["9.7"] == ("9.7", ["latest", "9.8.7", "9.7"])


def test_a_minor_folder_listed_by_its_own_name_comes_before_the_releases_of_its_minor_version(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    latest_pages(dist)
    site = tmp_path / "published"
    write(site, "latest/index.html", header_page("", "9.8.7"))
    for tail in TAILS:
        write(site, f"9.7/{tail}index.html", header_page(tail, "9.7.1"))
        write(site, f"9.7.0/{tail}index.html", header_page(tail, "9.7.0"))

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    releases = ["latest", "9.8.7", "9.7", "9.7.0"]
    assert pickers(dist) == {
        "latest": ("latest", releases),
        "9.8.7": ("9.8.7", releases),
        "9.8": ("9.8.7", releases),
        "9.7": ("9.7", releases),
        "9.7.0": ("9.7.0", releases),
    }


def release_refusal(case: str, tmp_path: Path) -> tuple[list[str], str]:
    """Spoil the sources of the release folders one way: the options and what the build says."""
    site = published(tmp_path)
    if case == "a newer release folder":
        write(site, "9.8.9/index.html", header_page("", "9.8.9"))
        return ["--published", str(site)], (
            "the published site holds 9.8.9/, a version newer than 9.8.7, the one this build "
            "documents: build the documentation of the newest version"
        )
    saved = saved_site(tmp_path, "9.7.0")
    options = [
        "--published",
        str(site),
        "--saved",
        str(saved_site(tmp_path)),
        "--saved",
        str(saved),
    ]
    if case == "a link among the saved latest pages":
        os.symlink(saved / "latest" / "index.html", saved / "latest" / "install" / "copy.html")
        return options, (
            f"latest/install/copy.html in the saved site {saved} is a link: a kept folder holds "
            "files and folders"
        )
    if case == "a saved latest page without the place of the picker":
        write(saved, "latest/odd.html", "<html><head></head><body><header>x</header></body></html>")
        return options, (
            f"latest/odd.html in the saved site {saved} has a header without one title wrapper, "
            "the place of the version picker: give the built site as its release built it"
        )
    if case == "a saved site without a file its latest pages name":
        (saved / "share.png").unlink()
        return options, (
            f"the saved site {saved} has no share.png, which its latest pages name: give the "
            "built site of 9.7.0 as it was built"
        )
    if case == "a saved search fragment of a page its latest pages lack":
        shutil.rmtree(saved / "latest" / "install")
        fragment = saved / "pagefind/fragment/en_1.pf_fragment"
        return options, (
            f"{fragment} is the search fragment of latest/install/, a page that the saved site "
            f"{saved} does not hold: give the built site of 9.7.0 as it was built"
        )
    raise AssertionError(case)


RELEASE_REFUSALS = (
    "a newer release folder",
    "a link among the saved latest pages",
    "a saved latest page without the place of the picker",
    "a saved site without a file its latest pages name",
    "a saved search fragment of a page its latest pages lack",
)


@pytest.mark.parametrize("case", RELEASE_REFUSALS)
def test_the_finish_step_refuses_a_release_folder_it_cannot_put_together_before_it_writes(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    options, message = release_refusal(case, tmp_path)
    before = files(dist)

    code = docs_site.main(["finish", *options])

    assert (code, capsys.readouterr()) == (EXIT_REFUSED, ("", f"docs_site: {message}\n"))
    assert files(dist) == before


def test_the_finish_step_refuses_a_version_without_a_patch_part_before_it_writes(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    with_version(docs_site, monkeypatch, address, "9.8")
    before = files(dist)

    code = docs_site.main(["finish"])

    assert (code, capsys.readouterr()) == (
        EXIT_REFUSED,
        ("", "docs_site: the version must start with MAJOR.MINOR.PATCH: '9.8'\n"),
    )
    assert files(dist) == before


@pytest.mark.parametrize("version", ["9.8.7rc1", "9.8.7.dev0"])
def test_a_pre_release_builds_its_site_without_the_published_site(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    version: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    with_version(docs_site, monkeypatch, address, version)
    latest_pages(dist, version)

    code = docs_site.main(["finish"])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert version_names(dist) == ["9.8", "9.8.7", "9.8.7.md", "9.8.md"]
    assert pickers(dist) == {
        "latest": ("latest", ["latest", "9.8.7"]),
        "9.8.7": ("9.8.7", ["latest", "9.8.7"]),
        "9.8": ("9.8.7", ["latest", "9.8.7"]),
    }


@pytest.mark.parametrize("version", ["9.8.7rc1", "9.8.7.dev0", "9.8.7+local"])
def test_the_finish_step_refuses_the_published_site_for_a_version_that_is_not_a_release(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    version: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    with_version(docs_site, monkeypatch, address, version)
    site = published(tmp_path)
    before = files(dist)

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (
        EXIT_REFUSED,
        (
            "",
            f"docs_site: --published builds the site of a release, MAJOR.MINOR.PATCH: {version!r} "
            "is a pre-release, development or local version, whose pages would take the place "
            "of those of 9.8.7: build its site without --published\n",
        ),
    )
    assert files(dist) == before
