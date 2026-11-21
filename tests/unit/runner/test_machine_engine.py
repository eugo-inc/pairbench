# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The container engine a capture records is the one its sides launched with."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pairbench.model import (
    CpuRecord,
    EngineInfo,
    Experiment,
    GateSettings,
    MachineRecord,
    RunSettings,
    Side,
)
from pairbench.runner import run_experiment

# The made-up world of conftest.py: what the made-up plug-ins saw and are told to do.
World = Any

SIDES = (
    Side(name="new", kind="fake", spec={"argv": ["./new"]}),
    Side(name="old", kind="fake", spec={"argv": ["./old"]}),
)
# The engine the machine's own look-up would pick when nothing is asked for.
FOUND = EngineInfo(name="docker", version="1.1.1")
# The engine the sides were told to use and launched with.
CHOSEN = EngineInfo(name="podman", version="2.2.2")


def _experiment() -> Experiment:
    return Experiment(
        sides=SIDES,
        driver="fakedriver",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
    )


@pytest.fixture
def machine_finds_docker(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Make the machine's own look-up name an engine other than the sides' one."""

    def machine_record(
        self: Any, *, gpus: str | None, node_type: str | None, environ: Mapping[str, str]
    ) -> MachineRecord:
        return MachineRecord(os="linux", arch="x86_64", cpu=CpuRecord(model="cpu-a"), engine=FOUND)

    facts = type(world.services().facts)
    monkeypatch.setattr(facts, "machine_record", machine_record)
    return world


def test_the_engine_the_sides_launched_with_is_recorded(
    machine_finds_docker: World, tmp_path: Path
) -> None:
    machine_finds_docker.behaviour.engine = CHOSEN
    capture = run_experiment(
        _experiment(), out=tmp_path / "run", services=machine_finds_docker.services()
    )
    assert capture.machine is not None
    assert capture.machine.engine == CHOSEN


# A second engine some side launches with.
OTHER = EngineInfo(name="docker", version="3.3.3")
NOTE_ENGINES_DIFFER = "engines_differ"
ENGINES_DIFFER = (
    "the sides launch with more than one container engine: new with podman 2.2.2, old with "
    "docker 3.3.3; the machine record names only the first, podman 2.2.2"
)


def _engine_notes(capture: Any) -> list[str]:
    return [n.message for n in capture.notes if n.code == NOTE_ENGINES_DIFFER]


def test_sides_that_launch_with_different_engines_are_each_named_in_a_note(
    machine_finds_docker: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine_finds_docker.behaviour.engines = {"new": CHOSEN, "old": OTHER}
    capture = run_experiment(
        _experiment(), out=tmp_path / "run", services=machine_finds_docker.services()
    )
    assert capture.machine is not None
    assert capture.machine.engine == CHOSEN
    assert _engine_notes(capture) == [ENGINES_DIFFER]
    printed = [line for line in capsys.readouterr().err.splitlines() if NOTE_ENGINES_DIFFER in line]
    assert printed == [f"pairbench: note: {NOTE_ENGINES_DIFFER}: {ENGINES_DIFFER}"]


@pytest.mark.parametrize(
    "engines",
    [{"new": CHOSEN, "old": CHOSEN}, {"new": None, "old": CHOSEN}],
    ids=["same engine", "one side without an engine"],
)
def test_sides_that_share_one_engine_give_no_note_of_engines(
    machine_finds_docker: World, tmp_path: Path, engines: dict[str, EngineInfo | None]
) -> None:
    machine_finds_docker.behaviour.engines = engines
    capture = run_experiment(
        _experiment(), out=tmp_path / "run", services=machine_finds_docker.services()
    )
    assert capture.machine is not None
    assert capture.machine.engine == CHOSEN
    assert _engine_notes(capture) == []


def test_without_a_side_that_uses_an_engine_the_machine_s_engine_is_recorded(
    machine_finds_docker: World, tmp_path: Path
) -> None:
    machine_finds_docker.behaviour.engine = None
    capture = run_experiment(
        _experiment(), out=tmp_path / "run", services=machine_finds_docker.services()
    )
    assert capture.machine is not None
    assert capture.machine.engine == FOUND
