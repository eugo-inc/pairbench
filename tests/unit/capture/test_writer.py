# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The capture writer: one JSON line per record, synced after each, an end record with a hash."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from pairbench.capture.writer import CaptureWriter
from pairbench.model import End, Header, Launch, Note, Observation, Side


def _records() -> list[Header | Side | Launch | Observation | Note]:
    return [
        Header(capture_id="cap-writer"),
        Side(name="old", kind="cmd", role="baseline", spec={"argv": ["true"]}),
        Launch(seq=1, phase="round", round=1, pos=1, name="old", timing={"run_s": 1.5}),
        Observation(seq=1, round=1, pos=1, name="old", case="wall", value=1.5),
        Note(code="made_up_note", message="a made-up note"),
    ]


def test_each_record_is_one_line_of_json_in_field_order(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    with CaptureWriter(path) as writer:
        for record in _records():
            writer.write(record)
    lines = path.read_text().splitlines()
    assert [json.loads(line)["t"] for line in lines] == ["header", "side", "launch", "obs", "note"]
    assert lines[3] == (
        '{"t":"obs","seq":1,"round":1,"pos":1,"name":"old","case":"wall","value":1.5,'
        '"n_inner":1,"reducer":"identity","suite":null}'
    )


def test_every_record_is_synced_before_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "capture.jsonl"
    synced: list[int] = []
    real_fsync = os.fsync

    def counting(fd: int) -> None:
        real_fsync(fd)
        synced.append(len(path.read_bytes().splitlines()))

    monkeypatch.setattr(os, "fsync", counting)
    writer = CaptureWriter(path)
    for record in _records():
        writer.write(record)
    writer.end("complete", 1)
    assert synced == [1, 2, 3, 4, 5, 6]


def test_the_end_record_carries_the_hash_of_every_byte_before_it(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    writer = CaptureWriter(path)
    for record in _records():
        writer.write(record)
    before = path.read_bytes()
    end = writer.end("complete", 1, discard_sha256="ab" * 32, finished_at="2000-01-01T00:00:00Z")
    data = path.read_bytes()
    last = json.loads(data.splitlines()[-1])
    assert last["t"] == "end"
    assert last["sha256_of_preceding"] == hashlib.sha256(before).hexdigest()
    assert last["status"] == "complete"
    assert last["rounds_completed"] == 1
    assert last["discard_sha256"] == "ab" * 32
    assert end.sha256_of_preceding == last["sha256_of_preceding"]
    assert writer.sha256 == hashlib.sha256(data).hexdigest()


def test_nothing_is_written_after_the_end_record(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    writer = CaptureWriter(path)
    writer.write(Header(capture_id="cap-writer"))
    writer.end("failed", 0)
    size = path.stat().st_size
    with pytest.raises(ValueError, match="nothing is written after its end record"):
        writer.write(Note(code="late", message="too late"))
    with pytest.raises(ValueError, match="nothing is written after its end record"):
        writer.end("complete", 0)
    assert path.stat().st_size == size
    assert writer.ended
    assert not writer.open


def test_the_end_record_goes_through_end_only(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "capture.jsonl")
    with pytest.raises(ValueError, match="end"):
        writer.write(End(status="complete", rounds_completed=0))
    writer.close()


def test_an_existing_file_is_never_written_over(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    path.write_text("kept\n")
    with pytest.raises(FileExistsError):
        CaptureWriter(path)
    assert path.read_text() == "kept\n"


def test_a_closed_writer_refuses_records(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "capture.jsonl")
    writer.close()
    writer.close()
    with pytest.raises(ValueError):
        writer.write(Header(capture_id="cap-writer"))


# The capture keeps the command line as typed, credentials included: only its owner may read it.
PRIVATE_MODE = 0o600


@pytest.mark.parametrize("umask", [0o000, 0o022], ids=["umask-000", "umask-022"])
def test_the_capture_file_is_readable_by_its_owner_only(tmp_path: Path, umask: int) -> None:
    path = tmp_path / "capture.jsonl"
    old = os.umask(umask)
    try:
        with CaptureWriter(path) as writer:
            writer.write(Header(capture_id="cap-writer"))
    finally:
        os.umask(old)
    assert path.stat().st_mode & 0o777 == PRIVATE_MODE
