# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The Python API of the package, the plug-in contract and the package metadata."""

from __future__ import annotations

import dataclasses
import inspect
import sys
import tomllib
import types
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api, registry
from pairbench.errors import Refusal
from pairbench.model import (
    STRICT,
    Capture,
    Experiment,
    Plan,
    PluginCounts,
    Results,
    Rule,
    Side,
)

REPO = Path(__file__).resolve().parents[3]


def _signature(function: Any) -> str:
    return str(inspect.signature(function)).replace("'", "").replace('"', "")


def _module(monkeypatch: pytest.MonkeyPatch, name: str, **members: Any) -> types.ModuleType:
    """Put a made-up module in place of one that another part of the package provides."""
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# ---------------------------------------------------------------------------
# Names and signatures
# ---------------------------------------------------------------------------

SIGNATURES: dict[str, str] = {
    "plan": "(experiment: Experiment) -> Plan",
    "run": "(experiment: Experiment, *, out: Path | None = None) -> Capture",
    "analyse": (
        "(captures: Capture | Sequence[Capture], *, rule: str | Rule = strict, "
        "baseline: str | None = None, floors: Floors | None = None, "
        "allow_incomplete: bool = False, allow_mixed_machines: bool = False, "
        "assume_interleaved: bool = False) -> Results"
    ),
    "check_pool": (
        "(captures: Sequence[Capture], *, allow_mixed_machines: bool = False) -> list[Refusal]"
    ),
    "check_matching_pool": "(read: MatchingRead) -> list[Refusal]",
    "refuse_matching_pool": "(read: MatchingRead) -> None",
    "load_capture": (
        "(path: Path | str, *, reader: str | None = None, strict: bool = True) -> list[Capture]"
    ),
    "load_results": "(path: Path | str) -> Results",
    "render": (
        "(results: Results, fmt: Literal[terminal, markdown, json, html], *, "
        "diagnostics: Diagnostics | None = None, folder: Path | None = None, "
        "options: ReportOptions | None = None) -> str"
    ),
    "explain": "(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics",
    "load_diagnostics": "(path: Path | str) -> Diagnostics",
    "draw": (
        "(results: Results, *, out: Path, diagnostics: Diagnostics | None = None, "
        "max_round_charts: int = 12, note: Notify | None = None) -> list[Path]"
    ),
    "fill": "(template: str | Path, results: Results | Mapping[str, Results]) -> str",
    "read_text_matching": (
        "(inputs: str | Path | Sequence[str | Path], *, default_order: str) -> MatchingRead"
    ),
}

SIDE_SIGNATURES: dict[str, str] = {
    "parse": "(text: str) -> Side",
    "image": (
        "(name: str, ref: str, *, args: Sequence[str] = (), "
        "env: Mapping[str, str] | None = None, entrypoint: str | None = None) -> Side"
    ),
    "command": "(name: str, argv: Sequence[str]) -> Side",
    "python": (
        "(name: str, *, interpreter: str | None = None, venv: str | None = None, "
        "conda: str | None = None) -> Side"
    ),
    "serve": (
        "(name: str, image: str, args: Sequence[str], *, "
        "ready: Ready = Ready(http=/health, timeout_s=900.0)) -> Side"
    ),
    "files": "(name: str, paths: Sequence[str], *, format: str | None) -> Side",
}


@pytest.mark.parametrize(("name", "signature"), sorted(SIGNATURES.items()))
def test_a_public_function_has_its_signature(name: str, signature: str) -> None:
    assert _signature(getattr(pairbench, name)) == signature


@pytest.mark.parametrize(("name", "signature"), sorted(SIDE_SIGNATURES.items()))
def test_a_side_constructor_has_its_signature(name: str, signature: str) -> None:
    assert _signature(getattr(Side, name)) == signature


def test_a_capture_from_rows_has_its_signature() -> None:
    assert _signature(Capture.from_rows) == (
        "(rows: Iterable[tuple[int, str, str, float]], *, sides: Sequence[str | Side], "
        "twins: Mapping[str, str] | None = None, "
        "positions: Mapping[tuple[int, str], int] | None = None, "
        "cases: Sequence[Case] | None = None, unit: str = s) -> Capture"
    )


