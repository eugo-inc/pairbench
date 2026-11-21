# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The words of an ``eval`` in a shell text are read as the shell text it runs.

``eval`` joins its words with blanks, each with its quotes taken off and its escapes read, and
runs what it joined. So a client's command that its words write with quotes in parts
(``'\\''``) or escaped (``\\'``) is read as the shell reads it, and its password is hidden in the
shown command and in the hash: each row is cleaned with two made-up values, no six characters in
a row of either show, and both give the same text and the same hash. The forms that were hidden
already stay hidden, and an ``eval`` with nothing to hide, or whose words hold no quote, is shown
as typed.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

# Two made-up values for ``{v}``.
VALUES = ("zq-made-up-kiwi7", "zq-made-up-pear3")
# A single quote written inside single quotes.
QUOTE = "'\\''"
# Forms that hide the value once the words of ``eval`` are read as the text it runs.
EVAL_FORMS = {
    "quoted in parts": ("sh", "-c", f"eval 'memtier_benchmark --command {QUOTE}AUTH {{v}}{QUOTE}'"),
    "escaped quotes": ("bash", "-c", "eval memtier_benchmark --command \\'AUTH {v}\\'"),
    "glued command in parts": (
        "pairbench",
        "run",
        "--",
        "sh",
        "-c",
        f"eval 'memtier_benchmark {QUOTE}--command=AUTH bob {{v}}{QUOTE}'",
    ),
    "glued command escaped": ("sh", "-c", "eval memtier_benchmark --command=\\'AUTH {v}\\'"),
    "escaped double quotes": ("sh", "-c", 'eval "memtier_benchmark --command \\"AUTH {v}\\""'),
    "eval in eval": ("sh", "-c", "eval eval memtier_benchmark --command \\'AUTH {v}\\'"),
    "between commands": (
        "sh",
        "-c",
        "cd x && eval memtier_benchmark --command \\'AUTH {v}\\' && ls",
    ),
    "in a nested shell text": (
        "sh",
        "-c",
        f"sh -c \"eval 'memtier_benchmark --command {QUOTE}AUTH {{v}}{QUOTE}'\"",
    ),
}
# A text an ``eval`` in a subshell runs (``{t}``): the ``(`` that opens the subshell, glued to
# ``eval`` or to the word before it, is no part of their names, and the ``)`` glued to the last
# word of the ``eval`` closes the subshell and is no part of the text.
SUBSHELL_OPENINGS = {
    "glued": "(eval {t})",
    "two brackets": "((eval {t}))",
    "after a blank": "( eval {t})",
    "blanks on both sides": "( eval {t} )",
    "builtin eval": "(builtin eval {t})",
    "command eval": "(command eval {t})",
    "before a redirection": "(eval {t})>out.log",
    "before an operator": "(eval {t}) && ls",
}
# The texts each opening runs, each with a later credential word that a shown command hides.
SUBSHELL_TEXTS = {
    "redis-cli": "'redis-cli -a {v} PING; true --token=x'",
    "mysql": "'mysql -p{v} -e s; true --token=x'",
    "memtier in parts": f"'memtier_benchmark --command {QUOTE}AUTH {{v}}{QUOTE}; true --token=x'",
    "memtier escaped": "memtier_benchmark --command \\'AUTH {v}\\'",
}
SUBSHELL_FORMS = {
    f"{opening} {client}": ("sh", "-c", shape.replace("{t}", text))
    for opening, shape in SUBSHELL_OPENINGS.items()
    for client, text in SUBSHELL_TEXTS.items()
}
# Each form, typed, and as it is shown and hashed: the brackets stay outside the quotes.
SUBSHELL_SHOWN = (
    (
        ("sh", "-c", "(eval 'redis-cli -a zq-made-up-kiwi7 PING; true --token=x')"),
        ("sh", "-c", "(eval 'redis-cli -a <hidden> PING; true --token=<hidden>')"),
    ),
    (
        ("sh", "-c", "( eval 'redis-cli -a zq-made-up-kiwi7 PING; true --token=x')"),
        ("sh", "-c", "( eval 'redis-cli -a <hidden> PING; true --token=<hidden>')"),
    ),
    (
        ("sh", "-c", "( eval 'redis-cli -a zq-made-up-kiwi7 PING; true --token=x' ) && ls"),
        ("sh", "-c", "( eval 'redis-cli -a <hidden> PING; true --token=<hidden>' ) && ls"),
    ),
    (
        ("sh", "-c", "((eval 'mysql -pzq-made-up-kiwi7 -e s'))>out.log"),
        ("sh", "-c", "((eval 'mysql -p<hidden> -e s'))>out.log"),
    ),
    (
        ("sh", "-c", "(eval memtier_benchmark --command \\'AUTH zq-made-up-kiwi7\\')"),
        ("sh", "-c", "(eval \"memtier_benchmark --command 'AUTH <hidden>'\")"),
    ),
)

