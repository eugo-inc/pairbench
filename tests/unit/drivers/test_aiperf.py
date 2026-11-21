# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The aiperf driver: one aiperf profile per load level, the serving cases of its records."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import (
    REDUCER_MEDIAN,
    REDUCER_TOOL_SUMMARY,
    DriverContext,
    Endpoint,
    EnergyReading,
    EnergyWindow,
    Sample,
    ToolVersion,
)
from pairbench.drivers import aiperf, guidellm
from pairbench.drivers.aiperf import AiperfDriver
from pairbench.errors import Refusal
from pairbench.model import LoadSettings

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "serving" / "aiperf"
SIDECAR = ".provenance.json"
GENERATOR = "tests/fixtures/_gen/serving.py"
# The public server image of the real runs, pinned by its digest.
SERVER_IMAGE = (
    "ghcr.io/ggml-org/llama.cpp:full"
    "@sha256:5bee33d877070ee246edb2f3442bcea4942d01d602f1abf479183c49a0f2ba7c"
)
URL = "http://127.0.0.1:8000"
MODEL = "made-up-model"
ENDPOINT = Endpoint(base_url=URL, model_name=MODEL)
WORKLOAD = ("--tokenizer", "made-up-tokenizer")
JOULES = 64.0
WINDOW_SAMPLES = 10

# The figures of the fixture levels, from the fixture files without the
# driver: plain medians, the linear 90th percentile, and the tokens and
# requests over the time from the first start to the last end.
C2_RECORDS = 40
C2 = {
    "c2/ttft_ms_median": 2.762336,
    "c2/ttft_ms_p90": 4.9525625,
    "c2/itl_ms_median": 0.6887811510344828,
    "c2/output_tokens_per_s": 1947.9125361837368,
    "c2/requests_per_s": 67.28540712206345,
}
C2_TOKENS = 1158
R2_RECORDS = 19
R2 = {
    "r2/ttft_ms_median": 4.233559,
    "r2/ttft_ms_p90": 4.8918295999999994,
    "r2/itl_ms_median": 0.480589724137931,
    "r2/output_tokens_per_s": 61.64410366227868,
    "r2/requests_per_s": 2.1065431107613217,
}
# The r2 folder keeps every record of the level, so aiperf's own p50 and p90
# of the time to first token, in its summary beside them, are the same figures.
R2_TOOL_TTFT_P50 = 4.233559
R2_TOOL_TTFT_P90 = 4.8918295999999994
# The c1 folder keeps no records, only aiperf's own summary of all of them.
C1_COUNT = 447
C1 = {
    "c1/ttft_ms_median": 2.4680299999999997,
    "c1/ttft_ms_p90": 9.534238800000013,
    "c1/itl_ms_median": 0.42838376666666667,
    "c1/output_tokens_per_s": 1309.833563566354,
    "c1/requests_per_s": 44.67045112643322,
}
C1_TOKENS = 13107.0


def serving_ctx(
    make_ctx: MakeCtx,
    *,
    levels: tuple[int, ...] = (1, 2),
    kind: str = "concurrency",
    duration: float | None = None,
    endpoint: Endpoint | None = ENDPOINT,
    energy: EnergyReading | None = None,
    result_file: Path | None = None,
) -> DriverContext:
    ctx = make_ctx(kind="serve" if result_file is None else "file", result_file=result_file)
    return dataclasses.replace(
        ctx,
        settings=LoadSettings(levels=levels, level_duration_s=duration, level_kind=kind),  # type: ignore[arg-type]
        endpoint=endpoint,
        energy=energy,
    )


def reading(*windows: tuple[str, float | None]) -> EnergyReading:
    return EnergyReading(
        source="made-up-sampler",
        sampler_ok=True,
        query_errors=0,
        windows=tuple(
            EnergyWindow(
                label=label,
                start_s=0.0,
                end_s=1.0,
                energy_j=joules,
                mean_power_w=joules,
                n_samples=WINDOW_SAMPLES,
            )
            for label, joules in windows
        ),
    )


def values(samples: list[Sample]) -> dict[str, float]:
    return {s.case: s.value for s in samples}


