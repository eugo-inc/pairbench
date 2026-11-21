# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""How the positional parameters of a shell text are read where the text uses them.

``sh -c TEXT NAME ARG...`` hands each ``ARG`` to the commands of ``TEXT``
that use ``"$1"`` or ``"$@"``, and each argument is read where it is used:
the password after ``-a`` is hidden. These rows pin the parts of that
reading that no other row reaches: the file after a redirection that stands
alone is no word of the command, a parameter glued to more of its word is
hidden only when the word it makes hides more than it holds, of two readings
that show as many characters the first is kept, a command the text repeats is
read once, and each argument is read once for all the commands that use it.
Every value is made up.
"""

from __future__ import annotations

import collections
import shlex
from collections.abc import Callable, Iterator, Sequence

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
H = model.HIDDEN
PASSWORD = "zqmkiwi"
NAME = "made-up-name"
# The place of the first argument in ``run(TEXT, ARG)``.
FIRST = 4


def run(text: str, *args: str) -> tuple[str, ...]:
    """Return the argument list ``sh -c TEXT _ ARGS...``."""
    return ("sh", "-c", text, "_", *args)


def shown_last(args: tuple[str, ...]) -> str:
    """Return the last argument as the shown command gives it, checking the hash reads it so."""
    shown = shlex.split(model.public_command((*LEAD, *args)))[-1]
    assert model.hashed_argv(args)[-1] == shown
    return shown


# The text, with a password the client takes after a redirection that stands alone: the shell
# takes out the redirection and its file, so the password is the value of ``-a``.
BARE_REDIRECTIONS = (
    'redis-cli -a > out.txt "$1"',
    'redis-cli -a >> out.txt "$1"',
    'redis-cli -a < in.txt "$1"',
    'redis-cli -a 2> err.txt "$1"',
)


@pytest.mark.parametrize("text", BARE_REDIRECTIONS)
def test_the_file_after_a_redirection_that_stands_alone_is_no_word_of_the_command(
    text: str,
) -> None:
    assert shown_last(run(text, PASSWORD)) == H


def test_a_redirection_glued_to_its_file_is_no_word_of_the_command() -> None:
    assert shown_last(run('redis-cli -a >out.txt "$1"', PASSWORD)) == H


def test_an_argument_after_a_redirection_of_a_program_with_no_password_option_shows() -> None:
    assert shown_last(run('tool > out.txt "$1"', NAME)) == NAME


# The text, with a parameter glued to more of its word that is no secret: the word it makes
# hides nothing, so the argument shows.
GLUED_ORDINARY = (
    'tool --out=dir/"$1"',
    'tool -o"$1".json',
    'tool "$1".json',
    'tool x"$1"',
    'tool --label="$1"',
)


@pytest.mark.parametrize("text", GLUED_ORDINARY)
def test_a_glued_parameter_whose_word_hides_nothing_shows(text: str) -> None:
    assert shown_last(run(text, NAME)) == NAME


@pytest.mark.parametrize("text", ['redis-cli -a"$1"', 'tool --password="$1"'])
def test_a_glued_parameter_whose_word_hides_more_is_hidden(text: str) -> None:
    assert shown_last(run(text, PASSWORD)) == H


def tagging_reader(tags: dict[str, str]) -> Callable[..., list[str]]:
    """Return a reader that puts the tag of a command's option before each word after it.

    Tags of one length make readings of an argument that show as many
    characters; a longer tag makes a reading that shows more.
    """

    def read(walk: object, words: Sequence[str], text: object) -> list[str]:
        return [*words[:2], *(tags[words[1]] + word for word in words[2:])]

    return read


def test_of_two_uses_that_show_as_much_the_first_is_kept() -> None:
    words = run('tool -x "$1"; tool -y "$1"; tool -z "$1"', NAME)
    read = tagging_reader({"-x": "x:", "-y": "y:", "-z": "z:"})

    assert model._parameter_readings(words, read) == {FIRST: "x:" + NAME}


def test_of_two_uses_the_one_that_shows_less_is_kept() -> None:
    words = run('tool -x "$1"; tool -y "$1"', NAME)
    read = tagging_reader({"-x": "xx:", "-y": "y:"})

    assert model._parameter_readings(words, read) == {FIRST: "y:" + NAME}


def test_a_reading_that_shows_as_much_as_a_use_is_kept() -> None:
    words = run('tool -x "$1"', NAME)
    reading = [*words[:4], "w:" + NAME]
    read = tagging_reader({"-x": "x:"})

    assert model._with_parameters(words, reading, read) == reading


def test_a_use_that_shows_less_than_the_reading_is_taken() -> None:
    words = run('tool -x "$1"', NAME)
    reading = [*words[:4], "ww:" + NAME]
    read = tagging_reader({"-x": "x:"})

    assert model._with_parameters(words, reading, read) == [*words[:4], "x:" + NAME]


# Made-up file names; with the blank after each, a list of 100 takes 1800 characters.
NAMES = tuple(f"made-up-{number:05d}.txt" for number in range(100))
# The text repeats one command more often than the bound lets a list of NAMES be read.
REPEATS = model._PARAMETER_READ_SPARE // 1800 + 4


def test_a_command_the_text_repeats_is_read_once() -> None:
    args = run('tool "$@"; ' * REPEATS, *NAMES)

    assert model.hashed_argv(args)[-len(NAMES) :] == list(NAMES)
    assert model.public_command((*LEAD, *args)).endswith(" ".join(NAMES[-3:]))


def test_commands_that_differ_are_each_read_until_the_bound() -> None:
    text = "".join(f'tool -n {number} "$@"; ' for number in range(REPEATS))

    assert model.hashed_argv(run(text, *NAMES))[-len(NAMES) :] == [H] * len(NAMES)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[collections.Counter[tuple[str, str]]]:
    """Count the reads of each argument, by the reader of the shown command and of the hash."""
    calls: collections.Counter[tuple[str, str]] = collections.Counter()

    def counted(kind: str, reader: Callable[..., str]) -> Callable[..., str]:
        def read(arg: str, *rest: object, **kinds: object) -> str:
            calls[kind, arg] += 1
            return reader(arg, *rest, **kinds)

        return read

    monkeypatch.setattr(model, "_public_shown", counted("shown", model._public_shown))
    monkeypatch.setattr(model, "_hashed_argument", counted("hashed", model._hashed_argument))
    yield calls


def test_each_argument_is_read_once_for_all_the_commands_that_use_it(
    reads: collections.Counter[tuple[str, str]],
) -> None:
    text = 'redis-cli -n 1 "$@"; redis-cli -n 2 "$@"; redis-cli -n 3 "$@"'
    args = run(text, "made-up-a", "made-up-b")

    model.public_command((*LEAD, *args))
    model.hashed_argv(args)

    # Once as a word of the argument list, and once for the three commands that use it.
    assert {key: count for key, count in reads.items() if key[1].startswith("made-up-")} == {
        ("shown", "made-up-a"): 2,
        ("shown", "made-up-b"): 2,
        ("hashed", "made-up-a"): 2,
        ("hashed", "made-up-b"): 2,
    }
