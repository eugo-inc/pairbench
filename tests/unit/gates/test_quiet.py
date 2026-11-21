# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The quiet-machine check and ``gate wait-quiet``, on synthetic processor counters."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from pairbench.errors import Refusal
from pairbench.gates import quiet as quiet_module
from pairbench.gates.quiet import QuietGate, busy_cores, parse_stat, wait_then_run
from pairbench.model import GateRecord, GateSettings, LaunchSettings, QuietSettings

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


# --- readiness checks during the wait ----------------------------------------


class _Ready:
    """A readiness check that answers from a script; its last answer repeats."""

    api_version = 1

    def __init__(self, name: str, statuses: list[str], message: str = "a made-up reason") -> None:
        self.name = name
        self.statuses = statuses
        self.message = message
        self.calls = 0

    def check(self, ctx: Any) -> GateRecord:
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        detail = {} if status == "pass" else {"message": self.message}
        return GateRecord(name=self.name, mode=ctx.mode, status=status, detail=detail)  # type: ignore[arg-type]


def _ready_settings(**quiet: Any) -> GateSettings:
    keys = {
        "stop_file": quiet.pop("stop_file", "made-up/hold.stop"),
        "min_gpu_free_mib": quiet.pop("min_gpu_free_mib", None),
        "check_locks": quiet.pop("check_locks", ()),
    }
    return replace(_settings(**quiet), **keys)


def test_while_waiting_a_sample_is_quiet_only_when_the_readiness_checks_pass(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    stop = _Ready("stop_file", ["fail", "fail", "fail", "pass"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True)))
    assert record.status == "pass"
    assert record.detail["samples_taken"] == 8
    assert stop.calls == 8
    assert record.detail["readiness"] == ("stop_file",)
    assert record.detail["not_ready"] == ()
    assert record.to_json()["detail"]["last"][0] == {
        "busy_cores": 1.0,
        "gpu_processes": None,
        "quiet": True,
        "ready": False,
    }


def test_a_sample_that_is_not_ready_starts_the_streak_again(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 12))
    stop = _Ready("stop_file", ["pass", "pass", "pass", "fail", "pass"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True)))
    assert record.status == "pass"
    assert record.detail["samples_taken"] == 9


def test_a_readiness_check_that_cannot_run_counts_as_not_ready(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    memory = _Ready("gpu_memory", ["unavailable"])
    gate = _gate(tree, clock, readiness=[memory])
    settings = _ready_settings(wait=True, max_wait_s=10.0, stop_file=None, min_gpu_free_mib=2000.0)
    record = gate.check(make_ctx(gates=settings))
    assert record.detail["samples_taken"] == 5
    assert memory.calls == 5
    assert record.detail["not_ready"] == ("gpu_memory",)


def test_when_time_runs_out_quiet_but_not_ready_the_quiet_record_passes(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    stop = _Ready("stop_file", ["fail"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True, max_wait_s=10.0)))
    assert record.status == "pass"
    assert "message" not in record.detail
    assert record.detail["not_ready"] == ("stop_file",)


def test_when_time_runs_out_busy_and_not_ready_the_quiet_record_fails_for_the_busy_cores(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET, QUIET, QUIET, BUSY, QUIET]))
    stop = _Ready("stop_file", ["fail"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True, max_wait_s=10.0)))
    assert record.status == "fail"
    assert record.detail["message"] == (
        "the machine did not become quiet within 10 s: busy cores 2.00 against a limit of 1"
    )


class _SlowReady(_Ready):
    """A readiness check whose every read takes ``seconds`` on the clock."""

    def __init__(self, clock: Any, seconds: float) -> None:
        super().__init__("gpu_memory", ["pass"])
        self.clock = clock
        self.seconds = seconds

    def check(self, ctx: Any) -> GateRecord:
        self.clock.now += self.seconds
        return super().check(ctx)