def test_the_names_the_package_exports() -> None:
    assert sorted(pairbench.__all__) == [
        "Capture",
        "Case",
        "CaseSettings",
        "Comparison",
        "ControlSettings",
        "Diagnostics",
        "EnergySettings",
        "Experiment",
        "ExplainSettings",
        "Floors",
        "GateSettings",
        "Launch",
        "LaunchCostSettings",
        "LaunchSettings",
        "LoadSettings",
        "Observation",
        "Plan",
        "PlanRow",
        "PlotSettings",
        "Ready",
        "ReportSettings",
        "Results",
        "Rule",
        "RuleSettings",
        "RunSettings",
        "ServeSpec",
        "Side",
        "__version__",
        "analyse",
        "check_matching_pool",
        "check_pool",
        "draw",
        "explain",
        "fill",
        "load_capture",
        "load_diagnostics",
        "load_results",
        "plan",
        "read_text_matching",
        "refuse_matching_pool",
        "render",
        "run",
    ]
    for name in pairbench.__all__:
        assert hasattr(pairbench, name), name


def test_the_version_is_the_static_version_of_the_package() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == "0.3.1"
    assert pairbench.__version__ == "0.3.1"
    assert "dynamic" not in project


# ---------------------------------------------------------------------------
# Each function hands its work to the module that does it
# ---------------------------------------------------------------------------

DELEGATES: dict[str, tuple[str, str]] = {
    "plan": ("pairbench.plan", "build_plan"),
    "run": ("pairbench.runner", "run_experiment"),
    "analyse": ("pairbench.stats.analyse", "analyse_captures"),
    "refused": ("pairbench.stats.analyse", "refused"),
    "check_pool": ("pairbench.stats.analyse", "pool_refusals"),
    "figures": ("pairbench.results.figures", "with_figures"),
    "load_results": ("pairbench.results.writer", "read_results"),
    "fill": ("pairbench.report.fill", "fill_text"),
    "main": ("pairbench.cli.main", "main"),
    "format_plan": ("pairbench.plan", "format_plan"),
    "look_up": ("pairbench.runner", "look_up_sides"),
    "profile": ("pairbench.runner", "record_profiles"),
    "write_results": ("pairbench.results.writer", "write_results"),
    "selftest": ("pairbench.stats.selftest", "run_selftest"),
    "load_experiment": ("pairbench.config", "load_experiment"),
    "doctor": ("pairbench.cli.doctor", "collect"),
    "checks": ("pairbench.gates.base", "machine_checks"),
    "meter": ("pairbench.energy.sampler", "energy_meter"),
    "facts": ("pairbench.provenance", "facts"),
    "profiler": ("pairbench.profile.nsight", "profiler"),
    "explain": ("pairbench.diagnose.explain", "explain_run"),
    "open_explain": ("pairbench.runner", "open_explain"),
    "load_diagnostics": ("pairbench.diagnose.document", "read_diagnostics"),
    "record_stacks": ("pairbench.diagnose.explain", "record_stacks"),
    "instruments": ("pairbench.diagnose.instruments", "doctor_reports"),
    "draw": ("pairbench.charts", "draw_charts"),
    "findings": ("pairbench.report.terminal", "findings_text"),
    "run_to_end": ("pairbench.cli.run", "run_to_end"),
}


def test_the_functions_other_parts_of_the_package_provide() -> None:
    assert {part: row[:2] for part, row in api.DELEGATES.items()} == DELEGATES
    for _module_name, _name, contract in api.DELEGATES.values():
        assert "__call__" in vars(contract)
        assert contract.__doc__


def test_a_delegate_is_imported_when_it_is_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    def build_plan(experiment: Experiment, **options: Any) -> str:
        return "made-up plan"

    _module(monkeypatch, "pairbench.plan", build_plan=build_plan)
    assert api.delegate("plan") is build_plan


def _experiment() -> Experiment:
    return Experiment(sides=(Side.parse("new=cmd:true"), Side.parse("old=cmd:true")))


def _capture() -> Capture:
    return Capture.from_rows(
        [(1, "new", "matmul", 1.5), (1, "old", "matmul", 3.0)], sides=["new", "old"]
    )


def _results(example_results: dict[str, Any]) -> Results:
    return Results.from_json(example_results)


