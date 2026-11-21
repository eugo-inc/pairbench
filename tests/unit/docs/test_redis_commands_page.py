# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages list the Redis and Valkey command passwords the code hides, as the code hides them.

Every row of the config page's table of Redis and Valkey commands is what the code shows,
as an argument list and inside ``sh -c``, as written, in lower case and in mixed case, which
the page says. The page names the variants of ``HELLO``, ``MIGRATE`` and ``ACL SETUSER`` the
code hides, the rule characters of ``ACL SETUSER`` are the code's, and so is the count of the
fixed arguments of ``MIGRATE``. The results page names each command of the table among the
forms it hides. Every value is made up.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
RESULTS_PAGE = "docs/reference/results-schema.md"
HEADING = "### Passwords in the commands of Redis and Valkey"
ANCHOR = "config.md#passwords-in-the-commands-of-redis-and-valkey"
LEAD = ("pairbench", "run", "--")
CLIENT = "redis-cli"
# Two made-up passwords, and a made-up hash built at run time.
PASSWORDS = ("zqm-made-up-one", "zqm-made-up-two")
HASH = "c0de" * 16
# What the page says of the case of a command.
ANY_CASE = (
    "A command and its words are read in any case: `auth user password`, `Auth user password` "
    "and `AUTH user password` each show the user and hide the password, and so does every row "
    "below written in lower case (`config set requirepass <hidden>`)."
)
# The variants the page names, each a row of its table.
VARIANTS = (
    "HELLO 3 SETNAME name AUTH user password",
    "MIGRATE host port key db timeout COPY REPLACE AUTH password",
    "MIGRATE host port '' db timeout AUTH password KEYS key key",
    "ACL SETUSER user reset on >password >password ~* +@all",
)
VARIANTS_TEXT = (
    "`AUTH` of `HELLO` is read wherever it stands after `HELLO`, before or after `SETNAME`. "
    "`AUTH` and `AUTH2` of `MIGRATE` are read after its {count} fixed arguments, after `COPY` "
    "and `REPLACE` too, and the words after the password are shown (`KEYS key key`). "
    "`ACL SETUSER` hides every rule that gives a password or its hash, however many it has. "
    "A password may hold blanks, so all of an argument after its first rule that gives one is "
    "hidden, blanks included: `'>made up'` and `'> made up'` show `'><hidden>'`, and the rules "
    "before it in the same argument are shown."
)
NUMBER_WORDS = {4: "four", 5: "five", 6: "six"}
# The examples of a word after the password of `AUTH` that the client passes on as the
# password: (the command as typed, as shown).
READ_APART = (
    ("redis-cli AUTH VALUE --raw", "redis-cli AUTH <hidden> --raw"),
    ("redis-cli AUTH VALUE '#' log in", "redis-cli AUTH <hidden> <hidden> log in"),
)
# The words that end the fixed arguments of MIGRATE in a row of the table.
MIGRATE_OPTIONS = ("COPY", "REPLACE", "AUTH", "AUTH2")
CASES: dict[str, Callable[[str], str]] = {
    "as written": str,
    "lower case": str.lower,
    "mixed case": str.title,
}


def section(repo_root: Path) -> str:
    """The text of the section, up to the next heading of its level or above."""
    text = (repo_root / CONFIG_PAGE).read_text(encoding="utf-8")
    start = text.index(f"\n{HEADING}\n")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def rows(repo_root: Path) -> list[tuple[list[str], str]]:
    """Each row of the table: the forms of its first cell, and its second cell."""
    found = []
    for line in section(repo_root).splitlines():
        if not line.startswith("| `"):
            continue
        typed, shown = line.strip().strip("|").split(" | ")
        found.append((re.findall(r"`([^`]+)`", typed), shown.strip().strip("`")))
    return found


def forms(cell: list[str]) -> list[str]:
    """The whole commands of a first cell: a rule alone stands for the last word of the first."""
    whole = []
    for form in cell:
        if form[0] in model._ACL_PASSWORD_RULES and " " not in form:
            head, _, _ = whole[0].rpartition(" ")
            whole.append(f"{head} {form}")
        else:
            whole.append(form)
    return whole


def cased(form: str, case: Callable[[str], str]) -> str:
    """The form with its command words, the words in capitals, in the given case."""
    return re.sub(r"\b[A-Z][A-Z0-9]*\b", lambda word: case(word.group()), form)


def typed(form: str, password: str) -> str:
    return re.sub(r"\bhash\b", HASH, re.sub(r"\bpassword\b", password, form))


