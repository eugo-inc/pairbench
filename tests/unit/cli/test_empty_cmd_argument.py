# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An empty argument in a ``cmd`` side is refused by its place in the list.

The refusal names the side and the place of the empty argument, counted from 1 for the
program, and prints none of the other arguments. A side whose command is no list keeps its
own refusal.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import KIND_CMD, Side
from pairbench.sides.command import declared_argv

from .conftest import refusal_text

Cli = Callable[..., Any]

EMPTY_SECOND = (
    "E_USAGE: side 'a': argument 2 of the command is empty; "
    "a cmd side is a list of non-empty arguments"
)
EMPTY_FOURTH = (
    "E_USAGE: side 'a': argument 4 of the command is empty; "
    "a cmd side is a list of non-empty arguments"
)
NO_LIST = "E_USAGE: side 'a': a cmd side is a non-empty list of arguments"


def plan_of(cli: Cli, tmp_path: Path, first: str) -> Any:
    config_file = tmp_path / "bench.toml"
    config_file.write_text(
        f'[sides.a]\ncmd = {first}\n[sides.b]\ncmd = ["true", "x"]\n', encoding="utf-8"
    )
    return cli("plan", "--config", str(config_file))


def test_an_empty_argument_in_a_config_cmd_list_is_named_by_its_place(
    cli: Cli, tmp_path: Path
) -> None:
    second = plan_of(cli, tmp_path, '["true", ""]')
    fourth = plan_of(cli, tmp_path, '["./bench", "--token", "made_up_value", ""]')

    assert (second.code, second.out, second.err) == (EXIT_USAGE, "", refusal_text(EMPTY_SECOND))
    assert (fourth.code, fourth.out, fourth.err) == (EXIT_USAGE, "", refusal_text(EMPTY_FOURTH))
    assert "made_up_value" not in fourth.err


def test_an_empty_argument_in_a_side_flag_is_named_by_its_place(cli: Cli) -> None:
    result = cli("plan", "--side", "a=cmd:true ''", "--side", "b=cmd:true x")

    assert (result.code, result.out, result.err) == (EXIT_USAGE, "", refusal_text(EMPTY_SECOND))


def test_a_command_that_is_no_list_keeps_its_own_refusal() -> None:
    for spec in ({"argv": "true"}, {"argv": ()}, {"argv": ("true", 3)}, {}):
        side = Side(name="a", kind=KIND_CMD, spec=spec)
        try:
            declared_argv(side)
        except Refusal as refusal:
            assert (refusal.code, refusal.message) == ("E_USAGE", NO_LIST.removeprefix("E_USAGE: "))
        else:
            raise AssertionError(f"{spec!r} was not refused")
