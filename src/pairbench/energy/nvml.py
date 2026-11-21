# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Power readings from the GPU management library, through the ``gpu`` extra.

The ``gpu`` extra installs ``nvidia-ml-py``, whose module is ``pynvml``. The
module is imported only inside the function that loads it, so the package
imports without it.

What the module relies on:

* nvidia-ml-py 13.615.71 (https://pypi.org/project/nvidia-ml-py/): the
  module ``pynvml``, ``nvmlInit``, ``nvmlShutdown``, ``nvmlDeviceGetCount``,
  ``nvmlDeviceGetHandleByIndex``, and the exception ``NVMLError`` whose
  ``value`` is the library's return code;
* NVML API Reference Guide, version 620, pages "Device Queries" and
  "Device Enums" (https://docs.nvidia.com/deploy/nvml-api/):
  ``nvmlDeviceGetPowerUsage`` gives the power of the GPU and its associated
  circuitry, in milliwatts; ``nvmlDeviceGetTotalEnergyConsumption`` the
  energy used since the driver was last reloaded, in millijoules;
  ``nvmlDeviceGetTemperature`` with ``NVML_TEMPERATURE_GPU`` the
  temperature of the GPU die; ``nvmlDeviceGetCurrentClocksThrottleReasons``
  the bit mask of active clock reasons. A query the device does not
  support returns ``NVML_ERROR_NOT_SUPPORTED``, which is 3 in the module;
* the module of nvidia-ml-py 13.615.71 also has
  ``nvmlDeviceGetCurrentClocksEventReasons``, the newer name of the call
  that reads the mask, with the bits named ``nvmlClocksEventReason*``; the
  mask is read with that call where the module has it, and with the older
  name otherwise.

The source polls every selected GPU once per interval on the sampler's
thread. Each field is read on its own: a field the device does not support
is left out without an error, and any other failure, a value that is no
finite number, or a power or energy counter below zero, is a query error
that leaves the other fields of the reading in place. A library that cannot
be loaded or started, or a selected GPU that cannot be opened, counts as a
query error and gives no reading.
"""

from __future__ import annotations

import importlib.util
import math
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Final

from pairbench.energy.integrate import Collected, Reading

MODULE: Final = "pynvml"
SOURCE: Final = "nvml"

# The library's return code for a query the device does not support.
NOT_SUPPORTED: Final = 3
# The sensor of ``nvmlDeviceGetTemperature`` that reads the GPU core.
TEMPERATURE_GPU: Final = 0

# What a field read gives when the device does not report the field or the read failed.
ABSENT: Final = object()

REASONS_CALLS: Final[tuple[str, ...]] = (
    "nvmlDeviceGetCurrentClocksEventReasons",
    "nvmlDeviceGetCurrentClocksThrottleReasons",
)


def available() -> bool:
    """Say whether the module of the ``gpu`` extra can be imported, without importing it."""
    try:
        return importlib.util.find_spec(MODULE) is not None
    except (ImportError, ValueError):
        return False


def load() -> Any:
    """Import and return the module of the ``gpu`` extra."""
    import pynvml

    return pynvml


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _field(library: Any, call: Callable[[], object]) -> tuple[object, int]:
    """Read one field: the raw value, or ``ABSENT``, and the query errors it counts."""
    try:
        return call(), 0
    except Exception as exc:
        code = getattr(exc, "value", None)
        unsupported = getattr(library, "NVML_ERROR_NOT_SUPPORTED", NOT_SUPPORTED)
        return ABSENT, 0 if code == unsupported else 1


def _scaled(
    library: Any, call: Callable[[], object], scale: float, *, minimum: float | None = None
) -> tuple[float | None, int]:
    """Read one numeric field and scale it; a value below ``minimum`` is a query error."""
    raw, errors = _field(library, call)
    if raw is ABSENT:
        return None, errors
    number = _number(raw)
    if number is None or (minimum is not None and number < minimum):
        return None, errors + 1
    return number * scale, errors


def read_gpu(
    library: Any, gpu: int, handle: object, clock: Callable[[], float]
) -> tuple[Reading, int]:
    """Read every field of one GPU once: the reading and its query errors."""
    power, e_power = _scaled(
        library, lambda: library.nvmlDeviceGetPowerUsage(handle), 1e-3, minimum=0.0
    )
    t_s = clock()
    counter, e_counter = _scaled(
        library, lambda: library.nvmlDeviceGetTotalEnergyConsumption(handle), 1e-3, minimum=0.0
    )
    sensor = getattr(library, "NVML_TEMPERATURE_GPU", TEMPERATURE_GPU)
    temperature, e_temperature = _scaled(
        library, lambda: library.nvmlDeviceGetTemperature(handle, sensor), 1.0
    )
    reasons_call = next(
        (getattr(library, name) for name in REASONS_CALLS if hasattr(library, name)), None
    )
    throttle: int | None = None
    e_throttle = 0
    if reasons_call is not None:
        raw, e_throttle = _field(library, lambda: reasons_call(handle))
        if raw is not ABSENT:
            if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                throttle = raw
            else:
                e_throttle += 1
    reading = Reading(
        t_s=t_s,
        gpu=gpu,
        power_w=power,
        temperature_c=temperature,
        throttle=throttle,
        counter_j=counter,
    )
    return reading, e_power + e_counter + e_temperature + e_throttle


class NvmlSource:
    """A source that polls the GPU management library on the sampler's thread.

    ``gpus`` of ``None`` reads every GPU the library counts.
    """

    name: Final = SOURCE

    def __init__(
        self,
        gpus: Sequence[int] | None,
        interval_s: float,
        *,
        loader: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gpus = None if gpus is None else tuple(gpus)
        self._interval_s = interval_s
        self._loader = loader or load
        self._clock = clock
        self._halt = threading.Event()

    def run(self, sink: Collected) -> None:
        """Read every selected GPU once per interval until ``halt``."""
        try:
            library = self._loader()
            library.nvmlInit()
        except Exception:
            sink.error()
            return
        try:
            self._poll(library, sink)
        finally:
            try:
                library.nvmlShutdown()
            except Exception:
                sink.error()

    def _poll(self, library: Any, sink: Collected) -> None:
        try:
            indices = self._gpus
            if indices is None:
                indices = tuple(range(int(library.nvmlDeviceGetCount())))
            handles = [(gpu, library.nvmlDeviceGetHandleByIndex(gpu)) for gpu in indices]
        except Exception:
            sink.error()
            return
        sink.select(indices)
        if not handles:
            return
        due = self._clock()
        while not self._halt.is_set():
            for gpu, handle in handles:
                reading, errors = read_gpu(library, gpu, handle, self._clock)
                if errors:
                    sink.error(errors)
                sink.add(reading)
            due += self._interval_s
            now = self._clock()
            if due < now:
                due = now
            self._halt.wait(due - now)

    def halt(self) -> None:
        """Stop polling; ``run`` returns after the reading under way."""
        self._halt.set()
