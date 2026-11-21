# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The guidellm driver: one guidellm run per load level, the serving cases of its reports."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import (
    REDUCER_IDENTITY,
    REDUCER_MEDIAN,
    REDUCER_TOOL_SUMMARY,
    DriverContext,
    Endpoint,
    EnergyReading,
    EnergyWindow,
    Sample,
    ToolVersion,
)
from pairbench.drivers import guidellm
from pairbench.drivers.guidellm import GuidellmDriver
from pairbench.errors import Refusal
from pairbench.model import LoadSettings

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "serving" / "guidellm"
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
DATA = ("--data", "kind=synthetic_text,prompt_tokens=8,output_tokens=8")
JOULES = 64.0
WINDOW_SAMPLES = 10

# The figures of the fixture levels, from the fixture files without the
# driver: plain medians, the linear 90th percentile, and the tokens and
# requests over the time from the first start to the last end.
C2_RECORDS = 40
C2 = {
    "c2/ttft_ms_median": 2.2635459899902344,
    "c2/ttft_ms_p90": 2.774930000305176,
    "c2/itl_ms_median": 0.5327963059948337,
    "c2/output_tokens_per_s": 2873.7120693881966,
    "c2/requests_per_s": 89.80350216838114,
}
C2_TOKENS = 1280
R2_RECORDS = 20
R2 = {
    "r2/ttft_ms_median": 2.54058837890625,
    "r2/ttft_ms_p90": 2.7689933776855473,
    "r2/itl_ms_median": 0.465439211937689,
    "r2/output_tokens_per_s": 67.2141398268573,
    "r2/requests_per_s": 2.100441869589291,
}
# The c1 report keeps no request, only guidellm's own summary of all of them.
C1_COUNT = 482
C1 = {
    "c1/ttft_ms_median": 3.7527084350585938,
    "c1/ttft_ms_p90": 9.718894958496094,
    "c1/itl_ms_median": 0.3514982038928616,
    "c1/output_tokens_per_s": 1541.5075342427378,
    "c1/requests_per_s": 48.1,
}
C1_TOKENS = 15424.0
UNITS = {
    "ttft_ms_median": ("ms", "lower", "time"),
    "ttft_ms_p90": ("ms", "lower", "time"),
    "itl_ms_median": ("ms", "lower", "time"),
    "output_tokens_per_s": ("tokens/s", "higher", "rate"),
    "requests_per_s": ("requests/s", "higher", "rate"),
    "tokens_per_joule[gpu]": ("tokens/J", "higher", "efficiency"),
}


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


def write_report(folder: Path, label: str, benchmarks: list[Any]) -> Path:
    path = folder / f"guidellm-{label}.json"
    path.write_text(json.dumps({"benchmarks": benchmarks}), encoding="utf-8")
    return path


def request(ttft: Any, itl: Any, tokens: Any, start: float, end: float) -> dict[str, Any]:
    return {
        "time_to_first_token_ms": ttft,
        "inter_token_latency_ms": itl,
        "output_tokens": tokens,
        "request_start_time": start,
        "request_end_time": end,
    }


# --- prepare ---------------------------------------------------------------


def test_prepare_gives_one_run_per_level_with_the_driver_options(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    ctx = serving_ctx(make_ctx, levels=(1, 4), duration=30.0)
    steps = GuidellmDriver().prepare(ctx, list(DATA)).steps
    assert [s.label for s in steps] == ["c1", "c4"]
    assert steps[0].argv == (
        "guidellm",
        "run",
        *DATA,
        "--backend",
        f"kind=openai_http,target={URL},model={MODEL}",
        "--profile",
        "kind=concurrent,streams=1",
        "--constraint",
        "kind=max_duration,seconds=30",
        "--seed",
        "kind=static,value=1234",
        "--output",
        f"kind=json,path={tmp_path}/guidellm-c1.json",
        "--disable-console-interactive",
    )
    assert steps[1].argv[steps[1].argv.index("--profile") + 1] == "kind=concurrent,streams=4"
    assert steps[1].argv[steps[1].argv.index("--output") + 1] == (
        f"kind=json,path={tmp_path}/guidellm-c4.json"
    )


def test_a_rate_level_runs_at_a_constant_rate_without_a_constraint_or_model(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), kind="rate", endpoint=Endpoint(base_url=URL))
    (step,) = GuidellmDriver().prepare(ctx, list(DATA)).steps
    assert step.label == "r2"
    assert step.argv == (
        "guidellm",
        "run",
        *DATA,
        "--backend",
        f"kind=openai_http,target={URL}",
        "--profile",
        "kind=constant,rate=2",
        "--seed",
        "kind=static,value=1234",
        "--output",
        f"kind=json,path={tmp_path}/guidellm-r2.json",
        "--disable-console-interactive",
    )


