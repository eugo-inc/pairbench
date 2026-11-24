# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The runner, with made-up sides, a made-up driver and made-up machine checks."""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api, registry
from pairbench.api import (
    API_VERSION,
    DEFAULT_SEED,
    ENV_PAD_VARIABLE,
    GROUP_DRIVERS,
    GROUP_GATES,
    GROUP_SIDE_KINDS,
    WORK_FACTOR_VARIABLE,
    CpuFacts,
    DriverContext,
    GateContext,
    InstrumentedCommand,
    Invocation,
    LaunchRequest,
    Sample,
    SideContext,
    Step,
    ToolCpus,
    ToolVersion,
)
from pairbench.capture.reader import JsonlReader
from pairbench.errors import (
    EXIT_ANALYSIS,
    EXIT_INTERRUPTED,
    EXIT_LAUNCH,
    EXIT_MACHINE,
    EXIT_SIDE,
    EXIT_USAGE,
    Refusal,
)
from pairbench.gates.base import machine_checks
from pairbench.gates.platform import Root
from pairbench.model import (
    FILE_CAPTURE,
    FILE_PLAN,
    NOTE_CONTROL_CANNOT_REPEAT,
    NOTE_CONTROL_CASE_MISSING,
    NOTE_CONTROL_NOT_JUDGED,
    NOTE_DRIVERS_DIFFER,
    NOTE_LAUNCH_COST_NOT_MEASURED,
    NOTE_NEW_CASE,
    NOTE_RESOURCE_FIGURE_MISSING,
    NOTE_TOOL_ON_PINNED_CPUS,
    NOTE_TOOL_VERSION_UNTESTED,
    NOTE_UNBALANCED,
    NOTE_UNDERPOWERED,
    NOTE_UNPINNED_MIXED_CORES,
    NOTE_WITNESS_FAILED,
    NOTE_WITNESS_UNDECIDED,
    Capture,
    CaseSettings,
    ControlSettings,
    DriverInfo,
    EnergySettings,
    Experiment,
    GateRecord,
    GateSettings,
    LaunchCostSettings,
    LaunchSettings,
    LoadSettings,
    RunSettings,
    Side,
    Witness,
    env_pad_length,
)
from pairbench.plan import build_plan
from pairbench.runner import look_up_sides, open_explain, record_profiles, run_experiment

# The made-up world of conftest.py: what the made-up plug-ins saw and are told to do.
World = Any
WORK_FILE = "work.txt"

SIDES = (
    Side(name="new", kind="fake", spec={"argv": ["./new"]}),
    Side(name="old", kind="fake", spec={"argv": ["./old"]}),
)
QUICK_LAUNCHES = 8 * 5 + 2
CMD_SIDES = (
    Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
    Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
)
MADE_UP_TRUE = "/made-up/bin/true"
ENERGY_ON = EnergySettings(enabled=True)
ENTRIES = ("new", "new~same", "old", "old~same", "old~twice")


def _experiment(
    *,
    sides: tuple[Side, ...] = SIDES,
    run: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
    cost: int = 0,
    **more: Any,
) -> Experiment:
    return Experiment(
        sides=sides,
        driver="fakedriver",
        run=RunSettings(**(run if run is not None else {"quick": True})),
        gates=GateSettings(**{"mode": "off", **(gates or {})}),
        launch_cost=LaunchCostSettings(launches=cost),
        **more,
    )


def _run(world: World, tmp_path: Path, experiment: Experiment | None = None) -> Capture:
    return run_experiment(
        experiment or _experiment(), out=tmp_path / "run", services=world.services()
    )


def _refused(world: World, tmp_path: Path, experiment: Experiment | None = None) -> Refusal:
    with pytest.raises(Refusal) as caught:
        _run(world, tmp_path, experiment)
    return caught.value


def _read(tmp_path: Path) -> Capture:
    (capture,) = JsonlReader().read(tmp_path / "run" / FILE_CAPTURE)
    return capture


def _records(tmp_path: Path) -> list[dict[str, Any]]:
    text = (tmp_path / "run" / FILE_CAPTURE).read_text()
    return [json.loads(line) for line in text.splitlines()]


def _rounds(capture: Capture) -> list[tuple[int, int | None, str]]:
    return [(x.round, x.pos, x.name) for x in capture.launches if x.phase == "round"]


def _values(capture: Capture, name: str, case: str) -> list[float]:
    return [o.value for o in capture.observations if o.name == name and o.case == case]


def _codes(capture: Capture) -> list[str]:
    return [n.code for n in capture.notes]


def _round_values(capture: Capture, name: str, case: str) -> list[float]:
    return [
        o.value for o in capture.observations if o.name == name and o.case == case and o.round >= 1
    ]


# ---------------------------------------------------------------------------
# The rows that run
# ---------------------------------------------------------------------------


def test_the_positions_of_the_capture_are_the_plan(world: World, tmp_path: Path) -> None:
    experiment = _experiment()
    capture = _run(world, tmp_path, experiment)
    plan = build_plan(experiment)
    assert _rounds(capture) == [(r.round, r.pos, r.name) for r in plan.rows]
    assert (tmp_path / "run" / FILE_PLAN).read_text() == plan.to_tsv()
    assert capture.complete
    assert capture.end is not None and capture.end.rounds_completed == 8
    assert len(world.requests) == QUICK_LAUNCHES
    assert NOTE_UNBALANCED not in _codes(capture)
    assert NOTE_UNDERPOWERED not in _codes(capture)


def test_rounds_run_exactly_that_are_not_balanced_are_stamped(world: World, tmp_path: Path) -> None:
    experiment = _experiment(run={"rounds": 12, "rounds_exact": True})
    capture = _run(world, tmp_path, experiment)
    assert capture.end is not None and capture.end.rounds_completed == 12
    assert _codes(capture).count(NOTE_UNBALANCED) == 1
    assert NOTE_UNDERPOWERED not in _codes(capture)


def test_an_underpowered_run_that_is_allowed_is_stamped(world: World, tmp_path: Path) -> None:
    experiment = _experiment(run={"rounds": 4, "rounds_exact": True, "allow_underpowered": True})
    capture = _run(world, tmp_path, experiment)
    assert capture.end is not None and capture.end.rounds_completed == 4
    stamped = [n.message for n in capture.notes if n.code == NOTE_UNDERPOWERED]
    assert stamped == [
        "4 rounds are planned and a verdict needs at least 6; every verdict is "
        "NO VERDICT (too_few_rounds)"
    ]


def test_the_capture_holds_header_machine_sides_lineup_in_order(
    world: World, tmp_path: Path
) -> None:
    capture = _run(world, tmp_path)
    kinds = [r["t"] for r in _records(tmp_path)]
    assert kinds[:7] == ["header", "machine", "side", "side", "side", "side", "launch"]
    assert kinds.index("lineup") < kinds.index("launch", kinds.index("lineup"))
    assert kinds[-1] == "end"
    assert [s.name for s in capture.sides] == ["new", "new~same", "old", "old~same", "old~twice"]
    assert capture.header.seeds == {"driver": 1234}
    assert capture.lineup is not None
    assert capture.lineup.control == "old~twice"
    assert capture.lineup.names == ("new", "new~same", "old", "old~same")


def test_warm_ups_run_once_per_side_before_round_one(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path)
    warm = [(x.round, x.pos, x.name) for x in capture.launches if x.phase == "warmup"]
    assert warm == [(0, None, "new"), (0, None, "old")]
    assert [r.phase for r in world.requests[:2]] == ["warmup", "warmup"]


def test_every_measured_launch_is_watched(world: World, tmp_path: Path) -> None:
    _run(world, tmp_path)
    assert world.witness_starts == QUICK_LAUNCHES
    assert world.witness_stops == [0.75] * QUICK_LAUNCHES


def test_only_the_launches_of_the_rounds_decide_what_is_set_aside(
    world: World, tmp_path: Path
) -> None:
    _run(world, tmp_path)
    seen = [(w.round, w.name) for w in world.set_aside_seen]
    assert len(seen) == 8 * 5
    for round_ in range(1, 9):
        assert sorted(name for r, name in seen if r == round_) == sorted(ENTRIES)


