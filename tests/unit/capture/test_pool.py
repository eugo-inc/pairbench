# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Loading several captures and saying what makes two of them the same capture."""

from __future__ import annotations

import shutil
from pathlib import Path

from pairbench.capture.pool import load_captures, shared_source
from pairbench.capture.writer import CaptureWriter
from pairbench.model import Capture, Header, Lineup, Side, Source


def _write(path: Path, capture_id: str) -> None:
    writer = CaptureWriter(path)
    writer.write(Header(capture_id=capture_id))
    writer.write(Side(name="new", kind="cmd", spec={"argv": ["true"]}))
    writer.write(Side(name="old", kind="cmd", role="baseline", spec={"argv": ["false"]}))
    writer.write(Lineup(names=("new", "old"), rounds=0))
    writer.end("complete", 0)


def _bare(capture_id: str, source: Source | None) -> Capture:
    return Capture(capture_id=capture_id, header=Header(capture_id=capture_id), source=source)


def test_load_captures_keeps_the_order_of_the_files(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(first, "cap-a")
    _write(second, "cap-b")
    text = tmp_path / "c.txt"
    text.write_text("## host\nx\tnew\t1\tm\t5\n## host\nx\tnew\t1\tm\t6\n")
    captures = load_captures([second, str(first), text])
    assert [c.capture_id for c in captures[:2]] == ["cap-b", "cap-a"]
    assert len(captures) == 4
    assert [c.source.reader.run_index for c in captures[2:] if c.source and c.source.reader] == [
        0,
        1,
    ]


def test_the_same_capture_id_is_shared_first(tmp_path: Path) -> None:
    a = _bare("cap-same", Source(path="/x/a.jsonl", sha256="0" * 64))
    b = _bare("cap-same", Source(path="/x/b.jsonl", sha256="1" * 64))
    assert shared_source(a, b) == "capture id"


def test_the_same_path_is_shared(tmp_path: Path) -> None:
    a = _bare("cap-a", Source(path="/x/a.jsonl", sha256="0" * 64))
    b = _bare("cap-b", Source(path="/x/a.jsonl", sha256="1" * 64))
    assert shared_source(a, b) == "file path"


def test_the_same_bytes_under_another_name_are_shared(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    _write(path, "cap-a")
    copy = tmp_path / "copy.jsonl"
    shutil.copyfile(path, copy)
    (a,) = load_captures([path])
    (b,) = load_captures([copy])
    a = _bare("cap-one", a.source)
    b = _bare("cap-two", b.source)
    assert shared_source(a, b) == "file hash"


def test_captures_that_share_nothing(tmp_path: Path) -> None:
    a = _bare("cap-a", Source(path="/x/a.jsonl", sha256="0" * 64))
    b = _bare("cap-b", Source(path="/x/b.jsonl", sha256="1" * 64))
    assert shared_source(a, b) is None
    assert shared_source(_bare("cap-a", None), b) is None
