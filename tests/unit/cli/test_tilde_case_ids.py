# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""compare keeps two cases whose ids differ only in the name of a home folder.

A case id cannot tell a user's home written ``~NAME`` from a word such as
``~alpha``, ``~mask`` or ``~Widget``, so a case id keeps such a word as typed,
and it cannot tell a path that ends at ``/home/NAME`` or ``/users/NAME`` from a
route such as ``/users/1``, so it cuts such a path to its last part, as it cuts
any path, whether hyperfine was given the name or named the case after its
command. Two such cases are compared as two cases, not refused as one name. The
result files are made-up hyperfine exports written by each test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

ROUNDS = 8
# (the name hyperfine was given or None, the command, the case id the results show), two per
# export, which differ only in a word that starts with ``~``.
GIVEN_NAMES: tuple[tuple[str | None, str, str], ...] = (
    ("t ~alpha", "true", "t ~alpha"),
    ("t ~beta", "true", "t ~beta"),
)
COMMAND_NAMES: tuple[tuple[str | None, str, str], ...] = (
    (None, "python3 -c 'print(~a)'", "python3 -c print(~a)"),
    (None, "python3 -c 'print(~b)'", "python3 -c print(~b)"),
)
WORDS_IN_COMMANDS: tuple[tuple[str | None, str, str], ...] = (
    (None, "echo ~alpha", "echo ~alpha"),
    (None, "echo ~beta", "echo ~beta"),
)
# Two per export, which differ only in the last part of a route under /users.
GIVEN_ROUTES: tuple[tuple[str | None, str, str], ...] = (
    ("GET /users/1", "true", "GET 1"),
    ("GET /users/2", "true", "GET 2"),
)
ROUTES_IN_COMMANDS: tuple[tuple[str | None, str, str], ...] = (
    (None, "python3 app.py --route /users/1", "python3 app.py --route 1"),
    (None, "python3 app.py --route /users/2", "python3 app.py --route 2"),
)


def _entry(name: str | None, command: str, value: float) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "command": command,
        "measurements": [{"time_wall_clock": {"value": value, "unit": "second"}, "exit_code": 0}],
    }
    if name is not None:
        entry["name"] = name
    return entry


def _exports(folder: Path, cases: tuple[tuple[str | None, str, str], ...]) -> None:
    files = folder / "files"
    files.mkdir()
    for side, base in (("new", 0.2), ("old", 0.3)):
        for r in range(1, ROUNDS + 1):
            results = [
                _entry(name, command, base + r / 1000 + k / 10000)
                for k, (name, command, _) in enumerate(cases)
            ]
            doc = {"schema_version": 2, "results": results}
            (files / f"{side}-{r}.json").write_text(json.dumps(doc), encoding="utf-8")


@pytest.mark.parametrize(
    "cases",
    [
        pytest.param(GIVEN_NAMES, id="names-given-to-hyperfine"),
        pytest.param(COMMAND_NAMES, id="names-made-from-commands"),
        pytest.param(WORDS_IN_COMMANDS, id="tilde-words-in-commands"),
        pytest.param(GIVEN_ROUTES, id="routes-given-to-hyperfine"),
        pytest.param(ROUTES_IN_COMMANDS, id="routes-in-commands"),
    ],
)
def test_compare_keeps_two_cases_that_differ_only_in_a_home_folder_name(
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cases: tuple[tuple[str | None, str, str], ...],
) -> None:
    monkeypatch.chdir(tmp_path)
    _exports(tmp_path, cases)

    shown = cli(
        "compare",
        "--side",
        "new=file:files/new-*.json",
        "--side",
        "old=file:files/old-*.json",
        "--driver",
        "hyperfine",
        "--out",
        "out",
    )

    assert shown.code == EXIT_OK
    assert "E_USAGE" not in shown.err
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [c["case"] for c in written["comparisons"]] == [case for _, _, case in cases]
