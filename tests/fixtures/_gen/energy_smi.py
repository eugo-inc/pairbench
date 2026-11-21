# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Generate the synthetic ``nvidia-smi`` query output of the energy tests.

No GPU tool is run. The lines follow the format the nvidia-smi documentation
describes for ``--query-gpu=... --format=csv,noheader,nounits`` in a ``-lms``
loop: one line per GPU per interval, the fields separated by a comma and a
space, ``N/A`` for data the GPU does not support, the time stamp as
``YYYY/MM/DD HH:MM:SS.msec`` and the reasons mask in hexadecimal.

Every value is made up: two GPUs, twelve intervals of 0.2 seconds from a
visibly made-up date, a steady 100 W on GPU 0 and 50 W on GPU 1, a
temperature GPU 1 does not report, and a power cap reason that GPU 1 shows on
three intervals in a row.

    python tests/fixtures/_gen/energy_smi.py

writes ``tests/fixtures/energy/nvidia-smi-query.csv`` and its
``*.provenance.json`` sidecar.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "energy"
NAME = "nvidia-smi-query.csv"
GENERATOR = "tests/fixtures/_gen/energy_smi.py"

QUERY = "timestamp,index,power.draw,temperature.gpu,clocks_throttle_reasons.active"
START = datetime(2001, 2, 3, 4, 5, 6)
STEP = timedelta(milliseconds=200)
INTERVALS = 12
POWER_CAP = 0x4


def lines() -> list[str]:
    """Return the lines of the fixture."""
    out: list[str] = []
    for i in range(INTERVALS):
        stamp = (START + i * STEP).strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]
        capped = POWER_CAP if 5 <= i <= 7 else 0
        out.append(f"{stamp}, 0, 100.00, 40, 0x{0:016x}")
        out.append(f"{stamp}, 1, 50.00, N/A, 0x{capped:016x}")
    return out


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / NAME).write_text("\n".join(lines()) + "\n", encoding="utf-8")
    sidecar = {
        "generator": GENERATOR,
        "seed": None,
        "tool": "nvidia-smi",
        "version": "query format of the nvidia-smi documentation, change log up to v620",
        "synthetic": True,
        "source": "https://docs.nvidia.com/deploy/nvidia-smi/index.html",
        "query": QUERY,
        "options": "--format=csv,noheader,nounits -lms 200",
    }
    (FIXTURES / f"{NAME}.provenance.json").write_text(
        json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
