# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The quiet-machine check.

The check samples the machine and passes when it has been quiet for a streak
of samples. Waiting is opt-in: only with ``gates.wait_quiet`` set, and only
in the checks before the locks, does it keep sampling until the streak is
reached or ``gates.quiet.max_wait_s`` has passed. Otherwise it takes one
streak of samples and records pass or fail. The re-check once the locks are
held takes one sample and never waits.

A sample is quiet when the busy cores, summed over the machine, are at most
``gates.quiet.max_busy_cores`` and, when GPUs are watched, no compute
process runs on them. A probe that fails to read counts as busy. The GPUs
watched are those any side selects, its own selection where it gives itself
one; by default they are watched when a side selects a GPU.

Busy cores come from the per-CPU lines of ``/proc/stat``
(https://docs.kernel.org/filesystems/proc.html): the time spent in user,
nice, system, irq, softirq and steal over the time of all states, times the
number of CPUs. Guest time is already counted in user time and is left out.
On macOS only the one-minute load average is read and the check is
``degraded``.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, TextIO

from pairbench.api import (
    API_VERSION,
    DoctorReport,
    GateContext,
    Notify,
    gate_line,
    no_notes,
)
from pairbench.errors import Refusal
from pairbench.gates.occupancy import (
    FailingSource,
    GpuSource,
    Probe,
    absent_message,
    gpu_source,
    missing_gpus,
)
from pairbench.gates.platform import (
    Platform,
    Root,
    System,
    all_selected,
    make_record,
    side_launches,
    this_system,
)
from pairbench.model import GateRecord, GateSettings, GateStatus, LaunchSettings

NAME: Final = "quiet"
# How many of the last samples a record keeps in its detail.
KEPT_SAMPLES: Final = 20

Counters = Mapping[int, tuple[int, int]]
"""Per CPU: the busy time and the time of all states, in clock ticks."""


def parse_stat(text: str) -> dict[int, tuple[int, int]] | None:
    """Read the per-CPU lines of ``/proc/stat`` into busy and total ticks per CPU.

    ``None`` when no per-CPU line can be read.
    """
    counters: dict[int, tuple[int, int]] = {}
    for raw in text.splitlines():
        parts = raw.split()
        if not parts or not parts[0].startswith("cpu") or not parts[0][3:].isdigit():
            continue
        try:
            values = [int(v) for v in parts[1:9]]
        except ValueError:
            return None
        if len(values) < 4:
            return None
        values += [0] * (8 - len(values))
        user, nice, system, idle, iowait, irq, softirq, steal = values
        busy = user + nice + system + irq + softirq + steal
        counters[int(parts[0][3:])] = (busy, busy + idle + iowait)
    return counters or None


def read_stat(root: Root) -> dict[int, tuple[int, int]] | None:
    """The per-CPU counters now, or ``None`` when they cannot be read."""
    text = root.text("proc/stat")
    return None if text is None else parse_stat(text)


def busy_cores(
    before: Counters | None, after: Counters | None, cpus: frozenset[int] | None = None
) -> float | None:
    """The busy cores between two readings, over all CPUs or the ones given.

    ``None`` when either reading failed, no CPU is common to both, or no
    clock tick passed between them, so nothing could be seen.
    """
    if before is None or after is None:
        return None
    common = set(before) & set(after)
    if cpus is not None:
        common &= cpus
    if not common:
        return None
    d_busy = sum(max(0, after[c][0] - before[c][0]) for c in common)
    d_total = sum(max(0, after[c][1] - before[c][1]) for c in common)
    if d_total <= 0:
        return None
    return len(common) * d_busy / d_total


@dataclass(frozen=True)
class QuietSample:
    """One sample: the busy cores, the other GPU compute processes, and whether it was quiet.

    A value of ``None`` means its probe failed to read; ``gpu_processes`` is
    also ``None`` when GPUs are not watched.
    """

    busy_cores: float | None
    gpu_processes: int | None
    quiet: bool

    def to_json(self) -> dict[str, Any]:
        """The sample as the record's detail keeps it."""
        return {
            "busy_cores": None if self.busy_cores is None else round(self.busy_cores, 4),
            "gpu_processes": self.gpu_processes,
            "quiet": self.quiet,
        }


def _selecting(ctx: GateContext, present: Sequence[int]) -> str:
    """Name the sides whose own GPU selection names a GPU not ``present``, as a prefix.

    Empty when the shared selection names such a GPU, or no side gives
    itself a selection that does.
    """
    shared = ctx.launch.gpus
    if shared is not None and missing_gpus(shared, present):
        return ""
    if ctx.sides:
        own = {name: settings.gpus for name, settings in ctx.sides.items()}
    else:
        own = {name: table.get("gpus") for name, table in ctx.launch.overrides.items()}
    names = sorted(
        name
        for name, gpus in own.items()
        if isinstance(gpus, str) and gpus != shared and missing_gpus(gpus, present)
    )
    if not names:
        return ""
    return f"{'side' if len(names) == 1 else 'sides'} {', '.join(names)}: "


def _reason(sample: QuietSample, limit: float, watch_gpu: bool, source: str) -> str:
    parts: list[str] = []
    if sample.busy_cores is None:
        parts.append(f"the {source} could not be read")
    elif sample.busy_cores > limit:
        parts.append(f"{source} {sample.busy_cores:.2f} against a limit of {limit:g}")
    if watch_gpu:
        if sample.gpu_processes is None:
            parts.append("the GPU processes could not be read")
        elif sample.gpu_processes > 0:
            parts.append(f"{sample.gpu_processes} other compute process(es) on the selected GPUs")
    return "; ".join(parts) or "not quiet"


class QuietGate:
    """The quiet-machine check (``api.Gate``)."""

    name: Final = NAME
    api_version: Final = API_VERSION

    def __init__(
        self,
        *,
        root: Root | None = None,
        system: System | None = None,
        gpu_sources: Callable[[str], GpuSource] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        loadavg: Callable[[], float] | None = None,
    ) -> None:
        self._root = root or Root()
        self._system = system
        self._gpu_sources = gpu_sources or gpu_source
        self._clock = clock
        self._sleep = sleep
        self._loadavg = loadavg or (lambda: os.getloadavg()[0])

    def check(self, ctx: GateContext) -> GateRecord:
        """Run the check once and report."""
        platform = Platform.of(ctx, self._system)
        settings = ctx.gates.quiet
        if platform.system == "other":
            return make_record(
                NAME,
                ctx,
                "unavailable",
                "busy cores cannot be read on this platform",
                where=platform.where,
            )
        selected = all_selected(gpus for _cpus, gpus in side_launches(ctx))
        watch_gpu = settings.gpu_idle if settings.gpu_idle is not None else bool(selected)
        gpus = selected or "all"
        probe: Probe | None = None
        if watch_gpu:
            linux = platform.system == "linux"
            gpu = self._gpu_sources(gpus) if linux else FailingSource()
            present = gpu.present() if linux and gpus != "all" else None
            missing = missing_gpus(gpus, present) if present is not None else ()
            if present is not None and missing:
                return make_record(
                    NAME,
                    ctx,
                    "unavailable",
                    f"{_selecting(ctx, present)}{absent_message(missing, present)}, "
                    "so they cannot be watched",
                    where=platform.where,
                    gpus=gpus,
                    gpus_present=list(present),
                )
            probe = Probe(gpu)
        waits = ctx.gates.wait_quiet and ctx.phase == "before"
        needed = settings.samples if ctx.phase == "before" else 1
        source = "load average" if platform.system == "darwin" else "busy cores"
        quiet, samples, taken, waited_s = self._sample(
            platform,
            settings.max_busy_cores,
            probe,
            needed,
            settings.interval_s,
            settings.max_wait_s if waits else None,
        )
        detail: dict[str, Any] = {
            "where": platform.where,
            "source": "load_average" if platform.system == "darwin" else "proc_stat",
            "view": "machine" if platform.in_container else "host",
            "ci": platform.ci,
            "phase": ctx.phase,
            "waited": waits,
            "waited_s": round(waited_s, 3),
            "samples_needed": needed,
            "samples_taken": taken,
            "max_busy_cores": settings.max_busy_cores,
            "gpu_idle": watch_gpu,
            "gpus": gpus if watch_gpu else None,
            "last": [s.to_json() for s in samples[-KEPT_SAMPLES:]],
        }
        label = " (machine-wide view from inside a container)" if platform.in_container else ""
        status: GateStatus
        if quiet:
            if platform.system == "darwin":
                status = "degraded"
                message = "quiet by the load average only; busy cores are not read on this platform"
            else:
                status, message = "pass", ""
        else:
            status = "fail"
            last_busy = next((s for s in reversed(samples) if not s.quiet), samples[-1])
            reason = _reason(last_busy, settings.max_busy_cores, watch_gpu, source)
            if waits:
                message = (
                    f"the machine did not become quiet within {settings.max_wait_s:g} s: {reason}"
                )
            else:
                busy = sum(1 for s in samples if not s.quiet)
                message = f"not quiet in {busy} of {taken} samples: {reason}"
        return make_record(NAME, ctx, status, message + label if message else "", **detail)

    def _read(self, platform: Platform) -> Any:
        if platform.system == "darwin":
            try:
                return float(self._loadavg())
            except (OSError, ValueError, TypeError):
                return None
        return read_stat(self._root)

    def _sample(
        self,
        platform: Platform,
        limit: float,
        probe: Probe | None,
        needed: int,
        interval_s: float,
        max_wait_s: float | None,
    ) -> tuple[bool, list[QuietSample], int, float]:
        """Sample until the streak is reached, the samples are taken, or the wait is over.

        Returns whether the streak was reached, the last samples, how many
        samples were taken and the seconds it took.
        """
        start = self._clock()
        previous = self._read(platform)
        samples: list[QuietSample] = []
        streak = 0
        taken = 0
        while True:
            self._sleep(interval_s)
            current = self._read(platform)
            if platform.system == "darwin":
                busy: float | None = current
            else:
                busy = busy_cores(previous, current)
            previous = current
            gpu_n = probe.compute_processes() if probe is not None else None
            quiet = (
                busy is not None
                and busy <= limit
                and (probe is None or (gpu_n is not None and gpu_n == 0))
            )
            samples.append(QuietSample(busy, gpu_n, quiet))
            if len(samples) > KEPT_SAMPLES * 2:
                del samples[: len(samples) - KEPT_SAMPLES]
            streak = streak + 1 if quiet else 0
            taken += 1
            elapsed = self._clock() - start
            if streak >= needed:
                return True, samples, taken, elapsed
            if max_wait_s is None and taken >= needed:
                return False, samples, taken, elapsed
            if max_wait_s is not None and elapsed >= max_wait_s:
                return False, samples, taken, elapsed

    def doctor(self) -> DoctorReport:
        """What this platform lets the check do."""
        system = this_system() if self._system is None else self._system
        if system == "darwin":
            return DoctorReport("degraded", "load average only on this platform")
        if system != "linux":
            return DoctorReport("unavailable", "busy cores cannot be read on this platform")
        if read_stat(self._root) is None:
            return DoctorReport("unavailable", "the processor time counters could not be read")
        return DoctorReport("ok", "busy cores from the processor time counters")


RunCommand = Callable[[Sequence[str]], int]


def _call(command: Sequence[str]) -> int:
    rc = subprocess.call(list(command))
    return 128 - rc if rc < 0 else rc


def wait_then_run(
    command: Sequence[str],
    *,
    gates: GateSettings,
    launch: LaunchSettings,
    sides: Mapping[str, LaunchSettings] | None = None,
    environ: Mapping[str, str] | None = None,
    in_container: bool = False,
    ci: bool = False,
    gate: QuietGate | None = None,
    run: RunCommand = _call,
    err: TextIO | None = None,
    note: Notify = no_notes,
) -> int:
    """``pairbench gate wait-quiet -- COMMAND``: wait for quiet, then run the command once.

    The check waits up to ``gates.quiet.max_wait_s`` whatever
    ``gates.wait_quiet`` says. When the machine became quiet the command
    runs and its own exit code is returned; a command ended by a signal
    gives 128 plus the signal number. Otherwise the command is not run: a
    check that failed is refused with ``E_GATE_FAILED``, one that was
    degraded or could not run with ``E_GATE_UNAVAILABLE``, both exit 4, and
    the check's line is printed on ``err``. A command that cannot be started
    is refused with ``E_USAGE``. ``sides`` gives the launch settings of each
    side, as ``GateContext.sides`` does.
    """
    if not command:
        raise Refusal("E_USAGE", "gate wait-quiet needs a command after --")
    ctx = GateContext(
        mode="enforce",
        gates=replace(gates, wait_quiet=True),
        launch=launch,
        phase="before",
        environ=dict(environ or {}),
        in_container=in_container,
        ci=ci,
        note=note,
        sides=dict(sides or {}),
    )
    record = (gate or QuietGate()).check(ctx)
    if record.status != "pass":
        if err is not None:
            print(gate_line(record), file=err)
        message = record.detail.get("message") or record.status
        code = "E_GATE_FAILED" if record.status == "fail" else "E_GATE_UNAVAILABLE"
        raise Refusal(
            code, f"the command was not run: {message}", detail={"record": record.to_json()}
        )
    try:
        return run(command)
    except OSError as exc:
        raise Refusal(
            "E_USAGE",
            f"the command could not be started: {os.path.basename(command[0])}",
            detail={"error": str(exc)},
        ) from exc
