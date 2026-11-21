# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a real run's shared files show of base64, ``0x`` hex, benchmark names and settings.

Each test runs ``pairbench run`` on a workload that holds the made-up values,
base64 written with percent escapes in a query value among them, and reads
results.json, results.md and report.html: no piece of a hidden value
is in any of them, and what must stay shown is in each. The capture keeps the
command as typed.
"""

from __future__ import annotations

import html
import json
import shlex
from pathlib import Path
from typing import Any

import pytest

SHARED_FILES = ("results.json", "results.md", "report.html")

# Made-up base64 values with `/` and `+` or padding, and the pieces of them that must not show.
SLASH_NEAR_START = "EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kE+Aw=="
SLASH_NEAR_END = "QX7kP2mV9nL4rT8wY3zB6cD1fG5hJ0sK2eAx+EXAMPLE5aB/n3Mq8Rt4Wv7Yz1Cd=="
BASE64_PIECES = ("EXAMPLE7q", "Q7xK2mP9", "n3Mq8Rt4Wv7Yz1Cd", "QX7kP2mV9")
# Made-up hexadecimal after 0x, and a short value after 0x that stays shown.
HEX_AFTER_0X = "0x" + "3f9a" * 16
HEX_PIECES = ("3f9a3f9a3f9a3f9a",)
SHORT_HEX = "0xdeadbeef"
# Made-up benchmark names with number arguments, which stay shown.
BENCHMARK_NAMES = (
    "--benchmark_filter=BM_Crc32BatchNormMapTensorPut/4096/4",
    "--benchmark_filter=BM_Crc32BatchNormMapTensorPut/64",
    "--benchmark_filter=BM_Crc32BatchNormMapTensorPut/8/1",
)
# A made-up key given to a credential setting, and a setting that names no credential.
SETTING_KEY = "EXAMPLEk/zwE+8qv5a4ABGOFharkRfu1EbgRhq2x"
SHORT_SETTING_VALUE = "zqmsetting-made-up"
SETTING_PIECES = ("EXAMPLEk", "zwE+8qv5", "zqmsetting")
KEPT_SETTING = "config user.name made-up-name"
# A made-up base64 value written with percent escapes for `/`, `+` and `=`: each part between
# its `/` is under 32 characters, and the text the escapes stand for looks random whole.
PERCENT_VALUE = "Q7xK2mP9vL4nR8tW3y%2FZ6bC1dF5gH0jS2k%2BEXAMPLEAw%3D%3D"
# A short made-up value under a credential-like query name.
QUERY_TOKEN = "zqmquery-made-up"
PERCENT_PIECES = ("Q7xK2mP9", "Z6bC1dF5", "EXAMPLEAw", "zqmquery")
ADDRESS = "http://127.0.0.1:8080/v1/objects"


def shared_texts(folder: Path) -> dict[str, str]:
    """The three shared files of a run folder, as a reader sees them."""
    texts = {name: (folder / name).read_text(encoding="utf-8") for name in SHARED_FILES}
    texts["report.html"] = html.unescape(texts["report.html"])
    return texts


def run_shell(cli: Any, tmp_path: Path, script: str) -> Path:
    """Run ``pairbench run`` with two made-up command sides on ``sh -c script``."""
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
        "sh",
        "-c",
        script,
    )
    assert run.code == 0, run.err
    return tmp_path / "run"


def command(folder: Path) -> str:
    shown: str = json.loads((folder / "results.json").read_text(encoding="utf-8"))["run"]["command"]
    return shown


def assert_absent(texts: dict[str, str], pieces: tuple[str, ...]) -> None:
    for where, text in texts.items():
        assert [piece for piece in pieces if piece in text] == [], where


def assert_present(texts: dict[str, str], kept: tuple[str, ...]) -> None:
    for where, text in texts.items():
        assert [k for k in kept if k not in text] == [], where


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_run_shows_no_piece_of_a_base64_value(cli: Any, in_tmp: Path) -> None:
    script = (
        "; ".join(
            (
                shlex.join(("true", SLASH_NEAR_START)),
                shlex.join(("true", "--hmac", SLASH_NEAR_START)),
                shlex.join(("true", "--hmac=" + SLASH_NEAR_START)),
                shlex.join(("env", "BLOB=" + SLASH_NEAR_START, "true")),
                shlex.join(("true", SLASH_NEAR_END)),
            )
        )
        + " && echo ok"
    )
    folder = run_shell(cli, in_tmp, script)

    texts = shared_texts(folder)
    assert_absent(texts, BASE64_PIECES)
    assert_present(texts, ("true --hmac <hidden>", "--hmac=<hidden>", "BLOB=<hidden>"))
    assert command(folder).endswith("true <hidden> && echo ok'")
    assert SLASH_NEAR_START in (folder / "capture.jsonl").read_text(encoding="utf-8")


def test_a_run_shows_no_hexadecimal_after_0x(cli: Any, in_tmp: Path) -> None:
    script = shlex.join(("true", "--seed", HEX_AFTER_0X, "--mask", SHORT_HEX))
    folder = run_shell(cli, in_tmp, script)

    texts = shared_texts(folder)
    assert_absent(texts, HEX_PIECES)
    assert_present(texts, ("--seed <hidden>", f"--mask {SHORT_HEX}"))


def test_a_run_keeps_benchmark_names_with_number_arguments(cli: Any, in_tmp: Path) -> None:
    script = shlex.join(("true", *BENCHMARK_NAMES))
    folder = run_shell(cli, in_tmp, script)

    texts = shared_texts(folder)
    assert_present(texts, BENCHMARK_NAMES)
    assert "<hidden>" not in command(folder).split(" -- ", 1)[1]


def test_a_run_shows_no_piece_of_a_percent_encoded_base64_value(cli: Any, in_tmp: Path) -> None:
    script = "; ".join(
        (
            shlex.join(("true", f"{ADDRESS}?part={PERCENT_VALUE}")),
            shlex.join(("true", f"{ADDRESS}?token={QUERY_TOKEN}")),
        )
    )
    folder = run_shell(cli, in_tmp, script)

    texts = shared_texts(folder)
    assert_absent(texts, PERCENT_PIECES)
    assert_present(texts, (f"{ADDRESS}?part=<hidden>", f"{ADDRESS}?token=<hidden>"))
    assert PERCENT_VALUE in (folder / "capture.jsonl").read_text(encoding="utf-8")


def test_a_run_hides_the_value_of_a_credential_setting(cli: Any, in_tmp: Path) -> None:
    script = "; ".join(
        (
            shlex.join(("true", "configure", "set", "aws_secret_access_key", SETTING_KEY)),
            shlex.join(("true", "config", "--global", "github.token", SHORT_SETTING_VALUE)),
            shlex.join(("true", "config", "user.name", "made-up-name")),
        )
    )
    folder = run_shell(cli, in_tmp, script)

    texts = shared_texts(folder)
    assert_absent(texts, SETTING_PIECES)
    assert_present(
        texts,
        ("set aws_secret_access_key <hidden>", "github.token <hidden>", KEPT_SETTING),
    )
    assert SETTING_KEY in (folder / "capture.jsonl").read_text(encoding="utf-8")
