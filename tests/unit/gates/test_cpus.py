# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Core types, the pinned-set refusals, where the tool runs, and the cpus check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from pairbench.api import CpuFacts, ToolCpus
from pairbench.errors import Refusal
from pairbench.gates.cpus import (
    CpusGate,
    core_types,
    cpu_facts,
    leave_pinned,
    return_home,
    tool_cpus_note,
)
from pairbench.gates.platform import Affinity
from pairbench.model import CpuGroup, GateSettings, LaunchSettings

X86_INFO = (
    "processor\t: 0\nvendor_id\t: VendorA\ncpu family\t: 6\nmodel\t\t: 77\n"
    "model name\t: made-up cpu\n\n"
    "processor\t: 1\nvendor_id\t: VendorA\ncpu family\t: 6\nmodel\t\t: 77\n\n"
    "processor\t: 2\nvendor_id\t: VendorA\ncpu family\t: 6\nmodel\t\t: 88\n\n"
    "processor\t: 3\nvendor_id\t: VendorA\ncpu family\t: 6\nmodel\t\t: 88\n"
)
ARM_INFO = (
    "processor\t: 0\nCPU implementer\t: 0x41\nCPU architecture: 8\nCPU part\t: 0xd0c\n\n"
    "processor\t: 1\nCPU implementer\t: 0x41\nCPU architecture: 8\nCPU part\t: 0xd0c\n"
)


def _two_type_machine(tree: Any) -> None:
    """CPUs 0-3 of one type, 4-7 of another, one cache per four CPUs, cgroup allows 0-7."""
    tree.online("0-7")
    for cpu in range(4):
        tree.midr(cpu, "0x00000000410fd801")
        tree.khz(cpu, 2000000)
    for cpu in range(4, 8):
        tree.midr(cpu, "0x00000000410fd4b0")
        tree.khz(cpu, 3000000 if cpu == 7 else 2900000)
    tree.llc([[0, 1, 2, 3], [4, 5, 6, 7]])
    tree.write("proc/self/cgroup", "0::/\n")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-7\n")


def test_core_type_from_the_arm_main_id_register(tree: Any) -> None:
    tree.midr(0, "0x00000000410fd4b0")
    tree.midr(1, "0x00000000410fd801")
    tree.midr(2, "0x00000000610f0000")
    assert core_types(tree.root, [0, 1, 2]) == {0: "arm-41-d4b", 1: "arm-41-d80", 2: "arm-61-000"}


def test_core_type_from_cpuinfo_on_x86(tree: Any) -> None:
    tree.write("proc/cpuinfo", X86_INFO)
    assert core_types(tree.root, range(4)) == {
        0: "VendorA-6-77",
        1: "VendorA-6-77",
        2: "VendorA-6-88",
        3: "VendorA-6-88",
    }


def test_core_type_from_cpuinfo_on_arm_agrees_with_the_register(tree: Any) -> None:
    tree.write("proc/cpuinfo", ARM_INFO)
    tree.midr(1, "0x00000000410fd0c1")
    assert core_types(tree.root, [0, 1]) == {0: "arm-41-d0c", 1: "arm-41-d0c"}


def test_hybrid_core_lists_add_the_kind_of_core(tree: Any) -> None:
    same = "".join(
        f"processor\t: {c}\nvendor_id\t: VendorA\ncpu family\t: 6\nmodel\t\t: 99\n\n"
        for c in range(4)
    )
    tree.write("proc/cpuinfo", same)
    tree.write("sys/devices/cpu_core/cpus", "0-1\n")
    tree.write("sys/devices/cpu_atom/cpus", "2-3\n")
    assert core_types(tree.root, range(4)) == {
        0: "VendorA-6-99-core",
        1: "VendorA-6-99-core",
        2: "VendorA-6-99-atom",
        3: "VendorA-6-99-atom",
    }


def test_frequency_stands_in_only_without_identification(tree: Any) -> None:
    tree.khz(0, 3600000)
    tree.khz(1, 2400000)
    tree.midr(2, "0x00000000410fd4b0")
    tree.khz(2, 1000000)
    assert core_types(tree.root, [0, 1, 2, 3]) == {
        0: "khz-3600000",
        1: "khz-2400000",
        2: "arm-41-d4b",
        3: "unknown",
    }


