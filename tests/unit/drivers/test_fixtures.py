# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every driver fixture has its sidecar, and the experimental mark follows the fixtures."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from pairbench import api, registry
from pairbench.api import DriverContext

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers"
SIDECAR = ".provenance.json"
SIDECAR_KEYS = {"generator", "seed", "tool", "version", "synthetic", "image", "command", "replaced"}
GENERATOR = "tests/fixtures/_gen/drivers.py"

# The fixture folder of each driver that reads a file. wall reads none.
FOLDERS = {
    "lines": "lines",
    "gbench": "gbench",
    "nvbench": "nvbench",
    "pytest-benchmark": "pytest-benchmark",
    "hyperfine": "hyperfine",
    "perf": "perf",
    "llama-bench": "llama-bench",
}
EXPERIMENTAL: set[str] = set()
TOOL_DRIVERS = ("gbench", "nvbench", "pytest-benchmark", "hyperfine", "perf", "llama-bench")


def _fixtures() -> list[Path]:
    """Return the fixtures of the drivers in FOLDERS; other drivers keep their own checks."""
    return sorted(
        p
        for folder in FOLDERS.values()
        for p in (FIXTURES / folder).glob("*")
        if p.is_file() and not p.name.endswith(SIDECAR)
    )


@pytest.mark.parametrize("folder", sorted(FOLDERS.values()))
def test_there_is_a_fixture_folder_for_every_driver_that_reads_a_file(folder: str) -> None:
    assert (FIXTURES / folder).is_dir()
    assert any(p.is_file() and not p.name.endswith(SIDECAR) for p in (FIXTURES / folder).iterdir())


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda p: str(p.relative_to(FIXTURES)))
def test_every_fixture_has_a_sidecar_that_says_how_it_was_made(fixture: Path) -> None:
    sidecar = fixture.with_name(fixture.name + SIDECAR)
    assert sidecar.is_file()
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert set(doc) >= SIDECAR_KEYS
    assert doc["generator"] == GENERATOR
    assert isinstance(doc["synthetic"], bool)
    if doc["synthetic"]:
        assert doc["image"] is None
    else:
        assert "@sha256:" in doc["image"]


@pytest.mark.parametrize("name", sorted(FOLDERS))
def test_a_driver_has_a_fixture_from_a_real_run_unless_it_is_experimental(name: str) -> None:
    sidecars = sorted((FIXTURES / FOLDERS[name]).glob(f"*{SIDECAR}"))
    assert sidecars
    real = any(not json.loads(p.read_text(encoding="utf-8"))["synthetic"] for p in sidecars)
    assert real is (name not in EXPERIMENTAL)


@pytest.mark.parametrize("name", TOOL_DRIVERS)
def test_doctor_shows_the_experimental_mark_exactly_without_a_real_run(name: str) -> None:
    driver = registry.driver(name)
    assert isinstance(driver, api.Diagnosable)
    expected = "experimental" if name in EXPERIMENTAL else "ok"
    assert driver.doctor().status == expected


# The fixture each driver reads, the name it reads it under, and a command to prepare.
READS = {
    "lines": ("lines/stdout.txt", "stdout.txt", ["python3", "work.py"]),
    "gbench": ("gbench/gbench.json", "gbench.json", ["./bench"]),
    "nvbench": ("nvbench/nvbench.json", "nvbench.json", ["./bench"]),
    "pytest-benchmark": (
        "pytest-benchmark/pytest-benchmark.json",
        "pytest-benchmark.json",
        ["pytest"],
    ),
    "hyperfine": ("hyperfine/hyperfine-v2.json", "hyperfine.json", ["hyperfine", "true"]),
    "perf": ("perf/perf-stat.txt", "perf-stat.txt", ["perf", "stat", "--", "true"]),
    "llama-bench": ("llama-bench/stdout.txt", "stdout.txt", ["llama-bench"]),
}


@pytest.mark.parametrize("name", sorted(READS))
def test_a_driver_prepared_and_read_twice_gives_the_same_both_times(
    name: str, make_ctx: MakeCtx, tmp_path: Path
) -> None:
    fixture, output, argv = READS[name]
    shutil.copy(FIXTURES / fixture, tmp_path / output)
    driver = registry.driver(name)
    first = (driver.prepare(make_ctx(), argv), driver.read(make_ctx(), tmp_path))
    second = (driver.prepare(make_ctx(), argv), driver.read(make_ctx(), tmp_path))
    assert first == second
    assert first[1]


def test_the_wall_driver_read_twice_gives_the_same_both_times(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    driver = registry.driver("wall")
    ctx = make_ctx(kind="image", timing={"run_s": 0.5, "launch_s": 0.25})
    assert driver.read(ctx, tmp_path) == driver.read(ctx, tmp_path)
    assert [s.case for s in driver.read(ctx, tmp_path)] == ["wall", "launch"]


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda p: str(p.relative_to(FIXTURES)))
def test_no_fixture_names_the_machine_it_ran_on(fixture: Path) -> None:
    sidecar = fixture.with_name(fixture.name + SIDECAR)
    text = fixture.read_text(encoding="utf-8") + sidecar.read_text(encoding="utf-8")
    for word in ("/home/", "/root/", "/out/", "/opt/", "/tmp/"):
        assert word not in text
