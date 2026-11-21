# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The config page says which raw strings of C++ and joins with ``.`` a credential's value takes.

The page lists a raw string of C++ with a prefix before its ``R`` among the strings a mark
of its own opens, and says that a variable joined with ``.`` and no blanks, one whose ``$``
a backslash escapes in a shell text, one on a line of its own, an element of an array or a
hash, and a here-document joined with ``.`` are part of the value. Each example, with a
made-up value where the page writes ``...``, is hidden whole in the shown command and in the
hash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
RAW_STRINGS = (
    'a raw string of C++ with a prefix before its `R` or none (`R"(...)"`, `u8R"(...)"`, '
    '`LR"x(...)x"`)'
)
JOINS = (
    "A variable of Perl or PHP joined with `.` is part of the value too, with the strings "
    "around it: `$token = 'made' . $x . '...'` hides all of it, and so does "
    "`$token = q{made}.$x.q{...}`, with no blanks around the `.`, and "
    "`perl -e \"\\$token = 'made'.\\$x.'...'\"` in a shell text, with a backslash before the "
    "`$`. The variable may stand on a line of its own, with the `.` at the end of a line or at "
    "the start of the next: `$token = 'made' .`, then `$x .` and `'...'` on the lines after it, "
    "hides all three. It may be an element of an array or a hash, with `->` or none: "
    "`$token = 'made' . $a[0] . '...'` hides all of it, as `$x->[0]`, `$h{a}` and `$x['k']` "
    "there do. So is a here-document joined with `.`: `$token = 'a' . <<'EOT'` hides the lines "
    "up to `EOT`."
)
# A made-up value for the ``...`` of each example.
VALUE = "kiwi7mango42"
# Each example of the page as the words of a command, ``...`` where the page writes it.
EXAMPLES: dict[str, list[str]] = {
    'u8R"(...)"': ["cling", "-e", 'auto token = u8R"(...)"; run_old();'],
    'LR"x(...)x"': ["cling", "-e", 'auto token = LR"x(...)x"; run_old();'],
    'R"(...)"': ["cling", "-e", 'auto token = R"(...)"; run_old();'],
    "$token = q{made}.$x.q{...}": ["perl", "-e", "$token = q{made}.$x.q{...}; run_old()"],
    "perl -e \"\\$token = 'made'.\\$x.'...'\"": [
        "sh",
        "-c",
        "perl -e \"\\$token = 'made'.\\$x.'...'; run_old()\"",
    ],
    "$token = 'a' . <<'EOT'": ["perl", "-e", "$token = 'a' . <<'EOT';\n...\nEOT\nrun_old();"],
    "$token = 'made' .": ["perl", "-e", "$token = 'made' .\n  $x .\n  '...';\nrun_old();"],
    "$token = 'made' . $a[0] . '...'": ["perl", "-e", "$token = 'made' . $a[0] . '...'; run_old()"],
    "$x->[0]": ["perl", "-e", "$token = 'made' . $x->[0] . '...'; run_old()"],
    "$h{a}": ["perl", "-e", "$token = 'made' . $h{a} . '...'; run_old()"],
    "$x['k']": ["php", "-r", "$token = 'made' . $x['k'] . '...'; run_old();"],
}


def page(repo_root: Path) -> str:
    return " ".join((repo_root / CONFIG_PAGE).read_text(encoding="utf-8").split())


def test_the_page_lists_raw_strings_of_cpp_with_a_prefix(repo_root: Path) -> None:
    assert RAW_STRINGS in page(repo_root)


def test_the_page_says_which_joins_with_a_dot_are_part_of_the_value(repo_root: Path) -> None:
    assert JOINS in page(repo_root)


@pytest.mark.parametrize("example", sorted(EXAMPLES))
def test_each_example_is_hidden_whole_in_the_shown_command_and_the_hash(example: str) -> None:
    words = [word.replace("...", VALUE) for word in EXAMPLES[example]]

    shown = model.public_command(words)

    assert VALUE not in shown
    assert VALUE not in "\n".join(model.hashed_argv(words))
    assert "run_old()" in shown
