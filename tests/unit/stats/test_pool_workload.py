# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Captures whose workloads differ are not pooled: pooled rounds must measure the same thing.

The workload's arguments, as each capture's header records them, are read as the published
hashes read them (``config_inputs``: the workload alone and after what each side runs before
it). Two captures whose readings differ are refused with ``E_POOL_SIDE_DRIFT``, and the
message names the first argument that differs by the text the results show of it, never a
hidden value. A difference only in a credential pools, and a difference only in a value hidden
for its shape is refused with the message of a hidden setup difference. What is no part of the
workload, a label or a case selection, keeps two captures pooling.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from pairbench.errors import EXIT_ANALYSIS, Refusal
from pairbench.model import (
    IMAGE_COMMAND_PROGRAM_KEY,
    IMAGE_ENTRYPOINT_KEY,
    STRICT,
    Capture,
    Results,
    config_inputs,
    config_sha256,
    workload_difference,
)
from pairbench.stats.analyse import analyse_captures
from pairbench.stats.selftest import synthetic_capture

FIRST, SECOND = "synthetic-a", "synthetic-b"
PYTHON_SIDES: Mapping[str, Any] = {
    "new": {"python": "made-up-python-new"},
    "old": {"python": "made-up-python-old", "baseline": True},
}
# A client whose password option the shown command and the hashes hide, named only in the
# command each side runs before the workload.
CLIENT_SIDES: Mapping[str, Any] = {
    "new": {"cmd": ["redis-benchmark", "{workload}"]},
    "old": {"cmd": ["redis-benchmark", "-p", "6380", "{workload}"], "baseline": True},
}
# Made-up credential values and two made-up runs of 32 hexadecimal digits, which the shown
# command hides for their shape.
KIWI, PLUM = "kiwi7", "plum4"
HEX_ONE = "3f9a1c7e5b2d4086a1c3e5f7092b4d6e"
HEX_TWO = "8e2b6d4f0a1c3e5b7d9f1a3c5e7b9d0f"
HIDDEN_SETUP = (
    f"the setup of new, old differs between the captures {FIRST} and {SECOND} in a value the "
    "results hide"
)
LEFT_OUT = "in a part the shown command leaves out"


def _drift(where: str) -> str:
    return f"the workload differs between the captures {FIRST} and {SECOND} {where}"


# (row id, first workload, second workload, the sides, the message of the refusal).
REFUSED: Sequence[tuple[str, list[str] | None, list[str], Mapping[str, Any], str]] = (
    (
        "ordinary-value",
        ["bench", "--size", "10"],
        ["bench", "--size", "20"],
        PYTHON_SIDES,
        _drift("at its argument 3: 10 against 20"),
    ),
    (
        "added-argument",
        ["bench", "--size", "10"],
        ["bench", "--size", "10", "--fast"],
        PYTHON_SIDES,
        _drift("at its argument 4: no argument against --fast"),
    ),
    (
        "removed-argument",
        ["bench", "--size", "10", "--fast"],
        ["bench", "--size", "10"],
        PYTHON_SIDES,
        _drift("at its argument 4: --fast against no argument"),
    ),
    (
        "reordered-arguments",
        ["bench", "--size", "10", "--fast"],
        ["bench", "--fast", "--size", "10"],
        PYTHON_SIDES,
        _drift("at its argument 2: --size against --fast"),
    ),
    (
        "value-glued-to-its-option",
        ["bench", "--size=10"],
        ["bench", "--size=20"],
        PYTHON_SIDES,
        _drift("at its argument 2: --size=10 against --size=20"),
    ),
    (
        "glued-against-apart",
        ["bench", "--size=10"],
        ["bench", "--size", "10"],
        PYTHON_SIDES,
        _drift("at its argument 2: --size=10 against --size"),
    ),
    (
        "value-inside-a-shell-text",
        ["sh", "-c", "bench --size 10"],
        ["sh", "-c", "bench --size 20"],
        PYTHON_SIDES,
        _drift("at its argument 3: 'bench --size 10' against 'bench --size 20'"),
    ),
    (
        "shell-text-that-holds-a-credential",
        ["sh", "-c", f"bench --token {KIWI} --size 10"],
        ["sh", "-c", f"bench --token {KIWI} --size 20"],
        PYTHON_SIDES,
        _drift(
            "at its argument 3: 'bench --token <hidden> --size 10' against "
            "'bench --token <hidden> --size 20'"
        ),
    ),
    (
        "credential-beside-an-ordinary-value",
        ["bench", "--api-key", KIWI, "--size", "10"],
        ["bench", "--api-key", PLUM, "--size", "20"],
        PYTHON_SIDES,
        _drift("at its argument 5: 10 against 20"),
    ),
    (
        "shape-hidden-value-beside-an-ordinary-value",
        ["bench", "--seed-file", HEX_ONE, "--size", "10"],
        ["bench", "--seed-file", HEX_TWO, "--size", "20"],
        PYTHON_SIDES,
        _drift("at its argument 5: 10 against 20"),
    ),
    (
        "client-password-beside-an-ordinary-value",
        ["-a", KIWI, "-n", "8"],
        ["-a", KIWI, "-n", "9"],
        CLIENT_SIDES,
        _drift("at its argument 4: 8 against 9"),
    ),
    (
        "folder-of-a-path",
        ["bench", "--input", "/made/up/small/data.bin"],
        ["bench", "--input", "/made/up/large/data.bin"],
        PYTHON_SIDES,
        _drift(f"at its argument 3, {LEFT_OUT}"),
    ),
    (
        "host-of-an-address",
        ["bench", "--url", "http://one.made-up.example:8000/v1"],
        ["bench", "--url", "http://two.made-up.example:8000/v1"],
        PYTHON_SIDES,
        _drift(f"at its argument 3, {LEFT_OUT}"),
    ),
    (
        "no-workload-against-a-workload",
        None,
        ["bench"],
        PYTHON_SIDES,
        _drift("at its argument 1: no argument against bench"),
    ),
)

