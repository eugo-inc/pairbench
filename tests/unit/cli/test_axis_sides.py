# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides whose texts differ in the values of an axis are two sides.

After ``-a`` or ``--axis`` the axis ``Key`` keeps its values in the text after ``sh -c`` and
in the quoted text of an option, as it does in a plain argument, so ``plan`` takes two sides
that differ there as two sides and ``compare`` refuses to pool two captures whose side
differs there with ``E_POOL_SIDE_DRIFT``. Two sides that differ only in a credential after
the axis value in the same text are still one side to both.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

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
SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)

# Two specs of a side each, which differ only in the values of the axis ``Key``.
AXIS_SPECS = {
    "sh-c": (
        "cmd:sh -c './made-up-bench-old -a Key=I32'",
        "cmd:sh -c './made-up-bench-old -a Key=I64'",
    ),
    "bash-c-long-option": (
        "cmd:bash -c './made-up-bench --axis Key=I32'",
        "cmd:bash -c './made-up-bench --axis Key=I64'",
    ),
    "option-text": (
        "cmd:true --opts '-a Key=I32'",
        "cmd:true --opts '-a Key=I64'",
    ),
    "option-text-in-sh-c": (
        """cmd:sh -c "./made-up-bench --opts '-a Key=I32'\"""",
        """cmd:sh -c "./made-up-bench --opts '-a Key=I64'\"""",
    ),
}


@pytest.mark.parametrize(("one", "two"), list(AXIS_SPECS.values()), ids=list(AXIS_SPECS))
def test_plan_takes_sides_whose_texts_differ_in_an_axis_value_as_two_sides(
    cli: Cli, one: str, two: str
) -> None:
    result = cli("plan", "--side", f"a={one}", "--side", f"b={two}")

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err


def test_plan_refuses_sides_whose_texts_differ_only_in_a_credential_after_an_axis_value(
    cli: Cli,
) -> None:
    result = cli(
        "plan",
        "--side",
        "a=cmd:sh -c './made-up-bench -a Key=I32 --token kiwi7'",
        "--side",
        "b=cmd:sh -c './made-up-bench -a Key=I32 --token plum4'",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT


def _capture_id(folder: Path) -> str:
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _compare(cli: Cli, tmp_path: Path, first: str, second: str) -> Any:
    """Two runs whose side ``new`` runs ``first`` and then ``second`` in a shell; then compare."""
    for name, text in (("one", first), ("two", second)):
        done = cli(
            "run",
            "--side",
            f"new=cmd:sh -c '{text}'",
            "--side",
            "old=cmd:sh -c 'true --old'",
            "--baseline",
            "old",
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


def _refusal_line(err: str) -> str:
    """The one line of standard error that gives the refusal's text code."""
    (line,) = [line for line in err.splitlines() if line.startswith("E_")]
    return line


def test_compare_refuses_captures_whose_side_differs_in_an_axis_value_in_a_shell_text(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, "true -a Key=I32", "true -a Key=I64")

    assert result.code == EXIT_ANALYSIS
    assert _refusal_line(result.err) == (
        "E_POOL_SIDE_DRIFT: the fingerprint of new differs between the captures "
        f"{_capture_id(tmp_path / 'one')} and {_capture_id(tmp_path / 'two')}"
    )


def test_compare_pools_captures_whose_side_differs_only_in_a_credential_after_an_axis_value(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(
        cli, tmp_path, "true -a Key=I32 --token kiwi7", "true -a Key=I32 --token plum4"
    )

    assert result.code == EXIT_OK, result.err
    results = json.loads((tmp_path / "pooled" / "results.json").read_text(encoding="utf-8"))
    assert results["run"]["pooled"] is True
    for text in (result.out, result.err, json.dumps(results)):
        assert "kiwi7" not in text
        assert "plum4" not in text
