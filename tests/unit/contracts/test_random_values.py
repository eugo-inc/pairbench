# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Long random-looking values, as the shown command hides them wherever they stand.

A value is hidden by its shape alone when it is long and its kinds of
character (capital, small letter, digit) change often, or when it is long
hexadecimal that has none of the shapes of an id. Every value here is made
up: the random-looking ones repeat a short pattern, which the rule reads as
it reads a real token. Each threshold is tested just inside and just outside.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "

# ---------------------------------------------------------------------------
# The rule's constants
# ---------------------------------------------------------------------------


def test_the_rule_constants() -> None:
    assert model.RANDOM_MIN_LENGTH == 32
    assert model.RANDOM_CHANGE_EVERY == 3
    assert model.RANDOM_MIN_CAPITAL_PAIRS == 1
    assert model.RANDOM_WORD_SMALL_LETTERS == 3
    assert model.RANDOM_WORD_VOWELS == "aeiouy"
    assert model.RANDOM_WORDS_SHOWN_PERCENT == 60
    assert model.COMMIT_ID_LENGTH == 40
    assert model.DIGEST_NAMES == (
        "md5",
        "sha1",
        "sha224",
        "sha256",
        "sha384",
        "sha512",
        "blake2b",
        "blake2s",
        "blake3",
    )


# ---------------------------------------------------------------------------
# The random-looking rule, both sides of each test
# ---------------------------------------------------------------------------

# 32 characters, 11 changes of kind (32 / 3 rounded up), capitals followed by a capital.
AT_EVERY_THRESHOLD = "QRSt1u2v3w4x5yzabcdefghijklmnopq"
# The same, one character short.
TOO_SHORT = "QRSt1u2v3w4x5yzabcdefghijklmnop"
# 32 characters with 10 changes of kind, one too few.
TOO_FEW_CHANGES = "QRSt1u2v3w4xyzabcdefghijklmnopqR"
# 32 characters with 13 changes and one capital followed by a capital or a digit: enough.
ONE_PAIR = "QRst1u2v3w4x5y6zabcdefghijklmnop"
# The same with no capital followed by a capital or a digit.
NO_PAIR = "Qrst1u2v3w4x5y6zabcdefghijklmnop"
# Many changes, and no capital or no small letter.
NO_UPPER_CASE = "z9" * 16
NO_LOWER_CASE = "XY99" * 8
# Mixed-case letters with no digit, as some tokens are written.
LETTERS_ONLY = "XYzw" * 8
# 40 characters, 24 of them in words of a capital and three small letters: 60 percent.
WORDS_AT_THE_SHARE = "Abcd" * 6 + "XY9z" * 4
# The same words in 41 characters: under 60 percent.
WORDS_UNDER_THE_SHARE = WORDS_AT_THE_SHARE + "9"
# A capital and two small letters without a vowel is no word.
WORDS_TOO_SHORT = "Abc9" * 6 + "XY9z" * 4
# A capital and two small letters with a vowel is a word: 24 of 40 characters.
SHORT_WORDS_WITH_A_VOWEL = "Abe" * 8 + "XY9z" * 4
# The same without a vowel.
SHORT_WORDS_WITHOUT_A_VOWEL = "Abc" * 8 + "XY9z" * 4


@pytest.mark.parametrize(
    ("value", "hidden"),
    [
        (AT_EVERY_THRESHOLD, True),
        (TOO_SHORT, False),
        (TOO_FEW_CHANGES, False),
        (ONE_PAIR, True),
        (NO_PAIR, False),
        (NO_UPPER_CASE, False),
        (NO_LOWER_CASE, False),
        (LETTERS_ONLY, True),
        ("XYz9" * 8, True),
        ("XYz9" * 8 + "==", True),
        (WORDS_AT_THE_SHARE, False),
        (WORDS_UNDER_THE_SHARE, True),
        (WORDS_TOO_SHORT, True),
        (SHORT_WORDS_WITH_A_VOWEL, False),
        (SHORT_WORDS_WITHOUT_A_VOWEL, True),
    ],
)
def test_the_random_looking_rule(value: str, hidden: bool) -> None:
    assert model.looks_random(value) is hidden


# ---------------------------------------------------------------------------
# The hexadecimal rule
# ---------------------------------------------------------------------------

HEX_32 = "deadbeef" * 4
HEX_40 = "deadbeef" * 5
HEX_64 = "deadbeef" * 8


