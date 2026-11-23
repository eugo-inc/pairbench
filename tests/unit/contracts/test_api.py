# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The values the runner exchanges with sides, drivers, machine checks and energy."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import Refusal
from pairbench.model import Case, LoadSettings, Side, Witness

# ---------------------------------------------------------------------------
# The container engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "found", "engine"),
    [
        ("auto", ["docker", "podman"], "docker"),
        ("auto", ["podman", "docker"], "docker"),
        ("auto", ["podman"], "podman"),
        ("auto", ["docker"], "docker"),
        ("docker", ["docker", "podman"], "docker"),
        ("podman", ["docker", "podman"], "podman"),
    ],
)
def test_the_engine_that_is_picked(requested: str, found: list[str], engine: str) -> None:
    assert api.find_engine(requested, found) == engine
    assert api.choose_engine(requested, found) == engine


@pytest.mark.parametrize(
    ("requested", "found", "words"),
    [
        ("auto", [], "no container engine found: neither docker nor podman"),
        ("podman", ["docker"], "container engine not found: podman"),
        ("docker", [], "container engine not found: docker"),
    ],
)
def test_a_missing_engine_is_none_for_a_look_up_and_a_refusal_for_a_run(
    requested: str, found: list[str], words: str
) -> None:
    assert api.find_engine(requested, found) is None
    with pytest.raises(Refusal, match=words) as caught:
        api.choose_engine(requested, found)
    assert caught.value.code == "E_SIDE_UNRESOLVED"
    assert caught.value.exit_code == 3


@pytest.mark.parametrize(
    ("named", "found", "engine"),
    [
        ("podman", ["docker", "podman"], "podman"),
        ("Podman ", ["docker", "podman"], "podman"),
        ("docker", ["docker", "podman"], "docker"),
        ("podman", ["docker"], "docker"),
        ("docker", ["podman"], "podman"),
        ("made-up-engine", ["docker", "podman"], "docker"),
        ("", ["docker", "podman"], "docker"),
    ],
)
def test_auto_prefers_the_engine_the_environment_names(
    named: str, found: list[str], engine: str
) -> None:
    environ = {"PAIRBENCH__LAUNCH__ENGINE": named}
    assert api.ENGINE_VARIABLE == "PAIRBENCH__LAUNCH__ENGINE"
    assert api.find_engine("auto", found, environ) == engine
    assert api.choose_engine("auto", found, environ) == engine


def test_a_named_engine_is_not_changed_by_the_environment() -> None:
    environ = {"PAIRBENCH__LAUNCH__ENGINE": "podman"}
    assert api.find_engine("docker", ["docker", "podman"], environ) == "docker"
    assert api.find_engine("docker", ["podman"], environ) is None
    assert api.find_engine("auto", [], environ) is None
    assert api.find_engine("auto", ["docker", "podman"], {}) == "docker"


def test_a_container_name_carries_the_run_id_and_is_unique_within_the_run() -> None:
    assert api.container_name("run42", 7, "new") == "pairbench-run42-0007-new"
    assert api.container_name("run42", 8, "new~same") == "pairbench-run42-0008-new-same"
    assert api.container_name("run42", 7, "new").startswith(api.CONTAINER_PREFIX)
    assert api.CONTAINER_PREFIX == "pairbench-"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("1", True),
        ("TRUE", True),
        ("yes", True),
        ("", False),
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("off", False),
    ],
)
def test_an_automated_pipeline_is_told_by_the_ci_variable(value: str, expected: bool) -> None:
    assert api.is_ci({"CI": value}) is expected


def test_a_run_records_the_command_line_only_inside_the_command_line() -> None:
    assert api.recorded_command_line() == ()
    with api.command_line(["pairbench", "run", "--rounds", "8"]):
        assert api.recorded_command_line() == ("pairbench", "run", "--rounds", "8")
        with api.command_line(["pairbench", "compare"]):
            assert api.recorded_command_line() == ("pairbench", "compare")
        assert api.recorded_command_line() == ("pairbench", "run", "--rounds", "8")
    assert api.recorded_command_line() == ()


