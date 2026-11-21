# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The GPU management library source, with a fake of the library's module."""

from __future__ import annotations

import importlib.util
import math
import threading
from collections.abc import Callable
from typing import Any

import pytest

from pairbench.energy import nvml
from pairbench.energy.integrate import Collected, Reading
from pairbench.energy.nvml import NvmlSource, read_gpu
from pairbench.energy.nvml import available as real_available

NOT_SUPPORTED = 3
UNKNOWN = 999
INVALID_ARGUMENT = 2


class FakeNvmlError(Exception):
    """The library's exception: ``value`` is its return code."""

    def __init__(self, value: int) -> None:
        super().__init__(value)
        self.value = value


class FakeLibrary:
    """A made-up stand-in for the module of the ``gpu`` extra.

    ``fields`` maps a GPU index to its field values; a value that is an
    exception is raised. ``on_power`` is called after every power read.
    """

    NVML_ERROR_NOT_SUPPORTED = NOT_SUPPORTED
    NVML_TEMPERATURE_GPU = 0
    NVMLError = FakeNvmlError

    def __init__(self, fields: dict[int, dict[str, object]]) -> None:
        self.fields = fields
        self.calls: list[str] = []
        self.power_reads = 0
        self.on_power: Callable[[int], None] = lambda reads: None

    def _value(self, handle: tuple[str, int], name: str) -> object:
        value = self.fields[handle[1]].get(name, FakeNvmlError(NOT_SUPPORTED))
        if isinstance(value, BaseException):
            raise value
        return value

    def nvmlInit(self) -> None:
        self.calls.append("init")

    def nvmlShutdown(self) -> None:
        self.calls.append("shutdown")

    def nvmlDeviceGetCount(self) -> int:
        return len(self.fields)

    def nvmlDeviceGetHandleByIndex(self, index: int) -> tuple[str, int]:
        if index not in self.fields:
            raise FakeNvmlError(INVALID_ARGUMENT)
        return ("handle", index)

    def nvmlDeviceGetPowerUsage(self, handle: tuple[str, int]) -> object:
        try:
            return self._value(handle, "power_mw")
        finally:
            self.power_reads += 1
            self.on_power(self.power_reads)

    def nvmlDeviceGetTotalEnergyConsumption(self, handle: tuple[str, int]) -> object:
        return self._value(handle, "energy_mj")

    def nvmlDeviceGetTemperature(self, handle: tuple[str, int], sensor: int) -> object:
        assert sensor == 0
        return self._value(handle, "temperature_c")

    def nvmlDeviceGetCurrentClocksEventReasons(self, handle: tuple[str, int]) -> object:
        return self._value(handle, "reasons")


class OlderLibrary(FakeLibrary):
    """A module that has only the older name of the reasons call."""

    def __getattribute__(self, name: str) -> Any:
        if name == "nvmlDeviceGetCurrentClocksEventReasons":
            raise AttributeError(name)
        return super().__getattribute__(name)

    def nvmlDeviceGetCurrentClocksThrottleReasons(self, handle: tuple[str, int]) -> object:
        return self._value(handle, "reasons")


GPU_A = {"power_mw": 123456, "energy_mj": 7000500, "temperature_c": 61, "reasons": 0x44}


def _clock(start: int = 0) -> Callable[[], float]:
    """A clock that moves a tenth of a second at each read."""
    ticks = iter(range(start, 1_000_000))
    return lambda: next(ticks) / 10


# --- one reading -------------------------------------------------------------------


def test_a_reading_converts_milliwatts_and_millijoules() -> None:
    library = FakeLibrary({0: GPU_A})
    reading, errors = read_gpu(library, 0, ("handle", 0), lambda: 4.5)
    assert errors == 0
    assert reading == Reading(
        t_s=4.5, gpu=0, power_w=123.456, temperature_c=61.0, throttle=0x44, counter_j=7000.5
    )


def test_a_field_the_device_does_not_support_is_left_out_without_an_error() -> None:
    library = FakeLibrary({0: {"power_mw": 50000}})
    reading, errors = read_gpu(library, 0, ("handle", 0), lambda: 1.0)
    assert errors == 0
    assert reading == Reading(t_s=1.0, gpu=0, power_w=50.0)


