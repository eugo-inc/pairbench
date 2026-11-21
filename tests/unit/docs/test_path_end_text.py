# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say where the shown command ends an absolute path, as the code does.

The config page says how far a path runs in a word of a command and in a
text of several words, the pytest-benchmark guide says the same of a case
id, and the security policy lists the forms of a path that are not read as
meant. Each example a page gives is run through the cleaner and shows what
the page says, and two case ids a page gives as cut alike get two marks from
the names of a run, and are refused without them.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import api, model
from pairbench.errors import Refusal

CONFIG_PAGE = "docs/reference/config.md"
GUIDE = "docs/guides/pytest-benchmark.md"
SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
# A made-up key of 32 bytes for the names of a run.
KEY = bytes(range(32))
PATH_END = (
    "**Where an absolute path ends.** An argument that starts as an absolute path is a path to "
    "its end, blanks included, so a folder named in words is cut with the rest",
    "In a text of several words, such as a shell text or a case id, a path runs on over the "
    "words after it that start with a letter, a digit or `_`, up to the last that holds a `/`, "
    "and the words it runs over are cut with it. A quote ends a path, and so does a word that "
    "starts with any other character",
    "When the cut of an id drops a word that holds no `/`, the name the results show is the cut "
    "id plus a mark: a space, `+` and eight hex digits",
    "The mark is the start of an HMAC-SHA256 keyed with a random key the run draws, taken over a "
    "hash of the words of the id that hold no `/`, read with its secrets hidden.",
    "Two ids that differ in such a word get two marks, and an id gets the same mark in every "
    "launch, on every side and in every twin of the run, whatever folder its path names and in "
    "whatever order the launches give the cases",
    "A cut that drops only words that hold a `/` adds no mark: `read /made/up/in.csv` shows "
    "`read in.csv`.",
    "no flag, environment variable, config key or file sets the key. The shared files hold "
    "neither the key nor any hash of an id.",
    "Pooled captures whose ids differ only in a folder or a secret are read as one case; if "
    "those folders are different inputs, keep the captures apart.",
    "Two that differ in a hidden secret and in a word that holds no `/` get two marks, and an id "
    "whose secret alone differs from one launch, side or twin to the next is read as the same "
    "case.",
    "An id whose cut already ends like a mark is refused, and so are two ids that a run's key "
    "gives the same mark.",
    "Give such cases names that differ before the path, or put the path in quotes",
    "each new run, and each new compare of result files, draws a new key, and a pool shows the "
    "marks of the first capture named.",
    "pool the captures with one `pairbench compare`, or fill from the results of the same capture.",
)
# The words of the config page on where an address ends a path in a text of several words, and
# the text, what a case id shows of it and what the shown command shows of it in a shell text.
ADDRESS_ENDS = (
    (
        "A word that holds `://` writes an address and ends a path too: "
        "`run /made/up/a.py fast unix:///made/up/s.sock` shows `run a.py fast unix:///s.sock`.",
        "run /made/up/a.py fast unix:///made/up/s.sock",
        "run a.py fast unix:///s.sock",
        "run a.py fast unix:///s.sock",
    ),
    (
        "A path in the query of an address runs on in the same way (the case id "
        "`get https://h.example/p?next=/made/up/Zq dir/d` shows "
        "`get https://h.example/p?next=/d`), and the address ends at the first blank that no "
        "such path runs over, so the words after it are read as any others.",
        "get https://h.example/p?next=/made/up/Zq dir/d",
        "get https://h.example/p?next=/d",
        "get https://<hidden>/p?next=/d",
    ),
)
# A case id whose cut drops only words that hold a `/`, and the name it keeps, with no mark.
FOLDER_ONLY = ("read /made/up/in.csv", "read in.csv")
# Two ids whose cut drops a word that writes its '/' as '%2F', the one name their cut ids share,
# the names KEY gives them, and the words of the config page: such a word holds no '/'.
ENCODED_WORDS = (
    ("run /made/up/a.py 4%2Fq data/x", "run /made/up/a.py 5%2Fq data/x"),
    "run x",
    ("run x +bf06410f", "run x +98b84fe5"),
    "A word that writes a `/` as `%2F` holds no `/`: `run /made/up/a.py 4%2Fq data/x` and "
    "`run /made/up/a.py 5%2Fq data/x` show as `run x` with two marks.",
)
# Ids whose path is written with '%2F' from its start, in an option's value and in an address,
# the names they keep, with no mark, and the words of the config page.
ENCODED_PATHS = (
    ("copy --in=%2Fmade%2Fup%2Fin.bin", "copy --in=%2Fin.bin"),
    ("get[?host=%2Fmade%2Fup%2Frun]", "get[?host=%2Frun]"),
)
ENCODED_PATH_WORDS = (
    "A path written with `%2F` from its start, with no letter, digit, `_`, `%`, `.`, `~` or `-` "
    "right before it, is cut to `%2F` and its last part wherever it stands, and its folders are "
    "read as folders, so they add no mark: `copy --in=%2Fmade%2Fup%2Fin.bin` shows "
    "`copy --in=%2Fin.bin`, and `get[?host=%2Fmade%2Fup%2Frun]` shows `get[?host=%2Frun]`."
)
# Words with a mark right before '%2F', which are no path written with it, and what they show.
ENCODED_NOT_PATHS = tuple(
    (f"copy {lead}%2Fmade%2Fin.bin", f"copy {lead}%2Fmade%2Fin.bin")
    for lead in ("a", "4", "_", "%25", ".", "~", "x-")
)
# The words of the security policy on the same two forms.
ENCODED_SECURITY = (
    "A word that writes a `/` as `%2F`, such as `4%2Fq`, holds no `/`, and a path written with "
    "`%2F` from its start, with no letter, digit, `_`, `%`, `.`, `~` or `-` right before it, is "
    "cut to `%2F` and its last part wherever it stands, its folders read as folders; a blank "
    "ends it, as the limit on a folder name with a blank in such a path says."
)
# A path written with '%2F' whose folder is named with a blank, what a case id and the shown
# command hold of it, the same path with '%20' for the blank, and the words of the pages.
ENCODED_BLANK = (
    "get[?host=%2Fmade%2FZq dir%2Frun]",
    "get[?host=%2FZq dir%2Frun]",
    "get[?host=%2Fmade%2FZq%20dir%2Frun]",
    "get[?host=%2Frun]",
)
ENCODED_BLANK_CONFIG = (
    "A blank ends such a path, so the words of a folder named with blanks show "
    "(`get[?host=%2Fmade%2FZq dir%2Frun]` shows `get[?host=%2FZq dir%2Frun]`) and two sides "
    "whose folders differ there are refused with `E_CASES_DIFFER`; written with `%20` for each "
    "blank, the folder is cut with the rest and the sides pair the case."
)
# The words of the exit-codes page on the same refusal: its cause and the way out.
EXIT_CODES_PAGE = "docs/reference/exit-codes.md"
ENCODED_BLANK_EXIT_CODES = (
    "A path written with `%2F` ends at a blank, so the words of a folder named with blanks in "
    "such a path show, and sides whose folders differ there name the case apart.",
    "In a path written with `%2F`, write each blank of a folder name as `%20`.",
)
# Two ids of one launch that differ only in the spaces in a path the cut drops, the name KEY
# gives them, and the words of the config page and of the security policy: they are refused.
SPACED = (
    ("copy /made/up/in.bin Zqfast  mode/x", "copy /made/up/in.bin Zqfast mode/x"),
    "copy x +f8e83fe4",
    (
        (
            CONFIG_PAGE,
            "and so are two that differ only in the spaces between the words a cut drops.",
        ),
        (SECURITY, "and when they differ only in the spaces between the words a cut drops."),
    ),
)
# The words of the tool-server page on a name given without its mark, for each tool that
# takes a case.
TOOL_SERVER = "docs/reference/tool-server.md"
TOOL_SERVER_ROWS = (
    "or the comparisons of one case; a name given without its mark gives those of every case "
    "that name shows with a mark |",
    "or of the comparisons of one case; a name given without its mark explains those of every "
    "case that name shows with a mark |",
)
# The notes the config page names for pooled ids that differ only in a folder or a secret.
POOL_NOTES = ("`pool_folders_merged`", "`pool_secrets_merged`")
# The words of the commands page on pooled ids read as one case: the parts the note on folders
# names, the folders of a path written with '%2F' among them.
COMMANDS_PAGE = "docs/reference/commands.md"
COMMANDS_POOL = (
    "Ids of the pooled captures that differ only in words that hold a `/` or in the folders of a "
    "path written with `%2F`, or only in a hidden secret, are read as one case"
)
# Two case ids that differ only in the words a path runs over, the one name their cut ids
# share, the words of the config page, and the names KEY gives them.
ALIKE_EXAMPLES = (
    (
        ("python3 /made/up/run.py fast data/x", "python3 /made/up/run.py slow data/x"),
        "python3 x",
        "`python3 /made/up/run.py fast data/x` and `python3 /made/up/run.py slow data/x` both "
        "read as `python3 x`",
        ("python3 x +a6fedace", "python3 x +cbddd074"),
    ),
    (
        ("copy /made/up/in.bin at 4 KiB/s", "copy /made/up/in.bin at 8 KiB/s"),
        "copy s",
        "`copy /made/up/in.bin at 4 KiB/s` and `copy /made/up/in.bin at 8 KiB/s` both read as "
        "`copy s`",
        ("copy s +013f0ae6", "copy s +39b7c6a4"),
    ),
)
# The made-up marks the config page shows for two such ids.
MARKED_WORDS = ("python3 x +3c5e7a91", "python3 x +b04d2f68")
# The guides that say what a run does with two case ids cut alike, two test ids the
# pytest-benchmark guide cuts alike, the names KEY gives them, and the made-up marks of the
# guides.
GUIDE_INDEX = "docs/guides/index.md"
GUIDE_ALIKE = (
    ("test_read[/made/up/in.csv fast mode/x]", "test_read[/made/up/in.csv slow mode/x]"),
    ("test_read[x] +1fbff4fd", "test_read[x] +7edb000e"),
    ("test_read[x] +3c5e7a91", "test_read[x] +b04d2f68"),
)
# Two test ids that differ only in their folders, the one name they share, and the words of
# the guides: in one launch the run cannot tell them apart, so they are refused.
GUIDE_FOLDERS = (
    ("test_read[/made/up/a/in.csv]", "test_read[/made/up/b/in.csv]"),
    "test_read[in.csv]",
    "Two ids of one launch that differ only in their folders, such as "
    "`test_read[/made/up/a/in.csv]` and `test_read[/made/up/b/in.csv]`, are refused with "
    "`E_USAGE`",
)
# The words of the guides on an id whose folders or secret alone differ between sides, and two
# such pairs of ids, each with the one name both sides give it.
GUIDE_ACROSS = (
    "An id whose folders or secret alone differ from one side or launch to the next names one "
    "case, and the run pairs it with itself.",
    (
        (("test_read[/made/up/a/in.csv]", "test_read[/made/up/b/in.csv]"), "test_read[in.csv]"),
        (("test_db[token:made-up]", "test_db[token:made-up-2]"), "test_db[token:<hidden>]"),
    ),
)
# Words the guides must not say: across sides such ids pair.
GUIDE_NEVER_PAIRED = "never paired"
# The words of the pytest-benchmark guide on the cut of one id: it shows with a mark.
GUIDE_CUT_MARK = (
    "test_read[/made/up/in.csv fast mode/x]",
    "test_read[x]",
    "(`test_read[/made/up/in.csv fast mode/x]` is cut to `test_read[x]` and shows with a mark, "
    "such as `test_read[x] +3c5e7a91`)",
)
# Two ids that differ only in a hidden secret, the one name their cut ids share, the name the
# refusal gives them, and the words of each page that say so: the run cannot tell them apart,
# so they are refused, never given two marks.
SECRET_ALIKE = (
    (
        GUIDE_INDEX,
        ("test_db[token:made-up]", "test_db[token:made-up-2]"),
        "test_db[token:<hidden>]",
        "test_db[token:<hidden>]",
        "and so are two that differ only in a hidden secret, such as `test_db[token:made-up]` and "
        "`test_db[token:made-up-2]`",
    ),
    (
        GUIDE,
        ("test_db[token:made-up]", "test_db[token:made-up-2]"),
        "test_db[token:<hidden>]",
        "test_db[token:<hidden>]",
        "and so are two that differ only in a hidden secret, such as `test_db[token:made-up]` and "
        "`test_db[token:made-up-2]`",
    ),
    (
        CONFIG_PAGE,
        (
            "python3 /made/up/run.py token=made-up data/x",
            "python3 /made/up/run.py token=made-up-2 data/x",
        ),
        "python3 x",
        "python3 x +e5f69dba",
        "Two ids of one launch that differ only in a hidden secret are refused with `E_USAGE`: "
        "`python3 /made/up/run.py token=made-up data/x` and "
        "`python3 /made/up/run.py token=made-up-2 data/x` read as one name once their path is cut "
        "and their secrets hidden",
    ),
    (
        SECURITY,
        ("query[token:made-up]", "query[token:made-up-2]"),
        "query[token:<hidden>]",
        "query[token:<hidden>]",
        "never pooled into one case, when they differ only in a hidden secret "
        "(`query[token:made-up]` and `query[token:made-up-2]`)",
    ),
)
# The words of the security policy on two ids cut alike, and the names KEY gives them.
SECURITY_ALIKE = (
    ("query[/made/up/in.csv fast mode/x]", "query[/made/up/in.csv slow mode/x]"),
    ("query[x] +1fbff4fd", "query[x] +7edb000e"),
    "`query[/made/up/in.csv fast mode/x]` and `query[/made/up/in.csv slow mode/x]` show as "
    "`query[x]` with two marks, such as `query[x] +3c5e7a91` and `query[x] +b04d2f68`",
)
# The words of the config page on a path in quotes in a case id, and what that id shows.
QUOTED_CASE = (
    'python3 "/made/up/run.py" fast data/x',
    'python3 "run.py" fast data/x',
    '`python3 "/made/up/run.py" fast data/x` shows `python3 "run.py" fast data/x`',
)
LIMITS = (
    "**A path quoted in part in a shell text.** In a shell text, a path in quotes is cut to its "
    "last part when the quotes are around the whole path. A word with quotes around only some "
    "of its folders is read as paths that end at each quote, so the folder names in quotes show",
    "**A path after a variable, or joined in code.** A path that starts with a variable, such as "
    "`$HOME/Zq Files/x.txt`, is not read as an absolute path, so its folders show as typed.",
    "Of a path that a program joins from parts, such as `Path('/srv') / 'Zq Files' / 'x.txt'`, "
    "each part after the first shows.",
    "**A folder name with a word that starts with a mark.** In a shell text, a case id or a free "
    "text, a path runs on over the blanks of a folder name to words that start with a letter, a "
    "digit or `_`. A folder name with a word that starts with a mark, such as `&`, `-`, `,`, `(` "
    "or `[`, or with a blank that is not a space or a tab, such as a no-break space, can end the "
    "path at that blank, and the rest of the name shows",
    "A word of a command that starts as an absolute path is cut whole.",
    "**A path after an option or a `<` in a case id.** A case id is read so that the `/` that "
    "joins the parts of a name is kept, so a path glued to an option or written after a `<` "
    "shows whole",
    "**A folder name with a blank in a path written with `%2F`.** A path that writes each `/` as "
    "`%2F` ends at a blank, so the words of a folder named with blanks show, in the shown command "
    "and in a case id: `get[?host=%2Fmade%2FZq dir%2Frun]` shows `get[?host=%2FZq dir%2Frun]`, "
    "and two sides whose folders differ there name the case apart, so the run is refused with "
    "`E_CASES_DIFFER`. Written with `%20` for each blank, as in "
    "`get[?host=%2Fmade%2FZq%20dir%2Frun]`, the folder is cut with the rest and shows "
    "`get[?host=%2Frun]`, so the sides pair the case.",
)
# A word of a command as typed, what the shown command holds of it, and the page that says so.
WORD_EXAMPLES = (
    (CONFIG_PAGE, "/srv/Zq One Two/x.txt", "x.txt", "(`/srv/Zq One Two/x.txt` shows `x.txt`)"),
    (SECURITY, "$HOME/Zq Files/x.txt", "$HOME/Zq Files/x.txt", "`$HOME/Zq Files/x.txt`"),
)
# The text of ``sh -c`` as typed, what the shown command holds of it, and the words of the page.
SHELL_EXAMPLES = (
    (
        CONFIG_PAGE,
        "python3 /made/up/bench.py run fast models/x.gguf",
        "python3 x.gguf",
        "`sh -c 'python3 /made/up/bench.py run fast models/x.gguf'` shows `sh -c 'python3 x.gguf'`",
    ),
    (
        CONFIG_PAGE,
        'python3 "/made/up/bench.py" run fast models/x.gguf',
        'python3 "bench.py" run fast models/x.gguf',
        "`sh -c 'python3 \"/made/up/bench.py\" run fast models/x.gguf'` shows "
        "`sh -c 'python3 \"bench.py\" run fast models/x.gguf'`",
    ),
    (
        SECURITY,
        "cat '/srv/Zq Files'/x.txt",
        "cat 'Zq Files'x.txt",
        "`cat '/srv/Zq Files'/x.txt` shows `cat 'Zq Files'x.txt`",
    ),
    (
        SECURITY,
        "cat /srv/'Zq Files'/x.txt",
        "cat srv'Zq Files'x.txt",
        "`cat /srv/'Zq Files'/x.txt` shows `cat srv'Zq Files'x.txt`",
    ),
)
# The words the reference page and the guides both give on a path that starts with a run of "/"
# after a mark, and on two "/" after ":" and after the other marks.
THREE_SLASHES = (
    "A path also starts at three `/` or more after one of `[`, `=`, `,`, `;`, `(`, `{`, `@` or a "
    "quote (`test_read[///made/up/in.bin]` shows `test_read[in.bin]`), and at two `/` or more "
    "after the `/` that ends a part of a name when two more parts follow "
    "(`BM_Read///made/up/in.bin` shows `BM_Read/in.bin`)."
)
AFTER_A_COLON = (
    "After `:` the `/` start an address (`file:///made/up/in.bin` shows `file://in.bin`), and two "
    "`/` after one of the other marks start the path at the second "
    "(`test_read[//made/up/in.bin]` shows `test_read[/in.bin]`)."
)
# A case id as a tool names it, what the results show of it, and the words of the page.
CASE_EXAMPLES = (
    (
        SECURITY,
        "test_read[/srv/Zq & Co/x.csv]",
        "test_read[Zq & Co/x.csv]",
        "`test_read[/srv/Zq & Co/x.csv]` shows `test_read[Zq & Co/x.csv]`",
    ),
    (
        SECURITY,
        "test_build[-I/srv/Zq/include]",
        "test_build[-I/srv/Zq/include]",
        "`test_build[-I/srv/Zq/include]` and `read </srv/Zq/x.txt` show as typed",
    ),
    (
        SECURITY,
        "read </srv/Zq/x.txt",
        "read </srv/Zq/x.txt",
        "`test_build[-I/srv/Zq/include]` and `read </srv/Zq/x.txt` show as typed",
    ),
    (
        CONFIG_PAGE,
        "run //made/up/in.bin",
        "run in.bin",
        "In a case id, a path that starts with two `/` or more at the start of the id or after a "
        "blank is cut like one that starts with a single `/` (`run //made/up/in.bin` shows "
        "`run in.bin`).",
    ),
    (
        GUIDE_INDEX,
        "run //made/up/in.bin",
        "run in.bin",
        "also with two `/` or more at the start of the id or after a space "
        "(`run //made/up/in.bin` shows `run in.bin`)",
    ),
    *(
        (page, case, shown, words)
        for page in (CONFIG_PAGE, GUIDE_INDEX)
        for case, shown, words in (
            ("test_read[///made/up/in.bin]", "test_read[in.bin]", THREE_SLASHES),
            ("BM_Read///made/up/in.bin", "BM_Read/in.bin", THREE_SLASHES),
            ("file:///made/up/in.bin", "file://in.bin", AFTER_A_COLON),
            ("test_read[//made/up/in.bin]", "test_read[/in.bin]", AFTER_A_COLON),
        )
    ),
)
# The code the security policy gives, and the parts of it the shown command holds.
JOINED_IN_CODE = ("Path('/srv') / 'Zq Files' / 'x.txt'", "Path('srv') / 'Zq Files' / 'x.txt'")


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def page_text(repo_root: Path, page: str) -> str:
    return plain((repo_root / page).read_text(encoding="utf-8"))


