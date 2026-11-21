# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The explain step, and ``pairbench profile --tool perf``.

The explain step runs after a run's capture is closed and its results are
written. It decides from ``explain.mode`` and the outcomes whether to run:
``off`` never runs, ``auto`` runs only when a primary case came out
``better`` or ``worse``, ``always`` always runs. Each subject and the
baseline (never a twin, never the positive control) is launched once more
for each instrument that is installed and permitted, through the session of
``pairbench.runner:open_explain``, the one way this package reaches a side:
``counters`` first, then ``stacks``, or ``pystacks`` in place of ``stacks``
where ``stacks`` cannot run and the side's command starts with a Python
interpreter.

What can be told without a launch is skipped without one: ``perf`` is not
installed or the system forbids it (for a side on this machine), or an image
side has no capability to use performance counters. A skipped or failed
instrument gets a row under ``instruments`` and a loud note in the document,
and never fails the step. A lock that cannot be taken skips every launch: the
document then holds a ``lock`` row for each side and instrument and one note.
A side whose identity changed is skipped. Nothing is printed here; the
caller prints the notes.

Each launch keeps its files in a folder under ``.explain/`` in the run
folder while it is read: one folder per side, named by the side's place in
the order of the sides and its name in a file name, so no side name can
lead out of ``.explain/``. The folder is removed afterwards, however deep
the folders a launch leaves in it go, so the run folder holds only
``diagnostics.json`` and the files under ``profiles/``.

A finding whose text would read as naming a cause, because a side, function
or shared-object name holds such a word, is left out, and one note per
subject names the finding ids that were left out.
"""

from __future__ import annotations

import errno
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, cast

from pairbench import api
from pairbench.api import ExplainSession, Instrument, InstrumentedLaunch, OpenExplain
from pairbench.diagnose import document, findings, flame, folded, instruments, pysampler
from pairbench.diagnose.instruments import HostFacts, Place
from pairbench.errors import Refusal
from pairbench.model import (
    FILE_CAPTURE,
    KIND_CMD,
    KIND_CONDA,
    KIND_FILE,
    KIND_IMAGE,
    KIND_PYTHON,
    KIND_ROWS,
    KIND_SERVE,
    KIND_VENV,
    NOTE_EXPLAIN_SKIPPED,
    NOTE_FINDING_LEFT_OUT,
    NOTE_STACK_INSTRUMENTS_DIFFER,
    NOTE_STACKS_NOT_SAMPLED,
    REDACTED,
    Diagnostics,
    DiagnosticsFiles,
    DiagnosticsRun,
    DiagnosticsState,
    Experiment,
    Finding,
    InstrumentName,
    InstrumentReason,
    InstrumentRun,
    InstrumentStatus,
    Note,
    Results,
    StackInstrument,
    StackSummary,
    file_names,
    flame_diff_file,
    flame_file,
    folded_diff_file,
    folded_file,
    starts_with_python,
)

# The folder of the run folder where explain launches keep their files while they are read.
LAUNCHES: Final = ".explain"
# The reasons for which ``stacks`` cannot run on a side, so ``pystacks`` may take its place.
STACKS_CANNOT_RUN: Final = frozenset(
    {"not_installed", "not_permitted", "not_in_image", "no_capability"}
)
# Reasons found on the ``counters`` launch that hold for ``stacks`` on the same side.
SAME_FOR_STACKS: Final = frozenset({"not_in_image", "launcher_cannot", "side_changed"})
_ON_HOST: Final = frozenset({KIND_CMD, KIND_PYTHON, KIND_VENV, KIND_CONDA})
# The outputs an instrument's tool opens itself and that would take the
# umask's mode: each is made owner-only before its launch, and the tool keeps
# that mode when it writes into it.
_MADE_BY_THE_TOOL: Final[Mapping[str, tuple[str, ...]]] = {
    "counters": (instruments.STAT_OUTPUT,),
}
_NOTHING_TO_LAUNCH: Final = frozenset({KIND_FILE, KIND_ROWS})

Where = Literal["host", "container", "unknown", "none"]


def explain_decision(experiment: Experiment, results: Results) -> DiagnosticsState | None:
    """Return the state of a step that does not run, or ``None`` when it runs.

    Mode ``off`` gives ``off``; mode ``auto`` without a primary case that
    came out ``better`` or ``worse`` gives ``skipped`` with the reason
    ``mode_auto_no_difference``.
    """
    mode = experiment.explain.mode
    if mode == "off":
        return DiagnosticsState(status="off")
    if mode == "auto" and not results.has_difference():
        return DiagnosticsState(status="skipped", reason="mode_auto_no_difference")
    return None


def explained_sides(results: Results) -> tuple[str, ...]:
    """Return the sides the step launches: each subject and the baseline, in the results' order."""
    return tuple(s.name for s in results.sides if s.role in ("subject", "baseline"))


