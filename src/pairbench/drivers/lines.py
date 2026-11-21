# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``lines`` driver: values the workload prints itself.

The workload prints one line per case on standard output::

    ::pairbench:: {"case": "name", "value": 1.23, "unit": "s", "better": "lower"}

The line starts with ``::pairbench::``; the rest is one JSON object. ``case``
and ``value`` are required. ``unit`` defaults to ``s`` and ``better`` to
``lower``; ``better`` may also be ``higher``, or ``none`` for a case that
describes and does not judge. Every other line of the output is ignored. A
byte order mark at the start of the output is no part of the first line.

Refused as output that cannot be read (``E_LAUNCH_FAILED``): no such line at
all, a line whose JSON does not parse, is nested too deeply or holds a number
with more digits than Python converts, or is no object, a key other than the
four above (a misspelt ``better`` would turn a verdict round), a case named
twice in one launch, a value that is no finite number.

A case's metric is ``value`` and its kind is ``time`` when its unit is a unit
of time, as for the rows of the text input format.

The driver adds nothing to the command. For a file side it reads the file it
is given as the standard output of one launch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Literal

from pairbench.api import API_VERSION, ARTIFACT_STDOUT, DriverContext, Invocation, Sample
from pairbench.drivers.base import launch_failed, number, read_text, result_path, unique
from pairbench.model import BETTER, kind_of_unit, public_case

PREFIX: Final = "::pairbench::"
KEYS: Final[tuple[str, ...]] = ("case", "value", "unit", "better")
DEFAULT_UNIT: Final = "s"
DEFAULT_BETTER: Final = "lower"
METRIC: Final = "value"
BYTE_ORDER_MARK: Final = "﻿"


class LinesDriver:
    """Reads the ``::pairbench::`` lines a workload prints on standard output."""

    name: str = "lines"
    api_version: int = API_VERSION
    where: Literal["in_side", "client"] = "in_side"

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return the command unchanged: the workload prints its own lines."""
        return Invocation.single(argv)

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return one sample per ``::pairbench::`` line of the launch's standard output."""
        path = result_path(ctx, artifacts, ARTIFACT_STDOUT)
        samples = []
        output = read_text(path, self.name).removeprefix(BYTE_ORDER_MARK)
        for line_no, line in enumerate(output.splitlines(), start=1):
            if line.startswith(PREFIX):
                samples.append(_sample(line[len(PREFIX) :], f"{path.name} line {line_no}"))
        if not samples:
            raise launch_failed(f"{path.name} holds no line that starts with {PREFIX}")
        return unique(samples, path.name)

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return every printed case."""
        return [sample.case for sample in samples]


def _sample(payload: str, where: str) -> Sample:
    try:
        obj: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise launch_failed(f"{where}: the JSON does not parse: {exc.msg}") from None
    except ValueError:
        raise launch_failed(
            f"{where}: the JSON holds a number with too many digits to read"
        ) from None
    except RecursionError:
        raise launch_failed(f"{where}: the JSON is nested too deeply to read") from None
    if not isinstance(obj, dict):
        raise launch_failed(f"{where}: the JSON is not an object")
    unknown = sorted(key for key in obj if key not in KEYS)
    if unknown:
        raise launch_failed(f"{where}: unknown key {unknown[0]!r}; a line holds {', '.join(KEYS)}")
    case = obj.get("case")
    if not isinstance(case, str) or not case:
        raise launch_failed(f"{where}: case is not a text that is not empty")
    if "value" not in obj:
        raise launch_failed(f"{where}: the case {public_case(case)!r} has no value")
    value = number(obj["value"], f"{where}: the value of {public_case(case)!r}")
    unit = obj.get("unit", DEFAULT_UNIT)
    if not isinstance(unit, str) or not unit:
        raise launch_failed(
            f"{where}: the unit of {public_case(case)!r} is not a text that is not empty"
        )
    better = obj.get("better", DEFAULT_BETTER)
    if better not in BETTER:
        raise launch_failed(
            f"{where}: better of {public_case(case)!r} is {better!r}; "
            f"it is one of {', '.join(BETTER)}"
        )
    return Sample(
        case=case,
        metric=METRIC,
        unit=unit,
        better=better,
        kind=kind_of_unit(unit),
        value=value,
    )
