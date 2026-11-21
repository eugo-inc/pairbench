# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the side kinds share: two seams to the machine and the timed launch of a host process.

* ``CommandRunner`` runs a command that is not timed: a call of the container
  engine, a question to an interpreter, an ``identify`` command. The default,
  ``run_command``, captures the output and never raises for a command that
  fails or does not start.
* ``HostProcesses`` holds every call a timed launch makes on the host: the
  clock, opening the output files, starting a process, collecting its exit,
  stopping it, pinning it to CPUs. ``launch_on_host`` makes those calls in a
  fixed order. Tests replace the seam with one that records the calls.

A command side and a Python environment side are one process on the host.
``launch_on_host`` reads one monotonic nanosecond clock directly before the
call that starts the process and directly after the call that collects its
exit returns. Everything that can be done before the first read or after the
second is done there: the output files are opened and the CPUs chosen before,
the output is read and stray processes are stopped after. Between the reads it
only starts the process, waits for it and hands its id to the timeout.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Final, Protocol

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import (
    KIND_CMD,
    KIND_CONDA,
    KIND_FILE,
    KIND_PYTHON,
    KIND_ROWS,
    KIND_SERVE,
    KIND_VENV,
    PRIVATE_FILE_MODE,
    LaunchSettings,
    Side,
)


def open_private(path: Path, *, append: bool = False) -> IO[bytes]:
    """Open ``path`` for writing, readable and writable by its owner only.

    The file is made with ``PRIVATE_FILE_MODE`` and set to it after opening,
    whatever the umask and whether it existed. An existing file is emptied,
    or written at its end with ``append``. A file this process may not change
    the mode of, such as one a container wrote as another user, keeps its
    mode.
    """
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    try:
        change = getattr(os, "fchmod", None)
        if callable(change):
            with contextlib.suppress(PermissionError):
                change(descriptor, PRIVATE_FILE_MODE)
        return os.fdopen(descriptor, "ab" if append else "wb")
    except BaseException:
        os.close(descriptor)
        raise


