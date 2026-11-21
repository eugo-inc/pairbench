# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the pages say about sides that are result files of another tool, against what the tool does.

``compare`` is run on made-up result files of a time-measuring tool; the
reason it gives, the run folder it writes and the grading the FAQ shows are
then looked for in the pages.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.config import SIDE_KIND_KEYS
from pairbench.errors import EXIT_OK, EXIT_USAGE
from pairbench.model import (
    DIR_ARTIFACTS,
    DIR_RUNS,
    FILE_CAPTURE,
    FILE_MARKDOWN,
    FILE_RESULTS,
    KIND_FILE,
)

ROOT = Path(__file__).resolve().parents[3]
COMMANDS = ROOT / "docs" / "reference" / "commands.md"
FAQ = ROOT / "docs" / "faq.md"
FAQ_QUESTION = "## Can I compare results from a tool I already ran?"
SIDES = ("--side", "new=file:new-*.json", "--side", "old=file:old-*.json")
COMPARE = ("compare", *SIDES, "--driver", "hyperfine", "--baseline", "old")
ROUNDS = 12


def _export(seconds: float) -> dict[str, Any]:
    """One made-up export of the tool, with a single command timed once."""
    return {
        "results": [
            {
                "command": "bench",
                "mean": seconds,
                "stddev": 0.001,
                "median": seconds,
                "user": seconds / 2,
                "system": 0.01,
                "min": seconds,
                "max": seconds,
                "times": [seconds],
                "exit_codes": [0],
            }
        ]
    }


@pytest.fixture
def result_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder of made-up result files, one per round and side, as the working folder."""
    for side, seconds in (("new", 0.5), ("old", 0.7)):
        for round_ in range(1, ROUNDS + 1):
            value = seconds + 0.001 * (round_ % 3)
            path = tmp_path / f"{side}-{round_:02d}.json"
            path.write_text(json.dumps(_export(value)), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_folder(where: Path) -> Path:
    (folder,) = (where / DIR_RUNS).iterdir()
    return folder


def _reasons(folder: Path) -> list[str]:
    results = json.loads((folder / FILE_RESULTS).read_text(encoding="utf-8"))
    return [comparison["reason"] for comparison in results["comparisons"]]


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_compare_of_result_files_writes_the_run_folder_the_pages_name(
    cli: Callable[..., Any], result_files: Path
) -> None:
    done = cli(*COMPARE, "--assume-interleaved")
    assert done.code == EXIT_OK, done.err

    folder = _run_folder(result_files)
    written = {path.name for path in folder.iterdir()}
    assert {FILE_CAPTURE, FILE_RESULTS, FILE_MARKDOWN, DIR_ARTIFACTS} <= written
    compare = _section(COMMANDS.read_text(encoding="utf-8"), "## compare")
    for name in (FILE_CAPTURE, FILE_RESULTS, FILE_MARKDOWN, f"{DIR_ARTIFACTS}/", DIR_RUNS):
        assert f"`{name}`" in compare, name
    assert "run folder" in _section(FAQ.read_text(encoding="utf-8"), FAQ_QUESTION)


@pytest.mark.parametrize("interleaved", [False, True])
def test_the_pages_name_the_reason_compare_gives_result_files(
    cli: Callable[..., Any], result_files: Path, interleaved: bool
) -> None:
    flags = ("--assume-interleaved",) if interleaved else ()
    done = cli(*COMPARE, *flags)
    assert done.code == EXIT_OK, done.err

    (reason,) = set(_reasons(_run_folder(result_files)))
    shown = f"NO VERDICT ({reason})"
    assert shown in _section(FAQ.read_text(encoding="utf-8"), FAQ_QUESTION)
    assert shown in _section(COMMANDS.read_text(encoding="utf-8"), "## compare")


def test_the_faq_grades_the_capture_compare_wrote_with_supplied_floors(
    cli: Callable[..., Any], result_files: Path
) -> None:
    assert cli(*COMPARE, "--assume-interleaved").code == EXIT_OK
    folder = _run_folder(result_files)
    answer = _section(FAQ.read_text(encoding="utf-8"), FAQ_QUESTION)
    (code,) = re.findall(r"```python\n(.*?)```", answer, flags=re.DOTALL)
    assert "pairbench-runs/FOLDER/capture.jsonl" in code

    scope: dict[str, Any] = {}
    exec(code.replace("pairbench-runs/FOLDER", str(folder.relative_to(result_files))), scope)

    (comparison,) = scope["results"].comparisons
    assert comparison.outcome == "better"
    assert comparison.reason is None


def test_the_run_page_offers_no_kind_that_run_refuses(cli: Callable[..., Any]) -> None:
    text = COMMANDS.read_text(encoding="utf-8")
    (row,) = [line for line in text.splitlines() if line.startswith("| `--side NAME=KIND:SPEC`")]
    listed = re.findall(r"`([a-z]+)`", row.split("`KIND` is", 1)[1].split(";", 1)[0])
    assert listed
    assert set(listed) <= set(SIDE_KIND_KEYS) - {KIND_FILE, "kind"}

    refused = cli("plan", "--side", "a=file:x*.json", "--side", "b=file:y*.json")
    assert refused.code == EXIT_USAGE
    (file_row,) = [line for line in text.splitlines() if line.startswith(f"| `{KIND_FILE}` |")]
    assert "`compare` only" in file_row
