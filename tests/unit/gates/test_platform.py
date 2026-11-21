# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""CPU lists, the kernel-file reader, the cgroup CPU set and the behaviour table."""

from __future__ import annotations

from typing import Any

import pytest

from pairbench.gates.platform import (
    BEHAVIOUR,
    MAX_CPU,
    CpuNumberTooHigh,
    Platform,
    cgroup_cpus,
    format_cpu_list,
    online_cpus,
    parse_cpu_list,
    this_system,
    upward,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0-3", frozenset({0, 1, 2, 3})),
        ("0,2,4", frozenset({0, 2, 4})),
        ("0-1,8,10-11", frozenset({0, 1, 8, 10, 11})),
        ("5", frozenset({5})),
        ("", frozenset()),
        (" 4-5 \n", frozenset({4, 5})),
    ],
)
def test_parse_cpu_list(text: str, expected: frozenset[int]) -> None:
    assert parse_cpu_list(text) == expected


@pytest.mark.parametrize("text", ["a", "3-1", "1-", "-1", "0:2", "1,,2"])
def test_parse_cpu_list_refuses_what_is_no_list(text: str) -> None:
    with pytest.raises(ValueError):
        parse_cpu_list(text)


def test_parse_cpu_list_accepts_the_highest_cpu_number() -> None:
    assert MAX_CPU == 65535
    assert parse_cpu_list("65535") == frozenset({65535})


@pytest.mark.parametrize("text", ["65536", "0-65536", "0,70000-70001"])
def test_parse_cpu_list_refuses_a_cpu_above_the_highest_number(text: str) -> None:
    with pytest.raises(CpuNumberTooHigh) as caught:
        parse_cpu_list(text)
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    ("cpus", "expected"),
    [
        ({0, 1, 2, 3}, "0-3"),
        ({0, 2, 4}, "0,2,4"),
        ({11, 10, 8, 1, 0}, "0-1,8,10-11"),
        ({7}, "7"),
        (set(), ""),
    ],
)
def test_format_cpu_list(cpus: set[int], expected: str) -> None:
    assert format_cpu_list(cpus) == expected


def test_online_cpus_reads_the_online_list(tree: Any) -> None:
    tree.online("0-5")
    assert online_cpus(tree.root) == frozenset(range(6))


def test_online_cpus_falls_back_to_the_cpu_folders(tree: Any) -> None:
    for cpu in (0, 1, 3):
        tree.write(f"sys/devices/system/cpu/cpu{cpu}/uevent", "")
    tree.write("sys/devices/system/cpu/cpufreq/x", "")
    assert online_cpus(tree.root) == frozenset({0, 1, 3})


def test_online_cpus_none_without_a_tree(tree: Any) -> None:
    assert online_cpus(tree.root) is None


def test_root_reads_nothing_that_is_missing(tree: Any) -> None:
    assert tree.root.text("proc/stat") is None
    assert tree.root.line("proc/stat") is None
    assert tree.root.names("proc") is None


def test_cgroup_v2_own_group(tree: Any) -> None:
    tree.write("proc/self/cgroup", "0::/user.slice/job.scope\n")
    tree.write("sys/fs/cgroup/user.slice/job.scope/cpuset.cpus.effective", "2-5\n")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-15\n")
    assert cgroup_cpus(tree.root) == frozenset({2, 3, 4, 5})


def test_cgroup_v2_walks_up_to_the_nearest_group_with_a_cpu_set(tree: Any) -> None:
    tree.write("proc/self/cgroup", "0::/a/b/c\n")
    tree.write("sys/fs/cgroup/a/cpuset.cpus.effective", "4-7\n")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-15\n")
    assert cgroup_cpus(tree.root) == frozenset({4, 5, 6, 7})


def test_cgroup_inside_a_container_reads_its_own_root(tree: Any) -> None:
    tree.write("proc/self/cgroup", "0::/\n")
    tree.write("sys/fs/cgroup/cpuset.cpus.effective", "0-1\n")
    assert cgroup_cpus(tree.root) == frozenset({0, 1})


def test_cgroup_v1_cpuset_hierarchy(tree: Any) -> None:
    tree.write("proc/self/cgroup", "12:memory:/x\n4:cpuset:/docker/abc\n")
    tree.write("sys/fs/cgroup/cpuset/docker/abc/cpuset.effective_cpus", "6,7\n")
    assert cgroup_cpus(tree.root) == frozenset({6, 7})


def test_cgroup_unreadable_is_none(tree: Any) -> None:
    assert cgroup_cpus(tree.root) is None
    tree.write("proc/self/cgroup", "0::/a\n")
    assert cgroup_cpus(tree.root) is None


def test_upward_lists_the_group_then_each_parent() -> None:
    assert upward("/a/b/c") == ["a/b/c", "a/b", "a", ""]
    assert upward("/") == [""]


@pytest.mark.parametrize(
    ("platform", "where"),
    [
        (Platform("linux"), "linux_host"),
        (Platform("linux", in_container=True), "container"),
        (Platform("linux", in_container=True, ci=True), "container"),
        (Platform("linux", ci=True), "ci"),
        (Platform("darwin"), "macos"),
        (Platform("darwin", ci=True), "macos"),
        (Platform("other"), "other"),
    ],
)
def test_where_a_check_runs(platform: Platform, where: str) -> None:
    assert platform.where == where


def test_the_behaviour_table_says_what_each_check_does_where_it_runs() -> None:
    assert BEHAVIOUR["quiet"]["macos"] == "load average only, degraded"
    assert BEHAVIOUR["quiet"]["container"] == "machine-wide view, labelled"
    assert BEHAVIOUR["quiet"]["ci"] == "recorded; not waited on unless asked"
    assert BEHAVIOUR["cpus"]["container"] == "limited to the container's own CPUs"
    assert BEHAVIOUR["cpus"]["macos"] == "refused with the reason"
    assert BEHAVIOUR["census"]["container"] == "unavailable without the engine socket"
    assert BEHAVIOUR["census"]["macos"] == "scoped to the engine's virtual machine, labelled"
    assert BEHAVIOUR["disturbed_rounds"]["macos"] == "off: no independent witness"
    assert {BEHAVIOUR["locks"][w] for w in BEHAVIOUR["locks"]} == {"full"}
    assert Platform("linux", ci=True).behaviour("cpus") == "full"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("linux", "linux"), ("linux2", "linux"), ("darwin", "darwin"), ("win32", "other")],
)
def test_this_system(name: str, expected: str) -> None:
    assert this_system(name) == expected
