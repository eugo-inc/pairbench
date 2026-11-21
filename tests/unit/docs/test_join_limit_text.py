# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the joins of Perl and PHP that are read only in part.

A credential's value joined with ``.`` is hidden with the plain variables and strings joined
to it, but a here-document of Perl joined after an element of an array, or after a variable on
a line of its own or with no blanks around its ``.``, keeps its lines; in PHP the string joined
after an element of an object's property, an element of a static property or a property of an
element shows; and so does a string joined after a call, a constant, an array or a numbered
variable. The security policy lists these among the known limits of the shown command with the
advice to join nothing to a credential's value in code, and the config reference, which says a
joined variable is part of the value, points at them. The same joins around a plain variable
are hidden whole.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A join of Perl or PHP read only in part.** A credential's value joined with `.` is hidden "
    "with the plain variables and strings joined to it, but not every join is read whole. A "
    "here-document joined after "
    "an element of an array, as in `perl -e 'my $token = \"made\" . $a[0] . <<EOT;'` with "
    "`password` and `EOT` on the lines after it, or after a variable that stands on a line of its "
    "own or has no blanks around its `.`, is not read with the value, so its lines show. In PHP, "
    'after an element of an object\'s property, such as `$o->p[0]` or `$this->cfg["k"]`, an '
    "element of a static property, such as `C::$p[0]`, or a property of an element, such as "
    '`$o["k"]->p`, the string joined to it shows: '
    '`php -r \'$token = "made" . $o->p[0] . "password";\'` shows '
    '`php -r \'$token = "<hidden> . "password";\'`. So does a string joined after a call, a '
    'constant, an array or a numbered variable, such as `f()`, `getenv("X")`, `PHP_EOL`, `@x` or '
    "`$1`."
)
ADVICE = "join nothing to a credential's value in code."
POINTER = (
    "A join after a call, a constant, an array such as `@x` or a numbered variable such as `$1`, "
    "and a here-document joined after an element of an array, are not read with the value, so "
    "what follows shows, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say."
)
HERE_DOC = "\npassword\nEOT\n"
# The Perl forms the limit names, each with the here-document's lines after it.
PERL_SHOWN = (
    'my $token = "made" . $a[0] . <<EOT;' + HERE_DOC,
    'my $token = "made" .\n$x\n. <<EOT;' + HERE_DOC,
    'my $token = "made".$x.<<EOT;' + HERE_DOC,
)
PERL_HIDDEN = ('my $token = "made" . $x . <<EOT;' + HERE_DOC, "perl -e 'my $token = \"<hidden>\n'")
PHP_EXAMPLE = (
    ("php", "-r", '$token = "made" . $o->p[0] . "password";'),
    'php -r \'$token = "<hidden> . "password";\'',
)
# The PHP forms the limit names.
PHP_SHOWN = (
    '$token = "made" . $this->cfg["k"] . "password";',
    '$token = "made" . C::$p[0] . "password";',
    '$token = "made" . $o["k"]->p . "password";',
)
# The joins after a call, a constant, an array or a numbered variable that the limit names.
AFTER_OTHER = (
    ("perl", "-e", 'my $token = "made" . f() . "password";'),
    ("perl", "-e", 'my $token = "made" . @x . "password";'),
    ("perl", "-e", 'my $token = "made" . $1 . "password";'),
    ("perl", "-e", 'my $token = "made" . f() . <<EOT;' + HERE_DOC),
    ("php", "-r", '$token = "made" . f() . "password";'),
    ("php", "-r", '$token = "made" . getenv("X") . "password";'),
    ("php", "-r", '$token = "made" . PHP_EOL . "password";'),
)
PHP_HIDDEN = ('$token = "made" . $o->p . "password";', "php -r '$token = \"<hidden>\";'")


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


def test_the_config_reference_names_the_limit(repo_root: Path) -> None:
    assert POINTER in " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())


def shows(args: tuple[str, ...]) -> tuple[bool, bool]:
    """Whether the shown command and the hashed words of a command show the password."""
    shown = model.public_command(args)
    assert shown is not None
    return "password" in shown, "password" in " ".join(model.hashed_argv(args))


@pytest.mark.parametrize("code", PERL_SHOWN)
def test_each_perl_form_shows_the_here_document(code: str) -> None:
    assert shows(("perl", "-e", code)) == (True, True)


def test_the_perl_join_around_a_plain_variable_is_hidden_whole() -> None:
    code, shown = PERL_HIDDEN

    assert model.public_command(("perl", "-e", code)) == shown
    assert shows(("perl", "-e", code)) == (False, False)


def test_the_php_example_shows_what_the_limit_says() -> None:
    args, shown = PHP_EXAMPLE

    assert model.public_command(args) == shown
    assert shows(args) == (True, True)


@pytest.mark.parametrize("code", PHP_SHOWN)
def test_each_php_form_shows_the_string_joined_to_it(code: str) -> None:
    assert shows(("php", "-r", code)) == (True, True)


def test_the_php_join_after_a_property_is_hidden_whole() -> None:
    code, shown = PHP_HIDDEN

    assert model.public_command(("php", "-r", code)) == shown
    assert shows(("php", "-r", code)) == (False, False)


@pytest.mark.parametrize("args", AFTER_OTHER)
def test_a_string_after_a_call_a_constant_an_array_or_a_numbered_variable_shows(
    args: tuple[str, ...],
) -> None:
    assert shows(args) == (True, True)
