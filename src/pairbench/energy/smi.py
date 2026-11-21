# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Power readings from one long-running ``nvidia-smi`` query process.

The process is started once per sampler and prints one line per GPU at
every interval::

    nvidia-smi --query-gpu=timestamp,index,power.draw,temperature.gpu,<reasons>
               --format=csv,noheader,nounits -lms <milliseconds> [-i <indices>]

What the module relies on, from the nvidia-smi documentation
(https://docs.nvidia.com/deploy/nvidia-smi/index.html, the page whose change
log runs to nvidia-smi v620) and the ``--help-query-gpu`` list as published
in the pynvml repository at release 11.5.3
(https://github.com/gpuopenanalytics/pynvml/blob/11.5.3/help_query_gpu.txt):

* ``--query-gpu`` takes a comma-separated list of properties;
  ``--format=csv`` with ``noheader`` skips the header line and ``nounits``
  leaves the units out of numeric values;
* ``-lms`` probes in a loop at an interval in milliseconds, until Ctrl+C;
  ``-i`` restricts the query to the GPUs listed;
* unsupported data is shown as ``N/A``;
* ``timestamp`` is the time the query was made, ``YYYY/MM/DD HH:MM:SS.msec``
  in local time; ``index`` is the GPU's zero-based index; ``power.draw`` the
  last measured power draw of the whole board in watts; ``temperature.gpu``
  the core temperature in degrees Celsius; ``clocks_throttle_reasons.active``
  the bit mask of active clock throttle reasons;
* the documentation's change log names ``power.draw.average`` and
  ``power.draw.instant`` (added in driver 530), renames the throttle reasons
  "clock event reasons", names query fields that start with
  ``clocks_event_reasons_counters.``, and says the throttle reasons field
  was added back for backward compatibility. The public source of
  insights-core 3.8.6, file ``insights/parsers/nvidia.py``
  (https://github.com/RedHatInsights/insights-core/blob/insights-core-3.8.6/insights/parsers/nvidia.py),
  queries ``clocks_event_reasons.active``. The names a driver accepts are
  therefore taken from its own ``nvidia-smi --help-query-gpu``: the first of ``power.draw``,
  ``power.draw.instant`` and ``power.draw.average`` it lists, and the first
  of ``clocks_event_reasons.active`` and ``clocks_throttle_reasons.active``.
  When it lists neither reasons field, or its list cannot be read, the query
  leaves the reasons out, so that a field the driver refuses cannot stop the
  power readings.

No query field gives a cumulative energy counter, so this source has none.

Each line is stamped from its own ``timestamp`` field, laid onto the
``time.monotonic`` clock by one pair of clock reads taken when the process
starts. A line therefore keeps its time however the process's output is
buffered. A ``timestamp`` that cannot be read is a query error, and the line
is then stamped with the time it arrived. The process is ended with the
interrupt Ctrl+C sends, and the lines it printed before it ended are read to
the end.

Each field of a line is parsed on its own. A field shown as not supported is
left out without an error. A field that is neither a number nor marked as
not supported is a query error, and the line's other fields are kept; so is
a power below zero. Numbers and the GPU index are read in ASCII digits. A line
whose GPU index cannot be read, or that does not hold one value per queried
field, is a query error as a whole. A process that cannot be started, or
that ends before it was asked to, counts as a query error.
"""

from __future__ import annotations

import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from pairbench.energy.integrate import Collected, Reading

PROGRAM: Final = "nvidia-smi"
SOURCE: Final = "nvidia-smi"

POWER_FIELDS: Final[tuple[str, ...]] = ("power.draw", "power.draw.instant", "power.draw.average")
REASONS_FIELDS: Final[tuple[str, ...]] = (
    "clocks_event_reasons.active",
    "clocks_throttle_reasons.active",
)
TIMESTAMP_FORMAT: Final = "%Y/%m/%d %H:%M:%S.%f"

# How long reading the list of query fields, and ending the process, may take.
HELP_TIMEOUT_S: Final = 10.0
STOP_WAIT_S: Final = 5.0

_NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", re.ASCII)
_MASK_HEX = re.compile(r"0[xX][0-9a-fA-F]+")
_MASK_DECIMAL = re.compile(r"\d+", re.ASCII)
_NOT_SUPPORTED = frozenset({"n/a", "not supported"})


@dataclass(frozen=True)
class Fields:
    """The query fields for power and for the reasons mask a driver accepts."""

    power: str = POWER_FIELDS[0]
    reasons: str | None = None

    @property
    def query(self) -> tuple[str, ...]:
        """Return the fields queried, in the order the lines hold them."""
        base = ("timestamp", "index", self.power, "temperature.gpu")
        return (*base, self.reasons) if self.reasons else base


def _listed(name: str, text: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", text) is not None


def choose_fields(help_text: str | None) -> Fields:
    """Pick the power and reasons fields from the driver's own list of query fields."""
    if help_text is None:
        return Fields()
    power = next((name for name in POWER_FIELDS if _listed(name, help_text)), POWER_FIELDS[0])
    reasons = next((name for name in REASONS_FIELDS if _listed(name, help_text)), None)
    return Fields(power=power, reasons=reasons)


def command(fields: Fields, interval_s: float, gpus: Sequence[int] | None) -> list[str]:
    """Return the query command. ``gpus`` of ``None`` reads every GPU."""
    argv = [
        PROGRAM,
        f"--query-gpu={','.join(fields.query)}",
        "--format=csv,noheader,nounits",
        "-lms",
        str(max(1, round(interval_s * 1000))),
    ]
    if gpus is not None:
        argv += ["-i", ",".join(str(gpu) for gpu in gpus)]
    return argv


def _not_supported(text: str) -> bool:
    return text.strip().strip("[]").strip().lower() in _NOT_SUPPORTED


def parse_number(text: str) -> tuple[float | None, int]:
    """Parse one numeric field: the value, or ``None``, and the query errors it counts."""
    if _not_supported(text):
        return None, 0
    if not _NUMBER.fullmatch(text):
        return None, 1
    value = float(text)
    # A number too large for a float reads as infinite.
    return (value, 0) if value not in (float("inf"), float("-inf")) else (None, 1)


def parse_mask(text: str) -> tuple[int | None, int]:
    """Parse the reasons mask, hexadecimal with ``0x`` or decimal."""
    if _not_supported(text):
        return None, 0
    if _MASK_HEX.fullmatch(text):
        return int(text, 16), 0
    if _MASK_DECIMAL.fullmatch(text):
        return int(text), 0
    return None, 1


def parse_line(
    line: str,
    fields: Fields,
    *,
    arrival_s: float,
    to_monotonic: Callable[[str], float | None],
) -> tuple[Reading | None, int]:
    """Parse one line of the query process: the reading, or ``None``, and its query errors."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != len(fields.query) or not _MASK_DECIMAL.fullmatch(parts[1]):
        return None, 1
    errors = 0
    t_s = to_monotonic(parts[0])
    if t_s is None:
        t_s, errors = arrival_s, 1
    power, e_power = parse_number(parts[2])
    if power is not None and power < 0:
        power, e_power = None, 1
    temperature, e_temperature = parse_number(parts[3])
    throttle, e_throttle = parse_mask(parts[4]) if fields.reasons else (None, 0)
    reading = Reading(
        t_s=t_s,
        gpu=int(parts[1]),
        power_w=power,
        temperature_c=temperature,
        throttle=throttle,
    )
    return reading, errors + e_power + e_temperature + e_throttle


def clock_mapping(wall_s: float, monotonic_s: float) -> Callable[[str], float | None]:
    """Return what lays a ``timestamp`` field onto the monotonic clock.

    ``wall_s`` and ``monotonic_s`` are ``time.time()`` and
    ``time.monotonic()`` read together. The field is local time.
    """

    def to_monotonic(text: str) -> float | None:
        try:
            when = datetime.strptime(text, TIMESTAMP_FORMAT).timestamp()
        except (ValueError, OverflowError, OSError):
            return None
        return when - wall_s + monotonic_s

    return to_monotonic


class Process(Protocol):
    """The part of ``subprocess.Popen`` the source uses."""

    @property
    def stdout(self) -> Iterable[str] | None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def send_signal(self, sig: int) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


def _spawn(argv: Sequence[str]) -> Process:
    return subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def _read_help(argv: Sequence[str]) -> str | None:
    try:
        done = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=HELP_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


class FieldCache:
    """The fields a driver accepts, read from its list once and kept for later samplers."""

    def __init__(self, read_help: Callable[[Sequence[str]], str | None] | None = None) -> None:
        self._read_help = read_help or _read_help
        self._lock = threading.Lock()
        self._fields: Fields | None = None

    def get(self) -> Fields:
        """Return the fields, reading the driver's list the first time."""
        with self._lock:
            if self._fields is None:
                self._fields = choose_fields(self._read_help([PROGRAM, "--help-query-gpu"]))
            return self._fields


def _end(process: Process, wait_s: float) -> None:
    """End the process: interrupt, then terminate, then kill, each given ``wait_s``."""
    steps: tuple[Callable[[], None], ...] = (
        lambda: process.send_signal(signal.SIGINT),
        process.terminate,
        process.kill,
    )
    for step in steps:
        if process.poll() is not None:
            return
        try:
            step()
            process.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            return


class SmiSource:
    """A source that reads one long-running ``nvidia-smi`` query process.

    ``run`` starts the process and reads its lines until it ends; ``halt``
    ends it. ``gpus`` of ``None`` reads every GPU.
    """

    name: Final = SOURCE

    def __init__(
        self,
        gpus: Sequence[int] | None,
        interval_s: float,
        *,
        fields: FieldCache | None = None,
        spawn: Callable[[Sequence[str]], Process] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        stop_wait_s: float = STOP_WAIT_S,
    ) -> None:
        self._gpus = None if gpus is None else tuple(gpus)
        self._interval_s = interval_s
        self._fields = fields or FieldCache()
        self._spawn = spawn or _spawn
        self._clock = clock
        self._wall = wall
        self._stop_wait_s = stop_wait_s
        self._lock = threading.Lock()
        self._process: Process | None = None
        self._halted = False

    def run(self, sink: Collected) -> None:
        """Start the process and hand every line it prints to ``sink``."""
        fields = self._fields.get()
        argv = command(fields, self._interval_s, self._gpus)
        with self._lock:
            if self._halted:
                return
            try:
                process = self._spawn(argv)
            except (OSError, subprocess.SubprocessError):
                sink.error()
                return
            self._process = process
        if self._gpus is not None:
            sink.select(self._gpus)
        to_monotonic = clock_mapping(self._wall(), self._clock())
        try:
            for line in process.stdout or ():
                arrival_s = self._clock()
                if not line.strip():
                    continue
                reading, errors = parse_line(
                    line, fields, arrival_s=arrival_s, to_monotonic=to_monotonic
                )
                if errors:
                    sink.error(errors)
                if reading is not None:
                    sink.add(reading)
        finally:
            _end(process, self._stop_wait_s)
            with self._lock:
                halted = self._halted
            if not halted:
                sink.error()

    def halt(self) -> None:
        """End the process; ``run`` then reads what it printed and returns."""
        with self._lock:
            self._halted = True
            process = self._process
        if process is not None:
            _end(process, self._stop_wait_s)
