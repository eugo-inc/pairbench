# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Two sides that run two programs over ``ssh`` behind a wrapper are two sides.

After ``taskset``, ``numactl``, ``chrt``, ``stdbuf``, ``ionice``, ``nice``, ``nohup``,
``timeout`` or ``sudo`` the remote command of ``ssh`` keeps its program, so ``plan`` takes two
sides whose remote commands run two programs as two sides, and refuses two sides that differ
only in a credential there with ``E_SAME_SIDE``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pairbench.errors import EXIT_OK, EXIT_SIDE

from .conftest import refusal_text

Cli = Callable[..., Any]

SAME_FINGERPRINT = refusal_text(
    "E_SAME_SIDE: sides 'a' and 'b' have the same fingerprint; give --allow-identical to "
    "compare a side with itself"
)

# The wrapper words before ``ssh`` in each side's shell text.
WRAPPERS = {
    "taskset": "taskset -c 0-3",
    "numactl": "numactl -N 0",
    "chrt": "chrt -f 10",
    "stdbuf": "stdbuf -oL",
    "ionice": "ionice -c 2 -n 7",
    "nice": "nice",
    "nice with an adjustment": "nice -n 5",
    "nohup": "nohup",
    "timeout": "timeout 30",
    "timeout with a signal": "timeout -s KILL 30",
    "sudo": "sudo -u app",
}


def _side(wrapper: str, key: str, program: str) -> str:
    return f"""cmd:sh -c "{wrapper} ssh made-up-host 'API_KEY={key} ./made-up-bench-{program}'\""""


@pytest.mark.parametrize("wrapper", list(WRAPPERS.values()), ids=list(WRAPPERS))
def test_plan_takes_two_programs_behind_a_wrapper_as_two_sides(cli: Cli, wrapper: str) -> None:
    result = cli(
        "plan",
        "--side",
        f"a={_side(wrapper, 'kiwi7', 'old')}",
        "--side",
        f"b={_side(wrapper, 'kiwi7', 'new')}",
    )

    assert result.code == EXIT_OK, result.err
    assert "E_SAME_SIDE" not in result.err


@pytest.mark.parametrize("wrapper", list(WRAPPERS.values()), ids=list(WRAPPERS))
def test_plan_refuses_two_credentials_behind_a_wrapper_as_one_side(cli: Cli, wrapper: str) -> None:
    result = cli(
        "plan",
        "--side",
        f"a={_side(wrapper, 'kiwi7', 'old')}",
        "--side",
        f"b={_side(wrapper, 'plum4', 'old')}",
    )

    assert result.code == EXIT_SIDE
    assert result.err == SAME_FINGERPRINT
    assert "kiwi7" not in result.out + result.err
    assert "plum4" not in result.out + result.err
