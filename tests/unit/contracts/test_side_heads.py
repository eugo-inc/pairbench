# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a side runs before ``{workload}`` changes neither how the workload reads nor what it hides.

The shared workload starts a command of its own after the words a side's
spec gives before ``{workload}``, unless those words leave their last word
waiting for it (an option's value, a shell, a runner's operands, a starter
such as ``env``). So the texts of a runner the workload names (``ssh``,
``hyperfine``) read the same after ``timeout 60``, ``./runner`` or
``redis-benchmark`` as alone: a program after a credential in such a text
tells two commands apart in the shown command, the config hash and each
side's argument hash, and two passwords give one of each.

A word the client of one side hides in the shared workload (the ``-a
VALUE`` of ``redis-benchmark {workload}``) is hidden in the argument hash of
every side (``model.hashed_workload``, ``model.hashed_command``), also of a
side whose own program is no client, while an ordinary word still tells two
workloads apart there and a side of a run with no client keeps the word.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model
from pairbench.model import HIDDEN, LaunchSettings, Side
from pairbench.sides.command import CommandKind
from pairbench.sides.identity import KEY_ARGV_SHA256, hashed_sha256

# Made-up passwords that hold no credential word, and two programs to tell commands apart.
PASSWORDS = ("kiwi7mango", "plum4grape")
PROGRAMS = ("bench-old", "bench-new")

# What a side's spec runs before ``{workload}``.
HEADS: dict[str, list[str]] = {
    "timeout": ["timeout", "60"],
    "nice": ["nice"],
    "sudo-u": ["sudo", "-u", "bench"],
    "own-runner": ["./runner"],
    "docker-run": ["docker", "run", "--rm", "made-up/image:1.0"],
    "time-v": ["/usr/bin/time", "-v"],
    "perf-stat": ["perf", "stat", "--"],
    "python-m": ["python3", "-m", "runner"],
    "client": ["redis-benchmark"],
    "taskset": ["taskset", "-c", "2"],
    "env": ["env", "PB_SIDE=1"],
}
# Each shared workload: its words, with ``{s}`` for the password and ``{p}`` for the program,
# and the words as they are shown and hashed.
TEXT = "API_KEY={s};./{p}"
WORKLOADS: dict[str, tuple[list[str], list[str]]] = {
    "ssh": (
        ["ssh", "made-up-host", TEXT],
        ["ssh", "made-up-host", f"API_KEY={HIDDEN};./bench-old"],
    ),
    "hyperfine": (["hyperfine", TEXT], ["hyperfine", f"API_KEY={HIDDEN};./bench-old"]),
}
# The same workloads in the shown command, quoted as a shell reads them.
SHOWN: dict[str, str] = {
    "ssh": f"ssh made-up-host 'API_KEY={HIDDEN};./bench-old'",
    "hyperfine": f"hyperfine 'API_KEY={HIDDEN};./bench-old'",
}
SHOWN_HEAD = "pairbench run --config pairbench.toml --"


def filled(runner: str, password: str, program: str) -> list[str]:
    words = WORKLOADS[runner][0]
    return [word.replace("{s}", password).replace("{p}", program) for word in words]


def declared(head: str) -> list[str]:
    return [*HEADS[head], model.WORKLOAD_PLACEHOLDER]


def side_hashed(head: str, workload: list[str]) -> list[str]:
    """The inputs of the argument hash of a side that runs ``head`` before the workload."""
    sides = [Side.command("a", declared(head))]
    shared = model.hashed_workload(workload, sides)
    return model.hashed_command(declared(head), workload, shared)


def config(head: str, workload: list[str]) -> dict[str, Any]:
    return {"sides": {"a": {"cmd": declared(head)}}, "workload": {"argv": workload}}


def shown(head: str, workload: list[str]) -> str:
    command = ("pairbench", "run", "--config", "pairbench.toml", "--", *workload)
    return model.public_command(command, config={"sides": {"a": {"cmd": declared(head)}}})


PAIRS = [(head, runner) for head in HEADS for runner in WORKLOADS]


