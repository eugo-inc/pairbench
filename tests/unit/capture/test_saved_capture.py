# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A capture written from its records and read back with the ``jsonl`` reader.

The end record ``to_records`` returns carries the hash of the lines before it,
as a run writes them, so a complete capture reads back complete. A capture
without an end, or whose end says the run did not complete, stays incomplete,
and a file that lost its tail or was edited still reads back without its end.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.capture.writer import CaptureWriter
from pairbench.errors import EXIT_ANALYSIS, Refusal
from pairbench.model import Capture, record_from_json

ROUNDS = 16


def _rows(folder: Path) -> Path:
    """Rows of two sides and their twins, in an order that reverses each round."""
    names = ("new", "newtwin", "old", "oldtwin")
    lines = ["## host", "unit=s", "sides=new old", "twin=newtwin:new", "twin=oldtwin:old"]
    for r in range(1, ROUNDS + 1):
        order = names if r % 2 else tuple(reversed(names))
        lines.append("pass_order=" + " ".join(order))
        values = {"new": 1.0, "newtwin": 1.0 + r / 1000, "old": 2.0, "oldtwin": 2.0 - r / 1000}
        lines += [f"s\t{side}\t{r}\tfast\t{values[side]!r}" for side in order]
    path = folder / "rows.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _capture(folder: Path) -> Capture:
    (capture,) = pairbench.load_capture(_rows(folder), reader="text")
    assert capture.complete
    return capture


def _compact(records: list[dict[str, Any]]) -> bytes:
    """The records as a run writes them: compact JSON, one per line, in UTF-8."""
    text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    return text.encode("utf-8")


def _reload(path: Path, data: bytes) -> Capture:
    path.write_bytes(data)
    (capture,) = pairbench.load_capture(path)
    return capture


def _refusal(capture: Capture) -> Refusal:
    with pytest.raises(Refusal) as caught:
        pairbench.analyse(capture)
    return caught.value


def test_a_complete_capture_written_from_its_records_reads_back_complete(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    assert back.complete
    assert back.end is not None
    assert back.end.status == "complete"
    assert back.end.rounds_completed == ROUNDS
    assert back.source is not None and back.source.torn is False
    assert pairbench.analyse(back).comparisons == pairbench.analyse(capture).comparisons


def test_to_jsonl_gives_the_bytes_of_the_records_and_reads_back_complete(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    data = capture.to_jsonl()
    assert data == _compact(capture.to_records())
    assert _reload(tmp_path / "capture.jsonl", data).complete


def test_the_end_hash_is_the_hash_of_every_line_before_the_end(tmp_path: Path) -> None:
    records = _capture(tmp_path).to_records()
    assert records[-1]["t"] == "end"
    preceding = _compact(records[:-1])
    assert records[-1]["sha256_of_preceding"] == hashlib.sha256(preceding).hexdigest()


def test_the_records_write_the_bytes_a_run_writes(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    end = capture.end
    assert end is not None
    path = tmp_path / "written.jsonl"
    with CaptureWriter(path) as writer:
        for record in capture.to_records()[:-1]:
            writer.write(record_from_json(record))
        writer.end(
            end.status,
            end.rounds_completed,
            discard_sha256=end.discard_sha256,
            finished_at=end.finished_at,
        )
    assert path.read_bytes() == _compact(capture.to_records())


def test_the_records_of_a_capture_read_back_are_the_records_it_was_written_from(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    assert back.to_records() == capture.to_records()
    assert Capture.from_records(back.to_records()).to_records() == back.to_records()


def test_a_capture_without_an_end_stays_incomplete(tmp_path: Path) -> None:
    capture = dataclasses.replace(_capture(tmp_path), end=None)
    assert [r["t"] for r in capture.to_records()].count("end") == 0
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    assert back.end is None
    assert back.complete is False
    refusal = _refusal(back)
    assert (refusal.code, refusal.exit_code) == ("E_CAPTURE_INCOMPLETE", EXIT_ANALYSIS)
    assert refusal.message == f"the capture {capture.capture_id} has no end record"


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_a_capture_whose_run_did_not_complete_stays_incomplete(tmp_path: Path, status: str) -> None:
    capture = _capture(tmp_path)
    assert capture.end is not None
    capture = dataclasses.replace(capture, end=dataclasses.replace(capture.end, status=status))
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    assert back.end is not None
    assert back.end.status == status
    assert back.complete is False
    refusal = _refusal(back)
    assert (refusal.code, refusal.exit_code) == ("E_CAPTURE_INCOMPLETE", EXIT_ANALYSIS)
    assert refusal.message == f"the capture {capture.capture_id} ended with the status {status}"


def test_a_file_that_lost_its_end_line_reads_back_without_its_end(tmp_path: Path) -> None:
    data = _compact(_capture(tmp_path).to_records())
    cut = data[: data.rstrip(b"\n").rfind(b"\n") + 1]
    back = _reload(tmp_path / "capture.jsonl", cut)
    assert back.end is None
    assert back.source is not None and back.source.torn is False


def test_a_file_whose_end_line_is_torn_reads_back_without_its_end(tmp_path: Path) -> None:
    data = _compact(_capture(tmp_path).to_records())
    back = _reload(tmp_path / "capture.jsonl", data[:-9])
    assert back.end is None
    assert back.source is not None and back.source.torn is True


def test_a_file_with_an_edited_observation_reads_back_without_its_end(tmp_path: Path) -> None:
    records = _capture(tmp_path).to_records()
    first = next(i for i, r in enumerate(records) if r["t"] == "obs")
    records[first] = {**records[first], "value": 1.5}
    back = _reload(tmp_path / "capture.jsonl", _compact(records))
    assert back.end is None
    assert back.complete is False


def test_a_file_written_with_other_separators_reads_back_without_its_end(tmp_path: Path) -> None:
    records = _capture(tmp_path).to_records()
    text = "".join(json.dumps(r) + "\n" for r in records)
    back = _reload(tmp_path / "capture.jsonl", text.encode("utf-8"))
    assert back.end is None
    assert len(back.observations) == 4 * ROUNDS


def test_a_capture_pooled_with_its_reloaded_copy_is_refused(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    refusals = pairbench.check_pool([capture, back])
    assert [(r.code, r.exit_code, r.message) for r in refusals] == [
        ("E_POOL_SAME", EXIT_ANALYSIS, f"the capture {capture.capture_id} is given twice")
    ]
    with pytest.raises(Refusal) as caught:
        pairbench.analyse([capture, back])
    assert (caught.value.code, caught.value.message) == (
        "E_POOL_SAME",
        f"the capture {capture.capture_id} is given twice",
    )


def test_a_reloaded_copy_under_another_id_is_refused_for_its_rows(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    back = _reload(tmp_path / "capture.jsonl", _compact(capture.to_records()))
    renamed = dataclasses.replace(
        back,
        capture_id="made-up-copy",
        header=dataclasses.replace(back.header, capture_id="made-up-copy"),
    )
    refusals = pairbench.check_pool([capture, renamed])
    assert [(r.code, r.exit_code) for r in refusals] == [("E_POOL_IDENTICAL_ROWS", EXIT_ANALYSIS)]
