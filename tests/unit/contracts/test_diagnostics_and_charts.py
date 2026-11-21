# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The explain step, the diagnostics document, the charts and the report page:
their settings, vocabularies, documents and the seams between the parts."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api, model, registry
from pairbench.errors import Refusal
from pairbench.model import (
    Artifacts,
    Capture,
    Diagnostics,
    DiagnosticsState,
    Experiment,
    ExplainSettings,
    Finding,
    Header,
    InstrumentRun,
    LaunchSettings,
    Note,
    PlotSettings,
    PlotsState,
    Results,
    Series,
    Side,
)
from pairbench.results import load_schema

jsonschema = pytest.importorskip(
    "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
)

REPO = Path(__file__).resolve().parents[3]


def _errors(name: str, document: Any) -> list[str]:
    validator = jsonschema.Draft202012Validator(load_schema(name))
    return sorted(error.message for error in validator.iter_errors(document))


def _module(monkeypatch: pytest.MonkeyPatch, name: str, **members: Any) -> types.ModuleType:
    """Put a made-up module in place of one that another part of the package provides."""
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _experiment(kind: str = "cmd", **changes: Any) -> Experiment:
    return Experiment(sides=(Side(name="new", kind=kind), Side(name="old", kind=kind)), **changes)


# ---------------------------------------------------------------------------
# The settings
# ---------------------------------------------------------------------------


def test_the_defaults_of_the_explain_settings() -> None:
    assert ExplainSettings() == ExplainSettings(
        mode="always", sample_hz=99, call_graph="fp", top=20
    )
    assert _experiment().explain == ExplainSettings()


@pytest.mark.parametrize(
    ("values", "words"),
    [
        ({"mode": "sometimes"}, "one of 'always', 'auto', 'off'"),
        ({"call_graph": "made_up"}, "one of 'fp', 'dwarf', 'lbr'"),
        ({"sample_hz": 0}, "at least 1"),
        ({"top": 0}, "at least 1"),
    ],
)
def test_explain_settings_that_are_refused(values: dict[str, Any], words: str) -> None:
    with pytest.raises(ValueError, match=words):
        ExplainSettings(**values)


def test_the_defaults_of_the_plot_and_report_settings() -> None:
    assert PlotSettings() == PlotSettings(mode="auto", max_round_charts=12)
    assert _experiment().plots == PlotSettings()
    assert model.ReportSettings() == model.ReportSettings(include_image_refs=False, html=True)
    with pytest.raises(ValueError, match="one of 'auto', 'on', 'off'"):
        PlotSettings(mode="always")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least 0"):
        PlotSettings(max_round_charts=-1)


def test_the_explain_plot_report_and_launch_cost_settings_are_read_and_written(
    example_config: dict[str, Any],
) -> None:
    example_config["explain"] = {"mode": "auto", "sample_hz": 49, "call_graph": "dwarf", "top": 5}
    example_config["plots"] = {"mode": "on", "max_round_charts": 3}
    example_config["report"] = {"include_image_refs": False, "html": False}
    example_config["launch_cost"] = {"launches": 0, "note_share": 0.05}
    experiment = Experiment.from_json(example_config)
    assert experiment.explain == ExplainSettings(
        mode="auto", sample_hz=49, call_graph="dwarf", top=5
    )
    assert experiment.plots == PlotSettings(mode="on", max_round_charts=3)
    assert experiment.report.html is False
    assert experiment.launch_cost == model.LaunchCostSettings(launches=0, note_share=0.05)
    written = experiment.to_json()
    for table in ("explain", "plots", "report", "launch_cost"):
        assert written[table] == example_config[table]
    assert _errors("config", written) == []
    assert Experiment.from_json(written) == experiment


@pytest.mark.parametrize(
    ("table", "values", "words"),
    [
        ("explain", {"mode": "sometimes"}, "explain.mode must be one of always, auto, off"),
        ("explain", {"sample_hz": 0}, "explain.sample_hz: expected at least 1"),
        ("explain", {"call_graph": "x"}, "explain.call_graph must be one of fp, dwarf, lbr"),
        ("explain", {"top": 0}, "explain.top: expected at least 1"),
        ("plots", {"mode": "always"}, "plots.mode must be one of auto, on, off"),
        ("plots", {"max_round_charts": -1}, "plots.max_round_charts: expected at least 0"),
        ("report", {"html": "yes"}, "report.html must be true or false"),
        ("launch_cost", {"launches": -1}, "launch_cost.launches: expected at least 0"),
        ("launch_cost", {"note_share": 0}, "launch_cost.note_share: expected more than 0"),
        ("launch_cost", {"note_share": 2}, "launch_cost.note_share: expected at most 1"),
        ("launch", {"perf_counters": "yes"}, "launch.perf_counters must be true or false"),
        ("run", {"vary_env_size": 1}, "run.vary_env_size must be true or false"),
        ("explain", {"made_up": 1}, "unknown config key: explain.made_up"),
        ("plots", {"made_up": 1}, "unknown config key: plots.made_up"),
    ],
)
def test_a_bad_setting_of_these_tables_fails_the_model_and_the_schema(
    example_config: dict[str, Any], table: str, values: dict[str, Any], words: str
) -> None:
    example_config[table] = {**example_config.get(table, {}), **values}
    with pytest.raises(Refusal, match=words) as caught:
        Experiment.from_json(example_config)
    assert (caught.value.code, caught.value.exit_code) == ("E_CONFIG", 2)
    assert _errors("config", example_config) != []


def test_the_capability_to_use_performance_counters_is_a_launch_setting() -> None:
    assert LaunchSettings().perf_counters is False
    assert "perf_counters" in LaunchSettings.OVERRIDABLE
    settings = LaunchSettings(overrides={"new": {"perf_counters": True}})
    assert settings.for_side(Side(name="new", kind="image")).perf_counters is True
    assert settings.for_side(Side(name="old", kind="image")).perf_counters is False
    assert settings.differences() == {"new": ("perf_counters",)}
    assert LaunchSettings().effective()["perf_counters"] is False
    assert LaunchSettings(perf_counters=True).effective()["perf_counters"] is True
    identity = {"image_id": "sha256:" + "ab" * 32}
    with_it = model.fingerprint_of(identity, LaunchSettings(perf_counters=True).effective())
    assert with_it != model.fingerprint_of(identity, LaunchSettings().effective())


def test_the_capability_is_set_in_the_config_for_all_sides_or_for_one(
    example_config: dict[str, Any],
) -> None:
    example_config["launch"]["perf_counters"] = True
    example_config["sides"]["old"]["launch"] = {"perf_counters": False}
    experiment = Experiment.from_json(example_config)
    assert experiment.launch.perf_counters is True
    assert experiment.launch.for_side(experiment.side("old")).perf_counters is False
    written = experiment.to_json()
    assert written["launch"]["perf_counters"] is True
    assert written["sides"]["old"]["launch"] == {"perf_counters": False}
    assert _errors("config", written) == []


