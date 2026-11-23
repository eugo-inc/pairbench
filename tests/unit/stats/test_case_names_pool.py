# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Pooling captures whose case names carry a run's mark.

A run marks the name of an id whose cut dropped words that hold no '/' with
its own random key, and keeps the key and, for each side and id, the hash of
what tells the case apart (``Capture.case_key``, ``Capture.case_names``). A
pool gives every marked name the mark the first capture's key makes, so one
case has one name in the pool; two different cases whose marks clash under
that key, and a mark no run gave, are refused. Ids that differ only in a
folder or only in a hidden secret are read as one case, and the pool says so
in a note that names only the shown case. Every folder, word and key here is
made up.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from pairbench import api
from pairbench.api import CaseNames
from pairbench.errors import EXIT_ANALYSIS, EXIT_USAGE, Refusal
from pairbench.model import (
    NOTE_CASE_NAMED_APART,
    NOTE_POOL_FOLDERS_MERGED,
    NOTE_POOL_SECRETS_MERGED,
    STRICT,
    Capture,
    Note,
    Results,
)
from pairbench.stats import analyse
from pairbench.stats.analyse import analyse_captures
from pairbench.stats.selftest import MATMUL, synthetic_capture

# The entries of a synthetic capture: each side and its twin.
ENTRIES = ("new", "new~same", "old", "old~same")
KEY = bytes(range(32))
OTHER_KEY = bytes(range(32, 64))
FAST = "run /made/up/{folder}/a.py Zqfast data/x"
SLOW = "run /made/up/{folder}/a.py Zqslow data/x"
# The names KEY and OTHER_KEY give the two ids.
FAST_NAME = "run x +9337c10f"
SLOW_NAME = "run x +69c21f80"
FAST_OTHER = "run x +ac15bd41"
SLOW_OTHER = "run x +b82ae192"
READ = "read /made/up/{folder}/in.csv"
READ_NAME = "read in.csv"
SECRET = "test_db[PGPASSWORD={secret}]"
SECRET_NAME = "test_db[PGPASSWORD=<hidden>]"
CLASH = " +0a0a0a0a"
MARK_WORDS = (
    "which ends like the mark pairbench adds to a name whose cut dropped words, ' +' and eight "
    "hex digits"
)
FOLDERS_WHY = (
    "from ids that differ only in words that hold a '/' or in the folders of a path written with "
    "'%2F', which pairbench reads as folders; if those folders are different inputs, keep the "
    "captures apart"
)
SECRETS_WHY = (
    "from ids that differ only in a hidden secret; if those secrets name different inputs, keep "
    "the captures apart"
)
HIDDEN_WORDS = ("Zqfast", "Zqslow", "Zqa", "Zqb", "kiwi7", "pear3", "made/up")


def _value(entry: str, case: str, round_: int, u: float) -> float:
    return 1.0 + u / 1000


def _named(key: bytes | None, raws: Sequence[str], folder: str = "Zqa") -> tuple[Any, ...]:
    """Name ``raws`` on every entry as a run with ``key`` does; return names, key and entries."""
    names = CaseNames(key)
    shown: dict[str, str] = {}
    for entry in ENTRIES:
        given = [raw.format(folder=folder) for raw in raws]
        shown = names.names(given, f"side {entry!r}", "made-up advice", side=entry)
    key_hex, recorded = names.take_new()
    return tuple(shown.values()), key_hex, recorded


def _capture(
    ident: str,
    seed: int,
    key: bytes | None,
    raws: Sequence[str],
    folder: str = "Zqa",
) -> Capture:
    cases, key_hex, recorded = _named(key, raws, folder)
    made = synthetic_capture(
        _value,
        seed=seed,
        capture_id=ident,
        cases=tuple(dataclasses.replace(MATMUL, id=case) for case in cases),
    )
    return dataclasses.replace(made, case_key=key_hex, case_names=recorded)


def _pool(*captures: Capture) -> Results:
    return analyse_captures(captures, rule=STRICT)


def _cases(results: Results) -> set[str]:
    return {c.case for c in results.comparisons}