@pytest.mark.parametrize(("head", "runner"), PAIRS)
def test_a_runner_the_workload_names_reads_its_text_after_any_head(head: str, runner: str) -> None:
    workload = filled(runner, PASSWORDS[0], PROGRAMS[0])

    assert side_hashed(head, workload) == [*HEADS[head], *WORKLOADS[runner][1]]
    assert shown(head, workload) == f"{SHOWN_HEAD} {SHOWN[runner]}"


@pytest.mark.parametrize(("head", "runner"), PAIRS)
def test_two_programs_after_a_head_give_two_hashes(head: str, runner: str) -> None:
    old, new = (filled(runner, PASSWORDS[0], program) for program in PROGRAMS)

    assert side_hashed(head, old) != side_hashed(head, new)
    assert model.config_sha256(config(head, old)) != model.config_sha256(config(head, new))
    assert shown(head, old) != shown(head, new)


@pytest.mark.parametrize(("head", "runner"), PAIRS)
def test_two_passwords_after_a_head_give_one_hash(head: str, runner: str) -> None:
    one, other = (filled(runner, password, PROGRAMS[0]) for password in PASSWORDS)

    assert side_hashed(head, one) == side_hashed(head, other)
    assert model.config_sha256(config(head, one)) == model.config_sha256(config(head, other))
    assert shown(head, one) == shown(head, other)


def test_the_head_s_own_client_still_reads_the_workload_s_options() -> None:
    workload = ["-a", PASSWORDS[0], "-n", "1000"]

    assert side_hashed("client", workload) == ["redis-benchmark", "-a", HIDDEN, "-n", "1000"]


def test_a_head_that_waits_for_the_workload_reads_it_as_its_own_words() -> None:
    head = ["redis-benchmark", "-a"]
    workload = [PASSWORDS[0], "-n", "1000"]
    sides = [Side.command("a", [*head, model.WORKLOAD_PLACEHOLDER])]
    hashed = model.hashed_command(
        [*head, model.WORKLOAD_PLACEHOLDER], workload, model.hashed_workload(workload, sides)
    )

    assert hashed == ["redis-benchmark", "-a", HIDDEN, "-n", "1000"]


# --- a word one side's client hides is hidden in every side's hash -------------------------

MIXED = {"a": ["redis-benchmark", "{workload}"], "b": ["./bench", "{workload}"]}
NO_CLIENT = {"a": ["./bench-old", "{workload}"], "b": ["./bench", "{workload}"]}


def hashed_sides(commands: dict[str, list[str]], workload: list[str]) -> dict[str, list[str]]:
    sides = [Side.command(name, command) for name, command in commands.items()]
    shared = model.hashed_workload(workload, sides)
    return {
        name: model.hashed_command(command, workload, shared) for name, command in commands.items()
    }


# An image side that names its entrypoint and gives no arguments of its own runs the shared
# workload behind that entrypoint, so the entrypoint is a head as a ``cmd`` side's words are.
ENTRYPOINT_SIDE = {"image": "made-up/redis:1.0", "entrypoint": "redis-benchmark"}


def test_an_image_side_s_entrypoint_key_is_a_head_in_every_side_s_hash() -> None:
    workload = ["-a", PASSWORDS[0], "-n", "1000"]
    sides = [
        Side.image("a", "made-up/redis:1.0", entrypoint="redis-benchmark"),
        Side.command("b", ["./bench", "{workload}"]),
    ]

    shared = model.hashed_workload(workload, sides)

    assert shared == ["-a", HIDDEN, "-n", "1000"]
    assert model.hashed_command(["./bench", "{workload}"], workload, shared) == [
        "./bench",
        "-a",
        HIDDEN,
        "-n",
        "1000",
    ]


