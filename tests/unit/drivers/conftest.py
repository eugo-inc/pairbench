# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Shared helpers of the driver tests: a made-up launch context and the fixture folder."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from pairbench.api import DriverContext
from pairbench.model import LaunchSettings, Side

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "drivers"

SPECS: dict[str, dict[str, Any]] = {
    "cmd": {"argv": ["made-up-tool"]},
    "image": {"image": "example.invalid/made-up:1", "args": [], "env": {}, "entrypoint": None},
    "python": {"interpreter": "python3"},
    "venv": {"venv": ".venv"},
    "conda": {"conda": "made-up-env"},
    "file": {"paths": ["result-*.json"], "format": None},
    "serve": {},
}


class Notes:
    """Collects the notes a driver writes through ``DriverContext.note``."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def __call__(self, code: str, message: str) -> None:
        self.seen.append((code, message))


@pytest.fixture
def notes() -> Notes:
    return Notes()


@pytest.fixture
def make_ctx(tmp_path: Path, notes: Notes) -> Callable[..., DriverContext]:
    """Return a function that makes the context of one launch of side ``new``."""

    def make(
        *,
        kind: str = "cmd",
        timing: Mapping[str, float] | None = None,
        result_file: Path | None = None,
        perf_counters: bool = False,
        artifacts_in_side: str = "/pairbench/artifacts",
    ) -> DriverContext:
        side = Side(name="new", kind=kind, spec=SPECS.get(kind, {}))
        return DriverContext(
            run_id="run-a",
            seq=3,
            phase="round",
            round=1,
            name="new",
            side=side,
            artifacts=tmp_path,
            artifacts_in_side=artifacts_in_side,
            timing=dict(timing or {}),
            rc=0,
            result_file=result_file,
            note=notes,
            launch=LaunchSettings(perf_counters=perf_counters),
        )

    return make
