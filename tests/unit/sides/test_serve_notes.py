# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A serving run notes its start-up phases once per side, from its rounds only.

The results hold the start-up phases of the rounds. The warm-ups are left out
of them, and the explain step launches each side a second time, outside the
capture; a reader that falls behind only in those launches gives no note, and
one that falls behind in the rounds gives one note per side, with or without
the explain step.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
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


class MadeUpLoad:
    """A client load that runs nothing and reports one made-up latency."""

    name = DRIVER
    api_version = API_VERSION
    where = "client"
    clock_cases: tuple[str, ...] = ()

    def prepare(self, ctx: DriverContext, argv: list[str]) -> Invocation:
        return Invocation(steps=(Step(label="c1", argv=(sys.executable, "-c", "pass")),))

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
def made_up_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Register the load driver, and give the explain step a stand-in perf to run."""
    registry.register(GROUP_DRIVERS, DRIVER, MadeUpLoad())
    folder = tmp_path / "bin"
    folder.mkdir()
    perf = folder / "perf"
    perf.write_text(STAND_IN_PERF % sys.executable, encoding="utf-8")
    perf.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    facts = instruments.HostFacts(perf=str(perf), paranoid=None, capabilities=None, euid=None)
    monkeypatch.setattr(instruments, "host_facts", lambda environ=None: facts)
    yield
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
