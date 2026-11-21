# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Cleaning a command takes time in proportion to its length.

A command, a free text, a case id and a shell text are cleaned in one pass
over them, whatever one unbroken argument repeats: letters, the characters of
a scheme, a name joined by dashes, short options or the name of a template
before a path, alone or next to an address, an assignment, a path or quotes.
The text of a program, a value of many words and a shell text with operators
are cleaned, and read for the hash that hides their secrets, in one pass too.
Each cleaner is timed on the CPU of a process of its own, the best of a few
tries, so a busy machine does not make it look slow; an argument eight times as
long takes about eight times as long, never the square of it. That process is
stopped after ``TIME_LIMIT_S``, so a cleaner that takes the square of the time
fails its test within the limit instead of running for hours.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from pairbench import model
from pairbench.model import public_case, public_command, public_text, public_words

# The folder the package under test is imported from, for a process of its own.
SRC = Path(model.__file__).resolve().parents[1]

# The lengths timed: one unbroken argument of each shape, and one eight times as long.
SHORT = 16_000
LONG = 128_000
# The longest one cleaner may take on the long argument, in seconds of CPU.
LONG_LIMIT_S = 1.0
# How many times as long the long argument may take as the short one: eight times as long
# is in proportion, and sixty-four times would be the square.
RATIO_LIMIT = 24.0
# A time shorter than this is read as this long, so that the timer's grain makes no ratio.
TIMER_GRAIN_S = 0.002
# The best of this many tries is the time of a cleaner.
TRIES = 3
# The lengths of a very long argument: long enough that copying a word for each character
# added to it, or the text before each part of it, takes far more than sixteen times as long
# on the longer one.
BIG_SHORT = 125_000
BIG_LONG = 2_000_000
# Sixteen times as long is in proportion, and two hundred and fifty-six times the square.
BIG_RATIO_LIMIT = 64.0
BIG_TRIES = 2
# A length at which a time that grows as the square of the length runs for hours.
HUGE = 2_000_000
# The longest the process that runs the cleaning of one test may take, in seconds on the
# clock of the wall: a cleaner in proportion ends well within it, and one that takes the
# square of the time is stopped at it.
TIME_LIMIT_S = 60

ADDRESS = "http://localhost:8000/v1"
# Arguments of one piece repeated, as (what stands before, the piece, what stands after):
# each is shown as typed by every cleaner, but for the quotes ``public_words`` takes off.
SHOWN_SHAPES: dict[str, tuple[str, str, str]] = {
    "letters": ("", "x", ""),
    "a word": ("", "pairbench", ""),
    "the characters of a scheme": ("", "a+b.c-", ""),
    "a name joined by dashes": ("", "a-", ""),
    "short options": ("", "-p", ""),
    "a short option and a letter": ("", "-pa", ""),
    "the name of a template before a path": ("", "a<1>/", ""),
    "letters before an address": ("", "x", " " + ADDRESS),
    "an address before letters": (ADDRESS + " ", "x", ""),
    "letters glued to an address": ("", "x", ADDRESS),
    "a name joined by dashes before an assignment": ("", "a-", " x=1"),
    "templates before a file": ("", "a<1>/", "b"),
    "letters in quotes": ("'", "x", "'"),
}
# The shapes ``public_words`` shows as the one shell word they are, without their quotes.
UNQUOTED_BY_PUBLIC_WORDS = frozenset({"letters in quotes"})
# A path of folders of one letter each, of which a command shows the last part.
CUT_SHAPES: dict[str, tuple[str, str, str]] = {"a path of one-letter folders": ("", "/x", "")}
CUT_SHOWN = {"public_command": "tool x", "public_words": "x"}
# The letter ``a`` alone makes a hexadecimal value: hidden in a command and in a shell
# text, shown in a free text and a case id.
HEX_LETTER = "a"
HEX_SHOWN = {
    "public_command": "tool '<hidden>'",
    "public_command after sh -c": "sh -c '<hidden>'",
    "public_text": None,
    "public_case": "<hidden>",
    "public_words": "<hidden>",
}


def _command(arg: str) -> str:
    return public_command(("tool", arg))


def _shell(arg: str) -> str:
    return public_command(("sh", "-c", arg))


CLEANERS: dict[str, Callable[[str], str]] = {
    "public_command": _command,
    "public_command after sh -c": _shell,
    "public_text": public_text,
    "public_case": public_case,
    "public_words": public_words,
}


