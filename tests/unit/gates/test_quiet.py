# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The quiet-machine check and ``gate wait-quiet``, on synthetic processor counters."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.errors import Refusal
from pairbench.gates import quiet as quiet_module
from pairbench.gates.quiet import QuietGate, busy_cores, parse_stat, wait_then_run
from pairbench.model import GateSettings, LaunchSettings, QuietSettings

# Per CPU, the busy and idle ticks of one interval.
QUIET = {0: (25, 75), 1: (25, 75), 2: (25, 75), 3: (25, 75)}  # 1.0 busy core: at the limit
BUSY = {0: (100, 0), 1: (100, 0), 2: (0, 100), 3: (0, 100)}  # 2.0 busy cores

Ctx = Callable[..., Any]


def _gate(tree: Any, clock: Any, **kw: Any) -> QuietGate:
    system = kw.pop("system", "linux")
    return QuietGate(root=tree.root, system=system, clock=clock, sleep=clock.sleep, **kw)


def _settings(**quiet: Any) -> GateSettings:
    wait = quiet.pop("wait", False)
    return GateSettings(wait_quiet=wait, quiet=QuietSettings(**quiet))


def test_parse_stat_known_answer() -> None:
    text = (
        "cpu  10 20 30 40 50 60 70 80 90 100\n"
        "cpu0 1 2 3 4 5 6 7 8 9 10\n"
        "cpu1 100 0 0 300\n"
        "intr 1 2 3\n"
    )
    # busy = user + nice + system + irq + softirq + steal; the total adds idle
    # and iowait; guest and guest_nice are already inside user and are left out.
    assert parse_stat(text) == {0: (27, 36), 1: (100, 400)}


def test_parse_stat_without_cpu_lines_is_none() -> None:
    assert parse_stat("intr 1\nctxt 2\n") is None
    assert parse_stat("cpu0 a b c d\n") is None
    assert parse_stat("cpu0 1 2\n") is None


def test_busy_cores_known_answer() -> None:
    before = {0: (1000, 2000), 1: (1000, 2000), 2: (1000, 2000), 3: (1000, 2000)}
    after = {0: (1100, 2100), 1: (1050, 2100), 2: (1000, 2100), 3: (1010, 2100)}
    # 4 CPUs * 160 busy ticks / 400 ticks; on CPUs 0 and 1: 2 * 150 / 200
    assert busy_cores(before, after) == 1.6
    assert busy_cores(before, after, frozenset({0, 1})) == 1.5


def test_busy_cores_none_when_nothing_could_be_seen() -> None:
    same = {0: (10, 20)}
    assert busy_cores(same, same) is None
    assert busy_cores(None, same) is None
    assert busy_cores(same, {1: (10, 20)}) is None


def test_one_streak_of_quiet_samples_passes(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    record = _gate(tree, clock).check(make_ctx(gates=_settings()))
    assert record.name == "quiet"
    assert record.mode == "warn"
    assert record.status == "pass"
    assert "message" not in record.detail
    assert clock.slept == [2.0, 2.0, 2.0, 2.0, 2.0]
    assert record.detail["samples_taken"] == 5
    assert record.detail["waited"] is False
    assert record.detail["source"] == "proc_stat"
    assert record.detail["view"] == "host"
    assert record.to_json()["detail"]["last"][0] == {
        "busy_cores": 1.0,
        "gpu_processes": None,
        "quiet": True,
    }


def test_one_busy_sample_without_waiting_fails(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET, QUIET, BUSY, QUIET, QUIET]))
    record = _gate(tree, clock).check(make_ctx(gates=_settings()))
    assert record.status == "fail"
    assert (
        record.detail["message"]
        == "not quiet in 1 of 5 samples: busy cores 2.00 against a limit of 1"
    )
    assert len(clock.slept) == 5


