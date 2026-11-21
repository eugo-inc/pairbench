# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``llama-bench`` driver: llama.cpp's benchmark in JSON output.

Field names taken from the output of a real run of ``llama-bench`` (llama.cpp
build 12375, commit 9d25e0014) on CPU with a small openly licensed model, and
checked against the tool's own source, ``tools/llama-bench/llama-bench.cpp``
at that commit
(https://github.com/ggml-org/llama.cpp/blob/9d25e0014/tools/llama-bench/llama-bench.cpp).

``prepare`` adds ``-o json`` when the command names no output format; the
tool then prints a JSON array on standard output, which the driver reads from
the launch's standard output file. ``-o json`` or ``--output json`` already
in the command is kept; any other output format is refused.

``read`` gives one case per test, named as the tool's own table names it:
``pp<N>`` for a prompt of N tokens, ``tg<N>`` for N generated tokens,
``pp<N>+tg<M>`` for both, each followed by `` @ d<D>`` when the test starts
at a context depth of D tokens. The value is the median of the test's
``samples_ts`` (tokens per second, one per repetition); a test without them
gives the tool's own ``avg_ts`` as a ``tool_summary``. Two tests of one name,
as a sweep over threads or models gives them, are refused.

The pure generation tests count toward the verdict by default.

The version is ``b<build_number> (<build_commit>)``. llama.cpp numbers its
builds and has no major version, so every build but the one the driver was
tested with gives the note of an untested version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pairbench.api import ARTIFACT_STDOUT, REDUCER_TOOL_SUMMARY, DriverContext, Sample, ToolVersion
from pairbench.drivers.base import (
    ToolDriver,
    count,
    items,
    launch_failed,
    mapping,
    member,
    number,
    numbers,
    read_json,
    reduce,
    result_path,
)
from pairbench.errors import Refusal

OUTPUT_OPTIONS: Final[tuple[str, ...]] = ("-o", "--output")
OUTPUT_FORMAT: Final = "json"
METRIC: Final = "tokens_per_s"
UNIT: Final = "tokens/s"
GENERATION: Final = "tg"
TESTED_BUILD: Final = 12375


class LlamaBenchDriver(ToolDriver):
    """Reads the token rate of each test from llama-bench's JSON output."""

    name = "llama-bench"
    tool = "llama-bench"
    output_file = ARTIFACT_STDOUT
    tested_majors = ()
    real_run = True
    format_read = "llama-bench JSON output (-o json) on standard output, llama.cpp build b12375"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Add ``-o json`` unless the command already asks for JSON."""
        for i, arg in enumerate(argv):
            if arg in OUTPUT_OPTIONS:
                given = argv[i + 1] if i + 1 < len(argv) else ""
                if given != OUTPUT_FORMAT:
                    raise Refusal(
                        "E_USAGE",
                        f"the llama-bench driver reads the output format json; the command "
                        f"asks for {arg} {given!r}: drop the option or give {arg} json",
                    )
                return argv
        return [*argv, "-o", OUTPUT_FORMAT]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return one case per test."""
        tests = items(read_json(path, self.name), path.name)
        samples = []
        for i, raw in enumerate(tests):
            where = f"{path.name}: [{i}]"
            test = mapping(raw, where)
            case = _test_name(
                count(member(test, "n_prompt", where), f"{where}: n_prompt"),
                count(member(test, "n_gen", where), f"{where}: n_gen"),
                count(test.get("n_depth", 0), f"{where}: n_depth"),
                where,
            )
            rates = test.get("samples_ts")
            if rates is not None and rates != []:
                value, n_inner, reducer = reduce(numbers(rates, f"{where}: samples_ts"))
            else:
                value = number(member(test, "avg_ts", where), f"{where}: avg_ts")
                n_inner, reducer = 1, REDUCER_TOOL_SUMMARY
            samples.append(
                Sample(
                    case=case,
                    metric=METRIC,
                    unit=UNIT,
                    better="higher",
                    kind="rate",
                    value=value,
                    n_inner=n_inner,
                    reducer=reducer,
                )
            )
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return the pure generation tests."""
        return [sample.case for sample in samples if sample.case.startswith(GENERATION)]

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        """Return the build the output names; only the tested build counts as tested."""
        path = result_path(ctx, artifacts, self.output_file)
        tests = items(read_json(path, self.name), path.name)
        if not tests or not isinstance(tests[0], dict):
            return None
        build = tests[0].get("build_number")
        if isinstance(build, bool) or not isinstance(build, int):
            return None
        commit = tests[0].get("build_commit")
        version = f"b{build}" + (f" ({commit})" if isinstance(commit, str) and commit else "")
        return ToolVersion(tool=self.tool, version=version, tested=build == TESTED_BUILD)


def _test_name(n_prompt: int, n_gen: int, n_depth: int, where: str) -> str:
    if n_prompt > 0 and n_gen == 0:
        name = f"pp{n_prompt}"
    elif n_gen > 0 and n_prompt == 0:
        name = f"tg{n_gen}"
    elif n_prompt > 0 and n_gen > 0:
        name = f"pp{n_prompt}+tg{n_gen}"
    else:
        raise launch_failed(f"{where}: a test with neither prompt nor generated tokens")
    if n_depth > 0:
        name += f" @ d{n_depth}"
    return name
