# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides that differ in more than a credential's value are two sides.

An ordinary setting whose name says key or token (``--max-num-queued-tokens``,
``--key-size``) is shown and hashed as typed, so two sides that differ in it
have two fingerprints. A value hidden only because it looks random, or the
words after the first space of a credential's value hidden to the end of its
argument, give two sides one fingerprint; ``plan`` and ``run`` compare their
raw specs, and when those differ the sides are compared, with one note that
names both sides and never the value. Sides with equal raw specs, and sides
that differ only in a credential's value up to its first space, are still
refused with ``E_SAME_SIDE``. ``compare`` refuses to pool captures whose sides
differ in more than a credential's value with ``E_POOL_SIDE_DRIFT``, and the
message holds no part of the value.
"""

from __future__ import annotations

import json
import shlex
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

PYTHON = shlex.quote(sys.executable)
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
# Two made-up runs of 32 hexadecimal digits, which the shown command hides for their shape.
HEX_ONE = "3f9a1c7e5b2d4086a1c3e5f7092b4d6e"
HEX_TWO = "8e2b6d4f0a1c3e5b7d9f1a3c5e7b9d0f"
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)
SAME_SPEC = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' declare the same kind, spec and launch settings; give "
    "--allow-identical to compare a side with itself"
)
NOTE_CODE = "sides_differ_in_hidden_value"
# results.md escapes each underscore of the code.
NOTE_CODE_IN_MARKDOWN = "sides\\_differ\\_in\\_hidden\\_value"


def hidden_note(first: str, second: str) -> str:
    """The message of the note that two sides differ only in a value the results hide."""
    return (
        f"sides {first!r} and {second!r} have the same fingerprint and differ only in a value "
        "the results hide; they are compared as two sides, and the results do not show the "
        "value"
    )


def note_line(first: str, second: str) -> str:
    return f"pairbench: note: {NOTE_CODE}: {hidden_note(first, second)}\n"


def _pieces(*values: str) -> list[str]:
    """Each value and every stretch of eight of its characters, as no output may hold."""
    return [v[k : k + 8] for v in values for k in range(len(v) - 7)]


# Ordinary settings whose names say key or token, with two values each.
ORDINARY = {
    "queued-tokens": ("--max-num-queued-tokens 1024", "--max-num-queued-tokens 4096"),
    "scheduled-tokens-with-equals": (
        "--max-num-scheduled-tokens=512",
        "--max-num-scheduled-tokens=2048",
    ),
    "token-threshold": ("--dbo-decode-token-threshold 32", "--dbo-decode-token-threshold 64"),
    "pass-config": (
        """--compilation-config '{"pass_config": {"enable_noop": true}}'""",
        """--compilation-config '{"pass_config": {"enable_noop": false}}'""",
    ),
    "switch-before-the-model": (
        "--allow-credentials org/model-a",
        "--allow-credentials org/model-b",
    ),
    "key-size": ("--key-size 16", "--key-size 32"),
    "num-keys": ("--num-keys 100", "--num-keys 200"),
    "token-budget": ("--token-budget 256", "--token-budget 512"),
    "keys": ("--keys 10", "--keys 20"),
    "max-keys": ("--max-keys 10", "--max-keys 20"),
    "db-bench-key-size": ("--key_size=16", "--key_size=24"),
    "keys-per-prefix": ("--keys_per_prefix=4", "--keys_per_prefix=8"),
    "benchmark-filter": (
        "--benchmark_filter=BM_x/key_size:8",
        "--benchmark_filter=BM_x/key_size:16",
    ),
    "benchmark-context": ("--benchmark_context=key_size=8", "--benchmark_context=key_size=16"),
    "axis-key": ("-a Key=I32", "-a Key=I64"),
    "axis-num-keys": ("-a NumKeys=64", "-a NumKeys=128"),
    "goodput": (
        "--goodput inter_token_latency:10",
        "--goodput inter_token_latency:20",
    ),
    "rankings-tokens": (
        "--rankings-passages-prompt-token-mean 128",
        "--rankings-passages-prompt-token-mean 256",
    ),
}


@pytest.mark.parametrize(("one", "two"), list(ORDINARY.values()), ids=list(ORDINARY))
def test_plan_takes_sides_that_differ_in_an_ordinary_setting_as_two_sides(
    cli: Cli, one: str, two: str
) -> None:
    result = cli("plan", "--side", f"a=cmd:true {one}", "--side", f"b=cmd:true {two}")

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err
    assert NOTE_CODE not in result.err


@pytest.fixture
def clients(tmp_path: Path) -> Path:
    """A folder with made-up programs named as two clients whose password options are hidden."""
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in ("redis-benchmark", "memtier_benchmark"):
        program = folder / name
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
    return folder


CLIENT_SECRETS = {
    "redis-benchmark-a": ("redis-benchmark", "-a {}"),
    "memtier-authenticate": ("memtier_benchmark", "--authenticate {}"),
    "memtier-authenticate-with-equals": ("memtier_benchmark", "--authenticate={}"),
}


@pytest.mark.parametrize(
    ("program", "form"), list(CLIENT_SECRETS.values()), ids=list(CLIENT_SECRETS)
)
def test_plan_refuses_client_sides_that_differ_only_in_a_password(
    cli: Cli, clients: Path, program: str, form: str
) -> None:
    head = shlex.quote(str(clients / program))
    result = cli(
        "plan",
        "--side",
        f"a=cmd:{head} {form.format('kiwi7')}",
        "--side",
        f"b=cmd:{head} {form.format('plum4')}",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def test_plan_takes_memtier_sides_that_differ_in_a_key_setting_as_two_sides(
    cli: Cli, clients: Path
) -> None:
    head = shlex.quote(str(clients / "memtier_benchmark"))
    result = cli(
        "plan",
        "--side",
        f"a=cmd:{head} --key-maximum 1000 --key-prefix kiwi-",
        "--side",
        f"b=cmd:{head} --key-maximum 2000 --key-prefix kiwi-",
    )

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err


@pytest.mark.parametrize(
    ("one", "two"),
    [
        ("true --api-key kiwi7", "true --api-key plum4"),
        ("true --hf-token=kiwi7", "true --hf-token=plum4"),
    ],
    ids=["api-key", "hf-token"],
)
def test_plan_refuses_sides_that_differ_only_under_a_credential_name(
    cli: Cli, one: str, two: str
) -> None:
    result = cli("plan", "--side", f"a=cmd:{one}", "--side", f"b=cmd:{two}")

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def test_plan_refuses_sides_whose_raw_specs_are_equal(cli: Cli) -> None:
    result = cli(
        "plan", "--side", f"a=cmd:true --run {HEX_ONE}", "--side", f"b=cmd:true --run {HEX_ONE}"
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_SPEC


@pytest.mark.parametrize(
    ("one", "two"),
    [
        (f"true --run {HEX_ONE}", f"true --run {HEX_TWO}"),
        (f"true --api-key kiwi7 {HEX_ONE}", f"true --api-key plum4 {HEX_TWO}"),
        (f"true /made/up/{HEX_ONE}/model", f"true /made/up/{HEX_TWO}/model"),
        # The run hides its whole path, so the folders before it are hidden with it.
        (f"true /made/up/{HEX_ONE}/model", f"true /made/ab/{HEX_ONE}/model"),
    ],
    ids=["bare-run", "run-beside-a-secret", "run-in-a-path", "folder-of-a-path-with-a-run"],
)
def test_plan_takes_sides_that_differ_in_a_value_hidden_for_its_shape_with_one_note(
    cli: Cli, one: str, two: str
) -> None:
    result = cli("plan", "--side", f"a=cmd:{one}", "--side", f"b=cmd:{two}")

    assert result.code == EXIT_OK, result.err
    assert result.err.count(note_line("a", "b")) == 1
    for piece in _pieces(HEX_ONE, HEX_TWO, "kiwi7", "plum4"):
        assert piece not in result.err


def test_plan_takes_sides_that_differ_after_the_first_space_of_a_hidden_value_with_one_note(
    cli: Cli,
) -> None:
    result = cli(
        "plan",
        "--side",
        "a=cmd:true 'HF_TOKEN=kiwi7 ./made-up-bench-old'",
        "--side",
        "b=cmd:true 'HF_TOKEN=kiwi7 ./made-up-bench-new'",
    )

    assert result.code == EXIT_OK, result.err
    assert result.err.count(note_line("a", "b")) == 1
    for piece in ("kiwi7", "bench-old", "bench-new"):
        assert piece not in result.err


def test_plan_refuses_sides_that_differ_only_in_a_hidden_value_before_its_first_space(
    cli: Cli,
) -> None:
    result = cli(
        "plan",
        "--side",
        "a=cmd:true 'HF_TOKEN=kiwi7 ./made-up-bench'",
        "--side",
        "b=cmd:true 'HF_TOKEN=plum4 ./made-up-bench'",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def _run(cli: Cli, folder: Path, new: str, old: str) -> Any:
    return cli(
        "run",
        "--side",
        f"new=cmd:{PYTHON} -c pass {new}",
        "--side",
        f"old=cmd:{PYTHON} -c pass {old}",
        "--baseline",
        "old",
        *QUICK,
        "--out",
        folder,
    )


def test_run_compares_sides_that_differ_in_a_value_hidden_for_its_shape(
    cli: Cli, tmp_path: Path
) -> None:
    folder = tmp_path / "run"
    result = _run(cli, folder, HEX_ONE, HEX_TWO)

    assert result.code == EXIT_OK, result.err
    assert result.err.count(note_line("new", "old")) == 1
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    notes = [n for n in results["notes"] if n["code"] == NOTE_CODE]
    assert notes == [{"code": NOTE_CODE, "message": hidden_note("new", "old")}]
    markdown = (folder / "results.md").read_text(encoding="utf-8")
    one_line = " ".join(markdown.split())
    assert one_line.count(f"Note {NOTE_CODE_IN_MARKDOWN}: {hidden_note('new', 'old')}") == 1
    shared = [result.out, result.err, (folder / "results.json").read_text(encoding="utf-8")]
    shared.append(markdown)
    page = folder / "report.html"
    if page.exists():
        shared.append(page.read_text(encoding="utf-8"))
    for text in shared:
        for piece in _pieces(HEX_ONE, HEX_TWO):
            assert piece not in text


def test_run_takes_sides_that_differ_in_an_ordinary_setting_as_two_sides(
    cli: Cli, tmp_path: Path
) -> None:
    result = _run(
        cli, tmp_path / "run", "--max-num-queued-tokens 1024", "--max-num-queued-tokens 4096"
    )

    assert result.code == EXIT_OK, result.err
    assert NOTE_CODE not in result.err


def _refusal_line(err: str) -> str:
    """The one line of standard error that gives the refusal's text code."""
    (line,) = [line for line in err.splitlines() if line.startswith("E_")]
    return line


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _compare(cli: Cli, tmp_path: Path, first: str, second: str) -> Any:
    for name, value in (("one", first), ("two", second)):
        done = _run(cli, tmp_path / name, value, "--old")
        assert done.code == EXIT_OK, done.err
    return cli(
        "compare",
        tmp_path / "one" / "capture.jsonl",
        tmp_path / "two" / "capture.jsonl",
        "--out",
        tmp_path / "pooled",
    )


