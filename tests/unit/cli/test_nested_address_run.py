# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A folder named in the query or fragment of an address stays out of what a run shows.

The workload hands a client five addresses whose query or fragment names a
file: a local address after an address with no host, a climbing path after a
host and an empty port, a local address with a host of its own after a
``unix:///`` socket, a climbing path in the fragment of an address with no host,
and a climbing path after a host in brackets. No made-up folder name is in what
``run`` prints or any file it writes but the raw capture, and the shown command
holds the last part of each path. Every folder name here is made up.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

# The made-up folders; none of them may be shown.
FOLDERS = ("Zqrun1", "Zqrun2", "Zqrun3", "Zqrun4", "Zqrun5")
# Each address as typed, and as the shown command holds it.
ADDRESSES = (
    (
        "postgresql:///bench?sslrootcert=file:///zqd/Zqrun1/ca.pem",
        "postgresql:///bench?sslrootcert=file://ca.pem",
    ),
    (
        "mysql://localhost:/bench?ssl-ca=../../zqd/Zqrun2/ca.pem",
        "mysql://localhost:/bench?ssl-ca=ca.pem",
    ),
    (
        "unix:///run/bench.sock?cert=file://localhost/zqd/Zqrun3/ca.pem",
        "unix:///bench.sock?cert=file://ca.pem",
    ),
    ("redis:///0#../../zqd/Zqrun4/dump.rdb", "redis:///0#dump.rdb"),
    ("http://[::1]/v1?cert=../zqd/Zqrun5/ca.pem", "http://[::1]/v1?cert=ca.pem"),
)
# The shell text: ``:`` runs nothing, so only the shell runs.
SCRIPT = ': psql "$1" "$2" "$3" "$4" "$5"'
QUICK = ("--gates", "off", "--rounds", "6", "--same-vs-same", "off", "--positive-control", "off")
SIDES = ("--side", "new=cmd:env {workload}", "--side", "old=cmd:{workload}", "--baseline", "old")
# The raw record of the run, which keeps the command as typed and is never shared.
CAPTURE = "capture.jsonl"
SHARED = ("results.json", "results.md", "report.html")

WORKLOAD = ["sh", "-c", SCRIPT, "sh", *(address for address, _ in ADDRESSES)]
SHOWN_WORKLOAD = "-- " + shlex.join(["sh", "-c", SCRIPT, "sh", *(shown for _, shown in ADDRESSES)])


def _shows_no_folder(text: str) -> bool:
    return not any(folder in text for folder in FOLDERS)


def test_a_run_shows_no_folder_named_in_the_query_of_an_address(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = cli(
        "run",
        *SIDES,
        *QUICK,
        "--explain",
        "off",
        "--plots",
        "off",
        "--out",
        "run",
        "--",
        *WORKLOAD,
    )

    assert result.code == EXIT_OK, result.err
    assert _shows_no_folder(result.out), result.out
    assert _shows_no_folder(result.err), result.err
    shared = sorted(
        path for path in (tmp_path / "run").rglob("*") if path.is_file() and path.name != CAPTURE
    )
    assert set(SHARED) <= {path.name for path in shared}
    for path in shared:
        assert _shows_no_folder(path.read_text(encoding="utf-8")), path.name
    results: dict[str, Any] = json.loads((tmp_path / "run" / "results.json").read_text("utf-8"))
    assert results["run"]["command"].endswith(SHOWN_WORKLOAD)