def hidden(form: str) -> str:
    """The form as shown: a rule that gives a password hides the rest of its quoted argument."""
    rules = re.escape("".join(model._ACL_PASSWORD_RULES))
    form = re.sub(rf"([{rules}])(?:password|hash)\b[^']*'", rf"\1{model.HIDDEN}'", form)
    return re.sub(r"\b(?:password|hash)\b", model.HIDDEN, form)


def commands(cell: list[str]) -> str:
    """The command a row names: its leading words in capitals (``CONFIG SET``)."""
    words = []
    for word in cell[0].split():
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", word):
            break
        words.append(word)
    return " ".join(words)


def test_the_section_says_commands_are_read_in_any_case(repo_root: Path) -> None:
    assert ANY_CASE in plain(section(repo_root))


def test_the_section_names_the_variants_of_hello_migrate_and_acl(repo_root: Path) -> None:
    text = plain(section(repo_root))
    listed = [form for cell, _ in rows(repo_root) for form in forms(cell)]

    assert [form for form in VARIANTS if form not in listed] == []
    assert VARIANTS_TEXT.format(count=NUMBER_WORDS[model._MIGRATE_ARGUMENTS]) in text


def test_the_rule_characters_of_acl_setuser_are_the_codes(repo_root: Path) -> None:
    (acl,) = [cell for cell, _ in rows(repo_root) if cell[0].startswith("ACL SETUSER user on >")]

    assert tuple(form.rpartition(" ")[2][0] for form in forms(acl)) == model._ACL_PASSWORD_RULES


def test_each_migrate_row_has_the_codes_count_of_fixed_arguments(repo_root: Path) -> None:
    migrate = [form for cell, _ in rows(repo_root) for form in cell if form.startswith("MIGRATE")]
    counts = set()
    for form in migrate:
        words = form.split()[1:]
        counts.add(next(at for at, word in enumerate(words) if word in MIGRATE_OPTIONS))

    assert len(migrate) == 4
    assert counts == {model._MIGRATE_ARGUMENTS}


@pytest.mark.parametrize("case", list(CASES))
def test_each_row_of_the_table_is_what_the_code_shows(repo_root: Path, case: str) -> None:
    table = rows(repo_root)
    assert len(table) >= 16
    for cell, shown in table:
        assert hidden(cell[0]) == shown
        for form in forms(cell):
            form_cased = cased(form, CASES[case])
            expected = [CLIENT, *shlex.split(hidden(form_cased))]
            hashes = []
            for password in PASSWORDS:
                text = f"{CLIENT} {typed(form_cased, password)}"
                argv = (CLIENT, *shlex.split(typed(form_cased, password)))
                in_argv = model.public_command((*LEAD, *argv))
                in_shell = model.public_command((*LEAD, "sh", "-c", text))
                assert in_argv is not None
                assert in_shell is not None
                assert shlex.split(in_argv)[len(LEAD) :] == expected, form_cased
                assert shlex.split(shlex.split(in_shell)[-1]) == expected, form_cased
                hashes.append(model.hashed_argv(argv))
            assert hashes[0] == hashes[1], form_cased
            assert not any(PASSWORDS[0] in word or HASH in word for word in hashes[0])


def test_the_examples_of_a_word_passed_on_as_the_password_are_what_the_code_shows(
    repo_root: Path,
) -> None:
    text = plain((repo_root / CONFIG_PAGE).read_text(encoding="utf-8"))

    assert " and ".join(f"`{typed}` shows `{shown}`" for typed, shown in READ_APART) in text
    for typed_text, shown in READ_APART:
        in_shell = model.public_command((*LEAD, "sh", "-c", typed_text))
        assert in_shell is not None
        assert shlex.split(in_shell)[-1] == shown
        assert model.public_words(typed_text) == shown


def test_the_results_page_names_each_command_of_the_table(repo_root: Path) -> None:
    text = plain((repo_root / RESULTS_PAGE).read_text(encoding="utf-8"))
    named = sorted({commands(cell) for cell, _ in rows(repo_root)} - {""})
    listed = ", ".join(f"`{command}`" for command in named)

    assert named == [
        "ACL SETUSER",
        "AUTH",
        "CONFIG SET",
        "HELLO",
        "MIGRATE",
        "SENTINEL CONFIG SET",
        "SENTINEL SET",
    ]
    assert (
        f"the passwords in the [commands of Redis and Valkey clients]({ANCHOR}) ({listed})"
    ) in text
