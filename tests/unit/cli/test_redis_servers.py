# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The passwords of Redis and Valkey servers and Sentinels stay out of what plan and run write.

A workload that starts ``redis-server``, ``valkey-server``, ``redis-sentinel``
or ``valkey-sentinel`` with ``--masterauth``, ``--primaryauth`` or a
``--sentinel`` line of ``auth-pass`` or ``sentinel-pass``, or that sends
``SENTINEL SET`` or ``SENTINEL CONFIG SET`` through ``redis-cli`` or
``valkey-cli``, is planned and run twice, with two made-up passwords: as the
words after ``--``, as the ``argv`` of the config's workload, and in a shell
text. Neither password is in what ``plan`` and ``run`` print or in any file
``run`` writes but the raw capture, every hash of the run is the same for
both, and the user names and the master's name are shown. Each program is a
stub in the run's folder that does nothing.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK

Cli = Callable[..., Any]

PASSWORDS = ("zqmkiwi", "zqmplum")
SIDES = ("--side", "new=cmd:{workload}", "--side", "old=cmd:env {workload}", "--baseline", "old")
QUICK = ("--gates", "off", "--rounds", "6", "--same-vs-same", "off", "--positive-control", "off")
RUN = ("--explain", "off", "--plots", "off", "--out", "run")
# The raw record of the run, which keeps the command as typed and is never shared.
CAPTURE = "capture.jsonl"
SHARED = {"results.json", "results.md", "report.html", "plan.tsv"}
PROGRAMS = ("redis-server", "redis-sentinel", "valkey-server", "redis-cli", "valkey-cli")

# Each form: its words (``{pw}`` the password) and the words as the shown command gives them.
FORMS: dict[str, tuple[str, str]] = {
    "server": (
        "env MASTERAUTH={pw} ./redis-server redis.conf --replicaof 127.0.0.1 6380 "
        "--masteruser app --masterauth {pw} --masterauth={pw} --requirepass {pw} "
        "--tls-key-file-pass {pw} --port 6380",
        "env 'MASTERAUTH=<hidden>' ./redis-server redis.conf --replicaof 127.0.0.1 6380 "
        "--masteruser app --masterauth '<hidden>' '--masterauth=<hidden>' --requirepass "
        "'<hidden>' --tls-key-file-pass '<hidden>' --port 6380",
    ),
    "sentinel lines": (
        "./redis-sentinel sentinel.conf --sentinel auth-user mymaster app --sentinel auth-pass "
        "mymaster {pw} --sentinel sentinel-user app --sentinel sentinel-pass {pw} --port 26380",
        "./redis-sentinel sentinel.conf --sentinel auth-user mymaster app --sentinel auth-pass "
        "mymaster '<hidden>' --sentinel sentinel-user app --sentinel sentinel-pass '<hidden>' "
        "--port 26380",
    ),
    "valkey server as a sentinel": (
        "./valkey-server --primaryuser app --primaryauth {pw} --sentinel --sentinel AUTH-PASS "
        "mymaster {pw}",
        "./valkey-server --primaryuser app --primaryauth '<hidden>' --sentinel --sentinel "
        "AUTH-PASS mymaster '<hidden>'",
    ),
    "sentinel set": (
        "./redis-cli -p 26379 SENTINEL SET mymaster auth-user app auth-pass {pw} quorum 2",
        "./redis-cli -p 26379 SENTINEL SET mymaster auth-user app auth-pass '<hidden>' quorum 2",
    ),
    "sentinel config set": (
        "./valkey-cli -p 26379 sentinel config set sentinel-user app sentinel-pass {pw}",
        "./valkey-cli -p 26379 sentinel config set sentinel-user app sentinel-pass '<hidden>'",
    ),
}
# The forms given in the config's workload.
CONFIG_FORMS = ("sentinel lines", "sentinel set")
# Every form after the ``:`` command of the shell, and memtier's command text, in one text.
SCRIPT = (
    "; ".join(f": {words}" for words, _shown in FORMS.values())
    + "; : memtier_benchmark --command 'SENTINEL SET mymaster auth-pass {pw}'"
)
# In a shell text each password is shown as ``<hidden>`` without quotes of its own.
SHOWN_SCRIPT = SCRIPT.format(pw="<hidden>")


def _stubs(folder: Path) -> None:
    for program in PROGRAMS:
        path = folder / program
        path.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        path.chmod(0o755)


def _argv(form: str, password: str) -> list[str]:
    return shlex.split(FORMS[form][0].format(pw=password))


def _run(
    cli: Cli,
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    password: str,
    placement: str,
    form: str,
) -> dict[str, Any]:
    """Plan and run one placement in a folder of its own; return the run's results.

    Each password's run has a folder named alike, so the two configurations
    differ in the password alone.
    """
    folder.mkdir()
    monkeypatch.chdir(folder)
    _stubs(folder)
    if placement == "config":
        workload = "[workload]\nargv = " + json.dumps(_argv(form, password)) + "\n"
        (folder / "pairbench.toml").write_text(workload, encoding="utf-8")
        tail: tuple[str, ...] = ("--config", "pairbench.toml")
    elif placement == "shell":
        tail = ("--", "sh", "-c", SCRIPT.format(pw=password))
    else:
        tail = ("--", *_argv(form, password))
    planned = cli("plan", *SIDES, *QUICK, *tail)
    assert planned.code == EXIT_OK, planned.err
    result = cli("run", *SIDES, *QUICK, *RUN, *tail)
    assert result.code == EXIT_OK, result.err
    for text in (planned.out, planned.err, result.out, result.err):
        assert password not in text
    shared = sorted(
        path for path in (folder / "run").rglob("*") if path.is_file() and path.name != CAPTURE
    )
    assert {path.name for path in shared} >= SHARED
    for path in shared:
        assert password.encode() not in path.read_bytes(), path.name
    results: dict[str, Any] = json.loads((folder / "run" / "results.json").read_text("utf-8"))
    results["plan printed"] = planned.out
    return results


def _hashes(results: dict[str, Any]) -> dict[str, str]:
    found = {"config": results["provenance"]["config_sha256"]}
    for side in results["sides"]:
        found[f"{side['name']} fingerprint"] = side["fingerprint"]
        found[f"{side['name']} arguments"] = side["identity"]["argv_sha256"]
    return found


PLACEMENTS = [
    *((form, "after the separator") for form in FORMS),
    *((form, "config") for form in CONFIG_FORMS),
    ("every form", "shell"),
]


@pytest.mark.parametrize(("form", "placement"), PLACEMENTS)
def test_a_run_writes_no_server_password_and_the_same_hashes_for_each(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str, placement: str
) -> None:
    first, second = (
        _run(cli, tmp_path / where, monkeypatch, password, placement, form)
        for where, password in zip(("one", "two"), PASSWORDS, strict=True)
    )

    assert _hashes(first) == _hashes(second)
    assert first["plan printed"] == second["plan printed"]
    if placement == "shell":
        assert first["run"]["command"].endswith("-- " + shlex.join(["sh", "-c", SHOWN_SCRIPT]))
    elif placement != "config":
        assert first["run"]["command"].endswith("-- " + FORMS[form][1])