@pytest.mark.parametrize(
    ("value", "before", "hidden"),
    [
        ("deadbee", "", False),  # 7: a short commit or image id
        ("deadbeefcafe", "", False),  # 12: a short image id
        (HEX_32[:31], "", False),  # under the rule's length
        (HEX_32, "", True),  # 32: as `openssl rand -hex 16` prints
        (HEX_40[:39], "", True),
        (HEX_40, "", False),  # 40: a commit id
        (HEX_40 + "d", "", True),
        (HEX_64, "", True),  # 64 with no digest name before it
        (HEX_64 + "d", "", True),
        (HEX_32.upper(), "", True),
        (HEX_40.upper(), "", False),
        (HEX_64, "sha256:", False),
        (HEX_64, "image@sha256:", False),
        (HEX_64, "SHA256:", False),
        (HEX_64 * 2, "sha512:", False),
        (HEX_32, "md5:", False),
        (HEX_40, "sha1:", False),
        (HEX_64, "blobs/sha256/", False),
        (HEX_64, "--checksum=sha256=", False),
        (HEX_64, "notsha256:", True),
        (HEX_64, "sha256:x", True),
        ("1234567890" * 4, "", False),  # digits only: a number
    ],
)
def test_the_hexadecimal_rule(value: str, before: str, hidden: bool) -> None:
    assert model.looks_random(value, before) is hidden


# ---------------------------------------------------------------------------
# Where the rule hides a value in a command
# ---------------------------------------------------------------------------

TOKEN = "XYz9" * 10  # 40 characters, token-shaped
BASE64 = "XYz9+XYz9/XYz9+XYz9/XYz9+XYz9/XYz9+XY=="  # 40 characters with / and +
SLASH_FIRST = "/XYz9+XYz9/XYz9+XYz9/XYz9+XYz9/XYz9+XY=="
# 40 characters whose `+/` and next `/` would cut out the middle as a path.
PLUS_SLASH = "XYz9XYz9XYz9XYz9XYz9+/XYz9XYz9/XYz9XY=="
# BASE64 as a query value of an address writes it: `+`, `/` and `=` as escapes.
PERCENT_BASE64 = BASE64.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")


@pytest.mark.parametrize(
    ("args", "shown"),
    [
        # A plain positional argument, a value after = and a value glued to its option.
        (("tool", TOKEN), ("tool", "<hidden>")),
        (("tool", "--opt=" + TOKEN), ("tool", "--opt=<hidden>")),
        (("tool", "--opt", TOKEN), ("tool", "--opt", "<hidden>")),
        (("tool", BASE64), ("tool", "<hidden>")),
        (("tool", "tok_" + TOKEN), ("tool", "<hidden>")),
        # A value that starts with / is hidden whole, so no part of it is shown as a path.
        (("tool", SLASH_FIRST), ("tool", "<hidden>")),
        (("tool", "--key=" + SLASH_FIRST), ("tool", "--key=<hidden>")),
        # So is the path of an address whose host is empty, and the host and path of a file
        # address, which are cut as a path is.
        (("tool", "sqlite://" + SLASH_FIRST), ("tool", "sqlite:<hidden>")),
        (("tool", "--db=sqlite:///" + SLASH_FIRST), ("tool", "--db=sqlite:<hidden>")),
        (("tool", "DATABASE_URL=unix://" + SLASH_FIRST), ("tool", "DATABASE_URL=unix:<hidden>")),
        (("tool", "file://" + SLASH_FIRST), ("tool", "file:<hidden>")),
        (("tool", "file://localhost" + SLASH_FIRST), ("tool", "file:<hidden>")),
        (("tool", "file://made-up.example" + SLASH_FIRST), ("tool", "file:<hidden>")),
        (("tool", "file://bench:x@made-up.example" + SLASH_FIRST), ("tool", "file:<hidden>")),
        # A path segment and a query value of an address.
        (
            ("curl", f"http://localhost:8000/v1/files/{TOKEN}/raw?part={TOKEN}&n=3"),
            ("curl", "http://localhost:8000/v1/files/<hidden>/raw?part=<hidden>&n=3"),
        ),
        (
            ("curl", f"https://made-up.example/blob/{HEX_64}"),
            ("curl", "https://<hidden>/blob/<hidden>"),
        ),
        # A segment of a relative path.
        (("tool", f"data/{TOKEN}/out.json"), ("tool", "data/<hidden>/out.json")),
        # The parts of a token joined by dots, as a web token is written.
        (("tool", f"{TOKEN}.{TOKEN}"), ("tool", "<hidden>.<hidden>")),
        # Hexadecimal joined to a word.
        (("tool", f"run-{HEX_32}"), ("tool", "run-<hidden>")),
        # A user name stays, its password goes.
        (("tool", f"bench:{TOKEN}"), ("tool", "bench:<hidden>")),
        # A value glued to an option of one letter: the letter stays, hexadecimal too.
        (("tool", "-k" + TOKEN), ("tool", "-k<hidden>")),
        (("tool", "-k" + HEX_32), ("tool", "-k<hidden>")),
        (("tool", "-k" + HEX_64), ("tool", "-k<hidden>")),
        # A value with a `/` after a `+`, which a path would start at, is hidden whole.
        (("tool", PLUS_SLASH), ("tool", "<hidden>")),
        (("tool", "--opt=" + PLUS_SLASH), ("tool", "--opt=<hidden>")),
        (("tool", "-k" + PLUS_SLASH), ("tool", "-k<hidden>")),
        (("cc", f"-I/srv/{TOKEN}/include"), ("cc", "-I<hidden>")),
        # A query value written with percent escapes is read as it is meant.
        (
            ("curl", f"http://localhost:8000/v1/x?part={PERCENT_BASE64}&n=3"),
            ("curl", "http://localhost:8000/v1/x?part=<hidden>&n=3"),
        ),
        (("tool", PERCENT_BASE64), ("tool", "<hidden>")),
        (("tool", "-k" + PERCENT_BASE64), ("tool", "-k<hidden>")),
        (("tool", "--opt=" + PERCENT_BASE64), ("tool", "--opt=<hidden>")),
    ],
)
def test_a_random_looking_value_is_hidden_where_it_stands(
    args: tuple[str, ...], shown: tuple[str, ...]
) -> None:
    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(shown)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"tool {TOKEN}", "tool <hidden>"),
        (f"tool '{TOKEN}' -n 3", "tool '<hidden>' -n 3"),
        (f"tool --opt={BASE64}", "tool --opt=<hidden>"),
        (f"curl http://localhost/v1?key={HEX_64}", "curl http://localhost/v1?key=<hidden>"),
    ],
)
def test_a_random_looking_value_is_hidden_inside_sh_c(text: str, shown: str) -> None:
    assert model.public_command((*LEAD, "sh", "-c", text)) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", shown]
    )
    assert model.public_words(text) == " ".join(shlex.split(shown))


