# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The energy meter of a run and its power sampler.

``energy_meter()`` makes the meter. It looks at nothing when it is made: the
source is picked when sampling starts. The source is the GPU management
library when the module of the ``gpu`` extra can be imported, and one
long-running ``nvidia-smi`` query process otherwise. Both hand the same
``Reading`` records to the sampler, and ``pairbench.energy.integrate`` makes
the energy of each window from them.

``Meter.start`` begins sampling on a thread of its own and waits, for at
most ``START_WAIT_S`` seconds, for the first reading, so that the window
that follows is covered from its start. ``Sampler.stop`` ends the sampling,
waits for the source to finish, and integrates each window. It never raises:
a fault of the sampler is a query error, which makes the sampler not ok, so
that no window gets a value.

``Meter.idle_power_w`` samples a short stretch with nothing launched: from
the first reading for ``energy.min_samples`` intervals and one more, so that
each GPU gives about two readings more than ``energy.min_samples``. The mean
power of
that stretch, summed over the GPUs, is remembered for the GPU selection and
stamped into every later reading of the same selection. It is recorded and
never subtracted. It is ``None`` when the sampler had a query error or too
few readings.

An interruption while ``start`` waits for the first reading, or during the
idle stretch, ends the source and its query process before it goes on.

A thread started after the tool moved itself off a pinned CPU set runs
where the tool runs, and so does the query process it starts.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from typing import Final, Protocol

from pairbench.api import EnergyReading, EnergyWindow, Window
from pairbench.energy import integrate, nvml, smi
from pairbench.energy.integrate import Collected
from pairbench.errors import Refusal
from pairbench.model import EnergySettings

# How long ``start`` waits for the first reading, and ``stop`` for the source to end.
START_WAIT_S: Final = 10.0
STOP_WAIT_S: Final = 20.0

ALL_GPUS: Final = "all"


class Source(Protocol):
    """A source of power readings, run on the sampler's thread."""

    @property
    def name(self) -> str: ...

    def run(self, sink: Collected) -> None:
        """Hand readings to ``sink`` until ``halt`` is called."""
        ...

    def halt(self) -> None:
        """Make ``run`` return soon."""
        ...


MakeSource = Callable[[tuple[int, ...] | None, EnergySettings], Source]


def idle_seconds(settings: EnergySettings) -> float:
    """Return how long the idle stretch runs after its first reading.

    ``energy.min_samples`` intervals and one more, so that each GPU gives at
    least ``energy.min_samples`` readings when one arrives a little late.
    """
    return (settings.min_samples + 1) * settings.interval_s


def selection(gpus: str) -> tuple[int, ...] | None:
    """Read a GPU selection: ``None`` for ``all``, else the indices in the order given.

    A selection that is neither ``all`` nor a comma list of GPU indices is
    refused with ``E_USAGE``.
    """
    text = gpus.strip()
    if text == ALL_GPUS:
        return None
    parts = [part.strip() for part in text.split(",")]
    if not parts or not all(part.isascii() and part.isdigit() for part in parts):
        raise Refusal("E_USAGE", f"a GPU selection is 'all' or a comma list of indices: {gpus!r}")
    return tuple(dict.fromkeys(int(part) for part in parts))