def test_facts_of_the_machine_when_nothing_is_pinned(tree: Any) -> None:
    _two_type_machine(tree)
    facts = cpu_facts(tree.root, "linux", None, allow_mixed=False)
    assert facts == CpuFacts(
        identity=(
            CpuGroup(cpus="0-3", key="arm-41-d80", max_khz=2000000),
            CpuGroup(cpus="4-7", key="arm-41-d4b", max_khz=3000000),
        ),
        cache_domains=("0-3", "4-7"),
        mixed=True,
    )


def test_facts_of_a_pinned_set_of_one_type(tree: Any) -> None:
    _two_type_machine(tree)
    facts = cpu_facts(tree.root, "linux", "5-6", allow_mixed=False)
    assert facts == CpuFacts(
        identity=(CpuGroup(cpus="5-6", key="arm-41-d4b", max_khz=2900000),),
        cache_domains=("4-7",),
        mixed=False,
    )


def test_a_set_that_mixes_core_types_is_refused(tree: Any) -> None:
    _two_type_machine(tree)
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "2-5", allow_mixed=False)
    assert caught.value.code == "E_CPUS_MIXED_TYPES"
    assert caught.value.exit_code == 4
    assert caught.value.message == (
        "the CPU set 2-5 mixes core types (arm-41-d4b, arm-41-d80); "
        "give --allow-mixed-core-types to run on it anyway"
    )


def test_a_mixed_set_is_described_when_allowed(tree: Any) -> None:
    _two_type_machine(tree)
    facts = cpu_facts(tree.root, "linux", "2-5", allow_mixed=True)
    assert facts.mixed is True
    assert [g.key for g in facts.identity] == ["arm-41-d80", "arm-41-d4b"]


def test_a_cpu_of_unknown_type_beside_known_ones_counts_as_mixed(tree: Any) -> None:
    _two_type_machine(tree)
    tree.write("sys/devices/system/cpu/cpu7/regs/identification/midr_el1", "")
    tree.write("sys/devices/system/cpu/cpu7/cpufreq/cpuinfo_max_freq", "")
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "6-7", allow_mixed=False)
    assert caught.value.code == "E_CPUS_MIXED_TYPES"


def test_a_cpu_that_is_not_online_is_refused(tree: Any) -> None:
    _two_type_machine(tree)
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "6-9", allow_mixed=False)
    assert caught.value.code == "E_PIN_UNSUPPORTED"
    assert caught.value.exit_code == 4
    assert caught.value.message == "CPUs 8-9 are not online on this machine"


def test_a_cpu_outside_the_container_cpus_is_refused(tree: Any) -> None:
    _two_type_machine(tree)
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-5\n")
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "4-7", allow_mixed=False)
    assert caught.value.code == "E_PIN_UNSUPPORTED"
    assert caught.value.message == "CPUs 6-7 are outside the CPUs this process may use"


@pytest.mark.parametrize("system", ["darwin", "other"])
def test_pinning_off_linux_is_refused(tree: Any, system: str) -> None:
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, system, "0-1", allow_mixed=False)  # type: ignore[arg-type]
    assert caught.value.code == "E_PIN_UNSUPPORTED"
    assert caught.value.exit_code == 4
    assert caught.value.message == "pinning to CPUs is not supported on this platform"


def test_unpinned_off_linux_describes_nothing(tree: Any) -> None:
    assert cpu_facts(tree.root, "darwin", None, allow_mixed=False) == CpuFacts()


def test_a_list_that_is_no_cpu_list_is_a_usage_error(tree: Any) -> None:
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "4-", allow_mixed=False)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


def test_a_cpu_above_the_highest_number_is_refused_as_unsupported(tree: Any) -> None:
    _two_type_machine(tree)
    with pytest.raises(Refusal) as caught:
        cpu_facts(tree.root, "linux", "0-65536", allow_mixed=False)
    assert caught.value.code == "E_PIN_UNSUPPORTED"
    assert caught.value.exit_code == 4
    assert caught.value.message == "CPU numbers above 65535 are not supported: '0-65536'"


