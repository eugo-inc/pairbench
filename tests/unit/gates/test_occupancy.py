# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""GPU occupancy through a fake query command and a fake management library.

No GPU tool is run: every answer below is written by the test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from pairbench.gates.occupancy import (
    FailingSource,
    NvmlSource,
    Probe,
    SmiSource,
    absent_message,
    gpu_source,
    is_slowdown,
    missing_gpus,
    run_command,
    selected_indices,
)

UUID0 = "GPU-made-up-0"
UUID1 = "GPU-made-up-1"


@dataclass
class FakeSmi:
    """Answers the query command from a table of query argument to (exit code, output)."""

    answers: dict[str, tuple[int, str]]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, argv: Sequence[str], timeout_s: float) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        return self.answers.get(argv[1], (6, ""))


def _smi(**extra: tuple[int, str]) -> FakeSmi:
    answers = {
        "--query-gpu=index,uuid,memory.used": (0, f"0, {UUID0}, 512\n1, {UUID1}, 1024\n"),
        "--query-compute-apps=pid,gpu_uuid": (0, f"4242, {UUID0}\n5151, {UUID1}\n"),
        "--query-gpu=index,clocks_event_reasons.active": (
            0,
            "0, 0x0000000000000001\n1, 0x0000000000000004\n",
        ),
    }
    answers.update(extra)
    return FakeSmi(answers)


def test_reason_bits_that_are_slowdowns() -> None:
    assert is_slowdown(0x0) is False
    assert is_slowdown(0x1) is False  # GPU idle
    assert is_slowdown(0x2) is False  # applications clocks setting
    assert is_slowdown(0x100) is False  # display clock setting
    assert is_slowdown(0x103) is False
    for bit in (0x4, 0x8, 0x10, 0x20, 0x40, 0x80, 0x200, 0x400):
        assert is_slowdown(bit) is True
    assert is_slowdown(0x1 | 0x40) is True


@pytest.mark.parametrize(
    ("gpus", "count", "expected"),
    [("all", 3, (0, 1, 2)), ("1", 3, (1,)), ("2,0", 3, (2, 0)), ("3", 3, None), ("x", 3, None)],
)
def test_selected_indices(gpus: str, count: int, expected: tuple[int, ...] | None) -> None:
    assert selected_indices(gpus, count) == expected


def test_smi_processes_on_the_selected_gpus() -> None:
    smi = _smi()
    source = SmiSource("1", run=smi, program="smi")
    assert source.processes() == (5151,)
    assert smi.calls[0] == (
        "smi",
        "--query-gpu=index,uuid,memory.used",
        "--format=csv,noheader,nounits",
    )


def test_smi_looks_up_the_gpu_ids_once() -> None:
    smi = _smi()
    source = SmiSource("all", run=smi)
    assert source.processes() == (4242, 5151)
    assert source.processes() == (4242, 5151)
    queries = [call[1] for call in smi.calls]
    assert queries == [
        "--query-gpu=index,uuid,memory.used",
        "--query-compute-apps=pid,gpu_uuid",
        "--query-compute-apps=pid,gpu_uuid",
    ]


def test_smi_no_compute_process_is_an_empty_answer() -> None:
    smi = _smi(**{"--query-compute-apps=pid,gpu_uuid": (0, "")})
    assert SmiSource("0", run=smi).processes() == ()


def test_smi_memory_in_use_is_summed() -> None:
    assert SmiSource("all", run=_smi()).memory_used_mib() == 1536.0
    assert SmiSource("0", run=_smi()).memory_used_mib() == 512.0


def test_smi_reason_masks_and_the_older_field_name() -> None:
    assert SmiSource("all", run=_smi()).reason_masks() == (0x1, 0x4)
    older = _smi(
        **{
            "--query-gpu=index,clocks_event_reasons.active": (2, ""),
            "--query-gpu=index,clocks_throttle_reasons.active": (0, "0, 0x40\n1, 0x0\n"),
        }
    )
    source = SmiSource("all", run=older)
    assert source.reason_masks() == (0x40, 0x0)
    assert source.reason_masks() == (0x40, 0x0)
    reason_queries = [c[1] for c in older.calls if "reasons" in c[1]]
    assert reason_queries == [
        "--query-gpu=index,clocks_event_reasons.active",
        "--query-gpu=index,clocks_throttle_reasons.active",
        "--query-gpu=index,clocks_throttle_reasons.active",
    ]


@pytest.mark.parametrize(
    "broken",
    [
        {"--query-gpu=index,uuid,memory.used": (9, "")},
        {"--query-gpu=index,uuid,memory.used": (0, "zero, GPU-x, 1\n")},
        {"--query-compute-apps=pid,gpu_uuid": (9, "")},
        {"--query-compute-apps=pid,gpu_uuid": (0, "[N/A], GPU-x\n")},
    ],
)
def test_smi_processes_that_cannot_be_read_are_none(broken: dict[str, tuple[int, str]]) -> None:
    assert SmiSource("all", run=_smi(**broken)).processes() is None


def test_smi_a_selected_gpu_that_is_missing_is_a_failed_read() -> None:
    source = SmiSource("5", run=_smi())
    assert source.processes() is None
    assert source.memory_used_mib() is None
    assert source.reason_masks() is None


def test_smi_unsupported_values_are_failed_reads() -> None:
    smi = _smi(
        **{
            "--query-gpu=index,uuid,memory.used": (0, f"0, {UUID0}, [N/A]\n"),
            "--query-gpu=index,clocks_event_reasons.active": (0, "0, [Not Supported]\n"),
        }
    )
    source = SmiSource("0", run=smi)
    assert source.memory_used_mib() is None
    assert source.reason_masks() is None


