# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Through ``plan``, ``run`` and ``compare``: a side's head changes nothing the workload hides.

Each head a side's spec runs before ``{workload}`` (``timeout 60``,
``./runner``, ``docker run``, a client) leaves the texts of a runner the
workload names read as they are alone: two programs after a credential give
the side two argument hashes, and two passwords give it one. A value the
client of one side hides in the shared workload is hidden in the argument
hash of every side, so two runs that differ in it alone pool, and the
sidecar of hash inputs rebuilds each side's hash.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pairbench.errors import EXIT_OK
from pairbench.model import HIDDEN

Cli = Callable[..., Any]

PASSWORDS = ("kiwi7mango", "plum4grape")
PROGRAMS = ("bench-old", "bench-new")
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
COMPARED_FILES = ("results.json", "results.md")
# The programs the heads name, each a made-up one that does nothing, first on PATH.
FAKES = ("timeout", "nice", "sudo", "docker", "time", "perf", "python3", "redis-benchmark")
HEADS: dict[str, list[str]] = {
    "timeout": ["timeout", "60"],
    "nice": ["nice"],
    "sudo-u": ["sudo", "-u", "bench"],
    "own-runner": ["./runner"],
    "docker-run": ["docker", "run", "--rm", "made-up/image:1.0"],
    "time-v": ["time", "-v"],
    "perf-stat": ["perf", "stat", "--"],
    "python-m": ["python3", "-m", "runner"],
    "client": ["redis-benchmark"],
}
TEXT = "API_KEY={s};./{p}"
WORKLOADS: dict[str, list[str]] = {
    "ssh": ["ssh", "made-up-host", TEXT],
    "hyperfine": ["hyperfine", TEXT],
}
# What the sidecar writer says of a sidecar that holds the values the shared files hide.
SIDECAR_PRIVATE = (
    "hash_inputs.json is private: the shared files do not show 4 of the values it holds; "
    "keep it with capture.jsonl\n"
)
ARGV_HASH = re.compile(r"^# side (?P<name>\S+): identified \(argv_sha256=(?P<hash>[0-9a-f]{64})")


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder, with the head programs, a runner and a benchmark that do nothing."""
    programs = tmp_path / "bin"
    programs.mkdir()
    folder = tmp_path / "work"
    folder.mkdir()
    for path in (*(programs / name for name in FAKES), folder / "runner", folder / "bench"):
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.chdir(folder)
    return folder


def write_sides(work: Path, sides: dict[str, list[str]]) -> str:
    """Write one side per command, the first the baseline; return the config's name."""
    tables = "".join(
        f"[sides.{name}]\ncmd = {json.dumps(cmd)}\n" + ("baseline = true\n" if k == 0 else "")
        for k, (name, cmd) in enumerate(sides.items())
    )
    (work / "sides.toml").write_text(tables + '[workload]\ndriver = "wall"\n', encoding="utf-8")
    return "sides.toml"


def argv_hashes(cli: Cli, config: str, workload: list[str]) -> dict[str, str]:
    """Plan the config with the workload; return each side's argument hash the plan shows."""
    result = cli("plan", "--config", config, "--", *workload)
    assert result.code == EXIT_OK, result.err
    assert pieces(result.out + result.err) == []
    found = (ARGV_HASH.match(line) for line in result.out.splitlines())
    return {match["name"]: match["hash"] for match in found if match}


def pieces(text: str) -> list[str]:
    """Return each six characters in a row of either password that the text holds."""
    return [
        password[at : at + 6]
        for password in PASSWORDS
        for at in range(len(password) - 5)
        if password[at : at + 6] in text
    ]


def filled(runner: str, password: str, program: str) -> list[str]:
    return [word.replace("{s}", password).replace("{p}", program) for word in WORKLOADS[runner]]


def head_sides(work: Path, head: str) -> str:
    return write_sides(
        work, {"a": [*HEADS[head], "{workload}"], "b": ["env", "PB_SIDE=2", "{workload}"]}
    )


PAIRS = [(head, runner) for head in HEADS for runner in WORKLOADS]


