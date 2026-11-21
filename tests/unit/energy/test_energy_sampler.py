# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The energy meter and its sampler thread, with fake sources."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

import pytest

from pairbench import api
from pairbench.api import EnergyMeter, PowerSampler, Window
from pairbench.energy import nvml, sampler, smi
from pairbench.energy.integrate import (
    REASON_SAMPLER_NOT_OK,
    REASON_TOO_FEW_SAMPLES,
    Collected,
    Reading,
)
from pairbench.energy.sampler import Meter, Sampler, energy_meter, idle_seconds, selection
from pairbench.errors import EXIT_USAGE, Refusal
from pairbench.model import EnergySettings

SETTINGS = EnergySettings(enabled=True, interval_s=0.5, min_samples=3)
KNOWN = (
    Reading(t_s=0.0, gpu=0, power_w=10.0),
    Reading(t_s=0.5, gpu=0, power_w=20.0),
    Reading(t_s=1.0, gpu=0, power_w=30.0),
)
WHOLE = Window(label="", start_s=0.0, end_s=1.0)


class FakeSource:
    """Hands fixed readings over, then waits until it is halted."""

    def __init__(
        self,
        readings: Sequence[Reading] = KNOWN,
        *,
        errors: int = 0,
        named: Sequence[int] | None = None,
        delay_s: float = 0.0,
        fail: BaseException | None = None,
        fail_halt: bool = False,
        ignore_halt: bool = False,
    ) -> None:
        self.name = "fake"
        self._readings = tuple(readings)
        self._errors = errors
        self._named = named
        self._delay_s = delay_s
        self._fail = fail
        self._fail_halt = fail_halt
        self._ignore_halt = ignore_halt
        self.halted = threading.Event()
        self.release = threading.Event()
        self.runs = 0

    def run(self, sink: Collected) -> None:
        self.runs += 1
        if self._fail is not None:
            raise self._fail
        if self._named is not None:
            sink.select(self._named)
        if self._delay_s:
            time.sleep(self._delay_s)
        for reading in self._readings:
            sink.add(reading)
        if self._errors:
            sink.error(self._errors)
        (self.release if self._ignore_halt else self.halted).wait(10.0)

    def halt(self) -> None:
        if self._fail_halt:
            raise RuntimeError("halt failed")
        self.halted.set()


def _meter(source: FakeSource, made: list[tuple[tuple[int, ...] | None, EnergySettings]]) -> Meter:
    def make_source(gpus: tuple[int, ...] | None, settings: EnergySettings) -> FakeSource:
        made.append((gpus, settings))
        return source

    return Meter(make_source=make_source, pause=lambda seconds: None, stop_wait_s=5.0)


# --- the GPU selection -------------------------------------------------------------


def test_a_selection_is_all_or_a_list_of_indices() -> None:
    assert selection("all") is None
    assert selection("0") == (0,)
    assert selection("0,2") == (0, 2)
    assert selection(" 3 , 1,3 ") == (3, 1)


@pytest.mark.parametrize("text", ["", "x", "0,,1", "-1", "1.5", "0;1", chr(0x661)])
def test_another_selection_is_refused(text: str) -> None:
    with pytest.raises(Refusal) as caught:
        selection(text)
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == EXIT_USAGE


# --- sampling a launch ---------------------------------------------------------------


def test_the_meter_and_its_sampler_keep_the_contract() -> None:
    meter: EnergyMeter = energy_meter()
    assert isinstance(meter, Meter)
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    running: PowerSampler = _meter(FakeSource(), made).start("all", SETTINGS)
    assert isinstance(running, Sampler)
    running.stop(())


def test_a_launch_is_sampled_and_its_window_integrated() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    source = FakeSource()
    running = _meter(source, made).start("0", SETTINGS)
    reading = running.stop((WHOLE,))
    assert made == [((0,), SETTINGS)]
    assert source.halted.is_set() is True
    assert reading.source == "fake"
    assert reading.sampler_ok is True
    assert reading.query_errors == 0
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].mean_power_w == 20.0
    assert reading.idle_power_w is None


