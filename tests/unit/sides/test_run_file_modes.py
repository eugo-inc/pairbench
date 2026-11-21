# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The files that hold what a process printed are owner-only, whatever the umask.

``open_private`` makes them; the two runs of a positive control and a failed
serving launch keep their output in files it opens. ``make_owner_only`` takes
the group's and others' permissions off the files a launch's own programs
write into its folder.
"""

from __future__ import annotations

import contextlib
import os
import stat
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench.sides.base import OpenFolder, make_owner_only, open_private
from pairbench.sides.container import make_run_folders

# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
# The four files of the two runs, under the launch's folder.
RUN_FILES = ("run1/stderr.txt", "run1/stdout.txt", "run2/stderr.txt", "run2/stdout.txt")


@pytest.fixture
def with_umask() -> Iterator[Callable[[int], None]]:
    """Set the process's umask for the test, and put the first one back after it."""
    first = os.umask(0o022)
    os.umask(first)

    def set_to(mask: int) -> None:
        os.umask(mask)

    yield set_to
    os.umask(first)


def _modes(folder: Path) -> list[tuple[str, int, int]]:
    """Each regular file under ``folder``: its path there, its mode and its size."""
    found = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            info = path.stat()
            found.append(
                (path.relative_to(folder).as_posix(), stat.S_IMODE(info.st_mode), info.st_size)
            )
    return found


@pytest.mark.parametrize("mask", [0o002, 0o022], ids=["umask-002", "umask-022"])
def test_the_files_of_the_two_runs_are_owner_only_whatever_the_umask(
    tmp_path: Path, with_umask: Callable[[int], None], mask: int
) -> None:
    folder = tmp_path / "0007-old_twice"
    folder.mkdir()
    with_umask(mask)
    make_run_folders(folder)
    assert _modes(folder) == [(name, OWNER_ONLY, 0) for name in RUN_FILES]


def test_a_run_file_already_there_is_set_owner_only_and_emptied(
    tmp_path: Path, with_umask: Callable[[int], None]
) -> None:
    folder = tmp_path / "0007-old_twice"
    (folder / "run1").mkdir(parents=True)
    there = folder / "run1" / "stdout.txt"
    there.write_text("a made-up line\n", encoding="utf-8")
    there.chmod(0o644)
    with_umask(0o022)
    make_run_folders(folder)
    assert _modes(folder) == [(name, OWNER_ONLY, 0) for name in RUN_FILES]


def test_the_files_a_launch_leaves_lose_the_group_s_and_others_permissions(tmp_path: Path) -> None:
    folder = tmp_path / "0007-new"
    (folder / "run1").mkdir(parents=True)
    written = {
        "hyperfine.json": (0o644, "a made-up export\n"),
        "run1/report.nsys-rep": (0o664, "a made-up report\n"),
        "tool.sh": (0o755, "a made-up script\n"),
        "stdout.txt": (0o600, "a made-up line\n"),
    }
    for name, (mode, text) in written.items():
        (folder / name).write_text(text, encoding="utf-8")
        (folder / name).chmod(mode)
    (folder / "run1").chmod(0o755)
    outside = tmp_path / "outside.json"
    outside.write_text("a made-up file outside the folder\n", encoding="utf-8")
    outside.chmod(0o644)
    (folder / "link.json").symlink_to(outside)

    make_owner_only(folder)

    # The link is followed only to read the mode of the file outside, which keeps it.
    assert _modes(folder) == [
        ("hyperfine.json", OWNER_ONLY, len("a made-up export\n")),
        ("link.json", 0o644, len("a made-up file outside the folder\n")),
        ("run1/report.nsys-rep", OWNER_ONLY, len("a made-up report\n")),
        ("stdout.txt", OWNER_ONLY, len("a made-up line\n")),
        ("tool.sh", 0o700, len("a made-up script\n")),
    ]
    assert (folder / "link.json").is_symlink()
    assert stat.S_IMODE((folder / "run1").stat().st_mode) == 0o755


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(0o264, 0o200), (0o044, 0o000)],
    ids=["owner-may-only-write", "owner-may-neither-read-nor-write"],
)
def test_a_file_its_owner_may_not_read_loses_the_group_s_and_others_permissions(
    tmp_path: Path, mode: int, expected: int
) -> None:
    if os.geteuid() == 0:
        pytest.skip("needs a user other than root, whom permissions do not stop")
    if not mode & 0o600 and not hasattr(os, "O_PATH"):
        pytest.skip("needs a descriptor that only names a file (os.O_PATH); this system has none")
    (tmp_path / "trace.bin").write_text("a made-up trace\n", encoding="utf-8")
    (tmp_path / "trace.bin").chmod(mode)
    make_owner_only(tmp_path)
    assert stat.S_IMODE((tmp_path / "trace.bin").stat().st_mode) == expected


