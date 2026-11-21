# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``perf`` driver: hardware and software counters from ``perf stat``.

Format read from the tool's own documentation, ``tools/perf/Documentation/perf-stat.txt``
of Linux v6.12, section "CSV FORMAT"
(https://github.com/torvalds/linux/blob/v6.12/tools/perf/Documentation/perf-stat.txt),
and checked against the output of a real run of perf 6.12.

``prepare`` puts ``-x ; -o <file>`` right after the word ``stat``: perf then
writes one line per event, its fields separated by ``;``. The documentation
says that commas inside a field are not quoted and recommends another
separator; event names can hold commas. The driver reads perf's own options
from the word ``stat`` up to ``--``, or to the end of the command when there
is no ``--``, and refuses a command that names its output options there
(``-x``, ``--field-separator``, ``-o``, ``--output``, ``-j``, ``--json``) or a
mode whose lines it does not read: interval printing (``-I``), no aggregation
(``-A``, ``--no-aggr``), counts per socket, die, cluster, cache, core, thread
or node (``--per-...``) and ``--metric-only``. Put ``--`` before the
workload's own command when it has options like these.

A container side needs the capability to use performance counters, the launch
setting ``perf_counters``; without it ``prepare`` refuses with
``E_ENGINE_UNSUPPORTED``. On a command or Python environment side the
system's own setting decides.

``read`` takes the first three fields of each line: the counter value, its
unit and the event name. The rest (run time, share of time counted, variance,
derived metric) is not read. A unit or event field that is a number marks a
line of one of the modes above, which the output of a file side can still
hold, and is refused. Lines starting with ``#`` and empty lines are
skipped, and so are lines that hold a derived metric only (empty value and
event). One case per event, named as perf printed it:

* a count with no unit is of unit ``count`` and kind ``count``;
* a time in ``msec``, ``usec`` or ``nsec`` is converted to seconds;
* any other unit is kept as printed.

Every event is better lower. ``<not counted>`` and ``<not supported>`` are
missing cases, each named in a note. A machine with more than one CPU
performance-monitoring unit prints one line per unit, for example
``cpu_core/instructions/`` and ``cpu_atom/instructions/``; each line is its
own case. ``ipc`` (instructions per cycle, better higher) is added when
instructions and cycles were both counted: the sum of the counted
instructions over the sum of the counted cycles, taken over the units that
counted both, for one set of event modifiers. With ``-r`` perf prints the
mean of the repeats and a variance column; such a value is the tool's own
summary (``tool_summary``).

No case counts toward the verdict by default. ``perf stat`` writes no
version into its output.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from pairbench.api import REDUCER_IDENTITY, REDUCER_TOOL_SUMMARY, DriverContext, Sample
from pairbench.drivers.base import (
    HOST_KINDS,
    NOTE_EVENT_NOT_COUNTED,
    ToolDriver,
    launch_failed,
    path_in_side,
    read_text,
)
from pairbench.errors import Refusal

OUTPUT_FILE: Final = "perf-stat.txt"
SEPARATOR: Final = ";"
STAT: Final = "stat"
# Options of ``perf stat`` that name its output; the driver adds its own.
OWN_SHORT: Final[tuple[str, ...]] = ("-x", "-o", "-j")
OWN_LONG: Final[tuple[str, ...]] = ("--field-separator", "--output", "--json")
# Modes that print lines the driver does not read.
MODE_SHORT: Final[tuple[str, ...]] = ("-I", "-A")
MODE_LONG: Final[tuple[str, ...]] = ("--interval-print", "--no-aggr", "--metric-only")
MODE_PREFIX: Final = "--per-"
NOT_COUNTED: Final[tuple[str, ...]] = ("<not counted>", "<not supported>")
# Seconds per unit, for the units of time perf prints.
TIME_UNITS: Final[dict[str, float]] = {
    "msec": 1e-3,
    "ms": 1e-3,
    "usec": 1e-6,
    "us": 1e-6,
    "nsec": 1e-9,
    "ns": 1e-9,
    "sec": 1.0,
    "s": 1.0,
}
COUNT_UNIT: Final = "count"
INSTRUCTIONS: Final = "instructions"
CYCLES: Final = "cycles"
IPC: Final = "ipc"
IPC_UNIT: Final = "insn/cycle"
_PMU_EVENT = re.compile(r"^([^/]+)/(.+)/$")
_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


class PerfDriver(ToolDriver):
    """Reads one case per event of ``perf stat``, plus ``ipc``."""

    name = "perf"
    tool = "perf"
    output_file = OUTPUT_FILE
    tested_majors = (6,)
    real_run = True
    format_read = "perf stat machine-readable output (-x), perf 6"

    def add_output(self, ctx: DriverContext, argv: list[str]) -> list[str]:
        """Put ``-x ; -o <file>`` after the word ``stat``."""
        if ctx.side.kind not in HOST_KINDS and not ctx.launch.perf_counters:
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {ctx.name!r} runs in a container, which needs the capability to use "
                "performance counters for the perf driver: set the launch setting "
                "perf_counters = true",
            )
        if STAT not in argv:
            raise Refusal(
                "E_USAGE",
                "the perf driver reads the output of perf stat: the command has no word stat",
            )
        at = argv.index(STAT)
        options = argv[at + 1 :]
        if "--" in options:
            options = options[: options.index("--")]
        for arg in options:
            refused = _refused_option(arg)
            if refused is not None:
                raise Refusal(
                    "E_USAGE",
                    f"the perf driver cannot take the perf stat option {refused}: "
                    f"{_why(refused)}; put -- before the workload's own command "
                    "when the option is the workload's",
                )
        added = ["-x", SEPARATOR, "-o", path_in_side(ctx, OUTPUT_FILE)]
        return [*argv[: at + 1], *added, *argv[at + 1 :]]

    def read_file(self, ctx: DriverContext, path: Path) -> list[Sample]:
        """Return one case per counted event, and ``ipc`` when it can be computed."""
        samples: list[Sample] = []
        for line_no, line in enumerate(read_text(path, self.name).splitlines(), start=1):
            if not line.strip() or line.startswith("#"):
                continue
            where = f"{path.name} line {line_no}"
            fields = line.split(SEPARATOR)
            if len(fields) < 3:
                raise launch_failed(f"{where}: fewer than three fields separated by {SEPARATOR}")
            raw, unit, event = fields[0].strip(), fields[1].strip(), fields[2].strip()
            if not raw and not event:
                continue
            for field, found in (("unit", unit), ("event", event)):
                if _NUMBER.fullmatch(found):
                    raise launch_failed(
                        f"{where}: the {field} field {found!r} is a number, so the line is no "
                        "event over the whole launch (perf stat -I, -A and --per-... write "
                        "lines like this); the perf driver reads one line per event over the "
                        "whole launch"
                    )
            if not event:
                raise launch_failed(f"{where}: the event name is empty")
            if raw in NOT_COUNTED:
                ctx.note(
                    NOTE_EVENT_NOT_COUNTED,
                    f"side {ctx.name!r}: perf reported the event {event!r} as {raw[1:-1]}; "
                    "the case is missing from this launch",
                )
                continue
            try:
                value = float(raw)
            except ValueError:
                raise launch_failed(
                    f"{where}: the counter value of {event!r} is not a number"
                ) from None
            summary = len(fields) > 3 and fields[3].strip().endswith("%")
            samples.append(_sample(event, unit, value, summary=summary))
        ipc = _ipc(samples)
        if ipc is not None:
            samples.append(
                Sample(
                    case=IPC,
                    metric=IPC,
                    unit=IPC_UNIT,
                    better="higher",
                    kind="other",
                    value=ipc,
                )
            )
        return samples

    def default_primary(self, samples: list[Sample]) -> list[str]:
        """Return no case: every counter is secondary unless the config names it."""
        return []


