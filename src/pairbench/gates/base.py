# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The machine checks a run uses as services, and what a check's status means
under the mode.

``machine_checks()`` returns the ``api.MachineChecks`` of this machine. Its
witness sampler watches one launch:

* the busy cores used by everything except the launch, from the per-CPU
  processor time counters read when the sampler starts and when it stops:
  in a pinned run, the busy cores outside the pinned set less the tool's
  own CPU time; otherwise the busy cores of the whole machine less the
  launch's own CPU time, or with the launch counted in, and so marked, when
  the side cannot report that time (see ``HostWitnessSampler``);
* the same restricted to the CPUs that share a last-level cache with the
  pinned set;
* the compute processes on the selected GPUs that were not the launch's own
  (the launch's first process, the first process of its second run, and
  their descendants), noting the ancestors of every compute process when it
  is first seen, so the answer can be given after the launch has ended;
* the throttle events the selected GPUs report.

The sampler is started before the side's first clock read and stopped after
the second. A thread polls the GPUs while the launch runs; between the two
clock reads the sampler is told nothing it must work on. ``stop`` never
raises: a witness it cannot read is reported as failed.

Modes: under ``warn`` every check that did not pass is printed and the run
goes on; under ``enforce`` a failed check is refused with ``E_GATE_FAILED``
and a degraded or unavailable one with ``E_GATE_UNAVAILABLE``, both exit 4;
under ``off`` the checks before the run are skipped, while witnesses are
still recorded and disturbed rounds still reported.
"""

from __future__ import annotations

import contextlib
import math
import threading
import time
from collections.abc import Callable, Sequence
from typing import Final, TextIO

from pairbench.api import CpuFacts, GpuProbe, LockSet, ToolCpus, WitnessSampler, gate_line
from pairbench.errors import Refusal
from pairbench.gates import cpus as cpus_module
from pairbench.gates.cache import sharing_cache
from pairbench.gates.discard import decide
from pairbench.gates.locks import acquire_locks
from pairbench.gates.occupancy import (
    GpuSource,
    Probe,
    absent_message,
    gpu_source,
    missing_gpus,
)
from pairbench.gates.platform import Affinity, Root, System, parse_cpu_list, this_system
from pairbench.gates.quiet import busy_cores, read_stat
from pairbench.model import (
    WITNESS_BUSY_CORES,
    WITNESS_BUSY_CORES_CACHE,
    WITNESS_GPU_OTHER_PROCESSES,
    WITNESS_GPU_THROTTLE_EVENTS,
    DiscardThresholds,
    GateRecord,
    RoundWitness,
    SetAside,
    Witness,
    clock_events,
)

# Seconds between two reads of the GPUs while a launch runs.
WITNESS_POLL_S: Final = 1.0
# How far up the process tree the ancestors of a GPU process are followed.
MAX_ANCESTRY: Final = 64
# How long ``stop`` waits for the polling thread to finish.
JOIN_S: Final = 5.0


def ancestors(root: Root, pid: int) -> tuple[int, ...]:
    """The parent, grandparent and further ancestors of a process, from ``proc/PID/stat``.

    The parent id is the second field after the command name in brackets.
    The walk stops at the first process that cannot be read, at process 1,
    or after ``MAX_ANCESTRY`` steps.
    """
    chain: list[int] = []
    current = pid
    for _ in range(MAX_ANCESTRY):
        text = root.text(f"proc/{current}/stat")
        if text is None:
            break
        fields = text.rpartition(")")[2].split()
        if len(fields) < 2 or not fields[1].isdigit():
            break
        parent = int(fields[1])
        if parent <= 0 or parent in (current, pid) or parent in chain:
            break
        chain.append(parent)
        if parent == 1:
            break
        current = parent
    return tuple(chain)


def _tool_seconds(read: Callable[[], float]) -> float | None:
    """The tool's own CPU time in seconds, or ``None`` when it is no duration or cannot be read."""
    try:
        value = float(read())
    except Exception:
        return None
    return value if math.isfinite(value) and value >= 0 else None


