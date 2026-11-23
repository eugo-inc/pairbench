# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A serving run notes its start-up phases once per entry, from the rounds it keeps.

The results hold the start-up phases of the rounds. The warm-ups are left out
of them, and the explain step and the profilers launch each side again,
outside the capture; a reader that falls behind only in those launches gives
no note, and one that falls behind in the rounds gives one note per entry, with
or without the explain step. A twin is a side of the results under its own
name, and the positive control is judged on the primary cases only. A round
that fails or is interrupted is left out of the results, and so are the notes
of its launches.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any

import pytest

from pairbench import registry
from pairbench.api import API_VERSION, DriverContext, Invocation, LaunchOutcome, Sample, Step
from pairbench.diagnose import instruments
from pairbench.registry import GROUP_DRIVERS
from pairbench.sides import serve
from pairbench.sides.serve import free_port

from .test_serve import (
    FAKE_SERVER,
    FILLER_LINES,
    NEED_LINES,
    VLLM_LINES,
    LateOutput,
    ReadyGate,
    TellingStream,
)

pytestmark = pytest.mark.slow

NOTE_CODES = ("startup_phases_read_late", "startup_phases_left_out")
SERVER_LINES = [*FILLER_LINES, *VLLM_LINES]
# The lines the stand-in server prints before its start-up lines: its tag and its wrapper.
LEAD_LINES = 2
DRIVER = "made-up-load"


def read_late(side: str) -> str:
    return (
        f"side {side}: the lines of the start-up phases weights_loaded, engine_ready, "
        "server_started were read after the server's first answer, so those phases are timed "
        "late: a phase is timed when pairbench reads its line, and the reader of the server's "
        "output fell behind; this note is given once for each side"
    )


STDERR_LINES = [
    f"pairbench: note: startup_phases_read_late: {read_late('new')}",
    f"pairbench: note: startup_phases_read_late: {read_late('old')}",
]
JSON_NOTES = [
    ("startup_phases_read_late", read_late("new")),
    ("startup_phases_read_late", read_late("old")),
]
MARKDOWN_LINES = [
    "- Note startup\\_phases\\_read\\_late: side new: the lines of the start-up phases "
    "weights\\_loaded, engine\\_ready, server\\_started were read after the server's first "
    "answer, so those phases are timed late: a phase is timed when pairbench reads its line, "
    "and the reader of the server's output fell behind; this note is given once for each side",
    "- Note startup\\_phases\\_read\\_late: side old: the lines of the start-up phases "
    "weights\\_loaded, engine\\_ready, server\\_started were read after the server's first "
    "answer, so those phases are timed late: a phase is timed when pairbench reads its line, "
    "and the reader of the server's output fell behind; this note is given once for each side",
]

# A stand-in perf: ``stat`` writes one made-up counter line to its ``-o`` file; both ``stat``
# and ``record`` then run the command after ``--``. ``--version`` names a made-up version.
STAND_IN_PERF = """#!%s
import os, sys
args = sys.argv[1:]
if "--" not in args:
    print("perf version 0.0.1-made-up")
    sys.exit(0)
cut = args.index("--")
if args[0] == "stat":
    with open(args[args.index("-o") + 1], "w") as handle:
        handle.write("1;;cycles;1;100.00;;\\n")
os.execvp(args[cut + 1], args[cut + 1:])
"""


# What a load step does when ``MadeUpLoad.stop`` says its launch fails.
FAILED_STEP = "raise SystemExit(3)"


class MadeUpLoad:
    """A client load that runs nothing and reports one made-up latency.

    ``stop`` is asked at the start of each load: ``"fail"`` makes its one step
    exit with 3, and ``"interrupt"`` stops the run as Ctrl-C does.
    """

    name = DRIVER
    api_version = API_VERSION
    where = "client"
    clock_cases: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.stop: Callable[[DriverContext], str | None] = lambda ctx: None

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        how = self.stop(ctx)
        if how == "interrupt":
            raise KeyboardInterrupt
        code = FAILED_STEP if how == "fail" else "pass"
        return Invocation(steps=(Step(label="c1", argv=(sys.executable, "-c", code)),))

    def read(self, ctx: DriverContext, artifacts: Path) -> list[Sample]:
        value = 1.0 + 0.001 * (ctx.seq or 0)
        return [
            Sample(
                case="latency", metric="latency", unit="s", better="lower", kind="time", value=value
            )
        ]

    def default_primary(self, samples: list[Sample]) -> list[str]:
        return ["latency"]


