# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The energy of the windows of a launch, from fixed readings."""

from __future__ import annotations

import threading

from pairbench.api import EnergyReading, Window
from pairbench.energy.integrate import (
    COUNTER_TOLERANCE,
    REASON_NOT_FINITE,
    REASON_SAMPLER_NOT_OK,
    REASON_TOO_FEW_SAMPLES,
    WINDOW_REASONS,
    Collected,
    Reading,
    gpus_seen,
    max_temperature,
    mean_power_w,
    read_windows,
    sampler_ok,
    throttle_events,
)
from pairbench.model import (
    CLOCK_REASONS_NOT_COUNTED,
    ENERGY_EXCLUDES,
    ENERGY_SCOPE,
    METRIC_ENERGY_J,
    METRIC_MEAN_POWER_W,
    NOTE_ENERGY_COUNTER_DISAGREES,
)

WHOLE = Window(label="", start_s=0.0, end_s=1.0)


def _power(gpu: int, *points: tuple[float, float]) -> list[Reading]:
    return [Reading(t_s=t, gpu=gpu, power_w=p) for t, p in points]


def _read(
    readings: list[Reading],
    windows: tuple[Window, ...] = (WHOLE,),
    *,
    gpus: tuple[int, ...] = (0,),
    min_samples: int = 3,
    query_errors: int = 0,
    idle_power_w: float | None = None,
) -> EnergyReading:
    return read_windows(
        readings,
        windows,
        gpus=gpus,
        min_samples=min_samples,
        source="fake",
        query_errors=query_errors,
        idle_power_w=idle_power_w,
    )


# --- a known answer ---------------------------------------------------------


def test_samples_of_10_20_30_watts_at_0_half_and_1_second_integrate_to_20_joules() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)))
    (window,) = reading.windows
    assert reading.sampler_ok is True
    assert window.energy_j == 20.0
    assert window.mean_power_w == 20.0
    assert window.n_samples == 3
    assert window.reason is None


def test_the_known_answer_reaches_the_cases_of_the_launch() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)))
    by_case = {s.case: s for s in reading.samples()}
    assert set(by_case) == {"energy_j[gpu]", "mean_power_w[gpu]"}
    assert by_case["energy_j[gpu]"].value == 20.0
    assert by_case["energy_j[gpu]"].unit == "J"
    assert by_case["energy_j[gpu]"].better == "lower"
    assert by_case["mean_power_w[gpu]"].unit == "W"


# --- several GPUs, windows, load levels -------------------------------------


def test_the_energy_of_several_gpus_is_summed() -> None:
    readings = _power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)) + _power(
        1, (0.0, 40.0), (0.5, 40.0), (1.0, 40.0)
    )
    (window,) = _read(readings, gpus=(0, 1)).windows
    assert window.energy_j == 60.0
    assert window.mean_power_w == 60.0


def test_a_gpu_with_too_few_samples_leaves_the_sum_without_a_value() -> None:
    readings = _power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)) + _power(
        1, (0.0, 40.0), (1.0, 40.0)
    )
    (window,) = _read(readings, gpus=(0, 1)).windows
    assert window.energy_j is None
    assert window.mean_power_w is None
    assert window.reason == REASON_TOO_FEW_SAMPLES
    assert window.n_samples == 2


def test_a_selected_gpu_that_gave_no_reading_makes_the_sampler_not_ok() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)), gpus=(0, 1))
    assert reading.sampler_ok is False
    assert reading.windows[0].reason == REASON_SAMPLER_NOT_OK


def test_each_load_level_has_its_own_window_and_cases() -> None:
    readings = _power(
        0, (0.0, 10.0), (0.5, 10.0), (1.0, 10.0), (2.0, 30.0), (2.5, 30.0), (3.0, 30.0)
    )
    windows = (Window("c1", 0.0, 1.0), Window("c32", 2.0, 3.0))
    reading = _read(readings, windows)
    assert [(w.label, w.energy_j) for w in reading.windows] == [("c1", 10.0), ("c32", 30.0)]
    cases = {s.case: s.value for s in reading.samples()}
    assert cases == {
        "c1/energy_j[gpu]": 10.0,
        "c1/mean_power_w[gpu]": 10.0,
        "c32/energy_j[gpu]": 30.0,
        "c32/mean_power_w[gpu]": 30.0,
    }