def test_a_wait_cut_short_by_slow_reads_says_too_few_samples_not_busy(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    slow = _SlowReady(clock, seconds=4.0)
    gate = _gate(tree, clock, readiness=[slow])
    settings = _ready_settings(wait=True, max_wait_s=10.0, stop_file=None, min_gpu_free_mib=2000.0)
    record = gate.check(make_ctx(gates=settings))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 2
    assert record.detail["message"] == (
        "the machine did not become quiet within 10 s: "
        "2 of the 5 quiet samples needed were taken in that time"
    )


def test_a_wait_shorter_than_the_samples_says_too_few_samples(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True, max_wait_s=3.0)))
    assert record.status == "fail"
    assert record.detail["message"] == (
        "the machine did not become quiet within 3 s: "
        "2 of the 5 quiet samples needed were taken in that time"
    )


def test_a_wait_that_kept_only_quiet_samples_counts_the_quiet_samples_in_a_row(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    # The first sample is busy and the 49 after it are quiet; the wait keeps only the
    # last samples, so the busy one is not in the record when the time runs out.
    stat_script(readings([BUSY] + [QUIET] * 60))
    settings = _settings(wait=True, samples=50, max_wait_s=100.0)
    record = _gate(tree, clock).check(make_ctx(gates=settings))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 50
    assert all(s["quiet"] for s in record.to_json()["detail"]["last"])
    assert record.detail["message"] == (
        "the machine did not become quiet within 100 s: "
        "49 of the 50 quiet samples needed were taken in that time"
    )


def test_a_wait_that_took_one_quiet_sample_says_one_was_taken(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True, max_wait_s=2.0)))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 1
    assert record.detail["message"] == (
        "the machine did not become quiet within 2 s: "
        "1 of the 5 quiet samples needed was taken in that time"
    )


def test_a_wait_quiet_but_never_ready_counts_the_quiet_samples_not_the_ready_ones(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    # Every sample is quiet by the busy cores and none is ready, so the streak of quiet
    # and ready samples stays at 0 while the quiet samples in a row reach 3.
    stat_script(readings([QUIET] * 10))
    stop = _Ready("stop_file", ["fail"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True, max_wait_s=6.0)))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 3
    assert record.detail["not_ready"] == ("stop_file",)
    assert record.detail["message"] == (
        "the machine did not become quiet within 6 s: "
        "3 of the 5 quiet samples needed were taken in that time"
    )


def test_without_a_wait_a_busy_sample_the_record_does_not_keep_is_counted(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    # The first sample is busy and the 49 after it are quiet; only the last samples are
    # kept, so the busy one is not in the record, yet the line counts it and says why.
    stat_script(readings([BUSY] + [QUIET] * 60))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(samples=50)))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 50
    assert all(s["quiet"] for s in record.to_json()["detail"]["last"])
    assert record.detail["message"] == (
        "not quiet in 1 of 50 samples: busy cores 2.00 against a limit of 1"
    )


# 3.0 and 4.0 busy cores. With BUSY they give three busy figures, so the busy sample a
# line names can be told apart from the first, the smallest and the largest of them.
BUSY3 = {0: (100, 0), 1: (100, 0), 2: (100, 0), 3: (0, 100)}
BUSY4 = {0: (100, 0), 1: (100, 0), 2: (100, 0), 3: (100, 0)}
# The last busy sample is BUSY3: neither the first, the smallest nor the largest one.
THREE_BUSY = [BUSY4, QUIET, BUSY, QUIET, BUSY3]


def test_without_a_wait_the_line_names_the_last_sample_that_was_not_quiet(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings(THREE_BUSY))
    record = _gate(tree, clock).check(make_ctx(gates=_settings()))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 5
    assert record.detail["message"] == (
        "not quiet in 3 of 5 samples: busy cores 3.00 against a limit of 1"
    )


