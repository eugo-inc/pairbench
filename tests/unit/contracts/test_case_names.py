# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The names a run gives to case ids whose cut drops words.

A path in a case id runs on over the words after it that start with a letter,
a digit or '_', and the cut keeps only its last part, so two ids that differ
in such a word would show alike. ``CaseNames`` gives such an id the shown name
plus a mark, ' +' and eight hex digits of a keyed hash, under the run's own
key, of what tells it apart: its words that hold no '/', read with its secrets
hidden. A name is a function of the key and the id alone, so it is the same in
every launch, on every side and in any order. A cut that drops only folders
gets no mark. Ids of one read that differ only in a hidden secret, or only in
words that hold a '/', are refused, and so are marks that clash, an id that
ends like a mark, and an id that needs a mark in a read without a key. The
capture keeps the key and a hash of what tells each name apart, never the
words. Every folder, word and key here is made up.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from pairbench import api
from pairbench.api import CaseNames, Sample, case_tell_sha256
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import (
    CASE_KEY_BYTES,
    Capture,
    CaseKeyRecord,
    CaseName,
    CaseNamesRecord,
    case_has_suffix,
    case_marked_name,
    case_suffix,
    case_tell_words,
    case_unsuffixed,
    public_case,
    public_case_drops,
    public_text,
)
from pairbench.stats.selftest import synthetic_capture as _synthetic

from .test_case_secrets import HIDDEN, RANDOMS, VALUES

WHERE = "side 'new'"
ADVICE = "give them other names"
SIDE = "new"
# A made-up key of CASE_KEY_BYTES bytes, and another.
KEY = bytes(range(32))
KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
OTHER_KEY = bytes(range(32, 64))
FAST = "run /made/up/new/a.py Zqfast data/x"
SLOW = "run /made/up/new/a.py Zqslow data/x"
MEDIUM = "run /made/up/new/a.py Zqmedium data/x"
# The same ids as another side or launch reads them: only their folders differ.
FAST_ELSEWHERE = "run /made/up/old/a.py Zqfast data/x"
SLOW_ELSEWHERE = "run /made/up/old/a.py Zqslow data/x"
SHOWN = "run x"
# The names KEY gives them, and the names OTHER_KEY gives them.
FAST_NAME = "run x +9337c10f"
SLOW_NAME = "run x +69c21f80"
MEDIUM_NAME = "run x +d4f87154"
FAST_OTHER = "run x +ac15bd41"
SLOW_OTHER = "run x +b82ae192"
READ = "read /made/up/1/in.csv"
READ_MOVED = "read /made/up/2/in.csv"
READ_SHOWN = "read in.csv"
# sha256 of the JSON text of what tells each id apart: ["words", <its words without a '/'>]
# for an id whose cut drops words, ["name", <its name>] for any other.
FAST_TELL = "057386923e0f145090594d82182e0a0da317c31fa77913cffeaeedd6063058c5"
SLOW_TELL = "872f53879ab29b4ee223b320b1307088fe7cfdb5dae7e558ef5457b24a325730"
READ_TELL = "a5717f29edbde71007d220098bd9032cc5a655723809dfab331e02e2fb49954c"
# sha256 of the ids as read; they hold no secret, so with their secrets hidden too.
FAST_SHA = "c40bb7561eadc1ec3792c4cefe11f85c6349ba8f8b522554effa74844a07f2e9"
SLOW_SHA = "b97cd6ff4b2d7073a12507d6c4e300d03da2ee53e2226b158712a44093d07df0"
READ_SHA = "e26fc16c43432d87c8ddad45cd2bfb37e04671cc40d0706696a6513ac0e0518b"
PLAIN_READ_SHA = "4edac4a2c273c496723cf4172223ac4cfa9df3e25c2cb13ea78289544e962a15"
HIDDEN_WORDS = ("Zqfast", "Zqslow", "Zqmedium", "made/up")
# What two ids shown alike are refused with.
SHOWN_ALIKE = (
    "two different cases have the name {shown!r} once absolute paths and paths that climb "
    "with '..' are cut and secrets hidden, as the results show it"
)
FOLDERS_ONLY = (
    "and differ only in words that hold a '/' once their secrets are hidden; pairbench reads "
    "such words as folders, which may differ between sides and launches"
)
CLASH = (
    f"{WHERE}: two different cases would have the name 'run x +0a0a0a0a': the marks pairbench "
    f"adds to names whose cut dropped words clash; {ADVICE}"
)
# sha256 of the JSON text ["words","run","Zqfast","token=<hidden>"] and of the same with
# Zqslow: the tells of two ids with a secret, read with the secret hidden.
SECRET_FAST_TELL = "0a68cb79c0e2643e09c5789c19c1c4116ff9a0be218f6e22beb35181016c64a4"
SECRET_SLOW_TELL = "d09571d365c91eb43b5990cd3463009dcfbefa9dfaba4ce72549f73152a0d741"
SECRET_FAST_NAME = "run x +1e192939"
SECRET_SLOW_NAME = "run x +19d164f0"
# The name KEY gives an id whose only dropped word is a hidden secret.
SECRET_ONLY_NAME = "run x +8d43a8db"


def synthetic_capture() -> Capture:
    return _synthetic(lambda entry, case, round_, u: 1.0 + u)


def _entry(name: str, tell: str, sha: str, side: str = SIDE) -> CaseName:
    return CaseName(name=name, side=side, tell_sha256=tell, hidden_sha256=sha, read_sha256=sha)


def _refused(names: CaseNames, raws: list[str], side: str = SIDE) -> Refusal:
    with pytest.raises(Refusal) as caught:
        names.names(raws, WHERE, ADVICE, side)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert not any(word in caught.value.message for word in HIDDEN_WORDS)
    assert KEY_HEX[:16] not in caught.value.message
    return caught.value


def test_the_key_and_the_mark_have_the_documented_size() -> None:
    assert CASE_KEY_BYTES == 32 == len(KEY)
    assert KEY.hex() == KEY_HEX
    assert case_suffix(KEY, FAST_TELL) == " +9337c10f"
    assert case_suffix(OTHER_KEY, FAST_TELL) == " +ac15bd41"


def test_an_id_with_nothing_cut_keeps_its_name_and_is_not_recorded() -> None:
    names = CaseNames(KEY)
    assert names.names(["run x", "BM_Vec<int>/8"], WHERE, ADVICE, SIDE) == {
        "run x": "run x",
        "BM_Vec<int>/8": "BM_Vec<int>/8",
    }
    assert names.take_new() == (None, ())


def test_a_cut_that_drops_only_folders_gives_no_mark_and_no_key() -> None:
    names = CaseNames(KEY)
    assert names.names([READ], WHERE, ADVICE, SIDE) == {READ: READ_SHOWN}
    assert case_tell_sha256(READ) == READ_TELL
    assert names.take_new() == (None, (_entry(READ_SHOWN, READ_TELL, READ_SHA),))