def test_samples_on_the_ends_of_a_window_are_inside_it_and_others_are_not() -> None:
    readings = _power(0, (-0.5, 99.0), (0.0, 10.0), (0.5, 20.0), (1.0, 30.0), (1.5, 99.0))
    (window,) = _read(readings).windows
    assert window.n_samples == 3
    assert window.energy_j == 20.0


def test_mean_power_divides_by_the_time_the_samples_span() -> None:
    readings = _power(0, (0.25, 8.0), (0.5, 8.0), (0.75, 8.0))
    (window,) = _read(readings).windows
    assert window.energy_j == 4.0
    assert window.mean_power_w == 8.0


def test_readings_out_of_order_are_put_in_time_order_first() -> None:
    readings = _power(0, (1.0, 30.0), (0.0, 10.0), (0.5, 20.0))
    assert _read(readings).windows[0].energy_j == 20.0


# --- refusing a value -------------------------------------------------------


def test_a_value_is_never_estimated_from_one_sample() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (5.0, 30.0)), min_samples=2)
    (window,) = reading.windows
    assert reading.sampler_ok is True
    assert window.n_samples == 2
    assert window.energy_j == 7.5
    one = _read(_power(0, (0.0, 10.0), (5.0, 20.0), (6.0, 30.0)), min_samples=2)
    assert one.windows[0].energy_j is None
    assert one.windows[0].n_samples == 1
    assert one.windows[0].reason == REASON_TOO_FEW_SAMPLES


def test_fewer_samples_than_the_settings_require_give_no_value() -> None:
    readings = _power(0, *((i * 0.1, 10.0) for i in range(9)))
    (window,) = _read(readings, min_samples=10).windows
    assert window.energy_j is None
    assert window.n_samples == 9
    assert window.reason == REASON_TOO_FEW_SAMPLES
    readings = _power(0, *((i * 0.1, 10.0) for i in range(10)))
    (window,) = _read(readings, min_samples=10).windows
    assert window.n_samples == 10
    assert window.energy_j is not None


def test_a_query_error_makes_the_sampler_not_ok_and_no_window_gets_a_value() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)), query_errors=1)
    assert reading.sampler_ok is False
    assert reading.query_errors == 1
    (window,) = reading.windows
    assert window.energy_j is None
    assert window.mean_power_w is None
    assert window.counter_j is None
    assert window.reason == REASON_SAMPLER_NOT_OK
    assert reading.samples() == []


def test_sampler_ok_needs_two_power_samples_of_every_gpu_and_no_query_error() -> None:
    two = _power(0, (0.0, 1.0), (1.0, 1.0))
    assert sampler_ok(two, (0,), 0) is True
    assert sampler_ok(two[:1], (0,), 0) is False
    assert sampler_ok(two, (0,), 1) is False
    assert sampler_ok(two, (), 0) is False
    no_power = [Reading(t_s=0.0, gpu=0, temperature_c=40.0), Reading(t_s=1.0, gpu=0)]
    assert sampler_ok(no_power, (0,), 0) is False


def test_samples_that_span_no_time_give_no_value() -> None:
    (window,) = _read(_power(0, (0.5, 10.0), (0.5, 20.0), (0.5, 30.0))).windows
    assert window.energy_j is None
    assert window.reason == REASON_TOO_FEW_SAMPLES


def test_a_sum_too_large_for_a_number_gives_no_value() -> None:
    (window,) = _read(_power(0, (0.0, 1e308), (0.5, 1e308), (1.0, 1e308))).windows
    assert window.energy_j is None
    assert window.reason == REASON_NOT_FINITE


def test_the_window_reasons_are_fixed_words() -> None:
    assert WINDOW_REASONS == ("sampler_not_ok", "too_few_samples", "not_finite")


# --- the cumulative counter beside the integral -----------------------------


def _with_counter(*counters: float | None) -> list[Reading]:
    points = ((0.0, 10.0), (0.5, 20.0), (1.0, 30.0))
    return [
        Reading(t_s=t, gpu=0, power_w=p, counter_j=c)
        for (t, p), c in zip(points, counters, strict=True)
    ]


def test_the_counter_difference_is_recorded_beside_the_integral() -> None:
    reading = _read(_with_counter(1000.0, 1010.0, 1020.5))
    (window,) = reading.windows
    assert window.energy_j == 20.0
    assert window.counter_j == 20.5
    assert reading.notes == ()