class HostWitnessSampler:
    """Watches the machine during one launch (``api.WitnessSampler``).

    ``applies`` is false on a platform with no independent witness: every
    witness then does not apply. ``pinned`` is the pinned CPU set, ``None``
    or empty when nothing is pinned. ``cache_cpus`` is the set of CPUs
    sharing a cache with the pinned set, ``None`` when nothing is pinned;
    ``cache_failed`` says the set could not be read. ``gpu`` is the source
    of the selected GPUs, ``None`` when none is selected. With ``poll_s`` of
    ``None`` no thread is started and the GPUs are read when the sampler
    starts and when it stops. ``tool_cpu_s`` reads the CPU time of the
    tool's own process, its witness thread included.

    The busy-core witness is counted in one of three ways:

    * a pinned run with CPUs outside the pinned set: the busy cores on the
      CPUs outside the set, less the tool's own CPU time over the launch.
      The launch's own CPU time is not needed. Load of others on the pinned
      CPUs themselves is not counted, and the helper processes of a
      container engine count as load of others;
    * any other run whose side reports its own CPU time: the busy cores of
      the whole machine less that time;
    * any other run whose side reports none (``own_cpu_s`` of ``None``): the
      busy cores of the whole machine, the launch's own load included, with
      the witness named in ``Witness.includes_launch``.

    The cache witness is the busy cores on ``cache_cpus`` less the launch's
    own CPU time, or with the launch included and so marked when the side
    reports none.
    """

    def __init__(
        self,
        *,
        root: Root,
        clock: Callable[[], float],
        applies: bool = True,
        pinned: frozenset[int] | None = None,
        cache_cpus: frozenset[int] | None = None,
        cache_failed: bool = False,
        gpu: GpuSource | None = None,
        poll_s: float | None = WITNESS_POLL_S,
        tool_cpu_s: Callable[[], float] = time.process_time,
    ) -> None:
        self._root = root
        self._clock = clock
        self._applies = applies
        self._pinned = pinned or frozenset()
        self._cache_cpus = cache_cpus
        self._cache_failed = cache_failed
        self._gpu = gpu if applies else None
        self._tool_cpu_s = tool_cpu_s
        self._tool_before = _tool_seconds(tool_cpu_s) if applies and self._pinned else None
        self._guard = threading.Lock()
        self._seen: dict[int, tuple[int, ...]] = {}
        self._gpu_failed = False
        self._throttle_events = 0
        self._throttle_failed = False
        self._masks_before: tuple[int, ...] = ()
        self._own: list[int] = []
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped: Witness | None = None
        self._start_s = clock()
        self._before = read_stat(root) if applies else None
        if self._gpu is not None:
            self.poll()
            if poll_s is not None and poll_s > 0:
                self._thread = threading.Thread(
                    target=self._loop, args=(poll_s,), name="pairbench-witness", daemon=True
                )
                self._thread.start()

    def own_process(self, pid: int) -> None:
        """Note a process of the launch's own. It stores the id and does nothing else."""
        self._own.append(pid)

    def poll(self) -> None:
        """Read the GPUs once: compute processes with their ancestors, and throttle masks."""
        gpu = self._gpu
        if gpu is None:
            return
        try:
            pids = gpu.processes()
        except Exception:
            pids = None
        try:
            masks = gpu.reason_masks()
        except Exception:
            masks = None
        fresh: dict[int, tuple[int, ...]] = {}
        if pids is not None:
            with self._guard:
                known = set(self._seen)
            for pid in pids:
                if pid not in known and pid not in fresh:
                    fresh[pid] = ancestors(self._root, pid)
        with self._guard:
            if pids is None:
                self._gpu_failed = True
            else:
                for pid, chain in fresh.items():
                    self._seen.setdefault(pid, chain)
            if masks is None:
                self._throttle_failed = True
            else:
                before = self._masks_before
                self._throttle_events += sum(
                    clock_events(before[i] if i < len(before) else 0, mask)
                    for i, mask in enumerate(masks)
                )
                self._masks_before = masks

    def _loop(self, poll_s: float) -> None:
        while not self._halt.wait(poll_s):
            self.poll()

    def stop(
        self, own_cpu_s: float | None, own_pid: int | None = None, second_pid: int | None = None
    ) -> Witness:
        """Stop watching and return the witness of the launch. Never raises.

        ``own_cpu_s`` is the launch's own CPU time in seconds, or ``None``
        when the side cannot report it: the busy-core witnesses then count
        the launch in (see the class). A value that is not a finite number
        at or above zero fails the busy-core witnesses that need it. A
        second call returns the first answer.
        """
        if self._stopped is not None:
            return self._stopped
        try:
            witness = self._finish(own_cpu_s, own_pid, second_pid)
        except Exception:
            witness = Witness().with_failed(*self._applicable())
        self._stopped = witness
        return witness

    def _applicable(self) -> tuple[str, ...]:
        if not self._applies:
            return ()
        names = [WITNESS_BUSY_CORES]
        if self._cache_cpus is not None or self._cache_failed:
            names.append(WITNESS_BUSY_CORES_CACHE)
        if self._gpu is not None:
            names += [WITNESS_GPU_OTHER_PROCESSES, WITNESS_GPU_THROTTLE_EVENTS]
        return tuple(names)

    def _finish(
        self, own_cpu_s: float | None, own_pid: int | None, second_pid: int | None
    ) -> Witness:
        self._halt.set()
        if self._thread is not None:
            self._thread.join(JOIN_S)
        if not self._applies:
            return Witness()
        after = read_stat(self._root)
        elapsed = self._clock() - self._start_s
        if self._gpu is not None:
            self.poll()
        failed: list[str] = []
        with_launch: list[str] = []
        own_cores = (
            own_cpu_s / elapsed
            if own_cpu_s is not None and math.isfinite(own_cpu_s) and own_cpu_s >= 0 and elapsed > 0
            else None
        )

        def others(cpus: frozenset[int] | None, name: str) -> float | None:
            seen = busy_cores(self._before, after, cpus)
            if seen is None or (own_cpu_s is not None and own_cores is None):
                failed.append(name)
                return None
            if own_cores is None:
                with_launch.append(name)
                return round(seen, 4)
            return round(max(0.0, seen - own_cores), 4)

        outside = self._outside(after)
        if outside:
            busy = self._outside_load(outside, after, elapsed)
            if busy is None:
                failed.append(WITNESS_BUSY_CORES)
        else:
            busy = others(None, WITNESS_BUSY_CORES)
        cache: float | None = None
        if self._cache_failed:
            failed.append(WITNESS_BUSY_CORES_CACHE)
        elif self._cache_cpus is not None:
            cache = others(self._cache_cpus, WITNESS_BUSY_CORES_CACHE)
        gpu_others: int | None = None
        throttle: int | None = None
        if self._gpu is not None:
            owners = {p for p in (own_pid, second_pid, *self._own) if p is not None}
            with self._guard:
                seen = dict(self._seen)
                gpu_failed = self._gpu_failed
                throttle_failed = self._throttle_failed
                events = self._throttle_events
            if gpu_failed:
                failed.append(WITNESS_GPU_OTHER_PROCESSES)
            else:
                gpu_others = sum(
                    1
                    for pid, chain in seen.items()
                    if pid not in owners and not owners.intersection(chain)
                )
            if throttle_failed:
                failed.append(WITNESS_GPU_THROTTLE_EVENTS)
            else:
                throttle = events
        return Witness(
            busy_cores=busy,
            busy_cores_cache=cache,
            gpu_other_processes=gpu_others,
            gpu_throttle_events=throttle,
            failed=tuple(failed),
            includes_launch=tuple(with_launch),
        )

    def _outside(self, after: dict[int, tuple[int, int]] | None) -> frozenset[int]:
        """The CPUs seen at both readings that are not pinned; empty when nothing is pinned."""
        if not self._pinned or self._before is None or after is None:
            return frozenset()
        return frozenset((set(self._before) & set(after)) - self._pinned)

    def _outside_load(
        self, outside: frozenset[int], after: dict[int, tuple[int, int]] | None, elapsed: float
    ) -> float | None:
        """The busy cores outside the pinned set, less the tool's own CPU time.

        The tool's time is left out of the reduction when it cannot be read
        at either end, so the value can only be too high.
        """
        seen = busy_cores(self._before, after, outside)
        if seen is None:
            return None
        before = self._tool_before
        now = _tool_seconds(self._tool_cpu_s)
        tool_cores = 0.0
        if before is not None and now is not None and elapsed > 0:
            tool_cores = max(0.0, now - before) / elapsed
        return round(max(0.0, seen - tool_cores), 4)


