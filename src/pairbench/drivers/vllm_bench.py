# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``vllm-bench`` driver: the result file of ``vllm bench serve``, one per load level.

Options and the result fields read from vLLM's public source at release
v0.33.0: ``vllm/benchmarks/serve.py`` and ``vllm/benchmarks/datasets/datasets.py``
(https://github.com/vllm-project/vllm/tree/v0.33.0/vllm/benchmarks). The
driver has no fixture from a run of the real tool yet, only one written from
that source, so ``pairbench doctor`` marks it experimental.

``prepare`` returns one step per load level of ``workload.levels``, in order,
each a ``vllm bench serve`` against the endpoint of the serving side. The
shared workload is the rest of the command: a workload that is empty or
starts with an option is put after ``vllm bench serve``, any other workload is
the whole command. The driver adds to each step:

* ``--base-url <endpoint>``, and ``--model <name>`` when the endpoint names a
  model and the workload names none;
* ``--max-concurrency <level>`` for a level of concurrent requests,
  ``--request-rate <level>`` for a level of requests per second;
* ``--seed <seed>``;
* ``--save-result``, ``--result-dir <launch folder>`` and
  ``--result-filename vllm-bench-<label>.json``.

A workload that gives ``--base-url``, ``--host``, ``--port``,
``--max-concurrency``, ``--request-rate``, ``--seed``, ``--result-dir``,
``--result-filename`` or ``--append-result`` is refused with ``E_USAGE``.
``vllm bench serve`` ends after its number of prompts, not after a time, so a
load with ``workload.level_duration`` is refused with ``E_USAGE`` too.

``read`` gives, per level, one case ``<label>/<field>`` for each field of the
result file that the script computes as a summary, with ``reducer``
``tool_summary``: ``request_throughput`` (requests/s),
``output_throughput`` and ``total_token_throughput`` (tokens/s), and every
``mean_``, ``median_`` and ``p<N>_`` field of ``ttft``, ``tpot``, ``itl`` and
``e2el`` in milliseconds. ``tokens_per_joule[gpu]`` divides
``total_output_tokens`` by the GPU energy of the level's window when power was
sampled. A result with no completed request, or with a negative figure, is
refused.

The output token rate at the highest level counts toward the verdict.
The result file names no version of vLLM.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final, Literal

from pairbench.api import REDUCER_TOOL_SUMMARY, DriverContext, Invocation, Sample, Step
from pairbench.drivers.base import (
    ToolDriver,
    count,
    launch_failed,
    mapping,
    number,
    own_option,
    read_json,
    refuse_own_option,
    unique,
)
from pairbench.drivers.guidellm import (
    LEVEL_LABEL,
    client_command,
    energy_sample,
    file_label,
    level_labels,
    level_value,
    need_endpoint,
)
from pairbench.errors import Refusal
from pairbench.model import case_id

PROGRAM: Final[tuple[str, ...]] = ("vllm", "bench", "serve")
FILE_PREFIX: Final = "vllm-bench-"
OWN_OPTIONS: Final[tuple[str, ...]] = (
    "--base-url",
    "--host",
    "--port",
    "--max-concurrency",
    "--request-rate",
    "--seed",
    "--result-dir",
    "--result-filename",
    "--append-result",
)
MODEL_OPTION: Final = "--model"
SAVE_OPTION: Final = "--save-result"
# The rate fields of a result: unit.
RATE_FIELDS: Final[dict[str, str]] = {
    "request_throughput": "requests/s",
    "output_throughput": "tokens/s",
    "total_token_throughput": "tokens/s",
}
# The latency fields of a result, in milliseconds.
LATENCY_FIELD: Final = re.compile(r"(mean|median|p[0-9]+(\.[0-9]+)?)_(ttft|tpot|itl|e2el)_ms")
PRIMARY_FIELD: Final = "output_throughput"


class VllmBenchDriver(ToolDriver):
    """The ``vllm-bench`` driver."""

    name = "vllm-bench"
    where: Literal["in_side", "client"] = "client"
    tool = "vllm bench serve"
    output_file = "vllm-bench-<label>.json"
    real_run = False
    format_read = "the result file of vllm bench serve, one per load level"

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return one ``vllm bench serve`` per load level against the serving side."""
        base_url = need_endpoint(ctx, self.name)
        labels = level_labels(ctx, self.name)
        if ctx.settings.level_duration_s is not None:
            raise Refusal(
                "E_USAGE",
                f"the {self.name} driver cannot end a level after a time: vllm bench serve ends "
                "after its number of prompts; leave workload.level_duration unset and give "
                "--num-prompts in the workload",
            )
        command = client_command(argv, PROGRAM)
        option = own_option(command, OWN_OPTIONS)
        if option is not None:
            raise refuse_own_option(self.name, self.tool, option)
        common = [*command, "--base-url", base_url]
        model = ctx.endpoint.model_name if ctx.endpoint is not None else None
        if model and own_option(command, (MODEL_OPTION,)) is None:
            common += [MODEL_OPTION, model]
        steps: list[Step] = []
        for label in labels:
            level = str(level_value(label))
            words = list(common)
            words += (
                ["--max-concurrency", level] if label.startswith("c") else ["--request-rate", level]
            )
            words += ["--seed", str(ctx.seed)]
            if own_option(command, (SAVE_OPTION,)) is None:
                words.append(SAVE_OPTION)
            words += ["--result-dir", str(ctx.artifacts)]
            words += ["--result-filename", f"{FILE_PREFIX}{label}.json"]
            steps.append(Step(label=label, argv=tuple(words)))
        return Invocation(steps=tuple(steps))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return the summary fields of every level's result file."""
        if ctx.result_file is not None:
            levels = [(file_label(ctx, self.name), ctx.result_file)]
        else:
            levels = [
                (label, artifacts / f"{FILE_PREFIX}{label}.json")
                for label in level_labels(ctx, self.name)
            ]
        out: list[Sample] = []
        for label, path in levels:
            out += self._level(ctx, label, path)
        return unique(out, "vllm bench serve results")

    def _level(self, ctx: DriverContext, label: str, path: Path) -> list[Sample]:
        where = path.name
        result = mapping(read_json(path, self.name), where)
        completed = result.get("completed")
        done = None if completed is None else count(completed, f"{where}: completed")
        if done == 0:
            raise launch_failed(f"{where}: the level {label} has no completed request")
        n_inner = done if done else 1
        out: list[Sample] = []
        for field, value in result.items():
            sample = _field_sample(label, field, value, n_inner, where)
            if sample is not None:
                out.append(sample)
        if not any(s.metric in RATE_FIELDS for s in out):
            raise launch_failed(f"{where} holds no request_throughput or output_throughput")
        tokens = result.get("total_output_tokens")
        total = None if tokens is None else not_negative(tokens, f"{where}: total_output_tokens")
        energy = energy_sample(ctx, label, total, where)
        return out + ([energy] if energy is not None else [])

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return ``output_throughput`` at the highest load level."""
        levels: dict[str, int] = {}
        for sample in samples:
            label = sample.case.partition("/")[0]
            found = LEVEL_LABEL.fullmatch(label)
            if found and sample.metric == PRIMARY_FIELD:
                levels[sample.case] = int(found.group(2))
        if not levels:
            return []
        top = max(levels.values())
        return [case for case, level in levels.items() if level == top]


def not_negative(value: Any, where: str) -> float:
    """Return ``value`` as a number of zero or more, or refuse naming ``where``."""
    figure = number(value, where)
    if figure < 0:
        raise launch_failed(f"{where} {value!r} is negative")
    return figure


def _field_sample(label: str, field: str, value: Any, n_inner: int, where: str) -> Sample | None:
    """Return the case of one field of a result, or ``None`` for a field that is no summary."""
    if field in RATE_FIELDS:
        unit, better, kind = RATE_FIELDS[field], "higher", "rate"
    elif LATENCY_FIELD.fullmatch(field):
        unit, better, kind = "ms", "lower", "time"
    else:
        return None
    if value is None:
        return None
    return Sample(
        case=case_id(label, field),
        metric=field,
        unit=unit,
        better=better,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        value=not_negative(value, f"{where}: {field}"),
        n_inner=n_inner,
        reducer=REDUCER_TOOL_SUMMARY,
    )
