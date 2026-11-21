# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The positive control: the entry, where it runs, how its values are made and judged."""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import Refusal
from pairbench.model import (
    Capture,
    ControlSettings,
    Experiment,
    Header,
    Launch,
    Lineup,
    Plan,
    PlanRow,
    Results,
    Side,
)


def _sides(kind: str = "cmd") -> tuple[Side, Side]:
    return (Side(name="new", kind=kind), Side(name="old", kind=kind))


def _experiment(**changes: Any) -> Experiment:
    return Experiment(sides=_sides(), **changes)


def _plan(experiment: Experiment, rounds: int) -> Plan:
    lineup = experiment.lineup()
    control = experiment.control()
    rows = model.plan_rows(lineup, rounds, control)
    return Plan(
        rows=rows,
        rounds_requested=rounds,
        rounds_planned=rounds,
        lineup=tuple(s.name for s in lineup),
        balance=model.count_balance(rows, model.compared_pairs(lineup)),
        launches=model.planned_launches(
            entries=len(lineup),
            rounds=rounds,
            sides=len(experiment.sides),
            warmups=experiment.run.warmups,
            control=control is not None,
        ),
        explain_launches=experiment.explain_launches(),
        control=None if control is None else control.name,
    )


def _sample(case: str, value: float, better: str = "lower", **changes: Any) -> api.Sample:
    fields: dict[str, Any] = {
        "case": case,
        "metric": "time",
        "unit": "s",
        "better": better,
        "kind": "time",
        "value": value,
    }
    fields.update(changes)
    return api.Sample(**fields)


# ---------------------------------------------------------------------------
# The entry
# ---------------------------------------------------------------------------


def test_the_reserved_suffix_of_the_control() -> None:
    assert model.CONTROL_SUFFIX == "~twice"
    assert model.TWIN_SUFFIX == "~same"


def test_the_control_is_a_copy_of_the_baseline_that_declares_what_it_controls() -> None:
    baseline = Side.command("old", ["made-up-workload"]).with_role("baseline")
    baseline = baseline.with_identity({"executable_sha256": "ab" * 32}, "cd" * 32)
    control = baseline.control()
    assert (control.name, control.role, control.control_of, control.twin_of) == (
        "old~twice",
        "control",
        "old",
        None,
    )
    assert (control.kind, control.spec, control.identity, control.fingerprint) == (
        baseline.kind,
        baseline.spec,
        baseline.identity,
        baseline.fingerprint,
    )
    assert control.source == "old"
    assert baseline.source == "old"
    assert baseline.twin().source == "old"


def test_only_the_baseline_has_a_control_and_a_control_has_no_twin() -> None:
    subject = Side(name="new", kind="cmd")
    with pytest.raises(Refusal, match="'new' is not the baseline") as caught:
        subject.control()
    assert caught.value.code == "E_USAGE"
    control = Side(name="old", kind="cmd", role="baseline").control()
    with pytest.raises(Refusal, match="is the positive control and cannot have a twin"):
        control.twin()
    with pytest.raises(Refusal, match="is not the baseline"):
        control.control()


def test_the_control_relation_is_the_declared_field_and_never_a_name() -> None:
    declared = Side(name="made-up-entry", kind="cmd", role="control", control_of="old")
    assert declared.control_of == "old"
    with pytest.raises(Refusal) as by_name:
        Side(name="old~twice", kind="cmd")
    assert by_name.value.code == "E_USAGE"
    with pytest.raises(Refusal, match="a control, and only a control, names control_of"):
        Side(name="old", kind="cmd", role="control")
    with pytest.raises(Refusal, match="a control, and only a control, names control_of"):
        Side(name="old", kind="cmd", control_of="old")


