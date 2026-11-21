# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Profiles and explain launches on host sides and on image sides with their own command line."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import (
    GROUP_SIDE_KINDS,
    InstrumentedCommand,
    LaunchOutcome,
    LaunchRequest,
    ProfiledCommand,
)
from pairbench.errors import Refusal
from pairbench.model import (
    Experiment,
    GateSettings,
    RunSettings,
    Side,
)
from pairbench.runner import open_explain, record_profiles, run_experiment

# The made-up world of conftest.py: what the made-up plug-ins saw and are told to do.
World = Any
WORK_FILE = "work.txt"
# Where a made-up container sees the launch folder.
INSIDE = "/pairbench/artifacts"
# The entrypoint and default command of the made-up image.
ENTRYPOINT = ("/made-up/entry",)
DEFAULT_COMMAND = ("--serve-default",)

CMD_SIDES = (
    Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
    Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
)
# Image sides that run the default command of their image.
IMAGE_SIDES = (
    Side(name="new", kind="image", spec={"image": "registry.example/app:2"}),
    Side(name="old", kind="image", spec={"image": "registry.example/app:1"}),
)
FINGERPRINTS = {"new": "new".ljust(64, "0"), "old": "old".ljust(64, "0")}


class OutProfiler:
    """A made-up GPU profiler that names its report under the folder it is given."""

    name = "nsys"
    licence_note = "a made-up licence note"

    def find(self) -> str | None:
        return "/made-up/bin/nsys"

    def wrap(self, argv: Sequence[str], out: str) -> ProfiledCommand:
        return ProfiledCommand(
            argv=("nsys", "profile", "-o", f"{out}/report", *argv),
            outputs=(f"{out.rstrip('/')}/{WORK_FILE}",),
        )


class ImageOnlyProfiler(OutProfiler):
    """The made-up profiler, held by the image but not installed on this machine."""

    def find(self) -> str | None:
        return None


class OutInstrument:
    """A made-up instrument that records what it was put in front of."""

    name = "counters"
    tool_files: tuple[Path, ...] = ()

    def __init__(self) -> None:
        self.wrapped: list[tuple[str, ...]] = []

    def wrap(self, argv: Sequence[str], *, out: str, tools: Any) -> InstrumentedCommand:
        self.wrapped.append(tuple(argv))
        return InstrumentedCommand(argv=("made-up-perf", *argv), outputs=(WORK_FILE,))


def _experiment(sides: tuple[Side, ...]) -> Experiment:
    return Experiment(
        sides=sides,
        driver="fakedriver",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )


def _services(world: World) -> Any:
    return dataclasses.replace(world.services(), profiler=lambda tool: OutProfiler())


