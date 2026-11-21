# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Running an experiment: the one module that composes sides, drivers, checks and energy.

``run_experiment`` checks the experiment, resolves every side, lays out the
plan, runs the machine checks, takes the locks, runs the warm-up launches,
measures the cost of a launch, runs every row of the plan and writes the
capture as it goes. It reaches side kinds, drivers and machine checks through
the registry and the services of ``RunServices``, and imports none of their
modules, except the function of the machine checks that words the notes for
a failed witness probe.

``look_up_sides`` runs the checks of the plan command. ``open_explain`` opens
the untimed launches of the explain step. ``record_profiles`` runs one
untimed launch per side under a GPU profiler.

While a launch runs, nothing is written to the capture and nothing is
printed: a note that arrives during a launch is held and given out after it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pairbench import registry
from pairbench.api import (
    DEFAULT_SEED,
    GROUP_DRIVERS,
    GROUP_GATES,
    GROUP_SIDE_KINDS,
    CaseNames,
    CpuFacts,
    Driver,
    DriverContext,
    Endpoint,
    EnergyReading,
    ExplainSession,
    GateContext,
    Instrument,
    InstrumentedCommand,
    InstrumentedLaunch,
    LaunchOutcome,
    LaunchPhase,
    LaunchRequest,
    LockSet,
    MachineChecks,
    Notify,
    PowerSampler,
    PreparedRun,
    ProfiledCommand,
    Profiler,
    ReportsToolVersion,
    ResolvedSide,
    RunServices,
    Sample,
    SideContext,
    SideLookup,
    Window,
    case_of,
    clock_cases,
    combine_runs,
    control_samples,
    default_services,
    env_pad,
    gate_line,
    is_ci,
    missing_resource_cases,
    no_notes,
    note_line,
    recorded_command_line,
    refuse_reserved_cases,
    resource_samples,
    run_folders,
    shown_cases,
    uncombined_cases,
    work_factor_env,
)
from pairbench.capture.reader import JsonlReader
from pairbench.capture.writer import CaptureWriter
from pairbench.errors import EXIT_SIDE, Refusal
from pairbench.gates.discard import witness_notes
from pairbench.gates.platform import all_selected, format_cpu_list, parse_cpu_list
from pairbench.model import (
    BUILTIN_GATES,
    CASE_KEY_BYTES,
    DIR_ARTIFACTS,
    DIR_PROFILES,
    DIR_RUNS,
    EMPTY_COMMAND,
    FILE_CAPTURE,
    FILE_PLAN,
    KIND_CMD,
    KIND_FILE,
    KIND_IMAGE,
    KIND_SERVE,
    NOTE_CONTROL_CANNOT_REPEAT,
    NOTE_CONTROL_CASE_MISSING,
    NOTE_DECLARED_IDENTICAL,
    NOTE_HIDDEN_DIFFERENCE,
    NOTE_LAUNCH_COST_NOT_MEASURED,
    NOTE_NEW_CASE,
    NOTE_RESOURCE_FIGURE_MISSING,
    NOTE_TOOL_ON_PINNED_CPUS,
    NOTE_TOOL_VERSION_UNTESTED,
    NOTE_UNBALANCED,
    NOTE_UNDERPOWERED,
    NOTE_UNPINNED_MIXED_CORES,
    NOTE_WITNESS_UNDECIDED,
    REDACTED,
    SEED_DRIVER,
    SEED_ENV_PAD,
    WORKLOAD_PLACEHOLDER,
    Capture,
    Case,
    CaseKeyRecord,
    CaseNamesRecord,
    CasesRecord,
    CpuGroup,
    End,
    EndStatus,
    Experiment,
    GateRecord,
    GateSettings,
    Header,
    Launch,
    LaunchCost,
    LaunchSettings,
    Lineup,
    LoadSettings,
    MachineRecord,
    Note,
    Observation,
    Plan,
    PlanRow,
    RoundWitness,
    Side,
    Witness,
    case_has_suffix,
    case_matches,
    case_unsuffixed,
    env_pad_length,
    file_names,
    hashed_workload,
    hidden_difference,
    launch_cost_side,
    public_case,
    safe_file_name,
    side_setup,
    undecided,
)
from pairbench.plan import build_plan
from pairbench.sides.base import OpenFolder, make_owner_only, open_private, working_folder_sha256

LAUNCH_COST_FOLDER = "cost"
"""The folder under the artifacts of a run that holds the empty launches."""

GPU_PROFILERS = ("nsys", "ncu")
"""The profilers ``record_profiles`` serves."""

NOT_IN_IMAGE_RC = 127
"""The exit code of a command that is not found: what a container engine gives when the
program that replaces an image's entrypoint is not in the image."""


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _folder_time() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Loud notes
# ---------------------------------------------------------------------------


class _Notes:
    """The loud notes of a run: a line on standard error and a note record each.

    Notes given before the capture is open are printed at once and written
    when it opens. While a launch runs they are held, and printed and written
    after it. ``once`` gives a note a single time per run for its key.
    """

    def __init__(self) -> None:
        self._writer: CaptureWriter | None = None
        self._unprinted: list[Note] = []
        self._unwritten: list[Note] = []
        self._holding = 0
        self._given: set[tuple[str, str]] = set()
        self.notes: list[Note] = []

    def __call__(self, code: str, message: str) -> None:
        note = Note(code=code, message=message)
        self.notes.append(note)
        self._unprinted.append(note)
        self._unwritten.append(note)
        self.flush()

    def once(self, code: str, message: str, key: str | None = None) -> None:
        """Give a note unless one with the same code and key was given in this run."""
        marker = (code, key if key is not None else message)
        if marker in self._given:
            return
        self._given.add(marker)
        self(code, message)

    def attach(self, writer: CaptureWriter) -> None:
        """Write the notes given so far, and every later one, into this capture."""
        self._writer = writer
        self.flush()

    def flush(self) -> None:
        """Print and write what is not yet out, unless a launch is running."""
        if self._holding:
            return
        for note in self._unprinted:
            print(note_line(note.code, note.message), file=sys.stderr)
        self._unprinted.clear()
        writer = self._writer
        if writer is not None and writer.open:
            for note in self._unwritten:
                writer.write(note)
            self._unwritten.clear()

    @contextlib.contextmanager
    def hold(self) -> Iterator[None]:
        """Hold every note until the outermost such block ends."""
        self._holding += 1
        try:
            yield
        finally:
            self._holding -= 1
            self.flush()


# ---------------------------------------------------------------------------
# Checks that need no launch
# ---------------------------------------------------------------------------


def _argv_of(side: Side) -> tuple[str, ...]:
    argv = side.spec.get("argv", ())
    return tuple(str(a) for a in argv) if isinstance(argv, list | tuple) else ()


def _static_checks(experiment: Experiment) -> None:
    """Refuse what can be refused without resolving a side."""
    for side in experiment.sides:
        registry.side_kind(side.kind)
        own = side.spec.get("format") if side.kind == KIND_FILE else None
        if isinstance(own, str) and own:
            registry.driver(own)
    _driver_fits_sides(experiment, registry.driver(experiment.driver))
    if experiment.workload:
        for side in experiment.sides:
            if side.kind == KIND_CMD and WORKLOAD_PLACEHOLDER not in _argv_of(side):
                raise Refusal(
                    "E_USAGE",
                    f"side {side.name!r} runs its own command line and a shared workload is "
                    f"given as well: add {WORKLOAD_PLACEHOLDER} to its command where the "
                    "workload goes",
                )
    if experiment.launch.allow_identical:
        return
    seen: dict[str, str] = {}
    for side in experiment.sides:
        key = repr(
            (side.kind, sorted(side.spec.items()), experiment.launch.for_side(side).to_json())
        )
        if key in seen:
            raise Refusal(
                "E_SAME_SIDE",
                f"sides {seen[key]!r} and {side.name!r} declare the same kind, spec and launch "
                "settings; give --allow-identical to compare a side with itself",
            )
        seen[key] = side.name


def _load_drivers() -> list[str]:
    """The names of the drivers that send load to a serving side, sorted."""
    found = []
    for name in registry.names(GROUP_DRIVERS):
        try:
            if registry.driver(name).where == "client":
                found.append(name)
        except Refusal:
            continue
    return sorted(found)


def _driver_fits_sides(experiment: Experiment, driver: Driver) -> None:
    """Refuse a driver that cannot measure the sides it is given, before any side resolves.

    A serving side is measured by a driver that sends it load; the built-in
    kinds that run a command are measured by a driver that runs inside them.
    A side kind of a plug-in may serve, so a load driver is not refused for
    it. A file side is read by its own format and is not checked here. The
    built-in load drivers need at least one load level; a load driver of a
    plug-in may not use levels, so it is not refused for having none.
    """
    client = driver.where == "client"
    launched = [s for s in experiment.sides if s.kind != KIND_FILE]
    for side in launched:
        if side.kind == KIND_SERVE and not client:
            raise Refusal(
                "E_USAGE",
                f"side {side.name!r} is a serving side and the driver {driver.name!r} sends it "
                f"no load; set workload.driver to a load driver: {', '.join(_load_drivers())}",
            )
        never_serves = side.kind != KIND_SERVE and registry.is_builtin(GROUP_SIDE_KINDS, side.kind)
        if client and never_serves:
            raise Refusal(
                "E_USAGE",
                f"the driver {driver.name!r} sends load to a serving side, and side "
                f"{side.name!r} is a {side.kind} side, which is not a server",
            )
    builtin = registry.is_builtin(GROUP_DRIVERS, driver.name)
    if client and builtin and launched and not experiment.load.levels:
        raise Refusal(
            "E_CONFIG",
            f"the {driver.name} driver runs one load level after another; "
            "workload.levels lists none",
        )


