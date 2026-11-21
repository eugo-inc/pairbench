# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``nvidia-smi`` source, with fake processes and synthetic output."""

from __future__ import annotations

import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from pairbench.api import Window
from pairbench.energy import integrate, nvml, smi
from pairbench.energy.integrate import Collected, Reading, read_windows
from pairbench.energy.smi import (
    FieldCache,
    Fields,
    SmiSource,
    choose_fields,
    clock_mapping,
    command,
    parse_line,
    parse_mask,
    parse_number,
)
from pairbench.energy.smi import _read_help as real_read_help
from pairbench.energy.smi import _spawn as real_spawn

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "energy" / "nvidia-smi-query.csv"
# 2001/02/03 04:05:06.000 in UTC, as seconds since the epoch.
FIXTURE_START_UTC = 981173106.0
EVENT_FIELDS = Fields(power="power.draw", reasons="clocks_event_reasons.active")
# The fields the fixture was written for.
FIXTURE_FIELDS = Fields(power="power.draw", reasons="clocks_throttle_reasons.active")


@pytest.fixture
def utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset to set the local time zone")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _fixed(t: float) -> float | None:
    return t


# --- the fields a driver accepts ---------------------------------------------

HELP_OLD = """\
"timestamp"
The timestamp of where the query was made in format "YYYY/MM/DD HH:MM:SS.msec".

"power.draw"
The last measured power draw for the entire board, in watts.

"clocks_throttle_reasons.active"
Bitmask of active clock throttle reasons. See nvml.h for more details.
"""

HELP_NEW = """\
"power.draw.average"
"power.draw.instant"
"clocks_event_reasons.active"
"clocks_event_reasons.sw_power_cap"
"clocks_throttle_reasons.active"
"""


def test_the_fields_come_from_the_drivers_own_list() -> None:
    assert choose_fields(HELP_OLD) == Fields(
        power="power.draw", reasons="clocks_throttle_reasons.active"
    )
    assert choose_fields(HELP_NEW) == Fields(
        power="power.draw.instant", reasons="clocks_event_reasons.active"
    )


def test_without_a_list_the_query_leaves_the_reasons_out() -> None:
    assert choose_fields(None) == Fields(power="power.draw", reasons=None)
    assert choose_fields('"power.draw"\n') == Fields(power="power.draw", reasons=None)


def test_a_longer_name_does_not_count_as_the_shorter_one() -> None:
    assert choose_fields('"power.draw.average"\n') == Fields(power="power.draw.average")
    assert choose_fields('"clocks_event_reasons.active_x"\n').reasons is None


def test_the_query_command_reads_every_or_the_selected_gpus() -> None:
    assert command(EVENT_FIELDS, 0.2, None) == [
        "nvidia-smi",
        "--query-gpu=timestamp,index,power.draw,temperature.gpu,clocks_event_reasons.active",
        "--format=csv,noheader,nounits",
        "-lms",
        "200",
    ]
    assert command(Fields(), 0.05, (0, 2)) == [
        "nvidia-smi",
        "--query-gpu=timestamp,index,power.draw,temperature.gpu",
        "--format=csv,noheader,nounits",
        "-lms",
        "50",
        "-i",
        "0,2",
    ]
    assert command(Fields(), 0.0001, None)[4] == "1"


def test_the_field_list_is_read_once() -> None:
    calls: list[tuple[str, ...]] = []

    def read_help(argv: Sequence[str]) -> str | None:
        calls.append(tuple(argv))
        return HELP_NEW

    cache = FieldCache(read_help)
    assert cache.get() == Fields(power="power.draw.instant", reasons="clocks_event_reasons.active")
    assert cache.get() == Fields(power="power.draw.instant", reasons="clocks_event_reasons.active")
    assert calls == [("nvidia-smi", "--help-query-gpu")]


# --- parsing each field on its own ---------------------------------------------


