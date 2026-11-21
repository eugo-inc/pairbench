# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The explain step against a made-up session: what is launched, what is skipped, what is written.

The session stands in for ``pairbench.runner:open_explain``; the facts of the
machine are made up, so no test runs ``perf``.
"""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench import api
from pairbench.api import Instrument, InstrumentedLaunch
from pairbench.diagnose import document, explain, instruments
from pairbench.diagnose.instruments import HostFacts
from pairbench.errors import Refusal
from pairbench.model import (
    Capture,
    CounterRow,
    DiagnosticsFiles,
    DiagnosticsState,
    Experiment,
    ExplainSettings,
    Header,
    InstrumentRun,
    LaunchSettings,
    Note,
    ObjectDiff,
    PlotsState,
    Results,
    ResultsSide,
    Side,
    TopFunction,
)
from pairbench.results import load_schema

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "diagnose"
STAT = (FIXTURES / "perf-stat.txt").read_text(encoding="utf-8")
SCRIPT = (FIXTURES / "perf-script.txt").read_text(encoding="utf-8")
BUILDIDS = (FIXTURES / "perf-buildids.txt").read_text(encoding="utf-8")
OLD_STAT = "1000;;instructions;1;100.00;;\n500;;cycles;1;100.00;;\n"
OLD_SCRIPT = (
    "python3 9/9 1000.010000: cycles:\n"
    "\t aa10 spin_numbers (/usr/bin/python3.13)\n"
    "\t aa20 main (/usr/bin/python3.13)\n"
    "\n"
    "python3 9/9 1000.020000: cycles:\n"
    "\t aa30 main (/usr/bin/python3.13)\n"
    "\n"
)
OLD_BUILDIDS = "1111111111111111111111111111111111111111 /usr/bin/python3.13\n"
FOLDED_NEW = "<module> (bench.py);nap (bench.py) 3\n<module> (bench.py);spin (bench.py) 1\n"
FOLDED_OLD = "<module> (bench.py);nap (bench.py) 1\n"
FP_NEW = "c" * 64
FP_OLD = "d" * 64
PARANOID = "perf_event_paranoid setting is 4\n"

OPEN = HostFacts(perf="/usr/bin/perf", paranoid=2, capabilities=0, euid=1000)
NO_PERF = HostFacts(perf=None, paranoid=2, capabilities=0, euid=1000)

Action = Callable[[Path], InstrumentedLaunch]


def writes(files: Mapping[str, str], rc: int = 0) -> Action:
    def act(folder: Path) -> InstrumentedLaunch:
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8")
        return InstrumentedLaunch(rc=rc, artifacts=folder)

    return act


def refuses(code: str) -> Action:
    def act(folder: Path) -> InstrumentedLaunch:
        raise Refusal(code, "a made-up refusal")

    return act


class FakeSession:
    def __init__(
        self,
        actions: Mapping[tuple[str, str], Action],
        commands: Mapping[str, tuple[str, ...] | Refusal | None] | None = None,
        prepared: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.actions = dict(actions)
        self.commands = dict(commands or {})
        self.prepared = dict(prepared or {})
        self.wrapped: list[tuple[str, ...]] = []
        self.launched: list[tuple[str, str]] = []
        self.instruments: list[Instrument] = []
        self.folders: list[Path] = []
        self.closed = 0

    def command(self, side: str) -> tuple[str, ...] | None:
        value = self.commands.get(side, ("python3", "bench.py"))
        if isinstance(value, Refusal):
            raise value
        return value

    def launch(self, side: str, instrument: Instrument, artifacts: Path) -> InstrumentedLaunch:
        assert artifacts.is_dir()
        self.launched.append((side, instrument.name))
        self.instruments.append(instrument)
        self.folders.append(artifacts)
        # As a real session does, the instrument wraps the command the driver prepared.
        argv = self.prepared.get(side, ("python3", "bench.py"))
        tools = {"pysampler.py": "/pairbench/tools/pysampler.py"}
        self.wrapped.append(instrument.wrap(argv, out=str(artifacts), tools=tools).argv)
        return self.actions[(side, instrument.name)](artifacts)

    def close(self) -> None:
        self.closed += 1


class Opener:
    def __init__(
        self,
        session: FakeSession,
        refusal: Refusal | None = None,
        notes: Sequence[tuple[str, str]] = (),
    ) -> None:
        self.session = session
        self.refusal = refusal
        self.notes = notes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(
        self,
        experiment: Experiment,
        *,
        run_id: str,
        fingerprints: Mapping[str, str],
        note: api.Notify = api.no_notes,
        services: api.RunServices | None = None,
    ) -> FakeSession:
        self.calls.append((run_id, dict(fingerprints)))
        for code, message in self.notes:
            note(code, message)
        if self.refusal is not None:
            raise self.refusal
        return self.session


def wire(monkeypatch: pytest.MonkeyPatch, opener: Opener, facts: HostFacts = OPEN) -> None:
    real = api.delegate
    monkeypatch.setattr(
        api, "delegate", lambda part: opener if part == "open_explain" else real(part)
    )
    monkeypatch.setattr(instruments, "host_facts", lambda environ=None: facts)


def _side(name: str, kind: str, role: str = "subject", **fields: Any) -> ResultsSide:
    fingerprint = FP_OLD if name.startswith("old") else FP_NEW
    return ResultsSide(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        twin_of=fields.get("twin_of"),
        control_of=fields.get("control_of"),
        identity={},
        fingerprint=fingerprint,
    )


def _results(example: dict[str, Any], kind: str = "cmd", *, difference: bool = True) -> Results:
    base = Results.from_json(example)
    sides = (
        _side("new", kind),
        _side("old", kind, "baseline"),
        _side("new~same", kind, "twin", twin_of="new"),
        _side("old~control", kind, "control", control_of="old"),
    )
    comparisons = tuple(dataclasses.replace(c, primary=difference) for c in base.comparisons)
    return dataclasses.replace(base, sides=sides, comparisons=comparisons)


def _experiment(
    kind: str = "cmd", *, mode: str = "always", perf_counters: bool = False
) -> Experiment:
    def made(name: str, role: str) -> Side:
        if kind == "image":
            spec: dict[str, Any] = {"image": f"made/up-{name}:1"}
        else:
            spec = {"argv": ["python3", "bench.py"]}
        return Side(name=name, kind=kind, role=role, spec=spec)  # type: ignore[arg-type]

    return Experiment(
        sides=(made("new", "subject"), made("old", "baseline")),
        explain=ExplainSettings(mode=mode, sample_hz=49, call_graph="dwarf", top=3),  # type: ignore[arg-type]
        launch=LaunchSettings(perf_counters=perf_counters),
    )


def _all_ok() -> dict[tuple[str, str], Action]:
    return {
        ("new", "counters"): writes({"perf-stat.txt": STAT}),
        ("new", "stacks"): writes({"perf-script.txt": SCRIPT, "perf-buildids.txt": BUILDIDS}),
        ("old", "counters"): writes({"perf-stat.txt": OLD_STAT}),
        ("old", "stacks"): writes(
            {"perf-script.txt": OLD_SCRIPT, "perf-buildids.txt": OLD_BUILDIDS}
        ),
    }


def _files(out: Path) -> list[str]:
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def _row(name: str, side: str, status: str, reason: str | None, rc: int | None) -> InstrumentRun:
    return InstrumentRun(name=name, side=side, status=status, reason=reason, rc=rc)  # type: ignore[arg-type]


def _skip_note(name: str, side: str, words: str) -> Note:
    return Note(
        code="instrument_skipped", message=f"instrument {name} did not run for side {side}: {words}"
    )


# ---------------------------------------------------------------------------
# Every instrument runs
# ---------------------------------------------------------------------------


def test_each_subject_and_the_baseline_are_launched_under_counters_then_stacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(_all_ok())
    opener = Opener(session)
    wire(monkeypatch, opener)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)

    assert session.launched == [
        ("new", "counters"),
        ("new", "stacks"),
        ("old", "counters"),
        ("old", "stacks"),
    ]
    assert opener.calls == [("cap-000001", {"new": FP_NEW, "old": FP_OLD})]
    assert session.closed == 1
    stacks_instrument = session.instruments[1]
    assert isinstance(stacks_instrument, instruments.Stacks)
    assert (stacks_instrument.hz, stacks_instrument.call_graph) == (49, "dwarf")
    assert made.instruments == (
        _row("counters", "new", "ok", None, 0),
        _row("stacks", "new", "ok", None, 0),
        _row("counters", "old", "ok", None, 0),
        _row("stacks", "old", "ok", None, 0),
    )
    assert made.state() == DiagnosticsState(status="written")
    assert made.notes == ()
    assert made.name_map == {"new": "new", "old": "old"}


def test_the_files_of_the_step_are_the_document_and_the_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    wire(monkeypatch, Opener(FakeSession(_all_ok())))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.files == DiagnosticsFiles(
        folded=("profiles/new.folded", "profiles/old.folded"),
        folded_diff=("profiles/new_vs_old.folded-diff.tsv",),
        flame=("profiles/new.flame.svg", "profiles/old.flame.svg"),
        flame_diff=("profiles/new_vs_old.flame-diff.svg",),
    )
    assert _files(tmp_path) == [
        "diagnostics.json",
        "profiles/new.flame.svg",
        "profiles/new.folded",
        "profiles/new_vs_old.flame-diff.svg",
        "profiles/new_vs_old.folded-diff.tsv",
        "profiles/old.flame.svg",
        "profiles/old.folded",
    ]
    assert not (tmp_path / ".explain").exists()
    assert document.read_diagnostics(tmp_path / "diagnostics.json") == made
    jsonschema = pytest.importorskip(
        "jsonschema", reason="needs the Python package jsonschema to validate against a JSON Schema"
    )
    jsonschema.validate(
        json.loads((tmp_path / "diagnostics.json").read_text(encoding="utf-8")),
        load_schema("diagnostics"),
    )
    assert (tmp_path / "profiles/old.folded").read_text(encoding="utf-8") == (
        "# pairbench: this file holds names from the user's code: "
        "functions, shared objects and stacks\n"
        "main 1\n"
        "main;spin_numbers 1\n"
    )


def test_the_counts_stacks_and_objects_of_both_sides_are_in_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    wire(monkeypatch, Opener(FakeSession(_all_ok())))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    rows = {r.event: r for r in made.counters}
    assert len(made.counters) == 10
    assert rows["instructions"] == CounterRow(
        event="instructions",
        subject="new",
        baseline="old",
        subject_value=8502870854.0,
        baseline_value=1000.0,
        ratio=8502870.854,
    )
    assert (rows["page-faults"].subject_value, rows["page-faults"].baseline_value) == (1361.0, None)
    by_side = {s.side: s for s in made.stacks}
    assert (by_side["new"].instrument, by_side["new"].samples) == ("stacks", 27)
    assert [f.name for f in by_side["new"].top_functions] == [
        "[unknown]",
        "[python3.13]",
        "[libcrypto.so.3]",
    ]
    assert by_side["old"].top_functions == (
        TopFunction(name="main", object="python3.13", share=0.5),
        TopFunction(name="spin_numbers", object="python3.13", share=0.5),
    )
    assert made.objects == ObjectDiff(
        only_in={
            "new": (
                "[kernel.kallsyms]",
                "[vdso]",
                "_hashlib.cpython-313-aarch64-linux-gnu.so",
                "ld-linux-aarch64.so.1",
                "libc.so.6",
                "libcrypto.so.3",
                "libexpat.so.1.13.0",
                "libm.so.6",
                "libz.so.1.3.1",
                "libzstd.so.1.5.7",
            ),
            "old": (),
        },
        differ=(
            {
                "name": "python3.13",
                "new": "9e7f76dabfdf1c3b469670d23239b2f4cb2743d1",
                "old": "1111111111111111111111111111111111111111",
            },
        ),
    )
    ids = [f.id for f in made.findings]
    assert "instructions" in ids
    assert "objects_differ" in ids
    assert "top_function_share" in ids


def test_twins_and_the_positive_control_are_never_launched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(_all_ok())
    opener = Opener(session)
    wire(monkeypatch, opener)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert {side for side, _ in session.launched} == {"new", "old"}
    assert set(opener.calls[0][1]) == {"new", "old"}
    assert {r.side for r in made.instruments} == {"new", "old"}
    assert "new~same" not in json.dumps(made.to_json())
    assert explain.explained_sides(_results(example_results)) == ("new", "old")


def test_the_notes_the_session_gives_are_kept_in_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    wire(monkeypatch, Opener(FakeSession(_all_ok()), notes=[("made_up_code", "a made-up note")]))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.notes == (Note(code="made_up_code", message="a made-up note"),)


# ---------------------------------------------------------------------------
# Instruments that cannot run
# ---------------------------------------------------------------------------


def test_without_perf_a_python_side_is_sampled_by_pystacks_and_nothing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {
            ("new", "pystacks"): writes({"pystacks.folded": FOLDED_NEW}),
            ("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD}),
        }
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == [("new", "pystacks"), ("old", "pystacks")]
    assert session.instruments[0] == instruments.PyStacks(hz=49)
    assert made.instruments == (
        _row("counters", "new", "skipped", "not_installed", None),
        _row("stacks", "new", "skipped", "not_installed", None),
        _row("pystacks", "new", "ok", None, 0),
        _row("counters", "old", "skipped", "not_installed", None),
        _row("stacks", "old", "skipped", "not_installed", None),
        _row("pystacks", "old", "ok", None, 0),
    )
    words = "its program is not installed"
    assert made.notes == (
        _skip_note("counters", "new", words),
        _skip_note("stacks", "new", words),
        _skip_note("counters", "old", words),
        _skip_note("stacks", "old", words),
    )
    assert made.counters == ()
    assert [(s.side, s.instrument, s.samples) for s in made.stacks] == [
        ("new", "pystacks", 4),
        ("old", "pystacks", 1),
    ]
    assert made.files.folded_diff == ("profiles/new_vs_old.folded-diff.tsv",)
    assert made.objects == ObjectDiff()
    assert made.state() == DiagnosticsState(status="written")


def test_without_perf_a_side_that_does_not_start_with_python_gets_no_instrument(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession({}, commands={"new": ("./app",), "old": None})
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == []
    assert session.closed == 1
    assert [r.name for r in made.instruments] == ["counters", "stacks", "counters", "stacks"]
    assert made.state() == DiagnosticsState(status="skipped", reason="no_instrument")
    assert made.files == DiagnosticsFiles()
    assert _files(tmp_path) == ["diagnostics.json"]


def test_a_system_that_forbids_perf_is_told_from_perfs_own_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("old", "counters")] = writes({"stderr.txt": PARANOID}, rc=255)
    actions[("old", "stacks")] = writes({"stderr.txt": PARANOID}, rc=255)
    actions[("old", "pystacks")] = writes({"pystacks.folded": FOLDED_OLD})
    wire(monkeypatch, Opener(FakeSession(actions)))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.instruments[2:] == (
        _row("counters", "old", "skipped", "not_permitted", 255),
        _row("stacks", "old", "skipped", "not_permitted", 255),
        _row("pystacks", "old", "ok", None, 0),
    )
    assert made.notes == (
        _skip_note(
            "counters",
            "old",
            "the system does not permit it: the kernel setting perf_event_paranoid forbids it",
        ),
        _skip_note(
            "stacks",
            "old",
            "the system does not permit it: the kernel setting perf_event_paranoid forbids it",
        ),
        Note(
            code="stack_instruments_differ",
            message=(
                "the stacks of side new come from instrument stacks and those of side old "
                "from instrument pystacks: no difference file and no difference graph are made"
            ),
        ),
    )
    assert made.files.folded_diff == ()
    assert made.files.flame_diff == ()
    assert made.files.folded == ("profiles/new.folded", "profiles/old.folded")
    assert "top_function_share" not in [f.id for f in made.findings]


def test_an_image_side_without_perf_counters_is_not_launched_under_perf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {
            ("new", "pystacks"): writes({"pystacks.folded": FOLDED_NEW}),
            ("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD}),
        },
        commands={"old": None},
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(
        _experiment("image"), _results(example_results, "image"), out=tmp_path
    )
    assert session.launched == [("new", "pystacks")]
    assert made.instruments == (
        _row("counters", "new", "skipped", "no_capability", None),
        _row("stacks", "new", "skipped", "no_capability", None),
        _row("pystacks", "new", "ok", None, 0),
        _row("counters", "old", "skipped", "no_capability", None),
        _row("stacks", "old", "skipped", "no_capability", None),
    )
    assert made.files.folded == ("profiles/new.folded",)
    assert made.files.folded_diff == ()


def test_an_image_without_perf_is_launched_once_and_stacks_is_not_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("new", "counters")] = writes({"stderr.txt": "perf: not found\n"}, rc=127)
    actions[("new", "pystacks")] = writes({"pystacks-too-old.txt": "old\n"}, rc=86)
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(
        _experiment("image", perf_counters=True), _results(example_results, "image"), out=tmp_path
    )
    assert session.launched[:2] == [("new", "counters"), ("new", "pystacks")]
    assert made.instruments[:3] == (
        _row("counters", "new", "skipped", "not_in_image", 127),
        _row("stacks", "new", "skipped", "not_in_image", None),
        _row("pystacks", "new", "skipped", "interpreter_too_old", 86),
    )
    assert made.notes[2] == _skip_note(
        "pystacks", "new", "the interpreter of the side is older than Python 3.8"
    )


def test_a_side_whose_identity_changed_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("new", "counters")] = refuses("E_SIDE_CHANGED")
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == [("new", "counters"), ("old", "counters"), ("old", "stacks")]
    assert made.instruments[:2] == (
        _row("counters", "new", "skipped", "side_changed", None),
        _row("stacks", "new", "skipped", "side_changed", None),
    )
    assert made.notes[0] == _skip_note(
        "counters", "new", "the identity of the side differs from the one the run recorded"
    )
    assert made.files.folded == ("profiles/old.folded",)


def test_a_side_that_cannot_be_started_under_an_instrument_is_launched_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("old", "counters")] = refuses("E_ENGINE_UNSUPPORTED")
    session = FakeSession(actions, commands={"old": None})
    wire(monkeypatch, Opener(session))
    made = explain.explain_run(
        _experiment("image", perf_counters=True), _results(example_results, "image"), out=tmp_path
    )
    assert session.launched[2:] == [("old", "counters")]
    assert made.instruments[2:] == (
        _row("counters", "old", "skipped", "launcher_cannot", None),
        _row("stacks", "old", "skipped", "launcher_cannot", None),
    )


def test_a_launch_that_fails_is_recorded_and_the_step_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("new", "counters")] = refuses("E_LAUNCH_FAILED")
    actions[("new", "stacks")] = writes({"stderr.txt": "Segmentation fault\n"}, rc=139)
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == [
        ("new", "counters"),
        ("new", "stacks"),
        ("old", "counters"),
        ("old", "stacks"),
    ]
    assert made.instruments[:2] == (
        _row("counters", "new", "failed", "launch_failed", None),
        _row("stacks", "new", "failed", "launch_failed", 139),
    )
    assert made.notes[1] == _skip_note("stacks", "new", "the launch under the instrument failed")
    assert made.state() == DiagnosticsState(status="written")


def test_a_refused_command_gives_a_pystacks_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD})},
        commands={"new": Refusal("E_SIDE_CHANGED", "a made-up refusal")},
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.instruments[2] == _row("pystacks", "new", "skipped", "side_changed", None)
    assert session.launched == [("old", "pystacks")]


def test_a_python_side_that_ends_before_the_first_sample_ran_and_has_no_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {
            ("new", "pystacks"): writes({"pystacks.folded": ""}),
            ("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD}),
        }
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.instruments[2] == _row("pystacks", "new", "ok", None, 0)
    assert made.notes[2] == Note(
        code="stacks_not_sampled",
        message="instrument pystacks took no samples for side new: the launch ended before "
        "the first sample",
    )
    assert [s.side for s in made.stacks] == ["old"]
    assert made.files.folded_diff == ()


def test_a_folded_file_that_cannot_be_read_is_a_failed_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {
            ("new", "pystacks"): writes({"pystacks.folded": "no count here\n"}),
            ("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD}),
        }
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert made.instruments[2] == _row("pystacks", "new", "failed", "launch_failed", 0)
    assert made.notes[2] == _skip_note("pystacks", "new", "the launch under the instrument failed")
    assert [s.side for s in made.stacks] == ["old"]


def test_an_error_that_is_no_refusal_still_closes_the_session_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    def boom(folder: Path) -> InstrumentedLaunch:
        raise RuntimeError("made-up")

    actions = _all_ok()
    actions[("new", "stacks")] = boom
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    with pytest.raises(RuntimeError, match="made-up"):
        explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.closed == 1
    assert not (tmp_path / ".explain").exists()


def test_every_launch_gets_its_own_folder_under_the_run_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(_all_ok())
    wire(monkeypatch, Opener(session))
    explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert [str(f.relative_to(tmp_path)) for f in session.folders] == [
        ".explain/1-new/counters",
        ".explain/1-new/stacks",
        ".explain/2-old/counters",
        ".explain/2-old/stacks",
    ]


def _renamed(
    example: dict[str, Any], subject: str, *, cores: bool = False
) -> tuple[Experiment, Results]:
    """The experiment and results of the other tests, with the subject named ``subject``."""
    base = _results(example)
    comparisons = base.comparisons
    if cores:
        comparisons = (
            *comparisons,
            dataclasses.replace(
                comparisons[0],
                case="res/cores",
                primary=False,
                subject_median=7.8,
                baseline_median=1.0,
                outcome="higher",  # type: ignore[arg-type]
                verdict="HIGHER",  # type: ignore[arg-type]
                n_rounds=20,
            ),
        )
    results = dataclasses.replace(
        base,
        sides=tuple(
            dataclasses.replace(s, name=subject) if s.name == "new" else s for s in base.sides
        ),
        comparisons=tuple(
            dataclasses.replace(c, subject=subject) if c.subject == "new" else c
            for c in comparisons
        ),
    )
    experiment = _experiment()
    experiment = dataclasses.replace(
        experiment,
        sides=tuple(
            dataclasses.replace(s, name=subject) if s.name == "new" else s for s in experiment.sides
        ),
    )
    return experiment, results


def test_a_side_named_dot_dot_is_refused_before_the_explain_step(
    example_results: dict[str, Any],
) -> None:
    with pytest.raises(Refusal) as caught:
        _renamed(example_results, "..")
    assert caught.value.code == "E_USAGE"
    assert caught.value.exit_code == 2


LEFT_OUT_WORDS = (
    "a side, function or shared-object name in their text reads as a word a finding never uses"
)


def test_a_function_name_that_reads_as_a_cause_leaves_its_finding_out_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    actions = _all_ok()
    actions[("new", "stacks")] = writes(
        {
            "perf-script.txt": OLD_SCRIPT.replace("spin_numbers", "explains"),
            "perf-buildids.txt": OLD_BUILDIDS,
        }
    )
    wire(monkeypatch, Opener(FakeSession(actions)))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    ids = [f.id for f in made.findings]
    assert "top_function_share" not in ids
    assert "instructions" in ids
    assert made.notes == (
        Note(
            code="finding_left_out",
            message=(
                f"the findings top_function_share of side new against side old are left out: "
                f"{LEFT_OUT_WORDS}"
            ),
        ),
    )
    assert document.read_diagnostics(tmp_path / "diagnostics.json") == made


def test_a_side_name_that_reads_as_a_cause_leaves_its_findings_out_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    wire(monkeypatch, Opener(FakeSession({}), refusal=Refusal("E_LOCK", "a made-up lock")))
    experiment, results = _renamed(example_results, "causes", cores=True)
    made = explain.explain_run(experiment, results, out=tmp_path)
    assert made.findings == ()
    assert made.notes[-1] == Note(
        code="finding_left_out",
        message=(
            f"the findings cores_used of side causes against side old are left out: "
            f"{LEFT_OUT_WORDS}"
        ),
    )
    assert document.read_diagnostics(tmp_path / "diagnostics.json") == made


# ---------------------------------------------------------------------------
# A lock, the mode, and runs that launch nothing
# ---------------------------------------------------------------------------


def test_a_lock_that_cannot_be_taken_skips_the_step_and_is_not_passed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(_all_ok())
    wire(monkeypatch, Opener(session, refusal=Refusal("E_LOCK", "a made-up lock")))
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == []
    assert made.instruments == (
        _row("counters", "new", "skipped", "lock", None),
        _row("stacks", "new", "skipped", "lock", None),
        _row("counters", "old", "skipped", "lock", None),
        _row("stacks", "old", "skipped", "lock", None),
    )
    assert made.notes == (
        Note(
            code="explain_skipped",
            message=(
                "the explain step was skipped: a lock could not be taken, "
                "so no instrument ran on any side"
            ),
        ),
    )
    assert made.state() == DiagnosticsState(status="skipped", reason="lock")
    assert _files(tmp_path) == ["diagnostics.json"]
    assert document.read_diagnostics(tmp_path / "diagnostics.json") == made


def test_another_refusal_of_the_session_is_passed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    wire(monkeypatch, Opener(FakeSession({}), refusal=Refusal("E_USAGE", "a made-up refusal")))
    with pytest.raises(Refusal) as caught:
        explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert caught.value.code == "E_USAGE"
    assert _files(tmp_path) == []


@pytest.mark.parametrize(
    ("mode", "difference", "state"),
    [
        ("off", True, DiagnosticsState(status="off")),
        ("auto", False, DiagnosticsState(status="skipped", reason="mode_auto_no_difference")),
        ("auto", True, None),
        ("always", False, None),
    ],
)
def test_the_mode_and_the_outcomes_decide_whether_the_step_runs(
    example_results: dict[str, Any], mode: str, difference: bool, state: DiagnosticsState | None
) -> None:
    results = _results(example_results, difference=difference)
    assert explain.explain_decision(_experiment(mode=mode), results) == state


@pytest.mark.parametrize(("mode", "difference"), [("off", True), ("auto", False)])
def test_a_step_that_does_not_run_launches_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    mode: str,
    difference: bool,
) -> None:
    opener = Opener(FakeSession(_all_ok()))
    wire(monkeypatch, opener)
    results = _results(example_results, difference=difference)
    made = explain.explain_run(_experiment(mode=mode), results, out=tmp_path)
    assert opener.calls == []
    assert _files(tmp_path) == []
    assert made.instruments == ()
    assert made.name_map == {"new": "new", "old": "old"}


@pytest.mark.parametrize("kind", ["file", "rows"])
def test_a_run_read_from_files_or_rows_launches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], kind: str
) -> None:
    opener = Opener(FakeSession({}))
    wire(monkeypatch, opener)
    made = explain.explain_run(_experiment(), _results(example_results, kind), out=tmp_path)
    assert opener.calls == []
    assert made.instruments == (
        _row("counters", "new", "skipped", "launcher_cannot", None),
        _row("stacks", "new", "skipped", "launcher_cannot", None),
        _row("counters", "old", "skipped", "launcher_cannot", None),
        _row("stacks", "old", "skipped", "launcher_cannot", None),
    )
    assert made.notes[0] == _skip_note(
        "counters", "new", "the side cannot be started under the instrument"
    )
    assert made.state() == DiagnosticsState(status="skipped", reason="no_instrument")
    assert _files(tmp_path) == ["diagnostics.json"]


def test_the_resource_rows_and_findings_need_no_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    base = _results(example_results)
    template = base.comparisons[0]
    cores = dataclasses.replace(
        template,
        case="res/cores",
        primary=False,
        subject_median=7.8,
        baseline_median=1.0,
        outcome="higher",  # type: ignore[arg-type]
        verdict="HIGHER",  # type: ignore[arg-type]
        n_rounds=20,
    )
    results = dataclasses.replace(base, comparisons=(template, cores))
    wire(monkeypatch, Opener(FakeSession({}), refusal=Refusal("E_LOCK", "a made-up lock")))
    made = explain.explain_run(_experiment(), results, out=tmp_path)
    assert [(r.case, r.subject, r.baseline) for r in made.resources] == [
        ("res/cores", "new", "old")
    ]
    assert [f.text for f in made.findings] == [
        "new used 7.8 cores against 1.0 for old (median of 20 rounds)."
    ]


# ---------------------------------------------------------------------------
# Where a side runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("side", "perf_counters", "place"),
    [
        (Side(name="a", kind="cmd", spec={"argv": ["x"]}), False, ("host", False)),
        (Side(name="a", kind="python", spec={"interpreter": "python3"}), False, ("host", False)),
        (Side(name="a", kind="venv", spec={"venv": "v"}), False, ("host", False)),
        (Side(name="a", kind="conda", spec={"conda": "c"}), False, ("host", False)),
        (Side(name="a", kind="image", spec={"image": "made/up:1"}), True, ("container", True)),
        (Side(name="a", kind="serve", spec={"launcher": "host"}), False, ("host", False)),
        (Side(name="a", kind="serve", spec={"image": "made/up:1"}), False, ("container", False)),
        (Side(name="a", kind="file", spec={"paths": ["r.json"]}), False, ("none", False)),
        (Side(name="a", kind="made-up", spec={"spec": "x"}), False, ("unknown", False)),
    ],
)
def test_where_a_side_runs(side: Side, perf_counters: bool, place: tuple[str, bool]) -> None:
    other = dataclasses.replace(side, name="b", role="baseline")
    experiment = Experiment(sides=(side, other), launch=LaunchSettings(perf_counters=perf_counters))
    assert explain.where(experiment, "a") == place
    assert explain.where(experiment, "absent") == ("unknown", False)


# ---------------------------------------------------------------------------
# pairbench profile --tool perf
# ---------------------------------------------------------------------------


def _capture(experiment: Experiment) -> Capture:
    def recorded(name: str, role: str, **fields: Any) -> Side:
        side = experiment.side(fields.pop("of", name))
        fingerprint = FP_OLD if name.startswith("old") else FP_NEW
        return dataclasses.replace(side, name=name, role=role, fingerprint=fingerprint, **fields)  # type: ignore[arg-type]

    return Capture(
        capture_id="cap-000007",
        header=Header(capture_id="cap-000007", config=experiment.to_json()),
        sides=(
            recorded("new", "subject"),
            recorded("old", "baseline"),
            recorded("new~same", "twin", of="new", twin_of="new"),
        ),
    )


def wire_capture(monkeypatch: pytest.MonkeyPatch, experiment: Experiment, run_dir: Path) -> None:
    capture = _capture(experiment)

    def load(path: Path | str, *, reader: str | None = None) -> list[Capture]:
        assert Path(path) == run_dir / "capture.jsonl"
        return [capture]

    monkeypatch.setattr(pairbench, "load_capture", load)


def _stacks_only() -> dict[tuple[str, str], Action]:
    return {key: action for key, action in _all_ok().items() if key[1] == "stacks"}


def test_stacks_are_recorded_for_each_subject_and_the_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = _experiment()
    session = FakeSession(_stacks_only())
    opener = Opener(session)
    wire(monkeypatch, opener)
    wire_capture(monkeypatch, experiment, tmp_path)
    paths = explain.record_stacks(tmp_path, tool="perf", case="matmul")
    assert paths == (
        "profiles/new.folded",
        "profiles/old.folded",
        "profiles/new.flame.svg",
        "profiles/old.flame.svg",
        "profiles/new_vs_old.folded-diff.tsv",
        "profiles/new_vs_old.flame-diff.svg",
    )
    assert session.launched == [("new", "stacks"), ("old", "stacks")]
    assert [str(f.relative_to(tmp_path)) for f in session.folders] == [
        ".explain/1-new/stacks",
        ".explain/2-old/stacks",
    ]
    assert opener.calls == [("cap-000007", {"new": FP_NEW, "old": FP_OLD})]
    assert session.closed == 1
    assert _files(tmp_path) == sorted(paths)
    assert not (tmp_path / "diagnostics.json").exists()


def test_stacks_are_recorded_for_the_side_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = _experiment()
    session = FakeSession(_stacks_only())
    wire(monkeypatch, Opener(session))
    wire_capture(monkeypatch, experiment, tmp_path)
    assert explain.record_stacks(tmp_path, side="old") == (
        "profiles/old.folded",
        "profiles/old.flame.svg",
    )
    assert session.launched == [("old", "stacks")]


def test_a_tool_other_than_perf_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path, tool="nsys")
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "stacks are recorded with perf, not with nsys",
    )


def test_a_side_that_is_no_subject_or_baseline_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, Opener(FakeSession({})))
    wire_capture(monkeypatch, _experiment(), tmp_path)
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path, side="new~same")
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "no subject or baseline named 'new~same' in the run",
    )


@pytest.mark.parametrize(
    ("kind", "perf_counters", "facts", "code", "words"),
    [
        ("cmd", False, NO_PERF, "E_PROFILER_MISSING", "perf is not installed"),
        (
            "cmd",
            False,
            HostFacts(perf="/usr/bin/perf", paranoid=4, capabilities=0, euid=1000),
            "E_LAUNCH_FAILED",
            "the system does not permit perf: the kernel setting perf_event_paranoid forbids it",
        ),
        (
            "image",
            False,
            OPEN,
            "E_ENGINE_UNSUPPORTED",
            "the container has no capability to use performance counters: "
            "set the launch setting perf_counters",
        ),
    ],
)
def test_what_is_known_before_a_launch_is_refused_before_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    perf_counters: bool,
    facts: HostFacts,
    code: str,
    words: str,
) -> None:
    opener = Opener(FakeSession({}))
    wire(monkeypatch, opener, facts=facts)
    wire_capture(monkeypatch, _experiment(kind, perf_counters=perf_counters), tmp_path)
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path)
    assert (caught.value.code, caught.value.message) == (
        code,
        f"cannot record stacks for side new: {words}",
    )
    assert opener.calls == []


@pytest.mark.parametrize(
    ("action", "code", "words"),
    [
        (
            writes({"stderr.txt": "perf: not found\n"}, rc=127),
            "E_PROFILER_MISSING",
            "the image of the side does not hold perf",
        ),
        (
            writes({"stderr.txt": PARANOID}, rc=255),
            "E_LAUNCH_FAILED",
            "the system does not permit perf: the kernel setting perf_event_paranoid forbids it",
        ),
        (writes({}, rc=1), "E_LAUNCH_FAILED", "the launch under perf record failed"),
    ],
)
def test_a_launch_that_records_nothing_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: Action, code: str, words: str
) -> None:
    session = FakeSession({("new", "stacks"): action})
    wire(monkeypatch, Opener(session))
    wire_capture(monkeypatch, _experiment("image", perf_counters=True), tmp_path)
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path)
    assert (caught.value.code, caught.value.message) == (
        code,
        f"cannot record stacks for side new: {words}",
    )
    assert session.closed == 1
    assert _files(tmp_path) == []


def test_a_refusal_of_the_side_is_passed_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = FakeSession({("new", "stacks"): refuses("E_SIDE_CHANGED")})
    wire(monkeypatch, Opener(session))
    wire_capture(monkeypatch, _experiment(), tmp_path)
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path)
    assert caught.value.code == "E_SIDE_CHANGED"
    assert session.closed == 1


def test_a_recorded_config_that_hides_a_value_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = dataclasses.replace(
        _experiment(), launch=LaunchSettings(env={"API_TOKEN": "x", "N": "1"})
    )
    opener = Opener(FakeSession({}))
    wire(monkeypatch, opener)
    wire_capture(monkeypatch, experiment, tmp_path)
    with pytest.raises(Refusal) as caught:
        explain.record_stacks(tmp_path)
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "the recorded config hides the value of launch.env.API_TOKEN: "
        "the sides cannot be launched as they ran",
    )
    assert opener.calls == []


# ---------------------------------------------------------------------------
# Each way an instrument can be skipped, in each place it is told
# ---------------------------------------------------------------------------

FORBIDS = HostFacts(perf="/usr/bin/perf", paranoid=4, capabilities=0, euid=1000)
SKIPS: dict[str, tuple[str, bool, HostFacts, dict[tuple[str, str], Action], str, str]] = {
    "not_installed": ("cmd", False, NO_PERF, {}, "counters", "its program is not installed"),
    "not_permitted": (
        "cmd",
        False,
        FORBIDS,
        {},
        "counters",
        "the system does not permit it: the kernel setting perf_event_paranoid forbids it",
    ),
    "not_in_image": (
        "image",
        True,
        OPEN,
        {("new", "counters"): writes({}, rc=127)},
        "counters",
        "the image does not hold its program",
    ),
    "no_capability": (
        "image",
        False,
        OPEN,
        {},
        "counters",
        "the container has no capability to use performance counters: "
        "the launch setting perf_counters gives it",
    ),
    "launcher_cannot": (
        "cmd",
        False,
        OPEN,
        {("new", "counters"): refuses("E_ENGINE_UNSUPPORTED")},
        "counters",
        "the side cannot be started under the instrument",
    ),
    "side_changed": (
        "cmd",
        False,
        OPEN,
        {("new", "counters"): refuses("E_SIDE_CHANGED")},
        "counters",
        "the identity of the side differs from the one the run recorded",
    ),
    "launch_failed": (
        "cmd",
        False,
        OPEN,
        {("new", "counters"): writes({}, rc=1)},
        "counters",
        "the launch under the instrument failed",
    ),
    "interpreter_too_old": (
        "cmd",
        False,
        NO_PERF,
        {("new", "pystacks"): writes({"pystacks-too-old.txt": "x"}, rc=86)},
        "pystacks",
        "the interpreter of the side is older than Python 3.8",
    ),
}


@pytest.mark.parametrize("reason", sorted(SKIPS))
def test_a_skipped_instrument_is_told_in_its_row_its_note_and_the_results_and_fails_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    example_results: dict[str, Any],
    reason: str,
) -> None:
    kind, perf_counters, facts, actions, instrument, words = SKIPS[reason]
    defaults = {
        ("new", "pystacks"): writes({"pystacks.folded": FOLDED_NEW}),
        ("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD}),
        **_all_ok(),
    }
    session = FakeSession({**defaults, **actions}, commands={"old": None})
    wire(monkeypatch, Opener(session), facts=facts)
    results = _results(example_results, kind)
    before = results.to_json()
    made = pairbench.explain(_experiment(kind, perf_counters=perf_counters), results, out=tmp_path)
    rows = [r for r in made.instruments if (r.name, r.side) == (instrument, "new")]
    assert [r.reason for r in rows] == [reason]
    assert rows[0].status == ("failed" if reason == "launch_failed" else "skipped")
    note = _skip_note(instrument, "new", words)
    assert note in made.notes
    printed = capsys.readouterr()
    assert printed.out == ""
    line = (
        f"pairbench: note: instrument_skipped: instrument {instrument} did not run for side new: "
    )
    assert line + words in printed.err.splitlines()
    shown = results.pending().finished(
        diagnostics=made.state(), plots=PlotsState(status="off"), notes=made.notes
    )
    assert note in shown.notes
    assert results.to_json() == before
    assert shown.comparisons == results.comparisons
    assert document.read_diagnostics(tmp_path / "diagnostics.json") == made


def test_a_driver_that_puts_its_own_program_first_gives_pystacks_nothing_to_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(
        {("old", "pystacks"): writes({"pystacks.folded": FOLDED_OLD})},
        prepared={
            "new": ("hyperfine", "--export-json", "/pairbench/artifacts/h.json", "python3 x")
        },
    )
    wire(monkeypatch, Opener(session), facts=NO_PERF)
    made = explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    assert session.launched == [("new", "pystacks"), ("old", "pystacks")]
    assert made.instruments[2] == _row("pystacks", "new", "skipped", "launcher_cannot", None)
    assert session.wrapped == [
        (
            "python3",
            "/pairbench/tools/pysampler.py",
            "--out",
            str(tmp_path / ".explain" / "2-old" / "pystacks"),
            "--hz",
            "49",
            "--",
            "bench.py",
        )
    ]


# ---------------------------------------------------------------------------
# The files of the step are owner-only
# ---------------------------------------------------------------------------

# The mode of a file that only its owner may read and write.
OWNER_ONLY = 0o600
STEP_FILES = (
    "diagnostics.json",
    "profiles/new.flame.svg",
    "profiles/new.folded",
    "profiles/new_vs_old.flame-diff.svg",
    "profiles/new_vs_old.folded-diff.tsv",
    "profiles/old.flame.svg",
    "profiles/old.folded",
)


def _modes(out: Path) -> dict[str, int]:
    return {
        str(path.relative_to(out)): stat.S_IMODE(path.stat().st_mode)
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }


def _keeping_the_counts_mode(seen: dict[str, int], side: str, action: Action) -> Action:
    """Run ``action``, which writes the counts file as ``perf stat -o`` does, and keep its mode."""

    def act(folder: Path) -> InstrumentedLaunch:
        launched = action(folder)
        seen[side] = stat.S_IMODE((folder / instruments.STAT_OUTPUT).stat().st_mode)
        return launched

    return act


@pytest.mark.parametrize("mask", [0o002, 0o022], ids=["umask-002", "umask-022"])
def test_every_file_the_explain_step_writes_is_owner_only_whatever_the_umask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], mask: int
) -> None:
    seen: dict[str, int] = {}
    actions = _all_ok()
    for side in ("new", "old"):
        actions[(side, "counters")] = _keeping_the_counts_mode(
            seen, side, actions[(side, "counters")]
        )
    wire(monkeypatch, Opener(FakeSession(actions)))
    first = os.umask(mask)
    try:
        explain.explain_run(_experiment(), _results(example_results), out=tmp_path)
    finally:
        os.umask(first)
    assert _modes(tmp_path) == dict.fromkeys(STEP_FILES, OWNER_ONLY)
    assert seen == {"new": OWNER_ONLY, "old": OWNER_ONLY}


def test_the_stacks_recorded_for_a_profile_are_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = _experiment()
    wire(monkeypatch, Opener(FakeSession(_stacks_only())))
    wire_capture(monkeypatch, experiment, tmp_path)
    first = os.umask(0o022)
    try:
        paths = explain.record_stacks(tmp_path)
    finally:
        os.umask(first)
    assert _modes(tmp_path) == dict.fromkeys(sorted(paths), OWNER_ONLY)
    assert len(paths) == len(STEP_FILES) - 1


# ---------------------------------------------------------------------------
# Each launch writes into a folder the step has just made
# ---------------------------------------------------------------------------

# What an earlier output of ``perf record`` in a folder could hold: made up.
LEFT_PERF_DATA = "a made-up perf.data left from an earlier launch\n"


def _seen_on_launch(actions: Mapping[tuple[str, str], Action], seen: dict[Path, list[str]]) -> None:
    """Make each action first note the names its launch folder holds when the launch starts."""

    def noting(action: Action) -> Action:
        def act(folder: Path) -> InstrumentedLaunch:
            seen[folder] = sorted(p.name for p in folder.iterdir())
            return action(folder)

        return act

    for key, action in list(actions.items()):
        actions[key] = noting(action)  # type: ignore[index]


def _leave(folder: Path) -> Path:
    """Leave a ``perf.data`` in ``folder`` as a stopped launch would; return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    left = folder / "perf.data"
    left.write_text(LEFT_PERF_DATA, encoding="utf-8")
    return left


