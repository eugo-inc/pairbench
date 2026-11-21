# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Case ids whose cut drops words, through a whole run.

The made-up driver reads one case per line of a file the made-up side writes,
so a test chooses the ids each launch gives. Two ids that differ in a word a
path runs over are shown alike once the path is cut; the run gives each the
shown name plus a mark made with the run's own random key, the same in every
launch and on every side, and writes the key before the first name that
carries a mark. Ids of one launch that differ only in a folder or only in a
hidden secret are refused. Every folder, word and key here is made up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import LaunchRequest, case_tell_sha256
from pairbench.capture.reader import JsonlReader
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import (
    CASE_KEY_BYTES,
    FILE_CAPTURE,
    Capture,
    Experiment,
    GateSettings,
    LaunchCostSettings,
    RunSettings,
    Side,
    case_suffix,
)
from pairbench.runner import _one_case, record_profiles, run_experiment

World = Any

SIDES = (
    Side(name="new", kind="fake", spec={"argv": ["./new"]}),
    Side(name="old", kind="fake", spec={"argv": ["./old"]}),
)
# Two ids whose path runs on over a word that tells them apart; the folder holds the side's
# name, so the ids of the two sides differ in their folders too.
FAST = "run /made/up/{side}/a.py Zqfast data/x"
SLOW = "run /made/up/{side}/a.py Zqslow data/x"
MEDIUM = "run /made/up/{side}/a.py Zqmedium data/x"
SHOWN = "run x"
# A made-up key, and the names it gives the three ids.
KEY = bytes(range(32))
KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
FAST_NAME = "run x +9337c10f"
SLOW_NAME = "run x +69c21f80"
MEDIUM_NAME = "run x +d4f87154"
# The words that only the ids as read hold.
HIDDEN_WORDS = ("Zqfast", "Zqslow", "Zqmedium", "made/up")
FAST_VALUE = 1.0
SLOW_VALUE = 2.0
RUN_ON_ADVICE = (
    "give them names that differ outside their paths, absolute or climbing with '..', and "
    "outside their secrets; a path runs on over the words after it that start with a letter, a "
    "digit or '_', up to the last that holds a '/', and a quote ends it"
)
SHOWN_ALIKE = (
    "two different cases have the name {shown!r} once absolute paths and paths that climb "
    "with '..' are cut and secrets hidden, as the results show it"
)


