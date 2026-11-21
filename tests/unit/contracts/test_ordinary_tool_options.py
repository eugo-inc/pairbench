# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Ordinary options of benchmark tools that name a key or a token are shown.

A key or a token followed by a measure, a range, a rate, a kind or another
treatment (``--keybits``, ``--keyrange_num``, ``--key-type``,
``--token-rate``, ``--token-healing``), or after a word that counts, groups
or seeds them (``MAX_TOKEN``, ``--multi-key-get``, ``--merge_keys``,
``--seed-token``), names no credential: its value is shown, and two values
make two sides. So does ``--token-file`` written apart and alone; glued
(``TOKENFILE``) or after another word (``HF_TOKEN_FILE``) it stays a
credential. A credential word in such a name, and a credential option after
it, still hide. An NVBench axis named ``Key`` or ``Keys`` glued to its
option is shown as it is after the option, except where a client's own
option takes a password.
"""

from __future__ import annotations

import pytest

from pairbench.model import hashed_argv, looks_like_credential, public_command

# A made-up secret.
SECRET = "kiwi7zq"
BENCH = "./made-up-bench"

SHOWN_NAMES = (
    "--multi-key-get",
    "--key_id_range",
    "--keyrange_num",
    "--keyrange_dist_a",
    "--keyrange_dist_b",
    "--keyrange_dist_c",
    "--keyrange_dist_d",
    "--merge_keys",
    "--use_existing_keys",
    "--key-type",
    "--keybits",
    "KEYBITS",
    "MAXTOKEN",
    "MAX_TOKEN",
    "--token-rate",
    "--token-file",
    "--seed-token",
    "--token-healing",
    # The same words in other spellings.
    "key_type",
    "KEYTYPE",
    "--key-bits",
    "KEY_BITS",
    "--keyrange",
    "--key-id-range",
    "--token_id_range",
    "--tokenrate",
    "TOKEN_TYPE",
    "SEED_TOKEN",
    "MERGE_KEY",
    "--use-existing-key",
    "--multi-key",
    "MIN_TOKEN",
    "NUM_TOKEN",
    "--ssh-key-type",
    "TOKEN_FILE",
    "token.file",
    "tokenFile",
)
HIDDEN_NAMES = (
    # A key or a token with its id names a credential.
    "KEY_ID",
    "--key-id",
    "--key_id",
    "--key-ids",
    "TOKEN_ID",
    "AWS_ACCESS_KEY_ID",
    # A file of a key, and a file of a token glued to it or after another word.
    "--key-file",
    "KEYFILE",
    "TOKENFILE",
    "--tokenfile",
    "HF_TOKEN_FILE",
    "HF_TOKENFILE",
    "--api-token-file",
    "--auth-token-file",
    "--token-file-path",
    # A credential word before the key or the token.
    "--api-key-type",
    "--private-key-type",
    "--secret-key-type",
    "--access-token-rate",
    "--auth-token-type",
    "--api-token-healing",
    "--api_key_id_range",
    "MAX_API_TOKEN",
    "MAXAPITOKEN",
    "MULTI_API_KEY",
    # A credential word after them.
    "--key-type-secret",
    "--keybits-secret",
    "KEYBITSPASSWORD",
    "--keyrange-secret",
    "--token-rate-secret",
    "--token-healing-key",
    "--seed-token-password",
    "--merge-keys-password",
    "MAX_TOKEN_SECRET",
    "MAXTOKENSECRET",
)


@pytest.mark.parametrize("name", SHOWN_NAMES)
def test_an_ordinary_key_or_token_option_of_a_tool_is_no_credential(name: str) -> None:
    assert looks_like_credential(name) is False


@pytest.mark.parametrize("name", HIDDEN_NAMES)
def test_a_credential_beside_those_names_is_still_a_credential(name: str) -> None:
    assert looks_like_credential(name) is True


# The names a tool takes as options, and the names a side sets as variables.
OPTION_NAMES = tuple(name for name in SHOWN_NAMES[:18] if name.startswith("-"))
VARIABLE_NAMES = ("KEYBITS", "MAXTOKEN", "MAX_TOKEN", "TOKEN_FILE")


@pytest.mark.parametrize("name", OPTION_NAMES)
def test_the_value_of_such_an_option_is_shown_and_tells_two_sides_apart(name: str) -> None:
    for argv in ([BENCH, name, "4"], [BENCH, f"{name}=4"]):
        assert public_command(argv) == " ".join(argv)
        assert hashed_argv(argv) == argv
    assert hashed_argv([BENCH, name, "4"]) != hashed_argv([BENCH, name, "8"])
    assert hashed_argv([BENCH, f"{name}=4"]) != hashed_argv([BENCH, f"{name}=8"])


@pytest.mark.parametrize("name", VARIABLE_NAMES)
def test_the_value_of_such_a_variable_is_shown_and_tells_two_sides_apart(name: str) -> None:
    argv = ["env", f"{name}=4", BENCH]
    assert public_command(argv) == f"env {name}=4 {BENCH}"
    assert hashed_argv(argv) == argv
    assert hashed_argv(argv) != hashed_argv(["env", f"{name}=8", BENCH])


def test_a_token_file_shows_only_the_last_part_of_its_path() -> None:
    argv = [BENCH, "--token-file", "/made/up/folder/tokens.txt"]
    assert public_command(argv) == f"{BENCH} --token-file tokens.txt"
    assert hashed_argv(argv) != hashed_argv([BENCH, "--token-file", "/made/up/folder/other.txt"])


@pytest.mark.parametrize("name", OPTION_NAMES)
def test_a_password_option_after_such_an_option_is_still_hidden(name: str) -> None:
    argv = [BENCH, name, "4", "--password", SECRET]
    assert public_command(argv) == f"{BENCH} {name} 4 --password '<hidden>'"
    assert hashed_argv(argv) == [BENCH, name, "4", "--password", "<hidden>"]


# Each row: the axis as typed, the command the shared files show, and the axis a second
# side gives.
AXIS_SHOWN = {
    "long-glued": ("--axis=Key=I32", f"{BENCH} --axis=Key=I32", "--axis=Key=I64"),
    "short-glued": ("-aKey=I32", f"{BENCH} -aKey=I32", "-aKey=I64"),
    "keys-long-glued": ("--axis=Keys=4", f"{BENCH} --axis=Keys=4", "--axis=Keys=8"),
    "keys-short-glued": ("-aKeys=4", f"{BENCH} -aKeys=4", "-aKeys=8"),
    "flags-long-glued": (
        "--axis=Key[pow2]=4",
        f"{BENCH} '--axis=Key[pow2]=4'",
        "--axis=Key[pow2]=8",
    ),
    "flags-short-glued": ("-aKey[pow2]=4", f"{BENCH} '-aKey[pow2]=4'", "-aKey[pow2]=8"),
    "list-long-glued": ("--axis=Key=I32,I64", f"{BENCH} --axis=Key=I32,I64", "--axis=Key=I32"),
}


@pytest.mark.parametrize(
    ("axis", "shown", "other"), list(AXIS_SHOWN.values()), ids=list(AXIS_SHOWN)
)
def test_a_key_axis_glued_to_its_option_is_shown_and_tells_two_sides_apart(
    axis: str, shown: str, other: str
) -> None:
    assert public_command([BENCH, axis]) == shown
    assert hashed_argv([BENCH, axis]) == [BENCH, axis]
    assert hashed_argv([BENCH, axis]) != hashed_argv([BENCH, other])


# Each row: the argument list, the command the shared files show, and the list every
# published hash reads.
AXIS_HIDDEN = {
    "client-password": (
        ["redis-cli", f"-aKey={SECRET}", "ping"],
        "redis-cli '-a<hidden>' ping",
        ["redis-cli", "-a<hidden>", "ping"],
    ),
    "benchmark-client-password": (
        ["redis-benchmark", f"-aKey={SECRET}"],
        "redis-benchmark '-a<hidden>'",
        ["redis-benchmark", "-a<hidden>"],
    ),
    "load-client-password": (
        ["memtier_benchmark", f"-aKey={SECRET}"],
        "memtier_benchmark '-a<hidden>'",
        ["memtier_benchmark", "-a<hidden>"],
    ),
    "wrapped-client-password": (
        ["env", "redis-cli", f"-aKey={SECRET}"],
        "env redis-cli '-a<hidden>'",
        ["env", "redis-cli", "-a<hidden>"],
    ),
    "token-axis": (
        [BENCH, f"--axis=Token={SECRET}"],
        f"{BENCH} '--axis=Token=<hidden>'",
        [BENCH, "--axis=Token=<hidden>"],
    ),
    "api-key-axis": (
        [BENCH, f"--axis=api_key={SECRET}"],
        f"{BENCH} '--axis=api_key=<hidden>'",
        [BENCH, "--axis=api_key=<hidden>"],
    ),
    "password-axis": (
        [BENCH, f"-aPassword={SECRET}"],
        f"{BENCH} '-aPassword=<hidden>'",
        [BENCH, "-aPassword=<hidden>"],
    ),
    "password-after-an-axis": (
        [BENCH, "--axis=Key=4", "--password", SECRET],
        f"{BENCH} --axis=Key=4 --password '<hidden>'",
        [BENCH, "--axis=Key=4", "--password", "<hidden>"],
    ),
}


@pytest.mark.parametrize(
    ("argv", "shown", "hashed"), list(AXIS_HIDDEN.values()), ids=list(AXIS_HIDDEN)
)
def test_a_password_in_or_after_an_axis_form_stays_hidden(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed
