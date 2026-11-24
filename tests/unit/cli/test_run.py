# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench run`` from the first write to the report page, with the measuring steps faked."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api, config
from pairbench.cli import main as entry
from pairbench.cli import run as run_command
from pairbench.cli.common import NOTE_COMMAND_SHOWN, command_shown_message
from pairbench.errors import EXIT_CHECK_FAILED, EXIT_INTERRUPTED, EXIT_OK, EXIT_SIDE, Refusal
from pairbench.model import (
    KIND_CMD,
    NOTE_CHARTS_FAILED,
    NOTE_EXPLAIN_FAILED,
    NOTE_PAGE_FAILED,
    Experiment,
    Results,
    second_write_changes,
)

from .conftest import CHART_NOTE, EXPLAIN_NOTE, Calls, Writes, refusal_text

SIDES = ("new=cmd:true", "old=cmd:true")
# The library's own drawing step, kept before the fakes stand in for it.
LIBRARY_DRAW = pairbench.draw


def experiment(out: Path | None, *sets: str, **flags: Any) -> Experiment:
    """An experiment of two command sides, the run folder named, with these settings."""
    given = {"--out": str(out) if out is not None else None, **flags}
    built = config.flag_config(
        {flag: value for flag, value in given.items() if value is not None},
        sides=SIDES,
        baseline="old",
    )
    return config.load_experiment(None, environ={}, flags=built, sets=sets)


