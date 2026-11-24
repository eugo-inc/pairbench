# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every command but ``run`` through the entry point: exit codes, text codes and streams."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api, registry
from pairbench.api import DoctorReport
from pairbench.errors import (
    EXIT_CHECK_FAILED,
    EXIT_FIGURE_MISSING,
    EXIT_MACHINE,
    EXIT_OK,
    EXIT_SIDE,
    EXIT_USAGE,
    Refusal,
)
from pairbench.model import GateRecord, Results
from pairbench.results import writer

from .conftest import COMMAND_NOTE, DOCS_LINE, refusal_text

Cli = Callable[..., Any]


@pytest.fixture
def results_file(tmp_path: Path, example_results: dict[str, Any]) -> Path:
    """A run folder holding the example results, written by the writer."""
    folder = tmp_path / "run"
    writer.write_results(Results.from_json(example_results), folder)
    return folder / "results.json"


# ---------------------------------------------------------------------------
# plan and run --print-plan
# ---------------------------------------------------------------------------

PLAN_ARGS = (
    "--side",
    "new=cmd:true",
    "--side",
    "old=cmd:true x",
    "--baseline",
    "old",
    "--rounds",
    "4",
)


@pytest.mark.parametrize("form", [("plan",), ("run", "--print-plan")])
def test_the_plan_is_printed_and_nothing_is_touched(
    form: tuple[str, ...],
    cli: Cli,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def no_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the plan launched a run")

    monkeypatch.setattr(pairbench, "run", no_run)

    result = cli(*form, *PLAN_ARGS, "--out", str(tmp_path / "here"))

    assert result.code == EXIT_OK
    assert "# lineup: new, new~same, old, old~same" in result.out
    assert "round\tpos\tname\tside\ttwin_of" in result.out
    assert result.err == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("form", [("plan",), ("run", "--print-plan")])
def test_the_plan_refuses_plots_on_without_the_extra(
    form: tuple[str, ...], cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "plot_extra_installed", lambda: False)

    refused = cli(*form, *PLAN_ARGS, "--plots", "on")
    noted = cli(*form, *PLAN_ARGS, "--plots", "auto")

    assert refused.code == EXIT_SIDE
    assert refused.err.startswith("E_PLOT_EXTRA_MISSING: ")
    assert refused.out == ""
    assert noted.code == EXIT_OK
    assert "# lineup: new, new~same, old, old~same" in noted.out


def test_a_side_name_holding_bytes_that_are_not_utf8_is_refused(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    planned = cli("plan", "--side", "\udcff=cmd:true", "--side", "b=cmd:false")
    run = cli("run", "--side", "\udcff=cmd:true", "--side", "b=cmd:false", "--out", "r")

    for refused in (planned, run):
        assert refused.code == EXIT_USAGE
        assert refused.err == refusal_text(
            "E_USAGE: side name '\\\\udcff' is refused: it is not UTF-8 text"
        )
        assert refused.out == ""
    assert list(tmp_path.iterdir()) == []


def test_the_plan_of_identical_sides_is_refused(cli: Cli) -> None:
    result = cli("plan", "--side", "a=cmd:true", "--side", "b=cmd:true")

    assert result.code == EXIT_SIDE
    assert result.err.startswith("E_SAME_SIDE: ")
    assert result.out == ""


def test_the_plan_refuses_sides_that_are_result_files(cli: Cli) -> None:
    result = cli("plan", "--side", "a=file:x*.json", "--side", "b=file:y*.json")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: sides that are result files are compared")


WAIT_WITHOUT_CHECKS = refusal_text(
    "E_USAGE: --wait-quiet needs --gates warn or enforce: --gates off skips the checks "
    "before the run, the quiet wait among them"
)


@pytest.mark.parametrize("form", [("plan",), ("run", "--print-plan")])
def test_the_plan_refuses_a_quiet_wait_with_the_checks_off(form: tuple[str, ...], cli: Cli) -> None:
    result = cli(*form, *PLAN_ARGS, "--gates", "off", "--wait-quiet")

    assert result.code == EXIT_USAGE
    assert result.err == WAIT_WITHOUT_CHECKS
    assert result.out == ""


def test_a_run_refuses_a_quiet_wait_with_the_checks_off_before_its_folder(
    cli: Cli, tmp_path: Path
) -> None:
    folder = tmp_path / "run"
    result = cli("run", *PLAN_ARGS, "--gates", "off", "--wait-quiet", "--out", str(folder))

    assert result.code == EXIT_USAGE
    assert result.err == WAIT_WITHOUT_CHECKS
    assert not folder.exists()


def test_the_python_api_refuses_a_quiet_wait_with_the_checks_off() -> None:
    from pairbench.config import flag_config, load_experiment

    flags = flag_config(
        {"--gates": "off", "--wait-quiet": True}, sides=("new=cmd:true", "old=cmd:true x")
    )
    experiment = load_experiment(None, environ={}, flags=flags)
    with pytest.raises(Refusal) as refused:
        pairbench.plan(experiment)
    assert refusal_text(refused.value.line) == WAIT_WITHOUT_CHECKS


def test_a_quiet_wait_with_the_checks_on_is_planned(cli: Cli) -> None:
    for mode in ("warn", "enforce"):
        result = cli("plan", *PLAN_ARGS, "--gates", mode, "--wait-quiet")
        assert (result.code, result.err) == (EXIT_OK, "")


def test_a_config_file_and_a_flag_both_reach_the_plan(cli: Cli, tmp_path: Path) -> None:
    config_file = tmp_path / "bench.toml"
    config_file.write_text(
        '[sides.new]\ncmd = "true"\n[sides.old]\ncmd = "true x"\nbaseline = true\n',
        encoding="utf-8",
    )

    result = cli("plan", "--config", str(config_file), "--rounds", "6")

    assert result.code == EXIT_OK
    assert "# rounds: requested 6" in result.out


def test_the_config_variable_and_an_override_both_reach_the_plan(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "bench.toml"
    config_file.write_text(
        '[run]\nrounds = 4\n[sides.first]\ncmd = "true"\n'
        '[sides.second]\ncmd = "true x"\nbaseline = true\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAIRBENCH_CONFIG", str(config_file))
    monkeypatch.setenv("PAIRBENCH__RUN__ROUNDS", "6")

    result = cli("plan")

    assert (result.code, result.err) == (EXIT_OK, "")
    assert "# lineup: first, first~same, second, second~same\n" in result.out
    assert "# rounds: requested 6" in result.out


def test_a_side_flag_makes_a_result_file_side_of_the_config_a_command(
    cli: Cli, tmp_path: Path
) -> None:
    config_file = tmp_path / "bench.toml"
    config_file.write_text(
        '[sides.first]\nfile = ["first-*.json"]\n[sides.second]\ncmd = "true x"\nbaseline = true\n',
        encoding="utf-8",
    )

    result = cli("plan", "--config", str(config_file), "--side", "first=cmd:true")

    assert (result.code, result.err) == (EXIT_OK, "")
    assert "# lineup: first, first~same, second, second~same\n" in result.out


def test_two_different_baselines_are_refused(cli: Cli) -> None:
    result = cli("plan", *PLAN_ARGS, "--baseline", "new")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: --baseline names more than one side: old, new")


def test_an_unknown_set_key_is_a_config_error(cli: Cli) -> None:
    result = cli("plan", *PLAN_ARGS, "--set", "run.colour=x")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_CONFIG: ")


def test_a_flag_and_a_set_that_disagree_are_refused(cli: Cli) -> None:
    result = cli("plan", *PLAN_ARGS, "--set", "run.rounds=6")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: a flag and --set give run.rounds different values")


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_compare(
    monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def load_capture(path: Any, *, reader: Any = None, strict: bool = True) -> list[Any]:
        calls.append({"load": str(path), "reader": reader, "strict": strict})
        return [object()]

    def analyse(captures: Any, **kwargs: Any) -> Results:
        calls.append({"analyse": len(captures), **kwargs})
        return Results.from_json(example_results)

    monkeypatch.setattr(pairbench, "load_capture", load_capture)
    monkeypatch.setattr(pairbench, "analyse", analyse)
    return calls


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "E_USAGE: compare needs capture files or --side NAME=file:GLOB"),
        (
            ("a.jsonl", "--side", "x=file:y"),
            "E_USAGE: give capture files or --side NAME=file:GLOB, not both",
        ),
        (
            ("--side", "x=file:y", "--reader", "text"),
            "E_USAGE: --reader reads capture files; result files take --driver",
        ),
        (
            ("--side", "x=file:y", "--lenient"),
            "E_USAGE: --lenient reads text capture files; result files take --driver",
        ),
        (
            ("a.jsonl", "--driver", "gbench"),
            "E_USAGE: --driver reads result files given with --side",
        ),
        (
            ("--side", "x=file:y", "--side", "z=file:w"),
            "E_USAGE: result files given with --side need --driver NAME",
        ),
    ],
)
def test_compare_refuses_inputs_that_do_not_fit(
    args: tuple[str, ...], message: str, cli: Cli, fake_compare: list[dict[str, Any]]
) -> None:
    result = cli("compare", *args)

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text(message)
    assert result.out == ""


def test_compare_refuses_sides_that_launch(cli: Cli) -> None:
    result = cli("compare", "--side", "x=file:y", "--side", "z=cmd:true", "--driver", "gbench")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text(
        "E_USAGE: file sides cannot be mixed with other kinds of side"
    )


def test_compare_pools_every_capture_with_the_strict_rule_by_default(
    cli: Cli, fake_compare: list[dict[str, Any]]
) -> None:
    result = cli("compare", "a.jsonl", "b.jsonl", "--allow-mixed-machines")

    assert result.code == EXIT_OK
    assert fake_compare[0] == {"load": "a.jsonl", "reader": None, "strict": True}
    assert fake_compare[1] == {"load": "b.jsonl", "reader": None, "strict": True}
    analysed = fake_compare[2]
    assert analysed["analyse"] == 2
    assert analysed["rule"] == "strict"
    assert analysed["allow_mixed_machines"] is True
    assert analysed["allow_incomplete"] is False
    assert "matmul" in result.out
    assert result.err == ""


def test_compare_reads_leniently_with_lenient(cli: Cli, fake_compare: list[dict[str, Any]]) -> None:
    result = cli("compare", "a.txt", "--reader", "text", "--lenient")

    assert result.code == EXIT_OK
    assert fake_compare[0] == {"load": "a.txt", "reader": "text", "strict": False}


def test_compare_hands_the_analysis_flags_through(
    cli: Cli, fake_compare: list[dict[str, Any]]
) -> None:
    result = cli("compare", "a.jsonl", "--allow-incomplete", "--assume-interleaved")

    assert result.code == EXIT_OK
    analysed = fake_compare[1]
    assert analysed["allow_incomplete"] is True
    assert analysed["assume_interleaved"] is True
    assert analysed["allow_mixed_machines"] is False


def test_compare_case_filters_what_is_shown(
    cli: Cli, fake_compare: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[Any] = []

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        shown.append(kwargs.get("options"))
        return "x"

    monkeypatch.setattr(pairbench, "render", render)

    result = cli("compare", "a.jsonl", "--case", "mat*", "--case", "fft")

    assert result.code == EXIT_OK
    assert result.out == "x\n"
    assert shown[0].cases == ("mat*", "fft")


def test_fail_on_counts_primary_cases_only(
    cli: Cli,
    fake_compare: list[dict[str, Any]],
    example_results: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses

    loaded = Results.from_json(example_results)
    primary = loaded.comparisons[0]
    secondary = dataclasses.replace(primary, case="fft", primary=False, outcome="worse")
    both = dataclasses.replace(loaded, comparisons=(primary, secondary))
    monkeypatch.setattr(pairbench, "analyse", lambda captures, **kwargs: both)

    secondary_only = cli("compare", "a.jsonl", "--fail-on", "worse")
    primary_too = cli("compare", "a.jsonl", "--fail-on", "worse", "--fail-on", "better")

    assert secondary_only.code == EXIT_OK
    assert secondary_only.err == ""
    assert primary_too.code == EXIT_CHECK_FAILED
    assert primary_too.err == "pairbench: --fail-on better: case matmul of side new against old\n"


def test_compare_without_out_writes_nothing(
    cli: Cli, fake_compare: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = cli("compare", "a.jsonl")

    assert result.code == EXIT_OK
    assert list(tmp_path.iterdir()) == []


def test_compare_with_out_and_json_writes_the_folder_and_prints_the_document(
    cli: Cli, fake_compare: list[dict[str, Any]], tmp_path: Path
) -> None:
    out = tmp_path / "pooled"

    result = cli("compare", "a.jsonl", "--out", str(out), "--json")

    assert result.code == EXIT_OK
    printed = json.loads(result.out)
    assert printed == json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert (out / "results.md").is_file()
    assert "matmul" in result.err


def test_compare_with_out_on_a_file_is_refused_as_usage(
    cli: Cli, fake_compare: list[dict[str, Any]], tmp_path: Path
) -> None:
    (tmp_path / "taken").write_text("kept\n")

    result = cli("compare", "a.jsonl", "--out", str(tmp_path / "taken"))

    assert result.code == EXIT_USAGE
    assert "E_USAGE: the results folder taken is a file, not a folder" in result.err
    assert "E_INTERNAL" not in result.err


def test_compare_fail_on_exits_1(cli: Cli, fake_compare: list[dict[str, Any]]) -> None:
    result = cli("compare", "a.jsonl", "--fail-on", "better")

    assert result.code == EXIT_CHECK_FAILED
    assert "--fail-on better: case matmul" in result.err


def test_compare_hands_a_refusal_through_with_its_exit_code(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, fake_compare: list[dict[str, Any]]
) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise Refusal("E_POOL_MACHINE", "x")

    monkeypatch.setattr(pairbench, "analyse", refused)

    result = cli("compare", "a.jsonl", "b.jsonl")

    assert result.code == 6
    assert result.err == refusal_text("E_POOL_MACHINE: x")


def test_compare_of_unreadable_result_files_writes_the_results_it_refuses(
    cli: Cli, tmp_path: Path
) -> None:
    for name in ("new1.json", "old1.json"):
        (tmp_path / name).write_text("not json\n", encoding="utf-8")
    out = tmp_path / "out"

    result = cli(
        "compare",
        "--side",
        f"new=file:{tmp_path}/new*.json",
        "--side",
        f"old=file:{tmp_path}/old*.json",
        "--driver",
        "gbench",
        "--out",
        out,
        "--json",
    )

    assert result.code == 5
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: new1.json is not valid JSON (line 1, column 1): Expecting value"
    )
    written = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert json.loads(result.out) == written
    assert (out / "results.md").is_file()


def _gbench_file(names: list[str]) -> dict[str, Any]:
    entry = {"run_type": "iteration", "repetitions": 1, "repetition_index": 0, "threads": 1}
    return {
        "benchmarks": [
            {**entry, "name": n, "run_name": n, "iterations": 10, "real_time": 2.0, "cpu_time": 1.0}
            | {"time_unit": "ms"}
            for n in names
        ]
    }


def _nvbench_file(states: list[str]) -> dict[str, Any]:
    def summary(tag: str, value: str) -> dict[str, Any]:
        return {"tag": tag, "data": [{"name": "value", "type": "float64", "value": value}]}

    gpu, cpu = summary("nv/cold/time/gpu/mean", "0.5"), summary("nv/cold/time/cpu/mean", "0.75")
    return {
        "benchmarks": [
            {"name": "bench", "states": [{"name": s, "summaries": [gpu, cpu]} for s in states]}
        ]
    }


@pytest.mark.parametrize(
    ("driver", "doc", "shown"),
    [
        (
            "gbench",
            _gbench_file(
                ["BM_Load/file:///made/up/home/a.gguf", "BM_Load/file://localhost/made/up/b.gguf"]
            ),
            [
                "BM_Load/file://a.gguf",
                "BM_Load/file://a.gguf/cpu_time",
                "BM_Load/file://b.gguf",
                "BM_Load/file://b.gguf/cpu_time",
            ],
        ),
        (
            "nvbench",
            _nvbench_file(["File=file:///made/up/home/a.bin", "File=sqlite:////made/up/b.db"]),
            [
                "bench/File=file://a.bin",
                "bench/File=file://a.bin/cpu_time",
                "bench/File=sqlite:///b.db",
                "bench/File=sqlite:///b.db/cpu_time",
            ],
        ),
    ],
)
def test_compare_records_a_case_named_after_a_file_address_by_the_name_its_driver_gives(
    cli: Cli, tmp_path: Path, driver: str, doc: dict[str, Any], shown: list[str]
) -> None:
    for name in ("new1.json", "new2.json", "old1.json", "old2.json"):
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")

    result = cli(
        "compare",
        "--side",
        f"new=file:{tmp_path}/new*.json",
        "--side",
        f"old=file:{tmp_path}/old*.json",
        "--driver",
        driver,
        "--out",
        tmp_path / "out",
        "--json",
    )

    assert result.code == 0
    assert result.err.endswith(COMMAND_NOTE)
    assert [case["id"] for case in json.loads(result.out)["cases"]] == shown


SERVING_FIXTURES = Path(__file__).parents[2] / "fixtures" / "serving" / "guidellm"


def test_compare_reads_serving_result_files_at_the_level_levels_names(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    sides = (
        "--side",
        f"new=file:{SERVING_FIXTURES}/guidellm-c1.json",
        "--side",
        f"old=file:{SERVING_FIXTURES}/guidellm-c2.json",
        "--driver",
        "guidellm",
    )

    without = cli("compare", *sides)
    read = cli("compare", *sides, "--levels", "1")

    assert without.code == 2
    assert without.err == COMMAND_NOTE + refusal_text(
        "E_USAGE: the guidellm driver reads a result file as one load level; give "
        "workload.levels exactly one level for it"
    )
    assert read.code == 0
    assert "c1/ttft_ms_median" in read.out


def test_compare_refuses_levels_without_result_files(cli: Cli) -> None:
    result = cli("compare", "a.jsonl", "--levels", "1")

    assert result.code == 2
    assert result.err == refusal_text(
        "E_USAGE: --levels names the load level of result files given with --side"
    )


def test_compare_gives_medians_too_far_apart_no_verdict_and_judges_the_rest(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    lines = ["## host", "unit=s", "sides=new old"]
    for r in range(1, 17):
        lines.append("pass_order=new old" if r % 2 else "pass_order=old new")
        for side, x, y in (("new", "1e300", "2"), ("old", "1e-10", "1")):
            lines += [f"suite\t{side}\t{r}\tx\t{x}", f"suite\t{side}\t{r}\ty\t{y}"]
    rows = tmp_path / "rows.txt"
    rows.write_text("\n".join(lines) + "\n", encoding="utf-8")

    shown = cli("compare", str(rows), "--reader", "text")
    printed = cli("compare", str(rows), "--reader", "text", "--json")

    assert (shown.code, printed.code) == (EXIT_OK, EXIT_OK)
    assert (
        "NO VERDICT (the medians 1e+300 and 1e-10 are too far apart for their ratio to be a "
        "finite number)"
    ) in shown.out
    x, y = json.loads(printed.out)["comparisons"]
    assert (x["case"], x["outcome"], x["reason"], x["ratio"]) == (
        "x",
        "no_verdict",
        "too_far_apart",
        None,
    )
    assert (x["subject_median"], x["baseline_median"]) == (1e300, 1e-10)
    assert (y["case"], y["ratio"], y["reason"]) == ("y", 2.0, "no_floor")


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_report_prints_the_terminal_report(cli: Cli, results_file: Path) -> None:
    result = cli("report", str(results_file))

    assert result.code == EXIT_OK
    assert "matmul" in result.out
    assert result.err == ""


def test_report_json_is_the_results_document(cli: Cli, results_file: Path) -> None:
    result = cli("report", str(results_file), "--format", "json")

    assert result.code == EXIT_OK
    assert json.loads(result.out) == json.loads(results_file.read_text(encoding="utf-8"))


def test_report_html_is_a_page(cli: Cli, results_file: Path) -> None:
    result = cli("report", str(results_file), "--format", "html")

    assert result.code == EXIT_OK
    assert result.out.lstrip().lower().startswith("<!doctype html>")


def test_report_hands_over_the_diagnostics_of_the_folder(
    cli: Cli,
    results_file: Path,
    example_diagnostics: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (results_file.parent / "diagnostics.json").write_text(
        json.dumps(example_diagnostics), encoding="utf-8"
    )
    seen: list[Any] = []
    real = pairbench.render

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        seen.append(kwargs.get("diagnostics"))
        return real(results, fmt, **kwargs)

    monkeypatch.setattr(pairbench, "render", render)

    assert cli("report", str(results_file)).code == EXIT_OK
    assert seen[0] is not None
    assert seen[0].state().status == "written"


def test_report_json_does_not_read_the_diagnostics_it_does_not_show(
    cli: Cli, results_file: Path
) -> None:
    (results_file.parent / "diagnostics.json").write_text("x", encoding="utf-8")

    printed = cli("report", str(results_file), "--format", "json")
    terminal = cli("report", str(results_file))
    drawn = cli("report", str(results_file), "--format", "json", "--plots", "auto")

    assert printed.code == EXIT_OK
    assert json.loads(printed.out) == json.loads(results_file.read_text(encoding="utf-8"))
    assert printed.err == ""
    for refused in (terminal, drawn):
        assert refused.code == EXIT_USAGE
        assert refused.err.startswith("E_USAGE: ")
        assert refused.out == ""


def test_report_hands_the_display_flags_to_the_reporter(
    cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        seen.append((fmt, kwargs["options"]))
        return "x"

    monkeypatch.setattr(pairbench, "render", render)

    plain = cli("report", str(results_file))
    flagged = cli(
        "report",
        str(results_file),
        "--format",
        "markdown",
        "--case",
        "mat*",
        "--case",
        "fft",
        "--all",
        "--verbose",
    )

    assert plain.code == EXIT_OK
    assert flagged.code == EXIT_OK
    assert flagged.out == "x\n"
    assert seen[0][0] == "terminal"
    assert (seen[0][1].cases, seen[0][1].all_cases, seen[0][1].verbose) == ((), False, False)
    assert seen[1][0] == "markdown"
    assert (seen[1][1].cases, seen[1][1].all_cases, seen[1][1].verbose) == (
        ("mat*", "fft"),
        True,
        True,
    )


def test_report_plots_on_without_the_extra_is_refused(
    cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "plot_extra_installed", lambda: False)

    result = cli("report", str(results_file), "--plots", "on")

    assert result.code == EXIT_SIDE
    assert result.err.startswith("E_PLOT_EXTRA_MISSING: ")
    assert result.out == ""


def test_report_plots_draws_into_the_folder_and_leaves_the_results_file(
    cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = results_file.read_bytes()
    seen: list[Results] = []

    def draw(results: Results, *, out: Path, **kwargs: Any) -> list[Path]:
        chart = out / "charts" / "verdict.svg"
        chart.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text("<svg/>", encoding="utf-8")
        return [chart]

    real = pairbench.render

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        seen.append(results)
        return real(results, fmt, **kwargs)

    monkeypatch.setattr(pairbench, "draw", draw)
    monkeypatch.setattr(pairbench, "render", render)

    result = cli("report", str(results_file), "--plots", "auto")

    assert result.code == EXIT_OK
    assert seen[0].artifacts.charts == ("charts/verdict.svg",)
    assert results_file.read_bytes() == before


def test_report_of_a_missing_file_is_refused(cli: Cli, tmp_path: Path) -> None:
    result = cli("report", str(tmp_path / "results.json"))

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: ")
    assert str(tmp_path) not in result.err


# ---------------------------------------------------------------------------
# fill
# ---------------------------------------------------------------------------

CRLF_TEMPLATE = b"# Title\r\n\r\nThe ratio is {{fig:matmul.new_vs_old.ratio}}.\r\nEnd\r\n"
CRLF_FILLED = b"# Title\r\n\r\nThe ratio is 0.80x.\r\nEnd\r\n"


def test_fill_keeps_the_line_endings_of_the_template(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)
    out = tmp_path / "doc.md"

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out))

    assert result.code == EXIT_OK
    assert out.read_bytes() == CRLF_FILLED
    assert result.out == ""


class ClosedBinaryPipe:
    """Standard output whose reader has gone, with a binary buffer that fails the same way."""

    class Buffer:
        def write(self, data: bytes) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    buffer = Buffer()

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        return None


class Collected:
    """Standard error that keeps what is written to it."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def write(self, text: str) -> int:
        self.lines.append(text)
        return len(text)

    def flush(self) -> None:
        return None


def test_fill_to_a_reader_that_has_gone_exits_0_quietly(
    results_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pairbench.cli.main import main

    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)
    monkeypatch.setattr(sys, "stdout", ClosedBinaryPipe())
    errors: list[str] = []
    monkeypatch.setattr(sys, "stderr", Collected(errors))

    code = main(["fill", str(template), "--results", str(results_file)])

    assert (code, "".join(errors)) == (EXIT_OK, "")


def test_fill_check_passes_when_the_output_is_current(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)
    out = tmp_path / "doc.md"
    out.write_bytes(CRLF_FILLED)

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out), "--check")

    assert result.code == EXIT_OK
    assert out.read_bytes() == CRLF_FILLED


def test_fill_check_fails_on_a_changed_line_ending(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)
    out = tmp_path / "doc.md"
    out.write_bytes(CRLF_FILLED.replace(b"\r\n", b"\n"))

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out), "--check")

    assert result.code == EXIT_CHECK_FAILED
    assert result.err == "pairbench: fill --check: doc.md does not match its results\n"
    assert out.read_bytes() == CRLF_FILLED.replace(b"\r\n", b"\n")


def test_fill_check_fails_on_a_missing_output(cli: Cli, results_file: Path, tmp_path: Path) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)

    result = cli(
        "fill",
        str(template),
        "--results",
        str(results_file),
        "-o",
        str(tmp_path / "doc.md"),
        "--check",
    )

    assert result.code == EXIT_CHECK_FAILED
    assert result.err == "pairbench: fill --check: doc.md does not exist\n"


def test_fill_check_escapes_control_characters_of_the_output_name(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(CRLF_TEMPLATE)
    out = tmp_path / "doc\x1b[8m\n.md"

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out), "--check")

    assert result.code == EXIT_CHECK_FAILED
    assert result.err == "pairbench: fill --check: doc\\x1b[8m\\n.md does not exist\n"


def test_fill_of_a_missing_figure_exits_7_and_writes_nothing(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(b"{{fig:nothing.here}}\n")
    out = tmp_path / "doc.md"

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out))

    assert result.code == EXIT_FIGURE_MISSING
    assert result.err.startswith("E_FIGURE_MISSING: ")
    assert not out.exists()


def test_fill_with_named_results(cli: Cli, results_file: Path, tmp_path: Path) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(b"{{fig:a/matmul.new_vs_old.verdict}} {{fig:b/matmul.new_vs_old.ratio}}\n")
    out = tmp_path / "doc.md"

    result = cli(
        "fill",
        str(template),
        "--results",
        f"a={results_file}",
        "--results",
        f"b={results_file}",
        "-o",
        str(out),
    )

    assert result.code == EXIT_OK
    assert out.read_bytes() == b"FASTER 0.80x\n"


def test_fill_without_results_writes_a_template_without_tokens_as_it_is(
    cli: Cli, tmp_path: Path
) -> None:
    template = tmp_path / "README.in.md"
    template.write_bytes(b"# Title\r\n\r\nThe figures are waiting for a run.\r\n")
    out = tmp_path / "README.md"

    written = cli("fill", str(template), "-o", str(out))
    checked = cli("fill", str(template), "-o", str(out), "--check")

    assert written.code == EXIT_OK
    assert out.read_bytes() == template.read_bytes()
    assert checked.code == EXIT_OK


def test_fill_without_results_refuses_every_token_as_missing(cli: Cli, tmp_path: Path) -> None:
    template = tmp_path / "README.in.md"
    template.write_bytes(b"{{fig:a.b}} {{fig:c.d}}\n")

    result = cli("fill", str(template), "-o", str(tmp_path / "README.md"))

    assert result.code == EXIT_FIGURE_MISSING
    assert result.err == refusal_text(
        "E_FIGURE_MISSING: 2 figures are missing from the results: a.b, c.d"
    )
    assert not (tmp_path / "README.md").exists()


def test_fill_without_output_writes_the_document_on_stdout(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(b"ratio {{fig:matmul.new_vs_old.ratio}}\n")

    result = cli("fill", str(template), "--results", str(results_file))

    assert result.code == EXIT_OK
    assert result.out == "ratio 0.80x\n"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            ("doc.in.md", "--results", "r.json", "--check"),
            "E_USAGE: --check compares with the output file: give -o OUT",
        ),
        (
            ("doc.in.md", "--results", "r.json", "--results", "s.json"),
            "E_USAGE: --results gives more than one results file without a name",
        ),
        (
            ("doc.in.md", "--results", "a=r.json", "--results", "a=s.json"),
            "E_USAGE: --results gives the name 'a'",
        ),
    ],
)
def test_fill_refuses_arguments_that_do_not_fit(
    args: tuple[str, ...], message: str, cli: Cli
) -> None:
    result = cli("fill", *args)

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text(message)


def test_fill_refuses_a_template_that_is_not_utf8(
    cli: Cli, results_file: Path, tmp_path: Path
) -> None:
    template = tmp_path / "doc.in.md"
    template.write_bytes(b"\xff\xfe{{fig:matmul.new_vs_old.ratio}}\n")
    out = tmp_path / "doc.md"

    result = cli("fill", str(template), "--results", str(results_file), "-o", str(out))

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: the template doc.in.md is not UTF-8 text")
    assert result.out == ""
    assert not out.exists()


def test_fill_reads_a_results_path_holding_an_equals_sign_as_one_unnamed_file(
    cli: Cli, results_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a=r.json").write_bytes(results_file.read_bytes())
    template = tmp_path / "doc.in.md"
    template.write_bytes(b"ratio {{fig:matmul.new_vs_old.ratio}}\n")

    result = cli("fill", "doc.in.md", "--results", "a=r.json")

    assert result.code == EXIT_OK
    assert result.out == "ratio 0.80x\n"
    assert result.err == ""


# ---------------------------------------------------------------------------
# selftest, schema
# ---------------------------------------------------------------------------


def test_selftest_runs_every_control_and_exits_0(cli: Cli) -> None:
    result = cli("selftest")

    assert result.code == EXIT_OK
    assert result.out.startswith("pass  ")
    assert "FAIL" not in result.out
    assert result.err.startswith("pairbench: selftest: all ")


def test_a_failed_control_makes_selftest_exit_1(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> None:
    from pairbench.stats import selftest

    real = selftest.run_selftest

    def one_fails() -> list[Any]:
        found = list(real())
        import dataclasses

        found[0] = dataclasses.replace(found[0], passed=False, detail="x")
        return found

    monkeypatch.setattr(selftest, "run_selftest", one_fails)

    result = cli("selftest")

    assert result.code == EXIT_CHECK_FAILED
    assert "FAIL  " in result.out
    assert "controls failed" in result.err


@pytest.mark.parametrize(
    ("status", "passed", "detail"),
    [
        ("ok", True, "ratio 2.0 on both cases"),
        ("not_run", False, "the positive control is not_run"),
    ],
)
def test_the_live_check_needs_the_positive_control_to_pass(
    status: str,
    passed: bool,
    detail: str,
    example_results: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses

    from pairbench.cli import selftest as selftest_command

    loaded = Results.from_json(example_results)
    base = dataclasses.replace(
        loaded.comparisons[0], subject="subject", baseline="baseline", primary=True, ratio=2.0
    )
    comparisons = tuple(dataclasses.replace(base, case=case) for case in ("live-a", "live-b"))
    positive = dataclasses.replace(loaded.controls.positive, status=status)
    analysed = dataclasses.replace(
        loaded,
        comparisons=comparisons,
        controls=dataclasses.replace(loaded.controls, positive=positive),
    )
    monkeypatch.setattr(pairbench, "run", lambda experiment, *, out: object())
    monkeypatch.setattr(pairbench, "analyse", lambda capture, **kwargs: analysed)

    outcome = selftest_command.live_check()

    assert (outcome.passed, outcome.detail) == (passed, detail)


@pytest.mark.parametrize("name", ["capture", "results", "config", "diagnostics"])
def test_schema_prints_each_schema(name: str, cli: Cli) -> None:
    result = cli("schema", name)

    assert result.code == EXIT_OK
    document = json.loads(result.out)
    assert document["$schema"].startswith("https://json-schema.org/")
    assert document["$id"] == f"pairbench/{name}/v1"
    assert result.err == ""


def test_schema_of_an_unknown_name_is_refused(cli: Cli) -> None:
    result = cli("schema", "plan")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: pairbench schema: argument name: invalid choice")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


class Reporting:
    """A plug-in that reports to the doctor."""

    def __init__(self, report: DoctorReport | Exception) -> None:
        self.report = report

    def doctor(self) -> DoctorReport:
        if isinstance(self.report, Exception):
            raise self.report
        return self.report


@pytest.fixture
def quiet_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The doctor's sources replaced: no program is run and no plug-in asked."""
    from pairbench.cli import doctor

    monkeypatch.setattr(
        doctor,
        "_tools",
        lambda: [
            {"name": "perf", "found": True, "version": "9.9", "note": ""},
            {"name": "docker", "found": False, "version": None, "note": ""},
        ],
    )
    reports = {
        "pairbench.side_kinds": {
            "image": Reporting(
                DoctorReport("degraded", "x", {"leftover_containers": ["pairbench-x"]})
            )
        },
        "pairbench.drivers": {
            "lines": Reporting(DoctorReport("ok", "ready")),
            "vllm-bench": Reporting(DoctorReport("experimental", "no real fixture")),
        },
        "pairbench.gates": {"quiet": Reporting(RuntimeError("x"))},
        "pairbench.capture_readers": {"jsonl": object()},
        "pairbench.reporters": {},
        "pairbench.launchers": {},
    }
    monkeypatch.setattr(registry, "names", lambda group: sorted(reports[group]))
    monkeypatch.setattr(registry, "get", lambda group, name: reports[group][name])
    monkeypatch.setattr(doctor, "_instruments", lambda environ: {})


def test_doctor_json_reports_every_part(cli: Cli, quiet_doctor: None) -> None:
    result = cli("doctor", "--json")

    assert result.code == EXIT_OK
    document = json.loads(result.out)
    assert document["tool"]["name"] == "pairbench"
    assert document["tools"][0] == {"name": "perf", "found": True, "version": "9.9", "note": ""}
    assert document["gates"]["quiet"] == {
        "status": "unavailable",
        "summary": "could not be asked (RuntimeError)",
        "detail": {},
    }
    assert document["capture_readers"]["jsonl"]["status"] == "ok"
    assert document["experimental"] == ["vllm-bench"]
    assert document["leftover_containers"] == ["pairbench-x"]
    assert "gates quiet: could not be asked (RuntimeError)" in document["degraded"]
    assert "side_kinds image: x" in document["degraded"]
    assert set(document["plot_extra"]) == {"installed"}
    assert result.err == ""


def test_doctor_lines_name_what_is_degraded(cli: Cli, quiet_doctor: None) -> None:
    result = cli("doctor")

    assert result.code == EXIT_OK
    assert "  perf: found 9.9" in result.out
    assert "  docker: not found" in result.out
    assert "experimental drivers: vllm-bench" in result.out
    assert "containers left behind by runs:\n  pairbench-x" in result.out


def test_doctor_exits_0_when_nothing_can_be_asked(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pairbench.cli import doctor

    def broken(environ: Any = None) -> Any:
        raise OSError("x")

    monkeypatch.setattr(doctor, "collect", broken)

    result = cli("doctor", "--json")

    assert result.code == EXIT_OK
    assert json.loads(result.out) == {"error": "the machine could not be described (OSError)"}


# The reason a plug-in failed to load, with a newline and backslashes, as an import gives it.
BROKEN_REASON = (
    "ImportError: Unable to import required dependencies:\nnumpy: cannot load C:\\lib\\x1b.dll"
)
BROKEN_PREFIX = "pairbench: plug-in failed to load: pairbench.drivers broken: "


@pytest.mark.parametrize("flags", [("--json",), ()])
def test_doctor_keeps_a_failed_plug_in_as_it_is_in_json_and_escapes_its_line(
    flags: tuple[str, ...], cli: Cli, quiet_doctor: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = registry.LoadFailure(
        group="pairbench.drivers", name="broken", origin="entry_point", reason=BROKEN_REASON
    )
    monkeypatch.setattr(registry, "failures", lambda: (failure,))

    result = cli("doctor", *flags)

    assert result.code == EXIT_OK
    if flags:
        assert json.loads(result.out)["plugins"]["failed"] == [BROKEN_PREFIX + BROKEN_REASON]
    else:
        assert (
            "  "
            + BROKEN_PREFIX
            + "ImportError: Unable to import required dependencies:\\n"
            + "numpy: cannot load C:\\\\lib\\\\x1b.dll"
            + "\n"
        ) in result.out


class _RegisteringEntry:
    """An installed entry point whose module registers a plug-in named with an escape
    character that fails to load."""

    name = "outer"
    value = "made_up_module:thing"
    dist = type("Dist", (), {"name": "made-up-dist"})()

    def load(self) -> Any:
        registry.register("pairbench.rules", "in\x1bner", object())
        raise AssertionError("register refuses the plug-in")


# The failure of the registration inside the entry point, as it is.
NESTED_FAILURE = (
    "pairbench: plug-in failed to load: pairbench.rules in\x1bner: "
    "it declares api_version None; this pairbench speaks 1"
)
# The same failure as its line shows it, escaped once.
NESTED_SHOWN = (
    "pairbench: plug-in failed to load: pairbench.rules in\\x1bner: "
    "it declares api_version None; this pairbench speaks 1"
)


@pytest.mark.parametrize("flags", [("--json",), ()])
def test_doctor_keeps_a_nested_plug_in_failure_as_it_is_in_json_and_escapes_it_once(
    flags: tuple[str, ...], cli: Cli, quiet_doctor: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.metadata

    def entry_points(*, group: str) -> list[Any]:
        return [_RegisteringEntry()] if group == "pairbench.rules" else []

    monkeypatch.setattr(importlib.metadata, "entry_points", entry_points)
    registry.load_plugins()

    result = cli("doctor", *flags)

    outer = "pairbench: plug-in failed to load: pairbench.rules outer: PluginError: "
    assert result.code == EXIT_OK
    shown = NESTED_SHOWN
    if flags:
        assert json.loads(result.out)["plugins"]["failed"] == [
            NESTED_FAILURE,
            outer + NESTED_FAILURE,
        ]
    else:
        assert f"  {shown}\n" in result.out
        assert f"  {outer}{shown}\n" in result.out


ODD_DETAIL: dict[Any, Any] = {
    "where": Path("x"),
    "set": {9, 1},
    ("a", "b"): 1,
    "ratio": float("nan"),
    "kept": [1, "y", None, True, 0.5],
}


@pytest.mark.parametrize("flags", [("--json",), ()])
def test_doctor_exits_0_when_a_plug_in_reports_values_json_cannot_hold(
    flags: tuple[str, ...], cli: Cli, quiet_doctor: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = {"odd": Reporting(DoctorReport("ok", "x", ODD_DETAIL))}
    monkeypatch.setattr(
        registry, "names", lambda group: sorted(reports) if group == "pairbench.drivers" else []
    )
    monkeypatch.setattr(registry, "get", lambda group, name: reports[name])

    result = cli("doctor", *flags)

    assert result.code == EXIT_OK
    assert result.err == ""
    if flags:
        assert json.loads(result.out)["drivers"]["odd"] == {
            "status": "ok",
            "summary": "x",
            "detail": {
                "where": "x",
                "set": [1, 9],
                "('a', 'b')": 1,
                "ratio": "nan",
                "kept": [1, "y", None, True, 0.5],
            },
        }
    else:
        assert "  odd: ok: x" in result.out


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


class FakeGate:
    def __init__(self, status: str, message: str = "") -> None:
        self.status = status
        self.message = message
        self.contexts: list[Any] = []

    def check(self, ctx: Any) -> GateRecord:
        self.contexts.append(ctx)
        detail = {"message": self.message} if self.message else {}
        return GateRecord(name="cpus", mode="enforce", status=self.status, detail=detail)  # type: ignore[arg-type]


@pytest.fixture
def no_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pairbench.cli.gate._machine", lambda environ: (False, False))


def test_gate_check_passes_and_prints_its_status(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    gate = FakeGate("pass")
    monkeypatch.setattr(registry, "gate", lambda name: gate)

    result = cli("gate", "check", "--cpus", "2-3")

    assert result.code == EXIT_OK
    assert result.out == "check cpus: pass\n"
    assert gate.contexts[0].mode == "enforce"
    assert gate.contexts[0].launch.cpus == "2-3"


@pytest.mark.parametrize(
    ("status", "line"),
    [
        ("fail", "E_GATE_FAILED: check cpus failed"),
        ("degraded", "E_GATE_UNAVAILABLE: check cpus could not run fully"),
    ],
)
def test_gate_check_that_does_not_pass_exits_4(
    status: str, line: str, cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: FakeGate(status, "mixed core types"))

    result = cli("gate", "check", "--cpus", "0-7")

    assert result.code == EXIT_MACHINE
    assert result.out == ""
    assert result.err.splitlines() == [
        f"pairbench: check cpus: {status}: mixed core types",
        f"{line}: mixed core types",
        DOCS_LINE + line.split(":", 1)[0].lower(),
    ]


def test_gate_check_json_prints_the_record(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: FakeGate("pass"))

    result = cli("gate", "check", "--cpus", "1", "--json")

    assert result.code == EXIT_OK
    assert json.loads(result.out)["status"] == "pass"


@pytest.mark.parametrize("cpus", ["7-4", "a-b", "1,,2"])
def test_gate_check_refuses_a_cpu_list_that_is_malformed_before_checking(
    cpus: str, cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    gate = FakeGate("degraded", "no such CPUs")
    monkeypatch.setattr(registry, "gate", lambda name: gate)

    result = cli("gate", "check", "--cpus", cpus)

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: --cpus: ")
    assert gate.contexts == []


def test_gate_check_names_a_cpu_range_that_runs_backwards(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: FakeGate("pass"))

    result = cli("gate", "check", "--cpus", "0,7-4")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: --cpus: the CPU range 7-4 runs backwards")


def test_gate_check_needs_cpus_or_a_readiness_key(cli: Cli, no_machine: None) -> None:
    result = cli("gate", "check")

    assert result.code == EXIT_USAGE
    assert result.out == ""
    assert result.err == refusal_text(
        "E_USAGE: gate check has nothing to check: give --cpus LIST, or set gates.stop_file, "
        "gates.min_gpu_free_mib or gates.check_locks"
    )


def test_gate_check_takes_no_command(cli: Cli, no_machine: None) -> None:
    result = cli("gate", "check", "--cpus", "1", "--", "true")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: gate check takes no command after --")


def test_gate_wait_quiet_runs_the_command_and_returns_its_exit_code(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: FakeGate("pass"))

    result = cli("gate", "wait-quiet", "--", sys.executable, "-c", "import sys; sys.exit(3)")

    assert result.code == 3


def test_gate_wait_quiet_on_a_busy_machine_does_not_run_the_command(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, no_machine: None, tmp_path: Path
) -> None:
    monkeypatch.setattr(registry, "gate", lambda name: FakeGate("fail", "busy"))
    marker = tmp_path / "ran"

    result = cli("gate", "wait-quiet", "--", "touch", str(marker))

    assert result.code == EXIT_MACHINE
    assert result.err.splitlines()[-2:] == [
        "E_GATE_FAILED: the command was not run: busy",
        DOCS_LINE + "e_gate_failed",
    ]
    assert not marker.exists()


def test_gate_wait_quiet_needs_a_command(cli: Cli, no_machine: None) -> None:
    result = cli("gate", "wait-quiet")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_USAGE: gate wait-quiet needs a command after --")


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(api.PROFILE_TOOLS))
def test_profile_goes_through_the_named_part_and_lists_the_files(
    tool: str, cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Path, dict[str, Any]]] = []
    real = api.delegate

    def delegate(part: str) -> Any:
        if part in api.PROFILE_TOOLS.values():

            def record(run_dir: Path, **kwargs: Any) -> list[str]:
                calls.append((part, run_dir, kwargs))
                return [f"profiles/{tool}.out"]

            return record
        return real(part)

    monkeypatch.setattr(api, "delegate", delegate)

    result = cli("profile", "--from", str(results_file), "--tool", tool, "--case", "matmul")

    assert result.code == EXIT_OK
    assert calls == [
        (
            api.PROFILE_TOOLS[tool],
            results_file.parent,
            {"tool": tool, "case": "matmul", "side": None},
        )
    ]
    assert result.out == f"profiles/{tool}.out\n"
    written = json.loads(results_file.read_text(encoding="utf-8"))
    assert written["artifacts"]["profiles"] == [f"profiles/{tool}.out"]


def test_a_missing_profiler_is_refused_with_exit_3(
    cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = api.delegate

    def delegate(part: str) -> Any:
        if part in api.PROFILE_TOOLS.values():

            def record(run_dir: Path, **kwargs: Any) -> list[str]:
                raise Refusal("E_PROFILER_MISSING", "nsys is not installed")

            return record
        return real(part)

    monkeypatch.setattr(api, "delegate", delegate)
    before = results_file.read_bytes()

    result = cli("profile", "--from", str(results_file), "--tool", "nsys")

    assert result.code == EXIT_SIDE
    assert result.err == refusal_text("E_PROFILER_MISSING: nsys is not installed")
    assert results_file.read_bytes() == before


def test_profile_needs_a_tool_it_knows(cli: Cli, results_file: Path) -> None:
    result = cli("profile", "--from", str(results_file), "--tool", "gprof")

    assert result.code == EXIT_USAGE
    assert "argument --tool: invalid choice: 'gprof'" in result.err


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


def test_mcp_without_the_server_is_refused_with_the_extra_named(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "pairbench.mcp.server", None)

    result = cli("mcp")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: the tool server is not available here")
    assert "install pairbench[mcp]" in result.err


def test_mcp_whose_server_finds_no_extra_when_it_starts_is_refused_with_the_extra_named(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    def main(*, allow_run: bool) -> int:
        raise ModuleNotFoundError("No module named 'mcp'", name="mcp")

    server = types.ModuleType("pairbench.mcp.server")
    server.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pairbench.mcp.server", server)

    result = cli("mcp")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text(
        "E_USAGE: the tool server is not available here (mcp): install pairbench[mcp]"
    )


def test_mcp_server_failing_on_another_import_is_an_internal_error(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    def main(*, allow_run: bool) -> int:
        raise ModuleNotFoundError("No module named 'x'", name="x")

    server = types.ModuleType("pairbench.mcp.server")
    server.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pairbench.mcp.server", server)

    result = cli("mcp")

    assert result.code == 8
    assert result.err.startswith("E_INTERNAL: ModuleNotFoundError")


@pytest.mark.parametrize(("args", "allowed"), [((), False), (("--allow-run",), True)])
def test_mcp_starts_the_server_with_the_run_tools_only_when_allowed(
    args: tuple[str, ...], allowed: bool, cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    import types

    seen: list[bool] = []

    def main(*, allow_run: bool) -> int:
        seen.append(allow_run)
        return 0

    server = types.ModuleType("pairbench.mcp.server")
    server.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pairbench.mcp.server", server)

    result = cli("mcp", *args)

    assert result.code == EXIT_OK
    assert seen == [allowed]


# ---------------------------------------------------------------------------
# skill
# ---------------------------------------------------------------------------


@pytest.fixture
def skill_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A made-up skill, as the source tree would carry it."""
    source = tmp_path / "source" / "pairbench"
    (source / "reference").mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: pairbench\n---\n", encoding="utf-8")
    (source / "reference" / "flags.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr("pairbench.cli.skill.skill_source", lambda: source)
    return source


def test_skill_install_copies_the_skill_into_the_folder(
    cli: Cli, skill_tree: Path, tmp_path: Path
) -> None:
    target = tmp_path / "skills"

    result = cli("skill", "install", "--dir", str(target))

    assert result.code == EXIT_OK
    assert result.out == "pairbench/SKILL.md\npairbench/reference/flags.md\n"
    assert (target / "pairbench" / "SKILL.md").read_bytes() == (
        skill_tree / "SKILL.md"
    ).read_bytes()


def test_skill_install_needs_a_folder(cli: Cli, skill_tree: Path) -> None:
    result = cli("skill", "install")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: skill install needs --dir PATH")


def test_skill_install_leaves_an_installed_skill_alone(
    cli: Cli, skill_tree: Path, tmp_path: Path
) -> None:
    target = tmp_path / "skills"
    (target / "pairbench").mkdir(parents=True)
    (target / "pairbench" / "SKILL.md").write_text("mine\n", encoding="utf-8")

    result = cli("skill", "install", "--dir", str(target))

    assert result.code == EXIT_USAGE
    assert "already exists" in result.err
    assert (target / "pairbench" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_the_skill_of_this_tree_or_package_is_found_when_it_exists(repo_root: Path) -> None:
    from pairbench.cli import skill

    if not (repo_root / "skills" / "pairbench" / "SKILL.md").is_file():
        with pytest.raises(Refusal) as refused:
            skill.skill_source()
        assert refused.value.code == "E_INTERNAL"
        return
    found = skill.skill_source()
    assert (found / "SKILL.md").is_file()


def test_no_command_reads_a_config_file_by_itself(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pairbench.toml").write_text(
        '[sides.a]\ncmd = "true"\n[sides.b]\ncmd = "true x"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PAIRBENCH_CONFIG", raising=False)
    assert "PAIRBENCH_CONFIG" not in os.environ

    result = cli("plan")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text("E_CONFIG: the config declares no side")


# ---------------------------------------------------------------------------
# --no-plugins
# ---------------------------------------------------------------------------

NO_PLUGINS_ARGS: dict[str, tuple[str, ...]] = {
    "plan": ("plan", *PLAN_ARGS),
    "run": ("run", "--print-plan", *PLAN_ARGS),
    "compare": ("compare", "a.jsonl"),
    "report": ("report", "RESULTS"),
    "profile": ("profile", "--from", "RESULTS", "--tool", "perf"),
    "doctor": ("doctor",),
    "mcp": ("mcp",),
}

# The first public function each command calls once its plug-in switch is set.
NO_PLUGINS_SEAM: dict[str, str] = {
    "plan": "plan",
    "run": "plan",
    "compare": "load_capture",
    "report": "load_results",
    "profile": "load_results",
    "doctor": "",
    "mcp": "",
}


@pytest.mark.parametrize("flag", [(), ("--no-plugins",)])
@pytest.mark.parametrize("name", sorted(NO_PLUGINS_ARGS))
def test_no_plugins_turns_third_party_plug_ins_off_for_the_command(
    name: str,
    flag: tuple[str, ...],
    cli: Cli,
    results_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    enabled: list[bool] = []

    def seen(*args: Any, **kwargs: Any) -> Any:
        enabled.append(registry.plugins_enabled())
        raise Refusal("E_USAGE", "x")

    seam = NO_PLUGINS_SEAM[name]
    if seam:
        monkeypatch.setattr(pairbench, seam, seen)
    elif name == "doctor":
        monkeypatch.setattr("pairbench.cli.doctor.collect", seen)
    else:
        server = types.ModuleType("pairbench.mcp.server")
        server.main = seen  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pairbench.mcp.server", server)
    args = [str(results_file) if a == "RESULTS" else a for a in NO_PLUGINS_ARGS[name]]

    result = cli(*args, *flag)

    assert enabled == [not flag]
    if name == "doctor":
        assert result.code == EXIT_OK
        assert result.out == "the machine could not be described (Refusal)\n"
    else:
        assert result.code == EXIT_USAGE
        assert result.err == refusal_text("E_USAGE: x")
    assert registry.plugins_enabled() is True


def test_the_same_baseline_named_twice_is_one_baseline(cli: Cli) -> None:
    result = cli("plan", *PLAN_ARGS, "--baseline", "old")

    assert result.code == EXIT_OK
    assert "# lineup: new, new~same, old, old~same" in result.out
    assert result.err == ""


def test_profile_keeps_the_files_listed_before_and_lists_each_once(
    cli: Cli, results_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made = [["profiles/a.out"], ["profiles/b.out", "profiles/a.out"]]
    real = api.delegate

    def delegate(part: str) -> Any:
        if part in api.PROFILE_TOOLS.values():
            return lambda run_dir, **kwargs: made.pop(0)
        return real(part)

    monkeypatch.setattr(api, "delegate", delegate)

    first = cli("profile", "--from", str(results_file), "--tool", "perf")
    second = cli("profile", "--from", str(results_file), "--tool", "perf")

    assert (first.code, second.code) == (EXIT_OK, EXIT_OK)
    assert second.out == "profiles/b.out\nprofiles/a.out\n"
    written = json.loads(results_file.read_text(encoding="utf-8"))
    assert written["artifacts"]["profiles"] == ["profiles/a.out", "profiles/b.out"]


def test_a_selftest_line_escapes_the_detail_of_a_failed_control() -> None:
    from pairbench.cli import selftest

    failed = selftest.Outcome("C9", "made-up control", False, "raised X: a\x1bb\\c\u2028d")
    assert selftest._line(failed) == "FAIL  C9   made-up control: raised X: a\\x1bb\\\\c\\u2028d"