def test_a_cut_that_drops_only_folders_needs_no_key() -> None:
    assert CaseNames(None).names([READ], WHERE, ADVICE, SIDE) == {READ: READ_SHOWN}


def test_a_read_without_a_key_or_a_side_names_a_folder_cut_and_records_nothing() -> None:
    keyless = CaseNames(None)
    assert keyless.names([READ], WHERE, ADVICE) == {READ: READ_SHOWN}
    assert keyless.take_new() == (None, ())
    sideless = CaseNames(KEY)
    assert sideless.names([READ], WHERE, ADVICE) == {READ: READ_SHOWN}
    assert sideless.take_new() == (None, ())
    # A driver outside a run cuts the folder as it always did.
    made = Sample(case=READ, metric="time", unit="s", better="lower", kind="time", value=1.0)
    (sample,) = api.public_cases([made], WHERE)
    assert sample.case == READ_SHOWN


def test_a_folder_that_moves_keeps_the_name_and_records_the_new_read() -> None:
    names = CaseNames(KEY)
    names.names([READ], WHERE, ADVICE, SIDE)
    names.take_new()
    assert names.names([READ_MOVED], WHERE, ADVICE, SIDE) == {READ_MOVED: READ_SHOWN}
    key, entries = names.take_new()
    assert key is None
    assert [(one.name, one.tell_sha256) for one in entries] == [(READ_SHOWN, READ_TELL)]


def test_two_ids_that_differ_in_words_their_path_runs_over_get_two_marks() -> None:
    names = CaseNames(KEY)
    assert names.names([FAST, SLOW], WHERE, ADVICE, SIDE) == {FAST: FAST_NAME, SLOW: SLOW_NAME}
    assert SHOWN + case_suffix(KEY, FAST_TELL) == FAST_NAME
    assert SHOWN + case_suffix(KEY, SLOW_TELL) == SLOW_NAME
    assert names.take_new() == (
        KEY_HEX,
        (_entry(FAST_NAME, FAST_TELL, FAST_SHA), _entry(SLOW_NAME, SLOW_TELL, SLOW_SHA)),
    )
    # Taken once: the key is not given again, and the next take holds only what came after.
    assert names.take_new() == (None, ())
    names.names([MEDIUM], WHERE, ADVICE, SIDE)
    key, entries = names.take_new()
    assert key is None
    assert [one.name for one in entries] == [MEDIUM_NAME]


def test_one_id_whose_cut_drops_a_word_is_marked_alone_too() -> None:
    names = CaseNames(KEY)
    assert names.names([FAST], WHERE, ADVICE, SIDE) == {FAST: FAST_NAME}
    # A later id cut alike gets its own mark: no name given earlier changes.
    assert names.names([SLOW], WHERE, ADVICE, SIDE) == {SLOW: SLOW_NAME}
    assert names.names([MEDIUM, FAST], WHERE, ADVICE, SIDE) == {
        MEDIUM: MEDIUM_NAME,
        FAST: FAST_NAME,
    }


def test_the_same_id_read_twice_is_one_case() -> None:
    names = CaseNames(KEY)
    assert names.names([FAST, FAST, SLOW], WHERE, ADVICE, SIDE) == {
        FAST: FAST_NAME,
        SLOW: SLOW_NAME,
    }


def test_a_name_depends_on_the_key_and_the_id_alone() -> None:
    # Another read, in the other order and with other folders, gives the same names.
    first = CaseNames(KEY).names([FAST, SLOW], WHERE, ADVICE, "new")
    later = CaseNames(KEY).names([SLOW_ELSEWHERE, FAST_ELSEWHERE], WHERE, ADVICE, "old")
    assert first == {FAST: FAST_NAME, SLOW: SLOW_NAME}
    assert later == {SLOW_ELSEWHERE: SLOW_NAME, FAST_ELSEWHERE: FAST_NAME}
    # Another key gives other marks.
    other = CaseNames(OTHER_KEY).names([FAST, SLOW], WHERE, ADVICE, SIDE)
    assert other == {FAST: FAST_OTHER, SLOW: SLOW_OTHER}


def test_each_side_and_read_of_a_name_is_recorded_once() -> None:
    names = CaseNames(KEY)
    names.names([FAST], WHERE, ADVICE, "new")
    names.names([FAST], WHERE, ADVICE, "old")
    names.names([FAST_ELSEWHERE], WHERE, ADVICE, "old")
    names.names([FAST], WHERE, ADVICE, "new")
    key, entries = names.take_new()
    assert key == KEY_HEX
    assert [(one.name, one.side, one.read_sha256 == FAST_SHA) for one in entries] == [
        (FAST_NAME, "new", True),
        (FAST_NAME, "old", True),
        (FAST_NAME, "old", False),
    ]


def test_an_id_shown_as_read_is_recorded_once_another_id_gets_its_name() -> None:
    names = CaseNames(KEY)
    names.names([READ_SHOWN], WHERE, ADVICE, "old")
    assert names.take_new() == (None, ())
    names.names([READ], WHERE, ADVICE, "new")
    assert names.take_new() == (
        None,
        (
            _entry(READ_SHOWN, READ_TELL, PLAIN_READ_SHA, "old"),
            _entry(READ_SHOWN, READ_TELL, READ_SHA, "new"),
        ),
    )


# Ids whose path starts with two "/" after white space: the path is cut as one with a single
# "/" is, so the word it runs over tells the ids apart, and each id gets the name the same id
# with a single "/" gets on another side.
DOUBLE_SLASH = ("run //made/up/new/a.py Zqfast data/x", "run //made/up/new/a.py Zqslow data/x")


def test_a_path_that_starts_with_two_slashes_is_cut_and_marked_as_one_with_one() -> None:
    assert [public_case_drops(raw) for raw in DOUBLE_SLASH] == [(SHOWN, True), (SHOWN, True)]
    names = CaseNames(KEY)
    given = names.names(list(DOUBLE_SLASH), WHERE, ADVICE, "new")
    assert given == {DOUBLE_SLASH[0]: FAST_NAME, DOUBLE_SLASH[1]: SLOW_NAME}
    assert names.names([FAST_ELSEWHERE], "side 'old'", ADVICE, "old") == {FAST_ELSEWHERE: FAST_NAME}


# Ids whose path starts with three "/" after "=": the path is cut whole, so the word it runs over
# tells the ids apart, each id gets the mark of its words, as FAST and SLOW do, and the same id
# with a single "/" on another side gets the same name.
TRIPLE_SLASH = (
    "run k=///made/up/new/a.py Zqfast data/x",
    "run k=///made/up/new/a.py Zqslow data/x",
)
TRIPLE_SLASH_ELSEWHERE = "run k=/made/up/old/a.py Zqfast data/x"
TRIPLE_SLASH_NAMES = ("run k=x +9337c10f", "run k=x +69c21f80")


