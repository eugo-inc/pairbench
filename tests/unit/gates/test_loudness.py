# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every check that did not pass is loud in three places.

1. A line on standard error, and nothing on standard output.
2. A gate record for the capture.
3. An entry for ``machine_state.degraded`` in the results.

One test per path of each check that can end in fail, degraded or
unavailable.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from pairbench.gates.base import report
from pairbench.gates.census import CensusGate
from pairbench.gates.cpus import CpusGate
from pairbench.gates.quiet import QuietGate
from pairbench.model import Degraded, GateRecord, GateSettings, LaunchSettings, QuietSettings

Ctx = Callable[..., Any]
BUSY = {0: (100, 0), 1: (100, 0), 2: (0, 100), 3: (0, 100)}  # two busy cores per interval
IDLE = {0: (10, 90), 1: (10, 90), 2: (10, 90), 3: (10, 90)}  # under half a busy core


def _loud(
    record: GateRecord,
    capsys: pytest.CaptureFixture[str],
    *,
    name: str,
    mode: str,
    status: str,
    message: str,
) -> None:
    assert report(record, sys.stderr) is True
    out, err = capsys.readouterr()
    assert out == ""
    assert err == f"pairbench: check {name}: {status}: {message}\n"

    row = json.loads(json.dumps(record.to_json()))
    assert {k: row[k] for k in ("t", "name", "mode", "status")} == {
        "t": "gate",
        "name": name,
        "mode": mode,
        "status": status,
    }
    assert row["detail"]["message"] == message

    assert record.degraded() == Degraded(name=name, status=status, message=message)  # type: ignore[arg-type]


def _two_type_machine(tree: Any) -> None:
    tree.online("0-7")
    for cpu in range(4):
        tree.midr(cpu, "0x00000000410fd801")
    for cpu in range(4, 8):
        tree.midr(cpu, "0x00000000410fd4b0")
    tree.llc([[0, 1, 2, 3], [4, 5, 6, 7]])


def _cpus_ctx(make_ctx: Ctx, cpus: str, mode: str = "warn") -> Any:
    return make_ctx(mode=mode, launch=LaunchSettings(cpus=cpus))


def test_loud_cpus_mixed_set_fails(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_cpus_ctx(make_ctx, "3-4", "enforce"))
    _loud(
        record,
        capsys,
        name="cpus",
        mode="enforce",
        status="fail",
        message="the CPU set 3-4 mixes core types (arm-41-d4b, arm-41-d80); "
        "give --allow-mixed-core-types to run on it anyway",
    )


def test_loud_cpus_core_type_unreadable_is_degraded(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    tree.online("0-3")
    record = CpusGate(root=tree.root, system="linux").check(_cpus_ctx(make_ctx, "0-1"))
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="degraded",
        message="the core type of some pinned CPUs could not be read",
    )


def test_loud_cpus_offline_cpu_is_unavailable(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_cpus_ctx(make_ctx, "7-8"))
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="unavailable",
        message="CPUs 8 are not online on this machine",
    )


def test_loud_cpus_pinning_on_macos_is_unavailable(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = CpusGate(root=tree.root, system="darwin").check(_cpus_ctx(make_ctx, "0-1"))
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="unavailable",
        message="pinning to CPUs is not supported on this platform",
    )


def test_loud_cpus_outside_the_allowed_cpus_is_unavailable(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_type_machine(tree)
    tree.write("proc/self/cgroup", "0::/\n")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-5\n")
    record = CpusGate(root=tree.root, system="linux").check(_cpus_ctx(make_ctx, "4-7"))
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="unavailable",
        message="CPUs 6-7 are outside the CPUs this process may use",
    )


def test_loud_cpus_unreadable_cpus_are_unavailable(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = CpusGate(root=tree.root, system="linux").check(make_ctx())
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="unavailable",
        message="the CPUs could not be read",
    )


def test_loud_cpus_unpinned_core_types_unreadable_is_degraded(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    tree.online("0-3")
    record = CpusGate(root=tree.root, system="linux").check(make_ctx())
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="degraded",
        message="the core type of some CPUs could not be read",
    )