def _notes(results: Results, *codes: str) -> list[Note]:
    return [n for n in results.notes if n.code in codes]


def _refused(make: Callable[[], Any], code: str = "E_USAGE") -> Refusal:
    with pytest.raises(Refusal) as caught:
        make()
    exit_code = EXIT_USAGE if code == "E_USAGE" else EXIT_ANALYSIS
    assert (caught.value.code, caught.value.exit_code) == (code, exit_code)
    assert not any(word in caught.value.message for word in HIDDEN_WORDS)
    return caught.value


def test_a_pool_shows_the_marks_of_the_first_capture() -> None:
    a = _capture("synthetic-a", 1, KEY, (FAST, SLOW))
    b = _capture("synthetic-b", 2, OTHER_KEY, (FAST, SLOW), folder="Zqa")
    assert _cases(_pool(a)) == {FAST_NAME, SLOW_NAME}
    assert _cases(_pool(b)) == {FAST_OTHER, SLOW_OTHER}

    pooled = _pool(a, b)
    assert pooled.run.pooled is True
    assert _cases(pooled) == {FAST_NAME, SLOW_NAME}
    # The other order shows the marks of the other key.
    assert _cases(_pool(b, a)) == {FAST_OTHER, SLOW_OTHER}
    # The same ids read in both captures: no case is read from different ids.
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == []


def test_a_mark_of_another_capture_stays_out_of_the_pool() -> None:
    a = _capture("synthetic-a", 1, KEY, (FAST, SLOW))
    b = _capture("synthetic-b", 2, OTHER_KEY, (FAST, SLOW))
    text = repr(_pool(a, b))
    assert FAST_OTHER not in text and SLOW_OTHER not in text


def test_ids_that_differ_in_a_shown_word_stay_two_cases() -> None:
    a = _capture("synthetic-a", 1, KEY, (FAST,))
    b = _capture("synthetic-b", 2, OTHER_KEY, (SLOW,))
    refused = _refused(lambda: _pool(a, b), "E_POOL_CASES")
    assert refused.message == (
        f"the cases {SLOW_NAME}, {FAST_NAME} differ between the captures synthetic-a and "
        "synthetic-b"
    )
    assert refused.detail["cases"] == [SLOW_NAME, FAST_NAME]


def test_two_cases_whose_marks_clash_in_the_pool_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def clash(key: bytes, tell: str) -> str:
        return CLASH

    monkeypatch.setattr(api, "case_suffix", clash)
    monkeypatch.setattr(analyse, "case_suffix", clash)
    a = _capture("synthetic-a", 1, KEY, (FAST,))
    b = _capture("synthetic-b", 2, OTHER_KEY, (SLOW,))
    refused = _refused(lambda: _pool(a, b))
    assert refused.message == (
        "two different cases of the captures synthetic-a and synthetic-b would have the name "
        "'run x +0a0a0a0a' in the pool: the marks pairbench adds to names whose cut dropped "
        "words clash; analyse the captures apart"
    )


@pytest.mark.parametrize(
    "case_key",
    [pytest.param(OTHER_KEY.hex(), id="another-key"), pytest.param(None, id="no-key")],
)
def test_a_mark_the_capture_key_does_not_give_is_refused(case_key: str | None) -> None:
    made = _capture("synthetic-a", 1, KEY, (FAST, SLOW))
    forged = dataclasses.replace(made, case_key=case_key)
    refused = _refused(lambda: _pool(forged))
    assert refused.message == (
        f"the capture synthetic-a holds the case {FAST_NAME!r} with a mark its run's key does "
        "not give; it was changed after its run"
    )


def test_a_name_that_ends_like_a_mark_no_run_gave_is_refused() -> None:
    made = synthetic_capture(
        _value,
        seed=1,
        capture_id="synthetic-a",
        cases=(dataclasses.replace(MATMUL, id="run x +1a2b3c4d"),),
    )
    refused = _refused(lambda: _pool(made))
    assert refused.message == (
        "the capture synthetic-a holds the case 'run x +1a2b3c4d', "
        f"{MARK_WORDS}, and no run gave it that mark; give it a name that does not end so"
    )


