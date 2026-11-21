# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Which differences between two recorded setups count as real, though the hashes hide them.

A value given to a credential-like name, or a client's password glued to its
option, is hidden in the hashes to the end of its argument, spaces included.
The words after its first space are still part of what a side runs, so two
setups that differ in them differ for ``hidden_difference``: plan and run keep
two such sides apart and pooling refuses such captures. A difference in the
value itself, up to its first space, is a difference in a secret only. In a
command text, as the remote command of ``ssh``, the hashes end such a value at
its first blank, so the words after it set two commands apart in the hashes
themselves.
"""

from __future__ import annotations

from typing import Any

import pytest

from pairbench.model import hashed_argv, hidden_difference, side_setup


def _command(argv: list[str]) -> dict[str, Any] | None:
    return side_setup({"sides": {"x": {"cmd": argv}}}, "x")


def _image(args: list[str]) -> dict[str, Any] | None:
    return side_setup({"sides": {"x": {"image": "made-up/image:1", "args": args}}}, "x")


# Two arguments each, alike up to the first space of a hidden value and different after it.
TAILS = {
    "glued-client-password": (["mysql", "-pa b"], ["mysql", "-pa c"]),
    "option-with-equals": (
        ["made-up-tool", "--api-key=k one"],
        ["made-up-tool", "--api-key=k two"],
    ),
    "client-user-password": (["ab", "-Auser:pw x"], ["ab", "-Auser:pw y"]),
    "variable-in-an-option": (
        ["made-up-tool", "--env=MY_TOKEN=a b"],
        ["made-up-tool", "--env=MY_TOKEN=a c"],
    ),
}

# Two command texts each, alike up to the first blank of a hidden value and different after
# it, and what the hashes read of the first.
TEXT_TAILS = {
    "ssh-text": (
        ["ssh", "h", "HF_TOKEN=t ./bench-old"],
        ["ssh", "h", "HF_TOKEN=t ./bench-new"],
        ["ssh", "h", "HF_TOKEN=<hidden> ./bench-old"],
    ),
    "env-split": (
        ["env", "-S", "HF_TOKEN=t ./bench-old"],
        ["env", "-S", "HF_TOKEN=t ./bench-new"],
        ["env", "-S", "HF_TOKEN=<hidden> ./bench-old"],
    ),
    "hyperfine-text": (
        ["hyperfine", "HF_TOKEN=t ./bench-old"],
        ["hyperfine", "HF_TOKEN=t ./bench-new"],
        ["hyperfine", "HF_TOKEN=<hidden> ./bench-old"],
    ),
}

# Two arguments each that differ only in the hidden value, up to its first space.
VALUES = {
    "ssh-text": (["ssh", "h", "HF_TOKEN=kiwi7 ./bench"], ["ssh", "h", "HF_TOKEN=plum4 ./bench"]),
    "glued-client-password": (["mysql", "-pkiwi7 b"], ["mysql", "-pplum4 b"]),
    "option-with-equals": (
        ["made-up-tool", "--api-key=kiwi7 one"],
        ["made-up-tool", "--api-key=plum4 one"],
    ),
    "client-user-password": (["ab", "-Auser:kiwi7 x"], ["ab", "-Auser:plum4 x"]),
    "quoted-value": (
        ["ssh", "h", "HF_TOKEN='kiwi7' ./bench"],
        ["ssh", "h", "HF_TOKEN='plum4' ./bench"],
    ),
    "env-split": (["env", "-S", "HF_TOKEN=kiwi7 ./bench"], ["env", "-S", "HF_TOKEN=plum4 ./bench"]),
    "hyperfine-text": (
        ["hyperfine", "HF_TOKEN=kiwi7 ./bench"],
        ["hyperfine", "HF_TOKEN=plum4 ./bench"],
    ),
    "variable-in-an-option": (
        ["made-up-tool", "--env=MY_TOKEN=kiwi7 b"],
        ["made-up-tool", "--env=MY_TOKEN=plum4 b"],
    ),
    "variable-glued-to-an-option": (
        ["made-up-tool", "-eMY_TOKEN=kiwi7 b"],
        ["made-up-tool", "-eMY_TOKEN=plum4 b"],
    ),
    "user-password-glued": (
        ["made-up-tool", "--user=user:kiwi7 x"],
        ["made-up-tool", "--user=user:plum4 x"],
    ),
    "client-option-with-equals": (
        ["mongosh", "--authenticate=kiwi7 x"],
        ["mongosh", "--authenticate=plum4 x"],
    ),
    "same-words-after-a-spaced-password": (
        ["env", "DB_PASSWORD=kiwi7 b c", "true"],
        ["env", "DB_PASSWORD=plum4 b c", "true"],
    ),
    "header-in-a-command-text": (
        ["sh", "-c", "curl -H 'Authorization: Bearer kiwi7' http://localhost/"],
        ["sh", "-c", "curl -H 'Authorization: Bearer plum4' http://localhost/"],
    ),
}


@pytest.mark.parametrize(("one", "two"), list(TAILS.values()), ids=list(TAILS))
def test_words_after_the_first_space_of_a_hidden_value_set_two_commands_apart(
    one: list[str], two: list[str]
) -> None:
    assert hashed_argv(one) == hashed_argv(two)

    assert hidden_difference(_command(one), _command(two)) is True
    assert hidden_difference(_command(two), _command(one)) is True


@pytest.mark.parametrize(("one", "two", "hashed"), list(TEXT_TAILS.values()), ids=list(TEXT_TAILS))
def test_words_after_the_first_blank_of_a_hidden_value_in_a_command_text_are_hashed(
    one: list[str], two: list[str], hashed: list[str]
) -> None:
    assert hashed_argv(one) == hashed
    assert hashed_argv(two) == [*hashed[:-1], hashed[-1].replace("old", "new")]

    assert hidden_difference(_command(one), _command(two)) is False


@pytest.mark.parametrize(("one", "two"), list(VALUES.values()), ids=list(VALUES))
def test_a_hidden_value_up_to_its_first_space_sets_no_two_commands_apart(
    one: list[str], two: list[str]
) -> None:
    assert hashed_argv(one) == hashed_argv(two)

    assert hidden_difference(_command(one), _command(two)) is False
    assert hidden_difference(_command(two), _command(one)) is False


def test_words_after_a_hidden_value_in_an_image_side_s_arguments_set_two_sides_apart() -> None:
    one = _image(["HF_TOKEN=t made-up-server --model a"])
    two = _image(["HF_TOKEN=t made-up-server --model b"])

    assert hidden_difference(one, two) is True


def test_a_hidden_value_alone_in_an_image_side_s_arguments_sets_no_two_sides_apart() -> None:
    one = _image(["HF_TOKEN=kiwi7 made-up-server --model a"])
    two = _image(["HF_TOKEN=plum4 made-up-server --model a"])

    assert hidden_difference(one, two) is False


def test_equal_setups_with_a_hidden_value_differ_in_nothing() -> None:
    one = _command(["ssh", "h", "HF_TOKEN=t ./bench-old"])

    assert hidden_difference(one, one) is False
