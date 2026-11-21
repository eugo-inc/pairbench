# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The neighbour census: other running containers, the CPU each used over one
second, and the CPUs each may use.

1. A container that is not pinned to CPUs and uses more than
   ``gates.census.max_busy_cores`` fails the check.
2. A container allowed on CPUs that share a last-level cache with the pinned
   set, and using more than that, fails the check.
3. Without access to the container engine the census is ``unavailable``.

With no CPU set pinned every CPU may run a launch, so a pinned container that
uses more than the limit fails the check too. The pinned set is that of every
side: each side's own set where it gives itself one, and a run with one
unpinned side counts as a run with nothing pinned. The census looks at CPUs
only: the GPUs a container may use are not read; the quiet check counts the
other compute processes on the selected GPUs.

The containers are listed with the engine's ``ps`` command and described
with its ``inspect`` command in the format ``INSPECT_FORMAT``; an answer
that does not parse leaves the containers unread. On a Linux host the CPU
used comes from each container's
cgroup counter (``cpu.stat`` ``usage_usec`` under cgroup v2,
``cpuacct.usage`` under v1, https://docs.kernel.org/admin-guide/cgroup-v2.html);
elsewhere from the engine's own ``stats`` command, and the record says so.
The record's detail counts the containers seen and those whose CPU use
could not be read, and lists each offender with its name, its CPUs, the
cores it used and the rule it broke. It holds no container id and no name
of a container that broke no rule; the reason a results document shows only
counts the offenders.
"""

from __future__ import annotations

import math
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from pairbench.api import API_VERSION, ENGINES, DoctorReport, GateContext, find_engine
from pairbench.gates.cache import sharing_cache
from pairbench.gates.occupancy import Run, run_command
from pairbench.gates.platform import (
    Platform,
    Root,
    System,
    all_pinned,
    format_cpu_list,
    make_record,
    parse_cpu_list,
    side_launches,
    this_system,
)
from pairbench.model import GateRecord, GateStatus

NAME: Final = "census"
WINDOW_S: Final = 1.0
ENGINE_TIMEOUT_S: Final = 30.0
INSPECT_FORMAT: Final = "{{.Id}}\t{{.Name}}\t{{.HostConfig.CpusetCpus}}\t{{.State.Pid}}"
STATS_FORMAT: Final = "{{.ID}}\t{{.CPUPerc}}"


@dataclass(frozen=True)
class Neighbour:
    """One running container: its id, name, allowed CPUs (``None``: any) and first process."""

    id: str
    name: str
    cpus: frozenset[int] | None
    pid: int | None


def parse_inspect(text: str) -> list[Neighbour] | None:
    """Read the lines of ``INSPECT_FORMAT``; ``None`` when a line does not parse."""
    found: list[Neighbour] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            return None
        ident, name, cpuset, pid = (p.strip() for p in parts)
        try:
            cpus = parse_cpu_list(cpuset) if cpuset else None
        except ValueError:
            return None
        found.append(
            Neighbour(
                id=ident,
                name=name.lstrip("/"),
                cpus=cpus or None,
                pid=int(pid) if pid.isdigit() and int(pid) > 0 else None,
            )
        )
    return found


def parse_stats(text: str) -> dict[str, float]:
    """Read ``ID<TAB>12.5%`` lines into cores used per container id (100% is one core).

    A figure that is not a finite number at or above zero is left out, so
    its container stays unread.
    """
    used: dict[str, float] = {}
    for raw in text.splitlines():
        ident, sep, percent = raw.partition("\t")
        if not sep:
            continue
        value = percent.strip().rstrip("%").strip()
        try:
            cores = float(value) / 100.0
        except ValueError:
            continue
        if math.isfinite(cores) and cores >= 0:
            used[ident.strip()] = cores
    return used


def _cgroup_counter(root: Root, pid: int) -> float | None:
    """The CPU seconds a process's cgroup has used, or ``None``."""
    text = root.text(f"proc/{pid}/cgroup")
    if text is None:
        return None
    for raw in text.splitlines():
        hierarchy, _, rest = raw.partition(":")
        controllers, _, path = rest.partition(":")
        path = path.strip().lstrip("/")
        if hierarchy == "0" and controllers == "":
            stat = root.text("/".join(p for p in ("sys/fs/cgroup", path, "cpu.stat") if p))
            for line in (stat or "").splitlines():
                key, _, value = line.partition(" ")
                if key == "usage_usec" and value.strip().isdigit():
                    return int(value) / 1e6
        elif "cpuacct" in controllers.split(","):
            for folder in ("sys/fs/cgroup/cpuacct", "sys/fs/cgroup/cpu,cpuacct"):
                usage = root.line("/".join(p for p in (folder, path, "cpuacct.usage") if p))
                if usage and usage.isdigit():
                    return int(usage) / 1e9
    return None


class CensusGate:
    """The neighbour census (``api.Gate``)."""

    name: Final = NAME
    api_version: Final = API_VERSION

    def __init__(
        self,
        *,
        root: Root | None = None,
        system: System | None = None,
        run: Run = run_command,
        which: Callable[[str], str | None] = shutil.which,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        window_s: float = WINDOW_S,
    ) -> None:
        self._root = root or Root()
        self._system = system
        self._run = run
        self._which = which
        self._clock = clock
        self._sleep = sleep
        self._window_s = window_s

    def _engine(self, ctx: GateContext) -> str | None:
        found = [engine for engine in ENGINES if self._which(engine)]
        return find_engine(ctx.launch.engine, found, ctx.environ)

    def check(self, ctx: GateContext) -> GateRecord:
        """Run the check once and report."""
        platform = Platform.of(ctx, self._system)
        scope = "engine_vm" if platform.system == "darwin" else "engine"
        label = " (scoped to the engine's virtual machine)" if scope == "engine_vm" else ""
        base: dict[str, Any] = {"where": platform.where, "scope": scope}
        engine = self._engine(ctx)
        if engine is None:
            return make_record(
                NAME, ctx, "unavailable", "no container engine could be reached", **base
            )
        base["engine"] = engine
        rc, out = self._run([engine, "ps", "--no-trunc", "--format", "{{.ID}}"], ENGINE_TIMEOUT_S)
        if rc != 0:
            return make_record(
                NAME,
                ctx,
                "unavailable",
                "the container engine could not be reached",
                rc=rc,
                **base,
            )
        ids = [line.strip() for line in out.splitlines() if line.strip()]
        if not ids:
            return make_record(NAME, ctx, "pass", containers=0, **base)
        rc, out = self._run([engine, "inspect", "--format", INSPECT_FORMAT, *ids], ENGINE_TIMEOUT_S)
        neighbours = parse_inspect(out) or []
        seen = {n.id for n in neighbours}
        missing = [i for i in ids if not any(n.startswith(i) or i.startswith(n) for n in seen)]
        use_cgroup = platform.system == "linux" and not platform.in_container
        used, source = self._cpu_used(engine, neighbours, use_cgroup)
        base["source"] = source
        limit = ctx.gates.census.max_busy_cores
        pinned = None
        sharing: frozenset[int] | None = None
        cpus = all_pinned(cpus for cpus, _gpus in side_launches(ctx))
        if cpus is not None:
            try:
                pinned = parse_cpu_list(cpus)
            except ValueError:
                pinned = None
            if pinned:
                sharing = sharing_cache(self._root, pinned) if platform.system == "linux" else None
        offenders: list[dict[str, Any]] = []
        unread = len(missing)
        for n in neighbours:
            cores = used.get(n.id)
            row = {
                "name": n.name,
                "cpus": None if n.cpus is None else format_cpu_list(n.cpus),
                "cores": None if cores is None else round(cores, 4),
            }
            if cores is None:
                unread += 1
                continue
            if cores <= limit:
                continue
            if n.cpus is None:
                offenders.append({**row, "rule": "unpinned"})
            elif pinned is None:
                offenders.append({**row, "rule": "nothing_pinned"})
            elif sharing is None or n.cpus & sharing:
                offenders.append({**row, "rule": "shares_cache"})
        detail = {**base, "containers": len(ids), "offenders": offenders, "unread": unread}
        detail["max_busy_cores"] = limit
        status: GateStatus
        if offenders:
            status = "fail"
            message = (
                f"{len(offenders)} other container(s) used more than {limit:g} cores "
                "where launches run"
            )
        elif unread:
            status = "degraded"
            message = f"the CPU use of {unread} container(s) could not be read"
        else:
            status, message = "pass", ""
        return make_record(NAME, ctx, status, message + label if message else "", **detail)

    def _cpu_used(
        self, engine: str, neighbours: Sequence[Neighbour], use_cgroup: bool
    ) -> tuple[dict[str, float], str]:
        """The cores each container used over one window, and where the figure came from."""
        if use_cgroup:
            before = {
                n.id: _cgroup_counter(self._root, n.pid) for n in neighbours if n.pid is not None
            }
            start = self._clock()
            self._sleep(self._window_s)
            after = {
                n.id: _cgroup_counter(self._root, n.pid) for n in neighbours if n.pid is not None
            }
            elapsed = self._clock() - start
            used: dict[str, float] = {}
            if elapsed > 0:
                for ident, first in before.items():
                    last = after.get(ident)
                    if first is not None and last is not None and last >= first:
                        used[ident] = (last - first) / elapsed
            return used, "cgroup"
        rc, out = self._run(
            [engine, "stats", "--no-stream", "--format", STATS_FORMAT],
            ENGINE_TIMEOUT_S,
        )
        if rc != 0:
            return {}, "engine_stats"
        by_id = parse_stats(out)
        used = {}
        for n in neighbours:
            for ident, cores in by_id.items():
                if ident and (n.id.startswith(ident) or ident.startswith(n.id)):
                    used[n.id] = cores
                    break
        return used, "engine_stats"

    def doctor(self) -> DoctorReport:
        """What this platform lets the census do."""
        found = [engine for engine in ENGINES if self._which(engine)]
        if not found:
            return DoctorReport("unavailable", "no container engine found")
        if (this_system() if self._system is None else self._system) == "darwin":
            return DoctorReport(
                "degraded", "scoped to the engine's virtual machine", {"engines": found}
            )
        return DoctorReport("ok", f"containers listed with {found[0]}", {"engines": found})