def test_a_file_its_owner_may_only_write_is_narrowed_where_no_descriptor_only_names_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A system without ``os.O_PATH`` opens such a file for writing; nothing is written."""
    if os.geteuid() == 0:
        pytest.skip("needs a user other than root, whom permissions do not stop")
    monkeypatch.delattr(os, "O_PATH", raising=False)
    (tmp_path / "trace.bin").write_text("a made-up trace\n", encoding="utf-8")
    (tmp_path / "trace.bin").chmod(0o264)
    make_owner_only(tmp_path)
    assert stat.S_IMODE((tmp_path / "trace.bin").stat().st_mode) == 0o200
    (tmp_path / "trace.bin").chmod(0o600)
    assert (tmp_path / "trace.bin").read_text(encoding="utf-8") == "a made-up trace\n"


def test_a_pipe_in_the_folder_keeps_its_mode(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "progress.fifo")
    (tmp_path / "progress.fifo").chmod(0o664)
    make_owner_only(tmp_path)
    assert stat.S_IMODE((tmp_path / "progress.fifo").stat().st_mode) == 0o664


@pytest.mark.parametrize(
    ("swap", "moment"),
    [
        ("link-to-folder", "looked-at"),
        ("link-to-file", "looked-at"),
        ("link-to-file", "opened"),
        ("folder-moved-in", "looked-at"),
    ],
)
def test_a_file_swapped_while_the_pass_runs_leaves_what_takes_its_place_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str, moment: str
) -> None:
    """A user who may write into the folder puts something of the caller's in a file's place."""
    folder = tmp_path / "0007-new"
    folder.mkdir()
    name = folder / "hyperfine.json"
    name.write_text("a made-up export\n", encoding="utf-8")
    name.chmod(0o664)
    # A folder or a file of the caller's elsewhere, that the group and others may read.
    elsewhere = tmp_path / "home"
    if swap == "link-to-file":
        elsewhere.write_text("a made-up script\n", encoding="utf-8")
    else:
        elsewhere.mkdir()
    elsewhere.chmod(0o755)
    swapped: list[str] = []

    def swap_after(look: Callable[..., os.stat_result]) -> Callable[..., os.stat_result]:
        def looked(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            found = look(path, *args, **kwargs)
            if not swapped and (moment == "opened" or str(path).endswith(name.name)):
                if swap == "folder-moved-in":
                    name.unlink()
                    elsewhere.rename(name)
                else:
                    (folder / "swap").symlink_to(elsewhere)
                    os.replace(folder / "swap", name)
                swapped.append(str(path))
            return found

        return looked

    if moment == "opened":
        monkeypatch.setattr(os, "fstat", swap_after(os.fstat))
    else:
        monkeypatch.setattr(os, "lstat", swap_after(os.lstat))
        monkeypatch.setattr(os, "stat", swap_after(os.stat))
    make_owner_only(folder)
    assert len(swapped) == 1
    taken = name if swap == "folder-moved-in" else elsewhere
    assert stat.S_IMODE(taken.stat().st_mode) == 0o755


def test_a_file_another_user_owns_keeps_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "hyperfine.json").write_text("a made-up export\n", encoding="utf-8")
    (tmp_path / "hyperfine.json").chmod(0o644)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
    make_owner_only(tmp_path)
    assert stat.S_IMODE((tmp_path / "hyperfine.json").stat().st_mode) == 0o644


@pytest.mark.parametrize("append", [False, True], ids=["write", "append"])
def test_open_private_sets_a_file_already_there_owner_only(
    tmp_path: Path, with_umask: Callable[[int], None], append: bool
) -> None:
    there = tmp_path / "stderr.txt"
    there.write_text("a made-up line\n", encoding="utf-8")
    there.chmod(0o644)
    with_umask(0o022)
    with open_private(there, append=append) as handle:
        handle.write(b"another made-up line\n")
    assert stat.S_IMODE(there.stat().st_mode) == OWNER_ONLY


# A file already there, longer than what is written into it, so a file that is
# not emptied first keeps the end of its old text.
OLD_TEXT = "a made-up line, longer than the one written after it\n"
NEW_TEXT = "a short made-up line\n"


@pytest.mark.parametrize(
    ("append", "expected"),
    [(False, NEW_TEXT), (True, OLD_TEXT + NEW_TEXT)],
    ids=["write-empties-it", "append-keeps-it"],
)
def test_open_private_empties_a_file_already_there_unless_it_appends(
    tmp_path: Path, append: bool, expected: str
) -> None:
    there = tmp_path / "stdout.txt"
    there.write_text(OLD_TEXT, encoding="utf-8")
    with open_private(there, append=append) as handle:
        handle.write(NEW_TEXT.encode())
    assert there.read_text(encoding="utf-8") == expected


def test_a_link_to_a_folder_leaves_the_files_of_the_folder_it_names_alone(tmp_path: Path) -> None:
    folder = tmp_path / "0007-new"
    folder.mkdir()
    elsewhere = tmp_path / "home"
    elsewhere.mkdir()
    (elsewhere / "notes.txt").write_text("a made-up note\n", encoding="utf-8")
    (elsewhere / "notes.txt").chmod(0o644)
    (folder / "linked").symlink_to(elsewhere, target_is_directory=True)
    make_owner_only(folder)
    assert stat.S_IMODE((elsewhere / "notes.txt").stat().st_mode) == 0o644


# How long the pass may take over one file before it is taken to wait on a pipe.
PASS_WAIT_S = 30.0


def test_a_pipe_swapped_in_after_the_file_is_looked_at_does_not_stop_the_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pipe opened for reading waits for a writer unless it is opened without waiting."""
    folder = tmp_path / "0007-new"
    folder.mkdir()
    name = folder / "hyperfine.json"
    name.write_text("a made-up export\n", encoding="utf-8")
    name.chmod(0o664)
    swapped: list[str] = []
    look = os.stat

    def looked(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
        found = look(path, *args, **kwargs)
        if not swapped and str(path) == name.name:
            name.unlink()
            os.mkfifo(name)
            name.chmod(0o664)
            swapped.append(str(path))
        return found

    monkeypatch.setattr(os, "stat", looked)
    ended = threading.Event()

    def run_the_pass() -> None:
        make_owner_only(folder)
        ended.set()

    worker = threading.Thread(target=run_the_pass, daemon=True)
    worker.start()
    in_time = ended.wait(PASS_WAIT_S)
    if not in_time:
        # A writer that opens the pipe lets a reader waiting on it go on.
        with contextlib.suppress(OSError):
            os.close(os.open(name, os.O_WRONLY | os.O_NONBLOCK))
        worker.join(PASS_WAIT_S)
    monkeypatch.undo()
    assert (in_time, swapped) == (True, [name.name])
    found = name.lstat()
    assert (stat.S_ISFIFO(found.st_mode), stat.S_IMODE(found.st_mode)) == (True, 0o664)


@pytest.mark.parametrize("mode", [0o640, 0o660, 0o604], ids=["0640", "0660", "0604"])
def test_a_file_only_the_group_or_only_others_may_use_ends_owner_only(
    tmp_path: Path, mode: int
) -> None:
    (tmp_path / "hyperfine.json").write_text("a made-up export\n", encoding="utf-8")
    (tmp_path / "hyperfine.json").chmod(mode)
    make_owner_only(tmp_path)
    assert stat.S_IMODE((tmp_path / "hyperfine.json").stat().st_mode) == OWNER_ONLY


@pytest.mark.parametrize("top", ["missing", "not-enterable", "a-file"])
def test_a_folder_that_cannot_be_opened_is_passed_over_without_an_error(
    tmp_path: Path, top: str
) -> None:
    folder = tmp_path / "0007-new"
    if top == "not-enterable":
        if os.geteuid() == 0:
            pytest.skip("needs a user other than root, whom permissions do not stop")
        folder.mkdir()
        (folder / "hyperfine.json").write_text("a made-up export\n", encoding="utf-8")
        folder.chmod(0o000)
    elif top == "a-file":
        folder.write_text("a made-up file where a folder was asked for\n", encoding="utf-8")
        folder.chmod(0o644)
    try:
        assert make_owner_only(folder) is None
    finally:
        if folder.is_dir():
            folder.chmod(0o700)
    if top == "a-file":
        assert stat.S_IMODE(folder.stat().st_mode) == 0o644


# Deeper than a walk that recurses once per folder can go with the interpreter's
# default limit on nested calls.
DEEP = 1100
# Fewer descriptors than there are folders in the chain.
FEW_DESCRIPTORS = 256


@pytest.mark.parametrize(
    "limit", [None, FEW_DESCRIPTORS], ids=["descriptors-as-set", "few-descriptors"]
)
def test_a_file_at_the_bottom_of_a_deep_chain_of_folders_ends_owner_only(
    tmp_path: Path, limit: int | None
) -> None:
    resource = pytest.importorskip("resource", reason="needs the resource module of a Unix system")
    chain = [tmp_path / "0007-new"]
    chain += [chain[0] / "/".join(["d"] * depth) for depth in range(1, DEEP + 1)]
    for folder in chain:
        folder.mkdir()
    bottom = chain[-1] / "hyperfine.json"
    bottom.write_text("a made-up export\n", encoding="utf-8")
    bottom.chmod(0o644)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (limit or soft, hard))
        try:
            make_owner_only(chain[0])
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        assert stat.S_IMODE(bottom.stat().st_mode) == OWNER_ONLY
    finally:
        bottom.unlink()
        for folder in reversed(chain):
            folder.rmdir()


