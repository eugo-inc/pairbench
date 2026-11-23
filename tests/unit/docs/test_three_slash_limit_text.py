# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the path inside a word that starts with three ``/`` or more.

In a shell text, in the value of an option or a variable and in the query of an address, a
path that starts with three ``/`` or more is not read as a path, so the shown command keeps
its folders. The security policy lists this among the known limits of the shown command with
the advice to write the path with one ``/`` at its start, and the config reference points at
it. An argument that starts so is cut, and so is a path inside a word that starts with one or
two ``/``. The hashes read every form as typed. Every folder name here is made up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
CONFIG = "docs/reference/config.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A path that starts with three `/` or more inside a word.** In a shell text, in the value "
    "of an option or a variable and in the query of an address, a path that starts with three "
    "`/` or more is not read as a path, so its folders show as typed: "
    "`sh -c 'cat ///made/up/x.txt'`, `--in=///made/up/x.txt` and "
    "`https://made-up.example/v1?file=///made/up/x.txt` show the folders. An argument that starts "
    "so is cut (`cat ///made/up/x.txt` shows `cat x.txt`), and so is a path inside a word that "
    "starts with one or two `/` (`--in=//made/up/x.txt` shows `--in=x.txt`); write the path with "
    "one `/` at its start."
)
POINTER = (
    "but a path inside a word that starts with three `/` or more, as in `--in=///made/up/x.txt`, "
    "is not read as a path, so its folders show, as the "
    "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say."
)
FOLDERS = ("made", "up")
# The forms the limit names whose folders show, and what the shown command holds of each.
SHOWN = (
    (("sh", "-c", "cat ///made/up/x.txt"), "sh -c 'cat ///made/up/x.txt'"),
    (("tool", "--in=///made/up/x.txt"), "tool --in=///made/up/x.txt"),
    (("env", "DATA=///made/up/x.txt", "tool"), "env DATA=///made/up/x.txt tool"),
    (
        ("curl", "https://made-up.example/v1?file=///made/up/x.txt"),
        "curl 'https://<hidden>/v1?file=///made/up/x.txt'",
    ),
    (
        ("psql", "postgresql:///db?sslrootcert=///made/up/ca.pem"),
        "psql 'postgresql:///db?sslrootcert=///made/up/ca.pem'",
    ),
    (
        ("psql", "postgresql://db.example/db?sslrootcert=///made/up/ca.pem"),
        "psql 'postgresql://<hidden>/db?sslrootcert=///made/up/ca.pem'",
    ),
    (
        ("psql", "postgresql://db.example/db?a=b;sslrootcert=///made/up/ca.pem"),
        "psql 'postgresql://<hidden>/db?a=b;sslrootcert=///made/up/ca.pem'",
    ),
)
# The forms the limit says are cut, and what the shown command holds of each.
CUT = (
    (("cat", "///made/up/x.txt"), "cat x.txt"),
    (("tool", "--in=//made/up/x.txt"), "tool --in=x.txt"),
    (("tool", "--in=/made/up/x.txt"), "tool --in=x.txt"),
    (("sh", "-c", "cat //made/up/x.txt"), "sh -c 'cat x.txt'"),
)


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_config_reference_points_at_the_limit(repo_root: Path) -> None:
    assert POINTER in " ".join((repo_root / CONFIG).read_text(encoding="utf-8").split())


@pytest.mark.parametrize(("args", "shown"), SHOWN)
def test_each_form_the_limit_names_shows_its_folders(args: tuple[str, ...], shown: str) -> None:
    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == list(args)


@pytest.mark.parametrize(("args", "shown"), CUT)
def test_each_form_the_limit_says_is_cut_shows_its_last_part(
    args: tuple[str, ...], shown: str
) -> None:
    command = model.public_command(args)

    assert command == shown
    assert not any(f"{folder}/" in str(command) for folder in FOLDERS)
    assert model.hashed_argv(args) == list(args)
