# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the shared files of a run show of its command: results.json, results.md, report.html.

A command is recorded in the capture as typed, and the three shared files
show it cleaned. Each test reads the three files a run writes and checks
that a made-up secret is in none of them, and that a value that must stay
visible is in each. A secret is checked by an alphanumeric part of it too,
so that no quoting or escaping in a file can hide it from the search.
"""

from __future__ import annotations

import dataclasses
import html
import json
import shlex
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.results.writer import write_results
from pairbench.stats.selftest import synthetic_capture

SHARED_FILES = ("results.json", "results.md", "report.html")
RUN_LEAD = ("pairbench", "run", "--side", "new=cmd:true", "--")


def shared_texts(folder: Path) -> dict[str, str]:
    """The three shared files of a run folder, by name, as a reader sees them.

    The report page writes ``=``, quotes and ``@`` as character references,
    so its text is read back with the references resolved.
    """
    texts = {name: (folder / name).read_text(encoding="utf-8") for name in SHARED_FILES}
    texts["report.html"] = html.unescape(texts["report.html"])
    return texts


def analysed_from_capture(argv: tuple[str, ...], folder: Path) -> dict[str, str]:
    """Write the shared files of a made-up capture whose command line is ``argv``."""

    def value(entry: str, case: str, round_: int, u: float) -> float:
        return 2.0 + u if entry.startswith("new") else 1.0 + u

    capture = synthetic_capture(value, capture_id="made-up-command")
    capture = dataclasses.replace(capture, header=dataclasses.replace(capture.header, argv=argv))
    analysed = pairbench.analyse(capture)
    written = write_results(analysed, folder)
    (folder / "report.html").write_text(pairbench.render(written, "html"), encoding="utf-8")
    return shared_texts(folder)


def assert_absent(texts: dict[str, str], secrets: tuple[str, ...]) -> None:
    for where, text in texts.items():
        assert [s for s in secrets if s in text] == [], where


def assert_present(texts: dict[str, str], kept: tuple[str, ...]) -> None:
    for where, text in texts.items():
        assert [k for k in kept if k not in text] == [], where


def run_folder(cli: Any, tmp_path: Path, workload: tuple[str, ...]) -> tuple[Any, Path]:
    """Run ``pairbench run`` with two made-up command sides on ``workload``."""
    run = cli(
        "run",
        "--side",
        "new=cmd:{workload}",
        "--side",
        "old=cmd:env {workload}",
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
        "--out",
        "run",
        "--",
        *workload,
    )
    return run, tmp_path / "run"


@pytest.fixture
def clients_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put made-up clients on PATH: each one exits 0 and does nothing else."""
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in CLIENTS:
        stub = folder / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}:{Path('/usr/bin')}:{Path('/bin')}")
    monkeypatch.chdir(tmp_path)
    return folder


# ---------------------------------------------------------------------------
# a. The password options of common benchmark clients
# ---------------------------------------------------------------------------

CLIENTS = (
    "redis-benchmark",
    "redis-cli",
    "memtier_benchmark",
    "mysql",
    "mysqlslap",
    "mysqladmin",
    "sshpass",
    "ab",
    "curl",
)

