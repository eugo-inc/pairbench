# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The neighbour census with a fake container engine and synthetic cgroup counters."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pairbench.gates.census import CensusGate, parse_inspect, parse_stats
from pairbench.model import CensusSettings, GateSettings, LaunchSettings

Ctx = Callable[..., Any]

# id, name, allowed CPUs, first process, cores used over the window
CONTAINERS = [
    ("aaaa0001", "neighbour-a", "", 1001, 0.8),  # unpinned, above the limit
    ("aaaa0002", "neighbour-b", "6-7", 1002, 0.9),  # shares a cache with 4-5
    ("aaaa0003", "neighbour-c", "0-1", 1003, 3.0),  # pinned away from the cache of 4-5
    ("aaaa0004", "neighbour-d", "", 1004, 0.2),  # unpinned, below the limit
]


@dataclass
class FakeEngine:
    """Answers the engine's commands from fixed outputs; records every call."""

    ps: tuple[int, str]
    inspect: tuple[int, str] = (0, "")
    stats: tuple[int, str] = (0, "")
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], timeout_s: float) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        return {"ps": self.ps, "inspect": self.inspect, "stats": self.stats}[argv[1]]


def _engine(rows: Sequence[tuple[str, str, str, int, float]], **kw: Any) -> FakeEngine:
    ps = (0, "".join(f"{r[0]}\n" for r in rows))
    inspect = (0, "".join(f"{r[0]}\t/{r[1]}\t{r[2]}\t{r[3]}\n" for r in rows))
    return FakeEngine(ps=ps, inspect=inspect, **kw)


def _counters(tree: Any, clock: Any, rows: Sequence[tuple[str, str, str, int, float]]) -> None:
    """cgroup v2 counters for each container, moving by its cores over one second."""
    for ident, _, _, pid, _ in rows:
        tree.write(f"proc/{pid}/cgroup", f"0::/system.slice/docker-{ident}.scope\n")

    def write(seconds: float) -> None:
        for ident, _, _, _, cores in rows:
            usec = int(5_000_000 + cores * seconds * 1_000_000)
            tree.write(
                f"sys/fs/cgroup/system.slice/docker-{ident}.scope/cpu.stat",
                f"usage_usec {usec}\nuser_usec 0\nsystem_usec 0\n",
            )

    write(0.0)
    clock.on_sleep = lambda count: write(1.0)


def _machine(tree: Any) -> None:
    tree.online("0-7")
    tree.llc([[0, 1, 2, 3], [4, 5, 6, 7]])


def _gate(tree: Any, clock: Any, engine: FakeEngine, **kw: Any) -> CensusGate:
    which: Mapping[str, str] = kw.pop("found", {"docker": "/usr/bin/docker"})
    return CensusGate(
        root=tree.root,
        system=kw.pop("system", "linux"),
        run=engine,
        which=lambda name: which.get(name),
        clock=clock,
        sleep=clock.sleep,
    )


def test_parse_inspect_and_stats() -> None:
    assert parse_inspect("abc\t/name-a\t0-3\t42\ndef\t/name-b\t\t0\n") is not None
    parsed = parse_inspect("abc\t/name-a\t0-3\t42\ndef\t/name-b\t\t0\n") or []
    assert [(n.id, n.name, n.cpus, n.pid) for n in parsed] == [
        ("abc", "name-a", frozenset({0, 1, 2, 3}), 42),
        ("def", "name-b", None, None),
    ]
    assert parse_inspect("only two\tfields\n") is None
    assert parse_stats("abc\t12.50%\ndef\t--\nbad line\n") == {"abc": 0.125}


def test_parse_stats_leaves_out_a_figure_that_is_no_cpu_use() -> None:
    assert parse_stats("abc\tnan%\ndef\t-5.00%\nghi\tinf%\njkl\t1e400%\nmno\t0.00%\n") == {
        "mno": 0.0
    }