def test_a_run_records_the_command_line_with_credential_values_redacted() -> None:
    argv = ["pairbench", "run", "--set", "launch.env.API_TOKEN=made-up-secret", "--", "tool"]
    with api.command_line(argv):
        assert api.recorded_command_line() == (
            "pairbench",
            "run",
            "--set",
            "launch.env.API_TOKEN=<redacted>",
            "--",
            "tool",
        )


def test_the_recorded_command_line_is_cleared_when_the_work_raises() -> None:
    with pytest.raises(RuntimeError), api.command_line(["pairbench", "run"]):
        raise RuntimeError("made-up failure")
    assert api.recorded_command_line() == ()


def test_the_lines_printed_on_standard_error() -> None:
    from pairbench.model import GateRecord

    assert api.note_line("floor_provisional", "a made-up note") == (
        "pairbench: note: floor_provisional: a made-up note"
    )
    failed = GateRecord(
        name="quiet", mode="warn", status="fail", detail={"message": "a made-up reason"}
    )
    assert api.gate_line(failed) == "pairbench: check quiet: fail: a made-up reason"
    silent = GateRecord(name="census", mode="warn", status="unavailable")
    assert api.gate_line(silent) == "pairbench: check census: unavailable"


def test_a_printed_line_escapes_the_control_characters_of_its_message() -> None:
    from pairbench.model import GateRecord

    forged = "x\x1b[31m red\r\npairbench: E_USAGE: made-up\x85\x7f\tend\x00"
    shown = "x\\x1b[31m red\\r\\npairbench: E_USAGE: made-up\\x85\\x7f\\tend\\x00"
    assert api.note_line("floor_provisional", forged) == (
        f"pairbench: note: floor_provisional: {shown}"
    )
    failed = GateRecord(name="quiet", mode="warn", status="fail", detail={"message": forged})
    assert api.gate_line(failed) == f"pairbench: check quiet: fail: {shown}"


def test_no_ci_variable_is_no_automated_pipeline() -> None:
    assert api.is_ci({}) is False
    assert api.is_ci({"CI_JOB": "1"}) is False


# ---------------------------------------------------------------------------
# Samples, invocations and energy
# ---------------------------------------------------------------------------


def test_a_sample_describes_its_case() -> None:
    sample = api.Sample(
        case="c32/ttft_ms_median",
        metric="ttft_ms_median",
        unit="ms",
        better="lower",
        kind="time",
        value=41.5,
    )
    assert (sample.n_inner, sample.reducer) == (1, "identity")
    assert sample.to_case(primary=True) == Case(
        id="c32/ttft_ms_median",
        metric="ttft_ms_median",
        unit="ms",
        better="lower",
        kind="time",
        primary=True,
        group=None,
    )
    assert sample.to_case(primary=False, group="latency").group == "latency"


def test_the_reducer_names() -> None:
    assert (
        api.REDUCER_IDENTITY,
        api.REDUCER_MEDIAN,
        api.REDUCER_TOOL_SUMMARY,
        api.REDUCER_TRAPEZOID,
    ) == ("identity", "median", "tool_summary", "trapezoid")


def test_an_in_side_invocation_is_one_step() -> None:
    invocation = api.Invocation.single(["bench", "--json", "out.json"], {"A": "1"})
    assert invocation.argv == ("bench", "--json", "out.json")
    assert invocation.env == {"A": "1"}
    assert [step.label for step in invocation.steps] == [""]


def test_a_client_invocation_has_one_step_per_load_level() -> None:
    levels = LoadSettings(levels=(1, 8), level_kind="rate")
    steps = tuple(api.Step(label=label, argv=("load", label)) for label in levels.labels())
    invocation = api.Invocation(steps=steps)
    assert [step.label for step in invocation.steps] == ["r1", "r8"]
    with pytest.raises(ValueError, match="more than one step"):
        _ = invocation.argv