class OpenFolder:
    """A folder opened once by its path, from which the folders below it are reached.

    A folder below it is opened one name at a time from its descriptor, never
    through a link, so a folder below it that is replaced by a link later
    leads nowhere. A folder that cannot be opened reaches nothing. ``close``,
    or leaving a ``with`` block, closes the descriptor.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._descriptor: int | None = None
        with contextlib.suppress(OSError):
            self._descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

    def __enter__(self) -> OpenFolder:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the descriptor; the folder reaches nothing after this."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def holds(self, folder: Path) -> bool:
        """Say whether ``folder`` names a folder below this one, by the names of the two paths."""
        try:
            below = folder.relative_to(self.path)
        except ValueError:
            return False
        return ".." not in below.parts

    def open_below(self, folder: Path) -> int | None:
        """Open ``folder``, which ``holds`` says lies below this one, without following a link.

        Return its descriptor, which the caller closes, or ``None`` when a name
        on the way is a link, is not a folder or cannot be opened.
        """
        if self._descriptor is None or not self.holds(folder):
            return None
        here = os.dup(self._descriptor)
        try:
            for name in folder.relative_to(self.path).parts:
                below = os.open(name, _OPEN_FOLDER, dir_fd=here)
                os.close(here)
                here = below
        except OSError:
            os.close(here)
            return None
        return here


def make_owner_only(folder: Path, *, within: OpenFolder | None = None) -> None:
    """Take the group's and others' permissions off every file the caller owns under ``folder``.

    A launch's own programs write files into its folder with the mode their
    umask gives: the export a benchmark tool writes for its driver, the report
    of a profiler, a file the workload writes. Once the launch has ended, each
    regular file there that this process's user owns keeps its owner's
    permissions only. Links are not followed and folders keep their mode. A
    file another user owns, such as one a container wrote and that was not
    handed back, keeps its mode.

    ``within``, an open folder that holds ``folder``, is where the pass starts:
    every folder from there down to ``folder`` is opened without following a
    link, so a folder on the way that is replaced by a link changes nothing.
    Without it, only ``folder`` itself may not be a link. A folder that cannot
    be opened is passed over.

    Each file is changed through a descriptor opened without following a link,
    so a name swapped for a link while the pass runs changes nothing. The walk
    holds a few descriptors at a time however deep the folders go. On a system
    with no descriptor that only names a file, a file its owner may neither
    read nor write keeps its mode.
    """
    getuid = getattr(os, "getuid", None)
    if not callable(getuid) or not _CAN_WALK:
        return
    uid = getuid()
    with contextlib.suppress(OSError):
        if within is not None and within.holds(folder):
            top = within.open_below(folder)
        else:
            top = os.open(folder, _OPEN_FOLDER)
        if top is None:
            return
        try:
            _owner_only_tree(top, uid)
        finally:
            os.close(top)


# Opens a name without following a link, without waiting on a pipe and without
# taking a terminal.
_OPEN_AS_FOUND: Final = (
    getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
)
# Opens a folder by one name as found: a name that is a link or not a folder is refused.
_OPEN_FOLDER: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _OPEN_AS_FOUND
# The walk opens names relative to an open folder and lists an open folder.
_CAN_WALK: Final = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.scandir in os.supports_fd
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
)


def _owner_only_tree(top: int, uid: int) -> None:
    """Make every file ``uid`` owns in the open folder ``top`` and the folders below it owner-only.

    The walk goes down one folder at a time and comes back up through each
    folder's entry for its parent, checking that it lands in the folder it
    came from, so it holds two descriptors at most however deep the folders
    go. Where a folder was moved away while the walk ran, the walk ends.
    """
    here = os.dup(top)
    try:
        # Each folder still being walked: its identity, and the folders in it not yet entered.
        open_folders = [(_identity(here), _owner_only_entries(here, uid))]
        while open_folders:
            waiting = open_folders[-1][1]
            if waiting:
                try:
                    below = os.open(waiting.pop(), _OPEN_FOLDER, dir_fd=here)
                except OSError:
                    continue
                os.close(here)
                here = below
                open_folders.append((_identity(here), _owner_only_entries(here, uid)))
                continue
            open_folders.pop()
            if not open_folders:
                return
            above = os.open("..", _OPEN_FOLDER, dir_fd=here)
            os.close(here)
            here = above
            if _identity(here) != open_folders[-1][0]:
                return
    finally:
        os.close(here)


def _identity(descriptor: int) -> tuple[int, int]:
    """The device and inode of the file open as ``descriptor``."""
    found = os.fstat(descriptor)
    return found.st_dev, found.st_ino


def _owner_only_entries(folder_fd: int, uid: int) -> list[str]:
    """Make the files ``uid`` owns in the open folder owner-only; return the folders in it."""
    folders: list[str] = []
    others: list[str] = []
    try:
        with os.scandir(folder_fd) as entries:
            for entry in entries:
                try:
                    is_folder = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_folder = False
                (folders if is_folder else others).append(entry.name)
    except OSError:
        return []
    for name in others:
        _make_one_owner_only(name, folder_fd, uid)
    return folders


def _others_may_use(found: os.stat_result, uid: int) -> bool:
    """Say whether ``found`` is a regular file ``uid`` owns that the group or others may use."""
    return (
        stat.S_ISREG(found.st_mode)
        and found.st_uid == uid
        and bool(stat.S_IMODE(found.st_mode) & 0o077)
    )


def _make_one_owner_only(name: str, folder_fd: int, uid: int) -> None:
    """Take the group's and others' permissions off the file ``name`` in the open folder."""
    try:
        found = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except OSError:
        return
    if not _others_may_use(found, uid):
        return
    # A file its owner may only write is opened for writing, and one its owner
    # may neither read nor write only to name it, where the system can; nothing
    # is read or written.
    name_only = getattr(os, "O_PATH", None)
    accesses = (os.O_RDONLY, os.O_WRONLY) + (() if name_only is None else (name_only,))
    for access in accesses:
        try:
            descriptor = os.open(name, access | _OPEN_AS_FOUND, dir_fd=folder_fd)
        except PermissionError:
            continue
        except OSError:
            return
        try:
            opened = os.fstat(descriptor)
            if _others_may_use(opened, uid):
                _change_mode(descriptor, stat.S_IMODE(opened.st_mode) & 0o700)
        except OSError:
            pass
        finally:
            os.close(descriptor)
        return


def _change_mode(descriptor: int, mode: int) -> None:
    """Change the mode of the file open as ``descriptor``, whatever it was opened for."""
    try:
        os.fchmod(descriptor, mode)
    except OSError:
        # A descriptor that only names its file cannot be changed through; the
        # process's own entry for it names that same file, not the name in the folder.
        os.chmod(f"/proc/self/fd/{descriptor}", mode)


# The exit code reported for a command that could not be started at all, as a
# shell reports a command it cannot find.
NOT_STARTED_RC: Final = 127

# Variables of the tool itself. They are not handed down to a launch from the
# caller's environment: a launch gets a pad or a work factor only when the
# runner adds one to ``LaunchRequest.env``.
TOOL_VARIABLE_PREFIX: Final = "PAIRBENCH_"

# The variable that selects the visible GPUs of a process on the host, and the
# one that orders them. The CUDA Programming Guide, v13.5, "CUDA Environment
# Variables"
# (https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html)
# says that integer indices in CUDA_VISIBLE_DEVICES are the ordinals nvidia-smi
# gives, and that CUDA enumerates the devices fastest first unless
# CUDA_DEVICE_ORDER is PCI_BUS_ID, which enumerates them by PCI bus id in
# ascending order. A host side whose ``gpus`` names devices gets both
# variables; ``all`` removes the visible-device variable instead.
GPU_VARIABLE: Final = "CUDA_VISIBLE_DEVICES"
GPU_ORDER_VARIABLE: Final = "CUDA_DEVICE_ORDER"
GPU_ORDER: Final = "PCI_BUS_ID"

# Launch settings a process on the host cannot honour.
HOST_REFUSED_SETTINGS: Final[tuple[str, ...]] = ("memory", "mounts", "network")


# ---------------------------------------------------------------------------
# Commands that are not timed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Completed:
    """What an untimed command gave back: its exit code and its output as text.

    ``started`` is false for a program that could not be started at all.
    """

    rc: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    started: bool = True


class CommandRunner(Protocol):
    """Runs one command that is not timed and returns what it printed.

    ``env`` of ``None`` hands down the caller's environment. A command that
    does not start comes back with ``NOT_STARTED_RC`` and ``started`` false;
    one that runs into ``timeout_s`` is stopped and comes back with
    ``timed_out`` set. Nothing is raised for either.
    """

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed: ...


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def run_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    timeout_s: float | None = None,
) -> Completed:
    """The default ``CommandRunner``: run the command and capture its output."""
    try:
        done = subprocess.run(
            list(argv),
            env=dict(env) if env is not None else None,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return Completed(
            rc=-int(signal.SIGKILL),
            stdout=_text(exc.stdout),
            stderr=_text(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return Completed(rc=NOT_STARTED_RC, stderr=str(exc), started=False)
    return Completed(rc=done.returncode, stdout=done.stdout, stderr=done.stderr)


# ---------------------------------------------------------------------------
# Resource usage of an exited process
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessUsage:
    """The resource usage the exit status call reported for one launch.

    ``user_s`` and ``sys_s`` are the CPU time; ``figures`` holds the other
    figures under the keys of ``api.USAGE_KEYS``.
    """

    user_s: float
    sys_s: float
    figures: Mapping[str, float] = field(default_factory=dict)

    def plus(self, other: ProcessUsage) -> ProcessUsage:
        """Return the usage of two processes that ran one after the other.

        CPU time, context switches and page faults add up. The peak resident
        memory of the two is the larger of the two peaks.
        """
        figures: dict[str, float] = {}
        for key in api.USAGE_KEYS:
            mine, theirs = self.figures.get(key), other.figures.get(key)
            if mine is None or theirs is None:
                continue
            figures[key] = max(mine, theirs) if key == api.USAGE_RSS_PEAK_BYTES else mine + theirs
        return ProcessUsage(self.user_s + other.user_s, self.sys_s + other.sys_s, figures)


def rss_scale(platform: str) -> int:
    """Return the bytes in one unit of ``ru_maxrss``.

    getrusage(2) gives the peak resident set size in kilobytes on Linux and
    the BSDs and in bytes on macOS.
    """
    return 1 if platform == "darwin" else 1024


def usage_from_rusage(ru: Any, platform: str | None = None) -> ProcessUsage:
    """Turn what ``os.wait4`` returned for a process into a ``ProcessUsage``.

    The figures cover the process and the children it waited for.
    """
    scale = rss_scale(sys.platform if platform is None else platform)
    return ProcessUsage(
        user_s=float(ru.ru_utime),
        sys_s=float(ru.ru_stime),
        figures={
            api.USAGE_RSS_PEAK_BYTES: float(ru.ru_maxrss * scale),
            api.USAGE_CTX_VOLUNTARY: float(ru.ru_nvcsw),
            api.USAGE_CTX_INVOLUNTARY: float(ru.ru_nivcsw),
            api.USAGE_FAULTS_MAJOR: float(ru.ru_majflt),
            api.USAGE_FAULTS_MINOR: float(ru.ru_minflt),
        },
    )


# ---------------------------------------------------------------------------
# The timed launch of a process on the host
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostRun:
    """One process of a launch on the host.

    ``executable`` is the file to start when it is known already; ``argv[0]``
    is then only what the process sees as its own name.
    """

    argv: tuple[str, ...]
    env: Mapping[str, str]
    stdout: Path
    stderr: Path
    cwd: str | None = None
    executable: str | None = None


class HostProcesses:
    """The calls a timed launch makes on the host. Tests replace it with a recording one.

    A process is started in a session of its own, so that stopping it stops
    every process it started as well.
    """

    def __init__(self) -> None:
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def clock(self) -> int:
        """Read the monotonic clock, in nanoseconds."""
        return time.monotonic_ns()

    def open_output(self, path: Path) -> IO[bytes]:
        """Open a file that receives standard output or standard error of a process.

        Only its owner may read it (``open_private``): what a process
        prints may hold the values of its command line.
        """
        return open_private(path)

    def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
        """Start one process and return its id. A process that cannot start raises ``OSError``."""
        child = subprocess.Popen(
            list(run.argv),
            executable=run.executable,
            env=dict(run.env),
            cwd=run.cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        self._children[child.pid] = child
        return child.pid

    def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
        """Wait for a process to exit; return its exit code and its resource usage.

        The exit code is negative when a signal ended the process. The usage
        is ``None`` where the platform has no exit status call that reports
        it.
        """
        child = self._children[pid]
        if hasattr(os, "wait4"):
            _pid, status, ru = os.wait4(pid, 0)
            rc = os.waitstatus_to_exitcode(status)
            child.returncode = rc
            del self._children[pid]
            return rc, usage_from_rusage(ru)
        rc = child.wait()
        del self._children[pid]
        return rc, None

    def kill(self, pid: int) -> None:
        """Stop a process and every process of its session that is still running."""
        try:
            if hasattr(os, "killpg"):
                os.killpg(pid, signal.SIGKILL)
            elif pid in self._children:
                self._children[pid].kill()
        except (ProcessLookupError, PermissionError):
            pass

    def pin(self, cpus: frozenset[int] | None) -> Any:
        """Let the processes started from now on run only on ``cpus``.

        The calling thread takes the CPU set, and a process inherits the set
        of the thread that starts it. Returns what ``unpin`` needs to put the
        thread back where it was. ``None`` changes nothing.
        """
        if cpus is None:
            return None
        before = os.sched_getaffinity(0)
        os.sched_setaffinity(0, cpus)
        return before

    def unpin(self, token: Any) -> None:
        """Put the calling thread back on the CPUs it had before ``pin``."""
        if token is not None:
            os.sched_setaffinity(0, token)

    def home(self) -> frozenset[int] | None:
        """The CPUs the calling thread may run on now; ``None`` where the platform cannot pin.

        A side with no CPU set of its own reads them when it is resolved,
        before the tool moves itself off another side's pinned set, and its
        launches run on them.
        """
        if not pinning_supported():
            return None
        try:
            return frozenset(os.sched_getaffinity(0))
        except OSError:
            return None


def pinning_supported() -> bool:
    """Say whether this platform lets a process choose the CPUs it runs on."""
    return hasattr(os, "sched_setaffinity") and hasattr(os, "sched_getaffinity")


class PinningFailed(OSError):
    """The CPUs of the launch setting ``cpus`` could not be given to a launch."""


class Watchdog:
    """Stops the process of a launch when the launch runs into its timeout.

    It is armed before the first clock read and cancelled after the second, so
    the launch never polls for it. Between the reads the launch only tells it
    which process is running.
    """

    def __init__(self, timeout_s: float | None, kill: Callable[[int], None]) -> None:
        self._timeout_s = timeout_s
        self._kill = kill
        self._lock = threading.Lock()
        self._pid: int | None = None
        self._fired = False
        self.killed = False
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        """Arm the timeout. Without one nothing happens."""
        if self._timeout_s is None:
            return
        self._timer = threading.Timer(self._timeout_s, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def watch(self, pid: int | None) -> None:
        """Name the process that runs now; a timeout that already passed stops it at once."""
        with self._lock:
            self._pid = pid
            if pid is not None and self._fired:
                self.killed = True
                self._kill(pid)

    @property
    def fired(self) -> bool:
        """Whether the timeout has passed."""
        return self._fired

    def _fire(self) -> None:
        with self._lock:
            self._fired = True
            if self._pid is not None:
                self.killed = True
                self._kill(self._pid)

    def cancel(self) -> None:
        """Disarm the timeout."""
        if self._timer is not None:
            self._timer.cancel()


@dataclass(frozen=True)
class HostLaunch:
    """What ``launch_on_host`` measured.

    ``run_ns`` is the second clock read minus the first. ``rc`` is zero only
    when every process that ran exited with zero, and otherwise the exit code
    of the one that failed. ``usage`` is ``None`` when the platform reported
    no usage for a process.
    """

    rc: int
    run_ns: int
    timed_out: bool
    pids: tuple[int, ...]
    usage: ProcessUsage | None


def launch_on_host(
    runs: Sequence[HostRun],
    *,
    host: HostProcesses,
    timeout_s: float | None = None,
    cpus: frozenset[int] | None = None,
    stop: Callable[[int], None] | None = None,
) -> HostLaunch:
    """Run one or two processes, one after the other, inside one clock interval.

    The second process starts only when the first exited with zero and the
    timeout has not passed. The order of the calls is fixed:

    1. every output file is opened, the timeout is armed, the CPUs are
       pinned; the timeout's thread is made before the pinning, so it does
       not run on the pinned CPUs;
    2. clock; start, collect; for a second run: start, collect; clock;
    3. the timeout is disarmed, the CPUs are given back, a message about a
       process that could not start is written to its standard error file,
       the files are closed, and every process the launch left running is
       stopped.

    An interrupt between the reads stops the running process, collects it
    and is raised again. ``stop`` is how a timeout or an interrupt stops the
    running process; it defaults to ``host.kill``. A container launch passes
    one that stops the container as well as the engine's command. A timeout
    that passes after the first of two runs, before the second starts, is
    reported as a timeout.
    """
    if not 1 <= len(runs) <= 2:
        raise ValueError("a launch on the host holds one or two runs")
    files: list[tuple[IO[bytes], IO[bytes]]] = []
    pids: list[int] = []
    rcs: list[int] = []
    usages: list[ProcessUsage | None] = []
    not_started: tuple[int, str] | None = None
    halt = stop if stop is not None else host.kill
    dog = Watchdog(timeout_s, halt)
    try:
        for run in runs:
            files.append((host.open_output(run.stdout), host.open_output(run.stderr)))
        dog.start()
        try:
            try:
                token = host.pin(cpus)
            except OSError as exc:
                raise PinningFailed(str(exc)) from exc
        except BaseException:
            dog.cancel()
            raise
        try:
            current: int | None = None
            try:
                first = host.clock()
                for index, run in enumerate(runs):
                    out, err = files[index]
                    try:
                        current = host.spawn(run, out, err)
                    except OSError as exc:
                        not_started = (index, str(exc))
                        rcs.append(NOT_STARTED_RC)
                        break
                    pids.append(current)
                    dog.watch(current)
                    rc, used = host.reap(current)
                    current = None
                    dog.watch(None)
                    rcs.append(rc)
                    usages.append(used)
                    if rc != 0 or dog.fired:
                        break
                second = host.clock()
            except BaseException:
                if current is not None:
                    halt(current)
                    with contextlib.suppress(OSError, KeyError):
                        host.reap(current)
                raise
        finally:
            dog.cancel()
            host.unpin(token)
        if not_started is not None:
            files[not_started[0]][1].write(f"cannot start the command: {not_started[1]}\n".encode())
    finally:
        for out, err in files:
            out.close()
            err.close()
    for pid in pids:
        host.kill(pid)
    rc = next((value for value in rcs if value != 0), 0)
    usage: ProcessUsage | None = None
    if usages and all(item is not None for item in usages):
        usage = usages[0]
        for item in usages[1:]:
            if usage is not None and item is not None:
                usage = usage.plus(item)
    cut_short = dog.fired and not_started is None and rc == 0 and len(rcs) < len(runs)
    return HostLaunch(
        rc=rc,
        run_ns=second - first,
        timed_out=dog.killed or cut_short,
        pids=tuple(pids),
        usage=usage,
    )


def host_outcome(result: HostLaunch) -> api.LaunchOutcome:
    """Turn a launch on the host into the outcome a side returns.

    ``run_s`` and ``launch_s`` both hold the one interval. The CPU time and
    the other figures are those the exit status call reported; a platform
    that reports none gives none.
    """
    seconds = result.run_ns / 1e9
    timing: dict[str, float] = {api.TIMING_RUN_S: seconds, api.TIMING_LAUNCH_S: seconds}
    usage: Mapping[str, float] = {}
    cpu_s: float | None = None
    if result.usage is not None:
        timing[api.TIMING_USER_S] = result.usage.user_s
        timing[api.TIMING_SYS_S] = result.usage.sys_s
        cpu_s = result.usage.user_s + result.usage.sys_s
        usage = dict(result.usage.figures)
    return api.LaunchOutcome(
        rc=result.rc,
        timing=timing,
        timed_out=result.timed_out,
        cpu_s=cpu_s,
        pid=result.pids[0] if result.pids else None,
        usage=usage,
        second_pid=result.pids[1] if len(result.pids) > 1 else None,
    )


# ---------------------------------------------------------------------------
# Launch settings
# ---------------------------------------------------------------------------


def parse_cpu_list(text: str, *, side: str = "") -> frozenset[int]:
    """Read a CPU list such as ``4-7`` or ``0,2,4`` into the set of CPU numbers.

    A range whose end lies below its start is refused with ``E_USAGE``.
    """
    cpus: set[int] = set()
    for part in text.split(","):
        start, dash, end = part.partition("-")
        try:
            low = int(start)
            high = int(end) if dash else low
        except ValueError:
            raise Refusal(
                "E_USAGE", f"side {side!r}: cpus is a list such as 4-7 or 0,2,4: {text!r}"
            ) from None
        if high < low:
            raise Refusal("E_USAGE", f"side {side!r}: the CPU range {part} runs backwards")
        cpus.update(range(low, high + 1))
    return frozenset(cpus)


def refuse_host_settings(side: Side, settings: LaunchSettings) -> None:
    """Refuse a launch setting a process on the host cannot honour.

    ``memory``, ``mounts`` and ``network`` are refused with
    ``E_ENGINE_UNSUPPORTED`` whenever they are set, to an empty text as
    well, and so is ``cpus`` on a platform that does not
    let a process choose its CPUs. ``gpus`` beside an ``env`` table that sets
    the visible-device variable itself is refused with ``E_USAGE``: the two
    would disagree. ``perf_counters`` changes nothing here: the system's own
    setting decides.
    """
    for key in HOST_REFUSED_SETTINGS:
        if getattr(settings, key) not in (None, ()):
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {side.name!r}: a {side.kind} side runs on the host and cannot honour "
                f"the launch setting {key}; it applies to container sides only",
            )
    if settings.cpus is not None:
        if not pinning_supported():
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {side.name!r}: this platform does not let a process choose its CPUs, "
                "so the launch setting cpus cannot be honoured",
            )
        parse_cpu_list(settings.cpus, side=side.name)
    if settings.gpus is not None and GPU_VARIABLE in settings.env:
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: gpus and the env table both set {GPU_VARIABLE}; keep one",
        )


def require_env_pass(side: Side, settings: LaunchSettings, environ: Mapping[str, str]) -> None:
    """Refuse an ``env_pass`` variable that is not set in the caller's environment."""
    missing = [name for name in settings.env_pass if name not in environ]
    if missing:
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: env_pass names variables that are not set: {', '.join(missing)}",
        )


