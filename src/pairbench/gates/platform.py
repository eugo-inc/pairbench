# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Where the checks run and how they read the machine.

Every read of the kernel's files goes through ``Root``, which reads paths
under a root folder: ``/`` on a real machine, a synthetic tree in the tests.
Every call that asks the operating system about CPUs goes through
``Affinity``, which the tests replace.

The formats read here are the ones the Linux kernel documents:
``/proc/stat`` (https://docs.kernel.org/filesystems/proc.html), the CPU
lists under ``/sys/devices/system/cpu``
(https://docs.kernel.org/admin-guide/cputopology.html) and the cgroup files
(https://docs.kernel.org/admin-guide/cgroup-v2.html).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from pairbench import model
from pairbench.api import GateContext
from pairbench.model import GateRecord, GateStatus

System = Literal["linux", "darwin", "other"]

# Where a check runs, as the columns of the behaviour table name it.
WHERE_HOST: Final = "linux_host"
WHERE_CONTAINER: Final = "container"
WHERE_MACOS: Final = "macos"
WHERE_CI: Final = "ci"
WHERE_OTHER: Final = "other"

# What each check does where it runs. ``full`` means the check works there;
# it does not mean the run waits.
BEHAVIOUR: Final[Mapping[str, Mapping[str, str]]] = {
    "quiet": {
        WHERE_HOST: "full",
        WHERE_CONTAINER: "machine-wide view, labelled",
        WHERE_MACOS: "load average only, degraded",
        WHERE_CI: "recorded; not waited on unless asked",
        WHERE_OTHER: "unavailable",
    },
    "cpus": {
        WHERE_HOST: "full",
        WHERE_CONTAINER: "limited to the container's own CPUs",
        WHERE_MACOS: "refused with the reason",
        WHERE_CI: "full",
        WHERE_OTHER: "refused with the reason",
    },
    "census": {
        WHERE_HOST: "full",
        WHERE_CONTAINER: "unavailable without the engine socket",
        WHERE_MACOS: "scoped to the engine's virtual machine, labelled",
        WHERE_CI: "full",
        WHERE_OTHER: "unavailable",
    },
    "locks": {
        WHERE_HOST: "full",
        WHERE_CONTAINER: "full",
        WHERE_MACOS: "full",
        WHERE_CI: "full",
        WHERE_OTHER: "full",
    },
    "disturbed_rounds": {
        WHERE_HOST: "full",
        WHERE_CONTAINER: "full",
        WHERE_MACOS: "off: no independent witness",
        WHERE_CI: "full",
        WHERE_OTHER: "off: no independent witness",
    },
}


def this_system(platform: str | None = None) -> System:
    """Name the operating system: ``linux``, ``darwin`` or ``other``."""
    name = sys.platform if platform is None else platform
    if name.startswith("linux"):
        return "linux"
    if name == "darwin":
        return "darwin"
    return "other"


@dataclass(frozen=True)
class Platform:
    """The facts a check needs about where it runs.

    ``in_container`` and ``ci`` come from the machine record, through the
    check's context; they are not detected here.
    """

    system: System
    in_container: bool = False
    ci: bool = False

    @property
    def where(self) -> str:
        """The column of the behaviour table this platform falls under.

        A platform other than Linux and macOS comes first, then macOS, then
        inside a container, then an automated pipeline, then a Linux host.
        """
        if self.system == "other":
            return WHERE_OTHER
        if self.system == "darwin":
            return WHERE_MACOS
        if self.in_container:
            return WHERE_CONTAINER
        if self.ci:
            return WHERE_CI
        return WHERE_HOST

    def behaviour(self, check: str) -> str:
        """What the named check does on this platform."""
        return BEHAVIOUR[check][self.where]

    @classmethod
    def of(cls, ctx: GateContext, system: System | None = None) -> Platform:
        """The platform of a check's context; ``system`` replaces the detected one."""
        return cls(
            system=this_system() if system is None else system,
            in_container=ctx.in_container,
            ci=ctx.ci,
        )


def make_record(
    name: str, ctx: GateContext, status: GateStatus, message: str = "", **detail: Any
) -> GateRecord:
    """Build a check's record: its status under the mode it ran in, and its detail.

    ``message`` is the one-line reason a results document shows; it names
    nothing that identifies the machine. Everything else of the detail stays
    in the capture.
    """
    body: dict[str, Any] = {"message": message} if message else {}
    body.update(detail)
    return GateRecord(name=name, mode=ctx.mode, status=status, detail=body)


@dataclass(frozen=True)
class Root:
    """Reads the kernel's files under a root folder.

    Every read returns ``None`` when the file cannot be read, so a caller
    decides what a missing file means.
    """

    path: Path = field(default_factory=lambda: Path("/"))

    def file(self, rel: str) -> Path:
        """The path of a file given relative to the root, such as ``proc/stat``."""
        return self.path / rel

    def text(self, rel: str) -> str | None:
        """The text of a file, or ``None`` when it cannot be read."""
        try:
            return self.file(rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return None

    def line(self, rel: str) -> str | None:
        """The first line of a file, stripped, or ``None``."""
        text = self.text(rel)
        if text is None:
            return None
        first = text.strip().splitlines()
        return first[0].strip() if first else ""

    def names(self, rel: str) -> list[str] | None:
        """The names in a folder, sorted, or ``None`` when it cannot be listed."""
        try:
            return sorted(os.listdir(self.file(rel)))
        except (OSError, ValueError):
            return None


# The highest CPU number a CPU list may name: the model's bound, which the
# launch settings check first. A list that names a higher one is refused
# before any set is built, so a mistyped range cannot fill memory.
MAX_CPU: Final = model.MAX_CPU


class CpuNumberTooHigh(ValueError):
    """A CPU list names a CPU number above ``MAX_CPU``."""


def parse_cpu_list(text: str) -> frozenset[int]:
    """Read a CPU list such as ``0-3,8,10-11`` into a set of CPU numbers.

    An empty text is an empty set. A list that names a CPU above
    ``MAX_CPU`` raises ``CpuNumberTooHigh``. Anything else that is not a
    list of numbers and ranges raises ``ValueError``.
    """
    text = text.strip()
    if not text:
        return frozenset()
    cpus: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        low, sep, high = part.partition("-")
        if not low.isdigit() or (sep and not high.isdigit()):
            raise ValueError(f"not a CPU list: {text!r}")
        first = int(low)
        last = int(high) if sep else first
        if last < first:
            raise ValueError(f"not a CPU list: {text!r}")
        if last > MAX_CPU:
            raise CpuNumberTooHigh(f"CPU {last} is above {MAX_CPU}: {text!r}")
        cpus.update(range(first, last + 1))
    return frozenset(cpus)


def format_cpu_list(cpus: Iterable[int]) -> str:
    """Write a set of CPU numbers as a CPU list with ranges, such as ``0-3,8``."""
    ordered = sorted(set(cpus))
    parts: list[str] = []
    start = prev = None
    for cpu in ordered:
        if start is None:
            start = prev = cpu
            continue
        assert prev is not None
        if cpu == prev + 1:
            prev = cpu
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = cpu
    if start is not None:
        parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(parts)


def all_pinned(sets: Iterable[str | None]) -> str | None:
    """The CPUs of every pinned set as one list, or ``None`` when one of them is unpinned.

    A launch that runs unpinned may run on any CPU, so a run with one such
    side counts as a run with nothing pinned. Each set is kept once, in the
    order given.
    """
    found = list(sets)
    if not found or any(cpus is None for cpus in found):
        return None
    return ",".join(dict.fromkeys(cpus for cpus in found if cpus is not None))


def all_selected(selections: Iterable[str | None]) -> str | None:
    """The GPUs any of the selections names, as one selection.

    ``all`` when one selection is ``all``; otherwise each index once, in
    the order named; ``None`` when no selection names a GPU.
    """
    picked = [gpus.strip() for gpus in selections if gpus is not None]
    if not picked:
        return None
    if "all" in picked:
        return "all"
    return ",".join(dict.fromkeys(part.strip() for gpus in picked for part in gpus.split(",")))


def side_launches(ctx: GateContext) -> list[tuple[str | None, str | None]]:
    """The CPU set and the GPU selection each launched side runs with.

    From ``ctx.sides`` when the run names its sides; otherwise the shared
    settings and the settings of each side the overrides name, a value a
    side does not give itself being the shared one.
    """
    if ctx.sides:
        return [(settings.cpus, settings.gpus) for settings in ctx.sides.values()]
    launch = ctx.launch
    found: list[tuple[str | None, str | None]] = [(launch.cpus, launch.gpus)]
    for table in launch.overrides.values():
        cpus = table.get("cpus", launch.cpus)
        gpus = table.get("gpus", launch.gpus)
        found.append(
            (
                cpus if isinstance(cpus, str) else launch.cpus,
                gpus if isinstance(gpus, str) else launch.gpus,
            )
        )
    return found


def read_cpu_list(root: Root, rel: str) -> frozenset[int] | None:
    """Read a file that holds a CPU list, or ``None`` when it cannot be read or parsed."""
    text = root.line(rel)
    if text is None:
        return None
    try:
        return parse_cpu_list(text)
    except ValueError:
        return None


CPU_DIR: Final = "sys/devices/system/cpu"


def online_cpus(root: Root) -> frozenset[int] | None:
    """The CPUs the kernel has online, or ``None`` when they cannot be read.

    The ``online`` list comes first; without it, the ``cpuN`` folders.
    """
    listed = read_cpu_list(root, f"{CPU_DIR}/online")
    if listed:
        return listed
    names = root.names(CPU_DIR)
    if not names:
        return None
    found = frozenset(int(n[3:]) for n in names if n.startswith("cpu") and n[3:].isdigit())
    return found or None


def cgroup_cpus(root: Root) -> frozenset[int] | None:
    """The CPUs the cgroup of this process allows, or ``None`` when they cannot be read.

    Under cgroup v2 it is ``cpuset.cpus.effective`` of the process's own
    group; under v1 the ``cpuset`` hierarchy's ``cpuset.effective_cpus``.
    Where the own group has no such file, the nearest group above it that
    has one answers. Inside a container this is the container's own set of
    CPUs. It does not change when the process changes its own affinity.
    """
    text = root.text("proc/self/cgroup")
    if text is None:
        return None
    for raw in text.splitlines():
        hierarchy, _, rest = raw.partition(":")
        controllers, _, path = rest.partition(":")
        if hierarchy == "0" and controllers == "":
            base, name = "sys/fs/cgroup", "cpuset.cpus.effective"
        elif "cpuset" in controllers.split(","):
            base, name = "sys/fs/cgroup/cpuset", "cpuset.effective_cpus"
        else:
            continue
        for group in upward(path):
            found = read_cpu_list(root, "/".join(p for p in (base, group, name) if p))
            if found:
                return found
    return None


def upward(path: str) -> list[str]:
    """A cgroup path relative to the hierarchy's root, then each group above it, then the root."""
    parts = [p for p in path.strip().split("/") if p and p not in (".", "..")]
    return ["/".join(parts[:n]) for n in range(len(parts), -1, -1)]


GetAffinity = Callable[[], "frozenset[int] | None"]
SetAffinity = Callable[[int, "frozenset[int]"], None]


def _get_affinity() -> frozenset[int] | None:
    getter = getattr(os, "sched_getaffinity", None)
    if getter is None:
        return None
    try:
        return frozenset(getter(0))
    except OSError:
        return None


def _set_affinity() -> SetAffinity | None:
    setter = getattr(os, "sched_setaffinity", None)
    if setter is None:
        return None

    def apply(task: int, cpus: frozenset[int]) -> None:
        setter(task, cpus)

    return apply


@dataclass(frozen=True)
class Affinity:
    """How the tool asks the operating system where its own threads may run.

    ``get`` returns the CPUs the calling thread may run on, or ``None`` where
    the platform cannot tell. ``set`` moves one thread (``0`` is the calling
    thread) onto a set of CPUs; it is ``None`` where the platform does not
    let a process choose its CPUs. ``threads`` lists the ids of the threads
    of this process.
    """

    get: GetAffinity
    set: SetAffinity | None
    threads: Callable[[], tuple[int, ...]]

    @classmethod
    def of_this_process(cls, root: Root) -> Affinity:
        """The calls of the running interpreter, with threads listed from ``proc/self/task``."""

        def threads() -> tuple[int, ...]:
            names = root.names("proc/self/task") or []
            return tuple(int(n) for n in names if n.isdigit())

        return cls(get=_get_affinity, set=_set_affinity(), threads=threads)