def _reading(throttle: int | None) -> api.EnergyReading:
    windows = (
        api.EnergyWindow(
            label="c8", start_s=10.0, end_s=12.0, energy_j=40.0, mean_power_w=20.0, n_samples=11
        ),
        api.EnergyWindow(
            label="c32",
            start_s=12.0,
            end_s=14.0,
            energy_j=None,
            mean_power_w=None,
            n_samples=3,
            reason="too few power samples",
        ),
    )
    return api.EnergyReading(
        source="made-up", sampler_ok=True, query_errors=0, windows=windows, throttle_events=throttle
    )


def test_an_energy_reading_gives_cases_only_for_windows_that_have_a_value() -> None:
    reading = _reading(0)
    assert [
        (s.case, s.metric, s.unit, s.better, s.kind, s.value, s.n_inner, s.reducer)
        for s in reading.samples()
    ] == [
        ("c8/energy_j[gpu]", "energy_j[gpu]", "J", "lower", "other", 40.0, 11, "trapezoid"),
        ("c8/mean_power_w[gpu]", "mean_power_w[gpu]", "W", "lower", "other", 20.0, 11, "trapezoid"),
    ]
    assert reading.window("c32") is not None
    assert reading.window("made-up") is None


def test_an_energy_reading_is_recorded_without_absolute_times() -> None:
    recorded = _reading(2).to_json()
    assert recorded["windows"][0] == {
        "label": "c8",
        "seconds": 2.0,
        "energy_j": 40.0,
        "mean_power_w": 20.0,
        "n_samples": 11,
        "counter_j": None,
        "reason": None,
    }
    assert recorded["windows"][1]["reason"] == "too few power samples"
    assert recorded["throttle_events"] == 2
    assert sorted(recorded) == [
        "idle_power_w",
        "max_temperature_c",
        "query_errors",
        "sampler_ok",
        "source",
        "throttle_events",
        "windows",
    ]


@pytest.mark.parametrize(
    ("seen", "witness", "expected"),
    [
        (3, Witness(busy_cores=0.5), Witness(busy_cores=0.5, gpu_throttle_events=3)),
        (0, Witness(gpu_throttle_events=2), Witness(gpu_throttle_events=2)),
        (4, Witness(gpu_throttle_events=2), Witness(gpu_throttle_events=4)),
        (
            1,
            Witness(failed=("gpu_throttle_events", "busy_cores")),
            Witness(gpu_throttle_events=1, failed=("busy_cores",)),
        ),
        (None, Witness(busy_cores=0.5), Witness(busy_cores=0.5)),
        (
            None,
            Witness(failed=("gpu_throttle_events",)),
            Witness(failed=("gpu_throttle_events",)),
        ),
    ],
)
def test_the_throttle_count_of_the_power_sampler_is_laid_into_the_witness(
    seen: int | None, witness: Witness, expected: Witness
) -> None:
    assert _reading(seen).witness(witness) == expected


# ---------------------------------------------------------------------------
# Contexts and requests
# ---------------------------------------------------------------------------


def test_the_defaults_of_a_driver_context(tmp_path: Path) -> None:
    ctx = api.DriverContext(
        run_id="run42",
        seq=7,
        phase="round",
        round=1,
        name="new",
        side=Side.parse("new=cmd:true"),
        artifacts=tmp_path,
        artifacts_in_side=str(tmp_path),
    )
    assert ctx.settings == LoadSettings()
    assert ctx.seed == 1234
    assert api.DEFAULT_SEED == 1234
    assert (ctx.endpoint, ctx.rc, ctx.energy, ctx.result_file) == (None, None, None, None)
    assert ctx.timing == {}
    assert ctx.note("made_up", "a made-up note") is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "1.5", None, True])
def test_a_sample_whose_value_is_no_finite_number_is_output_that_cannot_be_read(value: Any) -> None:
    words = r"case 'matmul': the value .* is not a finite number"
    with pytest.raises(Refusal, match=words) as caught:
        api.Sample(case="matmul", metric="time", unit="s", better="lower", kind="time", value=value)
    assert caught.value.code == "E_LAUNCH_FAILED"
    assert caught.value.exit_code == 5


@pytest.mark.parametrize("value", [0, 0.0, -2.5, 3, 1e300])
def test_a_sample_keeps_a_value_of_zero_or_less(value: float) -> None:
    sample = api.Sample(
        case="matmul", metric="time", unit="s", better="lower", kind="time", value=value
    )
    assert sample.value == value


