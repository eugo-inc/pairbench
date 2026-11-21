# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential's value joined with ``.`` or written as a raw string of C++ is hidden whole.

In the text of a program a value may join a quote-like word of Perl, a string,
a variable or a here-document with ``.``, with blanks around it or none
(``q{a}.$x.q{...}``, ``$x.'...'``, ``'a' . <<'EOT'``, ``'a' . <<<EOT``), and
the ``$`` of a variable may have a backslash before it, as a shell writes it
inside double quotes (``\\$x.'...'``). A raw string of C++ may carry a prefix
before its ``R`` (``u8R"(...)"``, ``LR"x(...)x"``). Each is hidden whole in
the shown command, and the hash is taken over it hidden, so two values give
one hash. The same pieces given to an ordinary name, and the words after the
hidden value, show as typed and still tell two sides apart. Every value is
made up.
"""

from __future__ import annotations

import pytest

from pairbench import model
from pairbench.model import HIDDEN

# Two made-up values of one word, and one of several words, none a credential word.
VALUES = ("kiwi7mango42", "plum4grape19", "made kiwi7mango42 value")
# Each workload, ``{s}`` for the value, and the shown command, ``<hidden>`` for the hidden value.
HIDDEN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "a quote-like word, a variable and a quote-like word joined with no blanks": (
        ("perl", "-e", "$token = q{made}.$x.q{x {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a string, a variable and a quote-like word joined with no blanks": (
        ("perl", "-e", "$token = 'made'.$x.q{x {s}}; run_old()"),
        "perl -e '$token = '\"'\"'<hidden>; run_old()'",
    ),
    "a variable joined with a blank on one side": (
        ("perl", "-e", "$token = q{made} .$x. q{x {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "qq words and a variable joined with no blanks": (
        ("perl", "-e", "$token = qq{made}.$x.qq{x {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "quote-like words in slashes and a variable joined with no blanks": (
        ("perl", "-e", "$token = q/made/.$x.q/x {s}/; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a joined value given to my": (
        ("perl", "-e", "my $token = q{made}.$x.q{x {s}}; run_old()"),
        "perl -e 'my $token = <hidden>; run_old()'",
    ),
    "a joined value given to a key of ENV": (
        ("perl", "-e", "$ENV{TOKEN} = q{made}.$x.q{x {s}}; run_old()"),
        "perl -e '$ENV{TOKEN} = <hidden>; run_old()'",
    ),
    "a joined value after eq": (
        ("perl", "-e", "if ($token eq q{made}.$x.q{x {s}}) { run_old() }"),
        "perl -e 'if ($token eq <hidden>) { run_old() }'",
    ),
    "a variable first, then a quote-like word": (
        ("perl", "-e", "$token = $x.q{x {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a variable first, then a string": (
        ("perl", "-e", "$token = $x.'x {s}'; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "two variables, then a quote-like word": (
        ("perl", "-e", "$token = $x.$y.q{x {s}}; run_old()"),
        "perl -e '$token = <hidden>; run_old()'",
    ),
    "a variable first, then a string, in PHP": (
        ("php", "-r", "$token = $x.'x {s}'; run_old();"),
        "php -r '$token = <hidden>; run_old();'",
    ),
    "a variable joined with blanks first, then a string": (
        ("perl", "-e", "$token = $x . 'x {s}'; print 1"),
        "perl -e '$token = <hidden>; print 1'",
    ),
    "a joined value in a shell text": (
        ("sh", "-c", "perl -e '$token = q{made}.$x.q{x {s}}; run_old()'"),
        "sh -c 'perl -e '\"'\"'$token = <hidden>; run_old()'\"'\"''",
    ),
    "a variable a backslash escapes in double quotes of a shell text": (
        ("sh", "-c", "perl -e \"\\$token = 'made'.\\$x.'x {s}'; run_old()\""),
        "sh -c 'perl -e '\"'\"'\\$token = '\"'\"'\"'\"'\"'\"'\"'\"'<hidden>"
        "'\"'\"'\"'\"'\"'\"'\"'\"'; run_old()'\"'\"''",
    ),
    "a variable a backslash escapes, joined with blanks, in a shell text": (
        ("sh", "-c", "perl -e \"\\$token = 'made' . \\$x . 'x {s}'; run_old()\""),
        "sh -c 'perl -e '\"'\"'\\$token = '\"'\"'\"'\"'\"'\"'\"'\"'<hidden>"
        "'\"'\"'\"'\"'\"'\"'\"'\"'; run_old()'\"'\"''",
    ),
    "a here-document in double quotes joined with .": (
        ("perl", "-e", 'my $token = "made " . <<"EOT";\n{s} x\nEOT\nprint 1;'),
        "perl -e 'my $token = \"<hidden>\nprint 1;'",
    ),
    "a here-document in single quotes joined with .": (
        ("perl", "-e", "$token = 'a' . <<'EOT';\n{s} x\nEOT\nprint 1;"),
        "perl -e '$token = '\"'\"'<hidden>\nprint 1;'",
    ),
    "a here-document joined with . and no blanks": (
        ("perl", "-e", "$token = 'a'.<<EOT;\n{s} x\nEOT\nprint 1;"),
        "perl -e '$token = '\"'\"'<hidden>\nprint 1;'",
    ),
    "a here-document with a blank after its <<": (
        ("perl", "-e", "$token = 'a' . << \"EOT\";\n{s} x\nEOT\nprint 1;"),
        "perl -e '$token = '\"'\"'<hidden>\nprint 1;'",
    ),
    "a here-document with ~ joined with .": (
        ("perl", "-e", "$token = 'a' . <<~EOT;\n  {s} x\n  EOT\nprint 1;"),
        "perl -e '$token = '\"'\"'<hidden>\nprint 1;'",
    ),
    "a here-document of PHP in single quotes joined with .": (
        ("php", "-r", "$token = \"made \" . <<<'EOT'\n{s} x\nEOT;\necho 1;"),
        "php -r '$token = \"<hidden>\necho 1;'",
    ),
    "a here-document of PHP joined with .": (
        ("php", "-r", "$token = 'a' . <<<EOT\n{s} x\nEOT;\necho 1;"),
        "php -r '$token = '\"'\"'<hidden>\necho 1;'",
    ),
    "a here-document joined with . in a shell text": (
        ("sh", "-c", "perl -e '$token = \"a\" . <<EOT;\n{s} x\nEOT\nprint 1;'"),
        "sh -c 'perl -e '\"'\"'$token = \"<hidden>\nprint 1;'\"'\"''",
    ),
    "a raw string of C++ with u8R": (
        ("cling", "-e", 'auto token = u8R"(made {s} x)";'),
        "cling -e 'auto token = <hidden>;'",
    ),
    "a raw string of C++ with LR": (
        ("cling", "-e", 'auto token = LR"(made {s} x)";'),
        "cling -e 'auto token = <hidden>;'",
    ),
    "a raw string of C++ with u8R and an end word": (
        ("cling", "-e", 'auto token = u8R"x(made {s} x)x";'),
        "cling -e 'auto token = <hidden>;'",
    ),
    "a raw string of C++ with LR and an end word": (
        ("cling", "-e", 'auto token = LR"x(made {s} x)x";'),
        "cling -e 'auto token = <hidden>;'",
    ),
    "a raw string of C++ with LR given to a typed name": (
        ("cling", "-e", 'std::wstring password = LR"(made {s} x)"; run_old();'),
        "cling -e 'std::wstring password = <hidden>; run_old();'",
    ),
    "a raw string of C++ with u8R in a shell text": (
        ("sh", "-c", "cling -e 'auto token = u8R\"(made {s} x)\"; run_old();'"),
        "sh -c 'cling -e '\"'\"'auto token = <hidden>; run_old();'\"'\"''",
    ),
}


# Each workload, ``{s}`` for the value, and the shown command, ``{s}`` for the first value.
SHOWN_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "a joined value given to an ordinary name": (
        ("perl", "-e", "$label = q{made}.$x.q{x {s}}; run_old()"),
        "perl -e '$label = q{made}.$x.q{x {s}}; run_old()'",
    ),
    "a joined value printed": (
        ("perl", "-e", "print $x.q{x {s}};"),
        "perl -e 'print $x.q{x {s}};'",
    ),
    "a here-document joined to an ordinary name": (
        ("perl", "-e", 'my $name = "a " . <<"EOT";\n{s} x\nEOT\nprint 1;'),
        'perl -e \'my $name = "a " . <<"EOT";\n{s} x\nEOT\nprint 1;\'',
    ),
    "a joined value echoed in PHP": (
        ("php", "-r", "echo $x.'x {s}';"),
        "php -r 'echo $x.'\"'\"'x {s}'\"'\"';'",
    ),
    "a raw string of C++ with u8R given to an ordinary name": (
        ("cling", "-e", 'auto label = u8R"(made {s} x)";'),
        "cling -e 'auto label = u8R\"(made {s} x)\";'",
    ),
    "a raw string of C++ with LR given to an ordinary name": (
        ("cling", "-e", 'auto label = LR"(made {s} x)";'),
        "cling -e 'auto label = LR\"(made {s} x)\";'",
    ),
    "the words after a joined value": (
        ("perl", "-e", "my $token = $cfg.q{x y}; print '{s}'"),
        "perl -e 'my $token = <hidden>; print '\"'\"'{s}'\"'\"''",
    ),
    "an escaped variable joined to an ordinary name in a shell text": (
        ("sh", "-c", "perl -e \"\\$label = 'made'.\\$x.'x {s}'; run_old()\""),
        "sh -c 'perl -e \"\\$label = '\"'\"'made'\"'\"'.\\$x.'\"'\"'x {s}'\"'\"'; run_old()\"'",
    ),
    "an escaped variable before a dot in a shell text": (
        ("sh", "-c", "cp \\$x.{s} out"),
        "sh -c 'cp \\$x.{s} out'",
    ),
    "a variable joined with blanks and printed": (
        ("perl", "-e", "print $x . '{s}'; $y = $x . $z;"),
        "perl -e 'print $x . '\"'\"'{s}'\"'\"'; $y = $x . $z;'",
    ),
    "an escaped variable and a dot as words in a shell text": (
        ("sh", "-c", "echo \\$x . {s}"),
        "sh -c 'echo \\$x . {s}'",
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
def test_a_credential_given_joined_pieces_or_a_raw_string_is_hidden_whole(
    row: str, value: str
) -> None:
    words, shown = HIDDEN_ROWS[row]

    out = model.public_command(fill(words, value))

    assert out == shown.replace("<hidden>", HIDDEN)
    assert pieces(out, "kiwi7mango42 plum4grape19") == []


@pytest.mark.parametrize("row", sorted(HIDDEN_ROWS))
def test_the_hash_of_joined_pieces_given_to_a_credential_holds_no_value(row: str) -> None:
    words, _ = HIDDEN_ROWS[row]
    hashed = [model.hashed_argv(fill(words, value)) for value in VALUES]

    assert hashed[0] == hashed[1] == hashed[2]
    assert pieces("\n".join(hashed[0]), "kiwi7mango42") == []


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_joined_pieces_of_an_ordinary_name_and_the_words_after_show_as_typed(row: str) -> None:
    words, shown = SHOWN_ROWS[row]

    out = model.public_command(fill(words, VALUES[0]))

    assert out == shown.replace("{s}", VALUES[0]).replace("<hidden>", HIDDEN)


@pytest.mark.parametrize("row", sorted(SHOWN_ROWS))
def test_joined_pieces_of_an_ordinary_name_still_tell_two_sides_apart(row: str) -> None:
    words, _ = SHOWN_ROWS[row]

    assert model.hashed_argv(fill(words, VALUES[0])) != model.hashed_argv(fill(words, VALUES[1]))
