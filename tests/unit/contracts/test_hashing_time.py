# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Reading a command for its hash takes time in proportion to its length.

The hash of a command, of a config and of the output of an ``identify`` command
is taken over the text with its secrets hidden. That text is made in one pass
over one unbroken argument, whatever it repeats: letters, the characters of a
scheme, a name joined by dashes or dots, an option of many words joined by
dashes, short options, quotes, hexadecimal, names between slashes or letters
next to an address. A config is read through ``config_inputs``, which reads
the commands of the config as ``_hashed_config`` does. Each reader is timed on
the CPU of a process of its own, the best of a few tries, so a busy machine
does not make it look slow; an argument eight times as long takes about eight
times as long, never the square of it. That process is stopped after
``TIME_LIMIT_S``, so a reader that takes the square of the time fails its test
within the limit instead of running for hours.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from pairbench import model

# The lengths timed: one unbroken argument of each shape, and one eight times as long.
SHORT = 16_000
LONG = 128_000
# The longest one reader may take on the long argument, in seconds of CPU.
LONG_LIMIT_S = 1.0
# How many times as long the long argument may take as the short one: eight times as long
# is in proportion, and sixty-four times would be the square.
RATIO_LIMIT = 24.0
# A time shorter than this is read as this long, so that the timer's grain makes no ratio.
TIMER_GRAIN_S = 0.002
# The best of this many tries is the time of a reader.
TRIES = 3
# The longest the process that runs the reading of one test may take, in seconds on the
# clock of the wall: a reader in proportion ends well within it, and one that takes the
# square of the time is stopped at it.
TIME_LIMIT_S = 60

ADDRESS = "http://localhost:8000/v1"
# Arguments of one piece repeated, as (what stands before, the piece, what stands after):
# each is kept as typed in the text a hash is taken over.
KEPT_SHAPES: dict[str, tuple[str, str, str]] = {
    "letters": ("", "x", ""),
    "letters and digits": ("", "u8jzPde0IgxLd6Gn", ""),
    "the characters of a scheme": ("", "a+b.c-", ""),
    "a name joined by dashes": ("", "a-", ""),
    "an option of many words joined by dashes": ("--", "word-", ""),
    "a name joined by dots": ("", "a.", ""),
    "short options": ("", "-p", ""),
    "letters in quotes": ("'", "x", "'"),
    "letters before an address": ("", "x", " " + ADDRESS),
    "an address before letters": (ADDRESS + " ", "x", ""),
    "letters glued to an address": ("", "x", ADDRESS),
    "a file address of letters": ("file://", "x", ""),
    "names between slashes": ("", "data/", ""),
    "names between a plus and a slash": ("", "x+/", ""),
}
# The letter ``a`` alone makes a hexadecimal value, hidden whole in a command and a config.
HEX_LETTER = "a"
# The readers that keep a hexadecimal value as typed: the output of an identify command keeps
# every value but a credential, and no rule of shape applies to it.
SHAPES_KEPT = frozenset({"hashed_output"})


def _repeated(piece: str, length: int) -> str:
    return (piece * (length // len(piece) + 1))[:length]


def _shaped(shape: str, length: int) -> str:
    before, piece, after = KEPT_SHAPES[shape]
    return before + _repeated(piece, length - len(before) - len(after)) + after


def _argv(arg: str) -> str:
    return json.dumps(model.hashed_argv(["tool", arg]))


def _config(arg: str) -> str:
    return json.dumps(model.config_inputs({"workload": {"driver": "wall", "argv": ["tool", arg]}}))


def _output(arg: str) -> str:
    return model.hashed_output(arg)


def _argv_read(arg: str) -> str:
    return json.dumps(["tool", arg])


def _config_read(arg: str) -> str:
    return json.dumps({"workload": {"driver": "wall", "argv": ["tool", arg]}})


def _output_read(arg: str) -> str:
    return arg


# Each reader, and the text it gives for an argument it reads as it is.
READERS: dict[str, tuple[Callable[[str], str], Callable[[str], str]]] = {
    "hashed_argv": (_argv, _argv_read),
    "config_inputs": (_config, _config_read),
    "hashed_output": (_output, _output_read),
}


# The readers a test times, by name, for the process that times them.
TIMED: dict[str, Callable[[str], str]] = {name: read for name, (read, _) in READERS.items()}


def _cpu_times(
    cpu_times: Callable[..., list[tuple[float, str]]], name: str, calls: list[tuple[str, str]]
) -> list[float]:
    """The best CPU time of a few tries of the reader ``name`` at each (argument, text).

    Every try gives the text expected. A try that takes several times ``LONG_LIMIT_S`` is the
    last: no other try comes near.
    """
    answers = cpu_times([(name, arg) for arg, _ in calls], TRIES, 4 * LONG_LIMIT_S, TIME_LIMIT_S)
    for (_, expected), (_, read_text) in zip(calls, answers, strict=True):
        assert read_text == expected
    return [best for best, _ in answers]


@pytest.mark.parametrize("name", list(READERS))
@pytest.mark.parametrize("shape", list(KEPT_SHAPES))
def test_a_long_argument_kept_as_typed_is_read_for_the_hash_in_proportion_to_its_length(
    name: str, shape: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    as_typed = READERS[name][1]
    short, long = _shaped(shape, SHORT), _shaped(shape, LONG)
    assert len(short) == SHORT
    assert len(long) == LONG
    short_s, long_s = _cpu_times(
        cpu_times, name, [(short, as_typed(short)), (long, as_typed(long))]
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT


@pytest.mark.parametrize("name", list(READERS))
def test_a_long_hexadecimal_argument_is_read_for_the_hash_in_proportion_to_its_length(
    name: str, cpu_times: Callable[..., list[tuple[float, str]]]
) -> None:
    as_typed = READERS[name][1]
    short, long = _repeated(HEX_LETTER, SHORT), _repeated(HEX_LETTER, LONG)
    kept = name in SHAPES_KEPT
    short_s, long_s = _cpu_times(
        cpu_times,
        name,
        [
            (short, as_typed(short if kept else model.HIDDEN)),
            (long, as_typed(long if kept else model.HIDDEN)),
        ],
    )
    assert long_s < LONG_LIMIT_S
    assert long_s / max(short_s, TIMER_GRAIN_S) < RATIO_LIMIT
