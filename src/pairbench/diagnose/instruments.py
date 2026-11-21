# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The three instruments of the explain step, and what each can do on this machine.

* ``counters``: ``perf stat`` counts the events of ``COUNTER_EVENTS`` for the
  whole launch and writes them in its machine-readable form (``-x``).
* ``stacks``: ``perf record`` samples call stacks; ``perf script`` and
  ``perf buildid-list`` read the recording back inside the same launch, where
  the side's binaries and the symbol maps of the process are.
* ``pystacks``: the sampler of ``pysampler.py`` runs the workload of a side
  whose command starts with a Python interpreter, on that interpreter.

Each instrument is the command that wraps a launch, and each output has a
reader here. The formats of ``perf`` were read from its public
documentation, Linux v6.12:

* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/Documentation/perf-stat.txt
  (``-x SEP``: one line per event, the fields being the count, the unit, the
  event, the run time of the counter, the share of that time it counted,
  and an optional metric; ``<not counted>`` or ``<not supported>`` in place
  of a count the machine did not give);
* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/Documentation/perf-record.txt
  (``-F``, ``--call-graph fp|dwarf|lbr``, ``--buildid-all``);
* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/Documentation/perf-script.txt
  and perf-buildid-list.txt (read by ``pairbench.diagnose.folded``);
