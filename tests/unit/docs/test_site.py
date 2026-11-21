# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The documentation site holds every page it must, lists each once, and its links resolve.

These tests need no Node, apart from one that asks npm to read the lockfile and skips
visibly without npm. The build of the site, and what it must hold, is tested in
``test_built_site.py``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

NAVIGATION = "site/navigation.json"
PACKAGE = "site/package.json"
LOCK = "site/package-lock.json"
NPM_SETTINGS = "site/.npmrc"
# npm's default lockfile format: every package under "packages", keyed by the folder it is
# installed in ("" is the site itself), with its version, address and integrity hash.
LOCK_FORMAT = 3
# The npm settings that change the lockfile's format or stop npm writing it.
LOCK_SETTINGS = ("lockfile-version", "package-lock")
# The lists of a package.json whose packages npm installs and locks at node_modules/NAME.
WANTED_LISTS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
REGISTRY = "https://registry.npmjs.org/"
ASTRO = "node_modules/astro"
NODE_FLOOR = re.compile(r">=\s*(\d+\.\d+\.\d+)")
SET_UP_NOTES = ("CONTRIBUTING.md", "AGENTS.md")
NPM_TIMEOUT_S = 120
ASTRO_CONFIG = "site/astro.config.mjs"
WORKFLOWS = ".github/workflows"
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# What a workflow holds when it publishes a site.
DEPLOYS = re.compile(r"deploy-pages|upload-pages-artifact|gh-pages|pages:\s*write", re.IGNORECASE)

# The pages of the site outline, the fifteen method pages and the reference pages.
OUTLINE_PAGES = (
    "index.md",
    "install.md",
    "quickstart.md",
    "concepts.md",
    "showcases.md",
    "agents.md",
    "comparison.md",
    "licence.md",
    "faq.md",
    "changelog.md",
)
METHOD_PAGES = (
    "paired-rounds.md",
    "noise-floor.md",
    "sign-test.md",
    "multiple-comparisons.md",
    "verdicts.md",
    "shared-machines.md",
    "instrument-controls.md",
    "first-token-definitions.md",
    "energy-per-token.md",
    "pitfalls.md",
    "reporting-checklist.md",
    "error-rates.md",
    "positive-control.md",
    "launch-cost.md",
    "diagnostics.md",
)
REFERENCE_PAGES = (
    "commands.md",
    "config.md",
    "results-schema.md",
    "plugin-api.md",
    "tool-server.md",
    "exit-codes.md",
    "text-format.md",
    "python-api.md",
)
COMPARED_TOOLS = ("hyperfine", "pyperf", "benchstat", "compare.py", "asv")
VERSION = re.compile(r"\bat (v?\d+\.\d+(\.\d+)?|commit `[0-9a-f]{7,}`)")
DATE = re.compile(
    r"\b(19|20)\d\d-\d\d-\d\d\b|\b(January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\b"
)


def driver_names(repo_root: Path) -> list[str]:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return sorted(project["project"]["entry-points"]["pairbench.drivers"])


def test_every_page_of_the_outline_exists(repo_root: Path) -> None:
    docs = repo_root / "docs"
    missing = [name for name in OUTLINE_PAGES if not (docs / name).is_file()]
    missing += [f"method/{n}" for n in METHOD_PAGES if not (docs / "method" / n).is_file()]
    missing += [f"reference/{n}" for n in REFERENCE_PAGES if not (docs / "reference" / n).is_file()]

    assert missing == []


def test_there_are_fifteen_method_pages() -> None:
    assert len(METHOD_PAGES) == 15


def test_every_built_in_driver_has_a_guide(repo_root: Path) -> None:
    guides = repo_root / "docs" / "guides"

    assert [name for name in driver_names(repo_root) if not (guides / f"{name}.md").is_file()] == []


def test_the_navigation_lists_every_page_once_and_only_pages_that_exist(
    repo_root: Path, kit: Any, docs_site: ModuleType
) -> None:
    docs = repo_root / "docs"
    listed = [entry.page for entry in docs_site.load_navigation(repo_root).entries]
    published = sorted(path.relative_to(docs).as_posix() for path in kit.site_pages(repo_root))

    assert sorted(set(listed)) == published
    assert len(listed) == len(set(listed))


def test_a_markdown_file_without_front_matter_is_not_a_page(repo_root: Path, kit: Any) -> None:
    pages = {path.relative_to(repo_root).as_posix() for path in kit.site_pages(repo_root)}

    assert "docs/readme/README.in.md" not in pages
    assert "docs/index.md" in pages


