# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A run with ``/`` and neither ``+`` nor padding is judged whole between the words of a path.

Base64 written with ``/`` and no ``+`` or ``=`` is hidden whole when it is
random as a whole, as a plain argument, an option value, the value of a name,
in a shell text, in the path of an address and in a relative path. The words
of a path or an address around it are kept (``data/<hidden>/out.json``,
``/v1/files/<hidden>/raw``). A path, a model id, an image reference, a path
pinned to a commit, a date and a version stay shown. What a key may still
show is a part at one of its ends that reads as a word of a path by chance,
and a key that fails one of the tests of ``looks_random`` as a whole shows
whole. Every value here is made up, by seeded generators.
"""

from __future__ import annotations

import base64
import random
import re
import shlex
from collections.abc import Callable

import pytest

from pairbench import model

# The length of a piece of a key that must not show.
PIECE = 6
# The sizes of the keys, in random bytes: 40, 48 and 64 characters of base64.
KEY_BYTES = (30, 36, 48)
# How many keys of each size are read in the plain form, and in each other form.
KEYS_PLAIN = 10_000
KEYS_PER_FORM = 1_000
# How many values of the ordinary corpus are read, in each form.
CORPUS_SIZE = 700
KEY_SEED = 11
CORPUS_SEED = 23

ADDRESS_LEAD = "http://localhost:8000/v1/files/"
ADDRESS_TAIL = "/raw"
RELATIVE_LEAD = "data/"
RELATIVE_TAIL = "/out.json"


def slash_keys(seed: int, size: int, count: int) -> list[str]:
    """Base64 of ``size`` random bytes that holds ``/`` and neither ``+`` nor padding."""
    rng = random.Random(seed * 100 + size)
    keys: list[str] = []
    while len(keys) < count:
        key = base64.b64encode(rng.randbytes(size)).decode("ascii")
        if "/" in key and "+" not in key and "=" not in key:
            keys.append(key)
    return keys


def aws_shaped(seed: int, count: int) -> list[str]:
    """Values of 40 characters of letters, digits, ``+`` and ``/``, as a secret access key is."""
    rng = random.Random(seed)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    values: list[str] = []
    while len(values) < count:
        value = "".join(rng.choice(alphabet) for _ in range(40))
        if "/" in value and not value.startswith("/"):
            values.append(value)
    return values


# A part between two `/` that reads as a word of a path, as the reference page lists them:
# digits, one or two small letters, a small letter and digits, three or more small letters
# with a vowel and maybe digits, digits and one small letter, or such pieces of small letters
# and digits joined by `-`, `_` or `+`.
PATH_WORD = re.compile(
    r"[0-9]+|[a-z]{1,2}|[a-z][0-9]+|(?=[a-z]*[aeiouy])[a-z]{3,}[0-9]*|[0-9]+[a-z]"
    r"|(?:[a-z]+[0-9]*|[0-9]+[a-z]*)(?:[-_+]+(?:[a-z]+[0-9]*|[0-9]+[a-z]*))+"
)


def edge_words(key: str) -> tuple[int, int]:
    """How far the parts at the start and at the end of a key read as words of a path.

    Returns the length of the key's longest start, and of its longest end, made of whole
    parts between ``/`` that each read as a word of a path, their ``/`` taken in.
    """
    parts = key.split("/")
    head = 0
    for part in parts[:-1]:
        if not PATH_WORD.fullmatch(part):
            break
        head += len(part) + 1
    tail = 0
    for part in reversed(parts[1:]):
        if not PATH_WORD.fullmatch(part):
            break
        tail += len(part) + 1
    return head, tail


def pieces_beside_words(key: str, text: str) -> list[str]:
    """The pieces of a key that show in a text, but for those inside its ends of path words."""
    head, tail = edge_words(key)
    return [
        key[at : at + PIECE]
        for at in range(len(key) - PIECE + 1)
        if key[at : at + PIECE] in text and at + PIECE > head and at < len(key) - tail
    ]


def plain(value: str) -> list[str]:
    return ["client", value]


def option(value: str) -> list[str]:
    return ["client", "--opt", value]


def glued_option(value: str) -> list[str]:
    return ["client", f"--opt={value}"]


def named(value: str) -> list[str]:
    return ["client", f"MODEL_NAME={value}"]


def shell_text(value: str) -> list[str]:
    return ["sh", "-c", f"client {value} && echo ok"]


def address(value: str) -> list[str]:
    return ["client", f"{ADDRESS_LEAD}{value}{ADDRESS_TAIL}"]


def relative(value: str) -> list[str]:
    return ["client", f"{RELATIVE_LEAD}{value}{RELATIVE_TAIL}"]


KEY_FORMS: dict[str, Callable[[str], list[str]]] = {
    "option": option,
    "option with =": glued_option,
    "value of a name": named,
    "shell text": shell_text,
    "address path": address,
    "relative path": relative,
}


def shown_text(argv: list[str]) -> str:
    text = model.public_command(argv)
    assert text is not None
    return text


def what_shows(keys: list[str], form: Callable[[str], list[str]]) -> tuple[list[str], list[str]]:
    """The keys of a form shown whole though they look random whole, and the pieces shown."""
    whole: list[str] = []
    pieces: list[str] = []
    for key in keys:
        text = shown_text(form(key))
        if key in text:
            if model.looks_random(key):
                whole.append(key)
            continue
        pieces += pieces_beside_words(key, text)
    return whole, pieces


# ---------------------------------------------------------------------------
# A key written with `/` and neither `+` nor padding
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("size", KEY_BYTES)
def test_no_piece_of_a_slash_key_shows_but_an_end_that_reads_as_a_word_of_a_path(
    size: int,
) -> None:
    keys = slash_keys(KEY_SEED, size, KEYS_PLAIN)

    assert what_shows(keys, plain) == ([], [])


@pytest.mark.parametrize("name", list(KEY_FORMS))
@pytest.mark.parametrize("size", KEY_BYTES)
def test_a_slash_key_is_hidden_whole_wherever_it_stands(size: int, name: str) -> None:
    keys = slash_keys(KEY_SEED + 1, size, KEYS_PER_FORM)

    assert what_shows(keys, KEY_FORMS[name]) == ([], [])


@pytest.mark.parametrize(("lead", "tail"), [(ADDRESS_LEAD, ADDRESS_TAIL), ("data/", "/out.json")])
def test_a_slash_key_in_a_path_keeps_the_words_around_it(lead: str, tail: str) -> None:
    key = "Q7xK2mP9vL4nR8tW3yZ6bC1dF5gH/0jS2kEAw4bN7cM1xZ5qR8"
    shown = model.public_command(["client", f"{lead}{key}{tail}"])

    assert shown == shlex.join(["client", f"{lead}<hidden>{tail}"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Short words beside a key are words of a path.
        ("data/up/Q7xK2mP9vL4nR8tW/3yZ6bC1dF5gH0jS2kEAw4bN7c/w.bin", "data/up/<hidden>/w.bin"),
        # A key that starts the run reads as no path: no part after it is a word of one.
        ("Q7xK2mP9vL4nR8tW/3yZ6bC1dF5gH0jS2kEAw4bN7c/out", "<hidden>"),
        ("Q7xK2mP9vL4nR8tW/3yZ6bC1dF5gH0jS2kE/4096", "<hidden>"),
    ],
)
def test_a_slash_key_is_hidden_between_the_words_of_a_path(value: str, expected: str) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", expected])
    assert model.hashed_argv(["client", value]) == ["client", expected]


def test_a_slash_key_that_starts_with_a_slash_is_hidden_whole_in_the_hash() -> None:
    # The shown command hides a run that starts with `/` whole when any part of it looks
    # random; the hash reads the key as no path, since its first part is no word of one.
    keys = [
        key
        for key in slash_keys(KEY_SEED + 2, 36, 4000)
        if key.startswith("/") and model.looks_random(key)
    ]
    assert len(keys) > 10
    keys = [key for key in keys if not PATH_WORD.fullmatch(key.split("/")[1])]

    assert {model.public_command(["client", key]) for key in keys} == {"client '<hidden>'"}
    assert {tuple(model.hashed_argv(["client", key])) for key in keys} == {("client", "<hidden>")}


# ---------------------------------------------------------------------------
# A secret access key in the path of an address or in a relative path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("form", [address, relative], ids=["address path", "relative path"])
def test_a_secret_access_key_in_a_path_is_hidden_whole(form: Callable[[str], list[str]]) -> None:
    values = aws_shaped(KEY_SEED + 3, 1000)

    assert what_shows(values, form) == ([], [])


# ---------------------------------------------------------------------------
# Ordinary values stay shown
# ---------------------------------------------------------------------------

ORGS = ("made-up-org", "example-labs", "org-name", "sample-research", "madeup", "acme-models")
FAMILIES = ("Quill", "Marlin", "Nimbus", "Kestrel", "Aster", "Lumen", "Tundra", "Vireo", "Sable")
# Made-up names cased as some public model names are: capitals inside, capitals with digits.
ODD_FAMILIES = (
    "QuiLLaMo",
    "MaRBERTo",
    "ZeBRAx",
    "XyLMo",
    "PaLiQX",
    "HuSKiT",
    "SmolQM2",
    "TinyGPTq",
    "LuMoSVL",
    "ViKiNGo",
)
SIZES = ("1B", "3B", "7B", "8B", "13B", "24B", "70B", "8x7B", "0.5B", "1.1B")
VARIANTS = ("Instruct", "Chat", "Base", "Coder", "VL", "Vision", "Math", "Guard", "Reward")
QUANTS = ("AWQ", "GPTQ", "GGUF", "FP8", "INT4", "BF16", "Q4_K_M", "W4A16", "EXL2")
WORDS = ("data", "results", "runs", "outputs", "configs", "logs", "models", "checkpoints", "cache")
CAMEL = ("MadeUp", "Experiment", "Baseline", "Sweep", "Ablation", "Quick", "Long", "Run", "Eval")
FILES = ("out.json", "config.json", "model.safetensors", "summary.csv", "train.log", "vocab.json")
HOSTS = ("registry.example.com", "registry.example.org", "images.example.net")
IMAGES = ("bench-runner", "serve-image", "python-bench", "inference-server", "madeup")
REPOS = ("repo-name", "bench-suite", "made-up-lib", "models")


def _hex(rng: random.Random, count: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(count))


def _camel(rng: random.Random, low: int, high: int) -> str:
    return "".join(rng.choice(CAMEL) for _ in range(rng.randint(low, high)))


def _model(rng: random.Random) -> str:
    names = ODD_FAMILIES if rng.random() < 0.35 else FAMILIES
    family = rng.choice(names) + rng.choice(("", "2", "3", "-2.5", "3.1", "-Mini"))
    parts = [family, rng.choice(SIZES)]
    parts += rng.sample(VARIANTS, rng.randint(0, 2))
    if rng.random() < 0.4:
        parts.append(rng.choice(QUANTS))
    if rng.random() < 0.3:
        parts.append(rng.choice(("v0.1", "v1.0", "2501", "0628", "hf")))
    name = "-".join(parts)
    # A part of 32 characters or more is judged on its own, as any value is: keep each under.
    while len(name) >= model.RANDOM_MIN_LENGTH and len(parts) > 2:
        parts.pop()
        name = "-".join(parts)
    if rng.random() < 0.3:
        name = name.lower()
    return f"{rng.choice(ORGS)}/{name}"


def model_id(rng: random.Random) -> str:
    value = _model(rng)
    pick = rng.random()
    if pick < 0.25:
        value += "/" + rng.choice(FILES)
    elif pick < 0.4:
        value += f"/resolve/main/{rng.choice(FILES)}"
    return value


def image_reference(rng: random.Random) -> str:
    path = f"{rng.choice(HOSTS)}/{rng.choice(ORGS)}/{rng.choice(IMAGES)}"
    if rng.random() < 0.3:
        path = f"{rng.choice(HOSTS)}/{rng.choice(ORGS)}/{rng.choice(WORDS)}/{rng.choice(IMAGES)}"
    pick = rng.random()
    if pick < 0.25:
        return f"{path}@sha256:{_hex(rng, 64)}"
    if pick < 0.5:
        return f"{path}:{rng.randint(0, 9)}.{rng.randint(0, 30)}.{rng.randint(0, 9)}"
    if pick < 0.75:
        cuda = f"cuda{rng.randint(11, 12)}.{rng.randint(0, 8)}"
        return f"{path}:v{rng.randint(0, 3)}.{rng.randint(0, 9)}.0-{cuda}-ubuntu22.04"
    return f"{path}:{rng.randint(2023, 2026)}.{rng.randint(1, 12):02d}.{rng.randint(1, 28):02d}"


def relative_path(rng: random.Random) -> str:
    parts = [rng.choice(WORDS)]
    for _ in range(rng.randint(1, 4)):
        pick = rng.random()
        if pick < 0.25:
            parts.append(_camel(rng, 1, 4) + rng.choice(("", "_v2", "V2", "-3", "_01")))
        elif pick < 0.45:
            parts.append(f"run_{rng.randint(0, 9999):04d}")
        elif pick < 0.6:
            parts.append(f"step-{rng.randint(0, 99) * 1000:06d}")
        elif pick < 0.75:
            parts.append(f"{rng.choice(FAMILIES)}-{rng.choice(SIZES)}-{rng.choice(VARIANTS)}")
        elif pick < 0.85:
            parts.append(rng.choice(("train", "eval", "test", "dev", "bench_main", "x86_64")))
        else:
            parts.append(rng.choice(QUANTS))
    parts.append(rng.choice(FILES))
    return "/".join(parts)


def commit_pinned_path(rng: random.Random) -> str:
    org, repo = rng.choice(ORGS), rng.choice(REPOS)
    commit = _hex(rng, model.COMMIT_ID_LENGTH)
    pick = rng.random()
    if pick < 0.3:
        return f"{org}/{repo}/blob/{commit}/src/{rng.choice(WORDS)}/{rng.choice(FILES)}"
    if pick < 0.5:
        return f"{org}/{repo}/tree/{_hex(rng, rng.randint(7, 12))}/{rng.choice(WORDS)}"
    if pick < 0.65:
        return f"{org}/{repo}/archive/{commit}.tar.gz"
    if pick < 0.8:
        return f"{_model(rng)}/resolve/{commit}/{rng.choice(FILES)}"
    if pick < 0.9:
        return f"{org}/{repo}/compare/{_hex(rng, 7)}...{_hex(rng, 7)}"
    return f"blobs/sha256/{_hex(rng, 64)}"


def date_value(rng: random.Random) -> str:
    y, m, d = rng.randint(2020, 2026), rng.randint(1, 12), rng.randint(1, 28)
    h, mi, s = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
    return rng.choice(
        (
            f"{y}/{m:02d}/{d:02d}",
            f"logs/{y}/{m:02d}/{d:02d}/run-{h:02d}.log",
            f"{y}-{m:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}Z",
            f"snapshots/{y}{m:02d}{d:02d}-{h:02d}{mi:02d}{s:02d}/state",
            f"nightly/{y}.{m:02d}.{d:02d}",
            f"runs/{y}-{m:02d}-{d:02d}_{h:02d}-{mi:02d}-{s:02d}_{rng.choice(WORDS)}/events.out",
        )
    )


def version_value(rng: random.Random) -> str:
    a, b, c = rng.randint(0, 9), rng.randint(0, 30), rng.randint(0, 9)
    return rng.choice(
        (
            f"v{a}.{b}.{c}",
            f"{a}.{b}.{c}+cu12{rng.randint(0, 8)}",
            f"made-up-pkg=={a}.{b}.{c}+cu12{rng.randint(0, 8)}",
            f"{a}.{b}.{c}-rc.{rng.randint(1, 5)}+build.{rng.randint(1, 99)}",
            f"cuda12.{rng.randint(0, 8)}/cudnn9.{rng.randint(0, 9)}",
            f"lib/python3.{rng.randint(11, 14)}/site-packages/made_up_pkg",
            f"releases/v{a}.{b}.{c}/made-up-{a}.{b}.{c}.tar.gz",
        )
    )


def rooted_path(rng: random.Random) -> str:
    """A path that starts with ``/``, ``./`` or ``~/``."""
    org, name = _model(rng).split("/", 1)
    pick = rng.random()
    if pick < 0.15:
        return f"/usr/lib/x86_64-linux-gnu/libmadeup{rng.randint(1, 9)}.so.{rng.randint(0, 9)}"
    if pick < 0.3:
        return f"/opt/{rng.choice(ORGS)}/bin/{rng.choice(('bench', 'serve', 'made-up-tool'))}"
    if pick < 0.45:
        return f"./{relative_path(rng)}"
    if pick < 0.6:
        return f"~/{rng.choice(WORDS)}/{org}/{name}/{rng.choice(FILES)}"
    if pick < 0.75:
        n = rng.randint(0, 99)
        return f"/made-up/runs/run-{n}/case_{n}/run_{n:04d}/{rng.choice(FILES)}"
    if pick < 0.9:
        return (
            f"/made-up/cache/hub/models--{org}--{name}"
            f"/snapshots/{_hex(rng, model.COMMIT_ID_LENGTH)}/{rng.choice(FILES)}"
        )
    return f"/made-up/store/{rng.choice(WORDS)}/{org}/{name}/{rng.choice(FILES)}"


# Pieces of the folders of an experiment, written as tags of capitals, digits and words: a
# model and its size, a split over devices, a machine, a batch and a feature.
TAG_KEYS = ("TP", "PP", "DP", "EP", "CP", "SP")
TAG_MACHINES = ("Q100", "Z90", "R7X", "M42", "K800")
TAG_LINKS = ("Ring", "Mesh", "PCIe", "Bus")
TAG_WORDS = (
    "Prefill",
    "Decode",
    "Chunked",
    "Paged",
    "Offload",
    "Cache",
    "Block",
    "Scaled",
    "Fused",
)
TAG_FORMATS = ("FP8", "BF16", "INT4", "W4A16", "FP4", "MXFP4")
TAG_ENGINES = ("madeLLM", "QuillServe", "MOCKRT", "SampleGen")


def _tag(rng: random.Random) -> str:
    pick = rng.randrange(6)
    family = rng.choice(FAMILIES)
    size = rng.choice(("7B", "13B", "70B", "8x7B", "1p5B", "175B"))
    if pick == 0:
        return family + rng.choice(("", "MoE", "Coder", "V3", f"{rng.randint(2, 4)}p1x")) + size
    if pick == 1:
        keys = rng.sample(TAG_KEYS, rng.randint(2, 3))
        return "".join(f"{key}{rng.choice((1, 2, 4, 8, 16, 64))}" for key in keys)
    if pick == 2:
        machine = rng.choice(TAG_MACHINES)
        return f"{machine}x{rng.choice((2, 4, 8))}{rng.choice(('', *TAG_LINKS))}"
    if pick == 3:
        batch = rng.choice((1, 8, 64, 256, 1024))
        return rng.choice((f"BS{batch}", f"BS{batch}xSeq{rng.choice((512, 4096, 32768))}"))
    if pick == 4:
        return rng.choice(TAG_FORMATS) + "".join(rng.sample(TAG_WORDS, rng.randint(1, 3)))
    minor = rng.randint(1, 13)
    return f"{rng.choice(TAG_ENGINES)}v{rng.randint(0, 1)}p{minor}{rng.choice(('', 'p2'))}"


def experiment_path(rng: random.Random) -> str:
    """A relative path whose folders are tags of an experiment, as ``runs/TP8PP2/BS64/out``."""
    folders = [_tag(rng) for _ in range(rng.randint(2, 4))]
    return "/".join([rng.choice(WORDS), *folders, rng.choice(FILES)])


SHAPES = (
    model_id,
    image_reference,
    relative_path,
    commit_pinned_path,
    date_value,
    version_value,
    rooted_path,
    experiment_path,
)


def ordinary_values(seed: int, count: int) -> list[str]:
    """``count`` made-up ordinary values, the shapes taken in turn."""
    rng = random.Random(seed)
    return [SHAPES[k % len(SHAPES)](rng) for k in range(count)]


CORPUS_FORMS: dict[str, Callable[[str], list[str]]] = {
    "plain": plain,
    "option": lambda value: ["client", "--model", value],
    "option with =": lambda value: ["client", f"--model={value}"],
    "value of a name": lambda value: ["client", f"MODEL={value}"],
    "shell text": lambda value: ["sh", "-c", f"client {shlex.quote(value)} && echo ok"],
}


def test_the_ordinary_corpus_holds_long_runs_with_a_slash() -> None:
    values = ordinary_values(CORPUS_SEED, CORPUS_SIZE)
    long_runs = [
        value
        for value in values
        if any(
            "/" in run and len(run) >= model.RANDOM_MIN_LENGTH
            for run in model._TOKEN_RUN.findall(value)
        )
    ]

    assert len(values) == CORPUS_SIZE
    assert len(long_runs) * 4 > len(values)


@pytest.mark.parametrize("name", list(CORPUS_FORMS))
def test_no_ordinary_value_is_hidden(name: str) -> None:
    form = CORPUS_FORMS[name]
    hidden = [
        value
        for value in ordinary_values(CORPUS_SEED, CORPUS_SIZE)
        if model.HIDDEN in shown_text(form(value))
    ]

    assert hidden == []


def test_no_ordinary_value_is_hidden_in_the_hash() -> None:
    values = ordinary_values(CORPUS_SEED, CORPUS_SIZE)

    assert [value for value in values if model.hashed_argv(["client", value])[1] != value] == []


# Paths whose parts between two `/` include tags of capitals and digits, as a format or a size
# is written, and whose other parts are names: each looks random as a whole.
TAGGED_PATHS = (
    "checkpoints/RunBaseline_v2/W4A16/INT4/EvalMadeUpLongMadeUp/train.log",
    "./models/W4A16/QuickMadeUpQuick_v2/MadeUpMadeUp_01/summary.csv",
    "cache/step-097000/Marlin-0.5B-Coder/MadeUpAblationMadeUpV2/EXL2/model.safetensors",
    # Tags of an experiment that mix capitals, digits and words, as a split over devices, a
    # machine, a batch or a version is written.
    "results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json",
    "runs/MarlinMoE8x7B/EP8TP2DP4/FP8CacheBlock/run_03/out.json",
    "logs/NimbusNeoX20B/ZeRO3OffloadBS64/Z90x8Ring/train.log",
    "outputs/madeLLMv0p6p3/ChunkedPrefill512MaxSeqs256/out.json",
)


@pytest.mark.parametrize("value", TAGGED_PATHS)
def test_a_path_with_tags_of_capitals_and_digits_stays_shown(value: str) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", value])
    assert model.hashed_argv(["client", value]) == ["client", value]


def test_two_paths_that_differ_in_a_tag_folder_hash_apart() -> None:
    one = ["client", "results/Quill-3.1-70B-Chat/TP8PP2DP4/BS256xSeq4096/Q100x8/summary.json"]
    two = ["client", "results/Quill-3.1-70B-Chat/TP4PP4DP4/BS256xSeq4096/Q100x8/summary.json"]

    assert model.public_command(one) != model.public_command(two)
    assert model.hashed_argv(one) != model.hashed_argv(two)


# A tag of capitals, digits and words is read as a name only when it is shorter than a value
# that may be hidden by its shape: this part of a key reads as one, piece by piece.
LONG_TAG_KEY = "K/UvFpoITTpBoHasghej0ZabjpNzyfaWgutMBjiD"


def test_a_key_part_that_reads_as_tags_does_not_keep_a_path_shown() -> None:
    shown = model.public_command(["client", f"{RELATIVE_LEAD}{LONG_TAG_KEY}{RELATIVE_TAIL}"])

    assert shown == shlex.join(["client", "<hidden>.json"])


# A key whose last part would read as tags if ``y`` counted as the vowel of a word in a tag,
# as in ``QyyU``.
Y_TAG_KEY = "RsXgeBco/4X/x3ZBraQyyUoBJiTOCRv4GcyguXAe"


def test_a_key_part_whose_words_hold_only_y_is_no_tag() -> None:
    assert model.public_command(["client", Y_TAG_KEY]) == shlex.join(["client", "<hidden>"])
    assert model.hashed_argv(["client", Y_TAG_KEY]) == ["client", "<hidden>"]
