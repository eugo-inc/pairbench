# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The vllm-bench driver: one vllm bench serve per load level, the summary of its result file."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.api import (
    REDUCER_TOOL_SUMMARY,
    DriverContext,
    Endpoint,
    EnergyReading,
    EnergyWindow,
    Sample,
)
from pairbench.drivers import guidellm, vllm_bench
from pairbench.drivers.vllm_bench import VllmBenchDriver
from pairbench.errors import Refusal
from pairbench.model import LoadSettings

MakeCtx = Callable[..., DriverContext]
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "serving" / "vllm-bench"
SIDECAR = ".provenance.json"
GENERATOR = "tests/fixtures/_gen/serving.py"
URL = "http://127.0.0.1:8000"
MODEL = "made-up-model"
ENDPOINT = Endpoint(base_url=URL, model_name=MODEL)
WORKLOAD = ("--num-prompts", "32")
JOULES = 64.0
WINDOW_SAMPLES = 10

# The made-up result files, as their fields read.
COMPLETED = 32
C1 = {
    "c1/request_throughput": 2.0,
    "c1/output_throughput": 128.0,
    "c1/total_token_throughput": 384.0,
    "c1/mean_ttft_ms": 20.5,
    "c1/median_ttft_ms": 20.0,
    "c1/p99_ttft_ms": 40.0,
    "c1/mean_tpot_ms": 5.5,
    "c1/median_tpot_ms": 5.0,
    "c1/p99_tpot_ms": 10.0,
    "c1/mean_itl_ms": 5.5,
    "c1/median_itl_ms": 5.0,
    "c1/p99_itl_ms": 10.0,
}
C4 = {
    "c4/request_throughput": 8.0,
    "c4/output_throughput": 512.0,
    "c4/total_token_throughput": 1536.0,
    "c4/mean_ttft_ms": 80.5,
    "c4/median_ttft_ms": 80.0,
    "c4/p99_ttft_ms": 160.0,
    "c4/mean_tpot_ms": 20.5,
    "c4/median_tpot_ms": 20.0,
    "c4/p99_tpot_ms": 40.0,
    "c4/mean_itl_ms": 20.5,
    "c4/median_itl_ms": 20.0,
    "c4/p99_itl_ms": 40.0,
}
OUTPUT_TOKENS = 2048
UNITS = {
    "request_throughput": ("requests/s", "higher", "rate"),
    "output_throughput": ("tokens/s", "higher", "rate"),
    "total_token_throughput": ("tokens/s", "higher", "rate"),
}


def serving_ctx(
    make_ctx: MakeCtx,
    *,
    levels: tuple[int, ...] = (1, 4),
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


def write_result(folder: Path, label: str, doc: Any) -> Path:
    path = folder / f"vllm-bench-{label}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# --- prepare ---------------------------------------------------------------


def test_prepare_gives_one_run_per_level_with_the_driver_options(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    steps = VllmBenchDriver().prepare(serving_ctx(make_ctx), list(WORKLOAD)).steps
    assert [s.label for s in steps] == ["c1", "c4"]
    assert steps[0].argv == (
        "vllm",
        "bench",
        "serve",
        *WORKLOAD,
        "--base-url",
        URL,
        "--model",
        MODEL,
        "--max-concurrency",
        "1",
        "--seed",
        "1234",
        "--save-result",
        "--result-dir",
        str(tmp_path),
        "--result-filename",
        "vllm-bench-c1.json",
    )
    assert steps[1].argv[steps[1].argv.index("--max-concurrency") + 1] == "4"
    assert steps[1].argv[-1] == "vllm-bench-c4.json"


def test_a_rate_level_runs_at_a_request_rate(make_ctx: MakeCtx, tmp_path: Path) -> None:
    ctx = serving_ctx(make_ctx, levels=(2,), kind="rate", endpoint=Endpoint(base_url=URL))
    (step,) = VllmBenchDriver().prepare(ctx, list(WORKLOAD)).steps
    assert step.argv == (
        "vllm",
        "bench",
        "serve",
        *WORKLOAD,
        "--base-url",
        URL,
        "--request-rate",
        "2",
        "--seed",
        "1234",
        "--save-result",
        "--result-dir",
        str(tmp_path),
        "--result-filename",
        "vllm-bench-r2.json",
    )


def test_a_model_and_a_save_option_of_the_workload_are_not_doubled(make_ctx: MakeCtx) -> None:
    argv = ["--model", "x", "--save-result", *WORKLOAD]
    (step,) = VllmBenchDriver().prepare(serving_ctx(make_ctx, levels=(1,)), argv).steps
    assert step.argv.count("--model") == 1
    assert step.argv.count("--save-result") == 1


def test_the_seed_of_the_run_is_passed(make_ctx: MakeCtx) -> None:
    ctx = dataclasses.replace(serving_ctx(make_ctx, levels=(1,)), seed=7)
    (step,) = VllmBenchDriver().prepare(ctx, list(WORKLOAD)).steps
    assert step.argv[step.argv.index("--seed") + 1] == "7"


@pytest.mark.parametrize("option", [*vllm_bench.OWN_OPTIONS, "--seed=1"])
def test_a_workload_with_an_option_the_driver_adds_is_refused(
    make_ctx: MakeCtx, option: str
) -> None:
    argv = [option] if "=" in option or option == "--append-result" else [option, "x"]
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().prepare(serving_ctx(make_ctx), argv)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert option.partition("=")[0] in caught.value.message


def test_a_level_duration_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().prepare(serving_ctx(make_ctx, duration=30.0), list(WORKLOAD))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)
    assert "--num-prompts" in caught.value.message


def test_a_load_without_levels_is_refused_as_a_config_error(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().prepare(serving_ctx(make_ctx, levels=()), list(WORKLOAD))
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)


def test_a_side_that_serves_nothing_is_refused(make_ctx: MakeCtx) -> None:
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().prepare(serving_ctx(make_ctx, endpoint=None), list(WORKLOAD))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", 2)


# --- read ------------------------------------------------------------------


def test_each_level_gives_the_summary_fields_of_its_result(make_ctx: MakeCtx) -> None:
    samples = VllmBenchDriver().read(serving_ctx(make_ctx), FIXTURES)
    assert values(samples) == {**C1, **C4}
    assert {s.reducer for s in samples} == {REDUCER_TOOL_SUMMARY}
    assert {s.n_inner for s in samples} == {COMPLETED}


def test_every_case_has_the_unit_and_direction_of_its_field(make_ctx: MakeCtx) -> None:
    for sample in VllmBenchDriver().read(serving_ctx(make_ctx), FIXTURES):
        expected = UNITS.get(sample.metric, ("ms", "lower", "time"))
        assert (sample.unit, sample.better, sample.kind) == expected


def test_the_output_rate_of_the_highest_level_is_the_primary_case(make_ctx: MakeCtx) -> None:
    driver = VllmBenchDriver()
    assert driver.default_primary(driver.read(serving_ctx(make_ctx), FIXTURES)) == [
        "c4/output_throughput"
    ]


def test_a_result_file_is_read_as_the_one_level_of_the_load(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(4,), result_file=FIXTURES / "vllm-bench-c4.json")
    assert values(VllmBenchDriver().read(ctx, Path("/made-up/elsewhere"))) == C4


def test_the_energy_of_a_level_gives_tokens_per_joule(make_ctx: MakeCtx) -> None:
    ctx = serving_ctx(make_ctx, levels=(4,), energy=reading(("c4", JOULES)))
    got = {s.case: s for s in VllmBenchDriver().read(ctx, FIXTURES)}
    sample = got["c4/tokens_per_joule[gpu]"]
    assert sample.value == OUTPUT_TOKENS / JOULES
    assert (sample.n_inner, sample.reducer) == (WINDOW_SAMPLES, guidellm.REDUCER_PER_JOULE)


def test_other_percentiles_and_the_end_to_end_latency_are_read_and_spreads_are_not(
    make_ctx: MakeCtx, tmp_path: Path
) -> None:
    doc = {
        "completed": 3,
        "output_throughput": 1.5,
        "p99.9_ttft_ms": 9.5,
        "median_e2el_ms": 7.5,
        "std_ttft_ms": 0.5,
        "p50_itl_ms": None,
        "duration": 2.0,
    }
    write_result(tmp_path, "c1", doc)
    got = values(VllmBenchDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path))
    assert got == {"c1/output_throughput": 1.5, "c1/p99.9_ttft_ms": 9.5, "c1/median_e2el_ms": 7.5}


