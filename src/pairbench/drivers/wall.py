# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``wall`` driver: the run time of the launch itself.

The case ``wall`` holds ``run_s``, the run time the side measured for the
launch: the container's own start-to-finish time for an image side, and the
interval around the process for a command or Python environment side. An
image side also gives the secondary case ``launch``, holding ``launch_s``,
the time on this machine from the start request to the exit.

Both values come from the launch's own clock, not from anything the workload
printed, so the driver names them in ``clock_cases``. The CPU time and the
other resource figures of a launch are the cases under ``res/``, which the
runner makes for every driver; this driver adds none of them.

The driver wraps no tool and reads no file. It has nothing to read for a file
side, which has no launch clock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pairbench.api import (
    API_VERSION,
    TIMING_LAUNCH_S,
    TIMING_RUN_S,
    DriverContext,
    Invocation,
    Sample,
)
from pairbench.errors import Refusal
from pairbench.model import CASE_LAUNCH, CASE_WALL, KIND_IMAGE

UNIT: str = "s"


class WallDriver:
    """Reads the launch's own run time: the case ``wall``, and ``launch`` for an image side."""

    name: str = "wall"
    api_version: int = API_VERSION
    where: Literal["in_side", "client"] = "in_side"
    clock_cases: tuple[str, ...] = (CASE_WALL, CASE_LAUNCH)

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return the command unchanged; an empty one runs an image's default command."""
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return ``wall``, and ``launch`` for an image side, from the launch's timing."""
        if ctx.result_file is not None:
            raise Refusal(
                "E_USAGE",
                f"the wall driver reads the run time of a launch, and the result file "
                f"{ctx.result_file.name} of a file side has none: name the format of the "
                "files with --driver",
            )
        samples = [self._sample(ctx, CASE_WALL, TIMING_RUN_S)]
        if ctx.side.kind == KIND_IMAGE:
            samples.append(self._sample(ctx, CASE_LAUNCH, TIMING_LAUNCH_S))
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return ``wall``: the launch's run time counts toward the verdict."""
        return [CASE_WALL]

    @staticmethod
    def _sample(ctx: DriverContext, case: str, key: str) -> Sample:
        if key not in ctx.timing:
            raise Refusal(
                "E_LAUNCH_FAILED",
                f"side {ctx.name!r}: the launch reported no {key}, which the case {case} needs",
            )
        return Sample(
            case=case,
            metric=case,
            unit=UNIT,
            better="lower",
            kind="time",
            value=ctx.timing[key],
        )
