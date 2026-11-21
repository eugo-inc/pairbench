# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The cost of a launch, the size of the environment and where the tool itself runs."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import Refusal
from pairbench.model import (
    Capture,
    EnvPad,
    Experiment,
    Header,
    Launch,
    LaunchCost,
    LaunchCostSettings,
    LaunchSettings,
    MachineRecord,
    Results,
    Side,
)

# ---------------------------------------------------------------------------
# The cost of a launch
# ---------------------------------------------------------------------------

COST_RECORD = {
    "t": "launch_cost",
    "command": "true",
    "n": 20,
    "median_s": 0.0005,
    "p25_s": 0.0004,
    "p75_s": 0.0007,
    "min_s": 0.0003,
}


def test_the_launch_cost_record_of_a_capture() -> None:
    cost = LaunchCost.from_json(COST_RECORD)
    assert cost == LaunchCost(
        command="true", n=20, median_s=0.0005, p25_s=0.0004, p75_s=0.0007, min_s=0.0003
    )
    assert cost.to_json() == COST_RECORD
    assert model.record_from_json(COST_RECORD) == cost
    assert model.RECORD_TYPES["launch_cost"] is LaunchCost
    assert model.EMPTY_COMMAND == "true"


def test_the_cost_is_made_from_the_times_of_the_empty_launches() -> None:
    cost = LaunchCost.of("true", [0.003, 0.001, 0.002, 0.005, 0.004])
    assert (cost.command, cost.n) == ("true", 5)
    assert (cost.median_s, cost.p25_s, cost.p75_s, cost.min_s) == (0.003, 0.002, 0.004, 0.001)
    assert cost.spread_s == 0.002
    assert LaunchCost.of("true", [0.25]) == LaunchCost(
        command="true", n=1, median_s=0.25, p25_s=0.25, p75_s=0.25, min_s=0.25
    )
    with pytest.raises(ValueError, match="needs at least one timed launch"):
        LaunchCost.of("true", [])


@pytest.mark.parametrize("key", ["command", "n", "median_s", "p25_s", "p75_s", "min_s"])
def test_a_launch_cost_record_needs_every_key(key: str) -> None:
    record = {k: v for k, v in COST_RECORD.items() if k != key}
    with pytest.raises(Refusal, match=f"missing key '{key}'") as caught:
        model.record_from_json(record)
    assert caught.value.code == "E_USAGE"


@pytest.mark.parametrize(
    ("key", "value"), [("n", 0), ("median_s", -0.1), ("p25_s", -1), ("p75_s", -1), ("min_s", -1)]
)
def test_a_launch_cost_keeps_its_limits(key: str, value: float) -> None:
    with pytest.raises(Refusal, match=f"LaunchCost.{key}: expected at least"):
        LaunchCost.from_json({**COST_RECORD, key: value})


def test_the_cost_follows_the_warm_up_launches_in_the_records_of_a_capture() -> None:
    cost = LaunchCost.from_json(COST_RECORD)
    capture = Capture(
        capture_id="cap-000001",
        header=Header(capture_id="cap-000001"),
        launches=(
            Launch(seq=1, phase="warmup", round=0, pos=None, name="new"),
            Launch(seq=2, phase="warmup", round=0, pos=None, name="old"),
            Launch(seq=3, phase="round", round=1, pos=1, name="new"),
        ),
        launch_cost=cost,
    )
    records = capture.to_records()
    assert [(r["t"], r.get("seq")) for r in records] == [
        ("header", None),
        ("launch", 1),
        ("launch", 2),
        ("launch_cost", None),
        ("launch", 3),
    ]
    assert Capture.from_records(records) == capture
    only_cost = Capture(
        capture_id="cap-000002", header=Header(capture_id="cap-000002"), launch_cost=cost
    )
    assert [r["t"] for r in only_cost.to_records()] == ["header", "launch_cost"]
    with pytest.raises(Refusal, match="two launch_cost records"):
        Capture.from_records([*records, COST_RECORD])