def test_a_path_that_starts_with_three_slashes_after_a_mark_is_cut_and_marked() -> None:
    assert [public_case_drops(raw) for raw in TRIPLE_SLASH] == [("run k=x", True)] * 2
    names = CaseNames(KEY)
    given = names.names(list(TRIPLE_SLASH), WHERE, ADVICE, "new")
    assert (given[TRIPLE_SLASH[0]], given[TRIPLE_SLASH[1]]) == TRIPLE_SLASH_NAMES
    elsewhere = names.names([TRIPLE_SLASH_ELSEWHERE], "side 'old'", ADVICE, "old")
    assert elsewhere == {TRIPLE_SLASH_ELSEWHERE: TRIPLE_SLASH_NAMES[0]}


# An id whose path in the query of an address starts with three "/" and runs over a word that
# names a credential: the folders of that path are no words that tell the id apart, so the id
# gets the mark of its other words, the same as with one "/" on another side.
QUERY_TRIPLE = "run k=/made/up/a.py Zqfast data/x postgresql:///db?host=///made/up/new/x token:/a/b"
QUERY_SINGLE = "run k=/made/up/a.py Zqfast data/x postgresql:///db?host=/made/up/old/x token:/a/b"
QUERY_NAME = "run k=x postgresql:///db?host=/b +9337c10f"


def test_a_query_path_that_starts_with_three_slashes_is_no_word_that_tells_ids_apart() -> None:
    assert case_tell_words(QUERY_TRIPLE) == ["run", "Zqfast"]
    assert case_tell_words("x postgresql:///db?host=///made/up/x token:/a/b") == ["x"]
    names = CaseNames(KEY)
    assert names.names([QUERY_TRIPLE], WHERE, ADVICE, "new") == {QUERY_TRIPLE: QUERY_NAME}
    assert names.names([QUERY_SINGLE], "side 'old'", ADVICE, "old") == {QUERY_SINGLE: QUERY_NAME}


# Ids that nest a local address in the query of an address with no host, on two sides whose
# folders differ: its folders go and tell nothing apart, so the first id needs no mark, the
# second gets the mark of its other words, and each id gets one name on both sides.
NESTED = (
    "test_conn[postgresql:///db?sslrootcert=file:///made/up/new/ca.pem] Zqfast",
    "run k=/made/up/a.py Zqfast data/x postgresql:///db?c=file:///made/up/new/x token:/a/b",
)
NESTED_ELSEWHERE = (
    "test_conn[postgresql:///db?sslrootcert=file:///made/up/old/ca.pem] Zqfast",
    "run k=/made/up/a.py Zqfast data/x postgresql:///db?c=file:///made/up/old/x token:/a/b",
)
NESTED_NAMES = (
    "test_conn[postgresql:///db?sslrootcert=file://ca.pem] Zqfast",
    "run k=x postgresql:///db?c=file://b +9337c10f",
)


def test_a_local_address_nested_in_a_query_is_no_word_that_tells_ids_apart() -> None:
    assert [case_tell_words(raw) for raw in NESTED] == [["Zqfast"], ["run", "Zqfast"]]
    assert case_tell_words("x postgresql:///db?host=file:///made/up/x token:/a/b") == ["x"]
    names = CaseNames(KEY)
    given = names.names(list(NESTED), WHERE, ADVICE, "new")
    assert (given[NESTED[0]], given[NESTED[1]]) == NESTED_NAMES
    elsewhere = names.names(list(NESTED_ELSEWHERE), "side 'old'", ADVICE, "old")
    assert (elsewhere[NESTED_ELSEWHERE[0]], elsewhere[NESTED_ELSEWHERE[1]]) == NESTED_NAMES


# Ids that hold a climbing path in the query of an address, with no host and after an earlier
# path behind a host, on two sides whose folders differ: its folders go and tell nothing apart,
# and each id gets one name on both sides.
CLIMBING = (
    "test_conn[postgresql:///db?sslrootcert=../../made/up/new/ca.pem] Zqfast",
    "run k=/made/up/a.py Zqfast data/x "
    "postgresql://h.example/db?k=/a/x&c=../made/up/new/x token:/a/b",
)
CLIMBING_ELSEWHERE = tuple(raw.replace("/new/", "/old/") for raw in CLIMBING)
CLIMBING_NAMES = (
    "test_conn[postgresql:///db?sslrootcert=ca.pem] Zqfast",
    "run k=x postgresql://h.example/db?k=/x&c=b +9337c10f",
)


def test_a_climbing_path_in_a_query_is_no_word_that_tells_ids_apart() -> None:
    assert [case_tell_words(raw) for raw in CLIMBING] == [["Zqfast"], ["run", "Zqfast"]]
    names = CaseNames(KEY)
    given = names.names(list(CLIMBING), WHERE, ADVICE, "new")
    assert (given[CLIMBING[0]], given[CLIMBING[1]]) == CLIMBING_NAMES
    elsewhere = names.names(list(CLIMBING_ELSEWHERE), "side 'old'", ADVICE, "old")
    assert (elsewhere[CLIMBING_ELSEWHERE[0]], elsewhere[CLIMBING_ELSEWHERE[1]]) == CLIMBING_NAMES


# Two ids whose path runs over a word that holds '%2F' and no '/', and the names KEY gives them:
# such a word is no folder, so it tells the two cases apart.
ENCODED_WORDS = ("run /made/up/a.py 4%2Fq data/x", "run /made/up/a.py 5%2Fq data/x")
ENCODED_WORD_NAMES = ("run x +bf06410f", "run x +98b84fe5")


def test_a_dropped_word_that_holds_an_encoded_slash_tells_two_ids_apart() -> None:
    assert [public_case_drops(raw) for raw in ENCODED_WORDS] == [(SHOWN, True), (SHOWN, True)]
    given = CaseNames(KEY).names(list(ENCODED_WORDS), WHERE, ADVICE, SIDE)
    assert tuple(given.values()) == ENCODED_WORD_NAMES


def test_sides_whose_dropped_words_differ_in_an_encoded_slash_name_two_cases() -> None:
    names = CaseNames(KEY)
    new = names.names([ENCODED_WORDS[0]], WHERE, ADVICE, "new")
    old = names.names([ENCODED_WORDS[1]], "side 'old'", ADVICE, "old")
    assert (new[ENCODED_WORDS[0]], old[ENCODED_WORDS[1]]) == ENCODED_WORD_NAMES


