# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A run interrupted during a launch of an image that runs as root, with a real engine.

Each test runs ``pairbench run`` in a session of its own under a set umask,
with two image sides, or two serving sides, made from a tiny public image
that runs as root and is never pulled. The workload, or the server, writes a
file into the folder it is given, then sleeps, or serves a folder whose
readiness address never answers. Once the file is there, the test sends an
interrupt or a termination request to the run's process group, as a terminal
or a job system does, and reads who owns the file and its mode after the run
has exited.

Without docker the tests are skipped and listed in the closing banner;
without the image on this machine they are skipped with the reason.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.errors import EXIT_INTERRUPTED

pytestmark = pytest.mark.slow

ENGINE = "docker"
IMAGE = "busybox:1.37.0"
EXPORT_FILE = "export.txt"
# The workload writes its export as root, with the mode the umask gives, and waits.
WORKLOAD = (
    "sh",
    "-c",
    f"echo a-made-up-export > /pairbench/artifacts/{EXPORT_FILE}; sleep 60",
)
# The server writes its export as root, then serves an empty folder, so the
# readiness address never answers and the launch waits until it is stopped.
SERVER = (
    "sh",
    "-c",
    f"echo a-made-up-export > /pairbench/artifacts/{EXPORT_FILE}; mkdir -p /www; "
    "exec httpd -f -p 8000 -h /www",
)
# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
STEP_TIMEOUT_S = 120
# How long the first export may take to appear, and the run to exit after the signal.
EXPORT_WAIT_S = 600
EXIT_WAIT_S = 300


def _image_lines() -> list[str]:
    argv = ", ".join(json.dumps(word) for word in WORKLOAD)
    return [
        "[workload]",
        f"argv = [{argv}]",
        'driver = "wall"',
        "[sides.new]",
        f'image = "{IMAGE}"',
        'env = { MADE_UP = "1" }',
        "[sides.old]",
        f'image = "{IMAGE}"',
        'env = { MADE_UP = "2" }',
        "baseline = true",
        "[launch]",
        'timeout = "2m"',
    ]


def _serving_lines() -> list[str]:
    args = ", ".join(json.dumps(word) for word in SERVER)
    lines = [
        "[workload]",
        'driver = "guidellm"',
        'argv = ["--data", "kind=synthetic_text,prompt_tokens=8,output_tokens=8"]',
        "levels = [1]",
        'level_duration = "5s"',
    ]
    for name, value in (("new", "1"), ("old", "2")):
        lines += [f"[sides.{name}]"] + (["baseline = true"] if name == "old" else [])
        lines += [
            f"[sides.{name}.serve]",
            f'image = "{IMAGE}"',
            f"args = [{args}]",
            "port = 8000",
            f'env = {{ MADE_UP = "{value}" }}',
            'ready = { http = "/health", timeout = "10m" }',
        ]
    return [*lines, "[launch]", 'timeout = "15m"']


def _config(folder: Path, *, serving: bool = False) -> Path:
    path = folder / "pairbench.toml"
    path.write_text(
        "\n".join(
            [
                "[run]",
                "rounds = 6",
                "warmups = 1",
                'same_vs_same = "off"',
                *(_serving_lines() if serving else _image_lines()),
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


def _exports(out: Path) -> list[Path]:
    artifacts = out / "artifacts"
    return sorted(artifacts.rglob(EXPORT_FILE)) if artifacts.is_dir() else []


def _interrupted_run(
    folder: Path, mask: int, ending: signal.Signals, *, serving: bool = False
) -> tuple[int, str, Path]:
    """Start a run, send ``ending`` to it once a launch has written its export, and wait."""
    out = folder / "run"
    source = str(Path(pairbench.__file__).resolve().parents[1])
    config = _config(folder, serving=serving)
    with (folder / "stderr.txt").open("w", encoding="utf-8") as err:
        run = subprocess.Popen(
            [sys.executable, "-m", "pairbench", "run", "--config", str(config), "--out", str(out)],
            cwd=folder,
            env={**os.environ, "PYTHONPATH": source},
            stdout=subprocess.DEVNULL,
            stderr=err,
            start_new_session=True,
            umask=mask,
        )
        try:
            deadline = time.monotonic() + EXPORT_WAIT_S
            while not _exports(out) and run.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            assert run.poll() is None, "the run ended before a launch wrote its export"
            assert _exports(out), "no launch wrote its export in time"
            os.killpg(run.pid, ending)
            code = run.wait(timeout=EXIT_WAIT_S)
        finally:
            if run.poll() is None:
                os.killpg(run.pid, signal.SIGKILL)
                run.wait(timeout=STEP_TIMEOUT_S)
    return code, (folder / "stderr.txt").read_text(encoding="utf-8"), out


ENDINGS = pytest.mark.parametrize(
    ("ending", "mask"),
    [
        (signal.SIGINT, 0o022),
        (signal.SIGINT, 0o002),
        (signal.SIGTERM, 0o022),
        (signal.SIGTERM, 0o002),
    ],
    ids=[
        "interrupt-umask-022",
        "interrupt-umask-002",
        "terminate-umask-022",
        "terminate-umask-002",
    ],
)


def _needs_the_image(needs: Any) -> None:
    needs.engine(ENGINE)
    found = subprocess.run(
        [ENGINE, "image", "inspect", IMAGE],
        capture_output=True,
        check=False,
        timeout=STEP_TIMEOUT_S,
    )
    if found.returncode != 0:
        pytest.skip(f"needs the image {IMAGE} on this machine; it is never pulled here")


def _left_to_the_caller_only(code: int, err: str, out: Path) -> None:
    assert code == EXIT_INTERRUPTED, err
    assert "E_INTERRUPTED: the run was interrupted\n" in err
    assert "files_not_handed_back" not in err
    exports = _exports(out)
    assert exports
    assert {path.stat().st_uid for path in exports} == {os.getuid()}
    assert {stat.S_IMODE(path.stat().st_mode) for path in exports} == {OWNER_ONLY}


@ENDINGS
def test_an_interrupted_launch_of_a_root_image_leaves_its_files_to_the_caller_only(
    needs: Any, tmp_path: Path, ending: signal.Signals, mask: int
) -> None:
    _needs_the_image(needs)

    code, err, out = _interrupted_run(tmp_path, mask, ending)

    _left_to_the_caller_only(code, err, out)


@ENDINGS
def test_an_interrupted_serving_launch_of_a_root_image_leaves_its_files_to_the_caller_only(
    needs: Any, tmp_path: Path, ending: signal.Signals, mask: int
) -> None:
    _needs_the_image(needs)

    code, err, out = _interrupted_run(tmp_path, mask, ending, serving=True)

    _left_to_the_caller_only(code, err, out)