def test_plan_hands_the_experiment_to_the_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    made = Plan(rows=(), rounds_requested=None, rounds_planned=8, lineup=(), balance=(), launches=0)

    def build_plan(experiment: Experiment, **options: Any) -> Plan:
        seen.append((experiment, options))
        return made

    _module(monkeypatch, "pairbench.plan", build_plan=build_plan)
    experiment = _experiment()
    assert pairbench.plan(experiment) is made
    assert seen == [(experiment, {})]


def test_the_name_plan_stays_the_function_when_the_module_of_that_name_is_set() -> None:
    function = pairbench.plan
    pairbench.plan = types.ModuleType("pairbench.plan")  # type: ignore[assignment]
    assert pairbench.plan is function
    assert callable(pairbench.plan)


def test_run_hands_the_experiment_to_the_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Any] = []
    capture = _capture()

    def run_experiment(experiment: Experiment, *, out: Path | None = None) -> Capture:
        seen.append((experiment, out))
        return capture

    _module(monkeypatch, "pairbench.runner", run_experiment=run_experiment)
    experiment = _experiment()
    assert pairbench.run(experiment, out=tmp_path) is capture
    assert pairbench.run(experiment) is capture
    assert seen == [(experiment, tmp_path), (experiment, None)]


def test_a_refused_run_passes_the_refusal_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_experiment(experiment: Experiment, *, out: Path | None = None) -> Capture:
        raise Refusal("E_SAME_SIDE", "two sides are the same")

    _module(monkeypatch, "pairbench.runner", run_experiment=run_experiment)
    with pytest.raises(Refusal) as caught:
        pairbench.run(_experiment())
    assert caught.value.code == "E_SAME_SIDE"
    assert caught.value.exit_code == 3
    assert caught.value.results is None


def test_a_run_refused_after_its_capture_was_opened_carries_the_results_of_the_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, example_results: dict[str, Any]
) -> None:
    capture = _capture()
    given = dataclasses.replace(_results(example_results), comparisons=())
    seen: list[Any] = []

    def run_experiment(experiment: Experiment, *, out: Path | None = None) -> Capture:
        raise Refusal("E_LAUNCH_FAILED", "a launch failed", detail={"run_dir": str(tmp_path)})

    def refused(captures: Any, refusal: Refusal, *, rule: Rule) -> Results:
        seen.append((list(captures), refusal.code, rule))
        return given

    class Reader:
        name = "jsonl"
        api_version = 1

        def sniff(self, path: Path, head: bytes) -> bool:
            return True

        def read(self, path: Path) -> list[Capture]:
            seen.append(path)
            return [capture]

    def analyse_captures(captures: Any, **options: Any) -> Results:
        raise AssertionError("a refused run is not analysed")

    _module(monkeypatch, "pairbench.runner", run_experiment=run_experiment)
    _analysis_modules(monkeypatch, analyse_captures, refused)
    monkeypatch.setattr(registry, "capture_reader", lambda name: Reader())
    with pytest.raises(Refusal) as caught:
        pairbench.run(_experiment())
    assert caught.value.code == "E_LAUNCH_FAILED"
    assert caught.value.exit_code == 5
    assert caught.value.results is not None
    assert caught.value.results.comparisons == ()
    assert seen == [tmp_path / "capture.jsonl", ([capture], "E_LAUNCH_FAILED", STRICT)]


def _analysis_modules(
    monkeypatch: pytest.MonkeyPatch, analyse_captures: Callable[..., Results], refused: Any = None
) -> None:
    def with_figures(results: Results) -> Results:
        return dataclasses.replace(results, notes=())

    _module(
        monkeypatch, "pairbench.stats.analyse", analyse_captures=analyse_captures, refused=refused
    )
    _module(monkeypatch, "pairbench.results.figures", with_figures=with_figures)