@dataclass
class FakeAffinity:
    """Records every move instead of making it."""

    current: frozenset[int] | None
    threads: tuple[int, ...] = ()
    fail_on: frozenset[int] = frozenset()
    moves: list[tuple[int, frozenset[int]]] = field(default_factory=list)
    can_set: bool = True

    def affinity(self) -> Affinity:
        def move(task: int, cpus: frozenset[int]) -> None:
            if task in self.fail_on:
                raise OSError(3, "no such process")
            self.moves.append((task, cpus))

        return Affinity(
            get=lambda: self.current,
            set=move if self.can_set else None,
            threads=lambda: self.threads,
        )


def test_leave_pinned_moves_every_thread_outside_the_set() -> None:
    fake = FakeAffinity(
        current=frozenset(range(8)), threads=(101, 102, 103), fail_on=frozenset({102})
    )
    answer = leave_pinned("4-7", system="linux", affinity=fake.affinity())
    assert answer == ToolCpus(cpus="0-3")
    outside = frozenset({0, 1, 2, 3})
    assert fake.moves == [(0, outside), (101, outside), (103, outside)]


def test_leave_pinned_respects_the_cpus_the_tool_may_use_now() -> None:
    fake = FakeAffinity(current=frozenset({2, 3, 4, 5}))
    assert leave_pinned("4-7", system="linux", affinity=fake.affinity()) == ToolCpus(cpus="2-3")


def test_leave_pinned_says_when_no_cpu_is_left() -> None:
    fake = FakeAffinity(current=frozenset({4, 5, 6, 7}))
    assert leave_pinned("4-7", system="linux", affinity=fake.affinity()) == ToolCpus(
        reason="none_left"
    )
    assert fake.moves == []


def test_leave_pinned_without_a_pinned_set() -> None:
    fake = FakeAffinity(current=frozenset(range(8)))
    assert leave_pinned(None, system="linux", affinity=fake.affinity()) == ToolCpus(
        reason="not_pinned"
    )
    assert fake.moves == []


def test_leave_pinned_refuses_a_cpu_above_the_highest_number() -> None:
    fake = FakeAffinity(current=frozenset(range(8)))
    with pytest.raises(Refusal) as caught:
        leave_pinned("65536", system="linux", affinity=fake.affinity())
    assert caught.value.code == "E_PIN_UNSUPPORTED"
    assert caught.value.exit_code == 4
    assert fake.moves == []


@pytest.mark.parametrize(
    ("system", "fake"),
    [
        ("darwin", FakeAffinity(current=frozenset(range(8)))),
        ("linux", FakeAffinity(current=frozenset(range(8)), can_set=False)),
        ("linux", FakeAffinity(current=None)),
        ("linux", FakeAffinity(current=frozenset(range(8)), fail_on=frozenset({0}))),
    ],
)
def test_leave_pinned_where_the_platform_does_not_allow_it(system: str, fake: FakeAffinity) -> None:
    answer = leave_pinned("4-7", system=system, affinity=fake.affinity())  # type: ignore[arg-type]
    assert answer == ToolCpus(reason="unsupported")
    assert fake.moves == []


def test_return_home_moves_every_thread_back() -> None:
    fake = FakeAffinity(
        current=frozenset({0, 1}), threads=(101, 102, 104), fail_on=frozenset({102})
    )
    home = frozenset(range(8))
    return_home(home, affinity=fake.affinity())
    assert fake.moves == [(0, home), (101, home), (104, home)]


def test_return_home_where_the_calling_thread_cannot_move_still_moves_the_others() -> None:
    fake = FakeAffinity(current=frozenset({0, 1}), threads=(101,), fail_on=frozenset({0}))
    return_home(frozenset(range(8)), affinity=fake.affinity())
    assert fake.moves == [(101, frozenset(range(8)))]


