# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every test fixture has a provenance sidecar naming its generator, seed, tool and version."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SIDECAR = ".provenance.json"
REQUIRED = ("generator", "seed", "tool", "version", "synthetic")
SKIPPED_PARTS = frozenset({"_gen", "__pycache__"})


def fixtures_folder(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures"


def fixture_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.name.endswith(SIDECAR)
        and not SKIPPED_PARTS.intersection(path.relative_to(root).parts)
    )


def sidecars(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(f"*{SIDECAR}")
        if not SKIPPED_PARTS.intersection(path.relative_to(root).parts)
    )


def test_every_fixture_has_a_sidecar(repo_root: Path) -> None:
    root = fixtures_folder(repo_root)
    if not root.is_dir():
        pytest.skip("SKIPPED: the repository holds no fixtures folder")
    missing = [
        path.relative_to(root).as_posix()
        for path in fixture_files(root)
        if not path.with_name(path.name + SIDECAR).is_file()
    ]
    assert missing == []


def test_every_sidecar_belongs_to_a_fixture(repo_root: Path) -> None:
    root = fixtures_folder(repo_root)
    if not root.is_dir():
        pytest.skip("SKIPPED: the repository holds no fixtures folder")
    orphans = [
        path.relative_to(root).as_posix()
        for path in sidecars(root)
        if not path.with_name(path.name[: -len(SIDECAR)]).is_file()
    ]
    assert orphans == []


def test_every_sidecar_names_its_generator_seed_tool_version_and_origin(repo_root: Path) -> None:
    root = fixtures_folder(repo_root)
    if not root.is_dir():
        pytest.skip("SKIPPED: the repository holds no fixtures folder")
    problems: list[str] = []
    for path in sidecars(root):
        name = path.relative_to(root).as_posix()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            problems.append(f"{name}: not JSON ({type(error).__name__})")
            continue
        if not isinstance(document, dict):
            problems.append(f"{name}: not an object")
            continue
        problems += [f"{name}: no {key}" for key in REQUIRED if key not in document]
        generator = document.get("generator")
        if not isinstance(generator, str) or not generator.startswith("tests/fixtures/_gen/"):
            problems.append(f"{name}: the generator is not under tests/fixtures/_gen/")
        elif not (repo_root / generator).is_file():
            problems.append(f"{name}: the generator {generator} does not exist")
        synthetic = document.get("synthetic")
        if synthetic is not True and synthetic is not False:
            problems.append(f"{name}: synthetic is not true or false")
        if synthetic is False and not document.get("image"):
            problems.append(f"{name}: a fixture from a real run names no public image")
    assert problems == []


def test_a_fixture_without_a_sidecar_is_found(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    (root / "drivers").mkdir(parents=True)
    (root / "_gen").mkdir()
    (root / "drivers" / "kept.json").write_text("{}", encoding="utf-8")
    (root / "drivers" / "kept.json.provenance.json").write_text("{}", encoding="utf-8")
    (root / "drivers" / "bare.txt").write_text("x", encoding="utf-8")
    (root / "_gen" / "drivers.py").write_text("", encoding="utf-8")

    found = [path.relative_to(root).as_posix() for path in fixture_files(root)]

    assert found == ["drivers/bare.txt", "drivers/kept.json"]
    assert [p.name for p in sidecars(root)] == ["kept.json.provenance.json"]
