# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``guidellm`` driver: guidellm's JSON report, one per load level.

Options and the report format read from guidellm 0.8.1: the output of
``guidellm run --help`` and the package's source at that release
(https://github.com/vllm-project/guidellm/tree/v0.8.1), checked against the
reports of real runs of that version against a small model served on CPU.

``prepare`` returns one step per load level of ``workload.levels``, in order,
each a ``guidellm run`` against the endpoint of the serving side. The shared
workload is the rest of the command: a workload that is empty or starts with
an option is put after ``guidellm run``, any other workload is the whole
command. The driver adds to each step:

* ``--backend kind=openai_http,target=<endpoint>`` with ``model=<name>`` when
  the endpoint names a model;
* ``--profile kind=concurrent,streams=<level>`` for a level of concurrent
  requests, ``--profile kind=constant,rate=<level>`` for a level of requests
  per second;
* ``--constraint kind=max_duration,seconds=<s>`` when
  ``workload.level_duration`` is set;
* ``--seed kind=static,value=<seed>``;
* ``--output kind=json,path=<launch folder>/guidellm-<label>.json``;
* ``--disable-console-interactive`` unless a console option is given.

guidellm keeps the statistics of every request in its report unless
``--metrics`` asks for a sample (``sample_size``), so a workload that gives
``sample_size``, or any of the options above but the constraint and the
console options, is refused with ``E_USAGE``. A workload without ``--data``
is refused too: guidellm then has nothing to send.

``read`` takes ``benchmarks[0]`` of each level's report. Its per-request
records, ``requests.successful``, give the serving metrics (see
``level_samples``). A report without them falls back to guidellm's own
summary under ``metrics``, with ``reducer`` ``tool_summary``: the median and
``p90`` of ``time_to_first_token_ms`` and the median of
``inter_token_latency_ms``, the ``mean`` of ``output_tokens_per_second`` and of
``requests_per_second``, and the ``total_sum`` of ``output_token_count``.

The version is ``metadata.guidellm_version``.

The serving metrics, shared with the ``aiperf`` driver. Cases are
``<label>/<metric>`` with the level's label, ``c<N>`` or ``r<N>``:

* ``ttft_ms_median`` and ``ttft_ms_p90``: the median and the 90th percentile
  of the time to first token of the successful requests, as the tool measured
  each, in milliseconds;
* ``itl_ms_median``: the median of the requests' inter-token latency, in
  milliseconds; a request with one output token has none and is left out;
* ``output_tokens_per_s`` and ``requests_per_s``: the output tokens and the
  number of the successful requests over the time from the first start to the
  last end among them;
* ``tokens_per_joule[gpu]``: the output tokens over the GPU energy of the
  level's window, when power was sampled.

Medians and percentiles come from ``pairbench.model.quantile``. The cases at
the highest level count toward the verdict, except ``ttft_ms_p90`` and
``requests_per_s``.

A request that cannot have happened is output that cannot be read
(``E_LAUNCH_FAILED``): a negative time to first token, inter-token latency
or output token count, a start or end that is not a finite number, or an
end before the start. So is a tool's summary with a negative figure.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pairbench.api import (
    REDUCER_TOOL_SUMMARY,
    DriverContext,
    Invocation,
    Sample,
    Step,
    ToolVersion,
)
from pairbench.drivers.base import (
    NOTE_CASE_SKIPPED,
    ToolDriver,
    count,
    items,
    launch_failed,
    mapping,
    member,
    number,
    own_option,
    read_json,
    reduce,
    refuse_own_option,
    tool_version_of,
    unique,
)
from pairbench.errors import Refusal
from pairbench.model import METRIC_TOKENS_PER_JOULE, case_id, quantile

# The serving metrics.
METRIC_TTFT_MEDIAN: Final = "ttft_ms_median"
METRIC_TTFT_P90: Final = "ttft_ms_p90"
METRIC_ITL_MEDIAN: Final = "itl_ms_median"
METRIC_OUTPUT_RATE: Final = "output_tokens_per_s"
METRIC_REQUEST_RATE: Final = "requests_per_s"
# The metrics at the highest level that count toward the verdict by default.
PRIMARY_METRICS: Final[tuple[str, ...]] = (
    METRIC_TTFT_MEDIAN,
    METRIC_ITL_MEDIAN,
    METRIC_OUTPUT_RATE,
    METRIC_TOKENS_PER_JOULE,
)
# How a value was made from the requests of a level, beside median and identity.
REDUCER_P90: Final = "p90"
REDUCER_RATE: Final = "rate"
REDUCER_PER_JOULE: Final = "per_joule"
# A load-level label: c<N> or r<N>.
LEVEL_LABEL: Final = re.compile(r"([cr])([1-9][0-9]*)")

