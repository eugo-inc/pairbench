# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists a command glued to an option of another name among the known limits.

Of a program the config reference does not list with its command options, the text glued
with ``=`` to ``--command``, ``--cmd``, ``--exec`` or ``--run`` is read as the same text given
as the next argument. The text glued to an option of any other name is one value, so a
client's password in it shows in the shown command and in the hash. The security policy says
so with an example and the advice to give such a text as the next argument; the example and
the advice behave as the entry says.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
NEXT_HEADING = "## Known limits of the hashes"
LIMIT = (
    "- **A command glued to an option of another name.** Of a program that the config reference\n"
    "  does not list with its command options, the text glued with `=` to `--command`, `--cmd`,\n"
    "  `--exec` or `--run` is read as the same text given as the next argument. The text glued to\n"
    "  an option of any other name is one value, so a client's password in it shows:\n"
    "  `made-up-tool '--execute=redis-cli -a password PING'` shows whole. Give such a text as the\n"
    "  next argument: `made-up-tool --execute 'redis-cli -a password PING'` shows\n"
    "  `made-up-tool --execute 'redis-cli -a <hidden> PING'`.\n"
)
LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "
GLUED = ("made-up-tool", "--execute=redis-cli -a password PING")
SPACED = ("made-up-tool", "--execute", "redis-cli -a password PING")
SPACED_SHOWN = ("made-up-tool", "--execute", f"redis-cli -a {model.HIDDEN} PING")


def limits_text(root: Path) -> str:
    text = (root / SECURITY).read_text(encoding="utf-8")
    start = text.index(LIMITS_HEADING)
    return text[start : text.index(NEXT_HEADING, start)]


def test_the_known_limits_list_a_command_glued_to_an_option_of_another_name(
    repo_root: Path,
) -> None:
    assert LIMIT in limits_text(repo_root)


def test_the_example_of_the_limit_shows_and_hashes_whole() -> None:
    assert model.public_command((*LEAD, *GLUED)) == SHOWN_LEAD + shlex.join(GLUED)
    assert model.hashed_argv(GLUED) == list(GLUED)


def test_the_advice_of_the_limit_hides_the_password() -> None:
    assert model.public_command((*LEAD, *SPACED)) == SHOWN_LEAD + shlex.join(SPACED_SHOWN)
    assert model.hashed_argv(SPACED) == list(SPACED_SHOWN)


def test_the_four_names_of_the_limit_read_their_glued_text() -> None:
    for option in ("--command", "--cmd", "--exec", "--run"):
        glued = ("made-up-tool", f"{option}=redis-cli -a password PING")
        shown = ("made-up-tool", f"{option}=redis-cli -a {model.HIDDEN} PING")
        assert model.public_command((*LEAD, *glued)) == SHOWN_LEAD + shlex.join(shown), option
