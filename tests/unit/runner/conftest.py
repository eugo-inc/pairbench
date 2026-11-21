# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Made-up sides, drivers, checks and services for the runner's tests. Nothing real is started."""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import pytest

from pairbench import registry
from pairbench.api import (
    API_VERSION,
    GROUP_DRIVERS,
    GROUP_SIDE_KINDS,
    CpuFacts,
    DriverContext,
    Endpoint,
    EnergyReading,
    EnergyWindow,
    Invocation,
    LaunchOutcome,
    LaunchRequest,
    MachineChecks,
    ProfiledCommand,
    RunServices,
    Sample,
    SideContext,
    SideLookup,
    ToolCpus,
    Window,
    run_folders,
)
from pairbench.errors import Refusal
from pairbench.gates.cpus import cpu_facts
from pairbench.gates.occupancy import absent_message, missing_gpus
from pairbench.gates.platform import Root
from pairbench.model import (
    CpuRecord,
    DiscardThresholds,
    EnergySettings,
    EngineInfo,
    MachineRecord,
    RoundWitness,
    SetAside,
    Side,
    Witness,
    set_aside,
)

ZERO_ID = "0" * 64
WORK_FILE = "work.txt"
ENDPOINT = Endpoint(base_url="http://made-up.invalid:8000")
ENERGY_J = 7.5
POWER_W = 2.5


@dataclasses.dataclass
class Behaviour:
    """What the made-up sides do. Tests change it before a run."""

    seconds: Mapping[str, float] = dataclasses.field(
        default_factory=lambda: {"new": 2.0, "old": 3.0}
    )
    second_seconds: float = 5.0
    work: Mapping[str, float] = dataclasses.field(default_factory=lambda: {"new": 2.0, "old": 3.0})
    cases: Callable[[LaunchRequest], Mapping[str, float]] | None = None
    fail_at: int | None = None
    # The exit code the launch of ``fail_at`` reports, and whether it ran into its timeout.
    fail_rc: int = 1
    timed_out: bool = False
    # The cause the launch of ``fail_at`` gives when it failed because its side
    # cannot run two commands in one start after all.
    fail_cannot_repeat: str | None = None
    interrupt_at: int | None = None
    during: Callable[[LaunchRequest], None] | None = None
    cannot_repeat: str | None = None
    changed_after: int | None = None
    usage: Mapping[str, float] = dataclasses.field(
        default_factory=lambda: {"rss_peak_bytes": 1000.0}
    )
    engine: EngineInfo | None = None
    # A side named here launches with its own engine in place of ``engine``.
    engines: Mapping[str, EngineInfo | None] = dataclasses.field(default_factory=dict)
    files: int | None = None
    side_samples: Callable[[LaunchRequest], Sequence[Sample]] | None = None
    serve: bool = False
    # The ``better`` of the case ``work`` and of the cases of ``cases``, and of ``wall``.
    better: Literal["lower", "higher", "none"] = "lower"
    wall_better: Literal["lower", "higher", "none"] = "lower"