PROGRAM: Final[tuple[str, ...]] = ("guidellm", "run")
FILE_PREFIX: Final = "guidellm-"
OWN_OPTIONS: Final[tuple[str, ...]] = ("--backend", "--profile", "--output", "--seed", "--override")
DATA_OPTION: Final = "--data"
METRICS_OPTION: Final = "--metrics"
CONSOLE_OPTIONS: Final[tuple[str, ...]] = (
    "--disable-console-interactive",
    "--disable-progress",
    "--disable-console",
    "--disable-console-outputs",
)
TESTED_MAJORS: Final[tuple[int, ...]] = (0,)


# ---------------------------------------------------------------------------
# The serving metrics, shared with the aiperf driver
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Request:
    """One successful request as a load tool recorded it.

    ``ttft_ms`` and ``itl_ms`` are milliseconds, ``itl_ms`` is ``None`` for a
    request with no inter-token latency, ``start_s`` and ``end_s`` are
    seconds on one clock.
    """

    ttft_ms: float
    itl_ms: float | None
    output_tokens: float
    start_s: float
    end_s: float


@dataclasses.dataclass(frozen=True)
class Summary:
    """A level as a load tool's own summary gives it. ``None`` is a figure it does not give."""

    count: int
    ttft_ms_median: float | None
    ttft_ms_p90: float | None
    itl_ms_median: float | None
    output_tokens_per_s: float | None
    requests_per_s: float | None
    output_tokens: float | None


def checked(request: Request, where: str) -> Request:
    """Return ``request`` when it could have happened, or refuse naming ``where``.

    A negative time to first token, inter-token latency or output token
    count, a start or end that is not a finite number, and an end before the
    start are output that cannot be read.
    """
    if not (math.isfinite(request.start_s) and math.isfinite(request.end_s)):
        raise launch_failed(f"{where}: the start or end of the request is not a finite number")
    if request.ttft_ms < 0:
        raise launch_failed(f"{where}: the time to first token {request.ttft_ms!r} ms is negative")
    if request.itl_ms is not None and request.itl_ms < 0:
        raise launch_failed(f"{where}: the inter-token latency {request.itl_ms!r} ms is negative")
    if request.output_tokens < 0:
        raise launch_failed(f"{where}: the output tokens {request.output_tokens:g} are negative")
    if request.end_s < request.start_s:
        raise launch_failed(f"{where}: the request ends before it starts")
    return request


def serving_sample(
    label: str, metric: str, value: float, *, n_inner: int = 1, reducer: str = REDUCER_TOOL_SUMMARY
) -> Sample:
    """Return one serving case of a level, with the unit and direction of its metric."""
    unit, better, kind = {
        METRIC_TTFT_MEDIAN: ("ms", "lower", "time"),
        METRIC_TTFT_P90: ("ms", "lower", "time"),
        METRIC_ITL_MEDIAN: ("ms", "lower", "time"),
        METRIC_OUTPUT_RATE: ("tokens/s", "higher", "rate"),
        METRIC_REQUEST_RATE: ("requests/s", "higher", "rate"),
        METRIC_TOKENS_PER_JOULE: ("tokens/J", "higher", "efficiency"),
    }[metric]
    return Sample(
        case=case_id(label, metric),
        metric=metric,
        unit=unit,
        better=better,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        value=value,
        n_inner=n_inner,
        reducer=reducer,
    )