def test_mutant_a_failed_counter_read_never_passes_the_quiet_check(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    record = _gate(tree, clock).check(make_ctx(gates=_settings(max_busy_cores=1000.0)))
    assert record.status == "fail"
    assert (
        record.detail["message"] == "not quiet in 5 of 5 samples: the busy cores could not be read"
    )


def test_mutant_a_failed_gpu_read_never_passes_the_quiet_check(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[None])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    record = gate.check(make_ctx(gates=_settings(), launch=LaunchSettings(gpus="0")))
    assert record.status == "fail"
    assert (
        record.detail["message"]
        == "not quiet in 5 of 5 samples: the GPU processes could not be read"
    )


def test_another_gpu_compute_process_is_busy(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    seen: list[str] = []
    gpu = fake_gpu(pids=[(4242,)])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: seen.append(gpus) or gpu)
    record = gate.check(make_ctx(gates=_settings(), launch=LaunchSettings(gpus="0,1")))
    assert seen == ["0,1"]
    assert record.status == "fail"
    assert record.detail["message"] == (
        "not quiet in 5 of 5 samples: 1 other compute process(es) on the selected GPUs"
    )


@pytest.mark.parametrize(
    ("sides", "watched"),
    [
        ({"old": LaunchSettings(gpus="0"), "new": LaunchSettings(gpus="1")}, "0,1"),
        ({"old": LaunchSettings(gpus="1,0"), "new": LaunchSettings(gpus="0")}, "1,0"),
        ({"old": LaunchSettings(), "new": LaunchSettings(gpus="1")}, "1"),
        ({"old": LaunchSettings(gpus="all"), "new": LaunchSettings(gpus="1")}, "all"),
    ],
)
def test_the_gpus_each_side_selects_for_itself_are_watched(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Any,
    readings: Any,
    fake_gpu: Any,
    sides: dict[str, LaunchSettings],
    watched: str,
) -> None:
    stat_script(readings([QUIET] * 5))
    seen: list[str] = []
    gpu = fake_gpu(pids=[(4242,)])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: seen.append(gpus) or gpu)
    record = gate.check(make_ctx(gates=_settings(), sides=sides))
    assert seen == [watched]
    assert record.detail["gpu_idle"] is True
    assert record.status == "fail"


def test_a_side_override_names_gpus_the_check_watches(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    seen: list[str] = []
    gpu = fake_gpu(pids=[()])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: seen.append(gpus) or gpu)
    launch = LaunchSettings(overrides={"new": {"gpus": "1"}})
    record = gate.check(make_ctx(gates=_settings(), launch=launch))
    assert seen == ["1"]
    assert record.detail["gpu_idle"] is True
    assert record.status == "pass"


def test_gpu_idle_off_wins_over_a_side_that_selects_gpus(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[None])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    sides = {"old": LaunchSettings(gpus="0"), "new": LaunchSettings(gpus="1")}
    record = gate.check(make_ctx(gates=_settings(gpu_idle=False), sides=sides))
    assert record.status == "pass"
    assert record.detail["gpu_idle"] is False
    assert gpu.reads == 0


def test_gpus_are_not_read_when_gpu_idle_is_off(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[None])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    record = gate.check(make_ctx(gates=_settings(gpu_idle=False), launch=LaunchSettings(gpus="0")))
    assert record.status == "pass"
    assert gpu.reads == 0


def test_gpus_are_not_read_when_none_is_requested(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[None])
    record = _gate(tree, clock, gpu_sources=lambda gpus: gpu).check(make_ctx(gates=_settings()))
    assert record.status == "pass"
    assert record.detail["gpu_idle"] is False
    assert gpu.reads == 0


def test_gpu_idle_on_without_a_gpu_selected_watches_all(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    seen: list[str] = []
    gpu = fake_gpu(pids=[()])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: seen.append(gpus) or gpu)
    record = gate.check(make_ctx(gates=_settings(gpu_idle=True)))
    assert record.status == "pass"
    assert seen == ["all"]


def test_waiting_keeps_sampling_until_the_streak(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY, BUSY] + [QUIET] * 5))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True)))
    assert record.status == "pass"
    assert record.detail["waited"] is True
    assert record.detail["samples_taken"] == 7
    assert record.detail["waited_s"] == 14.0


def test_waiting_starts_the_streak_again_after_a_busy_sample(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET, QUIET, BUSY] + [QUIET] * 5))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True)))
    assert record.status == "pass"
    assert record.detail["samples_taken"] == 8
    assert record.detail["waited_s"] == 16.0


def test_waiting_gives_up_after_the_longest_wait(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 10))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True, max_wait_s=10.0)))
    assert record.status == "fail"
    assert record.detail["message"] == (
        "the machine did not become quiet within 10 s: busy cores 2.00 against a limit of 1"
    )
    assert record.detail["samples_taken"] == 5


