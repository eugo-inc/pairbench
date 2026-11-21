# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What of the shared launch table keeps two captures from pooling.

The shared ``launch`` table is part of each side's setup. A value in it that
the shared files hide for its shape, as a run of hexadecimal digits in a
path, keeps two captures apart though their fingerprints are equal. A value
the shared files show is left to the fingerprint: a difference in it is no
difference in a hidden value.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK

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
# A run of 64 hexadecimal digits, made up, that a path hides with the rest of the path.
HEX = "0123456789abcdef" * 4


def _run(cli: Cli, folder: Path, setting: str) -> Any:
    return cli(
        "run",
        "--side",
        f"new=cmd:{PYTHON} -c pass",
        "--side",
        f"old=cmd:{PYTHON} -c pass --old",
        "--baseline",
        "old",
        *QUICK,
        "--set",
        setting,
        "--out",
        folder,
    )


def _compare(cli: Cli, tmp_path: Path, first: str, second: str) -> Any:
    for name, setting in (("one", first), ("two", second)):
        done = _run(cli, tmp_path / name, setting)
        assert done.code == EXIT_OK, done.err
    return cli(
        "compare",
        tmp_path / "one" / "capture.jsonl",
        tmp_path / "two" / "capture.jsonl",
        "--out",
        tmp_path / "pooled",
    )


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _refusal_line(err: str) -> str:
    (line,) = [line for line in err.splitlines() if line.startswith("E_")]
    return line


def test_compare_refuses_captures_whose_shared_launch_table_differs_in_a_hidden_part(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(
        cli,
        tmp_path,
        f"launch.env.MADE_UP_DIR=/made/up/{HEX}/alpha",
        f"launch.env.MADE_UP_DIR=/made/up/{HEX}/beta",
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the setup of new, old differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')} in a value the "
        "results hide"
    )
    for piece in (HEX, "alpha", "beta"):
        assert piece not in result.out
        assert piece not in result.err


def test_compare_pools_captures_whose_shared_launch_table_differs_in_a_shown_setting(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, "launch.timeout=30", "launch.timeout=60")

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True


def test_compare_names_the_fingerprint_for_a_shown_launch_variable(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(
        cli, tmp_path, "launch.env.MADE_UP_MODE=alpha", "launch.env.MADE_UP_MODE=beta"
    )

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the fingerprint of new, old differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')}"
    )
