# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A client named only in a side's spec keeps its password out of every shared file.

Two command sides run ``./build-old/CLIENT {workload}`` and
``./build-new/CLIENT {workload}``, and the shared workload holds the
client's password option. The shown command and ``config_sha256`` read the
workload after each side's own words, as the fingerprint does, so the
password is hidden in ``results.json``, ``results.md`` and ``report.html``,
and every published hash is the same for two passwords. This holds with the
workload after ``--``, with it in the config file, with the sides in the
config file, and for ``compare`` of the capture.

In a shell text a credential's value ends at an operator in the hash as it
does in the shown command, so two programs behind one credential
(``sh -c "API_KEY=VALUE;./bench-old"`` and ``...;./bench-new``) are two sides:
``plan`` takes them and ``compare`` refuses to pool their captures, while one
program behind two credentials stays one side and pools.
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

# Made-up passwords that hold no credential word, so only the client's option hides them.
PASSWORDS = ("kiwi7mango", "plum4grape")
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
# The command line before the workload, as the shown command gives it.
SHOWN_SIDES = (
    "--side 'old=cmd:<hidden>' --side 'new=cmd:<hidden>' --baseline old --gates off --rounds 6 "
    "--same-vs-same off --positive-control off --explain off --plots off"
)

# Each client: the words of the side's spec after the program and before ``{workload}``,
# the workload (``{}`` the password), and the workload as the shown command gives it.
CLIENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "redis-benchmark": ((), ("-a", "{}", "-n", "1000"), "-a '<hidden>' -n 1000"),
    "redis-cli": ((), ("-a", "{}", "PING"), "-a '<hidden>' PING"),
    "mysql": ((), ("-p{}", "shop"), "'-p<hidden>' shop"),
    "mysqlslap": ((), ("-p{}", "--concurrency=4"), "'-p<hidden>' --concurrency=4"),
    "sshpass": ((), ("-p", "{}", "true"), "-p '<hidden>' true"),
    "ab": (
        (),
        ("-A", "bench:{}", "http://localhost:8000/"),
        "-A 'bench:<hidden>' http://localhost:8000/",
    ),
    "mytool": (("--api-key",), ("{}", "-n", "1000"), "'<hidden>' -n 1000"),
}


def programs(root: Path, client: str) -> dict[str, list[str]]:
    """Write two builds of a client that do nothing, and return each side's command."""
    extra, _workload, _shown = CLIENTS[client]
    commands: dict[str, list[str]] = {}
    for build in ("old", "new"):
        folder = root / f"build-{build}"
        folder.mkdir(parents=True, exist_ok=True)
        program = folder / client
        program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        program.chmod(0o755)
        commands[build] = [str(program), *extra, "{workload}"]
    return commands


def workload(client: str, password: str) -> list[str]:
    return [word.replace("{}", password) for word in CLIENTS[client][1]]


def run(cli: Cli, root: Path, client: str, password: str, placement: str) -> Path:
    """Run the two sides with one password in one placement; return the run folder.

    Every run writes to the same folder, which is then moved aside under the
    password's name, so the configs of two runs differ in the password alone.
    """
    commands = programs(root, client)
    out = root / placement
    out.mkdir(parents=True, exist_ok=True)
    config = out / "pairbench.toml"
    sides = ["--side", f"old=cmd:{' '.join(commands['old'])}"]
    sides += ["--side", f"new=cmd:{' '.join(commands['new'])}", "--baseline", "old"]
    if placement == "after-separator":
        args: list[Any] = [
            "run",
            *sides,
            *QUICK,
            "--out",
            out / "out",
            "--",
            *workload(client, password),
        ]
    elif placement == "config-workload":
        config.write_text(
            "[workload]\nargv = " + json.dumps(workload(client, password)) + "\n", encoding="utf-8"
        )
        args = ["run", "--config", config, *sides, *QUICK, "--out", out / "out"]
    else:
        tables = "".join(
            f"[sides.{build}]\ncmd = {json.dumps(command)}\n"
            + ("baseline = true\n" if build == "old" else "")
            for build, command in commands.items()
        )
        config.write_text(tables, encoding="utf-8")
        args = [
            "run",
            "--config",
            config,
            *QUICK,
            "--out",
            out / "out",
            "--",
            *workload(client, password),
        ]
    result = cli(*args)
    assert result.code == EXIT_OK, result.err
    return (out / "out").rename(out / password)