class FakeResolved:
    """A resolved made-up side."""

    def __init__(self, side: Side, ctx: SideContext, world: World) -> None:
        self.world = world
        self.ctx = ctx
        identity = {"made_up": side.name}
        self._side = side.with_identity(identity, side.name.ljust(64, "0")[:64])
        self.closed = 0

    @property
    def side(self) -> Side:
        return self._side

    @property
    def command(self) -> tuple[str, ...] | None:
        argv = self._side.spec.get("argv")
        return tuple(argv) if argv else None

    @property
    def engine(self) -> EngineInfo | None:
        behaviour = self.world.behaviour
        return behaviour.engines.get(self._side.name, behaviour.engine)

    @property
    def rounds_available(self) -> int | None:
        return self.world.behaviour.files

    @property
    def cannot_repeat(self) -> str | None:
        return self.world.behaviour.cannot_repeat

    def identify(self) -> Mapping[str, Any]:
        changed = self.world.behaviour.changed_after
        if changed is not None and len(self.world.requests) >= changed:
            return {"made_up": self._side.name + "-changed"}
        return dict(self._side.identity)

    def artifacts_in_side(self, host: Path) -> str:
        return str(host)

    def tool_file_in_side(self, host: Path) -> str:
        return str(host)

    def launch(self, request: LaunchRequest) -> LaunchOutcome:
        world = self.world
        behaviour = world.behaviour
        world.requests.append(request)
        if behaviour.during is not None:
            behaviour.during(request)
        index = len(world.requests)
        if behaviour.interrupt_at == index:
            raise KeyboardInterrupt
        if behaviour.serve and request.load is not None:
            request.load(ENDPOINT)
        if request.phase == "cost":
            return LaunchOutcome(rc=0, timing={"run_s": 0.25, "launch_s": 0.25})
        source = self._side.name
        seconds = behaviour.seconds.get(source, 1.0)
        work = behaviour.work.get(source, 1.0)
        if request.second is not None:
            first, second = run_folders(request.artifacts, str(request.artifacts))
            (first[0] / WORK_FILE).write_text(f"{seconds}\n")
            (second[0] / WORK_FILE).write_text(f"{behaviour.second_seconds}\n")
            seconds += behaviour.second_seconds
        else:
            (request.artifacts / WORK_FILE).write_text(f"{work}\n")
        if behaviour.cases is not None:
            extra = behaviour.cases(request)
            lines = "".join(f"{k} {v}\n" for k, v in extra.items())
            (request.artifacts / "cases.txt").write_text(lines)
        failing = behaviour.fail_at == index
        rc = behaviour.fail_rc if failing else 0
        result_file = None
        if behaviour.files is not None:
            result_file = request.artifacts / f"file-{request.round}.txt"
            result_file.write_text(f"{work}\n")
        return LaunchOutcome(
            rc=rc,
            timing={"run_s": seconds, "launch_s": seconds, "user_s": 0.5, "sys_s": 0.25},
            cpu_s=0.75,
            usage=dict(behaviour.usage),
            result_file=result_file,
            samples=tuple(behaviour.side_samples(request)) if behaviour.side_samples else (),
            timed_out=failing and behaviour.timed_out,
            cannot_repeat=behaviour.fail_cannot_repeat if failing else None,
        )

    def close(self) -> None:
        self.closed += 1


class FakeKind:
    """A made-up side kind."""

    api_version: int = API_VERSION

    def __init__(self, world: World, name: str = "fake") -> None:
        self.world = world
        self.name = name

    def resolve(self, side: Side, ctx: SideContext) -> FakeResolved:
        resolved = FakeResolved(side, ctx, self.world)
        self.world.resolved.append(resolved)
        return resolved

    def look_up(self, side: Side, ctx: SideContext) -> SideLookup:
        return SideLookup(status="identified", identity={"made_up": side.name})


class FakeDriver:
    """Reads ``wall`` from the launch's clock and ``work`` from a file the side wrote."""

    name: str = "fakedriver"
    api_version: int = API_VERSION
    where: Literal["in_side", "client"] = "in_side"
    clock_cases: tuple[str, ...] = ("wall",)

    def __init__(self, world: World) -> None:
        self.world = world

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        self.world.prepared.append((ctx.artifacts, tuple(argv)))
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        folder = artifacts
        source = ctx.result_file if ctx.result_file is not None else folder / WORK_FILE
        better = self.world.behaviour.better
        out = [
            Sample(
                case="wall",
                metric="wall",
                unit="s",
                better=self.world.behaviour.wall_better,
                kind="time",
                value=float(ctx.timing["run_s"]),
            ),
            Sample(
                case="work",
                metric="work",
                unit="s",
                better=better,
                kind="time",
                value=float(source.read_text()),
            ),
        ]
        extra = folder / "cases.txt"
        if extra.exists():
            for line in extra.read_text().splitlines():
                case, value = line.rsplit(None, 1)
                out.append(
                    Sample(
                        case=case,
                        # A fixed metric, as a real driver gives: the id may hold a path.
                        metric="value",
                        unit="s",
                        better=better,
                        kind="time",
                        value=float(value),
                    )
                )
        return out

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return [s.case for s in samples if s.case != "wall"]


