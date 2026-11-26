# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The build keeps the earlier versions' folders of the site that is published.

``--published FOLDER`` names the site as it is published. Its version folders, ``9.7/`` and
the Markdown page ``9.7.md`` beside it, are copied into the built site as they are; the
two folders of the release the build documents, the latest pages and the base pages are the
build's own. The site is made up, of the release 9.8.7, whose folders are ``9.8.7``, its own,
and ``9.8``, its minor version's.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import ModuleType

import pytest

from .test_docs_site import (
    ASTRO_CONFIG,
    BASE,
    EXIT_OK,
    EXIT_REFUSED,
    SITE,
    address,
    astro_stand_in,
    paged_build,
    staged_image,
    write,
)

__all__ = ["address"]  # the fixture of the made-up address, shared with the generator's tests

# A page of an earlier version: its canonical link names a latest page, its links stay in
# its own folder.
EARLIER_PAGE = (
    f'<html><head><link rel="canonical" href="{SITE}{BASE}latest/install/"></head>'
    f'<body><a href="{BASE}9.7/install/">Install</a></body></html>'
)
EARLIER_FILES = {
    "9.7/index.html": EARLIER_PAGE,
    "9.7/install/index.html": EARLIER_PAGE,
    "9.7/install/index.md": "# Install the tool, as of 9.7\n",
    "9.7/_astro/page.css": "body { margin: 0; }\n",
    "9.7.md": "# tool 9.7\n",
    "0.10/index.html": EARLIER_PAGE.replace("9.7", "0.10"),
    "0.10/install/index.html": EARLIER_PAGE.replace("9.7", "0.10"),
}
# What the published site holds that the build writes itself, with text the build never
# writes: none of it may reach the built site.
STALE = "stale text of the published site\n"
STALE_FILES = (
    "9.8/index.html",
    "9.8.md",
    "9.8.7/index.html",
    "9.8.7.md",
    "latest/index.html",
    "index.html",
    "llms.txt",
)
NO_LATEST = "holds no latest/index.html: give the folder of the site as it is published"