def test_loud_cpus_unpinned_on_macos_is_unavailable(
    tree: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = CpusGate(root=tree.root, system="darwin").check(make_ctx())
    _loud(
        record,
        capsys,
        name="cpus",
        mode="warn",
        status="unavailable",
        message="core types cannot be read on this platform",
    )


def _quiet(tree: Any, clock: Any, system: str = "linux", **kw: Any) -> QuietGate:
    return QuietGate(root=tree.root, system=system, clock=clock, sleep=clock.sleep, **kw)  # type: ignore[arg-type]


def _one_sample() -> GateSettings:
    return GateSettings(quiet=QuietSettings(samples=1))


def test_loud_quiet_busy_machine_fails(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Callable[[Sequence[Any]], None],
    readings: Callable[..., Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    stat_script(readings([BUSY]))
    record = _quiet(tree, clock).check(make_ctx(gates=_one_sample(), in_container=True))
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="not quiet in 1 of 1 samples: busy cores 2.00 against a limit of 1 "
        "(machine-wide view from inside a container)",
    )


def test_loud_quiet_wait_that_gives_up_fails(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Callable[[Sequence[Any]], None],
    readings: Callable[..., Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    stat_script(readings([BUSY] * 4))
    gates = GateSettings(wait_quiet=True, quiet=QuietSettings(samples=1, max_wait_s=4.0))
    record = _quiet(tree, clock).check(make_ctx(gates=gates))
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="the machine did not become quiet within 4 s: busy cores 2.00 against a limit of 1",
    )


def test_loud_quiet_other_gpu_process_fails(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Callable[[Sequence[Any]], None],
    readings: Callable[..., Any],
    fake_gpu: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stat_script(readings([IDLE]))
    gpu = fake_gpu(pids=[(4242,)])
    record = _quiet(tree, clock, gpu_sources=lambda gpus: gpu).check(
        make_ctx(gates=_one_sample(), launch=LaunchSettings(gpus="0"))
    )
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="not quiet in 1 of 1 samples: 1 other compute process(es) on the selected GPUs",
    )


def test_loud_quiet_gpu_unreadable_fails(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Callable[[Sequence[Any]], None],
    readings: Callable[..., Any],
    fake_gpu: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stat_script(readings([IDLE]))
    gpu = fake_gpu(pids=[None])
    record = _quiet(tree, clock, gpu_sources=lambda gpus: gpu).check(
        make_ctx(gates=_one_sample(), launch=LaunchSettings(gpus="0"))
    )
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="not quiet in 1 of 1 samples: the GPU processes could not be read",
    )


def test_loud_quiet_busy_on_macos_fails(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _quiet(tree, clock, "darwin", loadavg=lambda: 3.0).check(make_ctx(gates=_one_sample()))
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="not quiet in 1 of 1 samples: load average 3.00 against a limit of 1",
    )


def test_loud_quiet_counters_unreadable_fails(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _quiet(tree, clock).check(make_ctx(gates=_one_sample()))
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="fail",
        message="not quiet in 1 of 1 samples: the busy cores could not be read",
    )


def test_loud_quiet_on_macos_is_degraded(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _quiet(tree, clock, "darwin", loadavg=lambda: 0.25).check(
        make_ctx(gates=_one_sample())
    )
    _loud(
        record,
        capsys,
        name="quiet",
        mode="warn",
        status="degraded",
        message="quiet by the load average only; busy cores are not read on this platform",
    )


def test_loud_quiet_on_another_platform_is_unavailable(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _quiet(tree, clock, "other").check(make_ctx(mode="off"))
    _loud(
        record,
        capsys,
        name="quiet",
        mode="off",
        status="unavailable",
        message="busy cores cannot be read on this platform",
    )


class Engine:
    """A container engine that lists one container and answers its CPU use from fixed text."""

    def __init__(self, stats: tuple[int, str]) -> None:
        self.answers = {
            "ps": (0, "aaaa0001\n"),
            "inspect": (0, "aaaa0001\t/neighbour-a\t\t1001\n"),
            "stats": stats,
        }

    def __call__(self, argv: Sequence[str], timeout_s: float) -> tuple[int, str]:
        return self.answers[argv[1]]


def _census(tree: Any, clock: Any, engine: Engine, found: bool = True) -> CensusGate:
    return CensusGate(
        root=tree.root,
        system="darwin",
        run=engine,
        which=lambda name: f"/usr/bin/{name}" if found and name == "docker" else None,
        clock=clock,
        sleep=clock.sleep,
    )


def test_loud_census_busy_neighbour_fails(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _census(tree, clock, Engine((0, "aaaa0001\t80.00%\n"))).check(make_ctx())
    _loud(
        record,
        capsys,
        name="census",
        mode="warn",
        status="fail",
        message="1 other container(s) used more than 0.5 cores where launches run "
        "(scoped to the engine's virtual machine)",
    )


def test_loud_census_unread_container_is_degraded(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _census(tree, clock, Engine((1, ""))).check(make_ctx())
    _loud(
        record,
        capsys,
        name="census",
        mode="warn",
        status="degraded",
        message="the CPU use of 1 container(s) could not be read "
        "(scoped to the engine's virtual machine)",
    )


def test_loud_census_without_an_engine_is_unavailable(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _census(tree, clock, Engine((0, "")), found=False).check(make_ctx(mode="enforce"))
    _loud(
        record,
        capsys,
        name="census",
        mode="enforce",
        status="unavailable",
        message="no container engine could be reached",
    )


def test_loud_census_engine_that_refuses_is_unavailable(
    tree: Any, clock: Any, make_ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = Engine((0, ""))
    engine.answers["ps"] = (1, "")
    record = _census(tree, clock, engine).check(make_ctx())
    _loud(
        record,
        capsys,
        name="census",
        mode="warn",
        status="unavailable",
        message="the container engine could not be reached",
    )


def test_a_passed_check_is_quiet_in_all_three_places(
    tree: Any,
    clock: Any,
    make_ctx: Ctx,
    stat_script: Callable[[Sequence[Any]], None],
    readings: Callable[..., Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    quiet = {0: (10, 90), 1: (10, 90), 2: (10, 90), 3: (10, 90)}
    stat_script(readings([quiet]))
    record = _quiet(tree, clock).check(make_ctx(gates=_one_sample()))
    assert record.status == "pass"
    assert report(record, sys.stderr) is False
    assert capsys.readouterr() == ("", "")
    assert "message" not in record.to_json()["detail"]
    assert record.degraded() is None
