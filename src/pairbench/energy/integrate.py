# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The energy of each window of a launch, from the readings of a power sampler.

Both sources of power readings, the GPU management library and the
``nvidia-smi`` query process, produce ``Reading`` records. This module is
where they meet: ``read_windows`` turns the readings of one launch into an
``EnergyReading``.

For each window and each selected GPU, the power readings whose time lies
inside the window (both ends included) are integrated with the trapezoid
rule of ``pairbench.model.trapezoid``. The energy of several GPUs is summed.
A window gets no value when the sampler is not ok, or when one of the GPUs
has fewer power readings inside it than ``energy.min_samples``: a value is
never estimated from one sample, and a sum that misses a GPU is no sum.

Mean power is the energy of each GPU divided by the time its readings span,
summed over the GPUs.

Where a GPU also gives its own cumulative energy counter, the difference of
the counter over the window is recorded beside the integral, when every GPU
gave at least ``energy.min_samples`` distinct values of it inside the
window. A counter that goes back between any two of its readings inside the
window, as it does when the driver is loaded again, gives no difference.
When the two disagree by more than 5 percent of the integral, the
reading carries a loud note.

Throttle events are counted from the bit mask of clock event reasons both
sources read. Every reason counts except the three that describe an idle GPU
or a setting rather than clocks held down under load: GPU idle (``0x1``),
the applications clocks setting (``0x2``) and the display clock setting
(``0x100``). The reasons that count include SW power cap (``0x4``), HW
slowdown (``0x8``), sync boost (``0x10``), SW thermal slowdown (``0x20``),
HW thermal slowdown (``0x40``), HW power brake slowdown (``0x80``), board
limit (``0x200``) and reliability (``0x400``); a reason a later driver adds
counts as well. Bit values from the module of nvidia-ml-py 13.615.71
(https://pypi.org/project/nvidia-ml-py/13.615.71/), whose
``nvmlClocksThrottleReason*`` names cover every bit above and whose
``nvmlClocksEventReason*`` names cover all but board limit and
reliability; the meaning of each reason from the NVML API Reference Guide,
version 620, page "NvmlClocksEventReasons"
(https://docs.nvidia.com/deploy/nvml-api/api/group__nvmlClocksEventReasons.html).
An event is a counted reason that is active in a reading and was not active
in the reading of the same GPU before it; a reason active in the first
reading counts as one event. The mask and the rule are the model's
``CLOCK_REASONS_NOT_COUNTED`` and ``clock_events``, which the machine checks
use as well.
"""

from __future__ import annotations

import itertools
import math
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from pairbench.api import EnergyReading, EnergyWindow, Window
from pairbench.model import NOTE_ENERGY_COUNTER_DISAGREES, clock_events, trapezoid

# How far the GPU's own energy counter may lie from the integral, as a share
# of the integral, before the reading carries a loud note.
COUNTER_TOLERANCE: Final = 0.05

# Why a window has no value: the words recorded in ``EnergyWindow.reason``.
REASON_SAMPLER_NOT_OK: Final = "sampler_not_ok"
REASON_TOO_FEW_SAMPLES: Final = "too_few_samples"
REASON_NOT_FINITE: Final = "not_finite"
WINDOW_REASONS: Final[tuple[str, ...]] = (
    REASON_SAMPLER_NOT_OK,
    REASON_TOO_FEW_SAMPLES,
    REASON_NOT_FINITE,
)


@dataclass(frozen=True)
class Reading:
    """What one source read from one GPU at one time.

    ``t_s`` is in ``time.monotonic()`` seconds. ``power_w`` is the power the
    GPU reported, in watts; ``counter_j`` its cumulative energy counter, in
    joules; ``temperature_c`` its temperature, in degrees Celsius;
    ``throttle`` the bit mask of active clock event reasons. A field is
    ``None`` when the GPU does not report it or the value could not be read;
    the source counts the second case as a query error.
    """

    t_s: float
    gpu: int
    power_w: float | None = None
    temperature_c: float | None = None
    throttle: int | None = None
    counter_j: float | None = None


class Collected:
    """The readings and query errors a source hands over while it runs.

    A source runs on the sampler's own thread and calls ``add`` for each
    reading, ``error`` for each value it could not read, and ``select`` once
    it knows which GPUs it reads. ``started`` is set at the first reading,
    and when the source gives up before one, so that a caller waiting for
    the first reading is not held longer than needed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readings: list[Reading] = []
        self._errors = 0
        self._gpus: tuple[int, ...] | None = None
        self.started = threading.Event()

    def add(self, reading: Reading) -> None:
        """Keep one reading."""
        with self._lock:
            self._readings.append(reading)
        self.started.set()

    def error(self, count: int = 1) -> None:
        """Count values that could not be read."""
        with self._lock:
            self._errors += count

    def select(self, gpus: Sequence[int]) -> None:
        """Record the GPUs the source reads."""
        with self._lock:
            self._gpus = tuple(gpus)

    def settle(self) -> None:
        """Say that no first reading is coming, so that nobody waits for one."""
        self.started.set()

    def snapshot(self) -> tuple[tuple[Reading, ...], int, tuple[int, ...] | None]:
        """Return the readings so far, the query errors and the GPUs the source named."""
        with self._lock:
            return tuple(self._readings), self._errors, self._gpus


def gpus_seen(readings: Iterable[Reading]) -> tuple[int, ...]:
    """Return the GPUs that gave at least one reading, in index order."""
    return tuple(sorted({r.gpu for r in readings}))


def _of_gpu(readings: Sequence[Reading], gpu: int) -> list[Reading]:
    """Return the readings of one GPU in time order (equal times keep their order)."""
    return sorted((r for r in readings if r.gpu == gpu), key=lambda r: r.t_s)


def _inside(reading: Reading, window: Window) -> bool:
    return window.start_s <= reading.t_s <= window.end_s


def sampler_ok(readings: Sequence[Reading], gpus: Sequence[int], query_errors: int) -> bool:
    """Say whether the sampler is ok: no query error, and two power readings of every GPU."""
    if query_errors or not gpus:
        return False
    return all(
        sum(1 for r in readings if r.gpu == gpu and r.power_w is not None) >= 2 for gpu in gpus
    )


def throttle_events(readings: Sequence[Reading], gpus: Sequence[int]) -> int | None:
    """Count the throttle events of the selected GPUs.

    ``None`` means the events could not be read: no GPU is known, a GPU gave
    no reading, or one of its readings holds no reasons mask. A count of 0
    is a reading that saw none.
    """
    if not gpus:
        return None
    events = 0
    for gpu in gpus:
        mine = _of_gpu(readings, gpu)
        if not mine or any(r.throttle is None for r in mine):
            return None
        before = 0
        for r in mine:
            mask = r.throttle or 0
            events += clock_events(before, mask)
            before = mask
    return events


def max_temperature(readings: Iterable[Reading]) -> float | None:
    """Return the highest temperature read, or ``None`` when none was read."""
    seen = [r.temperature_c for r in readings if r.temperature_c is not None]
    return max(seen) if seen else None


def _counter_j(
    readings: Sequence[Reading], window: Window, gpus: Sequence[int], need: int
) -> float | None:
    """Return the counter difference over the window, summed over the GPUs, or ``None``."""
    total = 0.0
    for gpu in gpus:
        values = [
            r.counter_j
            for r in _of_gpu(readings, gpu)
            if _inside(r, window) and r.counter_j is not None
        ]
        if len(set(values)) < need:
            return None
        if any(later < earlier for earlier, later in itertools.pairwise(values)):
            return None
        total += values[-1] - values[0]
    return total if math.isfinite(total) else None


def _disagreement(label: str, energy_j: float, counter_j: float) -> tuple[str, str] | None:
    """Return the loud note for a counter that lies more than 5 percent from the integral."""
    if abs(counter_j - energy_j) <= COUNTER_TOLERANCE * abs(energy_j):
        return None
    where = f"window {label}" if label else "the launch"
    if energy_j:
        apart = f"{abs(counter_j - energy_j) / abs(energy_j) * 100:.1f} percent apart"
    else:
        apart = "apart while the integral is zero"
    return (
        NOTE_ENERGY_COUNTER_DISAGREES,
        f"{where}: the GPU energy counter gave {counter_j:.6g} J and the integral of "
        f"power {energy_j:.6g} J, {apart}; the two may differ by 5 percent at most",
    )


def _window(
    readings: Sequence[Reading],
    window: Window,
    gpus: Sequence[int],
    min_samples: int,
    ok: bool,
) -> tuple[EnergyWindow, tuple[str, str] | None]:
    """Integrate one window and return it with the note it gives, if any."""
    series = [
        [r for r in _of_gpu(readings, gpu) if r.power_w is not None and _inside(r, window)]
        for gpu in gpus
    ]
    n_samples = min((len(s) for s in series), default=0)

    def without(reason: str) -> tuple[EnergyWindow, None]:
        empty = EnergyWindow(
            label=window.label,
            start_s=window.start_s,
            end_s=window.end_s,
            energy_j=None,
            mean_power_w=None,
            n_samples=n_samples,
            reason=reason,
        )
        return empty, None

    if not ok:
        return without(REASON_SAMPLER_NOT_OK)
    if n_samples < min_samples:
        return without(REASON_TOO_FEW_SAMPLES)
    energy_j = 0.0
    mean_power_w = 0.0
    for points in series:
        times = [r.t_s for r in points]
        powers = [r.power_w for r in points if r.power_w is not None]
        span = times[-1] - times[0]
        if span <= 0:
            return without(REASON_TOO_FEW_SAMPLES)
        energy = trapezoid(times, powers)
        energy_j += energy
        mean_power_w += energy / span
    if not (math.isfinite(energy_j) and math.isfinite(mean_power_w)):
        return without(REASON_NOT_FINITE)
    counter_j = _counter_j(readings, window, gpus, min_samples)
    note = None if counter_j is None else _disagreement(window.label, energy_j, counter_j)
    result = EnergyWindow(
        label=window.label,
        start_s=window.start_s,
        end_s=window.end_s,
        energy_j=energy_j,
        mean_power_w=mean_power_w,
        n_samples=n_samples,
        counter_j=counter_j,
    )
    return result, note


def read_windows(
    readings: Sequence[Reading],
    windows: Sequence[Window],
    *,
    gpus: Sequence[int],
    min_samples: int,
    source: str,
    query_errors: int,
    idle_power_w: float | None = None,
) -> EnergyReading:
    """Turn the readings of one launch into the energy of each window.

    ``gpus`` are the GPUs the reading covers: the selected ones, or every GPU
    that gave a reading when all are selected. ``query_errors`` counts the
    values the source could not read. ``n_samples`` of a window is the
    smallest number of power readings any one GPU has inside it, the number
    ``min_samples`` is held against.
    """
    ok = sampler_ok(readings, gpus, query_errors)
    done = [_window(readings, w, gpus, min_samples, ok) for w in windows]
    return EnergyReading(
        source=source,
        sampler_ok=ok,
        query_errors=query_errors,
        windows=tuple(w for w, _ in done),
        throttle_events=throttle_events(readings, gpus),
        max_temperature_c=max_temperature(readings),
        idle_power_w=idle_power_w,
        notes=tuple(note for _, note in done if note is not None),
    )


def mean_power_w(
    readings: Sequence[Reading], gpus: Sequence[int], min_samples: int
) -> float | None:
    """Return the mean power of a stretch with nothing launched, summed over the GPUs.

    The stretch runs from the first reading to the last. ``None`` when a GPU
    gave fewer power readings than ``min_samples``, or none of its readings
    span any time.
    """
    if not readings or not gpus:
        return None
    whole = Window(
        label="",
        start_s=min(r.t_s for r in readings),
        end_s=max(r.t_s for r in readings),
    )
    window, _ = _window(readings, whole, gpus, min_samples, ok=True)
    return window.mean_power_w
