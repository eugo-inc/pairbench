# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A text in double quotes that a shell reads is read with its escapes taken out.

A shell takes ``\\"`` and ``\\\\`` out of a word in double quotes before it passes the
word on. When that word is the text after ``-c`` of a shell or the remote command of
``ssh``, the next shell reads the text without them: an escaped blank or an escaped
quote joins a credential option and its value into one word, and an operator between
escaped quotes is part of the value it stands in. The shown command and the hash read
the text the same way, so no part of the value shows, two values give one hash, and
each level of the shown command splits into as many words as the typed one.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterator

import pytest

from pairbench.model import hashed_argv, public_command, public_words

# Two made-up values of one credential: a side that differs only in it is the same side.
VALUE = "made-up-secret-1"
OTHER_VALUE = "made-up-secret-2"

# Commands of three quoting layers or more, with ``{value}`` where the value stands, and the
# shown command, which is also what the hash is taken over.
LAYERED: dict[str, tuple[tuple[str, ...], str]] = {
    "an escaped blank in a shell text in double quotes": (
        ("sh", "-c", 'sh -c "./bench-old --token\\\\ {value}"'),
        """sh -c 'sh -c "./bench-old '"'"'--token <hidden>'"'"'"'""",
    ),
    "escaped quotes in the remote command in a shell text in double quotes": (
        ("sh", "-c", 'sh -c "ssh made-up-host \'./bench-old --token\\" {value}\\"\'"'),
        """sh -c 'sh -c "ssh made-up-host '"'"'./bench-old \\"--token <hidden>\\"'"'"'"'""",
    ),
    "escaped quotes in a remote command in double quotes in a shell text": (
        ("sh", "-c", 'sh -c \'ssh made-up-host "./bench-old --token\\" {value}\\""\''),
        """sh -c 'sh -c '"'"'ssh made-up-host "./bench-old --token\\\\ <hidden>"'"'"''""",
    ),
    # The next shell gets ``--name\ a"b\ --token\ VALUE``: the quote it opens is not closed,
    # so the words before it are kept and only the value is hidden.
    "an escaped quote before the option in a remote command in double quotes": (
        ("sh", "-c", 'sh -c \'ssh made-up-host "./bench-old --name\\ a\\"b\\ --token\\ {value}"\''),
        """sh -c 'sh -c '"'"'ssh made-up-host "./bench-old --name\\\\ a\\"b\\\\"""
        """ --token\\\\ <hidden>"'"'"''""",
    ),
    "escaped quotes in a remote command in double quotes": (
        ("sh", "-c", 'ssh made-up-host "./bench-old --token\\" {value}\\""'),
        """sh -c 'ssh made-up-host "./bench-old '"'"'--token <hidden>'"'"'"'""",
    ),
    "an operator between escaped quotes in a client password": (
        ("sh", "-c", 'sh -c "mysql -p\\"made;{value}\\" db"'),
        """sh -c 'sh -c '"'"'mysql -p<hidden> db'"'"''""",
    ),
    "an operator between escaped quotes after a credential option": (
        ("sh", "-c", 'sh -c "./bench-old --api-key \\"made|{value}\\""'),
        """sh -c 'sh -c '"'"'./bench-old --api-key <hidden>'"'"''""",
    ),
}

