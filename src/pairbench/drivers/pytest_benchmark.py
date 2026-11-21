# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``pytest-benchmark`` driver: pytest-benchmark's JSON output.

Format read from the tool's own documentation and source at version 5.3.1
(https://github.com/ionelmc/pytest-benchmark/tree/v5.3.1, ``src/pytest_benchmark/stats.py``
and ``session.py``), and checked against the output of a real run of
pytest-benchmark 5.3.1 under pytest 9.2.0.

``prepare`` adds ``--benchmark-json=<file>``. A command that already names
``--benchmark-json`` is refused.

``read`` gives one case per entry of ``benchmarks[]``, named by the test's
full name (``fullname``), in seconds:

* when ``stats.data`` holds the time of each round, the value is the median
  of those times and ``n_inner`` their count;
* otherwise, as in a file saved without the data of each round, the value is
  the tool's own ``stats.median``, the reducer is ``tool_summary`` and
  ``n_inner`` is the tool's ``stats.rounds``.

The version is the file's top-level ``version``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pairbench.api import REDUCER_TOOL_SUMMARY, DriverContext, Sample
from pairbench.drivers.base import (
    ToolDriver,
    count,
    items,
    mapping,
    member,
    number,
    numbers,
    own_option,
    path_in_side,
    read_json,
    reduce,
    refuse_own_option,
    text,
)

OUTPUT_FILE: Final = "pytest-benchmark.json"
OWN_OPTIONS: Final[tuple[str, ...]] = ("--benchmark-json",)
METRIC: Final = "time"


class PytestBenchmarkDriver(ToolDriver):
    """Reads the time of each test from pytest-benchmark's JSON output."""

    name = "pytest-benchmark"
    tool = "pytest-benchmark"
    output_file = OUTPUT_FILE
    tested_majors = (5,)
    real_run = True
    format_read = "pytest-benchmark JSON output (--benchmark-json), version 5"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Add ``--benchmark-json``."""
        found = own_option(argv, OWN_OPTIONS)
        if found is not None:
            raise refuse_own_option(self.name, self.tool, found)
        return [*argv, f"--benchmark-json={path_in_side(ctx, OUTPUT_FILE)}"]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return one case per test."""
        doc = mapping(read_json(path, self.name), path.name)
        entries = items(member(doc, "benchmarks", path.name), f"{path.name}: benchmarks")
        samples = []
        for i, raw in enumerate(entries):
            where = f"{path.name}: benchmarks[{i}]"
            entry = mapping(raw, where)
            fullname = text(member(entry, "fullname", where), f"{where}: fullname")
            stats = mapping(member(entry, "stats", where), f"{where}: stats")
            data = stats.get("data")
            if data is not None and data != []:
                value, n_inner, reducer = reduce(numbers(data, f"{where}: stats.data"))
            else:
                value = number(member(stats, "median", f"{where}: stats"), f"{where}: stats.median")
                rounds = stats.get("rounds")
                n_inner = (
                    max(count(rounds, f"{where}: stats.rounds"), 1) if rounds is not None else 1
                )
                reducer = REDUCER_TOOL_SUMMARY
            samples.append(
                Sample(
                    case=fullname,
                    metric=METRIC,
                    unit="s",
                    better="lower",
                    kind="time",
                    value=value,
                    n_inner=n_inner,
                    reducer=reducer,
                )
            )
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return every test."""
        return [sample.case for sample in samples]

    def version_in(self, path: Path) -> str | None:
        """Return the file's top-level ``version``."""
        doc = mapping(read_json(path, self.name), path.name)
        version = doc.get("version")
        return version if isinstance(version, str) and version else None