def test_compare_refuses_captures_whose_side_differs_in_a_value_hidden_for_its_shape(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, HEX_ONE, HEX_TWO)

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    pooled = tmp_path / "pooled" / "results.json"
    shared = [result.out, result.err]
    if pooled.exists():
        shared.append(pooled.read_text(encoding="utf-8"))
    for text in shared:
        for piece in _pieces(HEX_ONE, HEX_TWO):
            assert piece not in text


def test_compare_refuses_captures_whose_side_differs_in_the_folder_of_a_hidden_path(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, f"/made/up/{HEX_ONE}/model", f"/made/ab/{HEX_ONE}/model")

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    for piece in _pieces(HEX_ONE):
        assert piece not in result.err


def test_compare_refuses_captures_whose_side_differs_after_the_first_space_of_a_hidden_value(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(
        cli,
        tmp_path,
        "'HF_TOKEN=kiwi7 ./made-up-bench-old'",
        "'HF_TOKEN=kiwi7 ./made-up-bench-new'",
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    pooled = tmp_path / "pooled" / "results.json"
    shared = [result.out, result.err]
    if pooled.exists():
        shared.append(pooled.read_text(encoding="utf-8"))
    for text in shared:
        for piece in ("kiwi7", "bench-old", "bench-new"):
            assert piece not in text


def test_compare_pools_captures_whose_side_differs_only_in_a_hidden_value_before_its_space(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(
        cli, tmp_path, "'HF_TOKEN=kiwi7 ./made-up-bench'", "'HF_TOKEN=plum4 ./made-up-bench'"
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True


def test_compare_refuses_captures_whose_side_differs_in_an_ordinary_setting(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, "--max-num-queued-tokens 1024", "--max-num-queued-tokens 4096")

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err).startswith("E_POOL_SIDE_DRIFT: the fingerprint of new")


def test_compare_pools_captures_whose_side_differs_only_under_a_credential_name(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, "--api-key kiwi7", "--api-key plum4")

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True


def _identified_runs(cli: Cli, tmp_path: Path, first: str, second: str) -> Any:
    """Two runs whose identify command prints ``first`` and then ``second``; then compare."""
    printed = tmp_path / "made-up-weights.sum"
    identify = json.dumps(["cat", str(printed)])
    for name, text in (("one", first), ("two", second)):
        printed.write_text(text, encoding="utf-8")
        done = cli(
            "run",
            "--side",
            f"new=cmd:{PYTHON} -c pass",
            "--side",
            f"old=cmd:{PYTHON} -c pass --old",
            "--baseline",
            "old",
            "--set",
            f"launch.identify={identify}",
            *QUICK,
            "--out",
            tmp_path / name,
        )
        assert done.code == EXIT_OK, done.err
    return cli(
        "compare",
        tmp_path / "one" / "capture.jsonl",
        tmp_path / "two" / "capture.jsonl",
        "--out",
        tmp_path / "pooled",
    )


def test_compare_refuses_captures_whose_identify_output_differs_in_a_checksum(
    cli: Cli, tmp_path: Path
) -> None:
    result = _identified_runs(
        cli, tmp_path, f"{HEX_ONE}  made-up-weights.bin\n", f"{HEX_TWO}  made-up-weights.bin\n"
    )

    # The output is hashed with only its credentials hidden, so a checksum is in the fingerprint.
    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the fingerprint of new, old differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')}"
    )
    for text in (result.out, result.err):
        for piece in _pieces(HEX_ONE, HEX_TWO):
            assert piece not in text


def test_compare_pools_captures_whose_identify_output_differs_only_in_a_credential(
    cli: Cli, tmp_path: Path
) -> None:
    result = _identified_runs(
        cli,
        tmp_path,
        "made-up-tool 1.0\nMADE_UP_TOKEN=kiwi7\n",
        "made-up-tool 1.0\nMADE_UP_TOKEN=plum4\n",
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True
    for piece in ("kiwi7", "plum4"):
        assert piece not in result.err
