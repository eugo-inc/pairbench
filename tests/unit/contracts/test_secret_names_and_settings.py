# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Names that glue a password to its form or a word to an authentication, and a secret's value.

A word of a password glued to ``HASH`` or ``TEXT`` names a credential as the
same words written apart do (``PASSWDHASH`` as ``PASSWD_HASH``), and so does
a word glued to an authentication word (``MASTERAUTH``), unless it starts
with a switch or a word that undoes the authentication (``NOAUTH``,
``DEAUTH``). After ``secret set`` or ``secrets set`` the setting is a secret
whatever its name, so its value is hidden in every form a command gives it.
Ordinary names around them stay shown, and so do the values of ordinary
settings.
"""

from __future__ import annotations

import pytest

from pairbench.model import hashed_argv, looks_like_credential, public_command

# A made-up secret.
SECRET = "kiwi7zq"

HIDDEN_NAMES = (
    "PASSWDHASH",
    "passwdhash",
    "--passwdhash",
    "PASSWDTEXT",
    "--passwdtext",
    "PASSPHRASETEXT",
    "PGPASSTEXT",
    "PWDHASH",
    "PASSCODEHASHES",
    "MASTERAUTH",
    "masterauth",
    "--masterauth",
    "BASICAUTH",
    "proxyauth",
    "--sentinelauth",
    "PROXYAUTHORIZATION",
)
SHOWN_NAMES = (
    "MASTER_ADDR",
    "MASTER_PORT",
    "MASTERADDR",
    "MASTERPORT",
    "masteruser",
    "NOAUTH",
    "--noauth",
    "--deauth",
    "REAUTH",
    "--no-masterauth",
    "--masterauth-type",
    "HASH",
    "--hash",
    "TEXT",
    "CONTEXT",
    "PLAINTEXT",
    "PRETEXT",
    "PYTHONHASHSEED",
    "PASSTHROUGH",
    "BYPASSHASH",
    "COMPASSTEXT",
    "PATHHASH",
    "FILEHASH",
    "GITHASH",
)


@pytest.mark.parametrize("name", HIDDEN_NAMES)
def test_a_password_glued_to_its_form_or_a_word_glued_to_auth_is_a_credential(name: str) -> None:
    assert looks_like_credential(name) is True


@pytest.mark.parametrize("name", SHOWN_NAMES)
def test_an_ordinary_sibling_of_those_names_is_no_credential(name: str) -> None:
    assert looks_like_credential(name) is False


# Each row: the argument list, the command the shared files show, and the list every
# published hash reads.
HIDDEN_FORMS = {
    "variable-hash": (
        ["env", f"PASSWDHASH={SECRET}", "./made-up-bench"],
        "env 'PASSWDHASH=<hidden>' ./made-up-bench",
        ["env", "PASSWDHASH=<hidden>", "./made-up-bench"],
    ),
    "variable-auth": (
        ["env", f"MASTERAUTH={SECRET}", "./made-up-bench"],
        "env 'MASTERAUTH=<hidden>' ./made-up-bench",
        ["env", "MASTERAUTH=<hidden>", "./made-up-bench"],
    ),
    "option-text": (
        ["./made-up-bench", "--passwdtext", SECRET],
        "./made-up-bench --passwdtext '<hidden>'",
        ["./made-up-bench", "--passwdtext", "<hidden>"],
    ),
    "option-auth": (
        ["./made-up-bench", "--masterauth", SECRET],
        "./made-up-bench --masterauth '<hidden>'",
        ["./made-up-bench", "--masterauth", "<hidden>"],
    ),
    "glued-option-text": (
        ["./made-up-bench", f"--passphrasetext={SECRET}"],
        "./made-up-bench '--passphrasetext=<hidden>'",
        ["./made-up-bench", "--passphrasetext=<hidden>"],
    ),
    "secret-body": (
        ["gh", "secret", "set", "MADE_UP_NAME", "--body", SECRET],
        "gh secret set MADE_UP_NAME --body '<hidden>'",
        ["gh", "secret", "set", "MADE_UP_NAME", "--body", "<hidden>"],
    ),
    "secret-short-body": (
        ["gh", "secret", "set", "MADE_UP_NAME", "-b", SECRET],
        "gh secret set MADE_UP_NAME -b '<hidden>'",
        ["gh", "secret", "set", "MADE_UP_NAME", "-b", "<hidden>"],
    ),
    "secret-glued-body": (
        ["gh", "secret", "set", "MADE_UP_NAME", f"--body={SECRET}"],
        "gh secret set MADE_UP_NAME '--body=<hidden>'",
        ["gh", "secret", "set", "MADE_UP_NAME", "--body=<hidden>"],
    ),
    "secret-glued-short-body": (
        ["gh", "secret", "set", "MADE_UP_NAME", f"-b{SECRET}"],
        "gh secret set MADE_UP_NAME '<hidden>'",
        ["gh", "secret", "set", "MADE_UP_NAME", "<hidden>"],
    ),
    "secret-options-first": (
        ["gh", "secret", "set", "--repo", "made/up", "MADE_UP_NAME", "--body", SECRET],
        "gh secret set --repo '<hidden>' '<hidden>' --body '<hidden>'",
        ["gh", "secret", "set", "--repo", "<hidden>", "<hidden>", "--body", "<hidden>"],
    ),
    "secret-body-first": (
        ["gh", "secret", "set", "-b", SECRET, "MADE_UP_NAME"],
        "gh secret set -b '<hidden>' '<hidden>'",
        ["gh", "secret", "set", "-b", "<hidden>", "<hidden>"],
    ),
    "secrets-name-and-value": (
        ["fly", "secrets", "set", f"MADE_UP_NAME={SECRET}"],
        "fly secrets set 'MADE_UP_NAME=<hidden>'",
        ["fly", "secrets", "set", "MADE_UP_NAME=<hidden>"],
    ),
    "secret-in-a-shell-text": (
        ["sh", "-c", f"gh secret set MADE_UP_NAME --body {SECRET} && true"],
        "sh -c 'gh secret set MADE_UP_NAME --body <hidden> && true'",
        ["sh", "-c", "gh secret set MADE_UP_NAME --body <hidden> && true"],
    ),
}


@pytest.mark.parametrize(
    ("argv", "shown", "hashed"), list(HIDDEN_FORMS.values()), ids=list(HIDDEN_FORMS)
)
def test_a_secret_is_hidden_in_the_shown_command_and_every_hash(
    argv: list[str], shown: str, hashed: list[str]
) -> None:
    assert public_command(argv) == shown
    assert hashed_argv(argv) == hashed


SHOWN_FORMS = {
    "pull-request-body": ["gh", "pr", "create", "--body", "alpha"],
    "variable-body": ["gh", "variable", "set", "MADE_UP_NAME", "--body", "alpha"],
    "secret-list": ["gh", "secret", "list", "--repo", "made/up"],
    "switch-before-a-count": ["./made-up-bench", "--noauth", "-n", "8"],
    "deauth-count": ["./made-up-bench", "--deauth", "8"],
    "hash-option": ["./made-up-bench", "--hash", "alpha"],
    "plaintext-option": ["./made-up-bench", "--plaintext", "alpha"],
    "master-port": ["env", "MASTER_PORT=29500", "./made-up-bench"],
    "set-after-another-word": ["./made-up-bench", "alpha", "set", "MADE_UP_NAME", "beta"],
}


@pytest.mark.parametrize("argv", list(SHOWN_FORMS.values()), ids=list(SHOWN_FORMS))
def test_an_ordinary_value_beside_those_forms_is_shown(argv: list[str]) -> None:
    assert public_command(argv) == " ".join(argv)
    assert hashed_argv(argv) == argv