def limits_section(repo_root: Path) -> str:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    return plain(text.split(f"\n{LIMITS_HEADING}\n", 1)[1].split("\n## ", 1)[0])


def test_the_config_page_says_where_an_absolute_path_ends(repo_root: Path) -> None:
    text = page_text(repo_root, CONFIG_PAGE)

    assert [phrase for phrase in PATH_END if phrase not in text] == []


def test_the_security_policy_lists_the_forms_of_a_path_not_read_as_meant(
    repo_root: Path,
) -> None:
    section = limits_section(repo_root)

    assert [limit for limit in LIMITS if limit not in section] == []


@pytest.mark.parametrize(("page", "typed", "shown", "words"), WORD_EXAMPLES)
def test_each_word_of_a_command_shows_what_the_page_says(
    repo_root: Path, page: str, typed: str, shown: str, words: str
) -> None:
    assert words in page_text(repo_root, page)
    assert model.public_command(("tool", typed)) == shlex.join(["tool", shown])


@pytest.mark.parametrize(("page", "typed", "shown", "words"), SHELL_EXAMPLES)
def test_each_shell_text_shows_what_the_page_says(
    repo_root: Path, page: str, typed: str, shown: str, words: str
) -> None:
    assert words in page_text(repo_root, page)
    assert model.public_command(("sh", "-c", typed)) == shlex.join(["sh", "-c", shown])