def test_a_name_a_capture_gives_to_two_cases_is_refused() -> None:
    made = _capture("synthetic-a", 1, KEY, (FAST, SLOW))
    fast = next(n for n in made.case_names if n.name == FAST_NAME)
    edited = dataclasses.replace(
        made, case_names=(*made.case_names, dataclasses.replace(fast, tell_sha256="f" * 64))
    )
    refused = _refused(lambda: _pool(edited))
    assert refused.message == (
        f"the capture synthetic-a gives the name {FAST_NAME!r} to two different cases; it was "
        "changed after its run"
    )


def test_marked_ids_whose_folders_differ_between_captures_pool_with_a_note() -> None:
    a = _capture("synthetic-a", 1, KEY, (FAST, SLOW), folder="Zqa")
    b = _capture("synthetic-b", 2, OTHER_KEY, (FAST, SLOW), folder="Zqb")
    pooled = _pool(a, b)
    assert _cases(pooled) == {FAST_NAME, SLOW_NAME}
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == [
        Note(
            code=NOTE_POOL_FOLDERS_MERGED,
            message=f"the pooled captures read each of the cases {SLOW_NAME!r}, {FAST_NAME!r} "
            f"as one case {FOLDERS_WHY}",
        )
    ]


def test_ids_that_differ_only_in_a_folder_between_captures_pool_with_a_note() -> None:
    a = _capture("synthetic-a", 1, KEY, (READ,), folder="Zqa")
    b = _capture("synthetic-b", 2, OTHER_KEY, (READ,), folder="Zqb")
    assert a.case_key is None and b.case_key is None
    pooled = _pool(a, b)
    assert _cases(pooled) == {READ_NAME}
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == [
        Note(
            code=NOTE_POOL_FOLDERS_MERGED,
            message=f"the pooled captures read the case {READ_NAME!r} as one case {FOLDERS_WHY}",
        )
    ]
    assert not any(word in repr(pooled) for word in HIDDEN_WORDS)


# An id that names a path written with percent escapes, its folder put in, and the name it shows.
ENCODED = "get[?host=%2Fmade%2F{folder}%2Frun]"
ENCODED_NAME = "get[?host=%2Frun]"


def test_ids_that_differ_only_in_an_encoded_folder_between_captures_pool_with_a_note() -> None:
    a = _capture("synthetic-a", 1, KEY, (ENCODED,), folder="Zqa")
    b = _capture("synthetic-b", 2, OTHER_KEY, (ENCODED,), folder="Zqb")
    pooled = _pool(a, b)
    assert _cases(pooled) == {ENCODED_NAME}
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == [
        Note(
            code=NOTE_POOL_FOLDERS_MERGED,
            message=f"the pooled captures read the case {ENCODED_NAME!r} as one case {FOLDERS_WHY}",
        )
    ]
    assert "Zqa" not in repr(pooled) and "Zqb" not in repr(pooled)


# An id with a secret written as a path, its folder put in, and the name it shows.
CREDENTIAL = "test_db[token:/made/{folder}/x.pem]"
CREDENTIAL_NAME = "test_db[token:<hidden>]"


def test_a_secret_path_through_a_folder_with_a_blank_pools_with_a_plain_folder() -> None:
    a = _capture("synthetic-a", 1, KEY, (CREDENTIAL,), folder="Zq dir")
    b = _capture("synthetic-b", 2, OTHER_KEY, (CREDENTIAL,), folder="up")
    assert a.case_key is None and b.case_key is None
    pooled = _pool(a, b)
    assert _cases(pooled) == {CREDENTIAL_NAME}
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == [
        Note(
            code=NOTE_POOL_FOLDERS_MERGED,
            message=f"the pooled captures read the case {CREDENTIAL_NAME!r} as one case "
            f"{FOLDERS_WHY}",
        )
    ]
    assert "Zq dir" not in repr(pooled) and "made/up" not in repr(pooled)