@pytest.fixture
def drawn(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Give every run the made-up key, and keep how many bytes each run asked for."""
    asked: list[int] = []

    def token_bytes(count: int) -> bytes:
        asked.append(count)
        return KEY

    monkeypatch.setattr("pairbench.runner.secrets.token_bytes", token_bytes)
    return asked


def _experiment() -> Experiment:
    return Experiment(
        sides=SIDES,
        driver="fakedriver",
        run=RunSettings(quick=True),
        gates=GateSettings(mode="off"),
        launch_cost=LaunchCostSettings(launches=0),
    )


def _run(world: World, tmp_path: Path, folder: str = "run") -> Capture:
    return run_experiment(_experiment(), out=tmp_path / folder, services=world.services())


def _refused(world: World, tmp_path: Path) -> Refusal:
    with pytest.raises(Refusal) as caught:
        _run(world, tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert not any(word in caught.value.message for word in HIDDEN_WORDS)
    return caught.value


def _read(tmp_path: Path, folder: str = "run") -> Capture:
    (capture,) = JsonlReader().read(tmp_path / folder / FILE_CAPTURE)
    return capture


def _values(capture: Capture, case: str) -> set[float]:
    return {o.value for o in capture.observations if o.case == case}


def _side(request: LaunchRequest) -> str:
    return request.name.split("~")[0]


def _both(request: LaunchRequest) -> dict[str, float]:
    side = _side(request)
    ids = {FAST.format(side=side): FAST_VALUE, SLOW.format(side=side): SLOW_VALUE}
    if side == "old":
        # The other side prints its cases in the other order.
        return dict(reversed(list(ids.items())))
    return ids


def test_two_ids_cut_alike_get_two_marks_and_pair_on_every_side(
    world: World, tmp_path: Path, drawn: list[int]
) -> None:
    world.behaviour.cases = _both

    _run(world, tmp_path)

    capture = _read(tmp_path)
    ids = [c.id for c in capture.cases]
    assert FAST_NAME in ids and SLOW_NAME in ids and SHOWN not in ids
    # Each name holds the values of one id only, on every side and in every launch.
    assert _values(capture, FAST_NAME) == {FAST_VALUE}
    assert _values(capture, SLOW_NAME) == {SLOW_VALUE}
    assert {o.name for o in capture.observations if o.case == FAST_NAME} >= {"new", "old"}
    assert capture.case_key == KEY_HEX
    assert drawn == [CASE_KEY_BYTES]
    recorded = {(n.name, n.side) for n in capture.case_names}
    assert {(FAST_NAME, "new"), (FAST_NAME, "old"), (SLOW_NAME, "new"), (SLOW_NAME, "old")} <= (
        recorded
    )
    assert {n.name for n in capture.case_names} == {FAST_NAME, SLOW_NAME}
    assert {n.tell_sha256 for n in capture.case_names if n.name == FAST_NAME} == {
        case_tell_sha256(FAST.format(side="new"))
    }


def test_each_run_draws_its_own_key_and_marks_with_it(world: World, tmp_path: Path) -> None:
    world.behaviour.cases = _both

    _run(world, tmp_path, "one")
    _run(world, tmp_path, "two")

    one, two = _read(tmp_path, "one"), _read(tmp_path, "two")
    assert one.case_key is not None and two.case_key is not None
    assert one.case_key != two.case_key
    tell = case_tell_sha256(FAST.format(side="new"))
    marks = []
    for capture in (one, two):
        assert capture.case_key is not None
        name = SHOWN + case_suffix(bytes.fromhex(capture.case_key), tell)
        assert _values(capture, name) == {FAST_VALUE}
        marks.append(name)
    assert marks[0] != marks[1]


def test_a_launch_that_lacks_one_of_the_ids_still_pairs_the_other(
    world: World, tmp_path: Path, drawn: list[int]
) -> None:
    def cases(request: LaunchRequest) -> dict[str, float]:
        ids = _both(request)
        if _side(request) == "old" and request.round >= 2:
            ids.pop(SLOW.format(side="old"))
        return ids

    world.behaviour.cases = cases

    _run(world, tmp_path)

    capture = _read(tmp_path)
    assert _values(capture, FAST_NAME) == {FAST_VALUE}
    assert _values(capture, SLOW_NAME) == {SLOW_VALUE}


def test_a_later_id_cut_alike_gets_its_own_mark_and_changes_no_name(
    world: World, tmp_path: Path, drawn: list[int]
) -> None:
    def cases(request: LaunchRequest) -> dict[str, float]:
        ids = _both(request)
        if request.round >= 2:
            ids[MEDIUM.format(side=_side(request))] = 3.0
        return ids

    world.behaviour.cases = cases

    _run(world, tmp_path)

    capture = _read(tmp_path)
    assert _values(capture, FAST_NAME) == {FAST_VALUE}
    assert _values(capture, SLOW_NAME) == {SLOW_VALUE}
    assert _values(capture, MEDIUM_NAME) == {3.0}


def test_one_id_first_and_another_later_are_two_cases(
    world: World, tmp_path: Path, drawn: list[int]
) -> None:
    def cases(request: LaunchRequest) -> dict[str, float]:
        side = _side(request)
        if request.round <= 1:
            return {FAST.format(side=side): FAST_VALUE}
        return {SLOW.format(side=side): SLOW_VALUE}

    world.behaviour.cases = cases

    _run(world, tmp_path)

    capture = _read(tmp_path)
    assert _values(capture, FAST_NAME) == {FAST_VALUE}
    assert _values(capture, SLOW_NAME) == {SLOW_VALUE}
    assert _values(capture, SHOWN) == set()


def test_a_folder_that_moves_from_launch_to_launch_keeps_one_name_without_a_mark(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.cases = lambda request: {
        f"read /made/up/{request.round}/{_side(request)}/in.csv": FAST_VALUE
    }

    _run(world, tmp_path)

    capture = _read(tmp_path)
    assert "read in.csv" in [c.id for c in capture.cases]
    assert _values(capture, "read in.csv") == {FAST_VALUE}
    assert {n.name for n in capture.case_names} == {"read in.csv"}
    # No name carries a mark, so the run wrote no key.
    assert capture.case_key is None
    text = (tmp_path / "run" / FILE_CAPTURE).read_text(encoding="utf-8")
    assert '"t":"case_key"' not in text.replace(" ", "")


def test_ids_of_one_launch_that_differ_only_in_their_folders_are_refused(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.cases = lambda request: {
        "read /made/up/Zqa/in.csv": FAST_VALUE,
        "read /made/up/Zqb/in.csv": SLOW_VALUE,
    }

    refused = _refused(world, tmp_path)

    side = refused.message.split(":", 1)[0]
    assert refused.message == (
        f"{side}: {SHOWN_ALIKE.format(shown='read in.csv')}, and differ only in words that hold "
        "a '/' once their secrets are hidden; pairbench reads such words as folders, which may "
        f"differ between sides and launches; {RUN_ON_ADVICE}"
    )
    assert "Zqa" not in refused.message and "Zqb" not in refused.message


def test_ids_of_one_launch_that_differ_only_in_a_hidden_secret_are_refused(
    world: World, tmp_path: Path
) -> None:
    world.behaviour.cases = lambda request: {
        "test_db[PGPASSWORD=zq-made-up-kiwi7]": FAST_VALUE,
        "test_db[PGPASSWORD=zq-made-up-pear3]": SLOW_VALUE,
    }

    refused = _refused(world, tmp_path)

    side = refused.message.split(":", 1)[0]
    shown = "test_db[PGPASSWORD=<hidden>]"
    assert refused.message == (
        f"{side}: {SHOWN_ALIKE.format(shown=shown)}, and differ only in a hidden secret; "
        f"{RUN_ON_ADVICE}"
    )
    assert "kiwi7" not in refused.message and "pear3" not in refused.message


def test_an_id_that_ends_like_a_mark_is_refused(world: World, tmp_path: Path) -> None:
    world.behaviour.cases = lambda request: {"run x +1a2b3c4d": FAST_VALUE}

    refused = _refused(world, tmp_path)

    side = refused.message.split(":", 1)[0]
    assert refused.message == (
        f"{side}: the case read as 'run x +1a2b3c4d' ends like the mark pairbench adds to a name "
        "whose cut dropped words, ' +' and eight hex digits; give it a name that does not end so"
    )


def test_the_capture_keeps_the_key_once_before_the_names_and_no_word_they_hide(
    world: World, tmp_path: Path, drawn: list[int]
) -> None:
    world.behaviour.cases = _both

    _run(world, tmp_path)

    text = (tmp_path / "run" / FILE_CAPTURE).read_text(encoding="utf-8")
    assert not any(word in text for word in HIDDEN_WORDS)
    records = [json.loads(line) for line in text.splitlines()]
    kinds = [r["t"] for r in records]
    assert kinds.count("case_key") == 1
    assert [r["key"] for r in records if r["t"] == "case_key"] == [KEY_HEX]
    # The key comes right before the first names, and both before the first launch.
    assert kinds.index("case_key") + 1 == kinds.index("case_names") < kinds.index("launch")
    names = [n for r in records if r["t"] == "case_names" for n in r["names"]]
    assert {n["name"] for n in names} == {FAST_NAME, SLOW_NAME}
    assert all(
        len(n[field]) == 64
        for n in names
        for field in ("tell_sha256", "hidden_sha256", "read_sha256")
    )


def test_a_profile_case_names_the_one_case_its_name_without_the_mark_gives() -> None:
    ids = [FAST_NAME, SLOW_NAME, "read in.csv", "BM_Read y +5a549880/cpu_time"]
    assert _one_case(FAST_NAME, ids) == FAST_NAME
    assert _one_case("read in.csv", ids) == "read in.csv"
    assert _one_case("BM_Read y/cpu_time", ids) == "BM_Read y +5a549880/cpu_time"
    # A mark from other results names the case whose name without the mark it gives.
    assert _one_case("BM_Read y/cpu_time", ids[3:]) == ids[3]


@pytest.mark.parametrize(
    ("case", "message"),
    [
        pytest.param(
            SHOWN,
            f"the case {SHOWN!r} names 2 cases of the run: {SLOW_NAME!r}, {FAST_NAME!r}; give "
            "one of them",
            id="two",
        ),
        pytest.param("run y", "the run has no case 'run y'", id="none"),
        pytest.param("run x +0a0a0a0a", "the run has no case 'run x +0a0a0a0a'", id="other-mark"),
    ],
)
def test_a_profile_case_that_names_no_case_or_two_is_refused(
    world: World, tmp_path: Path, drawn: list[int], case: str, message: str
) -> None:
    world.behaviour.cases = _both
    _run(world, tmp_path)

    with pytest.raises(Refusal) as caught:
        record_profiles(tmp_path / "run", tool="nsys", case=case, services=world.services())

    assert (caught.value.code, caught.value.exit_code, caught.value.message) == (
        "E_USAGE",
        EXIT_USAGE,
        message,
    )
