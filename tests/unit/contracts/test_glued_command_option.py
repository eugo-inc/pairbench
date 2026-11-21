# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A command text glued to ``--command=`` of a program no table names is read as given apart.

``made-up-tool --command 'redis-cli -a VALUE'`` reads its text as any argument
is, so the first word names a client and the password after ``-a`` is hidden.
The same text glued to the option (``--command=redis-cli -a VALUE``, and so
``--cmd=``, ``--exec=`` and ``--run=``) is read the same way, in the shown
command and in the hash, in an argument list and in a shell text. A program
with an option of its own of that name keeps its own reading. Every value is
made up; the password is a word of small letters that no command writes by
itself.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
H = model.HIDDEN
PASSWORD = "zqmkiwi"
OPTIONS = ("--command", "--cmd", "--exec", "--run")


def shown(args: tuple[str, ...]) -> list[str]:
    """Return the arguments as the shown command gives them, the leading words left out."""
    return shlex.split(model.public_command((*LEAD, *args)))[len(LEAD) :]


@pytest.mark.parametrize("option", OPTIONS)
def test_a_client_password_in_a_glued_command_text_is_hidden(option: str) -> None:
    args = ("made-up-tool", f"{option}=redis-cli -a {PASSWORD} PING")
    expected = ["made-up-tool", f"{option}=redis-cli -a {H} PING"]

    assert shown(args) == expected
    assert model.hashed_argv(args) == expected


@pytest.mark.parametrize("option", OPTIONS)
def test_a_glued_command_text_in_a_shell_text_is_hidden(option: str) -> None:
    args = ("sh", "-c", f"made-up-tool {option}='redis-cli -a {PASSWORD} PING'")
    expected = ["sh", "-c", f"made-up-tool {option}='redis-cli -a {H} PING'"]

    assert shown(args) == expected
    assert model.hashed_argv(args) == expected


def test_a_glued_command_text_after_a_prefix_program_is_hidden() -> None:
    args = ("taskset", "-c", "0", "made-up-tool", f"--command=redis-cli -a {PASSWORD}")
    expected = ["taskset", "-c", "0", "made-up-tool", f"--command=redis-cli -a {H}"]

    assert shown(args) == expected
    assert model.hashed_argv(args) == expected


# Texts read glued and apart: each hides in the glued form exactly what it hides apart.
TEXTS = (
    f"redis-cli -a {PASSWORD} PING",
    f"valkey-cli --pass {PASSWORD} PING",
    "redis-cli PING",
    "echo -a made-up-word",
    "made-up-bench --size 4 --label made-up-label",
    f"--password {PASSWORD}",
    "SELECT 1",
)


@pytest.mark.parametrize("option", OPTIONS)
@pytest.mark.parametrize("text", TEXTS)
def test_a_glued_command_text_is_read_as_the_text_given_apart(option: str, text: str) -> None:
    apart_shown = shown(("made-up-tool", option, text))
    apart_hashed = model.hashed_argv(("made-up-tool", option, text))

    glued = ("made-up-tool", f"{option}={text}")
    assert shown(glued) == ["made-up-tool", f"{option}={apart_shown[2]}"]
    assert model.hashed_argv(glued) == ["made-up-tool", f"{option}={apart_hashed[2]}"]


# (the arguments, as shown and hashed): a program's own option of that name, or another name.
KEPT_FORMS: dict[str, tuple[tuple[str, ...], list[str]]] = {
    "an ordinary text glued to --command": (
        ("made-up-tool", "--command=redis-cli PING"),
        ["made-up-tool", "--command=redis-cli PING"],
    ),
    "a memtier command with no password": (
        ("memtier_benchmark", "--command=SET __key__ a"),
        ["memtier_benchmark", "--command=SET __key__ a"],
    ),
    "a hyperfine command name": (
        ("hyperfine", "--command-name=made-up-name", "./bench-old"),
        ["hyperfine", "--command-name=made-up-name", "./bench-old"],
    ),
    "an option whose name only starts like one": (
        ("made-up-tool", "--commands=echo -a made-up-word"),
        ["made-up-tool", "--commands=echo -a made-up-word"],
    ),
    "an empty glued text": (
        ("made-up-tool", "--command="),
        ["made-up-tool", "--command="],
    ),
}


@pytest.mark.parametrize("name", list(KEPT_FORMS))
def test_other_glued_options_show_and_hash_as_typed(name: str) -> None:
    args, expected = KEPT_FORMS[name]

    assert shown(args) == expected
    assert model.hashed_argv(args) == expected


def test_a_memtier_command_keeps_its_own_reading() -> None:
    args = ("memtier_benchmark", f"--command=AUTH made-up-user {PASSWORD}")
    expected = ["memtier_benchmark", f"--command=AUTH made-up-user {H}"]

    assert shown(args) == expected
    assert model.hashed_argv(args) == expected