def test_a_number_field_is_a_value_not_supported_or_a_query_error() -> None:
    assert parse_number("123.45") == (123.45, 0)
    assert parse_number("40") == (40.0, 0)
    assert parse_number("N/A") == (None, 0)
    assert parse_number("[N/A]") == (None, 0)
    assert parse_number("[Not Supported]") == (None, 0)
    assert parse_number("[Unknown Error]") == (None, 1)
    assert parse_number("ERR!") == (None, 1)
    assert parse_number("") == (None, 1)
    assert parse_number("nan") == (None, 1)
    assert parse_number("inf") == (None, 1)
    assert parse_number("1e999") == (None, 1)
    assert parse_number("1_000") == (None, 1)


def test_the_reasons_mask_is_hexadecimal_or_decimal() -> None:
    assert parse_mask("0x0000000000000004") == (4, 0)
    assert parse_mask("0X00000000000000EC") == (0xEC, 0)
    assert parse_mask("12") == (12, 0)
    assert parse_mask("N/A") == (None, 0)
    assert parse_mask("0xZZ") == (None, 1)
    assert parse_mask("Active") == (None, 1)


def test_a_line_gives_one_reading_of_one_gpu() -> None:
    reading, errors = parse_line(
        "2001/02/03 04:05:06.500, 1, 123.45, 61, 0x0000000000000040",
        EVENT_FIELDS,
        arrival_s=99.0,
        to_monotonic=lambda text: 7.5,
    )
    assert errors == 0
    assert reading == Reading(t_s=7.5, gpu=1, power_w=123.45, temperature_c=61.0, throttle=0x40)


def test_a_field_that_fails_keeps_the_other_fields_and_counts_one_error() -> None:
    reading, errors = parse_line(
        "2001/02/03 04:05:06.500, 0, 123.45, [Unknown Error], 0x0000000000000000",
        EVENT_FIELDS,
        arrival_s=99.0,
        to_monotonic=lambda text: 7.5,
    )
    assert errors == 1
    assert reading == Reading(t_s=7.5, gpu=0, power_w=123.45, temperature_c=None, throttle=0)


def test_a_field_not_supported_is_left_out_without_an_error() -> None:
    reading, errors = parse_line(
        "2001/02/03 04:05:06.500, 0, 80.00, N/A, [N/A]",
        EVENT_FIELDS,
        arrival_s=99.0,
        to_monotonic=lambda text: 7.5,
    )
    assert errors == 0
    assert reading == Reading(t_s=7.5, gpu=0, power_w=80.0)


def test_a_power_below_zero_is_a_query_error_and_keeps_the_other_fields() -> None:
    reading, errors = parse_line(
        "2001/02/03 04:05:06.500, 0, -5.00, 40",
        Fields(),
        arrival_s=99.0,
        to_monotonic=lambda text: 7.5,
    )
    assert errors == 1
    assert reading == Reading(t_s=7.5, gpu=0, power_w=None, temperature_c=40.0)


def test_digits_outside_ascii_are_not_read_as_numbers() -> None:
    arabic_ten = chr(0x661) + chr(0x660)
    arabic_three = chr(0x663)
    assert parse_number(arabic_ten) == (None, 1)
    assert parse_mask(arabic_three) == (None, 1)
    line = f"2001/02/03 04:05:06.500, {arabic_three}, 80.00, 40"
    assert parse_line(line, Fields(), arrival_s=0.0, to_monotonic=_fixed_text) == (None, 1)


def test_a_time_stamp_that_cannot_be_read_is_an_error_and_the_arrival_time_is_used() -> None:
    reading, errors = parse_line(
        "soon, 0, 80.00, 40",
        Fields(),
        arrival_s=99.0,
        to_monotonic=lambda text: None,
    )
    assert errors == 1
    assert reading == Reading(t_s=99.0, gpu=0, power_w=80.0, temperature_c=40.0)


@pytest.mark.parametrize(
    "line",
    [
        "No devices were found",
        "2001/02/03 04:05:06.500, 0, 80.00",
        "2001/02/03 04:05:06.500, 0, 80.00, 40, 0x0, 7",
        "2001/02/03 04:05:06.500, GPU-0, 80.00, 40, 0x0",
        "2001/02/03 04:05:06.500, -1, 80.00, 40, 0x0",
    ],
)
def test_a_line_that_cannot_be_split_into_its_fields_is_one_error(line: str) -> None:
    assert parse_line(line, EVENT_FIELDS, arrival_s=0.0, to_monotonic=_fixed_text) == (None, 1)


