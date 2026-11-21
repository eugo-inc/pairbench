# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential's value in the text of a setting or a program ends where the value ends.

A bare value holds ``;`` and a closing bracket, as a password may, unless the ``;`` is an
operator of a shell text or the bracket closes one open before the value:
``tool --config '{password: a;b}'`` hides all of ``a;b``, in a shell text too. A value in
quotes ends at its closing quote, a quote after a backslash aside, but in the single quotes
of a shell text, which hold no escape. In the text of a program
that no shell reads, as after ``python -c``, the statement after a quoted value stays shown,
and a value given with ``name:`` ends at its line. A backslash before a line break joins the
two lines in a shell's double quotes and in a program, so a bare value runs on to the next
line there. So two values give one hash, while a setting or a program after the value still
tells two sides apart. The shown command and the hash read every form the same way.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from pairbench.model import hashed_argv, public_command
from pairbench.sides.identity import argv_sha256

# Each form: the argument list as typed, with ``{v}`` where the value stands and ``{x}`` where
# what tells two sides apart stands; the two values; the two settings or programs; the
# command shown with the first of each; and a part of the value that is never shown.
Form = tuple[tuple[str, ...], tuple[str, str], tuple[str, str], str, str]

THREADS = ("8", "16")
PROGRAMS = ("old", "new")
# Two made-up values that hold ``;``, two that hold ``)`` and two pairs that hold an escaped
# quote.
SEMICOLON = ("made;tail-1", "made;tail-2")
BRACKET = ("made)tail-1", "made)tail-2")
ESCAPED = ('made\\"tail-1', 'made\\"tail-2')
ESCAPED_SINGLE = ("made\\'tail-1", "made\\'tail-2")
# Two made-up values that run on after a backslash and a line break.
CONTINUED = ("made\\\ntail-1", "made\\\ntail-2")
# Two made-up values with nothing in them to end a value early.
PLAIN = ("made-up-secret-1", "made-up-secret-2")

# A value in the text of a setting, which no shell reads, and the settings after it.
SETTINGS: dict[str, Form] = {
    "a value in braces that holds a semicolon": (
        ("tool", "--config", "{password: {v}, threads: {x}}"),
        SEMICOLON,
        THREADS,
        "tool --config '{password: <hidden>, threads: 8}'",
        "tail-1",
    ),
    "a value after an equals sign that holds a semicolon": (
        ("tool", "--config", "password = {v}\nthreads = {x}"),
        SEMICOLON,
        THREADS,
        "tool --config 'password = <hidden>\nthreads = 8'",
        "tail-1",
    ),
    "a value in a section of an INI text": (
        ("tool", "--config", "[auth]\npassword = {v}\n[run]\nthreads = {x}"),
        SEMICOLON,
        THREADS,
        "tool --config '[auth]\npassword = <hidden>\n[run]\nthreads = 8'",
        "tail-1",
    ),
    "a value in braces that holds a closing bracket": (
        ("tool", "--config", "{api_key: {v}, threads: {x}}"),
        BRACKET,
        THREADS,
        "tool --config '{api_key: <hidden>, threads: 8}'",
        "tail-1",
    ),
    "a value in double quotes that holds an escaped quote": (
        ("tool", "--config", '{"password": "{v}", "threads": {x}}'),
        ESCAPED,
        THREADS,
        """tool --config '{"password": "<hidden>", "threads": 8}'""",
        "tail-1",
    ),
    "a value in single quotes that holds an escaped quote": (
        ("tool", "--config", "{'password': '{v}', 'threads': {x}}"),
        ESCAPED_SINGLE,
        THREADS,
        """tool --config '{'"'"'password'"'"': '"'"'<hidden>'"'"', '"'"'threads'"'"': 8}'""",
        "tail-1",
    ),
    "a value in braces in a quoted word of a shell text": (
        ("sh", "-c", "./bench --config '{password: {v}, threads: {x}}'"),
        SEMICOLON,
        THREADS,
        """sh -c './bench --config '"'"'{password: <hidden>, threads: 8}'"'"''""",
        "tail-1",
    ),
    "a value continued on the next line in a double-quoted word of a shell text": (
        ("sh", "-c", './bench --config "password = {v}\nthreads = {x}"'),
        CONTINUED,
        THREADS,
        """sh -c './bench --config "password = <hidden>\nthreads = 8"'""",
        "tail-1",
    ),
    "a value in braces continued on the next line in a double-quoted word of a shell text": (
        ("sh", "-c", './bench --config "{password: {v}, threads: {x}}"'),
        CONTINUED,
        THREADS,
        """sh -c './bench --config "{password: <hidden>, threads: 8}"'""",
        "tail-1",
    ),
    "a value continued on the next line in a setting": (
        ("tool", "--config", "password = {v}\nthreads = {x}"),
        CONTINUED,
        THREADS,
        "tool --config 'password = <hidden>\nthreads = 8'",
        "tail-1",
    ),
}

