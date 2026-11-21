# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The witness sampler, the machine checks as services, and what a status means under a mode."""

from __future__ import annotations

import io
import threading
from typing import Any

import pytest

from pairbench import api, model
from pairbench.api import CpuFacts, ToolCpus
from pairbench.errors import Refusal
from pairbench.gates.base import (
    MAX_ANCESTRY,
    HostChecks,
    HostWitnessSampler,
    ancestors,
    judge,
    machine_checks,
    report,
)
from pairbench.gates.occupancy import Probe
from pairbench.gates.platform import Affinity
from pairbench.model import (
    DiscardThresholds,
    GateMode,
    GateRecord,
    GateStatus,
    RoundWitness,
    Witness,
)

EXIT_MACHINE = 4
OWN, CHILD, STRANGER, SECOND, GRANDCHILD = 4242, 4300, 6000, 7000, 7100

# Per CPU (busy ticks, idle ticks) before and after a launch of two seconds:
# CPUs 0, 1 and 2 fully busy, CPU 3 idle.
BEFORE = {0: (1000, 1000), 1: (1000, 1000), 2: (1000, 1000), 3: (1000, 1000)}
AFTER = {0: (1200, 1000), 1: (1200, 1000), 2: (1200, 1000), 3: (1000, 1200)}
ELAPSED_S = 2.0
OWN_CPU_S = 1.0  # half a core over the two seconds


def _processes(tree: Any) -> None:
    tree.process(OWN, 1, "launch")
    tree.process(CHILD, OWN, "worker")
    tree.process(STRANGER, 1, "other")
    tree.process(SECOND, 1, "launch")
    tree.process(GRANDCHILD, SECOND, "worker")


def _sampler(tree: Any, clock: Any, **kw: Any) -> HostWitnessSampler:
    tree.stat(BEFORE)
    sampler = HostWitnessSampler(root=tree.root, clock=clock, poll_s=None, **kw)
    tree.stat(AFTER)
    clock.now += ELAPSED_S
    return sampler


def test_ancestors_follow_the_parent_ids(tree: Any) -> None:
    tree.process(500, 400, "a) b")
    tree.process(400, 300)
    tree.process(300, 1)
    assert ancestors(tree.root, 500) == (400, 300, 1)


def test_ancestors_stop_at_a_process_that_cannot_be_read(tree: Any) -> None:
    tree.process(500, 400)
    assert ancestors(tree.root, 500) == (400,)
    assert ancestors(tree.root, 999) == ()
    tree.write("proc/600/stat", "600 (x) S\n")
    assert ancestors(tree.root, 600) == ()


def test_ancestors_stop_at_a_loop_and_at_the_limit(tree: Any) -> None:
    tree.process(10, 11)
    tree.process(11, 10)
    assert ancestors(tree.root, 10) == (11,)
    for pid in range(2000, 2000 + MAX_ANCESTRY + 5):
        tree.process(pid, pid + 1)
    assert len(ancestors(tree.root, 2000)) == MAX_ANCESTRY


def test_witness_busy_cores_leave_out_the_launch_itself(tree: Any, clock: Any) -> None:
    witness = _sampler(tree, clock).stop(OWN_CPU_S)
    assert witness == Witness(busy_cores=2.5)


def test_witness_on_the_cpus_sharing_a_cache(tree: Any, clock: Any) -> None:
    witness = _sampler(tree, clock, cache_cpus=frozenset({0, 1})).stop(OWN_CPU_S)
    assert witness == Witness(busy_cores=2.5, busy_cores_cache=1.5)


def test_witness_never_below_zero(tree: Any, clock: Any) -> None:
    assert _sampler(tree, clock).stop(10.0) == Witness(busy_cores=0.0)


def test_witness_without_the_launch_cpu_time_counts_the_launch_in(tree: Any, clock: Any) -> None:
    witness = _sampler(tree, clock, cache_cpus=frozenset({0})).stop(None)
    assert witness == Witness(
        busy_cores=3.0, busy_cores_cache=1.0, includes_launch=("busy_cores", "busy_cores_cache")
    )


class ToolCpu:
    """The tool's own CPU time in seconds: each reading in turn, the last one repeated."""

    def __init__(self, *readings: float) -> None:
        self.readings = list(readings)

    def __call__(self) -> float:
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