def hidden_difference_message(first: str, second: str) -> str:
    """The note that two sides with one fingerprint differ only in a value the results hide."""
    return (
        f"sides {first!r} and {second!r} have the same fingerprint and differ only in a value "
        "the results hide; they are compared as two sides, and the results do not show the "
        "value"
    )


def working_folder_message(first: str, second: str) -> str:
    """The note that two sides with one fingerprint run in two working folders."""
    return (
        f"sides {first!r} and {second!r} have the same fingerprint and run in two working "
        "folders; they are compared as two sides, and the results do not show the folders"
    )


def declared_identical_message(first: str, second: str) -> str:
    """The note that two sides that are one side are compared because that was allowed."""
    return (
        f"sides {first!r} and {second!r} have the same fingerprint, run in the same working "
        "folder and differ in nothing else; they are compared because identical sides were "
        "allowed"
    )


def _working_folders(experiment: Experiment) -> dict[str, str | None]:
    """The hash of each side's working folder, by side name; see ``working_folder_sha256``."""
    return {
        side.name: working_folder_sha256(side, experiment.launch.for_side(side))
        for side in experiment.sides
    }


def _same_fingerprints(
    experiment: Experiment,
    fingerprints: Mapping[str, str],
    note: Notify,
    folders: Mapping[str, str | None],
) -> None:
    """Refuse two sides with one fingerprint, unless their working folder or a hidden value differs.

    Two sides with one fingerprint whose working folders differ
    (``folders``, compared as a yes or no) are compared, with one note per
    pair that names both sides and never a folder. So are sides whose
    recorded specs differ in more than a credential's value
    (``hidden_difference``), with a note that never names the value. Sides
    in one working folder that differ at most in a credential's value, or
    not at all, are one side: ``E_SAME_SIDE``, unless identical sides are
    allowed, when they are compared with a note that says so.
    """
    config = experiment.to_json()
    seen: dict[str, list[str]] = {}
    apart: list[tuple[str, str]] = []
    for name, fingerprint in fingerprints.items():
        if not fingerprint:
            continue
        for other in seen.get(fingerprint, []):
            if folders.get(other) != folders.get(name):
                apart.append((NOTE_HIDDEN_DIFFERENCE, working_folder_message(other, name)))
            elif hidden_difference(side_setup(config, other), side_setup(config, name)):
                apart.append((NOTE_HIDDEN_DIFFERENCE, hidden_difference_message(other, name)))
            elif experiment.launch.allow_identical:
                apart.append((NOTE_DECLARED_IDENTICAL, declared_identical_message(other, name)))
            else:
                raise Refusal(
                    "E_SAME_SIDE",
                    f"sides {other!r} and {name!r} have the same fingerprint; give "
                    "--allow-identical to compare a side with itself",
                )
        seen.setdefault(fingerprint, []).append(name)
    for code, message in apart:
        note(code, message)


def _side_context(
    experiment: Experiment,
    side: Side,
    *,
    run_id: str,
    environ: Mapping[str, str],
    note: Notify,
    services: RunServices | None,
    launch_folders: Path | None = None,
    recorded: Sequence[Side] = (),
) -> SideContext:
    """The context a side is resolved with.

    A GPU selection the side gives itself that names a GPU the machine does
    not have is refused naming the side, as its own CPU set is. ``recorded``
    are the image sides as already resolved or looked up, whose image's
    entrypoint the shared workload's hash is read after
    (``pairbench.model.hashed_workload``).
    """
    settings = experiment.launch.for_side(side)
    try:
        gpu = services.checks.gpu_probe(settings.gpus) if services is not None else None
    except Refusal as refusal:
        if settings.gpus == experiment.launch.gpus:
            raise
        raise Refusal(
            refusal.code,
            f"side {side.name}: {refusal.message}",
            exit_code=refusal.exit_code,
            detail={**refusal.detail, "side": side.name},
        ) from None
    workload = experiment.workload
    return SideContext(
        run_id=run_id,
        settings=settings,
        workload=workload,
        driver=experiment.driver,
        environ=environ,
        gpu=gpu,
        mode=experiment.gates.mode,
        note=note,
        launch_folders=launch_folders,
        workload_hashed=(
            tuple(hashed_workload(workload, experiment.sides, recorded)) if workload else None
        ),
    )


def _records_head(side: Side, experiment: Experiment) -> bool:
    """Say whether a side records the program its image runs the shared workload behind.

    That is an image side with no ``entrypoint`` and no ``args`` of its own,
    given a workload (``pairbench.sides.container.image_head``).
    """
    return (
        side.kind == KIND_IMAGE
        and bool(experiment.workload)
        and not side.spec.get("entrypoint")
        and not side.spec.get("args")
    )


def _heads_first(experiment: Experiment) -> list[Side]:
    """Return the sides in the order they are resolved: those that record a head first.

    So the hash of every other side's command is taken after what their
    images run before the shared workload, as the shown command reads it.
    """
    sides = list(experiment.sides)
    return [
        *(s for s in sides if _records_head(s, experiment)),
        *(s for s in sides if not _records_head(s, experiment)),
    ]


def _resolve(
    experiment: Experiment,
    *,
    run_id: str,
    environ: Mapping[str, str],
    note: Notify,
    services: RunServices | None,
    only: Sequence[str] | None = None,
    launch_folders: Path | None = None,
    recorded: Sequence[Side] | None = None,
) -> dict[str, ResolvedSide]:
    """Resolve the sides, closing the ones already resolved when one is refused.

    The image sides that record what their image runs before the shared
    workload are resolved first, and the other sides' commands are hashed
    after it (``_side_context``); ``recorded``, the sides a capture records,
    stands for them when given. The sides come back in their own order.
    """
    resolved: dict[str, ResolvedSide] = {}
    heads: list[Side] = list(recorded or ())
    try:
        for side in _heads_first(experiment):
            if only is not None and side.name not in only:
                continue
            ctx = _side_context(
                experiment,
                side,
                run_id=run_id,
                environ=environ,
                note=note,
                services=services,
                launch_folders=launch_folders,
                recorded=heads,
            )
            one = registry.side_kind(side.kind).resolve(side, ctx)
            resolved[side.name] = one
            if recorded is None and _records_head(side, experiment):
                heads.append(one.side)
    except BaseException:
        _close_all(resolved)
        raise
    return {s.name: resolved[s.name] for s in experiment.sides if s.name in resolved}


def _close_all(resolved: Mapping[str, ResolvedSide]) -> None:
    for one in resolved.values():
        with contextlib.suppress(Exception):
            one.close()


def _launch(
    resolved: ResolvedSide, request: LaunchRequest, *, within: OpenFolder | None = None
) -> LaunchOutcome:
    """Launch ``request`` on ``resolved``; then keep what it left in its folder to its owner.

    The files the launch's own programs wrote there, such as a tool's export
    or a profiler's report, lose the group's and others' permissions once the
    launch has ended, whether it ended well or not. The timed launches of a
    run do the same after their witness and energy reading stop. ``within``,
    the run folder held open, is where that pass starts, so a folder between
    the two that is replaced by a link leads it nowhere.
    """
    try:
        return resolved.launch(request)
    finally:
        make_owner_only(request.artifacts, within=within)


def _check_twins(resolved: Mapping[str, ResolvedSide], twinned: Sequence[str]) -> None:
    """Refuse a twin whose fingerprint differs from its side's, as the run starts."""
    for name in twinned:
        side = resolved[name].side
        if side.twin().fingerprint != side.fingerprint:
            raise Refusal(
                "E_TWIN_DRIFT",
                f"the twin of side {name!r} has another fingerprint than the side",
                exit_code=EXIT_SIDE,
            )


def look_up_sides(
    experiment: Experiment, *, environ: Mapping[str, str] | None = None
) -> dict[str, SideLookup]:
    """Run the checks of the plan command and look up every side without changing anything.

    The look-ups come back by side name in the order of the sides; twins are
    left out. Nothing is started, pulled, created or locked.
    """
    if any(s.kind == KIND_FILE for s in experiment.sides):
        raise Refusal(
            "E_USAGE",
            "sides that are result files are compared with pairbench compare, not planned or run",
        )
    _static_checks(experiment)
    env = dict(os.environ if environ is None else environ)
    note: Notify = _print_note
    looked: dict[str, SideLookup] = {}
    heads: list[Side] = []
    for side in _heads_first(experiment):
        ctx = _side_context(
            experiment, side, run_id="", environ=env, note=note, services=None, recorded=heads
        )
        looked[side.name] = registry.side_kind(side.kind).look_up(side, ctx)
        if _records_head(side, experiment) and looked[side.name].identity:
            heads.append(side.with_identity(looked[side.name].identity, ""))
    found = {s.name: looked[s.name] for s in experiment.sides}
    folders = _working_folders(experiment)
    _same_fingerprints(
        experiment, {name: f.fingerprint for name, f in found.items()}, note, folders
    )
    return found


def _print_note(code: str, message: str) -> None:
    print(note_line(code, message), file=sys.stderr)


# ---------------------------------------------------------------------------
# The run folder
# ---------------------------------------------------------------------------


def _run_folder(out: Path | None, run_id: str) -> Path:
    if out is None:
        folder = Path.cwd() / DIR_RUNS / f"{_folder_time()}-{run_id}"
        _can_be_made(folder)
        return folder
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refusal("E_USAGE", f"the run folder {out.name} must be empty or absent")
    _can_be_made(out)
    return out