# Ids that name a path written with percent escapes, whose folders move, and the names KEY
# gives them: the path is cut to '%2F' and its last part, and its folders are read as folders,
# after the path that runs over a word and inside the words it runs over.
ENCODED_PATHS = (
    (
        "run /made/up/a.py Zqfast data/x host=%2Fmade%2Fold%2Frun",
        "run /made/up/a.py Zqfast data/x host=%2Fmade%2Fnew%2Frun",
        "run /made/up/a.py Zqslow data/x host=%2Fmade%2Fold%2Frun",
        ("run x host=%2Frun +a95da970", "run x host=%2Frun +72da8838"),
    ),
    (
        "run /made/up/a.py Zqfast host=%2Fmade%2Fold%2Frun data/x",
        "run /made/up/a.py Zqfast host=%2Fmade%2Fnew%2Frun data/x",
        "run /made/up/a.py Zqslow host=%2Fmade%2Fold%2Frun data/x",
        ("run x +a95da970", "run x +72da8838"),
    ),
)


@pytest.mark.parametrize(("first", "moved", "other", "marked"), ENCODED_PATHS)
def test_the_folders_of_a_path_written_with_percent_escapes_are_read_as_folders(
    first: str, moved: str, other: str, marked: tuple[str, str]
) -> None:
    names = CaseNames(KEY)
    given = names.names([first, other], WHERE, ADVICE, "new")
    assert (given[first], given[other]) == marked
    assert names.names([moved], "side 'old'", ADVICE, "old") == {moved: marked[0]}


# Two ids of one read whose encoded folders alone differ, and the one name they would share.
ENCODED_FOLDERS = ("get[?host=%2Fmade%2FZqa%2Frun]", "get[?host=%2Fmade%2FZqb%2Frun]")
ENCODED_FOLDERS_SHOWN = "get[?host=%2Frun]"


def test_ids_that_differ_only_in_an_encoded_folder_are_refused_in_one_read() -> None:
    refused = _refused(CaseNames(KEY), list(ENCODED_FOLDERS))
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=ENCODED_FOLDERS_SHOWN)}, and differ only in the "
        "folders of a path written with '%2F', or in those and words that hold a '/', once their "
        "secrets are hidden; pairbench reads such parts as folders, which may differ between "
        f"sides and launches; {ADVICE}"
    )
    assert "Zqa" not in refused.message and "Zqb" not in refused.message


# The name KEY gives "copy /made/up/in.bin Zqfast mode/x", with one space or two in the path.
SPACED_NAME = "copy x +f8e83fe4"


def test_ids_that_differ_only_in_the_spaces_in_a_cut_path_are_refused_as_such() -> None:
    ids = ["copy /made/up/in.bin Zqfast  mode/x", "copy /made/up/in.bin Zqfast mode/x"]
    refused = _refused(CaseNames(KEY), ids)
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=SPACED_NAME)}, and differ only in the spaces between "
        f"their words once their secrets are hidden; {ADVICE}"
    )


# Ids whose path is an address that keeps the '/' before its last part, the last folder named
# in words with a space: the cut drops only words that hold a '/', so it adds no mark.
ADDRESS_FOLDERS = (
    ("x unix:///made/up/my dir/s.sock", "x unix:///s.sock"),
    ("sqlite:////made/up/x y/db.sqlite", "sqlite:///db.sqlite"),
    ("x unix:///made/up/in.bin x/y", "x unix:///y"),
    ("x redis+unix:///made/up/my dir/r.sock?db=0", "x redis+unix:///r.sock?db=0"),
)
# Ids whose cut drops a word that holds no '/': the middle word of a folder named in three
# words, and a word the path runs over, each in an address that keeps the '/'.
ADDRESS_WORDS = (
    ("x unix:///made/up/my big dir/s.sock", "x unix:///s.sock"),
    ("x unix:///made/up/in.bin Zqfast x/y", "x unix:///y"),
)


@pytest.mark.parametrize(("raw", "shown"), ADDRESS_FOLDERS)
def test_an_address_whose_cut_drops_only_folders_adds_no_mark(raw: str, shown: str) -> None:
    assert public_case_drops(raw) == (shown, False)
    assert CaseNames(None).names([raw], WHERE, ADVICE) == {raw: shown}


@pytest.mark.parametrize(("raw", "shown"), ADDRESS_WORDS)
def test_an_address_whose_cut_drops_a_plain_word_adds_a_mark(raw: str, shown: str) -> None:
    assert public_case_drops(raw) == (shown, True)


# Ids whose path ends with a '/' that the cut does not show, its last part named in words with a
# space: every word that holds no '/' is shown, so the cut adds no mark.
END_SLASH_FOLDERS = (
    ("x /made/up/in.bin fast mode/ x", "x in.bin fast mode x"),
    ("x /made/up/my big dir/ x", "x my big dir x"),
    ("x '/made/up/in.bin fast mode/' x", "x 'in.bin fast mode' x"),
    ("x unix:///made/up/my big dir/ x", "x unix:///my big dir x"),
)
# Ids whose path ends with a '/' and whose cut drops a word that holds no '/': the middle word
# of a folder named in three words, and a word the path runs over.
END_SLASH_WORDS = (
    ("x /made/up/my big dir/q/ x", "x q x"),
    ("x /made/up/in.bin Zqfast x/y/ x", "x y x"),
)


@pytest.mark.parametrize(("raw", "shown"), END_SLASH_FOLDERS)
def test_a_path_whose_last_part_and_end_slash_hold_every_plain_word_adds_no_mark(
    raw: str, shown: str
) -> None:
    assert public_case_drops(raw) == (shown, False)
    assert CaseNames(None).names([raw], WHERE, ADVICE) == {raw: shown}


@pytest.mark.parametrize(("raw", "shown"), END_SLASH_WORDS)
def test_a_path_with_an_end_slash_whose_cut_drops_a_plain_word_adds_a_mark(
    raw: str, shown: str
) -> None:
    assert public_case_drops(raw) == (shown, True)


# Ids whose first address keeps its query and whose later words write a path in a query value,
# each with the same id as another side reads it, with fewer or other folders: every word the
# cuts drop holds a '/', so neither id gets a mark and the two sides name the case alike.
QUERY_FOLDERS = (
    (
        "x unix:///made/s.sock?db=0 y https://h.example/p?next=/made/up/d",
        "x unix:///made/s.sock?db=0 y https://h.example/p?next=/d",
        "x unix:///s.sock?db=0 y https://h.example/p?next=/d",
    ),
    (
        "x unix:///made/s.sock?db=0 y h.example/p?next=/made/up/d",
        "x unix:///other/s.sock?db=0 y h.example/p?next=/d",
        "x unix:///s.sock?db=0 y h.example/p?next=d",
    ),
    (
        "x postgresql:///db?host=/made/up/Zq dir/run",
        "x postgresql:///db?host=/other/run",
        "x postgresql:///db?host=/run",
    ),
    (
        "x https://h.example/p?next=/made/up/Zq dir/d",
        "x https://h.example/p?next=/d",
        "x https://h.example/p?next=/d",
    ),
)