@pytest.fixture(autouse=True)
def made_up_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[MadeUpLoad]:
    """Register the load driver, and give the explain step a stand-in perf to run."""
    load = MadeUpLoad()
    registry.register(GROUP_DRIVERS, DRIVER, load)
    folder = tmp_path / "bin"
    folder.mkdir()
    perf = folder / "perf"
    perf.write_text(STAND_IN_PERF % sys.executable, encoding="utf-8")
    perf.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    facts = instruments.HostFacts(perf=str(perf), paranoid=None, capabilities=None, euid=None)
    monkeypatch.setattr(instruments, "host_facts", lambda environ=None: facts)
    yield load
    registry.reset()


@pytest.fixture
def phases(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The phase of every serving launch, in order."""
    seen: list[str] = []
    launch = serve.ServeResolved.launch

    def recorded(self: serve.ServeResolved, request: Any) -> LaunchOutcome:
        seen.append(request.phase)
        return launch(self, request)

    monkeypatch.setattr(serve.ServeResolved, "launch", recorded)
    return seen


def config(tmp_path: Path, conf: dict[str, Any]) -> Path:
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    parts = [f'[workload]\ndriver = "{DRIVER}"\n']
    for name in ("old", "new"):
        port = free_port()
        command = [sys.executable, str(script), str(port), json.dumps(conf), name]
        parts.append(
            f'[sides.{name}.serve]\nlauncher = "host"\ncommand = {json.dumps(command)}\n'
            f'port = {port}\nready = {{ http = "/health", timeout = "120s" }}\n'
        )
    path = tmp_path / "pairbench.toml"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def run(cli: Any, tmp_path: Path, conf: dict[str, Any], explain: str, warmups: str = "0") -> Any:
    return cli(
        "run", "--config", config(tmp_path, conf), "--rounds", "2", "--rounds-exact",
        "--allow-underpowered", "--same-vs-same", "off", "--positive-control", "off",
        "--warmups", warmups, "--gates", "off", "--explain", explain, "--plots", "off",
        "--out", tmp_path / "run",
    )  # fmt: skip


def told(tmp_path: Path, err: str) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """The start-up phase notes on stderr, in results.json and in results.md."""
    (results,) = (tmp_path / "run").rglob("results.json")
    doc = json.loads(results.read_text(encoding="utf-8"))
    markdown = (results.parent / "results.md").read_text(encoding="utf-8").splitlines()
    return (
        sorted(line for line in err.splitlines() if any(c in line for c in NOTE_CODES)),
        sorted((n["code"], n["message"]) for n in doc["notes"] if n["code"] in NOTE_CODES),
        sorted(line for line in markdown if any(c.replace("_", "\\_") in line for c in NOTE_CODES)),
    )


@pytest.mark.parametrize(
    ("explain", "launched"),
    [
        ("always", ["round"] * 4 + ["explain"] * 4),
        ("off", ["round"] * 4),
    ],
)
def test_a_reader_late_in_every_launch_gives_one_note_per_side(
    explain: str,
    launched: list[str],
    cli: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phases: list[str],
) -> None:
    reader = serve.LogReader

    def late(stream: IO[bytes] | None) -> serve.LogReader:
        return reader(None if stream is None else LateOutput(stream))

    monkeypatch.setattr(serve, "LogReader", late)
    result = run(cli, tmp_path, {"lines": SERVER_LINES}, explain)

    assert result.code == 0
    assert phases == launched
    assert told(tmp_path, result.err) == (STDERR_LINES, JSON_NOTES, MARKDOWN_LINES)


@pytest.mark.parametrize(
    ("late_in", "explain", "warmups", "launched"),
    [
        ("explain", "always", "0", ["round"] * 4 + ["explain"] * 4),
        ("warmup", "off", "1", ["warmup"] * 2 + ["round"] * 4),
    ],
)
def test_a_reader_late_only_in_launches_the_results_leave_out_gives_no_note(
    late_in: str,
    explain: str,
    warmups: str,
    launched: list[str],
    cli: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phases: list[str],
) -> None:
    # Each round's server stays unready until the side's reader has taken every start-up
    # line, so the rounds read their phases in time however busy the machine is; the
    # warm-ups or the explain launches read them late.
    ready = tmp_path / "ready"
    reader = serve.LogReader

    def made(stream: IO[bytes] | None) -> serve.LogReader:
        if stream is None:
            return reader(None)
        if phases[-1] == late_in:
            ready.touch()
            return reader(LateOutput(stream))
        ready.unlink(missing_ok=True)
        gate = ReadyGate(ready, (NEED_LINES,))
        lines = LEAD_LINES + len(SERVER_LINES)
        return reader(TellingStream(stream, lines, gate))  # type: ignore[arg-type]

    monkeypatch.setattr(serve, "LogReader", made)
    conf = {"lines": SERVER_LINES, "ready_file": str(ready)}
    result = run(cli, tmp_path, conf, explain, warmups)

    assert result.code == 0
    assert phases == launched
    assert told(tmp_path, result.err) == ([], [], [])


# ---------------------------------------------------------------------------
# Twins, the positive control, failed and interrupted rounds, the profilers
# ---------------------------------------------------------------------------

# A launch as the tests see it: its phase, its round and the name of its entry.
Launched = tuple[str, int, str]


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> list[Launched]:
    """The phase, round and entry name of every serving launch, in order."""
    seen: list[Launched] = []
    launch = serve.ServeResolved.launch

    def recorded(self: serve.ServeResolved, request: Any) -> LaunchOutcome:
        seen.append((request.phase, request.round, request.name))
        return launch(self, request)

    monkeypatch.setattr(serve.ServeResolved, "launch", recorded)
    return seen


def place(launches: list[Launched]) -> tuple[str, int, int]:
    """The phase and round of the newest launch, and its place in that round from 1."""
    phase, round_, _name = launches[-1]
    return phase, round_, sum(1 for p, r, _n in launches if (p, r) == (phase, round_))


def late_only_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    launches: list[Launched],
    late: Callable[[list[Launched]], bool],
) -> dict[str, Any]:
    """Read late the output of the launches ``late`` picks, and every other in time.

    A launch read in time stays unready until its reader has taken every
    start-up line, so a busy machine makes it wait and changes nothing else.
    Returns the stand-in server's config.
    """
    ready = tmp_path / "ready"
    reader = serve.LogReader

    def made(stream: IO[bytes] | None) -> serve.LogReader:
        if stream is None:
            return reader(None)
        if late(launches):
            ready.touch()
            return reader(LateOutput(stream))
        ready.unlink(missing_ok=True)
        gate = ReadyGate(ready, (NEED_LINES,))
        lines = LEAD_LINES + len(SERVER_LINES)
        return reader(TellingStream(stream, lines, gate))  # type: ignore[arg-type]

    monkeypatch.setattr(serve, "LogReader", made)
    return {"lines": SERVER_LINES, "ready_file": str(ready)}


def run_with(cli: Any, tmp_path: Path, conf: dict[str, Any], *options: str, rounds: int = 2) -> Any:
    """A serving run without warm-ups or the explain step.

    A lineup with twins or the control needs four rounds to vary its order.
    """
    return cli(
        "run", "--config", config(tmp_path, conf), "--rounds", rounds, "--rounds-exact",
        "--allow-underpowered", "--warmups", "0", "--gates", "off", "--explain", "off",
        "--plots", "off", "--out", tmp_path / "run", *options,
    )  # fmt: skip


def noted(tmp_path: Path, err: str) -> tuple[list[str], list[tuple[str, str]]]:
    """The start-up phase notes on stderr and in the capture, of a run that may have failed."""
    (capture,) = (tmp_path / "run").rglob("capture.jsonl")
    records = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
    return (
        sorted(line for line in err.splitlines() if any(c in line for c in NOTE_CODES)),
        sorted(
            (r["code"], r["message"])
            for r in records
            if r.get("t") == "note" and r.get("code") in NOTE_CODES
        ),
    )


def stderr_note(side: str) -> str:
    return f"pairbench: note: startup_phases_read_late: {read_late(side)}"


def test_a_twin_late_in_the_rounds_is_noted_under_its_own_name(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launches: list[Launched]
) -> None:
    # The twin's start-up phases feed the noise floor of its side, under the twin's name.
    conf = late_only_in(monkeypatch, tmp_path, launches, lambda seen: seen[-1][2] == "old~same")
    result = run_with(
        cli, tmp_path, conf, "--same-vs-same", "on", "--positive-control", "off", rounds=4
    )

    assert result.code == 0
    assert sorted({name for _p, _r, name in launches}) == ["new", "new~same", "old", "old~same"]
    assert told(tmp_path, result.err) == (
        [stderr_note("old~same")],
        [("startup_phases_read_late", read_late("old~same"))],
        [MARKDOWN_LINES[1].replace("side old:", "side old\\~same:")],
    )


def test_a_side_and_its_twin_late_in_the_rounds_are_noted_once_each(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launches: list[Launched]
) -> None:
    # A twin's note is its own: the note of its side does not stand for it, nor it for its side.
    conf = late_only_in(monkeypatch, tmp_path, launches, lambda seen: True)
    result = run_with(
        cli, tmp_path, conf, "--same-vs-same", "on", "--positive-control", "off", rounds=4
    )

    assert result.code == 0
    assert sorted({name for _p, _r, name in launches}) == ["new", "new~same", "old", "old~same"]
    assert told(tmp_path, result.err) == (
        sorted(stderr_note(side) for side in ("new", "new~same", "old", "old~same")),
        sorted(
            ("startup_phases_read_late", read_late(side))
            for side in ("new", "new~same", "old", "old~same")
        ),
        sorted(
            [
                *MARKDOWN_LINES,
                MARKDOWN_LINES[0].replace("side new:", "side new\\~same:"),
                MARKDOWN_LINES[1].replace("side old:", "side old\\~same:"),
            ]
        ),
    )


def test_the_control_late_in_its_launches_gives_no_note_when_no_start_up_case_is_primary(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launches: list[Launched]
) -> None:
    # The positive control is judged on the primary cases, and the start-up cases are not.
    conf = late_only_in(monkeypatch, tmp_path, launches, lambda seen: seen[-1][2] == "new~twice")
    result = run_with(
        cli, tmp_path, conf, "--same-vs-same", "off", "--positive-control", "on", rounds=4
    )

    assert result.code == 0
    assert sorted({name for _p, _r, name in launches}) == ["new", "new~twice", "old"]
    assert told(tmp_path, result.err) == ([], [], [])


def test_the_control_late_in_its_launches_is_noted_under_its_own_name_for_a_primary_phase(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launches: list[Launched]
) -> None:
    conf = late_only_in(monkeypatch, tmp_path, launches, lambda seen: seen[-1][2] == "new~twice")
    result = run_with(
        cli, tmp_path, conf, "--same-vs-same", "off", "--positive-control", "on",
        "--case", "startup/*", rounds=4,
    )  # fmt: skip

    assert result.code == 0
    assert told(tmp_path, result.err) == (
        [stderr_note("new~twice")],
        [("startup_phases_read_late", read_late("new~twice"))],
        [MARKDOWN_LINES[0].replace("side new:", "side new\\~twice:")],
    )


# How the run ends when a launch's load fails, and when the run is interrupted.
FAILED = (5, "E_LAUNCH_FAILED")
INTERRUPTED = (130, "E_INTERRUPTED")


@pytest.mark.parametrize(
    ("late_at", "stop_at", "how", "ended", "noted_rounds"),
    [
        # The failing launch itself read its phases late.
        ({(1, 1)}, (1, 1), "fail", FAILED, ()),
        # An earlier launch of the round that fails read its phases late.
        ({(1, 1)}, (1, 2), "fail", FAILED, ()),
        # The round before the failing one was kept, and its notes with it.
        ({(1, 1), (1, 2)}, (2, 1), "fail", FAILED, (1,)),
        # The same two shapes for a run interrupted in a round.
        ({(1, 1)}, (1, 1), "interrupt", INTERRUPTED, ()),
        ({(1, 1)}, (1, 2), "interrupt", INTERRUPTED, ()),
    ],
)
def test_a_round_that_does_not_end_well_gives_no_start_up_phase_note(
    late_at: set[tuple[int, int]],
    stop_at: tuple[int, int],
    how: str,
    ended: tuple[int, str],
    noted_rounds: tuple[int, ...],
    cli: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launches: list[Launched],
    made_up_load: MadeUpLoad,
) -> None:
    def late(seen: list[Launched]) -> bool:
        phase, round_, at = place(seen)
        return phase == "round" and (round_, at) in late_at

    def stop(ctx: DriverContext) -> str | None:
        phase, round_, at = place(launches)
        return how if (phase, round_, at) == ("round", *stop_at) else None

    made_up_load.stop = stop
    conf = late_only_in(monkeypatch, tmp_path, launches, late)
    result = run_with(cli, tmp_path, conf, "--same-vs-same", "off", "--positive-control", "off")

    code, text = ended
    assert result.code == code
    assert [line for line in result.err.splitlines() if line.startswith(f"{text}: ")] != []
    sides = sorted(name for _p, r, name in launches if r in noted_rounds)
    assert noted(tmp_path, result.err) == (
        sorted(stderr_note(side) for side in sides),
        sorted(("startup_phases_read_late", read_late(side)) for side in sides),
    )


# A stand-in GPU profiler: answers ``--version`` and runs nothing else.
STAND_IN_PROFILER = """#!%s
print("0.0.1-made-up")
"""

# What the profile step says before it uses a GPU profiler, by the profiler's program name.
PROFILER_NOTICES = {
    "nsys": "nsys: pairbench does not include, download or redistribute NVIDIA Nsight Systems; "
    "it runs the copy you installed. Your use of it, and what you may publish from its output, "
    "is governed by the licence you accepted with it.",
    "ncu": "ncu: pairbench does not include, download or redistribute NVIDIA Nsight Compute; "
    "it runs the copy you installed. Your use of it, and what you may publish from its output, "
    "is governed by the licence you accepted with it.",
}


@pytest.mark.parametrize("tool", ["nsys", "ncu"])
def test_the_gpu_profilers_refuse_a_serving_side_before_any_launch(
    cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launches: list[Launched], tool: str
) -> None:
    # nsys and ncu put themselves in front of a side's command, and a serving side has none:
    # the profile step refuses it before it launches anything, so no launch can give a note.
    stand_in = tmp_path / "bin" / tool
    stand_in.write_text(STAND_IN_PROFILER % sys.executable, encoding="utf-8")
    stand_in.chmod(0o755)
    conf = late_only_in(monkeypatch, tmp_path, launches, lambda seen: True)
    result = run_with(cli, tmp_path, conf, "--same-vs-same", "off", "--positive-control", "off")
    assert result.code == 0
    (results,) = (tmp_path / "run").rglob("results.json")
    assert len(launches) == 4

    refused = cli("profile", "--from", results, "--tool", tool)
    assert refused.code == 3
    assert refused.out == ""
    assert refused.err.splitlines() == [
        PROFILER_NOTICES[tool],
        "E_ENGINE_UNSUPPORTED: side 'old' has no command to put a profiler in front of",
        "pairbench: see https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_engine_unsupported",
    ]
    assert len(launches) == 4