@pytest.mark.parametrize(("page", "typed", "shown", "words"), CASE_EXAMPLES)
def test_each_case_id_shows_what_the_page_says(
    repo_root: Path, page: str, typed: str, shown: str, words: str
) -> None:
    assert words in page_text(repo_root, page)
    assert model.public_case(typed) == shown


@pytest.mark.parametrize(("words", "typed", "case", "shell"), ADDRESS_ENDS)
def test_an_address_ends_a_path_as_the_page_says(
    repo_root: Path, words: str, typed: str, case: str, shell: str
) -> None:
    assert words in page_text(repo_root, CONFIG_PAGE)
    assert model.public_case_drops(typed) == (case, False)
    assert model.public_command(("sh", "-c", typed)) == shlex.join(["sh", "-c", shell])


def test_the_parts_of_a_path_joined_in_code_show_after_the_first(repo_root: Path) -> None:
    typed, shown = JOINED_IN_CODE

    assert f"`{typed}`" in limits_section(repo_root)
    assert model.public_command(("python3", "-c", typed)) == shlex.join(["python3", "-c", shown])


def _sample(case: str) -> api.Sample:
    return api.Sample(case=case, metric="time", unit="s", better="lower", kind="time", value=1.5)


def _two_marks(names: tuple[str, ...], cut: str) -> None:
    """Two names that are the cut id plus two different marks."""
    assert len(set(names)) == 2
    assert [model.case_has_suffix(name) for name in names] == [True, True]
    assert [model.case_unsuffixed(name) for name in names] == [cut, cut]