def test_the_side_record_names_what_a_control_controls() -> None:
    control = Side(name="old", kind="cmd", role="baseline").control()
    record = control.to_json()
    assert list(record) == [
        "t",
        "name",
        "kind",
        "role",
        "twin_of",
        "control_of",
        "spec",
        "identity",
        "fingerprint",
        "workdir_sha256",
    ]
    assert (record["role"], record["control_of"], record["twin_of"]) == ("control", "old", None)
    assert Side.from_json(record) == control
    without = {k: v for k, v in Side(name="old", kind="cmd").to_json().items() if k != "control_of"}
    assert Side.from_json(without).control_of is None


def test_a_control_is_never_declared_as_a_side_of_an_experiment() -> None:
    control = Side(name="old", kind="cmd", role="baseline").control()
    with pytest.raises(Refusal, match="the positive control is never declared as a side"):
        Experiment(sides=(Side(name="new", kind="cmd"), control))


def test_the_control_gets_the_launch_settings_of_the_baseline() -> None:
    settings = model.LaunchSettings(cpus="0-3", overrides={"old": {"cpus": "4-7"}})
    baseline = Side(name="old", kind="cmd", role="baseline")
    assert settings.for_side(baseline.control()).cpus == "4-7"
    assert settings.for_side(Side(name="new", kind="cmd")).cpus == "0-3"


# ---------------------------------------------------------------------------
# The settings
# ---------------------------------------------------------------------------


def test_the_defaults_of_the_control_settings() -> None:
    assert ControlSettings() == ControlSettings(
        positive=None, positive_tolerance=0.10, positive_via="repeat"
    )
    assert _experiment().controls == ControlSettings()


def test_the_control_is_on_by_default_except_for_serving_sides() -> None:
    assert _experiment().positive_control is True
    serving = Experiment(sides=_sides("serve"))
    assert serving.is_serving is True
    assert serving.positive_control is False
    assert serving.control() is None


def test_the_setting_overrides_the_default_either_way() -> None:
    off = _experiment(controls=ControlSettings(positive="off"))
    assert (off.positive_control, off.control()) == (False, None)
    serving = Experiment(sides=_sides("serve"), controls=ControlSettings(positive="on"))
    control = serving.control()
    assert control is not None
    assert (control.name, control.control_of) == ("old~twice", "old")


def test_sides_that_are_result_files_have_no_control() -> None:
    files = Experiment(sides=_sides("file"), controls=ControlSettings(positive="on"))
    assert (files.positive_control, files.control()) == (False, None)


def test_the_control_needs_no_twins() -> None:
    experiment = _experiment(run=model.RunSettings(same_vs_same="off"))
    control = experiment.control()
    assert [s.name for s in experiment.lineup()] == ["new", "old"]
    assert control is not None
    assert control.name == "old~twice"


@pytest.mark.parametrize(
    ("values", "words"),
    [
        ({"positive": "sometimes"}, "one of 'on', 'off'"),
        ({"positive": True}, "one of 'on', 'off'"),
        ({"positive_via": "sum"}, "one of 'repeat', 'factor'"),
        ({"positive_tolerance": -0.1}, "at least 0"),
    ],
)
def test_control_settings_that_are_refused(values: dict[str, Any], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        ControlSettings(**values)


def test_the_control_settings_are_read_from_and_written_to_the_config(
    example_config: dict[str, Any],
) -> None:
    assert Experiment.from_json(example_config).controls == ControlSettings()
    example_config["controls"] = {
        "positive": "off",
        "positive_tolerance": 0.25,
        "positive_via": "factor",
    }
    experiment = Experiment.from_json(example_config)
    assert experiment.controls == ControlSettings(
        positive="off", positive_tolerance=0.25, positive_via="factor"
    )
    assert experiment.to_json()["controls"] == example_config["controls"]
    default = Experiment.from_json({"sides": example_config["sides"]}).to_json()["controls"]
    assert default == {"positive_tolerance": 0.1, "positive_via": "repeat"}


@pytest.mark.parametrize(
    ("table", "words"),
    [
        ({"positive": True}, "controls.positive must be one of on, off"),
        ({"positive_via": "sum"}, "controls.positive_via must be one of repeat, factor"),
        ({"positive_tolerance": -1}, "controls.positive_tolerance: expected at least 0"),
        ({"made_up": 1}, "unknown config key: controls.made_up"),
    ],
)
def test_a_bad_control_setting_in_a_config_is_refused(
    example_config: dict[str, Any], table: dict[str, Any], words: str
) -> None:
    example_config["controls"] = table
    with pytest.raises(Refusal, match=words) as caught:
        Experiment.from_json(example_config)
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)