def _can_be_made(folder: Path) -> None:
    """Refuse a run folder that cannot be made, before any side is resolved.

    The nearest folder that exists on its path must be a folder this user may
    write into. A message names only the last part of each path.
    """
    if folder.is_dir():
        return
    parent = folder.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    why = (
        f"{parent.name or parent} is not a folder"
        if not parent.is_dir()
        else f"{parent.name or parent} does not let this user write into it"
        if not os.access(parent, os.W_OK | os.X_OK)
        else None
    )
    if why is not None:
        raise Refusal("E_USAGE", f"the run folder {folder.name} cannot be made: {why}")


def _make_run_folder(folder: Path) -> None:
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refusal(
            "E_USAGE", f"the run folder {folder.name} cannot be made: {exc.strerror}"
        ) from None


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


class _ControlStopped(Exception):
    """A launch of the positive control failed because its side cannot run two commands."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclasses.dataclass
class _Measured:
    """What one launch gave: its record, the cases read, and the launch's own outcome."""

    launch: Launch
    samples: list[Sample]
    driver_samples: list[Sample]
    default: list[str]
    seconds: float
    witness: Witness


def _energy_samples(reading: EnergyReading, *, control: bool) -> list[Sample]:
    """Return the energy cases of a launch as the power reading gives them.

    For the positive control only the windows whose label no other window of
    the launch carries are kept: under ``repeat`` the load of a serving side
    runs twice, so each load step has two windows of one label, and a case
    is recorded once per launch. The window of the whole launch is the one
    interval around both runs and is kept.
    """
    if not control:
        return reading.samples()
    labels = Counter(w.label for w in reading.windows)
    kept = tuple(w for w in reading.windows if labels[w.label] == 1)
    return dataclasses.replace(reading, windows=kept).samples()


class _Run:
    """The state of one run while it runs."""

    def __init__(
        self,
        experiment: Experiment,
        services: RunServices,
        run_id: str,
        run_dir: Path,
        resolved: Mapping[str, ResolvedSide],
        notes: _Notes,
        environ: Mapping[str, str],
    ) -> None:
        self.experiment = experiment
        self.services = services
        self.run_id = run_id
        self.run_dir = run_dir
        self.resolved = resolved
        self.notes = notes
        self.environ = environ
        self.driver: Driver = registry.driver(experiment.driver)
        self.writer: CaptureWriter | None = None
        self.seq = 0
        self.rounds_completed = 0
        self.known: dict[str, Case] = {}
        # The name each case id is shown by, kept for the whole capture, with the run's own
        # random key for the marks of names whose cut dropped words.
        self.case_names = CaseNames(secrets.token_bytes(CASE_KEY_BYTES))
        self.discovered = False
        self.round_witnesses: list[RoundWitness] = []
        self.locks: LockSet | None = None
        # The idle power of each GPU selection, measured before warm-up.
        self.idle_power_w: dict[str, float | None] = {}
        self.machine: MachineRecord | None = None
        # The hash of each side's working folder, recorded on its entries.
        self.folders: dict[str, str | None] = {}
        # The run folder, held open from when it is made until the run ends; the
        # owner-only pass after each launch starts from it.
        self.held: OpenFolder | None = None

    def entry(self, name: str) -> Side:
        """The resolved side ``name`` as the capture records it, with its working folder."""
        side = self.resolved[name].side
        return dataclasses.replace(side, workdir_sha256=self.folders.get(name))

    # -- records ----------------------------------------------------------

    def write(self, record: Any) -> None:
        assert self.writer is not None
        self.writer.write(record)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def artifacts(self, seq: int, name: str) -> Path:
        folder = self.run_dir / DIR_ARTIFACTS / f"{seq:04d}-{safe_file_name(name)}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    # -- cases ------------------------------------------------------------

    def record_cases(
        self, samples: Sequence[Sample], default: Sequence[str], *, discovering: bool
    ) -> list[Case]:
        """Record the cases first seen in these samples; return the ones that are new."""
        new: list[Case] = []
        for sample in samples:
            if sample.case in self.known:
                continue
            late = not discovering
            case = case_of(sample, self.experiment.cases, default, late=late)
            self.known[sample.case] = case
            new.append(case)
            if late and not case.id.startswith("res/"):
                self.notes(
                    NOTE_NEW_CASE,
                    f"case {case.id!r} was first seen after warm-up; it is recorded as secondary",
                )
        return new

    def primary_of(self, samples: Sequence[Sample], default: Sequence[str]) -> frozenset[str]:
        return frozenset(
            s.case for s in samples if case_of(s, self.experiment.cases, default).primary
        )

    # -- one launch -------------------------------------------------------

    def context(
        self, entry: Side, seq: int, phase: LaunchPhase, round_: int, artifacts: Path
    ) -> DriverContext:
        resolved = self.resolved[entry.source]
        return DriverContext(
            run_id=self.run_id,
            seq=seq,
            phase=phase,
            round=round_,
            name=entry.name,
            side=entry,
            artifacts=artifacts,
            artifacts_in_side=resolved.artifacts_in_side(artifacts),
            settings=self.experiment.load,
            seed=DEFAULT_SEED,
            note=self.notes,
            launch=self.experiment.launch.for_side(entry),
            case_names=self.case_names,
        )

    def witness_notes(self, name: str, round_: int, witness: Witness) -> None:
        """Give the loud notes of one measured launch's witness.

        One note per witness whose probe failed, and one note per run for the
        first launch the busy-core witness could not judge.
        """
        for code, message in witness_notes(name, round_, witness):
            self.notes(code, message)
        if undecided(witness, self.experiment.gates.discard):
            self.notes.once(
                NOTE_WITNESS_UNDECIDED,
                f"the busy-core witness could not judge the launch of {name} in round "
                f"{round_}: the side reports no CPU time of its own, and the busy cores counted "
                "with its own load in were above the threshold; the launch does not mark its "
                "round as disturbed, and later launches like it are counted in the results; pin "
                "a CPU set with --cpus for the full witness",
                key="undecided",
            )

    def pad(self, phase: str, round_: int) -> tuple[dict[str, str], int | None]:
        if not self.experiment.run.vary_env_size:
            return {}, None
        length = env_pad_length(DEFAULT_SEED, round_) if phase == "round" else 0
        return env_pad(length), length

    def measure(self, entry: Side, phase: LaunchPhase, round_: int, pos: int | None) -> _Measured:
        """Run one launch of a lineup entry or of the positive control and read its cases."""
        experiment = self.experiment
        resolved = self.resolved[entry.source]
        settings = experiment.launch.for_side(entry)
        control = entry.role == "control"
        repeat = control and experiment.controls.positive_via == "repeat"
        seq = self.next_seq()
        artifacts = self.artifacts(seq, entry.name)
        ctx = self.context(entry, seq, phase, round_, artifacts)
        pad, pad_length = self.pad(phase, round_)
        extra = {**pad, **(work_factor_env() if control and not repeat else {})}
        command = list(resolved.command or ())
        driver = self.driver_for(entry)
        client = driver.where == "client"
        file_side = entry.kind == KIND_FILE

        runs: list[DriverContext] = [ctx]
        if repeat:
            first, second = run_folders(artifacts, ctx.artifacts_in_side)
            runs = []
            for host, inside in (first, second):
                host.mkdir(parents=True, exist_ok=True)
                runs.append(dataclasses.replace(ctx, artifacts=host, artifacts_in_side=inside))

        load: _Load | None = None
        argv: tuple[str, ...] | None = None
        env: dict[str, str] = dict(extra)
        second_run: PreparedRun | None = None
        if file_side:
            env = {}
        elif client:
            load = _Load(driver, runs, list(experiment.workload or ()))
        else:
            prepared = [driver.prepare(run, list(command)) for run in runs]
            argv = prepared[0].argv or None
            env = {**prepared[0].env, **extra}
            if repeat:
                second_run = PreparedRun(
                    argv=prepared[1].argv or None, env={**prepared[1].env, **extra}
                )
        request = LaunchRequest(
            run_id=self.run_id,
            seq=seq,
            phase=phase,
            round=round_,
            pos=pos,
            name=entry.name,
            artifacts=artifacts,
            argv=argv,
            env=env,
            load=load,
            second=second_run,
        )

        sampler = (
            None if file_side else self.services.checks.start_witness(settings.cpus, settings.gpus)
        )
        power = None if file_side else self.start_power(settings.gpus)
        start = time.monotonic()
        try:
            with self.notes.hold():
                outcome = resolved.launch(request)
                end = time.monotonic()
        except BaseException:
            end = time.monotonic()
            if sampler is not None:
                with contextlib.suppress(Exception):
                    sampler.stop(None)
            with contextlib.suppress(Exception):
                self.stop_power(power, start, end, load, settings.gpus)
            make_owner_only(artifacts, within=self.held)
            raise
        own_cpu = outcome.cpu_s
        if load is not None and own_cpu is not None:
            own_cpu += load.cpu_s
        try:
            witness = (
                Witness()
                if sampler is None
                else sampler.stop(own_cpu, outcome.pid, outcome.second_pid)
            )
            reading = self.stop_power(power, start, end, load, settings.gpus)
        finally:
            # After the witness and the energy reading stop, so neither counts
            # it, and also when one of them fails to stop.
            make_owner_only(artifacts, within=self.held)
        if reading is not None:
            witness = reading.witness(witness)
        if phase != "warmup":
            self.witness_notes(entry.name, round_, witness)
        timed_out = outcome.timed_out
        record = Launch(
            seq=seq,
            phase="warmup" if phase == "warmup" else "round",
            round=round_,
            pos=pos,
            name=entry.name,
            rc=outcome.rc,
            timing=dict(outcome.timing),
            witness=witness.to_json(),
            energy=reading.to_json() if reading is not None else None,
            runs=2 if repeat else 1,
            env_pad=pad_length,
            timed_out=timed_out,
        )
        if outcome.rc != 0 or timed_out or (load is not None and load.failed):
            self.write(record)
            if repeat and outcome.cannot_repeat and not timed_out:
                raise _ControlStopped(outcome.cannot_repeat)
            why = "ran into its timeout" if outcome.timed_out else f"exited with {outcome.rc}"
            if load is not None and load.failed:
                why = load.failed
            which = (
                f"the warm-up launch of {entry.name!r}"
                if phase == "warmup"
                else f"the launch of {entry.name!r} in round {round_}"
            )
            raise Refusal(
                "E_LAUNCH_FAILED",
                f"{which} {why}",
                detail={"name": entry.name, "round": round_, "rc": outcome.rc},
            )
        try:
            done = [
                dataclasses.replace(
                    run,
                    timing=dict(outcome.timing),
                    rc=outcome.rc,
                    energy=reading,
                    endpoint=load.endpoint if load is not None else None,
                    result_file=outcome.result_file,
                )
                for run in runs
            ]
            where = f"side {entry.name!r}"
            read = [
                shown_cases(
                    driver, driver.read(run, run.artifacts), where, self.case_names, entry.name
                )
                for run in done
            ]
            for one in read:
                refuse_reserved_cases(one)
            version = self.tool_version(driver, done[0])
        except Refusal:
            self.write(record)
            raise
        if version is not None:
            record = dataclasses.replace(record, tool_version=version)
        if repeat:
            driver_samples = combine_runs(read[0], read[1], clock=clock_cases(driver))
            for case in uncombined_cases(read[0], read[1]):
                self.notes.once(
                    NOTE_CONTROL_CASE_MISSING,
                    f"case {case!r} came from only one of the two runs of the positive control "
                    "and has no value for it",
                    key=case,
                )
        elif control:
            driver_samples = control_samples(read[0])
        else:
            driver_samples = list(read[0])
        samples = list(driver_samples)
        if control:
            samples += control_samples(outcome.samples)
        else:
            samples += list(outcome.samples)
            if outcome.result_file is None:
                resources = resource_samples(outcome, load.seconds if load is not None else None)
                for case in missing_resource_cases(resources):
                    self.notes.once(
                        NOTE_RESOURCE_FIGURE_MISSING,
                        f"the resource figure {case!r} is not reported by this kind of side",
                        key=case,
                    )
                samples += resources
        if reading is not None:
            samples += _energy_samples(reading, control=control)
            for code, message in reading.notes:
                self.notes(code, message)
        default = driver.default_primary(list(driver_samples)) if driver_samples else []
        return _Measured(
            launch=record,
            samples=samples,
            driver_samples=driver_samples,
            default=default,
            seconds=end - start,
            witness=witness,
        )

    def driver_for(self, entry: Side) -> Driver:
        """The driver that reads a launch: a file side's own format when it names one."""
        own = entry.spec.get("format") if entry.kind == KIND_FILE else None
        return registry.driver(own) if isinstance(own, str) and own else self.driver

    def tool_version(self, driver: Driver, ctx: DriverContext) -> str | None:
        if not isinstance(driver, ReportsToolVersion):
            return None
        found = driver.tool_version(ctx, ctx.artifacts)
        if found is None:
            return None
        if not found.tested:
            self.notes.once(
                NOTE_TOOL_VERSION_UNTESTED,
                f"{found.tool} {found.version} is a major version this driver was not tested with",
                key=found.tool,
            )
        return found.version

    def start_power(self, gpus: str | None) -> PowerSampler | None:
        energy = self.experiment.energy
        if not energy.enabled:
            return None
        return self.services.meter.start(gpus or "all", energy)

    def stop_power(
        self,
        power: PowerSampler | None,
        start: float,
        end: float,
        load: _Load | None,
        gpus: str | None = None,
    ) -> EnergyReading | None:
        """Stop the power sampler; a reading without an idle power gets that of its GPUs."""
        if power is None:
            return None
        windows = [Window(label="", start_s=start, end_s=end)]
        if load is not None:
            windows += load.windows
        reading = power.stop(windows)
        idle = self.idle_power_w.get(gpus or "all")
        if reading.idle_power_w is None and idle is not None:
            reading = dataclasses.replace(reading, idle_power_w=idle)
        return reading

    def write_measured(self, measured: _Measured) -> None:
        """Write a measured launch with its observations.

        The names given since the last measured launch was written come first,
        in a ``case_names`` record, so a launch that is read but never written
        loses none of the names a later launch is read with; the run's key
        comes before the first of them that carries a mark.
        """
        record = measured.launch
        key, new = self.case_names.take_new()
        if key is not None:
            self.write(CaseKeyRecord(key=key))
        if new:
            self.write(CaseNamesRecord(names=new))
        self.write(record)
        for sample in measured.samples:
            self.write(
                Observation(
                    seq=record.seq,
                    round=record.round,
                    pos=record.pos,
                    name=record.name,
                    case=sample.case,
                    value=sample.value,
                    n_inner=sample.n_inner,
                    reducer=sample.reducer,
                )
            )


