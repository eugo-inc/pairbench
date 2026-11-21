# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A word after a scheme word that is a credential's whole value still tells sides apart.

The shown command and the published hashes hide the word after an
Authorization scheme word given as a credential's whole value
(``--auth basic WORD``, ``AUTH=token WORD``), as a token may stand there. The
comparison of two setups (``hidden_difference``) reads that word as typed, so
two setups that differ there are two sides: the word may be a program, an
image or a model file. A token after a scheme word given in the same argument
(``--token 'Bearer VALUE'``) stays the credential, and rotating it keeps one
side.
"""

from __future__ import annotations

from typing import Any

import pytest

from pairbench.model import hashed_argv, hidden_difference, side_setup

OLD, NEW = "kiwi7zq", "plum4zq"


def _setups(one: list[str], two: list[str]) -> tuple[Any, Any]:
    config = {"sides": {"a": {"cmd": one}, "b": {"cmd": two, "baseline": True}}}
    return side_setup(config, "a"), side_setup(config, "b")


def _two_sides(one: list[str], two: list[str]) -> bool:
    """Whether the two commands are two sides: their hashes differ, or a hidden value does."""
    return hashed_argv(one) != hashed_argv(two) or hidden_difference(*_setups(one, two))


# Pairs that differ only in the word after a scheme word that is a credential's whole value.
NEIGHBOURS = {
    "env-program": (
        ["env", "AUTH=token", "./made-up-old", "--port", "8000"],
        ["env", "AUTH=token", "./made-up-new", "--port", "8000"],
    ),
    "env-authorization-program": (
        ["env", "AUTHORIZATION=Bearer", "./made-up-old"],
        ["env", "AUTHORIZATION=Bearer", "./made-up-new"],
    ),
    "shell-text-program": (
        ["sh", "-c", "AUTH=basic ./made-up-old --n 8"],
        ["sh", "-c", "AUTH=basic ./made-up-new --n 8"],
    ),
    "docker-e-image": (
        ["docker", "run", "-e", "AUTH=basic", "made-up/old:1", "serve"],
        ["docker", "run", "-e", "AUTH=basic", "made-up/new:1", "serve"],
    ),
    "docker-e-glued-image": (
        ["docker", "run", "-eAUTH_TOKEN=Bearer", "made-up/old:1", "serve"],
        ["docker", "run", "-eAUTH_TOKEN=Bearer", "made-up/new:1", "serve"],
    ),
    "next-argument-model": (
        ["./made-up-bench", "--auth", "basic", "model-old.gguf"],
        ["./made-up-bench", "--auth", "basic", "model-new.gguf"],
    ),
    "glued-option-model": (
        ["./made-up-bench", "--auth=basic", "model-old.gguf"],
        ["./made-up-bench", "--auth=basic", "model-new.gguf"],
    ),
    "password-word-model": (
        ["./made-up-bench", "--password", "token", "model-old.gguf"],
        ["./made-up-bench", "--password", "token", "model-new.gguf"],
    ),
    "shell-text-option-model": (
        ["sh", "-c", "./made-up-bench --api-key=Bearer model-old.gguf"],
        ["sh", "-c", "./made-up-bench --api-key=Bearer model-new.gguf"],
    ),
    "value-text-model": (
        ["env", "MADE_UP_FLAGS=--auth basic model-old.gguf", "./made-up-bench"],
        ["env", "MADE_UP_FLAGS=--auth basic model-new.gguf", "./made-up-bench"],
    ),
    "split-token": (
        ["./made-up-bench", "--token", "Bearer", OLD, "-n", "8"],
        ["./made-up-bench", "--token", "Bearer", NEW, "-n", "8"],
    ),
}


@pytest.mark.parametrize(("one", "two"), list(NEIGHBOURS.values()), ids=list(NEIGHBOURS))
def test_a_word_after_a_whole_value_scheme_word_tells_two_sides_apart(
    one: list[str], two: list[str]
) -> None:
    assert _two_sides(one, two) is True


# Pairs that differ only in a token given in the same argument as its scheme word.
ROTATED = {
    "next-argument": (
        ["./made-up-bench", "--token", f"Bearer {OLD}", "model.gguf"],
        ["./made-up-bench", "--token", f"Bearer {NEW}", "model.gguf"],
    ),
    "glued-option": (
        ["./made-up-bench", f"--auth=Basic {OLD}", "model.gguf"],
        ["./made-up-bench", f"--auth=Basic {NEW}", "model.gguf"],
    ),
    "env-assignment": (
        ["env", f"AUTHORIZATION=Bearer {OLD}", "./made-up-bench"],
        ["env", f"AUTHORIZATION=Bearer {NEW}", "./made-up-bench"],
    ),
    "docker-e-assignment": (
        ["docker", "run", "-e", f"AUTHORIZATION=Bearer {OLD}", "made-up/image:1", "serve"],
        ["docker", "run", "-e", f"AUTHORIZATION=Bearer {NEW}", "made-up/image:1", "serve"],
    ),
    "shell-text-assignment": (
        ["sh", "-c", f"AUTHORIZATION='Bearer {OLD}' ./made-up-bench"],
        ["sh", "-c", f"AUTHORIZATION='Bearer {NEW}' ./made-up-bench"],
    ),
    "shell-text-double-quoted-assignment": (
        ["sh", "-c", f'AUTHORIZATION="Bearer {OLD}" ./made-up-bench'],
        ["sh", "-c", f'AUTHORIZATION="Bearer {NEW}" ./made-up-bench'],
    ),
    "shell-text-export": (
        ["bash", "-c", f"export AUTHORIZATION='Bearer {OLD}'; ./made-up-bench"],
        ["bash", "-c", f"export AUTHORIZATION='Bearer {NEW}'; ./made-up-bench"],
    ),
    "shell-text-glued-option": (
        ["sh", "-c", f"./made-up-bench --auth='Basic {OLD}'"],
        ["sh", "-c", f"./made-up-bench --auth='Basic {NEW}'"],
    ),
    "shell-text-next-argument": (
        ["sh", "-c", f"./made-up-bench --token 'Bearer {OLD}'"],
        ["sh", "-c", f"./made-up-bench --token 'Bearer {NEW}'"],
    ),
    "value-text-next-argument": (
        ["env", f"MADE_UP_FLAGS=--token 'Bearer {OLD}'", "./made-up-bench"],
        ["env", f"MADE_UP_FLAGS=--token 'Bearer {NEW}'", "./made-up-bench"],
    ),
    "code-assignment": (
        ["python3", "-c", f"token = 'Bearer {OLD}'; run()"],
        ["python3", "-c", f"token = 'Bearer {NEW}'; run()"],
    ),
}


@pytest.mark.parametrize(("one", "two"), list(ROTATED.values()), ids=list(ROTATED))
def test_a_token_in_the_argument_of_its_scheme_word_keeps_one_side(
    one: list[str], two: list[str]
) -> None:
    assert _two_sides(one, two) is False
