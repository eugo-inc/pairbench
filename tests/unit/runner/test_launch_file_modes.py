# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a launch's own programs write into its folder is owner-only once the launch ends.

The made-up sides of conftest.py write their work file with the mode the umask
gives, as a benchmark tool writes the export a driver reads or a profiler its
report. Nothing real is started.
"""

from __future__ import annotations

import dataclasses
import os
import stat
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import (
    API_VERSION,
    GROUP_DRIVERS,
    DriverContext,
    InstrumentedCommand,
    Invocation,
    LaunchRequest,
    ProfiledCommand,
    Sample,
    Step,
)
from pairbench.errors import Refusal
from pairbench.model import EnergySettings, Experiment, GateSettings, RunSettings, Side
from pairbench.runner import open_explain, record_profiles, run_experiment

# The made-up world of conftest.py.
World = Any
WORK_FILE = "work.txt"
# A file every made-up launch writes into its folder before it runs, the
# launches that measure the tool's own cost included.
LEFT_FILE = "left.txt"
# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
CMD_SIDES = (
    Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
    Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
)
# Sides of a made-up kind, which pairbench does not know cannot serve.
FAKE_SIDES = (
    Side(name="new", kind="fake", spec={"argv": ["./new"]}),
    Side(name="old", kind="fake", spec={"argv": ["./old"]}),
)
FINGERPRINTS = {"new": "new".ljust(64, "0"), "old": "old".ljust(64, "0")}
# The export a serving load writes, as a client benchmark tool writes its own.
EXPORT_FILE = "export.json"
# A real load step: the shell writes the export into the folder it is given,
# with the mode the umask gives.
EXPORT_STEP = ("sh", "-c", f'printf "{{}}\\n" > "$1/{EXPORT_FILE}"', "sh")


class ReportProfiler:
    """A made-up GPU profiler whose report is the work file the made-up side writes."""

    name = "nsys"
    licence_note = "a made-up licence note"

    def find(self) -> str | None:
        return "/made-up/bin/nsys"

    def wrap(self, argv: Sequence[str], out: str) -> ProfiledCommand:
        return ProfiledCommand(
            argv=("nsys", "profile", "-o", f"{out}/report", *argv),
            outputs=(f"{out.rstrip('/')}/{WORK_FILE}",),
        )


class WorkInstrument:
    """A made-up instrument whose output is the work file the made-up side writes."""

    name = "counters"
    tool_files: tuple[Path, ...] = ()

    def wrap(self, argv: Sequence[str], *, out: str, tools: Any) -> InstrumentedCommand:
        return InstrumentedCommand(argv=("made-up-perf", *argv), outputs=(WORK_FILE,))


class ExportLoad:
    """A made-up client driver whose one load step writes an export, then reads it back."""

    name = "made-up-load"
    api_version = API_VERSION
    where = "client"
    clock_cases: tuple[str, ...] = ()

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation(steps=(Step(label="c1", argv=(*EXPORT_STEP, str(ctx.artifacts))),))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        if not (artifacts / EXPORT_FILE).is_file():
            raise Refusal("E_LAUNCH_FAILED", "the load wrote no export")
        sample = Sample(
            case="latency", metric="latency", unit="s", better="lower", kind="time", value=1.0
        )
        return [sample]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return ["latency"]


@pytest.fixture
def with_umask() -> Iterator[Callable[[int], int]]:
    """Set the process's umask for the test, and put the first one back after it."""
    first = os.umask(0o022)
    os.umask(first)
    yield os.umask
    os.umask(first)


def _experiment() -> Experiment:
    return Experiment(
        sides=CMD_SIDES,
        driver="fakedriver",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )


def _leave_a_file(request: LaunchRequest) -> None:
    (request.artifacts / LEFT_FILE).write_text("a made-up line\n", encoding="utf-8")


def _files(folder: Path) -> dict[str, int]:
    """The mode of each regular file under ``folder``, by its path there."""
    return {
        path.relative_to(folder).as_posix(): stat.S_IMODE(path.stat().st_mode)
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _interrupt_a_round(request: LaunchRequest) -> None:
    """Leave a file, then stop the first timed launch of a round, as Ctrl-C does."""
    _leave_a_file(request)
    if request.phase == "round":
        raise KeyboardInterrupt


@pytest.mark.parametrize("mask", [0o002, 0o022], ids=["umask-002", "umask-022"])
def test_every_file_the_launches_of_a_run_leave_is_owner_only_whatever_the_umask(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int], mask: int
) -> None:
    as_cmd.behaviour.during = _leave_a_file
    with_umask(mask)
    run_experiment(_experiment(), out=tmp_path / "run", services=as_cmd.services())
    found = _files(tmp_path / "run" / "artifacts")
    assert {Path(name).name for name in found} == {WORK_FILE, LEFT_FILE}
    assert any(name.startswith("cost/") for name in found)
    assert set(found.values()) == {OWNER_ONLY}


