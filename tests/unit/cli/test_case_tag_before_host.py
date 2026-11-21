# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare on two case ids that differ only in a tag written before a host.

A word after a ``:`` with an ``@`` and a host after it is read as a password before a host, with
no user before the ``:`` too, so two hyperfine cases named ``test_tag[:latest@HOST]`` and
``test_tag[:stable@HOST]`` read the same once hidden and compare refuses them, as the security
policy's known limits say. The two tags in different launches, or on different sides, are read
as one case and judged as one. Named the two ways the limit gives, the same two tags show as
written and are judged as two cases; an image name that is credential-like loses its tag either
way and its two tags are refused, and joined to its tag with ``-`` it shows as written. The result
files are made-up hyperfine exports written by each test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_USAGE

from .conftest import refusal_text

Cli = Callable[..., Any]

ROUNDS = 8
TAGS = ("latest", "stable")
HIDDEN_ID = "test_tag[:<hidden>@registry.example:5000]"
REFUSAL = (
    "E_USAGE: side 'new': two different cases have the name "
    "'test_tag[:<hidden>@registry.example:5000]' once absolute paths and paths that climb with "
    "'..' are cut and secrets hidden, as the results show it, and differ only in a hidden secret; "
    "give them names that differ outside their paths, absolute or climbing with '..', and outside "
    "their secrets; a path runs on over the words after it that start with a letter, a digit or "
    "'_', up to the last that holds a '/', and a quote ends it"
)
CREDENTIAL_REFUSAL = REFUSAL.replace(HIDDEN_ID, "test_tag[auth:<hidden>]")
# Two ids that differ only in the tag, written before a host with no user before the ':'.
BEFORE_HOST = (
    "test_tag[:latest@registry.example:5000]",
    "test_tag[:stable@registry.example:5000]",
)
# The same two tags named the two ways the known limit gives.
REGISTRY_FIRST = (
    "test_tag[registry.example:5000/app:latest]",
    "test_tag[registry.example:5000/app:stable]",
)
NO_HOST = ("test_tag[app:latest]", "test_tag[app:stable]")
# An image name that is credential-like, glued to its tags with ``:``, and joined to them
# with ``-``.
CREDENTIAL_NAME = ("test_tag[auth:latest]", "test_tag[auth:stable]")
DASH_JOINED = ("test_tag[auth-latest]", "test_tag[auth-stable]")
COMPARE = (
    "compare",
    "--side",
    "new=file:files/new-*.json",
    "--side",
    "old=file:files/old-*.json",
    "--driver",
    "hyperfine",
    "--baseline",
    "old",
    "--assume-interleaved",
    "--out",
    "out",
)


def _exports(folder: Path, names: tuple[str, ...]) -> None:
    _round_exports(folder, lambda side, r: names)


def _round_exports(folder: Path, names_of: Callable[[str, int], tuple[str, ...]]) -> None:
    """Write the exports of both sides, round ``r`` of a side naming ``names_of(side, r)``."""
    files = folder / "files"
    files.mkdir()
    for side, base in (("new", 0.2), ("old", 0.3)):
        for r in range(1, ROUNDS + 1):
            names = names_of(side, r)
            results = [
                {
                    "command": "true",
                    "name": name,
                    "measurements": [
                        {
                            "time_wall_clock": {
                                "value": base + r / 1000 + k / 10000,
                                "unit": "second",
                            },
                            "exit_code": 0,
                        }
                    ],
                }
                for k, name in enumerate(names)
            ]
            doc = {"schema_version": 2, "results": results}
            (files / f"{side}-{r}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_compare_refuses_two_tags_before_a_host_that_read_the_same(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _exports(tmp_path, BEFORE_HOST)

    result = cli(*COMPARE)

    assert result.code == EXIT_USAGE, result.err
    assert result.out == ""
    assert result.err.endswith(refusal_text(REFUSAL)), result.err
    assert not any(tag in result.err for tag in TAGS)


@pytest.mark.parametrize(
    "names",
    [
        pytest.param(REGISTRY_FIRST, id="registry-first"),
        pytest.param(NO_HOST, id="no-host-after-the-tag"),
        pytest.param(DASH_JOINED, id="credential-like-name-joined-with-a-dash"),
    ],
)
def test_compare_judges_two_tags_named_the_ways_the_limit_gives_as_two_cases(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]
) -> None:
    monkeypatch.chdir(tmp_path)
    _exports(tmp_path, names)

    result = cli(*COMPARE)

    assert result.code == EXIT_OK, result.err
    assert "E_USAGE" not in result.err
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [c["case"] for c in written["comparisons"]] == list(names)


def test_compare_refuses_two_tags_of_a_credential_like_image_name(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _exports(tmp_path, CREDENTIAL_NAME)

    result = cli(*COMPARE)

    assert result.code == EXIT_USAGE, result.err
    assert result.out == ""
    assert result.err.endswith(refusal_text(CREDENTIAL_REFUSAL)), result.err
    assert not any(tag in result.err for tag in TAGS)


def _half_and_half(side: str, r: int) -> tuple[str, ...]:
    """Name ``:latest`` in the first half of each side's rounds and ``:stable`` in the second."""
    return (BEFORE_HOST[0] if r <= ROUNDS // 2 else BEFORE_HOST[1],)


def _one_tag_per_side(side: str, r: int) -> tuple[str, ...]:
    """Name ``:latest`` in every round of side new and ``:stable`` in every round of side old."""
    return (BEFORE_HOST[0] if side == "new" else BEFORE_HOST[1],)


@pytest.mark.parametrize(
    "names_of",
    [
        pytest.param(_half_and_half, id="different-launches"),
        pytest.param(_one_tag_per_side, id="different-sides"),
    ],
)
def test_compare_reads_two_tags_of_different_launches_or_sides_as_one_case(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names_of: Callable[[str, int], tuple[str, ...]],
) -> None:
    monkeypatch.chdir(tmp_path)
    _round_exports(tmp_path, names_of)

    result = cli(*COMPARE)

    assert result.code == EXIT_OK, result.err
    assert "E_USAGE" not in result.err
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [(c["case"], c["n_rounds"]) for c in written["comparisons"]] == [(HIDDEN_ID, ROUNDS)]