@pytest.mark.parametrize(("ids", "shown", "words", "marked"), ALIKE_EXAMPLES)
def test_two_case_ids_the_page_shows_alike_get_two_marks(
    repo_root: Path, ids: tuple[str, str], shown: str, words: str, marked: tuple[str, str]
) -> None:
    text = page_text(repo_root, CONFIG_PAGE)
    assert words in text
    assert f"as in `{MARKED_WORDS[0]}` and `{MARKED_WORDS[1]}`" in text
    _two_marks(MARKED_WORDS, "python3 x")
    assert [model.public_case(raw) for raw in ids] == [shown, shown]
    samples = [_sample(raw) for raw in ids]
    named = api.public_cases(samples, "made-up-driver", api.CaseNames(KEY))
    assert tuple(s.case for s in named) == marked
    _two_marks(marked, shown)
    # Without the names of a run there is no key to make a mark with: they are refused.
    with pytest.raises(Refusal) as caught:
        api.public_cases(samples, "made-up-driver")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert f"the case read as {shown!r} drops words that hold no '/'" in caught.value.message
    assert "needs the mark a run makes with its own key" in caught.value.message


def test_a_cut_that_drops_only_folders_adds_no_mark(repo_root: Path) -> None:
    typed, shown = FOLDER_ONLY
    named = api.public_cases([_sample(typed)], "made-up-driver", api.CaseNames(KEY))

    assert f"`{typed}` shows `{shown}`" in page_text(repo_root, CONFIG_PAGE)
    assert [s.case for s in named] == [shown]