def leaked(folder: Path, password: str, files: tuple[str, ...] = SHARED_FILES) -> list[str]:
    """Return each shared file that holds the password or any six characters of it in a row."""
    found: list[str] = []
    for name in files:
        text = (folder / name).read_text(encoding="utf-8")
        pieces = [password[at : at + 6] for at in range(len(password) - 5)]
        found.extend(f"{name}: {piece}" for piece in pieces if piece in text)
    return found


def hashes(folder: Path) -> dict[str, Any]:
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return {
        "config_sha256": results["provenance"]["config_sha256"],
        "fingerprints": {side["name"]: side["fingerprint"] for side in results["sides"]},
        "command": results["run"]["command"],
    }


@pytest.mark.parametrize("placement", ["after-separator", "config-workload", "config-sides"])
@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_a_client_named_only_in_the_side_spec_hides_its_password(
    cli: Cli, tmp_path: Path, client: str, placement: str
) -> None:
    folders = [run(cli, tmp_path, client, password, placement) for password in PASSWORDS]

    for folder, password in zip(folders, PASSWORDS, strict=True):
        assert leaked(folder, password) == []
    first, second = (hashes(folder) for folder in folders)
    assert first == second
    shown = CLIENTS[client][2]
    if placement == "after-separator":
        assert first["command"] == f"pairbench run {SHOWN_SIDES} --out out -- {shown}"
    elif placement == "config-workload":
        assert first["command"] == (
            f"pairbench run --config pairbench.toml {SHOWN_SIDES} --out out"
        )
    else:
        assert first["command"] == (
            "pairbench run --config pairbench.toml --gates off --rounds 6 --same-vs-same off "
            f"--positive-control off --explain off --plots off --out out -- {shown}"
        )


@pytest.mark.parametrize("client", ["redis-benchmark", "mysql", "mytool"])
def test_compare_of_the_capture_hides_the_password_as_run_does(
    cli: Cli, tmp_path: Path, client: str
) -> None:
    folder = run(cli, tmp_path, client, PASSWORDS[0], "after-separator")
    compared_folder = tmp_path / "compared"
    compared = cli("compare", folder / "capture.jsonl", "--out", compared_folder)

    assert compared.code == EXIT_OK, compared.err
    assert sorted(path.name for path in compared_folder.iterdir()) == sorted(COMPARED_FILES)
    assert leaked(compared_folder, PASSWORDS[0], COMPARED_FILES) == []
    assert hashes(compared_folder) == hashes(folder)


# Two made-up credentials, and shell texts that give one of them before an operator and a
# program after it; ``{c}`` is the credential and ``{p}`` the program.
CREDENTIAL = "Zq9vLm3Kx"
OTHER_CREDENTIAL = "Wp4rTn8Yc"
SHELL_TEXTS = {
    "semicolon": "API_KEY={c};./bench-{p}",
    "semicolon-and-blank": "API_KEY={c}; ./bench-{p}",
    "and": "API_KEY={c}&&./bench-{p}",
    "pipe": "API_KEY={c}|./bench-{p}",
    "header": "curl -H 'Authorization: Bearer {c}'; ./bench-{p}",
    "option": "tool --api-key={c}&&./bench-{p}",
    "shell-text-inside": 'sh -c "API_KEY={c}&&./bench-{p}"',
    "eval": "eval 'PGPASSWORD={c} ./bench-{p} -h db.example'",
    "eval-in-braces": "{ eval 'PGPASSWORD={c} ./bench-{p} -h db.example'; }",
    "eval-after-then": "if true; then eval 'PGPASSWORD={c} ./bench-{p} -h db.example'; fi",
    "eval-of-a-value-in-escaped-quotes": (
        "eval 'PGPASSWORD='\\''made {c}'\\'' ./bench-{p} -h db.example'"
    ),
}
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
# The note that two sides with one fingerprint differ in a hidden value.
HIDDEN_VALUE_NOTE = "sides_differ_in_hidden_value"


