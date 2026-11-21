# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Pure-Python tasks, each printed as one ``lines`` case.

Only the standard library is used, so the same file runs on every Python
version. Each case is the median of seven timed calls, after one untimed
call. With ``PAIRBENCH_WORK_FACTOR=N`` each timed call runs the task N times.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from collections.abc import Callable

CALLS = 7
FACTOR = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))


def fib(n: int) -> int:
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def dict_build() -> None:
    table = {f"key{i}": i for i in range(200_000)}
    sum(table[f"key{i}"] for i in range(0, 200_000, 7))


def str_join() -> None:
    "-".join(str(i) for i in range(300_000)).split("-")


DOCUMENT = {"items": [{"id": i, "name": f"item{i}", "tags": ["a", "b"]} for i in range(20_000)]}


def json_round_trip() -> None:
    json.loads(json.dumps(DOCUMENT))


TEXT = " ".join(f"user{i}@example.org word{i}" for i in range(50_000))
EMAIL = re.compile(r"[a-z0-9]+@[a-z]+\.[a-z]+")


def regex_scan() -> None:
    EMAIL.findall(TEXT)


def sort_tuples() -> None:
    sorted(((i * 7919) % 100_003, str(i)) for i in range(200_000))


def float_loop() -> None:
    x, v = 0.0, 1.0
    for _ in range(500_000):
        v -= 0.001 * x
        x += 0.001 * v


class Point:
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def objects() -> None:
    points = [Point(i, -i) for i in range(200_000)]
    sum(p.x + p.y for p in points)


def report(case: str, task: Callable[[], object]) -> None:
    task()
    times = []
    for _ in range(CALLS):
        start = time.perf_counter()
        for _ in range(FACTOR):
            task()
        times.append(time.perf_counter() - start)
    line = {"case": case, "value": statistics.median(times), "unit": "s", "better": "lower"}
    print("::pairbench::", json.dumps(line), flush=True)


def main() -> None:
    report("fib_recursive", lambda: fib(25))
    report("dict_build", dict_build)
    report("str_join_split", str_join)
    report("json_round_trip", json_round_trip)
    report("regex_scan", regex_scan)
    report("sort_tuples", sort_tuples)
    report("float_loop", float_loop)
    report("objects", objects)


if __name__ == "__main__":
    main()