# Commands whose value runs to the end of the text after ``-c``: the operator stands between
# escaped quotes, so it is part of the value the next shell gets. The value is hidden with all
# that follows it, as a value with no operator in it is. The double quote that opened the text
# after the first ``-c`` is given back, so that text splits as typed; the escaped quotes inside
# it are not.
TO_THE_END: dict[str, tuple[tuple[str, ...], str]] = {
    "an operator between escaped quotes in a setting": (
        ("sh", "-c", 'sh -c "./bench-old --config \\"password=made;{value}\\""'),
        """sh -c 'sh -c "./bench-old --config \\"password=<hidden>"'""",
    ),
    "an operator between escaped quotes in a credential option": (
        ("sh", "-c", 'sh -c "./bench-old \\"--token=made&&{value}\\""'),
        """sh -c 'sh -c "./bench-old \\"--token=<hidden>"'""",
    ),
}
# Commands whose text in double quotes holds a backslash before a line break. The shell takes
# both out of a word in double quotes, and out of a word outside quotes, so the two lines are
# one word for the next shell: the line break ends no command there and the value runs on.
JOINED: dict[str, tuple[tuple[str, ...], str]] = {
    "a line break after a backslash in a shell text in double quotes": (
        ("sh", "-c", 'sh -c "./bench-old --token made\\\n{value}"'),
        """sh -c 'sh -c '"'"'./bench-old --token <hidden>'"'"''""",
    ),
    "a line break after a backslash in a quoted part of a shell text": (
        ("sh", "-c", './bench-old --token" made\\\n{value}"'),
        """sh -c './bench-old '"'"'--token <hidden>'"'"''""",
    ),
    "a line break after a backslash outside quotes in a word with a quoted part": (
        ("sh", "-c", "./bench-old --token' 'made\\\n{value}"),
        """sh -c './bench-old '"'"'--token <hidden>'"'"''""",
    ),
    "a line break after a backslash in the remote command of ssh": (
        ("ssh", "made-up-host", 'sh -c "./bench-old --token made\\\n{value}"'),
        """ssh made-up-host 'sh -c '"'"'./bench-old --token <hidden>'"'"''""",
    ),
    "two line breaks after backslashes in a client password": (
        ("sh", "-c", 'sh -c "mysql --password made\\\nup\\\n{value} db"'),
        """sh -c 'sh -c '"'"'mysql --password <hidden> db'"'"''""",
    ),
    "a line break after a backslash before an operator": (
        ("sh", "-c", 'sh -c "./bench-old --token made\\\n{value}; ./run"'),
        """sh -c 'sh -c '"'"'./bench-old --token <hidden>; ./run'"'"''""",
    ),
    "a line break after a backslash in a text in double quotes of hyperfine": (
        ("sh", "-c", 'hyperfine "./bench-old --token made\\\n{value}"'),
        """sh -c 'hyperfine '"'"'./bench-old --token <hidden>'"'"''""",
    ),
}
ROWS = {**LAYERED, **TO_THE_END, **JOINED}

# Commands whose text in double quotes holds escapes and nothing hidden: shown as typed.
KEPT = (
    ("sh", "-c", 'sh -c "echo \\"made up\\" && ./bench-old"'),
    ("sh", "-c", 'sh -c \'ssh made-up-host "./bench-old --threads\\" 8\\""\''),
    ("sh", "-c", 'sh -c "./bench-old --threads \\\n8"'),
)


def _argv(name: str, value: str) -> tuple[str, ...]:
    return tuple(word.replace("{value}", value) for word in ROWS[name][0])


def _levels(text: str) -> Iterator[int]:
    """Yield the count of words of a shell text and of each text after ``-c`` in it."""
    words = shlex.split(text)
    yield len(words)
    for at, word in enumerate(words[:-1]):
        if word == "-c" and at > 0 and words[at - 1] in ("sh", "bash"):
            yield from _levels(words[at + 1])


@pytest.mark.parametrize("name", list(ROWS))
def test_a_value_after_an_escape_of_a_text_in_double_quotes_is_hidden(name: str) -> None:
    argv = _argv(name, VALUE)
    shown = ROWS[name][1]
    assert public_command(argv) == shown
    assert hashed_argv(argv) == shlex.split(shown)
    assert VALUE not in public_words(shlex.join(argv))


@pytest.mark.parametrize("name", list(LAYERED))
def test_each_level_of_the_shown_command_splits_into_as_many_words_as_typed(name: str) -> None:
    argv = _argv(name, VALUE)
    assert list(_levels(shlex.split(LAYERED[name][1])[2])) == list(_levels(argv[2]))


@pytest.mark.parametrize("name", list(ROWS))
def test_two_values_after_an_escape_give_one_hash(name: str) -> None:
    one, other = _argv(name, VALUE), _argv(name, OTHER_VALUE)
    assert json.dumps(hashed_argv(one)) == json.dumps(hashed_argv(other))
    assert public_command(one) == public_command(other)


@pytest.mark.parametrize("name", list(ROWS))
def test_two_programs_after_an_escape_still_give_two_hashes(name: str) -> None:
    old = _argv(name, VALUE)
    new = tuple(word.replace("bench-old", "bench-new").replace("mysql", "psql") for word in old)
    assert hashed_argv(old) != hashed_argv(new)
    assert public_command(old) != public_command(new)


@pytest.mark.parametrize(
    "argv",
    KEPT,
    ids=["an echo of escaped quotes", "an escaped thread count", "a line break after a backslash"],
)
def test_a_text_in_double_quotes_that_hides_nothing_is_shown_as_typed(
    argv: tuple[str, ...],
) -> None:
    assert public_command(argv) == shlex.join(argv)
    assert hashed_argv(argv) == list(argv)
