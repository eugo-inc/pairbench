# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Advisory locks on files in a temporary folder.

The locks are real ``flock`` locks: two descriptors opened separately in one
process conflict, so a lock "held elsewhere" is a second descriptor here.
``acquire_locks`` takes no mode: a lock error is refused the same way under
every mode.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import threading
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import Refusal
from pairbench.gates import locks
from pairbench.gates.base import HostChecks
from pairbench.gates.locks import RETRY_S, acquire_locks, holding

EXIT_MACHINE = 4


class RecordingOpener:
    """Opens files for real and records the flags and mode of every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.fds: list[int] = []

    def __call__(self, path: str, flags: int, mode: int) -> int:
        self.calls.append((os.path.basename(path), flags, mode))
        fd = os.open(path, flags, mode)
        self.fds.append(fd)
        return fd

    def all_closed(self) -> bool:
        """Whether every descriptor handed out is closed; call it before opening anything else."""
        for fd in self.fds:
            try:
                os.fstat(fd)
            except OSError:
                continue
            return False
        return True


def _held_elsewhere(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _free(path: Path) -> bool:
    """Whether a lock on the file can be taken now; it is released at once."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def test_locks_are_taken_in_order_and_released(tmp_path: Path, clock: Any) -> None:
    first, second = tmp_path / "a.lock", tmp_path / "b.lock"
    first.write_text("", encoding="utf-8")
    held = acquire_locks([str(first), str(second)], 5.0, clock=clock, sleep=clock.sleep)
    assert held.paths == (str(first), str(second))
    assert second.exists()
    assert not _free(first)
    assert not _free(second)
    held.release()
    assert _free(first)
    assert _free(second)
    held.release()
    assert held.paths == ()
    assert clock.slept == []


