# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two tiny images compared by the installed command, under each container engine found.

Each image is made by running a container of a small public image that
writes one file, with its memory capped and no network, and committing that
container; nothing is built from a recipe file. One image prints values
twice those of the other. The test removes the containers and images it
made and nothing else. Without an engine the test is skipped and listed in
the closing banner; ``PAIRBENCH_REQUIRE_ENGINE=docker`` makes the skip of
that engine a failure.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .conftest import ENGINES, Installed, primary, read_json

pytestmark = [pytest.mark.delivery, pytest.mark.slow]

BASE_IMAGE = "docker.io/library/busybox:1.37.0"
BUILD_LIMITS = ("--memory", "256m", "--memory-swap", "256m", "--cpus", "1", "--network", "none")
RUN_MEMORY = "512m"
VALUES = {"alpha": 0.25, "beta": 1.5}
STEP_TIMEOUT_S = 300


def lines(factor: float) -> str:
    return "\n".join(
        "::pairbench:: "
        + json.dumps({"case": case, "value": base * factor, "unit": "s", "better": "lower"})
        for case, base in VALUES.items()
    )


def engine_step(engine: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine, *args], capture_output=True, text=True, check=False, timeout=STEP_TIMEOUT_S
    )


class Made:
    """The containers and images one test made, removed again at its end."""

    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.containers: list[str] = []
        self.images: list[str] = []

    def image(self, name: str, factor: float) -> str:
        container = f"pb-e2e-{uuid.uuid4().hex[:12]}"
        tag = f"localhost/pairbench-e2e-{name}:{uuid.uuid4().hex[:12]}"
        self.containers.append(container)
        script = f"printf '%s\\n' '{lines(factor)}' > /lines.txt"
        done = engine_step(
            self.engine, "run", "--name", container, *BUILD_LIMITS, BASE_IMAGE, "sh", "-c", script
        )
        assert done.returncode == 0, done.stderr
        done = engine_step(
            self.engine, "commit", "--change", 'CMD ["cat", "/lines.txt"]', container, tag
        )
        assert done.returncode == 0, done.stderr
        self.images.append(tag)
        engine_step(self.engine, "rm", "-f", container)
        return tag

    def leftovers(self) -> list[str]:
        found: list[str] = []
        for tag in self.images:
            done = engine_step(self.engine, "ps", "-a", "-q", "--filter", f"ancestor={tag}")
            found += done.stdout.split()
        return found

    def remove(self) -> None:
        for container in self.containers:
            engine_step(self.engine, "rm", "-f", container)
        for tag in self.images:
            engine_step(self.engine, "rmi", tag)


@pytest.fixture
def made(request: pytest.FixtureRequest) -> Iterator[Made]:
    engine = request.node.callspec.params["engine"]
    found = Made(engine)
    yield found
    found.remove()


@pytest.mark.parametrize(
    "engine", [pytest.param(engine, marks=pytest.mark.needs_engine(engine)) for engine in ENGINES]
)
def test_two_committed_images_compare_at_exactly_2(
    engine: str, needs: Any, made: Made, installed: Installed, tmp_path: Path
) -> None:
    needs.engine(engine)
    twice = made.image("twice", 2.0)
    once = made.image("once", 1.0)
    folder = tmp_path / "run"

    done = installed.run(
        "run",
        "--side",
        f"twice=image:{twice}",
        "--side",
        f"once=image:{once}",
        "--baseline",
        "once",
        "--engine",
        engine,
        "--pull",
        "never",
        "--driver",
        "lines",
        "--gates",
        "off",
        "--rounds",
        "8",
        "--explain",
        "off",
        "--plots",
        "off",
        "--set",
        f"launch.memory={RUN_MEMORY}",
        "--out",
        folder,
        cwd=tmp_path,
    )

    assert done.code == 0, done.err
    results = read_json(folder / "results.json")
    found = primary(results)
    assert sorted(found) == [(case, "twice") for case in VALUES]
    for case in VALUES:
        assert found[(case, "twice")]["ratio"] == 2.0
    assert made.leftovers() == []
