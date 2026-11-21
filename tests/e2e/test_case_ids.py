# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Case ids that read alike once their paths are cut, through the installed command.

Each side prints its cases as ``read FOLDER/in.bin Zq<case> x/y`` (``seeded_side.py
--folder``): the path runs on over the word ``Zq<case>`` up to ``x/y``, so every id of a
launch is cut to ``read y``. The run names each case ``read y`` plus a mark, `` +`` and the
first eight hex digits of the HMAC-SHA256, under the key the capture keeps, of the SHA-256 of
the id's words that hold no ``/``. Each row makes that mark again from the capture's key
record, and finds one name per case in a launch, on two sides that name other folders and in a
pool of two captures, and none of the words the paths run over, the key or a hash of an id in
the files a run shares. Every folder and word here is made up.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from .conftest import Done, Installed, capture_records, primary, read_json

pytestmark = [pytest.mark.delivery, pytest.mark.slow]

CASES = ("alpha", "beta", "gamma")
# The words the paths run over, one per case, and the made-up folders the sides name.
RUN_OVER = tuple(f"Zq{case}" for case in CASES)
FOLDERS = ("/made/up/a", "/made/up/b")
# What each id reads as once its path is cut, and the shape of the name with its mark.
SHOWN = "read y"
MARKED = re.compile(r"read y \+[0-9a-f]{8}")
# Words no shared file may hold: the run-over words, and the folders the paths name.
HIDDEN = (*RUN_OVER, "made/up", "in.bin")
COMMON = (
    "--driver",
    "lines",
    "--vary-env-size",
    "--gates",
    "off",
    "--rounds",
    "8",
    "--explain",
    "off",
    "--plots",
    "off",
    "--positive-control",
    "off",
)
# Cases named by two addresses and a path in a query under each side's folder, with the case
# between them (``seeded_side.py --form addresses``): the name each case shows on both sides,
# with no mark, and words of the folders that no shared file may hold.
ADDRESSES = "get unix:///s.sock?db=0 {case} https://h.example/p?next=/d unix:///t.sock"
ADDRESS_HIDDEN = ("Zqhome", "Zq dir", "made/up")
# Cases named by a credential written as a path (``seeded_side.py --form credential``), on one
# side through one more folder whose name holds a blank: the name each case shows on both
# sides, with no mark, and words of the folders that no shared file may hold.
CREDENTIAL = "test_db[token:<hidden>] {case}"
CREDENTIAL_HIDDEN = ("Zq dir", "made/up", "x.pem")
# Cases named by a path under each side's folder that starts with three ``/`` after a bracket
# (``seeded_side.py --form bracket``): the name each case shows on both sides, with no mark, and
# words of the folders that no shared file may hold.
BRACKET = "test_read[in.bin] {case}"
BRACKET_HIDDEN = ("Zqhome", "made/up")
# Cases named by a local address under each side's folder in the query of an address with no
# host (``seeded_side.py --form nested``): the name each case shows on both sides, with no mark,
# and words of the folders that no shared file may hold.
NESTED = "test_conn[postgresql:///db?sslrootcert=file://ca.pem] {case}"
NESTED_HIDDEN = ("Zqhome", "made/up")
# Cases named by a path that climbs out of its folder in the query of an address with no host
# (``seeded_side.py --form climb``): the name each case shows on both sides, with no mark, and
# words of the folders that no shared file may hold.
CLIMB = "x postgresql:///db?sslrootcert=ca.pem {case}"
CLIMB_HIDDEN = ("Zqhome", "made/up")
# The files a run shares, and the ones a compare of captures writes.
RUN_SHARED = ("results.json", "results.md", "report.html", "plan.tsv")
COMPARE_SHARED = ("results.json", "results.md")
# The sides and twins of each run.
SIDES = ("new", "old", "new~same", "old~same")
# The new side reads exactly twice the old side in every round.
RATIO = 2.0
OUTCOME = "worse"


@dataclass(frozen=True)
class Run:
    """One run of the installed command and the folder it wrote."""

    done: Done
    folder: Path

    @property
    def results(self) -> Any:
        return read_json(self.folder / "results.json")


def _sides(installed: Installed, new_folder: str, old_folder: str, *extra: str) -> list[str]:
    new = installed.seeded(RATIO, "--name", "new", "--folder", new_folder, *extra)
    old = installed.seeded(1.0, "--name", "old", "--folder", old_folder, *extra)
    return ["--side", f"new=cmd:{new}", "--side", f"old=cmd:{old}", "--baseline", "old"]


def _run(installed: Installed, folder: Path, sides: list[str]) -> Run:
    done = installed.run("run", *sides, *COMMON, "--out", folder, cwd=folder.parent)
    return Run(done=done, folder=folder)


