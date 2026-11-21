# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say what the shown command keeps of a ``file://`` address, as the code does.

The config page and the two reference pages on the recorded command say a
file address with a host and no path loses the host; the security policy
lists the forms of address and of names the cleaner does not read as meant.
Each example a page gives is run through the cleaner and shows what the page
says.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

PAGES = (
    "docs/reference/config.md",
    "docs/reference/results-schema.md",
    "docs/reference/text-format.md",
)
SECURITY = "SECURITY.md"
BARE_HOST = "A `file://` address with a host and no path loses the host"
LIMITS_HEADING = "## Known limits of the shown command"
LIMITS = (
    "**A host part no host name has.** A `file://` address whose host part holds a character "
    "no host name can hold, such as a comma or a colon with no port number after it, is not "
    "read as an address with a path, so its folders show as typed. The host ends at a comma and "
    "is hidden, and a host before such a colon shows too",
    "**Two addresses written together.** Two addresses with no space between them are read as "
    "one, so the host of the second can show",
    "**A password word glued to another word.** A password word glued to a word that is not "
    "one of the endings the config reference lists, such as `FILE`, `PATH` or `VALUE`, is read "
    "as one word with the word after it, so the name is not read as a credential and its value "
    "shows",
    "**A key glued to a word that begins like an ordinary word.** A name that starts with a key "
    "glued to a word that begins like one of the ordinary words the config reference lists, such "
    "as `KEYPAD` or `KEYMAP`, is read as that ordinary word, so its value shows",
    "**A key written with `/` and neither `+` nor padding.** A base64 value written so is read "
    "as a path when a part at either end of it reads as a word of a path, such as `ab` or `x9`, "
    "and that part shows",
    "Such a key that fails one of the tests the config reference gives for a random-looking "
    "value, as a few generated values do by chance, shows whole.",
    "So does such a key each part of which between two `/` reads as a name, as the config "
    "reference says a part of a path does, which a few generated values do by chance",
    "Inside a path, such a key, and one written with `+`, shows whole when what lies between the "
    "words of the path at its ends, read with up to two short words of a path beside it, is "
    "under 32 characters, as when a part at one of its ends reads as a word of three small "
    "letters or more, which a few generated values do by chance",
    "Such a key can also show whole in a path with a folder that is no word of a path and holds "
    "a capital, a digit or a `-`, such as `SRV`, `srv2`, `Data-X` or `Documents`, as some "
    "generated values do",
    "**A path written with `\\` or split at a blank.** A path written with `\\` between its "
    "folders is not read as a path, so its folders show as typed",
    "In the name of a command that hyperfine runs, a path with a blank in a folder name and no "
    "quotes around it is read as the shell splits it, as two words, so the parts of the folder "
    "name on both sides of the blank show",
    "**A Redis command a client reads from its input.** A command that a program writes to the "
    "input of `redis-cli` or `valkey-cli`, as in `echo 'AUTH password' | redis-cli`, is an "
    "argument of that program and is not read as a Redis command, so its password shows.",
    "Give an address a host name it can have, put a space between two addresses, and write a "
    "password word or a key apart from the word after it. Write a path with `/` and start it "
    "with `/` rather than a variable, and in a shell text put quotes around the whole of a path "
    "whose folder names hold a blank.",
    "Give a key to a side through `launch.env_pass` or a key file, and a Redis password with "
    "`-a` or `--pass`, or through `launch.env_pass`.",
)
# Each example the pages give: the address as typed, what the shown command holds of it, and
# the words of the page that say so.
EXAMPLES = (
    ("file://made-up-host", "file://<hidden>", "`file://made-up-host` shows `file://<hidden>`"),
    (
        "file://made-up-host:8000",
        "file://<hidden>:8000",
        "(`file://<hidden>`, `file://<hidden>:8000`)",
    ),
    ("file://m.gguf", "file://<hidden>", "(`file://m.gguf` shows `file://<hidden>`)"),
    (
        "file://made-up-host/a/m.gguf",
        "file://m.gguf",
        "`file://made-up-host/a/m.gguf` shows `file://m.gguf`",
    ),
    (
        "file://localhost/a/m.gguf",
        "file://m.gguf",
        "(`file://localhost/a/m.gguf` shows `file://m.gguf`)",
    ),
    (
        "file://made-up-host,file://other-host",
        "file://<hidden>,file://<hidden>",
        "`file://made-up-host,file://other-host` shows `file://<hidden>,file://<hidden>`",
    ),
    (
        "file://a,b/made/up/c",
        "file://<hidden>,b/made/up/c",
        "`file://a,b/made/up/c` shows `file://<hidden>,b/made/up/c`",
    ),
    (
        "file://h:x/made/up/y",
        "file://h:x/made/up/y",
        "`file://h:x/made/up/y` shows whole",
    ),
    (
        "file://a.binhttps://made-up.example",
        "file://made-up.example",
        "`file://a.binhttps://made-up.example` shows `file://made-up.example`",
    ),
    ("PASSNOTE=madeup", "PASSNOTE=madeup", "`PASSNOTE=madeup` shows whole"),
    ("PASS_NOTE=madeup", "PASS_NOTE=<hidden>", "`PASS_NOTE=madeup` shows `PASS_NOTE=<hidden>`"),
    ("KEYPADDING=madeup", "KEYPADDING=madeup", "`KEYPADDING=madeup` shows whole"),
    (
        "KEY_PADDING=madeup",
        "KEY_PADDING=<hidden>",
        "`KEY_PADDING=madeup` shows `KEY_PADDING=<hidden>`",
    ),
    (
        "ab/EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw",
        "ab/<hidden>",
        "`ab/EXAMPLE7qQ7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw` shows `ab/<hidden>`",
    ),
    (
        "EXAMPLE7KqpbnaOKWGQ9GRST/BjCwHeizXolJuj",
        "EXAMPLE7KqpbnaOKWGQ9GRST/BjCwHeizXolJuj",
        "`EXAMPLE7KqpbnaOKWGQ9GRST/BjCwHeizXolJuj` shows whole",
    ),
    (
        "data/EXAMPLETailFak/zQ9zQx9XyTAILRea/made9/out.json",
        "data/EXAMPLETailFak/zQ9zQx9XyTAILRea/made9/out.json",
        "`data/EXAMPLETailFak/zQ9zQx9XyTAILRea/made9/out.json` shows whole",
    ),
    (
        "SRV/NFS/EXAMPLETailFakezQ9/zQx9XyTAILRealUP/out.json",
        "SRV/NFS/EXAMPLETailFakezQ9/zQx9XyTAILRealUP/out.json",
        "`SRV/NFS/EXAMPLETailFakezQ9/zQx9XyTAILRealUP/out.json` shows whole",
    ),
    (
        "C:\\Users\\Zq Name\\x.txt",
        "C:\\Users\\Zq Name\\x.txt",
        "`C:\\Users\\Zq Name\\x.txt` shows whole",
    ),
    (
        "results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json",
        "results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json",
        "`results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json` shows whole",
    ),
)


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def page_text(repo_root: Path, page: str) -> str:
    return plain((repo_root / page).read_text(encoding="utf-8"))