# (row id, first workload, second workload, the sides): captures that pool.
POOLED: Sequence[tuple[str, list[str] | None, list[str] | None, Mapping[str, Any]]] = (
    ("identical", ["bench", "--size", "10"], ["bench", "--size", "10"], PYTHON_SIDES),
    ("credential-option", ["bench", "--api-key", KIWI], ["bench", "--api-key", PLUM], PYTHON_SIDES),
    (
        "credential-variable",
        ["env", f"HF_TOKEN={KIWI}", "bench"],
        ["env", f"HF_TOKEN={PLUM}", "bench"],
        PYTHON_SIDES,
    ),
    (
        "credential-inside-a-shell-text",
        ["sh", "-c", f"bench --token {KIWI} --size 10"],
        ["sh", "-c", f"bench --token {PLUM} --size 10"],
        PYTHON_SIDES,
    ),
    ("client-password", ["-a", KIWI, "-n", "8"], ["-a", PLUM, "-n", "8"], CLIENT_SIDES),
    ("no-workload", None, None, PYTHON_SIDES),
)


def _config(argv: list[str] | None, sides: Mapping[str, Any], **more: Any) -> dict[str, Any]:
    workload: dict[str, Any] = {"driver": "wall"}
    if argv is not None:
        workload["argv"] = list(argv)
    return {"workload": workload, "sides": json.loads(json.dumps(sides)), **more}


def _with_config(cap: Capture, config: Mapping[str, Any]) -> Capture:
    return dataclasses.replace(cap, header=dataclasses.replace(cap.header, config=config))


def _two(one: Mapping[str, Any], two: Mapping[str, Any]) -> list[Capture]:
    """Two captures of one experiment, alike but for their seeds, with these header configs."""
    return [
        _with_config(synthetic_capture(_value, seed=seed, capture_id=name), config)
        for seed, name, config in ((1, FIRST, one), (2, SECOND, two))
    ]


def _value(entry: str, case: str, round_: int, u: float) -> float:
    """A made-up time: ``new`` twice ``old``, with a small seeded jitter."""
    return (2.0 if entry.startswith("new") else 1.0) * (1.0 + round_ / 64) * (1.0 + u / 1000)


def _analyse(captures: Sequence[Capture]) -> Results:
    return analyse_captures(tuple(captures), rule=STRICT)


def _refusal(captures: Sequence[Capture]) -> Refusal:
    with pytest.raises(Refusal) as caught:
        _analyse(captures)
    return caught.value


@pytest.mark.parametrize(
    ("one", "two", "sides", "message"),
    [row[1:] for row in REFUSED],
    ids=[row[0] for row in REFUSED],
)
def test_captures_whose_workloads_differ_are_refused_as_drift(
    one: list[str] | None, two: list[str], sides: Mapping[str, Any], message: str
) -> None:
    caught = _refusal(_two(_config(one, sides), _config(two, sides)))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == message
    assert caught.detail["captures"] == [FIRST, SECOND]