# ---------------------------------------------------------------------------
# Config keys and the flags that set them
# ---------------------------------------------------------------------------

CONTROL_EXPLAIN_AND_CHART_KEYS = (
    "run.vary_env_size",
    "controls.positive",
    "controls.positive_tolerance",
    "controls.positive_via",
    "launch_cost.launches",
    "launch_cost.note_share",
    "explain.mode",
    "explain.sample_hz",
    "explain.call_graph",
    "explain.top",
    "plots.mode",
    "plots.max_round_charts",
    "report.html",
    "launch.perf_counters",
    "sides.NAME.launch.perf_counters",
)


def test_the_config_keys_of_the_controls_the_explain_step_and_the_charts() -> None:
    assert len(CONTROL_EXPLAIN_AND_CHART_KEYS) == 15
    for key in CONTROL_EXPLAIN_AND_CHART_KEYS:
        assert key in model.CONFIG_KEYS, key
    assert len(model.CONFIG_KEYS) == 106
    assert len(set(model.CONFIG_KEYS)) == 106


FLAG_KEYS = {
    "--driver": "workload.driver",
    "--case": "cases.primary",
    "--levels": "workload.levels",
    "--level-duration": "workload.level_duration",
    "--rounds": "run.rounds",
    "--rounds-exact": "run.rounds_exact",
    "--quick": "run.quick",
    "--budget": "run.budget",
    "--warmups": "run.warmups",
    "--same-vs-same": "run.same_vs_same",
    "--positive-control": "controls.positive",
    "--vary-env-size": "run.vary_env_size",
    "--allow-underpowered": "run.allow_underpowered",
    "--engine": "launch.engine",
    "--cpus": "launch.cpus",
    "--gpus": "launch.gpus",
    "--pull": "launch.pull",
    "--timeout": "launch.timeout",
    "--allow-identical": "launch.allow_identical",
    "--gates": "gates.mode",
    "--wait-quiet": "gates.wait_quiet",
    "--lock": "gates.locks",
    "--lock-timeout": "gates.lock_timeout",
    "--allow-mixed-core-types": "gates.allow_mixed_core_types",
    "--rule": "rule.name",
    "--fail-on": "rule.fail_on",
    "--explain": "explain.mode",
    "--plots": "plots.mode",
    "--out": "run.out",
    "--print-plan": "run.print_plan",
    "--json": "run.json",
    "--no-plugins": "run.no_plugins",
}


def test_the_config_key_each_flag_of_the_run_command_sets() -> None:
    assert dict(model.FLAG_KEYS) == FLAG_KEYS
    assert set(model.FLAG_KEYS.values()) <= set(model.CONFIG_KEYS)
    assert len(set(model.FLAG_KEYS.values())) == len(model.FLAG_KEYS)
    assert model.FLAGS_WITHOUT_KEY == ("--side", "--baseline", "--config", "--set")
    assert not set(model.FLAGS_WITHOUT_KEY) & set(model.FLAG_KEYS)


def test_every_flag_the_reference_lists_for_the_run_command_has_its_key() -> None:
    page = (REPO / "docs" / "reference" / "commands.md").read_text(encoding="utf-8")
    section = page.split("\n## run\n", 1)[1].split("\n## ", 1)[0]
    named = set(re.findall(r"^\| `(--[a-z][a-z-]*)", section, re.MULTILINE))
    assert "--positive-control" in named
    assert "--plots" in named
    assert len(named) >= 30
    assert named == set(model.FLAG_KEYS) | set(model.FLAGS_WITHOUT_KEY)


# ---------------------------------------------------------------------------
# Instruments and explain launches
# ---------------------------------------------------------------------------


def test_the_three_instruments() -> None:
    assert model.INSTRUMENTS == ("counters", "stacks", "pystacks")
    assert model.STACK_INSTRUMENTS == ("stacks", "pystacks")
    assert model.INSTRUMENT_STATUSES == ("ok", "skipped", "failed")
    assert model.INSTRUMENT_REASONS == (
        "not_installed",
        "not_permitted",
        "not_in_image",
        "no_capability",
        "launcher_cannot",
        "side_changed",
        "lock",
        "launch_failed",
        "interpreter_too_old",
    )
    assert tuple(model.INSTRUMENT_REASON_WORDS) == model.INSTRUMENT_REASONS
    assert model.PYSAMPLER_MIN_PYTHON == (3, 8)
    assert model.EXPLAIN_LAUNCHES_PER_SIDE == 2


def test_the_events_the_counters_count() -> None:
    assert model.COUNTER_EVENTS == (
        "instructions",
        "cycles",
        "branches",
        "branch-misses",
        "cache-references",
        "cache-misses",
        "task-clock",
        "context-switches",
        "cpu-migrations",
        "page-faults",
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (["python", "bench.py"], True),
        (["python3", "bench.py"], True),
        (["/made/up/bin/python3.12", "-m", "made_up"], True),
        (["python3.8"], True),
        (["pytest", "tests"], False),
        (["env", "python", "bench.py"], False),
        (["python3-config"], False),
        (["pythonw"], False),
        (["./bench"], False),
        ([], False),
        (None, False),
    ],
)
def test_a_command_that_starts_with_a_python_interpreter(
    command: list[str] | None, expected: bool
) -> None:
    assert model.starts_with_python(command) is expected


@pytest.mark.parametrize(
    ("sides", "mode", "launches"),
    [(2, "always", 4), (2, "auto", 4), (2, "off", 0), (3, "always", 6), (1, "always", 2)],
)
def test_the_explain_launches_a_plan_counts(sides: int, mode: str, launches: int) -> None:
    assert model.planned_explain_launches(sides, mode) == launches


def test_the_explain_launches_of_an_experiment_and_of_a_capture() -> None:
    assert _experiment().explain_launches() == 4
    assert _experiment(explain=ExplainSettings(mode="off")).explain_launches() == 0
    assert _experiment("file").explain_launches() == 0
    with pytest.raises(ValueError, match="the explain mode is one of always, auto, off"):
        model.planned_explain_launches(2, "sometimes")

    def capture(config: dict[str, Any], kind: str = "cmd") -> Capture:
        baseline = Side(name="old", kind=kind, role="baseline")
        sides = (Side(name="new", kind=kind), baseline, baseline.twin(), baseline.control())
        return Capture(
            capture_id="cap-000001",
            header=Header(capture_id="cap-000001", config=config),
            sides=sides,
        )

    assert capture({}).explain_launches() == 4
    assert capture({"explain": {"mode": "auto"}}).explain_launches() == 4
    assert capture({"explain": {"mode": "off"}}).explain_launches() == 0
    assert capture({}, "rows").explain_launches() == 0
    assert capture({}, "file").explain_launches() == 0


