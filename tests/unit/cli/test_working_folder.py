# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""One program run in two working folders is two sides.

A side that runs on the host runs in its working folder: ``launch.workdir``
read against the folder pairbench runs from, with links followed, or that
folder itself when none is set. Two sides with one fingerprint in two such
folders are compared, with one note that names both sides and never a folder;
captures whose sides ran in two folders are not pooled. The folder is compared
as a yes or no: no path, and no value made from one, reaches a shared file.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

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
HIDDEN_NOTE_CODE = "sides_differ_in_hidden_value"
IDENTICAL_NOTE_CODE = "sides_declared_identical"
FOLDER_NOTE = (
    "sides 'a' and 'b' have the same fingerprint and run in two working folders; they are "
    "compared as two sides, and the results do not show the folders"
)
IDENTICAL_NOTE = (
    "sides 'a' and 'b' have the same fingerprint, run in the same working folder and differ in "
    "nothing else; they are compared because identical sides were allowed"
)
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
# Folder names no shared file may hold.
FOLDER_ONE = "made-up-checkout-one"
FOLDER_TWO = "made-up-checkout-two"
TOOL = "#!/bin/sh\nexit 0\n"


@pytest.fixture
def place(tmp_path: Path) -> Path:
    """A folder with two checkouts, each holding a byte-identical ``tool`` and ``other``."""
    root = tmp_path / "place"
    for name in (FOLDER_ONE, FOLDER_TWO):
        for program in ("tool", "other"):
            path = root / name / program
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TOOL, encoding="utf-8")
            path.chmod(0o755)
    return root


def _tool(root: Path, folder: str) -> Path:
    return root / folder / "tool"


def _config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _two_folders(root: Path, first: str = FOLDER_ONE, second: str = FOLDER_TWO) -> Path:
    return _config(
        root / "two.toml",
        f"""
[sides.a]
cmd = ["./tool"]
launch.workdir = "{first}"
[sides.b]
cmd = ["./tool"]
baseline = true
launch.workdir = "{second}"
""",
    )


def _shared(*texts: str) -> str:
    return "\n".join(texts)


def _no_folder(text: str, root: Path) -> None:
    for word in (FOLDER_ONE, FOLDER_TWO, str(root)):
        assert word not in text


def _published(folder: Path) -> list[str]:
    texts = []
    for name in ("results.json", "results.md", "report.html"):
        path = folder / name
        if path.exists():
            texts.append(path.read_text(encoding="utf-8"))
    return texts