def test_every_markdown_file_beside_a_page_is_a_page(
    repo_root: Path, docs_site: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "docs" / "guides").mkdir(parents=True)
    (tmp_path / "docs" / "notes").mkdir()
    (tmp_path / "docs" / "guides" / "a.md").write_text('---\ndescription: "A."\n---\n')
    (tmp_path / "docs" / "guides" / "b.md").write_text("# B\n")
    (tmp_path / "docs" / "notes" / "c.md").write_text("# C\n")

    assert docs_site.stray_files(repo_root) == []
    assert docs_site.stray_files(tmp_path) == ["guides/b.md"]


def test_every_relative_link_of_the_site_resolves(repo_root: Path, kit: Any) -> None:
    broken: list[str] = []
    for page in kit.site_pages(repo_root):
        for target in kit.links(page.read_text(encoding="utf-8")):
            if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if not (page.parent / path).resolve().exists():
                broken.append(f"{page.relative_to(repo_root)} -> {target}")
    assert broken == []


def wanted_packages(package: dict[str, Any]) -> dict[str, str]:
    """The packages a ``package.json`` asks for, in any of its lists, with the version it
    asks for."""
    wanted: dict[str, str] = {}
    for field in WANTED_LISTS:
        wanted.update(package.get(field, {}))
    return wanted


def _installed_at(packages: dict[str, Any], folder: str, name: str) -> str | None:
    """The lockfile key npm installs ``name`` at for the package in ``folder``: its own
    ``node_modules`` first, then each folder above it."""
    while True:
        key = f"{folder}/node_modules/{name}" if folder else f"node_modules/{name}"
        if key in packages:
            return key
        if not folder:
            return None
        folder = folder.rpartition("/node_modules/")[0]


