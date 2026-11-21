# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A secret that holds a shell operator stays hidden whole where no shell reads it.

A word given to a program with no shell between keeps every operator it
holds: the arguments after ``parallel``'s ``:::``, ``:::+``, ``::::`` and
``::::+``, the first of them or a later one, the command of ``hyperfine
-iN`` (its ``-N`` in a group of short options, before the command or after
it) and of ``watch -xn1`` (its ``-x`` in a group that ends in a value),
the ``SetEnv`` value of ``ssh -o`` with a word after a space, and an option
whose name runs on into a credential's name (``--commandAPI_KEY=``), which
is no ``--command=`` text. A query parameter in a program's text, after a
``?`` in another word or in its own, ends at ``&`` or ``#`` only, not at a
blank or an operator. So no six
characters of the secret are shown or hashed, and two secrets give one
shown command and one hash.
"""

from __future__ import annotations

import pytest

from pairbench import model
from pairbench.sides.identity import argv_sha256

# Made-up secrets that each hold an operator that ends a command in a shell.
SECRETS = ("kiwi;7mango", "plum;4grape")

# Each form: its arguments with ``{s}`` for the secret, and the command as shown and hashed.
FORMS: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {
    "parallel-arguments-after-three-colons": (
        ("parallel", "./bench", ":::", "--token={s}"),
        "parallel ./bench ::: '--token=<hidden>'",
        ("parallel", "./bench", ":::", "--token=<hidden>"),
    ),
    "parallel-arguments-after-three-colons-and-a-plus": (
        ("parallel", "./bench", ":::", "1", ":::+", "--token={s}"),
        "parallel ./bench ::: 1 :::+ '--token=<hidden>'",
        ("parallel", "./bench", ":::", "1", ":::+", "--token=<hidden>"),
    ),
    "parallel-arguments-after-four-colons": (
        ("parallel", "./bench", "::::", "--token={s}"),
        "parallel ./bench :::: '--token=<hidden>'",
        ("parallel", "./bench", "::::", "--token=<hidden>"),
    ),
    "parallel-arguments-after-four-colons-and-a-plus": (
        ("parallel", "./bench", "::::", "made-up.txt", "::::+", "--token={s}"),
        "parallel ./bench :::: made-up.txt ::::+ '--token=<hidden>'",
        ("parallel", "./bench", "::::", "made-up.txt", "::::+", "--token=<hidden>"),
    ),
    "parallel-arguments-after-three-colons-and-a-plus-first": (
        ("parallel", "./bench", ":::+", "--token={s}"),
        "parallel ./bench :::+ '--token=<hidden>'",
        ("parallel", "./bench", ":::+", "--token=<hidden>"),
    ),
    "parallel-arguments-after-four-colons-and-a-plus-first": (
        ("parallel", "./bench", "::::+", "--token={s}"),
        "parallel ./bench ::::+ '--token=<hidden>'",
        ("parallel", "./bench", "::::+", "--token=<hidden>"),
    ),
    "hyperfine-no-shell-last-in-a-group": (
        ("hyperfine", "-iN", "./bench --token={s}"),
        "hyperfine -iN './bench --token=<hidden>'",
        ("hyperfine", "-iN", "./bench --token=<hidden>"),
    ),
    "hyperfine-no-shell-first-in-a-group": (
        ("hyperfine", "-Ni", "./bench --token={s}"),
        "hyperfine -Ni './bench --token=<hidden>'",
        ("hyperfine", "-Ni", "./bench --token=<hidden>"),
    ),
    "hyperfine-no-shell-last-in-a-group-after-the-command": (
        ("hyperfine", "./bench --token={s}", "-iN"),
        "hyperfine './bench --token=<hidden>' -iN",
        ("hyperfine", "./bench --token=<hidden>", "-iN"),
    ),
    "hyperfine-no-shell-first-in-a-group-after-the-command": (
        ("hyperfine", "./bench --token={s}", "-Ni"),
        "hyperfine './bench --token=<hidden>' -Ni",
        ("hyperfine", "./bench --token=<hidden>", "-Ni"),
    ),
    "watch-exec-in-a-group-that-ends-in-a-value": (
        ("watch", "-xn1", "./bench", "--token={s}&made-up"),
        "watch -xn1 ./bench '--token=<hidden>'",
        ("watch", "-xn1", "./bench", "--token=<hidden>"),
    ),
    "ssh-setenv-secret-after-a-space": (
        ("ssh", "-o", "SetEnv=API_TOKEN=made-up {s}", "made-up-host", "true"),
        "ssh -o 'SetEnv=API_TOKEN=<hidden>' made-up-host true",
        ("ssh", "-o", "SetEnv=API_TOKEN=<hidden>", "made-up-host", "true"),
    ),
    "ssh-setenv-secret-before-a-space": (
        ("ssh", "-o", "SetEnv=API_TOKEN={s} made-up", "made-up-host", "true"),
        "ssh -o 'SetEnv=API_TOKEN=<hidden>' made-up-host true",
        ("ssh", "-o", "SetEnv=API_TOKEN=<hidden>", "made-up-host", "true"),
    ),
    "option-name-that-runs-on-into-a-credential-name": (
        ("gcloud", "compute", "ssh", "made-up-vm", "--commandAPI_KEY={s}"),
        "gcloud compute ssh made-up-vm '--commandAPI_KEY=<hidden>'",
        ("gcloud", "compute", "ssh", "made-up-vm", "--commandAPI_KEY=<hidden>"),
    ),
    "query-parameter-after-a-question-mark-in-another-word": (
        ("python3", "-c", "u = 'http://localhost/p?a=1'; t = '&token={s}'"),
        "python3 -c 'u = '\"'\"'http://localhost/p?a=1'\"'\"'; t = '\"'\"'&token=<hidden>'\"'\"''",
        ("python3", "-c", "u = 'http://localhost/p?a=1'; t = '&token=<hidden>'"),
    ),
    "query-parameter-after-a-question-mark-in-its-word": (
        ("python3", "-c", "u = 'http://localhost/p?a=1&token={s}'"),
        "python3 -c 'u = '\"'\"'http://localhost/p?a=1&token=<hidden>'\"'\"''",
        ("python3", "-c", "u = 'http://localhost/p?a=1&token=<hidden>'"),
    ),
    "query-parameter-whose-value-holds-a-blank": (
        ("python3", "-c", "u = 'http://localhost/p?a=1&token=made-up {s}'"),
        "python3 -c 'u = '\"'\"'http://localhost/p?a=1&token=<hidden>'\"'\"''",
        ("python3", "-c", "u = 'http://localhost/p?a=1&token=<hidden>'"),
    ),
}


def typed(form: tuple[str, ...], secret: str) -> list[str]:
    return [word.replace("{s}", secret) for word in form]


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of either secret that the text holds."""
    return [
        secret[at : at + 6]
        for secret in SECRETS
        for at in range(len(secret) - 5)
        if secret[at : at + 6] in text
    ]


@pytest.mark.parametrize("name", sorted(FORMS))
def test_a_secret_that_holds_an_operator_is_shown_and_hashed_hidden_whole(name: str) -> None:
    form, shown, hashed = FORMS[name]
    argv = typed(form, SECRETS[0])

    assert model.public_command(argv) == shown
    assert model.hashed_argv(argv) == list(hashed)


@pytest.mark.parametrize("name", sorted(FORMS))
def test_no_six_characters_of_the_secret_are_shown_or_hashed(name: str) -> None:
    form, _shown, _hashed = FORMS[name]
    argv = typed(form, SECRETS[0])

    assert pieces(model.public_command(argv)) == []
    assert pieces(" ".join(model.hashed_argv(argv))) == []


@pytest.mark.parametrize("name", sorted(FORMS))
def test_two_secrets_that_hold_an_operator_give_one_shown_command_and_one_hash(
    name: str,
) -> None:
    form, _shown, _hashed = FORMS[name]
    one, other = (typed(form, secret) for secret in SECRETS)

    assert model.public_command(one) == model.public_command(other)
    assert argv_sha256(one) == argv_sha256(other)