class FakeSampler:
    def __init__(self, world: World) -> None:
        self.world = world

    def stop(
        self, own_cpu_s: float | None, own_pid: int | None = None, second_pid: int | None = None
    ) -> Witness:
        self.world.witness_stops.append(own_cpu_s)
        return self.world.witness


class FakeLocks:
    def __init__(self, world: World) -> None:
        self.world = world

    def release(self) -> None:
        self.world.released += 1


class FakeChecks:
    def __init__(self, world: World) -> None:
        self.world = world

    def cpu_facts(self, cpus: str | None, *, allow_mixed: bool) -> CpuFacts:
        """The world's facts, or, given a made-up kernel tree, what the real check reads in it."""
        self.world.cpu_sets.append(cpus)
        if self.world.cpu_tree is not None:
            return cpu_facts(self.world.cpu_tree, "linux", cpus, allow_mixed=allow_mixed)
        return self.world.cpu_facts

    def leave_pinned(self, cpus: str | None) -> ToolCpus:
        """The world's answer, or, given the checks of this machine, a real move."""
        self.world.left.append(cpus)
        if self.world.moving is not None:
            return self.world.moving.leave_pinned(cpus)
        return self.world.tool_cpus

    def restore_cpus(self) -> None:
        self.world.restored += 1
        if self.world.moving is not None:
            self.world.moving.restore_cpus()

    def gpu_probe(self, gpus: str | None) -> None:
        """No probe; a selection naming a GPU the world lacks is refused as the real check does."""
        present = self.world.gpus_present
        if gpus is not None and present is not None:
            missing = missing_gpus(gpus, present)
            if missing:
                raise Refusal("E_USAGE", f"gpus {gpus}: {absent_message(missing, present)}")
        return None

    def acquire_locks(self, paths: Sequence[str], timeout_s: float) -> FakeLocks:
        if self.world.lock_refused:
            raise Refusal("E_LOCK", "a lock could not be taken")
        self.world.locked.append(tuple(paths))
        return FakeLocks(self.world)

    def start_witness(self, cpus: str | None, gpus: str | None) -> FakeSampler:
        self.world.witness_starts += 1
        return FakeSampler(self.world)

    def set_aside(
        self, thresholds: DiscardThresholds, witnesses: Sequence[RoundWitness]
    ) -> SetAside:
        self.world.set_aside_seen = list(witnesses)
        return set_aside(thresholds, witnesses)