# (a command with a client password in it, the made-up password, a text the shown command keeps)
CLIENT_FORMS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("redis-benchmark", "-a", "zqmtaa", "-q"), "zqmtaa", "redis-benchmark -a"),
    (("redis-cli", "-a", "zqmtab", "ping"), "zqmtab", "redis-cli -a"),
    (("memtier_benchmark", "-a", "zqmtac", "-n", "10"), "zqmtac", "memtier_benchmark -a"),
    (
        ("memtier_benchmark", "--authenticate", "zqmtad"),
        "zqmtad",
        "memtier_benchmark --authenticate",
    ),
    (("memtier_benchmark", "--authenticate=zqmtae"), "zqmtae", "--authenticate="),
    (("mysql", "-pzqmtaf", "benchdb"), "zqmtaf", "benchdb"),
    (("mysqlslap", "-pzqmtag", "--iterations=5"), "zqmtag", "--iterations=5"),
    (("mysqladmin", "-pzqmtah", "status"), "zqmtah", "mysqladmin"),
    (
        ("sshpass", "-p", "zqmtai", "ssh", "-p", "2222", "bench-host"),
        "zqmtai",
        "ssh -p 2222 bench-host",
    ),
    (("ab", "-A", "someuser:zqmtaj", "-n", "10"), "zqmtaj", "someuser:"),
    (("ab", "-P", "proxyuser:zqmtak", "-n", "10"), "zqmtak", "proxyuser:"),
    (("curl", "-u", "someuser:zqmtal", "-s"), "zqmtal", "curl -u"),
    (("curl", "--user", "someuser:zqmtam", "-s"), "zqmtam", "curl --user"),
    (("curl", "-U", "proxyuser:zqmtan", "-s"), "zqmtan", "curl -U"),
    (("curl", "--proxy-user", "proxyuser:zqmtao", "-s"), "zqmtao", "curl --proxy-user"),
    (("curl", "--proxy-user=proxyuser:zqmtap", "-s"), "zqmtap", "--proxy-user="),
)
# A database name after a ``-p`` that stands alone: mysql asks for the password then, and the
# next word is no password.
CLIENT_CONTROL = (("mysql", "-p", "zqmtdbname"), "mysql -p zqmtdbname")


@pytest.mark.parametrize(("args", "secret", "kept"), CLIENT_FORMS)
def test_each_client_password_form_is_in_no_shared_file(
    tmp_path: Path, args: tuple[str, ...], secret: str, kept: str
) -> None:
    texts = analysed_from_capture((*RUN_LEAD, *args), tmp_path)

    assert_absent(texts, (secret,))
    assert_present(texts, (kept,))


@pytest.mark.parametrize(("args", "secret", "kept"), CLIENT_FORMS)
def test_each_client_password_form_inside_sh_c_is_in_no_shared_file(
    tmp_path: Path, args: tuple[str, ...], secret: str, kept: str
) -> None:
    texts = analysed_from_capture((*RUN_LEAD, "sh", "-c", shlex.join(args)), tmp_path)

    assert_absent(texts, (secret,))
    assert_present(texts, (kept,))


@pytest.mark.parametrize("inside_shell", [False, True])
def test_the_database_name_after_a_lone_p_stays_in_every_shared_file(
    tmp_path: Path, inside_shell: bool
) -> None:
    args, kept = CLIENT_CONTROL
    argv = (*RUN_LEAD, "sh", "-c", shlex.join(args)) if inside_shell else (*RUN_LEAD, *args)

    assert_present(analysed_from_capture(argv, tmp_path), (kept,))


def test_a_run_of_clients_in_a_shell_shows_no_client_password(
    cli: Any, tmp_path: Path, clients_on_path: Path
) -> None:
    script = "; ".join(
        shlex.join(args) for args, _, _ in (*CLIENT_FORMS, (CLIENT_CONTROL[0], "", ""))
    )
    run, folder = run_folder(cli, tmp_path, ("sh", "-c", script))

    assert run.code == 0, run.err
    texts = shared_texts(folder)
    assert_absent(texts, tuple(secret for _, secret, _ in CLIENT_FORMS))
    assert_present(texts, (CLIENT_CONTROL[1], "ssh -p 2222 bench-host"))
    assert "zqmtaa" in (folder / "capture.jsonl").read_text(encoding="utf-8")


def test_a_run_through_sshpass_and_ssh_shows_no_client_password(
    cli: Any, tmp_path: Path, clients_on_path: Path
) -> None:
    remote = "redis-benchmark -a zqmtba -q; mysql -pzqmtbb zqmtdbname; ab -A someuser:zqmtbc x"
    workload = ("sshpass", "-p", "zqmtbd", "ssh", "-p", "2222", "bench-host", remote)
    run, folder = run_folder(cli, tmp_path, workload)

    assert run.code == 0, run.err
    texts = shared_texts(folder)
    assert_absent(texts, ("zqmtba", "zqmtbb", "zqmtbc", "zqmtbd"))
    assert_present(texts, ("ssh -p 2222 bench-host", "zqmtdbname", "someuser:"))


# ---------------------------------------------------------------------------
# b. Long random-looking values
# ---------------------------------------------------------------------------