@pytest.mark.parametrize(("new", "old", "shown"), QUERY_FOLDERS)
def test_sides_whose_query_folders_differ_name_the_case_alike(
    new: str, old: str, shown: str
) -> None:
    assert public_case_drops(new) == public_case_drops(old) == (shown, False)
    names = CaseNames(KEY)
    assert names.names([new], WHERE, ADVICE, "new") == {new: shown}
    assert names.names([old], "side 'old'", ADVICE, "old") == {old: shown}


# Ids whose address, or the path in its query, runs over a plain word ("Zqa"): the cut drops
# it, so each id gets a mark, and two ids that differ in that word get two. Both marks of each
# pair are the HMAC-SHA256 under KEY of the sha256 of ["words","x","Zqa"] and of the same with
# Zqb, or with "get" and the word.
ADDRESS_RUNS_OVER_A_WORD = (
    (
        "x postgresql:///db?host=/made/x Zqa mode/run",
        "x postgresql:///db?host=/made/x Zqb mode/run",
        "x postgresql:///db?host=/run",
        ("x postgresql:///db?host=/run +eb137a7b", "x postgresql:///db?host=/run +45a1d638"),
    ),
    (
        "get https://h.example/p?next=/made/x Zqquick mode/d",
        "get https://h.example/p?next=/made/x Zqlate mode/d",
        "get https://h.example/p?next=/d",
        ("get https://h.example/p?next=/d +fbd5e91b", "get https://h.example/p?next=/d +4d26e3b8"),
    ),
    (
        "x postgresql://u@/db?host=/made/x Zqa mode/run",
        "x postgresql://u@/db?host=/made/x Zqb mode/run",
        "x postgresql://<hidden>@/db?host=/run",
        (
            "x postgresql://<hidden>@/db?host=/run +eb137a7b",
            "x postgresql://<hidden>@/db?host=/run +45a1d638",
        ),
    ),
    (
        "x postgresql://h.example/db?host=/made/x Zqa mode/run",
        "x postgresql://h.example/db?host=/made/x Zqb mode/run",
        "x postgresql://h.example/db?host=/run",
        (
            "x postgresql://h.example/db?host=/run +eb137a7b",
            "x postgresql://h.example/db?host=/run +45a1d638",
        ),
    ),
    (
        "get http://h.example:/v1?next=/made/x Zqa mode/d",
        "get http://h.example:/v1?next=/made/x Zqb mode/d",
        "get http://h.example:/v1?next=/d",
        (
            "get http://h.example:/v1?next=/d +31f61743",
            "get http://h.example:/v1?next=/d +9a6f2b2f",
        ),
    ),
    (
        "x unix:///made/x Zqa mode/s.sock",
        "x unix:///made/x Zqb mode/s.sock",
        "x unix:///s.sock",
        ("x unix:///s.sock +eb137a7b", "x unix:///s.sock +45a1d638"),
    ),
    (
        "x file:///made/x Zqa mode/in.csv",
        "x file:///made/x Zqb mode/in.csv",
        "x file://in.csv",
        ("x file://in.csv +eb137a7b", "x file://in.csv +45a1d638"),
    ),
)


@pytest.mark.parametrize(("new", "old", "shown", "marked"), ADDRESS_RUNS_OVER_A_WORD)
def test_sides_whose_address_runs_over_another_word_get_their_own_marks(
    new: str, old: str, shown: str, marked: tuple[str, str]
) -> None:
    assert [public_case_drops(new), public_case_drops(old)] == [(shown, True), (shown, True)]
    names = CaseNames(KEY)
    given_new = names.names([new], WHERE, ADVICE, "new")
    given_old = names.names([old], "side 'old'", ADVICE, "old")
    assert (given_new[new], given_old[old]) == marked


# Pairs of ids that hold a credential written as a path, one through a folder whose name holds
# a blank and one through a plain folder: the secret is hidden through both folders, and the
# folders are read as folders, so both sides name the case alike. The mark of the third and
# fourth is the HMAC-SHA256 under KEY of the sha256 of ["words","Zqfast"]. In the last, the cut
# starts at a path before the credential, and the folders after it go on with its path; its
# mark is the HMAC-SHA256 under KEY of the sha256 of ["words","API_KEY=<hidden>]"].
CREDENTIAL_FOLDERS = (
    (
        "test_db[token:/made/Zq dir/x.pem]",
        "test_db[token:/made/up/x.pem]",
        "test_db[token:<hidden>]",
        "test_db[token:<hidden>]",
        False,
    ),
    ("key=/made/Zq dir/x %2Fq", "key=/made/up/x %2Fq", "key=<hidden>", "key=<hidden>", False),
    (
        "test_db[token=../Zq dir/x.pem] /made/a.py Zqfast mode/z",
        "test_db[token=../up/x.pem] /made/a.py Zqfast mode/z",
        "test_db[token=<hidden>] z",
        "test_db[token=<hidden>] z +6ea86a25",
        True,
    ),
    (
        "test_db[token:/made/Zq dir/x.pem] /made/a.py Zqfast mode/z",
        "test_db[token:/made/up/x.pem] /made/a.py Zqfast mode/z",
        "test_db[token:<hidden>] z",
        "test_db[token:<hidden>] z +6ea86a25",
        True,
    ),
    (
        "test_db[/made/s.sock API_KEY=made/Zq dir/x.pem]",
        "test_db[/made/s.sock API_KEY=made/up/x.pem]",
        "test_db[x.pem]",
        "test_db[x.pem] +325a7d4c",
        True,
    ),
)


@pytest.mark.parametrize(("new", "old", "shown", "name", "dropped"), CREDENTIAL_FOLDERS)
def test_a_credential_path_through_a_folder_with_a_blank_names_the_case_as_a_plain_folder_does(
    new: str, old: str, shown: str, name: str, dropped: bool
) -> None:
    assert [public_case_drops(new), public_case_drops(old)] == [(shown, dropped), (shown, dropped)]
    names = CaseNames(KEY)
    given_new = names.names([new], WHERE, ADVICE, "new")
    given_old = names.names([old], "side 'old'", ADVICE, "old")
    assert (given_new[new], given_old[old]) == (name, name)