# Forms hidden without the reading of ``eval``, which stay hidden.
KEPT_FORMS = {
    "eval in double quotes": ("sh", "-c", "eval \"memtier_benchmark --command 'AUTH {v}'\""),
    "no eval": ("sh", "-c", "memtier_benchmark --command 'AUTH {v}'"),
    "no shell": ("memtier_benchmark", "--command", "AUTH {v}"),
    "a script": ("memtier_benchmark", "--command", "EVAL \"return redis.call('AUTH','{v}')\" 0"),
    "a script in a shell text": (
        "sh",
        "-c",
        "memtier_benchmark --command \"EVAL \\\"return redis.call('AUTH','{v}')\\\" 0\"",
    ),
    "bare words": ("sh", "-c", "eval tool --token {v}"),
    "a credential name": ("sh", "-c", "eval PGPASSWORD={v} psql -c 'select 1'"),
    "redis eval": ("sh", "-c", "redis-cli -a {v} eval 'return 1' 0"),
}
# Each form, typed, and as it is shown.
SHOWN = (
    (
        ("bash", "-c", "eval memtier_benchmark --command \\'AUTH zq-made-up-kiwi7\\'"),
        "bash -c 'eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"'",
    ),
    (
        ("sh", "-c", "cd x && eval memtier_benchmark --command \\'AUTH zq-made-up-kiwi7\\' && ls"),
        "sh -c 'cd x && eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\" && ls'",
    ),
    (("sh", "-c", "eval tool --token zq-made-up-kiwi7"), "sh -c 'eval tool --token <hidden>'"),
)
# ``eval`` with nothing to hide, shown as typed.
ORDINARY = (
    ("sh", "-c", "eval cd x"),
    ("sh", "-c", "eval 'echo hi; ls -l' && make"),
    ("sh", "-c", 'eval "$(ssh-agent -s)" && ./bench --threads 8'),
    ("sh", "-c", "eval memtier_benchmark --threads 4 --command \\'SET k v\\'"),
    ("sh", "-c", "redis-cli eval 'return 1' 0"),
    ("sh", "-c", "(eval 'echo hi')"),
    ("sh", "-c", "( eval 'echo hi' ) && ls"),
    ("sh", "-c", "(evaluate x)"),
    ("sh", "-c", "(evaluate 'a b')"),
    ("sh", "-c", "(builtin evaluate 'a b')"),
    ("sh", "-c", "(eval memtier_benchmark --threads 4 --command \\'SET k v\\')"),
)


