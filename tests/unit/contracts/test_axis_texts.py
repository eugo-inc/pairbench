# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The value of an axis option keeps the axis ``Key`` in every text a command holds.

After ``-a`` or ``--axis`` the axis ``Key`` keeps its values (``-a Key=I32``), in the text
after ``sh -c``, in a quoted word of that text, in a shell text inside another, in the
remote command of ``ssh`` and in the quoted text of an option, shown and hashed alike, so two
sides that differ in the axis's values are two sides. A credential after the axis value in
the same text stays hidden, and so does a credential-like name given a value after the
axis value in the same argument. A client whose ``-a`` takes a password keeps that rule, and
so does a shell builtin whose ``-a`` makes an array (``declare -a KEY=VALUE``). In the string
of a program that no shell reads, as the one after ``python -c``, a name after an axis option
is hidden as any credential-like name is.
"""

from __future__ import annotations

import json
import shlex

import pytest

from pairbench.model import hashed_argv, public_command, public_words
from pairbench.sides.identity import argv_sha256

# Two values of the axis, and two made-up secrets.
AXIS_VALUES = ("I32", "I64")
SECRETS = ("made-up-secret-1", "made-up-secret-2")

# Each form: the argument list with ``{x}`` where the axis value stands, and the command shown
# with the first value.
AXIS_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "the text after sh -c": (
        ("sh", "-c", "made-up-bench -a Key={x}"),
        "sh -c 'made-up-bench -a Key=I32'",
    ),
    "the text after bash -c with the long option": (
        ("bash", "-c", "made-up-bench --axis Key={x}"),
        "bash -c 'made-up-bench --axis Key=I32'",
    ),
    "the quoted text of an option": (
        ("made-up-bench", "--opts", "-a Key={x}"),
        "made-up-bench --opts '-a Key=I32'",
    ),
    "the quoted text of an option inside a shell text": (
        ("sh", "-c", "made-up-bench --opts '-a Key={x}'"),
        """sh -c 'made-up-bench --opts '"'"'-a Key=I32'"'"''""",
    ),
    "a quoted axis value in a shell text": (
        ("sh", "-c", "made-up-bench -a 'Key={x}'"),
        """sh -c 'made-up-bench -a '"'"'Key=I32'"'"''""",
    ),
    "an axis value of several values in a shell text": (
        ("sh", "-c", "made-up-bench -a Key=[{x},U8]"),
        "sh -c 'made-up-bench -a Key=[I32,U8]'",
    ),
    "an axis value after time in a shell text": (
        ("sh", "-c", "time made-up-bench -a Key={x}"),
        "sh -c 'time made-up-bench -a Key=I32'",
    ),
    "a program named declare by its path": (
        ("sh", "-c", "./declare -a Key={x}"),
        "sh -c './declare -a Key=I32'",
    ),
    "a declaring builtin's name given to a starter's option": (
        ("sh", "-c", "env -u local made-up-bench -a Key={x}"),
        "sh -c 'env -u local made-up-bench -a Key=I32'",
    ),
    "a declaring builtin's name given to an option": (
        ("sh", "-c", "made-up-bench --mode declare -a Key={x}"),
        "sh -c 'made-up-bench --mode declare -a Key=I32'",
    ),
    "a shell text in single quotes inside a shell text": (
        ("sh", "-c", "sh -c 'made-up-bench -a Key={x}'"),
        """sh -c 'sh -c '"'"'made-up-bench -a Key=I32'"'"''""",
    ),
    "a shell text in double quotes inside a shell text": (
        ("sh", "-c", 'sh -c "made-up-bench -a Key={x}"'),
        """sh -c 'sh -c "made-up-bench -a Key=I32"'""",
    ),
    "a shell text in double quotes with an escaped quote": (
        ("sh", "-c", 'sh -c "made-up-bench -a \\"Key={x}\\""'),
        """sh -c 'sh -c "made-up-bench -a \\"Key=I32\\""'""",
    ),
    "the remote command of ssh": (
        ("ssh", "made-up-host", "made-up-bench -a Key={x}"),
        "ssh made-up-host 'made-up-bench -a Key=I32'",
    ),
    "the remote command of ssh inside a shell text": (
        ("sh", "-c", "ssh made-up-host 'made-up-bench -a Key={x}'"),
        """sh -c 'ssh made-up-host '"'"'made-up-bench -a Key=I32'"'"''""",
    ),
    "the second command of a shell text": (
        ("sh", "-c", "made-up-bench -a Key=U8 && made-up-bench -a Key={x}"),
        "sh -c 'made-up-bench -a Key=U8 && made-up-bench -a Key=I32'",
    ),
}

# Each form: the argument list with ``{v}`` where a secret stands, and the command shown.
SECRET_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "an option after the axis value in a shell text": (
        ("sh", "-c", "made-up-bench -a Key=I32 --token {v}"),
        "sh -c 'made-up-bench -a Key=I32 --token <hidden>'",
    ),
    "a name after the axis value in a shell text": (
        ("sh", "-c", "made-up-bench -a Key=I32 Key={v}"),
        "sh -c 'made-up-bench -a Key=I32 Key=<hidden>'",
    ),
    "a variable of the next command of a shell text": (
        ("sh", "-c", "made-up-bench -a Key=I32; API_KEY={v} ./made-up-bench"),
        "sh -c 'made-up-bench -a Key=I32; API_KEY=<hidden> ./made-up-bench'",
    ),
    "a name after an operator that ends the command": (
        ("sh", "-c", "made-up-bench -a Key=I32 && Key={v} ./made-up-bench"),
        "sh -c 'made-up-bench -a Key=I32 && Key=<hidden> ./made-up-bench'",
    ),
    "a name on the line after the axis option": (
        ("sh", "-c", "made-up-bench -a\nKey={v} ./made-up-bench"),
        "sh -c 'made-up-bench -a\nKey=<hidden> ./made-up-bench'",
    ),
    "an option after the axis value in the quoted text of an option": (
        ("made-up-bench", "--opts", "-a Key=I32 --token {v}"),
        "made-up-bench --opts '-a Key=I32 --token <hidden>'",
    ),
    "a name glued after the axis value in its argument": (
        ("made-up-bench", "-a", "Key=I32,TOKEN={v}"),
        "made-up-bench -a 'Key=I32,TOKEN=<hidden>'",
    ),
    "a name glued after the axis value in a shell text": (
        ("sh", "-c", "made-up-bench -a Key=I32;TOKEN={v}"),
        "sh -c 'made-up-bench -a Key=I32;TOKEN=<hidden>'",
    ),
    "a name glued after a quoted axis value in a shell text": (
        ("sh", "-c", "made-up-bench -a 'Key=I32,TOKEN={v}'"),
        """sh -c 'made-up-bench -a '"'"'Key=I32,TOKEN=<hidden>'"'"''""",
    ),
    "the password option of a client in a shell text": (
        ("sh", "-c", "redis-cli -a Key={v} ping"),
        "sh -c 'redis-cli -a <hidden> ping'",
    ),
    "the axis glued to its option in a shell text": (
        ("sh", "-c", "made-up-bench --axis=Key={v}"),
        "sh -c 'made-up-bench --axis=Key=<hidden>'",
    ),
    "a name on the line after the axis option in the quoted text of an option": (
        ("made-up-bench", "--opts", "-a\nKey={v}"),
        "made-up-bench --opts '-a\nKey=<hidden>'",
    ),
    "a name after an escaped blank, in the word of the axis option": (
        ("sh", "-c", "made-up-bench -a\\ Key={v}"),
        "sh -c 'made-up-bench -a\\ Key=<hidden>'",
    ),
    "a name after an axis option glued to another option": (
        ("sh", "-c", 'made-up-bench --opts="-a Key={v}"'),
        """sh -c 'made-up-bench --opts="-a Key=<hidden>"'""",
    ),
    "a name after an axis option glued to another option in its argument": (
        ("made-up-bench", "--opts=-a Key={v}"),
        "made-up-bench '--opts=-a Key=<hidden>'",
    ),
    "a name after a word that ends in the axis option": (
        ("sh", "-c", "made-up-bench x-a Key={v}"),
        "sh -c 'made-up-bench x-a Key=<hidden>'",
    ),
    "another name after the axis option": (
        ("sh", "-c", "made-up-bench -a Password={v}"),
        "sh -c 'made-up-bench -a Password=<hidden>'",
    ),
}

# The forms of ``AXIS_FORMS`` with a client whose ``-a`` takes a password in place of the
# benchmark: the password stays hidden at every depth.
CLIENT_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "the text after sh -c": (
        ("sh", "-c", "redis-cli -a Key={v} ping"),
        "sh -c 'redis-cli -a <hidden> ping'",
    ),
    "the quoted text of an option": (
        ("redis-cli", "--opts", "-a Key={v}"),
        "redis-cli --opts '-a <hidden>'",
    ),
    "a quoted password in a shell text": (
        ("sh", "-c", "redis-cli -a 'Key={v}' ping"),
        "sh -c 'redis-cli -a <hidden> ping'",
    ),
    "a shell text in single quotes inside a shell text": (
        ("sh", "-c", "sh -c 'redis-cli -a Key={v} ping'"),
        """sh -c 'sh -c '"'"'redis-cli -a <hidden> ping'"'"''""",
    ),
    "a shell text in double quotes inside a shell text": (
        ("sh", "-c", 'sh -c "redis-cli -a Key={v} ping"'),
        """sh -c 'sh -c "redis-cli -a <hidden> ping"'""",
    ),
    "a shell text in double quotes with an escaped quote": (
        ("sh", "-c", 'sh -c "redis-cli -a \\"Key={v}\\" ping"'),
        """sh -c 'sh -c '"'"'redis-cli -a <hidden> ping'"'"''""",
    ),
    "the remote command of ssh": (
        ("ssh", "made-up-host", "redis-cli -a Key={v} ping"),
        "ssh made-up-host 'redis-cli -a <hidden> ping'",
    ),
    "the remote command of ssh inside a shell text": (
        ("sh", "-c", "ssh made-up-host 'redis-cli -a Key={v} ping'"),
        """sh -c 'ssh made-up-host '"'"'redis-cli -a <hidden> ping'"'"''""",
    ),
    "the second command of a shell text": (
        ("sh", "-c", "made-up-bench -a Key=U8 && redis-cli -a Key={v} ping"),
        "sh -c 'made-up-bench -a Key=U8 && redis-cli -a <hidden> ping'",
    ),
    "another client in a shell text": (
        ("sh", "-c", "valkey-cli -a Key={v} ping"),
        "sh -c 'valkey-cli -a <hidden> ping'",
    ),
}

# A shell builtin that declares variables takes ``-a`` for an array, so the word after it is
# a variable given a value, which a credential-like name hides, as ``KEY`` is: no axis there.
DECLARED_FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "declare in a shell text, before an axis value": (
        ("sh", "-c", "declare -a KEY={v}; made-up-bench -a Key=I32"),
        "sh -c 'declare -a KEY=<hidden>; made-up-bench -a Key=I32'",
    ),
    "local with an option before -a": (
        ("bash", "-c", "local -r -a key={v}"),
        "bash -c 'local -r -a key=<hidden>'",
    ),
    "typeset in a shell text in double quotes": (
        ("sh", "-c", 'sh -c "typeset -a Key={v}"'),
        """sh -c 'sh -c "typeset -a Key=<hidden>"'""",
    ),
    "readonly in the remote command of ssh": (
        ("ssh", "made-up-host", "readonly -a KEY={v}; ./bench"),
        "ssh made-up-host 'readonly -a KEY=<hidden>; ./bench'",
    ),
    "declare after then": (
        ("sh", "-c", "if true; then declare -a KEY={v}; fi"),
        "sh -c 'if true; then declare -a KEY=<hidden>; fi'",
    ),
    "local in the body of a function": (
        ("bash", "-c", "f() { local -a key={v}; }"),
        "bash -c 'f() { local -a key=<hidden>; }'",
    ),
    "declare after builtin": (
        ("sh", "-c", "builtin declare -a Key={v}"),
        "sh -c 'builtin declare -a Key=<hidden>'",
    ),
    "declare in a subshell": (
        ("sh", "-c", "(declare -a KEY={v}; ./bench)"),
        "sh -c '(declare -a KEY=<hidden>; ./bench)'",
    ),
    "an array of several elements": (
        ("sh", "-c", "declare -a KEY=(a {v})"),
        "sh -c 'declare -a KEY=<hidden>'",
    ),
    "an array whose first element is the value": (
        ("sh", "-c", "local -a key=({v} b) && ./bench"),
        "sh -c 'local -a key=<hidden> && ./bench'",
    ),
    "an array in the quoted text of an option": (
        ("made-up-bench", "--opts", "declare -a KEY=(a {v})"),
        "made-up-bench --opts 'declare -a KEY=<hidden>'",
    ),
    "an array in the remote command of ssh": (
        ("ssh", "made-up-host", "declare -a KEY=(a {v}); ./bench"),
        "ssh made-up-host 'declare -a KEY=<hidden>; ./bench'",
    ),
    "declare in a command substitution": (
        ("sh", "-c", "x=$(declare -a KEY={v}; echo)"),
        "sh -c 'x=$(declare -a KEY=<hidden>; echo)'",
    ),
    "an array in a command substitution after an assignment": (
        ("sh", "-c", "x=$(declare -a KEY=(a {v}) )"),
        "sh -c 'x=$(declare -a KEY=<hidden> )'",
    ),
    "an array after an operator": (
        ("sh", "-c", "true && declare -a KEY=(a {v})"),
        "sh -c 'true && declare -a KEY=<hidden>'",
    ),
    "an array glued after an operator": (
        ("sh", "-c", "echo a;declare -a KEY=(a {v})"),
        "sh -c 'echo a;declare -a KEY=<hidden>'",
    ),
    "an array after then": (
        ("sh", "-c", "if true; then declare -a KEY=(a {v}); fi"),
        "sh -c 'if true; then declare -a KEY=<hidden>; fi'",
    ),
    "an array after an assignment": (
        ("sh", "-c", "X=1 declare -a KEY=(a {v})"),
        "sh -c 'X=1 declare -a KEY=<hidden>'",
    ),
    "an array on a later line": (
        ("sh", "-c", "true\ndeclare -a KEY=(a {v})"),
        "sh -c 'true\ndeclare -a KEY=<hidden>'",
    ),
    "an array with an option before -a": (
        ("sh", "-c", "declare -g -a KEY=(a {v})"),
        "sh -c 'declare -g -a KEY=<hidden>'",
    ),
    "declare run by a program that starts others": (
        ("sh", "-c", "env declare -a KEY={v}"),
        "sh -c 'env declare -a KEY=<hidden>'",
    ),
    "declare in backquotes": (
        ("sh", "-c", "echo `declare -a KEY={v} `"),
        "sh -c 'echo `declare -a KEY=<hidden> `'",
    ),
    "declare after !": (
        ("sh", "-c", "! declare -a KEY={v}"),
        "sh -c '! declare -a KEY=<hidden>'",
    ),
    "declare after command": (
        ("sh", "-c", "command declare -a KEY={v}"),
        "sh -c 'command declare -a KEY=<hidden>'",
    ),
    "declare after do": (
        ("sh", "-c", "for x in 1; do declare -a KEY={v}; done"),
        "sh -c 'for x in 1; do declare -a KEY=<hidden>; done'",
    ),
    "declare after elif": (
        ("sh", "-c", "if false; then :; elif declare -a KEY={v}; then :; fi"),
        "sh -c 'if false; then :; elif declare -a KEY=<hidden>; then :; fi'",
    ),
    "declare after else": (
        ("sh", "-c", "if false; then :; else declare -a KEY={v}; fi"),
        "sh -c 'if false; then :; else declare -a KEY=<hidden>; fi'",
    ),
    "declare after eval": (
        ("sh", "-c", "eval declare -a KEY={v}"),
        "sh -c 'eval declare -a KEY=<hidden>'",
    ),
    "declare after if": (
        ("sh", "-c", "if declare -a KEY={v}; then :; fi"),
        "sh -c 'if declare -a KEY=<hidden>; then :; fi'",
    ),
    "declare after time": (
        ("sh", "-c", "time declare -a KEY={v}"),
        "sh -c 'time declare -a KEY=<hidden>'",
    ),
    "declare after until": (
        ("sh", "-c", "until declare -a KEY={v}; do :; done"),
        "sh -c 'until declare -a KEY=<hidden>; do :; done'",
    ),
    "declare after while": (
        ("sh", "-c", "while declare -a KEY={v}; do :; done"),
        "sh -c 'while declare -a KEY=<hidden>; do :; done'",
    ),
}

# Strings of a program, which no shell reads: a name after ``-a`` there is hidden as any is.
PROGRAM_FORMS: dict[str, tuple[str, ...]] = {
    "a benchmark": ("python3", "-c", "import os; os.system('made-up-bench -a Key={v}')"),
    "a client": ("python3", "-c", "import os; os.system('redis-cli -a Key={v} ping')"),
}
# What the shown command holds in place of the value in a program's string.
HIDDEN_NAME = "-a Key=<hidden>"

# Texts as ``public_words`` reads them, and what it shows.
WORDS: dict[str, tuple[str, str]] = {
    "the text after sh -c": (
        "sh -c 'made-up-bench -a Key=I32'",
        "sh -c made-up-bench -a Key=I32",
    ),
    "the quoted text of an option": (
        "made-up-bench --opts '-a Key=I32'",
        "made-up-bench --opts -a Key=I32",
    ),
    "a shell text inside a shell text": (
        """sh -c 'sh -c "made-up-bench -a Key=I32"'""",
        'sh -c sh -c "made-up-bench -a Key=I32"',
    ),
    "a credential after the axis value": (
        "sh -c 'made-up-bench -a Key=I32 --token made-up-secret-1'",
        "sh -c made-up-bench -a Key=I32 --token <hidden>",
    ),
    "the password option of a client": (
        "sh -c 'redis-cli -a Key=made-up-secret-1 ping'",
        "sh -c redis-cli -a <hidden> ping",
    ),
}


def _argv(form: tuple[str, ...], value: str) -> tuple[str, ...]:
    return tuple(word.replace("{x}", value).replace("{v}", value) for word in form)


@pytest.mark.parametrize(
    ("form", "shown"), [pytest.param(*form, id=name) for name, form in AXIS_FORMS.items()]
)
def test_an_axis_value_in_a_text_is_shown_and_hashed_as_typed(
    form: tuple[str, ...], shown: str
) -> None:
    argv = _argv(form, AXIS_VALUES[0])
    assert public_command(argv) == shown
    assert hashed_argv(argv) == shlex.split(shown)


@pytest.mark.parametrize(
    ("form", "shown"), [pytest.param(*form, id=name) for name, form in AXIS_FORMS.items()]
)
def test_two_axis_values_in_a_text_give_two_hashes(form: tuple[str, ...], shown: str) -> None:
    one, other = _argv(form, AXIS_VALUES[0]), _argv(form, AXIS_VALUES[1])
    assert argv_sha256(hashed_argv(one)) != argv_sha256(hashed_argv(other))
    assert public_command(other) == shown.replace("I32", "I64")


@pytest.mark.parametrize(
    ("form", "shown"), [pytest.param(*form, id=name) for name, form in SECRET_FORMS.items()]
)
def test_a_credential_beside_an_axis_value_stays_hidden(form: tuple[str, ...], shown: str) -> None:
    one, other = _argv(form, SECRETS[0]), _argv(form, SECRETS[1])
    assert public_command(one) == shown
    assert hashed_argv(one) == shlex.split(shown)
    assert "secret" not in json.dumps(hashed_argv(one))
    assert argv_sha256(hashed_argv(one)) == argv_sha256(hashed_argv(other))


@pytest.mark.parametrize(
    ("form", "shown"), [pytest.param(*form, id=name) for name, form in CLIENT_FORMS.items()]
)
def test_the_password_of_a_client_whose_a_takes_one_stays_hidden(
    form: tuple[str, ...], shown: str
) -> None:
    one, other = _argv(form, SECRETS[0]), _argv(form, SECRETS[1])
    assert public_command(one) == shown
    assert hashed_argv(one) == shlex.split(shown)
    assert "secret" not in json.dumps(hashed_argv(one))
    assert argv_sha256(hashed_argv(one)) == argv_sha256(hashed_argv(other))


@pytest.mark.parametrize(
    ("form", "shown"), [pytest.param(*form, id=name) for name, form in DECLARED_FORMS.items()]
)
def test_the_value_after_a_declaring_builtins_a_stays_hidden(
    form: tuple[str, ...], shown: str
) -> None:
    one, other = _argv(form, SECRETS[0]), _argv(form, SECRETS[1])
    assert public_command(one) == shown
    assert hashed_argv(one) == shlex.split(shown)
    assert "secret" not in json.dumps(hashed_argv(one))
    assert "secret" not in public_words(shlex.join(one))
    assert argv_sha256(hashed_argv(one)) == argv_sha256(hashed_argv(other))


@pytest.mark.parametrize(
    "form", [pytest.param(form, id=name) for name, form in PROGRAM_FORMS.items()]
)
def test_a_name_after_an_axis_option_in_a_program_string_is_hidden(form: tuple[str, ...]) -> None:
    one, other = _argv(form, SECRETS[0]), _argv(form, SECRETS[1])
    assert HIDDEN_NAME in public_command(one)
    assert "secret" not in public_command(one)
    assert "secret" not in json.dumps(hashed_argv(one))
    assert argv_sha256(hashed_argv(one)) == argv_sha256(hashed_argv(other))


@pytest.mark.parametrize(
    ("text", "shown"), [pytest.param(*row, id=name) for name, row in WORDS.items()]
)
def test_public_words_reads_an_axis_value_in_a_text_as_the_command_does(
    text: str, shown: str
) -> None:
    assert public_words(text) == shown