# Values that stay shown: paths of words, numbers, flags, versions, ids and digests.
ORDINARY: tuple[str, ...] = (
    "models/llama-3-8b-instruct/config.json",
    "data/run2/Model3B/Q4/Layer12/out3",
    "1234567890123456789012345678901234567890",
    "--max-num-batched-tokens=8192",
    "--benchmark_filter=BM_MatrixMultiplyLargeFloat32Contiguous",
    "2.5.1+cu124",
    "v0.6.3.post1",
    "deadbeefcafe",
    HEX_40,
    "sha256:" + HEX_64,
    "made-up/image@sha256:" + HEX_64,
    "12345678-dead-beef-cafe-1234567890ab",
    "12345678-DEAD-BEEF-CAFE-1234567890AB",
    "made-up-org/MadeUp-Small-24B-Instruct-2501",
    "unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF",
    "nvidia/Llama-3_3-Nemotron-Super-49B-v1",
    "RedHatAI/Llama-4-Scout-17B-16E-Instruct-FP8-dynamic",
    "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
    "MyLongClassName2WithManyWordsInIt3",
    "BM_Conv2D_NCHW_Float16_Batch64_Channels256",
    "test_ReadWriteLockUnderContention_8Threads_4KBlocks",
    # Names in CamelCase with capitals or digits run together, as benchmark and class names are.
    "--benchmark_filter=BM_ConvolutionNHWC3x3Stride2FP16TensorCore",
    "FlashAttentionV2ForwardFP16CausalHeadDim128",
    "MadeUpModelForCausalLMWithValueHead",
    "MadeUpServerHTTP2PushPromiseWithTrailersAndGzip",
    # A benchmark name of short words, each a capital and two small letters with a vowel.
    "--benchmark_filter=BM_LruCacheGetPutMixedKeyLen16ValLen64",
    # A UUID after a word, as a device id is written.
    "DEV-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
    "SLICE-DEV-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d/1/0",
    # A commit id glued to an option of one letter, and percent escapes of words and a digest.
    "-c" + HEX_40,
    "http://localhost:8000/v1/x?q=Made%20up%20words%20in%20a%20long%20query%20text",
    "http://localhost:8000/v1/x?digest=sha256%3A" + HEX_64,
    "Q4_K_M",
    NO_UPPER_CASE,
    TOO_SHORT,
)


@pytest.mark.parametrize("value", ORDINARY)
def test_an_ordinary_value_stays_shown(value: str) -> None:
    assert model.public_command((*LEAD, "tool", value)) == SHOWN_LEAD + shlex.join(["tool", value])
    assert model.public_words(f"tool {value}") == f"tool {value}"


def test_the_capture_keeps_a_random_looking_value_as_typed() -> None:
    argv = (*LEAD, "tool", TOKEN, HEX_64)

    assert model.redact_argv(argv) == argv
