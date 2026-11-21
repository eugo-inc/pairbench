# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every API key that vLLM's ``--api-key`` takes is hidden, shown and hashed.

The OpenAI-compatible server of vLLM takes one key or more after ``--api-key`` (and after
``--api_key``, which its parser reads as the same option), up to the next option. Each of
them is hidden, in the argument list, in a shell text and after a program that runs it, and
the hash of two commands that differ only in the keys is one. A key glued after ``=`` is the
option's only one, so the word after it is read as it stands, and so is the word after the one
value of any other program's ``--api-key``.
"""

from __future__ import annotations

import json

import pytest

from pairbench.model import HIDDEN, hashed_argv, public_command
from pairbench.sides.identity import argv_sha256

# Two sets of made-up keys.
KEYS = (
    ("made-up-key-1", "made-up-key-2", "made-up-key-3"),
    ("made-up-key-4", "made-up-key-5", "made-up-key-6"),
)

# Each form: the argument list with ``{a}``, ``{b}`` and ``{c}`` where the keys stand, and the
# command shown with the first set of keys.
FORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "two keys": (
        ("vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}"),
        "vllm serve org/model-a --api-key '<hidden>' '<hidden>'",
    ),
    "three keys before another option": (
        ("vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}", "{c}", "--port", "8000"),
        "vllm serve org/model-a --api-key '<hidden>' '<hidden>' '<hidden>' --port 8000",
    ),
    "the spelling with an underscore": (
        ("vllm", "serve", "org/model-a", "--api_key", "{a}", "{b}", "--port", "8000"),
        "vllm serve org/model-a --api_key '<hidden>' '<hidden>' --port 8000",
    ),
    "the option given twice": (
        ("vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}", "--api-key", "{c}"),
        "vllm serve org/model-a --api-key '<hidden>' '<hidden>' --api-key '<hidden>'",
    ),
    "the module of the server": (
        (
            "python3",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            "org/model-a",
            "--api-key",
            "{a}",
            "{b}",
            "--port",
            "8000",
        ),
        "python3 -m vllm.entrypoints.openai.api_server --model org/model-a"
        " --api-key '<hidden>' '<hidden>' --port 8000",
    ),
    "after env and an assignment": (
        ("env", "MADE_UP_LEVEL=1", "vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}"),
        "env MADE_UP_LEVEL=1 vllm serve org/model-a --api-key '<hidden>' '<hidden>'",
    ),
    "after nice": (
        ("nice", "-n", "5", "vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}"),
        "nice -n 5 vllm serve org/model-a --api-key '<hidden>' '<hidden>'",
    ),
    "in a shell text before an operator": (
        ("sh", "-c", "vllm serve org/model-a --api-key {a} {b} && ./made-up-bench"),
        "sh -c 'vllm serve org/model-a --api-key <hidden> <hidden> && ./made-up-bench'",
    ),
    "in a shell text before a glued separator": (
        ("sh", "-c", "vllm serve org/model-a --api-key {a} {b};./made-up-bench"),
        "sh -c 'vllm serve org/model-a --api-key <hidden> <hidden>;./made-up-bench'",
    ),
    "in a shell text before a redirection": (
        ("sh", "-c", "vllm serve org/model-a --api-key {a} {b} > made-up.log"),
        "sh -c 'vllm serve org/model-a --api-key <hidden> <hidden> > made-up.log'",
    ),
    "in the argument list of ssh, before a separator the remote shell reads": (
        (
            "ssh",
            "made-up-host",
            "vllm",
            "serve",
            "org/model-a",
            "--api-key",
            "{a}",
            "{b}",
            ";",
            "./made-up-bench",
        ),
        "ssh made-up-host vllm serve org/model-a --api-key '<hidden>' '<hidden>' ';'"
        " ./made-up-bench",
    ),
    "before the model, which the option takes as a key": (
        ("vllm", "serve", "--api-key", "{a}", "{b}", "{c}"),
        "vllm serve --api-key '<hidden>' '<hidden>' '<hidden>'",
    ),
    "a key glued after = is the only one": (
        ("vllm", "serve", "--api-key={a}", "org/model-a"),
        "vllm serve '--api-key=<hidden>' org/model-a",
    ),
    "another option that takes several words is read as it stands": (
        (
            "vllm",
            "serve",
            "org/model-a",
            "--api-key",
            "{a}",
            "--served-model-name",
            "made-up-a",
            "made-up-b",
        ),
        "vllm serve org/model-a --api-key '<hidden>' --served-model-name made-up-a made-up-b",
    ),
    "another program's --api-key takes one value": (
        ("./made-up-tool", "--api-key", "{a}", "made-up-out.json"),
        "./made-up-tool --api-key '<hidden>' made-up-out.json",
    ),
}


def typed(form: tuple[str, ...], keys: tuple[str, str, str]) -> list[str]:
    a, b, c = keys
    return [word.format(a=a, b=b, c=c) for word in form]


@pytest.mark.parametrize("name", FORMS)
def test_every_key_of_the_option_is_hidden_in_the_shown_command(name: str) -> None:
    form, shown = FORMS[name]

    assert public_command(typed(form, KEYS[0])) == shown


@pytest.mark.parametrize("name", FORMS)
def test_the_hash_reads_the_keys_as_the_shown_command_does(name: str) -> None:
    form, _shown = FORMS[name]
    hashed = hashed_argv(typed(form, KEYS[0]))

    assert not {key for key in KEYS[0] if key in json.dumps(hashed)}
    assert argv_sha256(typed(form, KEYS[0])) == argv_sha256(typed(form, KEYS[1]))


def test_the_hashed_words_are_the_typed_words_with_each_key_hidden() -> None:
    form = ("vllm", "serve", "org/model-a", "--api-key", "{a}", "{b}", "--port", "8000")

    assert hashed_argv(typed(form, KEYS[0])) == [
        "vllm",
        "serve",
        "org/model-a",
        "--api-key",
        HIDDEN,
        HIDDEN,
        "--port",
        "8000",
    ]


def test_two_servers_of_two_models_with_the_same_keys_hash_apart() -> None:
    old = ["vllm", "serve", "org/model-a", "--api-key", *KEYS[0][:2]]
    new = ["vllm", "serve", "org/model-b", "--api-key", *KEYS[0][:2]]

    assert argv_sha256(old) != argv_sha256(new)


@pytest.mark.parametrize(
    "args",
    [
        ("vllm", "serve", "org/model-a", "--api-key"),
        ("vllm", "serve", "org/model-a", "--api-key", "--port", "8000"),
    ],
)
def test_the_option_with_no_key_after_it_leaves_the_next_option_shown(
    args: tuple[str, ...],
) -> None:
    assert public_command(args) == " ".join(args)
