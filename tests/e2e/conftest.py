# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The delivery path: build the wheel, install it into a fresh virtual environment, run it.

The ``installed`` fixture builds the wheel from this tree once per session,
installs it into a new virtual environment under a temporary folder and
runs the ``pairbench`` command of that environment. Its runs see a ``PATH``
that holds the environment's own programs and a folder of links to the few
programs a run needs (``true``, and a container engine where one is
found), so no other program of the machine is found or asked anything.

Without the ``build`` and ``hatchling`` modules the delivery tests are
skipped; with ``PAIRBENCH_REQUIRE_DELIVERY=1`` set that skip is a failure.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REQUIRE_DELIVERY = os.environ.get("PAIRBENCH_REQUIRE_DELIVERY", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
ENGINES = ("docker", "podman")
# Variables a run of the installed command keeps from the test's environment.
KEPT_VARIABLES = (
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "CONTAINER_HOST",
    "XDG_RUNTIME_DIR",
)
SEEDED_SIDE = Path(__file__).resolve().parent / "seeded_side.py"
STEP_TIMEOUT_S = 600


@dataclass(frozen=True)
class Done:
    """What one run of the installed command gave."""

    code: int
    out: str
    err: str


def _missing_build_modules() -> list[str]:
    return [name for name in ("build", "hatchling") if importlib.util.find_spec(name) is None]


def _step(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        timeout=STEP_TIMEOUT_S,
        **kwargs,
    )
    if done.returncode != 0:
        pytest.fail(
            f"{Path(argv[0]).name} {' '.join(argv[1:3])} exited {done.returncode}:\n"
            f"{done.stdout[-2000:]}\n{done.stderr[-2000:]}"
        )
    return done


class Installed:
    """The ``pairbench`` command of a fresh virtual environment."""

    def __init__(self, venv: Path, tools: Path) -> None:
        self.venv = venv
        self.tools = tools
        bin_folder = "Scripts" if os.name == "nt" else "bin"
        self.bin = venv / bin_folder
        self.python = self.bin / "python"
        self.command = self.bin / "pairbench"

    def environment(self, **extra: str) -> dict[str, str]:
        env = {name: os.environ[name] for name in KEPT_VARIABLES if name in os.environ}
        env["PATH"] = os.pathsep.join([str(self.bin), str(self.tools)])
        env.update(extra)
        return env

    def run(self, *args: str | Path, cwd: Path, env: dict[str, str] | None = None) -> Done:
        done = subprocess.run(
            [str(self.command), *(str(a) for a in args)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            env=env if env is not None else self.environment(),
            timeout=STEP_TIMEOUT_S,
        )
        return Done(code=done.returncode, out=done.stdout, err=done.stderr)

    def seeded(self, factor: float, *extra: str) -> str:
        """The command of a seeded side, run by this environment's Python."""
        words = [str(self.python), str(SEEDED_SIDE), "--factor", repr(factor), *extra]
        return " ".join(shlex.quote(word) for word in words)


def link_tools(folder: Path) -> Path:
    """A folder of links to the programs a run may need: ``true`` and the engines found."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("true", *ENGINES):
        found = shutil.which(name)
        if found:
            (folder / name).symlink_to(found)
    return folder


@pytest.fixture(scope="session")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Installed:
    """Build the wheel of this tree and install it into a new virtual environment."""
    missing = _missing_build_modules()
    if missing:
        reason = f"SKIPPED: the delivery path needs the modules {', '.join(missing)}"
        if REQUIRE_DELIVERY:
            pytest.fail(f"{reason} (PAIRBENCH_REQUIRE_DELIVERY=1 turns this skip into a failure)")
        pytest.skip(reason)
    root = Path(__file__).resolve().parents[2]
    base = tmp_path_factory.mktemp("delivery")
    wheels = base / "wheels"
    _step(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(wheels)],
        cwd=root,
    )
    built = sorted(wheels.glob("pairbench-*.whl"))
    assert len(built) == 1, [p.name for p in built]
    venv = base / "venv"
    _step([sys.executable, "-m", "venv", str(venv)])
    found = Installed(venv, link_tools(base / "tools"))
    _step(
        [str(found.python), "-m", "pip", "install", "--no-index", "--no-deps", str(built[0])],
        env=found.environment(PIP_DISABLE_PIP_VERSION_CHECK="1"),
    )
    return found


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """An empty folder to run the installed command in."""
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def primary(results: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """The primary comparisons of a results document by case and subject."""
    return {(c["case"], c["subject"]): c for c in results["comparisons"] if c["primary"]}


def capture_records(folder: Path, kind: str) -> list[dict[str, Any]]:
    """The records of one kind in the capture of a run folder."""
    lines = (folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()
    return [record for record in map(json.loads, lines) if record.get("t") == kind]