def test_a_level_duration_with_a_fraction_keeps_the_fraction(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1,), duration=2.5)
    (step,) = GuidellmDriver().prepare(ctx, list(DATA)).steps
    assert "kind=max_duration,seconds=2.5" in step.argv


def test_the_seed_of_the_run_is_passed(make_ctx: MakeCtx) -> None:
    ctx = dataclasses.replace(serving_ctx(make_ctx, levels=(1,)), seed=7)
    (step,) = GuidellmDriver().prepare(ctx, list(DATA)).steps
    assert step.argv[step.argv.index("--seed") + 1] == "kind=static,value=7"


def test_a_whole_command_is_kept_and_a_console_option_is_not_doubled(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1,))
    argv = ["/made-up/guidellm", "run", *DATA, "--disable-progress"]
    (step,) = GuidellmDriver().prepare(ctx, argv).steps
    assert step.argv[:5] == ("/made-up/guidellm", "run", *DATA, "--disable-progress")
    assert "--disable-console-interactive" not in step.argv


@pytest.mark.parametrize(
    "option", ["--backend", "--profile", "--output", "--seed", "--override", "--output=x"]
)
def test_a_workload_with_an_option_the_driver_adds_is_refused(
    make_ctx: MakeCtx, option: str
) -> None:
    argv = [*DATA, option] if "=" in option else [*DATA, option, "x"]
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().prepare(serving_ctx(make_ctx), argv)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert option.partition("=")[0] in caught.value.message


@pytest.mark.parametrize(
    "metrics", [["--metrics", "kind=stats,sample_size=4"], ["--metrics=sample_size=4"]]
)
def test_a_sample_of_the_requests_is_refused(make_ctx: MakeCtx, metrics: list[str]) -> None:
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().prepare(serving_ctx(make_ctx), [*DATA, *metrics])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "sample_size" in caught.value.message


def test_a_workload_without_data_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().prepare(serving_ctx(make_ctx), [])
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "--data" in caught.value.message


def test_a_load_without_levels_is_refused_as_a_config_error(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().prepare(serving_ctx(make_ctx, levels=()), list(DATA))
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)


def test_a_side_that_serves_nothing_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().prepare(serving_ctx(make_ctx, endpoint=None), list(DATA))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


# --- read: the fixtures ----------------------------------------------------


def test_the_records_of_a_concurrency_level_give_the_serving_cases(make_ctx: MakeCtx) -> None:
    samples = GuidellmDriver().read(serving_ctx(make_ctx, levels=(2,)), FIXTURES)
    assert values(samples) == pytest.approx(C2, rel=1e-12)
    cases = by_case(samples)
    assert cases["c2/ttft_ms_median"].n_inner == C2_RECORDS
    assert cases["c2/ttft_ms_median"].reducer == REDUCER_MEDIAN
    assert cases["c2/ttft_ms_p90"].reducer == guidellm.REDUCER_P90
    assert cases["c2/output_tokens_per_s"].reducer == guidellm.REDUCER_RATE
    assert {s.n_inner for s in samples} == {C2_RECORDS}


def test_the_records_of_a_rate_level_give_the_serving_cases(make_ctx: MakeCtx) -> None:
    samples = GuidellmDriver().read(serving_ctx(make_ctx, levels=(2,), kind="rate"), FIXTURES)
    assert values(samples) == pytest.approx(R2, rel=1e-12)
    assert {s.n_inner for s in samples} == {R2_RECORDS}


def test_every_case_has_the_unit_and_direction_of_its_metric(make_ctx: MakeCtx) -> None:
    samples = GuidellmDriver().read(serving_ctx(make_ctx, levels=(2,)), FIXTURES)
    for sample in samples:
        assert (sample.unit, sample.better, sample.kind) == UNITS[sample.metric]


def test_a_report_without_records_falls_back_to_the_tools_summary(make_ctx: MakeCtx) -> None:
    samples = GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), FIXTURES)
    assert values(samples) == C1
    assert {s.reducer for s in samples} == {REDUCER_TOOL_SUMMARY}
    assert {s.n_inner for s in samples} == {C1_COUNT}


def test_levels_are_read_in_order_and_the_highest_gives_the_primary_cases(
    make_ctx: MakeCtx,
) -> None:
    driver = GuidellmDriver()
    ctx = serving_ctx(make_ctx, levels=(1, 2), energy=reading(("c2", JOULES)))
    samples = driver.read(ctx, FIXTURES)
    assert [s.case for s in samples][:5] == list(C1)
    assert driver.default_primary(samples) == [
        "c2/ttft_ms_median",
        "c2/itl_ms_median",
        "c2/output_tokens_per_s",
        "c2/tokens_per_joule[gpu]",
    ]