def by_case(samples: list[Sample]) -> dict[str, Sample]:
    return {s.case: s for s in samples}


def record(
    ttft: Any = 2.0,
    *,
    unit: str = "ms",
    itl: float | None = 0.5,
    tokens: dict[str, Any] | None = None,
    start_ns: int = 0,
    end_ns: int = 1_000_000_000,
    phase: str = "profiling",
    cancelled: bool = False,
    error: Any = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if ttft is not None:
        metrics["time_to_first_token"] = {"value": ttft, "unit": unit}
    if itl is not None:
        metrics["inter_token_latency"] = {"value": itl, "unit": "ms"}
    metrics.update(
        tokens if tokens is not None else {"output_sequence_length": {"value": 4, "unit": "tokens"}}
    )
    return {
        "metadata": {
            "benchmark_phase": phase,
            "was_cancelled": cancelled,
            "request_start_ns": start_ns,
            "request_end_ns": end_ns,
        },
        "metrics": metrics,
        "error": error,
    }


def write_records(folder: Path, label: str, lines: list[Any]) -> Path:
    level = folder / f"aiperf-{label}"
    level.mkdir(parents=True, exist_ok=True)
    path = level / "profile_export.jsonl"
    path.write_text(
        "".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines),
        encoding="utf-8",
    )
    return path


# --- prepare ---------------------------------------------------------------


def test_prepare_gives_one_profile_per_level_with_the_driver_options(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    ctx = serving_ctx(make_ctx, levels=(1, 4), duration=30.0)
    steps = AiperfDriver().prepare(ctx, list(WORKLOAD)).steps
    assert [s.label for s in steps] == ["c1", "c4"]
    assert steps[0].argv == (
        "aiperf",
        "profile",
        *WORKLOAD,
        "--url",
        URL,
        "--model",
        MODEL,
        "--endpoint-type",
        "chat",
        "--streaming",
        "--ui",
        "none",
        "--concurrency",
        "1",
        "--benchmark-duration",
        "30",
        "--random-seed",
        "1234",
        "--artifact-dir",
        f"{tmp_path}/aiperf-c1",
        "--export-level",
        "records",
    )
    assert steps[1].argv[steps[1].argv.index("--concurrency") + 1] == "4"
    assert steps[1].argv[steps[1].argv.index("--artifact-dir") + 1] == f"{tmp_path}/aiperf-c4"


def test_a_rate_level_runs_at_a_request_rate_without_a_duration_or_model(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), kind="rate", endpoint=Endpoint(base_url=URL))
    (step,) = AiperfDriver().prepare(ctx, []).steps
    assert step.label == "r2"
    assert step.argv == (
        "aiperf",
        "profile",
        "--url",
        URL,
        "--endpoint-type",
        "chat",
        "--streaming",
        "--ui",
        "none",
        "--request-rate",
        "2",
        "--random-seed",
        "1234",
        "--artifact-dir",
        f"{tmp_path}/aiperf-r2",
        "--export-level",
        "records",
    )


@pytest.mark.parametrize(
    ("given", "left_out"),
    [
        (["-m", "x"], ["--model"]),
        (["--model-names", "x"], ["--model"]),
        (["--endpoint-type", "completions"], ["chat"]),
        (["--no-streaming"], ["--streaming"]),
        (["--ui-type", "simple"], ["--ui"]),
    ],
)
def test_a_choice_of_the_workload_is_kept(
    make_ctx: MakeCtx, given: list[str], left_out: list[str]
) -> None:
    (step,) = AiperfDriver().prepare(serving_ctx(make_ctx, levels=(1,)), given).steps
    assert step.argv[2 : 2 + len(given)] == tuple(given)
    for word in left_out:
        assert word not in step.argv[2 + len(given) :]


def test_the_seed_of_the_run_is_passed(make_ctx: MakeCtx) -> None:
    ctx = dataclasses.replace(serving_ctx(make_ctx, levels=(1,)), seed=7)
    (step,) = AiperfDriver().prepare(ctx, []).steps
    assert step.argv[step.argv.index("--random-seed") + 1] == "7"


