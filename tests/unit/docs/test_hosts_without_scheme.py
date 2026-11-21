# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a host or a user written without a scheme, as the cleaner shows it.

The known limits of the shown command name a host or a user that no scheme such as
``https://`` stands before. Each command the list gives is run through the cleaner and shows
exactly what the list says, and every command of the list is a row here, so neither the list nor
the rows can name a form the other does not. The advice after the list gives two ways to keep
such a host out of the shown command; each is run too.

The list also says what a case id keeps: a host and a user, which the case cleaner does not
hide, while the secret forms the shown command hides are hidden in it too. Each case id it gives
is a row here and is cleaned as a driver's case id is, and an id in rows given from outside is
read by the text reader and kept as written.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from pairbench import model
from pairbench.api import CaseNames
from pairbench.capture.text import TextReader
from pairbench.errors import EXIT_USAGE, Refusal

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = "**A host or a user written without a scheme.**"
# The parts of a command the list names that are no command: the scheme, the sign before a
# host and the program that takes one.
PARTS = ("https://", "@", "ssh")
# Each command the list gives that shows as typed.
TYPED = (
    "tool -h db.example",
    "tool -h 192.0.2.10",
    "tool -x db.example",
    "mysqlslap -h db.example",
    "tool --host db.example",
    "tool --host=db.example",
    "tool --user made-up-user",
    "tool -hdb.example",
    "tool db.example",
    "env DB_HOST=db.example tool",
    "psql 'host=db.example user=made-up-user dbname=x'",
    "tool db.example:8080/x",
    "tool user@db.example",
    "tool user:made-up@db.example",
    "ssh db.example ./bench",
    "ssh user@db.example ./bench",
    "sh -c 'tool -h db.example'",
)
# Each command the list gives that shows other than typed, and what it shows.
CHANGED = (("scp user@db.example:/made/up/x .", "scp user@db.example:x ."),)
# The advice after the list: a host in an address with a scheme, and a host given in a variable.
ADVICE = (
    ("tool --url https://db.example:8080/v1", "tool --url 'https://<hidden>:8080/v1'"),
    ("sh -c 'tool -h \"$DB_HOST\"'", "sh -c 'tool -h \"$DB_HOST\"'"),
)
ADVICE_LEAD = "Where a program takes an address, write a host you do not want shown"
# A made-up value the config reference's tests read as random-looking: as the password before
# the host of an address with no scheme, it is hidden as any such value is; the list says so in
# words.
RANDOM_KEY = "EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw"
RANDOM_PASSWORD = (f"tool user:{RANDOM_KEY}@db.example", "tool 'user:<hidden>@db.example'")
RANDOM_WORDS = "unless it is a long random-looking value"

