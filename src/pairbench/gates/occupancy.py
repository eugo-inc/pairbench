# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""GPU occupancy: the compute processes on the selected GPUs, the memory in
use, and the reasons the GPUs give for running below full clocks.

Two sources are read the same way downstream:

* the GPU management library, through the ``gpu`` extra (the ``pynvml``
  module): the code calls the functions named in ``NVML_CALLS``, and for the
  reason mask the first of ``NVML_REASON_CALLS`` the module has;
* otherwise the ``nvidia-smi`` query command, asked for the fields the
  constants below name. When the query of a reason field fails, the next
  name in ``SMI_REASON_FIELDS`` is tried, and the one that answered is kept.

The bits of the reason mask are the ``nvmlClocksEventReason*`` values of the
NVML header, version 13.4.92
(https://github.com/NVIDIA/go-nvml/blob/main/gen/nvml/nvml.h). A bit other
than GPU idle, the applications clocks setting and the display clock setting
is a slowdown and counts as a throttle event.

Every read returns ``None`` when it fails; a caller counts that as busy. The
GPUs a source reads, and their ids, are looked up once and kept.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol

from pairbench.model import CLOCK_REASONS_NOT_COUNTED

# Bits of the active clock reason mask (NVML ``nvmlClocksEventReason*``).
REASON_GPU_IDLE: Final = 0x1
REASON_APPLICATIONS_CLOCKS_SETTING: Final = 0x2
REASON_SW_POWER_CAP: Final = 0x4
REASON_HW_SLOWDOWN: Final = 0x8
REASON_SYNC_BOOST: Final = 0x10
REASON_SW_THERMAL_SLOWDOWN: Final = 0x20
REASON_HW_THERMAL_SLOWDOWN: Final = 0x40
REASON_HW_POWER_BRAKE_SLOWDOWN: Final = 0x80
REASON_DISPLAY_CLOCK_SETTING: Final = 0x100
REASON_BOARD_LIMIT: Final = 0x200
REASON_RELIABILITY: Final = 0x400
# Reasons that are settings or an idle GPU, not a slowdown under load: the
# model's mask, which the power sampler's count uses as well.
NOT_A_SLOWDOWN: Final = CLOCK_REASONS_NOT_COUNTED

SMI: Final = "nvidia-smi"
SMI_TIMEOUT_S: Final = 20.0
SMI_FORMAT: Final = "--format=csv,noheader,nounits"
SMI_GPU_QUERY: Final = "--query-gpu=index,uuid,memory.used"
SMI_FREE_QUERY: Final = "--query-gpu=index,memory.free"
SMI_APPS_QUERY: Final = "--query-compute-apps=pid,gpu_uuid"
SMI_REASON_FIELDS: Final[tuple[str, ...]] = (
    "clocks_event_reasons.active",
    "clocks_throttle_reasons.active",
)
NVML_CALLS: Final[tuple[str, ...]] = (
    "nvmlInit",
    "nvmlDeviceGetCount",
    "nvmlDeviceGetHandleByIndex",
    "nvmlDeviceGetComputeRunningProcesses",
    "nvmlDeviceGetMemoryInfo",
)
NVML_REASON_CALLS: Final[tuple[str, ...]] = (
    "nvmlDeviceGetCurrentClocksEventReasons",
    "nvmlDeviceGetCurrentClocksThrottleReasons",
)
MIB: Final = 1024 * 1024

Run = Callable[[Sequence[str], float], tuple[int, str]]
"""Runs a command with a timeout and returns its exit code and standard output.
A command that cannot be started, or runs into the timeout, gives ``(-1, "")``."""


def run_command(argv: Sequence[str], timeout_s: float) -> tuple[int, str]:
    """Run a command, capturing its output; never raise."""
    try:
        done = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1, ""
    return done.returncode, done.stdout


def is_slowdown(mask: int) -> bool:
    """Say whether an active reason mask holds a slowdown."""
    return bool(mask & ~NOT_A_SLOWDOWN)


class GpuSource(Protocol):
    """Reads the selected GPUs. Each read gives ``None`` when it fails."""

    def processes(self) -> tuple[int, ...] | None:
        """The process ids of the compute processes on the selected GPUs."""
        ...

    def memory_used_mib(self) -> float | None:
        """The memory in use on the selected GPUs, summed, in MiB."""
        ...

    def reason_masks(self) -> tuple[int, ...] | None:
        """The active clock reason mask of each selected GPU."""
        ...

    def present(self) -> tuple[int, ...] | None:
        """The index of every GPU the source sees, selected or not."""
        ...

    def memory_free_mib(self) -> tuple[tuple[int, float], ...] | None:
        """The index and free memory in MiB of each selected GPU, in the order selected."""
        ...


def selected_indices(gpus: str, count: int) -> tuple[int, ...] | None:
    """The indices ``gpus`` selects among ``count`` GPUs, or ``None`` when one is missing.

    ``None`` stands for a selection that does not parse as well as for one
    that names an index past ``count``; ``missing_gpus`` names the indices
    a machine does not have.
    """
    if gpus.strip() == "all":
        return tuple(range(count))
    try:
        wanted = tuple(dict.fromkeys(int(part) for part in gpus.split(",")))
    except ValueError:
        return None
    if any(i < 0 or i >= count for i in wanted):
        return None
    return wanted


def missing_gpus(gpus: str, present: Sequence[int]) -> tuple[int, ...]:
    """The indices ``gpus`` names that are not among ``present``, in the order named.

    ``all`` names none. A selection that does not parse names none here: the
    launch settings refuse it before a run.
    """
    if gpus.strip() == "all":
        return ()
    try:
        wanted = dict.fromkeys(int(part) for part in gpus.split(","))
    except ValueError:
        return ()
    have = set(present)
    return tuple(index for index in wanted if index not in have)


def absent_message(missing: Sequence[int], present: Sequence[int]) -> str:
    """Say which selected GPUs the machine does not have, and which it has."""
    names = ", ".join(str(index) for index in missing)
    head = f"GPU {names} is" if len(missing) == 1 else f"GPUs {names} are"
    if present:
        here = f"the GPUs here are {', '.join(str(index) for index in present)}"
    else:
        here = "no GPU is visible here"
    return f"{head} not on this machine; {here}"


def _field(text: str) -> str | None:
    value = text.strip()
    if not value or value.startswith("[") or value.upper() in ("N/A", "NA"):
        return None
    return value


def _amount(text: str) -> float | None:
    """A finite amount that is not negative, or ``None``."""
    value = _field(text)
    if value is None:
        return None
    try:
        amount = float(value)
    except ValueError:
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


class SmiSource:
    """Reads the selected GPUs with the ``nvidia-smi`` query command."""

    def __init__(self, gpus: str, run: Run = run_command, program: str = SMI) -> None:
        self._gpus = gpus
        self._run = run
        self._program = program
        self._ids: list[tuple[int, str]] | None = None
        self._reason_field: str | None = None

    def _query(self, query: str) -> list[list[str]] | None:
        rc, out = self._run([self._program, query, SMI_FORMAT], SMI_TIMEOUT_S)
        if rc != 0:
            return None
        return [
            [part.strip() for part in raw.split(",")] for raw in out.splitlines() if raw.strip()
        ]

    def _rows(self) -> list[tuple[int, str, float | None]] | None:
        rows = self._query(SMI_GPU_QUERY)
        if rows is None:
            return None
        out: list[tuple[int, str, float | None]] = []
        for row in rows:
            if len(row) != 3 or not row[0].isdigit():
                return None
            memory = _field(row[2])
            try:
                used = float(memory) if memory is not None else None
            except ValueError:
                used = None
            out.append((int(row[0]), row[1], used))
        return out

    def _selected(self) -> list[tuple[int, str, float | None]] | None:
        rows = self._rows()
        if rows is None:
            return None
        by_index = {row[0]: row for row in rows}
        wanted = selected_indices(self._gpus, len(rows))
        if wanted is None or any(i not in by_index for i in wanted):
            return None
        chosen = [by_index[i] for i in wanted]
        self._ids = [(row[0], row[1]) for row in chosen]
        return chosen

    def present(self) -> tuple[int, ...] | None:
        """The index of every GPU the query command lists, or ``None`` when it fails."""
        rows = self._rows()
        return None if rows is None else tuple(sorted(row[0] for row in rows))

    def _known(self) -> list[tuple[int, str]] | None:
        """The index and id of each selected GPU, looked up once."""
        if self._ids is None:
            self._selected()
        return self._ids

    def processes(self) -> tuple[int, ...] | None:
        """The process ids of the compute processes on the selected GPUs."""
        ids = self._known()
        if ids is None:
            return None
        uuids = {uuid for _, uuid in ids}
        apps = self._query(SMI_APPS_QUERY)
        if apps is None:
            return None
        pids: list[int] = []
        for app in apps:
            if len(app) != 2 or not app[0].isdigit():
                return None
            if app[1] in uuids:
                pids.append(int(app[0]))
        return tuple(pids)

    def memory_used_mib(self) -> float | None:
        """The memory in use on the selected GPUs, summed, in MiB."""
        rows = self._selected()
        if rows is None or any(row[2] is None for row in rows):
            return None
        return float(sum(row[2] or 0.0 for row in rows))

    def reason_masks(self) -> tuple[int, ...] | None:
        """The active clock reason mask of each selected GPU."""
        ids = self._known()
        if ids is None:
            return None
        wanted = [index for index, _ in ids]
        names = (self._reason_field,) if self._reason_field else SMI_REASON_FIELDS
        for name in names:
            found = self._query(f"--query-gpu=index,{name}")
            if found is None:
                continue
            self._reason_field = name
            masks: dict[int, int] = {}
            for row in found:
                value = _field(row[1]) if len(row) == 2 else None
                if not row[0].isdigit() or value is None:
                    return None
                try:
                    masks[int(row[0])] = int(value, 16)
                except ValueError:
                    return None
            if any(i not in masks for i in wanted):
                return None
            return tuple(masks[i] for i in wanted)
        return None

    def memory_free_mib(self) -> tuple[tuple[int, float], ...] | None:
        """The index and free memory in MiB of each selected GPU, in the order selected.

        Only the selected GPUs are judged: a GPU that is not selected may
        report no figure (``[N/A]``) without making the read fail. A row
        that names no GPU index makes the whole read fail.
        """
        rows = self._query(SMI_FREE_QUERY)
        if rows is None:
            return None
        free: dict[int, float | None] = {}
        for row in rows:
            if len(row) != 2 or not row[0].isdigit():
                return None
            free[int(row[0])] = _amount(row[1])
        wanted = selected_indices(self._gpus, len(rows))
        if wanted is None:
            return None
        found: list[tuple[int, float]] = []
        for index in wanted:
            amount = free.get(index)
            if amount is None:
                return None
            found.append((index, amount))
        return tuple(found)


class NvmlSource:
    """Reads the selected GPUs through the GPU management library (the ``gpu`` extra).

    ``module`` stands in for the ``pynvml`` module; without it the module is
    imported on the first read.
    """

    def __init__(self, gpus: str, module: Any | None = None) -> None:
        self._gpus = gpus
        self._module = module
        self._library: Any | None = None
        self._opened: tuple[Any, list[Any]] | None = None
        self._wanted: tuple[int, ...] = ()

    def _ready(self) -> Any:
        """The module, imported and initialised once; raises when it cannot be."""
        if self._library is None:
            nvml = self._module or importlib.import_module("pynvml")
            self._module = nvml
            nvml.nvmlInit()
            self._library = nvml
        return self._library

    def present(self) -> tuple[int, ...] | None:
        """The index of every GPU the library counts, or ``None`` when it fails."""
        try:
            return tuple(range(int(self._ready().nvmlDeviceGetCount())))
        except Exception:
            return None

    def _handles(self) -> tuple[Any, list[Any]] | None:
        """The module and a handle per selected GPU, opened once."""
        if self._opened is not None:
            return self._opened
        try:
            nvml = self._ready()
            wanted = selected_indices(self._gpus, int(nvml.nvmlDeviceGetCount()))
            if wanted is None:
                return None
            self._opened = (nvml, [nvml.nvmlDeviceGetHandleByIndex(i) for i in wanted])
            self._wanted = wanted
        except Exception:
            return None
        return self._opened

    def processes(self) -> tuple[int, ...] | None:
        """The process ids of the compute processes on the selected GPUs."""
        opened = self._handles()
        if opened is None:
            return None
        nvml, handles = opened
        try:
            return tuple(
                int(process.pid)
                for handle in handles
                for process in nvml.nvmlDeviceGetComputeRunningProcesses(handle)
            )
        except Exception:
            return None

    def memory_used_mib(self) -> float | None:
        """The memory in use on the selected GPUs, summed, in MiB."""
        opened = self._handles()
        if opened is None:
            return None
        nvml, handles = opened
        try:
            return float(sum(nvml.nvmlDeviceGetMemoryInfo(h).used for h in handles)) / MIB
        except Exception:
            return None

    def reason_masks(self) -> tuple[int, ...] | None:
        """The active clock reason mask of each selected GPU."""
        opened = self._handles()
        if opened is None:
            return None
        nvml, handles = opened
        read = next(
            (getattr(nvml, name) for name in NVML_REASON_CALLS if hasattr(nvml, name)), None
        )
        if read is None:
            return None
        try:
            return tuple(int(read(handle)) for handle in handles)
        except Exception:
            return None

    def memory_free_mib(self) -> tuple[tuple[int, float], ...] | None:
        """The index and free memory in MiB of each selected GPU, in the order selected."""
        opened = self._handles()
        if opened is None:
            return None
        nvml, handles = opened
        try:
            free = [float(nvml.nvmlDeviceGetMemoryInfo(h).free) / MIB for h in handles]
        except Exception:
            return None
        if not all(math.isfinite(amount) and amount >= 0 for amount in free):
            return None
        return tuple(zip(self._wanted, free, strict=True))


class FailingSource:
    """The source where no GPU can be read: every read fails."""

    def processes(self) -> tuple[int, ...] | None:
        """Always ``None``."""
        return None

    def memory_used_mib(self) -> float | None:
        """Always ``None``."""
        return None

    def reason_masks(self) -> tuple[int, ...] | None:
        """Always ``None``."""
        return None

    def present(self) -> tuple[int, ...] | None:
        """Always ``None``."""
        return None

    def memory_free_mib(self) -> tuple[tuple[int, float], ...] | None:
        """Always ``None``."""
        return None


def gpu_source(
    gpus: str,
    *,
    run: Run = run_command,
    which: Callable[[str], str | None] = shutil.which,
    has_module: Callable[[str], bool] | None = None,
) -> GpuSource:
    """Pick the source for the selected GPUs: the library, the query command, or none.

    Nothing is started or loaded here; the first read does that.
    """
    present = has_module or (lambda name: importlib.util.find_spec(name) is not None)
    if present("pynvml"):
        return NvmlSource(gpus)
    program = which(SMI)
    if program:
        return SmiSource(gpus, run=run, program=program)
    return FailingSource()


class Probe:
    """``api.GpuProbe`` over a source. A read that fails gives ``None``."""

    def __init__(self, source: GpuSource) -> None:
        self.source = source

    def compute_processes(self, exclude_pids: Sequence[int] = ()) -> int | None:
        """Count the compute processes on the selected GPUs, leaving out the given ones."""
        pids = self.source.processes()
        if pids is None:
            return None
        return len(set(pids) - set(exclude_pids))

    def memory_used_mib(self) -> float | None:
        """Return the memory in use on the selected GPUs, summed, in MiB."""
        return self.source.memory_used_mib()