@pytest.mark.parametrize("option", [*aiperf.OWN_OPTIONS, "--url=x"])
def test_a_workload_with_an_option_the_driver_adds_is_refused(
    make_ctx: MakeCtx, option: str
) -> None:
    argv = [option] if "=" in option else [option, "x"]
    with pytest.raises(Refusal) as caught:
        AiperfDriver().prepare(serving_ctx(make_ctx), argv)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert option.partition("=")[0] in caught.value.message


def test_a_load_without_levels_is_refused_as_a_config_error(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        AiperfDriver().prepare(serving_ctx(make_ctx, levels=()), [])
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)


def test_a_side_that_serves_nothing_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        AiperfDriver().prepare(serving_ctx(make_ctx, endpoint=None), [])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


# --- read: the fixtures ----------------------------------------------------


def test_the_records_of_a_concurrency_level_give_the_serving_cases(make_ctx: MakeCtx) -> None:
    samples = AiperfDriver().read(serving_ctx(make_ctx, levels=(2,)), FIXTURES)
    assert values(samples) == pytest.approx(C2, rel=1e-12)
    assert {s.n_inner for s in samples} == {C2_RECORDS}
    assert by_case(samples)["c2/ttft_ms_median"].reducer == REDUCER_MEDIAN


def test_the_records_of_a_rate_level_give_the_serving_cases(make_ctx: MakeCtx) -> None:
    samples = AiperfDriver().read(serving_ctx(make_ctx, levels=(2,), kind="rate"), FIXTURES)
    assert values(samples) == pytest.approx(R2, rel=1e-12)
    assert {s.n_inner for s in samples} == {R2_RECORDS}


def test_all_records_of_a_level_give_the_tools_own_median_and_p90(make_ctx: MakeCtx) -> None:
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(2,), kind="rate"), FIXTURES))
    assert got["r2/ttft_ms_median"] == pytest.approx(R2_TOOL_TTFT_P50, rel=1e-12)
    assert got["r2/ttft_ms_p90"] == pytest.approx(R2_TOOL_TTFT_P90, rel=1e-12)


def test_a_level_without_records_falls_back_to_the_tools_summary(make_ctx: MakeCtx) -> None:
    samples = AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), FIXTURES)
    assert values(samples) == C1
    assert {s.reducer for s in samples} == {REDUCER_TOOL_SUMMARY}
    assert {s.n_inner for s in samples} == {C1_COUNT}


def test_the_highest_level_gives_the_primary_cases(make_ctx: MakeCtx) -> None:
    driver = AiperfDriver()
    samples = driver.read(serving_ctx(make_ctx, levels=(1, 2)), FIXTURES)
    assert driver.default_primary(samples) == [
        "c2/ttft_ms_median",
        "c2/itl_ms_median",
        "c2/output_tokens_per_s",
    ]


def test_a_result_file_is_read_as_the_one_level_of_the_load(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(
        make_ctx,
        levels=(2,),
        kind="rate",
        result_file=FIXTURES / "aiperf-r2" / "profile_export.jsonl",
    )
    samples = AiperfDriver().read(ctx, Path("/made-up/elsewhere"))
    assert values(samples) == pytest.approx(R2, rel=1e-12)


# --- read: energy ----------------------------------------------------------


def test_the_energy_of_a_level_gives_tokens_per_joule(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), energy=reading(("c2", JOULES)))
    sample = by_case(AiperfDriver().read(ctx, FIXTURES))["c2/tokens_per_joule[gpu]"]
    assert sample.value == C2_TOKENS / JOULES
    assert (sample.n_inner, sample.reducer) == (WINDOW_SAMPLES, guidellm.REDUCER_PER_JOULE)


def test_the_summary_fallback_takes_its_tokens_from_the_summary(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1,), energy=reading(("c1", JOULES)))
    sample = by_case(AiperfDriver().read(ctx, FIXTURES))["c1/tokens_per_joule[gpu]"]
    assert sample.value == C1_TOKENS / JOULES