# ---------------------------------------------------------------------------
# Where it runs
# ---------------------------------------------------------------------------


def test_the_control_is_no_part_of_the_lineup() -> None:
    experiment = _experiment()
    assert [s.name for s in experiment.lineup()] == ["new", "new~same", "old", "old~same"]
    assert all(s.role != "control" for s in experiment.lineup())


def test_the_control_runs_last_in_every_round_at_the_position_past_the_lineup() -> None:
    experiment = _experiment()
    rows = model.plan_rows(experiment.lineup(), 2, experiment.control())
    assert rows == (
        PlanRow(round=1, pos=1, name="new", side="new", twin_of=None),
        PlanRow(round=1, pos=2, name="new~same", side="new", twin_of="new"),
        PlanRow(round=1, pos=3, name="old", side="old", twin_of=None),
        PlanRow(round=1, pos=4, name="old~same", side="old", twin_of="old"),
        PlanRow(round=1, pos=5, name="old~twice", side="old", twin_of=None),
        PlanRow(round=2, pos=1, name="new~same", side="new", twin_of="new"),
        PlanRow(round=2, pos=2, name="old", side="old", twin_of=None),
        PlanRow(round=2, pos=3, name="old~same", side="old", twin_of="old"),
        PlanRow(round=2, pos=4, name="new", side="new", twin_of=None),
        PlanRow(round=2, pos=5, name="old~twice", side="old", twin_of=None),
    )


def test_the_rows_of_the_lineup_are_the_same_with_the_control_and_without() -> None:
    experiment = _experiment()
    with_control = model.plan_rows(experiment.lineup(), 16, experiment.control())
    without = model.plan_rows(experiment.lineup(), 16)
    assert tuple(row for row in with_control if row.name != "old~twice") == without
    assert len(with_control) == 80
    assert len(without) == 64


def test_the_plan_of_two_sides_with_twins_and_the_control() -> None:
    plan = _plan(_experiment(), 16)
    control_rows = [row for row in plan.rows if row.name == "old~twice"]
    assert [row.round for row in control_rows] == list(range(1, 17))
    assert {row.pos for row in control_rows} == {5}
    assert {(row.side, row.twin_of) for row in control_rows} == {("old", None)}
    assert plan.lineup == ("new", "new~same", "old", "old~same")
    assert plan.control == "old~twice"
    assert plan.launches == 82
    assert plan.explain_launches == 4
    assert plan.is_balanced() is True


@pytest.mark.parametrize("rounds", [8, 16, 24])
def test_the_balanced_counts_are_the_same_with_the_control(rounds: int) -> None:
    plan = _plan(_experiment(), rounds)
    half = rounds // 2
    assert [(p.a, p.b, p.a_first, p.b_first, p.position_sum) for p in plan.balance] == [
        ("new", "old", half, half, 0),
        ("new", "new~same", half, half, 0),
        ("old", "old~same", half, half, 0),
    ]
    assert plan.is_balanced() is True
    without = _plan(_experiment(controls=ControlSettings(positive="off")), rounds)
    assert plan.balance == without.balance
    assert plan.balanced_step() == 8
    assert without.balanced_step() == 8


