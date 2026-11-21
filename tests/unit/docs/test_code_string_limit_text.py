# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the strings in code that the cleaner reads only in part.

In code, a credential's value is hidden to the quote, the mark or the end word that closes it.
Some forms close otherwise, and the known limits of the shown command list each with an example
whose value shows. Each example is a row here and shows what the list says, in the shown command
and in the hash, and the same value written as the advice after the list says is hidden. The
configuration reference points to the list. Every value is made up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A string in code read only in part.** In code, a credential's value is hidden to the "
    "quote, the mark or the end word that closes it, with the strings joined to it. These forms "
    "are read only in part, so the rest of the value shows: an f-string of Python that uses its "
    'own quote inside its braces, as `python3 -c \'token = f"made {d["k"]} VALUE"\'` shows '
    "`python3 -c 'token = <hidden>k\"]} VALUE\"'`; a string with a tag before it in JavaScript, "
    "as ``node -e 'const token = String.raw`made VALUE`'`` shows "
    "``node -e 'const token = <hidden> VALUE`'``; a raw string of Julia or of Swift, as "
    "`julia -e 'token = raw\"made VALUE\"'` shows `julia -e 'token = <hidden>\"made VALUE\"'` and "
    "`swift -e 'let token = #\"made VALUE\"#'` shows "
    "`swift -e 'let token = <hidden>\"made VALUE\"#'`; a raw string of C++ that names an end word "
    'and holds a quote, as in `R"x(made " VALUE)x"`, where what follows that quote shows; a '
    "second string on the next line inside the brackets of a call with nothing between the two, "
    "as in `connect(token='made '` with `'VALUE')` on the next line, where `'VALUE'` shows; and a "
    "here-document of Ruby opened inside brackets, as in `token = (<<~EOT)` with `made VALUE` and "
    "`EOT` on the lines after it, whose lines show."
)
ADVICE = (
    "In code, write a credential's value as one string on one line, with nothing before its "
    "opening quote and no quote of its own inside it."
)
# The configuration reference's pointer to the list, after its strings in code.
CONFIG = "docs/reference/config.md"
CONFIG_POINTER = (
    "A few strings of this kind are read only in part, so the rest of their value shows: the "
    "[security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists them."
)
# The value each example gives, which shows.
VALUE = "VALUE"
# The examples on one line, as typed and as shown.
ONE_LINE = (
    (
        'python3 -c \'token = f"made {d["k"]} VALUE"\'',
        "python3 -c 'token = <hidden>k\"]} VALUE\"'",
    ),
    (
        "node -e 'const token = String.raw`made VALUE`'",
        "node -e 'const token = <hidden> VALUE`'",
    ),
    (
        "julia -e 'token = raw\"made VALUE\"'",
        "julia -e 'token = <hidden>\"made VALUE\"'",
    ),
    (
        "swift -e 'let token = #\"made VALUE\"#'",
        "swift -e 'let token = <hidden>\"made VALUE\"#'",
    ),
)
# The examples over several lines, as the words of a command.
LINES = (
    ("python3", "-c", "connect(token='made '\n 'VALUE')"),
    ("ruby", "-e", "token = (<<~EOT)\nmade VALUE\nEOT"),
    ("sh", "-c", 'echo \'auto token = R"x(made " VALUE)x";\' > x.cc'),
)
# The same values written as the advice says, each hidden whole.
AS_ADVISED = (
    ("python3 -c 'token = \"made VALUE\"'", "python3 -c 'token = \"<hidden>\"'"),
    ("node -e 'const token = `made VALUE`'", "node -e 'const token = <hidden>'"),
    (
        "python3 -c \"connect(token='made VALUE')\"",
        "python3 -c 'connect(token='\"'\"'<hidden>'\"'\"')'",
    ),
    ("node -e 'const token = `made ${f(x)} VALUE`'", "node -e 'const token = <hidden>'"),
    ("julia -e 'token = \"made VALUE\"'", "julia -e 'token = \"<hidden>\"'"),
    ("swift -e 'let token = \"made VALUE\"'", "swift -e 'let token = \"<hidden>\"'"),
    ("python3 -c 'API_KEY = \"made VALUE\"'", "python3 -c 'API_KEY = \"<hidden>\"'"),
    ("perl -e '$API_KEY = \"made VALUE\"'", "perl -e '$API_KEY = \"<hidden>\"'"),
    ('tool \'{"api_key": "made VALUE"}\'', 'tool \'{"api_key": "<hidden>"}\''),
)
# A string in backquotes whose braces hold a string in backquotes of their own, hidden whole,
# and its example, which the list does not hold.
NESTED_TEMPLATE = (
    "node -e 'const token = `made ${f(`x`)} VALUE`'",
    "node -e 'const token = <hidden>'",
)
NESTED_EXAMPLE = "`made ${f(`x`)} VALUE`"
# A here-document of Ruby opened with no brackets around it, hidden whole.
HEREDOC = (("ruby", "-e", "token = <<~EOT\nmade VALUE\nEOT"), "ruby -e 'token = <hidden>'")


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    text = " ".join((repo_root / SECURITY).read_text(encoding="utf-8").split())

    assert ADVICE in text


def test_the_configuration_reference_points_to_the_list(repo_root: Path) -> None:
    text = " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())

    assert CONFIG_POINTER in text


@pytest.mark.parametrize(("typed", "shown"), ONE_LINE)
def test_each_one_line_example_shows_as_the_limit_says(typed: str, shown: str) -> None:
    args = shlex.split(typed)

    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


@pytest.mark.parametrize("words", LINES)
def test_each_example_over_lines_shows_its_value(words: tuple[str, ...]) -> None:
    shown = model.public_command(list(words))

    assert shown is not None and "<hidden>" in shown
    assert VALUE in shown
    assert VALUE in " ".join(model.hashed_argv(list(words)))


@pytest.mark.parametrize(("typed", "shown"), AS_ADVISED)
def test_a_value_written_as_the_advice_says_is_hidden(typed: str, shown: str) -> None:
    args = shlex.split(typed)

    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


def test_a_here_document_with_no_brackets_around_it_is_hidden() -> None:
    words, shown = HEREDOC

    assert model.public_command(list(words)) == shown
    assert VALUE not in " ".join(model.hashed_argv(list(words)))


def test_a_template_whose_braces_hold_a_template_is_hidden_whole(repo_root: Path) -> None:
    typed, shown = NESTED_TEMPLATE
    args = shlex.split(typed)

    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)
    assert NESTED_EXAMPLE not in limits(repo_root)