# ---------------------------------------------------------------------------
# The diagnostics document
# ---------------------------------------------------------------------------

DIAGNOSTICS_KEYS = [
    "schema",
    "run",
    "holds_names",
    "instruments",
    "resources",
    "counters",
    "stacks",
    "objects",
    "findings",
    "files",
    "name_map",
]


def test_the_example_diagnostics_document_validates(example_diagnostics: dict[str, Any]) -> None:
    assert list(example_diagnostics) == DIAGNOSTICS_KEYS
    assert _errors("diagnostics", example_diagnostics) == []


def test_the_example_diagnostics_survive_a_round_trip(example_diagnostics: dict[str, Any]) -> None:
    document = Diagnostics.from_json(example_diagnostics)
    written = document.to_json()
    assert list(written) == [*DIAGNOSTICS_KEYS, "notes"]
    assert {k: v for k, v in written.items() if k != "notes"} == example_diagnostics
    assert written["notes"] == []
    assert _errors("diagnostics", written) == []
    assert Diagnostics.from_json(written) == document


def test_the_example_diagnostics_are_read_into_the_model(
    example_diagnostics: dict[str, Any],
) -> None:
    document = Diagnostics.from_json(example_diagnostics)
    assert document.schema == "pairbench/diagnostics/v1"
    assert document.run.id == "cap-000001"
    assert document.holds_names is True
    assert document.instruments == (
        InstrumentRun(name="counters", side="new", status="ok", reason=None, rc=0),
        InstrumentRun(name="stacks", side="old", status="skipped", reason="not_permitted"),
    )
    assert (document.resources[0].case, document.resources[0].outcome) == ("res/cores", "higher")
    assert (document.counters[0].event, document.counters[0].ratio) == ("instructions", 0.5)
    stacks = document.stacks[0]
    assert (stacks.side, stacks.instrument, stacks.samples) == ("new", "stacks", 1234)
    assert stacks.top_functions[0] == model.TopFunction(
        name="made_up_function", object="libmade-up.so", share=0.25
    )
    assert stacks.top_objects[0] == model.TopObject(name="libmade-up.so", share=0.5)
    assert document.objects.only_in == {"new": ("libmade-up.so",), "old": ()}
    assert document.objects.differ == (
        {"name": "libother-made-up.so", "new": "aa11", "old": "bb22"},
    )
    assert document.findings[0].id == "cores_used"
    assert document.findings[0].evidence["n_rounds"] == 20
    assert document.files == model.DiagnosticsFiles()
    assert (document.name_map, document.notes) == ({}, ())


@pytest.mark.parametrize("key", [k for k in DIAGNOSTICS_KEYS if k != "notes"])
def test_a_diagnostics_document_without_a_required_key_is_refused(
    example_diagnostics: dict[str, Any], key: str
) -> None:
    del example_diagnostics[key]
    assert _errors("diagnostics", example_diagnostics) == [f"'{key}' is a required property"]
    with pytest.raises(Refusal, match=f"missing key '{key}'") as caught:
        Diagnostics.from_json(example_diagnostics)
    assert caught.value.code == "E_USAGE"


def _set(document: dict[str, Any], path: tuple[Any, ...], value: Any) -> None:
    target: Any = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema",), "pairbench/diagnostics/v2"),
        (("instruments", 0, "name"), "made_up"),
        (("instruments", 0, "status"), "pending"),
        (("instruments", 1, "reason"), "made_up"),
        (("resources", 0, "outcome"), "faster"),
        (("stacks", 0, "instrument"), "counters"),
        (("stacks", 0, "samples"), -1),
        (("stacks", 0, "top_functions", 0, "share"), 1.5),
        (("stacks", 0, "top_objects", 0, "share"), -0.5),
        (("findings", 0, "id"), "made_up"),
        (("findings", 0, "text"), ""),
        (("holds_names",), "yes"),
        (("objects", "differ", 0, "new"), 7),
    ],
)
def test_a_diagnostics_value_outside_its_vocabulary_fails_schema_and_model(
    example_diagnostics: dict[str, Any], path: tuple[Any, ...], value: Any
) -> None:
    _set(example_diagnostics, path, value)
    assert _errors("diagnostics", example_diagnostics) != []
    with pytest.raises(Refusal) as caught:
        Diagnostics.from_json(example_diagnostics)
    assert caught.value.code == "E_USAGE"


def test_an_instrument_that_ran_has_no_reason_and_one_that_did_not_has_one() -> None:
    with pytest.raises(ValueError, match="a reason is given unless the instrument ran"):
        InstrumentRun(name="stacks", side="new", status="skipped")
    with pytest.raises(ValueError, match="a reason is given unless the instrument ran"):
        InstrumentRun(name="stacks", side="new", status="ok", reason="lock")
    failed = InstrumentRun(
        name="counters", side="new", status="failed", reason="launch_failed", rc=3
    )
    assert failed.rc == 3


def test_the_loud_note_of_an_instrument_that_did_not_run() -> None:
    assert InstrumentRun(name="counters", side="new", status="ok", rc=0).note() is None
    skipped = InstrumentRun(name="stacks", side="old", status="skipped", reason="not_permitted")
    assert skipped.note() == Note(
        code="instrument_skipped",
        message=(
            "instrument stacks did not run for side old: the system does not permit it: "
            "the kernel setting perf_event_paranoid forbids it"
        ),
    )
    capability = InstrumentRun(
        name="counters", side="new", status="skipped", reason="no_capability"
    ).note()
    assert capability is not None
    assert "the launch setting perf_counters gives it" in capability.message
    for reason in model.INSTRUMENT_REASONS:
        note = InstrumentRun(name="stacks", side="new", status="skipped", reason=reason).note()  # type: ignore[arg-type]
        assert note is not None
        assert note.code == model.NOTE_INSTRUMENT_SKIPPED


def test_the_notes_of_the_explain_step_are_part_of_the_document(
    example_diagnostics: dict[str, Any],
) -> None:
    example_diagnostics["notes"] = [{"code": "instrument_skipped", "message": "a made-up note"}]
    assert _errors("diagnostics", example_diagnostics) == []
    document = Diagnostics.from_json(example_diagnostics)
    assert document.notes == (Note(code="instrument_skipped", message="a made-up note"),)
    assert document.to_json()["notes"] == example_diagnostics["notes"]


def test_every_object_that_differs_is_named() -> None:
    with pytest.raises(ValueError, match="every entry names its object under 'name'"):
        model.ObjectDiff(differ=({"new": "aa11", "old": "bb22"},))


def _document(*rows: InstrumentRun) -> Diagnostics:
    return Diagnostics(run=model.DiagnosticsRun(id="cap-000001"), instruments=rows)


