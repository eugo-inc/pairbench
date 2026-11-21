# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A fixed amount of pure-Python arithmetic, timed from outside by ``wall``.

With ``PAIRBENCH_WORK_FACTOR=N`` it does N times the work.
"""

from __future__ import annotations

import os

STEPS = 3_000_000
FACTOR = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))


def main() -> None:
    total = 0
    for i in range(STEPS * FACTOR):
        total = (total + i * i) % 1_000_003
    print(total)


if __name__ == "__main__":
    main()
