# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The plug-in contract: ``API_VERSION``, one Protocol per plug-in group, and the
types the runner exchanges with sides, drivers, machine checks and energy.

Sides, drivers, machine checks and energy code do not import each other. The
runner composes them, and everything it says to them, or hears back, is
written with the types of this module and of ``pairbench.model``.

A plug-in is an object with a ``name`` and an ``api_version`` equal to
``API_VERSION``. An entry point may name such an object, or a class that is
called with no arguments to make one. A plug-in keeps no state of a run on
itself: one object serves every run of the process.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import importlib
import importlib.util
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol, runtime_checkable

from pairbench.errors import Refusal
from pairbench.model import (
    CASE_RES_CORES,
    CASE_RES_CTX_INVOLUNTARY,
    CASE_RES_CTX_VOLUNTARY,
    CASE_RES_FAULTS_MAJOR,
    CASE_RES_FAULTS_MINOR,
    CASE_RES_RSS_PEAK,
    CASE_RES_SYS,
    CASE_RES_USER,
    ENV_PAD_MAX,
    METRIC_ENERGY_J,
    METRIC_MEAN_POWER_W,
    RESERVED_CASE_PREFIXES,
    RESOURCE_CASES,
    WITNESS_GPU_THROTTLE_EVENTS,
    Better,
    Capture,
    Case,
    CaseKind,
    CaseName,
    CaseSettings,
    CpuGroup,
    Diagnostics,
    DiscardThresholds,
    EnergySettings,
    EngineInfo,
    Experiment,
    Floors,
    GateMode,
    GateRecord,
    GateSettings,
    InstrumentReason,
    LaunchSettings,
    LoadSettings,
    MachineRecord,
    Plan,
    Probe,
    Ready,
    Results,
    RoundWitness,
    Rule,
    ServeSpec,
    SetAside,
    Side,
    Witness,
    case_has_suffix,
    case_id,
    case_percent_paths,
    case_secrets_hidden,
    case_suffix,
    case_tell_words,
    case_text_sha256,
    combine_control,
    is_reserved_case,
    public_case,
    public_case_drops,
    redact_argv,
    resource_case,
)

API_VERSION: Final = 1

GROUP_SIDE_KINDS: Final = "pairbench.side_kinds"
GROUP_DRIVERS: Final = "pairbench.drivers"
GROUP_CAPTURE_READERS: Final = "pairbench.capture_readers"
GROUP_GATES: Final = "pairbench.gates"
GROUP_RULES: Final = "pairbench.rules"
GROUP_REPORTERS: Final = "pairbench.reporters"
GROUP_LAUNCHERS: Final = "pairbench.launchers"
GROUPS: Final[tuple[str, ...]] = (
    GROUP_SIDE_KINDS,
    GROUP_DRIVERS,
    GROUP_CAPTURE_READERS,
    GROUP_GATES,
    GROUP_RULES,
    GROUP_REPORTERS,
    GROUP_LAUNCHERS,
)

# Files every launch leaves in its artifact folder.
ARTIFACT_STDOUT: Final = "stdout.txt"
ARTIFACT_STDERR: Final = "stderr.txt"
ARTIFACT_SERVER_LOG: Final = "server.log"
# Where a container side sees its launch's artifact folder.
ARTIFACTS_IN_CONTAINER: Final = "/pairbench/artifacts"
# Where a container side sees a file of the tool that a launch was handed,
# mounted read-only: the folder, with the file's own name under it.
TOOLS_IN_CONTAINER: Final = "/pairbench/tools"
# A launch that holds two runs of the workload keeps what each run wrote in a
# folder of its own, under the launch's artifact folder.
RUN_FOLDERS: Final[tuple[str, str]] = ("run1", "run2")

CONTAINER_PREFIX: Final = "pairbench-"
ENGINES: Final[tuple[str, ...]] = ("docker", "podman")
# The environment variable that names the engine ``auto`` prefers.
ENGINE_VARIABLE: Final = "PAIRBENCH__LAUNCH__ENGINE"

TIMING_RUN_S: Final = "run_s"
TIMING_LAUNCH_S: Final = "launch_s"
# The CPU time of an exited process, where the platform reports it.
TIMING_USER_S: Final = "user_s"
TIMING_SYS_S: Final = "sys_s"

# The keys of the resource usage a side reports for a launch, beside the CPU
# time it reports under ``timing``. A key that is absent says the platform or
# the engine does not give that figure.
USAGE_RSS_PEAK_BYTES: Final = "rss_peak_bytes"
USAGE_CTX_VOLUNTARY: Final = "ctx_voluntary"
USAGE_CTX_INVOLUNTARY: Final = "ctx_involuntary"
USAGE_FAULTS_MAJOR: Final = "faults_major"
USAGE_FAULTS_MINOR: Final = "faults_minor"
USAGE_KEYS: Final[tuple[str, ...]] = (
    USAGE_RSS_PEAK_BYTES,
    USAGE_CTX_VOLUNTARY,
    USAGE_CTX_INVOLUNTARY,
    USAGE_FAULTS_MAJOR,
    USAGE_FAULTS_MINOR,
)

# The variable a launch of the positive control carries under ``factor``: a
# workload that honours it does twice the work inside its own timing.
WORK_FACTOR_VARIABLE: Final = "PAIRBENCH_WORK_FACTOR"
WORK_FACTOR: Final = "2"
# The variable that pads the environment of a launch when its size is varied.
ENV_PAD_VARIABLE: Final = "PAIRBENCH_ENV_PAD"
ENV_PAD_LETTER: Final = "x"
# The module the ``plot`` extra provides.
PLOT_MODULE: Final = "matplotlib"

REDUCER_IDENTITY: Final = "identity"
REDUCER_MEDIAN: Final = "median"
REDUCER_TOOL_SUMMARY: Final = "tool_summary"
REDUCER_TRAPEZOID: Final = "trapezoid"
# The value of the positive control: what two runs in one start reported, combined.
REDUCER_TWO_RUNS: Final = "two_runs"

# The seed handed to every load tool that accepts one, and the seed of the
# environment pad of a run that varies the size of the environment.
DEFAULT_SEED: Final = 1234

# Serving: how long to wait for a GPU free of other compute processes before a
# start, and for GPU memory to return to its level after a stop.
GPU_FREE_WAIT_S: Final = 300.0
GPU_RELEASE_WAIT_S: Final = 120.0
GPU_RELEASE_TOLERANCE_MIB: Final = 64.0

# The runner runs the built-in gates, in the order of ``pairbench.model.BUILTIN_GATES``,
# before any third-party gate.

Where = Literal["in_side", "client"]
DRIVER_WHERE: Final[tuple[str, ...]] = ("in_side", "client")
# ``cost`` is an empty launch that measures what a launch costs, ``explain`` a
# launch under an instrument and ``profile`` one under a profiler. None of
# the three is recorded as a launch of the capture.
LaunchPhase = Literal["warmup", "round", "profile", "explain", "cost"]
GatePhase = Literal["before", "recheck"]
# Why the tool did not move itself off the pinned CPUs.
NotMoved = Literal["not_pinned", "none_left", "unsupported"]
DoctorStatus = Literal["ok", "degraded", "unavailable", "experimental"]
LookupStatus = Literal["identified", "absent", "unchecked"]

Notify = Callable[[str, str], None]
"""Receives a loud note as ``(code, message)``. The runner prints it on standard
error and records it in the capture, from where it reaches the results. The
code is lower-case words joined by ``_``. The message reaches a document that
is meant to be shared: it names a side by the name the user gave it and a file
by the last part of its path, and holds no host, no user, no image reference
and no value of the environment."""


def no_notes(code: str, message: str) -> None:
    """Drop a note. The default where no receiver was given."""


def note_line(code: str, message: str) -> str:
    """Return the line printed on standard error for a loud note."""
    return f"pairbench: note: {code}: {message}"


def gate_line(record: GateRecord) -> str:
    """Return the line printed on standard error for a machine check that did not pass.

    It carries the check's name, its status and, when the check gave one, its
    one-line reason.
    """
    message = record.detail.get("message")
    reason = f": {message}" if isinstance(message, str) and message else ""
    return f"pairbench: check {record.name}: {record.status}{reason}"


