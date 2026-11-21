# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Where two parts of the package meet: one meaning for what passes between them."""

from __future__ import annotations

import copy
import inspect
import itertools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, model
from pairbench.errors import Refusal
from pairbench.model import (
    Artifacts,
    ControlCase,
    ControlSettings,
    DiagnosticsState,
    EnvPad,
    Experiment,
    LaunchCost,
    Lineup,
    Note,
    PlotsState,
    PositiveControl,
    Results,
    ResultsSide,
    Series,
    Side,
)
from pairbench.results import load_schema


def _errors(name: str, document: Any) -> list[str]:
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    validator = jsonschema.Draft202012Validator(load_schema(name))
    return sorted(error.message for error in validator.iter_errors(document))


def _sample(case: str, value: float, better: str = "lower") -> api.Sample:
    return api.Sample(case=case, metric=case, unit="s", better=better, kind="other", value=value)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# A launch that holds two runs: where each run keeps what it wrote
# ---------------------------------------------------------------------------


def test_each_run_of_a_launch_has_a_folder_of_its_own_inside_a_container() -> None:
    first, second = api.run_folders(Path("/made/up/launch"), "/pairbench/artifacts")
    assert first == (Path("/made/up/launch/run1"), "/pairbench/artifacts/run1")
    assert second == (Path("/made/up/launch/run2"), "/pairbench/artifacts/run2")
    assert first[1] != second[1]


def test_each_run_of_a_launch_has_a_folder_of_its_own_on_the_host() -> None:
    first, second = api.run_folders(Path("/made/up/launch"), "/made/up/launch/")
    assert first == (Path("/made/up/launch/run1"), "/made/up/launch/run1")
    assert second == (Path("/made/up/launch/run2"), "/made/up/launch/run2")


def test_a_side_is_asked_for_the_folder_of_the_launch_and_never_for_a_folder_of_a_run() -> None:
    asked = " ".join((api.ResolvedSide.artifacts_in_side.__doc__ or "").split())
    assert "``LaunchRequest.artifacts``, and never a folder under it" in asked
    assert "whatever the folder on the host" in asked
    told = " ".join((api.DriverContext.__doc__ or "").split())
    assert "the pair ``run_folders`` gives for the run" in told
    run = " ".join((api.RunExperiment.__doc__ or "").split())
    assert "run_folders(artifacts, resolved.artifacts_in_side(artifacts))" in run


# ---------------------------------------------------------------------------
# What a side may report as the usage of a launch
# ---------------------------------------------------------------------------


def test_the_usage_of_a_launch_holds_only_the_keys_that_have_a_case() -> None:
    kept = api.LaunchOutcome(rc=0, usage={"rss_peak_bytes": 4096.0, "faults_minor": 3.0})
    assert dict(kept.usage) == {"rss_peak_bytes": 4096.0, "faults_minor": 3.0}
    with pytest.raises(ValueError, match=r"usage holds only the keys .*: got rss_peak"):
        api.LaunchOutcome(rc=0, usage={"rss_peak": 4096.0})


# ---------------------------------------------------------------------------
# The cases of two runs
# ---------------------------------------------------------------------------


def test_a_case_only_one_of_two_runs_gave_is_named_and_not_dropped_silently() -> None:
    first = [_sample("a", 3.0), _sample("b", 1.0), _sample("res/made-up", 1.0, "none")]
    second = [_sample("a", 5.0), _sample("c", 2.0)]
    assert [(s.case, s.value) for s in api.combine_runs(first, second)] == [("a", 8.0)]
    assert api.uncombined_cases(first, second) == ("b", "c")
    assert api.uncombined_cases(first[:1], second[:1]) == ()
    assert model.NOTE_CONTROL_CASE_MISSING == "positive_control_case_missing"
    stated = " ".join((api.RunExperiment.__doc__ or "").split())
    assert "``uncombined_cases``) is named once per run in a loud note" in stated


def test_the_cases_of_the_clock_are_a_list_of_case_ids() -> None:
    class Listed:
        clock_cases = ("wall", "launch")

    class OneText:
        clock_cases = "wall"

    class Numbers:
        clock_cases = (1, 2)

    assert api.clock_cases(Listed()) == ("wall", "launch")
    assert api.clock_cases(object()) == ()
    for wrong in (OneText(), Numbers()):
        with pytest.raises(TypeError, match="clock_cases is a list of case ids"):
            api.clock_cases(wrong)


# ---------------------------------------------------------------------------
# The profile command reaches both of its parts in one way
# ---------------------------------------------------------------------------