def test_census_leaves_a_container_with_no_cpu_figure_unread(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    engine = _engine([CONTAINERS[0]], stats=(0, "aaaa0001\tNaN%\n"))
    record = _gate(tree, clock, engine, system="darwin").check(make_ctx())
    assert record.status == "degraded"
    assert record.to_json()["detail"]["unread"] == 1


def test_census_a_container_using_exactly_the_limit_passes(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    engine = _engine([CONTAINERS[0]], stats=(0, "aaaa0001\t50.00%\n"))
    record = _gate(tree, clock, engine, system="darwin").check(make_ctx())
    assert record.status == "pass"
    assert record.to_json()["detail"]["containers"] == 1
    assert record.to_json()["detail"]["offenders"] == []


def test_census_without_the_cache_topology_counts_every_busy_pinned_container(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    tree.online("0-7")
    rows = [CONTAINERS[2]]
    _counters(tree, clock, rows)
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(launch=LaunchSettings(cpus="4-5")))
    assert record.status == "fail"
    offenders = record.to_json()["detail"]["offenders"]
    assert [(o["name"], o["rule"]) for o in offenders] == [("neighbour-c", "shares_cache")]


def test_census_names_containers_that_use_cpus_of_the_run(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    _counters(tree, clock, CONTAINERS)
    engine = _engine(CONTAINERS)
    record = _gate(tree, clock, engine).check(make_ctx(launch=LaunchSettings(cpus="4-5")))
    assert record.name == "census"
    assert record.status == "fail"
    assert record.detail["message"] == (
        "2 other container(s) used more than 0.5 cores where launches run"
    )
    detail = record.to_json()["detail"]
    assert [(o["name"], o["rule"], o["cores"]) for o in detail["offenders"]] == [
        ("neighbour-a", "unpinned", 0.8),
        ("neighbour-b", "shares_cache", 0.9),
    ]
    assert detail["source"] == "cgroup"
    assert detail["engine"] == "docker"
    assert clock.slept == [1.0]
    assert "neighbour" not in record.detail["message"]


def test_census_records_counts_and_the_offenders_only_never_an_id_or_an_idle_name(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [
        ("zqcid0001" + "f" * 55, "zqname-busy", "", 1001, 0.8),
        ("zqcid0002" + "e" * 55, "zqname-idle", "", 1002, 0.0),
        ("zqcid0003" + "d" * 55, "zqname-gone", "", 1003, 0.0),
    ]
    _counters(tree, clock, rows[:2])
    record = _gate(tree, clock, _engine(rows)).check(make_ctx())
    text = json.dumps(record.to_json())
    assert "zqcid" not in text
    assert "zqname-idle" not in text
    assert "zqname-gone" not in text
    detail = record.to_json()["detail"]
    assert detail["containers"] == 3
    assert detail["unread"] == 1
    assert detail["offenders"] == [
        {"name": "zqname-busy", "cpus": None, "cores": 0.8, "rule": "unpinned"}
    ]


def test_census_passes_when_only_a_container_away_from_the_cache_is_busy(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(launch=LaunchSettings(cpus="4-5")))
    assert record.status == "pass"
    assert "message" not in record.detail


def test_census_with_nothing_pinned_counts_every_busy_container(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    record = _gate(tree, clock, _engine(rows)).check(make_ctx())
    assert record.status == "fail"
    offenders = record.to_json()["detail"]["offenders"]
    assert [(o["name"], o["rule"]) for o in offenders] == [("neighbour-c", "nothing_pinned")]


def test_census_reads_the_set_each_side_pins_for_itself(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    sides = {"old": LaunchSettings(cpus="4-5"), "new": LaunchSettings(cpus="5")}
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(sides=sides))
    assert record.status == "pass"
    assert record.to_json()["detail"]["offenders"] == []


def test_census_reads_the_set_a_side_override_pins(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    launch = LaunchSettings(cpus="5", overrides={"new": {"cpus": "1"}})
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(launch=launch))
    assert record.status == "fail"
    offenders = record.to_json()["detail"]["offenders"]
    assert [(o["name"], o["rule"]) for o in offenders] == [("neighbour-c", "shares_cache")]


def test_census_with_one_side_unpinned_counts_every_busy_container(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    sides = {"old": LaunchSettings(cpus="4-5"), "new": LaunchSettings()}
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(sides=sides))
    assert record.status == "fail"
    offenders = record.to_json()["detail"]["offenders"]
    assert [(o["name"], o["rule"]) for o in offenders] == [("neighbour-c", "nothing_pinned")]


def test_census_counts_a_container_that_shares_a_cache_with_either_side(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[2], CONTAINERS[3]]
    _counters(tree, clock, rows)
    sides = {"old": LaunchSettings(cpus="4"), "new": LaunchSettings(cpus="2")}
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(sides=sides))
    assert record.status == "fail"
    offenders = record.to_json()["detail"]["offenders"]
    assert [(o["name"], o["rule"]) for o in offenders] == [("neighbour-c", "shares_cache")]


def test_the_limit_comes_from_the_settings(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    _machine(tree)
    rows = [CONTAINERS[0]]
    _counters(tree, clock, rows)
    gates = GateSettings(census=CensusSettings(max_busy_cores=1.0))
    record = _gate(tree, clock, _engine(rows)).check(make_ctx(gates=gates))
    assert record.status == "pass"


def test_census_degraded_when_a_container_cannot_be_read(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    _machine(tree)
    rows = [CONTAINERS[3]]
    _counters(tree, clock, rows)
    lost = ("aaaa0009", "neighbour-gone", "", 1009, 0.0)
    record = _gate(tree, clock, _engine([*rows, lost])).check(make_ctx())
    assert record.status == "degraded"
    assert record.detail["message"] == "the CPU use of 1 container(s) could not be read"
    assert record.to_json()["detail"]["unread"] == 1


def test_census_reads_a_cgroup_v1_counter(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    _machine(tree)
    tree.write("proc/1001/cgroup", "7:memory:/docker/aaaa0001\n4:cpu,cpuacct:/docker/aaaa0001\n")

    def write(ns: int) -> None:
        tree.write("sys/fs/cgroup/cpu,cpuacct/docker/aaaa0001/cpuacct.usage", f"{ns}\n")

    write(1_000_000_000)
    clock.on_sleep = lambda count: write(1_700_000_000)
    record = _gate(tree, clock, _engine([CONTAINERS[0]])).check(make_ctx())
    assert record.status == "fail"
    assert record.to_json()["detail"]["offenders"][0]["cores"] == 0.7


def test_census_on_macos_reads_the_engine_stats_and_is_labelled(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    rows = [CONTAINERS[0]]
    engine = _engine(rows, stats=(0, "aaaa0001\t80.00%\n"))
    record = _gate(tree, clock, engine, system="darwin").check(make_ctx())
    assert record.status == "fail"
    assert record.detail["message"] == (
        "1 other container(s) used more than 0.5 cores where launches run "
        "(scoped to the engine's virtual machine)"
    )
    assert record.detail["scope"] == "engine_vm"
    assert record.detail["source"] == "engine_stats"
    assert clock.slept == []


def test_census_inside_a_container_reads_the_engine_stats(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    rows = [CONTAINERS[3]]
    engine = _engine(rows, stats=(0, "aaaa0004\t20.00%\n"))
    record = _gate(tree, clock, engine).check(make_ctx(in_container=True))
    assert record.status == "pass"
    assert record.detail["source"] == "engine_stats"
    assert record.detail["where"] == "container"


def test_census_engine_stats_that_fail_leave_containers_unread(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    engine = _engine([CONTAINERS[3]], stats=(1, ""))
    record = _gate(tree, clock, engine, system="darwin").check(make_ctx())
    assert record.status == "degraded"


def test_census_without_an_engine_is_unavailable(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    engine = _engine([])
    record = _gate(tree, clock, engine, found={}).check(make_ctx())
    assert record.status == "unavailable"
    assert record.detail["message"] == "no container engine could be reached"
    assert engine.calls == []


def test_census_without_access_to_the_engine_is_unavailable(
    tree: Any, clock: Any, make_ctx: Ctx
) -> None:
    engine = FakeEngine(ps=(1, ""))
    record = _gate(tree, clock, engine).check(make_ctx(in_container=True))
    assert record.status == "unavailable"
    assert record.detail["message"] == "the container engine could not be reached"


def test_census_uses_the_engine_that_is_asked_for(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    engine = FakeEngine(ps=(0, ""))
    found = {"podman": "/usr/bin/podman"}
    record = _gate(tree, clock, engine, found=found).check(make_ctx())
    assert record.status == "pass"
    assert engine.calls[0][0] == "podman"
    asked = _gate(tree, clock, FakeEngine(ps=(0, "")), found=found).check(
        make_ctx(launch=LaunchSettings(engine="docker"))
    )
    assert asked.status == "unavailable"


def test_census_with_no_other_container_passes(tree: Any, clock: Any, make_ctx: Ctx) -> None:
    record = _gate(tree, clock, FakeEngine(ps=(0, "\n"))).check(make_ctx())
    assert record.status == "pass"
    assert record.to_json()["detail"]["containers"] == 0


def test_census_doctor(tree: Any, clock: Any) -> None:
    gate = _gate(tree, clock, FakeEngine(ps=(0, "")), found={})
    assert gate.doctor().status == "unavailable"
    gate = _gate(tree, clock, FakeEngine(ps=(0, "")))
    assert gate.doctor().status == "ok"
