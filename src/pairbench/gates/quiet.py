# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The quiet-machine check.

The check samples the machine and passes when it has been quiet for a streak
of samples. Waiting is opt-in: only with ``gates.wait_quiet`` set, and only
in the checks before the locks, does it keep sampling until the streak is
reached or ``gates.quiet.max_wait_s`` has passed. Otherwise it takes one
streak of samples and records pass or fail. The re-check once the locks are
held takes one sample and never waits.

While it waits, a sample counts toward the streak only when every readiness
check that is on (``GateSettings.readiness``) also passes at that sample; one that
cannot run counts as not ready. When the time runs out and the last samples
were quiet by the busy cores and the GPU processes alone, the quiet record
passes: the readiness check that was not ready fails in its own record. The
check that does not wait, and the re-check, read no readiness check.

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
    Gate,
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
from pairbench.gates.ready import CheckLocksGate, GpuMemoryGate, StopFileGate
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
    also ``None`` when GPUs are not watched. ``quiet`` is judged by the busy
    cores and the GPU processes alone; ``ready`` says whether every readiness
    check that is on passed at the sample, and is ``None`` when none was read.
    """

    busy_cores: float | None
    gpu_processes: int | None
    quiet: bool
    ready: bool | None = None

    def to_json(self) -> dict[str, Any]:
        """The sample as the record's detail keeps it."""
        out: dict[str, Any] = {
            "busy_cores": None if self.busy_cores is None else round(self.busy_cores, 4),
            "gpu_processes": self.gpu_processes,
            "quiet": self.quiet,
        }
        if self.ready is not None:
            out["ready"] = self.ready
        return out


@dataclass(frozen=True)
class Sampled:
    """What one round of sampling found.

    ``quiet`` says whether the streak was reached, every sample of it quiet
    and ready; ``quiet_alone`` whether the last samples reached the streak
    by the busy cores and the GPU processes alone; ``not_ready`` names the
    readiness checks that did not pass at the last sample; ``quiet_run``
    counts the quiet samples in a row at the end, by the busy cores and the
    GPU processes alone, also when ``samples`` keeps only the last of them.
    ``busy`` counts the samples of all ``taken`` that were not quiet by the
    busy cores and the GPU processes, and ``last_busy`` is the last of them,
    also when ``samples`` does not keep it.
    """

    quiet: bool
    quiet_alone: bool
    samples: list[QuietSample]
    taken: int
    elapsed: float
    not_ready: tuple[str, ...] = ()
    quiet_run: int = 0
    busy: int = 0
    last_busy: QuietSample | None = None


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


def _too_few(run: int, needed: int) -> str:
    """Say how many quiet samples in a row were taken of the ``needed``."""
    taken = "was" if run == 1 else "were"
    return f"{run} of the {needed} quiet samples needed {taken} taken in that time"


