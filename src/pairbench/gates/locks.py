# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Advisory file locks, taken in the order given.

1. An existing lock file is opened read-only, so a file owned by another
   user can still be locked. A missing file is created.
2. One deadline bounds the wait for all of them. A timeout or any error is
   refused with ``E_LOCK`` (exit 4) in every mode; the locks already taken
   are released first, so a run never proceeds without a lock it asked for.
3. The locks are exclusive ``flock`` locks, which a file opened read-only
   can hold.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterator, Sequence
from types import TracebackType
from typing import Any, Final

from pairbench.errors import Refusal

# How long to sleep between two tries of a lock that is held elsewhere.
RETRY_S: Final = 0.1

Opener = Callable[[str, int, int], int]
Locker = Callable[[int, int], None]


def _flock() -> tuple[Locker, int, int, int] | None:
    try:
        import fcntl
    except ImportError:
        return None
    return fcntl.flock, fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN, 0


def flock_calls() -> tuple[Locker, int, int, int] | None:
    """``fcntl.flock`` with its exclusive-without-waiting and unlock operations.

    ``None`` on a platform without ``fcntl``.
    """
    return _flock()


class HeldLocks:
    """The locks a run holds. ``release`` frees every one; it is safe to call again."""

    def __init__(self, unlock: Callable[[int], None]) -> None:
        self._held: list[tuple[str, int]] = []
        self._unlock = unlock

    def add(self, path: str, fd: int) -> None:
        """Record a lock that was taken."""
        self._held.append((path, fd))

    @property
    def paths(self) -> tuple[str, ...]:
        """The lock files held, in the order they were taken."""
        return tuple(path for path, _ in self._held)

    def release(self) -> None:
        """Release every lock, the last taken first."""
        while self._held:
            _, fd = self._held.pop()
            with contextlib.suppress(OSError):
                self._unlock(fd)
            with contextlib.suppress(OSError):
                os.close(fd)

    def __enter__(self) -> HeldLocks:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


def _open(path: str, opener: Opener) -> int:
    """Open an existing file read-only, or create a missing one.

    The file is opened without waiting, so a named pipe given as a lock file
    does not hold the run past its deadline.
    """
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        return opener(path, flags, 0)
    except FileNotFoundError:
        return opener(path, flags | os.O_CREAT, 0o644)


def _invalid(path: str) -> Refusal:
    """The refusal of a lock path the operating system cannot take, such as one with a NUL."""
    name = os.path.basename(path) or path
    return Refusal("E_LOCK", f"lock file {name!r} is not a valid path", detail={"path": path})


def acquire_locks(
    paths: Sequence[str],
    timeout_s: float,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    opener: Opener = os.open,
    locker: Any = None,
) -> HeldLocks:
    """Take every lock in the order given, within one deadline, or refuse with ``E_LOCK``.

    ``locker`` stands in for ``fcntl.flock`` and its two operations, as the
    tuple ``(flock, exclusive_without_blocking, unlock, 0)``. A file named
    twice is refused at once: the second lock could never be taken.
    """
    if not paths:
        return HeldLocks(lambda fd: None)
    calls = locker if locker is not None else _flock()
    if calls is None:
        raise Refusal("E_LOCK", "file locks are not supported on this platform")
    flock, exclusive, unlock_op, _ = calls

    def unlock(fd: int) -> None:
        flock(fd, unlock_op)

    seen: set[str] = set()
    for path in paths:
        try:
            key = os.path.realpath(path)
        except (OSError, ValueError) as exc:
            raise _invalid(path) from exc
        if key in seen:
            raise Refusal(
                "E_LOCK", f"lock file named twice: {os.path.basename(path)}", detail={"path": path}
            )
        seen.add(key)
    held = HeldLocks(unlock)
    try:
        deadline = clock() + timeout_s
        for path in paths:
            fd = _take(path, opener, flock, exclusive, deadline, timeout_s, clock, sleep)
            held.add(path, fd)
    except BaseException:
        held.release()
        raise
    return held


def _take(
    path: str,
    opener: Opener,
    flock: Locker,
    exclusive: int,
    deadline: float,
    timeout_s: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    """Open one lock file and lock it before the deadline; return its descriptor."""
    name = os.path.basename(path) or path
    try:
        fd = _open(path, opener)
    except OSError as exc:
        raise Refusal(
            "E_LOCK",
            f"lock file {name} could not be opened: {exc.strerror or 'error'}",
            detail={"path": path, "errno": exc.errno},
        ) from exc
    except ValueError as exc:
        raise _invalid(path) from exc
    try:
        while True:
            try:
                flock(fd, exclusive)
                return fd
            except BlockingIOError:
                if clock() >= deadline:
                    raise Refusal(
                        "E_LOCK",
                        f"lock {name} was not taken within {timeout_s:g} s",
                        detail={"path": path, "timeout_s": timeout_s},
                    ) from None
                sleep(min(RETRY_S, max(0.0, deadline - clock())))
            except OSError as exc:
                raise Refusal(
                    "E_LOCK",
                    f"lock {name} could not be taken: {exc.strerror or 'error'}",
                    detail={"path": path, "errno": exc.errno},
                ) from exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise


@contextlib.contextmanager
def holding(paths: Sequence[str], timeout_s: float) -> Iterator[HeldLocks]:
    """Hold the locks for the block, releasing them however it ends."""
    held = acquire_locks(paths, timeout_s)
    try:
        yield held
    finally:
        held.release()