# A credential given its value at the start of the text of an ``eval``, before the program
# that text runs (``{p}``): only the value is hidden, as outside an ``eval``.
ASSIGNMENT_FORMS = {
    "single quotes": ("sh", "-c", "eval 'PGPASSWORD={v} {p} -h db.example'"),
    "double quotes": ("sh", "-c", 'eval "PGPASSWORD={v} {p} -h db.example"'),
    "after an assignment": ("sh", "-c", "x=1; eval 'PGPASSWORD={v} {p} -h db.example'"),
    "after and": ("sh", "-c", "true && eval 'PGPASSWORD={v} {p} -h db.example'"),
    "builtin eval": ("bash", "-c", "builtin eval 'PGPASSWORD={v} {p} -h db.example'"),
    "command eval": ("sh", "-c", "command eval 'PGPASSWORD={v} {p} -h db.example'"),
    "after a name": ("sh", "-c", "eval 'A=1 PGPASSWORD={v} {p} -h db.example'"),
    "after the end of options": ("bash", "-c", "eval -- 'PGPASSWORD={v} {p} -h db.example'"),
    "in a subshell": ("sh", "-c", "(eval 'PGPASSWORD={v} {p} -h db.example')"),
    "after a blank in a subshell": ("sh", "-c", "( eval 'PGPASSWORD={v} {p} -h db.example')"),
    "builtin eval in a subshell": (
        "bash",
        "-c",
        "(builtin eval 'PGPASSWORD={v} {p} -h db.example')",
    ),
}
# Two programs the text of an ``eval`` may run after the credential.
PROGRAMS = ("psql", "pgbench")
# Each form, typed, and as it is shown and hashed: the ``eval`` keeps its own quotes and its
# ``--``, and the program after the credential stays.
SHOWN_AS_TYPED = (
    (
        ("sh", "-c", "eval 'PGPASSWORD=zq-made-up-kiwi7 psql -h db.example'"),
        ("sh", "-c", "eval 'PGPASSWORD=<hidden> psql -h db.example'"),
    ),
    (
        ("sh", "-c", 'eval "PGPASSWORD=zq-made-up-kiwi7 pgbench -h db.example"'),
        ("sh", "-c", 'eval "PGPASSWORD=<hidden> pgbench -h db.example"'),
    ),
    (
        ("sh", "-c", "eval -- 'redis-cli -a zq-made-up-kiwi7 PING'"),
        ("sh", "-c", "eval -- 'redis-cli -a <hidden> PING'"),
    ),
    (
        ("sh", "-c", 'eval "redis-cli -a zq-made-up-kiwi7 PING $HOST_PORT"'),
        ("sh", "-c", 'eval "redis-cli -a <hidden> PING $HOST_PORT"'),
    ),
    (
        ("sh", "-c", "eval \"memtier_benchmark --command 'AUTH zq-made-up-kiwi7'\""),
        ("sh", "-c", "eval \"memtier_benchmark --command 'AUTH <hidden>'\""),
    ),
)


def _filled(argv: tuple[str, ...], at: int, program: str = "") -> tuple[str, ...]:
    return tuple(word.replace("{v}", VALUES[at]).replace("{p}", program) for word in argv)


def _pieces(text: str) -> list[str]:
    """Return each six characters in a row of a made-up value that the text holds."""
    found = (value[at : at + 6] for value in VALUES for at in range(len(value) - 5))
    return [piece for piece in found if piece in text]


@pytest.mark.parametrize("argv", list(EVAL_FORMS.values()), ids=list(EVAL_FORMS))
def test_the_words_of_an_eval_are_read_as_the_text_it_runs(argv: tuple[str, ...]) -> None:
    first, second = (model.public_command(_filled(argv, at)) for at in (0, 1))

    assert first == second
    assert first is not None and "<hidden>" in first
    assert _pieces(first + second) == []


@pytest.mark.parametrize("argv", list(EVAL_FORMS.values()), ids=list(EVAL_FORMS))
def test_the_hash_of_an_eval_reads_its_words_as_the_shown_command_does(
    argv: tuple[str, ...],
) -> None:
    first, second = (model.hashed_argv(_filled(argv, at)) for at in (0, 1))

    assert first == second
    assert _pieces(" ".join(first)) == []