CASE_LIMIT = "**A host or a user in a case id.**"
# The parts of the case item that are no case id: the program whose cases are named after their
# command, and its option that names one.
CASE_PARTS = ("hyperfine", "--command-name")
# Each case id a driver reads that the item says shows as the benchmark tool wrote it.
CASE_TYPED = (
    "test_get[https://db.example/x]",
    "BM_Connect/db.example:6379",
    "test_login[bench@db.example]",
    # A whole number after a ``/`` and a name glued to it with ``:``: a benchmark's named
    # argument.
    "BM_Hash/key:3",
    # A double colon, which gives no value.
    "query[Token::Kind]",
)
# A case id a driver reads that shows other than written, and what it shows: a path cut, the
# user part of an address hidden, and each secret form the shown command hides hidden.
CASE_CHANGED = (
    ("test_read[../../made/up/x.csv]", "test_read[x.csv]"),
    ("test_get[https://bench:made-up@db.example/x]", "test_get[https://<hidden>@db.example/x]"),
    ("query[PGPASSWORD=made-up]", "query[PGPASSWORD=<hidden>]"),
    ("query[--password=made-up]", "query[--password=<hidden>]"),
    ("query[bench:made-up@db.example]", "query[bench:<hidden>@db.example]"),
    # The same password with text after the host, as pytest joins two values with a dash.
    ("query[bench:made-up@db.example:5432-ro]", "query[bench:<hidden>@db.example:5432-ro]"),
    (f"query[{RANDOM_KEY}]", "query[<hidden>]"),
    # A credential-like name glued to its value with a colon, and the token after a scheme word.
    ("query[token:made-up]", "query[token:<hidden>]"),
    ("query[5432-password:made-up]", "query[5432-password:<hidden>]"),
    ('query[{"token":"made-up"}]', 'query[{"token":"<hidden>"}]'),
    ("query[--auth=Basic made-up]", "query[--auth=<hidden> <hidden>]"),
    # The words in a pair of brackets, read as the words of a command.
    ("bench[redis-cli -a made-up PING]", "bench[redis-cli -a <hidden> PING]"),
    ("query[--password made-up]", "query[--password <hidden>]"),
    (
        "bench[curl -H Authorization: Bearer made-up https://db.example/]",
        "bench[curl -H Authorization: <hidden>]",
    ),
    # A program's text in a pair of brackets, read as the shown command reads it.
    ("bench[python -c \"password = 'made-up'\"]", "bench[python -c \"password = '<hidden>'\"]"),
)
# A case id whose words stand outside its brackets, which are read only part by part, so it
# shows as written.
CASE_WORDS_OUTSIDE = ("bench[x]/run --token made-up",)
# The marks the item says end a value in a case id: a blank is no code span.
CASE_ENDS = ("/", ",", ";")
# The mark a password before a host ends at, which the item names twice: the hidden part runs
# up to the `@` before the host, and such a password holds no `@`.
CASE_HOST_MARKS = ("@", "@")
# A case named after its command, and the name it is given.
CASE_COMMANDS = (("curl https://db.example/x", "curl https://<hidden>/x"),)
# A case id in rows given from outside, kept as written.
CASE_OUTSIDE = ("t[/made/up/x.csv]",)
# Two ids of one launch that read the same once cut and hidden: refused when only a hidden
# secret tells them apart, and given two marks when, with their secrets hidden, they still
# differ in a word a path runs over that holds no `/`.
CASE_REFUSED = ("query[token:made-up]", "query[token:made-up-2]")
CASE_MARKED = ("query[/made/up/in.csv fast mode/x]", "query[/made/up/in.csv slow mode/x]")
# The name both cut to, and the made-up marks the item shows for them.
CASE_CUT = "query[x]"
CASE_MARKS = ("query[x] +3c5e7a91", "query[x] +b04d2f68")
# The names a made-up key of 32 bytes gives them.
KEY = bytes(range(32))
CASE_KEYED = ("query[x] +1fbff4fd", "query[x] +7edb000e")
# The marks the item names to say which words count: three times the `/` that words which
# keep two ids apart hold none of, twice more for a word that writes a `/` as `%2F` and holds
# none, and the `+` of a mark.
CASE_WORD_MARKS = ("/", "/", "/", "/", "/", "+")
# A word the item says writes a `/` as `%2F` and holds no `/`, and the `%2F` it names four
# times: in the folders of a path written with it that a refusal names, as the way the word
# writes a `/`, and twice for the cut of a path written with it from its start.
CASE_PERCENT_WORD = "4%2Fq"
CASE_PERCENT = ("%2F", "%2F", "%2F", "%2F")
# The marks that, right before '%2F', keep a word as typed rather than read as a path.
CASE_PERCENT_LEADS = ("_", "%", ".", "~", "-")
# The commands the item names for pooling captures and filling a document.
CASE_COMMAND_NAMES = ("pairbench compare", "pairbench fill")
# Where the naming rule says the ids came from, and the advice it gives.
CASE_WHERE = "side 'new'"
CASE_ADVICE = "give them other names"
CODE_SPAN = re.compile(r"`([^`]+)`")
# The guide's item on case ids, and what it says of the rest of a case id, with the link to the
# known limits.
GUIDE = "docs/guides/index.md"
GUIDE_ITEM = "- **Case ids.**"
GUIDE_WORDS = "Any other host, and a user written without a scheme, show in a case id"
# What the guide says is hidden in a case id besides its paths.
GUIDE_HIDDEN = "The secret forms the shown command hides are hidden in a case id too"
# The two things the guide says are hidden that the rest of a case id's host or user is not:
# the user part of an address after a scheme, and the host of a case named after its command;
# each is given with the case id it shows, as the security page gives it.
GUIDE_USER = ("the user part of an address after a scheme", CASE_CHANGED[1])
GUIDE_COMMAND = ("A case that `hyperfine` names after its command", CASE_COMMANDS[0])
LIMITS_LINK = "../../SECURITY.md#known-limits-of-the-shown-command"