def test_a_counter_exactly_5_percent_away_gives_no_note() -> None:
    reading = _read(_with_counter(1000.0, 1010.0, 1021.0))
    assert reading.windows[0].counter_j == 21.0
    assert reading.notes == ()
    below = _read(_with_counter(1000.0, 1010.0, 1019.0))
    assert below.windows[0].counter_j == 19.0
    assert below.notes == ()


def test_a_counter_more_than_5_percent_away_is_a_loud_note() -> None:
    reading = _read(_with_counter(1000.0, 1010.0, 1021.25))
    assert reading.windows[0].counter_j == 21.25
    (note,) = reading.notes
    assert note[0] == NOTE_ENERGY_COUNTER_DISAGREES
    assert note[1] == (
        "the launch: the GPU energy counter gave 21.25 J and the integral of power 20 J, "
        "6.2 percent apart; the two may differ by 5 percent at most"
    )
    below = _read(_with_counter(1000.0, 1010.0, 1018.75))
    assert [code for code, _ in below.notes] == [NOTE_ENERGY_COUNTER_DISAGREES]
    assert COUNTER_TOLERANCE == 0.05


def test_the_note_of_a_load_level_names_its_window() -> None:
    readings = [
        Reading(t_s=t, gpu=0, power_w=10.0, counter_j=c)
        for t, c in ((0.0, 0.0), (0.5, 8.0), (1.0, 16.0))
    ]
    reading = _read(readings, (Window("c8", 0.0, 1.0),))
    (note,) = reading.notes
    assert note[1].startswith("window c8: the GPU energy counter gave 16 J")


def test_the_counter_needs_min_samples_distinct_readings_in_the_window() -> None:
    reading = _read(_with_counter(1000.0, 1000.0, 1021.0))
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].counter_j is None
    assert reading.notes == ()
    missing = _read(_with_counter(1000.0, None, 1021.0))
    assert missing.windows[0].counter_j is None


def test_a_counter_that_went_back_gives_no_difference() -> None:
    reading = _read(_with_counter(1000.0, 1010.0, 5.0))
    assert reading.windows[0].counter_j is None
    assert reading.notes == ()


def test_a_counter_that_goes_back_inside_the_window_gives_no_difference() -> None:
    reading = _read(_with_counter(1000.0, 5.0, 1020.0))
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].counter_j is None
    assert reading.notes == ()


def test_a_counter_difference_too_large_for_a_number_gives_none() -> None:
    counters = ((0.0, 0.0), (0.5, 1e308), (1.0, 1.7e308))
    readings = [
        Reading(t_s=t, gpu=gpu, power_w=10.0, counter_j=c) for gpu in (0, 1) for t, c in counters
    ]
    reading = _read(readings, gpus=(0, 1))
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].counter_j is None
    assert reading.notes == ()


def test_the_counters_of_several_gpus_are_summed_and_need_every_gpu() -> None:
    gpu1 = [
        Reading(t_s=t, gpu=1, power_w=40.0, counter_j=c)
        for t, c in ((0.0, 500.0), (0.5, 520.0), (1.0, 540.0))
    ]
    both = _read(_with_counter(1000.0, 1010.0, 1020.0) + gpu1, gpus=(0, 1))
    assert both.windows[0].energy_j == 60.0
    assert both.windows[0].counter_j == 60.0
    gpu1_without = [Reading(t_s=r.t_s, gpu=1, power_w=40.0) for r in gpu1]
    one = _read(_with_counter(1000.0, 1010.0, 1020.0) + gpu1_without, gpus=(0, 1))
    assert one.windows[0].energy_j == 60.0
    assert one.windows[0].counter_j is None


# --- witnesses from the same source ------------------------------------------


def _masks(gpu: int, *masks: int | None) -> list[Reading]:
    return [
        Reading(t_s=float(i), gpu=gpu, power_w=10.0, throttle=mask) for i, mask in enumerate(masks)
    ]


def test_throttle_events_count_each_counted_reason_that_becomes_active() -> None:
    assert throttle_events(_masks(0, 0x0, 0x4, 0x4, 0x0, 0x44), (0,)) == 3
    assert throttle_events(_masks(0, 0x8, 0x8, 0x8), (0,)) == 1
    assert throttle_events(_masks(0, 0x0, 0x0), (0,)) == 0


