# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Through ``plan``: a runner's shell text tells two programs apart, and two passwords not.

A side runs a runner whose text a shell runs: ``tmux`` given its command as
one argument, ``watch -c`` (its colour option), ``hyperfine`` next to a
command that holds ``-N`` of its own, and the ``-c`` or ``--command`` text of
``su``, ``runuser``, ``flock``, ``script`` and ``fish``. A credential's value
there ends at the operator after it, so two sides that run two programs after
the same password are two sides, and two sides that differ in the password
alone are one, which ``plan`` refuses.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

PASSWORDS = ("kiwi7mango", "plum4grape")
PROGRAMS = ("bench-old", "bench-new")
TEXT = "API_KEY={s};./{p}"
# Each form a side runs, with ``{s}`` for the password and ``{p}`` for the program.
FORMS: dict[str, list[str]] = {
    "tmux-one-argument": ["tmux", "new", "-d", TEXT],
    "tmux-window-one-argument": ["tmux", "neww", "API_KEY={s}|./{p}"],
    "watch-colour": ["watch", "-c", TEXT],
    "watch-colour-in-a-group": ["watch", "-tc", TEXT],
    "hyperfine-next-to-ssh-no-shell": ["hyperfine", "ssh -N made-up-host true", TEXT],
    "su": ["su", "bench", "-c", TEXT],
    "runuser": ["runuser", "-l", "bench", "--command", TEXT],
    "flock": ["flock", "made-up.lock", "-c", TEXT],
    "script": ["script", "-q", "-c", TEXT, "made-up.log"],
    "fish": ["fish", "--command=" + TEXT],
}
# The programs the forms start, each a made-up one that does nothing, first on PATH.
FAKES = ("tmux", "watch", "hyperfine", "su", "runuser", "flock", "script", "fish")
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder, with the runners as made-up programs that do nothing first on PATH."""
    programs = tmp_path / "bin"
    programs.mkdir()
    for name in FAKES:
        path = programs / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def typed(form: str, password: str, program: str) -> list[str]:
    return [word.replace("{s}", password).replace("{p}", program) for word in FORMS[form]]


def two_sides(work: Path, sides: list[list[str]]) -> str:
    """Write the sides ``a`` and ``b``; return the config's name."""
    tables = "".join(
        f"[sides.{name}]\ncmd = {json.dumps(cmd)}\n" for name, cmd in zip("ab", sides, strict=True)
    )
    (work / "sides.toml").write_text(tables + '[workload]\ndriver = "wall"\n', encoding="utf-8")
    return "sides.toml"


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of either password that the text holds."""
    return [
        password[at : at + 6]
        for password in PASSWORDS
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


@pytest.mark.parametrize("form", sorted(FORMS))
def test_plan_takes_two_programs_after_one_password_as_two_sides(
    cli: Cli, work: Path, form: str
) -> None:
    config = two_sides(work, [typed(form, PASSWORDS[0], program) for program in PROGRAMS])
    result = cli("plan", "--config", config)

    assert result.code == EXIT_OK, result.err
    assert pieces(result.out + result.err) == []


@pytest.mark.parametrize("form", sorted(FORMS))
def test_plan_refuses_two_passwords_before_one_program_as_one_side(
    cli: Cli, work: Path, form: str
) -> None:
    config = two_sides(work, [typed(form, password, PROGRAMS[0]) for password in PASSWORDS])
    result = cli("plan", "--config", config)

    assert result.code == EXIT_SIDE
    assert result.out == ""
    assert result.err == SAME_FINGERPRINT