@pytest.mark.parametrize("left", ["launch-folders", "linked-launches"])
def test_the_explain_step_writes_perf_data_only_into_a_folder_it_has_just_made(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    example_results: dict[str, Any],
    left: str,
) -> None:
    """A folder of the step's launches that is already there is never written into.

    ``perf record`` opens its ``perf.data`` in the launch's folder; only in a
    folder made for that launch is it sure to be a new file.
    """
    out = tmp_path / "run"
    out.mkdir()
    if left == "launch-folders":
        planted = [_leave(out / ".explain" / f / "stacks") for f in ("1-new", "2-old")]
    else:
        elsewhere = tmp_path / "elsewhere"
        planted = [_leave(elsewhere / f / "stacks") for f in ("1-new", "2-old")]
        (out / ".explain").symlink_to(elsewhere, target_is_directory=True)
    actions = _all_ok()
    seen: dict[Path, list[str]] = {}
    _seen_on_launch(actions, seen)
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    explain.explain_run(_experiment(), _results(example_results), out=out)
    assert [(str(f.relative_to(out)), seen[f]) for f in session.folders] == [
        (".explain/1-new/counters", ["perf-stat.txt"]),
        (".explain/1-new/stacks", []),
        (".explain/2-old/counters", ["perf-stat.txt"]),
        (".explain/2-old/stacks", []),
    ]
    if left == "linked-launches":
        assert [p.read_text(encoding="utf-8") for p in planted] == [LEFT_PERF_DATA] * 2
    assert not (out / ".explain").exists()


