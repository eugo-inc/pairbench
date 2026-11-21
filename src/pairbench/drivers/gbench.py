# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``gbench`` driver: Google Benchmark's JSON output.

Format read from the tool's own source, ``src/json_reporter.cc`` at the tags
v1.8.3 and v1.9.4 (https://github.com/google/benchmark/blob/v1.9.4/src/json_reporter.cc),
and checked against the output of a real run of version 1.8.3.

``prepare`` adds ``--benchmark_out=<file> --benchmark_out_format=json``. A
command that already names ``--benchmark_out`` or ``--benchmark_out_format``
is refused.

``read`` takes the entries of ``benchmarks[]`` whose ``run_type`` is
``iteration``; aggregate entries (mean, median, standard deviation and the
like) are ignored. The entries of one benchmark name are its repetitions.
Per name:

* the case named as the benchmark holds the median of the entries'
  ``real_time``, converted from ``time_unit`` to seconds (metric
  ``real_time``);
* the secondary case ``<name>/cpu_time`` holds the median of ``cpu_time``
  (metric ``cpu_time``).

A name is shown with every absolute path in it cut to its last part
(``pairbench.model.public_case``) before ``/cpu_time`` is added, so
``BM_Load/path:/a/b/data.bin`` gives ``BM_Load/path:data.bin`` and
``BM_Load/path:data.bin/cpu_time``. A name whose cut drops words that hold no
``/``, such as the words a path runs over, ends with the run's mark
(``pairbench.api.CaseNames``), before ``/cpu_time``: ``BM_Load/x +1a2b3c4d``
and ``BM_Load/x +1a2b3c4d/cpu_time``. Two benchmarks shown alike, such as two
that differ only in a folder, are refused with ``E_USAGE``.

A benchmark that reported an error or a skip (``error_occurred`` or
``skipped``) in any of its entries is left out and named in a note. A file
with aggregate entries only, as ``--benchmark_report_aggregates_only`` writes
it, has no repetition to read and is refused. The format has no
per-iteration samples.

The version is ``context.library_version``, which the tool writes from
version 1.8.4 on (https://github.com/google/benchmark/blob/v1.8.4/src/json_reporter.cc);
version 1.8.3 and older name none.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pairbench.api import DriverContext, Sample, name_tool_cases
from pairbench.drivers.base import (
    NOTE_CASE_SKIPPED,
    SECONDS_PER,
    ToolDriver,
    items,
    launch_failed,
    mapping,
    member,
    number,
    own_option,
    path_in_side,
    read_json,
    reduce,
    refuse_own_option,
    text,
)

OUTPUT_FILE: Final = "gbench.json"
OWN_OPTIONS: Final[tuple[str, ...]] = ("--benchmark_out", "--benchmark_out_format")
REAL_TIME: Final = "real_time"
CPU_TIME: Final = "cpu_time"
CPU_SUFFIX: Final = "/cpu_time"


class GbenchDriver(ToolDriver):
    """Reads the repetitions of each benchmark from Google Benchmark's JSON output."""

    name = "gbench"
    tool = "Google Benchmark"
    output_file = OUTPUT_FILE
    tested_majors = (1,)
    real_run = True
    cleans_case_ids = True
    format_read = "Google Benchmark JSON output (--benchmark_out_format=json), versions 1.x"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Add ``--benchmark_out`` and ``--benchmark_out_format=json``."""
        found = own_option(argv, OWN_OPTIONS)
        if found is not None:
            raise refuse_own_option(self.name, self.tool, found)
        target = path_in_side(ctx, OUTPUT_FILE)
        return [*argv, f"--benchmark_out={target}", "--benchmark_out_format=json"]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return a real-time and a CPU-time case per benchmark name."""
        doc = mapping(read_json(path, self.name), path.name)
        entries = items(member(doc, "benchmarks", path.name), f"{path.name}: benchmarks")
        real: dict[str, list[float]] = {}
        cpu: dict[str, list[float]] = {}
        # Every name the file lists, skipped ones too, in the order it first lists them.
        listed: dict[str, None] = {}
        skipped: list[str] = []
        aggregates = 0
        for i, raw in enumerate(entries):
            where = f"{path.name}: benchmarks[{i}]"
            entry = mapping(raw, where)
            run_type = text(member(entry, "run_type", where), f"{where}: run_type")
            if run_type != "iteration":
                aggregates += 1
                continue
            name = text(member(entry, "name", where), f"{where}: name")
            listed[name] = None
            if _skipped(entry):
                if name not in skipped:
                    skipped.append(name)
                continue
            scale = _seconds_per(entry, where)
            real.setdefault(name, []).append(
                number(member(entry, REAL_TIME, where), f"{where}: {REAL_TIME}") * scale
            )
            cpu.setdefault(name, []).append(
                number(member(entry, CPU_TIME, where), f"{where}: {CPU_TIME}") * scale
            )
        for name in skipped:
            real.pop(name, None)
            cpu.pop(name, None)
        if not real and not skipped and aggregates:
            raise launch_failed(
                f"{path.name} holds aggregate entries only; the gbench driver reads the "
                "repetitions: drop --benchmark_report_aggregates_only"
            )
        shown = name_tool_cases(ctx, list(listed), path.name, _ADVICE)
        for name in skipped:
            ctx.note(
                NOTE_CASE_SKIPPED,
                f"side {ctx.name!r}: Google Benchmark reported an error or a skip for "
                f"{shown[name]!r}; the case is missing from this launch",
            )
        samples: list[Sample] = []
        for name, values in real.items():
            samples.append(_sample(shown[name], REAL_TIME, values))
            samples.append(_sample(shown[name] + CPU_SUFFIX, CPU_TIME, cpu[name]))
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return the real-time case of every benchmark."""
        return [sample.case for sample in samples if sample.metric == REAL_TIME]

    def version_in(self, path: Path) -> str | None:
        """Return ``context.library_version``, written from version 1.8.4 on."""
        doc = mapping(read_json(path, self.name), path.name)
        context = doc.get("context")
        if not isinstance(context, dict):
            return None
        version = context.get("library_version")
        return version if isinstance(version, str) and version else None


_ADVICE: Final = (
    "give each benchmark a name that differs outside its paths, absolute or climbing with '..', "
    "and outside its secrets"
)


def _skipped(entry: Mapping[str, Any]) -> bool:
    return entry.get("error_occurred") is True or entry.get("skipped") is True


def _seconds_per(entry: Mapping[str, Any], where: str) -> float:
    unit = text(member(entry, "time_unit", where), f"{where}: time_unit")
    scale = SECONDS_PER.get(unit)
    if scale is None:
        raise launch_failed(f"{where}: time_unit {unit!r} is not one of ns, us, ms, s")
    return scale


def _sample(case: str, metric: str, values: list[float]) -> Sample:
    value, n_inner, reducer = reduce(values)
    return Sample(
        case=case,
        metric=metric,
        unit="s",
        better="lower",
        kind="time",
        value=value,
        n_inner=n_inner,
        reducer=reducer,
    )