def test_analyse_takes_one_capture_or_several_and_a_rule_by_name(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    seen: list[Any] = []
    given = _results(example_results)

    def analyse_captures(captures: Any, **options: Any) -> Results:
        seen.append((captures, options))
        return given

    _analysis_modules(monkeypatch, analyse_captures)
    registry.register("pairbench.rules", "made-up", _MadeUpRule)
    capture = _capture()
    results = pairbench.analyse(capture)
    assert results.plugins == PluginCounts(loaded=1, failed=0)
    assert results.comparisons == given.comparisons
    pairbench.analyse([capture, capture], rule="made-up", baseline="new", allow_incomplete=True)
    custom = Rule("custom", alpha=0.01)
    pairbench.analyse((capture,), rule=custom)
    defaults = {
        "baseline": None,
        "floors": None,
        "allow_incomplete": False,
        "allow_mixed_machines": False,
        "assume_interleaved": False,
    }
    assert seen == [
        ((capture,), {**defaults, "rule": STRICT}),
        (
            (capture, capture),
            {**defaults, "rule": _MadeUpRule().rule(), "baseline": "new", "allow_incomplete": True},
        ),
        ((capture,), {**defaults, "rule": custom}),
    ]


def test_analyse_prints_the_notes_it_adds_on_standard_error_once(
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pairbench.model import Note

    capture = dataclasses.replace(
        _capture(),
        notes=(
            Note(code="unbalanced", message="made during the run"),
            Note(code="identity_not_checked", message="no socket at /made/up/run/e.sock"),
        ),
    )
    given = dataclasses.replace(
        _results(example_results),
        notes=(
            Note(code="unbalanced", message="made during the run"),
            Note(code="identity_not_checked", message="no socket at e.sock"),
            Note(code="floor_provisional", message="made by the analysis"),
            Note(code="floor_provisional", message="made by the analysis"),
        ),
    )

    def analyse_captures(captures: Any, **options: Any) -> Results:
        return given

    def with_figures(results: Results) -> Results:
        return results

    _module(monkeypatch, "pairbench.stats.analyse", analyse_captures=analyse_captures)
    _module(monkeypatch, "pairbench.results.figures", with_figures=with_figures)
    results = pairbench.analyse(capture)
    assert results.notes == given.notes
    streams = capsys.readouterr()
    assert streams.err == "pairbench: note: floor_provisional: made by the analysis\n"
    assert streams.out == ""


class _MadeUpRule:
    name = "made-up"
    api_version = 1

    def rule(self) -> Rule:
        return Rule("made-up", alpha=0.01)


def test_a_refused_analysis_carries_the_results_of_the_refusal(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    given = dataclasses.replace(_results(example_results), comparisons=())
    seen: list[Any] = []

    def analyse_captures(captures: Any, **options: Any) -> Results:
        raise Refusal("E_GRID", "a cell is missing")

    def refused(captures: Any, refusal: Refusal, *, rule: Rule) -> Results:
        seen.append((captures, refusal.code, rule))
        return given

    _analysis_modules(monkeypatch, analyse_captures, refused)
    capture = _capture()
    with pytest.raises(Refusal) as caught:
        pairbench.analyse(capture)
    assert caught.value.code == "E_GRID"
    assert caught.value.exit_code == 6
    assert caught.value.results is not None
    assert caught.value.results.comparisons == ()
    assert seen == [((capture,), "E_GRID", STRICT)]


def test_an_unknown_rule_name_is_refused_before_any_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def analyse_captures(captures: Any, **options: Any) -> Results:
        raise AssertionError("the analysis must not start")

    _analysis_modules(monkeypatch, analyse_captures)
    registry.set_plugins_enabled(False)
    with pytest.raises(Refusal, match="unknown rule 'made-up'") as caught:
        pairbench.analyse(_capture(), rule="made-up")
    assert caught.value.code == "E_USAGE"


class _Reader:
    api_version = 1

    def __init__(self, name: str, claims: bool, captures: list[Capture]) -> None:
        self.name = name
        self.claims = claims
        self.captures = captures
        self.sniffed: list[tuple[Path, bytes]] = []
        self.read_paths: list[Path] = []

    def sniff(self, path: Path, head: bytes) -> bool:
        self.sniffed.append((path, head))
        return self.claims

    def read(self, path: Path) -> list[Capture]:
        self.read_paths.append(path)
        return self.captures


def _readers(monkeypatch: pytest.MonkeyPatch, **readers: _Reader) -> None:
    monkeypatch.setattr(registry, "names", lambda group: tuple(readers))
    monkeypatch.setattr(registry, "capture_reader", lambda name: readers[name])


def test_load_capture_asks_the_named_reader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture()
    text = _Reader("text", claims=False, captures=[capture])
    _readers(monkeypatch, text=text)
    assert pairbench.load_capture(tmp_path / "rows.txt", reader="text") == [capture]
    assert pairbench.load_capture(str(tmp_path / "rows.txt"), reader="text") == [capture]
    assert text.read_paths == [tmp_path / "rows.txt", tmp_path / "rows.txt"]
    assert text.sniffed == []


def test_load_capture_lets_the_readers_sniff_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file = tmp_path / "rows.txt"
    file.write_bytes(b"## host\nunit=ns\n")
    capture = _capture()
    jsonl = _Reader("jsonl", claims=False, captures=[])
    text = _Reader("text", claims=True, captures=[capture])
    _readers(monkeypatch, jsonl=jsonl, text=text)
    assert pairbench.load_capture(file) == [capture]
    assert jsonl.sniffed == [(file, b"## host\nunit=ns\n")]
    assert jsonl.read_paths == []
    assert text.read_paths == [file]


def test_load_capture_refuses_a_file_no_reader_claims_and_a_file_it_cannot_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file = tmp_path / "rows.txt"
    file.write_bytes(b"made-up")
    _readers(monkeypatch, jsonl=_Reader("jsonl", claims=False, captures=[]))
    with pytest.raises(Refusal, match=r"no capture reader recognises rows\.txt") as unclaimed:
        pairbench.load_capture(file)
    assert unclaimed.value.code == "E_USAGE"
    with pytest.raises(Refusal, match=r"cannot read absent\.txt") as absent:
        pairbench.load_capture(tmp_path / "absent.txt")
    assert absent.value.code == "E_USAGE"
    assert str(tmp_path) not in absent.value.message


def test_load_results_hands_the_path_to_the_reader_of_results(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], tmp_path: Path
) -> None:
    seen: list[Path] = []
    given = _results(example_results)

    def read_results(path: Path) -> Results:
        seen.append(path)
        return given

    _module(monkeypatch, "pairbench.results.writer", read_results=read_results)
    assert pairbench.load_results(str(tmp_path / "results.json")) is given
    assert seen == [tmp_path / "results.json"]


def test_render_asks_the_reporter_of_the_format(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    seen: list[Any] = []

    class Reporter:
        name = "terminal"
        api_version = 1

        def render(self, results: Results, options: api.ReportOptions) -> str:
            seen.append(options)
            return "a made-up report"

    monkeypatch.setattr(registry, "reporter", lambda fmt: {"terminal": Reporter()}[fmt])
    results = _results(example_results)
    assert pairbench.render(results, "terminal") == "a made-up report"
    options = api.ReportOptions(cases=("mat*",), all_cases=True, verbose=True)
    assert pairbench.render(results, "terminal", options=options) == "a made-up report"
    assert seen == [api.ReportOptions(cases=(), all_cases=False, verbose=False), options]


def test_fill_reads_a_path_as_a_file_and_a_text_as_the_template(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], tmp_path: Path
) -> None:
    seen: list[Any] = []

    def fill_text(template: str, results: Any) -> str:
        seen.append((template, results))
        return "filled"

    _module(monkeypatch, "pairbench.report.fill", fill_text=fill_text)
    results = _results(example_results)
    template = tmp_path / "doc.md"
    template.write_text("from a file {{fig:a}}", encoding="utf-8")
    assert pairbench.fill(template, results) == "filled"
    assert pairbench.fill("as text {{fig:a}}", {"other": results}) == "filled"
    assert seen == [
        ("from a file {{fig:a}}", {"": results}),
        ("as text {{fig:a}}", {"other": results}),
    ]


def test_fill_keeps_the_line_endings_of_a_file(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], tmp_path: Path
) -> None:
    seen: list[str] = []

    def fill_text(template: str, results: Any) -> str:
        seen.append(template)
        return template

    _module(monkeypatch, "pairbench.report.fill", fill_text=fill_text)
    template = tmp_path / "doc.md"
    template.write_bytes(b"first\r\nsecond {{fig:a}}\rthird\n")
    expected = "first\r\nsecond {{fig:a}}\rthird\n"
    assert pairbench.fill(template, _results(example_results)) == expected
    assert seen == [expected]


def test_running_the_module_runs_the_command_line(monkeypatch: pytest.MonkeyPatch) -> None:
    from pairbench import __main__ as entry

    seen: list[Any] = []

    def main(argv: Any = None) -> int:
        seen.append(argv)
        return 7

    _module(monkeypatch, "pairbench.cli.main", main=main)
    assert entry.run() == 7
    assert seen == [None]


# ---------------------------------------------------------------------------
# The plug-in contract
# ---------------------------------------------------------------------------


def test_the_version_of_the_plug_in_contract() -> None:
    assert api.API_VERSION == 1


def test_a_driver_keeps_its_published_signatures() -> None:
    assert api.Driver.__annotations__ == {
        "name": "str",
        "api_version": "int",
        "where": "Literal['in_side', 'client']",
    }
    assert _signature(api.Driver.prepare) == (
        "(self, ctx: DriverContext, argv: list[str]) -> Invocation"
    )
    assert (
        _signature(api.Driver.read) == "(self, ctx: DriverContext, artifacts: Path) -> list[Sample]"
    )
    assert _signature(api.Driver.default_primary) == "(self, samples: list[Sample]) -> list[str]"


def test_a_capture_reader_keeps_its_published_signatures() -> None:
    assert api.CaptureReader.__annotations__ == {"name": "str", "api_version": "int"}
    assert _signature(api.CaptureReader.sniff) == "(self, path: Path, head: bytes) -> bool"
    assert _signature(api.CaptureReader.read) == "(self, path: Path) -> list[Capture]"


def test_a_sample_keeps_its_published_fields() -> None:
    assert [f.name for f in dataclasses.fields(api.Sample)] == [
        "case",
        "metric",
        "unit",
        "better",
        "kind",
        "value",
        "n_inner",
        "reducer",
    ]


PROTOCOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "pairbench.side_kinds": ("SideKind", ("resolve", "look_up")),
    "pairbench.drivers": ("Driver", ("prepare", "read", "default_primary")),
    "pairbench.capture_readers": ("CaptureReader", ("sniff", "read")),
    "pairbench.gates": ("Gate", ("check",)),
    "pairbench.rules": ("RuleProvider", ("rule",)),
    "pairbench.reporters": ("Reporter", ("render",)),
    "pairbench.launchers": ("Launcher", ("resolve", "look_up", "start")),
}