@pytest.mark.parametrize(
    ("one", "two", "sides"), [row[1:] for row in POOLED], ids=[row[0] for row in POOLED]
)
def test_captures_whose_workloads_differ_only_in_a_credential_are_pooled(
    one: list[str] | None, two: list[str] | None, sides: Mapping[str, Any]
) -> None:
    got = _analyse(_two(_config(one, sides), _config(two, sides)))

    assert got.run.pooled is True
    assert [c.capture_id for c in got.run.captures] == [FIRST, SECOND]


def test_a_workload_that_differs_only_in_a_value_hidden_for_its_shape_is_a_hidden_difference() -> (
    None
):
    one = _config(["bench", "--seed-file", HEX_ONE], PYTHON_SIDES)
    two = _config(["bench", "--seed-file", HEX_TWO], PYTHON_SIDES)

    caught = _refusal(_two(one, two))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == HIDDEN_SETUP


@pytest.mark.parametrize(
    ("one", "two"),
    [
        ({"run": {"node_type": "made-up-class-a"}}, {"run": {"node_type": "made-up-class-b"}}),
        ({"cases": {"primary": ["matmul*"]}}, {"cases": {"primary": []}}),
        ({"run": {"out": "made-up-run-a"}}, {"run": {"out": "made-up-run-b"}}),
    ],
    ids=["machine-label", "case-selection", "run-folder"],
)
def test_what_is_no_part_of_the_workload_keeps_two_captures_pooling(
    one: Mapping[str, Any], two: Mapping[str, Any]
) -> None:
    argv = ["bench", "--size", "10"]
    got = _analyse(_two(_config(argv, PYTHON_SIDES, **one), _config(argv, PYTHON_SIDES, **two)))

    assert got.run.pooled is True


def test_a_capture_that_records_no_config_is_left_to_the_fingerprint() -> None:
    got = _analyse(_two({}, _config(["bench", "--size", "20"], PYTHON_SIDES)))

    assert got.run.pooled is True


def _workload_refused(one: Mapping[str, Any], two: Mapping[str, Any]) -> bool:
    try:
        _analyse(_two(one, two))
    except Refusal as caught:
        return caught.message.startswith("the workload differs")
    return False


@pytest.mark.parametrize(
    ("one", "two", "sides"),
    [row[1:4] for row in REFUSED] + [row[1:] for row in POOLED],
    ids=[row[0] for row in REFUSED] + [row[0] for row in POOLED],
)
def test_the_workload_check_agrees_with_the_published_config_hash(
    one: list[str] | None, two: list[str] | None, sides: Mapping[str, Any]
) -> None:
    first, second = _config(one, sides), _config(two, sides)
    hashed = [config_inputs(c)["workload"].get("argv", []) for c in (first, second)]

    assert _workload_refused(first, second) is (hashed[0] != hashed[1])
    # The two configs differ in their workloads alone, so the published hash says the same.
    assert _workload_refused(first, second) is (config_sha256(first) != config_sha256(second))


@pytest.mark.parametrize(
    ("one", "two", "sides"),
    [row[1:4] for row in REFUSED if KIWI in json.dumps(row) or HEX_ONE in json.dumps(row)],
)
def test_the_workload_refusal_holds_no_hidden_value(
    one: list[str] | None, two: list[str], sides: Mapping[str, Any]
) -> None:
    caught = _refusal(_two(_config(one, sides), _config(two, sides)))

    text = caught.message + json.dumps(caught.detail)
    for value in (KIWI, PLUM, HEX_ONE, HEX_TWO):
        assert value not in text
    for value in (HEX_ONE, HEX_TWO):
        for k in range(len(value) - 7):
            assert value[k : k + 8] not in text


THIRD = "synthetic-c"


@pytest.mark.parametrize(
    "places",
    [(0, 1, 2), (1, 0, 2)],
    ids=["no-config-first", "no-config-between"],
)
def test_a_capture_that_records_no_workload_does_not_let_two_others_that_differ_pool(
    places: tuple[int, int, int],
) -> None:
    # The capture that records no config stands first or between the two whose workloads
    # differ; the refusal is the same, wherever it stands.
    named = (
        (FIRST, {}),
        (SECOND, _config(["bench", "--size", "10"], PYTHON_SIDES)),
        (THIRD, _config(["bench", "--size", "20"], PYTHON_SIDES)),
    )
    captures = [
        _with_config(synthetic_capture(_value, seed=k + 1, capture_id=name), config)
        for k, (name, config) in enumerate(named)
    ]

    caught = _refusal([captures[k] for k in places])

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == (
        f"the workload differs between the captures {SECOND} and {THIRD} at its argument 3: "
        "10 against 20"
    )
    assert caught.detail == {"captures": [SECOND, THIRD], "argument": 3}