def test_recorded_stacks_write_perf_data_only_into_a_folder_just_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = _experiment()
    for folder in ("1-new", "2-old"):
        _leave(tmp_path / ".explain" / folder / "stacks")
    actions = _stacks_only()
    seen: dict[Path, list[str]] = {}
    _seen_on_launch(actions, seen)
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    wire_capture(monkeypatch, experiment, tmp_path)
    explain.record_stacks(tmp_path, tool="perf")
    assert [(str(f.relative_to(tmp_path)), seen[f]) for f in session.folders] == [
        (".explain/1-new/stacks", []),
        (".explain/2-old/stacks", []),
    ]
    assert not (tmp_path / ".explain").exists()


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a user that a folder without write permission stops",
)
def test_a_left_folder_of_launches_that_cannot_be_removed_is_refused_before_any_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = _experiment()
    left = _leave(tmp_path / ".explain" / "1-new" / "stacks")
    left.parent.chmod(0o500)
    session = FakeSession(_stacks_only())
    wire(monkeypatch, Opener(session))
    wire_capture(monkeypatch, experiment, tmp_path)
    try:
        with pytest.raises(Refusal) as caught:
            explain.record_stacks(tmp_path, tool="perf")
    finally:
        left.parent.chmod(0o700)
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "the folder .explain in the run folder cannot be made anew for the launches: "
        "Permission denied",
    )
    assert (session.launched, session.closed) == ([], 1)
    assert left.read_text(encoding="utf-8") == LEFT_PERF_DATA