def _launch_folder(launches: Path, number: int, written: str) -> Path:
    """Return the folder of one side's launches: its place in the order and its written name."""
    return launches / f"{number}-{written}"


def _make_anew(launches: Path) -> None:
    """Make the folder the explain launches keep their files in, new and empty.

    What a stopped explain step left under that name, a folder or a link, is
    removed first, however deep its folders go. Every launch folder is then
    made in it, so an instrument writes its output, such as the ``perf.data``
    of ``perf record``, only into a folder made for its launch, never into one
    that could already hold it.
    """
    try:
        if launches.is_symlink() or (launches.exists() and not launches.is_dir()):
            launches.unlink()
        elif launches.exists():
            _remove_tree(launches)
        launches.mkdir()
    except OSError as exc:
        raise Refusal(
            "E_USAGE",
            f"the folder {LAUNCHES} in the run folder cannot be made anew for the launches: "
            f"{exc.strerror}",
        ) from None


# Opens a folder by one name as found: a name that is a link or not a folder is refused.
_OPEN_FOLDER: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
# The removal opens, lists and removes names relative to an open folder.
_CAN_REMOVE_BY_HANDLE: Final = (
    os.open in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd
    and os.scandir in os.supports_fd
    and hasattr(os, "O_NOFOLLOW")
    and hasattr(os, "O_DIRECTORY")
)
# Why a folder of launches is not removed: a folder in it moved while it was being removed.
_MOVED: Final = "a folder in it was moved away while it was being removed"
# Why a folder of launches is not removed where no folder can be opened by handle.
_TOO_DEEP: Final = "it holds folders nested too deeply to remove"


def _remove_tree(top: Path, *, keep_going: bool = False) -> None:
    """Remove the folder ``top`` and everything in it, however deep its folders go.

    The removal goes down one folder at a time, removing through each open
    folder the files and links it holds, and comes back up through each
    folder's entry for its parent, checking that it lands in the folder it
    came from. So it calls nothing recursively, holds two descriptors at most
    however deep the folders go, and removes a link without following it.
    What is already gone counts as removed. The first entry that cannot be
    removed raises ``OSError``; with ``keep_going``, that entry is left with
    the folders that hold it, and the rest is removed. Where the system cannot
    open or remove a name relative to an open folder, ``shutil.rmtree``
    removes the tree, and a tree too deep for it is an ``OSError`` too.
    """
    if not _CAN_REMOVE_BY_HANDLE:
        _remove_by_path(top, keep_going=keep_going)
        return
    try:
        here = os.open(top, _OPEN_FOLDER)
    except OSError as error:
        _unless_kept_going(error, keep_going)
        return
    try:
        # Each folder still being emptied: its identity, its name in the folder
        # above it, and the folders in it not yet entered.
        open_folders = [(_identity(here), "", _remove_files(here, keep_going))]
        while open_folders:
            waiting = open_folders[-1][2]
            if waiting:
                name = waiting.pop()
                try:
                    below = os.open(name, _OPEN_FOLDER, dir_fd=here)
                except OSError as error:
                    _unless_kept_going(error, keep_going)
                    continue
                os.close(here)
                here = below
                open_folders.append((_identity(here), name, _remove_files(here, keep_going)))
                continue
            name = open_folders.pop()[1]
            if not open_folders:
                break
            above = os.open("..", _OPEN_FOLDER, dir_fd=here)
            os.close(here)
            here = above
            if _identity(here) != open_folders[-1][0]:
                raise OSError(errno.ENOTEMPTY, _MOVED)
            try:
                os.rmdir(name, dir_fd=here)
            except OSError as error:
                _unless_kept_going(error, keep_going)
    except OSError:
        if keep_going:
            return
        raise
    finally:
        os.close(here)
    try:
        os.rmdir(top)
    except OSError as error:
        _unless_kept_going(error, keep_going)