def _fixed_text(text: str) -> float | None:
    return 0.0


def test_time_stamps_are_laid_onto_the_monotonic_clock(utc: None) -> None:
    to_monotonic = clock_mapping(FIXTURE_START_UTC, 50.0)
    assert to_monotonic("2001/02/03 04:05:06.000") == 50.0
    assert to_monotonic("2001/02/03 04:05:06.500") == 50.5
    assert to_monotonic("2001/02/03 04:05:07.250") == 51.25
    assert to_monotonic("2001-02-03 04:05:06") is None
    assert to_monotonic("") is None


# --- the process -----------------------------------------------------------------


class FakeProcess:
    """A query process that prints fixed lines, optionally until it is interrupted."""

    def __init__(self, lines: Sequence[str], *, wait_for_signal: bool = True) -> None:
        self._lines = list(lines)
        self._wait_for_signal = wait_for_signal
        self._ended = threading.Event()
        self.signals: list[int] = []
        self.terminated = False
        self.killed = False
        self.returncode: int | None = None

    @property
    def stdout(self) -> Iterator[str]:
        yield from self._lines
        if self._wait_for_signal:
            self._ended.wait(10.0)

    def poll(self) -> int | None:
        return 0 if self._ended.is_set() else None

    def wait(self, timeout: float | None = None) -> int:
        if not self._ended.wait(timeout if timeout is not None else 10.0):
            raise subprocess.TimeoutExpired("nvidia-smi", timeout or 0.0)
        self.returncode = 0
        return 0

    def _end(self) -> None:
        self._ended.set()

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self._end()

    def terminate(self) -> None:
        self.terminated = True
        self._end()

    def kill(self) -> None:
        self.killed = True
        self._end()


class StubbornProcess(FakeProcess):
    """A process that ignores the interrupt and ends only when killed."""

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)

    def terminate(self) -> None:
        self.terminated = True


def _listing(fields: Fields) -> str | None:
    """Return a list of query fields that names exactly these, or none at all."""
    if fields.reasons is None:
        return None
    return f'"{fields.power}"\n"{fields.reasons}"\n'


def _source(
    process: FakeProcess,
    *,
    gpus: Sequence[int] | None = None,
    fields: Fields = EVENT_FIELDS,
    spawned: list[list[str]] | None = None,
) -> SmiSource:
    def spawn(argv: Sequence[str]) -> FakeProcess:
        if spawned is not None:
            spawned.append(list(argv))
        return process

    return SmiSource(
        gpus,
        0.2,
        fields=FieldCache(lambda argv: _listing(fields)),
        spawn=spawn,
        clock=lambda: 50.0,
        wall=lambda: FIXTURE_START_UTC,
        stop_wait_s=0.05,
    )


def _run_until_halted(source: SmiSource, sink: Collected, wanted: int) -> None:
    thread = threading.Thread(target=source.run, args=(sink,))
    thread.start()
    deadline = time.monotonic() + 10.0
    while len(sink.snapshot()[0]) < wanted and time.monotonic() < deadline:
        sink.started.wait(0.01)
    source.halt()
    thread.join(10.0)
    assert thread.is_alive() is False