def _limits(repo_root: Path) -> str:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    return text.split(LIMITS_HEADING, 1)[1].split("\n## ", 1)[0]


def _item(repo_root: Path, limit: str = LIMIT) -> str:
    """The list item of a limit, its lines joined."""
    items = re.split(r"\n(?=- )|\n\s*\n", _limits(repo_root))
    (item,) = [part for part in items if limit in part]
    return " ".join(item.split())


def _advice(repo_root: Path) -> str:
    """The paragraph after the list that gives the ways to keep such a host out."""
    paragraphs = re.split(r"\n\s*\n", _limits(repo_root))
    (paragraph,) = [part for part in paragraphs if ADVICE_LEAD in " ".join(part.split())]
    return " ".join(paragraph.split())


def _spans(text: str) -> list[str]:
    return CODE_SPAN.findall(text)


def test_the_list_names_a_host_or_a_user_written_without_a_scheme(repo_root: Path) -> None:
    item = _item(repo_root)

    assert item.startswith(f"- {LIMIT}")
    assert "shows as typed" in item
    assert RANDOM_WORDS in item


def test_a_long_random_looking_password_before_the_host_is_hidden() -> None:
    typed, shown = RANDOM_PASSWORD

    assert model.public_command(shlex.split(typed)) == shown


def test_the_list_gives_each_command_of_the_rows_and_no_other(repo_root: Path) -> None:
    rows = [*PARTS, *TYPED, *(typed for typed, _ in CHANGED), *(shown for _, shown in CHANGED)]

    assert sorted(_spans(_item(repo_root))) == sorted(rows)


def test_the_list_says_what_a_command_that_changes_shows(repo_root: Path) -> None:
    item = _item(repo_root)

    assert [typed for typed, shown in CHANGED if f"`{shown}`" not in item.split(typed, 1)[1]] == []


@pytest.mark.parametrize("typed", TYPED)
def test_each_host_or_user_the_list_names_shows_as_typed(typed: str) -> None:
    argv = shlex.split(typed)

    assert model.public_command(argv) == typed
    assert shlex.join(argv) == typed


@pytest.mark.parametrize(("typed", "shown"), CHANGED)
def test_a_host_and_a_path_show_the_host_and_the_last_part(typed: str, shown: str) -> None:
    assert model.public_command(shlex.split(typed)) == shown


def test_the_advice_gives_each_way_and_its_shown_command(repo_root: Path) -> None:
    advice = _advice(repo_root)

    # A command that shows as typed is given once.
    expected = ["launch.env_pass", *{text: None for pair in ADVICE for text in pair}]

    assert sorted(_spans(advice)) == sorted(expected)


@pytest.mark.parametrize(("typed", "shown"), ADVICE)
def test_each_way_the_advice_gives_shows_what_it_says(typed: str, shown: str) -> None:
    assert model.public_command(shlex.split(typed)) == shown


def test_the_list_names_a_host_or_a_user_in_a_case_id(repo_root: Path) -> None:
    item = _item(repo_root, CASE_LIMIT)

    assert item.startswith(f"- {CASE_LIMIT}")
    assert "show as the tool wrote them" in item
    assert "the secret forms the shown command hides hidden" in item
    assert "a long random-looking value" in item
    assert "are refused with `E_USAGE`" in item
    assert "shows as written, an absolute path and a secret included" in item


def test_the_case_item_gives_each_case_id_of_the_rows_and_no_other(repo_root: Path) -> None:
    rows = [
        *CASE_PARTS,
        *CASE_TYPED,
        *(text for pair in CASE_CHANGED for text in pair),
        *(text for pair in CASE_COMMANDS for text in pair),
        *CASE_OUTSIDE,
        *CASE_WORDS_OUTSIDE,
        *CASE_ENDS,
        *CASE_HOST_MARKS,
        *CASE_REFUSED,
        *CASE_MARKED,
        CASE_CUT,
        *CASE_MARKS,
        *CASE_WORD_MARKS,
        CASE_PERCENT_WORD,
        *CASE_PERCENT,
        *CASE_PERCENT_LEADS,
        *CASE_COMMAND_NAMES,
        "E_USAGE",
    ]

    assert sorted(_spans(_item(repo_root, CASE_LIMIT))) == sorted(rows)


def test_the_case_item_says_what_a_case_id_that_changes_shows(repo_root: Path) -> None:
    item = _item(repo_root, CASE_LIMIT)
    pairs = (*CASE_CHANGED, *CASE_COMMANDS)

    assert [given for given, shown in pairs if f"`{shown}`" not in item.split(given, 1)[1]] == []