def test_return_home_where_the_platform_does_not_allow_it() -> None:
    fake = FakeAffinity(current=frozenset({0, 1}), threads=(101,), can_set=False)
    return_home(frozenset(range(8)), affinity=fake.affinity())
    assert fake.moves == []


def test_the_note_when_the_tool_stays_on_the_pinned_cpus() -> None:
    assert tool_cpus_note(ToolCpus(reason="none_left"), "0-7") == (
        "tool_on_pinned_cpus",
        "no CPU is left outside the pinned set 0-7; the tool runs on the same CPUs as the launches",
    )
    assert tool_cpus_note(ToolCpus(reason="unsupported"), "0-7") == (
        "tool_on_pinned_cpus",
        "this platform does not let the tool move off the pinned CPUs; "
        "the tool may run on the same CPUs as the launches",
    )
    assert tool_cpus_note(ToolCpus(cpus="0-3"), "4-7") is None
    assert tool_cpus_note(ToolCpus(reason="not_pinned"), None) is None


def _ctx(make_ctx: Callable[..., Any], cpus: str | None, **kw: Any) -> Any:
    allow = kw.pop("allow_mixed", False)
    return make_ctx(
        launch=LaunchSettings(cpus=cpus), gates=GateSettings(allow_mixed_core_types=allow), **kw
    )


def test_cpus_check_passes_a_set_of_one_type(tree: Any, make_ctx: Callable[..., Any]) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, "4-5", mode="enforce"))
    assert record.name == "cpus"
    assert record.mode == "enforce"
    assert record.status == "pass"
    assert "message" not in record.detail
    detail = record.to_json()["detail"]
    assert detail["identity"] == [{"cpus": "4-5", "key": "arm-41-d4b", "max_khz": 2900000}]
    assert detail["cache_domains"] == ["4-7"]


def test_cpus_check_fails_a_mixed_set(tree: Any, make_ctx: Callable[..., Any]) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, "3-4"))
    assert record.status == "fail"
    assert record.detail["code"] == "E_CPUS_MIXED_TYPES"
    assert record.detail["message"] == (
        "the CPU set 3-4 mixes core types (arm-41-d4b, arm-41-d80); "
        "give --allow-mixed-core-types to run on it anyway"
    )


def _side_ctx(make_ctx: Callable[..., Any], cpus: str | None, own: str, **kw: Any) -> Any:
    allow = kw.pop("allow_mixed", False)
    launch = LaunchSettings(cpus=cpus, overrides={"new": {"cpus": own}})
    return make_ctx(launch=launch, gates=GateSettings(allow_mixed_core_types=allow), **kw)


def test_cpus_check_fails_a_side_own_set_that_mixes_types_and_names_the_side(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    gate = CpusGate(root=tree.root, system="linux")
    for shared in ("4-5", None):
        record = gate.check(_side_ctx(make_ctx, shared, "3-4", mode="enforce"))
        assert record.status == "fail"
        assert record.detail["code"] == "E_CPUS_MIXED_TYPES"
        assert record.detail["side"] == "new"
        assert record.detail["message"] == (
            "side new: the CPU set 3-4 mixes core types (arm-41-d4b, arm-41-d80); "
            "give --allow-mixed-core-types to run on it anyway"
        )


def test_cpus_check_passes_a_side_own_mixed_set_that_is_allowed_and_describes_it(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    gate = CpusGate(root=tree.root, system="linux")
    record = gate.check(_side_ctx(make_ctx, "4-5", "3-4", allow_mixed=True))
    assert record.status == "pass"
    assert record.detail["cpus"] == "4-5"
    assert record.detail["mixed"] is False
    assert record.to_json()["detail"]["sides"] == {
        "new": {
            "cpus": "3-4",
            "identity": [
                {"cpus": "3", "key": "arm-41-d80", "max_khz": 2000000},
                {"cpus": "4", "key": "arm-41-d4b", "max_khz": 2900000},
            ],
            "cache_domains": ["0-3", "4-7"],
            "mixed": True,
        }
    }


def test_cpus_check_degrades_a_side_own_set_whose_core_type_cannot_be_read(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    tree.online("0-9")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-9\n")
    record = CpusGate(root=tree.root, system="linux").check(_side_ctx(make_ctx, "4-5", "8-9"))
    assert record.status == "degraded"
    assert record.detail["side"] == "new"
    assert (
        record.detail["message"] == "side new: the core type of some pinned CPUs could not be read"
    )


def test_cpus_check_passes_a_mixed_set_that_is_allowed(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, "3-4", allow_mixed=True))
    assert record.status == "pass"
    assert record.detail["mixed"] is True


def test_unpinned_on_two_core_types_leaves_the_note_to_the_runner(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    notes: list[tuple[str, str]] = []
    gate = CpusGate(root=tree.root, system="linux")
    first = gate.check(_ctx(make_ctx, None, notes=notes))
    again = gate.check(_ctx(make_ctx, None, notes=notes, phase="recheck"))
    assert first.status == "pass"
    assert again.status == "pass"
    assert first.detail["mixed"] is True
    assert notes == []


def test_unpinned_on_one_core_type_gives_no_note(tree: Any, make_ctx: Callable[..., Any]) -> None:
    tree.online("0-1")
    tree.write("proc/cpuinfo", ARM_INFO)
    notes: list[tuple[str, str]] = []
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, None, notes=notes))
    assert record.status == "pass"
    assert notes == []


def test_cpus_check_degraded_when_types_cannot_be_read(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    tree.online("0-3")
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, "0-1"))
    assert record.status == "degraded"
    assert record.detail["message"] == "the core type of some pinned CPUs could not be read"