def test_the_fixture_runs_through_the_source_and_integrates(utc: None) -> None:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    process = FakeProcess(lines)
    spawned: list[list[str]] = []
    source = _source(process, fields=FIXTURE_FIELDS, spawned=spawned)
    sink = Collected()
    _run_until_halted(source, sink, 24)
    readings, errors, gpus = sink.snapshot()
    assert errors == 0
    assert gpus is None
    assert len(readings) == 24
    assert readings[0] == Reading(t_s=50.0, gpu=0, power_w=100.0, temperature_c=40.0, throttle=0)
    assert readings[1] == Reading(t_s=50.0, gpu=1, power_w=50.0, temperature_c=None, throttle=0)
    assert process.signals == [signal.SIGINT]
    assert spawned == [command(FIXTURE_FIELDS, 0.2, None)]
    reading = read_windows(
        readings,
        (Window("", 50.0, 52.3),),
        gpus=(0, 1),
        min_samples=10,
        source=source.name,
        query_errors=errors,
    )
    assert reading.source == "nvidia-smi"
    assert reading.sampler_ok is True
    (window,) = reading.windows
    assert window.energy_j == pytest.approx(330.0, rel=1e-6)
    assert window.mean_power_w == pytest.approx(150.0, rel=1e-6)
    assert window.n_samples == 12
    assert window.counter_j is None
    assert reading.throttle_events == 1
    assert reading.max_temperature_c == 40.0


def test_a_selection_is_passed_on_and_named_to_the_sink() -> None:
    process = FakeProcess(["2001/02/03 04:05:06.000, 2, 10.00, 30\n"])
    spawned: list[list[str]] = []
    sink = Collected()
    _run_until_halted(_source(process, gpus=(2,), fields=Fields(), spawned=spawned), sink, 1)
    assert spawned[0][-2:] == ["-i", "2"]
    assert sink.snapshot()[2] == (2,)


def test_blank_lines_are_skipped_without_an_error() -> None:
    process = FakeProcess(["\n", "   \n", "2001/02/03 04:05:06.000, 0, 10.00, 30\n"])
    sink = Collected()
    _run_until_halted(_source(process, fields=Fields()), sink, 1)
    readings, errors, _ = sink.snapshot()
    assert errors == 0
    assert len(readings) == 1


def test_errors_of_a_line_are_counted() -> None:
    process = FakeProcess(
        [
            "2001/02/03 04:05:06.000, 0, ERR!, 30\n",
            "Failed to initialize NVML: Unknown Error\n",
        ]
    )
    sink = Collected()
    _run_until_halted(_source(process, fields=Fields()), sink, 1)
    readings, errors, _ = sink.snapshot()
    assert errors == 2
    assert readings == (Reading(t_s=readings[0].t_s, gpu=0, power_w=None, temperature_c=30.0),)


def test_a_process_that_ends_on_its_own_is_a_query_error() -> None:
    process = FakeProcess(["2001/02/03 04:05:06.000, 0, 10.00, 30\n"], wait_for_signal=False)
    process._end()
    sink = Collected()
    _source(process, fields=Fields()).run(sink)
    readings, errors, _ = sink.snapshot()
    assert len(readings) == 1
    assert errors == 1


def test_a_process_that_cannot_be_started_is_a_query_error() -> None:
    def spawn(argv: Sequence[str]) -> FakeProcess:
        raise FileNotFoundError(argv[0])

    sink = Collected()
    SmiSource(None, 0.2, fields=FieldCache(lambda argv: None), spawn=spawn).run(sink)
    assert sink.snapshot() == ((), 1, None)


def test_a_source_halted_before_it_started_starts_nothing() -> None:
    spawned: list[list[str]] = []
    source = _source(FakeProcess([]), spawned=spawned)
    source.halt()
    sink = Collected()
    source.run(sink)
    assert spawned == []
    assert sink.snapshot() == ((), 0, None)


def test_a_process_that_ignores_the_interrupt_is_terminated_then_killed() -> None:
    process = StubbornProcess([])
    source = _source(process, fields=Fields())
    sink = Collected()
    thread = threading.Thread(target=source.run, args=(sink,))
    thread.start()
    deadline = time.monotonic() + 10.0
    while source._process is None and time.monotonic() < deadline:
        time.sleep(0.001)
    source.halt()
    thread.join(10.0)
    assert thread.is_alive() is False
    assert process.signals[0] == signal.SIGINT
    assert process.terminated is True
    assert process.killed is True


def test_the_real_spawn_is_kept_away_from_the_tests() -> None:
    with pytest.raises(AssertionError, match="nvidia-smi"):
        smi._spawn(["nvidia-smi"])
    with pytest.raises(AssertionError, match="nvidia-smi"):
        smi._read_help(["nvidia-smi", "--help-query-gpu"])