def test_every_tool_of_the_profile_command_is_called_in_one_way(tmp_path: Path) -> None:
    def record(
        run_dir: Path, *, tool: str, case: str | None = None, side: str | None = None
    ) -> None:
        return None

    wanted = inspect.signature(record)
    for part in sorted(set(api.PROFILE_TOOLS.values())):
        protocol = api.DELEGATES[part][2]
        call = inspect.signature(protocol.__call__)
        # The call the command makes binds against either part.
        call.bind(None, tmp_path, tool="made-up", case=None, side=None)
        call.bind(None, tmp_path, tool="made-up")
        for name, parameter in wanted.parameters.items():
            assert call.parameters[name].kind == parameter.kind
    profiles = inspect.signature(api.RecordProfiles.__call__).parameters
    assert profiles["case"].default is None
    assert profiles["tool"].default is inspect.Parameter.empty
    assert inspect.signature(api.RecordStacks.__call__).parameters["tool"].default == "perf"


# ---------------------------------------------------------------------------
# An interrupt after the first write of the results
# ---------------------------------------------------------------------------


def test_an_interrupt_turns_what_was_pending_into_interrupted(
    example_results: dict[str, Any],
) -> None:
    first = Results.from_json(example_results).pending()
    stopped = first.interrupted()
    assert stopped.diagnostics == DiagnosticsState(status="interrupted")
    assert stopped.plots == PlotsState(status="interrupted")
    assert model.second_write_changes(first, stopped) == ()
    assert _errors("results", stopped.to_json()) == []


def test_an_interrupt_keeps_the_state_of_a_step_that_had_finished(
    example_results: dict[str, Any],
) -> None:
    first = Results.from_json(example_results).pending()
    explained = first.finished(
        diagnostics=DiagnosticsState(status="written"), plots=PlotsState(status="pending")
    )
    stopped = explained.interrupted()
    assert stopped.diagnostics == DiagnosticsState(status="written")
    assert stopped.plots == PlotsState(status="interrupted")
    done = Results.from_json(example_results)
    assert done.interrupted() == done
    stated = " ".join((api.RunToEnd.__doc__ or "").split())
    assert "The results are then written once more" in stated
    assert "no report page is written after an interrupt" in stated


# ---------------------------------------------------------------------------
# The tolerance of the positive control
# ---------------------------------------------------------------------------


def test_a_tolerance_stays_below_the_one_that_lets_no_difference_pass() -> None:
    assert model.CONTROL_TOLERANCE_BELOW == 0.5
    assert ControlSettings(positive_tolerance=0.49).positive_tolerance == 0.49
    assert ControlSettings(positive_tolerance=0).positive_tolerance == 0
    for refused in (0.5, 1, 1.5, 100):
        with pytest.raises(ValueError, match=r"positive_tolerance: expected less than 0\.5"):
            ControlSettings(positive_tolerance=refused)
        with pytest.raises(ValueError, match=r"tolerance: expected less than 0\.5"):
            PositiveControl(tolerance=refused)
    # What the limit protects: a reading of no difference lies outside every allowed tolerance.
    assert model.control_within(1.0, 2.0, 0.49) is False
    assert model.control_within(1.0, 0.5, 0.49) is False
    assert model.control_within(1.0, 2.0, 0.5) is True


@pytest.mark.parametrize("tolerance", [0.5, 1, 2.5])
def test_a_config_with_a_tolerance_that_is_too_wide_fails_schema_and_model(
    example_config: dict[str, Any], tolerance: float
) -> None:
    example_config["controls"] = {"positive_tolerance": 0.49}
    assert _errors("config", example_config) == []
    assert Experiment.from_json(example_config).controls.positive_tolerance == 0.49
    example_config["controls"] = {"positive_tolerance": tolerance}
    assert _errors("config", example_config) != []
    with pytest.raises(Refusal) as caught:
        Experiment.from_json(example_config)
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)


# ---------------------------------------------------------------------------
# The environment pad
# ---------------------------------------------------------------------------


def test_the_pad_length_changes_from_every_round_to_the_next() -> None:
    # The draws of rounds 25 and 26 under the seed 7 are both 44: round 26 moves on.
    assert [model.env_pad_length(7, r) for r in (24, 25, 26, 27)] == [3287, 44, 3362, 1816]
    for seed in range(120):
        lengths = [model.env_pad_length(seed, r) for r in range(1, 61)]
        assert all(a != b for a, b in itertools.pairwise(lengths)), seed
        assert all(0 <= length <= 4096 for length in lengths)