def level_samples(
    label: str, requests: Sequence[Request], where: str, note: Callable[[str, str], None]
) -> tuple[list[Sample], float]:
    """Return the serving cases of one level from its successful requests, and its output tokens.

    No successful request is output that cannot be read. A level whose
    requests carry no inter-token latency, or whose first start is not
    before its last end, leaves out the cases it cannot give and says so.
    """
    if not requests:
        raise launch_failed(f"{where}: the level {label} has no successful request")
    out: list[Sample] = []
    ttft = [r.ttft_ms for r in requests]
    value, n, reducer = reduce(ttft)
    out.append(serving_sample(label, METRIC_TTFT_MEDIAN, value, n_inner=n, reducer=reducer))
    out.append(
        serving_sample(
            label, METRIC_TTFT_P90, quantile(ttft, 0.9), n_inner=len(ttft), reducer=REDUCER_P90
        )
    )
    itl = [r.itl_ms for r in requests if r.itl_ms is not None]
    if itl:
        value, n, reducer = reduce(itl)
        out.append(serving_sample(label, METRIC_ITL_MEDIAN, value, n_inner=n, reducer=reducer))
    else:
        note(
            NOTE_CASE_SKIPPED,
            f"{where}: no request of the level {label} has an inter-token latency, so "
            f"{case_id(label, METRIC_ITL_MEDIAN)} is missing",
        )
    tokens = sum(r.output_tokens for r in requests)
    span = max(r.end_s for r in requests) - min(r.start_s for r in requests)
    if span > 0:
        n = len(requests)
        out.append(
            serving_sample(
                label, METRIC_OUTPUT_RATE, tokens / span, n_inner=n, reducer=REDUCER_RATE
            )
        )
        out.append(
            serving_sample(label, METRIC_REQUEST_RATE, n / span, n_inner=n, reducer=REDUCER_RATE)
        )
    else:
        note(
            NOTE_CASE_SKIPPED,
            f"{where}: the requests of the level {label} span no time, so its rates are missing",
        )
    return out, tokens


def checked_summary(summary: Summary, where: str) -> Summary:
    """Return ``summary`` when none of its figures is negative, or refuse naming ``where``."""
    for metric, value in (
        (METRIC_TTFT_MEDIAN, summary.ttft_ms_median),
        (METRIC_TTFT_P90, summary.ttft_ms_p90),
        (METRIC_ITL_MEDIAN, summary.itl_ms_median),
        (METRIC_OUTPUT_RATE, summary.output_tokens_per_s),
        (METRIC_REQUEST_RATE, summary.requests_per_s),
        ("output_tokens", summary.output_tokens),
    ):
        if value is not None and value < 0:
            raise launch_failed(
                f"{where}: the tool's summary gives {metric} {value!r}, which is negative"
            )
    return summary


def summary_samples(label: str, summary: Summary) -> tuple[list[Sample], float | None]:
    """Return the serving cases of one level from a tool's own summary, and its output tokens."""
    figures = (
        (METRIC_TTFT_MEDIAN, summary.ttft_ms_median),
        (METRIC_TTFT_P90, summary.ttft_ms_p90),
        (METRIC_ITL_MEDIAN, summary.itl_ms_median),
        (METRIC_OUTPUT_RATE, summary.output_tokens_per_s),
        (METRIC_REQUEST_RATE, summary.requests_per_s),
    )
    out = [
        serving_sample(label, metric, value, n_inner=max(summary.count, 1))
        for metric, value in figures
        if value is not None
    ]
    return out, summary.output_tokens


def energy_sample(
    ctx: DriverContext, label: str, tokens: float | None, where: str
) -> Sample | None:
    """Return ``tokens_per_joule[gpu]`` of a level, or ``None`` when it cannot be given.

    It needs the GPU energy of the level's window. When the power reading
    holds more than one window of the label, as when a load runs twice
    against one server start, the driver cannot tell its own and gives none.
    """
    reading = ctx.energy
    if reading is None or tokens is None:
        return None
    windows = [w for w in reading.windows if w.label == label]
    if len(windows) > 1:
        ctx.note(
            NOTE_CASE_SKIPPED,
            f"{where}: the power reading holds {len(windows)} windows of the level {label}, so "
            f"{case_id(label, METRIC_TOKENS_PER_JOULE)} is missing",
        )
        return None
    if not windows or windows[0].energy_j is None or windows[0].energy_j <= 0:
        return None
    return serving_sample(
        label,
        METRIC_TOKENS_PER_JOULE,
        tokens / windows[0].energy_j,
        n_inner=max(windows[0].n_samples, 1),
        reducer=REDUCER_PER_JOULE,
    )


def serving_primary(samples: Iterable[Sample]) -> list[str]:
    """Return the default primary cases: ``PRIMARY_METRICS`` at the highest load level."""
    listed = list(samples)
    levels = [_level_of(s.case) for s in listed]
    known = [level for level in levels if level is not None]
    if not known:
        return []
    top = max(known)
    return [
        s.case
        for s, level in zip(listed, levels, strict=True)
        if level == top and s.metric in PRIMARY_METRICS
    ]


def _level_of(case: str) -> int | None:
    label, slash, _metric = case.partition("/")
    found = LEVEL_LABEL.fullmatch(label) if slash else None
    return int(found.group(2)) if found else None


