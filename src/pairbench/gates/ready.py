# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The readiness checks: a stop file, a floor of free GPU memory, and check-only locks.

Each check is off until its key is set, and the runner skips a check that is
off, so it writes no record. A check that is on is a check of its own: it
has its own record and its own line, and the mode decides what a failure
means.

1. ``stop_file`` (``gates.stop_file``) fails while a file of any kind exists
   at the path. The path is looked up without following a final link; the
   file is never created, read or removed.
2. ``gpu_memory`` (``gates.min_gpu_free_mib``) fails while a watched GPU has
   less free memory than the floor, in MiB. The watched GPUs are those the
   quiet check selects: every GPU any side selects, or every GPU.
3. ``check_locks`` (``gates.check_locks``) fails while another process holds
   one of the lock files, with ``flock`` or with a POSIX record lock
   (``fcntl`` or ``lockf``). Both kinds are asked, as on a Linux local
   filesystem one kind does not see the other (flock(2), Linux man-pages
   6.19, https://man7.org/linux/man-pages/man2/flock.2.html). Each file
   is opened read-only, asked with ``F_GETLK`` whether another process holds
   a record lock on any part of it, which takes no lock, then tried once
   with an exclusive ``flock`` that does not wait and released at once; a
   missing file is free and is not created.

A record names no path, no amount of free memory and no process: its line
names the check, the GPU index or the lock's place in the list.
"""

from __future__ import annotations

import contextlib
import errno
import os
import struct
import sys
from collections.abc import Callable, Sequence
from typing import Any, Final

from pairbench.api import API_VERSION, DoctorReport, GateContext
from pairbench.gates.locks import Locker, Opener, flock_calls
from pairbench.gates.occupancy import GpuSource, absent_message, gpu_source, missing_gpus
from pairbench.gates.platform import (
    Platform,
    System,
    all_selected,
    make_record,
    side_launches,
    this_system,
)
from pairbench.model import GateRecord

STOP_FILE: Final = "stop_file"
GPU_MEMORY: Final = "gpu_memory"
CHECK_LOCKS: Final = "check_locks"
# A floor at or above this many MiB is shown in its shortest exact form
# rather than as a whole number of digits.
WHOLE_DIGITS_UP_TO: Final = 1e15

Lstat = Callable[[str], Any]


class StopFileGate:
    """The stop-file check (``api.Gate``)."""

    name: Final = STOP_FILE
    api_version: Final = API_VERSION

    def __init__(self, *, lstat: Lstat = os.lstat) -> None:
        self._lstat = lstat

    def check(self, ctx: GateContext) -> GateRecord:
        """Look the stop file up once and report."""
        path = ctx.gates.stop_file
        if path is None:
            return make_record(STOP_FILE, ctx, "pass", "no stop file is set")
        try:
            self._lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return make_record(STOP_FILE, ctx, "pass", present=False)
        except OSError as exc:
            return make_record(
                STOP_FILE,
                ctx,
                "unavailable",
                f"the stop file could not be looked up: {exc.strerror or 'error'}",
                errno=exc.errno,
            )
        except ValueError:
            return make_record(
                STOP_FILE, ctx, "unavailable", "the stop file could not be looked up: not a path"
            )
        return make_record(STOP_FILE, ctx, "fail", "the stop file is present", present=True)

    def doctor(self) -> DoctorReport:
        """What this platform lets the check do."""
        return DoctorReport("ok", "a file is looked up without being read")


def shown_mib(value: float) -> str:
    """A number of MiB as typed: ``4096`` for 4096 or 4096.0, ``1500.5`` for 1500.5.

    A whole number given as an ``int`` is shown with all its digits.
    """
    if isinstance(value, int):
        return str(value)
    if value.is_integer() and abs(value) < WHOLE_DIGITS_UP_TO:
        return str(int(value))
    return repr(value)


class GpuMemoryGate:
    """The free GPU memory check (``api.Gate``)."""

    name: Final = GPU_MEMORY
    api_version: Final = API_VERSION

    def __init__(
        self,
        *,
        system: System | None = None,
        gpu_sources: Callable[[str], GpuSource] | None = None,
    ) -> None:
        self._system = system
        self._gpu_sources = gpu_sources or gpu_source

    def check(self, ctx: GateContext) -> GateRecord:
        """Read the free memory of each watched GPU once and report."""
        floor = ctx.gates.min_gpu_free_mib
        if floor is None:
            return make_record(GPU_MEMORY, ctx, "pass", "no free GPU memory floor is set")
        gpus = all_selected(gpus for _cpus, gpus in side_launches(ctx)) or "all"
        kept: dict[str, Any] = {"floor_mib": floor, "gpus": gpus}
        if Platform.of(ctx, self._system).system != "linux":
            return make_record(
                GPU_MEMORY,
                ctx,
                "unavailable",
                "free GPU memory cannot be read on this platform",
                **kept,
            )
        source = self._gpu_sources(gpus)
        present = source.present() if gpus != "all" else None
        missing = missing_gpus(gpus, present) if present is not None else ()
        if present is not None and missing:
            whose = "its" if len(missing) == 1 else "their"
            return make_record(
                GPU_MEMORY,
                ctx,
                "unavailable",
                f"{absent_message(missing, present)}, so {whose} free memory cannot be read",
                **kept,
            )
        free = source.memory_free_mib()
        if free is None:
            return make_record(
                GPU_MEMORY,
                ctx,
                "unavailable",
                "the free memory of the watched GPUs could not be read",
                **kept,
            )
        if not free:
            return make_record(
                GPU_MEMORY,
                ctx,
                "unavailable",
                "no GPU is visible here, so free GPU memory cannot be read",
                **kept,
            )
        under = [index for index, mib in free if mib < floor]
        if not under:
            return make_record(GPU_MEMORY, ctx, "pass", **kept, under=[])
        names = ", ".join(str(index) for index in under)
        head = f"GPU {names} has" if len(under) == 1 else f"GPUs {names} have"
        return make_record(
            GPU_MEMORY,
            ctx,
            "fail",
            f"{head} less than {shown_mib(floor)} MiB free",
            **kept,
            under=under,
        )

    def doctor(self) -> DoctorReport:
        """What this platform lets the check do."""
        system = this_system() if self._system is None else self._system
        if system != "linux":
            return DoctorReport("unavailable", "free GPU memory cannot be read on this platform")
        return DoctorReport("ok", "free memory per GPU from the GPU library or nvidia-smi")


LockCalls = tuple[Locker, int, int, int]
RecordTest = Callable[[int], bool]
FcntlCall = Callable[[int, int, bytes], bytes]

# ``struct flock`` as ``F_GETLK`` reads and writes it: the format and the place
# of ``l_type`` in it. Linux puts l_type, l_whence, l_start, l_len, l_pid
# (include/uapi/asm-generic/fcntl.h, Linux v6.17:
# https://github.com/torvalds/linux/blob/v6.17/include/uapi/asm-generic/fcntl.h);
# macOS puts l_start, l_len, l_pid, l_type, l_whence (bsd/sys/fcntl.h,
# xnu-11215.1.10:
# https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.1.10/bsd/sys/fcntl.h).
FLOCK_LAYOUTS: Final[dict[str, tuple[str, int]]] = {
    "linux": ("@hhqqi", 0),
    "darwin": ("@qqihh", 3),
}


def record_lock_test(
    platform: str = sys.platform, call: FcntlCall | None = None
) -> RecordTest | None:
    """A test of whether another process holds a POSIX record lock on a file.

    The test takes a descriptor and asks with ``F_GETLK`` which lock would
    stop a write lock on the whole file. It takes no lock, so a read-only
    descriptor will do, and it is ``True`` when a read or a write lock of
    another process covers any part of the file. ``call`` stands in for
    ``fcntl.fcntl``. ``None`` on a platform whose ``struct flock`` is not
    listed in ``FLOCK_LAYOUTS``, or without ``fcntl``.
    """
    layout = FLOCK_LAYOUTS.get(platform)
    if layout is None:
        return None
    try:
        import fcntl
    except ImportError:
        return None
    query: FcntlCall = call if call is not None else fcntl.fcntl
    shape, at = layout
    fields = [0] * len(shape.lstrip("@"))
    fields[at] = fcntl.F_WRLCK
    fields[at + 1] = os.SEEK_SET
    request = struct.pack(shape, *fields)

    def held(fd: int) -> bool:
        answer = query(fd, fcntl.F_GETLK, request)
        try:
            kind = struct.unpack(shape, answer)[at]
        except struct.error:
            raise OSError(errno.EIO, "the lock query gave an answer of the wrong size") from None
        if kind == fcntl.F_UNLCK:
            return False
        if kind in (fcntl.F_RDLCK, fcntl.F_WRLCK):
            return True
        raise OSError(errno.EIO, "the lock query gave a lock of no known kind")

    return held


def _identity(path: str) -> tuple[int, int] | None:
    try:
        found = os.stat(path)
    except (OSError, ValueError):
        return None
    return found.st_dev, found.st_ino


def _real(path: str) -> str | None:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def _places(places: Sequence[int]) -> str:
    return ", ".join(str(place) for place in places)


class CheckLocksGate:
    """The check-only lock check (``api.Gate``).

    ``opener`` stands in for ``os.open``, ``locker`` for the look-up of
    ``fcntl.flock`` and its two operations, as ``(flock,
    exclusive_without_waiting, unlock, 0)``, or ``None`` where there is none,
    and ``records`` for the look-up of the record-lock test
    (``record_lock_test``), or ``None`` where record locks cannot be read.
    """

    name: Final = CHECK_LOCKS
    api_version: Final = API_VERSION

    def __init__(
        self,
        *,
        opener: Opener = os.open,
        locker: Callable[[], LockCalls | None] = flock_calls,
        records: Callable[[], RecordTest | None] = record_lock_test,
    ) -> None:
        self._opener = opener
        self._locker = locker
        self._records = records

    def check(self, ctx: GateContext) -> GateRecord:
        """Try each check-only lock once, release it at once, and report."""
        paths = ctx.gates.check_locks
        if not paths:
            return make_record(CHECK_LOCKS, ctx, "pass", "no check-only lock is set")
        count = len(paths)
        calls = self._locker()
        records = self._records() if calls is not None else None
        if calls is None or records is None:
            return make_record(
                CHECK_LOCKS,
                ctx,
                "unavailable",
                _missing_calls(calls),
                locks=count,
                held=[],
                unable=list(range(1, count + 1)),
            )
        own_paths = {real for real in map(_real, ctx.gates.locks) if real is not None}
        own_files = {found for found in map(_identity, ctx.gates.locks) if found is not None}
        held: list[int] = []
        unable: list[tuple[int, str]] = []
        for place, path in enumerate(paths, start=1):
            outcome = self._try(path, calls, records, own_paths, own_files)
            if outcome == "held":
                held.append(place)
            elif outcome:
                unable.append((place, outcome))
        detail: dict[str, Any] = {
            "locks": count,
            "held": held,
            "unable": [place for place, _ in unable],
        }
        if held:
            head = (
                f"check-only lock {held[0]} of {count} is held"
                if len(held) == 1
                else f"check-only locks {_places(held)} of {count} are held"
            )
            return make_record(CHECK_LOCKS, ctx, "fail", head, **detail)
        if unable:
            place, reason = unable[0]
            message = f"check-only lock {place} of {count} {reason}"
            return make_record(CHECK_LOCKS, ctx, "unavailable", message, **detail)
        return make_record(CHECK_LOCKS, ctx, "pass", **detail)

    def _try(
        self,
        path: str,
        calls: LockCalls,
        records: RecordTest,
        own_paths: set[str],
        own_files: set[tuple[int, int]],
    ) -> str:
        """``held``, the reason the lock could not be tried, or ``""`` when it is free."""
        taken_by_run = "is a lock this run takes itself (gates.locks)"
        if _real(path) in own_paths:
            return taken_by_run
        flock, exclusive, unlock, _ = calls
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = self._opener(path, flags, 0)
        except (FileNotFoundError, NotADirectoryError):
            return ""
        except OSError as exc:
            return f"could not be opened: {exc.strerror or 'error'}"
        except ValueError:
            return "could not be opened: not a path"
        try:
            try:
                found = os.fstat(fd)
            except OSError as exc:
                return f"could not be tried: {exc.strerror or 'error'}"
            if (found.st_dev, found.st_ino) in own_files:
                return taken_by_run
            try:
                if records(fd):
                    return "held"
            except OSError as exc:
                return f"could not be tried: {exc.strerror or 'error'}"
            try:
                flock(fd, exclusive)
            except BlockingIOError:
                return "held"
            except OSError as exc:
                return f"could not be tried: {exc.strerror or 'error'}"
            with contextlib.suppress(OSError):
                flock(fd, unlock)
            return ""
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)

    def doctor(self) -> DoctorReport:
        """What this platform lets the check do."""
        calls = self._locker()
        if calls is None or self._records() is None:
            return DoctorReport("unavailable", _missing_calls(calls))
        return DoctorReport(
            "ok",
            "each lock is asked for record locks, tried once with flock and released at once",
        )


def _missing_calls(calls: LockCalls | None) -> str:
    if calls is None:
        return "file locks are not supported on this platform"
    return "record locks cannot be read on this platform"


__all__ = [
    "CHECK_LOCKS",
    "FLOCK_LAYOUTS",
    "GPU_MEMORY",
    "STOP_FILE",
    "CheckLocksGate",
    "GpuMemoryGate",
    "StopFileGate",
    "record_lock_test",
    "shown_mib",
]