@pytest.mark.parametrize("case", CASE_TYPED)
def test_each_host_or_user_in_a_case_id_shows_as_written(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize("case", CASE_WORDS_OUTSIDE)
def test_words_outside_the_brackets_of_a_case_id_show_as_written(case: str) -> None:
    assert model.public_case(case) == case


@pytest.mark.parametrize(("case", "shown"), CASE_CHANGED)
def test_a_case_id_the_item_says_changes_shows_what_it_says(case: str, shown: str) -> None:
    assert model.public_case(case) == shown


@pytest.mark.parametrize(("command", "shown"), CASE_COMMANDS)
def test_a_case_named_after_its_command_is_cleaned_as_the_command(command: str, shown: str) -> None:
    # The hyperfine driver names such a case by the command's words, and every case id read
    # from a driver goes through the case cleaner after that.
    assert model.public_case(model.public_words(command)) == shown


@pytest.mark.parametrize("case", CASE_OUTSIDE)
def test_a_case_id_in_rows_given_from_outside_is_kept_as_written(case: str, tmp_path: Path) -> None:
    rows = tmp_path / "rows.txt"
    rows.write_text(
        "## host\nunit=ns\nsides=new old\npass_order=new old\n"
        f"suite\tnew\t1\t{case}\t1500\nsuite\told\t1\t{case}\t1600\n",
        encoding="utf-8",
    )

    (capture,) = TextReader().read(rows)

    assert [found.id for found in capture.cases] == [case]


def test_two_ids_the_item_says_differ_only_in_a_hidden_secret_are_refused() -> None:
    with pytest.raises(Refusal) as caught:
        CaseNames(KEY).names(list(CASE_REFUSED), CASE_WHERE, CASE_ADVICE)

    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert "differ only in a hidden secret" in caught.value.message
    assert "made-up" not in caught.value.message


def test_two_ids_the_item_says_still_differ_in_a_word_get_two_marks() -> None:
    names = CaseNames(KEY).names(list(CASE_MARKED), CASE_WHERE, CASE_ADVICE)

    assert tuple(names[raw] for raw in CASE_MARKED) == CASE_KEYED
    for marked in (CASE_KEYED, CASE_MARKS):
        assert len(set(marked)) == 2
        assert [model.case_unsuffixed(name) for name in marked] == [CASE_CUT, CASE_CUT]
        assert [model.case_has_suffix(name) for name in marked] == [True, True]


def test_a_word_the_item_says_writes_a_slash_as_percent_tells_ids_apart() -> None:
    raw = f"run /made/up/a.py {CASE_PERCENT_WORD} data/x"

    assert model.case_folder_word(CASE_PERCENT_WORD) is False
    assert model.case_tell_words(raw) == ["run", CASE_PERCENT_WORD]


@pytest.mark.parametrize("lead", CASE_PERCENT_LEADS)
def test_each_mark_the_case_item_names_before_an_encoded_slash_keeps_the_word(lead: str) -> None:
    typed = f"copy {lead}%2Fmade%2Fin.bin"

    assert model.public_case_drops(typed) == (typed, False)
    assert model.public_case_drops("copy %2Fmade%2Fin.bin") == ("copy %2Fin.bin", False)


def test_the_guide_on_case_ids_says_what_else_shows_and_links_the_limits(repo_root: Path) -> None:
    text = (repo_root / GUIDE).read_text(encoding="utf-8")
    item = text.split(GUIDE_ITEM, 1)[1].split("\n- ", 1)[0]
    words = " ".join(item.split())

    assert GUIDE_WORDS in words
    assert GUIDE_HIDDEN in words
    assert f"]({LIMITS_LINK})" in words


@pytest.mark.parametrize(("words", "pair"), (GUIDE_USER, GUIDE_COMMAND))
def test_the_guide_on_case_ids_says_what_else_is_hidden(
    repo_root: Path, words: str, pair: tuple[str, str]
) -> None:
    text = (repo_root / GUIDE).read_text(encoding="utf-8")
    item = " ".join(text.split(GUIDE_ITEM, 1)[1].split("\n- ", 1)[0].split())
    given, shown = pair

    assert words in item
    assert f"`{shown}`" in item.split(words, 1)[1].split(f"`{given}`", 1)[1]
