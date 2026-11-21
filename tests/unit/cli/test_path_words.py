# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A folder named in words stays out of what plan and run print and write.

The workload names a file in a folder whose name holds three words, as a word
of the command, as the value of an option and of a name, and quoted in the text
after ``sh -c``; the program of one side is in a folder whose name holds words
and brackets. No word of either folder is in what ``plan`` prints, what ``run``
prints or any file ``run`` writes but the raw capture, and the shown command
holds the last part of each path. Every folder name here is made up.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

# The words of the two made-up folders; none of them may be shown.
FOLDER_WORDS = ("Zqclient", "Zqcorp", "Zqfiles", "Zqtools", "Zqbench")
DATA_FOLDER = "Zqclient Zqcorp Zqfiles"
TOOL_FOLDER = "Zqtools Zqbench (x86)"
FILE = "data.txt"
# The shell text: ``:`` runs nothing, so only the shell runs.
SCRIPT = ": tool '{p}' --in=\"{p}\" 'DATA={p}'"
QUICK = ("--gates", "off", "--rounds", "6", "--same-vs-same", "off", "--positive-control", "off")
# The raw record of the run, which keeps the command as typed and is never shared.
CAPTURE = "capture.jsonl"


def _workload(path: str) -> list[str]:
    return ["sh", "-c", SCRIPT.format(p=path), "sh", path, f"--in={path}", f"DATA={path}"]


SHOWN_WORKLOAD = "-- " + shlex.join(_workload(FILE))


def _program(root: Path) -> Path:
    folder = root / TOOL_FOLDER
    folder.mkdir()
    program = folder / "made-up-tool"
    program.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    return program


def _sides(program: Path) -> tuple[str, ...]:
    return (
        "--side",
        f"new=cmd:{shlex.quote(str(program))} {{workload}}",
        "--side",
        "old=cmd:env {workload}",
        "--baseline",
        "old",
    )


def _shows_no_folder_word(text: str) -> bool:
    return not any(word in text for word in FOLDER_WORDS)


def test_plan_shows_no_word_of_a_folder_named_in_words(cli: Cli, tmp_path: Path) -> None:
    program = _program(tmp_path)
    data = str(tmp_path / DATA_FOLDER / FILE)

    result = cli("plan", *_sides(program), *QUICK, "--", *_workload(data))

    assert result.code == EXIT_OK, result.err
    assert _shows_no_folder_word(result.out), result.out
    assert _shows_no_folder_word(result.err), result.err
    assert "executable=made-up-tool" in result.out


def test_a_run_shows_no_word_of_a_folder_named_in_words(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _program(tmp_path)
    data = str(tmp_path / DATA_FOLDER / FILE)
    monkeypatch.chdir(tmp_path)

    result = cli(
        "run",
        *_sides(program),
        *QUICK,
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        *_workload(data),
    )

    assert result.code == EXIT_OK, result.err
    assert _shows_no_folder_word(result.out), result.out
    assert _shows_no_folder_word(result.err), result.err
    shared = sorted(
        path for path in (tmp_path / "run").rglob("*") if path.is_file() and path.name != CAPTURE
    )
    assert {"results.json", "results.md", "report.html"} <= {path.name for path in shared}
    for path in shared:
        assert _shows_no_folder_word(path.read_text(encoding="utf-8")), path.name
    results: dict[str, Any] = json.loads((tmp_path / "run" / "results.json").read_text("utf-8"))
    assert results["run"]["command"].endswith(SHOWN_WORKLOAD)


# A folder named by a client and two ordinary words, and the files a run writes to be shared.
CLIENT_FOLDER = "Zqclient Corp Files"
SHARED = ("results.json", "results.md", "report.html")


def test_a_run_shares_no_word_of_a_client_folder(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = _program(tmp_path)
    data = str(tmp_path / CLIENT_FOLDER / FILE)
    monkeypatch.chdir(tmp_path)

    result = cli(
        "run",
        *_sides(program),
        *QUICK,
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        *_workload(data),
    )

    assert result.code == EXIT_OK, result.err
    for name in SHARED:
        text = (tmp_path / "run" / name).read_text(encoding="utf-8")
        assert "Zqclient" not in text, name
        assert "Corp Files" not in text, name
