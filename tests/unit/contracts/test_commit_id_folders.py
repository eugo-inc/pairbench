# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Hexadecimal of a commit id's length between two ``/`` is a commit id only after its folder.

A path pinned to a commit, as a code host or a model hub writes it, names the
commit right after one of the folders of ``COMMIT_ID_FOLDERS``
(``org/repo/commit/<id>``, ``org/Model-3B/resolve/<id>/config``), and the id
stays shown. Elsewhere between two ``/``, as a token in the path of a hook's
address is written, hexadecimal of ``COMMIT_ID_LENGTH`` is hidden as
hexadecimal of any other length is, shown and hashed alike. So it is at the
start of a query parameter, its value or the fragment of an address when a
``.`` joins it to a path after it, as a part of that path (``?<id>./../b``);
any other run there, a UUID among them, is read as it is anywhere in a query.
A value of that length on its own is a commit id and stays shown. Every value
here is made up.
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


# Hexadecimal of a commit id's length that starts a query parameter, its value or the fragment
# of an address and that a `.` joins to a path after it: the value, how the shown command shows
# it and how the hash reads it.
GLUED = (
    (
        f"https://made-up.example/x?{HEX}./../b",
        f"https://{model.HIDDEN}/x?{model.HIDDEN}./../b",
        f"https://made-up.example/x?{model.HIDDEN}./../b",
    ),
    (
        f"postgresql:///db?k={HEX}./../b",
        f"postgresql:///db?k={model.HIDDEN}./../b",
        f"postgresql:///db?k={model.HIDDEN}./../b",
    ),
    (
        f"postgresql://[fd00::1]/db?k=1&{HEX}.x/../b",
        f"postgresql://{model.HIDDEN}/db?k=1&{model.HIDDEN}.x/../b",
        f"postgresql://[fd00::1]/db?k=1&{model.HIDDEN}.x/../b",
    ),
    (
        f"https://made-up.example/x&{HEX}./../b",
        f"https://{model.HIDDEN}/x&{model.HIDDEN}./../b",
        f"https://made-up.example/x&{model.HIDDEN}./../b",
    ),
    (
        f"postgresql:///db?-l{HEX}./b",
        f"postgresql:///db?-l{model.HIDDEN}./b",
        f"postgresql:///db?-l{model.HIDDEN}./b",
    ),
    (
        f"s3://made-up-bucket#0x{HEX}./b",
        f"s3://{model.HIDDEN}#{model.HIDDEN}./b",
        f"s3://made-up-bucket#{model.HIDDEN}./b",
    ),
)