class _Load:
    """The load callback of a serving launch: runs a client driver's steps on the host.

    Each run's steps run in order beside the server, one energy window each.
    With two runs (the positive control under ``repeat``) the load runs twice
    against the one server start, each run into its own folder. A step still
    running at the endpoint's deadline is stopped with every process it
    started, and no later step starts.
    """

    def __init__(self, driver: Driver, runs: Sequence[DriverContext], argv: list[str]) -> None:
        self.driver = driver
        self.runs = list(runs)
        self.argv = argv
        self.windows: list[Window] = []
        self.cpu_s = 0.0
        self.seconds = 0.0
        self.endpoint: Endpoint | None = None
        self.failed: str | None = None
        self.timed_out = False

    def __call__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint
        started = time.monotonic()
        before = _children_cpu_s()
        for run in self.runs:
            ctx = dataclasses.replace(run, endpoint=endpoint)
            invocation = self.driver.prepare(ctx, list(self.argv))
            for index, step in enumerate(invocation.steps):
                start = time.monotonic()
                rc = _run_step(step.argv, step.env, run.artifacts, index, endpoint.deadline)
                self.windows.append(Window(label=step.label, start_s=start, end_s=time.monotonic()))
                if rc is None:
                    self.failed = "ran into its timeout during the load"
                    self.timed_out = True
                    break
                if rc != 0:
                    self.failed = f"ran a load step that exited with {rc}"
                    break
            if self.failed:
                break
        self.cpu_s = max(0.0, _children_cpu_s() - before)
        self.seconds = time.monotonic() - started


def _children_cpu_s() -> float:
    try:
        import resource
    except ImportError:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(usage.ru_utime + usage.ru_stime)


def _run_step(
    argv: Sequence[str],
    env: Mapping[str, str],
    folder: Path,
    index: int,
    deadline: float | None = None,
) -> int | None:
    """Run one load step; return its exit status, or ``None`` when it ran into ``deadline``.

    The step runs in a session of its own. When it is still running at
    ``deadline`` (a ``time.monotonic()`` value), or the wait for it is
    interrupted, every process of that session is killed. When it exits,
    every process it started that still runs in its session is killed too.
    """
    with (
        open_private(folder / f"load-{index}.stdout.txt") as out,
        open_private(folder / f"load-{index}.stderr.txt") as err,
    ):
        if deadline is not None and time.monotonic() >= deadline:
            return None
        try:
            process = subprocess.Popen(
                list(argv),
                env={**os.environ, **env},
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        except OSError:
            return 127
        try:
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            rc = process.wait(timeout=left)
        except subprocess.TimeoutExpired:
            _kill_step(process)
            return None
        except BaseException:
            _kill_step(process)
            raise
        _kill_session(process.pid)
        return rc


def _kill_session(pid: int) -> None:
    """Kill every process still running in the session whose first process is ``pid``.

    While any process of the session runs, its id stays taken, so this also
    reaches what a step left behind after the step's own exit was collected.
    """
    if hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)


def _kill_step(process: subprocess.Popen[bytes]) -> None:
    """Kill a load step and every process still running in its session, then collect it."""
    _kill_session(process.pid)
    with contextlib.suppress(OSError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5.0)


# ---------------------------------------------------------------------------
# The steps of a run
# ---------------------------------------------------------------------------


def _pinned_sets(experiment: Experiment) -> list[str | None]:
    """The CPU set each side runs on, the shared one first, each set once."""
    sets: list[str | None] = [experiment.launch.cpus]
    for side in experiment.sides:
        cpus = experiment.launch.for_side(side).cpus
        if cpus not in sets:
            sets.append(cpus)
    return sets


def _check_own_cpus(
    checks: MachineChecks, launch: LaunchSettings, sides: Sequence[Side], *, allow_mixed: bool
) -> list[CpuFacts]:
    """Check the CPU set each side gives itself as the shared set is checked.

    A set that mixes core types is refused with ``E_CPUS_MIXED_TYPES`` unless
    ``allow_mixed``, and a set that cannot be pinned with
    ``E_PIN_UNSUPPORTED``; the refusal names the side. A side on the shared
    set is not checked again. Returns the facts of each set checked.
    """
    found: list[CpuFacts] = []
    for side in sides:
        cpus = launch.for_side(side).cpus
        if cpus is None or cpus == launch.cpus:
            continue
        try:
            found.append(checks.cpu_facts(cpus, allow_mixed=allow_mixed))
        except Refusal as refusal:
            raise Refusal(
                refusal.code,
                f"side {side.name}: {refusal.message}",
                exit_code=refusal.exit_code,
                detail={**refusal.detail, "side": side.name},
            ) from None
    return found


