#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A made-up benchmark for the README's recording: it prints made-up timings and times nothing.

Run as ``made_up_bench.py new`` or ``made_up_bench.py old``, it prints one ``::pairbench::``
line per case for the ``lines`` driver. Each value is a made-up mean for the side and the case,
times a small made-up spread drawn from a generator seeded by the side and by a count of the
launches so far, which it keeps in a file in the current folder (``.made-up-bench-count``). The
same launches in the same order print the same values.
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

SEED = "made-up"
COUNT_FILE = Path(".made-up-bench-count")
# Made-up mean timings in seconds: parse is quicker on new, encode the same, resize slower.
MEANS = {
    "new": {"parse": 0.310, "encode": 1.020, "resize": 0.588},
    "old": {"parse": 0.402, "encode": 1.020, "resize": 0.555},
}
# The made-up spread of one launch, as a fraction of the mean.
SPREAD = 0.006


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in MEANS:
        print(f"usage: made_up_bench.py {{{'|'.join(MEANS)}}}", file=sys.stderr)
        return 2
    side = argv[1]
    count = int(COUNT_FILE.read_text(encoding="utf-8")) if COUNT_FILE.is_file() else 0
    COUNT_FILE.write_text(str(count + 1), encoding="utf-8")
    generator = random.Random(f"{SEED}:{side}:{count}")
    factor = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
    for case, mean in MEANS[side].items():
        value = factor * mean * generator.gauss(1.0, SPREAD)
        print("::pairbench::", json.dumps({"case": case, "value": round(value, 6), "unit": "s"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