# Ids with an address whose query a word after it follows, and a second address or a path
# after that word: the first address ends at the blank, and what follows is cut as the same
# words alone are, so no folder of the second shows.
SECOND_PATHS = (
    (
        "x unix:///made/s.sock?db=0 y unix:///made/Zqhome/s.sock",
        "x unix:///s.sock?db=0 y unix:///s.sock",
    ),
    (
        "x sqlite:////made/db.sqlite?mode=ro y sqlite:////made/Zqhome/db.sqlite",
        "x sqlite:///db.sqlite?mode=ro y sqlite:///db.sqlite",
    ),
    (
        "x redis+unix:///made/r.sock?db=0 y redis+unix:///made/Zqhome/r.sock",
        "x redis+unix:///r.sock?db=0 y redis+unix:///r.sock",
    ),
    (
        "x unix:///made/s.sock?db=0 y z=unix:///made/Zqhome/s.sock",
        "x unix:///s.sock?db=0 y z=unix:///s.sock",
    ),
    ("x unix:///made/s.sock?db=0 y a//Zqhome/x", "x unix:///s.sock?db=0 y a/x"),
    ("x unix:///made/s.sock?db=0 y z=a/../../Zqhome/x", "x unix:///s.sock?db=0 y z=x"),
)


@pytest.mark.parametrize(("raw", "shown"), SECOND_PATHS)
def test_a_path_after_an_address_and_a_word_is_cut_as_it_is_alone(raw: str, shown: str) -> None:
    assert public_case_drops(raw) == (shown, False)
    alone = raw.partition(" y ")[2]
    assert shown.endswith(" y " + public_case(alone))


# The shown command reads the same words as one text: no folder of the second address shows.
SECOND_ADDRESSES_SHOWN = (
    (
        "x unix:///made/s.sock?db=0 y unix:///made/Zqhome/s.sock",
        "x unix:///s.sock?db=0 y unix:///s.sock",
    ),
    ("x unix:///made/s.sock?db=0 y z=a/../../Zqhome/x", "x unix:///s.sock?db=0 y z=x"),
)


@pytest.mark.parametrize(("raw", "shown"), SECOND_ADDRESSES_SHOWN)
def test_the_shown_command_cuts_a_path_after_an_address_and_a_word(raw: str, shown: str) -> None:
    assert public_text(raw) == shown


# A path whose last part the secret before it reads as its value: the word between them that
# the id shows with its paths in place is hidden, so the id gets a mark, and two ids that differ
# in that word get two. The marks are the HMAC-SHA256 under KEY of the sha256 of
# ["words","--token","<hidden>","Zqa"] and of the same with Zqb.
SECRET_LAST_PART = (
    "--token /made/up/in.csv mode/ Zqa b/",
    "--token /made/up/in.csv mode/ Zqb b/",
)
SECRET_LAST_PART_SHOWN = "--token  <hidden> b"
SECRET_LAST_PART_NAMES = ("--token  <hidden> b +60e21475", "--token  <hidden> b +df115bb1")


def test_a_word_a_secret_hides_after_a_cut_tells_two_ids_apart() -> None:
    assert [public_case_drops(raw) for raw in SECRET_LAST_PART] == [
        (SECRET_LAST_PART_SHOWN, True),
        (SECRET_LAST_PART_SHOWN, True),
    ]
    given = CaseNames(KEY).names(list(SECRET_LAST_PART), WHERE, ADVICE, SIDE)
    assert tuple(given.values()) == SECRET_LAST_PART_NAMES


# Two ids that differ in one word and show alike once paths are cut and secrets hidden: in the
# first pair the word holds a secret and a cut runs over the blank before it; in the second the
# cut leaves a credential option, so the word after it stands as its hidden value; in the third
# the cut that drops the word starts at a path after a credential's value. In the last two the
# cut runs over a credential written as a path, and the word that differs is a plain word after
# that path, or the name of a second credential after it. Each side names its case with its own
# mark.
CUT_HIDES_A_TELLING_WORD = (
    (
        "run /made/up/x API_KEY=zq/m",
        "run /made/up/x TOKEN=zq/m",
        "run m",
        ("run m +9be6a0e0", "run m +d8629de0"),
    ),
    (
        "run /made/up/--token Zqa",
        "run /made/up/--token Zqb",
        "run --token <hidden>",
        ("run --token <hidden> +37bb8f0e", "run --token <hidden> +27b55213"),
    ),
    (
        "run password=q/zq /made/up/s.sock %2Fq q/zq",
        "run password=q/zq /made/up/s.sock %2Fr q/zq",
        "run password=<hidden>",
        ("run password=<hidden> +09b14ae8", "run password=<hidden> +9355e83f"),
    ),
    (
        "run /made/s.sock API_KEY=made/up/x.pem Zqa mode/z",
        "run /made/s.sock API_KEY=made/up/x.pem Zqb mode/z",
        "run z",
        ("run z +e0b1eac7", "run z +e25eae1f"),
    ),
    (
        "run /made/s.sock password=q/zq q/zq PGPASSWORD=made/x mode/z",
        "run /made/s.sock password=q/zq q/zq TOKEN=made/x mode/z",
        "run z",
        ("run z +4a95cc31", "run z +c0e2fadc"),
    ),
)


@pytest.mark.parametrize(("new", "old", "shown", "marked"), CUT_HIDES_A_TELLING_WORD)
def test_sides_whose_ids_a_cut_and_a_secret_show_alike_get_their_own_marks(
    new: str, old: str, shown: str, marked: tuple[str, str]
) -> None:
    assert [public_case_drops(new), public_case_drops(old)] == [(shown, True), (shown, True)]
    names = CaseNames(KEY)
    given_new = names.names([new], WHERE, ADVICE, "new")
    given_old = names.names([old], "side 'old'", ADVICE, "old")
    assert (given_new[new], given_old[old]) == marked


# A secret read with the paths in place may hide more than it hides once they are cut; every
# word that tells the id apart is still shown, so the name needs no mark.
SECRET_HIDES_MORE = (
    ("bash -c 'API_KEY=q/made --out=/made/up/x.bin'", "bash -c 'API_KEY=<hidden> --out=x.bin'"),
    ("perl -e '$token =~ m/made Zq /x; run_old()'", "perl -e '$token =~ <hidden> Zq x; run_old()'"),
    ("run[API_KEY=q/made --out=/made/up/x.bin]", "run[API_KEY=<hidden> --out=x.bin]"),
)


@pytest.mark.parametrize(("raw", "shown"), SECRET_HIDES_MORE)
def test_a_secret_that_hides_more_before_the_cut_adds_no_mark(raw: str, shown: str) -> None:
    assert public_case_drops(raw) == (shown, False)
    assert CaseNames(KEY).names([raw], WHERE, ADVICE, SIDE) == {raw: shown}


def test_sides_whose_socket_folders_differ_name_the_case_alike() -> None:
    names = CaseNames(KEY)
    new = names.names(["x unix:///made/up/my dir/s.sock"], WHERE, ADVICE, "new")
    old = names.names(["x unix:///made/up/b/s.sock"], "side 'old'", ADVICE, "old")
    assert list(new.values()) == list(old.values()) == ["x unix:///s.sock"]


