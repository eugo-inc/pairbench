# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Shared pieces of the command-line tests: example documents and fakes of the public functions."""

from __future__ import annotations

import dataclasses
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.model import (
    Artifacts,
    Diagnostics,
    DiagnosticsFiles,
    DiagnosticsState,
    Note,
    PlotsState,
    Results,
)
from pairbench.results import writer

# The start of the line that follows a refusal's line on standard error: the address of
# the code's entry in the documentation of the installed version.
DOCS_LINE = "pairbench: see https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#"
# The note a run or a compare prints once when it writes results: what the shared files show
# of the command, and where secrets belong.
COMMAND_NOTE = (
    "pairbench: note: command_shown: results.json, results.md and report.html show the command "
    "with each --side spec, each --set value and the secret forms pairbench recognises hidden, "
    "and each absolute path cut to its last part (report.include_image_refs shows image "
    "references); put secrets in environment variables: "
    "https://eugo.io/docs/pairbench/0.3/reference/config/#what-the-shared-files-hide\n"
)


def refusal_text(line: str) -> str:
    """What a refusal prints on standard error: its line, then where its code's entry is."""
    code = line.split(":", 1)[0]
    return f"{line}\n{DOCS_LINE}{code.lower()}\n"


# A note the explain step adds in the fakes, and one the charts add.
EXPLAIN_NOTE = Note(code="instrument_skipped", message="counters were skipped on side new")
CHART_NOTE = Note(code="chart_without_data", message="no resource cases to draw")


@pytest.fixture
def results(example_results: dict[str, Any]) -> Results:
    """An analysed results document, as ``pairbench.analyse`` returns it."""
    loaded = Results.from_json(example_results)
    return dataclasses.replace(
        loaded,
        artifacts=Artifacts(),
        diagnostics=DiagnosticsState(),
        plots=PlotsState(),
    )


@pytest.fixture
def document(example_diagnostics: dict[str, Any]) -> Diagnostics:
    """A diagnostics document, as the explain step returns it, with one note and two files."""
    loaded = Diagnostics.from_json(example_diagnostics)
    files = DiagnosticsFiles(
        folded=("profiles/new/stacks.folded",), flame=("profiles/new/flame.svg",)
    )
    return dataclasses.replace(loaded, notes=(EXPLAIN_NOTE,), files=files)


class Writes:
    """Every results document written, in order, by the real writer."""

    def __init__(self) -> None:
        self.documents: list[Results] = []

    def __call__(self, results: Results, folder: Path, **kwargs: Any) -> Results:
        written = REAL_WRITE(results, folder, **kwargs)
        self.documents.append(written)
        return written


REAL_WRITE = writer.write_results


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> Writes:
    """Record every write of the results while still writing them."""
    recorder = Writes()
    monkeypatch.setattr(writer, "write_results", recorder)
    return recorder


@pytest.fixture
def run_folder(tmp_path: Path) -> Path:
    """The folder of a run, holding its capture as the runner leaves it."""
    folder = tmp_path / "run"
    folder.mkdir()
    (folder / "capture.jsonl").write_text("", encoding="utf-8")
    return folder


def fake_capture(folder: Path) -> Any:
    """A capture whose source is the capture file of a run folder."""
    return types.SimpleNamespace(source=types.SimpleNamespace(path=str(folder / "capture.jsonl")))


class Calls:
    """What the fakes were called with."""

    def __init__(self) -> None:
        self.run: list[dict[str, Any]] = []
        self.analyse: list[dict[str, Any]] = []
        self.explain: list[Results] = []
        self.draw: list[dict[str, Any]] = []


@pytest.fixture
def fakes(
    monkeypatch: pytest.MonkeyPatch, run_folder: Path, results: Results, document: Diagnostics
) -> Calls:
    """Fake run, analyse, explain and draw; the reporters and the writer are the real ones."""
    calls = Calls()

    def run(experiment: Any, *, out: Path | None = None) -> Any:
        calls.run.append({"experiment": experiment, "out": out})
        return fake_capture(run_folder)

    def analyse(captures: Any, **kwargs: Any) -> Results:
        calls.analyse.append(kwargs)
        return results

    def explain(experiment: Any, analysed: Results, *, out: Path) -> Diagnostics:
        calls.explain.append(analysed)
        (out / "diagnostics.json").write_text("{}", encoding="utf-8")
        return document

    def draw(analysed: Results, *, out: Path, note: Callable[..., None] | None = None, **kw: Any):
        calls.draw.append({"out": out, **kw})
        if note is not None:
            note(CHART_NOTE.code, CHART_NOTE.message)
        chart = out / "charts" / "verdict.svg"
        chart.parent.mkdir(parents=True, exist_ok=True)
        chart.write_text("<svg/>", encoding="utf-8")
        return [chart]

    monkeypatch.setattr(pairbench, "run", run)
    monkeypatch.setattr(pairbench, "analyse", analyse)
    monkeypatch.setattr(pairbench, "explain", explain)
    monkeypatch.setattr(pairbench, "draw", draw)
    return calls