def test_the_state_of_the_explain_step_follows_from_its_document() -> None:
    ran = InstrumentRun(name="counters", side="new", status="ok", rc=0)
    locked = InstrumentRun(name="stacks", side="new", status="skipped", reason="lock")
    absent = InstrumentRun(name="stacks", side="old", status="skipped", reason="not_installed")
    assert _document(ran, absent).state() == DiagnosticsState(status="written")
    assert _document(locked, locked).state() == DiagnosticsState(status="skipped", reason="lock")
    assert _document(absent, locked).state() == DiagnosticsState(
        status="skipped", reason="no_instrument"
    )
    assert _document().state() == DiagnosticsState(status="skipped", reason="no_instrument")


def test_a_difference_needs_the_same_instrument_on_both_sides() -> None:
    def stacks(side: str, instrument: str) -> model.StackSummary:
        return model.StackSummary(side=side, instrument=instrument, samples=10)  # type: ignore[arg-type]

    run = model.DiagnosticsRun(id="cap-000001")
    same = Diagnostics(run=run, stacks=(stacks("new", "stacks"), stacks("old", "stacks")))
    mixed = Diagnostics(run=run, stacks=(stacks("new", "pystacks"), stacks("old", "stacks")))
    one = Diagnostics(run=run, stacks=(stacks("new", "stacks"),))
    assert same.same_instrument("new", "old") is True
    assert mixed.same_instrument("new", "old") is False
    assert one.same_instrument("new", "old") is False
    assert mixed.stacks_of("new") == stacks("new", "pystacks")
    assert one.stacks_of("old") is None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_the_finding_ids() -> None:
    assert model.FINDING_IDS == (
        "cores_used",
        "cpu_time_split",
        "peak_memory",
        "context_switches",
        "page_faults",
        "instructions",
        "instructions_per_cycle",
        "cache_misses",
        "branch_misses",
        "top_function_share",
        "top_object_share",
        "objects_on_one_side",
        "objects_differ",
    )
    assert model.FINDINGS_WITHOUT_NAMES == (
        "cores_used",
        "cpu_time_split",
        "peak_memory",
        "context_switches",
        "page_faults",
        "instructions",
        "instructions_per_cycle",
        "cache_misses",
        "branch_misses",
    )
    assert set(model.FINDING_IDS) - set(model.FINDINGS_WITHOUT_NAMES) == {
        "top_function_share",
        "top_object_share",
        "objects_on_one_side",
        "objects_differ",
    }


def test_the_words_a_finding_never_uses() -> None:
    assert model.FINDING_FORBIDDEN_WORDS == (
        "because",
        "causes",
        "due to",
        "explains",
        "faster thanks to",
    )


@pytest.mark.parametrize(
    ("text", "used"),
    [
        ("new used 7.8 cores against 1.0 for old (median of 20 rounds).", ()),
        ("The share of samples differs: more in new, fewer in old.", ()),
        ("new is slower because it waits.", ("because",)),
        ("This CAUSES the gap.", ("causes",)),
        ("The gap is due  to paging.", ("due to",)),
        ("Paging explains the gap.", ("explains",)),
        ("new is faster thanks to a cache.", ("faster thanks to",)),
        ("It is so because this explains it.", ("because", "explains")),
        ("An unexplained pause; the becauses of it.", ()),
    ],
)
def test_the_forbidden_words_a_text_uses(text: str, used: tuple[str, ...]) -> None:
    assert model.forbidden_words(text) == used


def test_a_finding_that_names_a_cause_is_refused() -> None:
    with pytest.raises(ValueError, match="a finding never says because"):
        Finding(id="cores_used", text="new is slower because it uses 7.8 cores.")
    with pytest.raises(ValueError, match="one of 'cores_used'"):
        Finding(id="made_up", text="A made-up finding.")  # type: ignore[arg-type]
    kept = Finding(id="peak_memory", text="new used more memory at its peak.", evidence={"n": 3})
    assert kept.evidence == {"n": 3}


def test_the_findings_a_report_without_names_may_show(
    example_diagnostics: dict[str, Any],
) -> None:
    example_diagnostics["findings"].append(
        {
            "id": "top_function_share",
            "text": "made_up_function holds a 0.25 share of samples in new.",
            "evidence": {"share": 0.25},
        }
    )
    document = Diagnostics.from_json(example_diagnostics)
    assert [f.id for f in document.findings] == ["cores_used", "top_function_share"]
    assert [f.id for f in document.shareable_findings()] == ["cores_used"]


# ---------------------------------------------------------------------------
# File names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("matmul", "matmul"),
        ("c32/ttft_ms_median", "c32_ttft_ms_median"),
        ("energy_j[gpu]", "energy_j_gpu_"),
        ("new~same", "new_same"),
        ("v2.0-rc_1", "v2.0-rc_1"),
        ("a b\tc", "a_b_c"),
        ("<b>made-up</b>", "_b_made-up__b_"),
        ("../made/up", ".._made_up"),
    ],
)
def test_a_name_as_it_is_written_in_a_file_name(name: str, safe: str) -> None:
    assert model.safe_file_name(name) == safe


def test_a_long_name_is_written_short_and_stays_apart_from_its_neighbours() -> None:
    first = "made-up-case-" + "x" * 300 + "-one"
    second = "made-up-case-" + "x" * 300 + "-two"
    written = model.safe_file_name(first)
    assert len(written) == model.FILE_NAME_LIMIT == 100
    assert written == first[:83] + "-" + hashlib.sha256(first.encode()).hexdigest()[:16]
    assert model.safe_file_name(second) != written
    assert model.safe_file_name(written) == written
    assert model.safe_file_name("y" * 100) == "y" * 100