@pytest.mark.parametrize(("group", "expected"), sorted(PROTOCOLS.items()))
def test_a_group_has_one_protocol_with_its_methods(
    group: str, expected: tuple[str, tuple[str, ...]]
) -> None:
    name, methods = expected
    protocol = api.PROTOCOLS[group]
    assert protocol.__name__ == name
    assert getattr(protocol, "_is_protocol", False) is True
    assert api.REQUIRED_METHODS[group] == methods
    assert protocol.__doc__
    for method in methods:
        function = getattr(protocol, method)
        assert callable(function)
        signature = inspect.signature(function)
        assert signature.return_annotation is not inspect.Signature.empty, method
        for parameter in list(signature.parameters.values())[1:]:
            assert parameter.annotation is not inspect.Parameter.empty, (method, parameter.name)
    for attribute in ("name", "api_version"):
        assert attribute in protocol.__annotations__ or hasattr(protocol, attribute), attribute


def test_every_protocol_of_the_contract_says_what_it_requires() -> None:
    protocols = [
        value
        for value in vars(api).values()
        if isinstance(value, type)
        and getattr(value, "_is_protocol", False)
        and value.__module__ == api.__name__
    ]
    assert len(protocols) >= 30
    for protocol in protocols:
        assert protocol.__doc__ and protocol.__doc__.strip(), protocol.__name__