def test_a_result_file_is_read_as_the_one_level_of_the_load(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), kind="rate", result_file=FIXTURES / "guidellm-r2.json")
    samples = GuidellmDriver().read(ctx, Path("/made-up/elsewhere"))
    assert values(samples) == pytest.approx(R2, rel=1e-12)


def test_a_result_file_with_more_than_one_level_is_refused(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1, 2), result_file=FIXTURES / "guidellm-c2.json")
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(ctx, FIXTURES)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


# --- read: energy ----------------------------------------------------------


def test_the_energy_of_a_level_gives_tokens_per_joule(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), energy=reading(("c2", JOULES)))
    sample = by_case(GuidellmDriver().read(ctx, FIXTURES))["c2/tokens_per_joule[gpu]"]
    assert sample.value == C2_TOKENS / JOULES
    assert (sample.n_inner, sample.reducer) == (WINDOW_SAMPLES, guidellm.REDUCER_PER_JOULE)
    assert (sample.unit, sample.better, sample.kind) == ("tokens/J", "higher", "efficiency")


def test_the_summary_fallback_takes_its_tokens_from_the_summary(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1,), energy=reading(("c1", JOULES)))
    sample = by_case(GuidellmDriver().read(ctx, FIXTURES))["c1/tokens_per_joule[gpu]"]
    assert sample.value == C1_TOKENS / JOULES


def test_each_level_takes_the_energy_of_its_own_window(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(1, 2), energy=reading(("c1", 32.0), ("c2", JOULES)))
    got = values(GuidellmDriver().read(ctx, FIXTURES))
    assert got["c1/tokens_per_joule[gpu]"] == C1_TOKENS / 32.0
    assert got["c2/tokens_per_joule[gpu]"] == C2_TOKENS / JOULES


@pytest.mark.parametrize("joules", [None, 0.0])
def test_a_window_without_energy_gives_no_case(make_ctx: MakeCtx, joules: float | None) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), energy=reading(("c2", joules)))
    assert "c2/tokens_per_joule[gpu]" not in values(GuidellmDriver().read(ctx, FIXTURES))


def test_two_windows_of_one_level_give_no_case_and_a_note(make_ctx: MakeCtx, notes: Any) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), energy=reading(("c2", JOULES), ("c2", JOULES)))
    assert "c2/tokens_per_joule[gpu]" not in values(GuidellmDriver().read(ctx, FIXTURES))
    assert notes.seen == [
        (
            "case_skipped",
            "guidellm-c2.json: the power reading holds 2 windows of the level c2, so "
            "c2/tokens_per_joule[gpu] is missing",
        )
    ]


# --- read: reports that cannot be read -------------------------------------


def test_a_missing_report_is_a_failed_launch(make_ctx: MakeCtx, tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)


def test_a_report_of_two_benchmarks_is_a_failed_launch(make_ctx: MakeCtx, tmp_path: Path) -> None:
    write_report(tmp_path, "c1", [{}, {}])
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert "one benchmark, this one 2" in caught.value.message


def test_a_request_without_a_time_to_first_token_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    write_report(tmp_path, "c1", [{"requests": {"successful": [request(None, 1.0, 4, 0.0, 1.0)]}}])
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)


@pytest.mark.parametrize(
    ("held", "message"),
    [
        (
            request(-2.0, 0.5, 4, 0.0, 1.0),
            "guidellm-c1.json: requests.successful[0]: the time to first token -2.0 ms is negative",
        ),
        (
            request(2.0, -0.5, 4, 0.0, 1.0),
            "guidellm-c1.json: requests.successful[0]: the inter-token latency -0.5 ms is negative",
        ),
        (
            request(2.0, 0.5, 4, 3.0, 1.0),
            "guidellm-c1.json: requests.successful[0]: the request ends before it starts",
        ),
        (
            request(2.0, 0.5, 4, float("nan"), 1.0),
            "guidellm-c1.json: requests.successful[0]: the start or end of the request is not "
            "a finite number",
        ),
    ],
    ids=["negative-ttft", "negative-itl", "end-before-start", "start-not-finite"],
)
def test_a_request_that_cannot_have_happened_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path, held: dict[str, Any], message: str
) -> None:
    # The first request is fine; the second widens the span so only a check per request sees it.
    good = request(2.0, 0.5, 4, 0.0, 10.0)
    write_report(tmp_path, "c1", [{"requests": {"successful": [held, good]}}])
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_a_summary_of_no_successful_request_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    summary = {"time_to_first_token_ms": {"successful": {"count": 0}}}
    write_report(tmp_path, "c1", [{"requests": {"successful": []}, "metrics": summary}])
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert "no successful request" in caught.value.message