def container_name(run_id: str, seq: int, name: str) -> str:
    """Return the name of the container of one launch.

    It starts with ``CONTAINER_PREFIX``, carries the run id and is unique
    within the run, so leftover containers of an interrupted run can be found.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    return f"{CONTAINER_PREFIX}{run_id}-{seq:04d}-{safe}"


def find_engine(
    requested: str, found: Sequence[str], environ: Mapping[str, str] | None = None
) -> str | None:
    """Pick the container engine, or return ``None`` when the one asked for is not there.

    ``requested`` is ``auto`` or the name of an engine; ``found`` lists the
    engines that can be reached. ``auto`` picks the engine that is found. When
    both are found it picks the one the variable ``ENGINE_VARIABLE`` names in
    ``environ``, and docker when the variable names neither. A caller passes
    the environment it was handed, ``SideContext.environ`` or
    ``GateContext.environ``.
    """
    if requested == "auto":
        preferred = (environ or {}).get(ENGINE_VARIABLE, "").strip().lower()
        if preferred in ENGINES and preferred in found:
            return preferred
        return next((engine for engine in ENGINES if engine in found), None)
    return requested if requested in found else None


_COMMAND_LINE: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "pairbench_command_line", default=()
)


@contextlib.contextmanager
def command_line(argv: Sequence[str]) -> Iterator[None]:
    """Make ``argv`` the command line that runs started inside the block record.

    The command line wraps its work in this, with the program name first. A
    run started by a call of the Python API records no command line. What is
    recorded is ``pairbench.model.redact_argv(argv)``: the value of a
    ``--set`` that sets a credential-like environment variable is replaced.
    """
    token = _COMMAND_LINE.set(redact_argv(argv))
    try:
        yield
    finally:
        _COMMAND_LINE.reset(token)


def recorded_command_line() -> tuple[str, ...]:
    """Return the command line a run writes into its capture header, or nothing."""
    return _COMMAND_LINE.get()


def is_ci(environ: Mapping[str, str]) -> bool:
    """Say whether the environment is an automated pipeline.

    It is one when the variable ``CI`` holds a true value: any text other
    than the empty text, ``0``, ``false``, ``no`` and ``off``, in any case.
    """
    return environ.get("CI", "").strip().lower() not in ("", "0", "false", "no", "off")


def choose_engine(
    requested: str, found: Sequence[str], environ: Mapping[str, str] | None = None
) -> str:
    """Pick the container engine, as ``find_engine`` does, or refuse.

    A named engine that is not found, or ``auto`` with none found, is refused
    with ``E_SIDE_UNRESOLVED``. A read-only look-up calls ``find_engine``
    instead and reports that identity was not checked.
    """
    engine = find_engine(requested, found, environ)
    if engine is None and requested == "auto":
        raise Refusal("E_SIDE_UNRESOLVED", "no container engine found: neither docker nor podman")
    if engine is None:
        raise Refusal("E_SIDE_UNRESOLVED", f"container engine not found: {requested}")
    return engine


def env_pad(length: int) -> dict[str, str]:
    """Return the variable that pads the environment of a launch.

    Its value is ``length`` times the letter ``x``. Every entry of a round
    gets the same length, ``pairbench.model.env_pad_length(seed, round)``,
    and a warm-up launch and an explain launch get a length of 0. The
    variable is added to ``LaunchRequest.env`` only when the environment
    size is varied. It is no part of a side's fingerprint.
    """
    if isinstance(length, bool) or not isinstance(length, int) or not 0 <= length <= ENV_PAD_MAX:
        raise ValueError(f"a pad length lies from 0 to {ENV_PAD_MAX}: {length!r}")
    return {ENV_PAD_VARIABLE: ENV_PAD_LETTER * length}


def run_folders(
    artifacts: Path, artifacts_in_side: str
) -> tuple[tuple[Path, str], tuple[Path, str]]:
    """Return the folders of the two runs of a launch that holds two runs.

    ``artifacts`` is the launch's own folder on the host,
    ``LaunchRequest.artifacts``, and ``artifacts_in_side`` the same folder as
    the launch sees it, what ``ResolvedSide.artifacts_in_side`` returned for
    it. Each run has the folder named in ``RUN_FOLDERS`` under both: the
    answer holds, for the first run and then for the second, the folder on
    the host and the same folder as the launch sees it.

    A runner creates both folders on the host before the driver prepares
    the runs, and builds the ``DriverContext`` of each run from its pair. A
    container side mounts the launch's own folder and nothing else, so both
    run folders lie inside that one mount and neither run can write over
    the other.
    """
    inside = artifacts_in_side.rstrip("/")
    first, second = ((artifacts / name, f"{inside}/{name}") for name in RUN_FOLDERS)
    return first, second


def work_factor_env() -> dict[str, str]:
    """Return the variable a launch of the positive control carries under ``factor``."""
    return {WORK_FACTOR_VARIABLE: WORK_FACTOR}


def plot_extra_installed() -> bool:
    """Say whether the module the ``plot`` extra provides can be imported.

    The module itself is not imported here: only the functions that draw a
    chart import it.
    """
    try:
        return importlib.util.find_spec(PLOT_MODULE) is not None
    except (ImportError, ValueError):
        return False


def require_plot_extra(mode: str) -> None:
    """Refuse a run that asks for charts when the ``plot`` extra is not installed.

    Under plot mode ``on`` a missing extra is refused with
    ``E_PLOT_EXTRA_MISSING``, before any launch. Under ``auto`` and ``off``
    nothing is refused: ``auto`` draws no chart and says so in a loud note.
    """
    if mode == "on" and not plot_extra_installed():
        raise Refusal(
            "E_PLOT_EXTRA_MISSING",
            "charts were asked for and the plot extra is not installed: "
            "install pairbench[plot], or leave --plots at auto",
        )


# ---------------------------------------------------------------------------
# Values exchanged at run time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """One value of one case, as a driver or a side reads it from one launch.

    When a tool gives several inner samples for a case, ``value`` is their
    median, ``n_inner`` their count and ``reducer`` is ``"median"``. When a
    tool gives only its own summary, ``reducer`` is ``"tool_summary"``.

    ``value`` is a finite number. A value that is not one, such as the
    ``nan`` or ``inf`` a tool may print, is output that cannot be read: making
    the sample is refused with ``E_LAUNCH_FAILED``. A value of zero or less
    is kept; the analysis gives its case no verdict.
    """

    case: str
    metric: str
    unit: str
    better: Better
    kind: CaseKind
    value: float
    n_inner: int = 1
    reducer: str = REDUCER_IDENTITY

    def __post_init__(self) -> None:
        value = self.value
        number = isinstance(value, int | float) and not isinstance(value, bool)
        if not number or not math.isfinite(value):
            raise Refusal(
                "E_LAUNCH_FAILED",
                f"case {public_case(self.case)!r}: the value {value!r} is not a finite number",
            )

    def to_case(self, *, primary: bool, group: str | None = None) -> Case:
        """Return the case this sample describes."""
        return Case(
            id=self.case,
            metric=self.metric,
            unit=self.unit,
            better=self.better,
            kind=self.kind,
            primary=primary,
            group=group,
        )


@dataclass(frozen=True)
class Endpoint:
    """Where a started server answers: its base address and the model name requests use.

    ``deadline`` is the ``time.monotonic()`` value by which the load must
    end, set from the launch timeout counted from the server start; ``None``
    when no timeout is set.
    """

    base_url: str
    model_name: str | None = None
    deadline: float | None = None


@dataclass(frozen=True)
class Window:
    """A stretch of a launch, in ``time.monotonic()`` seconds.

    ``label`` is empty for a whole launch and the load-level label, such as
    ``c32`` or ``r32``, for one level of a serving load.
    """

    label: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class EnergyWindow:
    """The energy of one window.

    ``energy_j`` and ``mean_power_w`` are ``None`` when no value may be given;
    ``reason`` then says why. ``counter_j`` is the difference of the GPU's own
    cumulative counter over the window, when it exposes one.
    """

    label: str
    start_s: float
    end_s: float
    energy_j: float | None
    mean_power_w: float | None
    n_samples: int
    counter_j: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EnergyReading:
    """What the power sampler saw during one launch.

    ``sampler_ok`` is true when there are at least two power samples and no
    query error. ``throttle_events`` counts the throttle events the GPUs
    reported during the launch; ``None`` means the sampler could not read
    them. ``max_temperature_c`` is recorded for information. ``notes`` are
    loud notes, each a ``(code, message)`` pair.
    """

    source: str
    sampler_ok: bool
    query_errors: int
    windows: tuple[EnergyWindow, ...] = ()
    throttle_events: int | None = None
    max_temperature_c: float | None = None
    idle_power_w: float | None = None
    notes: tuple[tuple[str, str], ...] = ()

    def window(self, label: str) -> EnergyWindow | None:
        """Return the window with this label, or ``None``."""
        return next((w for w in self.windows if w.label == label), None)

    def witness(self, witness: Witness) -> Witness:
        """Return the witness of the launch with this reading's throttle events laid in.

        The power sampler reads throttle events from the same source as power,
        so its count stands where it has one: the larger of the two counts
        when the witness already holds one, and it lifts a failed probe. Where
        the sampler read none, the witness is returned as it is.
        """
        if self.throttle_events is None:
            return witness
        seen = max(self.throttle_events, witness.gpu_throttle_events or 0)
        failed = tuple(name for name in witness.failed if name != WITNESS_GPU_THROTTLE_EVENTS)
        return dataclasses.replace(witness, gpu_throttle_events=seen, failed=failed)

    def samples(self) -> list[Sample]:
        """Return the energy and mean-power cases of every window that has a value."""
        out: list[Sample] = []
        for w in self.windows:
            if w.energy_j is None or w.mean_power_w is None:
                continue
            out.append(
                Sample(
                    case=case_id(w.label, METRIC_ENERGY_J),
                    metric=METRIC_ENERGY_J,
                    unit="J",
                    better="lower",
                    kind="other",
                    value=w.energy_j,
                    n_inner=w.n_samples,
                    reducer=REDUCER_TRAPEZOID,
                )
            )
            out.append(
                Sample(
                    case=case_id(w.label, METRIC_MEAN_POWER_W),
                    metric=METRIC_MEAN_POWER_W,
                    unit="W",
                    better="lower",
                    kind="other",
                    value=w.mean_power_w,
                    n_inner=w.n_samples,
                    reducer=REDUCER_TRAPEZOID,
                )
            )
        return out

    def to_json(self) -> dict[str, Any]:
        """Return the mapping recorded under ``energy`` in a launch record."""
        return {
            "source": self.source,
            "sampler_ok": self.sampler_ok,
            "query_errors": self.query_errors,
            "windows": [
                {
                    "label": w.label,
                    "seconds": w.end_s - w.start_s,
                    "energy_j": w.energy_j,
                    "mean_power_w": w.mean_power_w,
                    "n_samples": w.n_samples,
                    "counter_j": w.counter_j,
                    "reason": w.reason,
                }
                for w in self.windows
            ],
            "throttle_events": self.throttle_events,
            "max_temperature_c": self.max_temperature_c,
            "idle_power_w": self.idle_power_w,
        }


@dataclass(frozen=True)
class Step:
    """One command of an invocation. ``label`` is empty, or a load-level label."""

    label: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Invocation:
    """What a driver wants run for one launch.

    An ``in_side`` driver returns exactly one step with an empty label; the
    side launches its ``argv``. A ``client`` driver returns one step per load
    level; the runner runs them in order on the host, beside the server, and
    times each as one energy window.
    """

    steps: tuple[Step, ...]

    @classmethod
    def single(cls, argv: Sequence[str], env: Mapping[str, str] | None = None) -> Invocation:
        """Build the invocation of an ``in_side`` driver."""
        return cls(steps=(Step(label="", argv=tuple(argv), env=dict(env or {})),))

    @property
    def argv(self) -> tuple[str, ...]:
        """The command of a single-step invocation."""
        return self._only().argv

    @property
    def env(self) -> Mapping[str, str]:
        """The added environment of a single-step invocation."""
        return self._only().env

    def _only(self) -> Step:
        if len(self.steps) != 1:
            raise ValueError("this invocation has more than one step")
        return self.steps[0]


@dataclass(frozen=True)
class DriverContext:
    """What a driver is told about one launch.

    ``artifacts`` is the launch's folder on the host and ``artifacts_in_side``
    the same folder as the launched program sees it; a driver points the
    tool's output option at the latter and reads from the former. ``settings``
    carries the load levels and the length of each. ``endpoint`` is set for a
    ``client`` driver. ``timing``, ``rc`` and ``energy`` are filled when
    ``read`` is called. ``result_file`` is set for a file side: the one
    existing file to read in place of the artifact folder. ``note`` receives
    loud notes, for example a case the tool skipped. ``launch`` are the
    launch settings already merged for the side; a driver that needs a
    setting of the launch, such as the capability to use performance
    counters, reads it there. ``case_names`` holds the names the run gives
    to the case ids it reads (``CaseNames``); a driver that cleans its ids
    itself (``CleansCaseIds``) names them with ``name_tool_cases``.

    In a launch of the positive control that holds two runs, the driver is
    asked to prepare and to read each run on its own: ``artifacts`` and
    ``artifacts_in_side`` are then the folder of that run, on the host and
    as the launch sees it, the pair ``run_folders`` gives for the run, and
    ``timing`` is the one interval around both runs.
    """

    run_id: str
    seq: int
    phase: LaunchPhase
    round: int
    name: str
    side: Side
    artifacts: Path
    artifacts_in_side: str
    settings: LoadSettings = field(default_factory=LoadSettings)
    seed: int = DEFAULT_SEED
    endpoint: Endpoint | None = None
    timing: Mapping[str, float] = field(default_factory=dict)
    rc: int | None = None
    energy: EnergyReading | None = None
    result_file: Path | None = None
    note: Notify = no_notes
    launch: LaunchSettings = field(default_factory=LaunchSettings)
    case_names: CaseNames | None = field(default=None, compare=False)


@dataclass(frozen=True)
class ToolVersion:
    """The version of the tool a driver wraps, and whether its major version was tested."""

    tool: str
    version: str
    tested: bool = True


@dataclass(frozen=True)
class DoctorReport:
    """What a plug-in reports to ``pairbench doctor``: a status and one line.

    ``detail`` holds extras for the JSON output, for example the names of
    leftover containers.
    """

    status: DoctorStatus
    summary: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SideContext:
    """What a side kind is told when it resolves or looks up a side.

    ``settings`` are the launch settings already merged for this side.
    ``workload`` is the shared workload. ``driver`` is the driver's name; a
    file side reads with it when its own format is unset. ``environ`` is the
    caller's environment: values of ``env_pass`` variables are taken from it,
    forwarded and never recorded. ``gpu`` reads the selected GPUs for a serving
    side's waits. ``mode`` is the machine-check mode. ``note`` receives loud
    notes. ``launch_folders`` is the folder in which the run makes the folder
    of each launch; it may not exist yet when the side is resolved, and it is
    ``None`` for the sides of an explain or profile session. For a look-up
    there is no run: ``run_id`` is empty, and ``gpu`` and ``launch_folders``
    are ``None``. ``workload_hashed`` is the shared workload as the published
    hash of every side's command reads it, after what each side of the
    experiment runs before it (``pairbench.model.hashed_workload``): a kind
    that hashes a command holding the workload hashes it through
    ``pairbench.model.hashed_command`` with these words, so a value that the
    client of one side hides is hidden in the hash of every side. ``None``
    leaves each side to read the workload after its own command alone.
    """

    run_id: str
    settings: LaunchSettings
    workload: tuple[str, ...] | None = None
    driver: str = "wall"
    environ: Mapping[str, str] = field(default_factory=dict)
    gpu: GpuProbe | None = None
    mode: GateMode = "warn"
    note: Notify = no_notes
    launch_folders: Path | None = None
    workload_hashed: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SideLookup:
    """What a read-only look-up found out about one side.

    ``status`` is one of:

    * ``identified``: the side is on this machine and its identity was read.
      ``identity`` holds what ``resolve`` would record, apart from the output
      of an ``identify`` command, which a look-up never runs;
    * ``absent``: the image is not on this machine and the pull policy is
      ``missing`` or ``always``, so a run would pull it. ``identity`` is
      empty;
    * ``unchecked``: no container engine could be reached, so the identity
      was not checked. ``identity`` is empty.

    ``fingerprint`` is set only when ``status`` is ``identified`` and no
    ``identify`` command is configured for the side: it then equals the
    fingerprint ``resolve`` would record. Otherwise it is empty.
    ``message`` is one line for the plan output: what a run would do about an
    absent image, why nothing was checked, or that an image under pull policy
    ``always`` is pulled again by a run.
    """

    status: LookupStatus
    identity: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    message: str = ""


@dataclass(frozen=True)
class PreparedRun:
    """The second run of a launch that holds two runs: a command as the driver prepared it.

    ``argv`` and ``env`` mean what they mean on a ``LaunchRequest``.
    """

    argv: tuple[str, ...] | None = None
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LaunchRequest:
    """One launch asked of a resolved side.

    ``name`` is the entry launched: the side's name, its twin's, or the
    positive control's. ``argv`` is the complete command the side runs:
    ``ResolvedSide.command`` as the driver prepared it. The side runs it as
    given and substitutes nothing more. ``None`` runs the default command of
    an image, and is what a serving side and a file side get. ``env`` is what
    the launch adds to the environment: what the driver asked for, the
    environment pad of the round and, for the positive control under
    ``factor``, the work factor. None of it is part of a fingerprint.
    ``artifacts`` is this launch's folder on the host; standard output and
    standard error go to ``stdout.txt`` and ``stderr.txt`` in it. A relative
    ``artifacts`` is taken from the current directory: the side makes it
    absolute before it uses it, so a container mount and a process started
    in another directory see the same folder. ``load`` is
    set for a serving launch: the side calls it once, with the endpoint, after
    the first answer and before it stops the server. For a file side ``pos``
    is ``None`` and ``round`` picks the file.

    ``second`` is set for a launch of the positive control that runs the
    workload twice in one start. The side starts once and runs ``argv`` and
    then the command of ``second``, the second only when the first exited
    with zero:

    * an image side starts one container whose command runs both;
    * a command side and a Python environment side start two processes, one
      after the other, inside one clock interval: the clock is read before
      the first process starts and after the exit of the second is
      collected, and nothing avoidable happens in between.

    Standard output and standard error of the first run go into the folder
    ``RUN_FOLDERS[0]`` under ``artifacts`` and those of the second into
    ``RUN_FOLDERS[1]``; the driver prepared each command against its own of
    the two folders and reads each from it. ``artifacts`` stays the launch's
    own folder, the one folder a container side mounts; both run folders
    exist under it before the launch starts (``run_folders``). A side whose
    ``ResolvedSide.cannot_repeat`` gives a reason is never sent a request
    with ``second``. A serving launch has no ``second``: its ``load`` runs
    the load twice against the one server start.

    ``tool_files`` are files of the tool the launch must be able to read,
    such as the sampler of the ``pystacks`` instrument. A container side
    mounts each read-only; ``ResolvedSide.tool_file_in_side`` says where the
    launch sees it. ``wrap_server`` is set for an explain launch of a
    serving side: the launcher hands it the command that starts the server
    and starts what comes back, the command and the environment it adds; a
    launcher that cannot start its server under another command refuses with
    ``E_ENGINE_UNSUPPORTED``. It is set too for an explain or profile launch
    of an image side: the side hands it the whole command line its container
    would run for ``argv`` (the entrypoint and the command) and runs what
    comes back, its first word as the entrypoint.
    """

    run_id: str
    seq: int
    phase: LaunchPhase
    round: int
    pos: int | None
    name: str
    artifacts: Path
    argv: tuple[str, ...] | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    load: Callable[[Endpoint], None] | None = None
    second: PreparedRun | None = None
    tool_files: tuple[Path, ...] = ()
    wrap_server: Callable[[Sequence[str]], InstrumentedCommand] | None = None


@dataclass(frozen=True)
class LaunchNote:
    """A loud note about one launch, handed back for the run to give.

    ``code`` and ``message`` are the note's text code and its words, which
    name the launch's entry (``LaunchRequest.name``). ``cases`` are the cases
    the note speaks for, such as the start-up phases a serving side timed
    late.
    """

    code: str
    message: str
    cases: tuple[str, ...] = ()


@dataclass(frozen=True)
class LaunchOutcome:
    """What one launch gave back.

    ``timing`` holds ``run_s``, the launch's own start-to-finish time, and
    ``launch_s``, the wall time on the host from the start request to exit.
    A command or Python environment side is one process on the host: it reads
    one monotonic clock directly before the call that starts the process and
    directly after the call that collects its exit, gives ``run_s`` the
    difference and ``launch_s`` the same value, and adds ``user_s`` and
    ``sys_s``, the CPU time of the exited process, where the platform reports
    it. Between the two reads it does nothing it can avoid: the output goes
    to files that are read afterwards.
    ``cpu_s`` is the CPU time the launch itself used, or ``None`` when it
    cannot be told; the busy-cores witness leaves it out. ``samples`` are
    cases the side measured itself, such as the start-up cases of a serving
    side. ``result_file`` is set by a file side.

    ``pid`` is how the machine checks learn which processes were the launch's
    own: the id of the launch's first process as this machine numbers it,
    which is the process the side started or the first process of the
    container. It is ``None`` when the side cannot tell it, for example
    because the engine runs on another machine or in a virtual machine.

    ``usage`` holds the resource usage of the launch beyond its CPU time,
    under the keys of ``USAGE_KEYS``: the peak resident memory in bytes, the
    voluntary and involuntary context switches, the major and minor page
    faults. A command side and a Python environment side take it, and
    ``user_s`` and ``sys_s``, from what the exit status call returns for the
    process and the children it waited for; an image side from the engine's
    own statistics for the container; a serving side from the engine's
    statistics for the server over the load phase. A key that is absent, in
    ``usage`` or for the CPU time in ``timing``, says the source does not
    give that figure: its case is missing for the launch. ``usage`` holds no
    other key: making an outcome with one is refused with ``ValueError``.
    ``resource_samples`` turns all of it into the cases under ``res/``.

    A launch that held two runs, one asked for with ``LaunchRequest.second``,
    reports one interval around both: ``run_s`` and ``launch_s`` run from
    before the first run to after the second. ``rc`` is zero only when both
    runs exited with zero, and otherwise the exit code of the run that
    failed. ``cpu_s`` covers both runs. ``pid`` is the first process of the
    first run and ``second_pid`` that of the second, where the two runs are
    two processes the side started itself; it is ``None`` for every other
    launch.

    ``cannot_repeat`` is set only by a failed launch of two runs whose side
    can tell that the launch failed because the side cannot run two commands
    in one start after all, for example because the shell of an image was
    refused when writing a run's output file: it gives the reason in one
    line, and the run goes on without the positive control.

    ``notes`` are the loud notes the side has about the launch, such as a
    serving side's start-up phases timed late. The run gives each once per
    entry and code, after the round the launch is in has completed: for a
    twin under the twin's own name, and for the positive control only when a
    case the note speaks for is primary, even when the control is then not
    judged. A failed or interrupted round gives none, and so does every launch
    outside the rounds.
    """

    rc: int
    timing: Mapping[str, float] = field(default_factory=dict)
    timed_out: bool = False
    cpu_s: float | None = None
    samples: tuple[Sample, ...] = ()
    result_file: Path | None = None
    pid: int | None = None
    usage: Mapping[str, float] = field(default_factory=dict)
    second_pid: int | None = None
    cannot_repeat: str | None = None
    notes: tuple[LaunchNote, ...] = ()

    def __post_init__(self) -> None:
        unknown = sorted(set(self.usage) - set(USAGE_KEYS))
        if unknown:
            raise ValueError(
                f"usage holds only the keys {', '.join(USAGE_KEYS)}: got {', '.join(unknown)}"
            )


@dataclass(frozen=True)
class InstrumentedCommand:
    """A command wrapped by an instrument of the explain step.

    ``argv`` is the command to start and ``env`` what it adds to the
    environment. ``outputs`` names the files the instrument writes, relative
    to the launch's artifact folder.
    """

    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstrumentedLaunch:
    """What one explain launch gave back.

    ``rc`` is the exit code of the launch and ``timed_out`` says it ran into
    its timeout; neither is raised. ``artifacts`` is the launch's folder on
    the host and ``outputs`` the files the instrument was to write, as paths
    on the host; a file the launch did not write does not exist.
    """

    rc: int
    artifacts: Path
    outputs: tuple[Path, ...] = ()
    timed_out: bool = False


@dataclass(frozen=True)
class ToolCpus:
    """Where the tool's own process runs once a CPU set is pinned.

    ``cpus`` is the CPU list the tool moved itself to, outside the pinned
    set, or ``None`` when it did not move. ``reason`` then says why: no CPU
    set is pinned (``not_pinned``), no CPU is left outside the set
    (``none_left``), or the platform does not allow a process to choose its
    CPUs (``unsupported``).
    """

    cpus: str | None = None
    reason: NotMoved | None = None

    def __post_init__(self) -> None:
        if (self.cpus is None) == (self.reason is None):
            raise ValueError("the tool either moved to a CPU list or says why it did not")


def resource_samples(outcome: LaunchOutcome, seconds: float | None = None) -> list[Sample]:
    """Return the resource cases of one launch: the cases under ``res/``.

    The CPU time comes from ``outcome.timing`` (``user_s``, ``sys_s``) and
    every other figure from ``outcome.usage``. ``res/cores`` is the user
    plus the system CPU time divided by ``seconds``, the time the usage
    covers: the launch's ``run_s`` unless another length is given, as for a
    serving launch, whose usage covers the load phase. A figure the side
    did not report gives no sample, and so does ``res/cores`` without both
    CPU times or without a length above zero. A value of zero is kept.

    Every sample has ``better`` of ``none``. The positive-control entry
    records no resource cases: this function is not called for its launches.
    """
    timing, usage = outcome.timing, outcome.usage
    user, system = timing.get(TIMING_USER_S), timing.get(TIMING_SYS_S)
    span = timing.get(TIMING_RUN_S) if seconds is None else seconds
    cores: float | None = None
    if user is not None and system is not None and span is not None and span > 0:
        cores = (user + system) / span
    figures: dict[str, float | None] = {
        CASE_RES_USER: user,
        CASE_RES_SYS: system,
        CASE_RES_CORES: cores,
        CASE_RES_RSS_PEAK: usage.get(USAGE_RSS_PEAK_BYTES),
        CASE_RES_CTX_VOLUNTARY: usage.get(USAGE_CTX_VOLUNTARY),
        CASE_RES_CTX_INVOLUNTARY: usage.get(USAGE_CTX_INVOLUNTARY),
        CASE_RES_FAULTS_MAJOR: usage.get(USAGE_FAULTS_MAJOR),
        CASE_RES_FAULTS_MINOR: usage.get(USAGE_FAULTS_MINOR),
    }
    out: list[Sample] = []
    for case in RESOURCE_CASES:
        value = figures[case]
        if value is None:
            continue
        record = resource_case(case)
        out.append(
            Sample(
                case=case,
                metric=record.metric,
                unit=record.unit,
                better=record.better,
                kind=record.kind,
                value=value,
            )
        )
    return out


def missing_resource_cases(samples: Sequence[Sample]) -> tuple[str, ...]:
    """Name the resource cases a launch did not give, in the order of ``RESOURCE_CASES``.

    A runner names each of them once per run in a loud note.
    """
    given = {sample.case for sample in samples}
    return tuple(case for case in RESOURCE_CASES if case not in given)


def refuse_reserved_cases(samples: Sequence[Sample]) -> None:
    """Refuse a driver's own case whose id starts with a reserved prefix.

    The prefixes ``res/`` and ``startup/`` belong to the tool's own cases. A
    workload line or a tool result with such an id is a failed launch:
    ``E_LAUNCH_FAILED``. A runner calls this on what ``Driver.read``
    returned, and not on the cases a side measured itself or on the resource
    cases.
    """
    taken = sorted(sample.case for sample in samples if is_reserved_case(sample.case))
    if taken:
        prefixes = " or ".join(repr(prefix) for prefix in RESERVED_CASE_PREFIXES)
        raise Refusal(
            "E_LAUNCH_FAILED",
            f"a case id of a workload or a tool may not start with {prefixes}: {', '.join(taken)}",
        )


def refuse_shown_alike(names: Iterable[tuple[str, str]], where: str, advice: str) -> None:
    """Refuse two different case ids that a results document would show as one.

    ``names`` holds each id as read and as shown. The same id read twice is
    left for the check of an id given twice; two different ids shown alike
    are refused with ``E_USAGE``. The message names only the id as shown,
    then ``advice``, so it holds no path and no credential.
    """
    seen: dict[str, str] = {}
    for raw, shown in names:
        first = seen.setdefault(shown, raw)
        if first != raw:
            raise Refusal("E_USAGE", f"{where}: {_shown_alike(shown)}; {advice}")


def _shown_alike(shown: str) -> str:
    """Return what a refusal of two different case ids shown as ``shown`` says of them."""
    return (
        f"two different cases have the name {shown!r} once absolute paths and paths that climb "
        "with '..' are cut and secrets hidden, as the results show it"
    )


# What the refusal of two case ids shown alike asks for: the words a path runs over are cut
# with it (``public_case``), so ids that differ only there are shown alike.
_PATHS_RUN_ON_ADVICE = (
    "give them names that differ outside their paths, absolute or climbing with '..', and "
    "outside their secrets; a path runs on over the words after it that start with a letter, a "
    "digit or '_', up to the last that holds a '/', and a quote ends it"
)


def _alike(first: str, raw: str, advice: str) -> str:
    """Say what alone two different ids with one name and one tell differ in, then ``advice``.

    It names the first of these that holds, read with their secrets
    hidden: nothing, so a hidden secret; the spaces between their words;
    words that hold a ``/``, when their paths written with percent escapes
    are alike; or the folders of such a path, with or without such words.
    The ids themselves are never named.
    """
    first_hidden, hidden = case_secrets_hidden(first), case_secrets_hidden(raw)
    if first_hidden == hidden:
        return f"differ only in a hidden secret; {advice}"
    if first_hidden.split() == hidden.split():
        return (
            f"differ only in the spaces between their words once their secrets are hidden; {advice}"
        )
    if case_percent_paths(first_hidden) == case_percent_paths(hidden):
        return (
            "differ only in words that hold a '/' once their secrets are hidden; pairbench reads "
            f"such words as folders, which may differ between sides and launches; {advice}"
        )
    return (
        "differ only in the folders of a path written with '%2F', or in those and words that "
        "hold a '/', once their secrets are hidden; pairbench reads such parts as folders, which "
        f"may differ between sides and launches; {advice}"
    )


def case_tell_sha256(raw: str) -> str:
    """Return the SHA-256 of what tells the case id ``raw`` apart from ids cut alike.

    An id whose cut drops words that hold no ``/``
    (``pairbench.model.public_case_drops``) is told apart by its words,
    split on white space, that hold no ``/``, in order, read with its
    secrets hidden and a path written with percent escapes cut to ``%2F``
    and its last part (``pairbench.model.case_tell_words``): the words its
    path runs over are among them, a word that holds a ``/``, the folders
    of a cut path, a folder name with blanks included, and the folders of
    a path written with ``%2F`` are read as folders, which may differ
    between sides and launches, and a secret never tells two cases apart.
    Any other id is told apart by its name as shown. The hash is of the
    compact JSON text of ``["words", word, ...]`` or of ``["name", shown]``.
    """
    shown, drops = public_case_drops(raw)
    tell = ["words", *case_tell_words(raw)] if drops else ["name", shown]
    return case_text_sha256(json.dumps(tell, ensure_ascii=False, separators=(",", ":")))


class CaseNames:
    """The names a run gives to the case ids it reads, kept for the whole capture.

    An id is shown with its absolute paths cut and its secrets hidden
    (``pairbench.model.public_case``). When the cut drops words that hold
    no ``/``, such as the words a path runs over, the name ends with a mark
    (``pairbench.model.case_suffix``): `` +`` and eight hex digits of the
    keyed hash, under the run's ``key``, of what tells the case apart
    (``case_tell_sha256``). So two ids that differ in those words have two
    names, and an id has the same name in every launch and on every side of
    the run whatever its folder. A name is a function of the key and the
    id alone.

    Two different ids of one read with one name are refused with
    ``E_USAGE``: ids that differ only in a hidden secret, ids that differ
    only in words that hold a ``/`` or in the folders of a path written
    with ``%2F`` (read as folders), ids that differ only in the spaces
    between the words their cut drops, and two whose marks clash. An id
    that is shown ending like a mark is refused too, and so is an id that
    needs a mark when ``key`` is ``None``: a run always has a key, and a
    driver read outside a run has none. A refusal gives no name.

    ``take_new`` returns the entries the capture records (``CaseName``):
    one for each side and id of a name that differs from an id read under
    it, with the key the first time a name with a mark is among them. A
    read without a key, or without a side, writes no capture and records
    nothing.
    """

    def __init__(self, key: bytes | None) -> None:
        self._key = key
        self._given: dict[str, tuple[str, str, bool]] = {}
        self._tells: dict[str, str] = {}
        self._reads: dict[str, list[tuple[str, str]]] = {}
        self._recorded: set[str] = set()
        self._seen: set[tuple[str, str]] = set()
        self._new: list[CaseName] = []
        self._key_due = False
        self._key_taken = False

    def names(self, raws: Sequence[str], where: str, advice: str, side: str = "") -> dict[str, str]:
        """Return the name of each id in ``raws``, read by ``side``; refuse a read they cannot hold.

        ``where`` starts a refusal's message and ``advice`` ends it. The
        message names the ids only as they are shown.
        """
        read: dict[str, dict[str, str]] = {}
        given: dict[str, tuple[str, str, bool]] = {}
        for raw in dict.fromkeys(raws):
            name, tell, marked = self._given.get(raw) or self._name(raw, where, advice)
            given[raw] = (name, tell, marked)
            first = read.setdefault(name, {}).setdefault(tell, raw)
            if first != raw:
                alike = _alike(first, raw, advice)
                raise Refusal("E_USAGE", f"{where}: {_shown_alike(name)}, and {alike}")
        for name, tells in read.items():
            known = self._tells.get(name)
            if len(tells) > 1 or (known is not None and known not in tells):
                raise Refusal(
                    "E_USAGE",
                    f"{where}: two different cases would have the name {name!r}: the marks "
                    f"pairbench adds to names whose cut dropped words clash; {advice}",
                )
        for raw, (name, tell, marked) in given.items():
            self._given[raw] = (name, tell, marked)
            self._tells.setdefault(name, tell)
            self._key_due = self._key_due or marked
            if self._key is not None and side:
                self._record(name, tell, raw, side)
        return {raw: name for raw, (name, _, _) in given.items()}

    def _name(self, raw: str, where: str, advice: str) -> tuple[str, str, bool]:
        shown, drops = public_case_drops(raw)
        if case_has_suffix(shown):
            raise Refusal(
                "E_USAGE",
                f"{where}: the case read as {shown!r} ends like the mark pairbench adds to a name "
                "whose cut dropped words, ' +' and eight hex digits; give it a name that does not "
                "end so",
            )
        tell = case_tell_sha256(raw)
        if not drops:
            return shown, tell, False
        if self._key is None:
            raise Refusal(
                "E_USAGE",
                f"{where}: the cut of the case read as {shown!r} drops words that hold no '/', so "
                "its name needs the mark a run makes with its own key, and this read has none; "
                f"read it in a run, or {advice}",
            )
        return shown + case_suffix(self._key, tell), tell, True

    def _record(self, name: str, tell: str, raw: str, side: str) -> None:
        if name not in self._recorded:
            reads = self._reads.setdefault(name, [])
            if (side, raw) not in reads:
                reads.append((side, raw))
            if raw == name:
                return
            self._recorded.add(name)
            pending = self._reads.pop(name)
        else:
            pending = [(side, raw)]
        for one_side, one_raw in pending:
            if (one_side, one_raw) in self._seen:
                continue
            self._seen.add((one_side, one_raw))
            self._new.append(
                CaseName(
                    name=name,
                    side=one_side,
                    tell_sha256=tell,
                    hidden_sha256=case_text_sha256(case_secrets_hidden(one_raw)),
                    read_sha256=case_text_sha256(one_raw),
                )
            )

    def take_new(self) -> tuple[str | None, tuple[CaseName, ...]]:
        """Return the run's key when the capture must record it now, and the entries since last.

        The key is returned once, with the first entries after a name with
        a mark was given; it is lower-case hex.
        """
        key: str | None = None
        if self._key_due and not self._key_taken and self._key is not None:
            key = self._key.hex()
            self._key_taken = True
        new, self._new = tuple(self._new), []
        return key, new


def public_cases(
    samples: Sequence[Sample], where: str, names: CaseNames | None = None, side: str = ""
) -> list[Sample]:
    """Return what a driver read, with each case id as a results document may show it.

    Every absolute path in an id, and every relative path that climbs out
    of its folder with ``..``, is cut to its last part, as
    ``pairbench.model.public_case`` cuts it, so a test named after a file
    (``test_read[/a/b/data.csv]``) gives ``test_read[data.csv]``, and an id
    without a path, such as ``BM_Vec<int>/8/cpu_time``, is kept as it is. A
    path in an id runs on over the words after it that start with a letter,
    a digit or ``_``, up to the last that holds a ``/``, and a quote ends it,
    so ``read /a/in.csv fast mode/x`` and ``read /a/in.csv slow mode/x`` are
    both cut to ``read x``; with the names of the run (``names``) they are
    named ``read x +`` and eight hex digits each, two different marks
    (``CaseNames``). Without them the read has no key, and an id whose cut
    drops such words is refused with ``E_USAGE``, as are two different ids
    shown alike. ``where`` starts a refusal's message. A runner calls this
    on what ``Driver.read`` returned, before it records any case, so the
    capture, the results and the reports hold the same ids. A driver that
    adds a part to a name the tool gave, such as ``/cpu_time``, names the
    tool's name before it adds the part and says so (``CleansCaseIds``);
    the runner keeps its ids as they are (``shown_cases``).
    """
    named = names if names is not None else CaseNames(None)
    given = named.names([sample.case for sample in samples], where, _PATHS_RUN_ON_ADVICE, side)
    return [
        sample
        if sample.case == given[sample.case]
        else dataclasses.replace(sample, case=given[sample.case])
        for sample in samples
    ]


def shown_cases(
    driver: object,
    samples: Sequence[Sample],
    where: str,
    names: CaseNames | None = None,
    side: str = "",
) -> list[Sample]:
    """Return what ``driver`` read, with each case id as a results document may show it.

    The ids of a driver that cleans them itself (``CleansCaseIds``) are kept
    as they are: cleaning one again could read a cut name and the part the
    driver added after it as the host and the path of an address, and show
    ``file://m.gguf/cpu_time`` as ``file://cpu_time``; such a driver names
    its ids with ``DriverContext.case_names``. The ids of any other driver
    go through ``public_cases`` with ``names``, as read by ``side``.
    """
    if getattr(driver, "cleans_case_ids", False) is True:
        return list(samples)
    return public_cases(samples, where, names, side)


def name_tool_cases(
    ctx: DriverContext, listed: Sequence[str], where: str, advice: str
) -> dict[str, str]:
    """Return the name of each id a tool listed, for a driver that names its ids itself.

    With the names of the run (``ctx.case_names``) every listed id is named
    as ``CaseNames`` names it, read by the side ``ctx.name``; without them
    the read has no key, so an id whose cut drops words that hold no ``/``
    is refused, as are two different ids shown alike.
    """
    named = ctx.case_names if ctx.case_names is not None else CaseNames(None)
    return named.names(listed, where, advice, ctx.name)


def case_of(
    sample: Sample, cases: CaseSettings, default: Iterable[str], *, late: bool = False
) -> Case:
    """Return the record of the case a sample describes, as a runner writes it.

    A resource case is recorded by ``pairbench.model.resource_case``: it is
    secondary and a floor group of its own, whatever the patterns of the
    config say. Every other case is primary as ``cases.is_primary`` says,
    with ``default`` being what ``Driver.default_primary`` returned, and in
    the group ``cases.group_of`` gives. ``late`` says the case was first
    seen after the warm-up: it is then secondary.
    """
    if sample.case in RESOURCE_CASES:
        return resource_case(sample.case)
    primary = not late and cases.is_primary(sample.case, default, better=sample.better)
    return sample.to_case(primary=primary, group=cases.group_of(sample.case))


def control_samples(samples: Sequence[Sample]) -> list[Sample]:
    """Return the cases of a launch of the positive control that ran the workload once.

    Under ``factor`` the workload does twice the work inside its own timing
    and its values are taken as reported. A case whose ``better`` is
    ``none`` is not recorded for the entry.
    """
    return [sample for sample in samples if sample.better != "none"]


def combine_runs(
    first: Sequence[Sample], second: Sequence[Sample], *, clock: Iterable[str] = ()
) -> list[Sample]:
    """Return the cases of a launch that held two runs, from what was read of each run.

    A case that the workload or a driver reports is combined over the two
    runs with ``pairbench.model.combine_control``: the values add up where
    lower is better and combine as rates where higher is better. A case
    named in ``clock`` is a time the tool or the engine measured: it is the
    one interval around both runs, both reads hold the same value, and it is
    taken as it is and never combined. A case whose ``better`` is ``none``
    is not recorded for the entry, and neither is a case only one of the two
    runs gave: ``uncombined_cases`` names those, and a runner says so in a
    loud note.

    ``clock`` is what ``clock_cases(driver)`` returns.
    """
    by_case = {sample.case: sample for sample in second}
    timed = set(clock)
    out: list[Sample] = []
    for one in first:
        other = by_case.get(one.case)
        if other is None or one.better == "none":
            continue
        if one.case in timed:
            out.append(one)
            continue
        value = combine_control(one.value, other.value, one.better)
        if value is None:
            continue
        out.append(
            dataclasses.replace(
                one, value=value, n_inner=one.n_inner + other.n_inner, reducer=REDUCER_TWO_RUNS
            )
        )
    return out


def uncombined_cases(first: Sequence[Sample], second: Sequence[Sample]) -> tuple[str, ...]:
    """Name the cases only one of the two runs of a launch gave, in the order read.

    ``combine_runs`` records no value for such a case, because half a value
    cannot stand for twice the work. Nothing is left out silently: a runner
    names each of them once per run in a loud note with the code
    ``pairbench.model.NOTE_CONTROL_CASE_MISSING``. A case whose ``better`` is
    ``none`` is never recorded for the entry and is not named here.
    """
    one = {sample.case for sample in first}
    other = {sample.case for sample in second}
    return tuple(
        dict.fromkeys(
            sample.case
            for sample in (*first, *second)
            if sample.better != "none" and (sample.case in one) != (sample.case in other)
        )
    )


@dataclass(frozen=True)
class CpuFacts:
    """The CPUs of a pinned set, or of the machine when nothing is pinned.

    ``identity`` has one entry per core type. ``cache_domains`` lists the
    CPUs that share a last-level cache. ``mixed`` says the set holds more
    than one core type.
    """

    identity: tuple[CpuGroup, ...] = ()
    cache_domains: tuple[str, ...] = ()
    mixed: bool = False


@dataclass(frozen=True)
class GateContext:
    """What a machine check is told.

    ``phase`` is ``before`` for the checks ahead of the locks and ``recheck``
    for the short re-check once the locks are held; a check never waits in
    the re-check. ``in_container`` and ``ci`` are the facts of the machine
    record: the run is inside a container, or in an automated pipeline. A
    check waits for a quiet machine only when ``gates.wait_quiet`` is set.
    ``sides`` holds the launch settings each launched side runs with, by side
    name, overrides merged in. It is empty when the sides are not known; a
    check then reads ``launch`` and the sides its overrides name.
    """

    mode: GateMode
    gates: GateSettings
    launch: LaunchSettings
    phase: GatePhase = "before"
    environ: Mapping[str, str] = field(default_factory=dict)
    in_container: bool = False
    ci: bool = False
    note: Notify = no_notes
    sides: Mapping[str, LaunchSettings] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportOptions:
    """Display choices for a report, and what else a report may show.

    ``cases``, ``all_cases`` and ``verbose`` filter what is shown, never what
    was tested. ``diagnostics`` is the diagnostics document of the run, when
    there is one: the terminal and markdown reports add its findings and the
    report page adds the diagnostics. ``folder`` is the run folder: the
    report page embeds the chart and flame-graph files found there. Without
    either, every format is rendered from the results alone.
    """

    cases: tuple[str, ...] = ()
    all_cases: bool = False
    verbose: bool = False
    diagnostics: Diagnostics | None = None
    folder: Path | None = None


@dataclass(frozen=True)
class ProfiledCommand:
    """A command wrapped by a profiler, and the files the profiler will write."""

    argv: tuple[str, ...]
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class ToolFact:
    """Whether an external program was found, and its version."""

    name: str
    found: bool
    version: str | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# Plug-in group: pairbench.side_kinds
# ---------------------------------------------------------------------------


class ResolvedSide(Protocol):
    """A side that was resolved and can be identified, launched and torn down.

    Required of an implementation:

    * ``side`` carries the recorded identity and the fingerprint
      ``fingerprint_of(identity, settings.effective(...))``;
    * ``command`` is the complete command a launch of this side runs, before
      the driver prepares it. Every substitution is already made: a ``cmd``
      side gives its own arguments with ``{workload}`` replaced by the shared
      workload; an image side gives its own ``args``, else the shared
      workload, else ``None`` for the image's default command; a Python
      environment side gives its interpreter followed by the workload, a
      leading ``python`` or ``python3`` of the workload being replaced by the
      interpreter. A serving side and a file side give ``None``. A side
      whose container runs more than ``command``, an image side with an
      entrypoint or a default command, may also give ``whole_command``, that
      whole command line or ``None``; the explain step reads it, when given,
      in place of ``command`` to choose its sampler;
    * ``identify`` reads the identity again, so the runner can compare it
      after the last round; it never pulls;
    * ``launch`` starts a fresh launch, waits for it, tears it down and
      removes what it created, also when it is interrupted. A container is
      started by image ID with pulling disabled, named with
      ``container_name`` and has the artifact folder mounted at
      ``ARTIFACTS_IN_CONTAINER``. Values of ``env_pass`` variables are
      forwarded and never recorded. A setting the kind cannot honour is
      refused with ``E_ENGINE_UNSUPPORTED``, never dropped;
    * a non-zero exit or a timeout is reported in the outcome, not raised:
      the runner decides what a failed launch means;
    * a file side launches nothing. Its files are the matches of its paths,
      sorted by file name; ``rounds_available`` is their number; ``launch``
      for round ``r`` returns ``LaunchOutcome(rc=0, result_file=...)`` with
      the ``r``-th of them, counted from 1;
    * ``launch`` reports the resource usage of the launch in the outcome, as
      ``LaunchOutcome`` states for each kind of side;
    * a container is given the capability to use performance counters, and
      no other capability, exactly when the launch setting ``perf_counters``
      is set. A capability that was not asked for is never added;
    * ``cannot_repeat`` says whether the side can run two prepared commands
      in one start, which a launch of the positive control asks for with
      ``LaunchRequest.second``. A command side and a Python environment side
      always can. An image side can when the image lets one container run
      two commands one after the other, for example because it holds a
      shell; when it does not, the property gives the reason in one line.
      The answer is known before the first measured launch and does not
      change during a run. A side that gave no reason and then cannot run
      the second command reports a failed launch, as for any other command
      that does not start; it never runs the two commands as two launches.
      When it can tell that cause, it says so in
      ``LaunchOutcome.cannot_repeat``, and the run goes on without the
      control.
    """

    @property
    def side(self) -> Side:
        """The side with its identity and fingerprint filled in."""
        ...

    @property
    def command(self) -> tuple[str, ...] | None:
        """The complete command of a launch before the driver prepares it, or ``None``."""
        ...

    @property
    def engine(self) -> EngineInfo | None:
        """The container engine this side uses, or ``None`` when it uses none."""
        ...

    @property
    def rounds_available(self) -> int | None:
        """How many rounds exist: the number of files of a file side, else ``None``."""
        ...

    @property
    def cannot_repeat(self) -> str | None:
        """Why the side cannot run two commands in one start, or ``None`` when it can."""
        ...

    def identify(self) -> Mapping[str, Any]:
        """Read the identity again."""
        ...

    def artifacts_in_side(self, host: Path) -> str:
        """Return the path under which a launch sees its artifact folder.

        ``host`` is the launch's own folder, ``LaunchRequest.artifacts``, and
        never a folder under it. A side on the host sees the folder where it
        is; a container side sees it at ``ARTIFACTS_IN_CONTAINER``, whatever
        the folder on the host. The folders of the two runs of a launch that
        holds two runs are not asked for here: ``run_folders`` derives them
        from this answer.
        """
        ...

    def tool_file_in_side(self, host: Path) -> str:
        """Return the path under which a launch sees a file of ``LaunchRequest.tool_files``.

        A side on the host sees the file where it is. A container side sees
        it under ``TOOLS_IN_CONTAINER``, by its own file name, mounted
        read-only.
        """
        ...

    def launch(self, request: LaunchRequest) -> LaunchOutcome:
        """Run one launch to its end and tear it down.

        A pinned CPU set the side cannot apply when it starts the launch is
        refused with ``E_PIN_UNSUPPORTED`` (exit 4).
        """
        ...

    def close(self) -> None:
        """Release everything still held. Safe to call more than once."""
        ...


class SideKind(Protocol):
    """A kind of side: ``cmd``, ``image``, ``python``, ``venv``, ``conda``, ``serve``, ``file``.

    ``resolve`` turns a declared side into something launchable and records
    its identity. The image pull policy applies in ``resolve`` and nowhere
    else. A side that cannot be found is refused with ``E_SIDE_UNRESOLVED``;
    one that cannot be identified, or whose ``identify`` command gives no
    output or fails, with ``E_SIDE_UNIDENTIFIED``. ``resolve`` starts no
    workload.

    ``look_up`` reads a side's identity for the plan command and changes
    nothing: it never pulls, starts no container, runs no ``identify``
    command, creates no directory and takes no lock. It may inspect an image
    that is already on the machine, ask an interpreter for its version and
    its installed distributions, and hash files. What it reports and what it
    refuses:

    * an image that is not on the machine: status ``absent`` under pull
      policy ``missing`` or ``always``; refused with ``E_SIDE_UNRESOLVED``
      under ``never``;
    * no container engine reachable: status ``unchecked``, never a refusal.
      It finds the engine with ``find_engine``, not ``choose_engine``;
    * an executable, an interpreter, an environment or a result file that
      does not exist: refused with ``E_SIDE_UNRESOLVED``;
    * a launch setting the kind cannot honour: refused with
      ``E_ENGINE_UNSUPPORTED``;
    * a side that exists but whose identity cannot be read, such as an
      interpreter that gives no version: refused with
      ``E_SIDE_UNIDENTIFIED`` (exit 3);
    * a spec the kind cannot read: refused with ``E_USAGE``.

    It raises no other refusal.
    """

    @property
    def name(self) -> str: ...

    @property
    def api_version(self) -> int: ...

    def resolve(self, side: Side, ctx: SideContext) -> ResolvedSide:
        """Resolve and identify one side."""
        ...

    def look_up(self, side: Side, ctx: SideContext) -> SideLookup:
        """Read one side's identity without changing anything."""
        ...