def test_a_word_with_an_encoded_slash_gets_a_mark_as_the_pages_say(repo_root: Path) -> None:
    ids, shown, marked, words = ENCODED_WORDS

    assert words in page_text(repo_root, CONFIG_PAGE)
    assert ENCODED_SECURITY in page_text(repo_root, SECURITY)
    assert [model.public_case(raw) for raw in ids] == [shown, shown]
    named = api.public_cases([_sample(raw) for raw in ids], "made-up-driver", api.CaseNames(KEY))
    assert tuple(s.case for s in named) == marked
    _two_marks(marked, shown)


# Two ids with a secret written as a path, one through a folder named with a blank: both show
# the same name, with no mark, as the config page says.
CREDENTIAL_FOLDERS = (
    ("test_db[token:/made/Zq dir/x.pem]", "test_db[token:/made/up/x.pem]"),
    "test_db[token:<hidden>]",
    "Nor does a folder named with a blank in a secret written as a path: "
    "`test_db[token:/made/Zq dir/x.pem]` and `test_db[token:/made/up/x.pem]` both show "
    "`test_db[token:<hidden>]`.",
)


def test_a_secret_path_through_a_folder_with_a_blank_adds_no_mark_as_the_page_says(
    repo_root: Path,
) -> None:
    ids, shown, words = CREDENTIAL_FOLDERS
    # Each id is named in a launch of its own, as each side's id is.
    named = [api.public_cases([_sample(raw)], "made-up-driver", api.CaseNames(KEY)) for raw in ids]

    assert words in page_text(repo_root, CONFIG_PAGE)
    assert [[s.case for s in launch] for launch in named] == [[shown], [shown]]
    assert [model.public_case_drops(raw) for raw in ids] == [(shown, False), (shown, False)]