@pytest.mark.parametrize("argv", list(KEPT_FORMS.values()), ids=list(KEPT_FORMS))
def test_a_form_hidden_before_stays_hidden(argv: tuple[str, ...]) -> None:
    shown = [model.public_command(_filled(argv, at)) for at in (0, 1)]
    hashed = [model.hashed_argv(_filled(argv, at)) for at in (0, 1)]

    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]
    assert _pieces(f"{shown[0]} {' '.join(hashed[0])}") == []


@pytest.mark.parametrize(("argv", "shown"), SHOWN)
def test_an_eval_shows_its_command_with_the_value_hidden(argv: tuple[str, ...], shown: str) -> None:
    assert model.public_command(argv) == shown


@pytest.mark.parametrize("argv", ORDINARY)
def test_an_eval_with_nothing_to_hide_is_shown_as_typed(argv: tuple[str, ...]) -> None:
    assert model.public_command(argv) == shlex.join(argv)
    assert model.hashed_argv(argv) == list(argv)


def test_an_eval_nested_deeper_than_the_texts_read_is_hidden_whole() -> None:
    text = "memtier_benchmark --command 'AUTH zq-made-up-kiwi7'"
    for _ in range(model._SHELL_DEPTH + 1):
        text = "eval '" + text.replace("'", QUOTE) + "'"

    shown = model.public_command(("sh", "-c", text))

    assert shown is not None and "<hidden>" in shown
    assert _pieces(shown) == []


@pytest.mark.parametrize("argv", list(ASSIGNMENT_FORMS.values()), ids=list(ASSIGNMENT_FORMS))
@pytest.mark.parametrize("program", PROGRAMS)
def test_an_assignment_at_the_start_of_an_eval_hides_only_its_value(
    argv: tuple[str, ...], program: str
) -> None:
    shown = [model.public_command(_filled(argv, at, program)) for at in (0, 1)]
    hashed = [model.hashed_argv(_filled(argv, at, program)) for at in (0, 1)]

    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]
    assert shown[0] is not None
    assert f"PGPASSWORD=<hidden> {program} -h db.example" in shown[0]
    assert f"PGPASSWORD=<hidden> {program} -h db.example" in hashed[0][-1]
    assert _pieces(f"{shown[0]} {' '.join(hashed[0])}") == []


@pytest.mark.parametrize("argv", list(ASSIGNMENT_FORMS.values()), ids=list(ASSIGNMENT_FORMS))
def test_two_programs_after_a_credential_in_an_eval_are_shown_and_hashed_apart(
    argv: tuple[str, ...],
) -> None:
    first, second = (_filled(argv, 0, program) for program in PROGRAMS)

    assert model.public_command(first) != model.public_command(second)
    assert model.hashed_argv(first) != model.hashed_argv(second)


@pytest.mark.parametrize(("argv", "shown"), SHOWN_AS_TYPED)
def test_an_eval_keeps_its_own_quotes_and_its_end_of_options(
    argv: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    assert model.public_command(argv) == shlex.join(shown)
    assert model.hashed_argv(argv) == list(shown)


@pytest.mark.parametrize("argv", list(SUBSHELL_FORMS.values()), ids=list(SUBSHELL_FORMS))
def test_an_eval_in_a_subshell_is_read_as_the_text_it_runs(argv: tuple[str, ...]) -> None:
    shown = [model.public_command(_filled(argv, at)) for at in (0, 1)]
    hashed = [model.hashed_argv(_filled(argv, at)) for at in (0, 1)]

    assert shown[0] == shown[1]
    assert hashed[0] == hashed[1]
    assert shown[0] is not None and "<hidden>" in shown[0]
    assert _pieces(f"{shown[0]} {' '.join(hashed[0])}") == []


@pytest.mark.parametrize(("argv", "shown"), SUBSHELL_SHOWN)
def test_an_eval_in_a_subshell_keeps_its_brackets_outside_its_text(
    argv: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    assert model.public_command(argv) == shlex.join(shown)
    assert model.hashed_argv(argv) == list(shown)