def test_the_recheck_takes_one_sample_and_never_waits(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 10))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True), phase="recheck"))
    assert record.status == "fail"
    assert clock.slept == [2.0]
    assert (
        record.detail["message"]
        == "not quiet in 1 of 1 samples: busy cores 2.00 against a limit of 1"
    )


def test_inside_a_container_the_view_is_labelled(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 5))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(), in_container=True))
    assert record.status == "fail"
    assert record.detail["view"] == "machine"
    assert record.detail["message"] == (
        "not quiet in 5 of 5 samples: busy cores 2.00 against a limit of 1 "
        "(machine-wide view from inside a container)"
    )


def test_an_automated_pipeline_is_recorded_and_not_waited_on(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 10))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(), ci=True))
    assert record.status == "fail"
    assert record.detail["ci"] is True
    assert record.detail["where"] == "ci"
    assert len(clock.slept) == 5


def test_macos_quiet_by_load_average_is_degraded(clock: Any, tree: Any, make_ctx: Ctx) -> None:
    gate = _gate(tree, clock, system="darwin", loadavg=lambda: 0.5)
    record = gate.check(make_ctx(gates=_settings()))
    assert record.status == "degraded"
    assert record.detail["source"] == "load_average"
    assert record.detail["message"] == (
        "quiet by the load average only; busy cores are not read on this platform"
    )


def test_macos_busy_by_load_average_fails(clock: Any, tree: Any, make_ctx: Ctx) -> None:
    gate = _gate(tree, clock, system="darwin", loadavg=lambda: 3.0)
    record = gate.check(make_ctx(gates=_settings()))
    assert record.status == "fail"
    assert (
        record.detail["message"]
        == "not quiet in 5 of 5 samples: load average 3.00 against a limit of 1"
    )


def test_macos_load_average_that_fails_to_read_is_busy(
    clock: Any, tree: Any, make_ctx: Ctx
) -> None:
    def broken() -> float:
        raise OSError("no load average")

    record = _gate(tree, clock, system="darwin", loadavg=broken).check(make_ctx(gates=_settings()))
    assert record.status == "fail"
    assert (
        record.detail["message"]
        == "not quiet in 5 of 5 samples: the load average could not be read"
    )


def test_macos_gpus_cannot_be_read_so_gpu_idle_is_busy(
    clock: Any, tree: Any, make_ctx: Ctx
) -> None:
    gate = _gate(tree, clock, system="darwin", loadavg=lambda: 0.0)
    record = gate.check(make_ctx(gates=_settings(gpu_idle=True)))
    assert record.status == "fail"
    assert (
        record.detail["message"]
        == "not quiet in 5 of 5 samples: the GPU processes could not be read"
    )


def test_another_platform_is_unavailable(clock: Any, tree: Any, make_ctx: Ctx) -> None:
    record = _gate(tree, clock, system="other").check(make_ctx(gates=_settings()))
    assert record.status == "unavailable"
    assert record.detail["message"] == "busy cores cannot be read on this platform"
    assert clock.slept == []


def test_quiet_doctor(tree: Any, clock: Any) -> None:
    assert _gate(tree, clock).doctor().status == "unavailable"
    tree.stat(QUIET)
    assert _gate(tree, clock).doctor().status == "ok"
    assert _gate(tree, clock, system="darwin").doctor().status == "degraded"


# --- gate wait-quiet -- COMMAND ----------------------------------------------


def _wait(tree: Any, clock: Any, **kw: Any) -> Any:
    ran: list[tuple[str, ...]] = []

    def run(command: Any) -> int:
        ran.append(tuple(command))
        return kw.pop("rc", 0)

    gate = _gate(tree, clock, system=kw.pop("system", "linux"), **kw.pop("gate", {}))
    return gate, run, ran


def test_wait_quiet_runs_the_command_once_quiet_and_returns_its_code(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY, QUIET, QUIET]))
    gate, _, ran = _wait(tree, clock)

    def run(command: Any) -> int:
        ran.append(tuple(command))
        return 3

    rc = wait_then_run(
        ["make", "bench"],
        gates=_settings(samples=2, interval_s=1.0),
        launch=LaunchSettings(),
        gate=gate,
        run=run,
    )
    assert rc == 3
    assert ran == [("make", "bench")]


