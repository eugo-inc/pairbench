# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A password given in a form that holds a blank, or typed in a comment, stays out of shared files.

A rule of ``ACL SETUSER`` that gives a password hides the rest of its
argument, blanks included, so a password with a blank in it, or a blank
right after the rule's ``>``, shows none of its words. A password in a shell
comment on the line of a client's command (``# -a VALUE``, ``#AUTH VALUE``)
is hidden as the client hides it. Two runs of the same workload that differ
in the password alone write ``results.json``, ``results.md`` and
``report.html`` with no six characters of the password in a row, give one
shown command, one ``config_sha256`` and one fingerprint per side, and
``compare`` pools their captures with no part of either password on its
streams or in the pooled files. Every value is made up.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_OK
from pairbench.model import HIDDEN

Cli = Callable[..., Any]

# Made-up passwords that hold no credential word, so only the client's rules hide them.
PASSWORDS = ("kiwi7mango42", "plum4grape19")
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
SHARED_FILES = ("results.json", "results.md", "report.html")
# What ``compare --out`` writes.
COMPARED_FILES = ("results.json", "results.md")
# Two sides that run the shared workload, told apart by a variable.
SIDES = (
    '[sides.a]\ncmd = ["env", "PB_SIDE=1", "{workload}"]\nbaseline = true\n'
    '[sides.b]\ncmd = ["env", "PB_SIDE=2", "{workload}"]\n'
)
SHOWN_HEAD = (
    "pairbench run --config pairbench.toml --gates off --rounds 6 --same-vs-same off "
    "--positive-control off --explain off --plots off --out out --"
)
CLIENTS = ("redis-cli", "valkey-cli", "memtier_benchmark")

# Each workload: its words with ``{s}`` for the password, and the workload as shown.
FORMS: dict[str, tuple[list[str], str]] = {
    "acl password with a blank": (
        ["redis-cli", "ACL", "SETUSER", "app", "on", ">{s} {s}x"],
        f"redis-cli ACL SETUSER app on '>{HIDDEN}'",
    ),
    "acl blank right after the rule": (
        ["valkey-cli", "ACL", "SETUSER", "app", "> {s}"],
        f"valkey-cli ACL SETUSER app '>{HIDDEN}'",
    ),
    "acl password to remove with a blank after sh -c": (
        ["sh", "-c", "redis-cli ACL SETUSER app on '<{s} {s}x'"],
        shlex.join(["sh", "-c", f"redis-cli ACL SETUSER app on '<{HIDDEN}'"]),
    ),
    "acl password with a blank in the command of memtier_benchmark": (
        ["memtier_benchmark", "--command", "ACL SETUSER app on '>{s} {s}x'"],
        shlex.join(["memtier_benchmark", "--command", f"ACL SETUSER app on '>{HIDDEN}'"]),
    ),
    "password option in a comment after sh -c": (
        ["sh", "-c", "redis-cli -h made-up-host PING # -a {s}"],
        shlex.join(["sh", "-c", f"redis-cli -h made-up-host PING # -a {HIDDEN}"]),
    ),
    "client's command glued to a comment sign after sh -c": (
        ["sh", "-c", "valkey-cli PING #AUTH {s}"],
        shlex.join(["sh", "-c", f"valkey-cli PING #AUTH {HIDDEN}"]),
    ),
}


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder, with made-up clients that do nothing first on PATH."""
    programs = tmp_path / "bin"
    programs.mkdir()
    for name in CLIENTS:
        path = programs / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "pairbench.toml").write_text(SIDES, encoding="utf-8")
    monkeypatch.chdir(folder)
    return folder


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of any password that the text holds."""
    return [
        password[at : at + 6]
        for password in PASSWORDS
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


def read(folder: Path, names: tuple[str, ...]) -> str:
    return "".join((folder / name).read_text(encoding="utf-8") for name in names)


def hashes(folder: Path) -> dict[str, Any]:
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return {
        "config_sha256": results["provenance"]["config_sha256"],
        "fingerprints": {side["name"]: side["fingerprint"] for side in results["sides"]},
        "command": results["run"]["command"],
    }


def run(cli: Cli, work: Path, words: list[str], name: str) -> Path:
    """Run the two sides with one workload; return the run folder, moved aside under ``name``."""
    result = cli("run", "--config", "pairbench.toml", *QUICK, "--out", "out", "--", *words)
    assert result.code == EXIT_OK, result.err
    assert pieces(result.out + result.err) == []
    return (work / "out").rename(work / name)


@pytest.mark.slow
@pytest.mark.parametrize("form", sorted(FORMS))
def test_the_password_stays_out_of_every_shared_file(cli: Cli, work: Path, form: str) -> None:
    words, shown = FORMS[form]
    folders = [
        run(cli, work, [word.replace("{s}", password) for word in words], password)
        for password in PASSWORDS
    ]
    compared = cli(
        "compare", folders[0] / "capture.jsonl", folders[1] / "capture.jsonl", "--out", "pooled"
    )

    assert compared.code == EXIT_OK, compared.err
    assert pieces(compared.out + compared.err) == []
    for folder in folders:
        assert pieces(read(folder, SHARED_FILES)) == []
    assert pieces(read(work / "pooled", COMPARED_FILES)) == []
    pool = json.loads((work / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert pool["run"]["pooled"] is True
    first, second = (hashes(folder) for folder in folders)
    assert first == second
    assert first["command"] == f"{SHOWN_HEAD} {shown}"
