# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A relative path that climbs with ``..`` is cut to its last part, as an absolute path is.

Such a path may name a folder outside the run folder, a home folder and the
user's name among them, whether or not a folder of it is called ``home``. So
it shows its last part where it stands as an argument of its own, after
``--data=``, glued to an option (``-I``), inside a shell text, as a path and
in a case id, whether the climb comes first (``../../a/in.csv``), after
``./`` (``./../a/in.csv``) or after a folder (``data/../../a/in.csv``), and
whole when its folders hold blanks. A relative path that stays inside its
folder (``a/../b``, the ``s/../X/`` of ``sed``), and ``..`` parts alone
(``cd ../..``), are left as typed. The published hashes keep a path as typed, which
SECURITY.md lists among the known limits of the hashes.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import api, model
from pairbench.errors import Refusal

# A made-up user's folder name, which no row may show.
USER = "zq-made-up-user"
# Climbing paths, each as typed: the climb first, with no folder named ``home``, after ``./``,
# after a folder, and after ``./`` and a folder.
CLIMBING = (
    f"../../../home/{USER}/data/in.csv",
    f"../../{USER}/data/in.csv",
    f"./../../../home/{USER}/in.csv",
    f"data/../../../home/{USER}/in.csv",
    f"./data/../../{USER}/in.csv",
)
LAST = "in.csv"


@pytest.mark.parametrize("path", CLIMBING)
def test_a_climbing_path_as_an_argument_of_its_own_shows_its_last_part(path: str) -> None:
    assert model.public_command(("mytool", path)) == f"mytool {LAST}"


@pytest.mark.parametrize("path", CLIMBING)
def test_a_climbing_path_given_to_a_name_shows_its_last_part(path: str) -> None:
    assert model.public_command(("mytool", f"--data={path}")) == f"mytool --data={LAST}"


@pytest.mark.parametrize("path", CLIMBING)
def test_a_climbing_path_glued_to_an_option_shows_its_last_part(path: str) -> None:
    assert USER not in model.public_command(("mytool", f"-I{path}"))


@pytest.mark.parametrize(
    "path", [p for p in CLIMBING if not p.startswith("data/")], ids=lambda p: p.split(USER)[0]
)
def test_a_climbing_path_glued_to_an_option_keeps_the_option(path: str) -> None:
    assert model.public_command(("mytool", f"-I{path}")) == f"mytool -I{LAST}"


@pytest.mark.parametrize("path", CLIMBING)
def test_a_climbing_path_in_a_shell_text_shows_its_last_part(path: str) -> None:
    text = f"cat {path} | mytool --data={path} -I{path}"

    shown = model.public_command(("sh", "-c", text))

    assert USER not in shown
    assert shown.startswith(f"sh -c 'cat {LAST} | mytool --data={LAST} -I")


@pytest.mark.parametrize("path", CLIMBING)
def test_a_climbing_path_shows_its_last_part_as_a_path_a_text_and_a_case_id(path: str) -> None:
    assert model.public_path(path) == LAST
    assert model.public_text(f"read {path} now") == f"read {LAST} now"
    assert model.public_case(f"test_read[{path}]") == f"test_read[{LAST}]"
    assert model.public_case(f"bench file={path}") == f"bench file={LAST}"


def test_climbing_paths_side_by_side_each_show_their_last_part() -> None:
    text = f"cat ../a/{USER}/in.csv ../b/{USER}/out.csv ./../c/{USER}/z.csv"

    assert model.public_command(("sh", "-c", text)) == "sh -c 'cat in.csv out.csv z.csv'"


def test_a_climbing_path_whose_folders_hold_blanks_is_cut_whole() -> None:
    path = f"../../{USER} (x86)/Zq Files/in.csv"

    assert model.public_path(path) == LAST
    assert model.public_command(("mytool", path)) == f"mytool {LAST}"
    assert model.public_command(("mytool", f"--data={path}")) == f"mytool --data={LAST}"
    assert model.public_command(("sh", "-c", f"cat '{path}'")) == shlex.join(
        ["sh", "-c", f"cat '{LAST}'"]
    )


def test_a_name_whose_parts_climb_out_of_it_is_cut_in_a_case_id() -> None:
    assert model.public_case(f"bench/../../{USER}/in.csv") == LAST


# Words that climb out of no folder, or name none, and are shown as typed: ``..`` parts no
# more than the folders before them, as a text of ``sed`` has.
SHOWN_AS_TYPED = (
    "cd ../..",
    "./run.sh",
    "data/in.csv",
    "..",
    "../",
    "a/../..",
    "a/../b",
    "src/../include/x.h",
    "sed 's/../X/'",
    "sed 's/../&:/g'",
    "sed 's/..//'",
    "-I./include/x",
    "HEAD~2..HEAD",
    "v1.2..v1.3",
)


@pytest.mark.parametrize("text", SHOWN_AS_TYPED)
def test_a_word_that_climbs_no_folder_is_shown_as_typed(text: str) -> None:
    assert model.public_text(text) == text
    assert model.public_command(("sh", "-c", text)) == shlex.join(["sh", "-c", text])


def test_the_hash_keeps_a_climbing_path_as_typed() -> None:
    path = CLIMBING[1]

    assert model.hashed_argv(("mytool", path)) == ["mytool", path]


def _sample(case: str) -> api.Sample:
    return api.Sample(case=case, metric="time", unit="s", better="lower", kind="time", value=1.5)


def test_two_case_ids_that_differ_only_in_a_climbing_path_are_refused() -> None:
    ids = (f"test_read[../a/{USER}/in.csv]", f"test_read[../b/{USER}/in.csv]")

    assert [model.public_case(raw) for raw in ids] == ["test_read[in.csv]"] * 2
    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "made-up-driver")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "the name 'test_read[in.csv]'" in caught.value.message
    assert USER not in caught.value.message