def _described(facts: Sequence[CpuFacts]) -> tuple[tuple[CpuGroup, ...], tuple[str, ...]]:
    """The CPUs of several sets as one description: each core type once, each domain once.

    A core type's CPUs are those it has in any of the sets, and its maximum
    frequency the highest of them; core types and cache domains keep the
    order they are first met in.
    """
    if len(facts) == 1:
        return facts[0].identity, facts[0].cache_domains
    members: dict[str, set[int]] = {}
    khz: dict[str, int] = {}
    for one in facts:
        for group in one.identity:
            members.setdefault(group.key, set()).update(parse_cpu_list(group.cpus))
            khz[group.key] = max(khz.get(group.key, 0), group.max_khz)
    identity = tuple(
        CpuGroup(cpus=format_cpu_list(cpus), key=key, max_khz=khz[key])
        for key, cpus in members.items()
    )
    domains = tuple(dict.fromkeys(d for one in facts for d in one.cache_domains))
    return identity, domains


def _side_settings(experiment: Experiment) -> dict[str, LaunchSettings]:
    """The launch settings of each side that launches, overrides merged in, by name."""
    return {
        side.name: experiment.launch.for_side(side)
        for side in experiment.sides
        if side.kind != KIND_FILE
    }


# The note of a run whose sides launch with more than one container engine.
NOTE_ENGINES_DIFFER = "engines_differ"


def _machine(run: _Run) -> MachineRecord:
    experiment = run.experiment
    checks = run.services.checks
    launch = experiment.launch
    allow_mixed = experiment.gates.allow_mixed_core_types
    facts = checks.cpu_facts(launch.cpus, allow_mixed=allow_mixed)
    launched = [s for s in experiment.sides if s.kind != KIND_FILE]
    own = _check_own_cpus(checks, launch, launched, allow_mixed=allow_mixed)
    settings = _side_settings(experiment)
    # The record describes the CPUs of every set a side runs on: the shared
    # set (the machine when it is unpinned) when a side runs on it, and each
    # side's own set.
    on_shared = not launched or any(s.cpus == launch.cpus for s in settings.values())
    identity, domains = _described([facts, *own] if on_shared else own)
    if facts.mixed and any(launch.for_side(s).cpus is None for s in launched):
        run.notes(
            NOTE_UNPINNED_MIXED_CORES,
            "a side runs on no pinned CPU set and this machine has more than one core type; "
            "a launch may run on either type (pin one type with --cpus)",
        )
    pinned = [cpus for cpus in _pinned_sets(experiment) if cpus is not None]
    tool = checks.leave_pinned(",".join(pinned) if pinned else None)
    if tool.reason in ("none_left", "unsupported"):
        why = (
            "no CPU is left outside the pinned set"
            if tool.reason == "none_left"
            else "this platform does not let the tool choose its CPUs"
        )
        run.notes(NOTE_TOOL_ON_PINNED_CPUS, f"the tool runs on the pinned CPUs: {why}")
    gpus = all_selected(s.gpus for s in settings.values()) if launched else launch.gpus
    record = run.services.facts.machine_record(
        gpus=gpus, node_type=experiment.run.node_type, environ=run.environ
    )
    cpu = dataclasses.replace(record.cpu, identity=identity, cache_domains=domains)
    # The engine the sides launch with, which ``--engine`` chose; the machine's
    # own look-up names the engine ``auto`` would pick, kept for a run whose
    # sides use none.
    engines = {name: r.engine for name, r in run.resolved.items() if r.engine is not None}
    engine = next(iter(engines.values()), None)
    if engine is not None and len(set(engines.values())) > 1:
        # The record holds one engine; the note names the engine of each side.
        each = ", ".join(f"{name} with {e.name} {e.version}" for name, e in engines.items())
        run.notes(
            NOTE_ENGINES_DIFFER,
            f"the sides launch with more than one container engine: {each}; the machine "
            f"record names only the first, {engine.name} {engine.version}",
        )
    if engine is None:
        engine = record.engine
    return dataclasses.replace(record, cpu=cpu, tool_cpus=tool.cpus, engine=engine)


def _gates(run: _Run, phase: str) -> None:
    experiment = run.experiment
    gates = experiment.gates
    if gates.mode == "off":
        return
    machine = run.machine
    ctx = GateContext(
        mode=gates.mode,
        gates=gates,
        launch=experiment.launch,
        phase="recheck" if phase == "recheck" else "before",
        environ=run.environ,
        in_container=machine.in_container if machine is not None else False,
        ci=machine.ci if machine is not None else is_ci(run.environ),
        note=run.notes,
        sides=_side_settings(experiment),
    )
    names = [*BUILTIN_GATES, *(n for n in registry.names(GROUP_GATES) if n not in BUILTIN_GATES)]
    records: list[GateRecord] = []
    for name in names:
        record = registry.gate(name).check(ctx)
        run.write(record)
        records.append(record)
        if record.status != "pass":
            print(gate_line(record), file=sys.stderr)
    if gates.mode != "enforce":
        return
    failed = [r.name for r in records if r.status == "fail"]
    if failed:
        hint = _quiet_hint(gates, failed)
        raise Refusal("E_GATE_FAILED", f"machine check failed: {', '.join(failed)}{hint}")
    unable = [r.name for r in records if r.status != "pass"]
    if unable:
        raise Refusal(
            "E_GATE_UNAVAILABLE", f"machine check could not run fully: {', '.join(unable)}"
        )


def _quiet_hint(gates: GateSettings, failed: Sequence[str]) -> str:
    """What to change when the quiet check failed: wait for quiet, or say what quiet is."""
    if "quiet" not in failed:
        return ""
    if gates.wait_quiet:
        return (
            "; gates.quiet.max_wait_s sets how long --wait-quiet waits, and gates.quiet.* "
            "set what counts as quiet"
        )
    return (
        "; --wait-quiet waits for a quiet machine before the run, and gates.quiet.* "
        "set what counts as quiet"
    )


def _warm_up(run: _Run) -> dict[str, float]:
    """Run the warm-up launches; return each side's launch time."""
    times: dict[str, float] = {}
    primaries: dict[str, frozenset[str]] = {}
    for side in run.experiment.sides:
        entry = run.resolved[side.name].side
        for _ in range(run.experiment.run.warmups):
            with run.notes.hold():
                measured = run.measure(entry, "warmup", 0, None)
                run.record_cases(measured.samples, measured.default, discovering=True)
                run.write_measured(measured)
            times[side.name] = measured.seconds
            primaries[side.name] = run.primary_of(measured.driver_samples, measured.default)
    if primaries:
        _cases_known(run, primaries)
        run.discovered = True
    return times


# How many case ids a refusal lists before it says how many more there are.
SHOWN_CASES = 20


def _cases_known(run: _Run, primaries: Mapping[str, frozenset[str]]) -> None:
    """Check the cases once they are first known: the sides agree, and every pattern matches.

    A pattern of ``cases.primary`` that matches no case is refused with
    ``E_USAGE``, naming the pattern, with the secrets a case id may hold
    hidden as ``public_case`` hides them, and the cases there are: a misspelt
    pattern would otherwise leave nothing to judge, and a run with nothing to
    judge cannot fail. So is a pattern that matches only cases that are never
    primary, a resource case or a case whose ``better`` is ``none``, naming
    the cases it matched and the cases that can be primary. With no pattern
    and no primary case, a loud note says the run tests no case.
    """
    _cases_agree(primaries)
    ids = sorted(run.known)
    judged = [case for case in ids if run.known[case].primary]
    for pattern in run.experiment.cases.primary:
        matched = [case for case in ids if case_matches(case, (pattern,))]
        if not matched:
            raise Refusal(
                "E_USAGE",
                f"the primary case pattern {public_case(pattern)!r} matches no case of this run; "
                f"its cases are: {_listed(ids)}{_mark_hint(pattern)}",
            )
        if not any(case in judged for case in matched):
            raise Refusal(
                "E_USAGE",
                f"the primary case pattern {public_case(pattern)!r} matches only cases that "
                "describe and do not judge, which are never primary (a resource case under "
                f"'res/', or a case whose better is none): {_listed(matched)}; the cases that "
                "can be primary are: "
                f"{_listed([case for case in ids if run.known[case].better != 'none'])}",
            )
    if not judged:
        _no_case_primary(run, ids)


# The note of a run whose cases hold no primary case.
NOTE_NO_CASE_PRIMARY = "no_case_primary"


def _no_case_primary(run: _Run, ids: Sequence[str]) -> None:
    """Say loudly that no case is primary: the run tests no case and cannot fail on one.

    The cases that have a better side and are not primary are named, for
    ``--case`` to choose from.
    """
    message = (
        "no case of this run is primary, so no case is tested and no --fail-on outcome can "
        "match; a resource case under 'res/' and a case whose better is none are never primary"
    )
    can = [case for case in ids if run.known[case].better != "none"]
    if can:
        message += f"; --case makes a case primary, among: {_listed(can)}"
    run.notes.once(NOTE_NO_CASE_PRIMARY, message)


def _listed(ids: Sequence[str]) -> str:
    """The case ids of a refusal: the first ``SHOWN_CASES``, then how many more there are."""
    shown = ", ".join(repr(case) for case in ids[:SHOWN_CASES])
    more = len(ids) - SHOWN_CASES
    return (shown or "none") + (f", and {more} more" if more > 0 else "")


def _mark_hint(pattern: str) -> str:
    """The end of a refusal of a pattern that holds the mark a run adds to a name, else ``""``."""
    if not case_has_suffix(pattern):
        return ""
    return (
        "; the mark ' +' and eight hex digits at the end of a name is made with each run's own "
        "key, so a name from another run's results matches no case here: give the name without "
        "its mark"
    )