def test_a_capture_without_a_measured_cost_has_none() -> None:
    capture = Capture(capture_id="cap-000001", header=Header(capture_id="cap-000001"))
    assert capture.launch_cost is None
    assert all(record["t"] != "launch_cost" for record in capture.to_records())


def test_the_results_carry_the_same_cost_and_leave_the_key_out_without_one(
    example_results: dict[str, Any], example_results_required_only: dict[str, Any]
) -> None:
    results = Results.from_json(example_results)
    assert results.launch_cost == LaunchCost(
        command="true", n=20, median_s=0.0005, p25_s=0.0004, p75_s=0.0007, min_s=0.0003
    )
    written = results.to_json()["launch_cost"]
    assert written == {k: v for k, v in COST_RECORD.items() if k != "t"}
    without = Results.from_json(example_results_required_only)
    assert without.launch_cost is None
    assert "launch_cost" not in without.to_json()


def test_the_figures_of_the_launch_cost() -> None:
    assert model.FIGURE_LAUNCH_COST_MEDIAN == "launch_cost.median"
    assert model.FIGURE_LAUNCH_COST_SPREAD == "launch_cost.spread"


def test_the_defaults_of_the_launch_cost_settings() -> None:
    assert LaunchCostSettings() == LaunchCostSettings(launches=20, note_share=0.01)
    assert Experiment(sides=(Side(name="new", kind="cmd"),)).launch_cost == LaunchCostSettings()
    assert LaunchCostSettings(launches=0).launches == 0