# A value in the text of a program that no shell reads, and the statement after it.
PROGRAM_TEXTS: dict[str, Form] = {
    "a value given with a colon ends at its line": (
        ("python3", "-c", "token: {v}\nrun_{x}()"),
        PLAIN,
        PROGRAMS,
        "python3 -c 'token: <hidden>\nrun_old()'",
        "secret",
    ),
    "a typed value read from the environment ends at its line": (
        ("python3", "-c", 'api_key: str = os.environ["{v}"]\nrun_{x}()'),
        PLAIN,
        PROGRAMS,
        "python3 -c 'api_key: <hidden>\nrun_old()'",
        "secret",
    ),
    "a value in single quotes before a semicolon": (
        ("python3", "-c", "API_KEY='{v}';run_{x}()"),
        PLAIN,
        PROGRAMS,
        """python3 -c 'API_KEY='"'"'<hidden>'"'"';run_old()'""",
        "secret",
    ),
    "a value in double quotes before a semicolon": (
        ("python3", "-c", 'API_KEY="{v}";run_{x}()'),
        PLAIN,
        PROGRAMS,
        """python3 -c 'API_KEY="<hidden>";run_old()'""",
        "secret",
    ),
    "a value in quotes in a call": (
        ("python3", "-c", "connect(password='{v}');run_{x}()"),
        PLAIN,
        PROGRAMS,
        """python3 -c 'connect(password='"'"'<hidden>'"'"');run_old()'""",
        "secret",
    ),
    "a value in quotes in a program inside a shell text": (
        ("sh", "-c", "python3 -c \"API_KEY='{v}';run_{x}()\""),
        PLAIN,
        PROGRAMS,
        """sh -c 'python3 -c "API_KEY='"'"'<hidden>'"'"';run_old()"'""",
        "secret",
    ),
    "a bare value continued on the next line in a program": (
        ("python3", "-c", "API_KEY = {v}\nrun_{x}()"),
        CONTINUED,
        PROGRAMS,
        "python3 -c 'API_KEY = <hidden>\nrun_old()'",
        "tail-1",
    ),
    "a bare value continued on the next line in a program inside a shell text": (
        ("sh", "-c", 'python3 -c "API_KEY = {v}\nrun_{x}()"'),
        CONTINUED,
        PROGRAMS,
        """sh -c 'python3 -c "API_KEY = <hidden>\nrun_old()"'""",
        "tail-1",
    ),
}

# Forms whose value runs on past where the rules above end one, or whose end is not sure:
# hidden to the end of the value, or of the word, so no part of it shows.
HIDDEN_WHOLE: dict[str, tuple[tuple[str, ...], str]] = {
    "a block of YAML after a colon": (
        ("tool", "--config", "password: |\n  {v}"),
        "tool --config 'password: <hidden>'",
    ),
    "a value on the line after a colon": (
        ("tool", "--config", "password:\n  {v}"),
        "tool --config 'password: <hidden>'",
    ),
    "a word after a quoted value and a semicolon in a setting": (
        ("tool", "--config", "password='made';{v}"),
        "tool --config 'password=<hidden>'",
    ),
    "a word after a semicolon in an argument": (
        ("tool", "password=made;{v}"),
        "tool 'password=<hidden>'",
    ),
    "a value continued after a backslash at the end of a line": (
        ("python3", "-c", 'token: str = "made" \\\n"{v}"\nrun_old()'),
        "python3 -c 'token: <hidden>\nrun_old()'",
    ),
    "a value in two quoted pieces": (
        ("python3", "-c", "API_KEY='made'\"{v}\";run_old()"),
        "python3 -c 'API_KEY=<hidden>'",
    ),
    "a value with an escaped quote in single quotes": (
        ("python3", "-c", "API_KEY='made\\'{v}';run_old()"),
        """python3 -c 'API_KEY='"'"'<hidden>'"'"';run_old()'""",
    ),
    "a header in a string of a program": (
        ("python3", "-c", "print('Authorization: {v} more')\nrun_old()"),
        """python3 -c 'print('"'"'Authorization: <hidden>\nrun_old()'""",
    ),
    "a bare value before a semicolon in a program": (
        ("python3", "-c", "API_KEY = made;{v}"),
        "python3 -c 'API_KEY = <hidden>'",
    ),
}