@pytest.mark.parametrize("page", PAGES)
def test_each_page_on_the_shown_command_says_a_bare_file_host_is_hidden(
    repo_root: Path, page: str
) -> None:
    assert BARE_HOST in page_text(repo_root, page)


def test_the_security_policy_lists_the_forms_the_cleaner_does_not_read_as_meant(
    repo_root: Path,
) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = plain(text.split(f"\n{LIMITS_HEADING}\n", 1)[1].split("\n## ", 1)[0])

    assert [limit for limit in LIMITS if limit not in section] == []


@pytest.mark.parametrize(("typed", "shown", "words"), EXAMPLES)
def test_each_example_shows_what_the_pages_say(
    repo_root: Path, typed: str, shown: str, words: str
) -> None:
    pages = [page for page in (*PAGES, SECURITY) if words in page_text(repo_root, page)]

    assert pages != []
    assert model.public_command(("tool", typed)) == shlex.join(["tool", shown])


# The command name the security policy gives, as hyperfine names it, and what the results show.
SPLIT_AT_A_BLANK = ("tool /srv/Zq One/x.txt", "tool Zq One/x.txt")


def test_a_command_name_with_a_path_split_at_a_blank_shows_what_the_policy_says(
    repo_root: Path,
) -> None:
    typed, shown = SPLIT_AT_A_BLANK

    assert f"`{typed}` shows `{shown}`" in page_text(repo_root, SECURITY)
    assert model.public_words(typed) == shown