def _remove_files(folder: int, keep_going: bool) -> list[str]:
    """Remove the files and links in the open ``folder``; return the names of the folders in it."""
    folders: list[str] = []
    others: list[str] = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    is_folder = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_folder = False
                (folders if is_folder else others).append(entry.name)
    except OSError as error:
        _unless_kept_going(error, keep_going)
        return []
    for name in others:
        try:
            os.unlink(name, dir_fd=folder)
        except OSError as error:
            _unless_kept_going(error, keep_going)
    return folders


def _identity(descriptor: int) -> tuple[int, int]:
    """The device and inode of the file open as ``descriptor``."""
    found = os.fstat(descriptor)
    return found.st_dev, found.st_ino


def _unless_kept_going(error: OSError, keep_going: bool) -> None:
    """Raise ``error``, unless what it is about is already gone or the removal keeps going."""
    if not keep_going and not isinstance(error, FileNotFoundError):
        raise error


def _remove_by_path(top: Path, *, keep_going: bool) -> None:
    """Remove the folder ``top`` by its path, as where no folder can be opened by handle."""
    try:
        shutil.rmtree(top, ignore_errors=keep_going)
    except RecursionError:
        if not keep_going:
            raise OSError(errno.ENOTEMPTY, _TOO_DEEP) from None


def _left_out_notes(left_out: Mapping[str, Sequence[str]], baseline: str | None) -> list[Note]:
    """Return one note per subject that had findings left out for the words of a name."""
    return [
        Note(
            code=NOTE_FINDING_LEFT_OUT,
            message=(
                f"the findings {', '.join(dict.fromkeys(ids))} of side {subject} against side "
                f"{baseline} are left out: a side, function or shared-object name in their "
                "text reads as a word a finding never uses"
            ),
        )
        for subject, ids in left_out.items()
        if ids
    ]


def _baseline(results: Results) -> str | None:
    return next((s.name for s in results.sides if s.role == "baseline"), None)


def where(experiment: Experiment, name: str) -> tuple[Where, bool]:
    """Return where a side runs and whether its launch setting ``perf_counters`` is on.

    A command side and a Python environment side run on this machine; an
    image side in a container; a serving side on this machine under the
    ``host`` launcher and in a container under every other; a file side and
    a side made from rows launch nothing. A kind a plug-in provides is
    ``unknown``.
    """
    try:
        side = experiment.side(name)
    except Refusal:
        return "unknown", False
    perf_counters = experiment.launch.for_side(side).perf_counters
    if side.kind in _ON_HOST:
        return "host", perf_counters
    if side.kind == KIND_IMAGE:
        return "container", perf_counters
    if side.kind == KIND_SERVE:
        return ("host" if side.spec.get("launcher") == "host" else "container"), perf_counters
    if side.kind in _NOTHING_TO_LAUNCH:
        return "none", perf_counters
    return "unknown", perf_counters


@dataclass
class _Step:
    """What the launches of one explain step found."""

    rows: list[InstrumentRun] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    counts: dict[str, Mapping[str, float]] = field(default_factory=dict)
    profiles: dict[str, folded.Profile] = field(default_factory=dict)

    def record(self, row: InstrumentRun) -> InstrumentRun:
        self.rows.append(row)
        note = row.note()
        if note is not None:
            self.notes.append(note)
        return row

    def heard(self, code: str, message: str) -> None:
        self.notes.append(Note(code=code, message=message))


def _row(
    name: str, side: str, status: InstrumentStatus, reason: InstrumentReason | None, rc: int | None
) -> InstrumentRun:
    return InstrumentRun(
        name=cast(InstrumentName, name), side=side, status=status, reason=reason, rc=rc
    )