def test_every_file_of_a_long_name_can_be_created(tmp_path: Path) -> None:
    subject = "s/" * 200
    baseline = "b" * 400
    names = model.file_names([subject, baseline, "b" * 401])
    assert len(set(names.values())) == 3
    assert all(len(written) <= model.FILE_NAME_LIMIT for written in names.values())
    assert all(model.safe_file_name(written) == written for written in names.values())
    paths = [
        model.folded_file(names[subject]),
        model.flame_file(names[subject]),
        model.folded_diff_file(names[subject], names[baseline]),
        model.flame_diff_file(names[subject], names[baseline]),
        model.chart_file("rounds", names[subject]),
    ]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("made-up", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "made-up"


def test_names_cut_alike_get_their_count_inside_the_limit() -> None:
    long_safe = "z" * 120
    names = model.file_names([long_safe, long_safe + "/", long_safe + " "])
    assert len(set(names.values())) == 3
    assert all(len(written) <= model.FILE_NAME_LIMIT for written in names.values())
    assert all(model.safe_file_name(written) == written for written in names.values())


def test_the_files_of_the_run_folder() -> None:
    assert (model.FILE_DIAGNOSTICS, model.FILE_REPORT) == ("diagnostics.json", "report.html")
    assert (model.DIR_PROFILES, model.DIR_CHARTS) == ("profiles", "charts")
    assert model.folded_file("new") == "profiles/new.folded"
    assert model.folded_diff_file("new", "old") == "profiles/new_vs_old.folded-diff.tsv"
    assert model.flame_file("new") == "profiles/new.flame.svg"
    assert model.flame_diff_file("new", "old") == "profiles/new_vs_old.flame-diff.svg"
    assert model.flame_file("a/b") == "profiles/a_b.flame.svg"
    assert model.CHARTS == ("verdict", "rounds", "noise", "resources")
    assert model.chart_file("verdict") == "charts/verdict.svg"
    assert model.chart_file("noise") == "charts/noise.svg"
    assert model.chart_file("resources") == "charts/resources.svg"
    assert model.chart_file("rounds", "matmul") == "charts/rounds.matmul.svg"
    assert model.chart_file("rounds", "c32/ttft_ms_median") == (
        "charts/rounds.c32_ttft_ms_median.svg"
    )
    with pytest.raises(ValueError, match="a chart is one of"):
        model.chart_file("made_up")
    with pytest.raises(ValueError, match="only it, is drawn per case"):
        model.chart_file("rounds")
    with pytest.raises(ValueError, match="only it, is drawn per case"):
        model.chart_file("verdict", "matmul")


# ---------------------------------------------------------------------------
# What the results record of the two steps
# ---------------------------------------------------------------------------


def test_the_states_of_the_explain_step_and_of_the_charts() -> None:
    assert model.DIAGNOSTICS_STATUSES == (
        "pending",
        "written",
        "skipped",
        "off",
        "failed",
        "interrupted",
    )
    assert model.DIAGNOSTICS_REASONS == ("mode_auto_no_difference", "lock", "no_instrument")
    assert model.PLOTS_STATUSES == ("pending", "drawn", "not_drawn", "off", "interrupted")
    assert model.PLOTS_REASONS == ("extra_missing", "failed")
    assert DiagnosticsState() == DiagnosticsState(status="off", reason=None)
    assert PlotsState() == PlotsState(status="off", reason=None)


def test_a_reason_belongs_to_a_skipped_step_and_to_charts_that_were_not_drawn() -> None:
    assert DiagnosticsState(status="skipped", reason="lock").reason == "lock"
    with pytest.raises(ValueError, match="a reason is given with skipped and only with it"):
        DiagnosticsState(status="skipped")
    with pytest.raises(ValueError, match="a reason is given with skipped and only with it"):
        DiagnosticsState(status="written", reason="lock")
    assert PlotsState(status="not_drawn", reason="extra_missing").reason == "extra_missing"
    assert PlotsState(status="not_drawn").reason is None
    with pytest.raises(ValueError, match="a reason is given only with not_drawn"):
        PlotsState(status="drawn", reason="failed")


def test_the_results_record_the_series_the_states_and_the_files(
    example_results: dict[str, Any], example_results_every_key: dict[str, Any]
) -> None:
    results = Results.from_json(example_results)
    assert results.series == (
        Series(case="matmul", name="new", values=(1.92, 1.91), disturbed_rounds=()),
    )
    assert results.plots == PlotsState(status="drawn")
    assert results.diagnostics == DiagnosticsState(status="written")
    assert results.artifacts == Artifacts(
        capture="capture.jsonl",
        markdown="results.md",
        plan="plan.tsv",
        html="report.html",
        diagnostics="diagnostics.json",
        charts=(),
        profiles=(),
    )
    assert list(results.to_json()["artifacts"]) == [
        "capture",
        "markdown",
        "plan",
        "html",
        "diagnostics",
        "charts",
        "profiles",
    ]
    every = Results.from_json(example_results_every_key)
    assert every.env_pad == model.EnvPad(varied=True, min=0, max=4096)
    assert every.artifacts.charts == ("charts/verdict.svg", "charts/rounds.matmul.svg")


def test_a_round_without_a_value_holds_null_in_a_series() -> None:
    series = Series(case="matmul", name="new", values=(1.92, None, 1.91), disturbed_rounds=(2,))
    written = series.to_json()
    assert written == {
        "case": "matmul",
        "name": "new",
        "values": [1.92, None, 1.91],
        "disturbed_rounds": [2],
    }
    assert Series.from_json(written) == series


def test_results_without_the_keys_that_may_be_absent_are_read_with_their_defaults(
    example_results_required_only: dict[str, Any],
) -> None:
    document = example_results_required_only
    for key in ("controls", "launch_cost", "env_pad", "series", "plots", "diagnostics"):
        assert key not in document
    assert "explain_launches" not in document["plan"]
    assert "control_of" not in document["sides"][0]
    assert "html" not in document["artifacts"]
    assert _errors("results", document) == []
    results = Results.from_json(document)
    assert results.series == ()
    assert results.plots == PlotsState(status="off")
    assert results.diagnostics == DiagnosticsState(status="off")
    assert results.env_pad == model.EnvPad(varied=False)
    assert results.plan.explain_launches == 0
    assert results.sides[0].control_of is None
    assert results.artifacts == Artifacts(
        capture="capture.jsonl", markdown="results.md", plan="plan.tsv"
    )


def test_a_results_document_has_no_field_for_a_name_from_the_code_of_the_user() -> None:
    names: set[str] = set()

    def walk(cls: Any) -> None:
        if not (dataclasses.is_dataclass(cls) and isinstance(cls, type)) or cls.__name__ in names:
            return
        names.add(cls.__name__)
        for hint in inspect.get_annotations(cls, eval_str=True).values():
            for arg in (hint, *getattr(hint, "__args__", ())):
                walk(arg)
                for inner in getattr(arg, "__args__", ()):
                    walk(inner)

    walk(Results)
    assert "Comparison" in names
    assert "PositiveControl" in names
    for holder in ("StackSummary", "TopFunction", "TopObject", "ObjectDiff", "Finding"):
        assert holder not in names
    fields = set(load_schema("results")["properties"]) | {
        key
        for definition in load_schema("results")["$defs"].values()
        for key in definition["properties"]
    }
    assert not fields & {
        "stacks",
        "top_functions",
        "top_objects",
        "objects",
        "findings",
        "name_map",
    }


# ---------------------------------------------------------------------------
# The two writes of the results of a run
# ---------------------------------------------------------------------------


def test_the_first_write_says_pending_for_both_steps(example_results: dict[str, Any]) -> None:
    analysed = dataclasses.replace(
        Results.from_json(example_results),
        diagnostics=DiagnosticsState(),
        plots=PlotsState(),
    )
    first = analysed.pending()
    assert first.diagnostics == DiagnosticsState(status="pending")
    assert first.plots == PlotsState(status="pending")
    assert dataclasses.replace(first, diagnostics=analysed.diagnostics, plots=analysed.plots) == (
        analysed
    )


def test_the_second_write_differs_only_in_the_steps_their_notes_and_the_files(
    example_results: dict[str, Any],
) -> None:
    first = Results.from_json(example_results).pending()
    files = dataclasses.replace(first.artifacts, charts=("charts/verdict.svg",))
    added = Note(code="instrument_skipped", message="a made-up note")
    second = first.finished(
        diagnostics=DiagnosticsState(status="skipped", reason="no_instrument"),
        plots=PlotsState(status="drawn"),
        notes=[added],
        artifacts=files,
    )
    assert model.SECOND_WRITE_KEYS == ("diagnostics", "plots", "artifacts", "notes")
    assert second.diagnostics == DiagnosticsState(status="skipped", reason="no_instrument")
    assert second.plots == PlotsState(status="drawn")
    assert second.notes == (*first.notes, added)
    assert second.artifacts.charts == ("charts/verdict.svg",)
    assert model.second_write_changes(first, second) == ()
    kept = first.finished(diagnostics=DiagnosticsState(), plots=PlotsState())
    assert kept.artifacts == first.artifacts
    assert model.second_write_changes(first, kept) == ()


def test_a_second_write_that_changes_anything_else_is_seen(
    example_results: dict[str, Any],
) -> None:
    noted = dict(
        example_results, notes=[{"code": "floor_provisional", "message": "a made-up note"}]
    )
    first = Results.from_json(noted).pending()
    second = first.finished(diagnostics=DiagnosticsState(), plots=PlotsState())
    other_comparisons = dataclasses.replace(second, comparisons=())
    assert model.second_write_changes(first, other_comparisons) == ("comparisons",)
    other_run = dataclasses.replace(
        second, cases=(), plan=dataclasses.replace(second.plan, launches=1)
    )
    assert model.second_write_changes(first, other_run) == ("cases", "plan")
    dropped = dataclasses.replace(second, notes=())
    assert model.second_write_changes(first, dropped) == ("notes",)
    moved = dataclasses.replace(
        second, notes=(Note(code="instrument_skipped", message="a made-up note"), *first.notes)
    )
    assert model.second_write_changes(first, moved) == ("notes",)


def test_the_explain_step_runs_under_auto_only_after_a_better_or_worse_primary_case(
    example_results: dict[str, Any],
) -> None:
    assert Results.from_json(example_results).has_difference() is True
    tie = copy.deepcopy(example_results)
    tie["comparisons"][0].update(verdict="TIE", outcome="tie")
    assert Results.from_json(tie).has_difference() is False
    secondary = copy.deepcopy(example_results)
    secondary["comparisons"][0]["primary"] = False
    assert Results.from_json(secondary).has_difference() is False
    described = copy.deepcopy(example_results)
    described["comparisons"][0].update(verdict="LOWER", outcome="lower", primary=False)
    assert Results.from_json(described).has_difference() is False


# ---------------------------------------------------------------------------
# The plot extra
# ---------------------------------------------------------------------------


def test_the_plot_extra_brings_matplotlib() -> None:
    assert api.PLOT_MODULE == "matplotlib"
    assert Refusal("E_PLOT_EXTRA_MISSING", "made-up").exit_code == 3


def test_charts_asked_for_without_the_extra_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    assert api.plot_extra_installed() is False
    with pytest.raises(Refusal, match="the plot extra is not installed") as caught:
        api.require_plot_extra("on")
    assert (caught.value.code, caught.value.exit_code) == ("E_PLOT_EXTRA_MISSING", 3)
    assert api.require_plot_extra("auto") is None
    assert api.require_plot_extra("off") is None


def test_charts_asked_for_with_the_extra_are_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    made_up = types.ModuleType("matplotlib")
    made_up.__spec__ = types.SimpleNamespace(name="matplotlib")  # type: ignore[assignment]
    monkeypatch.setitem(sys.modules, "matplotlib", made_up)
    assert api.plot_extra_installed() is True
    assert api.require_plot_extra("on") is None


def test_asking_for_the_extra_does_not_import_it() -> None:
    before = "matplotlib" in sys.modules
    api.plot_extra_installed()
    assert ("matplotlib" in sys.modules) is before


# ---------------------------------------------------------------------------
# The Python API: render, explain, load_diagnostics, draw
# ---------------------------------------------------------------------------


def test_the_report_page_is_a_reporter_of_the_package() -> None:
    assert registry.BUILTINS["pairbench.reporters"]["html"] == "pairbench.page.html:HtmlReporter"


def test_render_hands_the_reporter_what_it_may_show(
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    example_diagnostics: dict[str, Any],
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, api.ReportOptions]] = []

    class Reporter:
        api_version = 1

        def __init__(self, name: str) -> None:
            self.name = name

        def render(self, results: Results, options: api.ReportOptions) -> str:
            seen.append((self.name, options))
            return f"a made-up {self.name} report"

    monkeypatch.setattr(registry, "reporter", Reporter)
    results = Results.from_json(example_results)
    document = Diagnostics.from_json(example_diagnostics)
    assert pairbench.render(results, "html") == "a made-up html report"
    page = pairbench.render(results, "html", diagnostics=document, folder=tmp_path)
    assert page == "a made-up html report"
    options = api.ReportOptions(cases=("mat*",), verbose=True)
    pairbench.render(results, "terminal", diagnostics=document, options=options)
    assert seen == [
        ("html", api.ReportOptions()),
        ("html", api.ReportOptions(diagnostics=document, folder=tmp_path)),
        ("terminal", api.ReportOptions(cases=("mat*",), verbose=True, diagnostics=document)),
    ]
    assert api.ReportOptions().diagnostics is None
    assert api.ReportOptions().folder is None


