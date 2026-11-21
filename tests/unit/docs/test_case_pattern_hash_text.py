# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The security policy lists the case patterns of the config as typed in the config's hash.

The hash of the config takes its case patterns, given with ``--case`` or as ``cases.primary``
or ``cases.groups``, as typed, while the shown command hides a credential in such a pattern. So
two configs whose patterns differ only in a credential have two hashes, and a guess at it can be
checked against the hash. The security policy lists it among the known limits of the shown
command with the advice to write the pattern as the results show the case, or with a ``*``;
the pages that say the config's hash hides the recognised forms point at that limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pairbench import model

SECURITY = "SECURITY.md"
LIMITS_HEADING = "## Known limits of the shown command"
LIMIT = (
    "**A case pattern in the hash of the config.** The hash of the config, `config_sha256`, takes "
    "its case patterns, given with `--case` or as `cases.primary` or `cases.groups`, as typed. The "
    "shown command hides a credential in such a pattern, as `--case 'test_api[token:made-up]'` "
    "shows `--case 'test_api[token:<hidden>]'`, but someone who knows the rest of the config can "
    "confirm a guess at it by hashing the guess."
)
ADVICE = (
    "write a case pattern as the results show the case (`--case 'test_api[token:<hidden>]'`) or "
    "with a `*` in place of the secret (`--case 'test_api*'`)."
)
# Each page that says the hash of the config hides the recognised forms, and the sentence on it
# that names the case patterns as the exception.
POINTERS = (
    (
        SECURITY,
        "The case patterns of the config are the exception the "
        "[known limits](#known-limits-of-the-shown-command) name: `config_sha256` takes them as "
        "typed.",
    ),
    (
        "docs/reference/config.md",
        "The case patterns of the config, given with `--case` or as `cases.primary` or "
        "`cases.groups`, are in the hash of the config as typed, as the "
        "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say.",
    ),
    (
        "docs/reference/results-schema.md",
        "The case patterns of the config are in `provenance.config_sha256` as typed, as the "
        "[known limits](../../SECURITY.md#known-limits-of-the-shown-command) say.",
    ),
)
FIRST = "kiwi7mango42"
SECOND = "plum3fig88qz"
TYPED_COMMAND = ("pairbench", "run", "--case", "test_api[token:made-up]", "--", "./bench")
SHOWN_COMMAND = "pairbench run --case 'test_api[token:<hidden>]' -- ./bench"
CASE = "test_api[token:made-up]"
CASE_SHOWN = "test_api[token:<hidden>]"


def joined(repo_root: Path, page: str) -> str:
    """A page's text on one line."""
    return " ".join((repo_root / page).read_text(encoding="utf-8").split())


def limits(repo_root: Path) -> str:
    """The security policy's section on the known limits of the shown command, on one line."""
    text = (repo_root / SECURITY).read_text(encoding="utf-8")
    start = text.index(f"\n{LIMITS_HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def test_the_security_policy_lists_the_limit(repo_root: Path) -> None:
    assert LIMIT in limits(repo_root)


def test_the_security_policy_gives_the_advice(repo_root: Path) -> None:
    assert ADVICE in limits(repo_root)


@pytest.mark.parametrize(("page", "sentence"), POINTERS)
def test_each_page_on_the_config_hash_names_the_exception(
    repo_root: Path, page: str, sentence: str
) -> None:
    assert sentence in joined(repo_root, page)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            {"cases": {"primary": [f"test_api[token:{FIRST}]"]}},
            {"cases": {"primary": [f"test_api[token:{SECOND}]"]}},
        ),
        (
            {"cases": {"groups": {"db": [f"test_api[token:{FIRST}]"]}}},
            {"cases": {"groups": {"db": [f"test_api[token:{SECOND}]"]}}},
        ),
    ],
    ids=["primary", "groups"],
)
def test_the_config_hash_takes_a_case_pattern_as_typed(
    first: dict[str, object], second: dict[str, object]
) -> None:
    assert model.config_sha256(first) != model.config_sha256(second)


def test_the_shown_command_hides_the_pattern_s_credential() -> None:
    assert model.public_command(TYPED_COMMAND) == SHOWN_COMMAND


@pytest.mark.parametrize("pattern", [CASE_SHOWN, "test_api*"])
def test_the_advised_patterns_match_the_case_as_the_results_show_it(pattern: str) -> None:
    assert model.public_case(CASE) == CASE_SHOWN
    assert model.case_matches(model.public_case(CASE), [pattern]) is True
