# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An interrupted launch of an image side whose files cannot be handed back names its folder.

A made-up engine answers every engine call and refuses the ``chown`` that
hands files back; the timed launch of the first round is interrupted, as
Ctrl-C does. Nothing real is started.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import GROUP_SIDE_KINDS, RefusedResults, delegate
from pairbench.errors import Refusal
from pairbench.model import STRICT, Experiment, GateSettings, RunSettings, Side
from pairbench.runner import run_experiment
from pairbench.sides import container
from pairbench.sides.base import Completed, HostProcesses, HostRun, ProcessUsage
from pairbench.sides.container import ImageKind

# The made-up world of conftest.py.
World = Any

SIDES = (
    Side.image("new", "registry.example/app:2"),
    Side.image("old", "registry.example/app:1"),
)
# What the made-up chown in the image exits with.
CHOWN_RC = 1
# The note of the interrupted launch, once the folder it names is known.
KEPT = (
    "files a container of side {side} wrote in artifacts/{folder} of the run folder still "
    "belong to the user its image runs as, so other users may be able to read them and you "
    f"may not be able to delete them: chown in the image exited with {CHOWN_RC}"
)


class Engine:
    """A made-up docker: every container runs, and chown in the image fails."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed:
        verb, rest = argv[1], tuple(argv[2:])
        if verb == "version":
            return Completed(0, "9.9.9\n")
        if verb == "info":
            return Completed(0, "{}")
        if verb == "image":
            digit = rest[-1][-1]
            details = {
                "Id": "sha256:" + digit * 64,
                "RepoDigests": [],
                "Os": "linux",
                "Architecture": "arm64",
                "Config": {"Entrypoint": None, "Cmd": ["./work"]},
            }
            return Completed(0, json.dumps(details))
        if verb == "run":
            entry = rest[rest.index("--entrypoint") + 1] if "--entrypoint" in rest else ""
            if entry == "chown":
                return Completed(CHOWN_RC, "", "chown: made-up failure")
            return Completed(0)
        if verb == "inspect":
            state = {
                "StartedAt": "2001-02-03T04:05:06.000000000Z",
                "FinishedAt": "2001-02-03T04:05:06.250000000Z",
                "ExitCode": 0,
            }
            return Completed(0, json.dumps(state))
        if verb in ("rm", "kill"):
            return Completed(0)
        raise AssertionError(f"unexpected engine call: {argv}")


class Containers(HostProcesses):
    """Timed launches of ``docker run``; the first launch of a round is interrupted."""

    def __init__(self) -> None:
        super().__init__()
        self.now = 1_000_000_000
        self.runs: list[HostRun] = []
        self.interrupted: Path | None = None

    def clock(self) -> int:
        return self.now

    def open_output(self, path: Path) -> IO[bytes]:
        return path.open("wb")

    def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
        self.runs.append(run)
        return 5000 + len(self.runs)

    def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
        self.now += 250_000_000
        folder = Path(self.runs[pid - 5001].stdout).parent
        if self.interrupted is None and folder.parent.name == "artifacts":
            self.interrupted = folder
            raise KeyboardInterrupt
        return 0, None

    def kill(self, pid: int) -> None:
        return None

    def pin(self, cpus: frozenset[int] | None) -> Any:
        return None

    def unpin(self, token: Any) -> None:
        return None


def _which(word: str, path: str | None = None) -> str | None:
    return "/usr/bin/docker" if word == "docker" else None


def test_an_interrupted_launch_whose_files_stay_with_another_user_is_named_on_stderr_and_results(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    containers = Containers()
    kind = ImageKind(runner=Engine(), host=containers, which=_which, environ={})
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "image"), kind)
    # The test cannot give files to another user: every launch folder looks like another's.
    monkeypatch.setattr(container, "foreign_entries", lambda folder, uid: [folder])
    experiment = Experiment(
        sides=SIDES,
        driver="wall",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )
    with pytest.raises(Refusal) as caught:
        run_experiment(experiment, out=tmp_path / "run", services=world.services())
    assert caught.value.code == "E_INTERRUPTED"
    folder = containers.interrupted
    assert folder is not None
    side = folder.name.split("-", 1)[1]
    message = KEPT.format(side=side, folder=folder.name)
    err = capsys.readouterr().err
    assert f"pairbench: note: files_not_handed_back: {message}\n" in err
    (capture,) = pairbench.load_capture(tmp_path / "run" / "capture.jsonl")
    kept = [note.message for note in capture.notes if note.code == "files_not_handed_back"]
    assert kept[-1] == message
    # The results document the command line writes for the interrupted run.
    refused: RefusedResults = delegate("refused")
    results = refused([capture], caught.value, rule=STRICT)
    assert message in [note.message for note in results.notes]