def test_plan_takes_one_program_in_two_working_folders_as_two_sides(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    result = cli("plan", "--config", _two_folders(place))

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert result.err.count(f"pairbench: note: {HIDDEN_NOTE_CODE}: {FOLDER_NOTE}\n") == 1
    assert "# sides differ in: a: launch.workdir; b: launch.workdir\n" in result.out
    _no_folder(_shared(result.out, result.err), place)


def test_plan_refuses_a_folder_and_a_link_to_it_as_one_side(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (place / "made-up-link").symlink_to(place / FOLDER_ONE, target_is_directory=True)
    monkeypatch.chdir(place)
    result = cli("plan", "--config", _two_folders(place, FOLDER_ONE, "made-up-link"))

    assert result.code == EXIT_SIDE
    assert result.err.endswith(SAME_FINGERPRINT)
    assert result.out == ""


def test_plan_refuses_one_folder_typed_relative_and_absolute_as_one_side(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    result = cli("plan", "--config", _two_folders(place, FOLDER_ONE, str(place / FOLDER_ONE)))

    assert result.code == EXIT_SIDE
    assert result.err.endswith(SAME_FINGERPRINT)


def test_plan_takes_two_programs_typed_by_full_path_as_two_sides(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    config = _config(
        place / "full.toml",
        f"""
[sides.a]
cmd = ["{_tool(place, FOLDER_ONE)}"]
[sides.b]
cmd = ["{_tool(place, FOLDER_TWO)}"]
baseline = true
""",
    )
    result = cli("plan", "--config", config)

    assert result.code == EXIT_OK, result.err
    assert "# sides differ in: a: argv\n" in result.out
    assert HIDDEN_NOTE_CODE not in result.err


def test_plan_refuses_a_working_folder_that_does_not_exist(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    result = cli("plan", "--config", _two_folders(place, "made-up-missing", FOLDER_TWO))

    assert result.code == EXIT_SIDE
    assert result.err.endswith(
        refusal_text(
            "E_SIDE_UNRESOLVED: side 'a': the working directory 'made-up-missing' does not exist"
        )
    )


def test_plan_refuses_a_side_when_the_folder_pairbench_runs_from_is_gone(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(
        place / "gone.toml",
        f"""
[sides.a]
cmd = ["{_tool(place, FOLDER_ONE)}"]
[sides.b]
cmd = ["{_tool(place, FOLDER_TWO)}"]
baseline = true
""",
    )
    gone = place / "made-up-gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()
    result = cli("plan", "--config", config)

    assert result.code == EXIT_SIDE
    assert result.err.endswith(
        refusal_text(
            "E_SIDE_UNRESOLVED: side 'a': the folder pairbench runs from, its working "
            "directory, cannot be found"
        )
    )


def test_run_compares_one_program_in_two_working_folders_with_one_note(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    out = place / "run"
    result = cli("run", "--config", _two_folders(place), *QUICK, "--out", out)

    assert result.code == EXIT_OK, result.err
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    notes = [n for n in results["notes"] if n["code"] == HIDDEN_NOTE_CODE]
    assert notes == [{"code": HIDDEN_NOTE_CODE, "message": FOLDER_NOTE}]
    assert IDENTICAL_NOTE_CODE not in json.dumps(results)
    _no_folder(_shared(result.out, result.err, *_published(out)), place)


def test_run_with_allow_identical_records_that_the_sides_were_declared_identical(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    out = place / "run"
    config = _two_folders(place, FOLDER_ONE, FOLDER_ONE)
    result = cli("run", "--config", config, *QUICK, "--allow-identical", "--out", out)

    assert result.code == EXIT_OK, result.err
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    notes = [n for n in results["notes"] if n["code"] == IDENTICAL_NOTE_CODE]
    assert notes == [{"code": IDENTICAL_NOTE_CODE, "message": IDENTICAL_NOTE}]
    assert HIDDEN_NOTE_CODE not in json.dumps(results)
    markdown = " ".join((out / "results.md").read_text(encoding="utf-8").split())
    assert markdown.count("sides\\_declared\\_identical") == 1


def test_run_with_allow_identical_gives_no_identical_note_for_two_folders(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    out = place / "run"
    result = cli("run", "--config", _two_folders(place), *QUICK, "--allow-identical", "--out", out)

    assert result.code == EXIT_OK, result.err
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert [n["code"] for n in results["notes"] if n["code"] == IDENTICAL_NOTE_CODE] == []


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _refusal_line(err: str) -> str:
    (line,) = [line for line in err.splitlines() if line.startswith("E_")]
    return line


def _shared_folder(root: Path, folder: str) -> Path:
    # The file is named for its place in the test, never for the folder it names.
    return _config(
        root / f"shared-{(FOLDER_ONE, FOLDER_TWO).index(folder)}.toml",
        f"""
[sides.a]
cmd = ["./tool"]
[sides.b]
cmd = ["./other"]
baseline = true
[launch]
workdir = "{folder}"
""",
    )


def _run_twice(cli: Cli, root: Path, first: Path, second: Path) -> Any:
    for name, config in (("one", first), ("two", second)):
        done = cli("run", "--config", config, *QUICK, "--out", root / name)
        assert done.code == EXIT_OK, done.err
    return cli(
        "compare",
        root / "one" / "capture.jsonl",
        root / "two" / "capture.jsonl",
        "--out",
        root / "pooled",
    )


def _drift(root: Path) -> str:
    return (
        f"E_POOL_SIDE_DRIFT: the working folder of a, b differs between the captures "
        f"{_capture_id(root / 'one')} and {_capture_id(root / 'two')}"
    )


def test_compare_refuses_captures_made_in_two_shared_working_folders(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    result = _run_twice(
        cli, place, _shared_folder(place, FOLDER_ONE), _shared_folder(place, FOLDER_TWO)
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == _drift(place)
    _no_folder(_shared(result.out, result.err, *_published(place / "pooled")), place)


def test_compare_refuses_captures_run_from_two_folders_with_no_working_folder_set(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(
        place / "plain.toml",
        """
[sides.a]
cmd = ["./tool"]
[sides.b]
cmd = ["./other"]
baseline = true
""",
    )
    for name, folder in (("one", FOLDER_ONE), ("two", FOLDER_TWO)):
        monkeypatch.chdir(place / folder)
        done = cli("run", "--config", config, *QUICK, "--out", place / name)
        assert done.code == EXIT_OK, done.err
    result = cli(
        "compare",
        place / "one" / "capture.jsonl",
        place / "two" / "capture.jsonl",
        "--out",
        place / "pooled",
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == _drift(place)
    _no_folder(_shared(result.out, result.err, *_published(place / "pooled")), place)


def test_compare_pools_captures_made_in_one_working_folder(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    config = _shared_folder(place, FOLDER_ONE)
    result = _run_twice(cli, place, config, config)

    assert result.code == EXIT_OK, result.err
    assert "E_POOL_SIDE_DRIFT" not in result.err


def _without_folder_record(capture: Path) -> None:
    """Rewrite a capture as one made before sides recorded their working folder."""
    rows = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
    text = ""
    for row in rows:
        if row.get("t") == "side":
            assert len(str(row.pop("workdir_sha256"))) == 64
        if row.get("t") == "end":
            # The end record seals the bytes before it.
            row["sha256_of_preceding"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        text += json.dumps(row) + "\n"
    capture.write_text(text, encoding="utf-8")


def test_compare_refuses_a_capture_without_a_folder_record_beside_one_with_it(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    config = _shared_folder(place, FOLDER_ONE)
    for name in ("one", "two"):
        done = cli("run", "--config", config, *QUICK, "--out", place / name)
        assert done.code == EXIT_OK, done.err
    _without_folder_record(place / "two" / "capture.jsonl")
    result = cli(
        "compare",
        place / "one" / "capture.jsonl",
        place / "two" / "capture.jsonl",
        "--out",
        place / "pooled",
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        f"E_POOL_SIDE_DRIFT: the working folder of a, b could not be compared between the "
        f"captures {_capture_id(place / 'one')} and {_capture_id(place / 'two')}: "
        f"{_capture_id(place / 'two')} does not record it; run it again to pool it"
    )


def test_compare_pools_two_captures_without_a_folder_record(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    config = _shared_folder(place, FOLDER_ONE)
    for name in ("one", "two"):
        done = cli("run", "--config", config, *QUICK, "--out", place / name)
        assert done.code == EXIT_OK, done.err
        _without_folder_record(place / name / "capture.jsonl")
    result = cli(
        "compare",
        place / "one" / "capture.jsonl",
        place / "two" / "capture.jsonl",
        "--out",
        place / "pooled",
    )

    assert result.code == EXIT_OK, result.err


def test_a_capture_records_a_hash_of_the_resolved_folder_and_no_path(
    cli: Cli, place: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(place)
    out = place / "run"
    result = cli("run", "--config", _shared_folder(place, FOLDER_ONE), *QUICK, "--out", out)

    assert result.code == EXIT_OK, result.err
    rows = [json.loads(line) for line in (out / "capture.jsonl").read_text().splitlines()]
    sides = {row["name"]: row for row in rows if row.get("t") == "side"}
    resolved = os.fsencode(os.path.realpath(place / FOLDER_ONE))
    expected = hashlib.sha256(resolved).hexdigest()
    assert {name: row["workdir_sha256"] for name, row in sides.items()} == {
        "a": expected,
        "b": expected,
    }