def test_explain_hands_the_run_to_the_explain_step_and_prints_its_notes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    example_results: dict[str, Any],
    example_diagnostics: dict[str, Any],
    tmp_path: Path,
) -> None:
    example_diagnostics["notes"] = [{"code": "instrument_skipped", "message": "a made-up note"}]
    document = Diagnostics.from_json(example_diagnostics)
    seen: list[Any] = []

    def explain_run(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics:
        seen.append((experiment, results, out))
        return document

    _module(monkeypatch, "pairbench.diagnose.explain", explain_run=explain_run)
    experiment = _experiment()
    results = Results.from_json(example_results)
    assert pairbench.explain(experiment, results, out=tmp_path) is document
    assert seen == [(experiment, results, tmp_path)]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "pairbench: note: instrument_skipped: a made-up note\n"


def test_a_lock_that_cannot_be_taken_is_recorded_for_every_instrument(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    example_results: dict[str, Any],
    tmp_path: Path,
) -> None:
    refused = Refusal("E_LOCK", "a made-up lock could not be taken")
    assert (refused.code, refused.exit_code) == ("E_LOCK", 4)
    assert api.instrument_reason(refused) == "lock"
    rows = [
        {"name": name, "side": side, "status": "skipped", "reason": "lock", "rc": None}
        for side in ("new", "old")
        for name in ("counters", "stacks")
    ]
    note = {"code": "explain_skipped", "message": "a made-up lock could not be taken"}
    document = Diagnostics.from_json(
        {
            "schema": "pairbench/diagnostics/v1",
            "run": {"id": "run-a"},
            "holds_names": True,
            "instruments": rows,
            "resources": [],
            "counters": [],
            "stacks": [],
            "objects": {"only_in": {}, "differ": []},
            "findings": [],
            "files": {"folded": [], "folded_diff": [], "flame": [], "flame_diff": []},
            "name_map": {},
            "notes": [note],
        }
    )

    def explain_run(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics:
        return document

    _module(monkeypatch, "pairbench.diagnose.explain", explain_run=explain_run)
    returned = pairbench.explain(_experiment(), Results.from_json(example_results), out=tmp_path)
    assert returned is document
    assert returned.state() == DiagnosticsState(status="skipped", reason="lock")
    assert model.NOTE_EXPLAIN_SKIPPED == "explain_skipped"
    assert capsys.readouterr().err == (
        "pairbench: note: explain_skipped: a made-up lock could not be taken\n"
    )
    stated = " ".join((api.ExplainRun.__doc__ or "").split())
    assert "The ``E_LOCK`` that ``OpenExplain`` raised is not passed on" in stated
    session = " ".join((api.ExplainSession.__doc__ or "").split())
    assert "take no lock themselves and never raise ``E_LOCK``" in session


def test_load_diagnostics_hands_the_path_to_the_reader(
    monkeypatch: pytest.MonkeyPatch, example_diagnostics: dict[str, Any], tmp_path: Path
) -> None:
    document = Diagnostics.from_json(example_diagnostics)
    seen: list[Path] = []

    def read_diagnostics(path: Path) -> Diagnostics:
        seen.append(path)
        return document

    _module(monkeypatch, "pairbench.diagnose.document", read_diagnostics=read_diagnostics)
    assert pairbench.load_diagnostics(str(tmp_path / "diagnostics.json")) is document
    assert seen == [tmp_path / "diagnostics.json"]


def test_draw_hands_the_documents_to_the_charts_and_prints_their_notes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    example_results: dict[str, Any],
    example_diagnostics: dict[str, Any],
    tmp_path: Path,
) -> None:
    seen: list[Any] = []

    def draw_charts(results: Results, **options: Any) -> list[Path]:
        note = options.pop("note")
        seen.append((results, options))
        note("charts_not_drawn", "a made-up note")
        return [options["out"] / "charts" / "verdict.svg"]

    _module(monkeypatch, "pairbench.charts", draw_charts=draw_charts)
    results = Results.from_json(example_results)
    document = Diagnostics.from_json(example_diagnostics)
    collected: list[tuple[str, str]] = []
    drawn = pairbench.draw(
        results,
        out=tmp_path,
        diagnostics=document,
        max_round_charts=3,
        note=lambda code, message: collected.append((code, message)),
    )
    assert drawn == [tmp_path / "charts" / "verdict.svg"]
    assert pairbench.draw(results, out=tmp_path) == [tmp_path / "charts" / "verdict.svg"]
    assert seen == [
        (results, {"out": tmp_path, "diagnostics": document, "max_round_charts": 3}),
        (results, {"out": tmp_path, "diagnostics": None, "max_round_charts": 12}),
    ]
    assert collected == [("charts_not_drawn", "a made-up note")]
    assert capsys.readouterr().err == "pairbench: note: charts_not_drawn: a made-up note\n" * 2


# ---------------------------------------------------------------------------
# The seam between the explain step and a side
# ---------------------------------------------------------------------------


def test_what_an_instrument_is() -> None:
    wrap = inspect.signature(api.Instrument.wrap)
    assert [(p.name, p.kind.name, p.annotation) for p in wrap.parameters.values()] == [
        ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("argv", "POSITIONAL_OR_KEYWORD", "Sequence[str]"),
        ("out", "KEYWORD_ONLY", "str"),
        ("tools", "KEYWORD_ONLY", "Mapping[str, str]"),
    ]
    assert wrap.return_annotation == "InstrumentedCommand"
    assert isinstance(vars(api.Instrument)["name"], property)
    assert isinstance(vars(api.Instrument)["tool_files"], property)
    command = api.InstrumentedCommand(argv=("perf", "stat", "--", "made-up-workload"))
    assert (command.env, command.outputs) == ({}, ())


def test_the_session_of_the_explain_launches() -> None:
    assert str(inspect.signature(api.ExplainSession.command)) == (
        "(self, side: 'str') -> 'tuple[str, ...] | None'"
    )
    assert str(inspect.signature(api.ExplainSession.launch)) == (
        "(self, side: 'str', instrument: 'Instrument', artifacts: 'Path') -> 'InstrumentedLaunch'"
    )
    assert str(inspect.signature(api.ExplainSession.close)) == "(self) -> 'None'"
    opened = inspect.signature(api.OpenExplain.__call__)
    assert [(p.name, p.kind.name) for p in opened.parameters.values()] == [
        ("self", "POSITIONAL_OR_KEYWORD"),
        ("experiment", "POSITIONAL_OR_KEYWORD"),
        ("run_id", "KEYWORD_ONLY"),
        ("fingerprints", "KEYWORD_ONLY"),
        ("note", "KEYWORD_ONLY"),
        ("services", "KEYWORD_ONLY"),
    ]
    assert opened.return_annotation == "ExplainSession"
    assert api.DELEGATES["open_explain"][:2] == ("pairbench.runner", "open_explain")
    text = " ".join((api.ExplainSession.__doc__ or "").split())
    assert "a twin and the positive control are never launched" in text
    assert "It gets no witness, no power sampling and no record in a capture" in text


def test_what_an_explain_launch_gives_back(tmp_path: Path) -> None:
    launch = api.InstrumentedLaunch(rc=0, artifacts=tmp_path)
    assert (launch.outputs, launch.timed_out) == ((), False)
    failed = api.InstrumentedLaunch(rc=127, artifacts=tmp_path, timed_out=True)
    assert (failed.rc, failed.timed_out) == (127, True)


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("E_SIDE_CHANGED", "side_changed"),
        ("E_ENGINE_UNSUPPORTED", "launcher_cannot"),
        ("E_LOCK", "lock"),
        ("E_SIDE_UNRESOLVED", "launch_failed"),
        ("E_LAUNCH_FAILED", "launch_failed"),
        ("E_INTERNAL", "launch_failed"),
    ],
)
def test_the_reason_a_refused_explain_launch_stands_for(code: str, reason: str) -> None:
    assert api.instrument_reason(Refusal(code, "made-up")) == reason
    assert reason in model.INSTRUMENT_REASONS