# ---------------------------------------------------------------------------
# The folder of the launches is removed however deep the folders in it go
# ---------------------------------------------------------------------------

# Folders nested in one another below a launch folder: more than Python calls itself by default.
DEEP = sys.getrecursionlimit() + 100
# A folder the step's launches reach, as a stopped launch could leave it.
LEFT_FOLDER = Path(".explain") / "1-new" / "stacks"


def _plant_deep(folder: Path, depth: int = DEEP) -> None:
    """Make ``depth`` folders, each inside the one before, in ``folder``, and a file in the last."""
    folder.mkdir(parents=True, exist_ok=True)
    here = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for _ in range(depth):
            os.mkdir("d", dir_fd=here)
            below = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=here)
            os.close(here)
            here = below
        os.close(os.open("left.txt", os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=here))
    finally:
        os.close(here)


def _clear(top: Path) -> None:
    """Remove what a row left in ``top`` by path, deepest folder first, with nothing recursive."""
    if not os.path.lexists(top):
        return
    if top.is_symlink() or not top.is_dir():
        top.unlink()
        return
    folders = [top]
    waiting = [top]
    while waiting:
        with os.scandir(waiting.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    folders.append(Path(entry.path))
                    waiting.append(Path(entry.path))
                else:
                    os.unlink(entry.path)
    for folder in reversed(folders):
        os.rmdir(folder)


@pytest.fixture
def deep_cleared(tmp_path: Path) -> Iterator[Path]:
    """The run folder of a row that plants a deep tree; what is left of it is removed after."""
    yield tmp_path
    _clear(tmp_path / ".explain")


def _step(
    step: str, monkeypatch: pytest.MonkeyPatch, out: Path, example: dict[str, Any]
) -> tuple[str, ...]:
    """Run the explain step, or record stacks, over ``out``; return the profiles written."""
    experiment = _experiment()
    if step == "explain":
        made = explain.explain_run(experiment, _results(example), out=out)
        return tuple(f"profiles/{s.side}.folded" for s in made.stacks)
    wire_capture(monkeypatch, experiment, out)
    return explain.record_stacks(out, tool="perf")[:2]


def _actions(step: str) -> dict[tuple[str, str], Action]:
    return _all_ok() if step == "explain" else _stacks_only()


def _planting(action: Action) -> Action:
    """Make ``action`` first leave a tree nested deeper than the recursion limit in its folder."""

    def act(folder: Path) -> InstrumentedLaunch:
        _plant_deep(folder / "left")
        return action(folder)

    return act


PROFILES = ("profiles/new.folded", "profiles/old.folded")


@pytest.mark.parametrize("step", ["explain", "stacks"])
def test_a_left_tree_deeper_than_the_recursion_limit_is_removed_before_any_launch(
    deep_cleared: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], step: str
) -> None:
    """What a stopped step left is removed whole, never with an error about recursion."""
    assert sys.getrecursionlimit() < DEEP
    out = deep_cleared
    _plant_deep(out / LEFT_FOLDER)
    actions = _actions(step)
    seen: dict[Path, list[str]] = {}
    _seen_on_launch(actions, seen)
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    assert _step(step, monkeypatch, out, example_results) == PROFILES
    assert seen[out / LEFT_FOLDER] == []
    assert session.closed == 1
    assert not (out / ".explain").exists()


@pytest.mark.parametrize("step", ["explain", "stacks"])
def test_a_tree_deeper_than_the_recursion_limit_a_launch_leaves_is_removed_after_the_step(
    deep_cleared: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], step: str
) -> None:
    out = deep_cleared
    actions = _actions(step)
    actions[("new", "stacks")] = _planting(actions[("new", "stacks")])
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    assert _step(step, monkeypatch, out, example_results) == PROFILES
    assert session.closed == 1
    assert not (out / ".explain").exists()


@pytest.mark.parametrize("step", ["explain", "stacks"])
def test_the_error_of_a_launch_that_left_a_deep_tree_is_the_error_passed_on(
    deep_cleared: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], step: str
) -> None:
    error = RuntimeError("a made-up failure of the launch")

    def boom(folder: Path) -> InstrumentedLaunch:
        _plant_deep(folder / "left")
        raise error

    out = deep_cleared
    actions = _actions(step)
    actions[("new", "stacks")] = boom
    session = FakeSession(actions)
    wire(monkeypatch, Opener(session))
    with pytest.raises(RuntimeError) as caught:
        _step(step, monkeypatch, out, example_results)
    assert caught.value is error
    assert session.closed == 1
    assert not (out / ".explain").exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="needs a system that limits the files a process keeps open"
)
def test_a_left_deep_tree_is_removed_with_few_files_open(
    deep_cleared: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    """The removal keeps a few folders open at a time, not one for each level of the tree."""
    import resource

    out = deep_cleared
    _plant_deep(out / LEFT_FOLDER)
    session = FakeSession(_all_ok())
    wire(monkeypatch, Opener(session))
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    few = 256
    assert few < DEEP
    resource.setrlimit(resource.RLIMIT_NOFILE, (few, hard))
    try:
        assert _step("explain", monkeypatch, out, example_results) == PROFILES
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert not (out / ".explain").exists()


@pytest.mark.parametrize("when", ["left-before", "left-by-a-launch"])
def test_a_link_in_the_folder_of_the_launches_is_removed_and_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any], when: str
) -> None:
    elsewhere = tmp_path / "elsewhere"
    kept = _leave(elsewhere / "inner")
    out = tmp_path / "run"
    actions = _all_ok()
    if when == "left-before":
        (out / ".explain" / "1-new").mkdir(parents=True)
        (out / ".explain" / "1-new" / "linked").symlink_to(elsewhere, target_is_directory=True)
    else:
        out.mkdir()
        made = actions[("new", "stacks")]

        def linking(folder: Path) -> InstrumentedLaunch:
            (folder / "linked").symlink_to(elsewhere, target_is_directory=True)
            return made(folder)

        actions[("new", "stacks")] = linking
    wire(monkeypatch, Opener(FakeSession(actions)))
    assert _step("explain", monkeypatch, out, example_results) == PROFILES
    assert kept.read_text(encoding="utf-8") == LEFT_PERF_DATA
    assert sorted(p.name for p in elsewhere.iterdir()) == ["inner"]
    assert not (out / ".explain").exists()


def _too_deep(path: Any, ignore_errors: bool = False) -> None:
    raise RecursionError("maximum recursion depth exceeded")


def test_where_no_folder_opens_by_handle_a_tree_too_deep_to_remove_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    left = _leave(tmp_path / LEFT_FOLDER)
    session = FakeSession(_all_ok())
    wire(monkeypatch, Opener(session))
    monkeypatch.setattr(explain, "_CAN_REMOVE_BY_HANDLE", False)
    monkeypatch.setattr(explain.shutil, "rmtree", _too_deep)
    with pytest.raises(Refusal) as caught:
        _step("explain", monkeypatch, tmp_path, example_results)
    assert (caught.value.code, caught.value.message) == (
        "E_USAGE",
        "the folder .explain in the run folder cannot be made anew for the launches: "
        "it holds folders nested too deeply to remove",
    )
    assert (session.launched, session.closed) == ([], 1)
    assert left.read_text(encoding="utf-8") == LEFT_PERF_DATA


def test_where_no_folder_opens_by_handle_a_tree_too_deep_to_remove_after_the_step_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, example_results: dict[str, Any]
) -> None:
    session = FakeSession(_all_ok())
    wire(monkeypatch, Opener(session))
    monkeypatch.setattr(explain, "_CAN_REMOVE_BY_HANDLE", False)
    monkeypatch.setattr(explain.shutil, "rmtree", _too_deep)
    assert _step("explain", monkeypatch, tmp_path, example_results) == PROFILES
    assert session.closed == 1
    assert (tmp_path / ".explain" / "1-new" / "stacks").is_dir()