class QuietGate:
    """The quiet-machine check (``api.Gate``).

    ``readiness`` holds the readiness checks the wait reads, by name; by
    default the built-in ones, reading GPUs through the same source.
    """

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
        readiness: Sequence[Gate] | None = None,
    ) -> None:
        self._root = root or Root()
        self._system = system
        self._gpu_sources = gpu_sources or gpu_source
        self._clock = clock
        self._sleep = sleep
        self._loadavg = loadavg or (lambda: os.getloadavg()[0])
        if readiness is None:
            readiness = (
                StopFileGate(),
                GpuMemoryGate(system=system, gpu_sources=self._gpu_sources),
                CheckLocksGate(),
            )
        self._readiness = {gate.name: gate for gate in readiness}

    def readiness(self, gates: GateSettings) -> list[Gate]:
        """The readiness checks that are on, in the order they run."""
        return [self._readiness[name] for name in gates.readiness if name in self._readiness]

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
        ready = self.readiness(ctx.gates) if waits else []
        found = self._sample(
            platform,
            settings.max_busy_cores,
            probe,
            needed,
            settings.interval_s,
            settings.max_wait_s if waits else None,
            ready=lambda: _not_ready(ready, ctx) if ready else None,
        )
        samples, taken = found.samples, found.taken
        quiet = found.quiet or (bool(ready) and found.quiet_alone)
        detail: dict[str, Any] = {
            "where": platform.where,
            "source": "load_average" if platform.system == "darwin" else "proc_stat",
            "view": "machine" if platform.in_container else "host",
            "ci": platform.ci,
            "phase": ctx.phase,
            "waited": waits,
            "waited_s": round(found.elapsed, 3),
            "samples_needed": needed,
            "samples_taken": taken,
            "max_busy_cores": settings.max_busy_cores,
            "gpu_idle": watch_gpu,
            "gpus": gpus if watch_gpu else None,
            "last": [s.to_json() for s in samples[-KEPT_SAMPLES:]],
        }
        if ready:
            detail["readiness"] = [gate.name for gate in ready]
            detail["not_ready"] = list(found.not_ready)
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
            if waits:
                last_busy = next((s for s in reversed(samples) if not s.quiet), None)
                if last_busy is None:
                    # Every kept sample was quiet: the time ran out before enough were in a row.
                    reason = _too_few(found.quiet_run, needed)
                else:
                    reason = _reason(last_busy, settings.max_busy_cores, watch_gpu, source)
                message = (
                    f"the machine did not become quiet within {settings.max_wait_s:g} s: {reason}"
                )
            else:
                # Without a wait every sample needed is taken, so one of them was not quiet,
                # even when the kept samples do not hold it.
                last_busy = found.last_busy
                reason = (
                    "not quiet"
                    if last_busy is None
                    else _reason(last_busy, settings.max_busy_cores, watch_gpu, source)
                )
                message = f"not quiet in {found.busy} of {taken} samples: {reason}"
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
        ready: Callable[[], tuple[str, ...] | None] = lambda: None,
    ) -> Sampled:
        """Sample until the streak is reached, the samples are taken, or the wait is over.

        ``ready`` names the readiness checks that do not pass at this sample, or gives
        ``None`` when none is read; a sample counts toward the streak only
        when it is quiet and that list is empty.
        """
        start = self._clock()
        previous = self._read(platform)
        samples: list[QuietSample] = []
        streak = 0
        alone = 0
        taken = 0
        not_quiet = 0
        last_busy: QuietSample | None = None
        not_ready: tuple[str, ...] = ()
        while True:
            self._sleep(interval_s)
            current = self._read(platform)
            if platform.system == "darwin":
                cores: float | None = current
            else:
                cores = busy_cores(previous, current)
            previous = current
            gpu_n = probe.compute_processes() if probe is not None else None
            quiet = (
                cores is not None
                and cores <= limit
                and (probe is None or (gpu_n is not None and gpu_n == 0))
            )
            missing = ready()
            is_ready = None if missing is None else not missing
            not_ready = missing or ()
            sample = QuietSample(cores, gpu_n, quiet, is_ready)
            samples.append(sample)
            if not quiet:
                not_quiet += 1
                last_busy = sample
            if len(samples) > KEPT_SAMPLES * 2:
                del samples[: len(samples) - KEPT_SAMPLES]
            alone = alone + 1 if quiet else 0
            streak = streak + 1 if quiet and is_ready is not False else 0
            taken += 1
            elapsed = self._clock() - start
            done = (
                streak >= needed
                or (max_wait_s is None and taken >= needed)
                or (max_wait_s is not None and elapsed >= max_wait_s)
            )
            if done:
                return Sampled(
                    quiet=streak >= needed,
                    quiet_alone=alone >= needed,
                    samples=samples,
                    taken=taken,
                    elapsed=elapsed,
                    not_ready=not_ready,
                    quiet_run=alone,
                    busy=not_quiet,
                    last_busy=last_busy,
                )

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


def _not_ready(ready: Sequence[Gate], ctx: GateContext) -> tuple[str, ...]:
    """The readiness checks that do not pass at this read; one that cannot run is not ready."""
    return tuple(gate.name for gate in ready if gate.check(ctx).status != "pass")


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
    readiness: Sequence[Gate] | None = None,
    run: RunCommand = _call,
    err: TextIO | None = None,
    note: Notify = no_notes,
) -> int:
    """``pairbench gate wait-quiet -- COMMAND``: wait for quiet, then run the command once.

    The check waits whatever ``gates.wait_quiet`` says, until the machine is
    quiet or ``gates.quiet.max_wait_s`` has passed; the time is looked at
    after each sample, so a slow read can end the wait later. The wait
    includes the readiness checks that are on. After it each of them runs
    once. When the quiet check and every one of them passed, the command
    runs and its own exit code is returned; a command ended by a signal
    gives 128 plus the signal number.
    Otherwise the command is not run: the line of each check that did not
    pass is printed on ``err``, and the refusal names the first of them, in
    the order quiet, stop file, GPU memory, check-only locks: one that failed
    is refused with ``E_GATE_FAILED``, one that was degraded or could not run
    with ``E_GATE_UNAVAILABLE``, both exit 4. A command that cannot be
    started is refused with ``E_USAGE``. ``sides`` gives the launch settings
    of each side, as ``GateContext.sides`` does. ``readiness`` holds the
    readiness checks run after the wait, by name; by default those of the
    quiet check.
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
    quiet = gate or QuietGate()
    if readiness is None:
        after = quiet.readiness(ctx.gates) if isinstance(quiet, QuietGate) else []
    else:
        by_name = {ready.name: ready for ready in readiness}
        after = [by_name[name] for name in ctx.gates.readiness if name in by_name]
    records = [quiet.check(ctx)]
    records += [ready.check(ctx) for ready in after]
    missed = [record for record in records if record.status != "pass"]
    if missed:
        if err is not None:
            for record in missed:
                print(gate_line(record), file=err)
        first = missed[0]
        message = first.detail.get("message") or first.status
        code = "E_GATE_FAILED" if first.status == "fail" else "E_GATE_UNAVAILABLE"
        raise Refusal(
            code, f"the command was not run: {message}", detail={"record": first.to_json()}
        )
    try:
        return run(command)
    except OSError as exc:
        raise Refusal(
            "E_USAGE",
            f"the command could not be started: {os.path.basename(command[0])}",
            detail={"error": str(exc)},
        ) from exc