def level_labels(ctx: DriverContext, driver: str) -> tuple[str, ...]:
    """Return the labels of the load levels, refusing a load without levels with ``E_CONFIG``."""
    labels = ctx.settings.labels()
    if not labels:
        raise Refusal(
            "E_CONFIG",
            f"the {driver} driver runs one load level after another; workload.levels lists none",
        )
    return labels


def file_label(ctx: DriverContext, driver: str) -> str:
    """Return the label of the one level a file side's result file holds.

    The file does not say which level of the load it is, so the load must
    list exactly one; otherwise the file is refused with ``E_USAGE``.
    """
    labels = ctx.settings.labels()
    if len(labels) != 1:
        raise Refusal(
            "E_USAGE",
            f"the {driver} driver reads a result file as one load level; give workload.levels "
            "exactly one level for it",
        )
    return labels[0]


def client_command(argv: Sequence[str], program: Sequence[str]) -> list[str]:
    """Return the command of a load step: the workload after ``program``, or the workload alone."""
    words = list(argv)
    if not words or words[0].startswith("-"):
        return [*program, *words]
    return words


def need_endpoint(ctx: DriverContext, driver: str) -> str:
    """Return the base address of the serving side, or refuse when there is none."""
    if ctx.endpoint is None:
        raise Refusal(
            "E_USAGE", f"the {driver} driver runs a load against a serving side; this side is none"
        )
    return ctx.endpoint.base_url


def level_value(label: str) -> int:
    """Return the number of a level label: 32 of ``c32``."""
    found = LEVEL_LABEL.fullmatch(label)
    if found is None:
        raise ValueError(f"not a load-level label: {label!r}")
    return int(found.group(2))


def optional_number(obj: Mapping[str, Any], key: str, where: str) -> float | None:
    """Return ``obj[key]`` as a number, ``None`` when it is absent or null."""
    value = obj.get(key)
    return None if value is None else number(value, f"{where}.{key}")


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------


class GuidellmDriver(ToolDriver):
    """The ``guidellm`` driver."""

    name = "guidellm"
    where: Literal["in_side", "client"] = "client"
    tool = "guidellm"
    output_file = "guidellm-<label>.json"
    tested_majors = TESTED_MAJORS
    real_run = True
    format_read = "guidellm's JSON report, one per load level"

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        """Return one ``guidellm run`` per load level against the serving side."""
        base_url = need_endpoint(ctx, self.name)
        labels = level_labels(ctx, self.name)
        command = client_command(argv, PROGRAM)
        option = own_option(command, OWN_OPTIONS)
        if option is not None:
            raise refuse_own_option(self.name, self.tool, option)
        if _metrics_sample(command):
            raise Refusal(
                "E_USAGE",
                f"the {self.name} driver reads the statistics of every request; remove "
                "sample_size from --metrics",
            )
        if own_option(command, (DATA_OPTION,)) is None:
            raise Refusal(
                "E_USAGE",
                f"the {self.name} driver needs the data guidellm sends: give --data in the "
                "workload, for example --data kind=synthetic_text,prompt_tokens=256,"
                "output_tokens=128",
            )
        backend = f"kind=openai_http,target={base_url}"
        model = ctx.endpoint.model_name if ctx.endpoint is not None else None
        if model:
            backend += f",model={model}"
        steps: list[Step] = []
        for label in labels:
            level = level_value(label)
            profile = (
                f"kind=concurrent,streams={level}"
                if label.startswith("c")
                else f"kind=constant,rate={level}"
            )
            words = [*command, "--backend", backend, "--profile", profile]
            if ctx.settings.level_duration_s is not None:
                seconds = f"{ctx.settings.level_duration_s:g}"
                words += ["--constraint", f"kind=max_duration,seconds={seconds}"]
            words += ["--seed", f"kind=static,value={ctx.seed}"]
            words += ["--output", f"kind=json,path={ctx.artifacts / (FILE_PREFIX + label)}.json"]
            if own_option(command, CONSOLE_OPTIONS) is None:
                words.append(CONSOLE_OPTIONS[0])
            steps.append(Step(label=label, argv=tuple(words)))
        return Invocation(steps=tuple(steps))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        """Return the serving cases of every level's report."""
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
        return unique(out, "guidellm reports")

    def _level(self, ctx: DriverContext, label: str, path: Path) -> list[Sample]:
        where = path.name
        benchmark = _benchmark(read_json(path, self.name), where)
        requests = _requests(benchmark, where)
        if requests:
            samples, tokens = level_samples(label, requests, where, ctx.note)
            total: float | None = tokens
        else:
            summary = _summary(benchmark, where)
            if summary.count == 0:
                raise launch_failed(f"{where}: the level {label} has no successful request")
            samples, total = summary_samples(label, checked_summary(summary, where))
        energy = energy_sample(ctx, label, total, where)
        return samples + ([energy] if energy is not None else [])

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return serving_primary(samples)

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None:
        """Return ``metadata.guidellm_version`` of the first level's report, or ``None``."""
        if ctx.result_file is not None:
            path = ctx.result_file
        else:
            labels = ctx.settings.labels()
            if not labels:
                return None
            path = artifacts / f"{FILE_PREFIX}{labels[0]}.json"
        try:
            doc = read_json(path, self.name)
        except Refusal:
            return None
        meta = doc.get("metadata") if isinstance(doc, dict) else None
        version = meta.get("guidellm_version") if isinstance(meta, dict) else None
        if not isinstance(version, str) or not version:
            return None
        return tool_version_of(self.tool, version, self.tested_majors)