def test_start_waits_for_the_first_reading() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    source = FakeSource(delay_s=0.2)
    meter = _meter(source, made)
    running = meter.start("all", SETTINGS)
    readings, _errors, _gpus = running._collected.snapshot()
    assert len(readings) >= 1
    running.stop(())


def test_start_does_not_wait_for_a_source_that_gave_up() -> None:
    meter = Meter(
        make_source=lambda gpus, settings: FakeSource(fail=OSError("gone")),
        start_wait_s=30.0,
        stop_wait_s=5.0,
    )
    began = time.monotonic()
    running = meter.start("all", SETTINGS)
    assert time.monotonic() - began < 20.0
    reading = running.stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.query_errors == 1
    assert reading.windows[0].reason == REASON_SAMPLER_NOT_OK


def test_every_gpu_seen_is_covered_when_all_are_selected() -> None:
    readings = (*KNOWN, *(Reading(t_s=r.t_s, gpu=1, power_w=40.0) for r in KNOWN))
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    reading = _meter(FakeSource(readings), made).start("all", SETTINGS).stop((WHOLE,))
    assert made == [(None, SETTINGS)]
    assert reading.windows[0].energy_j == 60.0


def test_the_gpus_a_source_names_are_covered_when_all_are_selected() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    source = FakeSource(KNOWN, named=(0, 1))
    reading = _meter(source, made).start("all", SETTINGS).stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.windows[0].reason == REASON_SAMPLER_NOT_OK


def test_a_selected_gpu_without_enough_readings_leaves_the_window_without_a_value() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    readings = (
        *KNOWN,
        Reading(t_s=0.0, gpu=1, power_w=40.0),
        Reading(t_s=1.0, gpu=1, power_w=40.0),
    )
    reading = _meter(FakeSource(readings), made).start("0,1", SETTINGS).stop((WHOLE,))
    assert reading.sampler_ok is True
    assert reading.windows[0].energy_j is None
    assert reading.windows[0].reason == REASON_TOO_FEW_SAMPLES


def test_query_errors_of_the_source_make_the_sampler_not_ok() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    reading = _meter(FakeSource(errors=2), made).start("0", SETTINGS).stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.query_errors == 2
    assert reading.windows[0].energy_j is None


def test_a_source_that_raises_is_a_query_error_and_stop_does_not_raise() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    source = FakeSource(fail=RuntimeError("broken"))
    reading = _meter(source, made).start("0", SETTINGS).stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.query_errors == 1


def test_a_halt_that_raises_is_a_query_error() -> None:
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    source = FakeSource(fail_halt=True, ignore_halt=True)
    running = _meter(source, made).start("0", SETTINGS)
    source.release.set()
    reading = running.stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.query_errors == 1
    assert reading.windows[0].energy_j is None


def test_a_source_that_does_not_stop_in_time_is_a_query_error() -> None:
    source = FakeSource(ignore_halt=True)
    meter = Meter(make_source=lambda gpus, settings: source, stop_wait_s=0.05)
    reading = meter.start("0", SETTINGS).stop((WHOLE,))
    source.release.set()
    assert reading.sampler_ok is False
    assert reading.query_errors == 1


def test_a_fault_while_integrating_gives_windows_without_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise ZeroDivisionError("made up")

    monkeypatch.setattr(sampler.integrate, "read_windows", broken)
    made: list[tuple[tuple[int, ...] | None, EnergySettings]] = []
    reading = _meter(FakeSource(), made).start("0", SETTINGS).stop((WHOLE, Window("c8", 2, 3)))
    assert reading.sampler_ok is False
    assert reading.query_errors == 1
    assert [(w.label, w.energy_j, w.reason) for w in reading.windows] == [
        ("", None, REASON_SAMPLER_NOT_OK),
        ("c8", None, REASON_SAMPLER_NOT_OK),
    ]


def test_a_sampler_that_never_began_stops_without_waiting() -> None:
    running = Sampler(FakeSource(), (0,), SETTINGS)
    reading = running.stop((WHOLE,))
    assert reading.sampler_ok is False
    assert reading.query_errors == 0


# --- idle power -------------------------------------------------------------------------


