# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Sides that differ only in a secret the tool hides have one fingerprint.

The fingerprint is taken with every recognised secret form hidden, so two
command sides that differ only in a password after ``--password`` are the
same side to ``plan`` and ``run``: ``E_SAME_SIDE``. Sides that differ in a
path or an ordinary value are two sides. ``run``, ``compare`` and the explain
step compute the fingerprint the same way and agree on it.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import load_capture
from pairbench.errors import EXIT_OK, EXIT_SIDE
from pairbench.model import Experiment
from pairbench.runner import open_explain

from .conftest import refusal_text

Cli = Callable[..., Any]

SAME_SIDE = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
PYTHON = shlex.quote(sys.executable)
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("true --password kiwi7", "true --password plum4"),
        ("true --api-key=kiwi7", "true --api-key=plum4"),
        ("env API_TOKEN=kiwi7 true", "env API_TOKEN=plum4 true"),
        (
            "true --url https://madeup:kiwi7@made-up.example/",
            "true --url https://madeup:plum4@made-up.example/",
        ),
    ],
    ids=["option", "option-with-equals", "variable", "address-user-part"],
)
def test_sides_that_differ_only_in_a_hidden_secret_are_the_same_side(
    cli: Cli, a: str, b: str
) -> None:
    result = cli("plan", "--side", f"a=cmd:{a}", "--side", f"b=cmd:{b}")

    assert result.code == EXIT_SIDE
    assert result.err == SAME_SIDE
    assert result.out == ""


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("true /made/up/one", "true /made/up/two"),
        ("true --size 1", "true --size 2"),
        ("true --host one.example", "true --host two.example"),
        ("true kiwi7", "true plum4"),
        # A name that starts with a word of its own beginning with KEY names no key.
        ("true --keydb-port 6379", "true --keydb-port 6380"),
        ("env KEYCLOAK_REALM=one true", "env KEYCLOAK_REALM=two true"),
        ("true --keyed 1", "true --keyed 2"),
        ("env KEYLESS_SIGNING=0 true", "env KEYLESS_SIGNING=1 true"),
    ],
    ids=[
        "path",
        "ordinary-value",
        "host",
        "unrecognised-password",
        "keydb",
        "keycloak",
        "keyed",
        "keyless",
    ],
)
def test_sides_that_differ_in_a_path_or_an_ordinary_value_are_two_sides(
    cli: Cli, a: str, b: str
) -> None:
    result = cli("plan", "--side", f"a=cmd:{a}", "--side", f"b=cmd:{b}")

    assert result.code == EXIT_OK
    assert "E_SAME_SIDE" not in result.err


def _run(cli: Cli, folder: Path, password: str) -> dict[str, Any]:
    result = cli(
        "run",
        "--side",
        f"new=cmd:{PYTHON} -c pass --password {password}",
        "--side",
        f"old=cmd:{PYTHON} -c pass",
        "--baseline",
        "old",
        *QUICK,
        "--out",
        folder,
    )
    assert result.code == EXIT_OK, result.err
    results: dict[str, Any] = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return results


def _fingerprints(results: dict[str, Any]) -> dict[str, str]:
    return {side["name"]: side["fingerprint"] for side in results["sides"]}


def test_run_compare_and_explain_agree_on_a_fingerprint_with_a_secret_hidden(
    cli: Cli, tmp_path: Path
) -> None:
    first = _fingerprints(_run(cli, tmp_path / "kiwi", "kiwi7"))
    second = _fingerprints(_run(cli, tmp_path / "plum", "plum4"))
    assert first == second

    compared = cli("compare", tmp_path / "kiwi" / "capture.jsonl", "--out", tmp_path / "again")
    assert compared.code == EXIT_OK, compared.err
    again = json.loads((tmp_path / "again" / "results.json").read_text(encoding="utf-8"))
    assert _fingerprints(again) == first

    capture = load_capture(tmp_path / "kiwi" / "capture.jsonl")[0]
    experiment = Experiment.from_json(dict(capture.header.config))
    session = open_explain(experiment, run_id=capture.capture_id, fingerprints=first)
    try:
        command = session.command("new")
    finally:
        session.close()
    assert command is not None
    assert list(command[-2:]) == ["--password", "kiwi7"]