# ---------------------------------------------------------------------------
# Plug-in group: pairbench.drivers
# ---------------------------------------------------------------------------


class Driver(Protocol):
    """Turns one launch into one value per case.

    Required of an implementation:

    * ``prepare`` adds the wrapped tool's own output option when the user's
      command lacks it, pointing at ``ctx.artifacts_in_side``, and changes
      nothing else of the command. For an ``in_side`` driver ``argv`` is
      ``ResolvedSide.command``, complete and already substituted, or empty
      when the side has none; the side then runs the returned command as it
      is. A driver that needs a command to add its option to refuses an empty
      one with ``E_USAGE``; ``wall`` returns it unchanged. For a ``client``
      driver ``argv`` is the shared workload, or empty; it builds one step
      per load level against ``ctx.endpoint`` and passes ``ctx.seed`` to a
      tool that accepts a seed. ``prepare`` is not called for a file side;
    * ``read`` returns one ``Sample`` per case from ``artifacts``, or from
      ``ctx.result_file`` for a file side. Output it cannot read is refused
      with ``E_LAUNCH_FAILED``. A case the tool skipped is left out and
      reported through ``ctx.note``;
    * ``default_primary`` names the cases that count toward the verdict. It
      may name every case it read: a case whose ``better`` is ``none`` is
      recorded as secondary all the same, without a refusal.

    An implementation declares ``where`` with its full type, for example
    ``where: Literal["in_side", "client"] = "in_side"``.
    """

    name: str
    api_version: int
    where: Literal["in_side", "client"]

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation: ...

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]: ...

    def default_primary(self, samples: list[Sample]) -> list[str]: ...


