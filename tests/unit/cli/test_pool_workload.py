# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench compare`` refuses to pool two runs whose shared workloads differ.

The sides are Python environment sides, whose fingerprints do not hold the
workload, and command sides that put the workload in their command. A
difference in an ordinary argument is refused with ``E_POOL_SIDE_DRIFT`` and
exit code 6, and the message names the first argument that differs by the
text the results show of it. A difference only in a credential pools, a
difference only in a value hidden for its shape is refused as a hidden setup
difference, and a label or a case selection is no part of the workload.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, EXIT_OK

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
CODE = "E_POOL_SIDE_DRIFT"
# Made-up credential values and two made-up runs of 32 hexadecimal digits.
KIWI, PLUM = "kiwi7", "plum4"
HEX_ONE = "3f9a1c7e5b2d4086a1c3e5f7092b4d6e"
HEX_TWO = "8e2b6d4f0a1c3e5b7d9f1a3c5e7b9d0f"
HIDDEN = (KIWI, PLUM, HEX_ONE, HEX_TWO)

# (row id, first workload, second workload, where the message says they differ).
REFUSED: Sequence[tuple[str, list[str], list[str], str]] = (
    (
        "ordinary-value",
        ["-c", "pass", "--size", "10"],
        ["-c", "pass", "--size", "20"],
        "4: 10 against 20",
    ),
    (
        "added-argument",
        ["-c", "pass", "--size", "10"],
        ["-c", "pass", "--size", "10", "--fast"],
        "5: no argument against --fast",
    ),
    (
        "removed-argument",
        ["-c", "pass", "--size", "10", "--fast"],
        ["-c", "pass", "--size", "10"],
        "5: --fast against no argument",
    ),
    (
        "reordered-arguments",
        ["-c", "pass", "--size", "10", "--fast"],
        ["-c", "pass", "--fast", "--size", "10"],
        "3: --size against --fast",
    ),
    (
        "value-glued-to-its-option",
        ["-c", "pass", "--size=10"],
        ["-c", "pass", "--size=20"],
        "3: --size=10 against --size=20",
    ),
    (
        "credential-beside-an-ordinary-value",
        ["-c", "pass", "--api-key", KIWI, "--size", "10"],
        ["-c", "pass", "--api-key", PLUM, "--size", "20"],
        "6: 10 against 20",
    ),
)

# (row id, first workload, second workload): runs that pool.
POOLED: Sequence[tuple[str, list[str], list[str]]] = (
    ("identical", ["-c", "pass", "--size", "10"], ["-c", "pass", "--size", "10"]),
    ("credential-only", ["-c", "pass", "--api-key", KIWI], ["-c", "pass", "--api-key", PLUM]),
)


@pytest.fixture
def pythons(tmp_path: Path) -> tuple[Path, Path]:
    """Two made-up interpreters, each a script that runs this test's own Python."""
    made: list[Path] = []
    for name in ("python-new", "python-old"):
        path = tmp_path / name
        path.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
        path.chmod(0o755)
        made.append(path)
    return made[0], made[1]