@pytest.fixture
def as_image(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Put the made-up side kind in place of the built-in ``image`` kind."""
    kind = type(registry.side_kind("fake"))(world, "image")
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "image"), kind)
    return world


def _like_a_container(
    world: World, monkeypatch: pytest.MonkeyPatch, *, rc: int = 0
) -> list[tuple[str, ...]]:
    """Make the made-up sides behave as a container: run what ``wrap_server`` gives back.

    The made-up side sees its folder at ``INSIDE``, runs the image's whole
    command line under what the wrap returns, and leaves its work file in
    the folder on the host. It returns the command lines it ran.
    """
    resolved = type(world.resolved[0])
    launch = resolved.launch
    ran: list[tuple[str, ...]] = []

    def contained(self: Any, request: LaunchRequest) -> LaunchOutcome:
        if request.wrap_server is not None:
            whole = (*ENTRYPOINT, *(request.argv or DEFAULT_COMMAND))
            ran.append(tuple(request.wrap_server(whole).argv))
        if rc != 0:
            world.requests.append(request)
            return LaunchOutcome(rc=rc, timing={"run_s": 0.25, "launch_s": 0.25})
        return launch(self, request)

    monkeypatch.setattr(resolved, "artifacts_in_side", lambda self, host: INSIDE)
    monkeypatch.setattr(resolved, "launch", contained)
    return ran


def test_a_profile_of_host_sides_lists_the_reports_named_under_their_folder(
    as_cmd: World, tmp_path: Path
) -> None:
    run_experiment(_experiment(CMD_SIDES), out=tmp_path / "run", services=as_cmd.services())
    written = record_profiles(tmp_path / "run", tool="nsys", services=_services(as_cmd))
    assert written == ("profiles/new/work.txt", "profiles/old/work.txt")
    assert (tmp_path / "run" / "profiles" / "new" / WORK_FILE).is_file()


def test_a_profile_of_an_image_side_runs_its_whole_command_line_under_the_profiler(
    as_image: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_experiment(_experiment(IMAGE_SIDES), out=tmp_path / "run", services=as_image.services())
    ran = _like_a_container(as_image, monkeypatch)
    written = record_profiles(tmp_path / "run", tool="nsys", services=_services(as_image))
    assert written == ("profiles/new/work.txt", "profiles/old/work.txt")
    assert (
        ran
        == [
            ("nsys", "profile", "-o", f"{INSIDE}/report", *ENTRYPOINT, *DEFAULT_COMMAND),
        ]
        * 2
    )
    assert as_image.requests[-1].phase == "profile"


def test_an_image_side_is_profiled_with_a_profiler_this_machine_does_not_hold(
    as_image: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_experiment(_experiment(IMAGE_SIDES), out=tmp_path / "run", services=as_image.services())
    _like_a_container(as_image, monkeypatch)
    services = dataclasses.replace(as_image.services(), profiler=lambda tool: ImageOnlyProfiler())
    written = record_profiles(tmp_path / "run", tool="nsys", services=services)
    assert written == ("profiles/new/work.txt", "profiles/old/work.txt")


def test_a_host_side_needs_the_profiler_on_this_machine(as_cmd: World, tmp_path: Path) -> None:
    run_experiment(_experiment(CMD_SIDES), out=tmp_path / "run", services=as_cmd.services())
    services = dataclasses.replace(as_cmd.services(), profiler=lambda tool: ImageOnlyProfiler())
    with pytest.raises(Refusal) as caught:
        record_profiles(tmp_path / "run", tool="nsys", services=services)
    assert (caught.value.code, caught.value.exit_code) == ("E_PROFILER_MISSING", 3)
    assert caught.value.message == "the profiler nsys is not installed"


def test_a_profiler_that_is_not_in_the_image_is_refused_by_name(
    as_image: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_experiment(_experiment(IMAGE_SIDES), out=tmp_path / "run", services=as_image.services())
    _like_a_container(as_image, monkeypatch, rc=127)
    with pytest.raises(Refusal) as caught:
        record_profiles(tmp_path / "run", tool="nsys", services=_services(as_image))
    assert (caught.value.code, caught.value.exit_code) == ("E_PROFILER_MISSING", 3)
    assert caught.value.message == (
        "nsys is not in the image of side 'new': the profiler runs inside the container, "
        "so the image must hold it on its PATH"
    )


def test_a_command_not_found_under_a_profiler_that_wrote_its_report_is_a_failed_launch(
    as_image: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_experiment(_experiment(IMAGE_SIDES), out=tmp_path / "run", services=as_image.services())
    _like_a_container(as_image, monkeypatch, rc=127)
    for side in ("new", "old"):
        (tmp_path / "run" / "profiles" / side).mkdir(parents=True)
        (tmp_path / "run" / "profiles" / side / WORK_FILE).write_text("made-up report\n")
    with pytest.raises(Refusal) as caught:
        record_profiles(tmp_path / "run", tool="nsys", services=_services(as_image))
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == "the profiled launch of 'new' exited with 127"


def test_an_explain_launch_of_an_image_side_wraps_its_whole_command_line(
    as_image: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_experiment(_experiment(IMAGE_SIDES), out=tmp_path / "run", services=as_image.services())
    ran = _like_a_container(as_image, monkeypatch)
    instrument = OutInstrument()
    session = open_explain(
        _experiment(IMAGE_SIDES),
        run_id="run-a",
        fingerprints=FINGERPRINTS,
        services=as_image.services(),
    )
    try:
        launched = session.launch("new", instrument, tmp_path / "explain")
    finally:
        session.close()
    assert instrument.wrapped == [(*ENTRYPOINT, *DEFAULT_COMMAND)]
    assert ran == [("made-up-perf", *ENTRYPOINT, *DEFAULT_COMMAND)]
    assert launched.rc == 0
    assert launched.outputs == (tmp_path / "explain" / WORK_FILE,)