def test_wait_quiet_refuses_with_exit_4_and_runs_nothing_when_quiet_never_comes(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 10))
    gate, run, ran = _wait(tree, clock)
    err = io.StringIO()
    with pytest.raises(Refusal) as caught:
        wait_then_run(
            ["make", "bench"],
            gates=_settings(samples=2, interval_s=1.0, max_wait_s=4.0),
            launch=LaunchSettings(),
            gate=gate,
            run=run,
            err=err,
        )
    assert caught.value.code == "E_GATE_FAILED"
    assert caught.value.exit_code == 4
    assert caught.value.message == (
        "the command was not run: the machine did not become quiet within 4 s: "
        "busy cores 2.00 against a limit of 1"
    )
    assert caught.value.detail["record"]["detail"]["samples_taken"] == 4
    assert ran == []
    assert err.getvalue() == (
        "pairbench: check quiet: fail: the machine did not become quiet within 4 s: "
        "busy cores 2.00 against a limit of 1\n"
    )


def test_wait_quiet_on_macos_runs_nothing(tree: Any, clock: Any) -> None:
    gate, run, ran = _wait(tree, clock, system="darwin", gate={"loadavg": lambda: 0.0})
    with pytest.raises(Refusal) as caught:
        wait_then_run(["true"], gates=_settings(), launch=LaunchSettings(), gate=gate, run=run)
    assert caught.value.code == "E_GATE_UNAVAILABLE"
    assert caught.value.exit_code == 4
    assert ran == []


def test_wait_quiet_needs_a_command() -> None:
    with pytest.raises(Refusal) as caught:
        wait_then_run([], gates=GateSettings(), launch=LaunchSettings())
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_wait_quiet_with_a_command_that_cannot_start(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gate = _gate(tree, clock)

    def run(command: Any) -> int:
        raise FileNotFoundError(2, "No such file or directory")

    with pytest.raises(Refusal) as caught:
        wait_then_run(
            ["/made-up/folder/nothing-here"],
            gates=_settings(samples=1),
            launch=LaunchSettings(),
            gate=gate,
            run=run,
        )
    assert caught.value.code == "E_USAGE"
    assert caught.value.message == "the command could not be started: nothing-here"


def test_a_command_ended_by_a_signal_exits_128_plus_the_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "call", lambda argv: -15)
    assert quiet_module._call(["sleep", "9"]) == 143
    monkeypatch.setattr(subprocess, "call", lambda argv: 7)
    assert quiet_module._call(["false"]) == 7


ABSENT = "GPU 3 is not on this machine; the GPUs here are 0, 1, so they cannot be watched"


@pytest.mark.parametrize(
    ("ctx_kw", "message"),
    [
        ({"launch": LaunchSettings(gpus="3")}, ABSENT),
        (
            {"sides": {"old": LaunchSettings(gpus="0"), "new": LaunchSettings(gpus="3")}},
            f"side new: {ABSENT}",
        ),
        (
            {"sides": {"old": LaunchSettings(gpus="3"), "new": LaunchSettings(gpus="1,3")}},
            f"sides new, old: {ABSENT}",
        ),
        (
            {"launch": LaunchSettings(gpus="0", overrides={"old": {"gpus": "3"}})},
            f"side old: {ABSENT}",
        ),
        (
            {
                "launch": LaunchSettings(gpus="3"),
                "sides": {"old": LaunchSettings(gpus="3"), "new": LaunchSettings(gpus="0")},
            },
            ABSENT,
        ),
    ],
    ids=["shared", "one-side", "two-sides", "override", "shared-kept-by-a-side"],
)
def test_a_gpu_the_machine_does_not_have_is_named_at_once_not_waited_on(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Any,
    readings: Any,
    fake_gpu: Any,
    ctx_kw: dict[str, Any],
    message: str,
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[()], indices=(0, 1))
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    record = gate.check(make_ctx(gates=_settings(wait=True, max_wait_s=600.0), **ctx_kw))
    assert record.status == "unavailable"
    assert record.detail["message"] == message
    assert list(record.detail["gpus_present"]) == [0, 1]
    assert gpu.reads == 0
    assert clock.slept == []


def test_gpus_the_machine_has_are_watched_as_before(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    gpu = fake_gpu(pids=[()], indices=(0, 1))
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    record = gate.check(make_ctx(gates=_settings(), launch=LaunchSettings(gpus="1")))
    assert record.status == "pass"
    assert gpu.reads > 0
