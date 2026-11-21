# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy says that a version given to a password's name stays in the hashes.

A line of an ``identify`` output that gives a name a version is read as a package's version
whatever the name, so ``DB_PASSWORD: 1.2.3`` is hashed as printed. The policy names it as a
limit of the hashes; its example is run here and does what the policy says, so the page changes
when the rule does.
"""

from __future__ import annotations

from pathlib import Path

from pairbench import model
from pairbench.sides.identity import sha256_hex

SECURITY = "SECURITY.md"
LIMIT = (
    "A line of an `identify` output that gives a name a version, two numbers or more joined by "
    "dots after a colon and nothing else, is read as a package's version whatever the name, so "
    "`DB_PASSWORD: 1.2.3` stays as printed in `identify_sha256`, in the side's fingerprint and "
    "in `hash_inputs.json`. A reader who knows the rest of the output can confirm a guessed "
    "value by hashing the guess, and a change to the value keeps captures made before and after "
    "it from pooling (`E_POOL_SIDE_DRIFT`). Keep a password out of what an `identify` command "
    "prints, and give it to the side through `launch.env_pass`."
)
KEPT = ("DB_PASSWORD: 1.2.3\n", "DB_PASSWORD: 1.2\n", "MADE_UP_TOKEN: 1.2.3.4\n")
# Lines of the same name that are no version, each hidden.
HIDDEN = (
    ("DB_PASSWORD: 12\n", "DB_PASSWORD: <hidden>\n"),
    ("DB_PASSWORD=1.2.3\n", "DB_PASSWORD=<hidden>\n"),
)


def plain(text: str) -> str:
    """The text with its lines joined, so a phrase broken across lines is found."""
    return " ".join(text.split())


def test_the_security_policy_names_the_limit_among_those_of_the_hashes(repo_root: Path) -> None:
    text = plain((repo_root / SECURITY).read_text(encoding="utf-8"))
    hashes = text.split("## Known limits of the hashes", 1)[1].split(" ## ", 1)[0]

    assert LIMIT in hashes


def test_a_version_given_to_a_password_name_is_hashed_as_printed() -> None:
    assert [line for line in KEPT if model.hashed_output(line) != line] == []


def test_a_change_to_that_version_changes_the_hash() -> None:
    one, two = (sha256_hex(model.hashed_output(f"DB_PASSWORD: {v}\n")) for v in ("1.2.3", "1.2.4"))

    assert one != two


def test_a_value_of_that_name_that_is_no_version_is_hidden() -> None:
    assert [model.hashed_output(line) for line, _ in HIDDEN] == [shown for _, shown in HIDDEN]
