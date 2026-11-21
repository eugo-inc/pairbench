# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A change in what the identify command prints tells two builds apart.

A side's fingerprint is taken over the output of ``launch.identify``, with the
credentials it holds hidden and every other value kept: a checksum, a build
id, a measure such as ``KEY_SIZE`` and a package version stay in the hash, and so does a
version given to a name that reads like a credential (``DB_PASSWORD: 1.2.3``). So
two captures of one command whose identified file changed between them do not
pool (``E_POOL_SIDE_DRIFT``), and two sides told apart only by what their
identify prints are two sides.
"""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import load_capture
from pairbench.errors import EXIT_ANALYSIS, EXIT_OK

from .conftest import COMMAND_NOTE, refusal_text

Cli = Callable[..., Any]

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
# What identify prints before the change: one line of each form, all made up.
PRINTED = {
    "sha256sum": "0123456789abcdef" * 4 + "  model.bin",
    "md5sum": "0123456789abcdef" * 2 + "  weights.bin",
    "build-id": "    Build ID: 00112233445566778899aabbccddeeff",
    "key-size": "KEY_SIZE=128",
    "keyring": "keyring==24.3.0",
    "version-named-like-a-password": "DB_PASSWORD: 1.2.3",
}
# The same line after the change.
CHANGED = {
    "sha256sum": "fedcba9876543210" * 4 + "  model.bin",
    "md5sum": "fedcba9876543210" * 2 + "  weights.bin",
    "build-id": "    Build ID: ffeeddccbbaa99887766554433221100",
    "key-size": "KEY_SIZE=256",
    "keyring": "keyring==25.1.0",
    "version-named-like-a-password": "DB_PASSWORD: 1.2.4",
}
# Two credentials identify prints, each a value of the same made-up name.
TOKENS = ("MADE_UP_TOKEN=made-up-token-one", "MADE_UP_TOKEN=made-up-token-two")
DRIFT = "E_POOL_SIDE_DRIFT: the fingerprint of a, b differs between the captures {} and {}"
SAME_SIDE = "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint"


def _main(*args: object) -> tuple[int, str]:
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, err.getvalue()


def _run(folder: Path, printed: dict[str, str]) -> Path:
    """A real run of two command sides whose identify prints ``printed``, one form a line."""
    folder.mkdir(parents=True)
    shown = folder / "identify.txt"
    shown.write_text("".join(line + "\n" for line in printed.values()), encoding="utf-8")
    code, err = _main(
        "run",
        "--side",
        "a=cmd:true",
        "--side",
        "b=cmd:env true",
        "--baseline",
        "b",
        *QUICK,
        "--set",
        f"launch.identify={json.dumps(['cat', str(shown)])}",
        "--out",
        folder / "run",
    )
    assert code == EXIT_OK, err
    return folder / "run"


@pytest.fixture(scope="module")
def before(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _run(tmp_path_factory.mktemp("before") / "made", PRINTED)


def _shown(folder: Path) -> dict[str, tuple[str, str]]:
    results = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return {
        side["name"]: (side["identity"]["identify_sha256"], side["fingerprint"])
        for side in results["sides"]
    }


def _capture_id(folder: Path) -> str:
    return load_capture(folder / "capture.jsonl")[0].capture_id


@pytest.mark.parametrize("form", sorted(PRINTED))
def test_captures_whose_identify_printed_another_build_do_not_pool(
    cli: Cli, before: Path, tmp_path: Path, form: str
) -> None:
    after = _run(tmp_path / "made", {**PRINTED, form: CHANGED[form]})

    result = cli(
        "compare", before / "capture.jsonl", after / "capture.jsonl", "--out", tmp_path / "pooled"
    )

    first, second = _shown(before), _shown(after)
    for name in ("a", "b"):
        assert first[name][0] != second[name][0]
        assert first[name][1] != second[name][1]
    assert result.code == EXIT_ANALYSIS
    assert result.err == COMMAND_NOTE + refusal_text(
        DRIFT.format(_capture_id(before), _capture_id(after))
    )


def test_captures_whose_identify_printed_the_same_build_pool(
    cli: Cli, before: Path, tmp_path: Path
) -> None:
    later = _run(tmp_path / "made", PRINTED)

    result = cli(
        "compare", before / "capture.jsonl", later / "capture.jsonl", "--out", tmp_path / "pooled"
    )

    assert _shown(before) == _shown(later)
    assert result.code == EXIT_OK, result.err
    assert "E_POOL_SIDE_DRIFT" not in result.err


def test_captures_whose_identify_printed_another_credential_pool(cli: Cli, tmp_path: Path) -> None:
    one, two = (
        _run(tmp_path / name, {**PRINTED, "token": token})
        for name, token in zip(("one", "two"), TOKENS, strict=True)
    )

    result = cli(
        "compare", one / "capture.jsonl", two / "capture.jsonl", "--out", tmp_path / "pooled"
    )

    recorded = [
        {side.name: side.identity["identify_output"] for side in load_capture(f)[0].sides}
        for f in (one / "capture.jsonl", two / "capture.jsonl")
    ]
    assert recorded[0]["a"] != recorded[1]["a"]
    assert _shown(one) == _shown(two)
    assert result.code == EXIT_OK, result.err
    assert "E_POOL_SIDE_DRIFT" not in result.err


def test_two_sides_told_apart_only_by_the_checksum_their_identify_prints_are_two_sides(
    cli: Cli, tmp_path: Path
) -> None:
    files = {}
    for name, line in (("a", PRINTED["sha256sum"]), ("b", CHANGED["sha256sum"])):
        files[name] = tmp_path / f"{name}.txt"
        files[name].write_text(line + "\n", encoding="utf-8")

    result = cli(
        "run",
        "--side",
        "a=cmd:true",
        "--side",
        "b=cmd:true",
        *QUICK,
        "--set",
        f"sides.a.launch.identify={json.dumps(['cat', str(files['a'])])}",
        "--set",
        f"sides.b.launch.identify={json.dumps(['cat', str(files['b'])])}",
        "--out",
        tmp_path / "run",
    )

    assert SAME_SIDE not in result.err
    assert result.code == EXIT_OK, result.err
    shown = _shown(tmp_path / "run")
    assert shown["a"][0] != shown["b"][0]
    assert shown["a"][1] != shown["b"][1]
