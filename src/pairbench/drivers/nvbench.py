# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``nvbench`` driver: NVBench's JSON output.

Format read from the tool's own source at commit 0f8eb2dd715f (project version
0.1.0, JSON file version 1.0.0): ``nvbench/json_printer.cu``,
``nvbench/detail/measure_cold.cu``, ``nvbench/state.cxx`` and ``docs/cli_help.md``
(https://github.com/NVIDIA/nvbench/blob/0f8eb2dd715f90e963a8ab0ff9374097110cc3f9/nvbench/json_printer.cu),
and checked against the output of a real run of NVBench at that commit on one
NVIDIA GPU.

``prepare`` adds ``--json <file>``. A command that already names ``--json``
is refused.

``read`` walks ``benchmarks[].states[]``. A state's case is named by the
benchmark's ``name`` and the state's ``name`` (its axis values, as the tool
writes them, for example ``Device=0 Elements=2^20``), joined by ``/``. Of the
state's ``summaries[]``:

* the summary tagged ``nv/cold/time/gpu/mean`` gives the case's value: the
  ``data`` entry named ``value``, which the tool stores as a text, in
  seconds (metric ``gpu_time``);
* the summary tagged ``nv/cold/time/cpu/mean`` gives the secondary case
  ``<case>/cpu_time`` (metric ``cpu_time``), when present.

A case is shown with every absolute path in it cut to its last part
(``pairbench.model.public_case``) before ``/cpu_time`` is added, so a string
axis that holds a path (``File=/a/b/data.bin``) gives ``File=data.bin``. A
name whose cut drops words that hold no ``/``, such as the words a path runs
over, ends with the run's mark (``pairbench.api.CaseNames``), before
``/cpu_time``. Two states shown alike, such as two that differ only in a
folder, are refused with ``E_USAGE``.

Both are the tool's own means (``tool_summary``); ``n_inner`` is the count of
the summary tagged ``nv/cold/sample_size``, or 1. A state the tool skipped
(``is_skipped``) is a missing case and is named in a note. A state that was
not skipped and has no GPU-time mean is refused.

The version is ``meta.version.nvbench.string``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pairbench.api import REDUCER_TOOL_SUMMARY, DriverContext, Sample, name_tool_cases
from pairbench.drivers.base import (
    NOTE_CASE_SKIPPED,
    ToolDriver,
    items,
    launch_failed,
    mapping,
    member,
    own_option,
    path_in_side,
    read_json,
    refuse_own_option,
    text,
)

OUTPUT_FILE: Final = "nvbench.json"
OWN_OPTIONS: Final[tuple[str, ...]] = ("--json",)
GPU_MEAN: Final = "nv/cold/time/gpu/mean"
CPU_MEAN: Final = "nv/cold/time/cpu/mean"
SAMPLE_SIZE: Final = "nv/cold/sample_size"
GPU_TIME: Final = "gpu_time"
CPU_TIME: Final = "cpu_time"
CPU_SUFFIX: Final = "/cpu_time"


class NvbenchDriver(ToolDriver):
    """Reads the mean GPU time of each state from NVBench's JSON output."""

    name = "nvbench"
    tool = "NVBench"
    output_file = OUTPUT_FILE
    tested_majors = (0,)
    real_run = True
    cleans_case_ids = True
    format_read = "NVBench JSON output (--json), version 0.1"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Add ``--json``."""
        found = own_option(argv, OWN_OPTIONS)
        if found is not None:
            raise refuse_own_option(self.name, self.tool, found)
        return [*argv, "--json", path_in_side(ctx, OUTPUT_FILE)]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return a GPU-time case, and a CPU-time case where given, per state."""
        doc = mapping(read_json(path, self.name), path.name)
        benchmarks = items(member(doc, "benchmarks", path.name), f"{path.name}: benchmarks")
        # Every state the file lists, skipped ones too, in the order it lists them.
        states: list[tuple[str, Mapping[str, Any], str]] = []
        for b, raw_bench in enumerate(benchmarks):
            at = f"{path.name}: benchmarks[{b}]"
            bench = mapping(raw_bench, at)
            bench_name = text(member(bench, "name", at), f"{at}: name")
            for s, raw_state in enumerate(items(member(bench, "states", at), f"{at}: states")):
                where = f"{at}: states[{s}]"
                state = mapping(raw_state, where)
                state_name = member(state, "name", where)
                if not isinstance(state_name, str):
                    raise launch_failed(f"{where}: name is not a text")
                given = f"{bench_name}/{state_name}" if state_name else bench_name
                states.append((given, state, where))
        shown = name_tool_cases(ctx, [given for given, _, _ in states], path.name, _ADVICE)
        samples: list[Sample] = []
        for given, state, where in states:
            case = shown[given]
            if state.get("is_skipped") is True:
                ctx.note(
                    NOTE_CASE_SKIPPED,
                    f"side {ctx.name!r}: NVBench skipped {case!r}; "
                    "the case is missing from this launch",
                )
                continue
            summaries = _summaries(state, where)
            if GPU_MEAN not in summaries:
                raise launch_failed(f"{where}: the state {case!r} has no summary {GPU_MEAN}")
            n_inner = 1
            if SAMPLE_SIZE in summaries:
                size = _value(summaries[SAMPLE_SIZE], where, SAMPLE_SIZE)
                if not math.isfinite(size):
                    raise launch_failed(f"{where}: {SAMPLE_SIZE} is not a finite number")
                n_inner = max(int(size), 1)
            samples.append(
                _sample(case, GPU_TIME, _value(summaries[GPU_MEAN], where, GPU_MEAN), n_inner)
            )
            if CPU_MEAN in summaries:
                samples.append(
                    _sample(
                        case + CPU_SUFFIX,
                        CPU_TIME,
                        _value(summaries[CPU_MEAN], where, CPU_MEAN),
                        n_inner,
                    )
                )
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return the GPU-time case of every state."""
        return [sample.case for sample in samples if sample.metric == GPU_TIME]

    def version_in(self, path: Path) -> str | None:
        """Return ``meta.version.nvbench.string``."""
        doc = mapping(read_json(path, self.name), path.name)
        node: Any = doc
        for key in ("meta", "version", "nvbench", "string"):
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node if isinstance(node, str) and node else None


_ADVICE: Final = (
    "give each state a name that differs outside its paths, absolute or climbing with '..', "
    "and outside its secrets"
)


def _summaries(state: Mapping[str, Any], where: str) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for i, raw in enumerate(items(state.get("summaries", []), f"{where}: summaries")):
        summary = mapping(raw, f"{where}: summaries[{i}]")
        tag = text(
            member(summary, "tag", f"{where}: summaries[{i}]"), f"{where}: summaries[{i}]: tag"
        )
        out[tag] = summary
    return out


def _value(summary: Mapping[str, Any], where: str, tag: str) -> float:
    at = f"{where}: {tag}"
    for i, raw in enumerate(items(member(summary, "data", at), f"{at}: data")):
        entry = mapping(raw, f"{at}: data[{i}]")
        if entry.get("name") == "value":
            stored = member(entry, "value", f"{at}: data[{i}]")
            if not isinstance(stored, str):
                raise launch_failed(f"{at}: the value is not stored as a text")
            try:
                return float(stored)
            except ValueError:
                raise launch_failed(f"{at}: the value {stored!r} is not a number") from None
    raise launch_failed(f"{at}: no data entry named value")


def _sample(case: str, metric: str, value: float, n_inner: int) -> Sample:
    return Sample(
        case=case,
        metric=metric,
        unit="s",
        better="lower",
        kind="time",
        value=value,
        n_inner=n_inner,
        reducer=REDUCER_TOOL_SUMMARY,
    )
