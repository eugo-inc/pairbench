# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The positive control of an image whose user cannot write the files the host creates."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import pytest

import pairbench
from pairbench import registry
from pairbench.api import GROUP_SIDE_KINDS
from pairbench.errors import EXIT_LAUNCH, Refusal
from pairbench.model import (
    NOTE_CONTROL_CANNOT_REPEAT,
    NOTE_CONTROL_NOT_JUDGED,
    Experiment,
    GateSettings,
    RunSettings,
    Side,
)
from pairbench.runner import run_experiment
from pairbench.sides.base import Completed, HostProcesses, HostRun, ProcessUsage
from pairbench.sides.container import ImageKind

# The made-up world of conftest.py: what the made-up plug-ins saw and are told to do.
World = Any

SIDES = (
    Side.image("new", "registry.example/app:2"),
    Side.image("old", "registry.example/app:1"),
)
# Where the image side mounts the launch folder.
MOUNT = "/pairbench/artifacts"
# The exit code of dash when a redirection of a plain command cannot be opened.
REDIRECT_FAILED_RC = 2


def _image(ref: str) -> dict[str, Any]:
    digit = ref[-1]
    return {
        "Id": "sha256:" + digit * 64,
        "RepoDigests": [],
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Entrypoint": None, "Cmd": ["./work"], "User": "made-up-user"},
    }


def _shell_rc(argv: Sequence[str]) -> int:
    """What ``/bin/sh -c SCRIPT`` exits with when the image's user cannot write the mount.

    The first redirection into the mounted folder fails. A script that ends
    with ``|| exit N`` exits with ``N``; any other exits as dash does.
    """
    script = argv[-1]
    if f">{MOUNT}" not in script:
        return 0
    tail = script.rsplit("|| exit ", 1)
    return int(tail[1]) if len(tail) == 2 else REDIRECT_FAILED_RC


class Engine:
    """A made-up docker whose image runs as a user that may not write host-owned files.

    ``exits`` holds the exit code of each container that ran, by name, for
    the state the engine reports after it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.exits: dict[str, int] = {}

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed:
        argv = tuple(argv)
        self.calls.append(argv)
        verb, rest = argv[1], argv[2:]
        if verb == "version":
            return Completed(0, "9.9.9\n")
        if verb == "info":
            return Completed(0, "{}")
        if verb == "image":
            ref = rest[-1]
            for side in SIDES:
                details = _image(side.spec["image"])
                if ref in (side.spec["image"], details["Id"]):
                    return Completed(0, json.dumps(details))
            return Completed(1, "", f"Error: No such image: {ref}")
        if verb == "run":
            return Completed(_shell_rc(argv))
        if verb == "inspect":
            state = {
                "StartedAt": "2001-02-03T04:05:06.000000000Z",
                "FinishedAt": "2001-02-03T04:05:06.250000000Z",
                "ExitCode": self.exits.get(rest[-1], 0),
            }
            return Completed(0, json.dumps(state))
        if verb in ("rm", "kill"):
            return Completed(0)
        raise AssertionError(f"unexpected engine call: {argv}")


class Containers(HostProcesses):
    """Timed launches of ``docker run``: a made-up clock, and the shell's exit code."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        self.now = 1_000_000_000
        self.runs: list[HostRun] = []

    def clock(self) -> int:
        return self.now

    def open_output(self, path: Path) -> IO[bytes]:
        return path.open("wb")

    def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
        self.runs.append(run)
        return 5000 + len(self.runs)

    def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
        self.now += 250_000_000
        argv = self.runs[pid - 5001].argv
        rc = _shell_rc(argv)
        self.engine.exits[argv[argv.index("--name") + 1]] = rc
        return rc, None

    def kill(self, pid: int) -> None:
        return None

    def pin(self, cpus: frozenset[int] | None) -> Any:
        return None

    def unpin(self, token: Any) -> None:
        return None


def _which(word: str, path: str | None = None) -> str | None:
    return "/usr/bin/docker" if word == "docker" else None


@pytest.fixture
def images(world: World, monkeypatch: pytest.MonkeyPatch) -> tuple[Engine, Containers]:
    """Put the image kind, driven by the made-up engine, in place of the built-in one."""
    engine = Engine()
    containers = Containers(engine)
    kind = ImageKind(runner=engine, host=containers, which=_which, environ={})
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "image"), kind)
    return engine, containers


def test_the_measured_rounds_complete_when_the_image_user_cannot_write_the_mount(
    world: World, images: tuple[Engine, Containers], tmp_path: Path
) -> None:
    _engine, containers = images
    experiment = Experiment(
        sides=SIDES,
        driver="wall",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )
    capture = run_experiment(experiment, out=tmp_path / "run", services=world.services())
    assert capture.lineup is not None
    assert capture.lineup.control is None
    assert not any(launch.name.endswith("~twice") for launch in capture.launches)
    assert not any("/bin/sh" in run.argv for run in containers.runs)
    notes = [note for note in capture.notes if note.code == NOTE_CONTROL_CANNOT_REPEAT]
    assert [note.message for note in notes] == [
        "the positive control does not run: 'old' cannot run two commands in one start "
        "(the user the image of side old runs as cannot write the files pairbench creates in "
        "the folder it mounts, where the two runs keep their output; an image whose user is "
        "root or has your user id can)"
    ]
    rounds = {launch.round for launch in capture.launches if launch.phase == "round"}
    assert rounds == set(range(1, 9))