def test_two_windows_of_one_level_give_no_case_and_a_note(make_ctx: MakeCtx, notes: Any) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), energy=reading(("c2", JOULES), ("c2", JOULES)))
    assert "c2/tokens_per_joule[gpu]" not in values(AiperfDriver().read(ctx, FIXTURES))
    assert notes.seen == [
        (
            "case_skipped",
            "aiperf-c2: the power reading holds 2 windows of the level c2, so "
            "c2/tokens_per_joule[gpu] is missing",
        )
    ]


# --- read: which records count ---------------------------------------------


def test_only_finished_profiling_records_without_an_error_count(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    write_records(
        tmp_path,
        "c1",
        [
            record(2.0),
            record(4.0, start_ns=1_000_000_000, end_ns=2_000_000_000),
            record(100.0, phase="warmup"),
            record(100.0, cancelled=True),
            record(100.0, error={"code": 500, "message": "x"}),
            "",
        ],
    )
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got == {
        "c1/ttft_ms_median": 3.0,
        "c1/ttft_ms_p90": 3.8,
        "c1/itl_ms_median": 0.5,
        "c1/output_tokens_per_s": 4.0,
        "c1/requests_per_s": 1.0,
    }


@pytest.mark.parametrize(("ttft", "unit"), [(0.002, "s"), (2000.0, "us"), (2_000_000, "ns")])
def test_a_time_is_converted_from_the_unit_the_record_names(
    make_ctx: MakeCtx, tmp_path: Path, ttft: float, unit: str
) -> None:
    write_records(tmp_path, "c1", [record(ttft, unit=unit)])
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got["c1/ttft_ms_median"] == pytest.approx(2.0, rel=1e-12)


def test_the_span_of_a_level_is_taken_in_whole_nanoseconds(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    # Two requests of 4 tokens over 500000003 ns, on a clock far from zero: 8 tokens
    # and 2 requests over 0.500000003 s. Taken as seconds since the clock's zero
    # first, the span would come out as 0.5 s.
    start = 1_700_000_000_123_456_789
    write_records(
        tmp_path,
        "c1",
        [
            record(start_ns=start, end_ns=start + 250_000_001),
            record(start_ns=start + 1, end_ns=start + 500_000_003),
        ],
    )
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got["c1/output_tokens_per_s"] == 15.999999904
    assert got["c1/requests_per_s"] == 3.999999976


def test_the_output_token_count_is_taken_without_a_sequence_length(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    tokens = {"output_token_count": {"value": 6, "unit": "tokens"}}
    write_records(tmp_path, "c1", [record(tokens=tokens)])
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got["c1/output_tokens_per_s"] == 6.0


def test_records_without_inter_token_latency_leave_that_case_out_with_a_note(
    make_ctx: MakeCtx, notes: Any, tmp_path: Path
) -> None:
    write_records(tmp_path, "c1", [record(itl=None)])
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert "c1/itl_ms_median" not in got
    assert notes.seen == [
        (
            "case_skipped",
            "aiperf-c1/profile_export.jsonl: no request of the level c1 has an inter-token "
            "latency, so c1/itl_ms_median is missing",
        )
    ]


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ("{not json", "is not valid JSON"),
        (record(None), "has no time_to_first_token"),
        (record(2.0, unit="tokens"), "not a unit of time"),
        (record(tokens={}), "has no output_sequence_length"),
        (record(phase="warmup"), "has no successful request"),
        (
            record(-2.0),
            "aiperf-c1/profile_export.jsonl line 1: the time to first token -2.0 ms is negative",
        ),
        (
            record(itl=-0.5),
            "aiperf-c1/profile_export.jsonl line 1: the inter-token latency -0.5 ms is negative",
        ),
        (
            record(tokens={"output_sequence_length": {"value": -4, "unit": "tokens"}}),
            "aiperf-c1/profile_export.jsonl line 1: the output tokens -4 are negative",
        ),
        (
            record(start_ns=5, end_ns=4),
            "aiperf-c1/profile_export.jsonl line 1: the request ends before it starts",
        ),
    ],
    ids=[
        "not-json",
        "no-ttft",
        "ttft-not-time",
        "no-tokens",
        "no-profiling-record",
        "negative-ttft",
        "negative-itl",
        "negative-tokens",
        "end-before-start",
    ],
)
def test_records_that_cannot_be_read_are_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path, line: Any, found: str
) -> None:
    write_records(tmp_path, "c1", [line])
    with pytest.raises(Refusal) as caught:
        AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert found in caught.value.message