@pytest.mark.parametrize(
    ("metric", "key", "message"),
    [
        (
            "time_to_first_token_ms",
            "median",
            "guidellm-c1.json: the tool's summary gives ttft_ms_median -2.0, which is negative",
        ),
        (
            "output_tokens_per_second",
            "mean",
            "guidellm-c1.json: the tool's summary gives output_tokens_per_s -2.0, which is "
            "negative",
        ),
    ],
)
def test_a_negative_figure_of_the_summary_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path, metric: str, key: str, message: str
) -> None:
    summary: dict[str, Any] = {
        "time_to_first_token_ms": {"successful": {"count": 4, "median": 2.0}},
        "output_tokens_per_second": {"successful": {"mean": 2.0}},
    }
    summary[metric]["successful"][key] = -2.0
    write_report(tmp_path, "c1", [{"metrics": summary}])
    with pytest.raises(Refusal) as caught:
        GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert caught.value.message == message


def test_requests_without_inter_token_latency_leave_that_case_out_with_a_note(
    make_ctx: MakeCtx, notes: Any, tmp_path: Path
) -> None:
    held = [request(2.0, None, 1, 0.0, 1.0), request(4.0, None, 1, 1.0, 2.0)]
    write_report(tmp_path, "c1", [{"requests": {"successful": held}}])
    got = GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert values(got) == {
        "c1/ttft_ms_median": 3.0,
        "c1/ttft_ms_p90": 3.8,
        "c1/output_tokens_per_s": 1.0,
        "c1/requests_per_s": 1.0,
    }
    assert notes.seen == [
        (
            "case_skipped",
            "guidellm-c1.json: no request of the level c1 has an inter-token latency, so "
            "c1/itl_ms_median is missing",
        )
    ]


def test_one_request_is_taken_as_it_is(make_ctx: MakeCtx, tmp_path: Path) -> None:
    write_report(tmp_path, "c1", [{"requests": {"successful": [request(2.0, 0.5, 8, 0.0, 2.0)]}}])
    got = by_case(GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got["c1/ttft_ms_median"].reducer == REDUCER_IDENTITY
    assert got["c1/output_tokens_per_s"].value == 4.0


def test_requests_that_span_no_time_leave_the_rates_out_with_a_note(
    make_ctx: MakeCtx, notes: Any, tmp_path: Path
) -> None:
    write_report(tmp_path, "c1", [{"requests": {"successful": [request(2.0, 0.5, 8, 5.0, 5.0)]}}])
    got = values(GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert set(got) == {"c1/ttft_ms_median", "c1/ttft_ms_p90", "c1/itl_ms_median"}
    assert notes.seen == [
        (
            "case_skipped",
            "guidellm-c1.json: the requests of the level c1 span no time, so its rates are missing",
        )
    ]


def test_a_summary_without_inter_token_latency_leaves_that_case_out(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    summary = {
        "time_to_first_token_ms": {"successful": {"count": 3, "median": 2.0}},
        "inter_token_latency_ms": {"successful": {"count": 0, "median": 0.0}},
    }
    write_report(tmp_path, "c1", [{"metrics": summary}])
    got = values(GuidellmDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got == {"c1/ttft_ms_median": 2.0}


# --- version, doctor, registry, fixtures -----------------------------------


def test_the_version_is_the_one_the_report_names(make_ctx: MakeCtx) -> None:
    got = GuidellmDriver().tool_version(serving_ctx(make_ctx, levels=(2,)), FIXTURES)
    assert got == ToolVersion(tool="guidellm", version="0.8.1", tested=True)


def test_no_report_gives_no_version(make_ctx: MakeCtx, tmp_path: Path) -> None:
    assert GuidellmDriver().tool_version(serving_ctx(make_ctx), tmp_path) is None


def test_the_driver_has_a_real_run_and_runs_on_the_client() -> None:
    driver = registry.driver("guidellm")
    assert isinstance(driver, GuidellmDriver)
    assert driver.where == "client"
    assert driver.doctor().status == "ok"


@pytest.mark.parametrize(
    "fixture",
    sorted(p for p in FIXTURES.glob("*.json") if not p.name.endswith(SIDECAR)),
    ids=lambda p: p.name,
)
def test_every_fixture_comes_from_a_real_run_and_says_how(fixture: Path) -> None:
    doc = json.loads(fixture.with_name(fixture.name + SIDECAR).read_text(encoding="utf-8"))
    assert doc["generator"] == GENERATOR
    assert (doc["tool"], doc["version"], doc["synthetic"]) == ("guidellm", "0.8.1", False)
    assert doc["image"] == SERVER_IMAGE
    assert doc["command"].startswith("guidellm run ")