def test_a_launch_outcome_tells_the_first_process_of_the_launch() -> None:
    told = api.LaunchOutcome(rc=0, pid=4242)
    assert told.pid == 4242
    assert api.LaunchOutcome(rc=0).pid is None


def test_a_witness_sampler_is_told_the_first_process_of_the_launch_when_it_stops() -> None:
    import inspect

    stop = inspect.signature(api.WitnessSampler.stop)
    assert [(p.name, p.annotation, p.default) for p in stop.parameters.values()] == [
        ("self", inspect.Parameter.empty, inspect.Parameter.empty),
        ("own_cpu_s", "float | None", inspect.Parameter.empty),
        ("own_pid", "int | None", None),
        ("second_pid", "int | None", None),
    ]
    assert stop.return_annotation == "Witness"
    assert not hasattr(api.WitnessSampler, "launched")
    text = " ".join((api.WitnessSampler.__doc__ or "").split())
    assert "every compute process seen counts as another one" in text
    assert "the launch is never interrupted to ask" in text


def test_the_defaults_of_the_serving_waits() -> None:
    assert api.GPU_FREE_WAIT_S == 300.0
    assert api.GPU_RELEASE_WAIT_S == 120.0
    assert api.GPU_RELEASE_TOLERANCE_MIB == 64.0


def test_the_files_and_names_of_a_launch() -> None:
    assert (api.ARTIFACT_STDOUT, api.ARTIFACT_STDERR, api.ARTIFACT_SERVER_LOG) == (
        "stdout.txt",
        "stderr.txt",
        "server.log",
    )
    assert api.ARTIFACTS_IN_CONTAINER == "/pairbench/artifacts"
    assert (api.TIMING_RUN_S, api.TIMING_LAUNCH_S) == ("run_s", "launch_s")
    assert (api.TIMING_USER_S, api.TIMING_SYS_S) == ("user_s", "sys_s")
    assert (model.CASE_WALL, model.CASE_LAUNCH) == ("wall", "launch")
    assert (model.CASE_RES_USER, model.CASE_RES_SYS) == ("res/user", "res/sys")
    assert not hasattr(model, "CASE_USER")
    assert not hasattr(model, "CASE_SYS")
    assert api.ENGINES == ("docker", "podman")


def test_a_launch_outcome_reports_a_failure_without_raising() -> None:
    outcome = api.LaunchOutcome(rc=3, timing={"run_s": 1.5, "launch_s": 1.75}, timed_out=True)
    assert (outcome.rc, outcome.timed_out, outcome.cpu_s, outcome.samples) == (3, True, None, ())


def test_a_gate_context_carries_the_facts_of_the_machine_record() -> None:
    from pairbench.model import GateSettings, LaunchSettings

    ctx = api.GateContext(mode="warn", gates=GateSettings(), launch=LaunchSettings())
    assert (ctx.phase, ctx.in_container, ctx.ci, ctx.environ) == ("before", False, False, {})


# ---------------------------------------------------------------------------
# The services of a run
# ---------------------------------------------------------------------------


def test_the_services_of_a_run_come_from_the_modules_that_provide_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: dict[str, Any] = {"checks": object(), "meter": object(), "facts": object()}

    def profiler(tool: str) -> str:
        return f"profiler for {tool}"

    def module(name: str, **members: Any) -> None:
        fake = types.ModuleType(name)
        for key, value in members.items():
            setattr(fake, key, value)
        monkeypatch.setitem(sys.modules, name, fake)

    module("pairbench.gates.base", machine_checks=lambda: made["checks"])
    module("pairbench.energy.sampler", energy_meter=lambda: made["meter"])
    module("pairbench.provenance", facts=lambda: made["facts"])
    module("pairbench.profile.nsight", profiler=profiler)
    services = api.default_services()
    assert services.checks is made["checks"]
    assert services.meter is made["meter"]
    assert services.facts is made["facts"]
    assert services.profiler("nsys") == "profiler for nsys"