@pytest.mark.parametrize("round", [1.5, True, "1"])
def test_a_round_of_a_pad_length_is_a_whole_number(round: Any) -> None:
    with pytest.raises(ValueError, match="a round is a whole number"):
        model.env_pad_length(1234, round)


# ---------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------


def test_two_names_never_share_a_file_name() -> None:
    assert model.file_names(["c32/ttft", "c32_ttft", "c32 ttft", "plain"]) == {
        "c32/ttft": "c32_ttft-2",
        "c32_ttft": "c32_ttft",
        "c32 ttft": "c32_ttft-3",
        "plain": "plain",
    }
    assert model.file_names(["a/b", "a b", "a_b-2", "a/b"]) == {
        "a/b": "a_b",
        "a b": "a_b-3",
        "a_b-2": "a_b-2",
    }
    assert model.file_names([""]) == {"": "-2"}
    assert model.file_names([]) == {}


def test_a_name_of_the_mapping_is_written_into_a_file_name_as_it_stands() -> None:
    names = model.file_names(["c32/ttft", "c32_ttft"])
    assert model.chart_file("rounds", names["c32/ttft"]) == "charts/rounds.c32_ttft-2.svg"
    assert model.chart_file("rounds", names["c32_ttft"]) == "charts/rounds.c32_ttft.svg"
    assert model.folded_file(names["c32/ttft"]) == "profiles/c32_ttft-2.folded"
    assert all(model.safe_file_name(written) == written for written in names.values())


# ---------------------------------------------------------------------------
# What points outside a file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("<img src=http://example.invalid/a.png>", ("src=http://example.invalid/a.png",)),
        ("<script src=a.js></script>", ("src=a.js",)),
        ("<a href=//example.invalid>", ("href=//example.invalid",)),
        ('<img srcset="a.png 2x">', ('srcset="a.png 2x"',)),
        ("<video poster='a.png'>", ("poster='a.png'",)),
        ("<use href=#shape />", ()),
        ("<image href=data:image/png;base64,AAAA />", ()),
        ("if (node.href == other) { node.src === other; }", ()),
        ('<g data-src="made-up" data-href="made-up">', ()),
    ],
)
def test_a_reference_counts_with_its_value_in_quotes_or_without(
    text: str, found: tuple[str, ...]
) -> None:
    assert model.points_outside(text) == found


# ---------------------------------------------------------------------------
# What the steps after the analysis put into a results document
# ---------------------------------------------------------------------------


def test_a_note_of_a_later_step_is_shown_without_absolute_paths(
    example_results: dict[str, Any],
) -> None:
    first = Results.from_json(example_results).pending()
    added = [
        Note(code="explain_skipped", message="the lock /made/up/locks/a.lock could not be taken"),
        Note(code="charts_failed", message="cannot write ~/runs/run-a/charts/verdict.svg"),
    ]
    second = first.finished(
        diagnostics=DiagnosticsState(status="skipped", reason="lock"),
        plots=PlotsState(status="not_drawn", reason="failed"),
        notes=added,
    )
    assert [note.message for note in second.notes[len(first.notes) :]] == [
        "the lock a.lock could not be taken",
        "cannot write verdict.svg",
    ]
    assert "/made/up" not in json.dumps(second.to_json())
    assert model.second_write_changes(first, second) == ()


def test_the_files_of_a_run_are_named_relative_to_its_folder() -> None:
    kept = Artifacts(
        capture="capture.jsonl",
        html="report.html",
        diagnostics="diagnostics.json",
        charts=("charts/verdict.svg", "charts/rounds.matmul.svg"),
        profiles=("profiles/new.folded", "profiles/new_vs_old.flame-diff.svg"),
    )
    assert kept.charts == ("charts/verdict.svg", "charts/rounds.matmul.svg")
    for field, value in (
        ("charts", ("/made/up/run/charts/verdict.svg",)),
        ("profiles", ("profiles/../../new.folded",)),
        ("html", "~/runs/report.html"),
        ("diagnostics", "/made/up/diagnostics.json"),
        ("capture", ".."),
        ("plan", ""),
    ):
        with pytest.raises(ValueError, match="a file is named relative to the run folder"):
            Artifacts(**{field: value})  # type: ignore[arg-type]
    assert model.OUTSIDE_RUN_FOLDER == r"^[/~]|(^|/)\.\.(/|$)"