@pytest.mark.parametrize("replaced", ["artifacts", "run"])
def test_a_folder_above_a_launch_folder_replaced_by_a_link_leaves_what_it_names_alone(
    tmp_path: Path, replaced: str
) -> None:
    """The run folder is opened once; the folders below it are reached without links."""
    run = tmp_path / "run"
    launch = run / "artifacts" / "0007-new"
    launch.mkdir(parents=True)
    elsewhere = tmp_path / "home"
    (elsewhere / "artifacts" / "0007-new").mkdir(parents=True)
    notes = elsewhere / "artifacts" / "0007-new" / "notes.txt"
    notes.write_text("a made-up note\n", encoding="utf-8")
    notes.chmod(0o644)
    with OpenFolder(run) as held:
        if replaced == "artifacts":
            (run / "artifacts" / "0007-new").rmdir()
            (run / "artifacts").rmdir()
            (run / "artifacts").symlink_to(elsewhere / "artifacts", target_is_directory=True)
        else:
            run.rename(tmp_path / "moved-away")
            run.symlink_to(elsewhere, target_is_directory=True)
        make_owner_only(launch, within=held)
    assert stat.S_IMODE(notes.stat().st_mode) == 0o644


def test_a_launch_folder_below_an_open_run_folder_ends_owner_only(tmp_path: Path) -> None:
    run = tmp_path / "run"
    launch = run / "artifacts" / "0007-new"
    launch.mkdir(parents=True)
    (launch / "hyperfine.json").write_text("a made-up export\n", encoding="utf-8")
    (launch / "hyperfine.json").chmod(0o644)
    (run / "plan.tsv").write_text("a made-up plan\n", encoding="utf-8")
    (run / "plan.tsv").chmod(0o644)
    with OpenFolder(run) as held:
        make_owner_only(launch, within=held)
    assert _modes(run) == [
        ("artifacts/0007-new/hyperfine.json", OWNER_ONLY, len("a made-up export\n")),
        ("plan.tsv", 0o644, len("a made-up plan\n")),
    ]


