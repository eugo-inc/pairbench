# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Hexadecimal of a commit id's length between two ``/`` is a commit id only after its folder.

A path pinned to a commit, as a code host or a model hub writes it, names the
commit right after one of the folders of ``COMMIT_ID_FOLDERS``
(``org/repo/commit/<id>``, ``org/Model-3B/resolve/<id>/config``), and the id
stays shown. Elsewhere between two ``/``, as a token in the path of a hook's
address is written, hexadecimal of ``COMMIT_ID_LENGTH`` is hidden as
hexadecimal of any other length is, shown and hashed alike. A value of that
length on its own is a commit id and stays shown. Every value here is made up.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

HEX = "0badc0de" * 5

# A path pinned to a commit: shown as typed, and hashed as typed.
PINNED = (
    f"made-up-org/made-up-repo/commit/{HEX}",
    f"made-up-org/made-up-repo/commits/{HEX}",
    f"made-up-org/made-up-repo/tree/{HEX}/src",
    f"made-up-org/made-up-repo/blob/{HEX}/src/main.py",
    f"made-up-org/made-up-repo/archive/{HEX}.tar.gz",
    f"made-up-org/Model-3B/resolve/{HEX}/config.json",
    f"models--made-up-org--Model-3B/snapshots/{HEX}/config.json",
    f"http://localhost:8000/made-up-org/made-up-repo/blob/{HEX}/src/main.py",
    f"--rev=made-up-org/made-up-repo/tree/{HEX}",
)


@pytest.mark.parametrize("value", PINNED)
def test_a_commit_id_after_its_folder_is_shown(value: str) -> None:
    for argv in (["client", value], ["sh", "-c", f"client {value} && echo ok"]):
        assert model.public_command(argv) == shlex.join(argv)
        assert model.hashed_argv(argv) == argv


# A value of a commit id's length on its own, glued to an option of one letter, or after an
# ``@`` of a pinned package: shown as typed.
ALONE = (
    ("git", "checkout", HEX),
    ("client", f"-c{HEX}"),
    ("pip", "install", f"git+http://localhost:8000/made-up-org/made-up-repo@{HEX}"),
)


@pytest.mark.parametrize("argv", ALONE)
def test_a_commit_id_on_its_own_is_shown(argv: tuple[str, ...]) -> None:
    assert model.public_command(argv) == shlex.join(argv)
    assert model.hashed_argv(argv) == list(argv)


# Hexadecimal of a commit id's length between two `/` after no such folder: the value, how the
# shown command shows it and how the hash reads it.
HIDDEN = (
    (
        f"--webhook=https://hooks.example.com/{HEX}/notify",
        f"--webhook=https://{model.HIDDEN}/{model.HIDDEN}/notify",
        f"--webhook=https://hooks.example.com/{model.HIDDEN}/notify",
    ),
    (
        f"http://localhost:8000/v1/hooks/{HEX}/notify",
        f"http://localhost:8000/v1/hooks/{model.HIDDEN}/notify",
        f"http://localhost:8000/v1/hooks/{model.HIDDEN}/notify",
    ),
    (
        f"data/{HEX}/out.json",
        f"data/{model.HIDDEN}/out.json",
        f"data/{model.HIDDEN}/out.json",
    ),
    (
        f"made-up-org/made-up-repo/{HEX}",
        f"made-up-org/made-up-repo/{model.HIDDEN}",
        f"made-up-org/made-up-repo/{model.HIDDEN}",
    ),
    (
        f"/srv/hooks/{HEX}/out.json",
        f"{model.HIDDEN}.json",
        f"{model.HIDDEN}.json",
    ),
)


@pytest.mark.parametrize(("value", "shown", "hashed"), HIDDEN)
def test_hexadecimal_of_a_commit_id_s_length_after_no_such_folder_is_hidden(
    value: str, shown: str, hashed: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", hashed]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


def test_the_reference_page_names_each_folder_of_a_commit_id(repo_root: Path) -> None:
    text = " ".join((repo_root / "docs" / "reference" / "config.md").read_text("utf-8").split())
    folders = ", ".join(f"`{folder}`" for folder in model.COMMIT_ID_FOLDERS[:-1])
    assert (
        f"right after one of the folders {folders} or `{model.COMMIT_ID_FOLDERS[-1]}` "
        "(`COMMIT_ID_FOLDERS`)"
    ) in text