@pytest.mark.parametrize(("typed", "shown"), ENCODED_PATHS)
def test_a_path_written_with_encoded_slashes_adds_no_mark_as_the_page_says(
    repo_root: Path, typed: str, shown: str
) -> None:
    named = api.public_cases([_sample(typed)], "made-up-driver", api.CaseNames(KEY))

    assert ENCODED_PATH_WORDS in page_text(repo_root, CONFIG_PAGE)
    assert f"`{typed}` shows `{shown}`" in ENCODED_PATH_WORDS
    assert [s.case for s in named] == [shown]
    assert model.public_case_drops(typed) == (shown, False)


@pytest.mark.parametrize(("typed", "shown"), ENCODED_NOT_PATHS)
def test_a_mark_right_before_an_encoded_slash_keeps_the_word_as_typed(
    typed: str, shown: str
) -> None:
    assert model.public_case_drops(typed) == (shown, False)


def test_a_blank_ends_a_path_written_with_encoded_slashes_as_the_pages_say(
    repo_root: Path,
) -> None:
    spaced, spaced_shown, escaped, escaped_shown = ENCODED_BLANK

    assert ENCODED_BLANK_CONFIG in page_text(repo_root, CONFIG_PAGE)
    assert model.public_case_drops(spaced) == (spaced_shown, False)
    assert model.public_case_drops(escaped) == (escaped_shown, False)
    assert model.public_command(("tool", spaced)) == shlex.join(["tool", spaced_shown])
    assert model.public_command(("tool", escaped)) == shlex.join(["tool", escaped_shown])