def _as_typed(name: str, arg: str) -> str:
    """What a cleaner shows of an argument it shows as typed."""
    if name == "public_command":
        return "tool " + shlex.quote(arg)
    if name == "public_command after sh -c":
        return "sh -c " + shlex.quote(arg)
    return arg


def _shaped(shape: str, length: int) -> str:
    before, piece, after = {**SHOWN_SHAPES, **CUT_SHAPES}[shape]
    return before + _repeated(piece, length - len(before) - len(after)) + after


def _shown(name: str, shape: str, arg: str) -> str:
    if shape in CUT_SHAPES:
        return CUT_SHOWN[name]
    if name == "public_words" and shape in UNQUOTED_BY_PUBLIC_WORDS:
        return arg[1:-1]
    return _as_typed(name, arg)


def _repeated(piece: str, length: int) -> str:
    return (piece * (length // len(piece) + 1))[:length]


def _cpu_times(
    cpu_times: Callable[..., list[tuple[float, str]]],
    name: str,
    calls: list[tuple[str, str]],
    tries: int = TRIES,
) -> list[float]:
    """The best CPU time of a few tries of the cleaner ``name`` at each (argument, shown).

    Every try shows what is expected. A try that takes several times ``LONG_LIMIT_S`` is the
    last: no other try comes near.
    """
    answers = cpu_times([(name, arg) for arg, _ in calls], tries, 4 * LONG_LIMIT_S, TIME_LIMIT_S)
    for (_, expected), (_, shown) in zip(calls, answers, strict=True):
        assert shown == expected
    return [best for best, _ in answers]


@pytest.mark.parametrize("name", list(CLEANERS))
@pytest.mark.parametrize("shape", list(SHOWN_SHAPES))
def test_a_long_argument_shown_as_typed_is_cleaned_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = _shaped(shape, SHORT), _shaped(shape, LONG)
    assert len(short) == SHORT
    assert len(long) == LONG
    short_s, long_s = _cpu_times(
        cpu_times, name, [(short, _shown(name, shape, short)), (long, _shown(name, shape, long))]
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize("name", list(CLEANERS))
def test_a_long_hexadecimal_argument_is_hidden_in_proportion_to_its_length(
    name: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = _repeated(HEX_LETTER, SHORT), _repeated(HEX_LETTER, LONG)
    shown = HEX_SHOWN[name]
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [
            (short, _as_typed(name, short) if shown is None else shown),
            (long, _as_typed(name, long) if shown is None else shown),
        ],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("public_words", "letters"),
        ("public_command", "letters in quotes"),
        ("public_command", "a path of one-letter folders"),
        ("public_words", "a path of one-letter folders"),
    ],
    ids=[
        "a shell text of one word",
        "a quoted argument of a command",
        "a path in a command",
        "a path in a shell text",
    ],
)
def test_a_very_long_argument_is_cleaned_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = _shaped(shape, BIG_SHORT), _shaped(shape, BIG_LONG)
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [(short, _shown(name, shape, short)), (long, _shown(name, shape, long))],
        BIG_TRIES,
    )
    assert long_s / max(short_s, TIMER_GRAIN_S) < BIG_RATIO_LIMIT


# Case ids whose words in brackets are read as the words of a command, as (what stands before,
# the piece, what stands after): each is shown as typed.
CASE_WORD_SHAPES: dict[str, tuple[str, str, str]] = {
    "letters in one pair of brackets": ("bench[", "x ", "]"),
    "many pairs of brackets": ("", "a[x y]", ""),
    "an option of a client and its number": ("bench[redis-cli ", "-p 1 ", "]"),
    "an option named like a credential's": ("bench[", "--token-count 8 ", "]"),
    # Hosts after an ``@`` with no password before them, and users with no host after them.
    "hosts with no password before them": ("bench[", "x@h.example-", "]"),
    "hosts after a user with no password": ("bench[", "u:@h.example-", "]"),
    "users with no host after them": ("bench[", "u:p@", "]"),
}


@pytest.mark.parametrize("shape", list(CASE_WORD_SHAPES))
def test_a_long_case_id_of_words_in_brackets_is_cleaned_in_proportion_to_its_length(
    shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    before, piece, after = CASE_WORD_SHAPES[shape]
    short, long = (
        before + _repeated(piece, length - len(before) - len(after)) + after
        for length in (SHORT, LONG)
    )
    short_s, long_s = _cpu_times(cpu_times, "public_case", [(short, short), (long, long)])
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# Names given a value, of one piece repeated whole, as (what stands before, the piece, whether
# the value is hidden): the words glued to a word of a key, a token or a password are read once.
NAME_SHAPES: dict[str, tuple[str, str, bool]] = {
    "a key glued to identities": ("KEY", "ID", True),
    "identities": ("", "ID", False),
    "keys": ("", "KEY", True),
    "tokens": ("", "TOKENS", True),
    "a password glued to files": ("PASS", "FILE", True),
    # Only the first KEYBOARD starts the word; each one after it is a key glued to more letters.
    "a key before the start of a word of its own": ("", "KEYBOARD", True),
    "a token before the start of a word of its own": ("", "TOKENIZE", False),
    "an option of a key glued to identities": ("--key", "id", True),
}


def _name_arg(shape: str, form: str, length: int) -> str:
    """A name of ``shape`` given the value ``v``, as long as ``length`` or a piece shorter."""
    before, piece, _ = NAME_SHAPES[shape]
    lead = "--" if form.startswith("--") and not before.startswith("--") else ""
    count = (length - len(lead) - len(before) - len("=v")) // len(piece)
    return f"{lead}{before}{piece * count}=v"


def _name_shown(shape: str, arg: str) -> str:
    """What a command shows of a name of ``shape`` given a value."""
    hidden = NAME_SHAPES[shape][2]
    return shlex.join(["tool", arg[: -len("v")] + "<hidden>" if hidden else arg])


@pytest.mark.parametrize("form", ["NAME=VALUE", "--NAME=VALUE"])
@pytest.mark.parametrize("shape", list(NAME_SHAPES))
def test_a_long_name_given_a_value_is_read_in_proportion_to_its_length(
    shape: str, form: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = _name_arg(shape, form, SHORT), _name_arg(shape, form, LONG)
    assert LONG - len(NAME_SHAPES[shape][1]) < len(long) <= LONG
    short_s, long_s = _cpu_times(
        cpu_times,
        "public_command",
        [(short, _name_shown(shape, short)), (long, _name_shown(shape, long))],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize("shape", ["identities", "keys", "a password glued to files"])
def test_a_very_long_name_given_a_value_is_read_in_proportion_to_its_length(
    shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short = _name_arg(shape, "NAME=VALUE", BIG_SHORT)
    long = _name_arg(shape, "NAME=VALUE", BIG_LONG)
    short_s, long_s = _cpu_times(
        cpu_times,
        "public_command",
        [(short, _name_shown(shape, short)), (long, _name_shown(shape, long))],
        BIG_TRIES,
    )
    assert long_s / max(short_s, TIMER_GRAIN_S) < BIG_RATIO_LIMIT


# Commands whose last argument holds one piece repeated, as (the words before it, what stands
# before the piece, the piece, what stands after it), then what the shown command holds of
# that argument and what its hash is taken over, each as (before, the piece, after).
FORM_SHAPES: dict[
    str,
    tuple[tuple[str, ...], str, str, str, tuple[str, str, str], tuple[str, str, str]],
] = {
    "a credential given a value of many words": (
        ("tool",),
        "DB_PASSWORD=",
        "x ",
        "",
        ("DB_PASSWORD=<hidden>", "", ""),
        ("DB_PASSWORD=<hidden>", "", ""),
    ),
    "a client password of many words glued to its option": (
        ("mysql",),
        "-p",
        "x ",
        "",
        ("-p<hidden>", "", ""),
        ("-p<hidden>", "", ""),
    ),
    "a value of a program after many line breaks": (
        ("python", "-c"),
        '{"api_key":',
        "\n",
        '"v"}',
        ('{"api_key":', "\n", '"<hidden>"}'),
        ('{"api_key":', "\n", '"<hidden>"}'),
    ),
    "names and signs on many lines of a program": (
        ("python", "-c"),
        "",
        "x:\n",
        "",
        ("", "x:\n", ""),
        ("", "x:\n", ""),
    ),
    "quoted names and commas in a program": (
        ("python", "-c"),
        "",
        "'x', ",
        "",
        ("", "'x', ", ""),
        ("", "'x', ", ""),
    ),
    "password options in the lists of a program": (
        ("python", "-c"),
        "",
        '["--password", "v"], ',
        "",
        ("", '["--password", "<hidden>"], ', ""),
        ("", '["--password", "<hidden>"], ', ""),
    ),
    "token options before shell operators": (
        ("sh", "-c"),
        "",
        "--token=v;",
        "",
        ("", "--token=<hidden>;", ""),
        ("", "--token=<hidden>;", ""),
    ),
    "token values before the operators of a shell text": (
        ("sh", "-c"),
        "",
        "TOKEN=v&&",
        "",
        ("", "TOKEN=<hidden>&&", ""),
        ("", "TOKEN=<hidden>&&", ""),
    ),
    "password values in braces next to each other in a setting": (
        ("tool", "--config"),
        "",
        "{password:v}",
        "",
        ("", "{password:<hidden>}", ""),
        ("", "{password:<hidden>}", ""),
    ),
    "quoted values one statement after another in a program": (
        ("python3", "-c"),
        "",
        "API_KEY='v';",
        "",
        ("", "API_KEY='<hidden>';", ""),
        ("", "API_KEY='<hidden>';", ""),
    ),
    "a header before shell operators": (
        ("sh", "-c"),
        "curl -H 'Authorization: v' ",
        "x;",
        "",
        ("curl -H 'Authorization: <hidden>' ", "x;", ""),
        ("curl -H 'Authorization: <hidden>' ", "x;", ""),
    ),
    "many names given a client's option before the client": (
        ("sh", "-c"),
        "",
        "X=-av ",
        "redis-cli",
        ("", "X=-a<hidden> ", "redis-cli"),
        ("", "X=-a<hidden> ", "redis-cli"),
    ),
    "many substitutions before a client's password": (
        ("sh", "-c"),
        "redis-benchmark ",
        "-n $(nproc) ",
        "-a v",
        ("redis-benchmark ", "-n $(nproc) ", "-a <hidden>"),
        ("redis-benchmark ", "-n $(nproc) ", "-a <hidden>"),
    ),
    "many backquotes that run a client": (
        ("sh", "-c"),
        "",
        "`redis-cli -a v` ",
        "",
        ("", "`redis-cli -a <hidden>` ", ""),
        ("", "`redis-cli -a <hidden>` ", ""),
    ),
    "many substitutions that run a client": (
        ("sh", "-c"),
        "./bench ",
        "--label $(redis-cli -a v get k) ",
        "",
        ("./bench ", "--label $(redis-cli -a <hidden> get k) ", ""),
        ("./bench ", "--label $(redis-cli -a <hidden> get k) ", ""),
    ),
    "many names given a client's option before no client": (
        ("sh", "-c"),
        "",
        "X=-av ",
        "./bench",
        ("", "X=-av ", "./bench"),
        ("", "X=-av ", "./bench"),
    ),
    "axis values after axis options in a shell text": (
        ("sh", "-c"),
        "made-up-bench",
        " -a Key=v",
        "",
        ("made-up-bench", " -a Key=v", ""),
        ("made-up-bench", " -a Key=v", ""),
    ),
    "axis values after axis options in the quoted text of an option": (
        ("made-up-bench", "--opts"),
        "",
        "-a 'Key=v' ",
        "",
        ("", "-a 'Key=v' ", ""),
        ("", "-a 'Key=v' ", ""),
    ),
    "axis values in escaped quotes in a shell text inside a shell text": (
        ("sh", "-c"),
        'sh -c "made-up-bench',
        ' -a \\"Key=v\\"',
        '"',
        ('sh -c "made-up-bench', ' -a \\"Key=v\\"', '"'),
        ('sh -c "made-up-bench', ' -a \\"Key=v\\"', '"'),
    ),
    "operators between escaped quotes in a shell text inside a shell text": (
        ("sh", "-c"),
        'sh -c "tool',
        ' --config \\"a;b\\" &&',
        '"',
        ('sh -c "tool', ' --config \\"a;b\\" &&', '"'),
        ('sh -c "tool', ' --config \\"a;b\\" &&', '"'),
    ),
    "a Perl q in braces that nothing closes": (
        ("perl", "-e"),
        "$token = q{",
        "a ",
        "",
        ("$token = <hidden>", "", ""),
        ("$token = <hidden>", "", ""),
    ),
    "a Ruby here-document with no line break": (
        ("ruby", "-e"),
        "",
        "token = <<EOT ",
        "",
        ("", "token = <hidden> ", ""),
        ("", "token = <hidden> ", ""),
    ),
    "strings joined by blanks": (
        ("python3", "-c"),
        "token = ",
        "'a' ",
        "",
        ("token = '<hidden>' ", "", ""),
        ("token = '<hidden>' ", "", ""),
    ),
    "Perl strings joined by dots": (
        ("perl", "-e"),
        "$token = ",
        "'a' . ",
        "'b'",
        ("$token = '<hidden>'", "", ""),
        ("$token = '<hidden>'", "", ""),
    ),
    "values of q before paths in a nested shell text": (
        ("sh", "-c"),
        "bash -c 'x",
        " TOKEN=q/a ./b",
        "'",
        ("bash -c 'x", " TOKEN=<hidden> ./b", "'"),
        ("bash -c 'x", " TOKEN=<hidden> ./b", "'"),
    ),
    "Perl substitutions": (
        ("perl", "-e"),
        "",
        "$token =~ s/a/b/; ",
        "",
        ("", "$token =~ <hidden>; ", ""),
        ("", "$token =~ <hidden>; ", ""),
    ),
    "f-strings": (
        ("python3", "-c"),
        "",
        "token = f'a'; ",
        "",
        ("", "token = <hidden>; ", ""),
        ("", "token = <hidden>; ", ""),
    ),
    "lines of a here-document": (
        ("sh", "-c"),
        "perl <<'END'\n",
        "$token = q/a /;\n",
        "END",
        ("perl <<'END'\n", "$token = <hidden>;\n", "END"),
        ("perl <<'END'\n", "$token = <hidden>;\n", "END"),
    ),
    "many here-documents": (
        ("sh", "-c"),
        "",
        "perl <<E\n$token = q/a /;\nE\n",
        "",
        ("", "perl <<E\n$token = <hidden>;\nE\n", ""),
        ("", "perl <<E\n$token = <hidden>;\nE\n", ""),
    ),
    "a here-document with a Perl q in braces that nothing closes": (
        ("sh", "-c"),
        "perl <<'END'\n$token = q{",
        "a ",
        "",
        ("perl <<'END'\n$token = <hidden>", "", ""),
        ("perl <<'END'\n$token = <hidden>", "", ""),
    ),
}


def _form(shape: str, length: int) -> tuple[str, str, str]:
    """The last argument of ``shape`` about ``length`` long, what is shown of it, what is hashed."""
    _, before, piece, after, shown, hashed = FORM_SHAPES[shape]
    count = (length - len(before) - len(after)) // len(piece)
    return (
        before + piece * count + after,
        shown[0] + shown[1] * count + shown[2],
        hashed[0] + hashed[1] * count + hashed[2],
    )


def _form_shown(head: tuple[str, ...], arg: str) -> str:
    return public_command((*head, arg))


def _form_hashed(head: tuple[str, ...], arg: str) -> str:
    return json.dumps(model.hashed_argv((*head, arg)))


@pytest.mark.parametrize("shape", list(FORM_SHAPES))
def test_a_long_program_text_or_value_of_many_words_is_cleaned_and_hashed_in_proportion(
    shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    head = FORM_SHAPES[shape][0]
    short, short_shown, short_hashed = _form(shape, SHORT)
    long, long_shown, long_hashed = _form(shape, LONG)
    assert LONG - len(FORM_SHAPES[shape][2]) - len(FORM_SHAPES[shape][3]) < len(long) <= LONG
    for read, short_out, long_out in (
        ("shown", shlex.join([*head, short_shown]), shlex.join([*head, long_shown])),
        ("hashed", json.dumps([*head, short_hashed]), json.dumps([*head, long_hashed])),
    ):
        short_s, long_s = _cpu_times(
            cpu_times, f"{shape}: {read}", [(short, short_out), (long, long_out)]
        )
        assert long_s < LONG_LIMIT_S
        assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# Shell texts that use their positional parameters in many commands, each as (the text of
# ``count`` commands, the arguments after ``$0``, what is shown and hashed of each argument).
# A command the text repeats is read once. The others read no more characters in all than
# the argument list holds and a spare (``_PARAMETER_READ_SPARE``); an argument a command past
# that would take is hidden, as here every argument of the two last shapes is.
PARAMETER_SHAPES: dict[
    str, tuple[Callable[[int], str], Callable[[int], list[str]], Callable[[int], list[str]]]
] = {
    "one client handed every argument many times": (
        lambda count: "; ".join(['redis-cli "$@"'] * count),
        lambda count: ["-a", "x"] * count,
        lambda count: ["-a", "<hidden>"] * count,
    ),
    "many commands handed every argument": (
        lambda count: "; ".join(f'c{k} "$@"' for k in range(count)),
        lambda count: ["-n", "1"] * count,
        lambda count: ["<hidden>"] * 2 * count,
    ),
    "many commands handed one long argument": (
        lambda count: "; ".join(f'c{k} "$1"' for k in range(count)),
        lambda count: ["x" * 16 * count],
        lambda count: ["<hidden>"],
    ),
}
# The length of the text and its arguments in characters, for each command of the text.
PARAMETER_PIECE = 64


def _parameters_shown(argv: str) -> str:
    """The shown command of the argument list written in JSON as ``argv``."""
    return public_command(("pairbench", "run", "--", *json.loads(argv))) or ""


def _parameters_hashed(argv: str) -> str:
    """What the hash of the argument list written in JSON as ``argv`` is taken over."""
    return json.dumps(model.hashed_argv(json.loads(argv)))


@pytest.mark.parametrize("shape", list(PARAMETER_SHAPES))
def test_a_shell_text_that_uses_its_arguments_in_many_commands_is_read_in_proportion(
    shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    text, arguments, hidden = PARAMETER_SHAPES[shape]
    calls: dict[str, list[tuple[str, str]]] = {"shown": [], "hashed": []}
    for length in (SHORT, LONG):
        count = length // PARAMETER_PIECE
        head = ("sh", "-c", text(count), "_")
        argv = json.dumps([*head, *arguments(count)])
        calls["shown"].append((argv, shlex.join(["pairbench", "run", "--", *head, *hidden(count)])))
        calls["hashed"].append((argv, json.dumps([*head, *hidden(count)])))
    for read, pairs in calls.items():
        short_s, long_s = _cpu_times(cpu_times, f"parameters: {read}", pairs)
        assert long_s < LONG_LIMIT_S
        assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# The cleaners a test times, by name, for the process that times them.
TIMED: dict[str, Callable[[str], str]] = {
    **CLEANERS,
    **{f"{shape}: shown": partial(_form_shown, form[0]) for shape, form in FORM_SHAPES.items()},
    **{f"{shape}: hashed": partial(_form_hashed, form[0]) for shape, form in FORM_SHAPES.items()},
    "parameters: shown": _parameters_shown,
    "parameters: hashed": _parameters_hashed,
}


_CLEAN_HUGE = """
import json, sys
from pairbench.model import public_case, public_command, public_text, public_words
arg = "x" * int(sys.argv[1])
print(json.dumps([
    public_command(("tool", arg)) == "tool " + arg,
    public_command(("sh", "-c", arg)) == "sh -c " + arg,
    public_text(arg) == arg,
    public_case(arg) == arg,
    public_words(arg) == arg,
]))
"""


def test_an_argument_of_two_million_letters_is_cleaned_at_all() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH_")}
    env["PYTHONPATH"] = str(SRC)
    try:
        done = subprocess.run(
            [sys.executable, "-c", _CLEAN_HUGE, str(HUGE)],
            env=env,
            capture_output=True,
            text=True,
            timeout=TIME_LIMIT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"cleaning {HUGE} letters did not end in {TIME_LIMIT_S} s")
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert json.loads(done.stdout) == [True, True, True, True, True]


# Paths whose folder names hold many words, each as before, the repeated piece and after: one
# that runs on over the words up to a word that holds a ``/``, one followed by words with no
# ``/`` after them, which stay as they are, and one in quotes, which runs to its closing quote.
SPACED_PATHS: dict[str, tuple[str, str, str]] = {
    "a path over many spaced words": ("/srv", " Zq", "/x"),
    "a path before many spaced words": ("/srv/x", " Zq", ""),
    "a quoted path over many spaced words": ("'/srv", " Zq", "/x'"),
}


def _spaced(shape: str, length: int) -> str:
    before, piece, after = SPACED_PATHS[shape]
    return before + piece * ((length - len(before) - len(after)) // len(piece)) + after


def _spaced_shown(name: str, shape: str, arg: str) -> str:
    """What a cleaner shows of a path over spaced words: its last part, and words with no path."""
    words = arg[len("/srv/") :]
    if shape == "a path over many spaced words":
        text, alone = "x", arg[1:]
    elif shape == "a path before many spaced words":
        text, alone = words, words
    else:
        text, alone = "'x'", "x"
    return {
        "public_command": "tool " + shlex.quote(text),
        "public_command after sh -c": "sh -c " + shlex.quote(text),
        "public_text": text,
        "public_case": text,
        "public_words": alone,
    }[name]


# The lengths of a text of many words that ``public_words`` cleans: it reads each word as an
# argument of its own, which costs far more per character than one unbroken argument, so it
# gets half the lengths, and the long text is still eight times as long as the short one.
WORDS_SHORT = SHORT // 2
WORDS_LONG = LONG // 2


def _lengths(name: str) -> tuple[int, int]:
    return (WORDS_SHORT, WORDS_LONG) if name == "public_words" else (SHORT, LONG)


@pytest.mark.parametrize("name", list(CLEANERS))
@pytest.mark.parametrize("shape", list(SPACED_PATHS))
def test_a_long_path_over_spaced_words_is_cleaned_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = (_spaced(shape, length) for length in _lengths(name))
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [(short, _spaced_shown(name, shape, short)), (long, _spaced_shown(name, shape, long))],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# Paths after double quotes with a backslash before each, many on one line: no such quote
# opens a quoted part, so each path is read on to the end of the line unless one read of the
# line serves every path on it.
ESCAPED_QUOTE_PIECE = 'x \\"/x '


def _escaped_quotes(length: int) -> str:
    return ESCAPED_QUOTE_PIECE * (length // len(ESCAPED_QUOTE_PIECE))


def _escaped_quotes_shown(name: str, arg: str) -> str:
    """What a cleaner shows of the paths after escaped quotes: the last part of each."""
    text = arg.replace('"/x', '"x')
    return {
        "public_command": "tool " + shlex.quote(text),
        "public_command after sh -c": "sh -c " + shlex.quote(text),
        "public_text": text,
        "public_case": text,
        "public_words": " ".join(shlex.split(text)),
    }[name]


@pytest.mark.parametrize("name", list(CLEANERS))
def test_a_long_line_of_paths_after_escaped_double_quotes_is_cleaned_in_proportion(
    name: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = (_escaped_quotes(length) for length in _lengths(name))
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [(short, _escaped_quotes_shown(name, short)), (long, _escaped_quotes_shown(name, long))],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


# Relative paths of many folders, as (what stands before, the piece repeated, what stands
# after): one that never climbs, and one whose folders end in a climb back into them, which
# every cleaner shows as typed; one of many climbs back and one climb more, which climbs out
# of its folder and shows its last part; one glued to an option after a ``.``; and many
# climbs each after an ``=``.
CLIMB_SHAPES: dict[str, tuple[str, str, str]] = {
    "folders that never climb": ("", "a/", "x"),
    "folders before a climb back into them": ("", "a/", "../x"),
    "climbs back and one climb more": ("", "a/../", "../x"),
    "folders glued to an option after a dot": ("-I.", "a/", "x"),
    "climbs after equals signs": ("", "=../x", ""),
}
# What every cleaner shows of a shape that is cut, with what stands before it.
CLIMB_CUT = {"climbs back and one climb more": "x", "climbs after equals signs": "=x"}


def _climbing(shape: str, length: int) -> str:
    before, piece, after = CLIMB_SHAPES[shape]
    return before + piece * ((length - len(before) - len(after)) // len(piece)) + after


def _climbing_shown(name: str, shape: str, arg: str) -> str:
    return _as_typed(name, CLIMB_CUT.get(shape, arg))


@pytest.mark.parametrize("name", list(CLEANERS))
@pytest.mark.parametrize("shape", list(CLIMB_SHAPES))
def test_a_long_relative_path_that_may_climb_is_cleaned_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    short, long = (_climbing(shape, length) for length in _lengths(name))
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [
            (short, _climbing_shown(name, shape, short)),
            (long, _climbing_shown(name, shape, long)),
        ],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT
