# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Names from the user's code stay in the diagnostics document and the profile files.

A made-up marker is put into the function and shared-object names of every
side. It must reach ``diagnostics.json``, the folded files and the flame
graphs, and must not reach any note, any finding a report may share, or the
results document written after the step.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pairbench import api
from pairbench.api import Instrument, InstrumentedLaunch
from pairbench.diagnose import explain, instruments
from pairbench.diagnose.instruments import HostFacts
from pairbench.model import (
    Experiment,
    ExplainSettings,
    PlotsState,
    Results,
    ResultsSide,
    Side,
)

MARKER = "zqxmarker"
SCRIPT = (
    "app 1/1 1000.010000: cycles:\n"
    f"\t aa10 {MARKER}_inner (/srv/{MARKER}/lib{MARKER}.so)\n"
    f"\t aa20 {MARKER}_main (/srv/{MARKER}/app)\n"
    "\n"
)
BUILDIDS = f"2222 /srv/{MARKER}/lib{MARKER}.so\n3333 /srv/{MARKER}/app\n"
OTHER_BUILDIDS = f"4444 /srv/{MARKER}/lib{MARKER}.so\n3333 /srv/{MARKER}/app\n"
FOLDED = f"<module> ({MARKER}.py);{MARKER}_nap ({MARKER}.py) 2\n"
STAT = "100;;instructions;1;100.00;;\n50;;cycles;1;100.00;;\n"
OTHER_STAT = "300;;instructions;1;100.00;;\n50;;cycles;1;100.00;;\n"
PARANOID = "perf_event_paranoid setting is 4\n"


class Session:
    def __init__(self, files: Mapping[tuple[str, str], tuple[int, Mapping[str, str]]]) -> None:
        self.files = files

    def command(self, side: str) -> tuple[str, ...] | None:
        return ("python3", f"{MARKER}.py")

    def launch(self, side: str, instrument: Instrument, artifacts: Path) -> InstrumentedLaunch:
        rc, files = self.files[(side, instrument.name)]
        for name, text in files.items():
            (artifacts / name).write_text(text, encoding="utf-8")
        return InstrumentedLaunch(rc=rc, artifacts=artifacts)

    def close(self) -> None:
        pass


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    files: Mapping[tuple[str, str], tuple[int, Mapping[str, str]]],
) -> tuple[Results, Any]:
    session = Session(files)

    def opener(experiment: Experiment, **_: Any) -> Session:
        _["note"]("made_up_code", "a made-up note")
        return session

    real = api.delegate
    monkeypatch.setattr(
        api, "delegate", lambda part: opener if part == "open_explain" else real(part)
    )
    monkeypatch.setattr(
        instruments,
        "host_facts",
        lambda environ=None: HostFacts(perf="/usr/bin/perf", paranoid=2, capabilities=0, euid=1000),
    )
    base = Results.from_json(example_results)
    results = dataclasses.replace(
        base,
        sides=(
            ResultsSide(
                name="new",
                kind="cmd",
                role="subject",
                twin_of=None,
                identity={},
                fingerprint="c" * 64,
            ),
            ResultsSide(
                name="old",
                kind="cmd",
                role="baseline",
                twin_of=None,
                identity={},
                fingerprint="d" * 64,
            ),
        ),
    )
    spec = {"argv": ["python3", f"{MARKER}.py"]}
    experiment = Experiment(
        sides=(
            Side(name="new", kind="cmd", spec=spec),
            Side(name="old", kind="cmd", role="baseline", spec=spec),
        ),
        explain=ExplainSettings(mode="always"),
    )
    return results, explain.explain_run(experiment, results, out=tmp_path)


ALL_RAN = {
    ("new", "counters"): (0, {"perf-stat.txt": STAT}),
    ("new", "stacks"): (0, {"perf-script.txt": SCRIPT, "perf-buildids.txt": BUILDIDS}),
    ("old", "counters"): (0, {"perf-stat.txt": OTHER_STAT}),
    ("old", "stacks"): (0, {"perf-script.txt": SCRIPT, "perf-buildids.txt": OTHER_BUILDIDS}),
}
MIXED = {
    **ALL_RAN,
    ("old", "stacks"): (255, {"stderr.txt": PARANOID}),
    ("old", "pystacks"): (0, {"pystacks.folded": FOLDED}),
}


@pytest.mark.parametrize("files", [ALL_RAN, MIXED], ids=["all-ran", "mixed-instruments"])
def test_names_from_the_users_code_stay_in_the_diagnostics_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    files: Mapping[tuple[str, str], tuple[int, Mapping[str, str]]],
) -> None:
    results, made = _run(tmp_path, monkeypatch, example_results, files)

    assert MARKER in (tmp_path / "diagnostics.json").read_text(encoding="utf-8")
    for path in (
        *made.files.folded,
        *made.files.flame,
        *made.files.folded_diff,
        *made.files.flame_diff,
    ):
        assert MARKER in (tmp_path / path).read_text(encoding="utf-8"), path
    assert made.notes, "the step gave no note to check"
    for note in made.notes:
        assert MARKER not in note.message, note
        assert MARKER not in note.code, note
    for finding in made.shareable_findings():
        assert MARKER not in json.dumps(finding.to_json()), finding

    finished = results.pending().finished(
        diagnostics=made.state(), plots=PlotsState(status="off"), notes=made.notes
    )
    shown = json.dumps(finished.to_json())
    assert MARKER not in shown
    assert "a made-up note" in shown


def test_findings_that_name_functions_are_kept_out_of_what_a_report_may_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    _results, made = _run(tmp_path, monkeypatch, example_results, ALL_RAN)
    named = [f for f in made.findings if MARKER in json.dumps(f.to_json())]
    assert {f.id for f in named} >= {"top_function_share", "objects_differ"}
    assert [f for f in made.shareable_findings() if f in named] == []
    assert [f.id for f in made.shareable_findings()] == ["instructions", "instructions_per_cycle"]