def test_a_failed_witness_probe_gives_a_loud_note_for_each_measured_launch(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.witness = Witness(busy_cores=0.0, failed=("gpu_other_processes",))
    capture = _run(world, tmp_path)
    measured = [x for x in capture.launches if x.phase == "round"]
    failed = [n for n in capture.notes if n.code == NOTE_WITNESS_FAILED]
    assert len(failed) == len(measured) == 8 * 5
    first = measured[0]
    assert failed[0].message == (
        "the other compute processes on the selected GPUs could not be read during the launch of "
        f"{first.name} in round {first.round}; the round is marked as disturbed"
    )
    assert capsys.readouterr().err.count("witness_probe_failed") == 8 * 5


def test_an_undecided_launch_gives_one_loud_note_per_run(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.witness = Witness(busy_cores=3.5, includes_launch=("busy_cores",))
    capture = _run(world, tmp_path)
    undecided = [n for n in capture.notes if n.code == NOTE_WITNESS_UNDECIDED]
    assert len(undecided) == 1
    first = next(x for x in capture.launches if x.phase == "round")
    assert undecided[0].message == (
        f"the busy-core witness could not judge the launch of {first.name} in round "
        f"{first.round}: the side reports no CPU time of its own, and the busy cores counted "
        "with its own load in were above the threshold; the launch does not mark its round "
        "as disturbed, and later launches like it are counted in the results; pin a CPU set "
        "with --cpus for the full witness"
    )
    assert "round is kept" not in undecided[0].message
    assert capsys.readouterr().err.count("witness_undecided") == 1
    assert [n.code for n in capture.notes].count(NOTE_WITNESS_FAILED) == 0


def test_an_interrupted_launch_stops_its_witness(world: World, tmp_path: Path) -> None:
    world.behaviour.interrupt_at = 5
    _refused(world, tmp_path)
    assert world.witness_starts == 5
    assert world.witness_stops == [0.75, 0.75, 0.75, 0.75, None]


# ---------------------------------------------------------------------------
# The positive control
# ---------------------------------------------------------------------------


def test_the_control_holds_two_runs_in_one_launch(world: World, tmp_path: Path) -> None:
    world.behaviour.seconds = {"new": 2.0, "old": 3.0}
    world.behaviour.second_seconds = 5.0
    capture = _run(world, tmp_path)
    assert _values(capture, "old~twice", "wall") == [8.0] * 8
    assert _values(capture, "old~twice", "work") == [8.0] * 8
    control = [x for x in capture.launches if x.name == "old~twice"]
    assert {(x.pos, x.runs) for x in control} == {(5, 2)}
    seconds = [r for r in world.requests if r.name == "old~twice"]
    assert all(r.second is not None for r in seconds)
    assert not any(o.case.startswith("res/") for o in capture.observations if o.name == "old~twice")


def _startup(request: LaunchRequest) -> tuple[Sample, ...]:
    return (
        Sample(
            case="startup/ready_s",
            metric="ready_s",
            unit="s",
            better="lower",
            kind="time",
            value=0.5,
        ),
        Sample(
            case="startup/ready_at",
            metric="ready_at",
            unit="s",
            better="none",
            kind="other",
            value=9.0,
        ),
    )


def test_the_control_keeps_the_cases_its_side_measured_itself(world: World, tmp_path: Path) -> None:
    world.behaviour.side_samples = _startup
    capture = _run(world, tmp_path)
    assert _round_values(capture, "old~twice", "startup/ready_s") == [0.5] * 8
    assert _round_values(capture, "old~twice", "startup/ready_at") == []
    assert _round_values(capture, "old", "startup/ready_s") == [0.5] * 8
    assert _round_values(capture, "old", "startup/ready_at") == [9.0] * 8
    assert not any(o.case.startswith("res/") for o in capture.observations if o.name == "old~twice")


def test_a_side_that_cannot_repeat_runs_without_the_control(world: World, tmp_path: Path) -> None:
    world.behaviour.cannot_repeat = "the image has no shell"
    capture = _run(world, tmp_path)
    assert capture.lineup is not None
    assert capture.lineup.control is None
    assert "old~twice" not in {s.name for s in capture.sides}
    assert not any(x.name == "old~twice" for x in capture.launches)
    assert not any(r.second is not None for r in world.requests)
    assert NOTE_CONTROL_CANNOT_REPEAT in _codes(capture)
    assert len(world.requests) == 8 * 4 + 2


def _control_fails_at_the_last_launch(world: World, tmp_path: Path, cause: str | None) -> Path:
    """Run once, then again with the control's launch in the last round failing.

    The made-up control reads as twice its side. In the made-up schedule the
    control is the last launch of each round, so the failing launch is the
    last launch of the run.
    """
    world.behaviour.second_seconds = world.behaviour.seconds["old"]
    _run(world, tmp_path / "first")
    launches = len(world.requests)
    assert (world.requests[-1].name, world.requests[-1].round) == ("old~twice", 8)
    world.behaviour.fail_at = 2 * launches
    world.behaviour.fail_rc = 2
    world.behaviour.fail_cannot_repeat = cause
    return tmp_path / "second"


def test_a_run_stopped_by_a_failed_control_launch_keeps_its_control_judged_on_the_rounds_kept(
    world: World, tmp_path: Path
) -> None:
    out = _control_fails_at_the_last_launch(world, tmp_path, None)
    refused = _refused(world, out)
    assert (refused.code, refused.exit_code) == ("E_LAUNCH_FAILED", EXIT_LAUNCH)
    results = pairbench.analyse(_read(out), allow_incomplete=True)
    control = results.controls.positive
    assert (control.status, [(c.case, c.n_rounds) for c in control.cases]) == ("ok", [("work", 7)])
    assert NOTE_CONTROL_NOT_JUDGED not in {n.code for n in results.notes}


def test_a_control_launch_that_times_out_in_round_1_is_named_where_the_control_is_not_judged(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.second_seconds = world.behaviour.seconds["old"]
    _run(world, tmp_path / "first")
    launches = len(world.requests)
    first_control = next(
        i for i, r in enumerate(world.requests, 1) if (r.name, r.round) == ("old~twice", 1)
    )
    world.behaviour.fail_at = launches + first_control
    world.behaviour.timed_out = True
    refused = _refused(world, tmp_path / "second")
    assert (refused.code, refused.exit_code) == ("E_LAUNCH_FAILED", EXIT_LAUNCH)
    assert refused.message == "the launch of 'old~twice' in round 1 ran into its timeout"
    capture = _read(tmp_path / "second")
    results = pairbench.analyse(capture, allow_incomplete=True)
    assert results.controls.positive.status == "not_run"
    assert [n.message for n in results.notes if n.code == NOTE_CONTROL_NOT_JUDGED] == [
        "the positive control was not judged: the launch of old~twice in round 1 of the capture "
        f"{capture.header.capture_id} ran into its timeout and stopped the run, so no primary "
        "case has the 6 paired rounds of the control and the baseline that judging it needs"
    ]


def test_a_launch_of_another_entry_that_stops_the_run_is_not_named_as_the_control(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.second_seconds = world.behaviour.seconds["old"]
    _run(world, tmp_path / "first")
    launches = len(world.requests)
    failing = next(
        i
        for i, r in enumerate(world.requests, 1)
        if r.round == 2 and r.name != "old~twice" and r.phase != "warmup"
    )
    name = world.requests[failing - 1].name
    world.behaviour.fail_at = launches + failing
    world.behaviour.fail_rc = 2
    refused = _refused(world, tmp_path / "second")
    assert (refused.code, refused.exit_code) == ("E_LAUNCH_FAILED", EXIT_LAUNCH)
    assert refused.message == f"the launch of '{name}' in round 2 exited with 2"
    results = pairbench.analyse(_read(tmp_path / "second"), allow_incomplete=True)
    assert results.controls.positive.status == "not_run"
    assert [n.message for n in results.notes if n.code == NOTE_CONTROL_NOT_JUDGED] == [
        "the positive control was not judged: no primary case has the 6 paired rounds of the "
        "control and the baseline that judging it needs"
    ]


def test_a_control_that_cannot_repeat_at_the_last_launch_of_a_run_is_not_judged(
    world: World, tmp_path: Path
) -> None:
    out = _control_fails_at_the_last_launch(world, tmp_path, "the shell was refused")
    capture = _run(world, out)
    assert capture.complete
    results = pairbench.analyse(capture)
    assert (results.controls.positive.status, results.controls.positive.cases) == ("not_run", ())
    assert [(n.code, n.message) for n in results.notes if "control" in n.code] == [
        (
            NOTE_CONTROL_CANNOT_REPEAT,
            "the positive control stops: its launch in round 8 failed because 'old' cannot run "
            "two commands in one start (the shell was refused); the measured rounds go on "
            "without it",
        ),
        (
            NOTE_CONTROL_NOT_JUDGED,
            "the positive control was not judged: a launch of old~twice failed and the run "
            "went on without the control",
        ),
    ]


def test_a_failed_control_launch_that_later_launches_of_the_control_follow_is_not_a_stop(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.second_seconds = world.behaviour.seconds["old"]
    capture = _run(world, tmp_path)
    launches = tuple(
        dataclasses.replace(x, rc=2)
        if (x.name, x.phase, x.round) == ("old~twice", "round", 3)
        else x
        for x in capture.launches
    )
    results = pairbench.analyse(dataclasses.replace(capture, launches=launches))
    control = results.controls.positive
    assert (control.status, [(c.case, c.n_rounds) for c in control.cases]) == ("ok", [("work", 8)])
    assert NOTE_CONTROL_NOT_JUDGED not in {n.code for n in results.notes}


def test_each_side_is_told_where_the_run_makes_the_folders_of_its_launches(
    world: World, tmp_path: Path
) -> None:
    # An image side's repeat check, asked before any launch when the run has no
    # warm-up, makes its folder there.
    _run(world, tmp_path, _experiment(run={"warmups": 0}))
    assert [r.ctx.launch_folders for r in world.resolved] == [tmp_path / "run" / "artifacts"] * 2


def test_the_control_by_factor_carries_the_variable_and_takes_values_as_read(
    world: World, tmp_path: Path
) -> None:
    experiment = dataclasses.replace(_experiment(), controls=ControlSettings(positive_via="factor"))
    capture = _run(world, tmp_path, experiment)
    control = [r for r in world.requests if r.name == "old~twice"]
    assert {r.env.get(WORK_FACTOR_VARIABLE) for r in control} == {"2"}
    assert all(r.second is None for r in control)
    assert _values(capture, "old~twice", "work") == [3.0] * 8
    assert {x.runs for x in capture.launches if x.name == "old~twice"} == {1}
    others = [r for r in world.requests if r.name != "old~twice"]
    assert not any(WORK_FACTOR_VARIABLE in r.env for r in others)


# ---------------------------------------------------------------------------
# Energy
# ---------------------------------------------------------------------------


def test_every_launch_records_the_energy_of_its_own_window(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(energy=ENERGY_ON))
    for name in ENTRIES:
        assert _round_values(capture, name, "energy_j[gpu]") == [7.5] * 8
        assert _round_values(capture, name, "mean_power_w[gpu]") == [2.5] * 8
    assert len(world.power_windows) == QUICK_LAUNCHES
    for started, windows in world.power_windows:
        assert [w.label for w in windows] == [""]
        assert started <= windows[0].start_s <= windows[0].end_s
    assert all(x.energy is not None for x in capture.launches)


def test_the_notes_of_every_power_reading_are_kept(world: World, tmp_path: Path) -> None:
    world.power_notes = [("made_up_power", "a made-up power note")]
    capture = _run(world, tmp_path, _experiment(energy=ENERGY_ON))
    assert _codes(capture).count("made_up_power") == QUICK_LAUNCHES


# ---------------------------------------------------------------------------
# A serving side: the load runs on the host
# ---------------------------------------------------------------------------


class _LoadDriver:
    """Sends a made-up load, one step per label, and reads how many steps ran."""

    name: str = "loaddriver"
    api_version: int = API_VERSION
    where: str = "client"
    clock_cases: tuple[str, ...] = ()

    def __init__(self, labels: tuple[str, ...]) -> None:
        self.labels = labels

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation(steps=tuple(Step(label=x, argv=("./load", x)) for x in self.labels))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        ran = list(artifacts.glob("load-*.done"))
        if ctx.endpoint is None or not ran:
            raise Refusal("E_LAUNCH_FAILED", "the load did not run")
        return [
            Sample(
                case="latency",
                metric="latency",
                unit="s",
                better="lower",
                kind="time",
                value=float(len(ran)),
            )
        ]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return ["latency"]


def _serve(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rc: int = 0,
    labels: tuple[str, ...] = ("c1",),
) -> list[tuple[tuple[str, ...], Path]]:
    registry.register(GROUP_DRIVERS, "loaddriver", _LoadDriver(labels))
    world.behaviour.serve = True
    ran: list[tuple[tuple[str, ...], Path]] = []

    def run_step(argv: Any, env: Any, folder: Path, index: int, deadline: Any = None) -> int:
        ran.append((tuple(argv), folder))
        (folder / f"load-{index}.done").write_text("done\n")
        return rc

    counter = itertools.count()
    monkeypatch.setattr("pairbench.runner._run_step", run_step)
    monkeypatch.setattr("pairbench.runner._children_cpu_s", lambda: next(counter) * 0.5)
    return ran


def _served(**more: Any) -> Experiment:
    return dataclasses.replace(_experiment(**more), driver="loaddriver")


def test_a_serving_launch_runs_its_load_on_the_host(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _serve(world, monkeypatch)
    capture = _run(world, tmp_path, _served())
    assert capture.complete
    assert _round_values(capture, "new", "latency") == [1.0] * 8
    assert _round_values(capture, "old~twice", "latency") == [2.0] * 8
    assert len(ran) == QUICK_LAUNCHES + 8
    assert {argv for argv, _ in ran} == {("./load", "c1")}
    assert world.witness_stops == [1.25] * QUICK_LAUNCHES


def test_a_load_step_that_fails_fails_the_launch(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(world, monkeypatch, rc=3)
    refusal = _refused(world, tmp_path, _served())
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    assert refusal.message == "the warm-up launch of 'new' ran a load step that exited with 3"
    capture = _read(tmp_path)
    assert capture.end is not None and capture.end.status == "failed"
    assert len(world.requests) == 1


def test_the_serving_control_keeps_only_the_energy_windows_it_has_once(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(world, monkeypatch, labels=("c1", "c2"))
    capture = _run(world, tmp_path, _served(energy=ENERGY_ON))
    assert _round_values(capture, "old", "c1/energy_j[gpu]") == [7.5] * 8
    assert _round_values(capture, "old~twice", "energy_j[gpu]") == [7.5] * 8
    assert _round_values(capture, "old~twice", "c1/energy_j[gpu]") == []
    labels = [[w.label for w in windows] for _, windows in world.power_windows]
    assert labels.count(["", "c1", "c2", "c1", "c2"]) == 8
    assert labels.count(["", "c1", "c2"]) == QUICK_LAUNCHES - 8


def test_the_serving_control_by_factor_keeps_every_energy_window(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(world, monkeypatch, labels=("c1", "c2"))
    experiment = dataclasses.replace(
        _served(energy=ENERGY_ON), controls=ControlSettings(positive_via="factor")
    )
    capture = _run(world, tmp_path, experiment)
    assert _round_values(capture, "old~twice", "c1/energy_j[gpu]") == [7.5] * 8
    assert _round_values(capture, "old~twice", "c2/mean_power_w[gpu]") == [2.5] * 8
    assert _round_values(capture, "old~twice", "latency") == [2.0] * 8


# ---------------------------------------------------------------------------
# The cost of a launch and the environment size
# ---------------------------------------------------------------------------


def test_the_cost_of_a_launch_is_measured_through_a_command_side(
    as_cmd: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pairbench.runner.shutil.which", lambda name: MADE_UP_TRUE)
    capture = _run(as_cmd, tmp_path, _experiment(sides=CMD_SIDES, cost=3))
    assert capture.launch_cost is not None
    assert (capture.launch_cost.command, capture.launch_cost.n) == ("true", 3)
    assert capture.launch_cost.median_s == 0.25
    cost = [r for r in as_cmd.requests if r.phase == "cost"]
    assert [r.argv for r in cost] == [(MADE_UP_TRUE,)] * 3
    assert [r.env for r in cost] == [{}] * 3
    assert not any(x.phase not in ("warmup", "round") for x in capture.launches)
    kinds = [r["t"] for r in _records(tmp_path)]
    assert kinds.index("launch_cost") > max(
        i for i, r in enumerate(_records(tmp_path)) if r.get("phase") == "warmup"
    )


def test_a_lineup_without_a_command_side_measures_no_cost(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(cost=3))
    assert capture.launch_cost is None
    assert not any(r.phase == "cost" for r in world.requests)


def test_a_missing_empty_command_gives_the_note(
    as_cmd: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pairbench.runner.shutil.which", lambda name: None)
    sides = (
        Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
        Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
    )
    capture = _run(as_cmd, tmp_path, _experiment(sides=sides, cost=3))
    assert capture.launch_cost is None
    assert NOTE_LAUNCH_COST_NOT_MEASURED in _codes(capture)


def test_cost_launches_get_a_pad_of_length_zero(
    as_cmd: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pairbench.runner.shutil.which", lambda name: MADE_UP_TRUE)
    experiment = _experiment(sides=CMD_SIDES, cost=2, run={"quick": True, "vary_env_size": True})
    _run(as_cmd, tmp_path, experiment)
    cost = [r for r in as_cmd.requests if r.phase == "cost"]
    assert [r.env for r in cost] == [{ENV_PAD_VARIABLE: ""}] * 2


def test_every_entry_of_a_round_gets_one_pad_length(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(run={"quick": True, "vary_env_size": True}))
    by_round: dict[int, set[int | None]] = {}
    for x in capture.launches:
        by_round.setdefault(x.round, set()).add(x.env_pad)
    assert by_round[0] == {0}
    assert by_round[1] == {484}
    assert by_round[2] == {3332}
    assert by_round[1] == {env_pad_length(DEFAULT_SEED, 1)}
    assert capture.header.seeds == {"driver": 1234, "env_pad": 1234}
    assert all(len(lengths) == 1 for lengths in by_round.values())
    for request in world.requests:
        assert len(request.env[ENV_PAD_VARIABLE]) == next(iter(by_round[request.round]))


def test_without_the_setting_no_launch_is_padded(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path)
    assert {x.env_pad for x in capture.launches} == {None}
    assert not any(ENV_PAD_VARIABLE in r.env for r in world.requests)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_side_and_twin_launches_give_resource_cases(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path)
    assert _values(capture, "new~same", "res/rss_peak") == [1000.0] * 8
    assert _values(capture, "new", "res/user")[:1] == [0.5]
    res = [c for c in capture.cases if c.id.startswith("res/")]
    assert res and not any(c.primary for c in res)
    missing = [n.message for n in capture.notes if n.code == NOTE_RESOURCE_FIGURE_MISSING]
    assert missing and len(missing) == len(set(missing))
    assert any("res/faults_major" in m for m in missing)


def test_a_case_with_a_reserved_prefix_fails_the_launch(world: World, tmp_path: Path) -> None:
    world.behaviour.cases = lambda request: {"res/made_up": 1.0}
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    capture = _read(tmp_path)
    assert capture.end is not None and capture.end.status == "failed"


def test_sides_with_different_primary_cases_are_refused(world: World, tmp_path: Path) -> None:
    world.behaviour.cases = lambda request: {"extra": 1.0} if request.name == "new" else {}
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_CASES_DIFFER"
    assert refusal.exit_code == EXIT_ANALYSIS


def test_a_primary_case_pattern_that_matches_no_case_is_refused(
    world: World, tmp_path: Path
) -> None:
    experiment = _experiment(cases=CaseSettings(primary=("wall", "Wall")))
    refusal = _refused(world, tmp_path, experiment)
    assert (refusal.code, refusal.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert refusal.message.startswith(
        "the primary case pattern 'Wall' matches no case of this run; its cases are: "
    )
    assert "'wall'" in refusal.message
    assert "'work'" in refusal.message


@pytest.mark.parametrize("pattern", ["res/user", "res/*"])
def test_a_primary_case_pattern_that_matches_only_resource_cases_is_refused(
    world: World, tmp_path: Path, pattern: str
) -> None:
    experiment = _experiment(cases=CaseSettings(primary=(pattern,)))
    refusal = _refused(world, tmp_path, experiment)
    assert (refusal.code, refusal.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert refusal.message.startswith(
        f"the primary case pattern {pattern!r} matches only cases that describe and do not "
        "judge, which are never primary (a resource case under 'res/', or a case whose better "
        "is none): 'res/"
    )
    assert refusal.message.endswith("; the cases that can be primary are: 'wall', 'work'")


def test_a_primary_case_pattern_that_matches_only_cases_whose_better_is_none_is_refused(
    world: World, tmp_path: Path
) -> None:
    def described(request: LaunchRequest) -> list[Sample]:
        return [
            Sample(case="size/a", metric="a", unit="B", better="none", kind="other", value=4.0),
            Sample(case="size/b", metric="b", unit="B", better="none", kind="other", value=5.0),
        ]

    world.behaviour.side_samples = described
    refusal = _refused(world, tmp_path, _experiment(cases=CaseSettings(primary=("size/*",))))
    assert (refusal.code, refusal.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert "'size/*' matches only cases that describe and do not judge" in refusal.message
    assert "'size/a', 'size/b'; the cases that can be primary are: " in refusal.message


NOTE_NO_CASE_PRIMARY = "no_case_primary"
NO_CASE_PRIMARY = (
    "no case of this run is primary, so no case is tested and no --fail-on outcome can "
    "match; a resource case under 'res/' and a case whose better is none are never primary; "
    "--case makes a case primary, among: 'wall'"
)
FILE_SIDES = (
    Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": None}),
    Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
)


@pytest.mark.parametrize("path", ["warm-up", "no warm-up", "result files"])
def test_a_run_whose_cases_are_never_primary_says_once_that_it_tests_none(
    as_file: World, tmp_path: Path, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    as_file.behaviour.better = "none"
    if path == "result files":
        as_file.behaviour.files = 3
        experiment = _experiment(sides=FILE_SIDES, run={})
    elif path == "no warm-up":
        experiment = _experiment(run={"quick": True, "warmups": 0})
    else:
        experiment = _experiment()

    capture = _run(as_file, tmp_path, experiment)

    notes = [n.message for n in capture.notes if n.code == NOTE_NO_CASE_PRIMARY]
    assert notes == [NO_CASE_PRIMARY]
    assert not any(c.primary for c in capture.cases)
    printed = [
        line for line in capsys.readouterr().err.splitlines() if NOTE_NO_CASE_PRIMARY in line
    ]
    assert printed == [f"pairbench: note: {NOTE_NO_CASE_PRIMARY}: {NO_CASE_PRIMARY}"]


def test_a_run_whose_cases_all_describe_names_no_case_to_choose(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.better = "none"
    world.behaviour.wall_better = "none"
    capture = _run(world, tmp_path)
    notes = [n.message for n in capture.notes if n.code == NOTE_NO_CASE_PRIMARY]
    assert notes == [
        "no case of this run is primary, so no case is tested and no --fail-on outcome can "
        "match; a resource case under 'res/' and a case whose better is none are never primary"
    ]


def test_a_run_with_a_primary_case_gives_no_note_that_it_tests_none(
    world: World, tmp_path: Path
) -> None:
    capture = _run(world, tmp_path)
    assert NOTE_NO_CASE_PRIMARY not in _codes(capture)


def test_a_pattern_that_matches_a_resource_case_and_a_judged_case_runs(
    world: World, tmp_path: Path
) -> None:
    capture = _run(world, tmp_path, _experiment(cases=CaseSettings(primary=("w*", "*"))))
    assert {c.id for c in capture.cases if c.primary} == {"wall", "work"}


def test_primary_case_patterns_that_each_match_a_case_run(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(cases=CaseSettings(primary=("w*", "work"))))
    assert {c.id for c in capture.cases if c.primary} == {"wall", "work"}


def test_a_case_first_seen_after_warm_up_is_secondary(world: World, tmp_path: Path) -> None:
    world.behaviour.cases = lambda request: {"late": 1.0} if request.round >= 2 else {}
    capture = _run(world, tmp_path)
    late = next(c for c in capture.cases if c.id == "late")
    assert late.primary is False
    assert _codes(capture).count(NOTE_NEW_CASE) == 1
    assert "cases" in [r["t"] for r in _records(tmp_path)]


def test_the_notes_of_a_run_are_printed_to_standard_error(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def during(request: LaunchRequest) -> None:
        if request.phase == "round" and request.round == 3 and request.name == "new":
            world.resolved[0].ctx.note("made_up_note", "said in round 3")

    world.behaviour.cases = lambda request: {"late": 1.0} if request.round >= 2 else {}
    world.behaviour.during = during
    _run(world, tmp_path)
    err = capsys.readouterr().err
    assert (
        err.count(
            "pairbench: note: case_after_warmup: case 'late' was first seen after warm-up; "
            "it is recorded as secondary\n"
        )
        == 1
    )
    assert err.count("pairbench: note: made_up_note: said in round 3\n") == 1


class _UntestedDriver:
    """Reads like the made-up driver and reports a tool version it was not tested with."""

    name: str = "untested"
    api_version: int = API_VERSION
    where: str = "in_side"
    clock_cases: tuple[str, ...] = ("wall",)

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        return list(self.inner.read(ctx, artifacts))

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return list(self.inner.default_primary(samples))

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        return ToolVersion(tool="made-up-tool", version="9.0", tested=False)


def test_a_tool_version_the_driver_was_not_tested_with_is_noted_once(
    world: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "untested", _UntestedDriver(registry.driver("fakedriver")))
    capture = _run(world, tmp_path, dataclasses.replace(_experiment(), driver="untested"))
    noted = [n.message for n in capture.notes if n.code == NOTE_TOOL_VERSION_UNTESTED]
    assert noted == ["made-up-tool 9.0 is a major version this driver was not tested with"]
    assert {x.tool_version for x in capture.launches} == {"9.0"}


class _RewritingDriver:
    """Reads like the made-up driver, then lets a test change what it read, and reports a
    tool name and version."""

    name: str = "rewriting"
    api_version: int = API_VERSION
    where: str = "in_side"
    clock_cases: tuple[str, ...] = ("wall",)

    def __init__(
        self,
        inner: Any,
        change: Callable[[Sample], Sample] = lambda sample: sample,
        tool: ToolVersion | None = None,
    ) -> None:
        self.inner = inner
        self.change = change
        self.tool = tool

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        return [self.change(sample) for sample in self.inner.read(ctx, artifacts)]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return list(self.inner.default_primary(samples))

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        return self.tool


# The command line a run records: a run started under it writes its results.
SHOWN_COMMAND = ["pairbench", "run"]


def _rewriting(
    world: World, tmp_path: Path, driver: _RewritingDriver, *, shown: bool = True
) -> Refusal | Capture:
    """Run with the rewriting driver, as the command line runs it or, without ``shown``, as a
    call of the Python API does."""
    registry.register(GROUP_DRIVERS, "rewriting", driver)
    experiment = dataclasses.replace(_experiment(), driver="rewriting")
    try:
        if not shown:
            return _run(world, tmp_path, experiment)
        with api.command_line(SHOWN_COMMAND):
            return _run(world, tmp_path, experiment)
    except Refusal as refusal:
        return refusal


def test_a_metric_a_plug_in_driver_read_with_a_lone_surrogate_fails_the_launch_and_keeps_it(
    world: World, tmp_path: Path
) -> None:
    def change(sample: Sample) -> Sample:
        if sample.case != "work":
            return sample
        return dataclasses.replace(sample, metric="w\ud800rk")

    refusal = _rewriting(world, tmp_path, _RewritingDriver(registry.driver("fakedriver"), change))
    assert isinstance(refusal, Refusal)
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    assert refusal.message == (
        "side 'new': the metric of case 'work': w\\ud800rk holds a lone surrogate, which is "
        "not UTF-8 text"
    )
    records = _records(tmp_path)
    launches = [r for r in records if r["t"] == "launch"]
    assert len(world.requests) == 1
    assert [(r["name"], r["phase"], r["rc"]) for r in launches] == [("new", "warmup", 0)]
    assert records[-1]["t"] == "end"
    assert records[-1]["status"] == "failed"


class _ControlAddingDriver(_RewritingDriver):
    """Reads like the rewriting driver, and adds to what a launch of the positive control
    read the samples ``added`` makes of it."""

    def __init__(self, inner: Any, added: Callable[[list[Sample]], list[Sample]]) -> None:
        super().__init__(inner)
        self.added = added

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        read = super().read(ctx, artifacts)
        return read + self.added(read) if ctx.name.endswith("~twice") else read


def _with_case(case: str, better: str = "lower") -> Callable[[list[Sample]], list[Sample]]:
    """Add a copy of the case ``work`` named ``case``, with ``better`` as given."""

    def added(read: list[Sample]) -> list[Sample]:
        return [
            dataclasses.replace(sample, case=case, better=better)
            for sample in read
            if sample.case == "work"
        ]

    return added


def _one_run_only(case: str, seconds: float) -> Callable[[list[Sample]], list[Sample]]:
    """Add a copy of the case ``work`` named ``case`` to the one run of the control whose
    ``work`` reads ``seconds``."""

    def added(read: list[Sample]) -> list[Sample]:
        return [
            dataclasses.replace(sample, case=case)
            for sample in read
            if sample.case == "work" and sample.value == seconds
        ]

    return added


# What the first and the second run of the positive control read in the tests of a case one
# of them alone gives: the first reads the baseline's time, the second the time set here.
FIRST_RUN_SECONDS = 3.0
SECOND_RUN_SECONDS = 7.25
CASE_HELD = "w\ud800rk"
NOTE_CASE_HELD_MISSING = (
    "case 'w\\ud800rk' came from only one of the two runs of the positive control and has "
    "no value for it"
)
CASE_HELD_REFUSED = (
    "side 'old~twice': the case w\\ud800rk holds a lone surrogate, which is not UTF-8 text"
)


def _utf8_records(tmp_path: Path) -> list[dict[str, Any]]:
    """The records of the capture, each of which UTF-8 text can hold."""
    records = _records(tmp_path)
    for record in records:
        json.dumps(record, ensure_ascii=False).encode("utf-8")
    return records


@pytest.mark.parametrize(
    "seconds", [FIRST_RUN_SECONDS, SECOND_RUN_SECONDS], ids=["first-run", "second-run"]
)
def test_a_case_with_a_lone_surrogate_the_control_does_not_record_is_noted_and_the_run_ends(
    world: World, tmp_path: Path, seconds: float
) -> None:
    world.behaviour.second_seconds = SECOND_RUN_SECONDS
    assert world.behaviour.seconds["old"] == FIRST_RUN_SECONDS
    driver = _ControlAddingDriver(registry.driver("fakedriver"), _one_run_only(CASE_HELD, seconds))
    ran = _rewriting(world, tmp_path, driver)
    assert isinstance(ran, Capture)
    noted = [n.message for n in ran.notes if n.code == NOTE_CONTROL_CASE_MISSING]
    assert noted == [NOTE_CASE_HELD_MISSING]
    records = _utf8_records(tmp_path)
    assert records[-1]["t"] == "end"
    assert records[-1]["status"] == "complete"
    assert {o.case for o in ran.observations if o.name == "old~twice"} >= {"wall", "work"}
    assert CASE_HELD not in {o.case for o in ran.observations} | {c.id for c in ran.cases}


def test_a_case_with_a_lone_surrogate_in_both_runs_of_the_control_fails_the_launch(
    world: World, tmp_path: Path
) -> None:
    driver = _ControlAddingDriver(registry.driver("fakedriver"), _with_case(CASE_HELD))
    refusal = _rewriting(world, tmp_path, driver)
    assert isinstance(refusal, Refusal)
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    assert refusal.message == CASE_HELD_REFUSED
    records = _records(tmp_path)
    launches = [r for r in records if r["t"] == "launch"]
    assert launches[-1]["name"] == "old~twice"
    assert len(launches) == len(world.requests)
    assert records[-1]["t"] == "end"
    assert records[-1]["status"] == "failed"


@pytest.mark.parametrize(
    ("better", "refused"), [("none", None), ("lower", CASE_HELD_REFUSED)], ids=["none", "lower"]
)
def test_a_case_with_a_lone_surrogate_under_the_work_factor_is_refused_only_if_recorded(
    world: World, tmp_path: Path, better: str, refused: str | None
) -> None:
    registry.register(
        GROUP_DRIVERS,
        "rewriting",
        _ControlAddingDriver(registry.driver("fakedriver"), _with_case(CASE_HELD, better)),
    )
    experiment = dataclasses.replace(
        _experiment(), driver="rewriting", controls=ControlSettings(positive_via="factor")
    )
    with api.command_line(SHOWN_COMMAND):
        if refused is None:
            ran = _run(world, tmp_path, experiment)
            assert CASE_HELD not in {o.case for o in ran.observations} | {c.id for c in ran.cases}
            assert _utf8_records(tmp_path)[-1]["status"] == "complete"
            return
        with pytest.raises(Refusal) as caught:
            _run(world, tmp_path, experiment)
    assert caught.value.code == "E_LAUNCH_FAILED"
    assert caught.value.message == refused
    assert _records(tmp_path)[-1]["status"] == "failed"


@pytest.mark.parametrize("tested", [True, False], ids=["tested", "untested"])
def test_a_tool_name_with_a_lone_surrogate_fails_the_launch_only_where_a_note_shows_it(
    world: World, tmp_path: Path, tested: bool
) -> None:
    tool = ToolVersion(tool="made-up-\udcfftool", version="9.0", tested=tested)
    ran = _rewriting(world, tmp_path, _RewritingDriver(registry.driver("fakedriver"), tool=tool))
    if tested:
        assert isinstance(ran, Capture)
        assert {x.tool_version for x in ran.launches} == {"9.0"}
        assert NOTE_TOOL_VERSION_UNTESTED not in _codes(ran)
        return
    assert isinstance(ran, Refusal)
    assert ran.code == "E_LAUNCH_FAILED"
    assert ran.message == (
        "side 'new': the tool name made-up-\\udcfftool holds a lone surrogate, which is not "
        "UTF-8 text"
    )


def _metric(sample: Sample) -> Sample:
    return dataclasses.replace(sample, metric="w\ud800rk") if sample.case == "work" else sample


def _case(sample: Sample) -> Sample:
    return dataclasses.replace(sample, case="w\ud800rk") if sample.case == "work" else sample


def _unit(sample: Sample) -> Sample:
    return dataclasses.replace(sample, unit="s\udcff") if sample.case == "work" else sample


@pytest.mark.parametrize(
    ("change", "tool", "held", "escaped"),
    [
        pytest.param(_metric, None, "w\ud800rk", b"w\\ud800rk", id="metric"),
        pytest.param(_case, None, "w\ud800rk", b"w\\ud800rk", id="case"),
        pytest.param(_unit, None, "s\udcff", b"s\\udcff", id="unit"),
        pytest.param(
            None,
            ToolVersion("made-up", "9.\udcff", tested=True),
            "9.\udcff",
            b"9.\\udcff",
            id="tool-version",
        ),
        pytest.param(
            None,
            ToolVersion("made-up-\udcfftool", "9.0", tested=False),
            "made-up-\udcfftool",
            b"made-up-\\udcfftool",
            id="tool-name",
        ),
    ],
)
def test_a_run_of_the_python_api_keeps_what_a_driver_read_with_a_lone_surrogate(
    world: World,
    tmp_path: Path,
    change: Callable[[Sample], Sample] | None,
    tool: ToolVersion | None,
    held: str,
    escaped: bytes,
) -> None:
    driver = _RewritingDriver(registry.driver("fakedriver"), change or (lambda s: s), tool=tool)
    ran = _rewriting(world, tmp_path, driver, shown=False)
    assert isinstance(ran, Capture)
    kept = json.dumps([r for r in _records(tmp_path) if r["t"] != "header"], ensure_ascii=False)
    assert held in kept
    assert escaped in (tmp_path / "run" / FILE_CAPTURE).read_bytes()
    assert _records(tmp_path)[-1]["status"] == "complete"


def test_with_no_warm_up_the_cases_follow_round_one(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(run={"quick": True, "warmups": 0}))
    records = _records(tmp_path)
    lineup = next(r for r in records if r["t"] == "lineup")
    assert lineup["cases"] == []
    at = next(i for i, r in enumerate(records) if r["t"] == "cases")
    before = [r for r in records[:at] if r["t"] == "launch"]
    after = [r for r in records[at:] if r["t"] == "launch"]
    assert {r["round"] for r in before} == {1}
    assert {r["round"] for r in after} == set(range(2, 9))
    assert {c.id for c in capture.cases} >= {"wall", "work"}
    assert not any(x.phase == "warmup" for x in capture.launches)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_failed_launch_ends_the_capture_as_failed(world: World, tmp_path: Path) -> None:
    world.behaviour.fail_at = 4
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    assert refusal.detail["run_dir"] == str(tmp_path / "run")
    capture = _read(tmp_path)
    assert capture.end is not None
    assert capture.end.status == "failed"
    assert capture.launches[-1].rc == 1
    assert all(r.closed >= 1 for r in world.resolved)


def test_a_failed_warm_up_launch_is_named_as_the_warm_up(world: World, tmp_path: Path) -> None:
    world.behaviour.fail_at = 1
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_LAUNCH_FAILED"
    assert refusal.exit_code == EXIT_LAUNCH
    assert refusal.message == "the warm-up launch of 'new' exited with 1"
    capture = _read(tmp_path)
    assert capture.launches[-1].phase == "warmup"


def test_a_failed_launch_of_a_round_names_its_round(world: World, tmp_path: Path) -> None:
    world.behaviour.fail_at = 4
    refusal = _refused(world, tmp_path)
    capture = _read(tmp_path)
    failed = capture.launches[-1]
    assert failed.phase == "round"
    assert refusal.message == f"the launch of {failed.name!r} in round {failed.round} exited with 1"


# The exit code each kind of side reports for a launch it stopped at its timeout:
# a command and a Python environment are killed, an engine reports its own code
# for a killed container, and a serving side reports 1.
TIMEOUT_RCS = {"cmd": -9, "pyenv": -9, "image": 137, "serve": 1}


@pytest.mark.parametrize("kind", sorted(TIMEOUT_RCS))
def test_a_launch_that_ran_into_its_timeout_says_so_in_its_record_for_every_kind(
    world: World, tmp_path: Path, kind: str
) -> None:
    world.behaviour.fail_at = 4
    world.behaviour.fail_rc = TIMEOUT_RCS[kind]
    world.behaviour.timed_out = True
    refusal = _refused(world, tmp_path)
    capture = _read(tmp_path)
    failed = capture.launches[-1]
    assert (failed.rc, failed.timed_out) == (TIMEOUT_RCS[kind], True)
    assert refusal.message == (
        f"the launch of {failed.name!r} in round {failed.round} ran into its timeout"
    )
    assert not any(x.timed_out for x in capture.launches[:-1])


def test_a_launch_that_failed_without_a_timeout_says_it_did_not_time_out(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.fail_at = 4
    _refused(world, tmp_path)
    capture = _read(tmp_path)
    assert (capture.launches[-1].rc, capture.launches[-1].timed_out) == (1, False)


def test_without_out_the_run_folder_of_the_run_settings_is_used(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    named = tmp_path / "named"
    experiment = _experiment(run={"quick": True, "out": str(named)})
    capture = run_experiment(experiment, services=world.services())
    assert capture.source is not None and capture.source.path is not None
    assert Path(capture.source.path).parent == named
    assert (named / FILE_CAPTURE).is_file()


def test_an_interrupt_ends_the_capture_as_interrupted(world: World, tmp_path: Path) -> None:
    world.behaviour.interrupt_at = 5
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_INTERRUPTED"
    assert refusal.exit_code == EXIT_INTERRUPTED
    assert refusal.detail["run_dir"] == str(tmp_path / "run")
    capture = _read(tmp_path)
    assert capture.end is not None
    assert capture.end.status == "interrupted"


class _StopsOnResolve:
    """A side kind whose resolve is interrupted."""

    name: str = "stops"
    api_version: int = API_VERSION

    def resolve(self, side: Side, ctx: Any) -> Any:
        raise KeyboardInterrupt

    def look_up(self, side: Side, ctx: Any) -> Any:
        raise AssertionError("look_up is not called by a run")


def test_an_interrupt_while_sides_resolve_is_refused_as_interrupted(
    world: World, tmp_path: Path
) -> None:
    registry.register(GROUP_SIDE_KINDS, "stops", _StopsOnResolve())
    sides = (SIDES[0], Side(name="old", kind="stops", spec={"argv": ["./old"]}))
    with pytest.raises(BaseException) as caught:
        _run(world, tmp_path, _experiment(sides=sides))
    assert isinstance(caught.value, Refusal)
    assert caught.value.code == "E_INTERRUPTED"
    assert caught.value.exit_code == EXIT_INTERRUPTED
    assert not (tmp_path / "run").exists()
    assert [r.closed for r in world.resolved] == [1]


def test_two_sides_that_are_the_same_are_refused_before_anything(
    world: World, tmp_path: Path
) -> None:
    sides = (
        Side(name="new", kind="fake", spec={"argv": ["./same"]}),
        Side(name="old", kind="fake", spec={"argv": ["./same"]}),
    )
    refusal = _refused(world, tmp_path, _experiment(sides=sides))
    assert refusal.code == "E_SAME_SIDE"
    assert refusal.exit_code == 3
    assert "run_dir" not in refusal.detail
    assert not (tmp_path / "run").exists()
    assert world.requests == []


def test_a_twin_with_another_fingerprint_is_refused_as_the_run_starts(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_twin = Side.twin

    def drifted(self: Side) -> Side:
        return dataclasses.replace(real_twin(self), fingerprint="f" * 64)

    monkeypatch.setattr(Side, "twin", drifted)
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_TWIN_DRIFT"
    assert refusal.exit_code == EXIT_SIDE
    assert not (tmp_path / "run").exists()
    assert world.requests == []
    assert all(r.closed == 1 for r in world.resolved)


def test_a_side_whose_shown_identity_is_not_utf_8_is_refused_before_the_run_folder(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Side.with_identity

    def reported(self: Side, identity: Mapping[str, Any], fingerprint: str) -> Side:
        if self.name == "old":
            identity = {**identity, "python_version": "9.\udcff"}
        return real(self, identity, fingerprint)

    monkeypatch.setattr(Side, "with_identity", reported)
    with api.command_line(SHOWN_COMMAND):
        refusal = _refused(world, tmp_path)
    assert refusal.code == "E_SIDE_UNIDENTIFIED"
    assert refusal.exit_code == EXIT_SIDE
    assert refusal.message == (
        "side 'old': identity.python_version of what the results show of it is not UTF-8 "
        "text, which the results are"
    )
    assert not (tmp_path / "run").exists()
    assert world.requests == []


def test_a_run_of_the_python_api_keeps_a_shown_identity_and_a_node_type_not_utf_8(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Side.with_identity

    def reported(self: Side, identity: Mapping[str, Any], fingerprint: str) -> Side:
        if self.name == "old":
            identity = {**identity, "python_version": "9.\udcff"}
        return real(self, identity, fingerprint)

    monkeypatch.setattr(Side, "with_identity", reported)
    capture = _run(world, tmp_path, _experiment(run={"quick": True, "node_type": "g\udcffb"}))
    old = next(side for side in capture.sides if side.name == "old")
    assert old.identity["python_version"] == "9.\udcff"
    assert b'"python_version":"9.\\udcff"' in (tmp_path / "run" / FILE_CAPTURE).read_bytes()
    assert _records(tmp_path)[-1]["status"] == "complete"


def test_a_run_on_the_command_line_refuses_a_node_type_not_utf_8_before_the_run_folder(
    world: World, tmp_path: Path
) -> None:
    with api.command_line(SHOWN_COMMAND):
        refusal = _refused(
            world, tmp_path, _experiment(run={"quick": True, "node_type": "g\udcffb"})
        )
    assert refusal.code == "E_USAGE"
    assert refusal.exit_code == EXIT_USAGE
    assert refusal.message == "the setting run.node_type is not UTF-8 text, which the results are"
    assert not (tmp_path / "run").exists()
    assert world.requests == []


def test_a_side_whose_hidden_identity_is_not_utf_8_runs_and_reads_back(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Side.with_identity

    def reported(self: Side, identity: Mapping[str, Any], fingerprint: str) -> Side:
        if self.name == "old":
            identity = {**identity, "prefix": "/made-up/v\udcffw"}
        return real(self, identity, fingerprint)

    monkeypatch.setattr(Side, "with_identity", reported)
    capture = _run(world, tmp_path)
    old = next(side for side in capture.sides if side.name == "old")
    assert old.identity["prefix"] == "/made-up/v\udcffw"
    assert b'"prefix":"/made-up/v\\udcffw"' in (tmp_path / "run" / FILE_CAPTURE).read_bytes()
    assert _read(tmp_path).sides == capture.sides


def test_a_spec_that_is_not_utf_8_runs_and_reads_back(world: World, tmp_path: Path) -> None:
    sides = (
        Side(name="new", kind="fake", spec={"argv": ["./new", "v\udcffw"]}),
        Side(name="old", kind="fake", spec={"argv": ["./old"]}),
    )
    capture = _run(world, tmp_path, _experiment(sides=sides))
    new = next(side for side in capture.sides if side.name == "new")
    assert new.spec["argv"] == ("./new", "v\udcffw")
    assert _read(tmp_path).sides == capture.sides


def test_too_few_rounds_are_refused_before_the_capture_opens(world: World, tmp_path: Path) -> None:
    refusal = _refused(world, tmp_path, _experiment(run={"rounds": 4, "rounds_exact": True}))
    assert refusal.code == "E_TOO_FEW_ROUNDS"
    assert refusal.exit_code == 6
    assert not (tmp_path / "run").exists()


def test_a_run_folder_that_is_not_empty_is_refused(world: World, tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "kept.txt").write_text("kept\n")
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_USAGE"
    assert refusal.exit_code == 2
    assert (tmp_path / "run" / "kept.txt").read_text() == "kept\n"


def test_a_run_folder_under_a_file_is_refused_before_any_side_resolves(
    world: World, tmp_path: Path
) -> None:
    (tmp_path / "a-file").write_text("kept\n")
    with pytest.raises(Refusal) as caught:
        run_experiment(_experiment(), out=tmp_path / "a-file" / "run", services=world.services())
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == "the run folder run cannot be made: a-file is not a folder"
    assert world.resolved == []


def test_a_run_folder_that_cannot_be_written_is_refused_before_any_side_resolves(
    world: World, tmp_path: Path
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this user may write into a folder without write permission")
        with pytest.raises(Refusal) as caught:
            run_experiment(_experiment(), out=locked / "run", services=world.services())
    finally:
        locked.chmod(0o700)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "the run folder run cannot be made: locked does not let this user write into it"
    )
    assert world.resolved == []


def test_a_side_that_changed_during_the_run_is_refused(world: World, tmp_path: Path) -> None:
    world.behaviour.changed_after = 1
    refusal = _refused(world, tmp_path)
    assert refusal.code == "E_SIDE_CHANGED"
    assert refusal.exit_code == 5
    capture = _read(tmp_path)
    assert capture.end is not None and capture.end.status == "failed"
    assert capture.end.rounds_completed == 8


SLASHED = Side(name="x/../../../y", kind="fake", spec={"argv": ["./old"]})


def test_a_side_name_with_slashes_stays_inside_the_run_folder(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(sides=(SIDES[0], SLASHED)))
    assert capture.complete
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run"]
    folders = {p.name.split("-", 1)[1] for p in (tmp_path / "run" / "artifacts").iterdir()}
    assert folders >= {"new", "new_same", "x_.._.._.._y", "x_.._.._.._y_same", "x_.._.._.._y_twice"}


# ---------------------------------------------------------------------------
# Machine checks, locks and where the tool runs
# ---------------------------------------------------------------------------


class _Gate:
    api_version: int = API_VERSION

    def __init__(self, name: str, status: str) -> None:
        self.name = name
        self.status = status

    def check(self, ctx: GateContext) -> GateRecord:
        return GateRecord(
            name=self.name,
            mode=ctx.mode,
            status=self.status,  # type: ignore[arg-type]
            detail={"message": "a made-up reason"},
        )


def _gates(monkeypatch: pytest.MonkeyPatch, quiet: str) -> None:
    for name, status in (("cpus", "pass"), ("quiet", quiet), ("census", "pass")):
        monkeypatch.setitem(registry._state.builtins, (GROUP_GATES, name), _Gate(name, status))


def test_a_failed_check_under_enforce_is_refused_loudly(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gates(monkeypatch, "fail")
    refusal = _refused(world, tmp_path, _experiment(gates={"mode": "enforce"}))
    assert refusal.code == "E_GATE_FAILED"
    assert refusal.exit_code == EXIT_MACHINE
    capture = _read(tmp_path)
    assert [(g.name, g.status) for g in capture.gates] == [
        ("cpus", "pass"),
        ("quiet", "fail"),
        ("census", "pass"),
    ]
    assert "pairbench: check quiet: fail: a made-up reason\n" in capsys.readouterr().err
    assert world.requests == []


@pytest.mark.parametrize(
    ("gates", "hint"),
    [
        (
            {"mode": "enforce"},
            "machine check failed: quiet; --wait-quiet waits for a quiet machine before the run, "
            "and gates.quiet.* set what counts as quiet",
        ),
        (
            {"mode": "enforce", "wait_quiet": True},
            "machine check failed: quiet; gates.quiet.max_wait_s sets how long --wait-quiet "
            "waits, and gates.quiet.* set what counts as quiet",
        ),
    ],
    ids=["no-wait", "wait"],
)
def test_a_failed_quiet_check_says_what_to_change(
    gates: dict[str, Any],
    hint: str,
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _gates(monkeypatch, "fail")
    refusal = _refused(world, tmp_path, _experiment(gates=gates))
    assert refusal.code == "E_GATE_FAILED"
    assert refusal.message == hint


def test_a_failed_check_other_than_quiet_carries_no_quiet_hint(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, status in (("cpus", "fail"), ("quiet", "pass"), ("census", "pass")):
        monkeypatch.setitem(registry._state.builtins, (GROUP_GATES, name), _Gate(name, status))
    refusal = _refused(world, tmp_path, _experiment(gates={"mode": "enforce"}))
    assert refusal.message == "machine check failed: cpus"


def test_a_check_that_could_not_run_under_enforce_is_refused(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gates(monkeypatch, "degraded")
    refusal = _refused(world, tmp_path, _experiment(gates={"mode": "enforce"}))
    assert refusal.code == "E_GATE_UNAVAILABLE"
    assert refusal.exit_code == EXIT_MACHINE


def test_under_warn_a_failed_check_is_recorded_and_the_run_goes_on(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gates(monkeypatch, "fail")
    capture = _run(world, tmp_path, _experiment(gates={"mode": "warn"}))
    assert capture.complete
    assert [g.name for g in capture.gates] == ["cpus", "quiet", "census"] * 2
    assert capsys.readouterr().err.count("pairbench: check quiet: fail") == 2


READINESS = ("stop_file", "gpu_memory", "check_locks")


def _all_gates(monkeypatch: pytest.MonkeyPatch, **statuses: str) -> None:
    """Fake every built-in check; each passes unless ``statuses`` says otherwise."""
    for name in ("cpus", "quiet", "census", *READINESS):
        status = statuses.get(name, "pass")
        monkeypatch.setitem(registry._state.builtins, (GROUP_GATES, name), _Gate(name, status))


def test_readiness_checks_that_are_off_write_no_record(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_gates(monkeypatch)
    capture = _run(world, tmp_path, _experiment(gates={"mode": "warn"}))
    assert [g.name for g in capture.gates] == ["cpus", "quiet", "census"] * 2


@pytest.mark.parametrize(
    ("keys", "order"),
    [
        ({"stop_file": "made-up/hold.stop"}, ["stop_file"]),
        ({"check_locks": ("made-up/a.lock",)}, ["check_locks"]),
        (
            {
                "check_locks": ("made-up/a.lock",),
                "min_gpu_free_mib": 2000.0,
                "stop_file": "made-up/hold.stop",
            },
            ["stop_file", "gpu_memory", "check_locks"],
        ),
    ],
    ids=["stop-file", "check-locks", "all-three"],
)
def test_readiness_checks_that_are_on_run_after_the_quiet_check_in_both_phases(
    keys: dict[str, Any],
    order: list[str],
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _all_gates(monkeypatch)
    capture = _run(world, tmp_path, _experiment(gates={"mode": "warn", **keys}))
    assert [g.name for g in capture.gates] == ["cpus", "quiet", *order, "census"] * 2


def test_a_present_stop_file_under_enforce_stops_the_run(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_gates(monkeypatch, stop_file="fail")
    experiment = _experiment(gates={"mode": "enforce", "stop_file": "made-up/hold.stop"})
    refusal = _refused(world, tmp_path, experiment)
    assert refusal.code == "E_GATE_FAILED"
    assert refusal.exit_code == EXIT_MACHINE
    assert refusal.message == "machine check failed: stop_file"
    assert "pairbench: check stop_file: fail: a made-up reason\n" in capsys.readouterr().err
    assert world.requests == []


def test_a_readiness_check_that_cannot_run_under_enforce_is_refused(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_gates(monkeypatch, gpu_memory="unavailable")
    experiment = _experiment(gates={"mode": "enforce", "min_gpu_free_mib": 2000.0})
    refusal = _refused(world, tmp_path, experiment)
    assert refusal.code == "E_GATE_UNAVAILABLE"
    assert refusal.message == "machine check could not run fully: gpu_memory"


def test_under_warn_a_present_stop_file_is_recorded_and_the_run_goes_on(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _all_gates(monkeypatch, stop_file="fail")
    capture = _run(world, tmp_path, _experiment(gates={"mode": "warn", "stop_file": "made-up/x"}))
    assert capture.complete
    assert [(g.name, g.status) for g in capture.gates if g.name == "stop_file"] == [
        ("stop_file", "fail"),
        ("stop_file", "fail"),
    ]
    assert capsys.readouterr().err.count("pairbench: check stop_file: fail") == 2


def test_with_the_checks_off_no_readiness_check_runs(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_gates(monkeypatch, stop_file="fail")
    capture = _run(world, tmp_path, _experiment(gates={"mode": "off", "stop_file": "made-up/x"}))
    assert capture.complete
    assert capture.gates == ()


def test_a_plugin_check_runs_after_the_census(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _all_gates(monkeypatch)
    monkeypatch.setitem(
        registry._state.plugins, (GROUP_GATES, "made-up-check"), _Gate("made-up-check", "pass")
    )
    experiment = _experiment(gates={"mode": "warn", "stop_file": "made-up/x"})
    capture = _run(world, tmp_path, experiment)
    assert [g.name for g in capture.gates] == [
        "cpus",
        "quiet",
        "stop_file",
        "census",
        "made-up-check",
    ] * 2


def test_locks_are_taken_and_released(world: World, tmp_path: Path) -> None:
    capture = _run(world, tmp_path, _experiment(gates={"locks": ("made-up.lock",)}))
    assert capture.complete
    assert world.locked == [("made-up.lock",)]
    assert world.released == 1


def test_a_lock_that_cannot_be_taken_is_refused(world: World, tmp_path: Path) -> None:
    world.lock_refused = True
    refusal = _refused(world, tmp_path, _experiment(gates={"locks": ("made-up.lock",)}))
    assert refusal.code == "E_LOCK"
    assert refusal.exit_code == EXIT_MACHINE
    assert refusal.detail["run_dir"] == str(tmp_path / "run")
    assert world.requests == []


def test_the_tool_cpus_are_restored_once_when_a_run_completes(world: World, tmp_path: Path) -> None:
    assert _run(world, tmp_path, _experiment(launch=LaunchSettings(cpus="0-1"))).complete
    assert (world.left, world.restored) == (["0-1"], 1)


def test_the_tool_cpus_are_restored_when_a_run_is_refused(world: World, tmp_path: Path) -> None:
    world.lock_refused = True
    experiment = _experiment(launch=LaunchSettings(cpus="0-1"), gates={"locks": ("made-up.lock",)})
    assert _refused(world, tmp_path, experiment).code == "E_LOCK"
    assert (world.left, world.restored) == (["0-1"], 1)


def test_the_tool_cpus_are_restored_when_a_run_is_interrupted(world: World, tmp_path: Path) -> None:
    world.behaviour.interrupt_at = 3
    refusal = _refused(world, tmp_path, _experiment(launch=LaunchSettings(cpus="0-1")))
    assert refusal.code == "E_INTERRUPTED"
    assert (world.left, world.restored) == (["0-1"], 1)


def _movable_cpus() -> frozenset[int]:
    """The CPUs this process may run on; skips where the tool cannot move off one of them."""
    if not (hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity")):
        pytest.skip("this platform does not let a process choose its CPUs")
    cpus = frozenset(os.sched_getaffinity(0))
    if len(cpus) < 2:
        pytest.skip("moving the tool off a pinned CPU needs at least two CPUs")
    return cpus


def test_the_tool_runs_on_all_its_cpus_again_after_a_pinned_run(
    world: World, tmp_path: Path
) -> None:
    before = _movable_cpus()
    world.moving = machine_checks()
    pinned = LaunchSettings(cpus=str(max(before)))
    try:
        capture = _run(world, tmp_path / "a", _experiment(launch=pinned))
        assert capture.machine is not None
        assert capture.machine.tool_cpus is not None
        assert os.sched_getaffinity(0) == before
        assert _run(world, tmp_path / "b", _experiment()).complete
        assert os.sched_getaffinity(0) == before
    finally:
        os.sched_setaffinity(0, before)


def test_the_tool_runs_on_all_its_cpus_again_after_a_pinned_run_fails(
    world: World, tmp_path: Path
) -> None:
    before = _movable_cpus()
    world.moving = machine_checks()
    world.lock_refused = True
    pinned = LaunchSettings(cpus=str(max(before)))
    experiment = _experiment(launch=pinned, gates={"locks": ("made-up.lock",)})
    try:
        assert _refused(world, tmp_path, experiment).code == "E_LOCK"
        assert world.left == [str(max(before))]
        assert os.sched_getaffinity(0) == before
    finally:
        os.sched_setaffinity(0, before)


def test_a_tool_left_on_the_pinned_cpus_says_so(world: World, tmp_path: Path) -> None:
    world.tool_cpus = ToolCpus(reason="none_left")
    capture = _run(world, tmp_path)
    assert NOTE_TOOL_ON_PINNED_CPUS in _codes(capture)
    assert capture.machine is not None and capture.machine.tool_cpus is None


def test_the_cpus_the_tool_moved_to_are_recorded(world: World, tmp_path: Path) -> None:
    world.tool_cpus = ToolCpus(cpus="0-1")
    world.cpu_facts = CpuFacts(mixed=True)
    capture = _run(world, tmp_path)
    assert capture.machine is not None and capture.machine.tool_cpus == "0-1"
    assert NOTE_TOOL_ON_PINNED_CPUS not in _codes(capture)
    assert NOTE_UNPINNED_MIXED_CORES in _codes(capture)


@pytest.mark.parametrize(
    ("launch", "left"),
    [
        (LaunchSettings(), [None]),
        (LaunchSettings(cpus="0-1"), ["0-1"]),
        (LaunchSettings(overrides={"new": {"cpus": "4-5"}}), ["4-5"]),
        (LaunchSettings(cpus="0-1", overrides={"new": {"cpus": "4-5"}}), ["0-1,4-5"]),
        (
            LaunchSettings(overrides={"new": {"cpus": "4-5"}, "old": {"cpus": "4-5"}}),
            ["4-5"],
        ),
    ],
)
def test_the_tool_leaves_every_pinned_set_a_side_runs_on(
    world: World, tmp_path: Path, launch: LaunchSettings, left: list[str | None]
) -> None:
    _run(world, tmp_path, _experiment(launch=launch))
    assert world.left == left


def test_a_run_whose_sides_all_have_their_own_set_gives_no_unpinned_note(
    world: World, tmp_path: Path
) -> None:
    world.cpu_facts = CpuFacts(mixed=True)
    launch = LaunchSettings(overrides={"new": {"cpus": "4-5"}, "old": {"cpus": "6-7"}})
    capture = _run(world, tmp_path, _experiment(launch=launch))
    assert NOTE_UNPINNED_MIXED_CORES not in _codes(capture)


def test_a_side_without_a_set_on_two_core_types_gives_the_note_once(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world.cpu_facts = CpuFacts(mixed=True)
    launch = LaunchSettings(overrides={"new": {"cpus": "4-5"}})
    capture = _run(world, tmp_path, _experiment(launch=launch))
    notes = [n for n in capture.notes if n.code == NOTE_UNPINNED_MIXED_CORES]
    assert [n.message for n in notes] == [
        "a side runs on no pinned CPU set and this machine has more than one core type; "
        "a launch may run on either type (pin one type with --cpus)"
    ]
    assert capsys.readouterr().err.count("more than one core type") == 1


def _two_core_types(folder: Path) -> Root:
    """A made-up kernel tree: CPUs 0-3 of one core type, CPUs 4-7 of another."""
    files = {"sys/devices/system/cpu/online": "0-7"}
    for cpu in range(8):
        midr = "0x00000000410fd801" if cpu < 4 else "0x00000000410fd4b0"
        files[f"sys/devices/system/cpu/cpu{cpu}/regs/identification/midr_el1"] = midr
    for rel, text in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text + "\n", encoding="utf-8")
    return Root(folder)


MIXED_MESSAGE = (
    "the CPU set 2-5 mixes core types (arm-41-d4b, arm-41-d80); "
    "give --allow-mixed-core-types to run on it anyway"
)


@pytest.mark.parametrize(
    ("launch", "message"),
    [
        (LaunchSettings(cpus="2-5"), MIXED_MESSAGE),
        (LaunchSettings(overrides={"new": {"cpus": "2-5"}}), f"side new: {MIXED_MESSAGE}"),
        (
            LaunchSettings(cpus="4-5", overrides={"old": {"cpus": "2-5"}}),
            f"side old: {MIXED_MESSAGE}",
        ),
    ],
)
def test_a_cpu_set_that_mixes_core_types_is_refused_whether_shared_or_a_side_own(
    world: World, tmp_path: Path, launch: LaunchSettings, message: str
) -> None:
    world.cpu_tree = _two_core_types(tmp_path / "root")
    refusal = _refused(world, tmp_path, _experiment(launch=launch))
    assert (refusal.code, refusal.exit_code) == ("E_CPUS_MIXED_TYPES", EXIT_MACHINE)
    assert refusal.message == message
    assert world.requests == []
    assert not (tmp_path / "run").exists()


ABSENT_MESSAGE = "GPU 7 is not on this machine; the GPUs here are 0, 1"


@pytest.mark.parametrize(
    ("launch", "message", "side"),
    [
        (LaunchSettings(gpus="7"), f"gpus 7: {ABSENT_MESSAGE}", None),
        (
            LaunchSettings(overrides={"new": {"gpus": "7"}}),
            f"side new: gpus 7: {ABSENT_MESSAGE}",
            "new",
        ),
        (
            LaunchSettings(gpus="1", overrides={"old": {"gpus": "0,7"}}),
            f"side old: gpus 0,7: {ABSENT_MESSAGE}",
            "old",
        ),
    ],
    ids=["shared", "new-own", "old-own"],
)
def test_a_gpu_the_machine_lacks_is_refused_naming_the_side_that_selects_it(
    world: World, tmp_path: Path, launch: LaunchSettings, message: str, side: str | None
) -> None:
    world.gpus_present = (0, 1)
    refusal = _refused(world, tmp_path, _experiment(launch=launch))
    assert (refusal.code, refusal.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert refusal.message == message
    assert refusal.detail.get("side") == side
    assert world.requests == []


def test_a_side_own_cpu_set_that_mixes_core_types_runs_when_allowed(
    world: World, tmp_path: Path
) -> None:
    world.cpu_tree = _two_core_types(tmp_path / "root")
    launch = LaunchSettings(cpus="4-5", overrides={"new": {"cpus": "2-5"}})
    experiment = _experiment(launch=launch, gates={"allow_mixed_core_types": True})
    assert _run(world, tmp_path, experiment).complete
    assert world.cpu_sets == ["4-5", "2-5"]


def test_each_side_own_cpu_set_of_one_core_type_is_checked_and_runs(
    world: World, tmp_path: Path
) -> None:
    world.cpu_tree = _two_core_types(tmp_path / "root")
    launch = LaunchSettings(overrides={"new": {"cpus": "4-5"}, "old": {"cpus": "0-1"}})
    capture = _run(world, tmp_path, _experiment(launch=launch))
    assert capture.complete
    assert world.cpu_sets == [None, "4-5", "0-1"]
    assert NOTE_UNPINNED_MIXED_CORES not in _codes(capture)


@pytest.mark.parametrize(
    ("launch", "groups"),
    [
        (LaunchSettings(), [("0-3", "arm-41-d80"), ("4-7", "arm-41-d4b")]),
        (LaunchSettings(cpus="4-5"), [("4-5", "arm-41-d4b")]),
        (
            LaunchSettings(cpus="4-5", overrides={"new": {"cpus": "0-1"}}),
            [("4-5", "arm-41-d4b"), ("0-1", "arm-41-d80")],
        ),
        (
            LaunchSettings(overrides={"new": {"cpus": "0-1"}, "old": {"cpus": "4-5"}}),
            [("0-1", "arm-41-d80"), ("4-5", "arm-41-d4b")],
        ),
        (
            LaunchSettings(overrides={"new": {"cpus": "5"}, "old": {"cpus": "4"}}),
            [("4-5", "arm-41-d4b")],
        ),
        (
            LaunchSettings(overrides={"new": {"cpus": "0-1"}}),
            [("0-3", "arm-41-d80"), ("4-7", "arm-41-d4b")],
        ),
    ],
)
def test_the_machine_record_describes_the_cpus_every_side_runs_on(
    world: World, tmp_path: Path, launch: LaunchSettings, groups: list[tuple[str, str]]
) -> None:
    world.cpu_tree = _two_core_types(tmp_path / "root")
    experiment = _experiment(launch=launch, gates={"allow_mixed_core_types": True})
    capture = _run(world, tmp_path, experiment)
    assert capture.machine is not None
    assert [(g.cpus, g.key) for g in capture.machine.cpu.identity] == groups


@pytest.mark.parametrize(
    ("launch", "gpus"),
    [
        (LaunchSettings(), [None]),
        (LaunchSettings(gpus="1"), ["1"]),
        (LaunchSettings(overrides={"new": {"gpus": "0"}, "old": {"gpus": "1"}}), ["0,1"]),
        (LaunchSettings(gpus="1", overrides={"new": {"gpus": "0"}}), ["0,1"]),
        (LaunchSettings(gpus="1", overrides={"new": {"gpus": "all"}}), ["all"]),
    ],
)
def test_the_machine_record_lists_the_gpus_every_side_selects(
    world: World, tmp_path: Path, launch: LaunchSettings, gpus: list[str | None]
) -> None:
    _run(world, tmp_path, _experiment(launch=launch))
    assert world.machine_gpus == gpus


def test_each_gpu_selection_gets_its_own_idle_power(world: World, tmp_path: Path) -> None:
    world.idle_power = {"0": 30.0, "1": 50.0}
    launch = LaunchSettings(overrides={"new": {"gpus": "0"}, "old": {"gpus": "1"}})
    capture = _run(world, tmp_path, _experiment(launch=launch, energy=ENERGY_ON))
    assert world.idle_asked == ["0", "1"]
    idle = {"new": 30.0, "new~same": 30.0, "old": 50.0, "old~same": 50.0, "old~twice": 50.0}
    for record in capture.launches:
        assert record.energy is not None
        assert record.energy["idle_power_w"] == idle[record.name]


def test_sides_on_one_gpu_selection_share_one_idle_power(world: World, tmp_path: Path) -> None:
    world.idle_power = {"all": 40.0}
    _run(world, tmp_path, _experiment(energy=ENERGY_ON))
    assert world.idle_asked == ["all"]


def test_the_machine_checks_see_the_settings_each_side_runs_with(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, tuple[str | None, str | None]]] = []

    class _Watching(_Gate):
        def check(self, ctx: GateContext) -> GateRecord:
            seen.append({name: (s.cpus, s.gpus) for name, s in ctx.sides.items()})
            return super().check(ctx)

    monkeypatch.setitem(
        registry._state.builtins, (GROUP_GATES, "quiet"), _Watching("quiet", "pass")
    )
    launch = LaunchSettings(cpus="4-5", overrides={"new": {"cpus": "6-7", "gpus": "1"}})
    _run(world, tmp_path, _experiment(launch=launch, gates={"mode": "warn"}))
    assert seen == [{"new": ("6-7", "1"), "old": ("4-5", None)}] * 2


def test_a_run_of_result_files_gives_no_unpinned_note(as_file: World, tmp_path: Path) -> None:
    as_file.behaviour.files = 3
    as_file.cpu_facts = CpuFacts(mixed=True)
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": None}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert NOTE_UNPINNED_MIXED_CORES not in _codes(capture)


def test_nothing_is_written_or_printed_while_a_launch_runs(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture_file = tmp_path / "run" / FILE_CAPTURE
    seen: list[tuple[int, int, str]] = []

    def during(request: LaunchRequest) -> None:
        if request.phase != "round" or request.round != 2:
            return
        capsys.readouterr()
        before = capture_file.stat().st_size
        world.resolved[0].ctx.note("made_up_note", f"said during launch {request.seq}")
        seen.append((before, capture_file.stat().st_size, capsys.readouterr().err))

    world.behaviour.during = during
    capture = _run(world, tmp_path)
    assert seen and all(before == after and err == "" for before, after, err in seen)
    assert _codes(capture).count("made_up_note") == len(seen)


def test_the_end_record_carries_the_hash_and_nothing_follows_it(
    world: World, tmp_path: Path
) -> None:
    capture = _run(world, tmp_path)
    assert capture.source is not None and capture.source.torn is False
    assert capture.end is not None
    assert capture.end.sha256_of_preceding is not None
    assert capture.end.discard_sha256 is not None and len(capture.end.discard_sha256) == 64
    assert _records(tmp_path)[-1]["t"] == "end"


# ---------------------------------------------------------------------------
# Result files
# ---------------------------------------------------------------------------


def test_sides_that_are_files_are_read_round_by_round(as_file: World, tmp_path: Path) -> None:
    as_file.behaviour.files = 3
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": None}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert _rounds(capture) == [(r, None, n) for r in (1, 2, 3) for n in ("new", "old")]
    assert capture.lineup is not None and capture.lineup.schedule is None
    assert not (tmp_path / "run" / FILE_PLAN).exists()
    assert as_file.witness_starts == 0
    assert as_file.prepared == []
    assert [s.name for s in capture.sides] == ["new", "old"]


class _TenfoldDriver:
    """Reads like the made-up driver and gives ten times its ``work``."""

    name: str = "tenfold"
    api_version: int = API_VERSION
    where: str = "in_side"
    clock_cases: tuple[str, ...] = ("wall",)

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        return [
            dataclasses.replace(s, value=s.value * 10) if s.case == "work" else s
            for s in self.inner.read(ctx, artifacts)
        ]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return list(self.inner.default_primary(samples))


def test_a_file_side_that_changed_during_the_run_is_refused(as_file: World, tmp_path: Path) -> None:
    as_file.behaviour.files = 3
    as_file.behaviour.changed_after = 1
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": None}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    refusal = _refused(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert refusal.code == "E_SIDE_CHANGED"
    assert refusal.exit_code == 5
    capture = _read(tmp_path)
    assert capture.end is not None and capture.end.status == "failed"
    assert capture.end.rounds_completed == 3


def test_a_file_side_with_its_own_format_is_read_by_that_driver(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "tenfold", _TenfoldDriver(registry.driver("fakedriver")))
    as_file.behaviour.files = 3
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": "tenfold"}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert _values(capture, "new", "work") == [20.0, 20.0, 20.0]
    assert _values(capture, "old", "work") == [3.0, 3.0, 3.0]


class _VersionedDriver(_TenfoldDriver):
    """Reports a tool version found in the result file the side handed over."""

    name: str = "versioned"

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        if ctx.result_file is None or ctx.rc != 0 or "run_s" not in ctx.timing:
            raise Refusal("E_LAUNCH_FAILED", "found no output file")
        return ToolVersion(tool="made-up-tool", version="1.2.3")


def test_a_file_side_driver_reads_its_version_from_the_same_context_as_its_cases(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "versioned", _VersionedDriver(registry.driver("fakedriver")))
    as_file.behaviour.files = 3
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": "versioned"}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert capture.complete
    versions = {x.name: x.tool_version for x in capture.launches}
    assert versions == {"new": "1.2.3", "old": None}


def test_a_run_of_file_sides_read_by_two_drivers_records_each_and_is_flagged(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "versioned", _VersionedDriver(registry.driver("fakedriver")))
    as_file.behaviour.files = 3
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": "versioned"}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert _read(tmp_path).side_drivers() == {"new": "versioned", "old": "fakedriver"}
    results = pairbench.analyse(capture)
    assert {s.name: s.driver for s in results.sides} == {
        "new": DriverInfo(name=None, tool_versions=("1.2.3",)),
        "old": DriverInfo(name=None, tool_versions=()),
    }
    assert NOTE_DRIVERS_DIFFER in [n.code for n in results.notes]


class _PathDriver(_TenfoldDriver):
    """Names its ``work`` case after a file, by an absolute path, as a test id may."""

    name: str = "pathnamed"

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        return [
            dataclasses.replace(s, case="test_read[/made/up/home/data.csv]")
            if s.case == "work"
            else s
            for s in self.inner.read(ctx, artifacts)
        ]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return [s.case for s in samples if s.case.startswith("test_read")]


def test_a_case_id_a_driver_reads_is_recorded_with_its_absolute_paths_cut(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "pathnamed", _PathDriver(registry.driver("fakedriver")))
    as_file.behaviour.files = 3
    sides = tuple(
        Side(name=n, kind="file", spec={"paths": [f"{n}-*.json"], "format": "pathnamed"})
        for n in ("new", "old")
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert capture.complete
    assert _values(capture, "new", "test_read[data.csv]") == [2.0, 2.0, 2.0]
    assert "/made/up" not in (tmp_path / "run" / FILE_CAPTURE).read_text()
    assert [c.id for c in capture.cases if c.primary] == ["test_read[data.csv]"]


class _TwoFoldersDriver(_TenfoldDriver):
    """Gives its ``work`` case twice, under two ids that differ only in a folder."""

    name: str = "made-up-plugin-driver"

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        read = self.inner.read(ctx, artifacts)
        work = [s for s in read if s.case == "work"]
        return [
            *(s for s in read if s.case != "work"),
            *(dataclasses.replace(s, case="test_read[/made/up/a/in.csv]") for s in work),
            *(dataclasses.replace(s, case="test_read[/made/up/b/in.csv]") for s in work),
        ]


def test_two_case_ids_shown_alike_are_refused_naming_the_side_never_the_driver(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(
        GROUP_DRIVERS, "made-up-plugin-driver", _TwoFoldersDriver(registry.driver("fakedriver"))
    )
    as_file.behaviour.files = 3
    sides = tuple(
        Side(
            name=n, kind="file", spec={"paths": [f"{n}-*.json"], "format": "made-up-plugin-driver"}
        )
        for n in ("new", "old")
    )
    refusal = _refused(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert (refusal.code, refusal.exit_code) == ("E_USAGE", 2)
    assert refusal.message.startswith(("side 'new': two different cases", "side 'old': two"))
    assert "'test_read[in.csv]'" in refusal.message
    assert "made-up-plugin-driver" not in refusal.message
    assert "/made/up" not in refusal.message


class _TemplatedDriver(_TenfoldDriver):
    """Names its cases as Google Benchmark names a templated benchmark over a range."""

    name: str = "templated"

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        read = self.inner.read(ctx, artifacts)
        work = [s for s in read if s.case == "work"]
        return [
            *(s for s in read if s.case != "work"),
            *(
                dataclasses.replace(s, case=f"BM_made_up<int>/{n}{part}")
                for s in work
                for n in (8, 64)
                for part in ("", "/cpu_time")
            ),
        ]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return [s.case for s in samples if s.case.startswith("BM_")]


def test_case_ids_whose_parts_are_joined_by_a_slash_are_recorded_as_read(
    as_file: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "templated", _TemplatedDriver(registry.driver("fakedriver")))
    as_file.behaviour.files = 3
    sides = tuple(
        Side(name=n, kind="file", spec={"paths": [f"{n}-*.json"], "format": "templated"})
        for n in ("new", "old")
    )
    capture = _run(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert capture.complete
    assert [c.id for c in capture.cases if c.id.startswith("BM_")] == [
        "BM_made_up<int>/8",
        "BM_made_up<int>/8/cpu_time",
        "BM_made_up<int>/64",
        "BM_made_up<int>/64/cpu_time",
    ]


def test_a_file_side_with_an_unknown_format_is_refused_before_anything(
    as_file: World, tmp_path: Path
) -> None:
    as_file.behaviour.files = 3
    sides = (
        Side(name="new", kind="file", spec={"paths": ["new-*.json"], "format": "absent"}),
        Side(name="old", kind="file", spec={"paths": ["old-*.json"], "format": None}),
    )
    refusal = _refused(as_file, tmp_path, _experiment(sides=sides, run={}))
    assert refusal.code == "E_USAGE"
    assert refusal.exit_code == EXIT_USAGE
    assert not (tmp_path / "run").exists()
    assert as_file.resolved == []


# ---------------------------------------------------------------------------
# The plan command's look-ups, the explain step and profiles
# ---------------------------------------------------------------------------


def test_look_up_sides_returns_each_side_in_order(world: World) -> None:
    found = look_up_sides(_experiment())
    assert list(found) == ["new", "old"]
    assert found["new"].status == "identified"


def test_look_up_sides_refuses_files_and_same_sides(world: World) -> None:
    sides = (
        Side(name="new", kind="fake", spec={"argv": ["./same"]}),
        Side(name="old", kind="fake", spec={"argv": ["./same"]}),
    )
    with pytest.raises(Refusal) as caught:
        look_up_sides(_experiment(sides=sides))
    assert caught.value.code == "E_SAME_SIDE"
    assert caught.value.exit_code == 3
    files = (
        Side(name="new", kind="file", spec={"paths": ["a"], "format": None}),
        Side(name="old", kind="file", spec={"paths": ["b"], "format": None}),
    )
    with pytest.raises(Refusal) as caught:
        look_up_sides(_experiment(sides=files))
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_command_side_without_the_workload_mark_is_refused(as_cmd: World) -> None:
    sides = (
        Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
        Side(name="old", kind="cmd", spec={"argv": ["./old", "{workload}"]}),
    )
    with pytest.raises(Refusal) as caught:
        look_up_sides(dataclasses.replace(_experiment(sides=sides), workload=("work",)))
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert "{workload}" in caught.value.message


SERVE_SIDES = (
    Side(name="new", kind="serve", spec={"image": "example/new"}),
    Side(name="old", kind="serve", spec={"image": "example/old"}),
)


def test_a_serving_side_with_a_driver_that_sends_no_load_is_refused(world: World) -> None:
    with pytest.raises(Refusal) as caught:
        look_up_sides(_experiment(sides=SERVE_SIDES))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "side 'new' is a serving side and the driver 'fakedriver' sends it no load; "
        "set workload.driver to a load driver: aiperf, guidellm, vllm-bench"
    )
    assert world.resolved == []


def test_a_load_driver_with_a_built_in_side_that_is_not_a_server_is_refused(
    world: World,
) -> None:
    sides = (
        Side(name="new", kind="cmd", spec={"argv": ["./new"]}),
        Side(name="old", kind="cmd", spec={"argv": ["./old"]}),
    )
    experiment = dataclasses.replace(
        _experiment(sides=sides), driver="guidellm", load=LoadSettings(levels=(1, 4))
    )
    with pytest.raises(Refusal) as caught:
        look_up_sides(experiment)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert caught.value.message == (
        "the driver 'guidellm' sends load to a serving side, and side 'new' is a cmd side, "
        "which is not a server"
    )
    assert world.resolved == []


def test_a_load_driver_without_load_levels_is_refused_before_any_side_resolves(
    world: World,
) -> None:
    experiment = dataclasses.replace(_experiment(sides=SERVE_SIDES), driver="guidellm")
    with pytest.raises(Refusal) as caught:
        look_up_sides(experiment)
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)
    assert caught.value.message == (
        "the guidellm driver runs one load level after another; workload.levels lists none"
    )
    assert world.resolved == []


class _Instrument:
    name: str = "counters"
    tool_files: tuple[Path, ...] = ()

    def wrap(self, argv: Any, *, out: str, tools: Any) -> InstrumentedCommand:
        return InstrumentedCommand(argv=("made-up-instrument", *argv), outputs=(WORK_FILE,))


FINGERPRINTS = {"new": "new".ljust(64, "0"), "old": "old".ljust(64, "0")}


def test_an_explain_launch_runs_the_wrapped_command_untimed(world: World, tmp_path: Path) -> None:
    experiment = _experiment(gates={"locks": ("made-up.lock",)})
    session = open_explain(
        experiment, run_id="run-a", fingerprints=FINGERPRINTS, services=world.services()
    )
    assert world.locked == [("made-up.lock",)]
    assert session.command("new") == ("./new",)
    launched = session.launch("new", _Instrument(), tmp_path / "explain")
    request = world.requests[-1]
    assert request.phase == "explain"
    assert request.argv == ("made-up-instrument", "./new")
    assert launched.rc == 0
    assert launched.outputs == (tmp_path / "explain" / WORK_FILE,)
    assert world.witness_starts == 0
    session.close()
    session.close()
    assert world.released == 1


IMAGE_REF = "registry.example/made-up:1"


def _image_kind(config: dict[str, Any]) -> Any:
    """The built-in image kind, with an engine that answers from made-up image facts."""
    from pairbench.sides.base import Completed
    from pairbench.sides.container import ImageKind

    details = {
        "Id": "sha256:" + "ab" * 32,
        "RepoDigests": [f"registry.example/made-up@sha256:{'cd' * 32}"],
        "Os": "linux",
        "Architecture": "arm64",
        "Config": config,
    }

    def engine(argv: Any, **_: Any) -> Completed:
        verb = argv[1]
        if verb == "version":
            return Completed(0, "9.9.9\n")
        if verb == "info":
            return Completed(0, "{}")
        if verb == "image":
            return Completed(0, json.dumps(details))
        raise AssertionError(f"unexpected engine call: {argv}")

    def which(word: str, path: str | None = None) -> str | None:
        return "/made-up/bin/docker" if word == "docker" else None

    return ImageKind(runner=engine, which=which, environ={})


@pytest.mark.parametrize(
    ("args", "config", "command"),
    [
        ((), {"Entrypoint": ["python3"], "Cmd": ["app.py"]}, ("python3", "app.py")),
        (
            ("app.py", "--fast"),
            {"Entrypoint": ["python3"], "Cmd": None},
            ("python3", "app.py", "--fast"),
        ),
        (
            ("python3", "app.py"),
            {"Entrypoint": ["/entry.sh"], "Cmd": None},
            ("/entry.sh", "python3", "app.py"),
        ),
        ((), {"Entrypoint": None, "Cmd": ["python3", "-m", "app"]}, ("python3", "-m", "app")),
        ((), {"Entrypoint": None, "Cmd": None}, None),
    ],
    ids=[
        "entrypoint-and-default",
        "entrypoint-and-args",
        "shell-entrypoint",
        "default-only",
        "none",
    ],
)
def test_the_explain_command_of_an_image_side_is_its_whole_command_line(
    monkeypatch: pytest.MonkeyPatch,
    world: World,
    args: tuple[str, ...],
    config: dict[str, Any],
    command: tuple[str, ...] | None,
) -> None:
    kind = _image_kind(config)
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "image"), kind)
    sides = (
        Side.image("new", IMAGE_REF, args=args),
        Side.image("old", "registry.example/made-up:0"),
    )
    experiment = _experiment(sides=sides)
    ctx = SideContext(run_id="run-a", settings=experiment.launch, environ={})
    fingerprint = kind.resolve(sides[0], ctx).side.fingerprint
    session = open_explain(
        experiment, run_id="run-a", fingerprints={"new": fingerprint}, services=world.services()
    )
    assert session.command("new") == command
    session.close()


def test_an_explain_launch_gets_a_pad_of_length_zero(world: World, tmp_path: Path) -> None:
    experiment = _experiment(run={"quick": True, "vary_env_size": True})
    session = open_explain(
        experiment, run_id="run-a", fingerprints=FINGERPRINTS, services=world.services()
    )
    session.launch("new", _Instrument(), tmp_path / "explain")
    assert world.requests[-1].env == {ENV_PAD_VARIABLE: ""}
    session.close()


class _ClientDriver:
    """A driver that sends the load from the host to a server side."""

    name: str = "clientdriver"
    api_version: int = API_VERSION
    where: str = "client"
    clock_cases: tuple[str, ...] = ()

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        return []

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return []


def _start_server(request: LaunchRequest) -> None:
    if request.wrap_server is not None:
        request.wrap_server(("./serve",))


def test_an_explain_launch_of_a_server_keeps_the_instrument_outputs(
    world: World, tmp_path: Path
) -> None:
    registry.register(GROUP_DRIVERS, "clientdriver", _ClientDriver())
    world.behaviour.during = _start_server
    experiment = dataclasses.replace(_experiment(), driver="clientdriver")
    session = open_explain(
        experiment, run_id="run-a", fingerprints=FINGERPRINTS, services=world.services()
    )
    launched = session.launch("new", _Instrument(), tmp_path / "explain")
    request = world.requests[-1]
    assert request.argv is None
    assert request.wrap_server is not None
    assert launched.outputs == (tmp_path / "explain" / WORK_FILE,)
    session.close()


def test_an_explain_launch_refuses_twins_and_changed_sides(world: World) -> None:
    session = open_explain(
        _experiment(),
        run_id="run-a",
        fingerprints={"new": "1" * 64, "old": FINGERPRINTS["old"]},
        services=world.services(),
    )
    with pytest.raises(Refusal) as caught:
        session.command("new~same")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    with pytest.raises(Refusal) as caught:
        session.command("new")
    assert caught.value.code == "E_SIDE_CHANGED"
    assert caught.value.exit_code == 5
    session.close()


def test_open_explain_refuses_a_lock_it_cannot_take(world: World) -> None:
    world.lock_refused = True
    with pytest.raises(Refusal) as caught:
        open_explain(
            _experiment(gates={"locks": ("made-up.lock",)}),
            run_id="run-a",
            fingerprints=FINGERPRINTS,
            services=world.services(),
        )
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == 4


class _CountingGate(_Gate):
    def __init__(self, name: str) -> None:
        super().__init__(name, "fail")
        self.calls = 0

    def check(self, ctx: GateContext) -> GateRecord:
        self.calls += 1
        return super().check(ctx)


def test_the_explain_launches_take_the_locks_and_run_no_readiness_check(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    counting = {name: _CountingGate(name) for name in READINESS}
    for name, gate in counting.items():
        monkeypatch.setitem(registry._state.builtins, (GROUP_GATES, name), gate)
    experiment = _experiment(
        gates={
            "mode": "enforce",
            "locks": ("made-up.lock",),
            "stop_file": "made-up/hold.stop",
            "min_gpu_free_mib": 2000.0,
            "check_locks": ("made-up/other.lock",),
        }
    )
    session = open_explain(
        experiment, run_id="run-a", fingerprints=FINGERPRINTS, services=world.services()
    )
    session.close()
    assert world.locked == [("made-up.lock",)]
    assert [gate.calls for gate in counting.values()] == [0, 0, 0]


def test_profiles_are_recorded_under_the_run_folder(
    as_cmd: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = as_cmd
    _run(world, tmp_path, _experiment(sides=CMD_SIDES))
    run_dir = tmp_path / "run"
    written = record_profiles(run_dir, tool="nsys", services=world.services())
    assert written == ("profiles/new/work.txt", "profiles/old/work.txt")
    assert world.requests[-1].phase == "profile"
    assert world.requests[-1].argv == ("made-up-profiler", "./old")
    assert "a made-up licence note" in capsys.readouterr().err


def test_a_profile_folder_holds_the_side_name_as_a_file_name(as_cmd: World, tmp_path: Path) -> None:
    sides = (CMD_SIDES[0], Side(name="x/../../../y", kind="cmd", spec={"argv": ["./old"]}))
    _run(as_cmd, tmp_path, _experiment(sides=sides))
    written = record_profiles(tmp_path / "run", tool="nsys", services=as_cmd.services())
    assert written == ("profiles/new/work.txt", "profiles/x_.._.._.._y/work.txt")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["run"]
    assert (tmp_path / "run" / "profiles" / "x_.._.._.._y" / "work.txt").is_file()


def test_profiles_refuse_what_they_cannot_serve(as_cmd: World, tmp_path: Path) -> None:
    world = as_cmd
    _run(world, tmp_path, _experiment(sides=CMD_SIDES))
    run_dir = tmp_path / "run"
    with pytest.raises(Refusal) as caught:
        record_profiles(run_dir, tool="perf", services=world.services())
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    with pytest.raises(Refusal) as caught:
        record_profiles(run_dir, tool="nsys", case="absent", services=world.services())
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    world.profiler_missing = True
    with pytest.raises(Refusal) as caught:
        record_profiles(run_dir, tool="nsys", services=world.services())
    assert caught.value.code == "E_PROFILER_MISSING"
    assert caught.value.exit_code == 3


# What a load step prints may hold the values of its command line: only its owner may read it.
PRIVATE_MODE = 0o600


@pytest.mark.parametrize("umask", [0o000, 0o022], ids=["umask-000", "umask-022"])
def test_a_load_step_s_output_files_are_readable_by_their_owner_only(
    tmp_path: Path, umask: int
) -> None:
    from pairbench.runner import _run_step

    old = os.umask(umask)
    try:
        rc = _run_step([sys.executable, "-c", "print('made-up load')"], {}, tmp_path, 1)
    finally:
        os.umask(old)
    assert rc == 0
    for name in ("load-1.stdout.txt", "load-1.stderr.txt"):
        assert (tmp_path / name).stat().st_mode & 0o777 == PRIVATE_MODE
    assert (tmp_path / "load-1.stdout.txt").read_text(encoding="utf-8") == "made-up load\n"