@runtime_checkable
class ReportsToolVersion(Protocol):
    """A driver that can tell the version of the tool it wraps.

    The runner records the version on the launch record and writes a loud
    note when ``tested`` is false: a major version the driver was not tested
    with is a note, never a refusal.
    """

    def tool_version(self, ctx: DriverContext, artifacts: Path) -> ToolVersion | None: ...


@runtime_checkable
class ReadsLaunchClock(Protocol):
    """A driver that reads cases from the launch's own clock.

    ``clock_cases`` names the cases whose value the driver takes from
    ``DriverContext.timing``, a time the tool or the engine measured, and
    not from what the workload or a tool reported: ``wall`` and ``launch``
    for the ``wall`` driver. In a launch of the positive control that holds
    two runs such a time is the one interval around both runs and is never
    combined; ``combine_runs`` is told these cases. A driver without the
    attribute reads no case from the clock.
    """

    clock_cases: tuple[str, ...]


@runtime_checkable
class CleansCaseIds(Protocol):
    """A driver that gives each case id as a results document may show it.

    ``cleans_case_ids`` is true when ``read`` names every name the tool gave
    before it adds a part of its own, such as ``/cpu_time``, through
    ``name_tool_cases``: with the names of the run
    (``DriverContext.case_names``) a name whose cut dropped words that hold
    no ``/`` ends with the run's mark, and without them such a name is
    refused. The runner records such ids as they are (``shown_cases``). A
    driver without the attribute has its ids cleaned by the runner
    (``public_cases``).
    """

    cleans_case_ids: bool


