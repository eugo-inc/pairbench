# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The load generator: busy loops that never stop, one per process.

The count of processes is the first argument, 1 by default.
"""

from __future__ import annotations

import multiprocessing
import sys


def spin() -> None:
    while True:
        pass


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    workers = [multiprocessing.Process(target=spin) for _ in range(count - 1)]
    for worker in workers:
        worker.start()
    spin()


if __name__ == "__main__":
    main()