@pytest.mark.parametrize("words", ENCODED_BLANK_EXIT_CODES)
def test_the_exit_codes_page_says_a_blank_in_an_encoded_folder_names_the_case_apart(
    repo_root: Path, words: str
) -> None:
    assert words in page_text(repo_root, EXIT_CODES_PAGE)


@pytest.mark.parametrize(("page", "words"), SPACED[2])
def test_two_ids_that_differ_only_in_spaces_a_cut_drops_are_refused_as_the_pages_say(
    repo_root: Path, page: str, words: str
) -> None:
    ids, shown, _ = SPACED

    assert words in page_text(repo_root, page)
    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "made-up-driver", api.CaseNames(KEY))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert f"the name {shown!r}" in caught.value.message
    assert "differ only in the spaces between their words" in caught.value.message


def test_the_tool_server_page_says_a_name_without_its_mark_gives_every_case_of_it(
    repo_root: Path,
) -> None:
    text = page_text(repo_root, TOOL_SERVER)

    assert [row for row in TOOL_SERVER_ROWS if row not in text] == []


def test_the_config_page_names_the_notes_of_a_pool_as_the_code_does(repo_root: Path) -> None:
    codes = (model.NOTE_POOL_FOLDERS_MERGED, model.NOTE_POOL_SECRETS_MERGED)

    assert tuple(f"`{code}`" for code in codes) == POOL_NOTES
    text = page_text(repo_root, CONFIG_PAGE)
    assert [note for note in POOL_NOTES if note not in text] == []


