# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The pages say how the keys of vLLM's ``--api-key`` are hidden, and where they are not.

The config reference names the option in its table of clients and gives a paragraph whose
examples are run here through the cleaner and come out as the page shows them. The security
policy names a shortened option as a limit of the shown command, and the arguments of a
serving side read with no program as a limit of the hashes; each example is run here and does
what the policy says, so the page changes when the cleaner does.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model
from pairbench.sides.identity import argv_sha256

CONFIG = "docs/reference/config.md"
SECURITY = "SECURITY.md"
ROW = (
    "| `vllm`, `vllm.entrypoints.openai.api_server` | `--api-key VALUE VALUE`, "
    "`--api_key VALUE VALUE` | `--api-key <hidden> <hidden>` |"
)
# Each example of the config reference's paragraph: (typed, shown).
EXAMPLES = (
    (
        "vllm serve org/model-a --api-key VALUE VALUE --port 8000",
        "vllm serve org/model-a --api-key '<hidden>' '<hidden>' --port 8000",
    ),
    ("vllm serve --api-key=VALUE org/model-a", "vllm serve '--api-key=<hidden>' org/model-a"),
    (
        "./made-up-tool --api-key VALUE made-up-out.json",
        "./made-up-tool --api-key '<hidden>' made-up-out.json",
    ),
)
SHOWN_LIMIT = (
    "**A client's option written shorter than its name.** A client's password option is read by "
    "its whole name, as the config reference lists it. A parser such as Python's `argparse` also "
    "takes a long option shortened to a start that no other option of the program shares, and "
    "such a shortened option is not read as a password option, so the value after it shows: "
    "`vllm serve org/model-a --api-ke made-up-key` shows whole."
)
SHORTENED = "vllm serve org/model-a --api-ke made-up-key"
HASH_LIMIT = (
    "The arguments of a serving side are read with the program that `serve.command` names; with "
    "no `serve.command`, as for an image whose own entrypoint starts the server, they are read "
    "alone, and an option that takes several keys, such as the `--api-key` of the vLLM server, "
    "is read as one that takes one: of "
    '`serve.args = ["--model", "org/model-a", "--api-key", "KEY1", "KEY2"]` the config\'s hash '
    "covers `KEY2` as typed. The hash of a serving side's arguments that its identity holds reads "
    "them alone even when `serve.command` names the program. So a reader who knows the rest of "
    "the side can confirm a guessed second key by hashing the guess. Give such a server one key "
    "on its command line."
)
ARGS = ["--model", "org/model-a", "--api-key", "KEY1", "KEY2"]


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def page(repo_root: Path, name: str) -> str:
    return plain((repo_root / name).read_text(encoding="utf-8"))


def serving_config(serve: dict[str, list[str]]) -> dict[str, object]:
    return {"sides": {"new": {"kind": "serve", "image": "made-up/server:1", "serve": serve}}}


def test_the_config_reference_lists_the_option_and_its_examples(repo_root: Path) -> None:
    text = page(repo_root, CONFIG)

    assert ROW in text
    assert [pair for pair in EXAMPLES if f"`{pair[0]}` shows `{pair[1]}`" not in text] == []


@pytest.mark.parametrize(("typed", "shown"), EXAMPLES)
def test_each_example_of_the_config_reference_shows_as_the_page_says(
    typed: str, shown: str
) -> None:
    assert model.public_command(shlex.split(typed)) == shown


def test_the_security_policy_names_both_limits(repo_root: Path) -> None:
    text = page(repo_root, SECURITY)
    shown = text.split("## Known limits of the shown command", 1)[1].split(" ## ", 1)[0]
    hashes = text.split("## Known limits of the hashes", 1)[1].split(" ## ", 1)[0]

    assert SHOWN_LIMIT in shown
    assert HASH_LIMIT in hashes


def test_a_shortened_option_shows_whole() -> None:
    assert model.public_command(shlex.split(SHORTENED)) == SHORTENED


def test_the_config_hash_covers_the_second_key_with_no_program() -> None:
    hashed = model.config_inputs(serving_config({"args": ARGS}))

    assert hashed["sides"]["new"]["serve"]["args"] == [*ARGS[:3], model.HIDDEN, "KEY2"]


def test_the_config_hash_hides_both_keys_with_the_program_named() -> None:
    hashed = model.config_inputs(serving_config({"command": ["vllm", "serve"], "args": ARGS}))

    assert hashed["sides"]["new"]["serve"]["args"] == [*ARGS[:3], model.HIDDEN, model.HIDDEN]


def test_the_hash_of_the_arguments_alone_covers_the_second_key() -> None:
    other = [*ARGS[:4], "KEY3"]

    assert argv_sha256(ARGS) != argv_sha256(other)