def clock_cases(driver: object) -> tuple[str, ...]:
    """Return the cases a driver reads from the launch's own clock, or none.

    The attribute holds case ids. One text in place of a list of them is
    refused with ``TypeError``: its letters would be taken for case ids and
    the clock's own cases would be combined after all.
    """
    named = getattr(driver, "clock_cases", ())
    if isinstance(named, str) or not all(isinstance(case, str) for case in named):
        raise TypeError(f"clock_cases is a list of case ids: {named!r}")
    return tuple(named)


@runtime_checkable
class Diagnosable(Protocol):
    """A plug-in with something to tell ``pairbench doctor``.

    A driver without a fixture from a real run reports ``experimental``. The
    image side kind reports the engine found and any leftover containers. A
    machine check reports what the platform lets it do.
    """

    def doctor(self) -> DoctorReport: ...


# ---------------------------------------------------------------------------
# Plug-in group: pairbench.capture_readers
# ---------------------------------------------------------------------------


class CaptureReader(Protocol):
    """Reads captures from a file in some format.

    ``sniff`` says whether the file looks like this reader's format, from its
    path and its first bytes, without reading further. ``read`` returns one
    capture per run in the file and sets each capture's ``source``.

    A reader of a format that has no end record gives each capture a lineup
    record and an end record that says ``complete``, as ``Capture.from_rows``
    does, with sides of kind ``rows``; the analysis then accepts the capture
    without the override for an incomplete one. Rows whose order the format
    did not record have no position. A value that is not a finite number is
    never read into a capture. A value that parses as a number and is zero
    or less is not malformed: its row is kept, and an analysis gives its
    case no verdict.
    """

    name: str
    api_version: int

    def sniff(self, path: Path, head: bytes) -> bool: ...

    def read(self, path: Path) -> list[Capture]: ...


# ---------------------------------------------------------------------------
# Plug-in group: pairbench.gates, and the machine checks that are not plug-ins
# ---------------------------------------------------------------------------


class Gate(Protocol):
    """One machine check.

    ``check`` returns a record whose status is ``pass``, ``fail``,
    ``degraded`` or ``unavailable``. A probe that fails to read counts as
    busy. A check that could not run is ``unavailable`` or ``degraded``,
    never ``pass``. ``detail["message"]`` is a one-line reason that names
    nothing which identifies the machine: no host, no user, no path, no image
    reference and no name of another container. It is what the results show;
    everything else of ``detail`` stays in the capture. The check does not
    decide what its status means under the mode: the runner does.
    """

    @property
    def name(self) -> str: ...

    @property
    def api_version(self) -> int: ...

    def check(self, ctx: GateContext) -> GateRecord:
        """Run the check once and report."""
        ...


class GpuProbe(Protocol):
    """Reads the selected GPUs. A value of ``None`` means the read failed."""

    def compute_processes(self, exclude_pids: Sequence[int] = ()) -> int | None:
        """Count the compute processes on the selected GPUs, leaving out the given ones."""
        ...

    def memory_used_mib(self) -> float | None:
        """Return the memory in use on the selected GPUs, summed, in MiB."""
        ...


class LockSet(Protocol):
    """Advisory file locks held for a run."""

    def release(self) -> None:
        """Release every lock. Safe to call more than once."""
        ...


class WitnessSampler(Protocol):
    """Watches the machine during one launch.

    ``stop`` returns the witness and never raises. ``own_cpu_s`` is the CPU
    time the launch itself used, or ``None`` when the side cannot report it,
    as for an image side and a serving side. The busy-core witness is
    counted one of three ways:

    * in a pinned run with CPUs outside the pinned set: the busy cores
      outside the set, less the tool's own CPU time. ``own_cpu_s`` is not
      needed;
    * otherwise, with ``own_cpu_s``: the busy cores of the machine less it;
    * otherwise, with ``own_cpu_s`` of ``None``: the busy cores of the
      machine with the launch's own load in, named in
      ``Witness.includes_launch``. At or under its threshold the launch is
      not disturbed; above it the launch is undecided (``model.undecided``):
      it does not mark its round as disturbed, and the machine state is not
      quiet.

    Every witness is in one of the states ``Witness`` describes:

    * a value, when it was read;
    * does not apply: the GPU witnesses when no GPU is selected, the cache
      witness when no CPU set is pinned, every witness on a platform that
      has no independent one;
    * probe failed, named in ``Witness.failed``: a counter could not be read,
      or ``own_cpu_s`` is given but is not a finite number at or above zero.

    ``own_pid`` is the first process of the launch, ``LaunchOutcome.pid``. A
    compute process on the selected GPUs that was that process, or descended
    from it, was the launch's own and is not counted among the other compute
    processes. The sampler notes the ancestors of every compute process when
    it sees one, so that it can tell after the launch has ended; the launch
    is never interrupted to ask. With ``own_pid`` of ``None`` every compute
    process seen counts as another one.

    For a serving launch whose server reports its own CPU time, the runner
    adds the CPU time of the load steps it ran itself to the server's before
    it calls ``stop``. A server that reports none, such as one in a
    container, gives ``own_cpu_s`` of ``None``, and the load steps are part
    of the launch's own load counted in. In a pinned run ``own_cpu_s`` is not
    used: load steps that run outside the pinned set count among the busy
    cores outside it.

    ``second_pid`` is ``LaunchOutcome.second_pid``: the first process of the
    second run of a launch that held two runs as two processes. A compute
    process that was it, or descended from it, was the launch's own as well.
    """

    def stop(
        self, own_cpu_s: float | None, own_pid: int | None = None, second_pid: int | None = None
    ) -> Witness: ...