@pytest.mark.parametrize(
    ("doc", "found"),
    [
        ({"completed": 0, "output_throughput": 0.0}, "no completed request"),
        ({"completed": 3, "mean_ttft_ms": 2.0}, "holds no request_throughput"),
        ({"completed": 3, "output_throughput": "x"}, "output_throughput"),
        ([1, 2], "vllm-bench-c1.json"),
        (
            {"completed": 3, "output_throughput": 1.5, "median_ttft_ms": -2.0},
            "vllm-bench-c1.json: median_ttft_ms -2.0 is negative",
        ),
        (
            {"completed": 3, "output_throughput": -1.5},
            "vllm-bench-c1.json: output_throughput -1.5 is negative",
        ),
        (
            {"completed": 3, "output_throughput": 1.5, "total_output_tokens": -4},
            "vllm-bench-c1.json: total_output_tokens -4 is negative",
        ),
    ],
    ids=[
        "none-completed",
        "no-rate",
        "not-a-number",
        "not-an-object",
        "negative-latency",
        "negative-rate",
        "negative-tokens",
    ],
)
def test_a_result_that_cannot_be_read_is_a_failed_launch(
    make_ctx: MakeCtx, tmp_path: Path, doc: Any, found: str
) -> None:
    write_result(tmp_path, "c1", doc)
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)
    assert found in caught.value.message


def test_a_missing_result_is_a_failed_launch(make_ctx: MakeCtx, tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        VllmBenchDriver().read(serving_ctx(make_ctx, levels=(1,)), tmp_path)
    assert (caught.value.code, caught.value.exit_code) == ("E_LAUNCH_FAILED", 5)


# --- version, doctor, registry, fixtures -----------------------------------


def test_the_result_names_no_version(make_ctx: MakeCtx) -> None:
    assert VllmBenchDriver().tool_version(serving_ctx(make_ctx), FIXTURES) is None


def test_the_driver_is_experimental_and_runs_on_the_client() -> None:
    driver = registry.driver("vllm-bench")
    assert isinstance(driver, VllmBenchDriver)
    assert driver.where == "client"
    report = driver.doctor()
    assert report.status == "experimental"
    assert report.summary == (
        "reads the result file of vllm bench serve, one per load level; no fixture from a run "
        "of the real tool yet, so the driver is experimental"
    )


@pytest.mark.parametrize(
    "fixture",
    sorted(p for p in FIXTURES.glob("*.json") if not p.name.endswith(SIDECAR)),
    ids=lambda p: p.name,
)
def test_every_fixture_is_marked_synthetic_with_no_image(fixture: Path) -> None:
    doc = json.loads(fixture.with_name(fixture.name + SIDECAR).read_text(encoding="utf-8"))
    assert doc["generator"] == GENERATOR
    assert (doc["tool"], doc["synthetic"], doc["image"]) == ("vllm bench serve", True, None)
