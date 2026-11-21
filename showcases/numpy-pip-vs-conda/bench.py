# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Eight NumPy operations, each printed as one ``lines`` case.

Each case is the median of seven timed calls, after one untimed call. The
clock is read just before and just after the operation, so making the input
is outside the timing. With ``PAIRBENCH_WORK_FACTOR=N`` each timed call runs
the operation N times, so the value grows N-fold.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Callable

import numpy as np

CALLS = 7
FACTOR = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
ELEMENTWISE = 1 << 22
RNG = np.random.default_rng(12345)


def report(case: str, operation: Callable[[], object]) -> None:
    operation()
    times = []
    for _ in range(CALLS):
        start = time.perf_counter()
        for _ in range(FACTOR):
            operation()
        times.append(time.perf_counter() - start)
    line = {"case": case, "value": statistics.median(times), "unit": "s", "better": "lower"}
    print("::pairbench::", json.dumps(line), flush=True)


def main() -> None:
    signal = RNG.standard_normal(1 << 21)
    report("rfft_2m", lambda: np.fft.rfft(signal))

    a = RNG.standard_normal((1024, 1024))
    spd = a @ a.T + 1024 * np.eye(1024)
    report("cholesky_1024", lambda: np.linalg.cholesky(spd))

    x = RNG.standard_normal(ELEMENTWISE)
    y = RNG.standard_normal(ELEMENTWISE)
    report("arcsinh", lambda: np.arcsinh(x))
    report("axpy", lambda: 2.5 * x + y)

    image = RNG.standard_normal((1024, 1024))
    report("fft2_1024", lambda: np.fft.fft2(image))

    positive = np.abs(x)
    report("sqrt_mul_add", lambda: np.sqrt(positive) * y + x)
    report("exp", lambda: np.exp(x))

    m = RNG.standard_normal((512, 512))
    n = RNG.standard_normal((512, 512))
    report("matmul_512", lambda: m @ n)


if __name__ == "__main__":
    main()