def test_a_folder_moved_away_while_the_pass_runs_takes_the_pass_no_further(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk comes back up only into the folder it went down from.

    One of two folders in the launch's folder is moved, while the pass is in
    the folder below it, into a folder of the caller's that holds folders of
    the same names. Coming back up from the moved folder leads there, not to
    the launch's folder, so the pass ends: the other name is not looked up in
    the wrong folder.
    """
    from pairbench.sides import base

    launch = tmp_path / "0007-new"
    elsewhere = tmp_path / "home"
    for name in ("p", "q"):
        (launch / name / "inner").mkdir(parents=True)
        (elsewhere / name).mkdir(parents=True)
        (elsewhere / name / "notes.txt").write_text("a made-up note\n", encoding="utf-8")
        (elsewhere / name / "notes.txt").chmod(0o644)
    inner = {
        (found.st_dev, found.st_ino): name
        for name in ("p", "q")
        for found in [(launch / name / "inner").stat()]
    }
    entries = base._owner_only_entries
    moved: list[str] = []

    def move_while_inside(folder_fd: int, uid: int) -> list[str]:
        found = os.fstat(folder_fd)
        name = inner.get((found.st_dev, found.st_ino))
        if name is not None and not moved:
            (launch / name).rename(elsewhere / "moved")
            moved.append(name)
        return entries(folder_fd, uid)

    monkeypatch.setattr(base, "_owner_only_entries", move_while_inside)
    make_owner_only(launch)
    assert len(moved) == 1
    assert _modes(elsewhere) == [
        ("p/notes.txt", 0o644, len("a made-up note\n")),
        ("q/notes.txt", 0o644, len("a made-up note\n")),
    ]