@pytest.mark.parametrize(("value", "shown", "hashed"), GLUED)
def test_a_commit_id_s_length_joined_to_a_path_in_a_query_is_hidden(
    value: str, shown: str, hashed: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.public_command(["client", f"--opt={value}"]) == shlex.join(
        ["client", f"--opt={shown}"]
    )
    assert model.public_command(["sh", "-c", f"client '{value}'"]) == shlex.join(
        ["sh", "-c", f"client {shlex.quote(shown)}"]
    )
    assert model.hashed_argv(["client", value]) == ["client", hashed]
    assert model.public_words(f"client {shlex.quote(value)}", case=True) == f"client {shown}"


def test_two_commands_that_differ_only_in_a_hidden_glued_value_hash_alike() -> None:
    one = ["curl", f"https://made-up.example/x?{HEX}./../b"]
    two = ["curl", f"https://made-up.example/x?{'0ddba11' * 5}fade1./../b"]
    hashed = ["curl", f"https://made-up.example/x?{model.HIDDEN}./../b"]

    assert model.hashed_argv(one) == hashed
    assert model.hashed_argv(two) == hashed
    assert model.hidden_difference(
        {"side": {"kind": "command"}, "launch": None, "argv": one},
        {"side": {"kind": "command"}, "launch": None, "argv": two},
    )


# Rows of `GLUED` with no `&` or `#`, in a shell text with no quotes around the address: the
# value and how the shown command shows it.
GLUED_UNQUOTED = (
    (f"https://made-up.example/x?{HEX}./../b", f"https://{model.HIDDEN}/x?{model.HIDDEN}./../b"),
    (f"postgresql:///db?k={HEX}./../b", f"postgresql:///db?k={model.HIDDEN}./../b"),
    (f"postgresql:///db?-l{HEX}./b", f"postgresql:///db?-l{model.HIDDEN}./b"),
)


@pytest.mark.parametrize(("value", "shown"), GLUED_UNQUOTED)
def test_a_commit_id_s_length_joined_to_a_path_in_an_unquoted_shell_text_is_hidden(
    value: str, shown: str
) -> None:
    assert model.public_command(["sh", "-c", f"client {value}"]) == shlex.join(
        ["sh", "-c", f"client {shown}"]
    )


# Any other run in the same place is read as it is anywhere in a query: a UUID, also inside a
# name, is an id, and a token of a commit id's length past its option letter is not
# random-looking. The value and how the shown command shows it; each is hashed as typed.
GLUED_SHOWN = (
    (
        "postgresql:///db#Bench_db5b5fab-8f4d-3e27-dda1-494c73cf256d_FP16./../b",
        "postgresql:///db#Bench_db5b5fab-8f4d-3e27-dda1-494c73cf256d_FP16./../b",
    ),
    (
        "postgresql:///db?k=3503E43E-E923-44F5-855C-EB46DF949F7A-v2./../b",
        "postgresql:///db?k=3503E43E-E923-44F5-855C-EB46DF949F7A-v2./../b",
    ),
    (
        "file:///a/b?-l3icfZGPRobmwdnAwmdMEc8ugnqezB0./../b",
        "file://b?-l3icfZGPRobmwdnAwmdMEc8ugnqezB0./../b",
    ),
)


@pytest.mark.parametrize(("value", "shown"), GLUED_SHOWN)
def test_another_run_joined_to_a_path_in_a_query_is_read_as_elsewhere(
    value: str, shown: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.public_command(["client", f"--opt={value}"]) == shlex.join(
        ["client", f"--opt={shown}"]
    )
    assert model.public_command(["sh", "-c", f"client {value}"]) == shlex.join(
        ["sh", "-c", f"client {shown}"]
    )
    assert model.public_command(["sh", "-c", f"client '{value}'"]) == shlex.join(
        ["sh", "-c", f"client {shlex.quote(shown)}"]
    )
    assert model.hashed_argv(["client", value]) == ["client", value]
    assert model.public_words(f"client {shlex.quote(value)}", case=True) == f"client {shown}"


# The same value with no path after it, or after the name of a digest, or outside an address:
# a commit id or a digest, shown as typed. A free text shows the value of a commit id's length
# as typed there too, and so does a case id in an address with no host.
QUERY_SHOWN = (
    f"https://made-up.example/x?ref={HEX}",
    f"https://made-up.example/x?{HEX}",
    f"https://made-up.example/x?{HEX}.json",
    f"https://made-up.example/x?sha1={HEX}./../b",
    f"k={HEX}./b",
)


@pytest.mark.parametrize("value", QUERY_SHOWN)
def test_a_commit_id_in_a_query_with_no_path_joined_to_it_is_shown(value: str) -> None:
    argv = ["client", value]
    assert model.public_command(argv).replace(model.HIDDEN, "made-up.example") == shlex.join(argv)
    assert model.hashed_argv(argv) == argv


def test_a_free_text_and_a_case_id_show_a_commit_id_joined_to_a_path() -> None:
    value = f"postgresql:///db?k={HEX}./../b"
    assert model.public_text(value) == value
    assert model.public_case(f"test_conn[{value}]") == f"test_conn[{value}]"


def test_the_reference_page_names_each_folder_of_a_commit_id(repo_root: Path) -> None:
    text = " ".join((repo_root / "docs" / "reference" / "config.md").read_text("utf-8").split())
    folders = ", ".join(f"`{folder}`" for folder in model.COMMIT_ID_FOLDERS[:-1])
    assert (
        f"right after one of the folders {folders} or `{model.COMMIT_ID_FOLDERS[-1]}` "
        "(`COMMIT_ID_FOLDERS`)"
    ) in text