def _metrics_sample(command: Sequence[str]) -> bool:
    """Say whether a ``--metrics`` option of the command asks for a sample of the requests."""
    for index, word in enumerate(command):
        value: str | None = None
        if word == METRICS_OPTION and index + 1 < len(command):
            value = command[index + 1]
        elif word.startswith(METRICS_OPTION + "="):
            value = word[len(METRICS_OPTION) + 1 :]
        if value is not None and "sample_size" in value:
            return True
    return False


def _benchmark(doc: Any, where: str) -> Mapping[str, Any]:
    benchmarks = items(member(mapping(doc, where), "benchmarks", where), f"{where}: benchmarks")
    if len(benchmarks) != 1:
        raise launch_failed(
            f"{where}: a report of one load level holds one benchmark, this one {len(benchmarks)}"
        )
    return mapping(benchmarks[0], f"{where}: benchmarks[0]")


def _requests(benchmark: Mapping[str, Any], where: str) -> list[Request]:
    """Return the successful requests of a benchmark; none when the report keeps none."""
    held = benchmark.get("requests")
    if held is None:
        return []
    successful = mapping(held, f"{where}: requests").get("successful")
    if successful is None:
        return []
    out: list[Request] = []
    for index, raw in enumerate(items(successful, f"{where}: requests.successful")):
        at = f"{where}: requests.successful[{index}]"
        record = mapping(raw, at)
        request = Request(
            ttft_ms=number(
                member(record, "time_to_first_token_ms", at), f"{at}.time_to_first_token_ms"
            ),
            itl_ms=optional_number(record, "inter_token_latency_ms", at),
            output_tokens=count(member(record, "output_tokens", at), f"{at}.output_tokens"),
            start_s=number(member(record, "request_start_time", at), f"{at}.request_start_time"),
            end_s=number(member(record, "request_end_time", at), f"{at}.request_end_time"),
        )
        out.append(checked(request, at))
    return out


def _summary(benchmark: Mapping[str, Any], where: str) -> Summary:
    """Return a benchmark as guidellm's own summary gives it."""
    metrics = mapping(member(benchmark, "metrics", where), f"{where}: metrics")

    def stats(name: str) -> Mapping[str, Any] | None:
        entry = metrics.get(name)
        if entry is None:
            return None
        found = mapping(entry, f"{where}: metrics.{name}").get("successful")
        return None if found is None else mapping(found, f"{where}: metrics.{name}.successful")

    def figure(name: str, key: str) -> float | None:
        found = stats(name)
        return None if found is None else optional_number(found, key, f"{where}: metrics.{name}")

    ttft = stats("time_to_first_token_ms")
    if ttft is None:
        raise launch_failed(f"{where}: metrics has no time_to_first_token_ms")
    seen = count(member(ttft, "count", f"{where}: metrics"), f"{where}: metrics.count")
    percentiles = ttft.get("percentiles")
    p90 = (
        optional_number(
            mapping(percentiles, f"{where}: percentiles"), "p90", f"{where}: percentiles"
        )
        if percentiles is not None
        else None
    )
    itl = stats("inter_token_latency_ms")
    itl_median = figure("inter_token_latency_ms", "median")
    if itl is not None and itl.get("count") == 0:
        itl_median = None
    return Summary(
        count=seen,
        ttft_ms_median=optional_number(ttft, "median", f"{where}: metrics"),
        ttft_ms_p90=p90,
        itl_ms_median=itl_median,
        output_tokens_per_s=figure("output_tokens_per_second", "mean"),
        requests_per_s=figure("requests_per_second", "mean"),
        output_tokens=figure("output_token_count", "total_sum"),
    )