# What dash writes on standard error when a redirection may not be opened.
DENIED_LINE = f"sh: 1: cannot create {MOUNT}/run1/stdout.txt: Permission denied\n"
# The note of a control whose launch was refused its output file.
STOPPED = (
    "the positive control stops: its launch in round 1 failed because 'old' cannot run two "
    "commands in one start (the shell in a container of side old was refused a file where "
    "one of the two runs keeps its output (permission denied), though the check before the "
    "first round could write it); the measured rounds go on without it"
)


class WritableCheck(Engine):
    """The repeat check's container writes every file it is asked to."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed:
        if argv[1] == "run":
            self.calls.append(tuple(argv))
            return Completed(0)
        return super().__call__(argv, env=env, cwd=cwd, timeout_s=timeout_s)


class RefusedControl(Containers):
    """Every measured launch runs; the control's shell is refused the first run's output file."""

    def __init__(self, engine: Engine, line: str = DENIED_LINE) -> None:
        super().__init__(engine)
        self.line = line

    def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
        if "-c" in run.argv:
            stderr.write(self.line.encode())
        return super().spawn(run, stdout, stderr)

    def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
        self.now += 250_000_000
        argv = self.runs[pid - 5001].argv
        rc = REDIRECT_FAILED_RC if "-c" in argv else 0
        self.engine.exits[argv[argv.index("--name") + 1]] = rc
        return rc, None


def _refused_run(world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, line: str) -> Any:
    engine = WritableCheck()
    containers = RefusedControl(engine, line)
    kind = ImageKind(runner=engine, host=containers, which=_which, environ={})
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "image"), kind)
    experiment = Experiment(
        sides=SIDES,
        driver="wall",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )
    return run_experiment(experiment, out=tmp_path / "run", services=world.services())


def test_a_control_whose_shell_is_refused_its_output_file_stops_and_the_rounds_complete(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _refused_run(world, monkeypatch, tmp_path, DENIED_LINE)

    assert capture.complete
    assert capture.lineup is not None
    assert capture.lineup.control == "old~twice"
    control = [(x.round, x.rc) for x in capture.launches if x.name == "old~twice"]
    assert control == [(1, REDIRECT_FAILED_RC)]
    notes = [note.message for note in capture.notes if note.code == NOTE_CONTROL_CANNOT_REPEAT]
    assert notes == [STOPPED]
    for name in ("new", "new~same", "old", "old~same"):
        rounds = [x.round for x in capture.launches if x.phase == "round" and x.name == name]
        assert rounds == list(range(1, 9))
    results = pairbench.analyse(capture)
    assert results.controls.positive.status == "not_run"
    assert results.controls.positive.entry == "old~twice"
    assert [n.message for n in results.notes if n.code == NOTE_CONTROL_NOT_JUDGED] == [
        "the positive control was not judged: a launch of old~twice failed and the run went "
        "on without the control"
    ]
    assert [n.message for n in results.notes if n.code == NOTE_CONTROL_CANNOT_REPEAT] == [STOPPED]
    assert results.comparisons
    for comparison in results.comparisons:
        assert "positive_control_failed" not in (comparison.reason, *comparison.reasons)


def test_a_control_that_fails_for_another_reason_still_stops_the_run(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(Refusal) as refused:
        _refused_run(world, monkeypatch, tmp_path, "made-up-work: no such input\n")

    assert (refused.value.code, refused.value.exit_code) == ("E_LAUNCH_FAILED", EXIT_LAUNCH)
    assert refused.value.message == (
        f"the launch of 'old~twice' in round 1 exited with {REDIRECT_FAILED_RC}"
    )


# What a shell might write when refused a file without naming it: the image side cannot tell
# this from any other failure of the control's launch, so the run stops as a failed launch does.
DENIED_WITHOUT_PATH = "sh: 1: cannot create: Permission denied\n"


def test_a_control_refused_without_naming_its_file_stops_the_run_and_compare_names_the_launch(
    world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cli: Any
) -> None:
    with pytest.raises(Refusal) as refused:
        _refused_run(world, monkeypatch, tmp_path, DENIED_WITHOUT_PATH)

    assert (refused.value.code, refused.value.exit_code) == ("E_LAUNCH_FAILED", EXIT_LAUNCH)
    assert refused.value.message == (
        f"the launch of 'old~twice' in round 1 exited with {REDIRECT_FAILED_RC}"
    )
    capture = tmp_path / "run" / "capture.jsonl"
    capture_id = pairbench.load_capture(capture)[0].header.capture_id
    expected = (
        "the positive control was not judged: the launch of old~twice in round 1 of the "
        f"capture {capture_id} exited with {REDIRECT_FAILED_RC} and stopped the run, so no "
        "primary case has the 6 paired rounds of the control and the baseline that judging "
        "it needs"
    )
    results = pairbench.analyse(pairbench.load_capture(capture), allow_incomplete=True)
    assert results.controls.positive.status == "not_run"
    assert results.controls.positive.entry == "old~twice"
    assert [n.message for n in results.notes if n.code == NOTE_CONTROL_NOT_JUDGED] == [expected]

    compared = cli("compare", capture, "--allow-incomplete", "--out", tmp_path / "again")
    assert compared.code == 0, compared.err
    assert f"pairbench: note: {NOTE_CONTROL_NOT_JUDGED}: {expected}\n" in compared.err
    written = json.loads((tmp_path / "again" / "results.json").read_text(encoding="utf-8"))
    assert written["controls"]["positive"]["status"] == "not_run"
    assert {"code": NOTE_CONTROL_NOT_JUDGED, "message": expected} in written["notes"]