# Made-up values the rule reads as random. Each holds a pattern that nothing
# else in the shared files holds, so a part of one left behind is found.
TOKEN = "XYz9" * 10
BASE64_SLASHES = "XYz9+XYz9/XYz9+XYz9/XYz9+XYz9/XYz9+XY=="
HEX_32 = "deadbeef" * 4
HEX_64 = "deadbeef" * 8
RANDOM_PARTS = ("XYz9", "z9XY", "deadbeef")

# (arguments of the workload, a text the shown command keeps). The text kept
# around a hidden path segment is what results.md keeps too, whose reproduce
# line cuts the paths of the command once more.
RANDOM_FORMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("tool", TOKEN), "tool"),
    (("tool", "--opt=" + TOKEN), "--opt="),
    (("tool", BASE64_SLASHES), "tool"),
    (("tool", "/" + BASE64_SLASHES), "tool"),
    (("tool", "data/" + TOKEN + "/out.json"), "out.json"),
    (
        ("curl", f"http://localhost:8000/v1/files/{TOKEN}/raw?part={TOKEN}&n=3"),
        "part=<hidden>&n=3",
    ),
    (("tool", HEX_32), "tool"),
    (("tool", HEX_64), "tool"),
    # Glued to an option of one letter, cut by a `+/` as a path would be, and a query
    # value written with percent escapes.
    (("tool", "-k" + HEX_32), "-k<hidden>"),
    (("tool", "XYz9" * 5 + "+/" + "XYz9" * 2 + "/XYz9XY=="), "tool"),
    (
        (
            "curl",
            "http://localhost:8000/v1/x?part="
            + BASE64_SLASHES.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")
            + "&n=3",
        ),
        "part=<hidden>&n=3",
    ),
)
# Values that stay shown: a commit id, a short image id, a digest, a version,
# a model name, a path of words, a number, a name in CamelCase with capitals and
# digits run together, and a UUID after a word.
COMMIT_ID = "cafebabe" * 5
RANDOM_CONTROLS: tuple[str, ...] = (
    "BM_ConvolutionNHWC3x3Stride2FP16TensorCore",
    "BM_LruCacheGetPutMixedKeyLen16ValLen64",
    "DEV-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    COMMIT_ID,
    "0ddba11cafe1",
    "sha256:" + "0ddba11c" * 8,
    "2.5.1+cu124",
    "made-up-org/MadeUp-Small-24B-Instruct-2501",
    "models/llama-3-8b-instruct/config.json",
    "1234567890" * 4,
)


@pytest.mark.parametrize(("args", "kept"), RANDOM_FORMS)
@pytest.mark.parametrize("inside_shell", [False, True])
def test_each_random_looking_value_is_in_no_shared_file(
    tmp_path: Path, args: tuple[str, ...], kept: str, inside_shell: bool
) -> None:
    workload = ("sh", "-c", shlex.join(args)) if inside_shell else args
    texts = analysed_from_capture((*RUN_LEAD, *workload), tmp_path)

    assert_absent(texts, RANDOM_PARTS)
    assert_present(texts, (kept,))


@pytest.mark.parametrize("inside_shell", [False, True])
def test_the_ordinary_values_stay_in_every_shared_file(tmp_path: Path, inside_shell: bool) -> None:
    args = ("tool", *RANDOM_CONTROLS)
    workload = ("sh", "-c", shlex.join(args)) if inside_shell else args

    assert_present(analysed_from_capture((*RUN_LEAD, *workload), tmp_path), RANDOM_CONTROLS)


def test_a_run_with_random_looking_values_shows_none_of_them(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    script = (
        "; ".join(shlex.join(("true", *args[1:])) for args, _ in RANDOM_FORMS)
        + "; "
        + shlex.join(("true", *RANDOM_CONTROLS))
    )
    run, folder = run_folder(cli, tmp_path, ("sh", "-c", script))

    assert run.code == 0, run.err
    texts = shared_texts(folder)
    assert_absent(texts, RANDOM_PARTS)
    assert_present(texts, RANDOM_CONTROLS)
    assert TOKEN in (folder / "capture.jsonl").read_text(encoding="utf-8")
    shown = json.loads(texts["results.json"])["run"]["command"]
    assert "true data/<hidden>/out.json;" in shown
    assert "http://localhost:8000/v1/files/<hidden>/raw?part=<hidden>&n=3" in shown