def test_a_failing_field_is_one_error_and_keeps_the_other_fields() -> None:
    fields = {**GPU_A, "temperature_c": FakeNvmlError(UNKNOWN)}
    reading, errors = read_gpu(FakeLibrary({0: fields}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 1
    assert reading.temperature_c is None
    assert reading.power_w == 123.456
    assert reading.counter_j == 7000.5
    assert reading.throttle == 0x44


def test_an_exception_without_a_return_code_is_an_error() -> None:
    fields = {**GPU_A, "power_mw": RuntimeError("lost")}
    reading, errors = read_gpu(FakeLibrary({0: fields}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 1
    assert reading.power_w is None


@pytest.mark.parametrize("value", [True, "120", math.nan, math.inf, None])
def test_a_value_that_is_no_finite_number_is_an_error(value: object) -> None:
    fields = {**GPU_A, "power_mw": value}
    reading, errors = read_gpu(FakeLibrary({0: fields}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 1
    assert reading.power_w is None


@pytest.mark.parametrize("value", [-1, 1.5, "0x4", False])
def test_a_reasons_mask_that_is_no_whole_number_is_an_error(value: object) -> None:
    fields = {**GPU_A, "reasons": value}
    reading, errors = read_gpu(FakeLibrary({0: fields}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 1
    assert reading.throttle is None


@pytest.mark.parametrize("field", ["power_mw", "energy_mj"])
def test_a_power_or_counter_below_zero_is_an_error(field: str) -> None:
    fields = {**GPU_A, field: -1}
    reading, errors = read_gpu(FakeLibrary({0: fields}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 1
    assert reading == Reading(
        t_s=1.0,
        gpu=0,
        power_w=None if field == "power_mw" else 123.456,
        temperature_c=61.0,
        throttle=0x44,
        counter_j=None if field == "energy_mj" else 7000.5,
    )


def test_the_older_name_of_the_reasons_call_is_used_where_the_newer_is_missing() -> None:
    library = OlderLibrary({0: GPU_A})
    reading, errors = read_gpu(library, 0, ("handle", 0), lambda: 1.0)
    assert errors == 0
    assert reading.throttle == 0x44


def test_a_module_without_a_reasons_call_reads_no_mask_and_no_error() -> None:
    class NoReasons(OlderLibrary):
        def __getattribute__(self, name: str) -> Any:
            if name == "nvmlDeviceGetCurrentClocksThrottleReasons":
                raise AttributeError(name)
            return super().__getattribute__(name)

    reading, errors = read_gpu(NoReasons({0: GPU_A}), 0, ("handle", 0), lambda: 1.0)
    assert errors == 0
    assert reading.throttle is None


# --- the polling source ---------------------------------------------------------------


def _run(library: FakeLibrary, gpus: tuple[int, ...] | None, polls: int) -> Collected:
    source = NvmlSource(gpus, 0.1, loader=lambda: library, clock=_clock())
    library.on_power = lambda reads: source.halt() if reads >= polls else None
    sink = Collected()
    thread = threading.Thread(target=source.run, args=(sink,))
    thread.start()
    thread.join(10.0)
    assert thread.is_alive() is False
    return sink


def test_every_gpu_is_read_once_per_interval_until_halted() -> None:
    gpu_b = {**GPU_A, "power_mw": 20000, "reasons": 0}
    library = FakeLibrary({0: GPU_A, 1: gpu_b})
    sink = _run(library, None, polls=4)
    readings, errors, gpus = sink.snapshot()
    assert errors == 0
    assert gpus == (0, 1)
    assert [(r.gpu, r.t_s, r.power_w) for r in readings] == [
        (0, 0.1, 123.456),
        (1, 0.2, 20.0),
        (0, 0.4, 123.456),
        (1, 0.5, 20.0),
    ]
    assert library.calls == ["init", "shutdown"]


class RecordedHalt:
    """Stands in for the halt event: records each wait and is set after ``waits`` waits."""

    def __init__(self, waits: int) -> None:
        self.timeouts: list[float] = []
        self.waits = waits

    def is_set(self) -> bool:
        return len(self.timeouts) >= self.waits

    def wait(self, timeout: float) -> bool:
        self.timeouts.append(timeout)
        return self.is_set()

    def set(self) -> None:
        self.waits = 0


def test_a_late_poll_starts_the_next_interval_from_now(monkeypatch: pytest.MonkeyPatch) -> None:
    # The first poll ends almost a second late; the next polls are one interval apart.
    ticks = iter([0.0, 0.01, 1.0, 1.01, 1.02, 1.11, 1.12, 1.13, 1.14, 1.15])
    source = NvmlSource(
        None, 0.1, loader=lambda: FakeLibrary({0: GPU_A}), clock=lambda: next(ticks)
    )
    halt = RecordedHalt(waits=3)
    monkeypatch.setattr(source, "_halt", halt)
    sink = Collected()
    source.run(sink)
    assert [round(timeout, 9) for timeout in halt.timeouts] == [0.0, 0.08, 0.08]
    readings, errors, _ = sink.snapshot()
    assert errors == 0
    assert [r.t_s for r in readings] == [0.01, 1.01, 1.11]


def test_a_selection_reads_only_the_gpus_named() -> None:
    library = FakeLibrary({0: GPU_A, 1: GPU_A, 2: {**GPU_A, "power_mw": 1000}})
    sink = _run(library, (2,), polls=2)
    readings, errors, gpus = sink.snapshot()
    assert errors == 0
    assert gpus == (2,)
    assert {r.gpu for r in readings} == {2}
    assert [r.power_w for r in readings] == [1.0, 1.0]


def test_errors_of_a_reading_are_counted_and_the_reading_kept() -> None:
    library = FakeLibrary({0: {**GPU_A, "energy_mj": FakeNvmlError(UNKNOWN)}})
    sink = _run(library, None, polls=2)
    readings, errors, _ = sink.snapshot()
    assert errors == 2
    assert len(readings) == 2
    assert readings[0].counter_j is None


def test_a_selected_gpu_that_cannot_be_opened_is_an_error_and_ends_the_source() -> None:
    library = FakeLibrary({0: GPU_A})
    sink = Collected()
    NvmlSource((0, 5), 0.1, loader=lambda: library, clock=_clock()).run(sink)
    assert sink.snapshot() == ((), 1, None)
    assert library.calls == ["init", "shutdown"]


def test_a_library_that_cannot_start_is_an_error() -> None:
    class Broken(FakeLibrary):
        def nvmlInit(self) -> None:
            raise FakeNvmlError(UNKNOWN)

    sink = Collected()
    NvmlSource(None, 0.1, loader=lambda: Broken({0: GPU_A}), clock=_clock()).run(sink)
    assert sink.snapshot() == ((), 1, None)


def test_a_module_that_cannot_be_loaded_is_an_error() -> None:
    def loader() -> Any:
        raise ModuleNotFoundError("pynvml")

    sink = Collected()
    NvmlSource(None, 0.1, loader=loader, clock=_clock()).run(sink)
    assert sink.snapshot() == ((), 1, None)


def test_a_failing_shutdown_is_an_error() -> None:
    class NoShutdown(FakeLibrary):
        def nvmlShutdown(self) -> None:
            raise FakeNvmlError(UNKNOWN)

    sink = _run(NoShutdown({0: GPU_A}), None, polls=1)
    assert sink.snapshot()[1] == 1


def test_a_machine_with_no_gpu_gives_no_reading_and_no_error() -> None:
    sink = Collected()
    NvmlSource(None, 0.1, loader=lambda: FakeLibrary({}), clock=_clock()).run(sink)
    assert sink.snapshot() == ((), 0, ())


def test_the_module_is_looked_for_without_importing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    looked: list[str] = []
    real_find_spec = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> Any:
        if name == "pynvml":
            looked.append(name)
            raise ValueError("pynvml.__spec__ is None")
        return real_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    assert real_available() is False
    assert looked == ["pynvml"]
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, package=None: object())
    assert real_available() is True


def test_the_real_library_is_kept_away_from_the_tests() -> None:
    with pytest.raises(AssertionError, match="GPU management library"):
        nvml.load()
    assert nvml.available() is False