class FakePower:
    """A power sampler that gives every window it is handed the same made-up energy."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.started = time.monotonic()

    def stop(self, windows: Sequence[Window]) -> EnergyReading:
        self.world.power_windows.append((self.started, tuple(windows)))
        return EnergyReading(
            source="made-up",
            sampler_ok=True,
            query_errors=0,
            windows=tuple(
                EnergyWindow(
                    label=w.label,
                    start_s=w.start_s,
                    end_s=w.end_s,
                    energy_j=ENERGY_J,
                    mean_power_w=POWER_W,
                    n_samples=12,
                )
                for w in windows
            ),
            notes=tuple(self.world.power_notes),
        )


class FakeMeter:
    def __init__(self, world: World) -> None:
        self.world = world

    def idle_power_w(self, gpus: str, settings: EnergySettings) -> float | None:
        self.world.idle_asked.append(gpus)
        return self.world.idle_power.get(gpus)

    def start(self, gpus: str, settings: EnergySettings) -> FakePower:
        if not settings.enabled:
            raise AssertionError("the meter is started only when energy is on")
        return FakePower(self.world)


class FakeFacts:
    def __init__(self, world: World) -> None:
        self.world = world

    def machine_record(
        self, *, gpus: str | None, node_type: str | None, environ: Mapping[str, str]
    ) -> MachineRecord:
        self.world.machine_gpus.append(gpus)
        return MachineRecord(os="linux", arch="x86_64", cpu=CpuRecord(model="cpu-a"))

    def tools(self) -> Sequence[Any]:
        return ()


class FakeProfiler:
    name: str = "nsys"
    licence_note: str = "a made-up licence note"

    def __init__(self, world: World) -> None:
        self.world = world

    def find(self) -> str | None:
        return None if self.world.profiler_missing else "/bin/made-up-profiler"

    def wrap(self, argv: Sequence[str], out: str) -> ProfiledCommand:
        return ProfiledCommand(argv=("made-up-profiler", *argv), outputs=(WORK_FILE,))


@dataclasses.dataclass
class World:
    """Everything the made-up plug-ins saw, and what they are told to do."""

    behaviour: Behaviour = dataclasses.field(default_factory=Behaviour)
    requests: list[LaunchRequest] = dataclasses.field(default_factory=list)
    resolved: list[FakeResolved] = dataclasses.field(default_factory=list)
    prepared: list[tuple[Path, tuple[str, ...]]] = dataclasses.field(default_factory=list)
    witness_starts: int = 0
    witness_stops: list[float | None] = dataclasses.field(default_factory=list)
    witness: Witness = dataclasses.field(default_factory=lambda: Witness(busy_cores=0.0))
    locked: list[tuple[str, ...]] = dataclasses.field(default_factory=list)
    released: int = 0
    lock_refused: bool = False
    profiler_missing: bool = False
    cpu_facts: CpuFacts = dataclasses.field(default_factory=CpuFacts)
    cpu_tree: Root | None = None
    cpu_sets: list[str | None] = dataclasses.field(default_factory=list)
    tool_cpus: ToolCpus = dataclasses.field(default_factory=lambda: ToolCpus(reason="not_pinned"))
    left: list[str | None] = dataclasses.field(default_factory=list)
    restored: int = 0
    # The machine checks of this machine, to move the tool's threads for real.
    moving: MachineChecks | None = None
    power_windows: list[tuple[float, tuple[Window, ...]]] = dataclasses.field(default_factory=list)
    power_notes: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    set_aside_seen: list[RoundWitness] = dataclasses.field(default_factory=list)
    machine_gpus: list[str | None] = dataclasses.field(default_factory=list)
    idle_asked: list[str] = dataclasses.field(default_factory=list)
    idle_power: dict[str, float] = dataclasses.field(default_factory=dict)
    # The GPUs the machine has; ``None`` when the probe cannot tell.
    gpus_present: tuple[int, ...] | None = None

    def services(self) -> RunServices:
        return RunServices(
            checks=FakeChecks(self),
            meter=FakeMeter(self),
            facts=FakeFacts(self),
            profiler=lambda tool: FakeProfiler(self),
        )


@pytest.fixture
def world() -> World:
    """A made-up world with the side kind ``fake`` and the driver ``fakedriver`` registered."""
    made = World()
    registry.register(GROUP_SIDE_KINDS, "fake", FakeKind(made))
    registry.register(GROUP_DRIVERS, "fakedriver", FakeDriver(made))
    return made


@pytest.fixture
def as_cmd(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Put the made-up side kind in place of the built-in ``cmd`` kind."""
    monkeypatch.setitem(registry._state.builtins, (GROUP_SIDE_KINDS, "cmd"), FakeKind(world, "cmd"))
    return world


@pytest.fixture
def as_file(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """Put the made-up side kind in place of the built-in ``file`` kind."""
    monkeypatch.setitem(
        registry._state.builtins, (GROUP_SIDE_KINDS, "file"), FakeKind(world, "file")
    )
    return world