def _cases_agree(primaries: Mapping[str, frozenset[str]]) -> None:
    sets = set(primaries.values())
    if len(sets) > 1:
        shown = "; ".join(f"{n}: {', '.join(sorted(c)) or 'none'}" for n, c in primaries.items())
        every = [set(one) for one in sets]
        differ = set().union(*every) - every[0].intersection(*every[1:])
        marked = [case for case in differ if case_has_suffix(case)]
        hint = (
            "; names that differ only in the mark ' +' and eight hex digits come from ids whose "
            "paths run over different words; if such names are one case, a folder whose name "
            "holds a space gives such words, and the sides' folders differ that way"
            if any(
                case_unsuffixed(case) in (other, case_unsuffixed(other))
                for case in marked
                for other in differ
                if other != case
            )
            else ""
        )
        raise Refusal(
            "E_CASES_DIFFER",
            f"the sides produce different sets of primary cases: {shown}{hint}",
            detail={"primary": {n: sorted(c) for n, c in primaries.items()}},
        )


def _launch_cost(run: _Run) -> None:
    experiment = run.experiment
    count = experiment.launch_cost.launches
    side = launch_cost_side([run.resolved[s.name].side for s in experiment.sides])
    if side is None or count <= 0:
        return
    found = shutil.which(EMPTY_COMMAND)
    if found is None:
        run.notes(
            NOTE_LAUNCH_COST_NOT_MEASURED,
            f"the empty command {EMPTY_COMMAND!r} was not found, so the cost of a launch "
            "was not measured",
        )
        return
    resolved = run.resolved[side.name]
    times: list[float] = []
    for index in range(1, count + 1):
        folder = run.run_dir / DIR_ARTIFACTS / LAUNCH_COST_FOLDER / f"{index:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        request = LaunchRequest(
            run_id=run.run_id,
            seq=0,
            phase="cost",
            round=0,
            pos=None,
            name=side.name,
            artifacts=folder,
            argv=(found,),
            env=env_pad(0) if experiment.run.vary_env_size else {},
        )
        with run.notes.hold():
            outcome = _launch(resolved, request, within=run.held)
        seconds = outcome.timing.get("run_s")
        if outcome.rc != 0 or seconds is None:
            run.notes(
                NOTE_LAUNCH_COST_NOT_MEASURED,
                f"an empty launch of {EMPTY_COMMAND!r} did not run cleanly, so the cost of a "
                "launch was not measured",
            )
            return
        times.append(float(seconds))
    run.write(LaunchCost.of(EMPTY_COMMAND, times))


def _control_entry(run: _Run) -> Side | None:
    experiment = run.experiment
    control = experiment.control()
    if control is None:
        return None
    baseline = run.resolved[experiment.baseline]
    if experiment.controls.positive_via == "repeat":
        reason = baseline.cannot_repeat
        if reason:
            run.notes(
                NOTE_CONTROL_CANNOT_REPEAT,
                f"the positive control does not run: {experiment.baseline!r} cannot run two "
                f"commands in one start ({reason})",
            )
            return None
    return run.entry(experiment.baseline).control()


def _without_control(experiment: Experiment) -> Experiment:
    return dataclasses.replace(
        experiment, controls=dataclasses.replace(experiment.controls, positive="off")
    )


def _rounds(run: _Run, plan: Plan, control: Side | None) -> None:
    experiment = run.experiment
    entries: dict[str, Side] = {}
    for side in experiment.sides:
        entry = run.resolved[side.name].side
        entries[entry.name] = entry
        if side.name in experiment.twinned():
            twin = entry.twin()
            entries[twin.name] = twin
    if control is not None:
        entries[control.name] = control
    first_round: list[Case] = []
    primaries: dict[str, frozenset[str]] = {}
    by_round: dict[int, list[PlanRow]] = {}
    for row in plan.rows:
        by_round.setdefault(row.round, []).append(row)
    stopped = False
    for round_, rows in by_round.items():
        for row in rows:
            entry = entries[row.name]
            if stopped and entry.role == "control":
                continue
            with run.notes.hold():
                try:
                    measured = run.measure(entry, "round", round_, row.pos)
                except _ControlStopped as refused:
                    run.notes(
                        NOTE_CONTROL_CANNOT_REPEAT,
                        f"the positive control stops: its launch in round {round_} failed "
                        f"because {experiment.baseline!r} cannot run two commands in one start "
                        f"({refused.reason}); the measured rounds go on without it",
                    )
                    stopped = True
                    continue
                discovering = not run.discovered
                new = run.record_cases(measured.samples, measured.default, discovering=discovering)
                if discovering:
                    first_round += new
                    if entry.role in ("subject", "baseline"):
                        primaries[entry.name] = run.primary_of(
                            measured.driver_samples, measured.default
                        )
                elif new:
                    run.write(CasesRecord(cases=tuple(new)))
                run.write_measured(measured)
            run.round_witnesses.append(
                RoundWitness(round=round_, name=entry.name, witness=measured.witness)
            )
        if not run.discovered:
            run.write(CasesRecord(cases=tuple(first_round)))
            run.discovered = True
            _cases_known(run, primaries)
        run.rounds_completed = round_


def _identify_again(run: _Run) -> None:
    for name, resolved in run.resolved.items():
        now = dict(resolved.identify())
        if now != dict(resolved.side.identity):
            raise Refusal(
                "E_SIDE_CHANGED",
                f"the identity of side {name!r} changed during the run",
                detail={"side": name},
            )


def _file_rounds(run: _Run) -> None:
    experiment = run.experiment
    counts = {n: r.rounds_available for n, r in run.resolved.items()}
    if len(set(counts.values())) != 1 or None in counts.values():
        shown = ", ".join(f"{n}: {c}" for n, c in counts.items())
        raise Refusal("E_USAGE", f"the sides hold different numbers of result files: {shown}")
    rounds = next(iter(counts.values())) or 0
    run.write(Lineup(names=tuple(s.name for s in experiment.sides), rounds=rounds, schedule=None))
    first_round: list[Case] = []
    primaries: dict[str, frozenset[str]] = {}
    for round_ in range(1, rounds + 1):
        for side in experiment.sides:
            entry = run.resolved[side.name].side
            with run.notes.hold():
                measured = run.measure(entry, "round", round_, None)
                new = run.record_cases(
                    measured.samples, measured.default, discovering=not run.discovered
                )
                if not run.discovered:
                    first_round += new
                    primaries[entry.name] = run.primary_of(
                        measured.driver_samples, measured.default
                    )
                elif new:
                    run.write(CasesRecord(cases=tuple(new)))
                run.write_measured(measured)
        if not run.discovered:
            run.write(CasesRecord(cases=tuple(first_round)))
            run.discovered = True
            _cases_known(run, primaries)
        run.rounds_completed = round_


def _primary_count(run: _Run) -> int | None:
    count = sum(1 for case in run.known.values() if case.primary)
    return count or None


def _launched(run: _Run) -> None:
    """Everything between the open capture and the end record."""
    experiment = run.experiment
    if any(s.kind == KIND_FILE for s in experiment.sides):
        _file_rounds(run)
        _identify_again(run)
        return
    _gates(run, "before")
    locks = experiment.gates.locks
    if locks:
        run.locks = run.services.checks.acquire_locks(locks, experiment.gates.lock_timeout_s)
    _gates(run, "recheck")
    if experiment.energy.enabled:
        # One idle stretch for each GPU selection a side runs on.
        for settings in _side_settings(experiment).values():
            gpus = settings.gpus or "all"
            if gpus not in run.idle_power_w:
                run.idle_power_w[gpus] = run.services.meter.idle_power_w(gpus, experiment.energy)
    times = _warm_up(run)
    _launch_cost(run)
    control = _control_entry(run)
    planned = experiment if control is not None else _without_control(experiment)
    launch_s = times if times else None
    plan = build_plan(planned, primary_cases=_primary_count(run), launch_s=launch_s)
    _stamps(run, planned, plan, launch_s)
    if control is not None:
        run.write(control)
    run.write(
        Lineup(
            names=plan.lineup,
            control=control.name if control is not None else None,
            rounds=plan.rounds_planned,
            cases=tuple(run.known.values()),
            discard_thresholds=experiment.gates.discard,
        )
    )
    (run.run_dir / FILE_PLAN).write_text(plan.to_tsv(), encoding="utf-8")
    _rounds(run, plan, control)
    _identify_again(run)


def _stamps(
    run: _Run, planned: Experiment, plan: Plan, launch_s: Mapping[str, float] | None
) -> None:
    """Stamp a plan that is not balanced, and one with fewer rounds than a verdict needs."""
    if not plan.is_balanced():
        run.notes(
            NOTE_UNBALANCED,
            f"{plan.rounds_planned} rounds are not balanced for this lineup: some pair of "
            "entries does not run in each order equally often",
        )
    if not planned.run.allow_underpowered:
        return
    strict = dataclasses.replace(
        planned, run=dataclasses.replace(planned.run, allow_underpowered=False)
    )
    try:
        build_plan(strict, primary_cases=_primary_count(run), launch_s=launch_s)
    except Refusal as refusal:
        if refusal.code != "E_TOO_FEW_ROUNDS":
            raise
        detail = refusal.detail or {}
        run.notes(
            NOTE_UNDERPOWERED,
            f"{detail.get('rounds_planned', plan.rounds_planned)} rounds are planned and a "
            f"verdict needs at least {detail.get('rounds_needed', '?')}; every verdict is "
            "NO VERDICT (too_few_rounds)",
        )


def _discard_sha256(run: _Run) -> str | None:
    try:
        return run.services.checks.set_aside(
            run.experiment.gates.discard, run.round_witnesses
        ).sha256
    except Exception:
        return None


