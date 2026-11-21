# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The positive control of an image side, run end to end with a real engine.

Each test runs ``pairbench run`` in a process of its own under a set umask,
with two image sides made from a tiny public image that is never pulled. The
baseline's image differs from it only in the user it runs as: root, a user
with the caller's user id, or another user. The control runs the baseline's
workload twice in one container, and each run keeps its output in files
pairbench creates in the folder it mounts.

The images are made by committing a container that was created and never
started, and are removed at the end. Without docker the tests are skipped
and listed in the closing banner; without the image on this machine they are
skipped with the reason.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import pairbench

pytestmark = pytest.mark.slow

ENGINE = "docker"
BASE_IMAGE = "busybox:1.37.0"
ROUNDS = 6
# What one run of the workload prints: one value on its output, one line on its errors.
WORKLOAD = (
    "sh",
    "-c",
    'echo \'::pairbench:: {"case": "a", "value": 1.0, "unit": "s", "better": "lower"}\'; '
    "echo a-made-up-line >&2",
)
# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
# The files each run of a control launch keeps its output in, under the launch's folder.
RUN_FILES = ("run1/stderr.txt", "run1/stdout.txt", "run2/stderr.txt", "run2/stdout.txt")
STEP_TIMEOUT_S = 120
RUN_TIMEOUT_S = 900
# The engine command that creates the container each image is committed from.
# The container is never started; it still gets a memory limit and no swap.
CREATE = (
    "create",
    "--rm",
    "--memory",
    "8g",
    "--memory-swap",
    "8g",
    "--network",
    "none",
    BASE_IMAGE,
    "true",
)
# A stand-in for hyperfine: its driver adds ``--export-json PATH`` after the
# workload's words, and the stand-in writes an export of one made-up command
# there with a shell redirection, so the file gets the mode the umask gives.
EXPORT_WORKLOAD = (
    "sh",
    "-c",
    'printf \'{"results": [{"command": "made-up", "times": [1.0, 1.0, 1.0], '
    '"exit_codes": [0, 0, 0]}]}\' > "$2"',
    "hyperfine",
)
EXPORT_FILE = "hyperfine.json"
CANNOT_REPEAT_LINE = (
    "pairbench: note: positive_control_cannot_repeat: the positive control does not run: "
    "'old' cannot run two commands in one start (the user the image of side old runs as "
    "cannot write the files pairbench creates in the folder it mounts, where the two runs keep "
    "their output; an image whose user is root or has your user id can)"
)


def _engine(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [ENGINE, *args], capture_output=True, text=True, check=False, timeout=STEP_TIMEOUT_S
    )


class Images:
    """Images made from ``BASE_IMAGE`` that run as a given user, all removed at the end."""

    def __init__(self) -> None:
        self._made: dict[str, str] = {}

    def as_user(self, user: str) -> str:
        if user in self._made:
            return self._made[user]
        if _engine("image", "inspect", BASE_IMAGE).returncode != 0:
            pytest.skip(f"needs the image {BASE_IMAGE} on this machine; it is never pulled here")
        created = _engine(*CREATE)
        assert created.returncode == 0, created.stderr
        container = created.stdout.strip()
        tag = f"localhost/pairbench-control-modes:{uuid.uuid4().hex[:12]}"
        try:
            done = _engine("commit", "--change", f"USER {user}", container, tag)
            assert done.returncode == 0, done.stderr
        finally:
            _engine("rm", "--force", container)
        self._made[user] = tag
        return tag

    def remove(self) -> None:
        for tag in self._made.values():
            _engine("rmi", "--force", tag)


def test_the_container_an_image_is_made_from_has_a_memory_limit_and_no_swap() -> None:
    assert "--rm" in CREATE
    memory = CREATE[CREATE.index("--memory") + 1]
    assert (memory, CREATE[CREATE.index("--memory-swap") + 1]) == ("8g", "8g")


@pytest.fixture(scope="module")
def images() -> Iterator[Images]:
    made = Images()
    yield made
    made.remove()


def _other_user() -> str:
    """A user id and group id that are neither root's nor the caller's."""
    other = 4321 if os.getuid() != 4321 else 4322
    return f"{other}:{other}"