class Sampler:
    """A running power sampler: one thread that runs one source."""

    def __init__(
        self,
        source: Source,
        gpus: tuple[int, ...] | None,
        settings: EnergySettings,
        *,
        idle_power_w: float | None = None,
        stop_wait_s: float = STOP_WAIT_S,
    ) -> None:
        self._source = source
        self._gpus = gpus
        self._settings = settings
        self._idle_power_w = idle_power_w
        self._stop_wait_s = stop_wait_s
        self._collected = Collected()
        self._thread = threading.Thread(target=self._run, name="pairbench-power", daemon=True)

    def _run(self) -> None:
        try:
            self._source.run(self._collected)
        except Exception:
            self._collected.error()
        finally:
            self._collected.settle()

    def begin(self, wait_s: float) -> None:
        """Start the thread and wait, at most ``wait_s`` seconds, for the first reading.

        When the wait is interrupted, the source is ended before the
        interruption goes on.
        """
        self._thread.start()
        try:
            self._collected.started.wait(wait_s)
        except BaseException:
            self.cancel()
            raise

    def cancel(self) -> None:
        """End the source and wait for its thread, keeping no reading."""
        self._halt()

    def _halt(self) -> int:
        """End the source and wait for its thread; return the query errors that adds."""
        errors = 0
        try:
            self._source.halt()
        except Exception:
            errors += 1
        if self._thread.ident is not None:
            self._thread.join(self._stop_wait_s)
            if self._thread.is_alive():
                errors += 1
        return errors

    def readings(self) -> tuple[tuple[integrate.Reading, ...], int, tuple[int, ...]]:
        """Stop and return the readings, the query errors and the GPUs they cover."""
        extra = self._halt()
        readings, errors, named = self._collected.snapshot()
        gpus = self._gpus if self._gpus is not None else named
        if gpus is None:
            gpus = integrate.gpus_seen(readings)
        return readings, errors + extra, gpus

    def stop(self, windows: Sequence[Window]) -> EnergyReading:
        """End the sampling and integrate each window. Never raises."""
        try:
            readings, errors, gpus = self.readings()
            return integrate.read_windows(
                readings,
                windows,
                gpus=gpus,
                min_samples=self._settings.min_samples,
                source=self._source.name,
                query_errors=errors,
                idle_power_w=self._idle_power_w,
            )
        except Exception:
            return self._failed(windows)

    def _failed(self, windows: Sequence[Window]) -> EnergyReading:
        _readings, errors, _gpus = self._collected.snapshot()
        return EnergyReading(
            source=self._source.name,
            sampler_ok=False,
            query_errors=errors + 1,
            windows=tuple(
                EnergyWindow(
                    label=w.label,
                    start_s=w.start_s,
                    end_s=w.end_s,
                    energy_j=None,
                    mean_power_w=None,
                    n_samples=0,
                    reason=integrate.REASON_SAMPLER_NOT_OK,
                )
                for w in windows
            ),
            idle_power_w=self._idle_power_w,
        )


class Meter:
    """The energy meter of one run (``api.EnergyMeter``).

    ``make_source`` builds the source for a GPU selection; the default picks
    the GPU management library or the query process when sampling starts.
    ``pause`` waits out the idle stretch.
    """

    def __init__(
        self,
        *,
        make_source: MakeSource | None = None,
        pause: Callable[[float], None] = time.sleep,
        start_wait_s: float = START_WAIT_S,
        stop_wait_s: float = STOP_WAIT_S,
    ) -> None:
        self._make_source = make_source or self._default_source
        self._pause = pause
        self._start_wait_s = start_wait_s
        self._stop_wait_s = stop_wait_s
        self._idle: dict[tuple[int, ...] | None, float | None] = {}
        self._smi_fields = smi.FieldCache()

    def _default_source(self, gpus: tuple[int, ...] | None, settings: EnergySettings) -> Source:
        if nvml.available():
            return nvml.NvmlSource(gpus, settings.interval_s)
        return smi.SmiSource(gpus, settings.interval_s, fields=self._smi_fields)

    def _sampler(self, gpus: tuple[int, ...] | None, settings: EnergySettings) -> Sampler:
        sampler = Sampler(
            self._make_source(gpus, settings),
            gpus,
            settings,
            idle_power_w=self._idle.get(gpus),
            stop_wait_s=self._stop_wait_s,
        )
        sampler.begin(self._start_wait_s)
        return sampler

    def idle_power_w(self, gpus: str, settings: EnergySettings) -> float | None:
        """Sample a short stretch with nothing launched and return its mean power."""
        selected = selection(gpus)
        sampler = self._sampler(selected, settings)
        try:
            self._pause(idle_seconds(settings))
        except BaseException:
            sampler.cancel()
            raise
        try:
            readings, errors, covered = sampler.readings()
            value = (
                None if errors else integrate.mean_power_w(readings, covered, settings.min_samples)
            )
        except Exception:
            value = None
        self._idle[selected] = value
        return value

    def start(self, gpus: str, settings: EnergySettings) -> Sampler:
        """Begin sampling every ``settings.interval_s`` seconds."""
        return self._sampler(selection(gpus), settings)


def energy_meter() -> Meter:
    """Make the energy meter of a run (``pairbench.api.MakeEnergyMeter``)."""
    return Meter()
