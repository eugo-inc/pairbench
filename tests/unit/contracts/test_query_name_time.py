# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The name before an ``=`` is found in one pass, however long a run of name letters it holds.

A query parameter's name and the text before an ``=`` are read for a name
that looks like a credential from their end, so a long run of letters that
ends in another character (``!``) gives the empty name at once. Each form is
cleaned for the shown command and read for the hash in a process of its own,
which is stopped after ``PROCESS_LIMIT_S``: a time that grows as the square of
the length runs far past that on the long argument. In that process each
cleaner is timed on its CPU, the best of a few tries, and an argument eight
times as long takes about eight times as long.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pairbench import model

# The folder the package under test is imported from, for a process of its own.
SRC = Path(model.__file__).resolve().parents[1]

# The lengths of the run of letters: one, and one eight times as long.
SHORT = 16_000
LONG = 128_000
# The longest one cleaner may take on the long argument, in seconds of CPU.
LONG_LIMIT_S = 1.0
# How many times as long the long argument may take as the short one: eight times as long
# is in proportion, and sixty-four times would be the square.
RATIO_LIMIT = 24.0
# A time shorter than this is read as this long, so that the timer's grain makes no ratio.
TIMER_GRAIN_S = 0.002
# The longest the process that times one form may run, in seconds on the clock.
PROCESS_LIMIT_S = 60
TRIES = 3

# Each form: the arguments after ``pairbench run --``, with ``{run}`` for the run of letters.
FORMS: dict[str, tuple[str, ...]] = {
    "a query name that ends in another character": (
        "curl",
        "http://localhost:8000/v1?token=zqm-made-up&{run}!=1",
    ),
    "a query name after a credential's value": (
        "curl",
        "http://localhost:8000/v1?{run}!=1&token=zqm-made-up",
    ),
    "a name before = that ends in another character": ("mytool", "{run}!=1"),
    "a name glued to an option": ("mytool", "--opt={run}!=1"),
    "a name in a shell text": ("sh", "-c", "mytool {run}!=1 && ./bench-old"),
}
# A run of name letters short enough to read, and what each form shows with it.
READABLE = 40
SHOWN: dict[str, str] = {
    "a query name that ends in another character": (
        f"curl 'http://localhost:8000/v1?token=<hidden>&{'a' * READABLE}!=1'"
    ),
    "a query name after a credential's value": (
        f"curl 'http://localhost:8000/v1?{'a' * READABLE}!=1&token=<hidden>'"
    ),
    "a name before = that ends in another character": f"mytool '{'a' * READABLE}!=1'",
    "a name glued to an option": f"mytool '--opt={'a' * READABLE}!=1'",
    "a name in a shell text": f"sh -c 'mytool {'a' * READABLE}!=1 && ./bench-old'",
}

# The program that times one form: it reads the arguments as JSON from its input and writes
# the best CPU time of the shown command and of the hash, and what the shown command holds.
TIMER = """
import json, sys, time
from pairbench import model

argv = json.loads(sys.stdin.read())
tries = int(sys.argv[1])
times = {}
for name, clean in (
    ("shown", lambda: model.public_command(("pairbench", "run", "--", *argv))),
    ("hashed", lambda: model.hashed_argv(argv)),
):
    best = None
    for _ in range(tries):
        start = time.process_time()
        out = clean()
        took = time.process_time() - start
        best = took if best is None else min(best, took)
    times[name] = best
shown = model.public_command(("pairbench", "run", "--", *argv))
print(json.dumps({"times": times, "shown": shown}))
"""


def filled(form: str, length: int) -> list[str]:
    return [word.replace("{run}", "a" * length) for word in FORMS[form]]


def timed(form: str, length: int) -> dict[str, object]:
    """Time the form in a process of its own; fail the test if it runs past the limit."""
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    try:
        done = subprocess.run(
            [sys.executable, "-c", TIMER, str(TRIES)],
            input=json.dumps(filled(form, length)),
            capture_output=True,
            text=True,
            env=env,
            timeout=PROCESS_LIMIT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"cleaning {form} of {length} letters did not end in {PROCESS_LIMIT_S} s")
    assert done.returncode == 0, done.stderr
    result: dict[str, object] = json.loads(done.stdout)
    return result


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_long_run_of_name_letters_is_read_in_proportion_to_its_length(form: str) -> None:
    short = timed(form, SHORT)
    long = timed(form, LONG)
    short_times = short["times"]
    long_times = long["times"]
    assert isinstance(short_times, dict) and isinstance(long_times, dict)

    for cleaner in ("shown", "hashed"):
        assert long_times[cleaner] < LONG_LIMIT_S
        assert long_times[cleaner] / max(short_times[cleaner], TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_run_of_name_letters_that_ends_in_another_character_is_shown(form: str) -> None:
    shown = model.public_command(("pairbench", "run", "--", *filled(form, READABLE)))

    assert shown == f"pairbench run -- {SHOWN[form]}"