@pytest.mark.parametrize(
    ("one_sides", "two_sides"),
    [(CLIENT_SIDES, PYTHON_SIDES), (PYTHON_SIDES, CLIENT_SIDES)],
    ids=["client-in-the-first", "client-in-the-second"],
)
def test_a_password_the_client_of_either_capture_reads_is_not_named_when_their_sides_differ(
    one_sides: Mapping[str, Any], two_sides: Mapping[str, Any]
) -> None:
    # Each capture's own hash reading tells the workloads apart, as the word after `-a` is a
    # password only after the client one of them runs; the message reads both after the sides
    # of both captures, so it shows neither word.
    one = _config(["-a", KIWI, "-n", "8"], one_sides)
    two = _config(["-a", PLUM, "-n", "8"], two_sides)

    caught = _refusal(_two(one, two))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == _drift(f"at its argument 2, {LEFT_OUT}")
    assert caught.detail == {"captures": [FIRST, SECOND], "argument": 2}
    assert _workload_refused(one, two) is (config_sha256(one) != config_sha256(two))


def test_workloads_typed_alike_under_different_sides_are_left_to_the_fingerprint() -> None:
    # The hash readings differ, as only one capture runs the client, but the workloads are
    # typed alike: what differs is the sides, which their fingerprints cover.
    argv = ["-a", KIWI, "-n", "8"]
    one, two = _config(argv, CLIENT_SIDES), _config(argv, PYTHON_SIDES)

    assert workload_difference(one, two) is None
    assert config_sha256(one) != config_sha256(two)


def test_no_argument_is_named_when_the_shown_command_cannot_be_read_word_by_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pairbench.model.public_command", lambda *_args, **_kwargs: None)
    one = _config(["bench", "--size", KIWI], PYTHON_SIDES)
    two = _config(["bench", "--size", PLUM], PYTHON_SIDES)

    caught = _refusal(_two(one, two))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == _drift(f"at its argument 3, {LEFT_OUT}")


@pytest.mark.parametrize(
    "places",
    [(0, 1, 2), (1, 0, 2)],
    ids=["no-config-first", "no-config-between"],
)
def test_a_capture_that_records_no_setup_does_not_let_two_others_with_hidden_drift_pool(
    places: tuple[int, int, int],
) -> None:
    # The two captures that record a config differ only in a value hidden for its shape, which
    # the hidden-value check refuses; a capture that records none does not stop it.
    named = (
        (FIRST, {}),
        (SECOND, _config(["bench", "--run-id", HEX_ONE], PYTHON_SIDES)),
        (THIRD, _config(["bench", "--run-id", HEX_TWO], PYTHON_SIDES)),
    )
    captures = [
        _with_config(synthetic_capture(_value, seed=k + 1, capture_id=name), config)
        for k, (name, config) in enumerate(named)
    ]

    caught = _refusal([captures[k] for k in places])

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == (
        f"the setup of new, old differs between the captures {SECOND} and {THIRD} "
        "in a value the results hide"
    )
    assert caught.detail["captures"] == [SECOND, THIRD]


def test_a_config_with_sides_but_no_workload_still_has_its_setups_compared() -> None:
    # A hand-made config may record the sides and no workload table: the workload check skips
    # it, but its side setups are still compared with those of the next capture.
    def sides(run: str) -> dict[str, Any]:
        return {
            "new": {"cmd": ["bench-new", "--run-id", run, "{workload}"]},
            "old": {"cmd": ["bench-old", "--run-id", run, "{workload}"], "baseline": True},
        }

    one = {"sides": sides(HEX_ONE)}
    two = _config(["bench"], sides(HEX_TWO))

    caught = _refusal(_two(one, two))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == HIDDEN_SETUP
    assert caught.detail["captures"] == [FIRST, SECOND]