@pytest.mark.parametrize("keep_going", [False, True], ids=["refused", "kept-going"])
def test_a_folder_moved_away_while_it_is_removed_is_not_climbed_out_of(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep_going: bool
) -> None:
    """Coming back up lands in the folder the removal came from, or the removal ends there."""
    top = tmp_path / ".explain"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for name in ("a", "b"):
        (top / name / "inner").mkdir(parents=True)
    kept: list[Path] = []
    real = explain._remove_files

    def moving(folder: int, keep_going: bool) -> list[str]:
        """Move the first folder entered out of the tree once the removal is below it."""
        found = os.fstat(folder)
        for name, other in (("a", "b"), ("b", "a")):
            inner = top / name / "inner"
            if not kept and inner.exists() and os.path.samestat(found, inner.stat()):
                kept.append(_leave(elsewhere / other))
                (top / name).rename(elsewhere / name)
        return real(folder, keep_going)

    monkeypatch.setattr(explain, "_remove_files", moving)
    if keep_going:
        explain._remove_tree(top, keep_going=True)
    else:
        with pytest.raises(OSError) as caught:
            explain._remove_tree(top)
        assert caught.value.strerror == "a folder in it was moved away while it was being removed"
    assert [p.read_text(encoding="utf-8") for p in kept] == [LEFT_PERF_DATA]
