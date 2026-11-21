# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A variable of Perl named with its package joins a credential's value as a plain one does.

Perl names a variable of a package with ``::``: ``$::x`` is ``$main::x``, and ``$Foo::x`` and
``$Foo::Bar::x`` name a variable of the package ``Foo`` or ``Foo::Bar``. Joined with ``.``
between the strings of a credential's value, with blanks around the ``.`` or none, across
lines, with an element after its name, or in the text of ``sh -c``, such a variable is read
as part of the value, so the string joined after it is hidden in the shown command and in the
hash. The same joins in code that gives no credential a value are shown as typed. Every value
is made up.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench import model

# Two made-up passwords, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")

# Perl code that joins a variable named with its package into a credential's value.
JOINED = {
    "$::x with blanks": 'my $token = "made" . $::x . "{v}";',
    "$::x with no blanks": 'my $token = "made".$::x."{v}";',
    "$::x with an element": 'my $token = "made" . $::x{k} . "{v}";',
    "$::x with an array element": 'my $token = "made" . $::x[0] . "{v}";',
    "$::x across lines": 'my $token = "made"\n . $::x\n . "{v}";',
    "$::Foo::x": 'my $token = "made" . $::Foo::x . "{v}";',
    "$Foo::x": 'my $token = "made" . $Foo::x . "{v}";',
    "$Foo::Bar::x": 'my $token = "made" . $Foo::Bar::x . "{v}";',
    "$main::x": 'my $token = "made" . $main::x . "{v}";',
    "$::x first": 'my $token = $::x . "{v}";',
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


@pytest.mark.parametrize("form", sorted(JOINED))
def test_a_package_variable_between_joins_hides_the_string_after_it(form: str) -> None:
    commands = [["perl", "-e", JOINED[form].replace("{v}", value)] for value in VALUES]
    shown = [model.public_command(words) for words in commands]
    hashed = [json.dumps(model.hashed_argv(words)) for words in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


# The same joins in the double-quoted text of ``sh -c``, where a backslash stands before each
# ``$`` of the Perl code.
IN_A_SHELL_TEXT = {
    "\\$::x": "perl -e \"my \\$token = 'made' . \\$::x . '{v}';\"",
    "\\$Foo::x": "perl -e \"my \\$token = 'made' . \\$Foo::x . '{v}';\"",
    "\\$Foo::Bar::x": "perl -e \"my \\$token = 'made' . \\$Foo::Bar::x . '{v}';\"",
}


@pytest.mark.parametrize("form", sorted(IN_A_SHELL_TEXT))
def test_a_package_variable_between_joins_in_a_shell_text_hides_the_string_after_it(
    form: str,
) -> None:
    commands = [["sh", "-c", IN_A_SHELL_TEXT[form].replace("{v}", value)] for value in VALUES]
    shown = [model.public_command(words) for words in commands]
    hashed = [json.dumps(model.hashed_argv(words)) for words in commands]

    for value, text, hash_input in zip(VALUES, shown, hashed, strict=True):
        assert pieces(text, value) == []
        assert pieces(hash_input, value) == []
    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]


def test_the_join_is_shown_hidden_whole() -> None:
    for value in VALUES:
        words = ["perl", "-e", f'my $token = "made" . $::x . "{value}";']

        assert model.public_command(words) == "perl -e 'my $token = \"<hidden>\";'"


# Perl code that joins such variables into a value that is no credential's.
SHOWN_AS_TYPED = (
    ["perl", "-e", 'my $label = "made" . $::x . "plain";'],
    ["perl", "-e", 'print $::x . "\\n";'],
    ["perl", "-e", 'my $n = $Foo::Bar::count . "items";'],
    ["perl", "-e", 'my $s = "a".$::x."b";'],
)


@pytest.mark.parametrize("words", SHOWN_AS_TYPED)
def test_a_join_that_gives_no_credential_a_value_is_shown_as_typed(words: list[str]) -> None:
    assert model.public_command(words) == shlex.join(words)
    assert model.hashed_argv(words) == words