def test_an_image_side_s_entrypoint_key_is_a_head_in_the_shown_command_and_config_hash() -> None:
    workload = ["-a", PASSWORDS[0], "-n", "1000"]
    sides = {"a": ENTRYPOINT_SIDE, "b": {"cmd": ["./bench", "{workload}"]}}
    command = ("pairbench", "run", "--config", "pairbench.toml", "--", *workload)
    one, other = (
        {"sides": sides, "workload": {"argv": ["-a", password, "-n", "1000"]}}
        for password in PASSWORDS
    )

    assert model.public_command(command, config={"sides": sides}) == (
        f"{SHOWN_HEAD} -a '{HIDDEN}' -n 1000"
    )
    assert model.config_sha256(one) == model.config_sha256(other)


def test_an_image_side_with_arguments_of_its_own_gives_no_head() -> None:
    workload = ["-a", PASSWORDS[0], "-n", "1000"]
    sides = [
        Side.image("a", "made-up/redis:1.0", args=["-q"], entrypoint="redis-benchmark"),
        Side.command("b", ["./bench", "{workload}"]),
    ]

    assert model.hashed_workload(workload, sides) == workload


def test_a_word_one_side_s_client_hides_is_hidden_in_the_other_side_s_hash() -> None:
    hashed = hashed_sides(MIXED, ["-a", PASSWORDS[0], "-n", "1000"])

    assert hashed == {
        "a": ["redis-benchmark", "-a", HIDDEN, "-n", "1000"],
        "b": ["./bench", "-a", HIDDEN, "-n", "1000"],
    }


def test_two_passwords_give_the_side_with_no_client_one_hash() -> None:
    one, other = (hashed_sides(MIXED, ["-a", password, "-n", "1000"]) for password in PASSWORDS)

    assert one == other


def test_an_ordinary_word_still_tells_two_workloads_apart_on_every_side() -> None:
    one, other = (
        hashed_sides(MIXED, ["-a", PASSWORDS[0], "-n", count]) for count in ("1000", "2000")
    )

    assert one["a"] != other["a"]
    assert one["b"] != other["b"]


def test_a_run_with_no_client_keeps_the_word_in_every_hash() -> None:
    one, other = (hashed_sides(NO_CLIENT, ["-a", password, "-n", "1000"]) for password in PASSWORDS)

    assert one == {
        "a": ["./bench-old", "-a", PASSWORDS[0], "-n", "1000"],
        "b": ["./bench", "-a", PASSWORDS[0], "-n", "1000"],
    }
    assert one["b"] != other["b"]


def test_a_command_with_no_workload_is_hashed_as_written() -> None:
    command = ["redis-benchmark", "-a", PASSWORDS[0], "-n", "1000"]

    assert model.hashed_command(command, None) == model.hashed_argv(command)
    assert model.hashed_command(command, None) == ["redis-benchmark", "-a", HIDDEN, "-n", "1000"]


def test_each_place_of_the_workload_hides_what_the_shared_reading_hides() -> None:
    command = ["./bench", "{workload}", "--then", "{workload}"]
    workload = ["-a", PASSWORDS[0]]
    shared = ["-a", HIDDEN]

    assert model.hashed_command(command, workload, shared) == [
        "./bench",
        "-a",
        HIDDEN,
        "--then",
        "-a",
        HIDDEN,
    ]


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    path = tmp_path / "bench"
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_a_command_side_hashes_the_workload_as_every_side_reads_it(tool: Path) -> None:
    workload = ("-a", PASSWORDS[0], "-n", "1000")
    sides = [Side.command(name, command) for name, command in MIXED.items()]
    side = Side.command("b", [str(tool), "{workload}"])
    settings = LaunchSettings()
    ctx = api.SideContext(
        run_id="run-a",
        settings=settings,
        workload=workload,
        workload_hashed=tuple(model.hashed_workload(workload, sides)),
    )
    alone = api.SideContext(run_id="run-a", settings=settings, workload=workload)

    shared = CommandKind().resolve(side, ctx).side.identity[KEY_ARGV_SHA256]
    own = CommandKind().resolve(side, alone).side.identity[KEY_ARGV_SHA256]

    assert shared == hashed_sha256([str(tool), "-a", HIDDEN, "-n", "1000"])
    assert own == hashed_sha256([str(tool), "-a", PASSWORDS[0], "-n", "1000"])
