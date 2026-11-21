# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A side's fingerprint holds its program by the last part of its path.

The identity of a command side keeps the absolute path of its executable, which
names the folder it was run from, a home folder among them. Its fingerprint, and
the inputs of it that ``tools/hash_inputs.py`` writes, hold that path the way
the look-up line shows it: cut to its last part. So a fingerprint names no
folder of the machine. Two programs typed as two paths are still two sides, by
the arguments typed. Two sides that differ only by the folder they run in, with
the same program and the same arguments, have one fingerprint and are two sides
by their working folder, which no shared file shows.
"""

from __future__ import annotations

import json
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pairbench import model
from pairbench.errors import EXIT_OK, EXIT_SIDE
from pairbench.model import LaunchSettings, fingerprint_of

from .conftest import COMMAND_NOTE, refusal_text

Cli = Callable[..., Any]

QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
)
# The same made-up program in two made-up home folders.
HOMES = ("/home/madeupuser-a/bin/made-up-tool", "/home/madeupuser-b/bin/made-up-tool")
PROGRAM = "#!/bin/sh\nexit 0\n"
SAME = (
    "E_SAME_SIDE: sides 'old' and 'new' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
HIDDEN_NOTE_CODE = "sides_differ_in_hidden_value"
FOLDER_NOTE = (
    "sides 'old' and 'new' have the same fingerprint and run in two working folders; they are "
    "compared as two sides, and the results do not show the folders"
)


def _identity(executable: str) -> dict[str, Any]:
    return {"executable": executable, "executable_sha256": "e" * 64}


def test_the_fingerprint_holds_the_last_part_of_the_executable_path() -> None:
    launch = LaunchSettings().effective(args=["made-up-tool"])

    inputs = model.fingerprint_inputs(_identity(HOMES[0]), launch)

    assert inputs["identity"] == {"executable": "made-up-tool", "executable_sha256": "e" * 64}
    assert fingerprint_of(_identity(HOMES[0]), launch) == fingerprint_of(
        _identity(HOMES[1]), launch
    )
    assert "madeupuser" not in json.dumps(inputs)


def _programs(base: Path, *folders: str) -> None:
    for name in folders:
        tool = base / name / "tool"
        tool.parent.mkdir(parents=True)
        tool.write_text(PROGRAM, encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)


def _fingerprints(folder: Path) -> dict[str, str]:
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return {side["name"]: side["fingerprint"] for side in results["sides"]}


def test_two_programs_typed_as_two_paths_are_two_sides(
    cli: Cli, tmp_path: Path, monkeypatch: Any
) -> None:
    _programs(tmp_path, "build-old", "build-new")
    monkeypatch.chdir(tmp_path)

    result = cli(
        "run",
        "--side",
        "old=cmd:./build-old/tool",
        "--side",
        "new=cmd:./build-new/tool",
        *QUICK,
        "--out",
        tmp_path / "run",
    )

    assert result.code == EXIT_OK, result.err
    shown = _fingerprints(tmp_path / "run")
    assert shown["old"] != shown["new"]


def _by_folder(cli: Cli, tmp_path: Path, *more: str) -> Any:
    _programs(tmp_path, "build-old", "build-new")
    return cli(
        "run",
        "--side",
        "old=cmd:./tool",
        "--side",
        "new=cmd:./tool",
        *QUICK,
        "--set",
        f"sides.old.launch.workdir={tmp_path / 'build-old'}",
        "--set",
        f"sides.new.launch.workdir={tmp_path / 'build-new'}",
        *more,
        "--out",
        tmp_path / "run",
    )


def test_two_sides_told_apart_only_by_their_folder_are_two_sides(cli: Cli, tmp_path: Path) -> None:
    result = _by_folder(cli, tmp_path)

    assert result.code == EXIT_OK, result.err
    assert result.err.startswith(f"pairbench: note: {HIDDEN_NOTE_CODE}: {FOLDER_NOTE}\n")
    assert result.err.endswith(COMMAND_NOTE)
    shown = _fingerprints(tmp_path / "run")
    assert shown["old"] == shown["new"]
    published = (tmp_path / "run" / "results.json").read_text(encoding="utf-8")
    assert "build-old" not in published
    assert "build-new" not in published


def test_two_sides_in_one_folder_typed_twice_are_one_side(
    cli: Cli, tmp_path: Path, monkeypatch: Any
) -> None:
    _programs(tmp_path, "build-old")
    monkeypatch.chdir(tmp_path)
    result = cli(
        "run",
        "--side",
        "old=cmd:./tool",
        "--side",
        "new=cmd:./tool",
        *QUICK,
        "--set",
        f"sides.old.launch.workdir={tmp_path / 'build-old'}",
        "--set",
        "sides.new.launch.workdir=build-old",
        "--out",
        tmp_path / "run",
    )

    assert result.code == EXIT_SIDE
    assert result.out == ""
    assert result.err == refusal_text(SAME)
    assert not (tmp_path / "run" / "results.json").exists()


def test_two_sides_told_apart_only_by_their_folder_run_with_allow_identical(
    cli: Cli, tmp_path: Path
) -> None:
    result = _by_folder(cli, tmp_path, "--allow-identical")

    assert result.code == EXIT_OK, result.err
    assert result.err.endswith(COMMAND_NOTE)
    shown = _fingerprints(tmp_path / "run")
    assert shown["old"] == shown["new"]