def test_the_exports_a_serving_load_writes_for_a_side_and_its_control_are_owner_only(
    world: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    registry.register(GROUP_DRIVERS, ExportLoad.name, ExportLoad())
    world.behaviour.serve = True
    with_umask(0o022)
    experiment = dataclasses.replace(_experiment(), sides=FAKE_SIDES, driver=ExportLoad.name)
    run_experiment(experiment, out=tmp_path / "run", services=world.services())
    found = _files(tmp_path / "run" / "artifacts")
    exports = {name for name in found if Path(name).name == EXPORT_FILE}
    assert {Path(name).parent.name for name in exports} >= {"run1", "run2"}
    assert {name: found[name] for name in exports} == dict.fromkeys(exports, OWNER_ONLY)
    assert set(found.values()) == {OWNER_ONLY}


def test_a_launch_that_is_interrupted_leaves_its_files_owner_only(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    as_cmd.behaviour.during = _interrupt_a_round
    with_umask(0o022)
    with pytest.raises(Refusal) as caught:
        run_experiment(_experiment(), out=tmp_path / "run", services=as_cmd.services())
    assert caught.value.code == "E_INTERRUPTED"
    last = as_cmd.requests[-1]
    assert (last.phase, last.round) == ("round", 1)
    assert _files(Path(last.artifacts)) == {LEFT_FILE: OWNER_ONLY}


def test_the_reports_a_profiler_leaves_are_owner_only(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    run_experiment(_experiment(), out=tmp_path / "run", services=as_cmd.services())
    with_umask(0o022)
    services = dataclasses.replace(as_cmd.services(), profiler=lambda tool: ReportProfiler())
    written = record_profiles(tmp_path / "run", tool="nsys", services=services)
    assert written == ("profiles/new/work.txt", "profiles/old/work.txt")
    assert _files(tmp_path / "run" / "profiles") == {
        "new/work.txt": OWNER_ONLY,
        "old/work.txt": OWNER_ONLY,
    }


def test_what_an_explain_launch_leaves_is_owner_only(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    with_umask(0o022)
    session = open_explain(
        _experiment(), run_id="run-a", fingerprints=FINGERPRINTS, services=as_cmd.services()
    )
    try:
        launched = session.launch("new", WorkInstrument(), tmp_path / "explain")
    finally:
        session.close()
    assert launched.rc == 0
    assert _files(tmp_path / "explain") == {WORK_FILE: OWNER_ONLY}


def test_an_explain_launch_whose_launches_folder_is_replaced_by_a_link_leaves_what_it_names_alone(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    """While an explain launch runs, its launches folder is moved and a link takes its place.

    The link names another folder of the caller's with a folder of the same
    name in it: its files keep their mode. The file the launch left in its
    own folder, wherever that folder went, ends owner-only.
    """
    launches = tmp_path / "run" / ".explain"
    folder = launches / "new-counters"
    folder.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / folder.name).mkdir(parents=True)
    with_umask(0o022)
    (elsewhere / folder.name / "notes.txt").write_text("a made-up note\n", encoding="utf-8")
    moved = tmp_path / "moved"

    def swap_in_a_link(request: LaunchRequest) -> None:
        _leave_a_file(request)
        launches.rename(moved)
        launches.symlink_to(elsewhere, target_is_directory=True)

    as_cmd.behaviour.during = swap_in_a_link
    session = open_explain(
        _experiment(), run_id="run-a", fingerprints=FINGERPRINTS, services=as_cmd.services()
    )
    try:
        launched = session.launch("new", WorkInstrument(), folder)
    finally:
        session.close()
    assert launched.rc == 0
    assert _files(elsewhere) == {
        "new-counters/notes.txt": 0o644,
        f"new-counters/{WORK_FILE}": 0o644,
    }
    assert _files(moved) == {f"new-counters/{LEFT_FILE}": OWNER_ONLY}


def _a_failing_stop(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("a made-up failure of a stop")


@pytest.mark.parametrize("stop", ["witness", "power"])
def test_a_timed_launch_whose_witness_or_power_reading_fails_to_stop_leaves_its_files_owner_only(
    as_cmd: World,
    tmp_path: Path,
    with_umask: Callable[[int], int],
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    as_cmd.behaviour.during = _leave_a_file
    with_umask(0o022)
    services = as_cmd.services()
    energy = EnergySettings(enabled=True)
    sampler = (
        services.checks.start_witness(None, None)
        if stop == "witness"
        else services.meter.start("all", energy)
    )
    monkeypatch.setattr(type(sampler), "stop", _a_failing_stop)
    experiment = dataclasses.replace(_experiment(), energy=energy)
    with pytest.raises(Refusal) as caught:
        run_experiment(experiment, out=tmp_path / "run", services=services)
    assert (caught.value.code, caught.value.message) == (
        "E_INTERNAL",
        "the run stopped on an unexpected error: a made-up failure of a stop",
    )
    last = as_cmd.requests[-1]
    assert _files(Path(last.artifacts)) == {LEFT_FILE: OWNER_ONLY, WORK_FILE: OWNER_ONLY}


def test_a_run_whose_launches_folder_is_replaced_by_a_link_leaves_what_it_names_alone(
    as_cmd: World, tmp_path: Path, with_umask: Callable[[int], int]
) -> None:
    """Another user who may write in the run folder puts a link in place of its launches."""
    elsewhere = tmp_path / "elsewhere"
    swapped: list[str] = []

    def swap_in_a_link(request: LaunchRequest) -> None:
        _leave_a_file(request)
        if request.phase == "round" and not swapped:
            launches = Path(request.artifacts).parent
            launches.rename(elsewhere)
            launches.symlink_to(elsewhere, target_is_directory=True)
            swapped.append(Path(request.artifacts).name)

    as_cmd.behaviour.during = swap_in_a_link
    with_umask(0o022)
    run_experiment(_experiment(), out=tmp_path / "run", services=as_cmd.services())
    assert len(swapped) == 1
    assert _files(elsewhere / swapped[0]) == {LEFT_FILE: 0o644, WORK_FILE: 0o644}