def test_a_launch_can_be_handed_files_of_the_tool(tmp_path: Path) -> None:
    request = api.LaunchRequest(
        run_id="run-a",
        seq=1,
        phase="explain",
        round=0,
        pos=None,
        name="new",
        artifacts=tmp_path,
        tool_files=(tmp_path / "pysampler.py",),
    )
    assert request.tool_files == (tmp_path / "pysampler.py",)
    assert request.wrap_server is None
    assert api.TOOLS_IN_CONTAINER == "/pairbench/tools"
    assert str(inspect.signature(api.ResolvedSide.tool_file_in_side)) == (
        "(self, host: 'Path') -> 'str'"
    )


def test_the_part_that_serves_each_tool_of_the_profile_command() -> None:
    assert dict(api.PROFILE_TOOLS) == {"nsys": "profile", "ncu": "profile", "perf": "record_stacks"}
    assert api.DELEGATES["profile"][:2] == ("pairbench.runner", "record_profiles")
    assert api.DELEGATES["record_stacks"][:2] == ("pairbench.diagnose.explain", "record_stacks")
    assert str(inspect.signature(api.RecordStacks.__call__)) == (
        "(self, run_dir: 'Path', *, tool: 'str' = 'perf', case: 'str | None' = None,"
        " side: 'str | None' = None) -> 'tuple[str, ...]'"
    )