def _end(run: _Run, status: EndStatus) -> End | None:
    writer = run.writer
    if writer is None or not writer.open:
        return None
    run.notes.flush()
    return writer.end(
        status,
        run.rounds_completed,
        discard_sha256=_discard_sha256(run),
        finished_at=_utc_now(),
    )


def _with_run_dir(refusal: Refusal, run_dir: Path) -> Refusal:
    refusal.detail["run_dir"] = str(run_dir)
    return refusal


def run_experiment(
    experiment: Experiment, *, out: Path | None = None, services: RunServices | None = None
) -> Capture:
    """Run an experiment, write its capture and plan, and return the capture read back.

    ``out`` names the run folder; without it the folder is the one the
    experiment's run settings name, or a new folder under ``pairbench-runs``.
    A refusal raised once the capture is open names the run folder in
    ``refusal.detail["run_dir"]``; the capture then ends with ``failed``, or
    with ``interrupted`` for an interrupt, which becomes ``E_INTERRUPTED``.
    However the run ends, the tool's own threads go back to the CPUs they
    ran on before the run moved them off the pinned set.
    """
    environ = dict(os.environ)
    notes = _Notes()
    run_id = _new_run_id()
    _static_checks(experiment)
    if out is None and experiment.run.out:
        out = Path(experiment.run.out)
    run_dir = _run_folder(out, run_id)
    file_sides = any(s.kind == KIND_FILE for s in experiment.sides)
    if file_sides:
        experiment = dataclasses.replace(
            experiment, run=dataclasses.replace(experiment.run, same_vs_same="off")
        )
    services = services if services is not None else default_services()
    try:
        resolved = _resolve(
            experiment,
            run_id=run_id,
            environ=environ,
            note=notes,
            services=services,
            launch_folders=run_dir / DIR_ARTIFACTS,
        )
    except KeyboardInterrupt:
        raise Refusal("E_INTERRUPTED", "the run was interrupted") from None
    run = _Run(experiment, services, run_id, run_dir, resolved, notes, environ)
    try:
        return _carry_out(run, file_sides=file_sides)
    finally:
        with contextlib.suppress(Exception):
            services.checks.restore_cpus()


def _carry_out(run: _Run, *, file_sides: bool) -> Capture:
    """Check, plan and run the resolved sides; write the capture and read it back."""
    experiment = run.experiment
    resolved = run.resolved
    run_dir = run.run_dir
    try:
        run.folders = _working_folders(experiment)
        _same_fingerprints(
            experiment,
            {n: r.side.fingerprint for n, r in resolved.items()},
            run.notes,
            run.folders,
        )
        _check_twins(resolved, experiment.twinned())
        if not file_sides:
            build_plan(experiment)
        run.machine = _machine(run)
        _make_run_folder(run_dir)
        run.held = OpenFolder(run_dir)
        run.writer = CaptureWriter(run_dir / FILE_CAPTURE)
    except KeyboardInterrupt:
        _let_go(run)
        raise Refusal("E_INTERRUPTED", "the run was interrupted") from None
    except BaseException:
        _let_go(run)
        raise
    try:
        _open(run)
        _launched(run)
        _end(run, "complete")
    except KeyboardInterrupt:
        _end(run, "interrupted")
        raise _with_run_dir(Refusal("E_INTERRUPTED", "the run was interrupted"), run_dir) from None
    except Refusal as refusal:
        _end(run, "failed")
        raise _with_run_dir(refusal, run_dir) from None
    except Exception as exc:
        _end(run, "failed")
        raise _with_run_dir(
            Refusal("E_INTERNAL", f"the run stopped on an unexpected error: {exc}"), run_dir
        ) from exc
    finally:
        if run.writer is not None:
            run.writer.close()
        if run.locks is not None:
            with contextlib.suppress(Exception):
                run.locks.release()
        _let_go(run)
    (capture,) = JsonlReader().read(run_dir / FILE_CAPTURE)
    return capture


def _let_go(run: _Run) -> None:
    """Close the resolved sides and the run folder held open."""
    _close_all(run.resolved)
    if run.held is not None:
        with contextlib.suppress(OSError):
            run.held.close()


def _open(run: _Run) -> None:
    experiment = run.experiment
    assert run.writer is not None and run.machine is not None
    run.write(
        Header(
            capture_id=run.run_id,
            started_at=_utc_now(),
            argv=recorded_command_line(),
            config=experiment.to_json(),
            seeds={
                SEED_DRIVER: DEFAULT_SEED,
                **({SEED_ENV_PAD: DEFAULT_SEED} if experiment.run.vary_env_size else {}),
            },
        )
    )
    run.write(run.machine)
    twinned = set(experiment.twinned())
    for side in experiment.sides:
        entry = run.entry(side.name)
        run.write(entry)
        if side.name in twinned:
            run.write(entry.twin())
    run.notes.attach(run.writer)


# ---------------------------------------------------------------------------
# The explain step
# ---------------------------------------------------------------------------


class _ExplainSession:
    """The explain launches of one run; see ``api.ExplainSession``."""

    def __init__(
        self,
        experiment: Experiment,
        *,
        run_id: str,
        fingerprints: Mapping[str, str],
        note: Notify,
        services: RunServices,
        locks: LockSet | None,
    ) -> None:
        self.experiment = experiment
        self.run_id = run_id
        self.fingerprints = dict(fingerprints)
        self.note = note
        self.services = services
        self.locks = locks
        self.resolved: dict[str, ResolvedSide] = {}
        self.driver: Driver | None = None
        self.seq = 0
        self.heads: list[Side] | None = None

    def _heads(self) -> list[Side]:
        """The image sides that record a head, as resolved here or looked up, for the hashes.

        The run resolved them before its other sides and hashed those sides'
        commands after what the images run (``_resolve``), so a side resolved
        here alone is hashed the same way and keeps its fingerprint. A side
        that cannot be looked up gives nothing; the fingerprint then tells.
        """
        if self.heads is None:
            self.heads = []
            for side in self.experiment.sides:
                if not _records_head(side, self.experiment):
                    continue
                if side.name in self.resolved:
                    self.heads.append(self.resolved[side.name].side)
                    continue
                ctx = _side_context(
                    self.experiment,
                    side,
                    run_id=self.run_id,
                    environ=dict(os.environ),
                    note=self.note,
                    services=self.services,
                )
                with contextlib.suppress(Refusal):
                    lookup = registry.side_kind(side.kind).look_up(side, ctx)
                    if lookup.identity:
                        self.heads.append(side.with_identity(lookup.identity, ""))
        return self.heads

    def _side(self, name: str) -> ResolvedSide:
        if name in self.resolved:
            return self.resolved[name]
        side = self.experiment.side(name) if _is_side(self.experiment, name) else None
        if side is None:
            raise Refusal(
                "E_USAGE",
                f"{name!r} is no subject or baseline of this run; twins and the positive "
                "control are never launched for the explain step",
            )
        recorded = self.fingerprints.get(name)
        if not recorded:
            raise Refusal("E_USAGE", f"the results record no fingerprint for side {name!r}")
        ctx = _side_context(
            self.experiment,
            side,
            run_id=self.run_id,
            environ=dict(os.environ),
            note=self.note,
            services=self.services,
            recorded=() if _records_head(side, self.experiment) else self._heads(),
        )
        resolved = registry.side_kind(side.kind).resolve(side, ctx)
        if resolved.side.fingerprint != recorded:
            with contextlib.suppress(Exception):
                resolved.close()
            raise Refusal(
                "E_SIDE_CHANGED",
                f"side {name!r} is not the side the results record: its fingerprint differs",
                detail={"side": name},
            )
        self.resolved[name] = resolved
        return resolved

    def command(self, side: str) -> tuple[str, ...] | None:
        """The command a launch of the side runs; for an image, its whole command line."""
        resolved = self._side(side)
        whole = getattr(resolved, "whole_command", None)
        return tuple(whole) if whole is not None else resolved.command

    def launch(self, side: str, instrument: Instrument, artifacts: Path) -> InstrumentedLaunch:
        resolved = self._side(side)
        experiment = self.experiment
        if self.driver is None:
            self.driver = registry.driver(experiment.driver)
        driver = self.driver
        self.seq += 1
        artifacts.mkdir(parents=True, exist_ok=True)
        inside = resolved.artifacts_in_side(artifacts)
        tools = {path.name: resolved.tool_file_in_side(path) for path in instrument.tool_files}
        pad = env_pad(0) if experiment.run.vary_env_size else {}
        entry = resolved.side
        ctx = DriverContext(
            run_id=self.run_id,
            seq=self.seq,
            phase="explain",
            round=0,
            name=entry.name,
            side=entry,
            artifacts=artifacts,
            artifacts_in_side=inside,
            settings=_highest_level(experiment),
            seed=DEFAULT_SEED,
            note=self.note,
            launch=experiment.launch.for_side(entry),
        )
        load: _Load | None = None
        wrap_server: Callable[[Sequence[str]], InstrumentedCommand] | None = None
        argv: tuple[str, ...] | None = None
        env: dict[str, str] = dict(pad)
        outputs: tuple[str, ...] = ()
        server: list[InstrumentedCommand] = []
        if driver.where == "client":
            load = _Load(driver, [ctx], list(experiment.workload or ()))

            def _wrap(command: Sequence[str]) -> InstrumentedCommand:
                wrapped = instrument.wrap(command, out=inside, tools=tools)
                server.append(wrapped)
                return wrapped

            wrap_server = _wrap
        else:
            command = resolved.command
            image = entry.kind == KIND_IMAGE
            if command is None and not image:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {side!r} has no command to put an instrument in front of",
                )
            invocation = driver.prepare(ctx, list(command or ()))
            if image:
                # The image's whole command line (entrypoint and command) goes
                # under the instrument, which then runs inside the container.
                argv = invocation.argv or None
                env = {**invocation.env, **pad}

                def _wrap_whole(whole: Sequence[str]) -> InstrumentedCommand:
                    wrapped = instrument.wrap(whole, out=inside, tools=tools)
                    server.append(wrapped)
                    return wrapped

                wrap_server = _wrap_whole
            else:
                wrapped = instrument.wrap(invocation.argv, out=inside, tools=tools)
                argv = wrapped.argv
                env = {**invocation.env, **wrapped.env, **pad}
                outputs = wrapped.outputs
        request = LaunchRequest(
            run_id=self.run_id,
            seq=self.seq,
            phase="explain",
            round=0,
            pos=None,
            name=entry.name,
            artifacts=artifacts,
            argv=argv,
            env=env,
            load=load,
            tool_files=instrument.tool_files,
            wrap_server=wrap_server,
        )
        # The launch folder is held open from before the launch, so the pass
        # after it narrows the files of this folder, wherever it is moved,
        # and never those of a folder a link put in its way names.
        held = OpenFolder(artifacts)
        try:
            outcome = _launch(resolved, request, within=held)
        finally:
            held.close()
        if server:
            outputs = server[-1].outputs
        return InstrumentedLaunch(
            rc=outcome.rc,
            artifacts=artifacts,
            outputs=tuple(artifacts / name for name in outputs),
            timed_out=outcome.timed_out or (load is not None and load.timed_out),
        )

    def close(self) -> None:
        _close_all(self.resolved)
        self.resolved.clear()
        if self.locks is not None:
            with contextlib.suppress(Exception):
                self.locks.release()
            self.locks = None