def test_an_existing_lock_file_is_opened_read_only(tmp_path: Path) -> None:
    path = tmp_path / "shared.lock"
    path.write_text("", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    opener = RecordingOpener()
    with acquire_locks([str(path)], 0.0, opener=opener) as held:
        assert held.paths == (str(path),)
    assert len(opener.calls) == 1
    name, flags, _ = opener.calls[0]
    assert name == "shared.lock"
    assert flags & os.O_ACCMODE == os.O_RDONLY
    assert flags & os.O_CREAT == 0


def test_a_missing_lock_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "new.lock"
    opener = RecordingOpener()
    with acquire_locks([str(path)], 0.0, opener=opener):
        assert path.exists()
    assert [(n, f & os.O_CREAT != 0, m) for n, f, m in opener.calls] == [
        ("new.lock", False, 0),
        ("new.lock", True, 0o644),
    ]
    assert opener.calls[1][1] & os.O_ACCMODE == os.O_RDONLY


def test_a_lock_held_elsewhere_is_refused_after_the_timeout(tmp_path: Path, clock: Any) -> None:
    path = tmp_path / "gpu.lock"
    other = _held_elsewhere(path)
    try:
        with pytest.raises(Refusal) as caught:
            acquire_locks([str(path)], 0.25, clock=clock, sleep=clock.sleep)
    finally:
        os.close(other)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock gpu.lock was not taken within 0.25 s"
    assert clock.slept[:2] == [RETRY_S, RETRY_S]
    assert len(clock.slept) == 3
    assert sum(clock.slept) == pytest.approx(0.25)


def test_a_lock_freed_before_the_deadline_is_taken(tmp_path: Path, clock: Any) -> None:
    path = tmp_path / "gpu.lock"
    other = _held_elsewhere(path)

    def free(count: int) -> None:
        if count == 2:
            os.close(other)

    clock.on_sleep = free
    with acquire_locks([str(path)], 10.0, clock=clock, sleep=clock.sleep) as held:
        assert held.paths == (str(path),)
    assert clock.slept == [RETRY_S, RETRY_S]


def test_mutant_a_lock_error_never_lets_the_run_proceed(tmp_path: Path) -> None:
    """A lock that cannot be taken is refused, and the locks taken before it are released."""
    first, second = tmp_path / "a.lock", tmp_path / "b.lock"
    other = _held_elsewhere(second)
    opener = RecordingOpener()
    try:
        with pytest.raises(Refusal) as caught:
            acquire_locks([str(first), str(second)], 0.0, opener=opener)
        assert opener.all_closed()
    finally:
        os.close(other)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock b.lock was not taken within 0 s"
    assert len(opener.fds) == 2
    assert _free(first)


def test_a_lock_file_that_cannot_be_opened_is_refused(tmp_path: Path) -> None:
    def denied(path: str, flags: int, mode: int) -> int:
        raise PermissionError(errno.EACCES, "Permission denied")

    with pytest.raises(Refusal) as caught:
        acquire_locks([str(tmp_path / "x.lock")], 1.0, opener=denied)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock file x.lock could not be opened: Permission denied"


def test_a_lock_path_with_a_nul_character_is_refused_before_any_is_taken(tmp_path: Path) -> None:
    opener = RecordingOpener()
    with pytest.raises(Refusal) as caught:
        acquire_locks([str(tmp_path / "a.lock"), str(tmp_path / "b\0.lock")], 1.0, opener=opener)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock file 'b\\x00.lock' is not a valid path"
    assert opener.calls == []


def test_a_lock_path_the_opener_rejects_is_refused(tmp_path: Path) -> None:
    def rejects(path: str, flags: int, mode: int) -> int:
        raise ValueError("made-up rejection")

    with pytest.raises(Refusal) as caught:
        acquire_locks([str(tmp_path / "x.lock")], 1.0, opener=rejects)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock file 'x.lock' is not a valid path"


def test_a_lock_file_that_is_a_named_pipe_is_opened_without_waiting(tmp_path: Path) -> None:
    path = tmp_path / "a.lock"
    os.mkfifo(path)
    outcome: list[Any] = []

    def take() -> None:
        try:
            outcome.append(acquire_locks([str(path)], 0.0))
        except Refusal as refusal:
            outcome.append(refusal)

    worker = threading.Thread(target=take, daemon=True)
    worker.start()
    worker.join(5.0)
    try:
        assert not worker.is_alive()
        assert len(outcome) == 1
        assert isinstance(outcome[0], locks.HeldLocks)
        assert outcome[0].paths == (str(path),)
    finally:
        if worker.is_alive():
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
            worker.join(5.0)
        for held in outcome:
            if isinstance(held, locks.HeldLocks):
                held.release()


def test_a_lock_error_other_than_held_is_refused_and_the_file_closed(tmp_path: Path) -> None:
    first, second = tmp_path / "a.lock", tmp_path / "b.lock"
    locked: list[int] = []
    opener = RecordingOpener()

    def flock(fd: int, op: int) -> None:
        if op == fcntl.LOCK_UN:
            locked.remove(fd)
            return
        if len(locked) == 1:
            raise OSError(errno.ENOLCK, "No locks available")
        locked.append(fd)

    with pytest.raises(Refusal) as caught:
        acquire_locks(
            [str(first), str(second)],
            1.0,
            opener=opener,
            locker=(flock, fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN, 0),
        )
    assert opener.all_closed()
    assert len(opener.fds) == 2
    assert caught.value.code == "E_LOCK"
    assert caught.value.message == "lock b.lock could not be taken: No locks available"
    assert locked == []


def test_an_interruption_releases_the_locks_taken(tmp_path: Path) -> None:
    first, second = tmp_path / "a.lock", tmp_path / "b.lock"

    def flock(fd: int, op: int) -> None:
        if op == fcntl.LOCK_UN:
            fcntl.flock(fd, op)
            return
        if os.fstat(fd).st_ino == second.stat().st_ino:
            raise KeyboardInterrupt
        fcntl.flock(fd, op)

    second.write_text("", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        acquire_locks(
            [str(first), str(second)],
            1.0,
            locker=(flock, fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN, 0),
        )
    assert _free(first)


def test_a_lock_file_named_twice_is_refused_before_any_is_taken(tmp_path: Path) -> None:
    path = tmp_path / "a.lock"
    link = tmp_path / "b.lock"
    path.write_text("", encoding="utf-8")
    link.symlink_to(path)
    opener = RecordingOpener()
    with pytest.raises(Refusal) as caught:
        acquire_locks([str(path), str(link)], 1.0, opener=opener)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert caught.value.message == "lock file named twice: b.lock"
    assert opener.calls == []


def test_without_file_locks_on_the_platform_a_lock_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(locks, "_flock", lambda: None)
    with pytest.raises(Refusal) as caught:
        acquire_locks([str(tmp_path / "a.lock")], 1.0)
    assert caught.value.code == "E_LOCK"
    assert caught.value.message == "file locks are not supported on this platform"
    assert not (tmp_path / "a.lock").exists()


def test_no_lock_asked_for_takes_nothing() -> None:
    def never(path: str, flags: int, mode: int) -> int:
        raise AssertionError("no file should be opened")

    held = acquire_locks([], 1.0, opener=never)
    assert held.paths == ()
    held.release()


def test_holding_releases_the_locks_however_the_block_ends(tmp_path: Path) -> None:
    path = tmp_path / "a.lock"
    with pytest.raises(ValueError, match="made-up failure"), holding([str(path)], 1.0):
        assert not _free(path)
        raise ValueError("made-up failure")
    assert _free(path)


def test_the_machine_checks_take_locks_with_their_clock(tmp_path: Path, clock: Any) -> None:
    path = tmp_path / "a.lock"
    other = _held_elsewhere(path)
    checks = HostChecks(root=None, system="linux", clock=clock, sleep=clock.sleep)
    try:
        with pytest.raises(Refusal) as caught:
            checks.acquire_locks([str(path)], 0.5)
    finally:
        os.close(other)
    assert caught.value.code == "E_LOCK"
    assert caught.value.exit_code == EXIT_MACHINE
    assert clock.slept[0] == RETRY_S
    assert sum(clock.slept) == pytest.approx(0.5)