@pytest.mark.parametrize(
    ("values", "words"),
    [
        ({"launches": -1}, "at least 0"),
        ({"note_share": 0}, "more than 0"),
        ({"note_share": 1.5}, "at most 1"),
    ],
)
def test_launch_cost_settings_that_are_refused(values: dict[str, Any], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        LaunchCostSettings(**values)


def test_a_short_wall_median_gets_the_launch_cost_note() -> None:
    assert model.launch_cost_note(0.04, 0.0005) is True
    assert model.launch_cost_note(0.06, 0.0005) is False
    assert model.launch_cost_note(0.04, 0.0005, 0.01) is True
    assert model.launch_cost_note(0.06, 0.0005, 0.01) is False


def test_the_note_follows_the_share() -> None:
    assert model.launch_cost_note(0.06, 0.0005, 0.005) is True
    assert model.launch_cost_note(0.04, 0.0005, 0.1) is False
    for share in (0.0, -0.01, 1.5):
        with pytest.raises(ValueError, match="note_share lies above 0"):
            model.launch_cost_note(0.04, 0.0005, share)


def test_the_cost_is_measured_through_a_command_or_python_environment_side() -> None:
    assert model.LAUNCH_COST_KINDS == ("cmd", "python", "venv", "conda")
    image = Side(name="new", kind="image")
    command = Side(name="old", kind="cmd", role="baseline")
    venv = Side(name="other", kind="venv")
    assert model.launch_cost_side((image, image.twin(), command, command.twin())) == command
    assert model.launch_cost_side((venv, command)) == venv
    assert model.launch_cost_side((image, Side(name="old", kind="image"))) is None
    assert model.launch_cost_side((Side(name="new", kind="serve"),)) is None
    assert model.launch_cost_side((command.twin(), command.control())) is None


def test_an_analysis_reads_the_share_from_the_recorded_config() -> None:
    def capture(config: dict[str, Any]) -> Capture:
        return Capture(
            capture_id="cap-000001", header=Header(capture_id="cap-000001", config=config)
        )

    assert capture({}).launch_cost_share() == 0.01
    assert capture({"launch_cost": {"note_share": 0.05}}).launch_cost_share() == 0.05
    assert capture({"launch_cost": {"note_share": "wide"}}).launch_cost_share() == 0.01
    assert capture({"launch_cost": {"note_share": 0}}).launch_cost_share() == 0.01


def test_the_phases_of_a_launch_that_is_no_record_of_a_capture() -> None:
    assert api.LaunchPhase.__args__ == ("warmup", "round", "profile", "explain", "cost")  # type: ignore[attr-defined]
    assert model.Phase.__args__ == ("warmup", "round")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The size of the environment
# ---------------------------------------------------------------------------


def test_the_pad_length_of_a_round_follows_from_the_seed_and_the_round() -> None:
    assert [model.env_pad_length(1234, r) for r in (1, 2, 3, 4)] == [484, 3332, 3683, 3641]
    assert [model.env_pad_length(7, r) for r in (1, 2, 3)] == [3177, 2343, 4063]
    assert model.env_pad_length(1234, 1) == model.env_pad_length(1234, 1)


def test_a_pad_length_lies_from_zero_to_the_largest_pad() -> None:
    assert model.ENV_PAD_MAX == 4096
    lengths = [model.env_pad_length(1234, r) for r in range(1, 501)]
    assert min(lengths) >= 0
    assert max(lengths) <= 4096
    assert len(set(lengths)) > 400


def test_the_pad_length_refuses_what_makes_no_sense() -> None:
    with pytest.raises(ValueError, match="rounds are numbered from 1"):
        model.env_pad_length(1234, 0)
    with pytest.raises(ValueError, match="a seed is a whole number"):
        model.env_pad_length("1234", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="a seed is a whole number"):
        model.env_pad_length(True, 1)


def test_the_variable_that_pads_the_environment() -> None:
    assert api.ENV_PAD_VARIABLE == "PAIRBENCH_ENV_PAD"
    assert api.env_pad(3) == {"PAIRBENCH_ENV_PAD": "xxx"}
    assert api.env_pad(0) == {"PAIRBENCH_ENV_PAD": ""}
    assert len(api.env_pad(4096)["PAIRBENCH_ENV_PAD"]) == 4096
    for length in (-1, 4097, 1.5, True):
        with pytest.raises(ValueError, match="a pad length lies from 0 to 4096"):
            api.env_pad(length)  # type: ignore[arg-type]


def test_the_setting_is_off_by_default_and_has_a_flag_and_a_key(
    example_config: dict[str, Any],
) -> None:
    assert model.RunSettings().vary_env_size is False
    assert model.FLAG_KEYS["--vary-env-size"] == "run.vary_env_size"
    example_config["run"]["vary_env_size"] = True
    experiment = Experiment.from_json(example_config)
    assert experiment.run.vary_env_size is True
    assert experiment.to_json()["run"]["vary_env_size"] is True


def test_a_launch_record_carries_the_pad_length_when_the_size_is_varied() -> None:
    launch = Launch(seq=1, phase="round", round=1, pos=1, name="new", env_pad=484)
    assert launch.to_json()["env_pad"] == 484
    assert Launch.from_json(launch.to_json()) == launch
    assert Launch(seq=1, phase="warmup", round=0, pos=None, name="new", env_pad=0).env_pad == 0
    for length in (-1, 4097):
        with pytest.raises(ValueError, match=r"Launch\.env_pad: expected at"):
            Launch(seq=1, phase="round", round=1, pos=1, name="new", env_pad=length)


def test_the_seed_of_the_pad_has_a_key_in_the_seeds_of_a_header() -> None:
    assert (model.SEED_DRIVER, model.SEED_ENV_PAD) == ("driver", "env_pad")
    header = Header(capture_id="cap-000001", seeds={"driver": 1234, "env_pad": 1234})
    assert Header.from_json(header.to_json()).seeds == {"driver": 1234, "env_pad": 1234}


def test_what_the_results_record_about_the_environment_size() -> None:
    assert EnvPad.of(False) == EnvPad(varied=False, min=None, max=None)
    assert EnvPad.of(True) == EnvPad(varied=True, min=0, max=4096)
    assert EnvPad.from_json({"varied": False}) == EnvPad()
    assert EnvPad.of(True).to_json() == {"varied": True, "min": 0, "max": 4096}

    def capture(*pads: int | None) -> Capture:
        launches = tuple(
            Launch(seq=i, phase="round", round=i, pos=1, name="new", env_pad=pad)
            for i, pad in enumerate(pads, start=1)
        )
        return Capture(
            capture_id="cap-000001", header=Header(capture_id="cap-000001"), launches=launches
        )

    assert capture(None, None).env_pad() == EnvPad.of(False)
    assert capture(484, 3332).env_pad() == EnvPad.of(True)
    warm_up_only = Capture(
        capture_id="cap-000001",
        header=Header(capture_id="cap-000001"),
        launches=(Launch(seq=1, phase="warmup", round=0, pos=None, name="new", env_pad=0),),
    )
    assert warm_up_only.env_pad() == EnvPad.of(False)


def test_the_pad_is_no_part_of_a_fingerprint() -> None:
    settings = LaunchSettings(env={"A": "1"})
    effective = settings.effective(args=["--fast"])
    assert "PAIRBENCH_ENV_PAD" not in effective["env"]
    assert "PAIRBENCH_WORK_FACTOR" not in effective["env"]
    identity = {"executable_sha256": "ab" * 32}
    plain = model.fingerprint_of(identity, effective)
    assert plain == model.fingerprint_of(identity, settings.effective(args=["--fast"]))
    padded = LaunchSettings(env={"A": "1", **api.env_pad(3)}).effective(args=["--fast"])
    assert model.fingerprint_of(identity, padded) != plain


# ---------------------------------------------------------------------------
# Where the tool itself runs
# ---------------------------------------------------------------------------

MACHINE = {
    "t": "machine",
    "os": "Linux 0.0",
    "arch": "arch-a",
    "cpu": {"model": "cpu-model-a", "identity": [], "cache_domains": []},
    "gpu": [],
    "engine": None,
    "in_container": False,
    "ci": False,
    "node_type": None,
}


def test_the_machine_record_says_which_cpus_the_tool_moved_to() -> None:
    assert MachineRecord.from_json(MACHINE).tool_cpus is None
    moved = MachineRecord.from_json({**MACHINE, "tool_cpus": "0-3"})
    assert moved.tool_cpus == "0-3"
    assert moved.to_json()["tool_cpus"] == "0-3"
    assert MachineRecord.from_json(MACHINE).to_json()["tool_cpus"] is None
    with pytest.raises(Refusal, match=r"MachineRecord\.tool_cpus: expected a text that matches"):
        MachineRecord.from_json({**MACHINE, "tool_cpus": "some"})


def test_the_machine_facts_a_results_document_shows_hold_no_cpu_list() -> None:
    summary = MachineRecord.from_json({**MACHINE, "tool_cpus": "0-3"}).summary()
    assert "tool_cpus" not in summary.to_json()


def test_the_machine_checks_move_the_tool_off_the_pinned_cpus() -> None:
    move = inspect.signature(api.MachineChecks.leave_pinned)
    assert [(p.name, p.annotation) for p in move.parameters.values()] == [
        ("self", inspect.Parameter.empty),
        ("cpus", "str | None"),
    ]
    assert move.return_annotation == "ToolCpus"
    assert api.ToolCpus(cpus="0-3") == api.ToolCpus(cpus="0-3", reason=None)
    assert api.ToolCpus(reason="none_left").cpus is None
    for neither_or_both in ({}, {"cpus": "0-3", "reason": "none_left"}):
        with pytest.raises(ValueError, match="either moved to a CPU list or says why"):
            api.ToolCpus(**neither_or_both)  # type: ignore[arg-type]
    assert api.NotMoved.__args__ == ("not_pinned", "none_left", "unsupported")  # type: ignore[attr-defined]
    assert model.NOTE_TOOL_ON_PINNED_CPUS == "tool_on_pinned_cpus"


def test_a_median_equal_to_the_bound_gets_no_note() -> None:
    # A cost of 0.5 at a share of 0.125 bounds the note at exactly 4.0.
    assert model.launch_cost_note(4.0, 0.5, 0.125) is False
    assert model.launch_cost_note(3.5, 0.5, 0.125) is True
    assert model.launch_cost_note(4.5, 0.5, 0.125) is False