def test_a_resolved_side_tells_the_command_it_runs_and_how_many_rounds_it_holds() -> None:
    members = {
        name
        for name, value in vars(api.ResolvedSide).items()
        if isinstance(value, property) or callable(value)
    }
    assert {
        "side",
        "command",
        "engine",
        "rounds_available",
        "cannot_repeat",
        "identify",
        "artifacts_in_side",
        "tool_file_in_side",
        "launch",
        "close",
    } <= members
    assert _signature(api.ResolvedSide.launch) == "(self, request: LaunchRequest) -> LaunchOutcome"
    assert [f.name for f in dataclasses.fields(api.LaunchRequest)] == [
        "run_id",
        "seq",
        "phase",
        "round",
        "pos",
        "name",
        "artifacts",
        "argv",
        "env",
        "load",
        "second",
        "tool_files",
        "wrap_server",
    ]
    assert [f.name for f in dataclasses.fields(api.LaunchOutcome)] == [
        "rc",
        "timing",
        "timed_out",
        "cpu_s",
        "samples",
        "result_file",
        "pid",
        "usage",
        "second_pid",
        "cannot_repeat",
        "notes",
    ]
    assert [f.name for f in dataclasses.fields(api.LaunchNote)] == ["code", "message", "cases"]


def test_the_read_only_look_up_is_a_method_beside_resolve() -> None:
    assert (
        _signature(api.SideKind.resolve) == "(self, side: Side, ctx: SideContext) -> ResolvedSide"
    )
    assert _signature(api.SideKind.look_up) == "(self, side: Side, ctx: SideContext) -> SideLookup"
    assert _signature(api.Launcher.look_up) == (
        "(self, spec: ServeSpec, ctx: SideContext) -> SideLookup"
    )
    assert [f.name for f in dataclasses.fields(api.SideLookup)] == [
        "status",
        "identity",
        "fingerprint",
        "message",
    ]
    assert api.SideLookup.__annotations__["status"] == "LookupStatus"
    assert api.LookupStatus.__args__ == ("identified", "absent", "unchecked")  # type: ignore[attr-defined]
    unchecked = api.SideLookup(status="unchecked", message="no container engine could be reached")
    assert (unchecked.identity, unchecked.fingerprint) == ({}, "")


