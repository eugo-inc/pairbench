# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Through ``plan`` and ``run``: a command side next to an image side whose entrypoint is a client.

The command side runs the image by hand (``docker run IMAGE {workload}``); the image side
runs the same image as an image side, whose recorded entrypoint is a client that takes a
password after ``-a``. The shared files hide that password, and the argument hash of the
command side is taken with it hidden as well, so a published hash cannot confirm a guess.
An entrypoint that is no client keeps the word in every hash.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pairbench.errors import EXIT_OK
from pairbench.model import HIDDEN
from pairbench.sides.identity import hashed_sha256

Cli = Callable[..., Any]

PASSWORDS = ("kiwi7mango42", "plum4grape19")
IMAGE = "localhost/made-up-bench:1"
HEAD = ["docker", "run", "--rm", IMAGE]
CLIENT = "redis-benchmark"
NO_CLIENT = "./made-up-tool"
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--plots",
    "off",
)
SHARED_FILES = ("results.json", "results.md", "report.html")
# What the explain step says of a side whose identity differs from the one the run recorded.
SIDE_CHANGED = "the identity of the side differs from the one the run recorded"
ARGV_HASH = re.compile(r"^# side (?P<name>\S+): identified \(argv_sha256=(?P<hash>[0-9a-f]{64})")
# A made-up engine: it answers the calls pairbench makes and never starts a container. The
# image's entrypoint is the program PB_MADE_UP_ENTRYPOINT names.
ENGINE = """\
import json, os, sys, time
args = sys.argv[1:]
verb = args[0] if args else ""
if verb == "version":
    print("9.9.9")
elif verb == "info":
    print("{}")
elif verb == "image":
    print(json.dumps({
        "Id": "sha256:" + "0123456789abcdef" * 4,
        "RepoDigests": [],
        "Os": "linux",
        "Architecture": "arm64",
        "Config": {"Entrypoint": [os.environ["PB_MADE_UP_ENTRYPOINT"]], "Cmd": None},
    }))
elif verb == "inspect":
    if any("State" in word for word in args):
        print(json.dumps({
            "ExitCode": 0,
            "StartedAt": "2001-02-03T04:05:06.100000000Z",
            "FinishedAt": "2001-02-03T04:05:06.350000000Z",
        }))
    else:
        print("4321")
elif verb == "run":
    value = time.monotonic_ns() % 1000003 / 1000.0 + 1.0
    print('::pairbench:: {"case": "a", "value": %s, "unit": "s", "better": "lower"}' % value)
elif verb not in ("rm", "kill", "pull", "ps"):
    print("unexpected: " + " ".join(args), file=sys.stderr)
    sys.exit(2)
"""
CONFIG = f"""\
[sides.old]
cmd = {json.dumps([*HEAD, "{workload}"])}
baseline = true
[sides.new]
image = "{IMAGE}"
[launch]
pull = "never"
engine = "docker"
[workload]
driver = "lines"
"""


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder with the config, and the made-up engine first on PATH."""
    programs = tmp_path / "bin"
    programs.mkdir()
    engine = programs / "docker"
    engine.write_text(f"#!{sys.executable}\n{ENGINE}", encoding="utf-8")
    engine.chmod(0o755)
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "sides.toml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PB_MADE_UP_ENTRYPOINT", CLIENT)
    monkeypatch.chdir(folder)
    return folder


def workload(password: str) -> list[str]:
    return ["-s", "127.0.0.1", "-a", password, "-n", "1000"]


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of either password that the text holds."""
    return [
        password[at : at + 6]
        for password in PASSWORDS
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


def argv_hashes(cli: Cli, password: str) -> dict[str, str]:
    """Plan the config with the password; return each side's argument hash the plan shows."""
    result = cli("plan", "--config", "sides.toml", "--", *workload(password))
    assert result.code == EXIT_OK, result.err
    assert pieces(result.out + result.err) == []
    found = (ARGV_HASH.match(line) for line in result.out.splitlines())
    return {match["name"]: match["hash"] for match in found if match}


# The command side's words as they are hashed, with the client's password hidden.
HIDDEN_HASH = hashed_sha256([*HEAD, *workload(HIDDEN)])


def test_plan_takes_the_command_side_s_hash_with_the_image_client_s_password_hidden(
    cli: Cli, work: Path
) -> None:
    one, other = (argv_hashes(cli, password) for password in PASSWORDS)

    assert one["old"] == HIDDEN_HASH
    assert other["old"] == HIDDEN_HASH
    assert hashed_sha256([*HEAD, *workload(PASSWORDS[0])]) != HIDDEN_HASH


def test_plan_keeps_the_word_when_the_image_s_entrypoint_is_no_client(
    cli: Cli, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PB_MADE_UP_ENTRYPOINT", NO_CLIENT)
    one, other = (
        cli("plan", "--config", "sides.toml", "--", *workload(password)) for password in PASSWORDS
    )
    hashes = [
        {m["name"]: m["hash"] for m in map(ARGV_HASH.match, r.out.splitlines()) if m}
        for r in (one, other)
    ]

    assert [one.code, other.code] == [EXIT_OK, EXIT_OK]
    assert hashes[0]["old"] == hashed_sha256([*HEAD, *workload(PASSWORDS[0])])
    assert hashes[0]["old"] != hashes[1]["old"]


def load_writer(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hash_inputs_image_client", repo_root / "tools" / "hash_inputs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.slow
def test_a_run_publishes_the_command_side_s_hash_with_the_image_client_s_password_hidden(
    cli: Cli, work: Path, repo_root: Path
) -> None:
    folders = []
    for password in PASSWORDS:
        result = cli(
            "run", "--config", "sides.toml", *QUICK, "--out", "out", "--", *workload(password)
        )
        assert result.code == EXIT_OK, result.err
        assert "E_SIDE_CHANGED" not in result.err
        assert SIDE_CHANGED not in result.err
        assert pieces(result.out + result.err) == []
        folders.append((work / "out").rename(work / password))
    writer = load_writer(repo_root)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        written = writer.main([str(folders[0])])
    sidecar = json.loads((folders[0] / "hash_inputs.json").read_text(encoding="utf-8"))
    sides = [
        {s["name"]: s for s in json.loads((f / "results.json").read_text())["sides"]}
        for f in folders
    ]

    for folder in folders:
        for name in SHARED_FILES:
            assert pieces((folder / name).read_text(encoding="utf-8")) == []
    assert [s["old"]["identity"]["argv_sha256"] for s in sides] == [HIDDEN_HASH, HIDDEN_HASH]
    assert sides[0]["old"]["fingerprint"] == sides[1]["old"]["fingerprint"]
    assert written == EXIT_OK
    assert sidecar["sides"]["old"]["argv_sha256"] == [*HEAD, *workload(HIDDEN)]
    assert pieces((folders[0] / "hash_inputs.json").read_text(encoding="utf-8")) == []