class MachineChecks(Protocol):
    """The machine checks that are services of a run and not plug-ins.

    Required of an implementation:

    * ``cpu_facts`` describes the pinned CPU set, or the machine when nothing
      is pinned. A set that mixes core types is refused with
      ``E_CPUS_MIXED_TYPES`` unless ``allow_mixed``; pinning where it cannot
      be done is refused with ``E_PIN_UNSUPPORTED``;
    * ``gpu_probe`` returns a probe of the selected GPUs, or ``None`` when no
      GPU is selected. A selection that names a GPU the machine does not
      have is refused with ``E_USAGE``, naming the GPUs it has, when those
      can be read;
    * ``acquire_locks`` takes the locks in the order given. An existing file
      is opened read-only; a missing one is created. A timeout or any error
      is refused with ``E_LOCK``;
    * ``start_witness`` begins watching the machine for one launch;
    * ``set_aside`` decides which rounds are disturbed. It hands the
      thresholds and the witnesses to ``pairbench.model.set_aside`` and
      returns its answer unchanged; it sees no measured value;
    * ``leave_pinned`` moves the tool's own process, and with it the sampler
      threads it starts afterwards, onto CPUs outside the pinned set, where
      the platform allows it, so that the tool shares no CPU with a launch.
      It says where the tool went, or why it stayed. It is called once,
      before a sampler thread exists. A launch is pinned to its set by the
      side that starts it and does not take over where the tool runs;
    * ``restore_cpus`` moves the tool's threads back onto the CPUs the
      calling thread had before ``leave_pinned`` moved it, and does nothing
      when it did not move. The runner calls it when the run ends, also when
      the run fails or is interrupted.
    """

    def cpu_facts(self, cpus: str | None, *, allow_mixed: bool) -> CpuFacts: ...

    def leave_pinned(self, cpus: str | None) -> ToolCpus: ...

    def restore_cpus(self) -> None: ...

    def gpu_probe(self, gpus: str | None) -> GpuProbe | None: ...

    def acquire_locks(self, paths: Sequence[str], timeout_s: float) -> LockSet: ...

    def start_witness(self, cpus: str | None, gpus: str | None) -> WitnessSampler: ...

    def set_aside(
        self, thresholds: DiscardThresholds, witnesses: Sequence[RoundWitness]
    ) -> SetAside: ...


# ---------------------------------------------------------------------------
# Plug-in groups: pairbench.rules and pairbench.reporters
# ---------------------------------------------------------------------------


class RuleProvider(Protocol):
    """Provides a named verdict rule."""

    @property
    def name(self) -> str: ...

    @property
    def api_version(self) -> int: ...

    def rule(self) -> Rule:
        """Return the rule."""
        ...


class Reporter(Protocol):
    """Renders a results document as text.

    A reporter reads ``Results`` and, when ``options.diagnostics`` holds one,
    the diagnostics document. It never reads a capture. Every number it
    shows comes from the documents; it computes none. The terminal and the
    markdown reporter show no function name and no shared-object name: of
    the findings they show those of ``Diagnostics.shareable_findings``. The
    reporter ``html`` writes the report page; it may show such names, says
    so at its top when it does, and embeds the chart and flame-graph files
    of ``options.folder``.
    """

    @property
    def name(self) -> str: ...

    @property
    def api_version(self) -> int: ...

    def render(self, results: Results, options: ReportOptions) -> str:
        """Return the report."""
        ...


# ---------------------------------------------------------------------------
# Plug-in group: pairbench.launchers
# ---------------------------------------------------------------------------


class ServerHandle(Protocol):
    """A server that was started for one launch.

    Times are seconds from the start request. ``wait_ready`` polls the
    readiness check and refuses with ``E_LAUNCH_FAILED`` when it does not
    pass in time. ``first_answer`` sends one small request and waits for the
    first non-empty answer. ``stop`` stops and removes the server and writes
    its log to ``server.log`` in the artifact folder. ``wait_released`` waits
    for GPU memory in use to return to within ``tolerance_mib`` of
    ``level_mib`` and refuses with ``E_GPU_NOT_RELEASED`` when it does not.

    A handle may also offer ``exited_during_load() -> int | None``: the exit
    status of a server that exited before its stop, else ``None``. The
    serving side asks it after the load and makes the launch a failed one
    when the server is gone; a handle without it gets no such check.
    """

    @property
    def endpoint(self) -> Endpoint: ...

    def wait_ready(self, ready: Ready) -> float: ...

    def first_answer(self, probe: Probe) -> float: ...

    def stop(self) -> None: ...

    def wait_released(
        self,
        level_mib: float,
        *,
        tolerance_mib: float = GPU_RELEASE_TOLERANCE_MIB,
        timeout_s: float = GPU_RELEASE_WAIT_S,
    ) -> None: ...


class Launcher(Protocol):
    """Starts what a ``ServeSpec`` describes: with docker, with podman, or as a host process.

    ``resolve`` finds the image or the command, applies the pull policy and
    returns the identity: the image ID and the arguments. ``look_up`` reads
    the same identity without changing anything, under the rules
    ``SideKind.look_up`` states; it leaves ``fingerprint`` empty, and the
    serving side kind fills it in. ``start`` starts one server for one launch
    and returns at once; two servers never run at the same time.
    """

    @property
    def name(self) -> str: ...

    @property
    def api_version(self) -> int: ...

    def resolve(self, spec: ServeSpec, ctx: SideContext) -> Mapping[str, Any]: ...

    def look_up(self, spec: ServeSpec, ctx: SideContext) -> SideLookup: ...

    def start(self, spec: ServeSpec, ctx: SideContext, request: LaunchRequest) -> ServerHandle: ...


# ---------------------------------------------------------------------------
# Energy, machine facts and the profiler hook
# ---------------------------------------------------------------------------


class PowerSampler(Protocol):
    """A running power sampler.

    ``stop`` ends the sampling and integrates each window with the trapezoid
    rule over the samples inside it. A window gets no value when the sampler
    is not ok or the window holds fewer power samples than the settings
    require; a value is never estimated from one sample. Energy of several
    GPUs is summed.
    """

    def stop(self, windows: Sequence[Window]) -> EnergyReading: ...


class EnergyMeter(Protocol):
    """Samples GPU power.

    ``idle_power_w`` is the mean over a short window with nothing launched;
    it is recorded and never subtracted. ``start`` begins sampling every
    ``settings.interval_s`` seconds, with timestamps from ``time.monotonic``.
    ``gpus`` is the GPU selection of the launch settings, and ``all`` when
    none is set.
    """

    def idle_power_w(self, gpus: str, settings: EnergySettings) -> float | None: ...

    def start(self, gpus: str, settings: EnergySettings) -> PowerSampler: ...


class Facts(Protocol):
    """Machine and tool facts.

    ``machine_record`` holds nothing that identifies the machine beyond what
    a capture may keep; the CPU identity and cache domains are added by the
    runner from ``CpuFacts``. ``ci`` in the record is ``is_ci(environ)``.
    ``tools`` lists the external programs looked for and which were found.
    """

    def machine_record(
        self, *, gpus: str | None, node_type: str | None, environ: Mapping[str, str]
    ) -> MachineRecord: ...

    def tools(self) -> Sequence[ToolFact]: ...


class Profiler(Protocol):
    """Wraps a command with a profiler the user installed.

    ``find`` returns the program's path, or ``None`` when it is not installed.
    ``wrap`` returns the command to launch and the files it will write under
    ``out``, the folder as the launch sees it. ``licence_note`` is printed on
    first use.
    """

    @property
    def name(self) -> str: ...

    @property
    def licence_note(self) -> str: ...

    def find(self) -> str | None: ...

    def wrap(self, argv: Sequence[str], out: str) -> ProfiledCommand: ...


class Instrument(Protocol):
    """One instrument of the explain step: ``counters``, ``stacks`` or ``pystacks``.

    ``name`` is one of ``pairbench.model.INSTRUMENTS``. ``tool_files`` are
    files of the tool the launch must be able to read: the sampler of
    ``pystacks``, and nothing for the two instruments that use ``perf``.

    ``wrap`` returns the command of the explain launch. ``argv`` is the
    command the side would run: complete and prepared by the driver for a
    side that runs a workload, the command that starts the server for a
    serving side. ``out`` is the launch's artifact folder as the launch sees
    it. ``tools`` maps the file name of each of ``tool_files`` to the path
    under which the launch sees that file. The instrument puts its own
    program in front of the command and points its output at ``out``; it
    changes nothing else of the command.
    """

    @property
    def name(self) -> str: ...

    @property
    def tool_files(self) -> tuple[Path, ...]: ...

    def wrap(
        self, argv: Sequence[str], *, out: str, tools: Mapping[str, str]
    ) -> InstrumentedCommand: ...


class ExplainSession(Protocol):
    """The explain launches of one run. ``pairbench.runner:open_explain`` returns one.

    The session holds the locks the run named from the moment it is opened
    until ``close``. ``command`` and ``launch`` take no lock themselves and
    never raise ``E_LOCK``: a lock that cannot be taken is refused by
    ``OpenExplain``, before a session exists. ``command`` and ``launch``
    resolve a side again the first time it is named, with the side kind of
    the registry, and compare its fingerprint with the one the results
    record: a side that differs is refused with ``E_SIDE_CHANGED``.

    ``command`` returns the complete command a launch of the side runs,
    ``ResolvedSide.command``, or ``None`` for a side that has none, such as a
    serving side. For an image side it is the image's whole command line:
    its entrypoint followed by the side's command, or by the image's default
    command, the words an instrument is put in front of; ``None`` when the
    image names neither.

    ``launch`` runs one untimed launch of the side under an instrument:

    * the launch has the phase ``explain``. It gets no witness, no power
      sampling and no record in a capture, and it is never part of a round.
      Where the run varied the environment size it gets a pad of length 0;
    * for a side that runs a workload, the driver prepares the side's
      command as for a measured launch, the instrument wraps the prepared
      command, and the side runs the result with the instrument's
      ``tool_files``. On an image side the instrument wraps the image's whole
      command line instead (its entrypoint and the prepared command, or its
      default command), handed over through ``LaunchRequest.wrap_server``,
      and runs inside the container in place of the entrypoint;
    * for a serving side, the launcher starts the server under the
      instrument through ``LaunchRequest.wrap_server`` and the load runs at
      the highest load level only. A launcher that cannot start its server
      under another command refuses with ``E_ENGINE_UNSUPPORTED``;
    * a twin and the positive control are never launched;
    * a non-zero exit and a timeout are reported in the answer, not raised.
      A refusal of the side or of the launcher is raised;
      ``instrument_reason`` says which reason of the diagnostics document it
      stands for.

    ``close`` releases the locks and everything the resolved sides hold. It
    is safe to call more than once.
    """

    def command(self, side: str) -> tuple[str, ...] | None: ...

    def launch(self, side: str, instrument: Instrument, artifacts: Path) -> InstrumentedLaunch: ...

    def close(self) -> None: ...


# The reason an instrument was skipped or failed, by the text code of the
# refusal an explain launch raised, or, for ``E_LOCK``, the refusal raised
# when the session was opened. Every other refusal is a failed launch.
EXPLAIN_REFUSALS: Final[Mapping[str, InstrumentReason]] = {
    "E_SIDE_CHANGED": "side_changed",
    "E_ENGINE_UNSUPPORTED": "launcher_cannot",
    "E_LOCK": "lock",
}


def instrument_reason(refusal: Refusal) -> InstrumentReason:
    """Return the reason the diagnostics document records for a refused explain launch.

    ``E_LOCK`` is raised when the session is opened and stands for every
    instrument on every side: each row then says ``lock``.
    """
    return EXPLAIN_REFUSALS.get(refusal.code, "launch_failed")


@dataclass(frozen=True)
class RunServices:
    """Everything the runner composes that is not looked up in the registry."""

    checks: MachineChecks
    meter: EnergyMeter
    facts: Facts
    profiler: Callable[[str], Profiler]


# ---------------------------------------------------------------------------
# The functions behind the Python API
# ---------------------------------------------------------------------------