def on_disk(folder: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    return loaded


def test_a_whole_run_writes_twice_and_the_second_write_changes_only_its_keys(
    fakes: Calls, writes: Writes, run_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_command.run_to_end(experiment(run_folder, "explain.mode=always"))

    assert code == EXIT_OK
    first, second = writes.documents
    assert first.diagnostics.status == "pending"
    assert first.plots.status == "pending"
    assert second_write_changes(first, second) == ()
    assert second.diagnostics.status == "written"
    assert second.plots.status == "drawn"
    assert second.artifacts.charts == ("charts/verdict.svg",)
    assert second.artifacts.diagnostics == "diagnostics.json"
    assert second.artifacts.html == "report.html"
    assert second.artifacts.profiles == ("profiles/new/stacks.folded", "profiles/new/flame.svg")
    assert second.notes == (EXPLAIN_NOTE, CHART_NOTE)
    assert (run_folder / "report.html").is_file()
    assert on_disk(run_folder) == second.to_json()
    captured = capsys.readouterr()
    assert "matmul" in captured.out
    # The stand-in for the drawing step prints nothing; the run prints only the command note.
    assert captured.err == f"pairbench: note: {NOTE_COMMAND_SHOWN}: {command_shown_message()}\n"


def test_the_run_folder_the_settings_name_is_handed_to_the_runner(
    fakes: Calls, writes: Writes, run_folder: Path
) -> None:
    run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=off"))

    assert fakes.run[0]["out"] == run_folder


def test_without_a_named_folder_the_runner_picks_one(
    fakes: Calls, writes: Writes, run_folder: Path
) -> None:
    run_command.run_to_end(experiment(None, "explain.mode=off", "plots.mode=off"))

    assert fakes.run[0]["out"] is None
    assert len(writes.documents) == 2


def test_fail_on_a_primary_outcome_exits_1_and_names_the_case(
    fakes: Calls, writes: Writes, run_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_command.run_to_end(
        experiment(run_folder, "explain.mode=off", "plots.mode=off", **{"--fail-on": ["better"]})
    )

    assert code == EXIT_CHECK_FAILED
    assert "--fail-on better: case matmul of side new against" in capsys.readouterr().err
    assert len(writes.documents) == 2


def test_fail_on_an_outcome_no_case_has_exits_0(
    fakes: Calls, writes: Writes, run_folder: Path
) -> None:
    code = run_command.run_to_end(
        experiment(run_folder, "explain.mode=off", "plots.mode=off", **{"--fail-on": ["worse"]})
    )

    assert code == EXIT_OK


def test_explain_off_and_plots_off_say_off(fakes: Calls, writes: Writes, run_folder: Path) -> None:
    run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=off"))

    second = writes.documents[-1]
    assert second.diagnostics.status == "off"
    assert second.plots.status == "off"
    assert fakes.explain == []
    assert fakes.draw == []
    assert second.artifacts.diagnostics is None
    assert second.artifacts.charts == ()


def test_explain_auto_without_a_difference_is_skipped_with_its_reason(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    results: Results,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Results, "has_difference", lambda self: False)

    run_command.run_to_end(experiment(run_folder, "explain.mode=auto", "plots.mode=off"))

    second = writes.documents[-1]
    assert second.diagnostics.status == "skipped"
    assert second.diagnostics.reason == "mode_auto_no_difference"
    assert fakes.explain == []


def test_explain_auto_with_a_difference_runs_the_explain_step(
    fakes: Calls, writes: Writes, run_folder: Path
) -> None:
    run_command.run_to_end(experiment(run_folder, "explain.mode=auto", "plots.mode=off"))

    assert len(fakes.explain) == 1
    assert fakes.explain[0].diagnostics.status == "pending"
    assert writes.documents[-1].diagnostics.status == "written"


def test_a_failed_explain_step_is_a_loud_note_and_the_run_exits_0(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("x")

    monkeypatch.setattr(pairbench, "explain", broken)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=always", "plots.mode=off"))

    assert code == EXIT_OK
    first, second = writes.documents
    assert second.diagnostics.status == "failed"
    assert [note.code for note in second.notes] == [NOTE_EXPLAIN_FAILED]
    assert "RuntimeError" in second.notes[0].message
    assert second.comparisons == first.comparisons
    assert second_write_changes(first, second) == ()
    assert NOTE_EXPLAIN_FAILED in capsys.readouterr().err


def test_charts_without_the_extra_record_the_reason(
    fakes: Calls, writes: Writes, run_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pairbench, "draw", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "plot_extra_installed", lambda: False)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=auto"))

    assert code == EXIT_OK
    second = writes.documents[-1]
    assert second.plots.status == "not_drawn"
    assert second.plots.reason == "extra_missing"


def test_charts_with_nothing_to_draw_record_no_reason(
    fakes: Calls, writes: Writes, run_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pairbench, "draw", lambda *args, **kwargs: [])
    monkeypatch.setattr(api, "plot_extra_installed", lambda: True)

    run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=auto"))

    second = writes.documents[-1]
    assert second.plots.status == "not_drawn"
    assert second.plots.reason is None


def test_plots_on_without_the_extra_is_refused_before_any_launch(
    fakes: Calls, writes: Writes, run_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "plot_extra_installed", lambda: False)

    with pytest.raises(Refusal) as refused:
        run_command.run_to_end(experiment(run_folder, "plots.mode=on"))

    assert refused.value.code == "E_PLOT_EXTRA_MISSING"
    assert refused.value.exit_code == EXIT_SIDE
    assert fakes.run == []
    assert writes.documents == []


def test_failed_charts_are_a_loud_note_and_keep_the_notes_already_given(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(results: Any, *, note: Any, **kwargs: Any) -> Any:
        note(CHART_NOTE.code, CHART_NOTE.message)
        raise ValueError("x")

    monkeypatch.setattr(pairbench, "draw", broken)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=auto"))

    assert code == EXIT_OK
    second = writes.documents[-1]
    assert second.plots.status == "not_drawn"
    assert second.plots.reason == "failed"
    assert [note.code for note in second.notes] == [CHART_NOTE.code, NOTE_CHARTS_FAILED]
    assert NOTE_CHARTS_FAILED in capsys.readouterr().err


def test_a_note_of_the_charts_is_printed_once_and_recorded_once(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def charts(results: Any, *, note: Any, **kwargs: Any) -> list[Path]:
        note(CHART_NOTE.code, CHART_NOTE.message)
        return []

    named = api.delegate
    monkeypatch.setattr(pairbench, "draw", LIBRARY_DRAW)
    monkeypatch.setattr(api, "delegate", lambda name: charts if name == "draw" else named(name))

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=auto"))

    assert code == EXIT_OK
    assert capsys.readouterr().err.count(CHART_NOTE.message) == 1
    assert [note.code for note in writes.documents[-1].notes] == [CHART_NOTE.code]


def test_a_failed_page_is_a_loud_note_and_no_page_is_named(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = pairbench.render

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        if fmt == "html":
            raise RuntimeError("x")
        return real_render(results, fmt, **kwargs)

    monkeypatch.setattr(pairbench, "render", render)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=off", "plots.mode=off"))

    assert code == EXIT_OK
    second = writes.documents[-1]
    assert second.artifacts.html is None
    assert [note.code for note in second.notes] == [NOTE_PAGE_FAILED]
    assert not (run_folder / "report.html").exists()


def test_a_diagnostics_document_left_unwritten_is_not_named(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    document: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pairbench, "explain", lambda experiment, analysed, *, out: document)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=always", "plots.mode=off"))

    assert code == EXIT_OK
    second = writes.documents[-1]
    assert second.diagnostics.status == "written"
    assert second.artifacts.diagnostics is None
    assert not (run_folder / "diagnostics.json").exists()


def test_report_html_false_writes_no_page(fakes: Calls, writes: Writes, run_folder: Path) -> None:
    run_command.run_to_end(
        experiment(run_folder, "explain.mode=off", "plots.mode=off", "report.html=false")
    )

    assert writes.documents[-1].artifacts.html is None
    assert not (run_folder / "report.html").exists()


@pytest.mark.parametrize("step", ["explain", "draw"])
def test_an_interrupt_after_the_first_write_writes_interrupted_and_exits_130(
    step: str,
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(pairbench, step, interrupt)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=always", "plots.mode=auto"))

    assert code == EXIT_INTERRUPTED
    _first, last = writes.documents
    assert last.plots.status == "interrupted"
    if step == "explain":
        assert last.diagnostics.status == "interrupted"
    assert last.artifacts.html is None
    assert not (run_folder / "report.html").exists()
    assert on_disk(run_folder) == last.to_json()
    assert capsys.readouterr().err.endswith(
        refusal_text("E_INTERRUPTED: interrupted after the results were written")
    )


def test_an_interrupt_refusal_counts_as_an_interrupt(
    fakes: Calls, writes: Writes, run_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise Refusal("E_INTERRUPTED", "x")

    monkeypatch.setattr(pairbench, "explain", interrupt)

    code = run_command.run_to_end(experiment(run_folder, "explain.mode=always", "plots.mode=off"))

    assert code == EXIT_INTERRUPTED
    assert writes.documents[-1].diagnostics.status == "interrupted"


def test_a_refused_run_with_results_has_them_written_once(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    results: Results,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = Refusal("E_LAUNCH_FAILED", "x", results=results, detail={"run_dir": str(run_folder)})

    def refused(*args: Any, **kwargs: Any) -> Any:
        raise refusal

    monkeypatch.setattr(pairbench, "run", refused)

    with pytest.raises(Refusal) as raised:
        run_command.run_to_end(experiment(run_folder))

    assert raised.value is refusal
    assert len(writes.documents) == 1
    assert writes.documents[0].comparisons == results.comparisons
    assert (run_folder / "results.json").is_file()


def test_a_refused_analysis_with_results_has_them_written_once(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    results: Results,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise Refusal("E_CASES_DIFFER", "x", results=results)

    monkeypatch.setattr(pairbench, "analyse", refused)

    with pytest.raises(Refusal) as raised:
        run_command.run_to_end(experiment(run_folder, **{"--json": True}))

    assert raised.value.code == "E_CASES_DIFFER"
    assert len(writes.documents) == 1
    assert json.loads(capsys.readouterr().out) == on_disk(run_folder)


def test_a_refusal_without_results_writes_nothing(
    fakes: Calls, writes: Writes, run_folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise Refusal("E_LAUNCH_FAILED", "x")

    monkeypatch.setattr(pairbench, "run", refused)

    with pytest.raises(Refusal):
        run_command.run_to_end(experiment(run_folder))

    assert writes.documents == []


def test_json_prints_the_final_document_alone_on_stdout(
    fakes: Calls, writes: Writes, run_folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_command.run_to_end(
        experiment(run_folder, "explain.mode=always", "plots.mode=auto", **{"--json": True})
    )

    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out) == writes.documents[-1].to_json()
    assert "matmul" in captured.err


class ClosedPipe:
    """A text stream whose reader has gone: every write and flush fails as a closed pipe does."""

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


def test_a_run_whose_output_reader_has_gone_still_writes_the_whole_folder(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    args = ["run", *(a for side in SIDES for a in ("--side", side)), "--baseline", "old"]
    code = entry.main([*args, "--out", str(run_folder), "--explain", "always"])

    assert code == EXIT_OK
    first, second = writes.documents
    assert first.diagnostics.status == "pending"
    assert second.diagnostics.status == "written"
    assert second.artifacts.html == "report.html"
    assert (run_folder / "report.html").is_file()
    assert on_disk(run_folder) == second.to_json()
    assert "BrokenPipeError" not in capsys.readouterr().err


def test_a_variable_that_gives_a_config_side_another_kind_runs_the_side_as_that_kind(
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_file = tmp_path / "bench.toml"
    config_file.write_text(
        '[sides.first]\nfile = ["first-*.json"]\nbaseline = true\n\n'
        '[sides.first.launch]\ntimeout = "45s"\n\n'
        '[sides.second]\ncmd = "true x"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAIRBENCH__SIDES__FIRST__CMD", "true first")

    args = ["--out", str(run_folder), "--explain", "off", "--set", "plots.mode=off"]
    code = entry.main(["run", "--config", str(config_file), *args])

    command_note = f"pairbench: note: {NOTE_COMMAND_SHOWN}: {command_shown_message()}\n"
    assert (code, capsys.readouterr().err) == (EXIT_OK, command_note)
    ran: Experiment = fakes.run[0]["experiment"]
    first = ran.side("first")
    assert (first.kind, first.spec["argv"]) == (KIND_CMD, ("true", "first"))
    assert "file" not in first.spec
    assert ran.baseline == "first"
    assert ran.launch.overrides["first"] == {"timeout_s": 45.0}


# A refusal nested in the note of a failed step: an escape character, a character that changes
# the order of the text, and a typed escape.
NESTED = Refusal("E_USAGE", "case a\x1bb‮c\\x1b")
# The refusal in the note as the results keep it, and as its printed line shows it: escaped
# once, as the refusal's own line is.
NESTED_KEPT = "E_USAGE: case a\x1bb‮c\\x1b"
NESTED_SHOWN = "E_USAGE: case a\\x1bb\\u202ec\\\\x1b"


def _raise_nested(*args: Any, **kwargs: Any) -> Any:
    raise NESTED


def _failed_step(
    step: str, document: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[tuple[str, ...], str]:
    """Make one step fail with the nested refusal; the settings of the run and the note."""
    if step == "explain":
        monkeypatch.setattr(pairbench, "explain", _raise_nested)
        words = "the explain step failed ({}); the verdicts are unchanged"
        return ("explain.mode=always", "plots.mode=off"), f"{NOTE_EXPLAIN_FAILED}:{words}"
    if step == "findings":
        named = api.delegate
        monkeypatch.setattr(pairbench, "explain", lambda experiment, analysed, *, out: document)
        monkeypatch.setattr(
            api, "delegate", lambda name: _raise_nested if name == "findings" else named(name)
        )
        words = "the findings could not be printed ({})"
        return ("explain.mode=always", "plots.mode=off"), f"{NOTE_EXPLAIN_FAILED}:{words}"
    if step == "charts":
        monkeypatch.setattr(pairbench, "draw", _raise_nested)
        words = "the charts could not be drawn ({}); the verdicts are unchanged"
        return ("explain.mode=off", "plots.mode=auto"), f"{NOTE_CHARTS_FAILED}:{words}"
    real_render = pairbench.render

    def render(results: Results, fmt: str, **kwargs: Any) -> str:
        if fmt == "html":
            raise NESTED
        return real_render(results, fmt, **kwargs)

    monkeypatch.setattr(pairbench, "render", render)
    words = "the report page could not be made ({}); the results are written"
    return ("explain.mode=off", "plots.mode=off"), f"{NOTE_PAGE_FAILED}:{words}"


@pytest.mark.parametrize("step", ["explain", "findings", "charts", "page"])
def test_a_refusal_in_the_note_of_a_failed_step_is_escaped_once_and_kept_as_it_is(
    step: str,
    fakes: Calls,
    writes: Writes,
    run_folder: Path,
    document: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, note = _failed_step(step, document, monkeypatch)
    code_of_note, words = note.split(":", 1)

    code = run_command.run_to_end(experiment(run_folder, *settings))

    assert code == EXIT_OK
    kept = [n.message for n in writes.documents[-1].notes if n.code == code_of_note]
    assert kept == [words.format(NESTED_KEPT)]
    on_file = [n["message"] for n in on_disk(run_folder)["notes"] if n["code"] == code_of_note]
    assert on_file == [words.format(NESTED_KEPT)]
    captured = capsys.readouterr()
    shown = f"pairbench: note: {code_of_note}: {words.format(NESTED_SHOWN)}"
    assert shown in captured.err.splitlines()
    assert NESTED_KEPT not in captured.err
    assert NESTED_SHOWN not in captured.out