@pytest.mark.parametrize(
    ("first_sides", "named"),
    [
        (dict(PYTHON_SIDES), "new, old"),
        ({"new": PYTHON_SIDES["new"]}, "new, old"),
    ],
    ids=["sides-and-no-workload", "one-side-table"],
)
@pytest.mark.parametrize(
    "places",
    [(0, 1, 2), (1, 0, 2)],
    ids=["it-first", "it-between"],
)
def test_a_capture_that_records_part_of_a_setup_does_not_let_two_others_with_hidden_drift_pool(
    first_sides: Mapping[str, Any], named: str, places: tuple[int, int, int]
) -> None:
    # The first capture records side tables but no workload, or a table for one side only, so
    # its setups match neither of the others; the two that differ only in a value hidden for
    # its shape are still compared with each other.
    named_configs = (
        (FIRST, {"sides": first_sides}),
        (SECOND, _config(["bench", "--run-id", HEX_ONE], PYTHON_SIDES)),
        (THIRD, _config(["bench", "--run-id", HEX_TWO], PYTHON_SIDES)),
    )
    captures = [
        _with_config(synthetic_capture(_value, seed=k + 1, capture_id=name), config)
        for k, (name, config) in enumerate(named_configs)
    ]

    caught = _refusal([captures[k] for k in places])

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == (
        f"the setup of {named} differs between the captures {SECOND} and {THIRD} "
        "in a value the results hide"
    )
    assert caught.detail["captures"] == [SECOND, THIRD]


# Image sides that name no entrypoint and no arguments of their own: each runs the shared
# workload behind what its image records, so the client the image runs is named only there.
IMAGE_SIDES: Mapping[str, Any] = {
    "new": {"image": "made-up-image:2"},
    "old": {"image": "made-up-image:1", "baseline": True},
}
# What each image records (``IMAGE_ENTRYPOINT_KEY`` and ``IMAGE_COMMAND_PROGRAM_KEY``): a client
# as its entrypoint, or a wrapper script as its entrypoint and a client as its command.
IMAGE_HEADS: Mapping[str, Mapping[str, Any]] = {
    "client-entrypoint": {IMAGE_ENTRYPOINT_KEY: ["memtier_benchmark"]},
    "wrapper-script-then-command": {
        IMAGE_ENTRYPOINT_KEY: ["docker-entrypoint.sh"],
        IMAGE_COMMAND_PROGRAM_KEY: "memtier_benchmark",
    },
}


def _two_images(one: Mapping[str, Any], two: Mapping[str, Any], head: str) -> list[Capture]:
    """Two captures of image sides whose images record ``IMAGE_HEADS[head]``."""
    captures = []
    for seed, name, config in ((1, FIRST, one), (2, SECOND, two)):
        cap = synthetic_capture(_value, seed=seed, capture_id=name, kind="image")
        sides = tuple(
            dataclasses.replace(s, identity={**s.identity, **IMAGE_HEADS[head]}) for s in cap.sides
        )
        captures.append(_with_config(dataclasses.replace(cap, sides=sides), config))
    return captures


@pytest.mark.parametrize("head", sorted(IMAGE_HEADS))
def test_workloads_that_differ_only_in_the_password_of_the_client_an_image_runs_are_pooled(
    head: str,
) -> None:
    one = _config(["-s", "made-up-host", "-a", KIWI, "-n", "8"], IMAGE_SIDES)
    two = _config(["-s", "made-up-host", "-a", PLUM, "-n", "8"], IMAGE_SIDES)
    captures = _two_images(one, two, head)

    got = _analyse(captures)

    assert got.run.pooled is True
    # The published hash, read after what each image records, says the same.
    assert config_sha256(one, captures[0].sides) == config_sha256(two, captures[1].sides)


@pytest.mark.parametrize("head", sorted(IMAGE_HEADS))
def test_a_workload_refusal_after_the_client_an_image_runs_names_no_password(head: str) -> None:
    one = _config(["-s", "made-up-host", "-a", KIWI, "-n", "8"], IMAGE_SIDES)
    two = _config(["-s", "made-up-host", "-a", PLUM, "-n", "9"], IMAGE_SIDES)

    caught = _refusal(_two_images(one, two, head))

    assert (caught.code, caught.exit_code) == ("E_POOL_SIDE_DRIFT", EXIT_ANALYSIS)
    assert caught.message == _drift("at its argument 6: 8 against 9")
    assert caught.detail == {"captures": [FIRST, SECOND], "argument": 6}
    for value in (KIWI, PLUM):
        assert value not in caught.message + json.dumps(caught.detail)