def shell_side(name: str, text: str, credential: str, program: str) -> str:
    """A ``--side`` value that runs one shell text through ``sh -c``."""
    typed = text.replace("{c}", credential).replace("{p}", program)
    return f"{name}=cmd:sh -c {shlex.quote(typed)}"


@pytest.mark.parametrize("text", list(SHELL_TEXTS.values()), ids=list(SHELL_TEXTS))
def test_plan_takes_two_programs_behind_one_credential_in_a_shell_text_as_two_sides(
    cli: Cli, text: str
) -> None:
    result = cli(
        "plan",
        "--side",
        shell_side("a", text, CREDENTIAL, "old"),
        "--side",
        shell_side("b", text, CREDENTIAL, "new"),
    )

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert HIDDEN_VALUE_NOTE not in result.err
    assert CREDENTIAL not in result.out + result.err


@pytest.mark.parametrize("text", list(SHELL_TEXTS.values()), ids=list(SHELL_TEXTS))
def test_plan_refuses_one_program_behind_two_credentials_in_a_shell_text(
    cli: Cli, text: str
) -> None:
    result = cli(
        "plan",
        "--side",
        shell_side("a", text, CREDENTIAL, "old"),
        "--side",
        shell_side("b", text, OTHER_CREDENTIAL, "old"),
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def shell_capture(
    cli: Cli, folder: Path, credential: str, program: str, text: str = SHELL_TEXTS["semicolon"]
) -> str:
    """Run a side that gives a credential and then runs a program in ``sh -c``; return its id."""
    result = cli(
        "run",
        "--side",
        shell_side("new", text, credential, program),
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


def test_compare_refuses_to_pool_two_programs_behind_one_credential(
    cli: Cli, benches: Path
) -> None:
    one = shell_capture(cli, benches / "one", CREDENTIAL, "old")
    two = shell_capture(cli, benches / "two", CREDENTIAL, "new")
    result = cli("compare", benches / "one" / "capture.jsonl", benches / "two" / "capture.jsonl")

    assert result.code == EXIT_ANALYSIS
    assert result.err == refusal_text(
        f"E_POOL_SIDE_DRIFT: the fingerprint of new differs between the captures {one} and {two}"
    )
    assert CREDENTIAL not in result.out + result.err


def test_compare_refuses_to_pool_two_programs_behind_one_credential_in_an_eval(
    cli: Cli, benches: Path
) -> None:
    one = shell_capture(cli, benches / "one", CREDENTIAL, "old", text=SHELL_TEXTS["eval"])
    two = shell_capture(cli, benches / "two", CREDENTIAL, "new", text=SHELL_TEXTS["eval"])
    result = cli("compare", benches / "one" / "capture.jsonl", benches / "two" / "capture.jsonl")

    assert result.code == EXIT_ANALYSIS
    assert result.err == refusal_text(
        f"E_POOL_SIDE_DRIFT: the fingerprint of new differs between the captures {one} and {two}"
    )
    assert CREDENTIAL not in result.out + result.err
    for name in SHARED_FILES:
        assert CREDENTIAL not in (benches / "one" / name).read_text(encoding="utf-8")


def test_compare_pools_one_program_behind_two_credentials(cli: Cli, benches: Path) -> None:
    shell_capture(cli, benches / "one", CREDENTIAL, "old")
    shell_capture(cli, benches / "two", OTHER_CREDENTIAL, "old")
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
    for credential in (CREDENTIAL, OTHER_CREDENTIAL):
        assert credential not in json.dumps(pooled)
