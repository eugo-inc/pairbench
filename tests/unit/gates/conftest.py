# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Shared pieces of the machine-check tests: a synthetic kernel tree, a fake
clock, fake GPUs and a check context.

Every test here reads a synthetic tree under a temporary folder. A safety
net makes any call that would start a process or move the test process onto
other CPUs fail the test at once.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import GateContext
from pairbench.gates.platform import Root
from pairbench.model import GateMode, GateSettings, LaunchSettings


def _forbidden(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("a machine-check test reached the real machine")


@pytest.fixture(autouse=True)
def _no_real_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "call", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    if hasattr(os, "sched_setaffinity"):
        monkeypatch.setattr(os, "sched_setaffinity", _forbidden)


class Tree:
    """A synthetic root folder holding the kernel files a test needs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.root = Root(path)

    def write(self, rel: str, text: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def online(self, cpus: str) -> None:
        self.write("sys/devices/system/cpu/online", cpus + "\n")

    def cache(self, cpu: int, index: int, level: int, kind: str, shared: str) -> None:
        base = f"sys/devices/system/cpu/cpu{cpu}/cache/index{index}"
        self.write(f"{base}/level", f"{level}\n")
        self.write(f"{base}/type", f"{kind}\n")
        self.write(f"{base}/shared_cpu_list", f"{shared}\n")

    def llc(self, domains: Sequence[Sequence[int]]) -> None:
        """Give every CPU an L1 data cache of its own and the last-level cache of its domain."""
        for domain in domains:
            listed = ",".join(str(c) for c in domain)
            for cpu in domain:
                self.cache(cpu, 0, 1, "Data", str(cpu))
                self.cache(cpu, 1, 1, "Instruction", str(cpu))
                self.cache(cpu, 2, 3, "Unified", listed)

    def midr(self, cpu: int, value: str) -> None:
        self.write(f"sys/devices/system/cpu/cpu{cpu}/regs/identification/midr_el1", value + "\n")

    def khz(self, cpu: int, khz: int) -> None:
        self.write(f"sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq", f"{khz}\n")

    def stat(self, per_cpu: Mapping[int, tuple[int, int]]) -> None:
        """Write ``proc/stat`` with, per CPU, the busy ticks (as user time) and the idle ticks."""
        busy = sum(b for b, _ in per_cpu.values())
        idle = sum(i for _, i in per_cpu.values())
        lines = [f"cpu  {busy} 0 0 {idle} 0 0 0 0 0 0"]
        lines += [f"cpu{c} {b} 0 0 {i} 0 0 0 0 0 0" for c, (b, i) in sorted(per_cpu.items())]
        lines += ["intr 0", "ctxt 0", "btime 0", "processes 1"]
        self.write("proc/stat", "\n".join(lines) + "\n")

    def process(self, pid: int, parent: int, name: str = "work") -> None:
        """Write ``proc/PID/stat`` naming the parent process."""
        self.write(f"proc/{pid}/stat", f"{pid} ({name}) S {parent} {pid} {pid} 0 -1 0\n")


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path / "root")


@dataclass
class FakeClock:
    """A monotonic clock that moves only when ``sleep`` is called.

    ``on_sleep`` runs after every sleep, for example to write the next
    reading of the processor counters.
    """

    now: float = 100.0
    slept: list[float] = field(default_factory=list)
    on_sleep: Callable[[int], None] | None = None

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.slept))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@dataclass
class FakeGpu:
    """A GPU source that answers from scripts; an answer of ``None`` is a failed read.

    Each script is used in order and its last answer repeats.
    """

    pids: list[tuple[int, ...] | None] = field(default_factory=lambda: [()])
    masks: list[tuple[int, ...] | None] = field(default_factory=lambda: [(0,)])
    memory: float | None = 0.0
    indices: tuple[int, ...] | None = None
    free: list[tuple[tuple[int, float], ...] | None] = field(
        default_factory=lambda: [((0, 81000.0),)]
    )
    reads: int = 0
    free_reads: int = 0

    @staticmethod
    def _next(script: list[Any]) -> Any:
        return script.pop(0) if len(script) > 1 else script[0]

    def processes(self) -> tuple[int, ...] | None:
        self.reads += 1
        return self._next(self.pids)

    def memory_used_mib(self) -> float | None:
        return self.memory

    def reason_masks(self) -> tuple[int, ...] | None:
        return self._next(self.masks)

    def present(self) -> tuple[int, ...] | None:
        return self.indices

    def memory_free_mib(self) -> tuple[tuple[int, float], ...] | None:
        self.free_reads += 1
        return self._next(self.free)


@pytest.fixture
def make_ctx() -> Callable[..., GateContext]:
    def build(
        *,
        mode: GateMode = "warn",
        gates: GateSettings | None = None,
        launch: LaunchSettings | None = None,
        phase: str = "before",
        in_container: bool = False,
        ci: bool = False,
        notes: list[tuple[str, str]] | None = None,
        environ: Mapping[str, str] | None = None,
        sides: Mapping[str, LaunchSettings] | None = None,
    ) -> GateContext:
        sink = notes if notes is not None else []
        return GateContext(
            mode=mode,
            gates=gates or GateSettings(),
            launch=launch or LaunchSettings(),
            phase=phase,  # type: ignore[arg-type]
            environ=dict(environ or {}),
            in_container=in_container,
            ci=ci,
            note=lambda code, message: sink.append((code, message)),
            sides=dict(sides or {}),
        )

    return build


@pytest.fixture
def stat_script(
    tree: Tree, clock: FakeClock
) -> Callable[[Sequence[Mapping[int, tuple[int, int]]]], None]:
    """Write the first reading now and each next one when the clock sleeps."""

    def install(readings: Sequence[Mapping[int, tuple[int, int]]]) -> None:
        tree.stat(readings[0])

        def advance(count: int) -> None:
            tree.stat(readings[min(count, len(readings) - 1)])

        clock.on_sleep = advance

    return install


def cumulative(
    start: Mapping[int, tuple[int, int]], steps: Sequence[Mapping[int, tuple[int, int]]]
) -> Iterator[dict[int, tuple[int, int]]]:
    """Readings that add each step's busy and idle ticks to the one before."""
    current = dict(start)
    yield dict(current)
    for step in steps:
        current = {c: (current[c][0] + step[c][0], current[c][1] + step[c][1]) for c in current}
        yield dict(current)


@pytest.fixture
def readings() -> Callable[..., list[dict[int, tuple[int, int]]]]:
    """Build cumulative readings from per-interval busy and idle ticks."""

    def build(steps: Sequence[Mapping[int, tuple[int, int]]]) -> list[dict[int, tuple[int, int]]]:
        start = dict.fromkeys(steps[0], (1000, 1000))
        return list(cumulative(start, steps))

    return build


@pytest.fixture
def fake_gpu() -> type[FakeGpu]:
    """The fake GPU source class, to build one per test."""
    return FakeGpu
