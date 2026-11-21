# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential's value joined around a variable across lines, or around an element, is hidden.

In the text of a program a value may join a string to a variable with ``.``
across a line break, with the ``.`` at the end of a line or at the start of
the next (``"a" .`` and then ``$x .`` and then ``"..."``), and the variable
may be an element of an array or a hash, with ``->`` or none (``$a[0]``,
``$x->[0]``, ``$h{a}``, ``$x['k']``). Each is hidden whole in the shown
command, and the hash is taken over it hidden, so two values give one hash.
The same pieces given to an ordinary name, a line break that joins nothing,
and the words after the hidden value show as typed and still tell two sides
apart. Every value is made up.
"""

from __future__ import annotations

import pytest

from pairbench import model
from pairbench.model import HIDDEN

# Two made-up values of one word, and one of several words, none a credential word.
VALUES = ("kiwi7mango42", "plum4grape19", "made kiwi7mango42 value")
# The shell's way to write a single quote inside single quotes.
Q = "'\"'\"'"
# Each workload, ``{s}`` for the value, and the shown command, ``<hidden>`` for the hidden value.
HIDDEN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "a string, a variable and a string joined across lines with . at the line ends": (
        ("perl", "-e", 'my $token = "made" .\n    $x .\n    "x {s}";\nprint 1;'),
        "perl -e 'my $token = \"<hidden>\";\nprint 1;'",
    ),
    "a string, a variable and a string joined across lines with . at the line starts": (
        ("perl", "-e", 'my $token = "made"\n    . $x\n    . "x {s}";\nprint 1;'),
        "perl -e 'my $token = \"<hidden>\";\nprint 1;'",
    ),
    "a variable joined across lines in PHP": (
        ("php", "-r", "$token = 'made' .\n  $x .\n  'x {s}';\necho 1;"),
        f"php -r '$token = {Q}<hidden>{Q};\necho 1;'",
    ),
    "a variable joined across lines with tabs": (
        ("perl", "-e", "my $token = 'made' .\n\t$x .\n\t'x {s}';\nprint 1;"),
        f"perl -e 'my $token = {Q}<hidden>{Q};\nprint 1;'",
    ),
    "a variable first, joined to a string on the next line": (
        ("perl", "-e", "my $token = $x .\n  'x {s}';\nprint 1;"),
        "perl -e 'my $token = <hidden>;\nprint 1;'",
    ),
    "a variable joined across lines in a here-document of a shell text": (
        ("sh", "-c", "perl <<'END'\nmy $token = 'made' .\n  $x .\n  'x {s}';\nEND"),
        f"sh -c 'perl <<{Q}END{Q}\nmy $token = {Q}<hidden>{Q};\nEND'",
    ),
    "a variable joined across lines in a shell text": (
        ("sh", "-c", 'perl -e \'my $token = "made" .\n  $x .\n  "x {s}"; print 1;\''),
        f"sh -c 'perl -e {Q}my $token = \"<hidden>\"; print 1;{Q}'",
    ),
    "an element of an array joined with .": (
        ("perl", "-e", '$token = "made" . $a[0] . "x {s}"; print 1'),
        "perl -e '$token = \"<hidden>\"; print 1'",
    ),
    "an element of an array at a variable's place joined with .": (
        ("perl", "-e", '$token = "made" . $a[$i] . "x {s}"; print 1'),
        "perl -e '$token = \"<hidden>\"; print 1'",
    ),
    "an element of an array behind -> joined with .": (
        ("perl", "-e", '$token = "made" . $x->[0] . "x {s}"; print 1'),
        "perl -e '$token = \"<hidden>\"; print 1'",
    ),
    "an element of a hash joined with .": (
        ("perl", "-e", '$token = "made" . $h{a} . "x {s}"; print 1'),
        "perl -e '$token = \"<hidden>\"; print 1'",
    ),
    "an element of a hash behind -> joined with .": (
        ("perl", "-e", '$token = "made" . $h->{a} . "x {s}"; print 1'),
        "perl -e '$token = \"<hidden>\"; print 1'",
    ),
    "an element of an array joined with no blanks": (
        ("perl", "-e", "$token = 'made'.$a[0].'x {s}'; print 1"),
        f"perl -e '$token = {Q}<hidden>{Q}; print 1'",
    ),
    "an element of an array joined across lines": (
        ("perl", "-e", "my $token = 'made' .\n  $a[0] .\n  'x {s}';\nprint 1;"),
        f"perl -e 'my $token = {Q}<hidden>{Q};\nprint 1;'",
    ),
    "an element of an array of PHP joined with .": (
        ("php", "-r", "$token = 'made' . $x[0] . 'x {s}';"),
        f"php -r '$token = {Q}<hidden>{Q};'",
    ),
    "an element of PHP with a quoted key joined with .": (
        ("php", "-r", "$token = 'made' . $x['k'] . 'x {s}';"),
        f"php -r '$token = {Q}<hidden>{Q};'",
    ),
    "an element of _ENV of PHP joined with .": (
        ("php", "-r", "$token = 'made' . $_ENV['A'] . 'x {s}';"),
        f"php -r '$token = {Q}<hidden>{Q};'",
    ),
}


# Each workload, ``{s}`` for the value, and the shown command, ``{s}`` for the first value.
SHOWN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "a line break that joins nothing ends the value": (
        ("perl", "-e", "my $token = $x\n;print '{s}';"),
        f"perl -e 'my $token = <hidden>\n;print {Q}{{s}}{Q};'",
    ),
    "a string after a ; on the next line": (
        ("perl", "-e", "my $token = 'made' . $x;\nprint 'x {s}';"),
        f"perl -e 'my $token = {Q}<hidden>;\nprint {Q}x {{s}}{Q};'",
    ),
    "a value across lines given to an ordinary name": (
        ("perl", "-e", 'my $label = "made" .\n    $x .\n    "x {s}";\nprint 1;'),
        'perl -e \'my $label = "made" .\n    $x .\n    "x {s}";\nprint 1;\'',
    ),
    "an element of an array given to an ordinary name": (
        ("perl", "-e", '$label = "made" . $a[0] . "x {s}"; print 1'),
        'perl -e \'$label = "made" . $a[0] . "x {s}"; print 1\'',
    ),
    "an element of an array with no . after it": (
        ("perl", "-e", "my $token = $a[0]; print 'x {s}';"),
        f"perl -e 'my $token = <hidden>; print {Q}x {{s}}{Q};'",
    ),
    "an element of a hash printed": (
        ("perl", "-e", "print $h{a} . 'x {s}';"),
        f"perl -e 'print $h{{a}} . {Q}x {{s}}{Q};'",
    ),
}


def fill(words: tuple[str, ...], value: str) -> list[str]:
    return [word.replace("{s}", value) for word in words]


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of a word of the value that the text holds."""
    return [
        word[at : at + 6]
        for word in value.split()
        for at in range(len(word) - 5)
        if word[at : at + 6] in text
    ]


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("row", sorted(HIDDEN_ROWS))
def test_a_credential_joined_across_lines_or_around_an_element_is_hidden_whole(
    row: str, value: str
) -> None:
    words, shown = HIDDEN_ROWS[row]

    out = model.public_command(fill(words, value))

    assert out == shown.replace("<hidden>", HIDDEN)
    assert pieces(out, "kiwi7mango42 plum4grape19") == []


@pytest.mark.parametrize("row", sorted(HIDDEN_ROWS))
def test_the_hash_of_a_value_joined_across_lines_or_around_an_element_holds_no_value(
    row: str,
) -> None:
    words, _ = HIDDEN_ROWS[row]
    hashed = [model.hashed_argv(fill(words, value)) for value in VALUES]

    assert hashed[0] == hashed[1] == hashed[2]
    assert pieces("\n".join(hashed[0]), "kiwi7mango42") == []


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_an_ordinary_name_and_a_line_that_joins_nothing_show_as_typed(row: str) -> None:
    words, shown = SHOWN_ROWS[row]

    out = model.public_command(fill(words, VALUES[0]))

    assert out == shown.replace("{s}", VALUES[0]).replace("<hidden>", HIDDEN)


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_an_ordinary_name_and_a_line_that_joins_nothing_still_tell_two_sides_apart(
    row: str,
) -> None:
    words, _ = SHOWN_ROWS[row]

    assert model.hashed_argv(fill(words, VALUES[0])) != model.hashed_argv(fill(words, VALUES[1]))
