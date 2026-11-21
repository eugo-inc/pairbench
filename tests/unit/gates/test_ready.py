# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The readiness checks: a stop file, a floor of free GPU memory, and locks
that are tried and released without being held.

The stop file and the locks are real files in a temporary folder. A lock
"held elsewhere" is held on a second descriptor of this process, or by a
child process; the GPUs are fakes.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import GateContext
from pairbench.gates import ready as ready_module
from pairbench.gates.ready import (
    CheckLocksGate,
    GpuMemoryGate,
    StopFileGate,
    record_lock_test,
)
from pairbench.model import GateRecord, GateSettings, LaunchSettings

PRESENT = "the stop file is present"


def _stop(path: str | None) -> GateSettings:
    return GateSettings(stop_file=path)


# ---------------------------------------------------------------------------
# Stop file
# ---------------------------------------------------------------------------


def test_a_present_stop_file_fails_and_the_line_names_no_path(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    stop = tmp_path / "made-up-folder" / "hold.stop"
    stop.parent.mkdir()
    stop.write_text("", encoding="utf-8")
    record = StopFileGate().check(make_ctx(gates=_stop(str(stop))))
    assert record.name == "stop_file"
    assert record.mode == "warn"
    assert record.status == "fail"
    assert record.detail == {"message": PRESENT, "present": True}
    assert "made-up-folder" not in repr(record.to_json())
    assert "hold.stop" not in repr(record.to_json())


def test_a_missing_stop_file_passes(tmp_path: Path, make_ctx: Callable[..., GateContext]) -> None:
    record = StopFileGate().check(make_ctx(gates=_stop(str(tmp_path / "hold.stop"))))
    assert record.status == "pass"
    assert record.detail == {"present": False}


def test_a_stop_file_under_a_missing_folder_passes(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    record = StopFileGate().check(make_ctx(gates=_stop(str(tmp_path / "gone" / "hold.stop"))))
    assert record.status == "pass"
    assert record.detail == {"present": False}


def test_a_stop_file_under_a_file_passes(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (tmp_path / "plain").write_text("", encoding="utf-8")
    record = StopFileGate().check(make_ctx(gates=_stop(str(tmp_path / "plain" / "hold.stop"))))
    assert record.status == "pass"
    assert record.detail == {"present": False}


def test_a_folder_at_the_stop_path_counts_as_present(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (tmp_path / "hold.stop").mkdir()
    record = StopFileGate().check(make_ctx(gates=_stop(str(tmp_path / "hold.stop"))))
    assert record.status == "fail"
    assert record.detail == {"message": PRESENT, "present": True}


def test_a_link_at_the_stop_path_counts_whatever_it_points_at(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (tmp_path / "hold.stop").symlink_to(tmp_path / "nowhere")
    record = StopFileGate().check(make_ctx(gates=_stop(str(tmp_path / "hold.stop"))))
    assert record.status == "fail"
    assert record.detail == {"message": PRESENT, "present": True}


def test_the_stop_file_is_never_created_read_or_removed(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    stop = tmp_path / "hold.stop"
    StopFileGate().check(make_ctx(gates=_stop(str(stop))))
    assert not stop.exists()
    stop.write_text("made-up text", encoding="utf-8")
    os.chmod(stop, 0)
    try:
        StopFileGate().check(make_ctx(gates=_stop(str(stop))))
        assert stop.exists()
    finally:
        os.chmod(stop, 0o600)
    assert stop.read_text(encoding="utf-8") == "made-up text"


def test_a_stop_path_that_cannot_be_looked_up_is_unavailable(
    make_ctx: Callable[..., GateContext],
) -> None:
    def denied(path: str) -> Any:
        raise PermissionError(errno.EACCES, "Permission denied", path)

    record = StopFileGate(lstat=denied).check(make_ctx(gates=_stop("/made-up/locked/hold.stop")))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "the stop file could not be looked up: Permission denied",
        "errno": errno.EACCES,
    }
    assert "locked" not in repr(record.to_json())


def test_the_stop_file_check_keeps_the_mode_it_ran_in(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (tmp_path / "hold.stop").write_text("", encoding="utf-8")
    record = StopFileGate().check(
        make_ctx(mode="enforce", gates=_stop(str(tmp_path / "hold.stop")))
    )
    assert (record.mode, record.status) == ("enforce", "fail")


def test_with_no_stop_file_set_the_check_passes_and_reads_nothing(
    make_ctx: Callable[..., GateContext],
) -> None:
    def never(path: str) -> Any:
        raise AssertionError("the check looked up a path")

    record = StopFileGate(lstat=never).check(make_ctx())
    assert record.status == "pass"
    assert record.detail == {"message": "no stop file is set"}


# ---------------------------------------------------------------------------
# Free GPU memory
# ---------------------------------------------------------------------------


def _floor(mib: float | None) -> GateSettings:
    return GateSettings(min_gpu_free_mib=mib)


def _memory_gate(gpu: Any, asked: list[str] | None = None, system: str = "linux") -> GpuMemoryGate:
    def sources(gpus: str) -> Any:
        if asked is not None:
            asked.append(gpus)
        return gpu

    return GpuMemoryGate(system=system, gpu_sources=sources)  # type: ignore[arg-type]


def test_every_watched_gpu_over_the_floor_passes(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[((0, 81000.0), (1, 2500.0))])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0)))
    assert record.name == "gpu_memory"
    assert record.status == "pass"
    assert record.detail == {"floor_mib": 2000.0, "gpus": "all", "under": ()}
    assert record.to_json()["detail"]["under"] == []
    assert gpu.free_reads == 1


def test_a_gpu_under_the_floor_fails_naming_its_index_and_no_amount(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[((0, 81000.0), (1, 1234.5))])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0)))
    assert record.status == "fail"
    assert record.detail == {
        "message": "GPU 1 has less than 2000 MiB free",
        "floor_mib": 2000.0,
        "gpus": "all",
        "under": (1,),
    }
    assert "1234" not in repr(record.to_json())
    assert "81000" not in repr(record.to_json())


