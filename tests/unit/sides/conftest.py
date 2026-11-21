# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Stand-ins for the machine, shared by the tests of the side kinds.

* ``FakeRunner`` answers untimed commands (engine calls, interpreter
  questions, ``identify`` commands) from a handler and records every call.
* ``RecordingHost`` replaces the calls of a timed launch on the host. It
  records the order of the calls and moves a made-up clock forward by the
  run time of each process when the process is collected.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import pytest

from pairbench.sides.base import Completed, HostProcesses, HostRun, ProcessUsage


@dataclass(frozen=True)
class Call:
    argv: tuple[str, ...]
    env: Mapping[str, str] | None
    cwd: str | None
    timeout_s: float | None


class FakeRunner:
    """A ``CommandRunner`` that answers from ``handler(argv)`` and records each call."""

    def __init__(self, handler: Callable[[tuple[str, ...]], Completed]) -> None:
        self.handler = handler
        self.calls: list[Call] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed:
        call = Call(tuple(argv), dict(env) if env is not None else None, cwd, timeout_s)
        self.calls.append(call)
        return self.handler(call.argv)

    def argvs(self) -> list[tuple[str, ...]]:
        return [call.argv for call in self.calls]


class RecordingHost(HostProcesses):
    """A ``HostProcesses`` that starts nothing and records the order of the calls.

    ``durations_ns`` and ``rcs`` give, per process in the order started, how
    far the clock moves while it runs and the exit code it reports.
    ``usages`` gives what the exit status call reports for each.
    """

    def __init__(
        self,
        *,
        durations_ns: Sequence[int] = (3_000_000_000,),
        rcs: Sequence[int] = (0,),
        usages: Sequence[ProcessUsage | None] | None = None,
        spawn_error: OSError | None = None,
        interrupt_on_reap: bool = False,
        home_cpus: frozenset[int] | None = None,
        refused: frozenset[int] | None = None,
    ) -> None:
        super().__init__()
        self.log: list[str] = []
        self.now = 1_000_000_000
        self.durations_ns = list(durations_ns)
        self.rcs = list(rcs)
        self.usages = list(usages) if usages is not None else [None] * len(self.rcs)
        self.spawn_error = spawn_error
        self.interrupt_on_reap = interrupt_on_reap
        self.runs: list[HostRun] = []
        self.killed: list[int] = []
        self.pinned: frozenset[int] | None = None
        self.home_cpus = home_cpus
        self.refused = refused
        self._index: dict[int, int] = {}

    def clock(self) -> int:
        self.log.append("clock")
        return self.now

    def open_output(self, path: Path) -> IO[bytes]:
        self.log.append("open")
        return path.open("wb")

    def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
        self.log.append("spawn")
        if self.spawn_error is not None:
            raise self.spawn_error
        self.runs.append(run)
        pid = 4000 + len(self.runs)
        self._index[pid] = len(self.runs) - 1
        return pid

    def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
        self.log.append("reap")
        if self.interrupt_on_reap:
            self.interrupt_on_reap = False
            raise KeyboardInterrupt
        index = self._index[pid]
        self.now += self.durations_ns[index]
        return self.rcs[index], self.usages[index]

    def kill(self, pid: int) -> None:
        self.log.append("kill")
        self.killed.append(pid)

    def pin(self, cpus: frozenset[int] | None) -> Any:
        self.log.append("pin")
        if cpus is not None and cpus == self.refused:
            raise OSError(22, "Invalid argument")
        self.pinned = cpus
        return "token"

    def home(self) -> frozenset[int] | None:
        return self.home_cpus

    def unpin(self, token: Any) -> None:
        self.log.append("unpin")


@pytest.fixture
def fake_runner() -> type[FakeRunner]:
    return FakeRunner


@pytest.fixture
def recording_host() -> type[RecordingHost]:
    return RecordingHost
