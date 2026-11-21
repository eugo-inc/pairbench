# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``file`` side kind: matching, order, identity and the file of each round."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pairbench import api
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.model import LaunchSettings, Side
from pairbench.sides.files import CANNOT_REPEAT, FileKind

# SHA-256 of the three bytes "abc" and of no bytes at all.
ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.fixture
def results(tmp_path: Path) -> Path:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    (tmp_path / "x" / "b.json").write_bytes(b"abc")
    (tmp_path / "y" / "a.json").write_bytes(b"")
    (tmp_path / "y" / "c.json").write_bytes(b"abc")
    (tmp_path / "x" / "notes.txt").write_text("not a result")
    return tmp_path


def _ctx(settings: LaunchSettings | None = None) -> api.SideContext:
    return api.SideContext(run_id="", settings=settings or LaunchSettings(), driver="gbench")


def _request(round_: int, tmp_path: Path) -> api.LaunchRequest:
    return api.LaunchRequest(
        run_id="run-a", seq=round_, phase="round", round=round_, pos=None, name="old",
        artifacts=tmp_path,
    )  # fmt: skip


def test_files_pair_by_sorted_file_name_and_round_r_gives_the_r_th(results: Path) -> None:
    side = Side.files("old", [str(results / "*" / "*.json")], format="gbench")
    resolved = FileKind().resolve(side, _ctx())
    assert resolved.rounds_available == 3
    assert resolved.launch(_request(1, results)).result_file == results / "y" / "a.json"
    assert resolved.launch(_request(2, results)).result_file == results / "x" / "b.json"
    third = resolved.launch(_request(3, results))
    assert (third.rc, third.result_file, third.timing) == (0, results / "y" / "c.json", {})


def test_the_identity_holds_one_hash_per_file_in_file_order(results: Path) -> None:
    side = Side.files("old", [str(results / "**" / "*.json")], format=None)
    resolved = FileKind().resolve(side, _ctx())
    assert resolved.side.public_identity() == {
        "files_sha256": [EMPTY_SHA256, ABC_SHA256, ABC_SHA256]
    }
    assert resolved.side.identity["files"] == (
        str(results / "y" / "a.json"),
        str(results / "x" / "b.json"),
        str(results / "y" / "c.json"),
    )


def test_the_look_up_matches_resolve(results: Path) -> None:
    side = Side.files("old", [str(results / "*" / "*.json")], format=None)
    found = FileKind().look_up(side, _ctx())
    resolved = FileKind().resolve(side, _ctx())
    assert found.status == "identified"
    assert found.identity == resolved.side.identity
    assert found.fingerprint == resolved.side.fingerprint


def test_a_file_two_paths_match_counts_once(results: Path) -> None:
    side = Side.files(
        "old", [str(results / "x" / "b.json"), str(results / "x" / "*.json")], format=None
    )
    assert FileKind().resolve(side, _ctx()).rounds_available == 1


def test_a_file_side_launches_nothing_and_has_no_control(results: Path) -> None:
    side = Side.files("old", [str(results / "x" / "b.json")], format=None)
    resolved = FileKind().resolve(side, _ctx())
    assert resolved.command is None
    assert resolved.engine is None
    assert resolved.cannot_repeat == CANNOT_REPEAT


def test_paths_that_match_no_file_are_refused(tmp_path: Path) -> None:
    side = Side.files("old", [str(tmp_path / "*.json")], format=None)
    for call in (FileKind().look_up, FileKind().resolve):
        with pytest.raises(Refusal) as caught:
            call(side, _ctx())
        assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
        assert str(tmp_path) not in caught.value.message


def test_a_result_file_that_cannot_be_read_is_a_side_refusal(results: Path) -> None:
    unreadable = results / "x" / "b.json"
    unreadable.chmod(0o200)
    if os.access(unreadable, os.R_OK):
        pytest.skip("this user reads a file without read permission (the superuser does)")
    side = Side.files("old", [str(results / "*" / "*.json")], format=None)
    for call in (FileKind().look_up, FileKind().resolve):
        with pytest.raises(Refusal) as caught:
            call(side, _ctx())
        assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)
        assert caught.value.message == (
            "side 'old': the result file 'b.json' cannot be read, so its hash cannot be recorded"
        )


def test_a_round_beyond_the_files_is_a_usage_error(results: Path) -> None:
    side = Side.files("old", [str(results / "x" / "b.json")], format=None)
    with pytest.raises(Refusal) as caught:
        FileKind().resolve(side, _ctx()).launch(_request(2, results))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


@pytest.mark.parametrize(
    "settings",
    [LaunchSettings(cpus="0"), LaunchSettings(env={"A": "1"}), LaunchSettings(identify=("v",))],
    ids=["cpus", "env", "identify"],
)
def test_a_launch_setting_is_refused_on_a_file_side(
    results: Path, settings: LaunchSettings
) -> None:
    side = Side.files("old", [str(results / "x" / "b.json")], format=None)
    with pytest.raises(Refusal) as caught:
        FileKind().look_up(side, _ctx(settings))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_the_engine_and_pull_settings_are_not_refused_on_a_file_side(results: Path) -> None:
    side = Side.files("old", [str(results / "x" / "b.json")], format=None)
    settings = LaunchSettings(engine="docker", pull="never")
    assert FileKind().resolve(side, _ctx(settings)).rounds_available == 1