def _run(cli: Cli, folder: Path, sides: Sequence[str], workload: Sequence[str], *more: str) -> str:
    """Run once, check that the run worked, and return the id of its capture."""
    side_flags = [word for spec in sides for word in ("--side", spec)]
    done = cli(
        "run",
        *side_flags,
        "--baseline",
        "old",
        "--allow-identical",
        *QUICK,
        *more,
        "--out",
        folder,
        "--",
        *workload,
    )
    assert done.code == EXIT_OK, done.err
    header = json.loads((folder / "capture.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return str(header["capture_id"])


def _python_sides(pythons: tuple[Path, Path]) -> list[str]:
    return [f"new=python:{pythons[0]}", f"old=python:{pythons[1]}"]


def _compare(cli: Cli, tmp_path: Path) -> Any:
    return cli(
        "compare",
        tmp_path / "one" / "capture.jsonl",
        tmp_path / "two" / "capture.jsonl",
        "--out",
        tmp_path / "pooled",
    )


def _pool(
    cli: Cli,
    tmp_path: Path,
    sides: Sequence[str],
    workloads: tuple[Sequence[str], Sequence[str]],
    more: tuple[Sequence[str], Sequence[str]] = ((), ()),
) -> tuple[Any, list[str]]:
    ids = [
        _run(cli, tmp_path / name, sides, workload, *extra)
        for name, workload, extra in zip(("one", "two"), workloads, more, strict=True)
    ]
    return _compare(cli, tmp_path), ids


def _refusal_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("E_")]


def _pooled(tmp_path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (tmp_path / "pooled" / "results.json").read_text(encoding="utf-8")
    )
    return loaded


def _assert_refused(result: Any, tmp_path: Path, message: str) -> None:
    assert result.code == EXIT_ANALYSIS
    assert _refusal_lines(result.err) == [f"{CODE}: {message}"]
    assert CODE not in result.out
    assert [(r["code"], r["message"]) for r in _pooled(tmp_path)["refusals"]] == [(CODE, message)]


@pytest.mark.parametrize(
    ("one", "two", "where"), [row[1:] for row in REFUSED], ids=[row[0] for row in REFUSED]
)
def test_compare_refuses_runs_whose_workloads_differ(
    cli: Cli,
    tmp_path: Path,
    pythons: tuple[Path, Path],
    one: list[str],
    two: list[str],
    where: str,
) -> None:
    result, ids = _pool(cli, tmp_path, _python_sides(pythons), (one, two))

    message = (
        f"the workload differs between the captures {ids[0]} and {ids[1]} at its argument {where}"
    )
    _assert_refused(result, tmp_path, message)
    for value in HIDDEN:
        assert value not in result.out + result.err
        assert value not in (tmp_path / "pooled" / "results.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("one", "two"), [row[1:] for row in POOLED], ids=[row[0] for row in POOLED]
)
def test_compare_pools_runs_whose_workloads_are_alike_but_for_a_credential(
    cli: Cli, tmp_path: Path, pythons: tuple[Path, Path], one: list[str], two: list[str]
) -> None:
    result, ids = _pool(cli, tmp_path, _python_sides(pythons), (one, two))

    assert result.code == EXIT_OK, result.err
    assert _refusal_lines(result.err) == []
    pooled = _pooled(tmp_path)
    assert pooled["run"]["pooled"] is True
    assert [c["capture_id"] for c in pooled["run"]["captures"]] == ids
    for value in HIDDEN:
        assert value not in result.out + result.err


def test_compare_refuses_runs_whose_workloads_differ_in_a_value_hidden_for_its_shape(
    cli: Cli, tmp_path: Path, pythons: tuple[Path, Path]
) -> None:
    result, ids = _pool(
        cli,
        tmp_path,
        _python_sides(pythons),
        (["-c", "pass", "--seed-file", HEX_ONE], ["-c", "pass", "--seed-file", HEX_TWO]),
    )

    message = (
        f"the setup of new, old differs between the captures {ids[0]} and {ids[1]} in a value "
        "the results hide"
    )
    _assert_refused(result, tmp_path, message)


@pytest.mark.parametrize(
    "more",
    [
        (("--set", "run.node_type=made-up-class-a"), ("--set", "run.node_type=made-up-class-b")),
        (("--case", "wall*"), ()),
    ],
    ids=["machine-label", "case-selection"],
)
def test_compare_pools_runs_that_differ_in_what_is_no_part_of_the_workload(
    cli: Cli,
    tmp_path: Path,
    pythons: tuple[Path, Path],
    more: tuple[Sequence[str], Sequence[str]],
) -> None:
    workload = ["-c", "pass", "--size", "10"]
    result, _ids = _pool(cli, tmp_path, _python_sides(pythons), (workload, workload), more)

    assert result.code == EXIT_OK, result.err
    assert _pooled(tmp_path)["run"]["pooled"] is True


def test_compare_names_the_argument_for_command_sides_that_run_the_workload(
    cli: Cli, tmp_path: Path
) -> None:
    python = shlex.quote(sys.executable)
    sides = [f"new=cmd:{python} {{workload}}", f"old=cmd:{python} -I {{workload}}"]
    result, ids = _pool(
        cli, tmp_path, sides, (["-c", "pass", "--size", "10"], ["-c", "pass", "--size", "20"])
    )

    message = (
        f"the workload differs between the captures {ids[0]} and {ids[1]} at its argument 4: "
        "10 against 20"
    )
    _assert_refused(result, tmp_path, message)


def test_compare_names_a_shell_text_that_differs_by_its_shown_text(
    cli: Cli, tmp_path: Path
) -> None:
    sides = ["new=cmd:env {workload}", "old=cmd:env -u MADE_UP_UNSET {workload}"]
    result, ids = _pool(
        cli,
        tmp_path,
        sides,
        (
            ["sh", "-c", f"true --token {KIWI} --size 10"],
            ["sh", "-c", f"true --token {KIWI} --size 20"],
        ),
    )

    message = (
        f"the workload differs between the captures {ids[0]} and {ids[1]} at its argument 3: "
        "'true --token <hidden> --size 10' against 'true --token <hidden> --size 20'"
    )
    _assert_refused(result, tmp_path, message)
    assert KIWI not in result.out + result.err


@pytest.fixture
def client(tmp_path: Path) -> Path:
    """A made-up ``redis-benchmark`` that does nothing, in a folder of its own."""
    folder = tmp_path / "bin"
    folder.mkdir()
    path = folder / "redis-benchmark"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_compare_hides_a_password_the_side_s_client_reads_when_it_names_the_argument(
    cli: Cli, tmp_path: Path, client: Path
) -> None:
    program = shlex.quote(str(client))
    sides = [f"new=cmd:{program} {{workload}}", f"old=cmd:{program} -q {{workload}}"]
    result, ids = _pool(cli, tmp_path, sides, (["-a", KIWI, "-n", "8"], ["-a", KIWI, "-n", "9"]))

    message = (
        f"the workload differs between the captures {ids[0]} and {ids[1]} at its argument 4: "
        "8 against 9"
    )
    _assert_refused(result, tmp_path, message)
    assert KIWI not in result.out + result.err


def test_compare_pools_runs_whose_client_password_alone_differs(
    cli: Cli, tmp_path: Path, client: Path
) -> None:
    program = shlex.quote(str(client))
    sides = [f"new=cmd:{program} {{workload}}", f"old=cmd:{program} -q {{workload}}"]
    result, _ids = _pool(cli, tmp_path, sides, (["-a", KIWI, "-n", "8"], ["-a", PLUM, "-n", "8"]))

    assert result.code == EXIT_OK, result.err
    assert _pooled(tmp_path)["run"]["pooled"] is True
    for value in (KIWI, PLUM):
        assert value not in result.out + result.err