def _skipped(name: str, side: str, reason: InstrumentReason) -> InstrumentRun:
    return _row(name, side, "skipped", reason, None)


def _launch(
    session: ExplainSession, side: str, instrument: Instrument, folder: Path, place: Place
) -> tuple[InstrumentRun, InstrumentedLaunch | None]:
    """Run one explain launch and judge it. A refusal of the side is recorded, not raised."""
    folder.mkdir(parents=True)
    for name in _MADE_BY_THE_TOOL.get(instrument.name, ()):
        document.create_private(folder / name)
    try:
        launched = session.launch(side, instrument, folder)
    except Refusal as refusal:
        refused = api.instrument_reason(refusal)
        status: InstrumentStatus = "failed" if refused == "launch_failed" else "skipped"
        return _row(instrument.name, side, status, refused, None), None
    status, reason = instruments.judge_launch(instrument.name, launched, place)
    return _row(instrument.name, side, status, reason, launched.rc), launched


def _read(folder: Path, name: str) -> str:
    try:
        return (folder / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _explain_side(
    session: ExplainSession,
    experiment: Experiment,
    side: str,
    folder: Path,
    facts: HostFacts,
    step: _Step,
) -> None:
    """Launch one side under ``counters`` and under one stack instrument, recording each."""
    kind_place, perf_counters = where(experiment, side)
    if kind_place == "none":
        step.record(_skipped("counters", side, "launcher_cannot"))
        step.record(_skipped("stacks", side, "launcher_cannot"))
        return
    place: Place = kind_place
    hz, graph = experiment.explain.sample_hz, experiment.explain.call_graph

    reason: InstrumentReason | None = instruments.skip_before_launch(
        "counters", place, facts, perf_counters
    )
    if reason is not None:
        counters_row = step.record(_skipped("counters", side, reason))
    else:
        counters_row, launched = _launch(
            session, side, instruments.counters, folder / "counters", place
        )
        step.record(counters_row)
        if counters_row.status == "ok" and launched is not None:
            reading = instruments.read_counters(_read(launched.artifacts, instruments.STAT_OUTPUT))
            step.counts[side] = reading.values

    reason = instruments.skip_before_launch("stacks", place, facts, perf_counters)
    if reason is None and counters_row.reason in SAME_FOR_STACKS:
        reason = counters_row.reason
    if reason is not None:
        stacks_row = step.record(_skipped("stacks", side, reason))
    else:
        stacks_row, launched = _launch(
            session, side, instruments.Stacks(hz=hz, call_graph=graph), folder / "stacks", place
        )
        step.record(stacks_row)
        if stacks_row.status == "ok" and launched is not None:
            step.profiles[side] = folded.parse_perf_script(
                _read(launched.artifacts, instruments.SCRIPT_OUTPUT),
                _read(launched.artifacts, instruments.BUILDIDS_OUTPUT),
            )

    if stacks_row.reason not in STACKS_CANNOT_RUN:
        return
    try:
        command = session.command(side)
    except Refusal as refusal:
        step.record(_skipped("pystacks", side, api.instrument_reason(refusal)))
        return
    if not starts_with_python(command):
        return
    sampler_row, launched = _launch(
        session, side, instruments.PyStacks(hz=hz), folder / "pystacks", place
    )
    step.record(sampler_row)
    if sampler_row.status == "ok" and launched is not None:
        try:
            profile = folded.profile_from_folded(
                _read(launched.artifacts, pysampler.FOLDED_OUTPUT), "pystacks"
            )
        except ValueError:
            step.rows[-1] = sampler_row = InstrumentRun(
                name="pystacks", side=side, status="failed", reason="launch_failed", rc=launched.rc
            )
            note = sampler_row.note()
            if note is not None:
                step.notes.append(note)
            return
        if not profile.stacks:
            step.notes.append(
                Note(
                    code=NOTE_STACKS_NOT_SAMPLED,
                    message=f"instrument pystacks took no samples for side {side}: the launch "
                    "ended before the first sample",
                )
            )
            return
        step.profiles[side] = profile


def _write_profiles(
    out: Path,
    profiles: Mapping[str, folded.Profile],
    name_map: Mapping[str, str],
    subjects: Sequence[str],
    baseline: str | None,
    notes: list[Note],
) -> DiagnosticsFiles:
    """Write the folded files and flame graphs, and per subject the difference file and graph."""
    folded_files: list[str] = []
    flame_files: list[str] = []
    diff_files: list[str] = []
    diff_graphs: list[str] = []
    for side, profile in profiles.items():
        path = folded_file(name_map[side])
        document.write_text(out / path, folded.folded_text(profile.stacks))
        folded_files.append(path)
        graph = flame_file(name_map[side])
        document.write_text(
            out / graph, flame.flame_svg(profile.stacks, side=side, instrument=profile.instrument)
        )
        flame_files.append(graph)
    if baseline is not None and baseline in profiles:
        other = profiles[baseline]
        for subject in subjects:
            own = profiles.get(subject)
            if own is None:
                continue
            if own.instrument != other.instrument:
                notes.append(
                    Note(
                        code=NOTE_STACK_INSTRUMENTS_DIFFER,
                        message=(
                            f"the stacks of side {subject} come from instrument {own.instrument} "
                            f"and those of side {baseline} from instrument {other.instrument}: "
                            "no difference file and no difference graph are made"
                        ),
                    )
                )
                continue
            path = folded_diff_file(name_map[subject], name_map[baseline])
            document.write_text(
                out / path, folded.diff_text(folded.diff_rows(own.stacks, other.stacks))
            )
            diff_files.append(path)
            graph = flame_diff_file(name_map[subject], name_map[baseline])
            document.write_text(
                out / graph,
                flame.flame_diff_svg(
                    own.stacks,
                    other.stacks,
                    subject=subject,
                    baseline=baseline,
                    instrument=own.instrument,
                ),
            )
            diff_graphs.append(graph)
    return DiagnosticsFiles(
        folded=tuple(folded_files),
        folded_diff=tuple(diff_files),
        flame=tuple(flame_files),
        flame_diff=tuple(diff_graphs),
    )


def _resource_findings(
    results: Results,
    subjects: Iterable[str],
    baseline: str | None,
    left_out: Mapping[str, list[str]],
) -> list[Finding]:
    if baseline is None:
        return []
    out: list[Finding] = []
    for subject in subjects:
        out.extend(
            findings.resource_findings(results, subject, baseline, left_out=left_out[subject])
        )
    return out


def explain_run(experiment: Experiment, results: Results, *, out: Path) -> Diagnostics:
    """Run the explain step, write ``diagnostics.json`` and ``profiles/``, return the document.

    When the mode says the step does not run, nothing is launched and
    nothing is written: the document returned holds the resource rows and
    their findings and no instrument row. A run whose sides are result files
    or rows launches nothing either; its document says so for each side.
    ``E_LOCK`` from opening the session is not passed on.
    """
    out = Path(out)
    sides = explained_sides(results)
    baseline = _baseline(results)
    subjects = [s for s in sides if s != baseline]
    name_map = file_names(sides)
    resources = findings.resource_rows(results, sides)
    left_out: dict[str, list[str]] = {subject: [] for subject in subjects}
    resource_findings = _resource_findings(results, subjects, baseline, left_out)
    run = DiagnosticsRun(id=results.run.id)
    if explain_decision(experiment, results) is not None:
        return Diagnostics(
            run=run,
            resources=resources,
            findings=tuple(resource_findings),
            name_map=name_map,
            notes=tuple(_left_out_notes(left_out, baseline)),
        )

    step = _Step()
    if any(s.kind in _NOTHING_TO_LAUNCH for s in results.sides if s.name in sides):
        # A run read from result files or rows plans no explain launch (and
        # takes no lock for one): every row says the side cannot be started.
        for side in sides:
            step.record(_skipped("counters", side, "launcher_cannot"))
            step.record(_skipped("stacks", side, "launcher_cannot"))
        made = Diagnostics(
            run=run,
            instruments=tuple(step.rows),
            resources=resources,
            findings=tuple(resource_findings),
            name_map=name_map,
            notes=(*step.notes, *_left_out_notes(left_out, baseline)),
        )
        document.write_diagnostics(made, out)
        return made
    fingerprints = {s.name: s.fingerprint for s in results.sides if s.name in sides}
    open_explain: OpenExplain = api.delegate("open_explain")
    try:
        session = open_explain(
            experiment, run_id=results.run.id, fingerprints=fingerprints, note=step.heard
        )
    except Refusal as refusal:
        if refusal.code != "E_LOCK":
            raise
        locked = tuple(
            _skipped(name, side, "lock") for side in sides for name in ("counters", "stacks")
        )
        made = Diagnostics(
            run=run,
            instruments=locked,
            resources=resources,
            findings=tuple(resource_findings),
            name_map=name_map,
            notes=(
                *step.notes,
                Note(
                    code=NOTE_EXPLAIN_SKIPPED,
                    message=(
                        "the explain step was skipped: a lock could not be taken, "
                        "so no instrument ran on any side"
                    ),
                ),
                *_left_out_notes(left_out, baseline),
            ),
        )
        document.write_diagnostics(made, out)
        return made

    launches = out / LAUNCHES
    facts = instruments.host_facts(os.environ)
    try:
        _make_anew(launches)
        for number, side in enumerate(sides, start=1):
            folder = _launch_folder(launches, number, name_map[side])
            _explain_side(session, experiment, side, folder, facts, step)
    finally:
        session.close()
        _remove_tree(launches, keep_going=True)

    files = _write_profiles(out, step.profiles, name_map, subjects, baseline, step.notes)
    top = experiment.explain.top
    summaries = tuple(
        StackSummary(
            side=side,
            instrument=cast(StackInstrument, profile.instrument),
            samples=profile.samples,
            top_functions=folded.top_functions(profile, top),
            top_objects=folded.top_objects(profile, top),
        )
        for side, profile in step.profiles.items()
    )
    counter_rows: list[Any] = []
    all_findings = list(resource_findings)
    if baseline is not None:
        for subject in subjects:
            rows = findings.counter_rows(
                subject, baseline, step.counts.get(subject), step.counts.get(baseline)
            )
            counter_rows.extend(rows)
            all_findings.extend(findings.counter_findings(rows, left_out=left_out[subject]))
        for subject in subjects:
            own, other = step.profiles.get(subject), step.profiles.get(baseline)
            if own is not None and other is not None:
                all_findings.extend(
                    findings.stack_findings(
                        subject, baseline, own, other, left_out=left_out[subject]
                    )
                )
    made = Diagnostics(
        run=run,
        instruments=tuple(step.rows),
        resources=resources,
        counters=tuple(counter_rows),
        stacks=summaries,
        objects=folded.compare_objects(step.profiles),
        findings=tuple(all_findings),
        files=files,
        name_map=name_map,
        notes=(*step.notes, *_left_out_notes(left_out, baseline)),
    )
    document.write_diagnostics(made, out)
    return made


# ---------------------------------------------------------------------------
# pairbench profile --tool perf
# ---------------------------------------------------------------------------


def _redacted_keys(value: Any, path: str = "") -> list[str]:
    """Name every key of a recorded config whose value is hidden."""
    if isinstance(value, Mapping):
        found: list[str] = []
        for key, inner in value.items():
            found.extend(_redacted_keys(inner, f"{path}.{key}" if path else str(key)))
        return found
    if isinstance(value, (list, tuple)):
        return [k for item in value for k in _redacted_keys(item, path)]
    return [path] if value == REDACTED else []


_REFUSED_FOR: Final[Mapping[str, tuple[str, str]]] = {
    "not_installed": ("E_PROFILER_MISSING", "perf is not installed"),
    "not_in_image": ("E_PROFILER_MISSING", "the image of the side does not hold perf"),
    "no_capability": (
        "E_ENGINE_UNSUPPORTED",
        "the container has no capability to use performance counters: "
        "set the launch setting perf_counters",
    ),
    "not_permitted": (
        "E_LAUNCH_FAILED",
        "the system does not permit perf: the kernel setting perf_event_paranoid forbids it",
    ),
    "launch_failed": ("E_LAUNCH_FAILED", "the launch under perf record failed"),
}


def _refuse(reason: str, side: str) -> Refusal:
    code, words = _REFUSED_FOR.get(reason, _REFUSED_FOR["launch_failed"])
    return Refusal(code, f"cannot record stacks for side {side}: {words}")


def record_stacks(
    run_dir: Path, *, tool: str = "perf", case: str | None = None, side: str | None = None
) -> tuple[str, ...]:
    """Record stacks with ``perf`` for one side, or for each subject and the baseline.

    The run folder's capture gives the experiment and the fingerprints.
    The folded files and flame graphs are written under ``profiles/`` as
    the explain step writes them, with the difference file and graph of
    each subject when the baseline was recorded too, and their paths are
    returned relative to the run folder. ``diagnostics.json`` is not
    touched. ``case`` selects nothing: stacks cover a whole launch.

    Because a tool was asked for, every way the recording cannot happen is
    a refusal: ``perf`` not installed, on this machine or in the image, is
    ``E_PROFILER_MISSING``; an image side without ``perf_counters`` is
    ``E_ENGINE_UNSUPPORTED``; a system that forbids ``perf`` and a failed
    launch are ``E_LAUNCH_FAILED``; a refusal of the side is passed on. A
    recorded config that hides a value is refused with ``E_USAGE``: the side
    would not run as it ran. So is a run folder in which the folder of the
    launches cannot be made anew.
    """
    del case
    if tool != "perf":
        raise Refusal("E_USAGE", f"stacks are recorded with perf, not with {tool}")
    from pairbench import load_capture

    folder = Path(run_dir)
    capture = load_capture(folder / FILE_CAPTURE)[0]
    hidden = _redacted_keys(capture.header.config)
    if hidden:
        raise Refusal(
            "E_USAGE",
            "the recorded config hides the value of "
            + ", ".join(sorted(hidden))
            + ": the sides cannot be launched as they ran",
        )
    experiment = Experiment.from_json(dict(capture.header.config))
    launched = [s for s in capture.sides if s.role in ("subject", "baseline")]
    names = [s.name for s in launched]
    if side is not None and side not in names:
        raise Refusal("E_USAGE", f"no subject or baseline named {side!r} in the run")
    chosen = [side] if side is not None else names
    baseline = next((s.name for s in launched if s.role == "baseline"), None)
    facts = instruments.host_facts(os.environ)
    for name in chosen:
        place, perf_counters = where(experiment, name)
        if place == "none":
            raise Refusal("E_USAGE", f"side {name} launches nothing to record")
        reason = instruments.skip_before_launch("stacks", place, facts, perf_counters)
        if reason is not None:
            raise _refuse(reason, name)
    name_map = file_names(names)
    profiles: dict[str, folded.Profile] = {}
    open_explain: OpenExplain = api.delegate("open_explain")
    session = open_explain(
        experiment,
        run_id=capture.capture_id,
        fingerprints={s.name: s.fingerprint for s in launched},
    )
    launches = folder / LAUNCHES
    stack_instrument = instruments.Stacks(
        hz=experiment.explain.sample_hz, call_graph=experiment.explain.call_graph
    )
    try:
        _make_anew(launches)
        for number, name in enumerate(chosen, start=1):
            place, _perf_counters = where(experiment, name)
            target = _launch_folder(launches, number, name_map[name]) / "stacks"
            target.mkdir(parents=True)
            result = session.launch(name, stack_instrument, target)
            status, reason = instruments.judge_launch(
                "stacks", result, place if place != "none" else "unknown"
            )
            if status != "ok":
                raise _refuse(reason or "launch_failed", name)
            profiles[name] = folded.parse_perf_script(
                _read(result.artifacts, instruments.SCRIPT_OUTPUT),
                _read(result.artifacts, instruments.BUILDIDS_OUTPUT),
            )
    finally:
        session.close()
        _remove_tree(launches, keep_going=True)
    subjects = [n for n in chosen if n != baseline]
    files = _write_profiles(folder, profiles, name_map, subjects, baseline, [])
    return (*files.folded, *files.flame, *files.folded_diff, *files.flame_diff)
