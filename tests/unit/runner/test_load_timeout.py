# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The load steps of a serving launch end at the end of the launch timeout."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from pairbench.api import DriverContext, Endpoint, Invocation, Step
from pairbench.model import LaunchSettings, Side
from pairbench.runner import _Load

# A load step that starts a process of its own, writes both ids, then sleeps.
HANGING_STEP = r"""
import json, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump({"step": __import__("os").getpid(), "child": child.pid}, out)
time.sleep(60)
"""
# A load step that only leaves a mark that it ran.
MARKING_STEP = "import pathlib, sys; pathlib.Path(sys.argv[1]).touch()"
# A load step that starts a process of its own, writes both ids and exits with 0 at once.
LEAVING_STEP = r"""
import json, os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump({"step": os.getpid(), "child": child.pid}, out)
"""


class TwoSteps:
    """A made-up client driver: a step that hangs, then a step that marks that it ran."""

    name = "made-up-load"
    where = "client"

    def __init__(self, record: Path, mark: Path) -> None:
        self.record = record
        self.mark = mark

    def prepare(self, ctx: DriverContext, argv: Sequence[str]) -> Invocation:
        return Invocation(
            steps=(
                Step(label="c1", argv=(sys.executable, "-c", HANGING_STEP, str(self.record))),
                Step(label="c8", argv=(sys.executable, "-c", MARKING_STEP, str(self.mark))),
            )
        )


def _context(folder: Path) -> DriverContext:
    return DriverContext(
        run_id="run-a",
        seq=3,
        phase="round",
        round=1,
        name="new",
        side=Side(name="new", kind="serve", spec={}),
        artifacts=folder,
        artifacts_in_side=str(folder),
        note=lambda code, message: None,
        launch=LaunchSettings(timeout_s=1.0),
    )


def _gone(pid: int, seconds: float = 5.0) -> bool:
    """Say whether a process has ended (or only waits to be collected) within ``seconds``."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return True
        if text[text.rfind(")") + 2] in "ZX":
            return True
        time.sleep(0.05)
    return False


def _ids(record: Path) -> dict[str, int]:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            return dict(json.loads(record.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            time.sleep(0.05)
    raise AssertionError("the load step wrote no process ids")


def test_a_load_step_that_runs_past_the_deadline_is_stopped_with_what_it_started(
    tmp_path: Path,
) -> None:
    record, mark = tmp_path / "ids.json", tmp_path / "second-step-ran"
    load = _Load(TwoSteps(record, mark), [_context(tmp_path)], [])  # type: ignore[arg-type]
    began = time.monotonic()
    load(Endpoint(base_url="http://127.0.0.1:1", deadline=began + 1.0))
    assert time.monotonic() - began < 10.0
    assert load.failed == "ran into its timeout during the load"
    assert load.timed_out
    assert [window.label for window in load.windows] == ["c1"]
    assert not mark.exists()
    ids = _ids(record)
    assert _gone(ids["step"])
    assert _gone(ids["child"])


def test_a_load_without_a_deadline_runs_every_step(tmp_path: Path) -> None:
    mark = tmp_path / "ran"

    class OneStep(TwoSteps):
        def prepare(self, ctx: DriverContext, argv: Sequence[str]) -> Invocation:
            return Invocation(
                steps=(Step(label="c1", argv=(sys.executable, "-c", MARKING_STEP, str(mark))),)
            )

    load = _Load(OneStep(mark, mark), [_context(tmp_path)], [])  # type: ignore[arg-type]
    load(Endpoint(base_url="http://127.0.0.1:1"))
    assert (load.failed, load.timed_out) == (None, False)
    assert mark.exists()


def test_what_a_load_step_left_running_when_it_exited_is_stopped(tmp_path: Path) -> None:
    record = tmp_path / "ids.json"

    class LeavingStep(TwoSteps):
        def prepare(self, ctx: DriverContext, argv: Sequence[str]) -> Invocation:
            return Invocation(
                steps=(Step(label="c1", argv=(sys.executable, "-c", LEAVING_STEP, str(record))),)
            )

    load = _Load(LeavingStep(record, record), [_context(tmp_path)], [])  # type: ignore[arg-type]
    load(Endpoint(base_url="http://127.0.0.1:1"))
    ids = _ids(record)
    try:
        assert (load.failed, load.timed_out) == (None, False)
        assert _gone(ids["child"])
    finally:
        with contextlib.suppress(OSError):
            os.kill(ids["child"], signal.SIGKILL)
