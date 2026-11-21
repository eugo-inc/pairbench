# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An absolute path whose folder names hold spaces is cut whole, whatever the number of words.

A folder named in words, as a home folder named after a person or a folder of a
client often is, shows none of its words: as a word of a command, the value of
an option or of a name, a quoted word of a shell text, a free text, a case id
and the program of a side. A word that starts as an absolute path is a path to
its end; a quoted path is a path to its closing quote; in a free text a path
runs on over the words of a folder name to the last word that holds a ``/``.
The hashes keep every path as it was typed. Every folder name here is made up.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model
from pairbench.model import LaunchSettings

# The words of a made-up folder name, the first one to five of which name the folder.
WORDS = ("Zqfirst", "Zqsecond", "Zqthird", "Zqfourth", "Zqfifth")
# The last part of each path, which every form shows.
FILE = "out.txt"
# Where the folder named in words stands in the path.
PLACES = {
    "the first folder": "/{folder}/bench/data/" + FILE,
    "a middle folder": "/srv/bench/{folder}/data/" + FILE,
    "the last folder": "/srv/bench/data/{folder}/" + FILE,
}
# Commands that hold the path, each written with ``{p}`` where the path stands. The shown
# command is the same command with the last part of the path in its place.
FORMS = {
    "a word of a command": ("tool", "{p}", "-q"),
    "the value of an option": ("tool", "--in={p}", "-q"),
    "the value of a name": ("tool", "DATA={p}", "-q"),
    "a word in single quotes after sh -c": ("sh", "-c", "tool '{p}' -q"),
    "a word in double quotes after sh -c": ("sh", "-c", 'tool "{p}" -q'),
    "an option's value in single quotes after sh -c": ("sh", "-c", "tool --in='{p}' -q"),
    "an option's value in double quotes after sh -c": ("sh", "-c", 'tool --in="{p}" -q'),
    "a name's value in single quotes after sh -c": ("sh", "-c", "DATA='{p}' tool -q"),
    "a name's value in double quotes after sh -c": ("sh", "-c", 'DATA="{p}" tool -q'),
    "an option and its value in single quotes after sh -c": ("sh", "-c", "tool '--in={p}' -q"),
    "a name and its value in double quotes after sh -c": ("sh", "-c", 'tool "DATA={p}" -q'),
    "an unquoted word after sh -c": ("sh", "-c", "tool {p} -q"),
}
# Folder names that hold characters a path in a free text ends at: a word in brackets and a
# comma. A word of a command and a quoted word of a shell text still hide them whole.
MARKED_FOLDERS = ("Zqtools Files (x86)", "Zqmade Up, Zqinc")
MARKED_FORMS = tuple(form for form in FORMS if form != "an unquoted word after sh -c")


def _folder(count: int) -> str:
    return " ".join(WORDS[:count])


def _rows() -> list[tuple[str, str, str]]:
    return [
        (place, _folder(count), form)
        for place in PLACES
        for count in range(1, len(WORDS) + 1)
        for form in FORMS
    ]


def _shown(form: str, path: str) -> tuple[str | None, str]:
    """What the command of ``form`` that holds ``path`` shows, and what it should show."""
    typed = [word.format(p=path) for word in FORMS[form]]
    expected = shlex.join(word.format(p=FILE) for word in FORMS[form])
    return model.public_command(typed), expected


@pytest.mark.parametrize(("place", "folder", "form"), _rows())
def test_a_folder_named_in_words_shows_no_word_in_the_shown_command(
    place: str, folder: str, form: str
) -> None:
    path = PLACES[place].format(folder=folder)

    shown, expected = _shown(form, path)

    assert shown == expected
    assert not any(word in str(shown) for word in WORDS)


@pytest.mark.parametrize("folder", MARKED_FOLDERS)
@pytest.mark.parametrize("form", MARKED_FORMS)
@pytest.mark.parametrize("place", list(PLACES))
def test_a_folder_name_with_brackets_or_a_comma_is_cut_whole_in_a_word(
    place: str, form: str, folder: str
) -> None:
    path = PLACES[place].format(folder=folder)

    shown, expected = _shown(form, path)

    assert shown == expected
    assert "Zq" not in str(shown)


@pytest.mark.parametrize(("place", "folder"), [(p, _folder(n)) for p in PLACES for n in (1, 3, 5)])
def test_a_folder_named_in_words_is_cut_in_a_free_text_and_a_case_id(
    place: str, folder: str
) -> None:
    path = PLACES[place].format(folder=folder)

    assert model.public_text(path) == FILE
    assert model.public_text(f"open {path} now") == f"open {FILE} now"
    assert model.public_text(f"cannot read {path!r}: no such file") == (
        f"cannot read {FILE!r}: no such file"
    )
    assert model.public_text(f'cannot read "{path}"') == f'cannot read "{FILE}"'
    assert model.public_case(f"test_read[{path}]") == f"test_read[{FILE}]"
    assert model.public_case(f"test_read[{path}]-x") == f"test_read[{FILE}]-x"


# A made-up folder name that holds double quotes, each written with a backslash before it as
# it stands inside a path in double quotes, and a last part of one letter, which no other
# reading of the path keeps on its own.
ESCAPED_QUOTE_FOLDER = 'Zqfirst \\"Zqsecond\\" Zqthird'
LETTER = "x"


@pytest.mark.parametrize("place", list(PLACES))
def test_a_double_quoted_path_runs_past_an_escaped_quote_in_a_free_text_and_a_case_id(
    place: str,
) -> None:
    path = PLACES[place].format(folder=ESCAPED_QUOTE_FOLDER).removesuffix(FILE) + LETTER

    assert model.public_text(f'cannot read "{path}" now') == f'cannot read "{LETTER}" now'
    assert model.public_case(f'test_read["{path}"]') == f'test_read["{LETTER}"]'