def test_when_a_wait_runs_out_the_line_names_the_last_sample_that_was_not_quiet(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings(THREE_BUSY))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True, max_wait_s=10.0)))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 5
    assert record.detail["message"] == (
        "the machine did not become quiet within 10 s: busy cores 3.00 against a limit of 1"
    )


@pytest.mark.parametrize(
    ("steps", "pids", "reason"),
    [
        ([QUIET] * 5, (4242,), "1 other compute process(es) on the selected GPUs"),
        ([QUIET] * 5, None, "the GPU processes could not be read"),
        (
            [BUSY] * 5,
            (4242, 4343),
            "busy cores 2.00 against a limit of 1; "
            "2 other compute process(es) on the selected GPUs",
        ),
    ],
    ids=["another-process", "unreadable", "cores-and-processes"],
)
def test_when_a_wait_runs_out_the_line_gives_the_gpu_reason(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Any,
    readings: Any,
    fake_gpu: Any,
    steps: list[dict[int, tuple[int, int]]],
    pids: tuple[int, ...] | None,
    reason: str,
) -> None:
    stat_script(readings(steps))
    gpu = fake_gpu(pids=[pids])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    settings = _settings(wait=True, max_wait_s=10.0)
    record = gate.check(make_ctx(gates=settings, launch=LaunchSettings(gpus="0,1")))
    assert record.status == "fail"
    assert record.detail["samples_taken"] == 5
    assert record.detail["message"] == f"the machine did not become quiet within 10 s: {reason}"