def test_two_gpus_under_the_floor_are_named_together(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[((0, 9000.0), (1, 10.0), (2, 9000.0), (3, 0.0))])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0)))
    assert record.status == "fail"
    assert record.detail["message"] == "GPUs 1, 3 have less than 2000 MiB free"
    assert record.detail["under"] == (1, 3)


def test_free_memory_equal_to_the_floor_passes(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[((0, 2000.0),)])
    assert _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0))).status == "pass"


@pytest.mark.parametrize(
    ("floor", "shown"),
    [
        (1500.5, "1500.5"),
        (4096.0, "4096"),
        (1234567.0, "1234567"),
        (0.25, "0.25"),
        # A floor given as an int through the Python interface.
        (4096, "4096"),
        (10**20, "100000000000000000000"),
    ],
)
def test_the_floor_is_shown_as_typed(
    make_ctx: Callable[..., GateContext], fake_gpu: Any, floor: float, shown: str
) -> None:
    gpu = fake_gpu(free=[((2, 0.0),)])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(floor)))
    assert record.detail["message"] == f"GPU 2 has less than {shown} MiB free"


def test_the_watched_gpus_are_those_the_sides_select(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    asked: list[str] = []
    gpu = fake_gpu(indices=(0, 1, 2, 3), free=[((3, 9000.0), (1, 9000.0))])
    ctx = make_ctx(
        gates=_floor(2000.0),
        sides={"old": LaunchSettings(gpus="3"), "new": LaunchSettings(gpus="1,3")},
    )
    record = _memory_gate(gpu, asked).check(ctx)
    assert asked == ["3,1"]
    assert record.status == "pass"
    assert record.detail["gpus"] == "3,1"


def test_a_selected_gpu_the_machine_lacks_is_unavailable(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(indices=(0, 1))
    record = _memory_gate(gpu).check(
        make_ctx(gates=_floor(2000.0), launch=LaunchSettings(gpus="5"))
    )
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "GPU 5 is not on this machine; the GPUs here are 0, 1, so its free memory "
        "cannot be read",
        "floor_mib": 2000.0,
        "gpus": "5",
    }
    assert gpu.free_reads == 0


def test_free_memory_that_cannot_be_read_is_unavailable(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[None])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "the free memory of the watched GPUs could not be read",
        "floor_mib": 2000.0,
        "gpus": "all",
    }


def test_no_gpu_to_read_is_unavailable(make_ctx: Callable[..., GateContext], fake_gpu: Any) -> None:
    gpu = fake_gpu(free=[()])
    record = _memory_gate(gpu).check(make_ctx(gates=_floor(2000.0)))
    assert record.status == "unavailable"
    assert record.detail["message"] == "no GPU is visible here, so free GPU memory cannot be read"