def test_a_level_with_neither_file_is_a_failed_launch(make_ctx: MakeCtx, tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert "profile_export.jsonl" in caught.value.message


def test_a_summary_of_no_request_is_a_failed_launch(make_ctx: MakeCtx, tmp_path: Path) -> None:
    level = tmp_path / "aiperf-c1"
    level.mkdir()
    summary = {"time_to_first_token": {"unit": "ms", "count": 0}}
    (level / "profile_export_aiperf.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert "no successful request" in caught.value.message


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        (
            {"time_to_first_token": {"unit": "ms", "count": 4, "p50": -2.0}},
            "aiperf-c1/profile_export_aiperf.json: the tool's summary gives ttft_ms_median "
            "-2.0, which is negative",
        ),
        (
            {
                "time_to_first_token": {"unit": "ms", "count": 4, "p50": 2.0},
                "request_throughput": {"avg": -1.0},
            },
            "aiperf-c1/profile_export_aiperf.json: the tool's summary gives requests_per_s "
            "-1.0, which is negative",
        ),
        (
            {"time_to_first_token": {"unit": "ms", "count": float("inf"), "p50": 2.0}},
            "aiperf-c1/profile_export_aiperf.json: time_to_first_token.count is not a whole "
            "number of zero or more",
        ),
        (
            {"time_to_first_token": {"unit": "ms", "count": 2.5, "p50": 2.0}},
            "aiperf-c1/profile_export_aiperf.json: time_to_first_token.count is not a whole "
            "number of zero or more",
        ),
    ],
    ids=["negative-median", "negative-rate", "infinite-count", "fractional-count"],
)
def test_a_summary_that_cannot_be_read_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path, summary: dict[str, Any], message: str
) -> None:
    level = tmp_path / "aiperf-c1"
    level.mkdir()
    (level / "profile_export_aiperf.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_a_summary_time_in_seconds_is_converted(make_ctx: MakeCtx, tmp_path: Path) -> None:
    level = tmp_path / "aiperf-c1"
    level.mkdir()
    summary = {"time_to_first_token": {"unit": "s", "count": 3, "p50": 0.002}}
    (level / "profile_export_aiperf.json").write_text(json.dumps(summary), encoding="utf-8")
    got = values(AiperfDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got == {"c1/ttft_ms_median": pytest.approx(2.0, rel=1e-12)}


# --- version, doctor, registry, fixtures -----------------------------------


def test_the_version_is_the_one_the_summary_names(make_ctx: MakeCtx) -> None:
    got = AiperfDriver().tool_version(serving_ctx(make_ctx, levels=(2,)), FIXTURES)
    assert got == ToolVersion(tool="aiperf", version="0.13.0", tested=True)


def test_no_summary_gives_no_version(make_ctx: MakeCtx, tmp_path: Path) -> None:
    assert AiperfDriver().tool_version(serving_ctx(make_ctx), tmp_path) is None


def test_the_driver_has_a_real_run_and_runs_on_the_client() -> None:
    driver = registry.driver("aiperf")
    assert isinstance(driver, AiperfDriver)
    assert driver.where == "client"
    assert driver.doctor().status == "ok"


@pytest.mark.parametrize(
    "fixture",
    sorted(p for p in FIXTURES.rglob("profile_export*") if not p.name.endswith(SIDECAR)),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_every_fixture_comes_from_a_real_run_and_says_how(fixture: Path) -> None:
    doc = json.loads(fixture.with_name(fixture.name + SIDECAR).read_text(encoding="utf-8"))
    assert doc["generator"] == GENERATOR
    assert (doc["tool"], doc["version"], doc["synthetic"]) == ("aiperf", "0.13.0", False)
    assert doc["image"] == SERVER_IMAGE
    assert doc["command"].startswith("aiperf profile ")
