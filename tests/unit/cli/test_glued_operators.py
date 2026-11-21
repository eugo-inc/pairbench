# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two programs behind one credential glued to an operator in a wrapper's shell text are two sides.

A side that runs ``env -S "sh -c 'API_KEY=VALUE;./bench-old'"`` and one
that runs the same with ``./bench-new`` differ in the program after the
operator, so ``plan`` takes them as two sides, and ``compare`` refuses to pool
a capture of one with a capture of the other. The same holds when the text after
``sh -c`` is a ``bash -c`` text in single quotes, with each inner quote written
as ``'"'"'``. Two sides that differ in the credential alone are one side:
``plan`` refuses them with ``E_SAME_SIDE``. The value never shows. Every value
is made up.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

VALUE = "kiwi7mango42"
OTHER_VALUE = "plum4grape19"
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
# The words of each wrapper before its shell text; ``{t}`` is the text after ``sh -c``.
WRAPPERS: dict[str, tuple[str, ...]] = {
    "env -S": ("env", "-S"),
    "flock ./l -c": ("flock", "./l", "-c"),
    "su app -c": ("su", "app", "-c"),
    "script -qc": ("script", "-qc"),
}
TEXTS = {
    "semicolon": "API_KEY={v};./bench-{p}",
    "and": "API_KEY={v}&&./bench-{p}",
}
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)


# How the shell text reaches ``sh -c``: as it is, or as the text of ``bash -c`` in single
# quotes, which ``shlex.quote`` writes with each inner quote as ``'"'"'``.
NESTINGS = {
    "sh -c": lambda inner: inner,
    "sh -c, then bash -c in single quotes": lambda inner: f"bash -c {shlex.quote(inner)}",
}


def side(
    name: str, wrapper: str, text: str, value: str, program: str, nesting: str = "sh -c"
) -> str:
    """A ``--side`` value whose wrapper runs ``sh -c`` with the credential and the program."""
    inner = NESTINGS[nesting](text.replace("{v}", value).replace("{p}", program))
    return f"{name}=cmd:{shlex.join([*WRAPPERS[wrapper], f'sh -c {shlex.quote(inner)}'])}"


@pytest.mark.parametrize("nesting", sorted(NESTINGS))
@pytest.mark.parametrize("text", sorted(TEXTS))
@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_plan_takes_two_programs_behind_one_glued_credential_as_two_sides(
    cli: Cli, wrapper: str, text: str, nesting: str
) -> None:
    result = cli(
        "plan",
        "--side",
        side("a", wrapper, TEXTS[text], VALUE, "old", nesting),
        "--side",
        side("b", wrapper, TEXTS[text], VALUE, "new", nesting),
    )

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert VALUE not in result.out + result.err


@pytest.mark.parametrize("nesting", sorted(NESTINGS))
@pytest.mark.parametrize("text", sorted(TEXTS))
@pytest.mark.parametrize("wrapper", sorted(WRAPPERS))
def test_plan_refuses_one_program_behind_two_glued_credentials(
    cli: Cli, wrapper: str, text: str, nesting: str
) -> None:
    result = cli(
        "plan",
        "--side",
        side("a", wrapper, TEXTS[text], VALUE, "old", nesting),
        "--side",
        side("b", wrapper, TEXTS[text], OTHER_VALUE, "old", nesting),
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


@pytest.fixture
def benches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder with made-up programs ``bench-old`` and ``bench-new`` that do nothing."""
    folder = tmp_path / "work"
    folder.mkdir()
    for program in ("bench-old", "bench-new"):
        path = folder / program
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.chdir(folder)
    return folder


def capture(cli: Cli, folder: Path, value: str, program: str) -> str:
    """Run a side whose ``env -S`` text runs ``sh -c`` with a glued credential; return its id."""
    result = cli(
        "run",
        "--side",
        side("new", "env -S", TEXTS["semicolon"], value, program),
        "--side",
        f"old=cmd:{shlex.quote(sys.executable)} -c pass",
        "--baseline",
        "old",
        *QUICK,
        "--out",
        folder,
    )
    assert result.code == EXIT_OK, result.err
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def test_compare_refuses_to_pool_two_programs_behind_one_glued_credential(
    cli: Cli, benches: Path
) -> None:
    one = capture(cli, benches / "one", VALUE, "old")
    two = capture(cli, benches / "two", VALUE, "new")
    result = cli("compare", benches / "one" / "capture.jsonl", benches / "two" / "capture.jsonl")

    assert result.code == EXIT_ANALYSIS
    assert result.err == refusal_text(
        f"E_POOL_SIDE_DRIFT: the fingerprint of new differs between the captures {one} and {two}"
    )
    assert VALUE not in result.out + result.err


def test_compare_pools_one_program_behind_two_glued_credentials(cli: Cli, benches: Path) -> None:
    capture(cli, benches / "one", VALUE, "old")
    capture(cli, benches / "two", OTHER_VALUE, "old")
    result = cli(
        "compare",
        benches / "one" / "capture.jsonl",
        benches / "two" / "capture.jsonl",
        "--out",
        benches / "pooled",
    )

    assert result.code == EXIT_OK, result.err
    pooled = json.loads((benches / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert pooled["run"]["pooled"] is True
    for value in (VALUE, OTHER_VALUE):
        assert value not in json.dumps(pooled)