class BuildPlan(Protocol):
    """``pairbench.plan:build_plan``. Lays out a plan; starts, pulls and writes nothing.

    ``primary_cases`` is the number of primary cases once a warm-up has found
    them; without it the plan is made for one. ``launch_s`` gives the warm-up
    launch time of each side, for the estimate and for a time budget.

    The rows are ``plan_rows(experiment.lineup(), rounds, experiment.control())``:
    the positive control is no part of the lineup, has one row per round at
    the position one past the lineup's length, and changes neither the
    balance nor any round count. ``Plan.control`` names it. ``Plan.launches``
    is ``planned_launches`` and counts one launch per round for the control;
    ``Plan.explain_launches`` is ``experiment.explain_launches()``. The
    estimate counts a launch of the control as two runs of the baseline's
    workload under ``repeat``.
    """

    def __call__(
        self,
        experiment: Experiment,
        *,
        primary_cases: int | None = None,
        launch_s: Mapping[str, float] | None = None,
    ) -> Plan: ...


class RunExperiment(Protocol):
    """``pairbench.runner:run_experiment``. Runs an experiment and writes its capture and plan.

    The returned capture's ``source.path`` is the capture file in the run
    folder. A refusal raised after the capture was opened names the run folder
    in ``refusal.detail["run_dir"]``. ``services`` of ``None`` means
    ``default_services()``.

    An interrupt is turned into a refusal here: the current launch is torn
    down, the end record says ``interrupted``, the locks are released and
    ``E_INTERRUPTED`` is raised, with the run folder named as for any other
    refusal. A failed launch ends the same way with status ``failed`` and
    ``E_LAUNCH_FAILED``.

    When it records a case it sets ``primary`` with
    ``experiment.cases.is_primary(id, driver.default_primary(samples))`` and
    ``group`` with ``experiment.cases.group_of(id)``. A case first seen after
    the warm-up is secondary.

    An experiment whose sides are result files is accepted here: nothing is
    launched and there are no twins, warm-ups, machine checks, locks,
    witnesses or positions. Round ``r`` reads the ``r``-th file of every
    side through ``Driver.read`` with ``ctx.result_file``. Sides that hold
    different numbers of files are refused with ``E_USAGE``. The capture is
    written as for any run, and no plan table is.

    Cases. What ``Driver.read`` returned is checked with
    ``refuse_reserved_cases``. Every measured launch of a side or a twin
    also gives the cases of ``resource_samples``; each resource case a
    launch did not give is named once per run in a loud note,
    ``NOTE_RESOURCE_FIGURE_MISSING``. A case is recorded with ``case_of``.

    The positive control. When ``experiment.control()`` gives an entry, the
    runner asks ``ResolvedSide.cannot_repeat`` of the baseline before it
    writes the lineup record, unless the control doubles the work by
    ``factor``. A reason means the control does not run: no side record, no
    row and no launch for it, ``control`` of the lineup record is null, and
    a loud note, ``NOTE_CONTROL_CANNOT_REPEAT``, carries the reason.
    Otherwise the entry gets a side record with the role ``control``, is
    named under ``control`` of the lineup record and is launched last in
    every round, at the position one past the lineup's length. It gets no
    warm-up launch and no resource cases.

    * under ``repeat`` one launch holds two runs: the runner makes the two
      folders of ``run_folders(artifacts, resolved.artifacts_in_side(artifacts))``,
      the driver prepares the baseline's command twice, each with the
      ``DriverContext`` of its own run, the side runs both in one start
      (``LaunchRequest.second``), the driver reads each run from its
      folder, and the cases are those of ``combine_runs`` with
      ``clock_cases(driver)``. A case only one of the two runs gave
      (``uncombined_cases``) is named once per run in a loud note,
      ``NOTE_CONTROL_CASE_MISSING``. For a serving side the load callback runs the
      load twice against the one server start and the cases are combined
      the same way. The launch record carries ``runs`` of 2;
    * under ``factor`` the launch runs the workload once with
      ``work_factor_env()`` added to its environment; the cases are those of
      ``control_samples``, taken as read, and the launch record carries
      ``runs`` of 1.

    The cost of a launch. After the warm-up launches, when
    ``launch_cost_side`` finds a side and ``launch_cost.launches`` is above
    zero, the empty command ``EMPTY_COMMAND`` is launched that many times
    through that side's launch path, with the phase ``cost``. The times are
    the ``run_s`` of those launches; the capture gets one ``launch_cost``
    record, ``LaunchCost.of``. The empty launches are no launch records and
    are not counted in the plan. An empty command that cannot be found
    skips the measurement with a loud note, ``NOTE_LAUNCH_COST_NOT_MEASURED``.

    The environment size. With ``run.vary_env_size`` every launch gets
    ``env_pad(length)`` in its environment and its record carries the
    length: ``env_pad_length(seed, round)`` for every entry of a round, the
    control included, and 0 for a warm-up. The seed is ``DEFAULT_SEED``; it
    is written under ``seeds`` of the header with the key ``SEED_ENV_PAD``,
    beside the seed of the load tools under ``SEED_DRIVER``. Without the
    setting no launch gets the variable and ``env_pad`` of a launch record
    is null.

    Where the tool runs. Before the machine record is written the runner
    calls ``MachineChecks.leave_pinned`` with the pinned CPU set and writes
    the CPUs the tool moved to into ``tool_cpus`` of the machine record. A
    set that leaves no CPU outside it, or a platform that does not let the
    tool move, is a loud note, ``NOTE_TOOL_ON_PINNED_CPUS``. When the run
    ends, whether it completes, fails or is interrupted, the runner calls
    ``MachineChecks.restore_cpus``.
    """

    def __call__(
        self,
        experiment: Experiment,
        *,
        out: Path | None = None,
        services: RunServices | None = None,
    ) -> Capture: ...


class AnalyseCaptures(Protocol):
    """``pairbench.stats.analyse:analyse_captures``. Builds the whole results document
    from captures, except ``figures``, ``plugins`` and ``artifacts``. Every
    refusal of a whole analysis is raised here, the pooling refusals included.

    A capture is incomplete when ``Capture.complete`` is false: it has no end
    record, or its end record says ``failed`` or ``interrupted``. ``run.command``
    is ``pairbench.model.public_command`` of the recorded command line and
    nothing else.

    The analysis also judges the positive control and fills
    ``controls.positive``. Its inputs are all in the capture: the control
    entry is ``Capture.control``, the side record whose ``control_of`` names
    the baseline; the tolerance and how the work was doubled are
    ``Capture.control_settings()``; the expected ratio of a case is
    ``control_expected``, the tolerance test ``control_within``, and the
    direction is tested with the uncorrected sign test at the rule's alpha.
    The control is no lineup entry, no compared pair and no part of the
    correction family. A failed control gives every comparison no verdict
    with the reason ``positive_control_failed`` and a loud note.

    A case whose ``better`` is ``none`` is graded like every secondary case
    and gets the outcome ``direction_outcome`` gives.

    From the capture come as well: ``launch_cost`` (the capture's record,
    unchanged), the launch-cost note for every ``wall`` case of a side whose
    kind is in ``LAUNCH_COST_KINDS`` that ``launch_cost_note`` selects, with
    the recorded share ``Capture.launch_cost_share()``; ``env_pad``
    (``Capture.env_pad()``); ``series``, the values of every primary case
    per lineup entry and round with the disturbed rounds;
    ``plan.launches``, the launches the capture records, and
    ``plan.explain_launches`` (``Capture.explain_launches()``).
    ``diagnostics`` and ``plots`` stay at their defaults, which say ``off``:
    a run sets them when it writes its results."""

    def __call__(
        self,
        captures: Sequence[Capture],
        *,
        rule: Rule,
        baseline: str | None = None,
        floors: Floors | None = None,
        allow_incomplete: bool = False,
        allow_mixed_machines: bool = False,
        assume_interleaved: bool = False,
    ) -> Results: ...


class RefusedResults(Protocol):
    """``pairbench.stats.analyse:refused``. Builds the results document of a refused run
    or analysis: every part that describes the captures, no comparison, and the
    refusal listed. It raises for no capture a reader could load."""

    def __call__(self, captures: Sequence[Capture], refusal: Refusal, *, rule: Rule) -> Results: ...


class WithFigures(Protocol):
    """``pairbench.results.figures:with_figures``. Returns the results with ``figures`` filled."""

    def __call__(self, results: Results) -> Results: ...


class ReadResults(Protocol):
    """``pairbench.results.writer:read_results``. Reads a results document from a file."""

    def __call__(self, path: Path) -> Results: ...


class FillText(Protocol):
    """``pairbench.report.fill:fill_text``. Fills the figure tokens of a template text.

    ``results`` maps a results name to its document; the empty name serves
    tokens that carry no name.
    """

    def __call__(self, template: str, results: Mapping[str, Results]) -> str: ...


class CliMain(Protocol):
    """``pairbench.cli.main:main``. Runs the command line and returns the exit code.

    ``argv`` of ``None`` means the arguments of the process. It never calls
    ``sys.exit`` itself.
    """

    def __call__(self, argv: Sequence[str] | None = None) -> int: ...


# ---------------------------------------------------------------------------
# The functions the command line and the tool server call beside the Python API
# ---------------------------------------------------------------------------


class FormatPlan(Protocol):
    """``pairbench.plan:format_plan``. Returns the text the plan command prints.

    A header, then the table of ``Plan.to_tsv``. The header names the lineup,
    the rounds requested and planned, the launches, the balance of every
    pair, whether a verdict is reachable and how many rounds must agree, the
    largest number of primary cases the round count still holds for, the
    estimated duration when known, what the sides differ in, and, from
    ``lookups``, each side's identity or why it was not read. It also names
    the positive control with what it costs, in launches and in estimated
    time, and how to turn it off, and the explain launches with their
    estimated time and how to turn them off. The table holds one row per
    round for the control.
    """

    def __call__(
        self,
        plan: Plan,
        experiment: Experiment,
        *,
        lookups: Mapping[str, SideLookup] | None = None,
    ) -> str: ...


class LookUpSides(Protocol):
    """``pairbench.runner:look_up_sides``. The checks of the plan command.

    Runs the static checks a run starts with, then ``SideKind.look_up`` for
    every side, twins left out, and returns the look-ups by side name in the
    order of the sides. It starts no container, pulls nothing, creates no
    directory and takes no lock. It refuses what ``SideKind.look_up``
    refuses; a side kind that is not known, a ``cmd`` side without
    ``{workload}`` beside a shared workload and a ``file`` side with
    ``E_USAGE``; a working folder of a side that runs on the host that
    does not exist with ``E_SIDE_UNRESOLVED``; and, unless identical sides
    are allowed, with ``E_SAME_SIDE`` two sides that declare the same kind,
    spec and effective launch settings, or whose look-ups carry equal
    fingerprints and that run in the same working folder. The refusal of a
    ``file`` side belongs to this function alone and not to the checks it
    shares with a run, which accepts file sides. ``environ`` of ``None``
    means the environment of the process.
    """

    def __call__(
        self, experiment: Experiment, *, environ: Mapping[str, str] | None = None
    ) -> dict[str, SideLookup]: ...


class RecordProfiles(Protocol):
    """``pairbench.runner:record_profiles``. One extra, untimed launch per side under a profiler.

    ``run_dir`` is a run folder; its capture gives the experiment. ``tool``
    names a GPU profiler, ``nsys`` or ``ncu``. ``case`` is the case the
    command was asked about, or ``None`` when it named none. ``side``
    limits the work to one side. The profiler's output goes under
    ``profiles/`` in the run folder; the paths are returned relative to the
    run folder. A profiler that is not installed is refused with
    ``E_PROFILER_MISSING``. The tool ``perf`` is not served here:
    ``PROFILE_TOOLS`` sends it to ``RecordStacks``, which is called in the
    same way: ``delegate(PROFILE_TOOLS[tool])(run_dir, tool=tool, case=case,
    side=side)``.
    """

    def __call__(
        self,
        run_dir: Path,
        *,
        tool: str,
        case: str | None = None,
        side: str | None = None,
        services: RunServices | None = None,
    ) -> tuple[str, ...]: ...


class WriteResults(Protocol):
    """``pairbench.results.writer:write_results``. Writes ``results.json`` and ``results.md``.

    Sets ``capture``, ``plan`` and ``markdown`` of ``artifacts`` to the files
    of the run folder that exist: the capture, the plan and the markdown
    report it writes. ``html``, ``diagnostics`` and ``charts`` stay as the
    results name them. ``profiles`` of ``None`` keeps the ones the results
    already name. Returns the results as written.

    Each of the two files is written whole under another name in the same
    folder and then put in place of the final name in one step, so a reader
    never finds half a document and a second write replaces the first. A
    run writes its results twice: see ``RunToEnd``.
    """

    def __call__(
        self, results: Results, folder: Path, *, profiles: Sequence[str] | None = None
    ) -> Results: ...


class OpenExplain(Protocol):
    """``pairbench.runner:open_explain``. Opens the explain launches of a run.

    It takes the locks ``experiment.gates.locks`` names, in the order given
    and with ``gates.lock_timeout_s``, and returns the session; a lock that
    cannot be taken is refused with ``E_LOCK`` and nothing is launched.
    ``fingerprints`` maps the name of each subject and of the baseline to
    the fingerprint the results record for it. ``run_id`` is the id of the
    run, for the names of containers. ``note`` receives loud notes.
    ``services`` of ``None`` means ``default_services()``. What the session
    does is stated on ``ExplainSession``.

    This is the one way the diagnostics part reaches a side: it imports no
    side kind, no driver, no machine check and no energy code.
    """

    def __call__(
        self,
        experiment: Experiment,
        *,
        run_id: str,
        fingerprints: Mapping[str, str],
        note: Notify = no_notes,
        services: RunServices | None = None,
    ) -> ExplainSession: ...