def finished(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """The made-up repository after prepare and the Astro step: its built folder."""
    repo = tmp_path / "repo"
    staged_image(repo_root, repo)
    write(repo, "site/astro.config.mjs", ASTRO_CONFIG)
    monkeypatch.setattr(docs_site, "REPO", repo)
    monkeypatch.setattr(docs_site, "load_build", lambda repo: paged_build(docs_site, repo, address))
    monkeypatch.setattr(docs_site, "read_version", lambda repo: "9.8.7")
    monkeypatch.setattr(docs_site, "check_generated_pages", lambda repo: None)
    assert docs_site.main(["prepare"]) == EXIT_OK
    return astro_stand_in(docs_site, paged_build(docs_site, repo, address))


def published_site(tmp_path: Path) -> Path:
    site = tmp_path / "published"
    for name, text in EARLIER_FILES.items():
        write(site, name, text)
    for name in STALE_FILES:
        write(site, name, STALE)
    return site


def files(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_the_finish_step_keeps_every_earlier_version_folder_as_it_is(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    built = files(dist)
    for name, text in EARLIER_FILES.items():
        assert built[name] == text.encode()
    assert files(dist / "9.7") == files(site / "9.7")
    for name in STALE_FILES:
        assert built[name] != STALE.encode()
    assert built["9.8/index.html"] == built["latest/index.html"]
    assert built["9.8.7/index.html"] == built["latest/index.html"]
    assert docs_site.check_site(dist, address) == []


def test_the_finish_step_without_a_published_site_writes_the_release_s_folders_only(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)

    code = docs_site.main(["finish"])

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    assert sorted(p.name for p in dist.iterdir() if p.is_dir()) == [
        "9.8",
        "9.8.7",
        "_astro",
        "latest",
    ]


def refusal(case: str, site: Path, dist: Path) -> tuple[Path, str]:
    """Spoil the published site one way: the folder to give and what the build says."""
    if case == "missing":
        given = site / "absent"
        return given, (
            f"the published site {given} is not a folder: give the folder of the site as it is "
            "published"
        )
    if case == "a file":
        given = site / "9.7.md"
        return given, (
            f"the published site {given} is not a folder: give the folder of the site as it is "
            "published"
        )
    if case == "the built folder":
        return dist, (
            f"the published site {dist} is the built folder or inside it, which the build "
            "replaces: give a folder outside site/dist"
        )
    if case == "inside the built folder":
        given = dist / "copy"
        given.mkdir()
        return given, (
            f"the published site {given} is the built folder or inside it, which the build "
            "replaces: give a folder outside site/dist"
        )
    if case == "a newer version":
        write(site, "9.10/index.html", EARLIER_PAGE)
        return site, (
            "the published site holds 9.10/, a version newer than 9.8, the one this build "
            "documents: build the documentation of the newest version"
        )
    if case == "a version that is a file":
        write(site, "9.6", STALE)
        return site, "9.6 in the published site is not a version folder: a folder with index.html"
    if case == "a version folder without its page":
        write(site, "9.6/install/index.html", EARLIER_PAGE)
        return site, "9.6 in the published site is not a version folder: a folder with index.html"
    if case == "a linked version folder":
        os.symlink(site / "9.7", site / "9.6")
        return site, "9.6 in the published site is a link: a kept folder holds files and folders"
    if case == "a link inside a version folder":
        os.symlink(site / "9.7" / "index.html", site / "9.7" / "install" / "copy.html")
        return site, (
            "9.7/install/copy.html in the published site is a link: a kept folder holds files "
            "and folders"
        )
    if case == "a linked markdown page":
        (site / "9.7.md").unlink()
        os.symlink(site / "9.8.md", site / "9.7.md")
        return site, (
            "9.7.md in the published site is a link: a kept folder holds files and folders"
        )
    if case == "a version folder given":
        given = site / "9.7"
        return given, f"the published site {given} {NO_LATEST}"
    if case == "a folder that holds the site":
        given = site.parent
        return given, f"the published site {given} {NO_LATEST}"
    if case == "a named pipe inside a version folder":
        os.mkfifo(site / "9.7" / "install" / "pipe")
        return site, (
            "9.7/install/pipe in the published site is not a file or a folder: a kept folder "
            "holds files and folders"
        )
    if case == "a markdown page that is a folder":
        (site / "9.7.md").unlink()
        (site / "9.7.md").mkdir()
        return site, (
            "9.7.md in the published site is not a file: the Markdown page beside a version "
            "folder is a file"
        )
    raise AssertionError(case)


REFUSALS = (
    "missing",
    "a file",
    "the built folder",
    "inside the built folder",
    "a newer version",
    "a version that is a file",
    "a version folder without its page",
    "a linked version folder",
    "a link inside a version folder",
    "a linked markdown page",
    "a version folder given",
    "a folder that holds the site",
    "a named pipe inside a version folder",
    "a markdown page that is a folder",
)


@pytest.mark.parametrize("case", REFUSALS)
def test_the_finish_step_refuses_a_published_site_it_cannot_keep_before_it_writes(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    given, message = refusal(case, published_site(tmp_path), dist)
    before = files(dist)

    code = docs_site.main(["finish", "--published", str(given)])

    assert (code, capsys.readouterr()) == (EXIT_REFUSED, ("", f"docs_site: {message}\n"))
    assert files(dist) == before


@pytest.mark.parametrize("case", REFUSALS)
def test_the_build_refuses_a_published_site_it_cannot_keep_before_it_prepares(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    given, message = refusal(case, published_site(tmp_path), dist)
    steps: list[str] = []
    monkeypatch.setattr(docs_site, "prepare", lambda repo: steps.append("prepare"))
    monkeypatch.setattr(docs_site, "install", lambda repo: steps.append("install"))
    monkeypatch.setattr(docs_site, "astro_build", lambda repo: steps.append("astro") or "")

    code = docs_site.main(["build", "--published", str(given)])

    assert (code, capsys.readouterr()) == (EXIT_REFUSED, ("", f"docs_site: {message}\n"))
    assert steps == []


def test_the_build_gives_the_published_site_to_the_finish_step(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)
    (dist.parent / "node_modules").mkdir()
    monkeypatch.setattr(docs_site, "prepare", lambda repo: None)
    monkeypatch.setattr(docs_site, "astro_build", lambda repo: "")

    code = docs_site.main(["build", "--published", str(site)])

    assert (code, capsys.readouterr()) == (EXIT_OK, (f"built {dist}\n", ""))
    assert files(dist / "9.7") == files(site / "9.7")
    assert (dist / "9.7.md").read_bytes() == (site / "9.7.md").read_bytes()


def test_the_finish_step_checks_the_kept_folders_with_the_rest_of_the_site(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)
    write(site, "9.7/index.html", EARLIER_PAGE.replace("9.7/install/", "9.7/absent/"))

    code = docs_site.main(["finish", "--published", str(site)])

    assert (code, capsys.readouterr()) == (
        EXIT_REFUSED,
        (
            "",
            "docs_site: the built site has problems:\n"
            f"9.7/index.html: a link to nothing: {BASE}9.7/absent/\n",
        ),
    )


def test_the_finish_step_run_twice_keeps_the_same_folders(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)

    first = docs_site.main(["finish", "--published", str(site)])
    once = files(dist)
    second = docs_site.main(["finish", "--published", str(site)])

    assert (first, second, capsys.readouterr()) == (EXIT_OK, EXIT_OK, ("", ""))
    assert files(dist) == once
    assert files(dist / "9.7") == files(site / "9.7")


def test_the_finish_step_run_again_with_fewer_versions_keeps_only_those(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)
    first = docs_site.main(["finish", "--published", str(site)])
    for path in sorted((site / "0.10").rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    (site / "0.10").rmdir()
    (site / "9.7.md").unlink()

    second = docs_site.main(["finish", "--published", str(site)])

    assert (first, second, capsys.readouterr()) == (EXIT_OK, EXIT_OK, ("", ""))
    assert sorted(p.name for p in dist.iterdir() if p.name[0].isdigit()) == [
        "9.7",
        "9.8",
        "9.8.7",
        "9.8.7.md",
        "9.8.md",
    ]
    assert files(dist / "9.7") == files(site / "9.7")


def test_the_finish_step_leaves_the_kept_folders_writable(
    docs_site: ModuleType,
    repo_root: Path,
    tmp_path: Path,
    address: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = finished(docs_site, repo_root, tmp_path, address, monkeypatch)
    site = published_site(tmp_path)
    kept = [site / "9.7.md", site / "9.7", *(site / "9.7").rglob("*")]
    for path in sorted(kept, reverse=True):
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)
    try:
        code = docs_site.main(["finish", "--published", str(site)])
    finally:
        for path in kept:
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)

    assert (code, capsys.readouterr()) == (EXIT_OK, ("", ""))
    copied = [dist / "9.7.md", dist / "9.7", *(dist / "9.7").rglob("*")]
    assert [p.relative_to(dist).as_posix() for p in copied if not p.stat().st_mode & 0o200] == []
    assert files(dist / "9.7") == files(site / "9.7")