def test_the_cost_of_a_launch_names_the_command_and_keeps_its_times_in_order() -> None:
    cost = LaunchCost.of("true", [0.0003, 0.0004, 0.0005, 0.0007])
    assert (cost.command, cost.min_s <= cost.p25_s <= cost.median_s <= cost.p75_s) == ("true", True)
    with pytest.raises(ValueError, match=r"LaunchCost\.command"):
        LaunchCost.of("/made/up/bin/true", [0.0003, 0.0004])
    for times in (
        {"min_s": 0.0005, "p25_s": 0.0004, "median_s": 0.0005, "p75_s": 0.0007},
        {"min_s": 0.0003, "p25_s": 0.0006, "median_s": 0.0005, "p75_s": 0.0007},
        {"min_s": 0.0003, "p25_s": 0.0004, "median_s": 0.0008, "p75_s": 0.0007},
    ):
        with pytest.raises(ValueError, match="come in that order"):
            LaunchCost(command="true", n=20, **times)


def test_a_disturbed_round_of_a_series_is_numbered_from_one() -> None:
    assert Series(
        case="matmul", name="new", values=(1.5, None), disturbed_rounds=(1, 2)
    ).values == (
        1.5,
        None,
    )
    for rounds in ((0,), (3, -1)):
        with pytest.raises(ValueError, match="rounds are numbered from 1"):
            Series(case="matmul", name="new", disturbed_rounds=rounds)


# ---------------------------------------------------------------------------
# What the model refuses, the schemas refuse too
# ---------------------------------------------------------------------------


def _set(path: tuple[Any, ...], value: Any) -> Callable[[Any], None]:
    def change(document: Any) -> None:
        for key in path[:-1]:
            document = document[key]
        document[path[-1]] = value

    return change


RESULTS_REFUSED: list[tuple[str, Callable[[Any], None]]] = [
    ("a side that is no twin names twin_of", _set(("sides", 0, "twin_of"), "old")),
    ("a side that is no control names control_of", _set(("sides", 0, "control_of"), "old")),
    ("a relation that names nothing", _set(("sides", 0, "role"), "twin")),
    ("an identity value that is no hash", _set(("sides", 0, "identity", "image_id"), None)),
    ("a list of hashes that holds none", _set(("sides", 0, "identity", "digests"), [None])),
    ("a control that is ok and names no entry", _set(("controls", "positive", "entry"), None)),
    ("a control that is ok without a case", _set(("controls", "positive", "cases"), [])),
    (
        "a control that is ok with a case that did not pass",
        _set(("controls", "positive", "cases", 0, "passed"), False),
    ),
    ("a failed control whose cases all passed", _set(("controls", "positive", "status"), "failed")),
    ("an empty entry", _set(("controls", "positive", "entry"), "")),
    ("a tolerance of one half", _set(("controls", "positive", "tolerance"), 0.5)),
    ("a varied size without its range", _set(("env_pad",), {"varied": True})),
    ("a range without a varied size", _set(("env_pad",), {"varied": False, "min": 0, "max": 9})),
    ("a range past the largest pad", _set(("env_pad",), {"varied": True, "min": 0, "max": 4097})),
    ("a reason without skipped", _set(("diagnostics",), {"status": "written", "reason": "lock"})),
    ("skipped without a reason", _set(("diagnostics",), {"status": "skipped", "reason": None})),
    ("a reason without not_drawn", _set(("plots",), {"status": "drawn", "reason": "failed"})),
    ("a chart named from the root", _set(("artifacts", "charts"), ["/made/up/run/verdict.svg"])),
    ("a page named from the home folder", _set(("artifacts", "html"), "~/runs/report.html")),
    ("a profile that leaves the run folder", _set(("artifacts", "profiles"), ["../new.folded"])),
    ("a capture named from the root", _set(("artifacts", "capture"), "/made/up/capture.jsonl")),
    ("a file without a name", _set(("artifacts", "diagnostics"), "")),
    ("the empty command by its path", _set(("launch_cost", "command"), "/made/up/bin/true")),
    ("a disturbed round before the first", _set(("series", 0, "disturbed_rounds"), [0])),
]


@pytest.mark.parametrize(
    ("what", "change"), RESULTS_REFUSED, ids=[what for what, _change in RESULTS_REFUSED]
)
def test_a_results_document_the_model_refuses_also_fails_the_schema(
    example_results: dict[str, Any], what: str, change: Callable[[Any], None]
) -> None:
    assert _errors("results", example_results) == []
    Results.from_json(example_results)
    change(example_results)
    assert _errors("results", example_results) != [], what
    with pytest.raises(Refusal) as caught:
        Results.from_json(example_results)
    assert caught.value.code == "E_USAGE"