def _argv(form: tuple[str, ...], value: str, other: str = "") -> tuple[str, ...]:
    return tuple(word.replace("{v}", value).replace("{x}", other) for word in form)


def _cases(forms: dict[str, Form]) -> list[object]:
    return [pytest.param(*form, id=name) for name, form in forms.items()]


ALL_FORMS = _cases(SETTINGS) + _cases(PROGRAM_TEXTS)


@pytest.mark.parametrize(("form", "values", "others", "shown", "never"), ALL_FORMS)
def test_a_value_is_hidden_to_its_end_and_what_follows_is_shown(
    form: tuple[str, ...], values: tuple[str, str], others: tuple[str, str], shown: str, never: str
) -> None:
    argv = _argv(form, values[0], others[0])
    assert public_command(argv) == shown
    assert hashed_argv(argv) == shlex.split(shown)
    assert never not in json.dumps(hashed_argv(argv))


@pytest.mark.parametrize(("form", "values", "others", "shown", "never"), ALL_FORMS)
def test_two_values_give_one_hash(
    form: tuple[str, ...], values: tuple[str, str], others: tuple[str, str], shown: str, never: str
) -> None:
    one, other = _argv(form, values[0], others[0]), _argv(form, values[1], others[0])
    assert hashed_argv(one) == hashed_argv(other)
    assert argv_sha256(hashed_argv(one)) == argv_sha256(hashed_argv(other))
    assert public_command(one) == public_command(other) == shown


@pytest.mark.parametrize(("form", "values", "others", "shown", "never"), ALL_FORMS)
def test_what_follows_the_value_still_tells_two_sides_apart(
    form: tuple[str, ...], values: tuple[str, str], others: tuple[str, str], shown: str, never: str
) -> None:
    one, other = _argv(form, values[0], others[0]), _argv(form, values[0], others[1])
    assert argv_sha256(hashed_argv(one)) != argv_sha256(hashed_argv(other))
    assert public_command(other) == shown.replace(others[0], others[1])


CONFIG_PAGE = Path(__file__).resolve().parents[3] / "docs" / "reference" / "config.md"
# Each example the config reference gives of these rules: the command as typed, what the page
# says of it, and the command as shown.
PAGE_EXAMPLES = (
    (
        ("tool", "--config", "{password: a;b, threads: 8}"),
        "`tool --config '{password: a;b, threads: 8}'` shows "
        "`tool --config '{password: <hidden>, threads: 8}'`",
        "tool --config '{password: <hidden>, threads: 8}'",
    ),
    (
        ("python3", "-c", 'API_KEY="VALUE";run_old()'),
        """in `python3 -c 'API_KEY="VALUE";run_old()'` the quoted value is hidden and """
        "`run_old()` stays",
        """python3 -c 'API_KEY="<hidden>";run_old()'""",
    ),
)


@pytest.mark.parametrize(("argv", "said", "shown"), PAGE_EXAMPLES)
def test_the_config_reference_shows_what_the_command_shows(
    argv: tuple[str, ...], said: str, shown: str
) -> None:
    page = " ".join(CONFIG_PAGE.read_text(encoding="utf-8").split())
    assert said in page
    assert public_command(argv) == shown


@pytest.mark.parametrize(
    ("form", "shown"),
    [pytest.param(*form, id=name) for name, form in HIDDEN_WHOLE.items()],
)
def test_a_value_whose_end_is_not_sure_is_hidden_whole(form: tuple[str, ...], shown: str) -> None:
    one, other = _argv(form, PLAIN[0]), _argv(form, PLAIN[1])
    assert public_command(one) == shown
    assert hashed_argv(one) == shlex.split(shown)
    assert "secret" not in json.dumps(hashed_argv(one))
    assert hashed_argv(one) == hashed_argv(other)
