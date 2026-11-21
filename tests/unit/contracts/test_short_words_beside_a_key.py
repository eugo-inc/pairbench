# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A key whose end parts read as short words of a path is hidden whole, shown and hashed alike.

A part of a key between two ``/`` reads as a short word of a path by chance:
digits, one or two small letters, a small letter and digits, digits and a small
letter, or such pieces joined by ``+`` (``8``, ``au``, ``j0``, ``fm``,
``p+em2``). The part of the key between such words may then be shorter than
``RANDOM_MIN_LENGTH``. Its length is read with up to two short words on each
side of it, and when the key looks random it is hidden with them, in the shown
command and in the hash alike, while the words of the path around it are kept
(``data/<hidden>/out.json``). A key is read between the longer words of a path
around it, and apart from the folders of small letters next to it, so a folder
that is no word of a path does not join it (``srv/data/<hidden>/out.json``,
``srv/nfs/<hidden>/x.bin``). A key still shows whole when a part at one of its
ends reads as a longer word of a path, when more than two short words stand at
one of its ends, when the part between its words of a path fails one of the
tests of ``looks_random``, or when every part of it reads as a name; the seeded
keys check that no other key shows. Paths and names that hold short words stay
shown. Every value here is made up, by hand or by seeded generators.
"""

from __future__ import annotations

import base64
import random
import re
import shlex
from collections.abc import Callable

import pytest

from pairbench import model

# Made-up keys whose first or last part reads as a short word of a path: written with a
# ``+`` in an end part, and with ``/`` only.
KEYS = (
    "au/EXAMPLETailFakezQ9zQx9XyTAILRea/p+em2",
    "au/NOTKeyXy42FakezQTailzQXy9RealUP/p+em2",
    "j0/EXAMPLE+TailFakezQ9zQx9XyTAILRe/fm",
    "8/EXAMPLETailFak/zQ9zQx9XyTAILRe",
    "0/EXAMPLETailFak/zQ9zQx9XyTAILRe",
    "EXAMPLETailFak/zQ9zQx9XyTAILRe/fm",
    "EXAMPLETailFak/zQ9zQx9XyTAILRea/0",
)

# Where a key stands in a command, with ``{}`` for the key.
RELATIVE = "data/{}/out.json"
ADDRESS = "http://localhost:8000/v1/files/{}/raw"
OPTION = "--in=data/{}/out.json"
SHELL = "client data/{}/out.json && echo ok"


def _argv_forms(key: str) -> list[tuple[list[str], list[str]]]:
    """Each command that holds the key, with the same command holding ``HIDDEN`` for it."""
    return [
        (["client", form.format(key)], ["client", form.format(model.HIDDEN)])
        for form in (RELATIVE, ADDRESS, OPTION)
    ] + [(["sh", "-c", SHELL.format(key)], ["sh", "-c", SHELL.format(model.HIDDEN)])]


@pytest.mark.parametrize("key", KEYS)
def test_a_key_with_short_words_at_its_ends_is_hidden_whole_shown_and_hashed(key: str) -> None:
    assert model.looks_random(key)
    for argv, hidden in _argv_forms(key):
        assert model.public_command(argv) == shlex.join(hidden)
        assert model.hashed_argv(argv) == hidden
    assert model.public_words(f"client {RELATIVE.format(key)}") == (
        f"client {RELATIVE.format(model.HIDDEN)}"
    )


# A key with three short words of a path at one end: the two beside it are hidden with it,
# and the third is kept. The value, and how the shown command and the hash show it.
BEYOND_TWO = (
    (
        "data/1/2/3/EXAMPLETailFak/zQ9zQx9XyTAILRe/out.json",
        f"data/1/{model.HIDDEN}/out.json",
    ),
    (
        "data/EXAMPLETailFak/zQ9zQx9XyTAILRea/up/8/0/out.json",
        f"data/{model.HIDDEN}/0/out.json",
    ),
)


@pytest.mark.parametrize(("value", "shown"), BEYOND_TWO)
def test_two_short_words_on_each_side_of_a_key_are_read_with_it(value: str, shown: str) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", shown]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


# A key in a path that starts with a folder that is no word of a path (three small letters
# with no vowel), with longer words or more such folders between that folder and the key: the
# key is read between the words around it. The value, how the shown command and the hash show
# it.
KEY = "EXAMPLETailFakezQ9/zQx9XyTAILRealUP"
BASE64_KEY = "VjmN/FakeZewHCOCLSZzrf04gExample+8LCjcLBNwvS"
AFTER_A_FOLDER_THAT_IS_NO_WORD = (
    (f"srv/data/{KEY}/out.json", f"srv/data/{model.HIDDEN}/out.json"),
    (f"nfs/scratch/{KEY}/x.bin", f"nfs/scratch/{model.HIDDEN}/x.bin"),
    (f"pkg/models/{KEY}", f"pkg/models/{model.HIDDEN}"),
    (f"srv/data/nfs/scratch/{KEY}/out.json", f"srv/data/nfs/scratch/{model.HIDDEN}/out.json"),
    (f"{KEY}/out/bkp", model.HIDDEN),
    (f"srv/data/au/{KEYS[5]}/out.json", f"srv/data/{model.HIDDEN}/out.json"),
    (f"/srv/data/{KEY}", model.HIDDEN),
    (f"/srv/data/{KEY}/out.json", f"{model.HIDDEN}.json"),
    (f"srv/nfs/{KEY}/x.bin", f"srv/nfs/{model.HIDDEN}/x.bin"),
    (f"tmp/pkg/{KEY}/out.json", f"tmp/pkg/{model.HIDDEN}/out.json"),
    (f"/mnt/nfs/{KEY}/x.bin", f"{model.HIDDEN}.bin"),
    (
        f"srv/data/nfs/scratch/pkg/models/{KEY}/out.json",
        f"srv/data/nfs/scratch/pkg/models/{model.HIDDEN}/out.json",
    ),
)


@pytest.mark.parametrize(("value", "shown"), AFTER_A_FOLDER_THAT_IS_NO_WORD)
def test_a_key_after_a_folder_that_is_no_word_is_read_between_the_longer_words(
    value: str, shown: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", shown]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


# A key beside folders that are no word of a path, with a word of a path before them or between
# them, as ``v1``, ``8``, ``run_01`` and ``data2`` are: the key is read apart from all of them,
# before the folders or after them. The value, how the shown command and the hash show it.
AFTER_WORDS_AND_FOLDERS = (
    (f"v1/srv/nfs/{KEY}/x.bin", f"v1/srv/nfs/{model.HIDDEN}/x.bin"),
    (f"8/tmp/pkg/{KEY}/out.json", f"8/tmp/pkg/{model.HIDDEN}/out.json"),
    (f"run_01/srv/nfs/{KEY}/x.bin", f"run_01/srv/nfs/{model.HIDDEN}/x.bin"),
    (f"data2/srv/nfs/{KEY}/x.bin", f"data2/srv/nfs/{model.HIDDEN}/x.bin"),
    (f"v1/en/srv/nfs/{KEY}/x.bin", f"v1/en/srv/nfs/{model.HIDDEN}/x.bin"),
    (f"en/{KEY}/srv/v1/nfs/x.bin", f"en/{model.HIDDEN}/srv/v1/nfs/x.bin"),
    (f"/opt/v2/srv/nfs/{KEY}/x.bin", f"{model.HIDDEN}.bin"),
    (f"/mnt/c/tmp/pkg/{KEY}/x.bin", f"{model.HIDDEN}.bin"),
    # A key written as base64, with a `+`: its core is hidden and the words around it are kept,
    # as in ``srv/nfs/<key>``, rather than the whole run.
    (f"v1/srv/nfs/{BASE64_KEY}/x.bin", f"v1/srv/nfs/{model.HIDDEN}/x.bin"),
    (f"8/tmp/pkg/{BASE64_KEY}/out.json", f"8/tmp/pkg/{model.HIDDEN}/out.json"),
    (f"srv/nfs/{BASE64_KEY}/x.bin", f"srv/nfs/{model.HIDDEN}/x.bin"),
)


@pytest.mark.parametrize(("value", "shown"), AFTER_WORDS_AND_FOLDERS)
def test_a_key_after_words_of_a_path_and_folders_that_are_no_word_is_read_apart_from_them(
    value: str, shown: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", shown]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


# A key that the reading with only the folders of small letters at its ends left out already
# hides: that reading comes first, so what it hides stays hidden. In ``srv/v1/nfs/<key>`` it
# hides ``nfs`` with the key. Under ``/mnt/c/tmp/pkg/`` it reaches a key whose last part reads
# as a longer word of a path (``zqfo6``), which the reading past ``c`` alone leaves whole in
# the hash. The value, how the shown command and the hash show it.
READ_FIRST_WITH_FOLDERS_LEFT_OUT = (
    (f"srv/v1/nfs/{KEY}/x.bin", f"srv/v1/{model.HIDDEN}/x.bin"),
    ("/mnt/c/tmp/pkg/EXAMPLETailFakezQ9zQx9XyT/zqfo6/x.bin", f"{model.HIDDEN}.bin"),
    ("/srv/c/tmp/pkg/EXAMPLEzQ9xFakeKEYtail7Qz/zqfo6/x.bin", f"{model.HIDDEN}.bin"),
)


@pytest.mark.parametrize(("value", "shown"), READ_FIRST_WITH_FOLDERS_LEFT_OUT)
def test_a_key_hidden_with_the_folders_of_small_letters_left_out_stays_hidden(
    value: str, shown: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", shown]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


# A key in a path with folders that are no word of a path and hold capitals or digits, which
# no part of three small letters or more stands for: the key is reached only by leaving out the
# longer words between them, one at an end, then two. The value, how the shown command and the
# hash show it.
CUT_AT_LONGER_WORDS = (
    (f"SRV/data/{KEY}/out.json", f"SRV/data/{model.HIDDEN}/out.json"),
    (f"{KEY}/data/SRV/out.json", f"{model.HIDDEN}.json"),
    (f"SRV/data/NFS2/runs/{KEY}/out.json", f"SRV/data/NFS2/runs/{model.HIDDEN}/out.json"),
    (f"{KEY}/data/NFS2/runs/SRV/out.json", f"{model.HIDDEN}.json"),
    (f"/SRV/data/NFS2/runs/{KEY}/out.json", f"{model.HIDDEN}.json"),
)


@pytest.mark.parametrize(("value", "shown"), CUT_AT_LONGER_WORDS)
def test_a_key_after_folders_with_capitals_is_read_with_up_to_two_longer_words_left_out(
    value: str, shown: str
) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", shown])
    assert model.hashed_argv(["client", value]) == ["client", shown]
    assert model.public_command(["sh", "-c", f"client {value} && echo ok"]) == shlex.join(
        ["sh", "-c", f"client {shown} && echo ok"]
    )


# Paths that start with a folder that is no word of a path and hold names: shown as typed.
NAMES_AFTER_A_FOLDER_THAT_IS_NO_WORD = (
    "srv/data/BM_Gemm/4096/out.json",
    "src/models/made-up-org/Quill-7B/config.json",
    "tmp/runs/MadeUpModel-7B-Instruct/v1/out.json",
    "nfs/scratch/TP8PP2/1/v1/out.json",
    "srv/nfs/MadeUpModel-7B-Instruct/v1/out.json",
    "tmp/pkg/BM_Gemm/4096/out.json",
    "v1/srv/nfs/MadeUpModel-7B-Instruct/v1/out.json",
    "8/tmp/pkg/BM_Gemm/4096/out.json",
    "run_01/srv/nfs/Quill-7B/config.json",
)


@pytest.mark.parametrize("value", NAMES_AFTER_A_FOLDER_THAT_IS_NO_WORD)
def test_names_after_a_folder_that_is_no_word_are_shown(value: str) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", value])
    assert model.hashed_argv(["client", value]) == ["client", value]


# The known limit SECURITY.md states: a key in a path with a folder that is no word of a path and
# holds a capital, a digit or a ``-`` can show whole, in the shown command and the hash alike; so
# does one that only leaving out three longer words at an end would reach, one more than the
# config reference says the rule leaves out.
WHOLE_BESIDE_A_FOLDER_NOT_SMALL_LETTERS = (
    f"SRV/NFS/{KEY}/out.json",
    f"srv2/nfs/{KEY}/x.bin",
    f"Data-X/nfs/{KEY}/x.bin",
    f"SRV/Data/{KEY}/out.json",
    f"Documents/{KEY}/x.bin",
    f"SRV/data/NFS2/runs/BKP3/logs/{KEY}/out.json",
)


@pytest.mark.parametrize("value", WHOLE_BESIDE_A_FOLDER_NOT_SMALL_LETTERS)
def test_a_key_beside_a_folder_not_small_letters_can_show_whole(value: str) -> None:
    assert model.public_command(["client", value]) == shlex.join(["client", value])
    assert model.hashed_argv(["client", value]) == ["client", value]


# The seeded keys: how many of each kind, and the seed.
SEEDED_KEYS = 600
KEY_SEED = 31
# How many short words of a path the rule reads on each side of the part of a key between
# its words of a path.
SHORT_WORDS_BESIDE = 2
BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

# A part between two ``/`` that reads as a word of a path, as the reference page lists them:
# empty, digits, one or two small letters, a small letter and digits, three or more small
# letters with a vowel and maybe digits, digits and one small letter, or pieces of small
# letters and digits joined by ``-``, ``_`` or ``+``.
WORD = re.compile(r"[0-9]+|[a-z]{1,2}|[a-z][0-9]+|(?=[a-z]*[aeiouy])[a-z]{3,}[0-9]*|[0-9]+[a-z]")
PIECE = re.compile(r"[a-z]+[0-9]*|[0-9]+[a-z]*")
JOINERS = re.compile(r"[-_+]+")
# What makes a word of a path a longer word: three small letters or more, or a ``-`` or ``_``.
LONGER = re.compile(r"[a-z]{3,}|[-_]")


def path_word(part: str) -> bool:
    if not JOINERS.search(part):
        return not part or WORD.fullmatch(part) is not None
    return all(PIECE.fullmatch(piece) for piece in JOINERS.split(part) if piece)


def short_word(part: str) -> bool:
    return path_word(part) and LONGER.search(part) is None


def short_end(key: str) -> bool:
    parts = key.split("/")
    return short_word(parts[0]) or short_word(parts[-1])


def slash_keys(count: int) -> list[str]:
    """Base64 of 24 random bytes, 32 characters, with ``/``, no ``+`` and a short word at an end."""
    rng = random.Random(KEY_SEED)
    keys: list[str] = []
    while len(keys) < count:
        key = base64.b64encode(rng.randbytes(24)).decode("ascii")
        if "/" in key and "+" not in key and short_end(key) and model.looks_random(key):
            keys.append(key)
    return keys


def plus_keys(count: int) -> list[str]:
    """40 characters of base64 with ``+`` and ``/``, and a short word at an end."""
    rng = random.Random(KEY_SEED + 1)
    keys: list[str] = []
    while len(keys) < count:
        key = "".join(rng.choice(BASE64) for _ in range(40))
        if "+" in key and "/" in key and short_end(key) and model.looks_random(key):
            keys.append(key)
    return keys


def why_shown(key: str) -> str | None:
    """Say why a key may show whole, or ``None`` when it should be hidden.

    The words of a path at an end of the key that the rule cannot read as part of it: more
    than ``SHORT_WORDS_BESIDE``, or one that is a longer word. The part between its words of a
    path failing tests 2 to 5 of ``looks_random``, its parts of digits left out of the share of
    words. Every part reading as a name.
    """
    parts = key.split("/")
    if all(model._ordinary_part(part, "") for part in parts):
        return "every part reads as a name"
    inner = [k for k, part in enumerate(parts) if not path_word(part)]
    if not inner:
        return "every part is a word of a path"
    for end in (parts[: inner[0]], parts[inner[-1] + 1 :]):
        if len(end) > SHORT_WORDS_BESIDE or not all(short_word(part) for part in end):
            return "an end the rule cannot read as part of the key"
    core = parts[inner[0] : inner[-1] + 1]
    digits = sum(len(part) + 1 for part in core if part.isdigit())
    if not model._random_shape("/".join(core), digits):
        return "the part between the words fails a test of looks_random"
    return None


SEEDED_FORMS: dict[str, Callable[[str], list[str]]] = {
    "plain": lambda key: ["client", key],
    "option": lambda key: ["client", f"--key={key}"],
    "relative": lambda key: ["client", RELATIVE.format(key)],
    "address": lambda key: ["client", ADDRESS.format(key)],
    "address after v1": lambda key: ["client", f"http://localhost:8000/v1/{key}/raw"],
    "after a short folder": lambda key: ["client", f"en/{key}/out.json"],
    "after a folder that is no word": lambda key: ["client", f"srv/data/{key}/out.json"],
    "after two folders that are no word": lambda key: ["client", f"srv/nfs/{key}/x.bin"],
    "after a word and two folders that are no word": lambda key: [
        "client",
        f"v1/srv/nfs/{key}/x.bin",
    ],
}


@pytest.mark.parametrize("kind", ["slash", "plus"])
@pytest.mark.parametrize("form", list(SEEDED_FORMS))
def test_a_seeded_key_with_a_short_end_shows_only_where_the_rule_cannot_reach_it(
    kind: str, form: str
) -> None:
    keys = slash_keys(SEEDED_KEYS) if kind == "slash" else plus_keys(SEEDED_KEYS)
    assert len(keys) == SEEDED_KEYS
    unexplained = []
    for key in keys:
        argv = SEEDED_FORMS[form](key)
        shown = model.public_command(argv)
        assert shown == shlex.join(model.hashed_argv(argv)), key
        if key in shown and why_shown(key) is None:
            unexplained.append(key)
    assert unexplained == []


# Paths and names with short words of a path next to a name: none is hidden.
CORPUS_SIZE = 400
CORPUS_SEED = 43
CAMEL = ("MadeUp", "Attention", "Gemm", "Softmax", "LayerNorm", "Reduce", "Scan", "TopK")
SHORT = ("0", "1", "8", "16", "128", "4096", "v1", "x86", "7b", "en", "a", "p1", "q4", "2x")
WORDS = ("data", "results", "runs", "out", "bench", "logs", "models", "cache")
FILES = ("out.json", "summary.csv", "bench", "run.sh", "config.yaml")
TAGS = ("TP8PP2", "BS64", "Q100x8", "W4A16", "FP8Cache", "NeoX20B")


def ordinary_values() -> list[str]:
    rng = random.Random(CORPUS_SEED)

    def camel(least: int, most: int) -> str:
        return "".join(rng.choice(CAMEL) for _ in range(rng.randint(least, most)))

    def shorts(least: int, most: int) -> list[str]:
        return [rng.choice(SHORT) for _ in range(rng.randint(least, most))]

    values: list[str] = []
    for _ in range(CORPUS_SIZE):
        numbers = "/".join(str(rng.choice((1, 8, 64, 1024, 4096))) for _ in range(3))
        name = rng.choice(
            (
                camel(2, 5),
                f"{camel(1, 2)}-{rng.choice(('7B', '13B', '8x7B'))}-Instruct",
                f"Run{camel(1, 3)}_{rng.randint(0, 99):02d}",
            )
        )
        values += [
            f"BM_{camel(1, 3)}/{numbers}",
            "/".join([rng.choice(WORDS), rng.choice(TAGS), *shorts(1, 4), rng.choice(FILES)]),
            "/".join([rng.choice(WORDS), *shorts(0, 3), name, *shorts(0, 3), rng.choice(FILES)]),
            "/".join(["made-up-org", f"Quill-{rng.choice(('7B', '1.5B'))}", *shorts(2, 2)]),
        ]
    return values


@pytest.mark.parametrize("form", ["plain", "relative", "address after v1"])
def test_a_path_or_name_with_short_words_is_shown(form: str) -> None:
    hidden = []
    for value in ordinary_values():
        argv = SEEDED_FORMS[form](value)
        if model.public_command(argv) != shlex.join(argv) or model.hashed_argv(argv) != argv:
            hidden.append(value)
    assert hidden == []