def test_the_commands_page_says_which_pooled_ids_are_one_case_as_the_note_does(
    repo_root: Path,
) -> None:
    assert COMMANDS_POOL in page_text(repo_root, COMMANDS_PAGE)


@pytest.mark.parametrize("page", [GUIDE, GUIDE_INDEX])
def test_the_guides_say_two_ids_cut_alike_get_two_marks(repo_root: Path, page: str) -> None:
    ids, marked, words = GUIDE_ALIKE
    folder_ids, shared, folder_words = GUIDE_FOLDERS
    text = page_text(repo_root, page)

    assert f"`{words[0]}` and `{words[1]}`" in text
    _two_marks(words, "test_read[x]")
    named = api.public_cases([_sample(raw) for raw in ids], "made-up-driver", api.CaseNames(KEY))
    assert tuple(s.case for s in named) == marked
    assert folder_words in text
    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in folder_ids], "made-up-driver", api.CaseNames(KEY))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert f"the name {shared!r}" in caught.value.message
    assert "differ only in words that hold a '/'" in caught.value.message


@pytest.mark.parametrize("page", [GUIDE, GUIDE_INDEX])
def test_the_guides_say_an_id_whose_folders_or_secret_differ_between_sides_pairs(
    repo_root: Path, page: str
) -> None:
    words, pairs = GUIDE_ACROSS
    text = page_text(repo_root, page)

    assert words in text
    assert GUIDE_NEVER_PAIRED not in text
    for (new, old), shown in pairs:
        names = api.CaseNames(KEY)
        given = (
            names.names([new], "side 'new'", "made-up advice", "new")[new],
            names.names([old], "side 'old'", "made-up advice", "old")[old],
        )
        assert given == (shown, shown)


def test_the_pytest_guide_shows_the_mark_of_the_id_it_cuts(repo_root: Path) -> None:
    typed, cut, words = GUIDE_CUT_MARK
    (named,) = api.public_cases([_sample(typed)], "made-up-driver", api.CaseNames(KEY))

    assert words in page_text(repo_root, GUIDE)
    assert model.public_case(typed) == cut
    assert model.case_has_suffix(named.case)
    assert model.case_unsuffixed(named.case) == cut


@pytest.mark.parametrize(("page", "ids", "shown", "named", "words"), SECRET_ALIKE)
def test_each_page_says_two_ids_that_differ_only_in_a_secret_are_refused(
    repo_root: Path, page: str, ids: tuple[str, str], shown: str, named: str, words: str
) -> None:
    assert words in page_text(repo_root, page)
    assert [model.public_case(raw) for raw in ids] == [shown, shown]
    with pytest.raises(Refusal) as caught:
        api.public_cases([_sample(raw) for raw in ids], "made-up-driver", api.CaseNames(KEY))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert f"the name {named!r}" in caught.value.message
    assert "differ only in a hidden secret" in caught.value.message
    assert all(raw not in caught.value.message for raw in ids)


def test_the_security_policy_says_two_ids_cut_alike_get_two_marks(repo_root: Path) -> None:
    ids, marked, words = SECURITY_ALIKE
    assert words in page_text(repo_root, SECURITY)
    named = api.public_cases([_sample(raw) for raw in ids], "made-up-driver", api.CaseNames(KEY))
    assert tuple(s.case for s in named) == marked
    _two_marks(marked, "query[x]")


def test_a_path_in_quotes_keeps_the_words_after_it_as_the_page_says(repo_root: Path) -> None:
    typed, shown, words = QUOTED_CASE

    assert words in page_text(repo_root, CONFIG_PAGE)
    assert model.public_case(typed) == shown