def _config(folder: Path, baseline: str, workload: tuple[str, ...], driver: str) -> Path:
    path = folder / "pairbench.toml"
    argv = ", ".join(json.dumps(word) for word in workload)
    path.write_text(
        "\n".join(
            [
                "[run]",
                f"rounds = {ROUNDS}",
                "warmups = 1",
                'same_vs_same = "off"',
                "[workload]",
                f"argv = [{argv}]",
                f'driver = "{driver}"',
                "[sides.new]",
                f'image = "{BASE_IMAGE}"',
                "[sides.old]",
                f'image = "{baseline}"',
                "baseline = true",
                "[launch]",
                'memory = "8g"',
                'pull = "never"',
                f'engine = "{ENGINE}"',
                "[gates]",
                'mode = "off"',
                "[explain]",
                'mode = "off"',
                "[plots]",
                'mode = "off"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _run(
    folder: Path,
    baseline: str,
    mask: int,
    *,
    workload: tuple[str, ...] = WORKLOAD,
    driver: str = "lines",
) -> tuple[int, str, Path]:
    """Run ``pairbench run`` under ``mask``; return its exit code, its errors and its run folder."""
    out = folder / "run"
    source = str(Path(pairbench.__file__).resolve().parents[1])
    config = _config(folder, baseline, workload, driver)
    done = subprocess.run(
        [sys.executable, "-m", "pairbench", "run", "--config", str(config), "--out", str(out)],
        cwd=folder,
        env={**os.environ, "PYTHONPATH": source},
        capture_output=True,
        text=True,
        check=False,
        timeout=RUN_TIMEOUT_S,
        umask=mask,
    )
    return done.returncode, done.stderr, out


def _control(out: Path) -> dict[str, Any]:
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    control: dict[str, Any] = results["controls"]["positive"]
    return control


def _run_files(out: Path) -> list[Path]:
    return sorted(
        path
        for launch in (out / "artifacts").iterdir()
        if launch.name.endswith("_twice")
        for path in (launch / name for name in RUN_FILES)
        if path.exists()
    )


def _output_modes(out: Path) -> set[int]:
    """The modes of every file under the run's artifacts that holds what a process printed."""
    return {
        stat.S_IMODE(path.stat().st_mode)
        for path in (out / "artifacts").rglob("*")
        if path.is_file() and path.name in ("stdout.txt", "stderr.txt")
    }


@pytest.mark.parametrize(
    ("user", "mask"),
    [("0:0", 0o022), ("0:0", 0o002), ("caller", 0o022)],
    ids=["root-umask-022", "root-umask-002", "caller-uid-umask-022"],
)
@pytest.mark.needs_engine(ENGINE)
def test_the_control_runs_and_its_run_files_are_owner_only(
    needs: Any, images: Images, tmp_path: Path, user: str, mask: int
) -> None:
    needs.engine(ENGINE)
    if user == "caller":
        user = f"{os.getuid()}:{os.getgid()}"
    code, err, out = _run(tmp_path, images.as_user(user), mask)

    assert code == 0, err
    assert CANNOT_REPEAT_LINE not in err.splitlines()
    control = _control(out)
    assert (control["status"], control["entry"], control["via"]) == ("ok", "old~twice", "repeat")
    assert [(case["case"], case["ratio"], case["passed"]) for case in control["cases"]] == [
        ("a", 2.0, True)
    ]
    found = _run_files(out)
    assert len(found) == ROUNDS * len(RUN_FILES)
    assert all(path.stat().st_size > 0 for path in found)
    assert {stat.S_IMODE(path.stat().st_mode) for path in found} == {OWNER_ONLY}
    assert {path.stat().st_uid for path in found} == {os.getuid()}
    assert _output_modes(out) == {OWNER_ONLY}


@pytest.mark.parametrize("mask", [0o022, 0o000], ids=["umask-022", "umask-000"])
@pytest.mark.needs_engine(ENGINE)
def test_an_image_of_another_user_runs_no_control_and_says_why(
    needs: Any, images: Images, tmp_path: Path, mask: int
) -> None:
    needs.engine(ENGINE)
    code, err, out = _run(tmp_path, images.as_user(_other_user()), mask)

    assert code == 0, err
    assert CANNOT_REPEAT_LINE in err.splitlines()
    control = _control(out)
    assert (control["status"], control["entry"], control["via"], control["cases"]) == (
        "not_run",
        None,
        "repeat",
        [],
    )
    assert _run_files(out) == []
    assert _output_modes(out) == {OWNER_ONLY}


@pytest.mark.parametrize("mask", [0o022, 0o002], ids=["umask-022", "umask-002"])
@pytest.mark.needs_engine(ENGINE)
def test_the_export_a_tool_writes_in_a_container_is_owner_only_once_the_launch_ends(
    needs: Any, images: Images, tmp_path: Path, mask: int
) -> None:
    needs.engine(ENGINE)
    code, err, out = _run(
        tmp_path, images.as_user("0:0"), mask, workload=EXPORT_WORKLOAD, driver="hyperfine"
    )

    assert code == 0, err
    assert _control(out)["status"] == "ok"
    exports = sorted((out / "artifacts").rglob(EXPORT_FILE))
    in_run1 = [path for path in exports if path.parent.name == "run1"]
    in_run2 = [path for path in exports if path.parent.name == "run2"]
    assert len(in_run1) == len(in_run2) > 0
    assert len(exports) > len(in_run1) + len(in_run2)
    assert {stat.S_IMODE(path.stat().st_mode) for path in exports} == {OWNER_ONLY}
    assert {path.stat().st_uid for path in exports} == {os.getuid()}
    every = {path for path in (out / "artifacts").rglob("*") if path.is_file()}
    assert {stat.S_IMODE(path.stat().st_mode) for path in every} == {OWNER_ONLY}