def test_wait_quiet_prints_the_gpu_reason_when_the_wait_runs_out(
    tree: Any, clock: Any, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    # Every sample is quiet by the busy cores; the selected GPU holds another compute process.
    stat_script(readings([QUIET] * 10))
    gpu = fake_gpu(pids=[(4242,)])
    gate, run, ran = _wait(tree, clock, gate={"gpu_sources": lambda gpus: gpu})
    err = io.StringIO()
    with pytest.raises(Refusal) as caught:
        wait_then_run(
            ["make", "bench"],
            gates=_settings(samples=2, interval_s=1.0, max_wait_s=4.0),
            launch=LaunchSettings(gpus="0"),
            gate=gate,
            run=run,
            err=err,
        )
    assert caught.value.code == "E_GATE_FAILED"
    assert caught.value.exit_code == 4
    assert caught.value.message == (
        "the command was not run: the machine did not become quiet within 4 s: "
        "1 other compute process(es) on the selected GPUs"
    )
    assert caught.value.detail["record"]["detail"]["samples_taken"] == 4
    assert ran == []
    assert err.getvalue() == (
        "pairbench: check quiet: fail: the machine did not become quiet within 4 s: "
        "1 other compute process(es) on the selected GPUs\n"
    )


def test_when_a_wait_runs_out_the_line_names_a_last_sample_busy_only_through_the_gpu(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    # The first sample is busy by the busy cores; the third is quiet by them and busy only
    # through another compute process on the GPUs, so it is the last sample that was not quiet.
    stat_script(readings([BUSY] + [QUIET] * 4))
    gpu = fake_gpu(pids=[(), (), (4242,), ()])
    gate = _gate(tree, clock, gpu_sources=lambda gpus: gpu)
    settings = _settings(wait=True, max_wait_s=10.0)
    record = gate.check(make_ctx(gates=settings, launch=LaunchSettings(gpus="0")))
    assert record.status == "fail"
    assert record.to_json()["detail"]["last"] == [
        {"busy_cores": 2.0, "gpu_processes": 0, "quiet": False},
        {"busy_cores": 1.0, "gpu_processes": 0, "quiet": True},
        {"busy_cores": 1.0, "gpu_processes": 1, "quiet": False},
        {"busy_cores": 1.0, "gpu_processes": 0, "quiet": True},
        {"busy_cores": 1.0, "gpu_processes": 0, "quiet": True},
    ]
    assert record.detail["message"] == (
        "the machine did not become quiet within 10 s: "
        "1 other compute process(es) on the selected GPUs"
    )


def test_the_wait_quiet_docstring_says_a_slow_read_can_end_the_wait_later() -> None:
    # The time is looked at after each sample, so the wait can end past its limit.
    text = " ".join((wait_then_run.__doc__ or "").split())
    assert "waits up to" not in text
    assert (
        "until the machine is quiet or ``gates.quiet.max_wait_s`` has passed; the time is "
        "looked at after each sample, so a slow read can end the wait later."
    ) in text


def test_the_quiet_check_that_does_not_wait_reads_no_readiness_check(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    stop = _Ready("stop_file", ["fail"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings()))
    assert record.status == "pass"
    assert stop.calls == 0
    assert "readiness" not in record.detail
    assert "ready" not in record.to_json()["detail"]["last"][0]


def test_the_recheck_reads_no_readiness_check(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    stop = _Ready("stop_file", ["fail"])
    gate = _gate(tree, clock, readiness=[stop])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True), phase="recheck"))
    assert record.status == "pass"
    assert stop.calls == 0


def test_a_readiness_check_that_is_off_is_not_read_while_waiting(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    stop = _Ready("stop_file", ["pass"])
    memory = _Ready("gpu_memory", ["fail"])
    locks = _Ready("check_locks", ["fail"])
    gate = _gate(tree, clock, readiness=[stop, memory, locks])
    record = gate.check(make_ctx(gates=_ready_settings(wait=True)))
    assert record.status == "pass"
    assert (stop.calls, memory.calls, locks.calls) == (5, 0, 0)
    assert record.detail["readiness"] == ("stop_file",)


def test_a_waiting_check_with_no_readiness_check_on_keeps_its_record(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    record = _gate(tree, clock).check(make_ctx(gates=_settings(wait=True)))
    assert record.status == "pass"
    assert "readiness" not in record.detail
    assert "not_ready" not in record.detail
    assert "ready" not in record.to_json()["detail"]["last"][0]


def test_the_built_in_stop_file_check_is_read_while_waiting(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, tmp_path: Any
) -> None:
    stop = tmp_path / "hold.stop"
    stop.write_text("")
    cumulative_readings = readings([QUIET] * 10)
    tree.stat(cumulative_readings[0])

    def advance(count: int) -> None:
        tree.stat(cumulative_readings[min(count, len(cumulative_readings) - 1)])
        if count == 3:
            stop.unlink()

    clock.on_sleep = advance
    gate = _gate(tree, clock)
    record = gate.check(make_ctx(gates=_ready_settings(wait=True, stop_file=str(stop))))
    assert record.status == "pass"
    # Samples 1 and 2 see the stop file; it is gone before sample 3 is read.
    assert record.detail["samples_taken"] == 7


def test_the_built_in_gpu_memory_check_reads_the_quiet_check_gpu_source(
    tree: Any, clock: Any, make_ctx: Ctx, stat_script: Any, readings: Any, fake_gpu: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    gpu = fake_gpu(pids=[()], free=[((0, 1000.0),), ((0, 1000.0),), ((0, 4000.0),)])
    seen: list[str] = []
    gate = _gate(tree, clock, gpu_sources=lambda gpus: seen.append(gpus) or gpu)
    settings = _ready_settings(wait=True, stop_file=None, min_gpu_free_mib=2000.0)
    record = gate.check(make_ctx(gates=settings, launch=LaunchSettings(gpus="0")))
    assert record.status == "pass"
    assert record.detail["samples_taken"] == 7
    assert gpu.free_reads == 7
    assert set(seen) == {"0"}


# --- gate wait-quiet with readiness checks -------------------------------------


def _wait_ready(
    tree: Any, clock: Any, readiness: list[_Ready], settings: GateSettings
) -> tuple[list[tuple[str, ...]], io.StringIO, Refusal | None]:
    ran: list[tuple[str, ...]] = []
    err = io.StringIO()
    gate = _gate(tree, clock, readiness=readiness)

    def run(command: Any) -> int:
        ran.append(tuple(command))
        return 0

    try:
        wait_then_run(
            ["make", "bench"], gates=settings, launch=LaunchSettings(), gate=gate, run=run, err=err
        )
    except Refusal as refusal:
        return ran, err, refusal
    return ran, err, None


def test_wait_quiet_runs_each_readiness_check_once_after_the_wait_then_the_command(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    stop = _Ready("stop_file", ["pass"])
    locks = _Ready("check_locks", ["pass"])
    settings = _ready_settings(check_locks=("made-up/a.lock",))
    ran, err, refusal = _wait_ready(tree, clock, [stop, locks], settings)
    assert refusal is None
    assert ran == [("make", "bench")]
    assert (stop.calls, locks.calls) == (6, 6)
    assert err.getvalue() == ""


def test_wait_quiet_with_the_stop_file_still_present_names_only_the_stop_file(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    stop = _Ready("stop_file", ["fail"], message="the stop file is present")
    ran, err, refusal = _wait_ready(tree, clock, [stop], _ready_settings(max_wait_s=10.0))
    assert refusal is not None
    assert refusal.code == "E_GATE_FAILED"
    assert refusal.exit_code == 4
    assert refusal.message == "the command was not run: the stop file is present"
    assert refusal.detail["record"]["name"] == "stop_file"
    assert ran == []
    assert err.getvalue() == "pairbench: check stop_file: fail: the stop file is present\n"


def test_wait_quiet_prints_each_check_that_did_not_pass_and_names_the_quiet_check_first(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([BUSY] * 10))
    memory = _Ready("gpu_memory", ["unavailable"], message="no GPU is visible here")
    settings = _ready_settings(max_wait_s=4.0, samples=2, stop_file=None, min_gpu_free_mib=2000.0)
    ran, err, refusal = _wait_ready(tree, clock, [memory], settings)
    assert refusal is not None
    assert refusal.code == "E_GATE_FAILED"
    assert refusal.message == (
        "the command was not run: the machine did not become quiet within 4 s: "
        "busy cores 2.00 against a limit of 1"
    )
    assert refusal.detail["record"]["name"] == "quiet"
    assert ran == []
    assert err.getvalue() == (
        "pairbench: check quiet: fail: the machine did not become quiet within 4 s: "
        "busy cores 2.00 against a limit of 1\n"
        "pairbench: check gpu_memory: unavailable: no GPU is visible here\n"
    )


def test_wait_quiet_names_the_first_readiness_check_in_table_order(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 10))
    stop = _Ready("stop_file", ["unavailable"], message="the stop file could not be looked up")
    locks = _Ready("check_locks", ["fail"], message="check-only lock 1 of 1 is held")
    settings = _ready_settings(max_wait_s=10.0, check_locks=("made-up/a.lock",))
    ran, err, refusal = _wait_ready(tree, clock, [locks, stop], settings)
    assert refusal is not None
    assert refusal.code == "E_GATE_UNAVAILABLE"
    assert refusal.message == "the command was not run: the stop file could not be looked up"
    assert ran == []
    assert err.getvalue() == (
        "pairbench: check stop_file: unavailable: the stop file could not be looked up\n"
        "pairbench: check check_locks: fail: check-only lock 1 of 1 is held\n"
    )


def test_wait_quiet_with_no_readiness_check_on_runs_none(
    tree: Any, clock: Any, stat_script: Any, readings: Any
) -> None:
    stat_script(readings([QUIET] * 5))
    stop = _Ready("stop_file", ["fail"])
    ran, err, refusal = _wait_ready(tree, clock, [stop], _settings())
    assert refusal is None
    assert ran == [("make", "bench")]
    assert err.getvalue() == ""
    assert stop.calls == 0