class HostChecks:
    """The machine checks of this machine (``api.MachineChecks``).

    Every way it reads or changes the machine is given at construction, so
    the tests replace each with a fake: ``root`` for the kernel's files,
    ``system`` for the operating system, ``affinity`` for where the tool's
    threads run, ``gpu_sources`` for the GPUs, ``clock`` and ``sleep`` for
    time, ``tool_cpu_s`` for the CPU time of the tool's own process.
    """

    def __init__(
        self,
        *,
        root: Root | None = None,
        system: System | None = None,
        affinity: Affinity | None = None,
        gpu_sources: Callable[[str], GpuSource] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        poll_s: float | None = WITNESS_POLL_S,
        tool_cpu_s: Callable[[], float] = time.process_time,
    ) -> None:
        self._root = root or Root()
        self._system: System = this_system() if system is None else system
        self._affinity = affinity or Affinity.of_this_process(self._root)
        self._gpu_sources = gpu_sources or gpu_source
        self._clock = clock
        self._sleep = sleep
        self._poll_s = poll_s
        self._tool_cpu_s = tool_cpu_s
        self._sources: dict[str, GpuSource] = {}
        self._sharing: dict[str, frozenset[int] | None] = {}
        # Where the calling thread ran before leave_pinned moved it.
        self._home: frozenset[int] | None = None

    def _source(self, gpus: str) -> GpuSource:
        """The source of the selected GPUs, made once per selection."""
        if gpus not in self._sources:
            self._sources[gpus] = self._gpu_sources(gpus)
        return self._sources[gpus]

    @staticmethod
    def _pinned(cpus: str) -> frozenset[int]:
        """The pinned CPU set, empty when the list cannot be read."""
        try:
            return parse_cpu_list(cpus)
        except ValueError:
            return frozenset()

    def _cache_of(self, cpus: str) -> frozenset[int] | None:
        """The CPUs sharing a cache with the pinned set, read once per set."""
        if cpus not in self._sharing:
            pinned = self._pinned(cpus)
            self._sharing[cpus] = sharing_cache(self._root, pinned) if pinned else None
        return self._sharing[cpus]

    def cpu_facts(self, cpus: str | None, *, allow_mixed: bool) -> CpuFacts:
        """Describe the pinned set, or the machine; refuse a mixed or impossible set."""
        return cpus_module.cpu_facts(self._root, self._system, cpus, allow_mixed=allow_mixed)

    def leave_pinned(self, cpus: str | None) -> ToolCpus:
        """Move the tool's own threads off the pinned set, where the platform allows it."""
        home = self._affinity.get() if cpus is not None else None
        answer = cpus_module.leave_pinned(cpus, system=self._system, affinity=self._affinity)
        if answer.cpus is not None and home is not None:
            self._home = home
        return answer

    def restore_cpus(self) -> None:
        """Move the tool's threads back to where ``leave_pinned`` found them; once."""
        home, self._home = self._home, None
        if home is not None:
            cpus_module.return_home(home, affinity=self._affinity)

    def gpu_probe(self, gpus: str | None) -> GpuProbe | None:
        """A probe of the selected GPUs, or ``None`` when no GPU is selected.

        A selection that names a GPU the machine does not have is refused
        with ``E_USAGE``, naming the GPUs it has. When the GPUs present
        cannot be read, the probe is made all the same and its reads fail.
        """
        if gpus is None:
            return None
        source = self._source(gpus)
        present = source.present() if gpus.strip() != "all" else None
        if present is not None:
            missing = missing_gpus(gpus, present)
            if missing:
                raise Refusal("E_USAGE", f"gpus {gpus}: {absent_message(missing, present)}")
        return Probe(source)

    def acquire_locks(self, paths: Sequence[str], timeout_s: float) -> LockSet:
        """Take the locks in the order given, or refuse with ``E_LOCK``."""
        return acquire_locks(paths, timeout_s, clock=self._clock, sleep=self._sleep)

    def start_witness(self, cpus: str | None, gpus: str | None) -> WitnessSampler:
        """Begin watching the machine for one launch."""
        applies = self._system == "linux"
        pinned: frozenset[int] | None = None
        cache: frozenset[int] | None = None
        cache_failed = False
        if applies and cpus is not None:
            pinned = self._pinned(cpus)
            cache = self._cache_of(cpus)
            cache_failed = cache is None
        gpu = self._source(gpus) if applies and gpus is not None else None
        return HostWitnessSampler(
            root=self._root,
            clock=self._clock,
            applies=applies,
            pinned=pinned,
            cache_cpus=cache,
            cache_failed=cache_failed,
            gpu=gpu,
            poll_s=self._poll_s,
            tool_cpu_s=self._tool_cpu_s,
        )

    def set_aside(
        self, thresholds: DiscardThresholds, witnesses: Sequence[RoundWitness]
    ) -> SetAside:
        """Decide which rounds are disturbed, as ``pairbench.model.set_aside`` decides."""
        return decide(thresholds, witnesses)


def machine_checks() -> HostChecks:
    """The machine checks of this machine. Nothing is read or started until a call needs it."""
    return HostChecks()


def judge(record: GateRecord) -> Refusal | None:
    """What a check's status means under the mode it ran in: a refusal, or ``None`` to go on.

    Under ``enforce`` a failed check is ``E_GATE_FAILED`` and a degraded or
    unavailable one ``E_GATE_UNAVAILABLE``. Under ``warn`` and ``off``
    nothing is refused.
    """
    if record.mode != "enforce" or record.status == "pass":
        return None
    message = record.detail.get("message")
    reason = message if isinstance(message, str) and message else record.status
    if record.status == "fail":
        return Refusal("E_GATE_FAILED", f"check {record.name} failed: {reason}")
    return Refusal("E_GATE_UNAVAILABLE", f"check {record.name} is {record.status}: {reason}")


def report(record: GateRecord, err: TextIO) -> bool:
    """Print the line of a check that did not pass on ``err``; say whether one was printed."""
    if record.status == "pass":
        return False
    with contextlib.suppress(OSError, ValueError):
        print(gate_line(record), file=err)
    return True
