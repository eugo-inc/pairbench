# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The passwords of Redis and Valkey commands stay out of what plan and run write.

A workload that gives a password in ``AUTH``, ``HELLO ... AUTH``, ``MIGRATE ...
AUTH`` or ``AUTH2``, ``CONFIG SET masterauth`` or ``requirepass`` after another
setting or alone, a rule of ``ACL SETUSER``, ``--pass``, memtier's
``--authenticate`` or the command text of ``memtier_benchmark --command`` is
planned and run twice, with two made-up passwords. Neither
password is in what ``plan`` prints or in any file ``run`` writes but the raw
capture, and every hash of the run is the same for both. Each client word
follows the ``:`` command of the shell, so nothing but the shell runs.
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

PASSWORDS = ("zqmkiwi", "zqmplum")
HIDDEN = "<hidden>"
SCRIPT = (
    ": redis-cli AUTH {pw}; "
    ": redis-cli AUTH made-up-user {pw}; "
    ": redis-cli CONFIG SET masterauth {pw}; "
    ": redis-cli CONFIG SET requirepass {pw}; "
    ": redis-cli CONFIG SET maxmemory 100mb masterauth {pw}; "
    ": redis-cli ACL SETUSER made-up-user on '>{pw}' '<{pw}' '#{pw}' +@all; "
    ": redis-cli HELLO 3 AUTH made-up-user {pw} SETNAME bench; "
    ": redis-cli MIGRATE 127.0.0.1 6380 made-up-key 0 5000 AUTH {pw}; "
    ": redis-cli MIGRATE 127.0.0.1 6380 '' 0 5000 AUTH2 made-up-user {pw} KEYS a b; "
    ": valkey-cli --user made-up-user --pass {pw} PING; "
    ": redis-benchmark -n 10 'AUTH {pw}'; "
    ": memtier_benchmark --authenticate {pw} --command 'AUTH {pw}'; "
    ": memtier_benchmark --authenticate={pw}; "
    ": memtier_benchmark '--command=HELLO 3 AUTH made-up-user {pw}'"
)
SIDES = ("--side", "new=cmd:{workload}", "--side", "old=cmd:env {workload}", "--baseline", "old")
QUICK = ("--gates", "off", "--rounds", "6", "--same-vs-same", "off", "--positive-control", "off")
# The raw record of the run, which keeps the command as typed and is never shared.
CAPTURE = "capture.jsonl"
SHOWN_WORKLOAD = "-- " + shlex.join(["sh", "-c", SCRIPT.format(pw=HIDDEN)])


def _plan(cli: Cli, password: str) -> str:
    result = cli("plan", *SIDES, *QUICK, "--", "sh", "-c", SCRIPT.format(pw=password))
    assert result.code == EXIT_OK, result.err
    assert password not in result.out
    assert password not in result.err
    return str(result.out)


def _run(cli: Cli, folder: Path, password: str) -> dict[str, Any]:
    # Each run writes to a folder of the same name, so the two configurations are alike.
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
        "sh",
        "-c",
        SCRIPT.format(pw=password),
    )
    assert result.code == EXIT_OK, result.err
    assert password not in result.out
    assert password not in result.err
    shared = sorted(
        path for path in (folder / "run").rglob("*") if path.is_file() and path.name != CAPTURE
    )
    assert {"results.json", "results.md", "report.html", "plan.tsv"} <= {p.name for p in shared}
    for path in shared:
        assert password.encode() not in path.read_bytes(), path.name
    text = (folder / "run" / "results.json").read_text(encoding="utf-8")
    results: dict[str, Any] = json.loads(text)
    return results


def _hashes(results: dict[str, Any]) -> dict[str, str]:
    found = {"config": results["provenance"]["config_sha256"]}
    for side in results["sides"]:
        found[f"{side['name']} fingerprint"] = side["fingerprint"]
        found[f"{side['name']} arguments"] = side["identity"]["argv_sha256"]
    return found


def test_plan_shows_the_same_text_whatever_the_redis_password(cli: Cli) -> None:
    first, second = (_plan(cli, password) for password in PASSWORDS)

    assert first == second


def test_a_run_writes_no_redis_password_and_the_same_hashes_for_each(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = []
    for where, password in zip(("one", "two"), PASSWORDS, strict=True):
        folder = tmp_path / where
        folder.mkdir()
        monkeypatch.chdir(folder)
        found.append(_run(cli, folder, password))
    first, second = found

    assert _hashes(first) == _hashes(second)
    assert first["run"]["command"].endswith(SHOWN_WORKLOAD)
    assert second["run"]["command"].endswith(SHOWN_WORKLOAD)