def test_a_double_quote_left_open_in_a_free_text_quotes_no_path_past_its_line() -> None:
    text = 'cannot read "/srv/Zqfirst Zqsecond/out.txt and more\nthen /srv/bench/in.txt'

    assert model.public_text(text) == 'cannot read "out.txt and more\nthen in.txt'


@pytest.mark.parametrize(("place", "folder"), [(p, _folder(n)) for p in PLACES for n in (1, 3, 5)])
def test_a_shell_text_read_word_by_word_shows_no_word_of_the_folder(
    place: str, folder: str
) -> None:
    path = PLACES[place].format(folder=folder)
    # A shell splits an unquoted path at its blanks into words of their own, so only the
    # quoted forms hold the path as one word here.
    for form in MARKED_FORMS:
        if FORMS[form][0] != "sh":
            continue
        text = FORMS[form][2]

        shown = model.public_words(text.format(p=path))

        assert shown == " ".join(shlex.split(text.format(p=FILE))), form


# Where the folder named in words stands in a path glued to an option.
GLUED_PLACES = ("/{folder}/include", "/srv/{folder}/include")


@pytest.mark.parametrize("count", range(1, len(WORDS) + 1))
@pytest.mark.parametrize("place", GLUED_PLACES)
@pytest.mark.parametrize("option", ["-I", "-isystem", "-MF"])
def test_a_folder_named_in_words_is_cut_after_an_option_it_is_glued_to(
    option: str, place: str, count: int
) -> None:
    include = place.format(folder=_folder(count))
    shown = f"cc {option}include -c x.c"

    assert model.public_text(f"{option}{include}") == f"{option}include"
    assert model.public_text(f"cc {option}{include} -c x.c") == shown
    assert model.public_command(("cc", f"{option}{include}", "-c", "x.c")) == shown
    assert model.public_command(("sh", "-c", f"cc {option}{include} -c x.c")) == shlex.join(
        ["sh", "-c", shown]
    )
    assert model.public_command(("sh", "-c", f"cc '{option}{include}' -c x.c")) == shlex.join(
        ["sh", "-c", f"cc '{option}include' -c x.c"]
    )


# A Windows folder seen from Windows, with its drive letter, and from WSL.
WINDOWS_PATHS = {
    "after a drive letter": ("C:/Users/{folder}/bench/" + FILE, "C:" + FILE),
    "under the Windows users folder seen from WSL": ("/mnt/c/Users/{folder}/bench/" + FILE, FILE),
}


@pytest.mark.parametrize("count", range(1, len(WORDS) + 1))
@pytest.mark.parametrize("where", list(WINDOWS_PATHS))
@pytest.mark.parametrize("form", list(FORMS))
def test_a_windows_folder_named_in_words_shows_no_word(form: str, where: str, count: int) -> None:
    given, kept = WINDOWS_PATHS[where]
    typed = [word.format(p=given.format(folder=_folder(count))) for word in FORMS[form]]

    shown = model.public_command(typed)

    assert shown == shlex.join(word.format(p=kept) for word in FORMS[form])
    assert not any(word in str(shown) for word in WORDS)


# A path whose last part holds spaces shows that part whole, as the last part of any path.
LAST_PARTS = (
    ("/srv/bench/Zq Last Part", "Zq Last Part"),
    ("/srv/Zqfirst Zqsecond/Zq Last Part", "Zq Last Part"),
    ("/srv/Zqfirst Zqsecond Zqthird/", "Zqfirst Zqsecond Zqthird"),
)


@pytest.mark.parametrize(("path", "kept"), LAST_PARTS)
def test_a_last_part_with_spaces_is_shown_whole(path: str, kept: str) -> None:
    assert model.public_command(("tool", path)) == shlex.join(["tool", kept])
    assert model.public_command(("sh", "-c", f"tool '{path}'")) == shlex.join(
        ["sh", "-c", f"tool '{kept}'"]
    )
    assert model.public_text(repr(path)) == repr(kept)


@pytest.mark.parametrize("place", list(PLACES))
@pytest.mark.parametrize("count", range(1, len(WORDS) + 1))
def test_the_program_of_a_side_in_a_folder_named_in_words_is_held_by_its_last_part(
    place: str, count: int
) -> None:
    program = PLACES[place].format(folder=_folder(count)).replace(FILE, "made-up-tool")
    identity = {"executable": program, "executable_sha256": "e" * 64}
    launch = LaunchSettings().effective(args=["made-up-tool"])

    inputs = model.fingerprint_inputs(identity, launch)

    assert inputs["identity"] == {"executable": "made-up-tool", "executable_sha256": "e" * 64}
    assert model.fingerprint_inputs(inputs["identity"], inputs["launch"]) == inputs


@pytest.mark.parametrize("folder", MARKED_FOLDERS)
def test_the_program_of_a_side_in_a_folder_with_brackets_is_held_by_its_last_part(
    folder: str,
) -> None:
    identity = {"executable": f"/opt/{folder}/made-up-tool"}

    inputs = model.fingerprint_inputs(identity, LaunchSettings().effective(args=["x"]))

    assert inputs["identity"] == {"executable": "made-up-tool"}
    assert model.public_path(f"/opt/{folder}/made-up-tool") == "made-up-tool"


@pytest.mark.parametrize("place", list(PLACES))
def test_the_hashes_keep_the_path_as_typed(place: str) -> None:
    path = PLACES[place].format(folder=_folder(3))
    for form in FORMS:
        typed = [word.format(p=path) for word in FORMS[form]]

        assert model.hashed_argv(typed) == typed, form