* https://raw.githubusercontent.com/torvalds/linux/v6.12/tools/perf/util/evsel.c
  (``evsel__open_strerror``: the message when the kernel setting forbids an
  event) and tools/perf/builtin-stat.c (``-o`` writes its first line,
  ``# started on``, before any event is opened).

A machine with more than one kind of CPU core prints one line per core type
for an event, such as ``armv8_pmuv3_0/instructions/``: the counts of those
lines add up to the event's count, and a line ``<not counted>`` is a core
type the launch did not run on. An event is left out, and named, only when
no line of it was counted.

Whether ``perf`` may run is told without guessing and without changing any
setting. Not installed: no ``perf`` on ``PATH``. Not permitted: the kernel
setting ``perf_event_paranoid`` lies above 2, the highest level the kernel
documents for a process watching its own children
(https://raw.githubusercontent.com/torvalds/linux/v6.12/Documentation/admin-guide/perf-security.rst
and Documentation/admin-guide/sysctl/kernel.rst), and the process holds
neither ``CAP_PERFMON`` nor ``CAP_SYS_ADMIN`` and is not root; after a
launch, ``perf``'s own message names that setting. Not in the image: a launch
in a container exits with 127, the code of a command that is not found, and
left no output. No capability: an image side whose launch setting
``perf_counters`` is off. CPython reports Python function names to ``perf``
when the variable ``PYTHONPERFSUPPORT`` is set, from Python 3.12 on
(https://docs.python.org/3.13/howto/perf_profiling.html); the ``stacks``
launch sets it.
"""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pairbench.api import (
    ARTIFACT_SERVER_LOG,
    ARTIFACT_STDERR,
    DoctorReport,
    InstrumentedCommand,
    InstrumentedLaunch,
)
from pairbench.diagnose import pysampler
from pairbench.errors import Refusal
from pairbench.model import (
    COUNTER_EVENTS,
    INSTRUMENT_REASON_WORDS,
    InstrumentReason,
    InstrumentStatus,
    starts_with_python,
)

STAT_OUTPUT: Final = "perf-stat.txt"
SCRIPT_OUTPUT: Final = "perf-script.txt"
BUILDIDS_OUTPUT: Final = "perf-buildids.txt"
RECORD_DATA: Final = "perf.data"
SCRIPT_FIELDS: Final = "comm,pid,tid,time,event,ip,sym,dso"
SEPARATOR: Final = ";"
PERF_SUPPORT_VARIABLE: Final = "PYTHONPERFSUPPORT"
SAMPLER_FILE: Final = Path(pysampler.__file__)
# The exit code of a shell, or of a container engine, for a command it cannot find.
EXIT_NOT_FOUND: Final = 127
# Part of the message perf prints when the kernel setting forbids opening an
# event (tools/perf/util/evsel.c, evsel__open_strerror). Its warning about
# restricted kernel addresses names the setting too, but not in these words.
PERF_REFUSED: Final = "perf_event_paranoid setting is"
# The highest level of perf_event_paranoid the kernel documents as letting a
# process watch its own children without a capability.
PARANOID_HIGHEST_OPEN: Final = 2
CAP_SYS_ADMIN: Final = 21
CAP_PERFMON: Final = 38
# The root of the process file system, read for the kernel setting and the capabilities.
PROC: Path = Path("/proc")

Place = Literal["host", "container", "unknown"]


def _join(folder: str, name: str) -> str:
    return folder.rstrip("/") + "/" + name


@dataclass(frozen=True)
class Counters:
    """``counters``: ``perf stat`` around the launch, its counts written to ``perf-stat.txt``."""

    name: str = "counters"

    @property
    def tool_files(self) -> tuple[Path, ...]:
        return ()

    def wrap(
        self, argv: Sequence[str], *, out: str, tools: Mapping[str, str]
    ) -> InstrumentedCommand:
        command = (
            "perf",
            "stat",
            "-x",
            SEPARATOR,
            "-o",
            _join(out, STAT_OUTPUT),
            "-e",
            ",".join(COUNTER_EVENTS),
            "--",
            *argv,
        )
        return InstrumentedCommand(argv=command, outputs=(STAT_OUTPUT,))


# The shell script of the ``stacks`` launch. Its arguments are the output
# folder, the sampling rate, the call-graph mode and then the command, so no
# part of the command is ever written into the script's text. The files that
# hold what ``perf script`` and ``perf buildid-list`` print are created
# readable and writable by their owner only: the umask is set after the
# command has run, so the command keeps its own.
STACKS_SCRIPT: Final = (
    "out=$1; hz=$2; graph=$3; shift 3; "
    'perf record -F "$hz" --call-graph "$graph" --buildid-all -o "$out/perf.data" -- "$@"; '
    "rc=$?; "
    'if [ -s "$out/perf.data" ]; then '
    "umask 077; "
    f'perf script -i "$out/perf.data" -F {SCRIPT_FIELDS} > "$out/{SCRIPT_OUTPUT}" '
    '2> "$out/perf-script.err"; '
    f'perf buildid-list -i "$out/perf.data" > "$out/{BUILDIDS_OUTPUT}" 2> /dev/null; '
    'rm -f "$out/perf.data"; '
    "fi; "
    'exit "$rc"'
)


@dataclass(frozen=True)
class Stacks:
    """``stacks``: ``perf record`` with call graphs, read back with ``perf script``.

    ``hz`` is the number of samples per second and ``call_graph`` how call
    graphs are collected (``explain.sample_hz``, ``explain.call_graph``).
    The recording itself is removed once it has been read back.
    """

    hz: int = 99
    call_graph: str = "fp"
    name: str = "stacks"

    @property
    def tool_files(self) -> tuple[Path, ...]:
        return ()

    def wrap(
        self, argv: Sequence[str], *, out: str, tools: Mapping[str, str]
    ) -> InstrumentedCommand:
        command = (
            "sh",
            "-c",
            STACKS_SCRIPT,
            "pairbench-stacks",
            out,
            str(self.hz),
            self.call_graph,
            *argv,
        )
        return InstrumentedCommand(
            argv=command,
            env={PERF_SUPPORT_VARIABLE: "1"},
            outputs=(SCRIPT_OUTPUT, BUILDIDS_OUTPUT),
        )


# Interpreter options that take a value in the next word, and the long one that does.
_OPTIONS_WITH_VALUE: Final = frozenset("WX")
_LONG_WITH_VALUE: Final = frozenset({"--check-hash-based-pycs"})


def split_interpreter(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split a Python command into the interpreter with its options and the program.

    The program starts at the script, at ``-m`` or ``-c`` (with or without
    its value attached), or at ``-``. Options may be combined (``-OO``,
    ``-uB``); ``-W`` and ``-X`` take a value, attached or in the next word.
    """
    head = [argv[0]] if argv else []
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "-" or not word.startswith("-"):
            return head, list(argv[index:])
        if word.startswith("--"):
            head.append(word)
            if word in _LONG_WITH_VALUE and index + 1 < len(argv):
                head.append(argv[index + 1])
                index += 1
            index += 1
            continue
        for position in range(1, len(word)):
            letter = word[position]
            if letter in "cm":
                flags = word[:position]
                if flags != "-":
                    head.append(flags)
                return head, ["-" + word[position:], *argv[index + 1 :]]
            if letter in _OPTIONS_WITH_VALUE:
                if position + 1 == len(word) and index + 1 < len(argv):
                    head.extend((word, argv[index + 1]))
                    index += 1
                else:
                    head.append(word)
                break
        else:
            head.append(word)
        index += 1
    return head, []


@dataclass(frozen=True)
class PyStacks:
    """``pystacks``: the sampler of pairbench runs the workload on the side's own interpreter.

    The command keeps the interpreter and its options and puts the sampler
    in front of the program.
    """

    hz: int = 99
    name: str = "pystacks"

    @property
    def tool_files(self) -> tuple[Path, ...]:
        return (SAMPLER_FILE,)

    def wrap(
        self, argv: Sequence[str], *, out: str, tools: Mapping[str, str]
    ) -> InstrumentedCommand:
        """Put the sampler in front of the program, or refuse a command that is not Python's.

        The command the launch would run is refused with
        ``E_ENGINE_UNSUPPORTED`` when it does not start with a Python
        interpreter, for example when the driver put its own program first.
        """
        if not starts_with_python(argv):
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                "the sampler of pystacks runs only a command that starts with a Python interpreter",
            )
        head, program = split_interpreter(argv)
        sampler = tools.get(SAMPLER_FILE.name, str(SAMPLER_FILE))
        command = (*head, sampler, "--out", out, "--hz", str(self.hz), "--", *program)
        return InstrumentedCommand(
            argv=command, outputs=(pysampler.FOLDED_OUTPUT, pysampler.TOO_OLD_OUTPUT)
        )


counters: Final = Counters()
stacks: Final = Stacks()
pystacks: Final = PyStacks()


# ---------------------------------------------------------------------------
# Reading what perf stat wrote
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterReading:
    """The counts of one ``counters`` launch.

    ``values`` maps each counted event to its count, added up over the
    lines of every core type that counted it. ``not_counted`` names, in the
    order of ``COUNTER_EVENTS``, each event no line of which was counted.
    """

    values: Mapping[str, float]
    not_counted: tuple[str, ...]


def event_name(printed: str) -> str:
    """Return the event a line of ``perf stat`` names, without its core type and modifiers.

    ``armv8_pmuv3_1/instructions/`` and ``instructions:u`` both name
    ``instructions``.
    """
    name = printed.strip()
    if "/" in name:
        parts = name.split("/")
        name = parts[1] if len(parts) > 1 and parts[1] else parts[0]
    return name.split(":")[0]


def read_counters(text: str) -> CounterReading:
    """Read what ``perf stat -x ';'`` wrote.

    A count that is no finite number is not counted, and neither is an event
    whose counts add up past the largest number.
    """
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split(SEPARATOR)
        if len(fields) < 3:
            continue
        try:
            count = float(fields[0])
        except ValueError:
            continue
        if not math.isfinite(count):
            continue
        event = event_name(fields[2])
        values[event] = values.get(event, 0.0) + count
    values = {event: value for event, value in values.items() if math.isfinite(value)}
    missing = tuple(event for event in COUNTER_EVENTS if event not in values)
    return CounterReading(values=values, not_counted=missing)


# ---------------------------------------------------------------------------
# What this machine allows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostFacts:
    """What decides whether ``perf`` can run for a process on this machine.

    ``perf`` is the path of the program on ``PATH``, or ``None``.
    ``paranoid`` is the kernel setting ``perf_event_paranoid``, or ``None``
    where it cannot be read. ``capabilities`` is the effective capability
    set of this process as a number, or ``None``. ``euid`` is the effective
    user id, or ``None``.
    """

    perf: str | None
    paranoid: int | None = None
    capabilities: int | None = None
    euid: int | None = None

    def forbidding(self) -> str | None:
        """Name the setting that forbids ``perf`` for this process, or ``None`` when none does."""
        if self.paranoid is None or self.paranoid <= PARANOID_HIGHEST_OPEN:
            return None
        if self.euid == 0:
            return None
        caps = self.capabilities or 0
        if caps & (1 << CAP_PERFMON) or caps & (1 << CAP_SYS_ADMIN):
            return None
        return (
            f"the kernel setting perf_event_paranoid is {self.paranoid}, which forbids it "
            "for a process without the capability CAP_PERFMON"
        )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def host_facts(environ: Mapping[str, str] | None = None) -> HostFacts:
    """Read what decides whether ``perf`` can run here. Nothing is launched or changed."""
    env = os.environ if environ is None else environ
    perf = shutil.which("perf", path=env.get("PATH", os.defpath))
    paranoid: int | None = None
    text = _read(PROC / "sys" / "kernel" / "perf_event_paranoid")
    if text is not None:
        try:
            paranoid = int(text.strip())
        except ValueError:
            paranoid = None
    capabilities: int | None = None
    for line in (_read(PROC / "self" / "status") or "").splitlines():
        if line.startswith("CapEff:"):
            try:
                capabilities = int(line.split(":", 1)[1].strip(), 16)
            except ValueError:
                capabilities = None
    euid = os.geteuid() if hasattr(os, "geteuid") else None
    return HostFacts(perf=perf, paranoid=paranoid, capabilities=capabilities, euid=euid)


def skip_before_launch(
    instrument: str, place: Place, facts: HostFacts, perf_counters: bool
) -> InstrumentReason | None:
    """Return why an instrument cannot run for a side, where that is known without a launch.

    ``place`` says where the side runs: on this machine, in a container, or
    unknown for a kind of side a plug-in provides. ``pystacks`` needs no
    privilege and is never skipped here.
    """
    if instrument == "pystacks":
        return None
    if place == "host":
        if facts.perf is None:
            return "not_installed"
        if facts.forbidding() is not None:
            return "not_permitted"
    elif place == "container" and not perf_counters:
        return "no_capability"
    return None


def _messages(launch: InstrumentedLaunch) -> str:
    """Return what the launch wrote to its error stream, and the server's log for a serving side."""
    return "".join(
        _read(launch.artifacts / name) or "" for name in (ARTIFACT_STDERR, ARTIFACT_SERVER_LOG)
    )


def _readable(path: Path) -> bool:
    """Say whether ``path`` is a regular file this process can open for reading."""
    if not path.is_file():
        return False
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def _wrote(launch: InstrumentedLaunch, name: str) -> bool:
    path = launch.artifacts / name
    return _readable(path) and path.stat().st_size > 0


# The output each instrument must leave for its launch to count.
_NEEDED: Final[Mapping[str, str]] = {
    "counters": STAT_OUTPUT,
    "stacks": SCRIPT_OUTPUT,
    "pystacks": pysampler.FOLDED_OUTPUT,
}


def judge_launch(
    instrument: str, launch: InstrumentedLaunch, place: Place
) -> tuple[InstrumentStatus, InstrumentReason | None]:
    """Return how an explain launch went: ``ok``, or skipped or failed with the reason.

    A launch that exited with zero and left the instrument's output ran. An
    output counts only when this process can read it: a file a container
    left with another owner, readable by that owner only, is not read as
    empty. Otherwise: the message ``perf`` prints when it may not open an event
    (``PERF_REFUSED``) means the system does not permit it, also when
    ``perf stat`` already wrote the first line of its output file; exit code
    127 without output means the program was not found, in the image for a
    container side; the sampler's own exit code and file mean the
    interpreter is too old; the sampler's empty file after exit code zero
    means the launch ended before the first sample and still ran. Everything
    else, a timeout included, is a failed launch.
    """
    wrote = _wrote(launch, _NEEDED[instrument])
    if launch.timed_out:
        return "failed", "launch_failed"
    if launch.rc == 0 and wrote:
        return "ok", None
    if instrument == "pystacks":
        # The sampler writes its file at exit; an empty one after exit code
        # zero means the launch ended before the first sample, not a failure.
        if launch.rc == 0 and _readable(launch.artifacts / pysampler.FOLDED_OUTPUT):
            return "ok", None
        if launch.rc == pysampler.EXIT_TOO_OLD and _wrote(launch, pysampler.TOO_OLD_OUTPUT):
            return "skipped", "interpreter_too_old"
        return "failed", "launch_failed"
    if PERF_REFUSED in _messages(launch):
        return "skipped", "not_permitted"
    if launch.rc == EXIT_NOT_FOUND and not wrote:
        return "skipped", ("not_in_image" if place == "container" else "not_installed")
    return "failed", "launch_failed"


def doctor_reports(environ: Mapping[str, str] | None = None) -> Mapping[str, DoctorReport]:
    """Say, for each instrument, whether it can run on this machine.

    Nothing is launched and no setting is changed. ``counters`` and
    ``stacks`` report ``unavailable`` when ``perf`` is not installed or the
    system forbids it, and the line then names the setting and the
    capability. ``pystacks`` needs no privilege. What applies inside a
    container is decided by the image and the launch setting
    ``perf_counters``, not here.
    """
    facts = host_facts(environ)
    if facts.perf is None:
        perf = DoctorReport(
            status="unavailable",
            summary=f"perf: {INSTRUMENT_REASON_WORDS['not_installed']}",
        )
    else:
        forbidding = facts.forbidding()
        if forbidding is not None:
            perf = DoctorReport(
                status="unavailable",
                summary=f"perf is installed, but {forbidding}",
                detail={
                    "setting": "perf_event_paranoid",
                    "value": facts.paranoid,
                    "capability": "CAP_PERFMON",
                },
            )
        else:
            perf = DoctorReport(status="ok", summary="perf is installed and the system permits it")
    sampler = DoctorReport(
        status="ok",
        summary=(
            "the sampler of pairbench needs no privilege; it runs a Python workload on the "
            "side's interpreter, Python 3.8 or newer, where perf cannot run"
        ),
    )
    return {"counters": perf, "stacks": perf, "pystacks": sampler}
