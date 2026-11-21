# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Keep every energy test away from a real GPU tool and a real GPU library.

Each test gets a module of the GPU management library that cannot be found or
loaded, and a query process that cannot be started, unless it passes a fake of
its own. A test that reached the real path fails instead of running a tool.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from pairbench.energy import nvml, smi


class RealToolReached(AssertionError):
    """A test reached the real GPU library or the real query process."""


def _no_spawn(argv: Sequence[str]) -> Any:
    raise RealToolReached(f"a test tried to start {argv[0]!r}")


def _no_help(argv: Sequence[str]) -> str | None:
    raise RealToolReached(f"a test tried to run {argv[0]!r}")


def _no_library() -> Any:
    raise RealToolReached("a test tried to load the GPU management library")


@pytest.fixture(autouse=True)
def _no_real_gpu_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smi, "_spawn", _no_spawn)
    monkeypatch.setattr(smi, "_read_help", _no_help)
    monkeypatch.setattr(nvml, "load", _no_library)
    monkeypatch.setattr(nvml, "available", lambda: False)