@pytest.mark.parametrize(("head", "runner"), PAIRS)
def test_plan_gives_two_programs_after_a_side_head_two_argument_hashes(
    cli: Cli, work: Path, head: str, runner: str
) -> None:
    config = head_sides(work, head)
    old, new = (argv_hashes(cli, config, filled(runner, PASSWORDS[0], p)) for p in PROGRAMS)

    assert old["a"] != new["a"]
    assert old["b"] != new["b"]


@pytest.mark.parametrize(("head", "runner"), PAIRS)
def test_plan_gives_two_passwords_after_a_side_head_one_argument_hash(
    cli: Cli, work: Path, head: str, runner: str
) -> None:
    config = head_sides(work, head)
    one, other = (argv_hashes(cli, config, filled(runner, s, PROGRAMS[0])) for s in PASSWORDS)

    assert one == other


# --- a word one side's client hides is hidden in every side's hash -------------------------

MIXED = {"a": ["redis-benchmark", "{workload}"], "b": ["./bench", "{workload}"]}
NO_CLIENT = {"a": ["./runner", "{workload}"], "b": ["./bench", "{workload}"]}


def test_plan_gives_the_side_with_no_client_one_hash_for_two_passwords(
    cli: Cli, work: Path
) -> None:
    config = write_sides(work, MIXED)
    one, other = (argv_hashes(cli, config, ["-a", s, "-n", "1000"]) for s in PASSWORDS)

    assert one == other


def test_plan_still_tells_two_counts_apart_on_the_side_with_no_client(cli: Cli, work: Path) -> None:
    config = write_sides(work, MIXED)
    one, other = (argv_hashes(cli, config, ["-a", PASSWORDS[0], "-n", n]) for n in ("1000", "2000"))

    assert one["a"] != other["a"]
    assert one["b"] != other["b"]


def test_plan_keeps_the_word_when_no_side_runs_a_client(cli: Cli, work: Path) -> None:
    config = write_sides(work, NO_CLIENT)
    result = [cli("plan", "--config", config, "--", "-a", s, "-n", "1000") for s in PASSWORDS]
    hashes = [
        {m["name"]: m["hash"] for m in map(ARGV_HASH.match, r.out.splitlines()) if m}
        for r in result
    ]

    assert [r.code for r in result] == [EXIT_OK, EXIT_OK]
    assert hashes[0]["b"] != hashes[1]["b"]


def load_writer(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hash_inputs_side_heads", repo_root / "tools" / "hash_inputs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.slow
def test_two_runs_that_differ_in_a_password_one_side_s_client_hides_pool(
    cli: Cli, work: Path, repo_root: Path
) -> None:
    config = write_sides(work, MIXED)
    folders = []
    for password in PASSWORDS:
        words = ["-a", password, "-n", "1000"]
        result = cli("run", "--config", config, *QUICK, "--out", "out", "--", *words)
        assert result.code == EXIT_OK, result.err
        folders.append((work / "out").rename(work / password))
    compared = cli(
        "compare", folders[0] / "capture.jsonl", folders[1] / "capture.jsonl", "--out", "pooled"
    )
    writer = load_writer(repo_root)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        written = writer.main([str(folders[0])])
    sidecar = json.loads((folders[0] / "hash_inputs.json").read_text(encoding="utf-8"))
    fingerprints = [
        {s["name"]: s["fingerprint"] for s in json.loads((f / "results.json").read_text())["sides"]}
        for f in folders
    ]

    assert compared.code == EXIT_OK, compared.err
    assert pieces(compared.out + compared.err) == []
    for folder in folders:
        for name in SHARED_FILES:
            assert pieces((folder / name).read_text(encoding="utf-8")) == []
    for name in COMPARED_FILES:
        assert pieces((work / "pooled" / name).read_text(encoding="utf-8")) == []
    pool = json.loads((work / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert pool["run"]["pooled"] is True
    assert fingerprints[0] == fingerprints[1]
    assert (written, err.getvalue()) == (EXIT_OK, SIDECAR_PRIVATE)
    assert sidecar["sides"]["b"]["argv_sha256"] == ["./bench", "-a", HIDDEN, "-n", "1000"]
    assert pieces((folders[0] / "hash_inputs.json").read_text(encoding="utf-8")) == []
