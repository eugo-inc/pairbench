# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy names the Redis forms whose password the shown command keeps.

Each limit is found in the section on the shown command, and each example it
gives is run through the cleaner and shows whole, as the policy says. The
config reference names the forms that are hidden; one is run here too, so the
two pages stay apart.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMITS = (
    "**A Redis command its client refuses or reads otherwise.** The command of a Redis or Valkey "
    "client is read where the client starts it, so in a form the client refuses or reads as "
    "something else, a password shows: `redis-benchmark -c AUTH madeup` shows whole, since the "
    "benchmark reads `AUTH` as its count of clients, and so does "
    "`redis-benchmark -i 1 AUTH madeup`, since the benchmark has no option `-i`. A `MIGRATE` with "
    "fewer words before `AUTH` than the server reads shows too: "
    "`redis-cli MIGRATE made-up-host 6380 AUTH madeup` shows whole.",
    "**A password given to a script or written to a file.** The words after the `,` of "
    "`redis-cli --eval` are arguments of the script, and a config line that a side writes to a "
    "file, through a here-document or `printf`, is text written by another program; neither is "
    "read as a password: `redis-cli --eval made-up.lua k , madeup` and "
    "`printf 'requirepass madeup\\n' > made-up.conf` show whole.",
    "Write the command of a Redis client in a form the client reads, and give a server its "
    "password on its command line (`--requirepass`) rather than in a file the side writes.",
)
# Each example of a limit, as the arguments of a side: each shows whole.
SHOWN_WHOLE = (
    ("redis-benchmark", "-c", "AUTH", "madeup"),
    ("redis-benchmark", "-i", "1", "AUTH", "madeup"),
    ("redis-cli", "MIGRATE", "made-up-host", "6380", "AUTH", "madeup"),
    ("redis-cli", "--eval", "made-up.lua", "k", ",", "madeup"),
    ("sh", "-c", "printf 'requirepass madeup\\n' > made-up.conf"),
    ("sh", "-c", "cat > made-up.conf <<EOF\nsentinel auth-pass made-up-master madeup\nEOF"),
)
# Forms close to a limit that the config reference names as hidden: (typed, shown).
HIDDEN = (
    (
        ("redis-cli", "MIGRATE", "made-up-host", "6380", "k", "0", "5000", "AUTH", "madeup"),
        ("redis-cli", "MIGRATE", "made-up-host", "6380", "k", "0", "5000", "AUTH", model.HIDDEN),
    ),
    (
        ("redis-benchmark", "-c", "50", "AUTH", "madeup"),
        ("redis-benchmark", "-c", "50", "AUTH", model.HIDDEN),
    ),
    (
        ("redis-cli", "CONFIG", "SET", "requirepass madeup"),
        ("redis-cli", "CONFIG", "SET", f"requirepass {model.HIDDEN}"),
    ),
)


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def test_the_security_policy_names_the_redis_forms_it_does_not_hide(repo_root: Path) -> None:
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    section = plain(text.split(f"\n{LIMITS_HEADING}\n", 1)[1].split("\n## ", 1)[0])

    assert [limit for limit in LIMITS if limit not in section] == []


@pytest.mark.parametrize("args", SHOWN_WHOLE)
def test_each_redis_limit_shows_whole(args: tuple[str, ...]) -> None:
    assert model.public_command(("tool", *args)) == shlex.join(["tool", *args])


@pytest.mark.parametrize(("typed", "shown"), HIDDEN)
def test_a_form_near_a_limit_is_hidden(typed: tuple[str, ...], shown: tuple[str, ...]) -> None:
    assert model.public_command(("tool", *typed)) == shlex.join(["tool", *shown])


def test_the_config_reference_names_a_config_setting_written_as_one_word(repo_root: Path) -> None:
    text = plain((repo_root / CONFIG).read_text(encoding="utf-8"))

    assert "| `CONFIG SET 'requirepass password'` | `CONFIG SET 'requirepass <hidden>'` |" in text