def lock_problems(package: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    """Every package of the site that is not pinned exactly or not locked, with why.

    A package the site asks for must name an exact version and be locked at it; every
    package of the lockfile must have an exact version, an address on the registry and an
    integrity hash; every package a locked package needs must be in the lockfile.
    """
    problems: list[str] = []
    packages: dict[str, Any] = lock.get("packages", {})
    wanted = wanted_packages(package)
    for name, version in wanted.items():
        if not EXACT_VERSION.match(version):
            problems.append(f"{name}: package.json asks for {version}, not one version")
        entry = packages.get(f"node_modules/{name}")
        if entry is None:
            problems.append(f"{name}: missing from the lockfile")
        elif entry.get("version") != version:
            problems.append(f"{name}: locked at {entry.get('version')}, wanted {version}")
    if wanted_packages(packages.get("", {})) != wanted:
        problems.append("the lockfile's own entry asks for other packages than package.json")
    for key, entry in packages.items():
        if not key:
            continue
        if not (
            EXACT_VERSION.match(str(entry.get("version", "")).split("-")[0])
            and str(entry.get("resolved", "")).startswith(REGISTRY)
            and str(entry.get("integrity", "")).startswith("sha512-")
        ):
            problems.append(f"{key}: no exact version, registry address and integrity hash")
        needs = {**entry.get("dependencies", {}), **entry.get("optionalDependencies", {})}
        for name in needs:
            if _installed_at(packages, key, name) is None:
                problems.append(f"{key}: needs {name}, missing from the lockfile")
    return problems


def test_every_package_of_the_site_is_pinned_exactly_and_locked(repo_root: Path) -> None:
    package = json.loads((repo_root / PACKAGE).read_text(encoding="utf-8"))
    lock = json.loads((repo_root / LOCK).read_text(encoding="utf-8"))
    wanted = wanted_packages(package)

    assert {"astro", "@astrojs/starlight"} <= set(wanted)
    assert lock["lockfileVersion"] == LOCK_FORMAT
    assert (lock["name"], lock["version"]) == (package["name"], package["version"])
    assert len(lock["packages"]) > len(wanted) + 1
    assert lock_problems(package, lock) == []


# A made-up site and its lockfile, each package pinned and locked.
SMALL_PACKAGE = {"name": "example-site", "version": "0.0.0", "dependencies": {"alpha": "1.2.3"}}


def _locked(version: str, **more: Any) -> dict[str, Any]:
    return {
        "version": version,
        "resolved": f"{REGISTRY}example/-/example-{version}.tgz",
        "integrity": "sha512-ZXhhbXBsZQ==",
        **more,
    }


def small_lock() -> dict[str, Any]:
    return {
        "name": "example-site",
        "version": "0.0.0",
        "lockfileVersion": LOCK_FORMAT,
        "packages": {
            "": {"name": "example-site", "version": "0.0.0", "dependencies": {"alpha": "1.2.3"}},
            "node_modules/alpha": _locked("1.2.3", dependencies={"beta": "^4.5.0"}),
            "node_modules/alpha/node_modules/beta": _locked("4.5.6"),
        },
    }


def test_a_pinned_and_locked_site_has_no_problem() -> None:
    assert lock_problems(SMALL_PACKAGE, small_lock()) == []


def test_a_package_the_site_asks_for_by_a_range_is_a_problem() -> None:
    package = {**SMALL_PACKAGE, "dependencies": {"alpha": "^1.2.3"}}
    lock = small_lock()
    lock["packages"][""]["dependencies"] = {"alpha": "^1.2.3"}

    assert lock_problems(package, lock) == [
        "alpha: package.json asks for ^1.2.3, not one version",
        "alpha: locked at 1.2.3, wanted ^1.2.3",
    ]


def test_a_package_the_site_asks_for_missing_from_the_lockfile_is_a_problem() -> None:
    package = {**SMALL_PACKAGE, "dependencies": {"alpha": "1.2.3", "gamma": "7.8.9"}}
    lock = small_lock()
    lock["packages"][""]["dependencies"] = dict(package["dependencies"])

    assert lock_problems(package, lock) == ["gamma: missing from the lockfile"]


@pytest.mark.parametrize("field", WANTED_LISTS)
def test_a_package_the_site_asks_for_by_a_range_in_any_list_is_a_problem(field: str) -> None:
    package = {**SMALL_PACKAGE, field: {**SMALL_PACKAGE.get(field, {}), "gamma": "^7.8.9"}}
    lock = small_lock()
    lock["packages"][""][field] = dict(package[field])
    lock["packages"]["node_modules/gamma"] = _locked("7.8.9")

    assert lock_problems(package, lock) == [
        "gamma: package.json asks for ^7.8.9, not one version",
        "gamma: locked at 7.8.9, wanted ^7.8.9",
    ]


@pytest.mark.parametrize("field", WANTED_LISTS)
def test_a_package_the_site_asks_for_in_any_list_missing_from_the_lockfile_is_a_problem(
    field: str,
) -> None:
    package = {**SMALL_PACKAGE, field: {**SMALL_PACKAGE.get(field, {}), "gamma": "7.8.9"}}
    lock = small_lock()
    lock["packages"][""][field] = dict(package[field])

    assert lock_problems(package, lock) == ["gamma: missing from the lockfile"]


def test_a_package_a_locked_package_needs_missing_from_the_lockfile_is_a_problem() -> None:
    lock = small_lock()
    del lock["packages"]["node_modules/alpha/node_modules/beta"]

    assert lock_problems(SMALL_PACKAGE, lock) == [
        "node_modules/alpha: needs beta, missing from the lockfile"
    ]


def test_a_package_npm_finds_in_a_folder_above_is_locked() -> None:
    lock = small_lock()
    lock["packages"]["node_modules/beta"] = lock["packages"].pop(
        "node_modules/alpha/node_modules/beta"
    )

    assert lock_problems(SMALL_PACKAGE, lock) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "4.x"),
        ("resolved", "https://packages.example.org/beta-4.5.6.tgz"),
        ("resolved", None),
        ("integrity", "sha1-ZXhhbXBsZQ=="),
        ("integrity", None),
    ],
    ids=["range", "other address", "no address", "weak hash", "no hash"],
)
def test_a_locked_package_without_a_version_address_or_hash_is_a_problem(
    field: str, value: str | None
) -> None:
    lock = small_lock()
    entry = lock["packages"]["node_modules/alpha/node_modules/beta"]
    if value is None:
        del entry[field]
    else:
        entry[field] = value

    assert lock_problems(SMALL_PACKAGE, lock) == [
        "node_modules/alpha/node_modules/beta: no exact version, registry address and "
        "integrity hash"
    ]


def test_a_lockfile_whose_own_entry_asks_for_other_packages_is_a_problem() -> None:
    lock = small_lock()
    lock["packages"][""]["dependencies"] = {}

    assert lock_problems(SMALL_PACKAGE, lock) == [
        "the lockfile's own entry asks for other packages than package.json"
    ]


@pytest.mark.needs_tool("npm")
def test_npm_finds_every_package_a_locked_package_needs_in_the_lockfile(repo_root: Path) -> None:
    """npm reads the lockfile alone, with no network, and finds each package every locked
    package needs at a version that package accepts."""
    env = {**os.environ, "npm_config_update_notifier": "false", "NO_COLOR": "1"}
    done = subprocess.run(
        [shutil.which("npm") or "npm", "ls", "--all", "--package-lock-only", "--offline"],
        cwd=repo_root / "site",
        env=env,
        capture_output=True,
        text=True,
        timeout=NPM_TIMEOUT_S,
        check=False,
    )
    errors = [line for line in done.stderr.splitlines() if line.startswith("npm error")]

    assert (done.returncode, errors) == (0, [])