class ExplainRun(Protocol):
    """``pairbench.diagnose.explain:explain_run``. Runs the explain step of one run.

    ``results`` is the analysed run and ``out`` its run folder. The step
    launches each subject and the baseline again under the instruments,
    through the session of ``OpenExplain``, and never a twin or the positive
    control. It writes ``diagnostics.json`` and the files under
    ``profiles/`` into ``out`` and returns the document. The resource rows
    and the findings made from them come from ``results`` and need no
    launch, so a document is written also when no instrument could run.

    An instrument that cannot run on a side is skipped: its row in
    ``instruments`` says why, and ``InstrumentRun.note`` is added to
    ``notes`` of the document. Nothing is printed here: ``pairbench.explain``
    prints every note of the document on standard error.

    A lock that cannot be taken skips every launch of the step. The
    ``E_LOCK`` that ``OpenExplain`` raised is not passed on: the document is
    written all the same, with the resource rows and their findings, and
    with one row per subject and baseline for ``counters`` and for
    ``stacks`` that says ``skipped`` with the reason ``lock`` and no exit
    code. In place of a note per row the document holds one note with the
    code ``pairbench.model.NOTE_EXPLAIN_SKIPPED``. ``Diagnostics.state()``
    of that document says ``skipped`` with ``lock``. The step changes no
    comparison and no exit code.
    """

    def __call__(self, experiment: Experiment, results: Results, *, out: Path) -> Diagnostics: ...


class ReadDiagnostics(Protocol):
    """``pairbench.diagnose.document:read_diagnostics``. Reads a diagnostics document
    from a file, with ``Diagnostics.from_json``."""

    def __call__(self, path: Path) -> Diagnostics: ...


class RecordStacks(Protocol):
    """``pairbench.diagnose.explain:record_stacks``. What ``pairbench profile --tool perf`` does.

    ``run_dir`` is a run folder; its capture gives the experiment. It
    records stacks with the ``stacks`` instrument alone, for the side named
    or for each subject and the baseline, and writes the folded files and
    the flame graphs under ``profiles/`` as the explain step does. The paths
    are returned relative to the run folder. ``tool`` is ``perf``, as the
    command was given it; another name is refused with ``E_USAGE``. ``case``
    is accepted for the command's flag and selects nothing: stacks cover a
    whole launch. Because a tool was asked for, a ``perf`` that is not
    installed is refused with ``E_PROFILER_MISSING`` where the explain step
    would skip. The call has the shape of ``RecordProfiles``, so the command
    calls either through ``PROFILE_TOOLS`` in one way.
    """

    def __call__(
        self,
        run_dir: Path,
        *,
        tool: str = "perf",
        case: str | None = None,
        side: str | None = None,
    ) -> tuple[str, ...]: ...


class InstrumentReports(Protocol):
    """``pairbench.diagnose.instruments:doctor_reports``. What each instrument of the
    explain step can do on this machine, by instrument name, for ``pairbench doctor``.

    An instrument that can run reports ``ok``. One that cannot reports
    ``unavailable`` and says why in one line: its program is not installed,
    or the system forbids it, and then the line names the setting or the
    capability that forbids it. Nothing is launched and no setting of the
    system is changed.
    """

    def __call__(self, environ: Mapping[str, str] | None = None) -> Mapping[str, DoctorReport]: ...


class DrawCharts(Protocol):
    """``pairbench.charts:draw_charts``. Draws the charts of a run into ``out``.

    It reads the results document and, when given, the diagnostics
    document, and never a capture. It returns the paths of the files it
    drew, in the order verdict, rounds per case, noise, resources. Without
    the ``plot`` extra it draws nothing, returns an empty list and says so
    through ``note``. At most ``max_round_charts`` round-by-round charts are
    drawn, in the order of the results; how many were left out is a note,
    and so is a chart whose data is absent. The module the extra provides
    is imported only inside the functions that draw.
    """

    def __call__(
        self,
        results: Results,
        *,
        out: Path,
        diagnostics: Diagnostics | None = None,
        max_round_charts: int = 12,
        note: Notify = no_notes,
    ) -> list[Path]: ...


class FindingsText(Protocol):
    """``pairbench.report.terminal:findings_text``. The lines a run prints after the
    explain step: the findings made from resource figures and counters alone,
    one sentence each, and where the full diagnostics are. It holds no
    function name and no shared-object name."""

    def __call__(self, diagnostics: Diagnostics) -> str: ...


class RunToEnd(Protocol):
    """``pairbench.cli.run:run_to_end``. Everything the ``run`` command does for one
    experiment, from the first launch to the report page. It returns the exit code.
    The tool server calls this same function.

    The sequence, composed from the functions of the Python API:

    1. ``require_plot_extra(experiment.plots.mode)``, then ``pairbench.run``.
       The capture is complete when it returns; nothing later is written
       into it.
    2. ``pairbench.analyse``. This and the outcomes named to fail on fix the
       exit code. No later step changes it; only an interrupt does.
    3. ``write_results`` with ``Results.pending()``: the explain step and
       the charts say ``pending``. The terminal report is printed.
    4. ``pairbench.explain`` when ``explain.mode`` says so: ``always``, or
       ``auto`` with ``Results.has_difference()``. The findings are printed
       (``FindingsText``).
    5. ``pairbench.draw`` unless ``plots.mode`` is ``off``.
    6. ``write_results`` with ``Results.finished(...)``: the final state of
       both steps, their notes and the final list of files. Nothing else
       differs from the first write: ``second_write_changes`` names what
       does. With ``run.json`` this document is printed on standard output.
    7. ``render(results, "html", diagnostics=..., folder=...)`` is written to
       ``report.html`` when ``report.html`` is set.

    The state of the explain step: ``off`` under mode ``off``; ``skipped``
    with ``mode_auto_no_difference`` under ``auto`` without a difference;
    ``Diagnostics.state()`` when a document came back, which says
    ``written``, or ``skipped`` with ``lock`` or with ``no_instrument``;
    ``failed`` for any failure. The state of the charts: ``off`` under mode
    ``off``; ``drawn`` when files came back; ``not_drawn`` with
    ``extra_missing`` when the extra is absent, and with ``failed`` when
    drawing failed.

    A failure in step 4, 5 or 7 is a loud note and never fails the run: the
    codes are ``NOTE_EXPLAIN_FAILED``, ``NOTE_CHARTS_FAILED`` and
    ``NOTE_PAGE_FAILED`` of the model. An interrupt during steps 4 to 7
    stops them, and the exit code is 130. The results are then written once
    more, by replacing the files as in step 6: a step that had finished
    keeps its final state, its notes and its files, and a state that still
    said ``pending`` says ``interrupted`` (``Results.interrupted()``).
    Nothing else differs from the first write, and no report page is
    written after an interrupt.
    """

    def __call__(self, experiment: Experiment) -> int: ...


class ControlResult(Protocol):
    """The result of one self-test control: its id such as ``K1`` or ``C12``, a
    one-line title, whether it passed, and what was expected and found."""

    @property
    def id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def passed(self) -> bool: ...

    @property
    def detail(self) -> str: ...


class RunSelftest(Protocol):
    """``pairbench.stats.selftest:run_selftest``. Runs every control and returns one
    result per control, in the order of ``selftest.CONTROLS``. It never raises for
    a control that fails."""

    def __call__(self) -> Sequence[ControlResult]: ...


class LoadExperiment(Protocol):
    """``pairbench.config:load_experiment``. Builds the experiment from every source.

    Precedence: ``flags`` and ``sets``, then the environment, then the file,
    then the defaults. ``path`` of ``None`` means the file ``PAIRBENCH_CONFIG``
    names, or no file. ``flags`` is a config-shaped dict made from command-line
    flags. ``sets`` are ``KEY=VALUE`` texts as written after ``--set``; each
    key is checked with ``match_config_key`` and each value is read as a TOML
    value when it parses as one and as text otherwise. A key named by a flag
    and by ``--set`` with different values is refused with ``E_USAGE``; an
    unknown key or a bad value with ``E_CONFIG``.
    """

    def __call__(
        self,
        path: Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        flags: Mapping[str, Any] | None = None,
        sets: Sequence[str] = (),
    ) -> Experiment: ...


class CollectDoctor(Protocol):
    """``pairbench.cli.doctor:collect``. Returns the document ``pairbench doctor --json``
    prints: what this machine supports, which external programs are found, what
    is degraded, the plug-ins that failed to load and leftover containers. It
    also says which instruments of the explain step can run here
    (``InstrumentReports``); where one is forbidden, the setting or the
    capability that forbids it is named."""

    def __call__(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# The services of a run and where each comes from
# ---------------------------------------------------------------------------


class MakeMachineChecks(Protocol):
    """``pairbench.gates.base:machine_checks``."""

    def __call__(self) -> MachineChecks: ...


class MakeEnergyMeter(Protocol):
    """``pairbench.energy.sampler:energy_meter``. The meter reads the GPU management
    library when the ``gpu`` extra is installed and one long-running query
    process otherwise."""

    def __call__(self) -> EnergyMeter: ...


class MakeFacts(Protocol):
    """``pairbench.provenance:facts``."""

    def __call__(self) -> Facts: ...


class MakeProfiler(Protocol):
    """``pairbench.profile.nsight:profiler``. ``tool`` is ``nsys`` or ``ncu``, a GPU
    profiler; another name is refused with ``E_USAGE``."""

    def __call__(self, tool: str) -> Profiler: ...


# The function behind each part of the Python API, and each function another
# part of the package provides to the runner, the command line or the tool
# server: module, name, signature.
DELEGATES: Final[Mapping[str, tuple[str, str, type]]] = {
    "plan": ("pairbench.plan", "build_plan", BuildPlan),
    "run": ("pairbench.runner", "run_experiment", RunExperiment),
    "analyse": ("pairbench.stats.analyse", "analyse_captures", AnalyseCaptures),
    "refused": ("pairbench.stats.analyse", "refused", RefusedResults),
    "figures": ("pairbench.results.figures", "with_figures", WithFigures),
    "load_results": ("pairbench.results.writer", "read_results", ReadResults),
    "fill": ("pairbench.report.fill", "fill_text", FillText),
    "main": ("pairbench.cli.main", "main", CliMain),
    "format_plan": ("pairbench.plan", "format_plan", FormatPlan),
    "look_up": ("pairbench.runner", "look_up_sides", LookUpSides),
    "profile": ("pairbench.runner", "record_profiles", RecordProfiles),
    "write_results": ("pairbench.results.writer", "write_results", WriteResults),
    "selftest": ("pairbench.stats.selftest", "run_selftest", RunSelftest),
    "load_experiment": ("pairbench.config", "load_experiment", LoadExperiment),
    "doctor": ("pairbench.cli.doctor", "collect", CollectDoctor),
    "checks": ("pairbench.gates.base", "machine_checks", MakeMachineChecks),
    "meter": ("pairbench.energy.sampler", "energy_meter", MakeEnergyMeter),
    "facts": ("pairbench.provenance", "facts", MakeFacts),
    "profiler": ("pairbench.profile.nsight", "profiler", MakeProfiler),
    "explain": ("pairbench.diagnose.explain", "explain_run", ExplainRun),
    "open_explain": ("pairbench.runner", "open_explain", OpenExplain),
    "load_diagnostics": ("pairbench.diagnose.document", "read_diagnostics", ReadDiagnostics),
    "record_stacks": ("pairbench.diagnose.explain", "record_stacks", RecordStacks),
    "instruments": ("pairbench.diagnose.instruments", "doctor_reports", InstrumentReports),
    "draw": ("pairbench.charts", "draw_charts", DrawCharts),
    "findings": ("pairbench.report.terminal", "findings_text", FindingsText),
    "run_to_end": ("pairbench.cli.run", "run_to_end", RunToEnd),
}

# The part of ``DELEGATES`` that serves each tool of ``pairbench profile``:
# a GPU profiler is recorded by the runner, ``perf`` by the diagnostics part.
PROFILE_TOOLS: Final[Mapping[str, str]] = {
    "nsys": "profile",
    "ncu": "profile",
    "perf": "record_stacks",
}


def delegate(part: str) -> Any:
    """Import and return the function ``DELEGATES`` names for a part."""
    module, name, _contract = DELEGATES[part]
    return getattr(importlib.import_module(module), name)


def default_services() -> RunServices:
    """Build the services of a run from the modules that provide them."""
    make_checks: MakeMachineChecks = delegate("checks")
    make_meter: MakeEnergyMeter = delegate("meter")
    make_facts: MakeFacts = delegate("facts")
    make_profiler: MakeProfiler = delegate("profiler")
    return RunServices(
        checks=make_checks(), meter=make_meter(), facts=make_facts(), profiler=make_profiler
    )


PROTOCOLS: Final[Mapping[str, type]] = {
    GROUP_SIDE_KINDS: SideKind,
    GROUP_DRIVERS: Driver,
    GROUP_CAPTURE_READERS: CaptureReader,
    GROUP_GATES: Gate,
    GROUP_RULES: RuleProvider,
    GROUP_REPORTERS: Reporter,
    GROUP_LAUNCHERS: Launcher,
}

# The methods a plug-in of each group must have.
REQUIRED_METHODS: Final[Mapping[str, tuple[str, ...]]] = {
    GROUP_SIDE_KINDS: ("resolve", "look_up"),
    GROUP_DRIVERS: ("prepare", "read", "default_primary"),
    GROUP_CAPTURE_READERS: ("sniff", "read"),
    GROUP_GATES: ("check",),
    GROUP_RULES: ("rule",),
    GROUP_REPORTERS: ("render",),
    GROUP_LAUNCHERS: ("resolve", "look_up", "start"),
}
