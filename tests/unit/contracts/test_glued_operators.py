# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A credential's value glued to a shell operator ends at the operator, in every shell text.

``sh -c 'API_KEY=VALUE;./bench-old'`` gives a credential and then runs a
program, and so does the same text glued with ``&&``, ``||``, ``|``, ``&``, a
line break or a closing ``)``. The value ends at the operator in the shown
command and in the hash, so ``./bench-old`` and ``./bench-new`` are two
commands and the program after the operator is shown. This holds for the text
after ``sh -c`` and ``bash -c``, one shell text inside another (in double
quotes, or in single quotes with each inner quote written as ``'"'"'``), and a
shell text that a wrapper starts: ``env -S``, ``hyperfine -N`` and ``--shell=none``,
``parallel -q``, ``su -c`` (also with a user and in a group of short options),
``runuser -u USER -c``, ``flock FILE -c`` and ``script -qc``. The text of a
wrapper that hands it to a shell (``su``, ``runuser``, ``flock``, ``script``)
is a shell text of its own, so the same holds there without ``sh -c``. Two
commands that differ in the credential alone are one command: one shown
command and one hash. Every value is made up.
"""

from __future__ import annotations

import json

import pytest

from pairbench import model

# Two made-up values, neither a credential word nor random-looking.
VALUES = ("kiwi7mango42", "plum4grape19")
PROGRAMS = ("old", "new")
# The words of each wrapper before the shell text it is given.
WRAPPERS: dict[str, tuple[str, ...]] = {
    "env -S": ("env", "-S"),
    "hyperfine -N": ("hyperfine", "-N"),
    "hyperfine --shell=none": ("hyperfine", "--shell=none"),
    "parallel -q": ("parallel", "-q"),
    "su -c": ("su", "-c"),
    "su app -c": ("su", "app", "-c"),
    "su -lc": ("su", "-lc"),
    "runuser -u app -c": ("runuser", "-u", "app", "-c"),
    "flock ./l -c": ("flock", "./l", "-c"),
    "script -qc": ("script", "-qc"),
}
# The wrappers that hand their text to a shell, so the text is a shell text of its own.
SHELL_WRAPPERS = ("su -c", "su app -c", "su -lc", "runuser -u app -c", "flock ./l -c", "script -qc")
# A credential glued to each operator, then a program; ``{v}`` is the value, ``{p}`` the program.
GLUED: dict[str, str] = {
    "semicolon": "API_KEY={v};./bench-{p}",
    "export and semicolon": "export API_KEY={v};./bench-{p}",
    "and": "API_KEY={v}&&./bench-{p}",
    "export and and": "export API_KEY={v}&&./bench-{p}",
    "or": "API_KEY={v}||./bench-{p}",
    "pipe": "API_KEY={v}|./bench-{p}",
    "background": "API_KEY={v}&./bench-{p}",
    "line break": "API_KEY={v}\n./bench-{p}",
    "closing bracket of a subshell": "(export API_KEY={v})&&./bench-{p}",
    "closing bracket and a blank": "(export API_KEY={v}) && ./bench-{p}",
}
# The same with blanks around the operator.
SPACED: dict[str, str] = {
    "semicolon and blank": "API_KEY={v}; ./bench-{p}",
    "and with blanks": "API_KEY={v} && ./bench-{p}",
}


def text(form: str, value: str, program: str) -> str:
    return form.replace("{v}", value).replace("{p}", program)


def shapes(form: str, value: str, program: str) -> dict[str, list[str]]:
    """Each command that runs the shell text: directly, nested, and under each wrapper."""
    inner = text(form, value, program)
    commands = {
        "sh -c": ["sh", "-c", inner],
        "bash -c": ["bash", "-c", inner],
        "sh -c, then bash -c": ["sh", "-c", f"bash -c '{inner}'"],
    }
    # ``bash -c '...'`` inside a text in single quotes, with each inner quote written as a
    # shell writes a quote inside single quotes: ``'"'"'``.
    own_quotes = f"sh -c 'bash -c '\"'\"'{inner}'\"'\"''"
    commands["sh -c, then sh -c and bash -c in single quotes"] = ["sh", "-c", own_quotes]
    for name, words in WRAPPERS.items():
        commands[f"{name}, then sh -c"] = [*words, f"sh -c '{inner}'"]
        commands[f"{name}, then sh -c and bash -c"] = [*words, f"sh -c \"bash -c '{inner}'\""]
        commands[f"{name}, then sh -c and bash -c in single quotes"] = [*words, own_quotes]
    for name in SHELL_WRAPPERS:
        commands[name] = [*WRAPPERS[name], inner]
    return commands


SHAPES = sorted(shapes("{v}", "x", "y"))
FORMS = {**GLUED, **SPACED}


def pieces(shown: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in shown]


def hashed(words: list[str]) -> str:
    return json.dumps(model.hashed_argv(words))


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_two_programs_after_one_glued_credential_are_two_commands(form: str, shape: str) -> None:
    old, new = (shapes(FORMS[form], VALUES[0], program)[shape] for program in PROGRAMS)

    shown_old, shown_new = model.public_command(old), model.public_command(new)

    assert "bench-old" in shown_old
    assert "bench-new" in shown_new
    assert shown_old.replace("bench-old", "bench-new") == shown_new
    assert hashed(old) != hashed(new)
    for shown in (shown_old, shown_new, hashed(old), hashed(new)):
        assert pieces(shown, VALUES[0]) == []


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("form", sorted(FORMS))
def test_one_program_after_two_glued_credentials_is_one_command(form: str, shape: str) -> None:
    first, second = (shapes(FORMS[form], value, "old")[shape] for value in VALUES)

    assert model.public_command(first) == model.public_command(second)
    assert hashed(first) == hashed(second)
    for words, value in ((first, VALUES[0]), (second, VALUES[1])):
        assert pieces(model.public_command(words), value) == []
        assert pieces(hashed(words), value) == []


# The shown command of the text after ``sh -c`` under each wrapper, for the credential glued
# to ``;``: the value is hidden, and the operator and the program after it are shown.
SHOWN_UNDER_WRAPPERS: dict[str, str] = {
    "env -S": "env -S 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "hyperfine -N": "hyperfine -N 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "hyperfine --shell=none": (
        "hyperfine --shell=none 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''"
    ),
    "parallel -q": "parallel -q 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "su -c": "su -c 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "su app -c": "su app -c 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "su -lc": "su -lc 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "runuser -u app -c": "runuser -u app -c 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "flock ./l -c": "flock ./l -c 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
    "script -qc": "script -qc 'sh -c '\"'\"'API_KEY=<hidden>;./bench-old'\"'\"''",
}


@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_the_program_after_a_glued_credential_under_a_wrapper_is_shown(wrapper: str) -> None:
    words = shapes(GLUED["semicolon"], VALUES[0], "old")[f"{wrapper}, then sh -c"]

    assert model.public_command(words) == SHOWN_UNDER_WRAPPERS[wrapper]


# The shown command of a wrapper's own shell text with the credential glued to ``&&``.
SHOWN_OWN_TEXTS: dict[str, str] = {
    "su -c": "su -c 'API_KEY=<hidden>&&./bench-old'",
    "su app -c": "su app -c 'API_KEY=<hidden>&&./bench-old'",
    "su -lc": "su -lc 'API_KEY=<hidden>&&./bench-old'",
    "runuser -u app -c": "runuser -u app -c 'API_KEY=<hidden>&&./bench-old'",
    "flock ./l -c": "flock ./l -c 'API_KEY=<hidden>&&./bench-old'",
    "script -qc": "script -qc 'API_KEY=<hidden>&&./bench-old'",
}


@pytest.mark.parametrize("wrapper", SHELL_WRAPPERS)
def test_a_wrapper_that_hands_its_text_to_a_shell_ends_a_value_at_an_operator(
    wrapper: str,
) -> None:
    words = shapes(GLUED["and"], VALUES[0], "old")[wrapper]

    assert model.public_command(words) == SHOWN_OWN_TEXTS[wrapper]


# A wrapper that runs its text with no shell keeps an operator of its own text in the value:
# the operator there is part of one word of the program's arguments.
@pytest.mark.parametrize("wrapper", ["env -S", "hyperfine -N", "parallel -q"])
def test_a_wrapper_with_no_shell_keeps_an_operator_of_its_own_text_in_the_value(
    wrapper: str,
) -> None:
    old, new = ([*WRAPPERS[wrapper], text(GLUED["semicolon"], VALUES[0], p)] for p in PROGRAMS)

    assert model.public_command(old) == model.public_command(new)
    assert hashed(old) == hashed(new)
    assert "bench" not in model.public_command(old)


# Texts read with no shell that hold quotes and a credential, as typed, and whether a shell
# text can stand in one of their quoted words: only one that names a shell or a program that
# runs a shell text can.
NO_SHELL_TEXTS: dict[str, tuple[tuple[str, ...], bool]] = {
    "code with no shell's name": (("python", "-c", '{"api_key":\n\n"kiwi7mango42"}'), False),
    "a split text with no shell's name": (("env", "-S", "tool '--api-key=kiwi7mango42;x'"), False),
    "a split text that runs a shell": (("env", "-S", "sh -c 'API_KEY=kiwi7mango42;x'"), True),
    "a command run with no shell that runs one": (
        ("hyperfine", "-N", "bash -c 'API_KEY=kiwi7mango42&&x'"),
        True,
    ),
}


@pytest.mark.parametrize("row", sorted(NO_SHELL_TEXTS))
def test_a_text_with_no_shell_reads_operators_only_when_it_names_a_shell(
    row: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    words, names_a_shell = NO_SHELL_TEXTS[row]
    shown = model.public_command(words)
    texts: list[str] = []
    spans = model._operator_spans

    def counted(text: str, depth: int = 0, *, shell: bool = True) -> list[tuple[int, int]]:
        if not shell:
            texts.append(text)
        return spans(text, depth, shell=shell)

    monkeypatch.setattr(model, "_operator_spans", counted)

    assert model.public_command(words) == shown
    assert model.HIDDEN in shown
    assert (words[-1] in texts) is names_a_shell


# Texts with their quotes taken out, and whether they name a shell or a program that runs a
# shell text as a word: a name inside a longer word does not count, a later one does.
NAMED_RUNNERS: dict[str, tuple[str, bool]] = {
    "a shell's name and its text": ("sh -c x", True),
    "a shell named by its path": ("/bin/bash", True),
    "a name after a dash": ("a-su", True),
    "a name after one inside a word": ("xbash sh", True),
    "a name after many line breaks": ("\n" * 4000 + "zsh", True),
    "a name ending a longer word": ("xsh", False),
    "a name starting a longer word": ("fishing", False),
    "a name before a word character": ("bash_x", False),
    "a name before a figure": ("tmux2", False),
    "no name at all": ("pushd", False),
    "nothing": ("", False),
}


@pytest.mark.parametrize("row", sorted(NAMED_RUNNERS))
def test_a_text_names_a_shell_only_by_a_whole_word(row: str) -> None:
    text, named = NAMED_RUNNERS[row]

    assert model._names_shell_runner(text) is named
    assert (model._SHELL_RUN_NAMES.search(text) is not None) is named


# ``env -S`` with ``sh -c`` and a ``bash -c`` text in single quotes, as typed (``{q}`` is
# ``'"'"'``), and its shown command and hashed words: a client's password is hidden, the
# ``;`` after it and the program after that are kept, and a text with nothing to hide is
# shown as typed.
INNER_QUOTE = "'\"'\"'"
NESTED_IN_SINGLE_QUOTES: dict[str, tuple[str, str, list[str]]] = {
    "a password before a semicolon": (
        "sh -c 'bash -c {q}redis-cli -a kiwi7mango42; ./bench-old{q}'",
        "env -S 'sh -c \"bash -c '\"'\"'redis-cli -a <hidden>; ./bench-old'\"'\"'\"'",
        ["env", "-S", "sh -c \"bash -c 'redis-cli -a <hidden>; ./bench-old'\""],
    ),
    "a password before an argument": (
        "sh -c 'bash -c {q}redis-cli -a kiwi7mango42 ./bench-old{q}'",
        "env -S 'sh -c \"bash -c '\"'\"'redis-cli -a <hidden> ./bench-old'\"'\"'\"'",
        ["env", "-S", "sh -c \"bash -c 'redis-cli -a <hidden> ./bench-old'\""],
    ),
    "nothing to hide": (
        "sh -c 'bash -c {q}./bench-old --fast; ./bench-old{q}'",
        (
            "env -S 'sh -c '\"'\"'bash -c '\"'\"'\"'\"'\"'\"'\"'\"'./bench-old --fast; "
            "./bench-old'\"'\"'\"'\"'\"'\"'\"'\"''\"'\"''"
        ),
        ["env", "-S", "sh -c 'bash -c '\"'\"'./bench-old --fast; ./bench-old'\"'\"''"],
    ),
}


@pytest.mark.parametrize("row", sorted(NESTED_IN_SINGLE_QUOTES))
def test_a_shell_text_in_single_quotes_inside_another_is_read_as_its_shell_reads_it(
    row: str,
) -> None:
    typed, shown, hashed_words = NESTED_IN_SINGLE_QUOTES[row]
    words = ["env", "-S", typed.replace("{q}", INNER_QUOTE)]

    assert model.public_command(words) == shown
    assert model.hashed_argv(words) == hashed_words