def test_the_function_that_does_everything_the_run_command_does() -> None:
    assert api.DELEGATES["run_to_end"][:2] == ("pairbench.cli.run", "run_to_end")
    assert str(inspect.signature(api.RunToEnd.__call__)) == (
        "(self, experiment: 'Experiment') -> 'int'"
    )
    text = " ".join((api.RunToEnd.__doc__ or "").split())
    for step in ("Results.pending()", "Results.finished(...)", "second_write_changes", "130"):
        assert step in text


# ---------------------------------------------------------------------------
# Nothing in a chart, a flame graph or the report page points outside the file
# ---------------------------------------------------------------------------

SELF_CONTAINED = """<?xml version="1.0"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
  <defs><clipPath id="clip"><rect width="10" height="10"/></clipPath></defs>
  <use xlink:href="#clip"/><a href="#top">top</a>
  <rect clip-path="url(#clip)" style="fill: url('#gradient')"/>
  <image href="data:image/png;base64,AAAA"/>
  <script>var ns = "http://www.w3.org/2000/svg"; if (a.href == b) { a.href = "#zoom"; }</script>
</svg>
"""


def test_a_file_that_points_nowhere_outside_itself() -> None:
    assert model.points_outside(SELF_CONTAINED) == ()
    assert model.points_outside("") == ()
    assert model.points_outside("<p>made-up text about href and src and url</p>") == ()


@pytest.mark.parametrize(
    ("text", "found"),
    [
        (
            '<script src="https://example.invalid/x.js"></script>',
            ('src="https://example.invalid/x.js"',),
        ),
        ('<link rel="stylesheet" href="style.css">', ('href="style.css"',)),
        (
            "<image xlink:href='//example.invalid/a.png'/>",
            ("xlink:href='//example.invalid/a.png'",),
        ),
        ('<img SRC = "made-up.png">', ('SRC = "made-up.png"',)),
        ("<rect style='fill: url(made-up.svg#g)'/>", ("url(made-up.svg#g)",)),
        (
            '<style>@import "fonts.css"; a { background: url("image.png") }</style>',
            ('@import "fonts.css"', 'url("image.png")'),
        ),
        (
            "<style>@import url(https://example.invalid/f.css);</style>",
            (
                "@import url(https://example.invalid/f.css)",
                "url(https://example.invalid/f.css)",
            ),
        ),
        (
            '<script>el.src = "https://example.invalid/t.gif";</script>',
            ('src = "https://example.invalid/t.gif"',),
        ),
        (
            '<a href="#top">top</a><a href="https://example.invalid/">out</a>',
            ('href="https://example.invalid/"',),
        ),
    ],
)
def test_what_points_outside_a_file_is_named(text: str, found: tuple[str, ...]) -> None:
    assert model.points_outside(text) == found


# ---------------------------------------------------------------------------
# What a driver and the doctor command are told
# ---------------------------------------------------------------------------


def test_a_driver_is_told_the_launch_settings_of_its_side(tmp_path: Path) -> None:
    ctx = api.DriverContext(
        run_id="run-a",
        seq=1,
        phase="round",
        round=1,
        name="new",
        side=Side(name="new", kind="image"),
        artifacts=tmp_path,
        artifacts_in_side="/pairbench/artifacts",
    )
    assert ctx.launch == LaunchSettings()
    assert ctx.launch.perf_counters is False
    told = dataclasses.replace(ctx, launch=LaunchSettings(perf_counters=True))
    assert told.launch.perf_counters is True


def test_the_doctor_command_asks_which_instruments_can_run() -> None:
    assert api.DELEGATES["instruments"][:2] == (
        "pairbench.diagnose.instruments",
        "doctor_reports",
    )
    assert str(inspect.signature(api.InstrumentReports.__call__)) == (
        "(self, environ: 'Mapping[str, str] | None' = None) -> 'Mapping[str, DoctorReport]'"
    )
    text = " ".join((api.InstrumentReports.__doc__ or "").split())
    assert "names the setting or the capability that forbids it" in text


def test_a_spec_that_cannot_be_read_counts_as_no_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = types.ModuleType("matplotlib")
    broken.__spec__ = None
    monkeypatch.setitem(sys.modules, "matplotlib", broken)
    assert api.plot_extra_installed() is False
    with pytest.raises(Refusal) as caught:
        api.require_plot_extra("on")
    assert caught.value.code == "E_PLOT_EXTRA_MISSING"


def test_only_the_letters_and_digits_of_a_to_z_stay_in_a_file_name() -> None:
    assert model.safe_file_name("caf\u00e9") == "caf_"
    assert model.safe_file_name("\u0442\u0435\u0441\u0442-1") == "____-1"
    assert model.safe_file_name("\u00b2x") == "_x"


def test_the_sampler_file_is_linted_as_source_of_an_older_python() -> None:
    import tomllib

    settings = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]
    assert settings["ruff"]["lint"]["per-file-ignores"] == {
        "src/pairbench/diagnose/pysampler.py": ["UP", "B905"]
    }
    assert settings["ruff"]["target-version"] == "py311"