def _key(folder: Path) -> bytes:
    """The key the capture of a run folder keeps, from its one ``case_key`` record."""
    (record,) = capture_records(folder, "case_key")
    assert sorted(record) == ["key", "t"]
    return bytes.fromhex(record["key"])


def _mark(key: bytes, case: str) -> str:
    """The name a run with ``key`` gives the case: the cut id plus its mark, made here."""
    tell = json.dumps(["words", "read", f"Zq{case}"], separators=(",", ":"))
    tell_sha256 = hashlib.sha256(tell.encode("utf-8")).hexdigest()
    digest = hmac.new(key, tell_sha256.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{SHOWN} +{digest[:8]}"


def _names(key: bytes) -> dict[str, str]:
    return {case: _mark(key, case) for case in CASES}


def _paired(results: Any, names: dict[str, str]) -> None:
    """Each case is one primary row of the new side under its name, read exactly twice."""
    found = primary(results)
    assert sorted(found) == sorted((name, "new") for name in names.values())
    for name in names.values():
        assert MARKED.fullmatch(name)
        assert found[(name, "new")]["ratio"] == RATIO
        assert found[(name, "new")]["outcome"] == OUTCOME
    # The cases the workload prints; the run's own resource cases start with ``res/``.
    printed = {c["case"] for c in results["comparisons"] if not c["case"].startswith("res/")}
    assert sorted(printed) == sorted(names.values())


@pytest.fixture(scope="module")
def one_folder(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Both sides name one folder: each launch gives the three ids cut alike."""
    folder = tmp_path_factory.mktemp("case-ids-one") / "run"
    return _run(installed, folder, _sides(installed, FOLDERS[0], FOLDERS[0]))


@pytest.fixture(scope="module")
def two_folders(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder: the ids of a case differ between the sides."""
    folder = tmp_path_factory.mktemp("case-ids-two") / "run"
    return _run(installed, folder, _sides(installed, FOLDERS[0], FOLDERS[1]))


@pytest.fixture(scope="module")
def addresses(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder in the addresses of its cases."""
    folder = tmp_path_factory.mktemp("case-ids-addresses") / "run"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--form", "addresses")
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def slashes(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder in a path that starts with two ``/``."""
    folder = tmp_path_factory.mktemp("case-ids-slashes") / "run"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--form", "slashes")
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def bracket(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder in a path that starts with three ``/`` after a bracket."""
    folder = tmp_path_factory.mktemp("case-ids-bracket") / "run"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--form", "bracket")
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def nested(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder in a local address in the query of an address with no
    host."""
    folder = tmp_path_factory.mktemp("case-ids-nested") / "run"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--form", "nested")
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def climb(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """Each side names its own folder through a climbing path in the query of an address with no
    host."""
    folder = tmp_path_factory.mktemp("case-ids-climb") / "run"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--form", "climb")
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def credential(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> Run:
    """A credential path in each id: the new side's runs through a folder with a blank."""
    folder = tmp_path_factory.mktemp("case-ids-credential") / "run"
    new = installed.seeded(
        RATIO, "--name", "new", "--folder", FOLDERS[0], "--form", "credential-blank"
    )
    old = installed.seeded(1.0, "--name", "old", "--folder", FOLDERS[1], "--form", "credential")
    sides = ["--side", f"new=cmd:{new}", "--side", f"old=cmd:{old}", "--baseline", "old"]
    return _run(installed, folder, sides)


@pytest.fixture(scope="module")
def pooled(installed: Installed, tmp_path_factory: pytest.TempPathFactory) -> tuple[Run, Run, Run]:
    """Two runs of one command, each with its own key and seed, pooled with one compare."""
    base = tmp_path_factory.mktemp("case-ids-pool")
    seed = base / "seed.txt"
    sides = _sides(installed, FOLDERS[0], FOLDERS[1], "--seed-file", str(seed))
    runs = []
    for name, value in (("one", "7"), ("two", "11")):
        seed.write_text(value, encoding="utf-8")
        runs.append(_run(installed, base / name, sides))
    one, two = runs
    out = base / "pooled"
    done = installed.run(
        "compare",
        one.folder / "capture.jsonl",
        two.folder / "capture.jsonl",
        "--out",
        out,
        cwd=base,
    )
    return one, two, Run(done=done, folder=out)


def test_one_launch_gives_each_id_cut_alike_its_own_mark(one_folder: Run) -> None:
    assert one_folder.done.code == 0, one_folder.done.err
    names = _names(_key(one_folder.folder))

    assert len(set(names.values())) == len(CASES)
    _paired(one_folder.results, names)


def test_sides_that_name_other_folders_pair_each_case_under_one_name(two_folders: Run) -> None:
    assert two_folders.done.code == 0, two_folders.done.err
    names = _names(_key(two_folders.folder))

    _paired(two_folders.results, names)
    # The capture keeps each name for every side and twin that read the case under its folder.
    entries = [
        e for record in capture_records(two_folders.folder, "case_names") for e in record["names"]
    ]
    sides = {name: {e["side"] for e in entries if e["name"] == name} for name in names.values()}
    assert sides == {name: set(SIDES) for name in names.values()}


def test_a_pool_of_two_captures_shows_the_first_captures_names(
    pooled: tuple[Run, Run, Run],
) -> None:
    one, two, pool = pooled
    for run in (one, two):
        assert run.done.code == 0, run.done.err
    assert pool.done.code == 0, pool.done.err
    first, second = _names(_key(one.folder)), _names(_key(two.folder))
    _paired(one.results, first)
    _paired(two.results, second)

    assert pool.results["run"]["pooled"] is True
    _paired(pool.results, first)
    assert set(first.values()).isdisjoint(second.values())


def _private(run: Run) -> list[str]:
    """The key and every hash of an id that the capture keeps; none may be shared."""
    kept = [_key(run.folder).hex()]
    for record in capture_records(run.folder, "case_names"):
        for entry in record["names"]:
            kept += [entry["tell_sha256"], entry["hidden_sha256"], entry["read_sha256"]]
    return kept


def _leaks(run: Run, files: tuple[str, ...], private: list[str]) -> list[tuple[str, str]]:
    texts = {name: (run.folder / name).read_text(encoding="utf-8") for name in files}
    texts["stdout"], texts["stderr"] = run.done.out, run.done.err
    return [
        (where, word)
        for where, text in texts.items()
        for word in (*HIDDEN, *private)
        if word in text
    ]


def test_the_shared_files_hold_no_run_over_word_key_or_hash_of_an_id(
    one_folder: Run, two_folders: Run, pooled: tuple[Run, Run, Run]
) -> None:
    one, two, pool = pooled
    runs = (one_folder, two_folders, one, two)
    for run in (*runs, pool):
        assert run.done.code == 0, run.done.err
    # Each capture keeps the key and three hashes of every id it read, on each side and twin.
    assert [len(_private(run)) for run in runs] == [1 + 3 * len(SIDES) * len(CASES)] * len(runs)

    assert [_leaks(run, RUN_SHARED, _private(run)) for run in runs] == [[]] * len(runs)
    assert _leaks(pool, COMPARE_SHARED, _private(one) + _private(two)) == []


def _paired_unmarked(run: Run, form: str, hidden: tuple[str, ...]) -> None:
    """Each case is one row of the new side under ``form``, read exactly twice; none of
    ``hidden`` is in a shared file or a stream."""
    assert run.done.code == 0, run.done.err
    names = [form.format(case=case) for case in CASES]

    found = primary(run.results)
    assert sorted(found) == sorted((name, "new") for name in names)
    for name in names:
        assert found[(name, "new")]["ratio"] == RATIO
        assert found[(name, "new")]["outcome"] == OUTCOME
    texts = {name: (run.folder / name).read_text(encoding="utf-8") for name in RUN_SHARED}
    texts["stdout"], texts["stderr"] = run.done.out, run.done.err
    leaks = [(where, word) for where, text in texts.items() for word in hidden if word in text]
    assert leaks == []


def test_cases_named_by_addresses_under_other_folders_pair_without_a_mark(
    addresses: Run,
) -> None:
    _paired_unmarked(addresses, ADDRESSES, ADDRESS_HIDDEN)


def test_a_credential_path_through_a_folder_with_a_blank_pairs_without_a_mark(
    credential: Run,
) -> None:
    _paired_unmarked(credential, CREDENTIAL, CREDENTIAL_HIDDEN)


def test_a_path_that_starts_with_three_slashes_after_a_bracket_pairs_without_a_mark(
    bracket: Run,
) -> None:
    _paired_unmarked(bracket, BRACKET, BRACKET_HIDDEN)


def test_a_local_address_in_the_query_of_an_address_with_no_host_pairs_without_a_mark(
    nested: Run,
) -> None:
    _paired_unmarked(nested, NESTED, NESTED_HIDDEN)


def test_a_climbing_path_in_the_query_of_an_address_with_no_host_pairs_without_a_mark(
    climb: Run,
) -> None:
    _paired_unmarked(climb, CLIMB, CLIMB_HIDDEN)


def test_a_path_that_starts_with_two_slashes_is_cut_and_marked_as_one_with_one(
    slashes: Run,
) -> None:
    assert slashes.done.code == 0, slashes.done.err
    _paired(slashes.results, _names(_key(slashes.folder)))
    assert _leaks(slashes, RUN_SHARED, _private(slashes)) == []