# ---------------------------------------------------------------------------
# The package metadata
# ---------------------------------------------------------------------------


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_project_metadata() -> None:
    project = _pyproject()["project"]
    assert project["name"] == "pairbench"
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "Apache-2.0"
    assert project["dependencies"] == []
    assert project["scripts"] == {"pairbench": "pairbench.cli.main:main"}
    assert project["urls"] == {
        "Documentation": "https://eugo.io/docs/pairbench/latest/",
        "Changelog": "https://eugo.io/docs/pairbench/latest/changelog/",
        "Issues": "https://github.com/eugo-inc/pairbench/issues",
        "Source": "https://github.com/eugo-inc/pairbench",
    }
    assert project["keywords"] == [
        "benchmarking",
        "performance-testing",
        "statistics",
        "containers",
        "docker",
        "podman",
        "llm-inference",
        "gpu",
        "mcp",
        "ai-agents",
        "performance",
        "optimization",
        "benchmark",
    ]
    assert project["readme"] == "README.md"


def test_the_extras() -> None:
    assert _pyproject()["project"]["optional-dependencies"] == {
        "gpu": ["nvidia-ml-py"],
        "mcp": ["mcp>=1.21.1,<3"],
        "llm": ["guidellm", "aiperf"],
        "micro": ["pytest-benchmark"],
        "plot": ["matplotlib>=3.7"],
    }


def test_the_built_files_are_listed_explicitly() -> None:
    build = _pyproject()["tool"]["hatch"]["build"]
    assert build["targets"]["wheel"]["only-include"] == ["src/pairbench", "skills/pairbench"]
    assert build["targets"]["wheel"]["sources"] == {
        "src": "",
        "skills/pairbench": "pairbench/skill",
    }
    assert build["targets"]["sdist"]["only-include"] == [
        "src/pairbench",
        "skills/pairbench",
        "LICENSE",
        "NOTICE",
        "README.md",
        "pyproject.toml",
    ]
    assert "include" not in build["targets"]["sdist"]


def test_the_typing_marker_and_the_schemas_are_package_data() -> None:
    package = resources.files("pairbench")
    assert package.joinpath("py.typed").is_file()
    for name in ("capture", "results", "config", "diagnostics"):
        assert package.joinpath("results", "schema", f"{name}.v1.schema.json").is_file()


def test_the_test_settings_name_every_marker() -> None:
    options = _pyproject()["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests"]
    assert "--strict-markers" in options["addopts"]
    assert sorted(marker.split(":")[0].split("(")[0] for marker in options["markers"]) == [
        "delivery",
        "needs_engine",
        "needs_gpu",
        "needs_plot",
        "needs_tool",
        "slow",
    ]
