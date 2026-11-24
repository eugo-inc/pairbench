# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``jsonl`` reader: round trip, a torn last line, an end record that cannot be trusted."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import pairbench
from pairbench import registry
from pairbench.capture.reader import JsonlReader
from pairbench.capture.writer import CaptureWriter
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import Header, Launch, Lineup, Observation, Side

TORN_TAIL = b'{"t":"obs","seq":3,"round":2,"pos":1,"na'


def _write(path: Path, *, end: bool = True) -> None:
    writer = CaptureWriter(path)
    writer.write(Header(capture_id="cap-reader"))
    writer.write(Side(name="new", kind="cmd", spec={"argv": ["true"]}))
    writer.write(Side(name="old", kind="cmd", role="baseline", spec={"argv": ["false"]}))
    writer.write(Lineup(names=("new", "old"), rounds=1))
    writer.write(Launch(seq=1, phase="round", round=1, pos=1, name="new"))
    writer.write(Observation(seq=1, round=1, pos=1, name="new", case="wall", value=12.5))
    writer.write(Launch(seq=2, phase="round", round=1, pos=2, name="old"))
    writer.write(Observation(seq=2, round=1, pos=2, name="old", case="wall", value=14.5))
    if end:
        writer.end("complete", 1)
    else:
        writer.close()


def test_a_written_capture_reads_back_complete(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    (capture,) = JsonlReader().read(path)
    assert capture.capture_id == "cap-reader"
    assert capture.complete
    assert capture.end is not None
    assert capture.end.rounds_completed == 1
    assert [o.value for o in capture.observations] == [12.5, 14.5]
    assert capture.source is not None
    assert capture.source.torn is False
    assert capture.source.path == str(path.resolve())
    assert capture.source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_torn_last_line_is_left_out_and_marked(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path, end=False)
    with path.open("ab") as handle:
        handle.write(TORN_TAIL)
    (capture,) = JsonlReader().read(path)
    assert capture.source is not None
    assert capture.source.torn is True
    assert len(capture.observations) == 2
    assert capture.end is None
    assert not capture.complete


def test_a_capture_without_an_end_record_is_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path, end=False)
    (capture,) = JsonlReader().read(path)
    assert capture.end is None
    assert not capture.complete
    assert capture.source is not None
    assert capture.source.torn is False


def test_an_end_record_whose_hash_does_not_match_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    data = path.read_bytes()
    changed = data.replace(b'"value":12.5', b'"value":12.6', 1)
    assert changed != data
    path.write_bytes(changed)
    (capture,) = JsonlReader().read(path)
    assert capture.end is None
    assert not capture.complete
    assert capture.observations[0].value == 12.6


def test_a_copy_that_lost_its_last_line_has_no_end(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    lines = path.read_bytes().splitlines(keepends=True)
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(b"".join(lines[:-1]))
    (capture,) = JsonlReader().read(copy)
    assert capture.end is None


def test_anything_after_the_end_record_drops_it(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    with path.open("ab") as handle:
        handle.write(b'{"t":"note","code":"late","message":"written after the end"}\n')
    (capture,) = JsonlReader().read(path)
    assert capture.end is None
    assert [n.code for n in capture.notes] == ["late"]


def test_a_torn_line_after_the_end_record_drops_it(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    with path.open("ab") as handle:
        handle.write(TORN_TAIL)
    (capture,) = JsonlReader().read(path)
    assert capture.end is None
    assert capture.source is not None
    assert capture.source.torn is True


def test_two_end_records_keep_neither(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    data = path.read_bytes()
    end_line = data.splitlines(keepends=True)[-1]
    path.write_bytes(data + end_line)
    (capture,) = JsonlReader().read(path)
    assert capture.end is None


def test_a_broken_line_before_the_last_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    lines = path.read_bytes().splitlines(keepends=True)
    lines[2] = b'{"t":"side","name":\n'
    path.write_bytes(b"".join(lines))
    with pytest.raises(Refusal) as caught:
        JsonlReader().read(path)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE
    assert "line 3 of capture.jsonl" in caught.value.message


def test_a_line_that_is_no_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    lines = path.read_bytes().splitlines(keepends=True)
    lines.insert(1, b"[1, 2]\n")
    path.write_bytes(b"".join(lines))
    with pytest.raises(Refusal) as caught:
        JsonlReader().read(path)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert "line 2 of capture.jsonl is not a capture record" in caught.value.message


@pytest.mark.parametrize(
    ("line", "said"),
    [
        pytest.param(b'{"t": []}\n', "not a capture record: record type []", id="list"),
        pytest.param(b'{"t": {}}\n', "not a capture record: record type {}", id="object"),
    ],
)
def test_a_record_type_that_is_no_text_is_refused(tmp_path: Path, line: bytes, said: str) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    lines = path.read_bytes().splitlines(keepends=True)
    lines.insert(1, line)
    path.write_bytes(b"".join(lines))
    with pytest.raises(Refusal) as caught:
        JsonlReader().read(path)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert caught.value.message == said


DEEP = b"[" * 100_000


def test_a_deeply_nested_line_before_the_last_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    lines = path.read_bytes().splitlines(keepends=True)
    lines.insert(1, DEEP + b"\n")
    path.write_bytes(b"".join(lines))
    with pytest.raises(Refusal) as caught:
        JsonlReader().read(path)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE
    assert "line 2 of capture.jsonl is not JSON" in caught.value.message


def test_a_deeply_nested_last_line_is_torn(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path, end=False)
    with path.open("ab") as handle:
        handle.write(DEEP)
    (capture,) = JsonlReader().read(path)
    assert capture.source is not None
    assert capture.source.torn is True
    assert [o.value for o in capture.observations] == [12.5, 14.5]


def test_sniff_says_no_to_a_deeply_nested_first_line(tmp_path: Path) -> None:
    assert JsonlReader().sniff(tmp_path / "capture.jsonl", DEEP + b"\n") is False


def test_a_missing_file_is_refused_by_its_name(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        JsonlReader().read(tmp_path / "absent.jsonl")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert caught.value.message.startswith("cannot read absent.jsonl")
    assert str(tmp_path) not in caught.value.message


def test_sniff_knows_the_header_record(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    reader = JsonlReader()
    head = path.read_bytes()[:4096]
    assert reader.sniff(path, head) is True
    assert reader.sniff(path, b'{"t":"obs","seq":1}\n') is False
    assert reader.sniff(path, b"## host\nunit=ns\n") is False
    assert reader.sniff(path, b'{"t":"header","config":{"a":"' + b"x" * 5000) is True
    assert reader.sniff(path, b"not json at all\n") is False


def test_the_registry_and_load_capture_use_this_reader(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    _write(path)
    assert isinstance(registry.capture_reader("jsonl"), JsonlReader)
    (capture,) = pairbench.load_capture(path)
    assert capture.capture_id == "cap-reader"
    assert capture.complete