def test_npm_keeps_the_lockfile_in_its_format(repo_root: Path) -> None:
    path = repo_root / NPM_SETTINGS
    settings = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    keys = [line.partition("=")[0].strip() for line in settings if "=" in line]
    lock = json.loads((repo_root / LOCK).read_text(encoding="utf-8"))

    assert [key for key in keys if key in LOCK_SETTINGS] == []
    assert lock["lockfileVersion"] == LOCK_FORMAT


def test_the_site_asks_for_the_node_version_the_pinned_astro_asks_for(repo_root: Path) -> None:
    package = json.loads((repo_root / PACKAGE).read_text(encoding="utf-8"))
    packages = json.loads((repo_root / LOCK).read_text(encoding="utf-8"))["packages"]
    floor = NODE_FLOOR.findall(packages[ASTRO]["engines"]["node"])[-1]

    assert package["engines"] == {"node": f">={floor}"}
    assert packages[""]["engines"] == package["engines"]
    for name in SET_UP_NOTES:
        text = " ".join((repo_root / name).read_text(encoding="utf-8").split())
        assert f"Node.js {floor} or newer" in text, name


def test_the_python_package_needs_no_node(repo_root: Path) -> None:
    project = (repo_root / "pyproject.toml").read_text(encoding="utf-8")

    assert not re.search(r"\b(npm|node|astro|site/)", project)


def test_the_site_shows_no_dates_editors_or_edit_links(repo_root: Path) -> None:
    config = (repo_root / ASTRO_CONFIG).read_text(encoding="utf-8")

    assert "lastUpdated: false" in config
    assert "credits: false" in config
    assert "editLink" not in config


def test_the_site_address_is_one_setting(repo_root: Path, docs_site: ModuleType) -> None:
    address = docs_site.read_address(repo_root)

    assert (address.site, address.base) == ("https://eugo.io", "/docs/pairbench/")
    assert address.root == "https://eugo.io/docs/pairbench/"


def test_the_release_folder_is_the_major_and_minor_version(docs_site: ModuleType) -> None:
    assert docs_site.version_folder("0.1.0") == "0.1"
    assert docs_site.version_folder("2.13.4rc1") == "2.13"


def test_no_workflow_publishes_the_site(repo_root: Path) -> None:
    folder = repo_root / WORKFLOWS
    files = sorted(folder.glob("*.y*ml")) if folder.is_dir() else []

    assert [path.name for path in files if DEPLOYS.search(path.read_text(encoding="utf-8"))] == []


def test_the_generated_pages_are_current(repo_root: Path, api_reference: ModuleType) -> None:
    page = repo_root / api_reference.PAGE

    assert page.read_text(encoding="utf-8") == api_reference.render(repo_root)


@pytest.mark.needs_tool("ruff")
def test_the_formatter_check_passes_on_the_reference_pages(repo_root: Path) -> None:
    # The formatter also formats the code blocks of Markdown pages; the page of
    # Python names must stay as its generator writes it, so the formatter skips it.
    done = subprocess.run(
        ["ruff", "format", "--check", "docs/reference"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("tool", COMPARED_TOOLS)
def test_the_comparison_names_each_tool_with_a_link_and_the_version_read(
    repo_root: Path, tool: str
) -> None:
    text = (repo_root / "docs" / "comparison.md").read_text(encoding="utf-8")
    sections = re.split(r"^## ", text, flags=re.MULTILINE)
    (section,) = [part for part in sections if tool in part.split("\n", 1)[0]]

    assert "](https://" in section
    assert VERSION.search(" ".join(section.split())), tool


def test_the_comparison_uses_the_agreed_wording(repo_root: Path) -> None:
    text = " ".join((repo_root / "docs" / "comparison.md").read_text(encoding="utf-8").split())

    assert "Most of these pieces exist in other tools." in text
    assert "If you know a tool that does the same, tell us." in text


def test_the_comparison_says_first_class_and_no_page_says_the_only(
    repo_root: Path, kit: Any
) -> None:
    comparison = " ".join((repo_root / "docs" / "comparison.md").read_text("utf-8").split())
    holding = [
        path.relative_to(repo_root).as_posix()
        for path in kit.site_pages(repo_root)
        if re.search(r"\bthe\s+only\b", path.read_text(encoding="utf-8"), re.IGNORECASE)
    ]

    assert "first-class" in comparison
    assert holding == []


def test_the_changelog_names_the_version_and_no_date(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"].get("version")
    text = (repo_root / "docs" / "changelog.md").read_text(encoding="utf-8")
    if version is None:
        from pairbench.model import TOOL_VERSION

        version = TOOL_VERSION

    assert f"## {version}" in text
    assert not DATE.search(text)


def test_the_licence_notes_carry_the_profiler_note(repo_root: Path) -> None:
    text = " ".join((repo_root / "docs" / "licence.md").read_text(encoding="utf-8").split())

    assert "It does not include, download or redistribute one." in text
    assert "The showcases here publish no output of a GPU profiler." in text