def _is_side(experiment: Experiment, name: str) -> bool:
    return any(s.name == name for s in experiment.sides)


def _highest_level(experiment: Experiment) -> LoadSettings:
    load = experiment.load
    if not load.levels:
        return load
    return dataclasses.replace(load, levels=(max(load.levels),))


def open_explain(
    experiment: Experiment,
    *,
    run_id: str,
    fingerprints: Mapping[str, str],
    note: Notify = no_notes,
    services: RunServices | None = None,
) -> ExplainSession:
    """Open the explain launches of a run, holding the run's locks until the session closes."""
    services = services if services is not None else default_services()
    gates = experiment.gates
    locks = (
        services.checks.acquire_locks(gates.locks, gates.lock_timeout_s) if gates.locks else None
    )
    return _ExplainSession(
        experiment,
        run_id=run_id,
        fingerprints=fingerprints,
        note=note,
        services=services,
        locks=locks,
    )


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def _has_redacted(value: Any) -> bool:
    if isinstance(value, str):
        return value == REDACTED
    if isinstance(value, Mapping):
        return any(_has_redacted(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_redacted(v) for v in value)
    return False


def _profile_whole(
    profiler: Profiler, inside: str, profiled: list[ProfiledCommand]
) -> Callable[[Sequence[str]], InstrumentedCommand]:
    """Return the wrap an image side hands its whole command line to; it keeps each result."""

    def wrap(whole: Sequence[str]) -> InstrumentedCommand:
        wrapped = profiler.wrap(whole, inside)
        profiled.append(wrapped)
        return InstrumentedCommand(argv=wrapped.argv)

    return wrap


def _output_in_folder(output: str, inside: str) -> str | None:
    """Return a profiler's output as a path inside the launch folder, or ``None``.

    A profiler names its outputs under the folder as the launch sees it
    (``inside``, a host path or a path in a container) or relative to that
    folder; an output anywhere else is not the launch's.
    """
    path = PurePosixPath(output)
    if path.is_absolute():
        try:
            path = path.relative_to(PurePosixPath(inside))
        except ValueError:
            return None
    if not path.parts or ".." in path.parts:
        return None
    return str(path)


def _one_case(case: str, ids: Sequence[str]) -> str:
    """Return the case id of the run that ``case`` names, or refuse with ``E_USAGE``.

    ``case`` names the id equal to it, or else the one id whose form without
    the mark a run adds to a name whose cut dropped words (``case_suffix``) is
    equal to it: the mark is made with each run's own key, so the name a
    reader carries from other results may hold another run's mark or none.
    """
    if case in ids:
        return case
    alike = sorted({one for one in ids if case_has_suffix(one) and case_unsuffixed(one) == case})
    if len(alike) == 1:
        return alike[0]
    if alike:
        raise Refusal(
            "E_USAGE",
            f"the case {case!r} names {len(alike)} cases of the run: "
            + ", ".join(repr(one) for one in alike)
            + "; give one of them",
        )
    raise Refusal("E_USAGE", f"the run has no case {case!r}")


def record_profiles(
    run_dir: Path,
    *,
    tool: str,
    case: str | None = None,
    side: str | None = None,
    services: RunServices | None = None,
) -> tuple[str, ...]:
    """Run one untimed launch per side under a GPU profiler; return the files it wrote.

    The paths are relative to the run folder, under ``profiles/<side>/``,
    where ``<side>`` is the side's name as ``model.file_names`` writes it.
    """
    if tool not in GPU_PROFILERS:
        raise Refusal("E_USAGE", f"the profiler is one of {', '.join(GPU_PROFILERS)}, not {tool!r}")
    (capture,) = JsonlReader().read(run_dir / FILE_CAPTURE)
    config = capture.header.config
    if _has_redacted(config):
        raise Refusal(
            "E_USAGE",
            "the recorded config holds redacted values, so the sides cannot be launched again "
            "as they ran; run the experiment again with the profile in mind",
        )
    experiment = Experiment.from_json(config)
    if case is not None:
        _one_case(case, [c.id for c in capture.cases])
    names = [s.name for s in experiment.sides]
    if side is not None:
        if side not in names:
            raise Refusal("E_USAGE", f"the run has no side {side!r}")
        names = [side]
    services = services if services is not None else default_services()
    profiler = services.profiler(tool)
    # An image side runs the profiler inside its container, from the image;
    # only a side that runs on this machine needs it installed here.
    on_host = any(s.name in names and s.kind != KIND_IMAGE for s in experiment.sides)
    if on_host and profiler.find() is None:
        raise Refusal("E_PROFILER_MISSING", f"the profiler {tool} is not installed")
    if profiler.licence_note:
        print(profiler.licence_note, file=sys.stderr)
    gates = experiment.gates
    locks = (
        services.checks.acquire_locks(gates.locks, gates.lock_timeout_s) if gates.locks else None
    )
    resolved: dict[str, ResolvedSide] = {}
    written: list[str] = []
    held = OpenFolder(run_dir)
    try:
        resolved = _resolve(
            experiment,
            run_id=capture.capture_id,
            environ=dict(os.environ),
            note=_print_note,
            services=services,
            only=names,
            recorded=capture.sides,
        )
        driver = registry.driver(experiment.driver)
        folders = file_names(s.name for s in experiment.sides)
        for seq, name in enumerate(names, start=1):
            one = resolved[name]
            folder = run_dir / DIR_PROFILES / folders[name]
            folder.mkdir(parents=True, exist_ok=True)
            inside = one.artifacts_in_side(folder)
            ctx = DriverContext(
                run_id=capture.capture_id,
                seq=seq,
                phase="profile",
                round=0,
                name=name,
                side=one.side,
                artifacts=folder,
                artifacts_in_side=inside,
                settings=experiment.load,
                note=_print_note,
                launch=experiment.launch.for_side(one.side),
            )
            command = one.command
            image = one.side.kind == KIND_IMAGE
            if command is None and not image:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {name!r} has no command to put a profiler in front of",
                )
            invocation = driver.prepare(ctx, list(command or ()))
            profiled: list[ProfiledCommand] = []
            wrap_whole: Callable[[Sequence[str]], InstrumentedCommand] | None = None
            if image:
                # The image's whole command line (entrypoint and command) goes
                # under the profiler, which then runs inside the container.
                wrap_whole = _profile_whole(profiler, inside, profiled)
                argv: tuple[str, ...] | None = invocation.argv or None
            else:
                profiled.append(profiler.wrap(invocation.argv, inside))
                argv = profiled[0].argv
            outcome = _launch(
                one,
                LaunchRequest(
                    run_id=capture.capture_id,
                    seq=seq,
                    phase="profile",
                    round=0,
                    pos=None,
                    name=name,
                    artifacts=folder,
                    argv=argv,
                    env=dict(invocation.env),
                    wrap_server=wrap_whole,
                ),
                within=held,
            )
            found: list[str] = []
            for output in profiled[-1].outputs if profiled else ():
                relative = _output_in_folder(output, inside)
                if relative is not None and (folder / relative).exists():
                    found.append(str(Path(DIR_PROFILES) / folders[name] / relative))
            if image and outcome.rc == NOT_IN_IMAGE_RC and not outcome.timed_out and not found:
                raise Refusal(
                    "E_PROFILER_MISSING",
                    f"{tool} is not in the image of side {name!r}: the profiler runs inside "
                    "the container, so the image must hold it on its PATH",
                    detail={"side": name, "profiler": tool},
                )
            if outcome.rc != 0 or outcome.timed_out:
                raise Refusal(
                    "E_LAUNCH_FAILED",
                    f"the profiled launch of {name!r} exited with {outcome.rc}",
                )
            written.extend(found)
    finally:
        _close_all(resolved)
        held.close()
        if locks is not None:
            with contextlib.suppress(Exception):
                locks.release()
    return tuple(written)


__all__: Sequence[str] = (
    "look_up_sides",
    "open_explain",
    "record_profiles",
    "run_experiment",
)