def test_idle_power_is_the_mean_of_a_short_stretch_and_is_stamped_later() -> None:
    idle = (
        Reading(t_s=0.0, gpu=0, power_w=4.0),
        Reading(t_s=0.5, gpu=0, power_w=6.0),
        Reading(t_s=1.0, gpu=0, power_w=8.0),
    )
    sources = [FakeSource(idle), FakeSource(KNOWN), FakeSource(KNOWN)]
    paused: list[float] = []
    meter = Meter(
        make_source=lambda gpus, settings: sources.pop(0),
        pause=paused.append,
        stop_wait_s=5.0,
    )
    assert meter.idle_power_w("0", SETTINGS) == 6.0
    assert paused == [2.0]
    reading = meter.start("0", SETTINGS).stop((WHOLE,))
    assert reading.idle_power_w == 6.0
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].mean_power_w == 20.0
    other = meter.start("all", SETTINGS).stop((WHOLE,))
    assert other.idle_power_w is None


class InterruptedWait:
    """Stands in for the first-reading event: waiting on it is interrupted."""

    def set(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> bool:
        raise KeyboardInterrupt


def test_an_interrupt_while_waiting_for_the_first_reading_ends_the_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FakeSource()
    power = Sampler(source, (0,), SETTINGS, stop_wait_s=5.0)
    monkeypatch.setattr(power._collected, "started", InterruptedWait())
    with pytest.raises(KeyboardInterrupt):
        power.begin(5.0)
    assert source.halted.is_set()


def test_an_interrupt_during_the_idle_stretch_ends_the_source() -> None:
    source = FakeSource()

    def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt

    meter = Meter(make_source=lambda gpus, settings: source, pause=interrupted, stop_wait_s=5.0)
    with pytest.raises(KeyboardInterrupt):
        meter.idle_power_w("0", SETTINGS)
    assert source.halted.is_set()


def test_the_idle_stretch_runs_one_interval_more_than_min_samples() -> None:
    assert idle_seconds(SETTINGS) == 2.0
    assert idle_seconds(EnergySettings()) == pytest.approx(2.2)


def test_idle_power_is_none_after_a_query_error_or_with_too_few_readings() -> None:
    meter = Meter(
        make_source=lambda gpus, settings: FakeSource(errors=1),
        pause=lambda seconds: None,
        stop_wait_s=5.0,
    )
    assert meter.idle_power_w("0", SETTINGS) is None
    meter = Meter(
        make_source=lambda gpus, settings: FakeSource(KNOWN[:2]),
        pause=lambda seconds: None,
        stop_wait_s=5.0,
    )
    assert meter.idle_power_w("0", SETTINGS) is None
    assert meter.start("0", SETTINGS).stop(()).idle_power_w is None


# --- which source --------------------------------------------------------------------------


def test_making_the_meter_looks_at_nothing() -> None:
    meter = energy_meter()
    assert isinstance(meter, Meter)
    assert api.DELEGATES["meter"] == (
        "pairbench.energy.sampler",
        "energy_meter",
        api.MakeEnergyMeter,
    )


def test_the_library_is_the_source_when_the_gpu_extra_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nvml, "available", lambda: True)
    source = Meter()._default_source((1,), SETTINGS)
    assert isinstance(source, nvml.NvmlSource)
    assert source.name == "nvml"


def test_the_query_process_is_the_source_otherwise() -> None:
    source = Meter()._default_source(None, SETTINGS)
    assert isinstance(source, smi.SmiSource)
    assert source.name == "nvidia-smi"


def test_the_query_process_reads_the_field_list_once_per_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helps: list[Sequence[str]] = []

    def read_help(argv: Sequence[str]) -> str | None:
        helps.append(argv)
        return None

    def spawn(argv: Sequence[str]) -> object:
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(smi, "_read_help", read_help)
    monkeypatch.setattr(smi, "_spawn", spawn)
    meter = Meter(stop_wait_s=5.0)
    for _ in range(2):
        reading = meter.start("all", SETTINGS).stop((WHOLE,))
        assert reading.source == "nvidia-smi"
        assert reading.sampler_ok is False
        assert reading.query_errors == 1
    assert len(helps) == 1