def test_ids_that_differ_only_in_a_hidden_secret_between_captures_pool_with_a_note() -> None:
    a = _capture("synthetic-a", 1, KEY, (SECRET.format(secret="zq-made-up-kiwi7"),))
    b = _capture("synthetic-b", 2, OTHER_KEY, (SECRET.format(secret="zq-made-up-pear3"),))
    assert a.case_key is None and b.case_key is None
    pooled = _pool(a, b)
    assert _cases(pooled) == {SECRET_NAME}
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == [
        Note(
            code=NOTE_POOL_SECRETS_MERGED,
            message=f"the pooled captures read the case {SECRET_NAME!r} as one case {SECRETS_WHY}",
        )
    ]
    assert not any(word in repr(pooled) for word in HIDDEN_WORDS)


def test_the_same_secret_in_both_captures_pools_without_a_note() -> None:
    a = _capture("synthetic-a", 1, KEY, (SECRET.format(secret="zq-made-up-kiwi7"),))
    b = _capture("synthetic-b", 2, OTHER_KEY, (SECRET.format(secret="zq-made-up-kiwi7"),))
    pooled = _pool(a, b)
    assert _notes(pooled, NOTE_POOL_FOLDERS_MERGED, NOTE_POOL_SECRETS_MERGED) == []


def test_a_case_one_capture_read_as_given_and_another_under_a_folder_pools_with_a_note() -> None:
    # The first capture recorded nothing: its case was read as it is shown. A run always has a
    # key; a capture records it only once a name gets a mark.
    plain = synthetic_capture(
        _value,
        seed=1,
        capture_id="synthetic-a",
        cases=(dataclasses.replace(MATMUL, id=READ_NAME),),
    )
    cut = _capture("synthetic-b", 2, KEY, (READ,), folder="Zqb")
    pooled = _pool(plain, cut)
    assert [n.code for n in _notes(pooled, NOTE_POOL_FOLDERS_MERGED)] == [NOTE_POOL_FOLDERS_MERGED]


def test_marked_names_one_name_without_their_marks_each_on_other_sides_get_a_note() -> None:
    made = synthetic_capture(
        _value,
        seed=1,
        capture_id="synthetic-a",
        cases=tuple(dataclasses.replace(MATMUL, id=c) for c in ("matmul", FAST_NAME, "run x")),
    )
    names = CaseNames(KEY)
    for entry in ENTRIES[:2]:
        names.names([FAST.format(folder="Zqa")], entry, "made-up advice", side=entry)
    key_hex, recorded = names.take_new()
    # The new side read the case with a mark, the old side without one.
    kept = tuple(
        o
        for o in made.observations
        if not (o.case == FAST_NAME and o.name.startswith("old"))
        and not (o.case == "run x" and o.name.startswith("new"))
    )
    capture = dataclasses.replace(made, observations=kept, case_key=key_hex, case_names=recorded)
    notes = _notes(_pool(capture), NOTE_CASE_NAMED_APART)
    assert notes == [
        Note(
            code=NOTE_CASE_NAMED_APART,
            message=f"the cases 'run x', {FAST_NAME!r} are each read by other sides, and their "
            "names are one name without the mark ' +' and eight hex digits that a cut adds when "
            "it drops words that hold no '/'; if they are one case, the words a path in its id "
            "runs over differ between the sides, as a folder whose name holds a space makes "
            "them, and the sides are not compared on it",
        )
    ]


def test_check_pool_lists_names_whose_marks_clash_as_the_analysis_refuses_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pairbench

    def clash(key: bytes, tell: str) -> str:
        return CLASH

    monkeypatch.setattr(api, "case_suffix", clash)
    monkeypatch.setattr(analyse, "case_suffix", clash)
    a = _capture("synthetic-a", 1, KEY, (FAST,))
    b = _capture("synthetic-b", 2, OTHER_KEY, (SLOW,))
    raised = _refused(lambda: _pool(a, b))
    (found,) = pairbench.check_pool([a, b])
    assert (found.code, found.exit_code, found.message) == (
        raised.code,
        raised.exit_code,
        raised.message,
    )