def test_cpus_check_unavailable_for_an_offline_cpu(tree: Any, make_ctx: Callable[..., Any]) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, "7-8"))
    assert record.status == "unavailable"
    assert record.detail["code"] == "E_PIN_UNSUPPORTED"
    assert record.detail["message"] == "CPUs 8 are not online on this machine"


def test_cpus_check_unavailable_for_a_cpu_above_the_highest_number(
    tree: Any, make_ctx: Callable[..., Any]
) -> None:
    _two_type_machine(tree)
    ctx = _ctx(make_ctx, None)
    # The launch settings refuse such a list when they are made; the check
    # refuses it again for a context built some other way.
    object.__setattr__(ctx.launch, "cpus", "7,65536")
    record = CpusGate(root=tree.root, system="linux").check(ctx)
    assert record.status == "unavailable"
    assert record.detail["code"] == "E_PIN_UNSUPPORTED"
    assert record.detail["message"] == "CPU numbers above 65535 are not supported: '7,65536'"


def test_cpus_check_unavailable_without_cpus(tree: Any, make_ctx: Callable[..., Any]) -> None:
    record = CpusGate(root=tree.root, system="linux").check(_ctx(make_ctx, None))
    assert record.status == "unavailable"
    assert record.detail["message"] == "the CPUs could not be read"


@pytest.mark.parametrize(
    ("cpus", "message"),
    [
        ("0-1", "pinning to CPUs is not supported on this platform"),
        (None, "core types cannot be read on this platform"),
    ],
)
def test_cpus_check_off_linux(
    tree: Any, make_ctx: Callable[..., Any], cpus: str | None, message: str
) -> None:
    record = CpusGate(root=tree.root, system="darwin").check(_ctx(make_ctx, cpus))
    assert record.status == "unavailable"
    assert record.detail["message"] == message
    assert record.detail["where"] == "macos"


def test_cpus_check_inside_a_container_is_labelled(tree: Any, make_ctx: Callable[..., Any]) -> None:
    _two_type_machine(tree)
    record = CpusGate(root=tree.root, system="linux").check(
        _ctx(make_ctx, "0-1", in_container=True)
    )
    assert record.status == "pass"
    assert record.detail["where"] == "container"


def test_cpus_doctor(tree: Any) -> None:
    _two_type_machine(tree)
    report = CpusGate(root=tree.root, system="linux").doctor()
    assert report.status == "ok"
    assert report.summary == "8 CPUs of 2 core type(s)"
    assert CpusGate(root=tree.root, system="darwin").doctor().status == "unavailable"