def host_environment(
    environ: Mapping[str, str],
    settings: LaunchSettings,
    *,
    remove: Sequence[str] = (),
    selection: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the environment of a process on the host, apart from what one launch adds.

    It is laid out in this order, a later layer winning: the caller's
    environment without the tool's own ``PAIRBENCH_`` variables and without
    the names in ``remove``; the ``env_pass`` variables; the ``selection``
    variables of a Python environment; the visible-device variable that
    ``gpus`` sets, with the device order set to the bus order (``all``
    removes the visible-device variable, so every device is visible); the
    ``env`` table of the launch settings.
    """
    env = {
        name: value
        for name, value in environ.items()
        if not name.startswith(TOOL_VARIABLE_PREFIX) and name not in remove
    }
    env.update({name: environ[name] for name in settings.env_pass if name in environ})
    env.update(selection or {})
    if settings.gpus == "all":
        env.pop(GPU_VARIABLE, None)
    elif settings.gpus is not None:
        env[GPU_VARIABLE] = settings.gpus
        env[GPU_ORDER_VARIABLE] = GPU_ORDER
    env.update(settings.env)
    return env


def resolve_workdir(side: Side, settings: LaunchSettings) -> str | None:
    """Return the working directory of a process on the host, or refuse one that is missing."""
    if settings.workdir is None:
        return None
    if not Path(settings.workdir).is_dir():
        raise Refusal(
            "E_SIDE_UNRESOLVED",
            f"side {side.name!r}: the working directory {Path(settings.workdir).name!r} "
            "does not exist",
            detail={"workdir": settings.workdir},
        )
    return settings.workdir


# The kinds whose process always runs on the host. A serving side runs there when it has no image.
HOST_KINDS: Final[frozenset[str]] = frozenset({KIND_CMD, KIND_PYTHON, KIND_VENV, KIND_CONDA})
# The kinds that run nothing: their sides have no working folder.
PROCESSLESS_KINDS: Final[frozenset[str]] = frozenset({KIND_FILE, KIND_ROWS})


def working_folder_sha256(
    side: Side, settings: LaunchSettings, *, cwd: str | None = None
) -> str | None:
    """Return the hash of the working folder a side runs in, or ``None`` when it runs nothing.

    Two sides, or one side in two captures, run in the same working folder
    when these hashes are equal; the hash is compared and kept in the
    capture, and never shown. For a side that runs on the host it is the
    hash of the folder's resolved path: ``launch.workdir`` read against the
    folder pairbench runs from (``cwd``, the current folder when ``None``),
    or that folder itself when none is set, with every link followed. So a
    folder and a link to it are one folder, and one relative path typed in
    two folders names two. A folder that does not exist, or that cannot be
    resolved, is refused with ``E_SIDE_UNRESOLVED``. For a side that runs in
    a container, an image side or a serving side with an image, and for a
    kind a plug-in adds, it is the hash of the folder as typed, a folder
    inside the image, or of the empty text when none is set. A file side and
    rows run nothing.
    """
    if side.kind in PROCESSLESS_KINDS:
        return None
    typed = settings.workdir
    on_host = side.kind in HOST_KINDS or (side.kind == KIND_SERVE and not side.spec.get("image"))
    if not on_host:
        return hashlib.sha256((typed or "").encode("utf-8", "surrogateescape")).hexdigest()
    what = (
        f"the working directory {Path(typed).name!r}"
        if typed
        else "the folder pairbench runs from, its working directory,"
    )
    try:
        base = os.getcwd() if cwd is None else cwd
        resolved = Path(base, typed or ".").resolve(strict=True)
    except FileNotFoundError:
        missing = "does not exist" if typed else "cannot be found"
        raise Refusal(
            "E_SIDE_UNRESOLVED", f"side {side.name!r}: {what} {missing}", detail={"workdir": typed}
        ) from None
    except (OSError, RuntimeError):
        # A loop of links: ``RuntimeError`` up to Python 3.12, ``OSError`` from 3.13.
        raise Refusal(
            "E_SIDE_UNRESOLVED",
            f"side {side.name!r}: {what} cannot be resolved",
            detail={"workdir": typed},
        ) from None
    if not resolved.is_dir():
        raise Refusal(
            "E_SIDE_UNRESOLVED",
            f"side {side.name!r}: {what} is not a folder",
            detail={"workdir": typed},
        )
    return hashlib.sha256(os.fsencode(resolved)).hexdigest()


def find_executable(word: str, *, environment: Mapping[str, str], cwd: str | None) -> str | None:
    """Find the file a command word starts, or ``None``.

    A word with a directory part names the file itself, relative to the
    working directory of the launch. A bare word is looked up on the ``PATH``
    of the launch environment. The file must exist and be executable.
    """
    if os.sep in word or (os.altsep is not None and os.altsep in word):
        candidate = Path(word)
        if not candidate.is_absolute():
            candidate = Path(cwd or os.getcwd()) / candidate
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return os.path.abspath(candidate)
        return None
    found = shutil.which(word, path=environment.get("PATH", os.defpath))
    return os.path.abspath(found) if found else None


def refuse_unfound(side: Side, what: str, word: str) -> Refusal:
    """Return the refusal for an executable, an interpreter or an environment that is not there."""
    return Refusal(
        "E_SIDE_UNRESOLVED",
        f"side {side.name!r}: the {what} {Path(word).name!r} was not found",
        detail={what: word},
    )


# ---------------------------------------------------------------------------
# A resolved side that runs on the host
# ---------------------------------------------------------------------------


class HostResolved:
    """A resolved command side or Python environment side: one process on the host per run.

    ``environment`` is the launch environment without what one launch adds;
    ``read_identity`` reads the identity again, ``identify`` command
    included.
    """

    def __init__(
        self,
        *,
        side: Side,
        settings: LaunchSettings,
        command: tuple[str, ...],
        executable: str,
        environment: Mapping[str, str],
        cwd: str | None,
        read_identity: Callable[[], dict[str, Any]],
        host: HostProcesses,
    ) -> None:
        self._side = side
        self._settings = settings
        self._command = command
        self._executable = executable
        self._environment = dict(environment)
        self._cwd = cwd
        self._read_identity = read_identity
        self._host = host
        self._cpus = parse_cpu_list(settings.cpus, side=side.name) if settings.cpus else None
        # Without a set of its own the side runs where the tool could run when
        # the side was resolved, not on the CPUs left once the tool moves off
        # another side's pinned set.
        self._home = host.home() if self._cpus is None else None

    @property
    def side(self) -> Side:
        return self._side

    @property
    def command(self) -> tuple[str, ...] | None:
        return self._command

    @property
    def engine(self) -> None:
        return None

    @property
    def rounds_available(self) -> int | None:
        return None

    @property
    def cannot_repeat(self) -> str | None:
        return None

    def identify(self) -> Mapping[str, Any]:
        return self._read_identity()

    def artifacts_in_side(self, host: Path) -> str:
        """The folder by its full path, which holds in the side's own working directory too."""
        return os.path.abspath(host)

    def tool_file_in_side(self, host: Path) -> str:
        """The file by its full path, which holds in the side's own working directory too."""
        return os.path.abspath(host)

    def _run(self, argv: tuple[str, ...] | None, env: Mapping[str, str], folder: Path) -> HostRun:
        command = tuple(argv) if argv else self._command
        executable = self._executable if command[0] == self._command[0] else None
        return HostRun(
            argv=command,
            env={**self._environment, **env},
            stdout=folder / api.ARTIFACT_STDOUT,
            stderr=folder / api.ARTIFACT_STDERR,
            cwd=self._cwd,
            executable=executable,
        )

    def launch(self, request: api.LaunchRequest) -> api.LaunchOutcome:
        """Run the launch as one process, or two inside one clock interval for ``second``."""
        if request.second is None:
            runs = [self._run(request.argv, request.env, request.artifacts)]
        else:
            first, second = (request.artifacts / name for name in api.RUN_FOLDERS)
            runs = [
                self._run(request.argv, request.env, first),
                self._run(request.second.argv, request.second.env, second),
            ]
        timeout_s = self._settings.timeout_s
        cpus = self._cpus if self._cpus is not None else self._home
        try:
            try:
                result = launch_on_host(runs, host=self._host, timeout_s=timeout_s, cpus=cpus)
            except PinningFailed:
                if self._cpus is not None:
                    raise
                # The CPUs the tool had cannot be given back: run where the tool runs.
                self._home = None
                result = launch_on_host(runs, host=self._host, timeout_s=timeout_s)
        except PinningFailed as exc:
            raise Refusal(
                "E_PIN_UNSUPPORTED",
                f"side {self._side.name!r}: the CPUs of the launch setting cpus cannot be "
                "pinned on this machine",
                detail={"cpus": self._settings.cpus, "error": str(exc)},
            ) from exc
        return host_outcome(result)

    def close(self) -> None:
        return None


class KindBase:
    """What every built-in side kind has: its name, the API version and the two seams."""

    name: str = ""
    api_version: int = api.API_VERSION

    def __init__(
        self, *, runner: CommandRunner | None = None, host: HostProcesses | None = None
    ) -> None:
        self._runner: CommandRunner = runner if runner is not None else run_command
        self._host = host if host is not None else HostProcesses()
