# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A path written with ``%2F`` that ends at a home folder tells a case id apart as any such path.

The cut keeps ``%2F`` and the last part of such a path, and reads its folders as folders,
which may differ between sides and launches. While a case id is read the name of a home
folder is kept, so ``%2Fhome%2Fzq`` and ``%2Fsrv%2Fzq`` both leave ``%2Fzq``: two ids that
differ only there are refused in one read and get one name on two sides. Every folder, word
and key here is made up.
"""

from __future__ import annotations

import pytest

from pairbench.api import CaseNames
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import case_tell_words

# A made-up key of 32 bytes.
KEY = bytes(range(32))
WHERE = "side 'new'"
ADVICE = "give them other names"
# Two made-up ids whose paths written with '%2F' differ only in their folders, the first
# ending at a home folder.
HOME = "copy /made/up fast mode/x %2Fhome%2Fzq"
OTHER = "copy /made/up fast mode/x %2Fsrv%2Fzq"
# The words that tell each apart, and the one name KEY gives both.
TELL = ["copy", "fast", "%2Fzq"]
NAME = "copy x %2Fzq +f5fe9780"
REFUSED = (
    "side 'new': two different cases have the name 'copy x %2Fzq +f5fe9780' once absolute "
    "paths and paths that climb with '..' are cut and secrets hidden, as the results show it, "
    "and differ only in the folders of a path written with '%2F', or in those and words that "
    "hold a '/', once their secrets are hidden; pairbench reads such parts as folders, which "
    "may differ between sides and launches; give them other names"
)


def test_a_home_folder_of_a_percent_path_tells_an_id_apart_as_another_folder_does() -> None:
    assert case_tell_words(HOME) == TELL
    assert case_tell_words(OTHER) == TELL


def test_two_ids_that_differ_only_in_such_folders_are_refused_in_one_read() -> None:
    with pytest.raises(Refusal) as caught:
        CaseNames(KEY).names([HOME, OTHER], WHERE, ADVICE, "new")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert caught.value.message == REFUSED


def test_two_ids_that_differ_only_in_such_folders_get_one_name_on_two_sides() -> None:
    assert CaseNames(KEY).names([HOME], "side 'old'", ADVICE, "old") == {HOME: NAME}
    assert CaseNames(KEY).names([OTHER], WHERE, ADVICE, "new") == {OTHER: NAME}