def test_ids_that_differ_only_in_their_folders_are_refused_in_one_read() -> None:
    names = CaseNames(KEY)
    refused = _refused(names, ["read /made/up/Zqa/in.csv", "read /made/up/Zqb/in.csv"])
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=READ_SHOWN)}, {FOLDERS_ONLY}; {ADVICE}"
    )
    assert "Zqa" not in refused.message and "Zqb" not in refused.message


def test_ids_whose_cut_drops_words_and_that_differ_only_in_a_folder_are_refused() -> None:
    refused = _refused(CaseNames(KEY), [FAST, FAST_ELSEWHERE])
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=FAST_NAME)}, {FOLDERS_ONLY}; {ADVICE}"
    )


def test_an_id_with_nothing_cut_and_a_cut_id_shown_alike_are_refused_in_one_read() -> None:
    refused = _refused(CaseNames(KEY), [READ_SHOWN, READ])
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=READ_SHOWN)}, {FOLDERS_ONLY}; {ADVICE}"
    )


def _with_secret(case: str, at: int) -> str:
    return case.replace("{v}", VALUES[at]).replace("{r}", RANDOMS[at])


def _no_secret_in(message: str) -> None:
    values = (*VALUES, *RANDOMS)
    pieces = (value[at : at + 6] for value in values for at in range(len(value) - 5))
    assert [piece for piece in pieces if piece in message] == []


@pytest.mark.parametrize("case", list(HIDDEN))
def test_a_hidden_secret_never_tells_two_ids_apart(case: str) -> None:
    assert case_tell_sha256(_with_secret(case, 0)) == case_tell_sha256(_with_secret(case, 1))


@pytest.mark.parametrize("case", list(HIDDEN))
def test_ids_that_differ_only_in_a_hidden_secret_are_refused(case: str) -> None:
    names = CaseNames(KEY)
    refused = _refused(names, [_with_secret(case, 0), _with_secret(case, 1)])
    shown = SHOWN_ALIKE.format(shown=HIDDEN[case])
    assert refused.message == f"{WHERE}: {shown}, and differ only in a hidden secret; {ADVICE}"
    _no_secret_in(refused.message)
    assert names.take_new() == (None, ())


@pytest.mark.parametrize(
    ("case", "shown"),
    [
        ("run /made/up/a.py token={v} data/x", SECRET_ONLY_NAME),
        ("run /made/up/a.py --token {v} data/x", "run a.py --token <hidden> data/x"),
        ("test_read[/made/up/in.csv token={v}]", "test_read[in.csv token=<hidden>]"),
        ("bench[/made/up/in.csv,api_key={v}]", "bench[in.csv,api_key=<hidden>]"),
    ],
)
def test_ids_whose_path_is_cut_and_that_differ_only_in_a_secret_are_refused(
    case: str, shown: str
) -> None:
    raws = [_with_secret(case, 0), _with_secret(case, 1)]
    assert CaseNames(KEY).names(raws[:1], WHERE, ADVICE, SIDE) == {raws[0]: shown}
    refused = _refused(CaseNames(KEY), raws)
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=shown)}, and differ only in a hidden secret; {ADVICE}"
    )
    _no_secret_in(refused.message)


def test_ids_that_differ_in_a_secret_and_in_a_word_their_path_runs_over_get_two_marks() -> None:
    names = CaseNames(KEY)
    fast = _with_secret("run /made/up/new/a.py Zqfast token={v} data/x", 0)
    slow = _with_secret("run /made/up/new/a.py Zqslow token={v} data/x", 1)
    assert names.names([fast, slow], WHERE, ADVICE, SIDE) == {
        fast: SECRET_FAST_NAME,
        slow: SECRET_SLOW_NAME,
    }
    key, entries = names.take_new()
    assert key == KEY_HEX
    assert [(one.name, one.tell_sha256) for one in entries] == [
        (SECRET_FAST_NAME, SECRET_FAST_TELL),
        (SECRET_SLOW_NAME, SECRET_SLOW_TELL),
    ]
    # Hashed with the secret hidden, and as read: the two differ for an id with a secret.
    assert all(one.hidden_sha256 != one.read_sha256 for one in entries)
    # A later launch with the secrets swapped and the folder moved keeps each name.
    slow_later = _with_secret("run /made/up/old/a.py Zqslow token={v} data/x", 0)
    fast_later = _with_secret("run /made/up/old/a.py Zqfast token={v} data/x", 1)
    assert names.names([slow_later, fast_later], WHERE, ADVICE, SIDE) == {
        slow_later: SECRET_SLOW_NAME,
        fast_later: SECRET_FAST_NAME,
    }


def test_ids_that_differ_in_a_secret_and_only_in_their_folders_are_refused() -> None:
    raws = [
        _with_secret("read /made/up/Zqa/in.csv token={v}", 0),
        _with_secret("read /made/up/Zqb/in.csv token={v}", 1),
    ]
    refused = _refused(CaseNames(KEY), raws)
    shown = "read in.csv token=<hidden>"
    assert refused.message == (
        f"{WHERE}: {SHOWN_ALIKE.format(shown=shown)}, {FOLDERS_ONLY}; {ADVICE}"
    )
    assert "Zqa" not in refused.message and "Zqb" not in refused.message
    _no_secret_in(refused.message)


@pytest.mark.parametrize("case", list(HIDDEN))
def test_an_id_whose_secret_differs_in_a_later_launch_keeps_its_name(case: str) -> None:
    names = CaseNames(KEY)
    first, later = _with_secret(case, 0), _with_secret(case, 1)
    assert names.names([first], WHERE, ADVICE, SIDE) == {first: HIDDEN[case]}
    assert names.names([later], WHERE, ADVICE, SIDE) == {later: HIDDEN[case]}


@pytest.mark.parametrize(
    "case",
    [
        "run x +1a2b3c4d",
        "BM_x +1a2b3c4d/cpu_time",
        "run /made/up/a.py +1a2b3c4d",
        "test_read[/made/up/in.csv] +0f0f0f0f",
    ],
)
def test_an_id_that_ends_like_a_mark_is_refused(case: str) -> None:
    names = CaseNames(KEY)
    refused = _refused(names, [case])
    shown = public_case(case)
    assert case_has_suffix(shown)
    assert refused.message == (
        f"{WHERE}: the case read as {shown!r} ends like the mark pairbench adds to a name whose "
        "cut dropped words, ' +' and eight hex digits; give it a name that does not end so"
    )
    assert names.take_new() == (None, ())


@pytest.mark.parametrize(
    "case", ["run x +1a2b3c4", "run x +1A2B3C4D", "run x+1a2b3c4d", "run x +1a2b3c4d9"]
)
def test_an_id_that_only_looks_near_a_mark_keeps_its_name(case: str) -> None:
    assert not case_has_suffix(case)
    assert CaseNames(KEY).names([case], WHERE, ADVICE, SIDE) == {case: case}


