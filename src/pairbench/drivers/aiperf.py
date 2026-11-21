# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``aiperf`` driver: aiperf's per-request records, one artifact folder per load level.

Options and file formats read from aiperf 0.13.0: the output of
``aiperf profile --help`` and the package's source at that release
(https://github.com/ai-dynamo/aiperf/tree/v0.13.0), in particular the record
model ``MetricRecordInfo`` in ``aiperf/common/models/record_models.py``,
checked against the files of real runs of that version against a small model
served on CPU.

``prepare`` returns one step per load level of ``workload.levels``, in order,
each an ``aiperf profile`` against the endpoint of the serving side. The
shared workload is the rest of the command: a workload that is empty or
starts with an option is put after ``aiperf profile``, any other workload is
the whole command. The driver adds to each step:

* ``--url <endpoint>``, and ``--model <name>`` when the endpoint names a
  model and the workload names none;
* ``--endpoint-type chat``, ``--streaming`` and ``--ui none`` unless the
  workload chooses an endpoint type, streaming or a user interface itself;
* ``--concurrency <level>`` for a level of concurrent requests,
  ``--request-rate <level>`` for a level of requests per second;
* ``--benchmark-duration <s>`` when ``workload.level_duration`` is set;
* ``--random-seed <seed>``;
* ``--artifact-dir <launch folder>/aiperf-<label>`` and
  ``--export-level records``, which makes aiperf write the per-request file
  ``profile_export.jsonl``.

A workload that gives any of the options of the last four points, under any
of their names, is refused with ``E_USAGE``.

``read`` takes each level's ``profile_export.jsonl``, one JSON object per
line: the records whose ``metadata.benchmark_phase`` is ``profiling``, that
were not cancelled (``metadata.was_cancelled``) and carry no ``error``. Each
gives a time to first token (``metrics.time_to_first_token``), an inter-token
latency (``metrics.inter_token_latency``, absent for a request of one output
token), its output tokens (``metrics.output_sequence_length``, else
``metrics.output_token_count``) and its start and end
(``metadata.request_start_ns`` and ``request_end_ns``). A metric's value is
converted from the unit the record names. Starts and ends that are whole
numbers are taken from the earliest start in whole nanoseconds before they
become seconds, so a clock far from zero loses no precision. The serving
metrics follow from them as the ``guidellm`` driver describes, which also
says which requests cannot have happened and are refused.

A level without the per-request file falls back to aiperf's own summary,
``profile_export_aiperf.json`` in the same folder, with ``reducer``
``tool_summary``: ``p50`` and ``p90`` of ``time_to_first_token``, ``p50`` of
``inter_token_latency``, ``avg`` of ``output_token_throughput`` and of
``request_throughput``, and ``sum`` of ``output_sequence_length``.

The version is ``aiperf_version`` of the summary.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal

from pairbench.api import DriverContext, Invocation, Sample, Step, ToolVersion
from pairbench.drivers.base import (
    SECONDS_PER,
    ToolDriver,
    count,
    launch_failed,
    mapping,
    member,
    number,
    own_option,
    read_json,
    read_text,
    refuse_own_option,
    text,
    tool_version_of,
    unique,
)
from pairbench.drivers.guidellm import (
    Request,
    Summary,
    checked,
    checked_summary,
    client_command,
    energy_sample,
    file_label,
    level_labels,
    level_samples,
    level_value,
    need_endpoint,
    serving_primary,
    summary_samples,
)
from pairbench.errors import Refusal

PROGRAM: Final[tuple[str, ...]] = ("aiperf", "profile")
FOLDER_PREFIX: Final = "aiperf-"
RECORDS_FILE: Final = "profile_export.jsonl"
SUMMARY_FILE: Final = "profile_export_aiperf.json"
PROFILING: Final = "profiling"
OWN_OPTIONS: Final[tuple[str, ...]] = (
    "--url",
    "-u",
    "--concurrency",
    "--request-rate",
    "--benchmark-duration",
    "--random-seed",
    "--artifact-dir",
    "--output-artifact-dir",
    "--export-level",
    "--profile-export-level",
    "--profile-export-prefix",
    "--profile-export-file",
)
MODEL_OPTIONS: Final[tuple[str, ...]] = ("--model", "--model-names", "-m")
ENDPOINT_TYPE_OPTIONS: Final[tuple[str, ...]] = ("--endpoint-type",)
STREAMING_OPTIONS: Final[tuple[str, ...]] = ("--streaming", "--no-streaming")
UI_OPTIONS: Final[tuple[str, ...]] = ("--ui", "--ui-type")
TESTED_MAJORS: Final[tuple[int, ...]] = (0,)
# Milliseconds per unit of a time metric.
MS_PER: Final[Mapping[str, float]] = {unit: s * 1e3 for unit, s in SECONDS_PER.items()}
# The record metrics that hold a request's output tokens, in the order tried.
TOKEN_METRICS: Final[tuple[str, ...]] = ("output_sequence_length", "output_token_count")


class AiperfDriver(ToolDriver):
    """The ``aiperf`` driver."""

    name = "aiperf"
    where: Literal["in_side", "client"] = "client"
    tool = "aiperf"
    output_file = f"aiperf-<label>/{RECORDS_FILE}"
    tested_majors = TESTED_MAJORS
    real_run = True
    format_read = "aiperf's per-request records (profile_export.jsonl), one folder per load level"

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return one ``aiperf profile`` per load level against the serving side."""
        base_url = need_endpoint(ctx, self.name)
        labels = level_labels(ctx, self.name)
        command = client_command(argv, PROGRAM)
        option = own_option(command, OWN_OPTIONS)
        if option is not None:
            raise refuse_own_option(self.name, self.tool, option)
        common = [*command, "--url", base_url]
        model = ctx.endpoint.model_name if ctx.endpoint is not None else None
        if model and own_option(command, MODEL_OPTIONS) is None:
            common += ["--model", model]
        if own_option(command, ENDPOINT_TYPE_OPTIONS) is None:
            common += ["--endpoint-type", "chat"]
        if own_option(command, STREAMING_OPTIONS) is None:
            common.append("--streaming")
        if own_option(command, UI_OPTIONS) is None:
            common += ["--ui", "none"]
        steps: list[Step] = []
        for label in labels:
            level = str(level_value(label))
            words = list(common)
            words += (
                ["--concurrency", level] if label.startswith("c") else ["--request-rate", level]
            )
            if ctx.settings.level_duration_s is not None:
                words += ["--benchmark-duration", f"{ctx.settings.level_duration_s:g}"]
            words += ["--random-seed", str(ctx.seed)]
            words += ["--artifact-dir", str(ctx.artifacts / f"{FOLDER_PREFIX}{label}")]
            words += ["--export-level", "records"]
            steps.append(Step(label=label, argv=tuple(words)))
        return Invocation(steps=tuple(steps))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return the serving cases of every level's records."""
        if ctx.result_file is not None:
            levels = [(file_label(ctx, self.name), ctx.result_file)]
        else:
            levels = [
                (label, artifacts / f"{FOLDER_PREFIX}{label}" / RECORDS_FILE)
                for label in level_labels(ctx, self.name)
            ]
        out: list[Sample] = []
        for label, path in levels:
            out += self._level(ctx, label, path)
        return unique(out, "aiperf records")

    def _level(self, ctx: DriverContext, label: str, path: Path) -> list[Sample]:
        summary_path = path.with_name(SUMMARY_FILE)
        tokens: float | None
        if path.exists() or not summary_path.exists():
            requests = records(read_text(path, self.name), f"{path.parent.name}/{path.name}")
            samples, tokens = level_samples(
                label, requests, f"{path.parent.name}/{path.name}", ctx.note
            )
        else:
            where = f"{path.parent.name}/{SUMMARY_FILE}"
            summary = summary_of(read_json(summary_path, self.name), where)
            if summary.count == 0:
                raise launch_failed(f"{where}: the level {label} has no successful request")
            samples, tokens = summary_samples(label, checked_summary(summary, where))
        energy = energy_sample(ctx, label, tokens, path.parent.name)
        return samples + ([energy] if energy is not None else [])

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return serving_primary(samples)

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        """Return ``aiperf_version`` of the first level's summary, or ``None``."""
        if ctx.result_file is not None:
            path = ctx.result_file.with_name(SUMMARY_FILE)
        else:
            labels = ctx.settings.labels()
            if not labels:
                return None
            path = artifacts / f"{FOLDER_PREFIX}{labels[0]}" / SUMMARY_FILE
        try:
            doc = read_json(path, self.name)
        except Refusal:
            return None
        version = doc.get("aiperf_version") if isinstance(doc, dict) else None
        if not isinstance(version, str) or not version:
            return None
        return tool_version_of(self.tool, version, self.tested_majors)


def records(content: str, where: str) -> list[Request]:
    """Return the successful profiling requests of a ``profile_export.jsonl``.

    Their start and end are seconds from the earliest start among them.
    """
    rows: list[tuple[str, float, float | None, float, int | float, int | float]] = []
    for number_, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        at = f"{where} line {number_}"
        try:
            raw = json.loads(line)
        except ValueError:
            raise launch_failed(f"{at} is not valid JSON") from None
        except RecursionError:
            raise launch_failed(f"{at} is nested too deeply to read") from None
        record = mapping(raw, at)
        meta = mapping(member(record, "metadata", at), f"{at}: metadata")
        if meta.get("benchmark_phase") != PROFILING:
            continue
        if meta.get("was_cancelled") is True or record.get("error") is not None:
            continue
        metrics = mapping(member(record, "metrics", at), f"{at}: metrics")
        ttft = _ms(metrics, "time_to_first_token", at)
        if ttft is None:
            raise launch_failed(f"{at}: metrics has no time_to_first_token")
        tokens = next(
            (_value(metrics, name, at) for name in TOKEN_METRICS if metrics.get(name) is not None),
            None,
        )
        if tokens is None:
            raise launch_failed(f"{at}: metrics has no output_sequence_length")
        itl = _ms(metrics, "inter_token_latency", at)
        start = _stamp(meta, "request_start_ns", at)
        end = _stamp(meta, "request_end_ns", at)
        rows.append((at, ttft, itl, tokens, start, end))
    if not rows:
        return []
    base = min(row[4] for row in rows)
    return [
        checked(
            Request(
                ttft_ms=ttft,
                itl_ms=itl,
                output_tokens=tokens,
                start_s=(start - base) / 1e9,
                end_s=(end - base) / 1e9,
            ),
            at,
        )
        for at, ttft, itl, tokens, start, end in rows
    ]


def _stamp(meta: Mapping[str, Any], key: str, where: str) -> int | float:
    """Return a clock reading in nanoseconds as the record gives it; a whole number stays whole."""
    raw = member(meta, key, where)
    value = number(raw, f"{where}: {key}")
    if isinstance(raw, int):
        return raw
    if not math.isfinite(value):
        raise launch_failed(f"{where}: the start or end of the request is not a finite number")
    return value


def _value(metrics: Mapping[str, Any], name: str, where: str) -> float:
    entry = mapping(metrics[name], f"{where}: metrics.{name}")
    return number(member(entry, "value", f"{where}: metrics.{name}"), f"{where}: {name}.value")


def _ms(metrics: Mapping[str, Any], name: str, where: str) -> float | None:
    """Return a time metric of a record in milliseconds, ``None`` when the record has none."""
    if metrics.get(name) is None:
        return None
    entry = mapping(metrics[name], f"{where}: metrics.{name}")
    unit = text(member(entry, "unit", f"{where}: metrics.{name}"), f"{where}: {name}.unit")
    if unit not in MS_PER:
        raise launch_failed(f"{where}: {name} is in the unit {unit!r}, not a unit of time")
    return _value(metrics, name, where) * MS_PER[unit]


def summary_of(doc: Any, where: str) -> Summary:
    """Return a level as aiperf's own summary gives it."""
    summary = mapping(doc, where)

    def stat(name: str, key: str, *, time: bool) -> float | None:
        entry = summary.get(name)
        if entry is None:
            return None
        found = mapping(entry, f"{where}: {name}")
        value = found.get(key)
        if value is None:
            return None
        figure = number(value, f"{where}: {name}.{key}")
        if not time:
            return figure
        unit = text(member(found, "unit", f"{where}: {name}"), f"{where}: {name}.unit")
        if unit not in MS_PER:
            raise launch_failed(f"{where}: {name} is in the unit {unit!r}, not a unit of time")
        return figure * MS_PER[unit]

    if summary.get("time_to_first_token") is None:
        raise launch_failed(f"{where} has no time_to_first_token")
    held = mapping(summary["time_to_first_token"], f"{where}: time_to_first_token").get("count")
    seen = 0 if held is None else count(held, f"{where}: time_to_first_token.count")
    return Summary(
        count=seen,
        ttft_ms_median=stat("time_to_first_token", "p50", time=True),
        ttft_ms_p90=stat("time_to_first_token", "p90", time=True),
        itl_ms_median=stat("inter_token_latency", "p50", time=True),
        output_tokens_per_s=stat("output_token_throughput", "avg", time=False),
        requests_per_s=stat("request_throughput", "avg", time=False),
        output_tokens=stat("output_sequence_length", "sum", time=False),
    )