THRESHOLDS = DiscardThresholds()
# Per CPU before and after: CPU 0 fully busy, CPU 1 half busy, CPUs 2 and 3 idle.
UNDER_AFTER = {0: (1200, 1000), 1: (1100, 1100), 2: (1000, 1200), 3: (1000, 1200)}


def test_a_pinned_run_counts_the_load_outside_the_pinned_set(tree: Any, clock: Any) -> None:
    # The tool used 0.4 s of CPU over the 2 s launch: 0.2 cores, left out.
    def pinned(cpus: set[int], own_cpu_s: float | None) -> Witness:
        sampler = _sampler(tree, clock, pinned=frozenset(cpus), tool_cpu_s=ToolCpu(0.0, 0.4))
        return sampler.stop(own_cpu_s)

    # Pinned to CPUs 2 and 3: CPUs 0 and 1 outside the set are busy, 2 cores.
    quiet = pinned({2, 3}, None)
    assert quiet == Witness(busy_cores=1.8)
    assert model.exceeded(quiet, THRESHOLDS) == ()
    # Pinned to CPU 3: CPUs 0, 1 and 2 outside the set are busy, 3 cores. The
    # load outside the set decides, whatever the launch reports of itself.
    busy = pinned({3}, None)
    assert busy == Witness(busy_cores=2.8)
    assert model.exceeded(busy, THRESHOLDS) == ("busy_cores",)
    assert pinned({3}, OWN_CPU_S) == busy


def test_a_pinned_run_with_every_cpu_pinned_falls_back_to_the_unpinned_rules(
    tree: Any, clock: Any
) -> None:
    every = frozenset(range(4))
    sampler = _sampler(tree, clock, pinned=every, tool_cpu_s=ToolCpu(0.0, 0.4))
    assert sampler.stop(OWN_CPU_S) == Witness(busy_cores=2.5)


def test_an_unpinned_image_launch_under_the_threshold_is_not_disturbed(
    tree: Any, clock: Any
) -> None:
    tree.stat(BEFORE)
    sampler = HostWitnessSampler(root=tree.root, clock=clock, poll_s=None)
    tree.stat(UNDER_AFTER)
    clock.now += ELAPSED_S
    # An image launch reports no CPU time of its own: counted with the launch in.
    witness = sampler.stop(None)
    assert witness == Witness(busy_cores=1.5, includes_launch=("busy_cores",))
    assert model.exceeded(witness, THRESHOLDS) == ()
    assert model.undecided(witness, THRESHOLDS) == ()


def test_an_unpinned_image_launch_over_the_threshold_is_undecided(tree: Any, clock: Any) -> None:
    witness = _sampler(tree, clock).stop(None)
    assert witness == Witness(busy_cores=3.0, includes_launch=("busy_cores",))
    # Not exceeding: the round is kept. Not a pass: the launch is undecided.
    assert model.exceeded(witness, THRESHOLDS) == ()
    assert model.undecided(witness, THRESHOLDS) == ("busy_cores",)
    kept = model.set_aside(THRESHOLDS, [RoundWitness(round=1, name="new", witness=witness)])
    assert kept.rounds == ()


@pytest.mark.parametrize("own_cpu_s", [float("nan"), float("inf"), -1.0])
def test_witness_with_a_launch_cpu_time_that_is_no_duration_failed(
    tree: Any, clock: Any, own_cpu_s: float
) -> None:
    witness = _sampler(tree, clock, cache_cpus=frozenset({0})).stop(own_cpu_s)
    assert witness == Witness(failed=("busy_cores", "busy_cores_cache"))


def test_witness_counters_unreadable_at_stop_failed(tree: Any, clock: Any) -> None:
    sampler = _sampler(tree, clock)
    (tree.path / "proc" / "stat").unlink()
    assert sampler.stop(OWN_CPU_S) == Witness(failed=("busy_cores",))


def test_witness_with_no_clock_tick_failed(tree: Any, clock: Any) -> None:
    tree.stat(BEFORE)
    sampler = HostWitnessSampler(root=tree.root, clock=clock, poll_s=None)
    clock.now += ELAPSED_S
    assert sampler.stop(OWN_CPU_S) == Witness(failed=("busy_cores",))