def _record(records: list[dict[str, Any]], kind: str, **changes: Any) -> dict[str, Any]:
    record = copy.deepcopy(next(r for r in records if r["t"] == kind))
    record.update(changes)
    return record


def test_a_capture_record_the_model_refuses_also_fails_the_schema(
    example_capture_records: list[dict[str, Any]],
    example_capture_run_records: list[dict[str, Any]],
) -> None:
    control = _record(example_capture_run_records, "side")
    machine = _record(example_capture_run_records, "machine")
    lineup = _record(example_capture_records, "lineup")
    subject = _record(example_capture_records, "side")
    for kept in (control, machine, lineup, subject):
        assert _errors("capture", kept) == []
        model.record_from_json(kept)
    refused = [
        {**control, "control_of": None},
        {**control, "control_of": ""},
        {**control, "name": ""},
        {**control, "twin_of": "old"},
        {**subject, "control_of": "old"},
        {**subject, "twin_of": "old"},
        {**subject, "name": "made up"},
        {**subject, "name": "made~up"},
        {**subject, "kind": ""},
        {**machine, "tool_cpus": "some"},
        {**machine, "tool_cpus": ""},
        {**lineup, "control": ""},
        {**lineup, "control": lineup["names"][0]},
    ]
    for record in refused[:-1]:
        assert _errors("capture", record) != [], record
    for record in refused:
        with pytest.raises(Refusal) as caught:
            model.record_from_json(record)
        assert caught.value.code == "E_USAGE", record


def test_a_diagnostics_document_the_model_refuses_also_fails_the_schema(
    example_diagnostics: dict[str, Any],
) -> None:
    assert _errors("diagnostics", example_diagnostics) == []
    model.Diagnostics.from_json(example_diagnostics)
    changes: list[Callable[[Any], None]] = [
        _set(("objects", "differ"), [{"new": "build-a", "old": "build-b"}]),
        _set(("instruments", 0, "reason"), "lock"),
        _set(("instruments", 1, "reason"), None),
    ]
    for change in changes:
        document = copy.deepcopy(example_diagnostics)
        change(document)
        assert _errors("diagnostics", document) != []
        with pytest.raises(Refusal) as caught:
            model.Diagnostics.from_json(document)
        assert caught.value.code == "E_USAGE"


def test_the_rules_that_span_two_fields_hold_when_an_object_is_made() -> None:
    row = ControlCase(case="matmul", expected=2.0, ratio=2.0, p_raw=0.001, n_rounds=20, passed=True)
    missed = ControlCase(
        case="matmul", expected=2.0, ratio=1.5, p_raw=0.001, n_rounds=20, passed=False
    )
    assert PositiveControl(status="ok", entry="old~twice", cases=(row,)).status == "ok"
    assert (
        PositiveControl(status="failed", entry="old~twice", cases=(row, missed)).cases[1] == missed
    )
    assert PositiveControl(status="not_run", cases=(missed,)).entry is None
    for wrong in (
        {"status": "ok", "entry": "old~twice"},
        {"status": "ok", "entry": "old~twice", "cases": (row, missed)},
        {"status": "ok", "cases": (row,)},
        {"status": "failed", "entry": "old~twice", "cases": (row,)},
        {"status": "failed", "cases": (missed,)},
    ):
        with pytest.raises(ValueError, match="PositiveControl"):
            PositiveControl(**wrong)  # type: ignore[arg-type]
    assert EnvPad.of(True) == EnvPad(varied=True, min=0, max=4096)
    assert EnvPad.of(False) == EnvPad()
    for values in (
        {"varied": True},
        {"varied": False, "min": 0, "max": 9},
        {"varied": True, "min": 0},
        {"varied": True, "max": 4096},
        {"varied": False, "min": 0},
        {"varied": False, "max": 4096},
    ):
        with pytest.raises(ValueError, match="EnvPad"):
            EnvPad(**values)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"Lineup\.control"):
        Lineup(names=("new", "old"), control="", rounds=2)
    with pytest.raises(ValueError, match=r"Side\.control_of"):
        Side(name="old~twice", kind="cmd", role="control", control_of="")
    shown = {"name": "new", "kind": "cmd", "identity": {}, "fingerprint": ""}
    for relation in ({"role": "subject", "twin_of": "old"}, {"role": "twin", "twin_of": None}):
        with pytest.raises(ValueError, match=r"ResultsSide\.twin_of"):
            ResultsSide(**shown, **relation)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"ResultsSide\.control_of"):
        ResultsSide(**shown, role="subject", twin_of=None, control_of="old")  # type: ignore[arg-type]