@pytest.mark.parametrize("system", ["darwin", "other"])
def test_free_gpu_memory_off_linux_is_unavailable(
    make_ctx: Callable[..., GateContext], fake_gpu: Any, system: str
) -> None:
    asked: list[str] = []
    record = _memory_gate(fake_gpu(), asked, system).check(make_ctx(gates=_floor(2000.0)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "free GPU memory cannot be read on this platform",
        "floor_mib": 2000.0,
        "gpus": "all",
    }
    assert asked == []


def test_the_memory_check_keeps_the_mode_it_ran_in(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    gpu = fake_gpu(free=[((0, 1.0),)])
    record = _memory_gate(gpu).check(make_ctx(mode="enforce", gates=_floor(2000.0)))
    assert (record.mode, record.status) == ("enforce", "fail")


def test_with_no_floor_set_the_check_passes_and_reads_no_gpu(
    make_ctx: Callable[..., GateContext], fake_gpu: Any
) -> None:
    asked: list[str] = []
    record = _memory_gate(fake_gpu(), asked).check(make_ctx())
    assert record.status == "pass"
    assert record.detail == {"message": "no free GPU memory floor is set"}
    assert asked == []


# ---------------------------------------------------------------------------
# Check-only locks
# ---------------------------------------------------------------------------


def _locks(*paths: Path | str, held_by_run: tuple[str, ...] = ()) -> GateSettings:
    return GateSettings(check_locks=tuple(str(p) for p in paths), locks=held_by_run)


def _files(tmp_path: Path, *names: str) -> list[Path]:
    made = []
    for name in names:
        path = tmp_path / "made-up-locks" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("made-up text", encoding="utf-8")
        made.append(path)
    return made


def _hold(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _is_free(path: Path) -> bool:
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def test_free_check_only_locks_pass_and_are_left_free(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    first, second = _files(tmp_path, "a.lock", "b.lock")
    record = CheckLocksGate().check(make_ctx(gates=_locks(first, second)))
    assert record.name == "check_locks"
    assert record.status == "pass"
    assert record.detail == {"locks": 2, "held": (), "unable": ()}
    assert _is_free(first) and _is_free(second)
    assert first.read_text(encoding="utf-8") == "made-up text"


def test_a_missing_lock_file_is_free_and_not_created(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    gone = tmp_path / "gone.lock"
    under_file = _files(tmp_path, "plain")[0] / "x.lock"
    record = CheckLocksGate().check(make_ctx(gates=_locks(gone, under_file)))
    assert record.status == "pass"
    assert record.detail == {"locks": 2, "held": (), "unable": ()}
    assert not gone.exists()


def test_a_lock_held_on_another_descriptor_fails_naming_its_place(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    first, second = _files(tmp_path, "a.lock", "b.lock")
    fd = _hold(second)
    try:
        record = CheckLocksGate().check(make_ctx(gates=_locks(first, second)))
    finally:
        os.close(fd)
    assert record.status == "fail"
    assert record.detail == {
        "message": "check-only lock 2 of 2 is held",
        "locks": 2,
        "held": (2,),
        "unable": (),
    }
    assert "made-up-locks" not in repr(record.to_json())
    assert "b.lock" not in repr(record.to_json())


def test_a_lock_held_by_another_process_fails(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    ready_r, ready_w = os.pipe()
    done_r, done_w = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child process
        os.close(ready_r)
        os.close(done_w)
        _hold(lock)
        os.write(ready_w, b"x")
        os.read(done_r, 1)
        os._exit(0)
    os.close(ready_w)
    os.close(done_r)
    try:
        assert os.read(ready_r, 1) == b"x"
        record = CheckLocksGate().check(make_ctx(gates=_locks(lock)))
    finally:
        os.close(done_w)
        os.close(ready_r)
        os.waitpid(pid, 0)
    assert record.status == "fail"
    assert record.detail["message"] == "check-only lock 1 of 1 is held"
    assert _is_free(lock)


@contextlib.contextmanager
def _held_by_child(take: Callable[[], object]) -> Iterator[None]:
    """Run ``take`` in a child process that keeps what it took until the block ends."""
    ready_r, ready_w = os.pipe()
    done_r, done_w = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child process
        try:
            os.close(ready_r)
            os.close(done_w)
            kept = take()
            os.write(ready_w, b"x")
            os.read(done_r, 1)
            del kept
        finally:
            os._exit(0)
    os.close(ready_w)
    os.close(done_r)
    try:
        assert os.read(ready_r, 1) == b"x"
        yield
    finally:
        os.close(done_w)
        os.close(ready_r)
        os.waitpid(pid, 0)


def _record_lock(path: Path, operation: int) -> Callable[[], object]:
    """A POSIX record lock on the whole file, taken with ``lockf``."""

    def take() -> object:
        mode = "r+" if operation == fcntl.LOCK_EX else "r"
        handle = open(path, mode, encoding="utf-8")  # noqa: SIM115 - kept open by the child
        fcntl.lockf(handle, operation | fcntl.LOCK_NB)
        return handle

    return take


@pytest.mark.parametrize("operation", [fcntl.LOCK_EX, fcntl.LOCK_SH], ids=["exclusive", "shared"])
def test_a_record_lock_held_by_another_process_fails(
    tmp_path: Path, make_ctx: Callable[..., GateContext], operation: int
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    with _held_by_child(_record_lock(lock, operation)):
        record = CheckLocksGate().check(make_ctx(gates=_locks(lock)))
    assert record.status == "fail"
    assert record.detail == {
        "message": "check-only lock 1 of 1 is held",
        "locks": 1,
        "held": (1,),
        "unable": (),
    }
    assert lock.read_text(encoding="utf-8") == "made-up text"


def test_a_record_lock_on_part_of_the_file_counts_as_held(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")

    def take() -> object:
        handle = open(lock, "r+", encoding="utf-8")  # noqa: SIM115 - kept open by the child
        fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB, 4, 2)
        return handle

    with _held_by_child(take):
        record = CheckLocksGate().check(make_ctx(gates=_locks(lock)))
    assert record.status == "fail"
    assert record.detail["message"] == "check-only lock 1 of 1 is held"


def test_several_held_locks_are_named_together(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    first, second, third = _files(tmp_path, "a.lock", "b.lock", "c.lock")
    held = [_hold(first), _hold(third)]
    try:
        record = CheckLocksGate().check(make_ctx(gates=_locks(first, second, third)))
    finally:
        for fd in held:
            os.close(fd)
    assert record.status == "fail"
    assert record.detail["message"] == "check-only locks 1, 3 of 3 are held"
    assert record.detail["held"] == (1, 3)


def test_the_lock_file_is_opened_read_only_without_waiting_or_creating(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    opened: list[tuple[int, int]] = []

    def opener(path: str, flags: int, mode: int = 0o777) -> int:
        fd = os.open(path, flags, mode)
        opened.append((fd, flags))
        return fd

    CheckLocksGate(opener=opener).check(make_ctx(gates=_locks(lock)))
    ((fd, flags),) = opened
    assert flags & os.O_ACCMODE == os.O_RDONLY
    assert flags & os.O_NONBLOCK
    assert flags & os.O_CLOEXEC
    assert not flags & os.O_CREAT
    with pytest.raises(OSError) as closed:
        os.fstat(fd)
    assert closed.value.errno == errno.EBADF


def test_a_lock_file_that_cannot_be_opened_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    first, second = _files(tmp_path, "a.lock", "b.lock")

    def opener(path: str, flags: int, mode: int = 0o777) -> int:
        if path.endswith("b.lock"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return os.open(path, flags, mode)

    record = CheckLocksGate(opener=opener).check(make_ctx(gates=_locks(first, second)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "check-only lock 2 of 2 could not be opened: Permission denied",
        "locks": 2,
        "held": (),
        "unable": (2,),
    }


def test_a_held_lock_fails_even_when_another_cannot_be_opened(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    first, second = _files(tmp_path, "a.lock", "b.lock")

    def opener(path: str, flags: int, mode: int = 0o777) -> int:
        if path.endswith("a.lock"):
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return os.open(path, flags, mode)

    fd = _hold(second)
    try:
        record = CheckLocksGate(opener=opener).check(make_ctx(gates=_locks(first, second)))
    finally:
        os.close(fd)
    assert record.status == "fail"
    assert record.detail == {
        "message": "check-only lock 2 of 2 is held",
        "locks": 2,
        "held": (2,),
        "unable": (1,),
    }


def test_a_lock_that_cannot_be_tried_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")

    def flock(fd: int, operation: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    calls = (flock, fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN, 0)
    record = CheckLocksGate(locker=lambda: calls).check(make_ctx(gates=_locks(lock)))
    assert record.status == "unavailable"
    assert record.detail["message"] == (
        "check-only lock 1 of 1 could not be tried: No locks available"
    )


def test_without_file_locks_the_check_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    record = CheckLocksGate(locker=lambda: None).check(make_ctx(gates=_locks(lock)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "file locks are not supported on this platform",
        "locks": 1,
        "held": (),
        "unable": (1,),
    }


def test_a_record_lock_query_that_fails_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")

    def records(fd: int) -> bool:
        raise OSError(errno.ENOLCK, "No locks available")

    record = CheckLocksGate(records=lambda: records).check(make_ctx(gates=_locks(lock)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "check-only lock 1 of 1 could not be tried: No locks available",
        "locks": 1,
        "held": (),
        "unable": (1,),
    }
    assert _is_free(lock)


def test_without_a_record_lock_query_the_check_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    gate = CheckLocksGate(records=lambda: None)
    record = gate.check(make_ctx(gates=_locks(lock)))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "record locks cannot be read on this platform",
        "locks": 1,
        "held": (),
        "unable": (1,),
    }
    report = gate.doctor()
    assert (report.status, report.summary) == (
        "unavailable",
        "record locks cannot be read on this platform",
    )


def test_the_lock_check_doctor_names_both_kinds_of_lock() -> None:
    report = CheckLocksGate().doctor()
    assert (report.status, report.summary) == (
        "ok",
        "each lock is asked for record locks, tried once with flock and released at once",
    )
    report = CheckLocksGate(locker=lambda: None).doctor()
    assert (report.status, report.summary) == (
        "unavailable",
        "file locks are not supported on this platform",
    )


def test_the_module_says_where_the_two_kinds_of_lock_do_not_see_each_other() -> None:
    # Both kinds are asked because on a Linux local filesystem one does not see the other;
    # elsewhere they can, so the module names where the claim holds and its source.
    text = " ".join((ready_module.__doc__ or "").split())
    assert "the two kinds do not see each other" not in text
    assert "on a Linux local filesystem one kind does not see the other" in text
    assert "https://man7.org/linux/man-pages/man2/flock.2.html" in text


MACOS_FLOCK = "@qqihh"
LINUX_FLOCK = "@hhqqi"


def test_the_record_lock_query_asks_for_a_write_lock_on_the_whole_file_in_each_layout() -> None:
    asked: list[tuple[int, int, bytes]] = []

    def call(fd: int, command: int, request: bytes) -> bytes:
        asked.append((fd, command, request))
        return request

    for platform, shape, fields in (
        ("linux", LINUX_FLOCK, (fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)),
        ("darwin", MACOS_FLOCK, (0, 0, 0, fcntl.F_WRLCK, os.SEEK_SET)),
    ):
        asked.clear()
        test = record_lock_test(platform, call)
        assert test is not None
        assert test(7) is True
        assert asked == [(7, fcntl.F_GETLK, struct.pack(shape, *fields))]


def test_the_record_lock_query_reads_the_kind_where_each_layout_puts_it() -> None:
    def answer(shape: str, fields: tuple[int, ...]) -> Callable[[int, int, bytes], bytes]:
        return lambda fd, command, request: struct.pack(shape, *fields)

    free_linux = record_lock_test("linux", answer(LINUX_FLOCK, (fcntl.F_UNLCK, 0, 0, 0, 0)))
    read_linux = record_lock_test("linux", answer(LINUX_FLOCK, (fcntl.F_RDLCK, 0, 0, 0, 7)))
    free_macos = record_lock_test("darwin", answer(MACOS_FLOCK, (0, 0, 0, fcntl.F_UNLCK, 0)))
    read_macos = record_lock_test("darwin", answer(MACOS_FLOCK, (0, 0, 7, fcntl.F_RDLCK, 0)))
    assert free_linux is not None and free_linux(3) is False
    assert read_linux is not None and read_linux(3) is True
    assert free_macos is not None and free_macos(3) is False
    assert read_macos is not None and read_macos(3) is True


def test_a_record_lock_answer_of_no_known_kind_or_size_is_an_error() -> None:
    unknown = record_lock_test(
        "linux", lambda fd, command, request: struct.pack(LINUX_FLOCK, 99, 0, 0, 0, 0)
    )
    short = record_lock_test("linux", lambda fd, command, request: b"\0\0")
    assert unknown is not None and short is not None
    with pytest.raises(OSError) as kind:
        unknown(3)
    assert (kind.value.errno, kind.value.strerror) == (
        errno.EIO,
        "the lock query gave a lock of no known kind",
    )
    with pytest.raises(OSError) as size:
        short(3)
    assert (size.value.errno, size.value.strerror) == (
        errno.EIO,
        "the lock query gave an answer of the wrong size",
    )


@pytest.mark.parametrize("name", ["stop_file", "gpu_memory", "check_locks"])
def test_the_readiness_checks_keep_their_own_names_in_results(name: str) -> None:
    gate = GateRecord(name=name, mode="warn", status="fail", detail={"message": "made-up"})
    assert gate.summary().name == name
    degraded = gate.degraded()
    assert degraded is not None
    assert degraded.to_json() == {"name": name, "status": "fail", "message": "made-up"}


def test_a_platform_whose_lock_layout_is_not_listed_has_no_record_lock_query() -> None:
    assert record_lock_test("made-up-os") is None
    assert record_lock_test("win32") is None


def test_a_check_only_lock_that_links_to_a_run_lock_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (run_lock,) = _files(tmp_path, "run.lock")
    link = tmp_path / "other-name.lock"
    link.symlink_to(run_lock)
    record = CheckLocksGate().check(make_ctx(gates=_locks(link, held_by_run=(str(run_lock),))))
    assert record.status == "unavailable"
    assert record.detail == {
        "message": "check-only lock 1 of 1 is a lock this run takes itself (gates.locks)",
        "locks": 1,
        "held": (),
        "unable": (1,),
    }


def test_a_check_only_lock_that_links_to_a_run_lock_not_made_yet_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    run_lock = tmp_path / "run.lock"
    link = tmp_path / "other-name.lock"
    link.symlink_to(run_lock)
    record = CheckLocksGate().check(make_ctx(gates=_locks(link, held_by_run=(str(run_lock),))))
    assert not run_lock.exists()
    assert record.status == "unavailable"
    assert record.detail["message"] == (
        "check-only lock 1 of 1 is a lock this run takes itself (gates.locks)"
    )


def test_a_check_only_lock_that_names_a_run_lock_is_told_before_it_is_opened(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (run_lock,) = _files(tmp_path, "run.lock")
    opened: list[str] = []

    def refuse(path: str, flags: int, mode: int) -> int:
        opened.append(path)
        raise PermissionError(errno.EACCES, "Permission denied")

    folder = tmp_path / "folder-link"
    folder.symlink_to(run_lock.parent)
    gates = _locks(folder / "run.lock", held_by_run=(str(run_lock),))
    record = CheckLocksGate(opener=refuse).check(make_ctx(gates=gates))
    assert opened == []
    assert record.status == "unavailable"
    assert record.detail["message"] == (
        "check-only lock 1 of 1 is a lock this run takes itself (gates.locks)"
    )


def test_a_check_only_lock_that_is_a_hard_link_to_a_run_lock_is_unavailable(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (run_lock,) = _files(tmp_path, "run.lock")
    other = tmp_path / "hard.lock"
    os.link(run_lock, other)
    fd = _hold(run_lock)
    try:
        record = CheckLocksGate().check(
            make_ctx(phase="recheck", gates=_locks(other, held_by_run=(str(run_lock),)))
        )
    finally:
        os.close(fd)
    assert record.status == "unavailable"
    assert record.detail["message"] == (
        "check-only lock 1 of 1 is a lock this run takes itself (gates.locks)"
    )


def test_the_lock_check_keeps_the_mode_it_ran_in(
    tmp_path: Path, make_ctx: Callable[..., GateContext]
) -> None:
    (lock,) = _files(tmp_path, "a.lock")
    fd = _hold(lock)
    try:
        record = CheckLocksGate().check(make_ctx(mode="enforce", gates=_locks(lock)))
    finally:
        os.close(fd)
    assert (record.mode, record.status) == ("enforce", "fail")


def test_with_no_check_only_lock_set_the_check_passes_and_opens_nothing(
    make_ctx: Callable[..., GateContext],
) -> None:
    def never(path: str, flags: int, mode: int = 0o777) -> int:
        raise AssertionError("the check opened a file")

    record = CheckLocksGate(opener=never).check(make_ctx())
    assert record.status == "pass"
    assert record.detail == {"message": "no check-only lock is set"}