def test_witness_cache_set_unreadable_failed(tree: Any, clock: Any) -> None:
    witness = _sampler(tree, clock, cache_failed=True).stop(OWN_CPU_S)
    assert witness == Witness(busy_cores=2.5, failed=("busy_cores_cache",))


def test_witness_on_a_platform_without_one_applies_nowhere(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    gpu = fake_gpu(pids=[(STRANGER,)])
    sampler = _sampler(tree, clock, applies=False, cache_cpus=frozenset({0}), gpu=gpu)
    assert sampler.stop(OWN_CPU_S) == Witness()
    assert gpu.reads == 0


def test_witness_counts_other_gpu_processes(tree: Any, clock: Any, fake_gpu: Any) -> None:
    _processes(tree)
    gpu = fake_gpu(pids=[(OWN, CHILD, STRANGER), ()], masks=[(0,)])
    witness = _sampler(tree, clock, gpu=gpu).stop(OWN_CPU_S, own_pid=OWN)
    assert witness == Witness(busy_cores=2.5, gpu_other_processes=1, gpu_throttle_events=0)


def test_witness_leaves_out_the_second_run_and_its_descendants(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    _processes(tree)
    gpu = fake_gpu(pids=[(OWN, CHILD), (SECOND, GRANDCHILD, STRANGER)])
    witness = _sampler(tree, clock, gpu=gpu).stop(OWN_CPU_S, own_pid=OWN, second_pid=SECOND)
    assert witness.gpu_other_processes == 1


def test_witness_remembers_ancestors_of_a_process_that_has_ended(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    _processes(tree)
    gpu = fake_gpu(pids=[(CHILD,), ()])
    sampler = _sampler(tree, clock, gpu=gpu)
    (tree.path / "proc" / str(CHILD) / "stat").unlink()
    assert sampler.stop(OWN_CPU_S, own_pid=OWN).gpu_other_processes == 0


def test_witness_without_the_launch_id_counts_every_gpu_process(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    _processes(tree)
    gpu = fake_gpu(pids=[(OWN, CHILD, STRANGER)])
    assert _sampler(tree, clock, gpu=gpu).stop(OWN_CPU_S).gpu_other_processes == 3


def test_noting_the_launch_process_reads_nothing(tree: Any, clock: Any, fake_gpu: Any) -> None:
    _processes(tree)
    gpu = fake_gpu(pids=[(OWN, CHILD, STRANGER)])
    sampler = _sampler(tree, clock, gpu=gpu)
    reads = gpu.reads
    (tree.path / "proc" / "stat").rename(tree.path / "proc" / "stat.away")
    sampler.own_process(OWN)
    assert gpu.reads == reads
    (tree.path / "proc" / "stat.away").rename(tree.path / "proc" / "stat")
    assert sampler.stop(OWN_CPU_S).gpu_other_processes == 1


def test_witness_gpu_read_that_fails_once_failed(tree: Any, clock: Any, fake_gpu: Any) -> None:
    gpu = fake_gpu(pids=[(), None, ()], masks=[(0,), (0,), None])
    sampler = _sampler(tree, clock, gpu=gpu)
    sampler.poll()
    witness = sampler.stop(OWN_CPU_S)
    assert witness == Witness(busy_cores=2.5, failed=("gpu_other_processes", "gpu_throttle_events"))


def test_witness_gpu_read_that_raises_failed(tree: Any, clock: Any) -> None:
    class Broken:
        def processes(self) -> tuple[int, ...] | None:
            raise RuntimeError("made-up library error")

        def memory_used_mib(self) -> float | None:
            return None

        def reason_masks(self) -> tuple[int, ...] | None:
            raise RuntimeError("made-up library error")

    witness = _sampler(tree, clock, gpu=Broken()).stop(OWN_CPU_S)
    assert witness.failed == ("gpu_other_processes", "gpu_throttle_events")


def test_witness_counts_each_reason_that_turns_on_per_gpu(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    gpu = fake_gpu(masks=[(0x4, 0x0), (0x1, 0x1), (0x1 | 0x40, 0x8)])
    sampler = _sampler(tree, clock, gpu=gpu)
    sampler.poll()
    assert sampler.stop(OWN_CPU_S).gpu_throttle_events == 3


def test_witness_counts_a_reason_held_over_many_polls_once(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    # The same rule as the power sampler's count: how often the GPU is read
    # does not change the count.
    gpu = fake_gpu(masks=[(0x4, 0x8), (0x4, 0x8), (0x4, 0x8), (0x0, 0x8), (0x4, 0x8)])
    sampler = _sampler(tree, clock, gpu=gpu)
    for _ in range(3):
        sampler.poll()
    assert sampler.stop(OWN_CPU_S).gpu_throttle_events == 3


def test_stop_never_raises(tree: Any, fake_gpu: Any) -> None:
    times = iter([100.0])

    def clock() -> float:
        return next(times)

    tree.stat(BEFORE)
    sampler = HostWitnessSampler(
        root=tree.root, clock=clock, cache_cpus=frozenset({0}), gpu=fake_gpu(), poll_s=None
    )
    witness = sampler.stop(OWN_CPU_S)
    assert witness == Witness().with_failed(
        "busy_cores", "busy_cores_cache", "gpu_other_processes", "gpu_throttle_events"
    )


def test_a_second_stop_gives_the_first_answer(tree: Any, clock: Any, fake_gpu: Any) -> None:
    gpu = fake_gpu()
    sampler = _sampler(tree, clock, gpu=gpu)
    first = sampler.stop(OWN_CPU_S)
    reads = gpu.reads
    tree.stat(BEFORE)
    assert sampler.stop(None) is first
    assert gpu.reads == reads


def test_the_witness_thread_polls_until_stopped(tree: Any, clock: Any) -> None:
    polled = threading.Event()

    class Counting:
        calls = 0

        def processes(self) -> tuple[int, ...] | None:
            Counting.calls += 1
            if Counting.calls >= 3:
                polled.set()
            return ()

        def memory_used_mib(self) -> float | None:
            return 0.0

        def reason_masks(self) -> tuple[int, ...] | None:
            return (0,)

    tree.stat(BEFORE)
    sampler = HostWitnessSampler(root=tree.root, clock=clock, gpu=Counting(), poll_s=0.001)
    tree.stat(AFTER)
    clock.now += ELAPSED_S
    assert polled.wait(5.0)
    witness = sampler.stop(OWN_CPU_S)
    assert witness.gpu_other_processes == 0
    alive = [t for t in threading.enumerate() if t.name == "pairbench-witness"]
    assert alive == []


def test_the_witness_thread_is_named_and_daemon(tree: Any, clock: Any, fake_gpu: Any) -> None:
    tree.stat(BEFORE)
    sampler = HostWitnessSampler(root=tree.root, clock=clock, gpu=fake_gpu(), poll_s=60.0)
    named = [t for t in threading.enumerate() if t.name == "pairbench-witness"]
    try:
        assert len(named) == 1
        assert named[0].daemon is True
    finally:
        sampler.stop(OWN_CPU_S)
    assert not named[0].is_alive()


def _checks(tree: Any, clock: Any, **kw: Any) -> HostChecks:
    kw.setdefault("system", "linux")
    kw.setdefault("tool_cpu_s", ToolCpu(0.0))
    return HostChecks(root=tree.root, clock=clock, sleep=clock.sleep, poll_s=None, **kw)


def test_machine_checks_offer_every_call_of_the_interface() -> None:
    calls = [n for n, v in vars(api.MachineChecks).items() if callable(v) and n[0] != "_"]
    assert calls
    checks = machine_checks()
    assert isinstance(checks, HostChecks)
    for name in calls:
        assert callable(getattr(checks, name))


def test_the_machine_checks_make_one_gpu_source_per_selection(
    tree: Any, clock: Any, fake_gpu: Any
) -> None:
    made: list[str] = []

    def sources(gpus: str) -> Any:
        made.append(gpus)
        return fake_gpu()

    tree.stat(BEFORE)
    checks = _checks(tree, clock, gpu_sources=sources)
    assert checks.gpu_probe(None) is None
    assert isinstance(checks.gpu_probe("0"), Probe)
    checks.gpu_probe("0")
    checks.start_witness(None, "0").stop(OWN_CPU_S)
    checks.start_witness(None, "1").stop(OWN_CPU_S)
    assert made == ["0", "1"]


def test_the_machine_checks_read_the_cache_set_once(tree: Any, clock: Any) -> None:
    tree.llc([[0, 1], [2, 3]])
    checks = _checks(tree, clock)

    def launch() -> Witness:
        tree.stat(BEFORE)
        sampler = checks.start_witness("0", None)
        tree.stat(AFTER)
        clock.now += ELAPSED_S
        return sampler.stop(OWN_CPU_S)

    # Pinned to CPU 0: CPUs 1 and 2 outside the set are busy.
    assert launch() == Witness(busy_cores=2.0, busy_cores_cache=1.5)
    for cpu in range(4):
        for index in range(3):
            (tree.path / f"sys/devices/system/cpu/cpu{cpu}/cache/index{index}/level").unlink()
    assert launch() == Witness(busy_cores=2.0, busy_cores_cache=1.5)


def test_the_machine_checks_witness_a_cache_set_they_cannot_read(tree: Any, clock: Any) -> None:
    tree.stat(BEFORE)
    sampler = _checks(tree, clock).start_witness("0-1", None)
    tree.stat(AFTER)
    clock.now += ELAPSED_S
    # Pinned to CPUs 0 and 1: CPU 2 outside the set is busy.
    assert sampler.stop(OWN_CPU_S) == Witness(busy_cores=1.0, failed=("busy_cores_cache",))


def test_the_machine_checks_witness_nothing_on_macos(tree: Any, clock: Any, fake_gpu: Any) -> None:
    gpu = fake_gpu()
    checks = _checks(tree, clock, system="darwin", gpu_sources=lambda gpus: gpu)
    assert checks.start_witness("0-1", "0").stop(OWN_CPU_S) == Witness()
    assert gpu.reads == 0


def test_the_machine_checks_describe_and_leave_the_pinned_cpus(tree: Any, clock: Any) -> None:
    tree.online("0-3")
    tree.llc([[0, 1], [2, 3]])
    for cpu in range(4):
        tree.midr(cpu, "0x00000000410fd801")
        tree.khz(cpu, 2000000)
    moves: list[tuple[int, frozenset[int]]] = []
    affinity = Affinity(
        get=lambda: frozenset(range(4)),
        set=lambda task, cpus: moves.append((task, cpus)),
        threads=lambda: (),
    )
    checks = _checks(tree, clock, affinity=affinity)
    facts = checks.cpu_facts("2-3", allow_mixed=False)
    assert isinstance(facts, CpuFacts)
    assert facts.cache_domains == ("2-3",)
    assert facts.mixed is False
    assert checks.leave_pinned("2-3") == ToolCpus(cpus="0-1")
    assert moves == [(0, frozenset({0, 1}))]


def _moving(moves: list[tuple[int, frozenset[int]]], current: frozenset[int]) -> Affinity:
    where = {0: current}

    def move(task: int, cpus: frozenset[int]) -> None:
        moves.append((task, cpus))
        where[task] = cpus

    return Affinity(get=lambda: where[0], set=move, threads=lambda: (7001,))


def test_the_machine_checks_put_the_tool_back_where_it_was(tree: Any, clock: Any) -> None:
    moves: list[tuple[int, frozenset[int]]] = []
    checks = _checks(tree, clock, affinity=_moving(moves, frozenset(range(4))))
    assert checks.leave_pinned("2-3") == ToolCpus(cpus="0-1")
    moves.clear()
    checks.restore_cpus()
    assert moves == [(0, frozenset(range(4))), (7001, frozenset(range(4)))]
    moves.clear()
    checks.restore_cpus()
    assert moves == []


@pytest.mark.parametrize(("cpus", "current"), [(None, range(4)), ("0-3", range(4))])
def test_the_machine_checks_restore_nothing_when_the_tool_did_not_move(
    tree: Any, clock: Any, cpus: str | None, current: range
) -> None:
    moves: list[tuple[int, frozenset[int]]] = []
    checks = _checks(tree, clock, affinity=_moving(moves, frozenset(current)))
    assert checks.leave_pinned(cpus).cpus is None
    checks.restore_cpus()
    assert moves == []


RECORD_MESSAGE = "made-up reason"


def _record(name: str, mode: GateMode, status: GateStatus, message: str = RECORD_MESSAGE) -> Any:
    detail = {"message": message} if message else {}
    return GateRecord(name=name, mode=mode, status=status, detail=detail)


@pytest.mark.parametrize(
    ("status", "code", "line"),
    [
        ("fail", "E_GATE_FAILED", "check quiet failed: made-up reason"),
        ("degraded", "E_GATE_UNAVAILABLE", "check quiet is degraded: made-up reason"),
        ("unavailable", "E_GATE_UNAVAILABLE", "check quiet is unavailable: made-up reason"),
    ],
)
def test_enforce_refuses_a_check_that_did_not_pass(
    status: GateStatus, code: str, line: str
) -> None:
    refusal = judge(_record("quiet", "enforce", status))
    assert isinstance(refusal, Refusal)
    assert refusal.code == code
    assert refusal.exit_code == EXIT_MACHINE
    assert refusal.message == line


def test_enforce_without_a_reason_names_the_status() -> None:
    refusal = judge(_record("census", "enforce", "unavailable", message=""))
    assert refusal is not None
    assert refusal.message == "check census is unavailable: unavailable"


@pytest.mark.parametrize("mode", ["warn", "off"])
@pytest.mark.parametrize("status", ["pass", "fail", "degraded", "unavailable"])
def test_warn_and_off_refuse_nothing(mode: GateMode, status: GateStatus) -> None:
    assert judge(_record("quiet", mode, status)) is None


def test_enforce_lets_a_passed_check_through() -> None:
    assert judge(_record("quiet", "enforce", "pass", message="")) is None


def test_report_prints_a_check_that_did_not_pass_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sys

    assert report(_record("cpus", "warn", "degraded"), sys.stderr) is True
    assert report(_record("cpus", "warn", "pass", message=""), sys.stderr) is False
    out, err = capsys.readouterr()
    assert out == ""
    assert err == "pairbench: check cpus: degraded: made-up reason\n"


def test_report_on_a_closed_stream_does_not_raise() -> None:
    stream = io.StringIO()
    stream.close()
    assert report(_record("cpus", "warn", "fail"), stream) is True


# --- a GPU the machine does not have -----------------------------------------


@pytest.mark.parametrize(
    ("gpus", "message"),
    [
        ("2", "gpus 2: GPU 2 is not on this machine; the GPUs here are 0, 1"),
        ("1,3,2", "gpus 1,3,2: GPUs 3, 2 are not on this machine; the GPUs here are 0, 1"),
    ],
)
def test_a_gpu_the_machine_does_not_have_is_refused_naming_the_gpus_it_has(
    tree: Any, clock: Any, fake_gpu: Any, gpus: str, message: str
) -> None:
    checks = _checks(tree, clock, gpu_sources=lambda g: fake_gpu(indices=(0, 1)))
    with pytest.raises(Refusal) as caught:
        checks.gpu_probe(gpus)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2
    assert caught.value.message == message


def test_a_gpu_on_a_machine_with_none_is_refused(tree: Any, clock: Any, fake_gpu: Any) -> None:
    checks = _checks(tree, clock, gpu_sources=lambda g: fake_gpu(indices=()))
    with pytest.raises(Refusal) as caught:
        checks.gpu_probe("0")
    assert caught.value.message == "gpus 0: GPU 0 is not on this machine; no GPU is visible here"


@pytest.mark.parametrize(
    ("gpus", "indices"),
    [("1", (0, 1)), ("1,0", (0, 1)), ("all", ()), ("0", None)],
    ids=["present", "both-present", "all", "unreadable"],
)
def test_a_selection_the_machine_has_or_cannot_tell_gets_a_probe(
    tree: Any, clock: Any, fake_gpu: Any, gpus: str, indices: tuple[int, ...] | None
) -> None:
    checks = _checks(tree, clock, gpu_sources=lambda g: fake_gpu(indices=indices))
    assert isinstance(checks.gpu_probe(gpus), Probe)