def test_an_id_that_needs_a_mark_is_refused_in_a_read_without_a_key() -> None:
    names = CaseNames(None)
    refused = _refused(names, [FAST])
    assert refused.message == (
        f"{WHERE}: the cut of the case read as {SHOWN!r} drops words that hold no '/', so its "
        "name needs the mark a run makes with its own key, and this read has none; read it in "
        f"a run, or {ADVICE}"
    )
    assert names.take_new() == (None, ())


def _clashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "case_suffix", lambda key, tell: " +0a0a0a0a")


def test_two_marks_that_clash_in_one_read_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clashing(monkeypatch)
    names = CaseNames(KEY)
    assert _refused(names, [FAST, SLOW]).message == CLASH
    assert names.take_new() == (None, ())


def test_a_mark_that_clashes_with_an_earlier_read_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clashing(monkeypatch)
    names = CaseNames(KEY)
    assert names.names([FAST], WHERE, ADVICE, "new") == {FAST: "run x +0a0a0a0a"}
    names.take_new()
    assert _refused(names, [READ, SLOW], "old").message == CLASH
    # The refused read gave no name: READ, read first in it, is not recorded.
    assert names.take_new() == (None, ())
    assert names.names([FAST_ELSEWHERE], WHERE, ADVICE, "old") == {
        FAST_ELSEWHERE: "run x +0a0a0a0a"
    }


def test_a_refused_read_gives_no_name_and_takes_no_key() -> None:
    names = CaseNames(KEY)
    _refused(names, [FAST, SLOW, "read /made/up/Zqa/in.csv", "read /made/up/Zqb/in.csv"])
    assert names.take_new() == (None, ())
    assert names.names([FAST], WHERE, ADVICE, SIDE) == {FAST: FAST_NAME}
    assert names.take_new() == (KEY_HEX, (_entry(FAST_NAME, FAST_TELL, FAST_SHA),))


def test_a_marked_name_is_not_cut_again() -> None:
    for name in (FAST_NAME, "BM_x +1a2b3c4d/cpu_time", "file://m.gguf +1a2b3c4d/cpu_time"):
        assert public_case(name) == name


def test_the_mark_is_found_and_taken_off() -> None:
    assert case_marked_name("BM_Read/x +1a2b3c4d/cpu_time") == "BM_Read/x +1a2b3c4d"
    assert case_marked_name(FAST_NAME) == FAST_NAME
    assert case_marked_name(SHOWN) is None
    assert case_unsuffixed("BM_Read/x +1a2b3c4d/cpu_time") == "BM_Read/x/cpu_time"
    assert case_unsuffixed(FAST_NAME) == SHOWN
    assert case_unsuffixed(SHOWN) == SHOWN


def _with_names(key: str | None, *given: CaseName) -> Capture:
    return dataclasses.replace(synthetic_capture(), case_key=key, case_names=given)


def test_the_records_hold_the_key_then_the_names_and_read_back() -> None:
    given = (_entry(FAST_NAME, FAST_TELL, FAST_SHA), _entry(SLOW_NAME, SLOW_TELL, SLOW_SHA))
    records = _with_names(KEY_HEX, *given).to_records()
    kinds = [r["t"] for r in records]
    assert kinds.index("case_key") + 1 == kinds.index("case_names")
    assert kinds.index("case_names") < kinds.index("launch")
    assert [r for r in records if r["t"] == "case_key"] == [{"t": "case_key", "key": KEY_HEX}]
    kept = [r for r in records if r["t"] == "case_names"]
    assert kept == [
        {
            "t": "case_names",
            "names": [
                {
                    "name": FAST_NAME,
                    "side": SIDE,
                    "tell_sha256": FAST_TELL,
                    "hidden_sha256": FAST_SHA,
                    "read_sha256": FAST_SHA,
                },
                {
                    "name": SLOW_NAME,
                    "side": SIDE,
                    "tell_sha256": SLOW_TELL,
                    "hidden_sha256": SLOW_SHA,
                    "read_sha256": SLOW_SHA,
                },
            ],
        }
    ]
    back = Capture.from_records(records)
    assert (back.case_key, back.case_names) == (KEY_HEX, given)
    assert CaseNamesRecord.from_json(kept[0]) == CaseNamesRecord(names=given)


def test_a_capture_with_no_names_writes_no_record() -> None:
    kinds = {r["t"] for r in synthetic_capture().to_records()}
    assert "case_names" not in kinds and "case_key" not in kinds
    assert (synthetic_capture().case_key, synthetic_capture().case_names) == (None, ())


def test_a_capture_with_two_keys_is_refused() -> None:
    records: list[dict[str, Any]] = synthetic_capture().to_records()
    records.insert(1, CaseKeyRecord(key=KEY_HEX).to_json())
    records.insert(2, CaseKeyRecord(key=OTHER_KEY.hex()).to_json())
    with pytest.raises(Refusal) as caught:
        Capture.from_records(records)
    assert (caught.value.code, caught.value.exit_code, caught.value.message) == (
        "E_USAGE",
        EXIT_USAGE,
        "a capture has two case_key records",
    )


def test_the_records_of_several_launches_are_merged_in_order() -> None:
    first = _entry(FAST_NAME, FAST_TELL, FAST_SHA)
    second = _entry(SLOW_NAME, SLOW_TELL, SLOW_SHA)
    read = _entry(READ_SHOWN, READ_TELL, READ_SHA)
    records: list[dict[str, Any]] = synthetic_capture().to_records()
    records.insert(1, CaseKeyRecord(key=KEY_HEX).to_json())
    records.insert(2, CaseNamesRecord(names=(first, second)).to_json())
    records.insert(3, CaseNamesRecord(names=(read,)).to_json())
    assert Capture.from_records(records).case_names == (first, second, read)


def test_the_records_validate_against_the_capture_schema() -> None:
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    from pairbench.results import load_schema

    validator = jsonschema.Draft202012Validator(load_schema("capture"))
    names = CaseNamesRecord(names=(_entry(FAST_NAME, FAST_TELL, FAST_SHA),)).to_json()
    assert list(validator.iter_errors(names)) == []
    assert list(validator.iter_errors(CaseKeyRecord(key=KEY_HEX).to_json())) == []
    entry = names["names"][0]
    bad: list[dict[str, Any]] = [
        {"t": "case_names", "names": [{**entry, "tell_sha256": "Zq"}]},
        {"t": "case_names", "names": [{k: v for k, v in entry.items() if k != "side"}]},
        {"t": "case_names", "names": [{**entry, "base": SHOWN}]},
        {"t": "case_key", "key": "Zq"},
        {"t": "case_key", "key": KEY_HEX.upper()},
        {"t": "case_key"},
    ]
    assert [bool(list(validator.iter_errors(one))) for one in bad] == [True] * len(bad)