def _refused_option(arg: str) -> str | None:
    for option in (*OWN_LONG, *MODE_LONG):
        if arg == option or arg.startswith(option + "="):
            return option
    if arg.startswith(MODE_PREFIX):
        return arg.split("=", 1)[0]
    for option in OWN_SHORT:
        # A short option may carry its value: -x, or -o/some/file.
        if arg == option or (arg.startswith(option) and not arg.startswith("--")):
            return option
    if arg in MODE_SHORT or (arg.startswith("-I") and not arg.startswith("--")):
        return arg[:2]
    return None


def _why(option: str) -> str:
    if option in (*OWN_SHORT, *OWN_LONG):
        return "it adds the options that name the output itself and reads the file it names"
    return "it reads one line per event over the whole launch"


def _sample(event: str, unit: str, value: float, *, summary: bool) -> Sample:
    reducer = REDUCER_TOOL_SUMMARY if summary else REDUCER_IDENTITY
    if not unit:
        return Sample(
            case=event,
            metric=event,
            unit=COUNT_UNIT,
            better="lower",
            kind="count",
            value=value,
            reducer=reducer,
        )
    scale = TIME_UNITS.get(unit)
    if scale is not None:
        return Sample(
            case=event,
            metric=event,
            unit="s",
            better="lower",
            kind="time",
            value=value * scale,
            reducer=reducer,
        )
    return Sample(
        case=event,
        metric=event,
        unit=unit,
        better="lower",
        kind="other",
        value=value,
        reducer=reducer,
    )


def _split_event(event: str) -> tuple[str, str, str]:
    """Return the monitoring unit, the event and its modifiers of a name perf printed."""
    pmu = ""
    found = _PMU_EVENT.match(event)
    if found is not None:
        pmu, event = found.group(1), found.group(2)
    base, _, modifiers = event.partition(":")
    return pmu, base, modifiers


def _ipc(samples: list[Sample]) -> float | None:
    instructions: dict[tuple[str, str], float] = {}
    cycles: dict[tuple[str, str], float] = {}
    for sample in samples:
        if sample.kind != "count":
            continue
        pmu, base, modifiers = _split_event(sample.case)
        if base == INSTRUCTIONS:
            instructions[(pmu, modifiers)] = sample.value
        elif base == CYCLES:
            cycles[(pmu, modifiers)] = sample.value
    both = [key for key in instructions if key in cycles]
    if not both or len({modifiers for _, modifiers in both}) != 1:
        return None
    total_cycles = sum(cycles[key] for key in both)
    if total_cycles <= 0:
        return None
    return sum(instructions[key] for key in both) / total_cycles
