# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Runs that hold ``/``, as the shown command judges them: base64, ``0x`` hexadecimal, names.

A run of token characters that holds ``/`` and a ``+`` or ``=`` padding is
written as base64 is, and is judged whole: when it looks random, no part of it
between two ``/`` shows, and when any part of it is hidden, all of it is. A run
with ``/`` and neither is judged whole between the words of a path at its ends,
so it is hidden whole when it is random as a whole, while a model name, a path
and an address keep their words. Hexadecimal written after ``0x`` follows the
hexadecimal rule. The parts of a benchmark name that hold no capital, such as
its number arguments, do not make it look random. Every value here is made up.
"""

from __future__ import annotations

import base64
import random
import shlex
import time

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "

# A made-up base64 value with `/` near its start and `+` and padding near its end.
SLASH_NEAR_START = "EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kE+Aw=="
FIRST_PIECE = "EXAMPLE7q"
# A made-up base64 value with `+` in its first part and `/` near its end.
SLASH_NEAR_END = "QX7kP2mV9nL4rT8wY3zB6cD1fG5hJ0sK2eAx+EXAMPLE5aB/n3Mq8Rt4Wv7Yz1Cd=="
LAST_PIECE = "n3Mq8Rt4Wv7Yz1Cd"
# A made-up token that looks random, as a segment of an address path holds one.
TOKEN = "XYz9" * 10


def shown(*args: str) -> str | None:
    return model.public_command((*LEAD, *args))


# ---------------------------------------------------------------------------
# A base64 value is hidden whole wherever it stands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("client", SLASH_NEAR_START), ("client", "<hidden>")),
        (("client", "--hmac", SLASH_NEAR_START), ("client", "--hmac", "<hidden>")),
        (("client", "--hmac=" + SLASH_NEAR_START), ("client", "--hmac=<hidden>")),
        (("BLOB=" + SLASH_NEAR_START,), ("BLOB=<hidden>",)),
        (
            ("sh", "-c", f"client {SLASH_NEAR_START} && echo ok"),
            ("sh", "-c", "client <hidden> && echo ok"),
        ),
        (("client", "-k" + SLASH_NEAR_START), ("client", "-k<hidden>")),
        (("client", SLASH_NEAR_END), ("client", "<hidden>")),
        (("client", "--hmac=" + SLASH_NEAR_END), ("client", "--hmac=<hidden>")),
    ],
)
def test_a_base64_value_with_a_slash_is_hidden_whole(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    text = shown(*args)

    assert text == SHOWN_LEAD + shlex.join(expected)
    assert FIRST_PIECE not in text
    assert LAST_PIECE not in text


def test_a_base64_value_inside_sh_c_keeps_the_command_after_it() -> None:
    text = shown("sh", "-c", f"client {SLASH_NEAR_START} && echo ok")

    assert text is not None
    assert text.endswith("&& echo ok'")
    assert model.public_words(f"client {SLASH_NEAR_START} && echo ok") == (
        "client <hidden> && echo ok"
    )


def b64_values(seed: int, count: int) -> list[str]:
    """Base64 of random bytes, 24 to 60 bytes long, that holds both ``+`` and ``/``."""
    rng = random.Random(seed)
    values: list[str] = []
    while len(values) < count:
        value = base64.b64encode(rng.randbytes(rng.randint(24, 60))).decode("ascii")
        if "+" in value and "/" in value:
            values.append(value)
    return values


def pieces(value: str, size: int = 6) -> set[str]:
    return {value[at : at + size] for at in range(len(value) - size + 1)}


def pieces_shown(values: list[str]) -> list[tuple[str, str]]:
    """Each value passed as a plain argument with each 6-character piece of it that shows."""
    found: list[tuple[str, str]] = []
    for value in values:
        text = shown("client", value)
        assert text is not None
        found += [(value, piece) for piece in sorted(pieces(value)) if piece in text]
    return found


def test_no_piece_of_a_random_base64_value_shows() -> None:
    # Every value of this seed looks random as a whole, as nearly every random value does.
    assert pieces_shown(b64_values(3, 1000)) == []


def test_a_base64_value_shows_a_piece_only_when_it_does_not_look_random_whole() -> None:
    # Over other seeds a few values fail a test of the rule by chance and show, as the
    # reference page says; every value the rule finds random as a whole is hidden whole.
    values = [value for seed in (1, 2, 4, 5) for value in b64_values(seed, 1000)]
    showing = {value for value, _ in pieces_shown(values)}

    assert [value for value in showing if model.looks_random(value)] == []


# A made-up base64 value whose first part looks random on its own while the whole value,
# its other parts made of words, does not: the hidden part takes the others with it.
RANDOM_PART = "Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEx"
WORD_PART = "MadeUpExampleTensorBatchNormLayer"
WORD_TAIL = "MadeUpExampleKernelQueueVectorTable"
WORD_TAILED = f"{RANDOM_PART}/{WORD_PART}+{WORD_TAIL}="


@pytest.mark.parametrize(
    "value",
    [
        WORD_TAILED,
        f"{RANDOM_PART}/{WORD_PART}+{WORD_TAIL}",
        f"{RANDOM_PART}/{WORD_PART}{WORD_TAIL}==",
        f"{RANDOM_PART}+{WORD_PART}{WORD_TAIL}",
        f"{WORD_PART}+{RANDOM_PART}/{WORD_TAIL}",
        f"{WORD_PART}/{WORD_TAIL}+{RANDOM_PART}",
        f"{RANDOM_PART}_{WORD_PART}-{WORD_TAIL}=",
    ],
    ids=["slash-plus-pad", "slash-plus", "slash-pad", "plus", "word-first", "random-last", "url"],
)
def test_no_part_of_a_base64_value_shows_beside_a_hidden_part(value: str) -> None:
    assert shown("client", value) == SHOWN_LEAD + "client '<hidden>'"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("client", "--hmac", WORD_TAILED), ("client", "--hmac", "<hidden>")),
        (("client", "--hmac=" + WORD_TAILED), ("client", "--hmac=<hidden>")),
        (("BLOB=" + WORD_TAILED,), ("BLOB=<hidden>",)),
        (
            ("sh", "-c", f"client {WORD_TAILED} && echo ok"),
            ("sh", "-c", "client <hidden> && echo ok"),
        ),
    ],
)
def test_a_base64_value_with_a_hidden_part_is_hidden_whole_where_it_stands(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert shown(*args) == SHOWN_LEAD + shlex.join(expected)


def test_padding_before_the_slash_of_an_address_path_marks_a_base64_value() -> None:
    # The padding stands after the run, before the `/` that goes on with the path; the
    # port and the words of the path stand in the run and go with the value.
    address = f"http://127.0.0.1:8080/v1/{RANDOM_PART}/{WORD_PART}==/raw"
    text = shown("curl", address)

    assert text is not None
    assert WORD_PART not in text
    assert model.hashed_argv(["curl", address]) == ["curl", "http://127.0.0.1:<hidden>==/raw"]


def word_tailed_values(seed: int, count: int) -> list[str]:
    """Base64 runs of a random part of 32 to 40 characters and made-up words, with a `+`."""
    rng = random.Random(seed)
    values: list[str] = []
    for _ in range(count):
        first = base64.b64encode(rng.randbytes(30)).decode("ascii")[: rng.randint(32, 40)]
        parts = [first, camel(rng, 3, 6), camel(rng, 3, 6)]
        rng.shuffle(parts)
        padding = rng.choice(("", "=", "=="))
        values.append(f"{parts[0]}{rng.choice('/+')}{parts[1]}+{parts[2]}{padding}")
    return values


def test_a_base64_value_shows_whole_or_not_at_all() -> None:
    # A value whose whole fails the rule shows whole; its padding after a credential word,
    # such as `Key`, is read as the empty value of a name and hidden.
    beside = []
    for value in word_tailed_values(7, 300):
        text = shown("client", value)
        assert text is not None
        if value.rstrip("=") not in text:
            beside += [(value, piece) for piece in sorted(pieces(value)) if piece in text]

    assert beside == []


# ---------------------------------------------------------------------------
# A run with `/` and no `+` or padding is judged whole between the words of a path
# ---------------------------------------------------------------------------

# The value above without its `+` and its padding: its first part, under 32 characters, is no
# word of a path, so the run is judged whole and hidden whole.
SLASH_ONLY = "EXAMPLE7q/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0jS2kEAw"


def test_a_slash_run_without_plus_or_padding_is_hidden_whole() -> None:
    assert shown("client", SLASH_ONLY) == SHOWN_LEAD + "client '<hidden>'"


@pytest.mark.parametrize(
    "value",
    [
        "2.5.1+cu124",
        "made-up/Model-3B-Instruct-FP8",
        "org-name/Model-Name-8B-Instruct",
        "made-up-org/MadeUp-Small-24B-Instruct-2501",
        "models/llama-3-8b-instruct/config.json",
        "data/run2/Model3B/Q4/Layer12/out3",
        "torch==2.5.1+cu124",
    ],
)
def test_model_names_paths_and_versions_stay_shown(value: str) -> None:
    assert shown("client", value) == SHOWN_LEAD + shlex.join(["client", value])


def test_an_address_keeps_the_words_of_its_path_around_a_hidden_token() -> None:
    address = f"http://localhost:8000/v1/files/{TOKEN}/raw"

    assert shown("curl", address) == SHOWN_LEAD + shlex.join(
        ["curl", "http://localhost:8000/v1/files/<hidden>/raw"]
    )


# ---------------------------------------------------------------------------
# Hexadecimal after 0x follows the hexadecimal rule
# ---------------------------------------------------------------------------

HEX_DIGITS_32 = "3f9a" * 8


@pytest.mark.parametrize(
    ("value", "piece"),
    [
        ("0x" + HEX_DIGITS_32, "3f9a3f9a3f9a3f9a"),
        ("0X" + HEX_DIGITS_32, "3f9a3f9a3f9a3f9a"),
        ("0x" + HEX_DIGITS_32.upper(), "3F9A3F9A3F9A3F9A"),
        ("0X" + HEX_DIGITS_32.upper(), "3F9A3F9A3F9A3F9A"),
        ("0x" + "3f9a" * 16, "3f9a3f9a3f9a3f9a"),
    ],
)
def test_hexadecimal_after_0x_of_32_digits_or_more_is_hidden(value: str, piece: str) -> None:
    text = shown("client", value)

    assert text == SHOWN_LEAD + "client '<hidden>'"
    assert piece not in text


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("client", "--seed", "0x" + HEX_DIGITS_32), ("client", "--seed", "<hidden>")),
        (("client", "--seed=0x" + HEX_DIGITS_32), ("client", "--seed=<hidden>")),
        (("client", "-k0x" + HEX_DIGITS_32), ("client", "-k<hidden>")),
        (("SEED=0x" + HEX_DIGITS_32,), ("SEED=<hidden>",)),
        (("sh", "-c", f"client 0x{HEX_DIGITS_32} -n 3"), ("sh", "-c", "client <hidden> -n 3")),
    ],
)
def test_hexadecimal_after_0x_is_hidden_where_it_stands(
    args: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert shown(*args) == SHOWN_LEAD + shlex.join(expected)


@pytest.mark.parametrize(
    "value",
    [
        "0x" + HEX_DIGITS_32[:31],  # under 32 digits, as an address or a mask is written
        "0xdeadbeef",
        "0XFFFF0000",
        "0x" + "3f9a" * 10,  # 40 digits: the length of a commit id
        "0X" + ("3f9a" * 10).upper(),
        "0x" + "3F9a" * 10,
        "0x" + "1234" * 8,  # digits only: a number
    ],
)
def test_short_and_commit_length_hexadecimal_after_0x_stays_shown(value: str) -> None:
    assert shown("client", value) == SHOWN_LEAD + shlex.join(["client", value])


@pytest.mark.parametrize(
    ("value", "before", "hidden"),
    [
        ("0x" + HEX_DIGITS_32, "", True),
        ("0X" + HEX_DIGITS_32.upper(), "", True),
        ("0x" + HEX_DIGITS_32[:31], "", False),
        ("0x" + "3F9a" * 10, "", False),
        ("0x" + "3f9a" * 16, "sha256:", False),
        ("0x", "", False),
        # Before digits that are not hexadecimal, `0x` is part of the value: 32 characters.
        ("0x" + "Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH0j", "", True),
    ],
)
def test_the_hexadecimal_rule_reads_the_digits_after_0x(
    value: str, before: str, hidden: bool
) -> None:
    assert model.looks_random(value, before) is hidden


# ---------------------------------------------------------------------------
# Number arguments do not turn a benchmark name hidden
# ---------------------------------------------------------------------------

BENCHMARK = "--benchmark_filter=BM_Crc32BatchNormMapTensorPut"


@pytest.mark.parametrize(
    "arguments", ["", "/64", "/8/1", "/4096/4", "/4096/4/65536", "/1/real_time", "/4/32"]
)
def test_number_arguments_keep_a_benchmark_name_shown(arguments: str) -> None:
    value = BENCHMARK + arguments

    assert shown("client", value) == SHOWN_LEAD + shlex.join(["client", value])


@pytest.mark.parametrize(
    "value", ["tree_parse/MapMaxHTTP2PopCopyCopy/16/64", "dot_norm/SetAddPushRingU64TableKey/64/1"]
)
def test_a_group_name_in_small_letters_keeps_a_benchmark_name_shown(value: str) -> None:
    assert shown("client", value) == SHOWN_LEAD + shlex.join(["client", value])


def test_random_parts_between_slashes_are_still_hidden_together() -> None:
    # Each part is under 32 characters and the run has no `+` or padding: the run is
    # judged whole, its number argument left out of the share of words, and is hidden whole.
    value = "Q7xK2mP9vL4nR8tW/3yZ6bC1dF5gH0jS2kE/4096"

    assert shown("client", value) == SHOWN_LEAD + "client '<hidden>'"


@pytest.mark.parametrize(
    "value",
    [
        "ab3d9x/Q7xK2mP9vL4nR8tW3yZ6bC1dF5g",  # a short part with no capital
        "4096/Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH",  # a part made only of digits
    ],
)
def test_a_random_run_with_one_part_beside_a_plain_part_is_hidden_whole(value: str) -> None:
    # The run is judged whole on its full length; only the share of words leaves the
    # plain parts out.
    assert shown("client", value) == SHOWN_LEAD + "client '<hidden>'"


def slash_values(seed: int, count: int) -> list[str]:
    """Base64 of random bytes, 32 to 44 characters with no padding, that holds `/` and no `+`."""
    rng = random.Random(seed)
    values: list[str] = []
    while len(values) < count:
        value = base64.b64encode(rng.randbytes(3 * rng.randint(8, 11))).decode("ascii")
        if "/" in value and "+" not in value:
            values.append(value)
    return values


def test_a_slash_run_shows_whole_only_when_it_does_not_look_random_whole() -> None:
    values = [value for seed in (1, 2, 3) for value in slash_values(seed, 1000)]
    whole = [value for value in values if value in (shown("client", value) or "")]

    assert [value for value in whole if model.looks_random(value)] == []


# Words of made-up benchmark names: CamelCase words, and runs of capitals and digits.
WORDS = (
    "Batch",
    "Norm",
    "Map",
    "Tensor",
    "Put",
    "Get",
    "Set",
    "Cache",
    "Hash",
    "Table",
    "Insert",
    "Lookup",
    "Erase",
    "Sort",
    "Merge",
    "Copy",
    "Move",
    "Vector",
    "Queue",
    "Push",
    "Pop",
    "Read",
    "Write",
    "File",
    "Buffer",
    "Parse",
    "Encode",
    "Decode",
    "Matrix",
    "Reduce",
    "Scan",
    "Gather",
    "Layer",
    "Kernel",
    "Pool",
    "Alloc",
    "Lock",
    "Ring",
    "Tree",
    "Key",
    "Value",
    "Find",
    "Load",
    "Store",
    "Add",
    "Mul",
    "Dot",
    "Sum",
    "Max",
    "Min",
)
CAPITALS = ("Crc32", "Lru", "Gpu", "Cpu", "FP16", "BF16", "NCHW", "HTTP2", "SIMD", "Int8", "U64")
SNAKE = tuple(word.lower() for word in WORDS)
NUMBERS = ("1", "2", "4", "8", "16", "32", "64", "128", "256", "512", "1024", "4096", "65536")


def camel(rng: random.Random, low: int, high: int) -> str:
    """A name of ``low`` to ``high`` CamelCase words, maybe with one run of capitals."""
    words = [rng.choice(WORDS) for _ in range(rng.randint(low, high))]
    if rng.random() < 0.5:
        words.insert(rng.randrange(len(words) + 1), rng.choice(CAPITALS))
    return "".join(words)


def number_arguments(rng: random.Random, low: int, high: int) -> str:
    return "/".join(rng.choice(NUMBERS) for _ in range(rng.randint(low, high)))


def benchmark_name(rng: random.Random) -> str:
    """A made-up name: Google Benchmark, criterion, pytest or CamelCase."""
    shape = rng.randrange(4)
    if shape == 0:
        return f"--benchmark_filter=BM_{camel(rng, 3, 7)}/{number_arguments(rng, 1, 3)}"
    if shape == 1:
        group = "_".join(rng.choice(SNAKE) for _ in range(rng.randint(1, 3)))
        return f"{group}/{camel(rng, 3, 6)}/{number_arguments(rng, 1, 2)}"
    if shape == 2:
        words = "_".join(rng.choice(SNAKE) for _ in range(rng.randint(2, 6)))
        return f"test_{words}[{rng.choice(NUMBERS)}-{rng.choice(SNAKE)}]"
    return camel(rng, 5, 10)


def test_no_made_up_benchmark_name_is_hidden() -> None:
    rng = random.Random(3)
    names = [benchmark_name(rng) for _ in range(2000)]

    assert [name for name in names if model.HIDDEN in (shown("tool", name) or "")] == []


# ---------------------------------------------------------------------------
# A long argument of each shape is cleaned quickly
# ---------------------------------------------------------------------------

# A command line far longer than any typed one; each takes a small part of a second.
LONG = 128_000
QUICK_S = 2.0


def cleaning_time(args: tuple[str, ...]) -> float:
    """The shortest of three timings of cleaning a command, in seconds."""
    times = []
    for _ in range(3):
        start = time.perf_counter()
        model.public_command((*LEAD, *args))
        times.append(time.perf_counter() - start)
    return min(times)


@pytest.mark.parametrize(
    "args",
    [
        ("client", base64.b64encode(random.Random(5).randbytes(LONG * 3 // 4)).decode("ascii")),
        ("client", "--hmac=" + (SLASH_NEAR_START.rstrip("=") * (LONG // 47)) + "=="),
        ("client", BENCHMARK + "/4096/4" * (LONG // 7)),
        ("client", "Q7xK2mP9vL4nR8tW/" * (LONG // 17)),
        ("client", "--seed=0x" + "3f9a" * 4_000),
        ("client", f"{RANDOM_PART}/{WORD_PART}+" * (LONG // 70) + "="),
    ],
    ids=["base64", "base64 after an option", "number arguments", "slash parts", "0x", "word parts"],
)
def test_a_long_run_with_slashes_is_cleaned_quickly(args: tuple[str, ...]) -> None:
    assert cleaning_time(args) < QUICK_S


def test_a_long_hexadecimal_value_after_0x_is_judged_quickly() -> None:
    value = "0x" + "3f9a" * (LONG // 4)
    start = time.perf_counter()

    assert model.looks_random(value) is True
    assert time.perf_counter() - start < QUICK_S
