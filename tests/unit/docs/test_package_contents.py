# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the source archive and the wheel carry: never an agent's notes or settings.

Both are built with the build backend from a copy of the project that holds a
``CLAUDE.md`` and a ``.claude/settings.json`` at its root and inside each
folder the archives take files from, and at its root the
``.claude/skills/pairbench`` link to the skill that the checkout carries.
None of them may come out in an archive.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip(
    "hatchling.build", reason="needs the build backend hatchling to build the archives"
)

ROOT = Path(__file__).resolve().parents[3]
COPIED = ("src/pairbench", "skills/pairbench", "LICENSE", "NOTICE", "README.md", "pyproject.toml")
PLANTED_IN = (".", "src/pairbench", "skills/pairbench")
AGENT_NOTES = "CLAUDE.md"
AGENT_FOLDER = ".claude"
SKILL_LINK = ".claude/skills/pairbench"
SKILL_LINK_TARGET = "../../skills/pairbench"
# The package index shows the README as the package's page: its type, its first line and
# the link to the documentation it carries.
README_TYPE = "Description-Content-Type: text/markdown"
# The README opens with a heading of the first level that holds the banner.
README_START = '<h1 align="center"><picture>'
DOCS_HOME = "https://eugo.io/docs/pairbench/latest/"
BUILD = (
    "import sys\n"
    "import hatchling.build as backend\n"
    "out = sys.argv[1]\n"
    "print(backend.build_sdist(out))\n"
    "print(backend.build_wheel(out))\n"
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The source archive and the wheel built from a planted copy."""
    tree = tmp_path_factory.mktemp("tree")
    for name in COPIED:
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(source, tree / name)
    for folder in PLANTED_IN:
        (tree / folder / AGENT_NOTES).write_text("made-up agent notes\n", encoding="utf-8")
        (tree / folder / AGENT_FOLDER).mkdir()
        (tree / folder / AGENT_FOLDER / "settings.json").write_text("{}\n", encoding="utf-8")
    link = tree / SKILL_LINK
    link.parent.mkdir()
    link.symlink_to(SKILL_LINK_TARGET, target_is_directory=True)
    assert (link / "SKILL.md").is_file()
    out = tmp_path_factory.mktemp("out")
    done = subprocess.run(
        [sys.executable, "-I", "-c", BUILD, str(out)],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    sdist, wheel = (out / line for line in done.stdout.split())
    return {"sdist": sdist, "wheel": wheel}


@pytest.fixture(scope="module")
def archives(built: dict[str, Path]) -> dict[str, list[str]]:
    """The member names of the source archive and of the wheel."""
    with tarfile.open(built["sdist"]) as archive:
        sdist_names = archive.getnames()
    with zipfile.ZipFile(built["wheel"]) as archive:
        wheel_names = archive.namelist()
    return {"sdist": sdist_names, "wheel": wheel_names}


@pytest.fixture(scope="module")
def metadata(built: dict[str, Path]) -> dict[str, str]:
    """The core metadata of the source archive (``PKG-INFO``) and of the wheel
    (``METADATA``), the text the package index shows."""
    with tarfile.open(built["sdist"]) as archive:
        member = next(
            m
            for m in archive.getmembers()
            if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")
        )
        handle = archive.extractfile(member)
        assert handle is not None
        sdist_text = handle.read().decode("utf-8")
    with zipfile.ZipFile(built["wheel"]) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        wheel_text = archive.read(name).decode("utf-8")
    return {"sdist": sdist_text, "wheel": wheel_text}


def _agent_files(names: list[str]) -> list[str]:
    return [
        name for name in names if Path(name).name == AGENT_NOTES or AGENT_FOLDER in Path(name).parts
    ]


@pytest.mark.parametrize("kind", ["sdist", "wheel"])
def test_the_archive_carries_no_agent_notes_or_settings(
    kind: str, archives: dict[str, list[str]]
) -> None:
    assert _agent_files(archives[kind]) == []


@pytest.mark.parametrize("kind", ["sdist", "wheel"])
def test_the_archive_still_carries_the_package_and_the_skill(
    kind: str, archives: dict[str, list[str]]
) -> None:
    names = archives[kind]
    assert any(name.endswith("pairbench/__init__.py") for name in names)
    assert any(name.endswith("/SKILL.md") for name in names)
    # The simulated error rates the plan and the report of a serving run read.
    assert any(name.endswith("pairbench/report/error_rates.json") for name in names)


@pytest.mark.parametrize("kind", ["sdist", "wheel"])
def test_the_metadata_carries_the_readme_as_the_long_description(
    kind: str, metadata: dict[str, str]
) -> None:
    headers, _, body = metadata[kind].partition("\n\n")

    assert README_TYPE in headers.splitlines()
    assert body.startswith(README_START)
    assert DOCS_HOME in body
    assert body == (ROOT / "README.md").read_text(encoding="utf-8")
