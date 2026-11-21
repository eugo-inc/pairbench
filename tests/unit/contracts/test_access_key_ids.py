# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""An AWS access key id, as the shown command hides it by its shape wherever it stands.

An access key id is one of the access key prefixes AWS gives on its page of IAM
identifiers, followed by capitals and digits to 20 characters in all. It is
hidden though it is shorter than a random-looking value has to be, under a name
that names nothing as well as alone. Other ids of that page, and capital codes
of the same length, stay shown. Every id here is made up.
"""

from __future__ import annotations

import shlex
import time

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "

# Made-up ids in the shape of an access key id and of a temporary one, each written as its
# prefix and a made-up tail so that no line of the source holds a whole id.
KEY_ID = "AKIA" + "MADEUPEXAMPLE123"
TEMPORARY_KEY_ID = "ASIA" + "ZQMADEUPEXAMPLE7"
KEY_IDS = (KEY_ID, TEMPORARY_KEY_ID)


def shown(*args: str) -> str | None:
    return model.public_command((*LEAD, *args))


def test_the_shape_constants() -> None:
    assert model.ACCESS_KEY_ID_PREFIXES == ("AKIA", "ASIA")
    assert model.ACCESS_KEY_ID_LENGTH == 20
    assert [len(key_id) for key_id in KEY_IDS] == [20, 20]


@pytest.mark.parametrize("key_id", KEY_IDS)
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("tool", "{}"), ("tool", "<hidden>")),
        (("tool", "--opt", "{}"), ("tool", "--opt", "<hidden>")),
        (("tool", "--opt={}"), ("tool", "--opt=<hidden>")),
        (("MODEL_NAME={}", "tool"), ("MODEL_NAME=<hidden>", "tool")),
        (("sh", "-c", "tool --opt {} && echo ok"), ("sh", "-c", "tool --opt <hidden> && echo ok")),
        (("sh", "-c", "MODEL_NAME={} tool"), ("sh", "-c", "MODEL_NAME=<hidden> tool")),
        (("tool", "-k{}"), ("tool", "-k<hidden>")),
        (("tool", "keys/{}/out.json"), ("tool", "keys/<hidden>/out.json")),
        (("tool", "made_up_{}"), ("tool", "made_up_<hidden>")),
        (
            ("curl", "http://127.0.0.1:8000/v1?id={}"),
            ("curl", "http://127.0.0.1:8000/v1?id=<hidden>"),
        ),
    ],
    ids=[
        "plain",
        "option",
        "glued-option",
        "name",
        "sh-c-option",
        "sh-c-name",
        "short-option",
        "path-part",
        "after-underscore",
        "query",
    ],
)
def test_an_access_key_id_is_hidden_wherever_it_stands(
    args: tuple[str, ...], expected: tuple[str, ...], key_id: str
) -> None:
    typed = tuple(arg.replace("{}", key_id) for arg in args)

    assert shown(*typed) == SHOWN_LEAD + shlex.join(expected)


@pytest.mark.parametrize("key_id", KEY_IDS)
def test_an_access_key_id_looks_random_by_its_shape(key_id: str) -> None:
    assert model.looks_random(key_id) is True
    assert model.looks_random(key_id + "==") is True


@pytest.mark.parametrize("key_id", KEY_IDS)
def test_the_hash_reads_an_access_key_id_as_hidden(key_id: str) -> None:
    assert model.hashed_argv(["tool", "--opt", key_id]) == ["tool", "--opt", model.HIDDEN]
    assert model.hashed_argv([f"MODEL_NAME={key_id}", "tool"]) == ["MODEL_NAME=<hidden>", "tool"]


@pytest.mark.parametrize(
    "value",
    [
        "MADEUPCODEFORTESTS20",
        "AIDAMADEUPEXAMPLE123",
        "AROAMADEUPEXAMPLE123",
        "AKIAMADEUPEXAMPLE12",
        "AKIAMADEUPEXAMPLE1234",
        "AKIAMADEUPEXAMPLe123",
        "akiamadeupexample123",
        "X" + KEY_ID,
    ],
    ids=[
        "capital-code",
        "user-id",
        "role-id",
        "one-short",
        "one-long",
        "small-letter",
        "small-letters",
        "prefix-inside",
    ],
)
def test_a_capital_code_of_the_same_length_stays_shown(value: str) -> None:
    assert model.looks_random(value) is False
    assert shown("tool", "--opt", value) == f"{SHOWN_LEAD}tool --opt {value}"
    assert shown(f"MODEL_NAME={value}", "tool") == f"{SHOWN_LEAD}MODEL_NAME={value} tool"


# A command line far longer than any typed one; each takes a small part of a second.
LONG = 128_000
QUICK_S = 2.0


@pytest.mark.parametrize(
    "arg",
    [
        " ".join([KEY_ID] * (LONG // 21)),
        "/".join([KEY_ID] * (LONG // 21)),
        "--ids=" + ",".join([TEMPORARY_KEY_ID] * (LONG // 21)),
        "_".join(["MADEUPCODEFORTESTS20"] * (LONG // 21)),
    ],
    ids=["words", "slash-parts", "option-list", "capital-codes"],
)
def test_a_long_argument_of_access_key_ids_is_cleaned_quickly(arg: str) -> None:
    times = []
    for _ in range(3):
        start = time.perf_counter()
        model.public_command((*LEAD, "tool", arg))
        times.append(time.perf_counter() - start)

    assert min(times) < QUICK_S