def test_idle_and_setting_reasons_are_not_throttle_events() -> None:
    assert throttle_events(_masks(0, 0x1, 0x3, 0x101, 0x103, 0x0), (0,)) == 0
    assert CLOCK_REASONS_NOT_COUNTED == 0x103


def test_every_other_reason_is_a_throttle_event() -> None:
    assert throttle_events(_masks(0, 0x1, 0x11), (0,)) == 1
    assert throttle_events(_masks(0, 0x0, 0x200, 0x600), (0,)) == 2
    assert throttle_events(_masks(0, 0xEC), (0,)) == 5
    assert throttle_events(_masks(0, 0x103, 0x1103), (0,)) == 1


def test_throttle_events_of_several_gpus_are_added() -> None:
    readings = _masks(0, 0x0, 0x20) + _masks(1, 0x80, 0x80)
    assert throttle_events(readings, (0, 1)) == 2


def test_throttle_events_are_unknown_unless_every_reading_holds_the_mask() -> None:
    assert throttle_events(_masks(0, 0x0, None, 0x0), (0,)) is None
    assert throttle_events(_masks(0, 0x0), (0, 1)) is None
    assert throttle_events([], (0,)) is None
    assert throttle_events(_masks(0, 0x0), ()) is None


def test_a_reading_carries_the_throttle_events_and_the_highest_temperature() -> None:
    readings = [
        Reading(t_s=0.0, gpu=0, power_w=10.0, temperature_c=41.0, throttle=0x0),
        Reading(t_s=0.5, gpu=0, power_w=20.0, temperature_c=57.0, throttle=0x40),
        Reading(t_s=1.0, gpu=0, power_w=30.0, temperature_c=None, throttle=0x40),
    ]
    reading = _read(readings)
    assert reading.throttle_events == 1
    assert reading.max_temperature_c == 57.0
    assert max_temperature(_power(0, (0.0, 1.0))) is None


def test_idle_power_is_recorded_and_never_subtracted() -> None:
    reading = _read(_power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)), idle_power_w=5.0)
    assert reading.idle_power_w == 5.0
    assert reading.windows[0].energy_j == 20.0
    assert reading.windows[0].mean_power_w == 20.0


def test_the_mean_power_of_an_idle_stretch_is_summed_over_the_gpus() -> None:
    readings = _power(0, (0.0, 10.0), (0.5, 20.0), (1.0, 30.0)) + _power(
        1, (0.0, 5.0), (0.5, 5.0), (1.0, 5.0)
    )
    assert mean_power_w(readings, (0, 1), 3) == 25.0
    assert mean_power_w(readings, (0, 1), 4) is None
    assert mean_power_w([], (0,), 2) is None


def test_the_scope_label_is_the_gpu_alone() -> None:
    assert METRIC_ENERGY_J == "energy_j[gpu]"
    assert METRIC_MEAN_POWER_W == "mean_power_w[gpu]"
    assert ENERGY_SCOPE == "gpu"
    assert ENERGY_EXCLUDES == ("cpu", "memory", "storage", "cooling", "power supply losses")


# --- what sources hand over ---------------------------------------------------


def test_the_collection_keeps_readings_errors_and_the_gpus_named() -> None:
    collected = Collected()
    assert collected.started.is_set() is False
    collected.error(2)
    collected.select((3, 1))
    collected.add(Reading(t_s=0.0, gpu=1, power_w=1.0))
    assert collected.started.is_set() is True
    readings, errors, gpus = collected.snapshot()
    assert readings == (Reading(t_s=0.0, gpu=1, power_w=1.0),)
    assert errors == 2
    assert gpus == (3, 1)


def test_settling_releases_a_wait_for_the_first_reading() -> None:
    collected = Collected()
    waiter = threading.Thread(target=collected.started.wait)
    waiter.start()
    collected.settle()
    waiter.join(5.0)
    assert waiter.is_alive() is False
    assert collected.snapshot() == ((), 0, None)


def test_the_gpus_seen_are_in_index_order() -> None:
    readings = _power(2, (0.0, 1.0)) + _power(0, (0.0, 1.0)) + _power(2, (1.0, 1.0))
    assert gpus_seen(readings) == (0, 2)