# --- the real process path, with a stand-in for the query loop --------------------------

# A stand-in for the query loop, run by the interpreter of the tests: it prints
# one line per interval in the query format and ends on the interrupt. With
# ``hold`` it prints three lines without flushing them, creates the file named
# after the mode, and waits.
STAND_IN = """
import signal, sys, time
from datetime import datetime
stop = []
signal.signal(signal.SIGINT, lambda signum, frame: stop.append(signum))
hold = sys.argv[1] == "hold"
for i in range(500):
    if stop:
        break
    if not hold or i < 3:
        stamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]
        sys.stdout.write(f"{stamp}, 0, {100 + i}.00, 40, 0x0000000000000000\\n")
        if not hold:
            sys.stdout.flush()
    elif i == 3:
        open(sys.argv[2], "w").close()
    time.sleep(0.02)
"""

needs_signals = pytest.mark.skipif(
    sys.platform == "win32", reason="needs POSIX signals to end the stand-in query process"
)


def _real_source(mode: str, started: list[subprocess.Popen[str]], *extra: str) -> SmiSource:
    def spawn(argv: Sequence[str]) -> smi.Process:
        process = real_spawn([sys.executable, "-c", STAND_IN, mode, *extra])
        assert isinstance(process, subprocess.Popen)
        started.append(process)
        return process

    return SmiSource(
        None,
        0.02,
        fields=FieldCache(lambda argv: _listing(EVENT_FIELDS)),
        spawn=spawn,
        stop_wait_s=5.0,
    )


@needs_signals
def test_the_real_process_is_read_line_by_line_and_ended_with_an_interrupt() -> None:
    started: list[subprocess.Popen[str]] = []
    source = _real_source("flush", started)
    sink = Collected()
    thread = threading.Thread(target=source.run, args=(sink,))
    thread.start()
    deadline = time.monotonic() + 10.0
    while len(sink.snapshot()[0]) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    before_halt = len(sink.snapshot()[0])
    source.halt()
    thread.join(10.0)
    assert thread.is_alive() is False
    readings, errors, _ = sink.snapshot()
    assert before_halt >= 3
    assert errors == 0
    assert readings[0] == Reading(
        t_s=readings[0].t_s, gpu=0, power_w=100.0, temperature_c=40.0, throttle=0
    )
    assert [r.t_s for r in readings] == sorted(r.t_s for r in readings)
    assert abs(time.monotonic() - readings[-1].t_s) < 5.0
    assert started[0].returncode is not None


@needs_signals
def test_lines_the_real_process_held_back_are_read_after_the_interrupt(tmp_path: Path) -> None:
    started: list[subprocess.Popen[str]] = []
    ready = tmp_path / "ready"
    source = _real_source("hold", started, str(ready))
    sink = Collected()
    thread = threading.Thread(target=source.run, args=(sink,))
    thread.start()
    deadline = time.monotonic() + 10.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    source.halt()
    thread.join(10.0)
    assert thread.is_alive() is False
    readings, errors, _ = sink.snapshot()
    assert errors == 0
    assert [r.power_w for r in readings] == [100.0, 101.0, 102.0]


def test_the_real_field_list_read_keeps_only_the_output_of_a_command_that_succeeded(
    tmp_path: Path,
) -> None:
    listing = [sys.executable, "-c", "print('\"power.draw\"')"]
    assert real_read_help(listing) == '"power.draw"\n'
    assert real_read_help([sys.executable, "-c", "import sys; sys.exit(1)"]) is None
    assert real_read_help([str(tmp_path / "missing")]) is None


def test_every_source_the_energy_modules_cite_names_a_version() -> None:
    for module in (integrate, nvml, smi):
        text = module.__doc__ or ""
        for unversioned in ("latest", "current reference", "current NVML", "master branch"):
            assert unversioned not in text, (module.__name__, unversioned)
        for link in re.findall(r"https://github\.com/\S+", text):
            assert "/blob/" in link, (module.__name__, link)