class FakeNvml:
    """Stands in for the management library module."""

    def __init__(self, *, newer: bool = True, fail: str = "") -> None:
        self.inits = 0
        self.fail = fail
        if newer:
            self.nvmlDeviceGetCurrentClocksEventReasons = self._reasons
        else:
            self.nvmlDeviceGetCurrentClocksThrottleReasons = self._reasons

    def nvmlInit(self) -> None:
        self.inits += 1

    def nvmlDeviceGetCount(self) -> int:
        return 2

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        return index

    def nvmlDeviceGetComputeRunningProcesses(self, handle: int) -> list[Any]:
        if self.fail == "processes":
            raise RuntimeError("made-up library error")
        return [type("P", (), {"pid": 100 + handle})()]

    def nvmlDeviceGetMemoryInfo(self, handle: int) -> Any:
        return type("M", (), {"used": (handle + 1) * 1024 * 1024 * 256})()

    def _reasons(self, handle: int) -> int:
        return 0x20 if handle else 0x0


def test_nvml_source_reads_the_selected_gpus() -> None:
    nvml = FakeNvml()
    source = NvmlSource("all", module=nvml)
    assert source.processes() == (100, 101)
    assert source.memory_used_mib() == 768.0
    assert source.reason_masks() == (0x0, 0x20)
    assert nvml.inits == 1


def test_nvml_source_uses_the_older_reason_call() -> None:
    assert NvmlSource("1", module=FakeNvml(newer=False)).reason_masks() == (0x20,)


def test_nvml_source_errors_are_failed_reads() -> None:
    source = NvmlSource("0", module=FakeNvml(fail="processes"))
    assert source.processes() is None
    assert NvmlSource("7", module=FakeNvml()).processes() is None


def test_failing_source_fails_every_read() -> None:
    source = FailingSource()
    assert source.processes() is None
    assert source.memory_used_mib() is None
    assert source.reason_masks() is None


def test_gpu_source_prefers_the_library_then_the_query_command() -> None:
    assert isinstance(gpu_source("0", has_module=lambda n: True), NvmlSource)
    picked = gpu_source("0", has_module=lambda n: False, which=lambda n: "/usr/bin/" + n)
    assert isinstance(picked, SmiSource)
    none = gpu_source("0", has_module=lambda n: False, which=lambda n: None)
    assert isinstance(none, FailingSource)


def test_probe_counts_processes_leaving_out_the_given_ones() -> None:
    probe = Probe(SmiSource("all", run=_smi()))
    assert probe.compute_processes() == 2
    assert probe.compute_processes(exclude_pids=[4242]) == 1
    assert probe.memory_used_mib() == 1536.0
    assert Probe(FailingSource()).compute_processes() is None


def test_run_command_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(subprocess, "run", missing)
    assert run_command(["no-such-tool"], 1.0) == (-1, "")


# --- the GPUs a machine has --------------------------------------------------


@pytest.mark.parametrize(
    ("gpus", "present", "missing"),
    [
        ("all", (), ()),
        ("all", (0, 1), ()),
        ("1", (0, 1), ()),
        ("1,0", (0, 1), ()),
        ("2", (0, 1), (2,)),
        ("3,0,2,3", (0, 1), (3, 2)),
        ("0", (), (0,)),
        ("x", (0, 1), ()),
    ],
)
def test_missing_gpus_names_each_index_the_machine_lacks(
    gpus: str, present: tuple[int, ...], missing: tuple[int, ...]
) -> None:
    assert missing_gpus(gpus, present) == missing


@pytest.mark.parametrize(
    ("missing", "present", "message"),
    [
        ((2,), (0, 1), "GPU 2 is not on this machine; the GPUs here are 0, 1"),
        ((3, 2), (0,), "GPUs 3, 2 are not on this machine; the GPUs here are 0"),
        ((0,), (), "GPU 0 is not on this machine; no GPU is visible here"),
    ],
)
def test_absent_message(missing: tuple[int, ...], present: tuple[int, ...], message: str) -> None:
    assert absent_message(missing, present) == message


def test_smi_present_lists_every_gpu_whatever_is_selected() -> None:
    smi = _smi(**{"--query-gpu=index,uuid,memory.used": (0, f"1, {UUID1}, 1\n0, {UUID0}, 1\n")})
    assert SmiSource("7", run=smi).present() == (0, 1)


@pytest.mark.parametrize(
    "rows", [(9, ""), (0, "zero, GPU-x, 1\n")], ids=["command-fails", "unreadable-row"]
)
def test_smi_present_that_cannot_be_read_is_none(rows: tuple[int, str]) -> None:
    smi = _smi(**{"--query-gpu=index,uuid,memory.used": rows})
    assert SmiSource("0", run=smi).present() is None


def test_nvml_present_counts_every_gpu_and_initialises_once() -> None:
    nvml = FakeNvml()
    source = NvmlSource("7", module=nvml)
    assert source.present() == (0, 1)
    assert source.processes() is None
    assert NvmlSource("1", module=nvml).present() == (0, 1)
    assert nvml.inits == 2


def test_nvml_present_that_cannot_be_read_is_none() -> None:
    class Broken(FakeNvml):
        def nvmlDeviceGetCount(self) -> int:
            raise RuntimeError("made-up library error")

    assert NvmlSource("0", module=Broken()).present() is None


def test_failing_source_sees_no_gpu_list() -> None:
    assert FailingSource().present() is None