@pytest.mark.parametrize(("rounds", "first", "second"), [(12, 7, 5), (20, 11, 9)])
def test_the_uneven_counts_are_the_same_with_the_control(
    rounds: int, first: int, second: int
) -> None:
    plan = _plan(_experiment(), rounds)
    by_pair = {(p.a, p.b): (p.a_first, p.b_first) for p in plan.balance}
    assert by_pair[("new", "old")] == (rounds // 2, rounds // 2)
    assert by_pair[("new", "new~same")] == (first, second)
    assert plan.is_balanced() is False


def test_the_automatic_round_count_is_sixteen_with_the_control() -> None:
    # The smallest balanced count that is at least min_rounds(1) + 4, which is 10.
    assert model.min_rounds(1) + 4 == 10
    balanced = [rounds for rounds in range(10, 25) if _plan(_experiment(), rounds).is_balanced()]
    assert balanced[0] == 16


def test_the_control_is_not_one_of_a_compared_pair() -> None:
    experiment = _experiment()
    control = experiment.control()
    assert control is not None
    entries = (*experiment.lineup(), control)
    assert model.compared_pairs(entries) == (
        ("new", "old"),
        ("new", "new~same"),
        ("old", "old~same"),
    )


@pytest.mark.parametrize(
    ("counts", "launches"),
    [
        ({"entries": 4, "rounds": 16, "sides": 2, "warmups": 1, "control": True}, 82),
        ({"entries": 4, "rounds": 16, "sides": 2, "warmups": 1, "control": False}, 66),
        ({"entries": 4, "rounds": 8, "sides": 2, "warmups": 0, "control": True}, 40),
        ({"entries": 2, "rounds": 8, "sides": 2, "warmups": 2, "control": False}, 20),
    ],
)
def test_the_launches_a_plan_counts(counts: dict[str, Any], launches: int) -> None:
    assert model.planned_launches(**counts) == launches


def test_the_plan_table_ends_every_round_with_the_row_of_the_control() -> None:
    plan = _plan(_experiment(), 1)
    assert plan.to_tsv() == (
        "round\tpos\tname\tside\ttwin_of\n"
        "1\t1\tnew\tnew\t\n"
        "1\t2\tnew~same\tnew\tnew\n"
        "1\t3\told\told\t\n"
        "1\t4\told~same\told\told\n"
        "1\t5\told~twice\told\t\n"
    )


def test_rows_are_laid_out_only_for_a_control_that_is_outside_the_lineup() -> None:
    experiment = _experiment()
    control = experiment.control()
    assert control is not None
    with pytest.raises(ValueError, match="is not a positive control"):
        model.plan_rows(experiment.lineup(), 1, experiment.sides[0])
    with pytest.raises(ValueError, match="no part of the lineup"):
        model.plan_rows((*experiment.lineup(), control), 1, control)


# ---------------------------------------------------------------------------
# The capture
# ---------------------------------------------------------------------------


def test_the_lineup_record_names_the_control_beside_its_names() -> None:
    lineup = Lineup(names=("new", "old"), control="old~twice", rounds=8)
    record = lineup.to_json()
    assert list(record)[:4] == ["t", "names", "control", "rounds"]
    assert (record["names"], record["control"]) == (["new", "old"], "old~twice")
    assert Lineup.from_json(record) == lineup
    assert Lineup(names=("new", "old"), rounds=8).to_json()["control"] is None
    without = {k: v for k, v in record.items() if k != "control"}
    assert Lineup.from_json(without).control is None
    with pytest.raises(ValueError, match="no part of the lineup's names"):
        Lineup(names=("new", "old~twice"), control="old~twice", rounds=8)


def test_a_launch_record_says_how_many_runs_it_held() -> None:
    launch = Launch(seq=5, phase="round", round=1, pos=5, name="old~twice", runs=2)
    assert launch.to_json()["runs"] == 2
    assert Launch.from_json(launch.to_json()) == launch
    plain = Launch(seq=1, phase="round", round=1, pos=1, name="new")
    assert (plain.runs, plain.env_pad) == (1, None)
    without = {k: v for k, v in plain.to_json().items() if k not in ("runs", "env_pad")}
    assert Launch.from_json(without) == plain
    for runs in (0, 3):
        with pytest.raises(ValueError, match=r"Launch\.runs: expected at"):
            Launch(seq=1, phase="round", round=1, pos=1, name="new", runs=runs)


def test_the_records_of_a_run_with_the_control_validate_and_are_read(
    example_capture_records: list[dict[str, Any]],
    example_capture_run_records: list[dict[str, Any]],
) -> None:
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    from pairbench.results import load_schema

    validator = jsonschema.Draft202012Validator(load_schema("capture"))
    assert [record["t"] for record in example_capture_run_records] == [
        "machine",
        "side",
        "launch_cost",
        "launch",
        "obs",
    ]
    for record in example_capture_run_records:
        assert list(validator.iter_errors(record)) == [], record["t"]
    records = [example_capture_records[0], *example_capture_run_records]
    capture = Capture.from_records(records)
    assert capture.control is not None
    assert (capture.control.name, capture.control.control_of) == ("old~twice", "old")
    assert capture.machine is not None
    assert capture.machine.tool_cpus == "0-3"
    assert capture.launches[0].runs == 2
    assert capture.launches[0].pos == 5
    assert capture.launch_cost is not None
    assert capture.launch_cost.median_s == 0.0005
    assert Capture.from_records(capture.to_records()) == capture


def test_a_capture_without_a_control_entry_has_none() -> None:
    capture = Capture.from_rows(
        [(1, "new", "matmul", 1.5), (1, "old", "matmul", 3.0)], sides=["new", "old"]
    )
    assert capture.control is None
    assert capture.lineup is not None
    assert capture.lineup.control is None


def test_an_analysis_reads_the_control_settings_from_the_recorded_config() -> None:
    def capture(config: dict[str, Any]) -> Capture:
        return Capture(
            capture_id="cap-000001", header=Header(capture_id="cap-000001", config=config)
        )

    assert capture({}).control_settings() == ControlSettings()
    recorded = capture({"controls": {"positive_tolerance": 0.25, "positive_via": "factor"}})
    assert recorded.control_settings() == ControlSettings(
        positive_tolerance=0.25, positive_via="factor"
    )
    assert capture({"controls": {"positive": "off"}}).control_settings().positive == "off"
    broken = capture({"controls": {"positive_tolerance": "wide", "positive_via": "factor"}})
    assert broken.control_settings() == ControlSettings(positive_via="factor")
    assert capture({"controls": "made-up"}).control_settings() == ControlSettings()


# ---------------------------------------------------------------------------
# The values of one launch that holds two runs
# ---------------------------------------------------------------------------


def test_three_and_five_give_eight_where_lower_is_better() -> None:
    assert model.combine_control(3, 5, "lower") == 8


def test_rates_three_and_six_give_two_where_higher_is_better() -> None:
    assert model.combine_control(3, 6, "higher") == 2


def test_a_case_that_describes_is_not_recorded_for_the_control() -> None:
    assert model.combine_control(3, 5, "none") is None


def test_a_rate_of_zero_or_less_on_either_run_gives_zero() -> None:
    assert model.combine_control(0, 6, "higher") == 0.0
    assert model.combine_control(3, -1, "higher") == 0.0
    assert model.combine_control(0, 5, "lower") == 5
    with pytest.raises(ValueError, match="better is one of"):
        model.combine_control(3, 5, "made_up")


def test_the_cases_of_two_runs_are_combined_case_by_case() -> None:
    first = [
        _sample("matmul", 3.0),
        _sample("rate", 3.0, "higher", kind="rate"),
        _sample("made-up-count", 4.0, "none", kind="count"),
        _sample("only-first", 1.0),
    ]
    second = [
        _sample("rate", 6.0, "higher", kind="rate"),
        _sample("matmul", 5.0),
        _sample("made-up-count", 4.0, "none", kind="count"),
        _sample("only-second", 1.0),
    ]
    combined = api.combine_runs(first, second)
    assert [(s.case, s.value, s.n_inner, s.reducer) for s in combined] == [
        ("matmul", 8.0, 2, "two_runs"),
        ("rate", 2.0, 2, "two_runs"),
    ]
    assert api.REDUCER_TWO_RUNS == "two_runs"


def test_a_time_the_tool_measures_is_the_one_interval_around_both_runs() -> None:
    # Two runs of 3 and 5 units in one clock interval: both reads see the interval, 8.
    first = [_sample("wall", 8.0), _sample("matmul", 3.0)]
    second = [_sample("wall", 8.0), _sample("matmul", 5.0)]
    combined = api.combine_runs(first, second, clock=("wall", "launch"))
    assert [(s.case, s.value, s.reducer) for s in combined] == [
        ("wall", 8.0, "identity"),
        ("matmul", 8.0, "two_runs"),
    ]
    assert len([s for s in combined if s.case == "wall"]) == 1


def test_a_driver_says_which_cases_it_reads_from_the_clock() -> None:
    class ClockDriver:
        clock_cases = ("wall", "launch")

    class PlainDriver:
        pass

    assert api.clock_cases(ClockDriver()) == ("wall", "launch")
    assert api.clock_cases(PlainDriver()) == ()
    assert isinstance(ClockDriver(), api.ReadsLaunchClock)
    assert not isinstance(PlainDriver(), api.ReadsLaunchClock)
    assert not hasattr(api.Driver, "clock_cases")


# ---------------------------------------------------------------------------
# The seam: one start, two runs
# ---------------------------------------------------------------------------


def test_a_launch_request_can_carry_a_second_prepared_command(tmp_path: Path) -> None:
    request = api.LaunchRequest(
        run_id="run-a",
        seq=5,
        phase="round",
        round=1,
        pos=5,
        name="old~twice",
        artifacts=tmp_path,
        argv=("made-up-workload", "--out", "run1"),
        second=api.PreparedRun(argv=("made-up-workload", "--out", "run2"), env={"A": "1"}),
    )
    assert request.second is not None
    assert request.second.argv == ("made-up-workload", "--out", "run2")
    assert request.second.env == {"A": "1"}
    assert [f.name for f in dataclasses.fields(api.PreparedRun)] == ["argv", "env"]
    plain = dataclasses.replace(request, second=None)
    assert plain.second is None
    assert api.RUN_FOLDERS == ("run1", "run2")


def test_a_side_says_before_any_launch_whether_it_can_run_two_commands_in_one_start() -> None:
    member = vars(api.ResolvedSide)["cannot_repeat"]
    assert isinstance(member, property)
    assert inspect.signature(member.fget).return_annotation == "str | None"
    text = " ".join((api.ResolvedSide.__doc__ or "").split())
    assert "it never runs the two commands as two launches" in text
    assert "known before the first measured launch" in text


def test_a_launch_of_two_processes_tells_both_to_the_witness() -> None:
    outcome = api.LaunchOutcome(rc=0, pid=4242, second_pid=4343)
    assert (outcome.pid, outcome.second_pid) == (4242, 4343)
    assert api.LaunchOutcome(rc=0).second_pid is None
    stop = inspect.signature(api.WitnessSampler.stop)
    assert stop.parameters["second_pid"].default is None


def test_the_work_factor_of_the_control_under_factor() -> None:
    assert api.WORK_FACTOR_VARIABLE == "PAIRBENCH_WORK_FACTOR"
    assert api.work_factor_env() == {"PAIRBENCH_WORK_FACTOR": "2"}


# ---------------------------------------------------------------------------
# How it is judged, and what the results record
# ---------------------------------------------------------------------------


def test_the_ratio_twice_the_work_must_read() -> None:
    assert model.control_expected("lower") == 2.0
    assert model.control_expected("higher") == 0.5
    assert model.control_expected("none") is None
    assert dict(model.CONTROL_EXPECTED) == {"lower": 2.0, "higher": 0.5}
    with pytest.raises(ValueError, match="better is one of"):
        model.control_expected("made_up")


@pytest.mark.parametrize(
    ("ratio", "expected", "inside"),
    [
        (2.0, 2.0, True),
        (1.8, 2.0, True),
        (2.2, 2.0, True),
        (1.79, 2.0, False),
        (2.21, 2.0, False),
        (1.5, 2.0, False),
        (1.0, 2.0, False),
        (0.5, 0.5, True),
        (0.45, 0.5, True),
        (0.55, 0.5, True),
        (0.44, 0.5, False),
        (0.56, 0.5, False),
        (1.0, 0.5, False),
    ],
)
def test_a_ratio_within_the_default_tolerance(ratio: float, expected: float, inside: bool) -> None:
    assert model.control_within(ratio, expected, 0.10) is inside


def test_the_tolerance_is_a_fraction_of_the_expected_value() -> None:
    assert model.control_within(1.5, 2.0, 0.25) is True
    assert model.control_within(1.49, 2.0, 0.25) is False
    assert model.control_within(2.0, 2.0, 0.0) is True
    assert model.control_within(2.01, 2.0, 0.0) is False
    with pytest.raises(ValueError, match="a tolerance is zero or more"):
        model.control_within(2.0, 2.0, -0.1)


def test_the_results_record_what_the_control_read(example_results: dict[str, Any]) -> None:
    results = Results.from_json(example_results)
    positive = results.controls.positive
    assert (positive.status, positive.entry, positive.via, positive.tolerance) == (
        "ok",
        "old~twice",
        "repeat",
        0.1,
    )
    assert positive.cases == (
        model.ControlCase(
            case="matmul", expected=2.0, ratio=2.01, p_raw=0.00003, n_rounds=16, passed=True
        ),
    )
    assert results.to_json()["controls"] == example_results["controls"]


def test_a_control_that_did_not_run_is_recorded_as_not_run(
    example_results_required_only: dict[str, Any],
) -> None:
    results = Results.from_json(example_results_required_only)
    assert results.controls == model.Controls()
    assert results.controls.positive == model.PositiveControl(
        status="not_run", entry=None, via="repeat", tolerance=0.10, cases=()
    )
    assert results.to_json()["controls"] == {
        "positive": {
            "status": "not_run",
            "entry": None,
            "via": "repeat",
            "tolerance": 0.1,
            "cases": [],
        }
    }


def test_the_states_of_the_control() -> None:
    assert model.CONTROL_STATUSES == ("ok", "failed", "not_run")
    with pytest.raises(ValueError, match="one of 'ok', 'failed', 'not_run'"):
        model.PositiveControl(status="skipped")  # type: ignore[arg-type]


def test_a_failed_control_is_the_first_reason_of_no_verdict() -> None:
    assert model.REASONS_NO_VERDICT[0] == "positive_control_failed"
    assert "positive_control_failed" in model.REASONS
    assert model.NOTE_CONTROL_FAILED == "positive_control_failed"
    assert model.NOTE_CONTROL_NOT_JUDGED == "positive_control_not_judged"
    assert model.NOTE_CONTROL_CANNOT_REPEAT == "positive_control_cannot_repeat"


def test_the_control_of_a_capture_is_told_by_its_role_and_not_by_its_name() -> None:
    declared = Side(name="made-up-entry", kind="cmd", role="control", control_of="old")
    named_like_one = Side(name="old~twice", kind="cmd", role="twin", twin_of="old")
    header = Header(capture_id="cap-000001")
    by_role = Capture(capture_id="cap-000001", header=header, sides=(named_like_one, declared))
    assert by_role.control == declared
    by_name_only = Capture(capture_id="cap-000001", header=header, sides=(named_like_one,))
    assert by_name_only.control is None


def test_the_cases_of_the_control_under_factor_are_taken_as_reported() -> None:
    read = [
        _sample("matmul", 6.0),
        _sample("rate", 1.5, "higher", kind="rate"),
        _sample("made-up-count", 4.0, "none", kind="count"),
    ]
    kept = api.control_samples(read)
    assert kept == read[:2]
    assert [(s.case, s.value, s.reducer) for s in kept] == [
        ("matmul", 6.0, "identity"),
        ("rate", 1.5, "identity"),
    ]
    assert api.control_samples([]) == []
