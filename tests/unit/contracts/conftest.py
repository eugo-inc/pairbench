# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the contract tests share.

* ``cpu_times`` times the cleaners of the calling test module in a process of
  its own, which is stopped after a time limit. A cleaner whose time grows as
  the square of the length of its argument runs for hours on a long one; with
  the limit, its test fails within the limit instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from pairbench import model

# The folder the package under test is imported from, for a process of its own.
SRC = Path(model.__file__).resolve().parents[1]

# The timing process. It loads the test module from its file and reads, on its standard
# input, the calls to time: each as (the name of a cleaner in the module's ``TIMED`` table,
# the argument). Each call is timed on the CPU of that process, the best of ``tries``; a try
# that takes longer than ``last_s`` is the last. It writes (the best time, the text the
# cleaner gave) for each call, or ends with an error when two tries give two texts.
_TIMER = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("timed_module", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
request = json.load(sys.stdin)
answers = []
for name, arg in request["calls"]:
    clean = module.TIMED[name]
    best, shown = float("inf"), None
    for _ in range(request["tries"]):
        start = time.process_time()
        text = clean(arg)
        took = time.process_time() - start
        best = min(best, took)
        if shown is not None and text != shown:
            sys.exit(f"two tries of {name} gave two texts")
        shown = text
        if took > request["last_s"]:
            break
    answers.append([best, shown])
json.dump(answers, sys.stdout)
"""

CpuTimes = Callable[[Sequence[tuple[str, str]], int, float, float], list[tuple[float, str]]]


@pytest.fixture
def cpu_times(request: pytest.FixtureRequest) -> CpuTimes:
    """Time named cleaners of the calling test module in a process stopped after a limit.

    The returned function takes the calls, as (the name of a cleaner in the module's
    ``TIMED`` table, the argument), the number of tries of each, the time of a try after
    which no other is made, and the limit in seconds on the clock of the wall for all of
    them. It gives (the best CPU time, the text the cleaner gave) for each call, and fails
    the test when the process does not end within the limit.
    """
    module = request.path

    def times(
        calls: Sequence[tuple[str, str]], tries: int, last_s: float, limit_s: float
    ) -> list[tuple[float, str]]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH_")}
        env["PYTHONPATH"] = str(SRC)
        asked = {"calls": [list(call) for call in calls], "tries": tries, "last_s": last_s}
        try:
            done = subprocess.run(
                [sys.executable, "-c", _TIMER, str(module)],
                input=json.dumps(asked),
                env=env,
                capture_output=True,
                text=True,
                timeout=limit_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            names = sorted({name for name, _ in calls})
            pytest.fail(f"timing {', '.join(names)} did not end in {limit_s} s")
        assert done.returncode == 0, done.stderr
        assert done.stderr == ""
        return [(float(best), str(shown)) for best, shown in json.loads(done.stdout)]

    return times
