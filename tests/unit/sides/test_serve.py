# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``serve`` side kind against a small HTTP server the tests start themselves.

The server is the script ``FAKE_SERVER``, run with this interpreter on a free
port of the loopback address. It prints start-up lines, answers a readiness
path, lists one model, answers chat requests as a stream, and records every
request it gets. Engine calls go to ``FakeEngine``; a container launch starts
the same script in place of the engine's ``run`` command. Nothing here needs
a container engine, a GPU or a model.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import pytest

from pairbench import api
from pairbench.errors import (
    EXIT_INTERNAL,
    EXIT_LAUNCH,
    EXIT_MACHINE,
    EXIT_SIDE,
    EXIT_USAGE,
    Refusal,
)
from pairbench.model import (
    HIDDEN,
    NOTE_GPU_BUSY_BEFORE_START,
    LaunchSettings,
    Probe,
    Ready,
    ServeSpec,
    Side,
    fingerprint_of,
)
from pairbench.sides import container, serve
from pairbench.sides.base import Completed
from pairbench.sides.container import REMOVE_WAIT_S
from pairbench.sides.serve import (
    NOTE_GPU_MEMORY_UNREADABLE,
    NOTE_PHASES_LEFT_OUT,
    NOTE_PHASES_READ_LATE,
    DockerLauncher,
    HostLauncher,
    PodmanLauncher,
    ServeKind,
    ServerProcess,
    ServerProcesses,
    Waits,
    free_port,
    http_ok,
    probe_body,
)

FAKE_SERVER = r"""
import json, os, signal, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

port = int(sys.argv[1])
conf = json.loads(sys.argv[2])
record = conf.get("record")


def note(entry):
    if record:
        with open(record, "a", encoding="utf-8") as out:
            out.write(json.dumps(entry) + "\n")


def stopping(*_args):
    print("stopping", flush=True)
    os._exit(0)


signal.signal(signal.SIGTERM, stopping)
if len(sys.argv) > 3:
    print("tag " + sys.argv[3], flush=True)
    print("wrap-env " + os.environ.get("MADE_UP_WRAP", "-"), flush=True)
for line in conf.get("lines", []):
    print(line, flush=True)
if conf.get("child") or conf.get("daemon"):
    # A process that ignores the stop signal and holds the server's output.
    marker = record + ".child"
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import pathlib, signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
         "pathlib.Path(sys.argv[1]).touch(); time.sleep(60)", marker],
        start_new_session=bool(conf.get("daemon")),
    )
    deadline = time.monotonic() + 10.0
    while not os.path.exists(marker) and time.monotonic() < deadline:
        time.sleep(0.01)
    note({"child": child.pid})
if conf.get("exit") is not None:
    sys.exit(conf["exit"])
time.sleep(conf.get("delay", 0.0))
ready_at = time.monotonic() + conf.get("unready_s", 0.0)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, text, kind="application/json"):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        note({"path": self.path})
        if self.path == "/health":
            healthy = conf.get("healthy", True) and time.monotonic() >= ready_at
            # Unready until the test creates the file "ready_file" names, when there is one.
            gated = conf.get("ready_file")
            healthy = healthy and (not gated or os.path.exists(gated))
            self.send(200 if healthy else 503, "{}")
        elif self.path == "/v1/models":
            models = conf.get("models", ["made-up-model"])
            self.send(200, json.dumps({"object": "list", "data": [{"id": m} for m in models]}))
        else:
            self.send(404, "{}")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        note({"path": self.path, "body": json.loads(body or b"null")})
        if conf.get("status"):
            self.send(conf["status"], "{}")
            return
        chunks = conf.get("chunks", [None, "Hi"])
        events = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": c}}]}
            for c in chunks
        ]
        text = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
        print("answered", flush=True)
        self.send(200, text, "text/event-stream")


ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""

# Start-up lines of the server, matching the built-in phase patterns.
VLLM_LINES = (
    "INFO made-up Model loading took 0.5 GiB and 0.25 seconds",
    "INFO made-up init engine (profile, create kv cache, warmup model) took 1.00 seconds",
    "INFO made-up Starting vLLM server on http://0.0.0.0:8000",
)
STARTUP_CASES = (
    "startup/ready_s",
    "startup/first_answer_s",
    "startup/weights_loaded_s",
    "startup/engine_ready_s",
    "startup/server_started_s",
)
MODEL = "made-up-model"
WAITS = Waits(free_s=0.2, release_s=0.2, poll_s=0.01, ready_poll_s=0.02)
READY = Ready(http="/health", timeout_s=20.0)
# A readiness deadline a busy machine does not reach, for a server held unready by a ReadyGate.
GATED_READY = Ready(http="/health", timeout_s=120.0)
# What a ReadyGate of a container launch waits for.
NEED_LINES = "the side's reader took the start-up lines"
NEED_PID = "the side asked the engine for the container's process id"
# How long a late reader holds back each line of the server's output.
LATE_READ_S = 0.2

# Made-up image facts for the container launchers.
REF = "registry.example/server:1"
IMAGE_ID = "sha256:" + "0123456789abcdef" * 4
DIGEST = "fedcba9876543210" * 4
DETAILS: dict[str, Any] = {
    "Id": IMAGE_ID,
    "RepoDigests": [f"registry.example/server@sha256:{DIGEST}"],
    "Os": "linux",
    "Architecture": "arm64",
    "Config": {"Entrypoint": ["/made-up/serve"], "Cmd": ["--made-up-default"]},
}
CONTAINER_PID = 4321
NAME = "pairbench-run-a-0003-new"
# Two reads of the container's cgroup files: 2.5 s of user time, 0.25 s of
# system time, 2 major and 58 minor page faults between them.
CGROUP_BEFORE = (
    "usage_usec 1500000\nuser_usec 1000000\nsystem_usec 500000\n"
    "anon 4096\npgfault 100\npgmajfault 4\n"
)
CGROUP_AFTER = (
    "usage_usec 4250000\nuser_usec 3500000\nsystem_usec 750000\n"
    "anon 8192\npgfault 160\npgmajfault 6\n"
)
CGROUP_TIMING = {"user_s": 2.5, "sys_s": 0.25}
CGROUP_USAGE = {"faults_major": 2.0, "faults_minor": 58.0}


# --- stand-ins -------------------------------------------------------------


class FakeGpu:
    """A GPU probe that answers from lists and records each read in ``log``."""

    def __init__(
        self,
        *,
        counts: Sequence[int | None] = (0,),
        memory: Sequence[float | None] = (1000.0,),
        log: list[str] | None = None,
        tag: Callable[[], str] | None = None,
    ) -> None:
        self.counts = list(counts)
        self.memory = list(memory)
        self.log = log if log is not None else []
        self.tag = tag

    def compute_processes(self, exclude_pids: Sequence[int] = ()) -> int | None:
        self.log.append("gpu_count")
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    def memory_used_mib(self) -> float | None:
        self.log.append("gpu_memory" + (f":{self.tag()}" if self.tag else ""))
        return self.memory.pop(0) if len(self.memory) > 1 else self.memory[0]


class RecordingProcesses(ServerProcesses):
    """Starts processes as the real seam does and records each start."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.starts: list[dict[str, Any]] = []
        self.started: list[ServerProcess] = []

    def start(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str | None = None,
        executable: str | None = None,
        cpus: frozenset[int] | None = None,
    ) -> ServerProcess:
        self.log.append("start")
        self.starts.append(
            {"argv": tuple(argv), "env": dict(env), "executable": executable, "cpus": cpus}
        )
        process = super().start(argv, env=env, cwd=cwd, executable=executable, cpus=cpus)
        self.started.append(process)
        return process


class EngineStandIn(RecordingProcesses):
    """Starts the fake server in place of the engine's ``run`` command, on the published port."""

    def __init__(self, script: Path, conf: Mapping[str, Any], *, host_port: int = 0) -> None:
        super().__init__()
        self.script = script
        self.conf = dict(conf)
        self.host_port = host_port
        self.fail: OSError | None = None

    def start(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str | None = None,
        executable: str | None = None,
        cpus: frozenset[int] | None = None,
    ) -> ServerProcess:
        if self.fail is not None:
            raise self.fail
        words = list(argv)
        port = self.host_port
        if "--publish" in words:
            port = int(words[words.index("--publish") + 1].split(":")[1])
        self.engine_argv = tuple(words)
        self.engine_env = dict(env)
        server = [sys.executable, str(self.script), str(port), json.dumps(self.conf)]
        return super().start(server, env=dict(os.environ), cpus=cpus)


class ReadyGate:
    """Keeps the stand-in server unready until each of ``needs`` is met.

    The server answers its readiness path with 503 while the file ``path`` is
    missing (its ``ready_file``), and the side polls that path until its
    readiness deadline. The gate creates the file once every need is met, so a
    busy machine makes the launch wait longer and changes nothing else.
    """

    def __init__(self, path: Path, needs: Sequence[str]) -> None:
        self.path = path
        self._left = set(needs)
        self._lock = threading.Lock()

    def met(self, need: str) -> None:
        with self._lock:
            self._left.discard(need)
            if not self._left:
                self.path.touch()


class TellingStream:
    """The server's output as the side's log reader takes it; tells a gate when it has taken it.

    The reader takes a line, stamps it with the time and keeps it, then asks
    for the next one. So when it asks for the line after the first ``lines``,
    those are stamped, and the gate hears ``NEED_LINES``. ``delay_s`` holds
    back each line that long, as a reader that runs late on a busy machine does.
    """

    def __init__(
        self, stream: IO[bytes], lines: int, gate: ReadyGate, delay_s: float = 0.0
    ) -> None:
        self._stream = stream
        self._lines = lines
        self._gate = gate
        self._delay_s = delay_s
        self._asked = 0

    def readline(self) -> bytes:
        self._asked += 1
        if self._asked == self._lines + 1:
            self._gate.met(NEED_LINES)
        line = self._stream.readline()
        if line and self._delay_s:
            time.sleep(self._delay_s)
        return line


def read_through(
    monkeypatch: pytest.MonkeyPatch, gate: ReadyGate, lines: int, delay_s: float = 0.0
) -> None:
    """Hand the side's log reader the server's output through a ``TellingStream``."""
    reader = serve.LogReader

    def made(stream: IO[bytes] | None) -> serve.LogReader:
        return reader(None if stream is None else TellingStream(stream, lines, gate, delay_s))  # type: ignore[arg-type]

    monkeypatch.setattr(serve, "LogReader", made)


class FakeEngine:
    """Answers the engine's commands; ``stop`` stops the stand-in server.

    With a ``gate``, the question for the container's process id meets ``NEED_PID``.
    """

    def __init__(
        self,
        *,
        processes: EngineStandIn | None = None,
        images: Mapping[str, dict[str, Any]] | None = None,
        rm_rc: int = 0,
        rm_hangs: bool = False,
        cgroup: Sequence[str] = (CGROUP_BEFORE, CGROUP_AFTER),
        identify_out: str = "v1\n",
        gate: ReadyGate | None = None,
    ) -> None:
        self.processes = processes
        self.images = dict(images if images is not None else {REF: DETAILS})
        self.rm_rc = rm_rc
        self.rm_hangs = rm_hangs
        self.cgroup = list(cgroup)
        self.identify_out = identify_out
        self.gate = gate
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...]) -> Completed:
        self.calls.append(argv)
        verb, rest = argv[1], argv[2:]
        if verb == "version":
            return Completed(0, "9.9.9\n")
        if verb == "info":
            return Completed(0, "{}")
        if verb == "image":
            ref = rest[-1]
            for key, details in self.images.items():
                if ref in (key, details["Id"]):
                    return Completed(0, json.dumps(details))
            return Completed(1, "", f"Error: No such image: {ref}")
        if verb == "pull":
            self.images[rest[-1]] = DETAILS
            return Completed(0)
        if verb == "run":
            return Completed(0, self.identify_out)
        if verb == "inspect":
            if self.gate is not None:
                self.gate.met(NEED_PID)
            return Completed(0, f"{CONTAINER_PID}\n")
        if verb == "exec":
            return Completed(0, self.cgroup.pop(0) if self.cgroup else "")
        if verb == "stop":
            if self.processes is not None:
                for process in self.processes.started:
                    process.signal(signal.SIGTERM)
            return Completed(0)
        if verb == "rm":
            if self.rm_hangs:
                # What the runner gives back for a command it stopped at its timeout.
                return Completed(-9, "", "", timed_out=True)
            return Completed(self.rm_rc, "", "" if self.rm_rc == 0 else "removal in progress")
        raise AssertionError(f"unexpected engine call: {argv}")

    def verbs(self) -> list[str]:
        return [argv[1] for argv in self.calls]


class Runner:
    """A ``CommandRunner`` that hands every call to a ``FakeEngine``."""

    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self.timeouts: list[tuple[tuple[str, ...], float | None]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float | None = None,
    ) -> Completed:
        self.timeouts.append((tuple(argv), timeout_s))
        return self.engine(tuple(argv))


def _which(*found: str) -> Callable[..., str | None]:
    def which(word: str, path: str | None = None) -> str | None:
        return f"/usr/bin/{word}" if word in found else None

    return which


# --- building sides and launches ---------------------------------------------


@pytest.fixture
def script(tmp_path: Path) -> Path:
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def _requests(record: Path) -> list[dict[str, Any]]:
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]


def host_side(
    script: Path, conf: Mapping[str, Any], *, port: int | None = None, **spec: Any
) -> tuple[Side, int]:
    port = port if port is not None else free_port()
    command = (sys.executable, str(script), str(port), json.dumps(conf))
    fields: dict[str, Any] = {"launcher": "host", "command": command, "port": port, "ready": READY}
    fields.update(spec)
    return Side(name="new", kind="serve", spec=ServeSpec(**fields).to_json()), port


def ctx(
    settings: LaunchSettings | None = None,
    *,
    gpu: Any = None,
    mode: str = "warn",
    notes: list[tuple[str, str]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> api.SideContext:
    sink = notes if notes is not None else []
    return api.SideContext(
        run_id="run-a",
        settings=settings or LaunchSettings(),
        environ={"PATH": "/usr/bin", **(environ or {})},
        gpu=gpu,
        mode=mode,  # type: ignore[arg-type]
        note=lambda code, text: sink.append((code, text)),
    )


def request(tmp_path: Path, **extra: Any) -> api.LaunchRequest:
    folder = tmp_path / "launch"
    folder.mkdir(exist_ok=True)
    fields: dict[str, Any] = {
        "run_id": "run-a",
        "seq": 3,
        "phase": "round",
        "round": 1,
        "pos": 1,
        "name": "new",
        "artifacts": folder,
    }
    fields.update(extra)
    return api.LaunchRequest(**fields)


def host_kind(processes: ServerProcesses | None = None) -> ServeKind:
    runner = Runner(FakeEngine())
    host = HostLauncher(runner=runner, processes=processes or RecordingProcesses(), waits=WAITS)
    return ServeKind(runner=runner, launchers={"host": host}, waits=WAITS, which=_which())


class Load:
    """The load callback: records each endpoint and runs ``during`` while the server is up."""

    def __init__(self, during: Callable[[api.Endpoint], None] | None = None) -> None:
        self.endpoints: list[api.Endpoint] = []
        self.during = during

    def __call__(self, endpoint: api.Endpoint) -> None:
        self.endpoints.append(endpoint)
        if self.during is not None:
            self.during(endpoint)


def _gone(pid: int) -> bool:
    """Say whether a process is gone or only waits to be collected."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return text[text.rfind(")") + 2] in "ZX"


# --- one launch on the host --------------------------------------------------


def test_a_launch_runs_the_steps_in_the_order_the_module_docstring_gives(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "requests.jsonl"
    side, port = host_side(script, {"record": str(record), "lines": list(VLLM_LINES)})
    log: list[str] = []
    folder = tmp_path / "launch"
    gpu = FakeGpu(
        memory=(1000.0, 1010.0),
        log=log,
        tag=lambda: "log" if (folder / "server.log").exists() else "nolog",
    )
    seen: list[Any] = []

    def during(endpoint: api.Endpoint) -> None:
        log.append("load")
        seen.append(http_ok(f"{endpoint.base_url}/health", 2.0))
        seen.append([entry["path"] for entry in _requests(record) if "body" in entry])

    kind = host_kind(RecordingProcesses(log))
    resolved = kind.resolve(side, ctx(gpu=gpu))
    outcome = resolved.launch(request(tmp_path, load=Load(during)))
    assert log == ["gpu_count", "gpu_memory:nolog", "start", "load", "gpu_memory:log"]
    assert seen == [True, ["/v1/chat/completions"]]
    assert outcome.rc == 0
    assert outcome.timed_out is False
    assert not http_ok(f"http://127.0.0.1:{port}/health", 0.5)


def test_a_launch_gives_the_start_up_cases_in_seconds(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A phase is timed when the side's reader reads its line, so the server is ready only once
    # the reader has taken the start-up lines, however late a busy machine runs the reader.
    gate = ReadyGate(tmp_path / "ready", (NEED_LINES,))
    read_through(monkeypatch, gate, len(VLLM_LINES))
    conf = {"lines": list(VLLM_LINES), "delay": 0.3, "ready_file": str(gate.path)}
    side, _port = host_side(script, conf, ready=GATED_READY)
    notes: list[tuple[str, str]] = []
    outcome = host_kind().resolve(side, ctx(notes=notes)).launch(request(tmp_path, load=Load()))
    cases = {sample.case: sample for sample in outcome.samples}
    assert tuple(cases) == STARTUP_CASES
    # The reader read every start-up line before the first answer, so no phase is late or lost.
    assert notes == []
    for sample in outcome.samples:
        assert (sample.unit, sample.better, sample.kind) == ("s", "lower", "time")
        assert sample.metric == sample.case.removeprefix("startup/")
    ready = cases["startup/ready_s"].value
    first = cases["startup/first_answer_s"].value
    assert 0.3 <= ready <= first
    for phase in STARTUP_CASES[2:]:
        assert 0.0 <= cases[phase].value <= ready


# How late a slow reader gets each line of the server's output, in seconds.
LATE_S = 0.05
# Ordinary lines the server prints before its start-up lines, so a reader that gets each line
# LATE_S late is still reading them when the first answer comes.
FILLER_LINES = tuple(f"INFO made-up warm-up step {n}" for n in range(40))


class LateOutput:
    """A server's output that reaches the side's reader ``LATE_S`` late per line.

    Each read waits first and then takes one line from the pipe, so the line
    waits in the pipe while the reader sleeps.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def fileno(self) -> int:
        return int(self._stream.fileno())

    def _line(self, *_size: int) -> bytes:
        time.sleep(LATE_S)
        out = bytearray()
        while not out.endswith(b"\n"):
            byte = os.read(self.fileno(), 1)
            if not byte:
                break
            out += byte
        return bytes(out)

    read1 = _line
    readline = _line

    def close(self) -> None:
        self._stream.close()


@pytest.fixture
def late_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every server started in the test gives its output to the side's reader late."""

    def output(process: ServerProcess) -> Any:
        stream = process._popen.stdout
        return None if stream is None else LateOutput(stream)

    monkeypatch.setattr(ServerProcess, "output", property(output))


@pytest.mark.parametrize("launcher", ["host", "docker"])
@pytest.mark.usefixtures("late_output")
def test_the_start_up_phases_do_not_depend_on_the_reader_keeping_up(
    launcher: str, script: Path, tmp_path: Path
) -> None:
    conf = {"lines": [*FILLER_LINES, *VLLM_LINES]}
    if launcher == "host":
        side, _port = host_side(script, conf)
        kind = host_kind()
    else:
        processes = EngineStandIn(script, conf)
        kind = container_kind(FakeEngine(processes=processes), processes)
        side = container_side()
    notes: list[tuple[str, str]] = []
    outcome = kind.resolve(side, ctx(notes=notes)).launch(request(tmp_path, load=Load()))
    assert outcome.rc == 0
    cases = {sample.case: sample.value for sample in outcome.samples}
    assert tuple(cases) == STARTUP_CASES
    # Each phase is timed by when its line was read: after the first answer, by the slow reader.
    first = cases["startup/first_answer_s"]
    assert [cases[phase] > first for phase in STARTUP_CASES[2:]] == [True, True, True]
    # The results say so; the reader caught up, so no phase is left out.
    assert notes == [(NOTE_PHASES_READ_LATE, READ_LATE_MESSAGE)]
    log = (tmp_path / "launch" / api.ARTIFACT_SERVER_LOG).read_text(encoding="utf-8")
    assert log.splitlines()[: len(FILLER_LINES) + len(VLLM_LINES)] == [*FILLER_LINES, *VLLM_LINES]


# What the side says of a launch whose phase lines were read after the first answer.
READ_LATE_MESSAGE = (
    "side new: the lines of the start-up phases weights_loaded, engine_ready, server_started "
    "were read after the server's first answer, so those phases are timed late: a phase is "
    "timed when pairbench reads its line, and the reader of the server's output fell behind; "
    "this note is given once for each side"
)
# How long the phases wait for the reader in the next test, and the most the held reader waits
# to be let go, in seconds.
CATCH_UP_S = 0.2
HELD_S = 60.0
# What the side says of a launch whose reader had not caught up when the phases were read.
LEFT_OUT_MESSAGE = (
    "side new: after a wait of 0.2 s the reader of the server's output had still not read all "
    "the server wrote before its first answer, so the start-up phases without a line read by "
    "then are left out: weights_loaded, engine_ready, server_started have no time; this note "
    "is given once for each side"
)


def test_a_reader_that_has_not_caught_up_leaves_phases_out_and_the_results_say_so(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The side's reader takes nothing until the load starts, which is after the phases are
    # read, so its catch-up runs out of time however fast or slow the machine is.
    let_go = threading.Event()

    class HeldReader(serve.LogReader):
        def _read(self, stream: IO[bytes]) -> None:
            let_go.wait(HELD_S)
            super()._read(stream)

    monkeypatch.setattr(serve, "LogReader", HeldReader)
    monkeypatch.setattr(serve, "READER_CATCH_UP_S", CATCH_UP_S)
    side, _port = host_side(script, {"lines": list(VLLM_LINES)})
    notes: list[tuple[str, str]] = []
    resolved = host_kind().resolve(side, ctx(notes=notes))
    cases: list[list[str]] = []
    try:
        # Two launches of the side: the second leaves its phases out too, and gives no note.
        for seq in (3, 4):
            let_go.clear()
            folder = tmp_path / f"000{seq}-new"
            folder.mkdir()
            load = Load(lambda _endpoint: let_go.set())
            outcome = resolved.launch(request(folder, seq=seq, load=load))
            assert outcome.rc == 0
            cases.append([sample.case for sample in outcome.samples])
    finally:
        let_go.set()

    assert cases == [list(STARTUP_CASES[:2]), list(STARTUP_CASES[:2])]
    assert notes == [(NOTE_PHASES_LEFT_OUT, LEFT_OUT_MESSAGE)]


# The launches whose start-up phases the results hold, and those whose phases they leave out.
MEASURED_PHASES = ("round", "round")
UNMEASURED_PHASES = ("warmup", "explain", "profile", "cost")


@pytest.mark.usefixtures("late_output")
def test_only_a_round_says_its_phases_were_read_late(script: Path, tmp_path: Path) -> None:
    # The results leave out the warm-ups, and the explain step and the profilers resolve each
    # side by themselves and launch it outside the capture, so those launches give no note
    # however late the reader reads; the note comes from the rounds, once for each side.
    side, _port = host_side(script, {"lines": [*FILLER_LINES, *VLLM_LINES]})
    notes: list[tuple[str, str]] = []
    kind = host_kind()
    outside = kind.resolve(side, ctx(notes=notes))
    for seq, phase in enumerate(UNMEASURED_PHASES, start=1):
        folder = tmp_path / f"{seq:04d}-{phase}"
        folder.mkdir()
        launched = outside.launch(
            request(folder, seq=seq, phase=phase, round=0, pos=None, load=Load())
        )
        assert launched.rc == 0
        first = {s.case: s.value for s in launched.samples}["startup/first_answer_s"]
        late = [s.case for s in launched.samples if s.case in STARTUP_CASES[2:]]
        assert [{s.case: s.value for s in launched.samples}[c] > first for c in late] == [
            True,
            True,
            True,
        ]
    assert notes == []

    measured = kind.resolve(side, ctx(notes=notes))
    for seq, phase in enumerate(MEASURED_PHASES, start=len(UNMEASURED_PHASES) + 1):
        folder = tmp_path / f"{seq:04d}-{phase}"
        folder.mkdir()
        launched = measured.launch(request(folder, seq=seq, phase=phase, load=Load()))
        assert launched.rc == 0
    assert notes == [(NOTE_PHASES_READ_LATE, READ_LATE_MESSAGE)]


@pytest.mark.parametrize("phase", UNMEASURED_PHASES)
def test_a_launch_the_results_leave_out_leaves_phases_out_without_a_note(
    phase: str, script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    let_go = threading.Event()

    class HeldReader(serve.LogReader):
        def _read(self, stream: IO[bytes]) -> None:
            let_go.wait(HELD_S)
            super()._read(stream)

    monkeypatch.setattr(serve, "LogReader", HeldReader)
    monkeypatch.setattr(serve, "READER_CATCH_UP_S", CATCH_UP_S)
    side, _port = host_side(script, {"lines": list(VLLM_LINES)})
    notes: list[tuple[str, str]] = []
    resolved = host_kind().resolve(side, ctx(notes=notes))
    try:
        load = Load(lambda _endpoint: let_go.set())
        launched = resolved.launch(
            request(tmp_path, seq=1, phase=phase, round=0, pos=None, load=load)
        )
    finally:
        let_go.set()

    assert launched.rc == 0
    assert [sample.case for sample in launched.samples] == list(STARTUP_CASES[:2])
    assert notes == []


def test_the_first_answer_names_the_model_of_the_list_and_skips_empty_chunks(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "requests.jsonl"
    side, port = host_side(script, {"record": str(record), "chunks": [None, "", "Hi"]})
    load = Load()
    host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    posted = [entry for entry in _requests(record) if "body" in entry]
    assert posted == [{"path": "/v1/chat/completions", "body": probe_body(MODEL)}]
    assert posted[0]["body"] == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Say hello."}],
        "max_tokens": 8,
        "stream": True,
    }
    assert load.endpoints == [api.Endpoint(base_url=f"http://127.0.0.1:{port}", model_name=MODEL)]


def test_the_model_name_of_the_config_is_used_without_asking_the_list(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "requests.jsonl"
    side, _port = host_side(script, {"record": str(record)}, model_name="named-model")
    load = Load()
    host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    paths = [entry["path"] for entry in _requests(record)]
    assert "/v1/models" not in paths
    assert [entry["body"]["model"] for entry in _requests(record) if "body" in entry] == [
        "named-model"
    ]
    assert load.endpoints[0].model_name == "named-model"


def test_a_request_body_of_the_config_is_sent_as_given(script: Path, tmp_path: Path) -> None:
    record = tmp_path / "requests.jsonl"
    body = {"prompt": "x", "max_tokens": 1}
    side, _port = host_side(
        script, {"record": str(record)}, probe=Probe(path="/v1/completions", body=body)
    )
    load = Load()
    host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    posted = [entry for entry in _requests(record) if "body" in entry]
    assert posted == [{"path": "/v1/completions", "body": body}]
    # The load tool still learns the model, from the server's list.
    assert load.endpoints[0].model_name == MODEL


def test_the_server_log_holds_what_the_server_printed(script: Path, tmp_path: Path) -> None:
    side, _port = host_side(script, {"lines": list(VLLM_LINES)})
    host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    text = (tmp_path / "launch" / "server.log").read_text(encoding="utf-8")
    assert text.splitlines() == [*VLLM_LINES, "answered", "stopping"]


def test_a_server_that_exits_before_it_is_ready_is_a_failed_launch(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {"exit": 3, "lines": ["made-up failure"]})
    load = Load()
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert (outcome.rc, outcome.timed_out) == (3, False)
    assert outcome.samples == ()
    assert load.endpoints == []
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the server exited with 3 before it was ready\n"
    assert (tmp_path / "launch" / "server.log").read_text(encoding="utf-8") == "made-up failure\n"


def test_the_message_of_a_failed_launch_is_written_owner_only_whatever_the_umask(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {"exit": 3, "lines": ["made-up failure"]})
    first = os.umask(0o022)
    try:
        outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    finally:
        os.umask(first)
    assert outcome.rc == 3
    stderr = tmp_path / "launch" / "stderr.txt"
    assert stderr.read_text(encoding="utf-8") == (
        "pairbench: the server exited with 3 before it was ready\n"
    )
    assert stat.S_IMODE(stderr.stat().st_mode) == 0o600


def test_a_server_that_never_becomes_ready_times_out_and_is_stopped(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()
    side, _port = host_side(script, {"healthy": False}, ready=Ready(timeout_s=0.6))
    load = Load()
    outcome = host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert (outcome.rc, outcome.timed_out) == (1, True)
    assert load.endpoints == []
    assert outcome.timing[api.TIMING_RUN_S] >= 0.6
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the server did not pass its readiness check within 0.6 s\n"
    assert _gone(processes.started[0].pid)


def test_a_server_whose_answer_holds_no_text_is_a_failed_launch(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {"chunks": [None, ""]})
    load = Load()
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert (outcome.rc, outcome.timed_out) == (1, False)
    assert load.endpoints == []
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the server's answer ended without text\n"


def test_an_error_status_of_the_first_answer_is_a_failed_launch(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {"status": 500})
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert (outcome.rc, outcome.timed_out) == (1, False)
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the first-answer request was answered with status 500\n"


def test_no_model_in_the_config_or_the_list_is_a_failed_launch(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {"models": []})
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert (outcome.rc, outcome.timed_out) == (1, False)
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == (
        "pairbench: the config names no model and the server's /v1/models list gave none\n"
    )


def test_a_failed_load_still_stops_the_server_and_writes_its_log(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()

    def during(endpoint: api.Endpoint) -> None:
        raise KeyboardInterrupt

    side, port = host_side(script, {})
    with pytest.raises(KeyboardInterrupt):
        host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=Load(during)))
    assert _gone(processes.started[0].pid)
    assert not http_ok(f"http://127.0.0.1:{port}/health", 0.5)
    assert (tmp_path / "launch" / "server.log").read_text(encoding="utf-8").endswith("stopping\n")


def test_a_server_that_exits_during_the_load_is_a_failed_launch(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()

    def during(endpoint: api.Endpoint) -> None:
        # The fake server exits with 0 on the stop signal.
        processes.started[0].signal(signal.SIGTERM)
        assert processes.started[0].ended(10.0)

    side, _port = host_side(script, {})
    load = Load(during)
    outcome = host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert (outcome.rc, outcome.timed_out) == (1, False)
    assert len(load.endpoints) == 1
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the server exited with 0 during the load\n"


def test_the_launch_timeout_bounds_the_wait_for_readiness(script: Path, tmp_path: Path) -> None:
    processes = RecordingProcesses()
    # The readiness check alone would wait its 20 s.
    side, _port = host_side(script, {"healthy": False})
    load = Load()
    began = time.monotonic()
    outcome = (
        host_kind(processes)
        .resolve(side, ctx(LaunchSettings(timeout_s=1.0)))
        .launch(request(tmp_path, load=load))
    )
    assert (outcome.rc, outcome.timed_out) == (1, True)
    assert time.monotonic() - began < 10.0
    assert load.endpoints == []
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == (
        "pairbench: the launch ran into its timeout of 1 s before the server was ready\n"
    )
    assert _gone(processes.started[0].pid)


def test_the_load_is_handed_the_end_of_the_launch_timeout(script: Path, tmp_path: Path) -> None:
    side, _port = host_side(script, {})
    load = Load()
    began = time.monotonic()
    outcome = (
        host_kind()
        .resolve(side, ctx(LaunchSettings(timeout_s=30.0)))
        .launch(request(tmp_path, load=load))
    )
    ended = time.monotonic()
    assert (outcome.rc, outcome.timed_out) == (0, False)
    (endpoint,) = load.endpoints
    assert endpoint.deadline is not None
    assert began + 30.0 <= endpoint.deadline <= ended + 30.0


def test_without_a_launch_timeout_the_load_has_no_end(script: Path, tmp_path: Path) -> None:
    side, _port = host_side(script, {})
    load = Load()
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert outcome.rc == 0
    assert [endpoint.deadline for endpoint in load.endpoints] == [None]


def test_a_load_that_runs_past_the_launch_timeout_is_a_timed_out_launch(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()

    def during(endpoint: api.Endpoint) -> None:
        assert endpoint.deadline is not None
        time.sleep(max(0.0, endpoint.deadline - time.monotonic()) + 0.1)

    side, _port = host_side(script, {})
    outcome = (
        host_kind(processes)
        .resolve(side, ctx(LaunchSettings(timeout_s=1.0)))
        .launch(request(tmp_path, load=Load(during)))
    )
    assert (outcome.rc, outcome.timed_out) == (1, True)
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: the launch ran into its timeout of 1 s during the load\n"
    assert _gone(processes.started[0].pid)


@contextlib.contextmanager
def foreign_server(script: Path, record: Path) -> Any:
    """A server this launch did not start, answering on a port of the loopback address."""
    port = free_port()
    conf = json.dumps({"record": str(record)})
    process = subprocess.Popen(
        [sys.executable, str(script), str(port), conf], stdout=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 10.0
        while not http_ok(f"http://127.0.0.1:{port}/health", 0.5):
            assert time.monotonic() < deadline, "the foreign server did not come up"
            time.sleep(0.02)
        yield port
    finally:
        process.terminate()
        process.wait(10.0)


def _port_taken(port: int) -> str:
    return (
        f"pairbench: side 'new': something already answers on port {port} of the loopback "
        "address, so a server started there could not be told apart from it\n"
    )


def test_a_host_port_that_already_answers_is_a_failed_launch_and_nothing_starts(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "foreign.jsonl"
    processes = RecordingProcesses()
    load = Load()
    with foreign_server(script, record) as port:
        # Started anyway, this server would bind its port only after 30 s.
        side, _port = host_side(script, {"delay": 30.0}, port=port)
        outcome = host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=load))
    assert (outcome.rc, outcome.timed_out) == (1, False)
    assert processes.starts == []
    assert load.endpoints == []
    assert [entry for entry in _requests(record) if "body" in entry] == []
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == _port_taken(port)


def test_what_the_server_left_running_is_stopped_with_it(script: Path, tmp_path: Path) -> None:
    record = tmp_path / "requests.jsonl"
    side, _port = host_side(script, {"record": str(record), "child": True})
    began = time.monotonic()
    host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    took = time.monotonic() - began
    child = next(entry["child"] for entry in _requests(record) if "child" in entry)
    try:
        deadline = time.monotonic() + 5.0
        while not _gone(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _gone(child)
        assert took < 20.0
    finally:
        _kill(child)


def _child_of(record: Path) -> int:
    return int(next(entry["child"] for entry in _requests(record) if "child" in entry))


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while not _gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return _gone(pid)


def test_what_a_server_that_exited_before_it_was_ready_left_running_is_stopped(
    script: Path, tmp_path: Path
) -> None:
    # The server starts a child that ignores the stop signal, then exits with 3.
    record = tmp_path / "requests.jsonl"
    side, _port = host_side(script, {"record": str(record), "child": True, "exit": 3})
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    child = _child_of(record)
    try:
        assert (outcome.rc, outcome.timed_out) == (3, False)
        assert _wait_gone(child)
    finally:
        _kill(child)


def test_what_a_server_that_exited_during_the_load_left_running_is_stopped(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "requests.jsonl"
    processes = RecordingProcesses()

    def during(endpoint: api.Endpoint) -> None:
        # The fake server exits with 0 on the stop signal; its child ignores it.
        os.kill(processes.started[0].pid, signal.SIGTERM)
        assert processes.started[0].ended(10.0)

    side, _port = host_side(script, {"record": str(record), "child": True})
    load = Load(during)
    outcome = host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=load))
    child = _child_of(record)
    try:
        assert (outcome.rc, outcome.timed_out) == (1, False)
        assert _wait_gone(child)
    finally:
        _kill(child)


def test_a_process_that_left_the_server_s_session_does_not_hold_up_the_stop(
    script: Path, tmp_path: Path
) -> None:
    # It keeps the server's output open; the launch ends without waiting for it.
    record = tmp_path / "requests.jsonl"
    side, _port = host_side(script, {"record": str(record), "daemon": True, "lines": ["one"]})
    began = time.monotonic()
    try:
        outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
        took = time.monotonic() - began
    finally:
        for entry in _requests(record):
            if "child" in entry:
                _kill(entry["child"])
    assert outcome.rc == 0
    assert took < 20.0
    log = (tmp_path / "launch" / "server.log").read_text(encoding="utf-8").splitlines()
    assert log[0] == "one"


def _kill(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)


def test_a_host_launch_reports_the_server_s_cpu_time_and_first_process(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()
    side, _port = host_side(script, {})
    outcome = host_kind(processes).resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert outcome.pid == processes.started[0].pid
    assert isinstance(outcome.cpu_s, float)
    assert outcome.cpu_s > 0.0
    assert outcome.timing[api.TIMING_LAUNCH_S] >= outcome.timing[api.TIMING_RUN_S] > 0.0


def test_a_host_launch_gives_the_session_s_figures_of_the_load_phase(
    script: Path, tmp_path: Path
) -> None:
    side, _port = host_side(script, {})
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert set(outcome.timing) == {"run_s", "launch_s", "user_s", "sys_s"}
    assert set(outcome.usage) == {
        "faults_minor",
        "faults_major",
        "ctx_voluntary",
        "ctx_involuntary",
    }
    assert "rss_peak_bytes" not in outcome.usage


def test_a_server_command_that_cannot_start_reports_127(script: Path, tmp_path: Path) -> None:
    class Failing(ServerProcesses):
        def start(self, argv: Sequence[str], **kwargs: Any) -> ServerProcess:
            raise PermissionError(13, "Permission denied", "/made-up/server")

    side, _port = host_side(script, {})
    outcome = host_kind(Failing()).resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert outcome.rc == 127
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert (
        stderr == "pairbench: side 'new': the server command could not be started: "
        "Permission denied\n"
    )


def test_a_serving_launch_is_never_asked_for_a_second_command(script: Path, tmp_path: Path) -> None:
    side, _port = host_side(script, {})
    resolved = host_kind().resolve(side, ctx())
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, second=api.PreparedRun(argv=("x",))))
    assert (caught.value.code, caught.value.exit_code) == ("E_INTERNAL", EXIT_INTERNAL)


def test_two_servers_never_run_at_the_same_time(script: Path, tmp_path: Path) -> None:
    events: list[str] = []
    first_side, _ = host_side(script, {})
    second_side, _ = host_side(script, {})
    kind = host_kind()
    first = kind.resolve(first_side, ctx())
    second = kind.resolve(second_side, ctx())
    threads: list[threading.Thread] = []

    def other(endpoint: api.Endpoint) -> None:
        events.append("second load")

    def during(endpoint: api.Endpoint) -> None:
        events.append("first load begins")
        folder = tmp_path / "second"
        folder.mkdir()
        thread = threading.Thread(
            target=second.launch, args=(request(folder, seq=4, load=Load(other)),)
        )
        thread.start()
        threads.append(thread)
        time.sleep(0.5)
        events.append("first load ends")

    first.launch(request(tmp_path, load=Load(during)))
    threads[0].join(30.0)
    assert events == ["first load begins", "first load ends", "second load"]


# --- the GPU waits -----------------------------------------------------------


def test_a_busy_gpu_under_enforce_is_refused_before_the_start(script: Path, tmp_path: Path) -> None:
    processes = RecordingProcesses()
    side, _port = host_side(script, {})
    resolved = host_kind(processes).resolve(side, ctx(gpu=FakeGpu(counts=(1,)), mode="enforce"))
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, load=Load()))
    assert (caught.value.code, caught.value.exit_code) == ("E_GATE_FAILED", EXIT_MACHINE)
    assert processes.starts == []


def test_a_busy_gpu_under_warn_gives_a_loud_note_and_goes_on(script: Path, tmp_path: Path) -> None:
    notes: list[tuple[str, str]] = []
    side, _port = host_side(script, {})
    resolved = host_kind().resolve(side, ctx(gpu=FakeGpu(counts=(1,)), notes=notes))
    outcome = resolved.launch(request(tmp_path, load=Load()))
    assert outcome.rc == 0
    assert [code for code, _text in notes] == [NOTE_GPU_BUSY_BEFORE_START]
    assert NOTE_GPU_BUSY_BEFORE_START == "gpu_busy_before_start"


def test_a_gpu_that_frees_up_in_time_gives_no_note(script: Path, tmp_path: Path) -> None:
    notes: list[tuple[str, str]] = []
    gpu = FakeGpu(counts=(2, 1, 0))
    side, _port = host_side(script, {})
    outcome = (
        host_kind().resolve(side, ctx(gpu=gpu, notes=notes)).launch(request(tmp_path, load=Load()))
    )
    assert outcome.rc == 0
    assert notes == []
    assert gpu.log.count("gpu_count") == 3


def test_the_run_time_starts_at_the_server_start_not_at_the_gpu_wait(
    script: Path, tmp_path: Path
) -> None:
    class SlowGpu(FakeGpu):
        def compute_processes(self, exclude_pids: Sequence[int] = ()) -> int | None:
            time.sleep(0.3)
            return super().compute_processes(exclude_pids)

    side, _port = host_side(script, {})
    outcome = host_kind().resolve(side, ctx(gpu=SlowGpu())).launch(request(tmp_path, load=Load()))
    assert outcome.rc == 0
    assert outcome.timing[api.TIMING_LAUNCH_S] - outcome.timing[api.TIMING_RUN_S] >= 0.3


def test_a_plug_in_launcher_that_fails_with_status_0_is_still_a_failed_launch(
    tmp_path: Path,
) -> None:
    class Refusing:
        name = "made-up"
        api_version = 1

        def resolve(self, spec: ServeSpec, ctx: api.SideContext) -> Mapping[str, Any]:
            return {"made_up": "1"}

        def look_up(self, spec: ServeSpec, ctx: api.SideContext) -> api.SideLookup:
            return api.SideLookup(status="identified", identity={"made_up": "1"})

        def start(
            self, spec: ServeSpec, ctx: api.SideContext, request: api.LaunchRequest
        ) -> api.ServerHandle:
            raise Refusal("E_LAUNCH_FAILED", "made-up start failure", detail={"rc": 0})

    runner = Runner(FakeEngine())
    kind = ServeKind(runner=runner, launchers={"made-up": Refusing()}, waits=WAITS, which=_which())
    side = Side(name="new", kind="serve", spec=ServeSpec(launcher="made-up", image=REF).to_json())
    outcome = kind.resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert outcome.rc == 127
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == "pairbench: made-up start failure\n"


def test_gpu_memory_that_is_not_released_is_refused_after_the_stop(
    script: Path, tmp_path: Path
) -> None:
    processes = RecordingProcesses()
    gpu = FakeGpu(memory=(1000.0, 1064.5))
    side, _port = host_side(script, {})
    resolved = host_kind(processes).resolve(side, ctx(gpu=gpu))
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, load=Load()))
    assert (caught.value.code, caught.value.exit_code) == ("E_GPU_NOT_RELEASED", EXIT_LAUNCH)
    assert caught.value.detail == {"level_mib": 1000.0, "used_mib": 1064.5, "tolerance_mib": 64.0}
    assert _gone(processes.started[0].pid)
    assert (tmp_path / "launch" / "server.log").exists()


def test_gpu_memory_within_the_tolerance_counts_as_released(script: Path, tmp_path: Path) -> None:
    gpu = FakeGpu(memory=(1000.0, 1064.0))
    side, _port = host_side(script, {})
    outcome = host_kind().resolve(side, ctx(gpu=gpu)).launch(request(tmp_path, load=Load()))
    assert outcome.rc == 0


def test_unreadable_gpu_memory_gives_a_note_and_no_release_wait(
    script: Path, tmp_path: Path
) -> None:
    notes: list[tuple[str, str]] = []
    gpu = FakeGpu(memory=(None,))
    side, _port = host_side(script, {})
    outcome = (
        host_kind().resolve(side, ctx(gpu=gpu, notes=notes)).launch(request(tmp_path, load=Load()))
    )
    assert outcome.rc == 0
    assert [code for code, _text in notes] == [NOTE_GPU_MEMORY_UNREADABLE]
    assert gpu.log == ["gpu_count", "gpu_memory"]


def test_an_unreadable_gpu_process_count_is_taken_as_busy_at_once(
    script: Path, tmp_path: Path
) -> None:
    gpu = FakeGpu(counts=(None,))
    side, _port = host_side(script, {})
    resolved = host_kind().resolve(side, ctx(gpu=gpu, mode="enforce"))
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, load=Load()))
    assert (caught.value.code, caught.value.exit_code) == ("E_GATE_FAILED", EXIT_MACHINE)
    assert gpu.log == ["gpu_count"]


# --- explain launches and pinning ----------------------------------------------


def test_an_explain_launch_on_the_host_starts_the_wrapped_command(
    script: Path, tmp_path: Path
) -> None:
    handed: list[tuple[str, ...]] = []

    def wrap(argv: Sequence[str]) -> api.InstrumentedCommand:
        handed.append(tuple(argv))
        return api.InstrumentedCommand(argv=(*argv, "wrapped"), env={"MADE_UP_WRAP": "1"})

    side, port = host_side(script, {})
    outcome = (
        host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load(), wrap_server=wrap))
    )
    assert outcome.rc == 0
    assert handed == [(sys.executable, str(script), str(port), "{}")]
    log = (tmp_path / "launch" / "server.log").read_text(encoding="utf-8").splitlines()
    assert log[:2] == ["tag wrapped", "wrap-env 1"]


@pytest.mark.skipif(
    not hasattr(os, "sched_setaffinity"), reason="needs a platform that lets a process pick CPUs"
)
def test_a_pinned_host_server_runs_on_its_cpus_and_the_load_outside_them(
    script: Path, tmp_path: Path
) -> None:
    mine = os.sched_getaffinity(0)
    if len(mine) < 2:
        pytest.skip("needs at least two CPUs this test may run on")
    pinned = min(mine)
    processes = RecordingProcesses()
    seen: list[set[int]] = []

    def during(endpoint: api.Endpoint) -> None:
        seen.append(os.sched_getaffinity(processes.started[0].pid))
        seen.append(os.sched_getaffinity(0))

    side, _port = host_side(script, {})
    resolved = host_kind(processes).resolve(side, ctx(LaunchSettings(cpus=str(pinned))))
    outcome = resolved.launch(request(tmp_path, load=Load(during)))
    assert outcome.rc == 0
    assert processes.starts[0]["cpus"] == frozenset({pinned})
    assert seen == [{pinned}, mine]


@pytest.mark.skipif(
    not hasattr(os, "sched_setaffinity"), reason="needs a platform that pins processes to CPUs"
)
def test_an_unpinned_host_server_runs_where_the_tool_ran_when_the_side_was_resolved(
    script: Path, tmp_path: Path
) -> None:
    mine = os.sched_getaffinity(0)
    if len(mine) < 2:
        pytest.skip("needs at least two CPUs this test may run on")
    processes = RecordingProcesses()
    seen: list[set[int]] = []

    def during(endpoint: api.Endpoint) -> None:
        seen.append(os.sched_getaffinity(processes.started[0].pid))

    side, _port = host_side(script, {})
    resolved = host_kind(processes).resolve(side, ctx(LaunchSettings()))
    # The tool moves itself off another side's pinned CPU after the sides are resolved.
    os.sched_setaffinity(0, {max(mine)})
    try:
        outcome = resolved.launch(request(tmp_path, load=Load(during)))
    finally:
        os.sched_setaffinity(0, mine)
    assert outcome.rc == 0
    assert processes.starts[0]["cpus"] == frozenset(mine)
    assert seen == [mine]


# --- identity, look-up and the launcher choice ---------------------------------


def test_a_host_server_is_identified_by_its_executable_and_its_command_line(
    script: Path,
) -> None:
    side, _port = host_side(script, {})
    kind = host_kind()
    resolved = kind.resolve(side, ctx())
    identity = dict(resolved.side.identity)
    assert set(identity) == {"executable", "executable_sha256", "argv_sha256"}
    assert identity["executable"] == os.path.abspath(sys.executable)
    looked = kind.look_up(side, ctx())
    assert looked.status == "identified"
    assert dict(looked.identity) == identity
    assert looked.fingerprint == resolved.side.fingerprint
    assert resolved.side.fingerprint == fingerprint_of(
        identity, LaunchSettings().effective(args=side.serve_spec().command, env={})
    )


def test_a_host_server_s_command_line_is_hashed_with_its_secrets_hidden(script: Path) -> None:
    kind = host_kind()
    found = [
        kind.resolve(host_side(script, {}, port=8000, args=("--api-key", word))[0], ctx()).side
        for word in ("kiwi7", "plum4", HIDDEN)
    ]
    assert len({side.identity["argv_sha256"] for side in found}) == 1
    assert len({side.fingerprint for side in found}) == 1
    other = kind.resolve(host_side(script, {}, port=8000, args=("--size", "2"))[0], ctx()).side
    assert other.identity["argv_sha256"] != found[0].identity["argv_sha256"]


def test_a_host_server_with_an_image_is_a_usage_error(script: Path) -> None:
    side, _port = host_side(script, {}, image=REF)
    with pytest.raises(Refusal) as caught:
        host_kind().resolve(side, ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


def test_a_host_server_whose_command_is_missing_is_unresolved(tmp_path: Path) -> None:
    spec = ServeSpec(launcher="host", command=(str(tmp_path / "no-such-server"),), port=8000)
    side = Side(name="new", kind="serve", spec=spec.to_json())
    with pytest.raises(Refusal) as caught:
        host_kind().resolve(side, ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert "no-such-server" in caught.value.message
    assert str(tmp_path) not in caught.value.message


def test_a_host_server_whose_command_may_run_but_not_be_read_is_a_side_refusal(
    tmp_path: Path,
) -> None:
    server = tmp_path / "made-up-server"
    server.write_text("#!/bin/sh\nexit 0\n")
    server.chmod(0o111)
    if os.access(server, os.R_OK):
        pytest.skip("this user reads a file without read permission (the superuser does)")
    spec = ServeSpec(launcher="host", command=(str(server),), port=8000)
    side = Side(name="new", kind="serve", spec=spec.to_json())
    for call in (host_kind().look_up, host_kind().resolve):
        with pytest.raises(Refusal) as caught:
            call(side, ctx())
        assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)
        assert caught.value.message == (
            "side 'new': the server command 'made-up-server' cannot be read, so its hash cannot "
            "be recorded"
        )


def test_a_server_without_an_image_or_a_launcher_is_a_usage_error() -> None:
    side = Side(name="new", kind="serve", spec=ServeSpec(command=("x",)).to_json())
    with pytest.raises(Refusal) as caught:
        host_kind().resolve(side, ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


@pytest.mark.parametrize(
    ("phases", "bad"),
    [({"ready": "x"}, "ready"), ({"Weights": "x"}, "Weights"), ({"weights": "("}, "weights")],
)
def test_a_bad_start_up_phase_is_a_usage_error(
    script: Path, phases: dict[str, str], bad: str
) -> None:
    side, _port = host_side(script, {}, phases=phases)
    with pytest.raises(Refusal) as caught:
        host_kind().resolve(side, ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert repr(bad) in caught.value.message


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (
            {"ready": Ready(http="health", timeout_s=20.0)},
            "side 'new': serve.ready.http is a path on the server, starting with '/' and "
            "holding no space or control character: 'health'",
        ),
        (
            {"probe": Probe(path="@made-up.example/v1")},
            "side 'new': serve.probe.path is a path on the server, starting with '/' and "
            "holding no space or control character: '@made-up.example/v1'",
        ),
        (
            {"probe": Probe(path="/v1/chat completions")},
            "side 'new': serve.probe.path is a path on the server, starting with '/' and "
            "holding no space or control character: '/v1/chat completions'",
        ),
    ],
)
def test_a_server_path_that_is_not_a_path_is_a_usage_error_before_any_start(
    script: Path, tmp_path: Path, spec: dict[str, Any], message: str
) -> None:
    processes = RecordingProcesses()
    side, _port = host_side(script, {}, **spec)
    kind = host_kind(processes)
    for call in (kind.look_up, kind.resolve):
        with pytest.raises(Refusal) as caught:
            call(side, ctx())
        assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
        assert caught.value.message == message
    assert processes.starts == []


def test_phases_of_the_config_replace_the_built_in_ones(script: Path, tmp_path: Path) -> None:
    lines = [*VLLM_LINES, "made-up weights are in"]
    side, _port = host_side(script, {"lines": lines}, phases={"weights": "weights are in"})
    outcome = host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    assert [s.case for s in outcome.samples] == [
        "startup/ready_s",
        "startup/first_answer_s",
        "startup/weights_s",
    ]


def test_a_host_side_runs_in_no_container() -> None:
    side = Side(name="new", kind="serve", spec=ServeSpec(launcher="host", command=("x",)).to_json())
    assert side.serve_spec().launcher == "host"
    resolved = serve.ServeResolved(
        side=side,
        spec=side.serve_spec(),
        start_spec=side.serve_spec(),
        launcher=HostLauncher(),
        ctx=ctx(),
        engine=None,
        waits=WAITS,
    )
    assert resolved.in_container is False
    assert resolved.artifacts_in_side(Path("made-up")) == os.path.abspath("made-up")
    assert resolved.cannot_repeat is None
    assert resolved.command is None


# --- container launchers ---------------------------------------------------------


def container_side(**spec: Any) -> Side:
    fields: dict[str, Any] = {"image": REF, "ready": READY}
    fields.update(spec)
    return Side(name="new", kind="serve", spec=ServeSpec(**fields).to_json())


def container_kind(
    engine: FakeEngine,
    processes: ServerProcesses | None = None,
    *,
    found: tuple[str, ...] = ("docker",),
) -> ServeKind:
    runner = Runner(engine)
    which = _which(*found)
    launchers: dict[str, api.Launcher] = {
        "docker": DockerLauncher(runner=runner, processes=processes, waits=WAITS, which=which),
        "podman": PodmanLauncher(runner=runner, processes=processes, waits=WAITS, which=which),
    }
    return ServeKind(runner=runner, launchers=launchers, waits=WAITS, which=which)


def test_a_container_server_is_identified_by_image_and_arguments() -> None:
    kind = container_kind(FakeEngine())
    side = container_side(args=("--made-up", "1"))
    resolved = kind.resolve(side, ctx())
    identity = dict(resolved.side.identity)
    assert identity["image_id"] == IMAGE_ID
    assert list(identity["digests"]) == [f"sha256:{DIGEST}"]
    assert identity["platform"] == "linux/arm64"
    assert set(identity) >= {"image_id", "digests", "platform", "args_sha256"}
    looked = kind.look_up(side, ctx())
    assert (looked.status, looked.fingerprint) == ("identified", resolved.side.fingerprint)
    assert resolved.engine is not None
    assert (resolved.engine.name, resolved.engine.version) == ("docker", "9.9.9")
    other = kind.resolve(container_side(args=("--made-up", "2")), ctx())
    assert other.side.fingerprint != resolved.side.fingerprint


@pytest.mark.parametrize(
    "spec",
    [
        lambda word: {"args": ("--api-key", word)},
        lambda word: {"args": ("--made-up", "1"), "env": {"HF_TOKEN": word}},
        lambda word: {"env": {"MADE_UP_URL": f"https://madeup:{word}@made-up.example/"}},
    ],
    ids=["argument", "credential-variable", "address-in-a-variable"],
)
def test_a_container_server_is_hashed_with_its_secrets_hidden(
    spec: Callable[[str], dict[str, Any]],
) -> None:
    kind = container_kind(FakeEngine())
    found = [
        kind.resolve(container_side(**spec(word)), ctx()).side
        for word in ("kiwi7", "plum4", HIDDEN)
    ]
    assert len({side.identity["args_sha256"] for side in found}) == 1
    assert len({side.fingerprint for side in found}) == 1


def test_the_model_location_of_a_container_server_is_part_of_its_fingerprint(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "model-a", tmp_path / "model-b"
    first.mkdir()
    second.mkdir()
    kind = container_kind(FakeEngine())
    one = kind.resolve(container_side(model=str(first)), ctx())
    again = kind.resolve(container_side(model=str(first)), ctx())
    other = kind.resolve(container_side(model=str(second)), ctx())
    assert one.side.fingerprint == again.side.fingerprint
    assert one.side.fingerprint != other.side.fingerprint
    looked = kind.look_up(container_side(model=str(second)), ctx())
    assert looked.fingerprint == other.side.fingerprint


def test_a_look_up_with_an_identify_command_gives_no_fingerprint() -> None:
    kind = container_kind(FakeEngine())
    looked = kind.look_up(container_side(), ctx(LaunchSettings(identify=("serve", "--version"))))
    assert looked.status == "identified"
    assert looked.fingerprint == ""


def test_the_identify_container_of_a_server_is_removed_with_a_bounded_wait() -> None:
    engine = FakeEngine()
    runner = Runner(engine)
    which = _which("docker")
    launcher = DockerLauncher(runner=runner, waits=WAITS, which=which)
    kind = ServeKind(runner=runner, launchers={"docker": launcher}, waits=WAITS, which=which)
    kind.resolve(container_side(), ctx(LaunchSettings(identify=("serve", "--version"))))
    removals = [timeout for argv, timeout in runner.timeouts if argv[1] == "rm"]
    assert removals == [REMOVE_WAIT_S]


def test_a_look_up_of_an_absent_image_pulls_nothing() -> None:
    engine = FakeEngine(images={})
    looked = container_kind(engine).look_up(container_side(), ctx())
    assert looked.status == "absent"
    assert "pull" not in engine.verbs()


def test_a_look_up_without_an_engine_is_unchecked() -> None:
    looked = container_kind(FakeEngine(), found=()).look_up(container_side(), ctx())
    assert looked.status == "unchecked"


def test_resolve_pulls_a_missing_image_and_refuses_under_pull_never() -> None:
    engine = FakeEngine(images={})
    container_kind(engine).resolve(container_side(), ctx())
    assert "pull" in engine.verbs()
    with pytest.raises(Refusal) as caught:
        container_kind(FakeEngine(images={})).resolve(
            container_side(), ctx(LaunchSettings(pull="never"))
        )
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert REF not in caught.value.message


def test_the_engine_the_settings_name_picks_the_launcher() -> None:
    engine = FakeEngine()
    resolved = container_kind(engine, found=("docker", "podman")).resolve(
        container_side(), ctx(LaunchSettings(engine="podman"))
    )
    assert resolved.engine is not None
    assert resolved.engine.name == "podman"


def test_a_server_on_the_network_none_is_refused() -> None:
    with pytest.raises(Refusal) as caught:
        container_kind(FakeEngine()).resolve(container_side(), ctx(LaunchSettings(network="none")))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_a_container_launch_is_named_labelled_published_and_removed(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    weights = tmp_path / "weights"
    weights.mkdir()
    # The server is ready only once the side has stamped its start-up lines and asked for
    # the container's process id, however late a busy machine runs the side's threads.
    gate = ReadyGate(tmp_path / "ready", (NEED_LINES, NEED_PID))
    read_through(monkeypatch, gate, len(VLLM_LINES))
    processes = EngineStandIn(script, {"lines": list(VLLM_LINES), "ready_file": str(gate.path)})
    engine = FakeEngine(processes=processes, gate=gate)
    side = container_side(model=str(weights), args=("--made-up", "1"), ready=GATED_READY)
    load = Load()
    outcome = (
        container_kind(engine, processes).resolve(side, ctx()).launch(request(tmp_path, load=load))
    )
    assert outcome.rc == 0
    argv = list(processes.engine_argv)
    port = int(argv[argv.index("--publish") + 1].split(":")[1])
    folder = os.path.abspath(tmp_path / "launch")
    assert argv == [
        "/usr/bin/docker",
        "run",
        "--name",
        NAME,
        "--label",
        "pairbench.run=run-a",
        "--pull",
        "never",
        "--volume",
        f"{folder}:/pairbench/artifacts",
        "--publish",
        f"127.0.0.1:{port}:8000",
        "--volume",
        f"{weights}:{weights}:ro",
        IMAGE_ID,
        "--made-up",
        "1",
    ]
    assert load.endpoints == [api.Endpoint(base_url=f"http://127.0.0.1:{port}", model_name=MODEL)]
    assert outcome.pid == CONTAINER_PID
    assert outcome.cpu_s is None
    stops = [call for call in engine.calls if call[1] in ("stop", "rm")]
    assert stops == [
        ("/usr/bin/docker", "stop", "--time", "10", NAME),
        ("/usr/bin/docker", "rm", "--force", NAME),
    ]
    assert [s.case for s in outcome.samples] == list(STARTUP_CASES)


def test_a_gated_container_launch_counts_every_phase_when_the_side_reads_its_output_late(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each line reaches the side's log late, as on a busy machine; the gate holds the server
    # unready until the side has stamped them, so each phase comes before the first answer.
    gate = ReadyGate(tmp_path / "ready", (NEED_LINES,))
    read_through(monkeypatch, gate, len(VLLM_LINES), delay_s=LATE_READ_S)
    processes = EngineStandIn(script, {"lines": list(VLLM_LINES), "ready_file": str(gate.path)})
    engine = FakeEngine(processes=processes)
    outcome = (
        container_kind(engine, processes)
        .resolve(container_side(ready=GATED_READY), ctx())
        .launch(request(tmp_path, load=Load()))
    )
    assert outcome.rc == 0
    cases = {sample.case: sample.value for sample in outcome.samples}
    assert tuple(cases) == STARTUP_CASES
    for phase in STARTUP_CASES[2:]:
        assert cases[phase] <= cases["startup/ready_s"]


def test_an_env_pass_variable_reaches_the_container_by_name_only(
    script: Path, tmp_path: Path
) -> None:
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)
    context = ctx(
        LaunchSettings(env_pass=("MADE_UP_HUB_TOKEN",)),
        environ={"MADE_UP_HUB_TOKEN": "made-up-value-0451"},
    )
    resolved = container_kind(engine, processes).resolve(container_side(), context)
    outcome = resolved.launch(request(tmp_path, load=Load()))
    assert outcome.rc == 0
    argv = list(processes.engine_argv)
    assert argv[argv.index("--env") + 1] == "MADE_UP_HUB_TOKEN"
    assert processes.engine_env["MADE_UP_HUB_TOKEN"] == "made-up-value-0451"
    assert "made-up-value-0451" not in " ".join(argv)
    assert all("made-up-value-0451" not in " ".join(call) for call in engine.calls)
    assert "made-up-value-0451" not in json.dumps(dict(resolved.side.identity))


def test_a_container_launch_gives_the_cgroup_figures_of_the_load_phase(
    script: Path, tmp_path: Path
) -> None:
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)
    outcome = (
        container_kind(engine, processes)
        .resolve(container_side(), ctx())
        .launch(request(tmp_path, load=Load()))
    )
    reads = [call for call in engine.calls if call[1] == "exec"]
    assert (
        reads
        == [
            (
                "/usr/bin/docker",
                "exec",
                NAME,
                "cat",
                "/sys/fs/cgroup/cpu.stat",
                "/sys/fs/cgroup/memory.stat",
            )
        ]
        * 2
    )
    assert {k: v for k, v in outcome.timing.items() if k in ("user_s", "sys_s")} == CGROUP_TIMING
    assert dict(outcome.usage) == CGROUP_USAGE


def test_a_container_that_cannot_be_removed_gives_a_loud_note(script: Path, tmp_path: Path) -> None:
    notes: list[tuple[str, str]] = []
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes, rm_rc=1)
    outcome = (
        container_kind(engine, processes)
        .resolve(container_side(), ctx(notes=notes))
        .launch(request(tmp_path, load=Load()))
    )
    assert outcome.rc == 0
    assert [code for code, _text in notes] == ["container_not_removed"]


def test_a_server_container_whose_removal_does_not_end_is_named(
    script: Path, tmp_path: Path
) -> None:
    notes: list[tuple[str, str]] = []
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes, rm_hangs=True)
    kind = container_kind(engine, processes)
    outcome = kind.resolve(container_side(), ctx(notes=notes)).launch(
        request(tmp_path, load=Load())
    )
    assert outcome.rc == 0
    assert notes == [
        (
            "container_not_removed",
            f"the engine did not remove the server container {NAME} within 60 s; it may be "
            "left behind, and pairbench doctor lists it",
        )
    ]


def _chowns(engine: FakeEngine) -> list[tuple[str, ...]]:
    return [call for call in engine.calls if call[1] == "run" and "chown" in call]


def _seen_as_another_user_s(
    monkeypatch: pytest.MonkeyPatch, until: Callable[[], bool] = lambda: False
) -> None:
    """Make the side see every file in a folder as another user's, until ``until`` holds.

    The test cannot give files to another user, so the look for such files
    is told the caller is someone else.
    """
    look = container.foreign_entries

    def foreign(folder: Path, uid: int) -> list[Path]:
        return [] if until() else look(folder, uid + 1)

    monkeypatch.setattr(container, "foreign_entries", foreign)


def test_files_a_server_container_left_to_another_user_are_handed_back_after_it_stops(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    notes: list[tuple[str, str]] = []
    launch = request(tmp_path, load=Load())
    (launch.artifacts / "made-up.out").write_text("made up\n", encoding="utf-8")
    outcome = (
        container_kind(engine, processes)
        .resolve(container_side(), ctx(LaunchSettings(memory="2g"), notes=notes))
        .launch(launch)
    )
    assert outcome.rc == 0
    folder = os.path.abspath(tmp_path / "launch")
    chown = (
        "/usr/bin/docker",
        "run",
        "--rm",
        "--name",
        f"{NAME}-chown",
        "--label",
        "pairbench.run=run-a",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        "0:0",
        "--volume",
        f"{folder}:/pairbench/artifacts",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        "--entrypoint",
        "chown",
        IMAGE_ID,
        "-R",
        "-h",
        f"{os.getuid()}:{(tmp_path / 'launch').stat().st_gid}",
        "/pairbench/artifacts",
    )
    assert _chowns(engine) == [chown]
    removed = engine.calls.index(("/usr/bin/docker", "rm", "--force", NAME))
    assert engine.calls.index(chown) > removed
    assert ("/usr/bin/docker", "rm", "--force", f"{NAME}-chown") in engine.calls
    assert notes == []


def test_server_files_left_to_another_user_give_one_note_per_side(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seen_as_another_user_s(monkeypatch)
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    for seq in (3, 4):
        folder = tmp_path / "artifacts" / f"000{seq}-new"
        folder.mkdir(parents=True)
        launch = api.LaunchRequest(
            run_id="run-a",
            seq=seq,
            phase="round",
            round=1,
            pos=1,
            name="new",
            artifacts=folder,
            load=Load(),
        )
        assert resolved.launch(launch).rc == 0
    assert len(_chowns(engine)) == 2
    assert notes == [
        (
            "files_not_handed_back",
            "files a container of side new wrote in artifacts/0003-new of the run folder still "
            "belong to the user its image runs as, so other users may be able to read them and "
            "you may not be able to delete them: chown in the image left some of them with "
            "another user; later launches of the side are not named again",
        )
    ]


def test_a_container_launch_on_the_host_network_uses_the_server_s_own_port(
    script: Path, tmp_path: Path
) -> None:
    port = free_port()
    processes = EngineStandIn(script, {}, host_port=port)
    engine = FakeEngine(processes=processes)
    load = Load()
    container_kind(engine, processes).resolve(
        container_side(port=port), ctx(LaunchSettings(network="host"))
    ).launch(request(tmp_path, load=load))
    assert "--publish" not in processes.engine_argv
    assert processes.engine_argv[processes.engine_argv.index("--network") + 1] == "host"
    assert load.endpoints[0].base_url == f"http://127.0.0.1:{port}"


def test_a_host_network_port_that_already_answers_is_a_failed_launch_and_nothing_runs(
    script: Path, tmp_path: Path
) -> None:
    record = tmp_path / "foreign.jsonl"
    load = Load()
    with foreign_server(script, record) as port:
        processes = EngineStandIn(script, {"delay": 30.0}, host_port=port)
        engine = FakeEngine(processes=processes)
        outcome = (
            container_kind(engine, processes)
            .resolve(container_side(port=port), ctx(LaunchSettings(network="host")))
            .launch(request(tmp_path, load=load))
        )
    assert (outcome.rc, outcome.timed_out) == (1, False)
    assert processes.starts == []
    assert load.endpoints == []
    assert [entry for entry in _requests(record) if "body" in entry] == []
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == _port_taken(port)


def test_an_engine_command_that_cannot_start_reports_127(script: Path, tmp_path: Path) -> None:
    processes = EngineStandIn(script, {})
    processes.fail = FileNotFoundError(2, "No such file or directory", "/usr/bin/docker")
    engine = FakeEngine(processes=processes)
    outcome = (
        container_kind(engine, processes)
        .resolve(container_side(), ctx())
        .launch(request(tmp_path, load=Load()))
    )
    assert outcome.rc == 127
    stderr = (tmp_path / "launch" / "stderr.txt").read_text(encoding="utf-8")
    assert stderr == (
        "pairbench: side 'new': the docker command could not be started: "
        "No such file or directory\n"
    )


def test_an_explain_launch_in_a_container_needs_perf_counters(script: Path, tmp_path: Path) -> None:
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)

    def wrap(argv: Sequence[str]) -> api.InstrumentedCommand:
        return api.InstrumentedCommand(argv=("/made-up/perf", "record", "--", *argv))

    resolved = container_kind(engine, processes).resolve(container_side(), ctx())
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, load=Load(), wrap_server=wrap))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
    assert processes.starts == []


def test_an_explain_launch_in_a_container_replaces_the_entrypoint(
    script: Path, tmp_path: Path
) -> None:
    processes = EngineStandIn(script, {})
    engine = FakeEngine(processes=processes)
    handed: list[tuple[str, ...]] = []

    def wrap(argv: Sequence[str]) -> api.InstrumentedCommand:
        handed.append(tuple(argv))
        return api.InstrumentedCommand(argv=("/made-up/perf", "record", "--", *argv))

    settings = LaunchSettings(perf_counters=True)
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(settings))
    outcome = resolved.launch(request(tmp_path, load=Load(), wrap_server=wrap))
    assert outcome.rc == 0
    assert handed == [("/made-up/serve", "--made-up-default")]
    argv = list(processes.engine_argv)
    at = argv.index("--entrypoint")
    assert argv[at : at + 2] == ["--entrypoint", "/made-up/perf"]
    assert argv[argv.index(IMAGE_ID) :] == [
        IMAGE_ID,
        "record",
        "--",
        "/made-up/serve",
        "--made-up-default",
    ]


class SlowAfterResolve(FakeEngine):
    """An engine whose image questions run out of time once ``slow`` is set."""

    slow = False

    def __call__(self, argv: tuple[str, ...]) -> Completed:
        if self.slow and argv[1] == "image":
            self.calls.append(argv)
            return Completed(-9, "", "", timed_out=True)
        return super().__call__(argv)


def test_an_explain_launch_whose_image_question_runs_out_of_time_names_the_side(
    script: Path, tmp_path: Path
) -> None:
    processes = EngineStandIn(script, {})
    engine = SlowAfterResolve(processes=processes)

    def wrap(argv: Sequence[str]) -> api.InstrumentedCommand:
        return api.InstrumentedCommand(argv=("/made-up/perf", "record", "--", *argv))

    settings = LaunchSettings(perf_counters=True)
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(settings))
    engine.slow = True
    with pytest.raises(Refusal) as caught:
        resolved.launch(request(tmp_path, load=Load(), wrap_server=wrap))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert caught.value.message == (
        "side 'new': the container engine did not answer within 60 s when asked about the "
        f"image {IMAGE_ID}"
    )
    assert processes.starts == []


def test_a_container_side_sees_its_artifacts_and_tools_at_fixed_paths() -> None:
    resolved = container_kind(FakeEngine()).resolve(container_side(), ctx())
    assert isinstance(resolved, serve.ServeResolved)
    assert resolved.in_container is True
    assert resolved.artifacts_in_side(Path("made-up")) == "/pairbench/artifacts"
    assert resolved.tool_file_in_side(Path("tools/sampler.py")) == "/pairbench/tools/sampler.py"


# A server's log may print its command line, credentials included: only its owner may read it.
PRIVATE_MODE = 0o600


def test_the_server_log_is_readable_by_its_owner_only(script: Path, tmp_path: Path) -> None:
    side, _port = host_side(script, {"lines": list(VLLM_LINES)})
    old = os.umask(0o022)
    try:
        host_kind().resolve(side, ctx()).launch(request(tmp_path, load=Load()))
    finally:
        os.umask(old)
    assert (tmp_path / "launch" / "server.log").stat().st_mode & 0o777 == PRIVATE_MODE


# Ordinary settings of a server whose names say key or token: each pair of values gives two
# fingerprints. A switch before the model takes no value, so the model still tells sides apart.
ORDINARY_SERVER_ARGS = {
    "queued-tokens": (
        ("org/model-a", "--max-num-queued-tokens", "1024"),
        ("org/model-a", "--max-num-queued-tokens", "4096"),
    ),
    "scheduled-tokens-with-equals": (
        ("org/model-a", "--max-num-scheduled-tokens=512"),
        ("org/model-a", "--max-num-scheduled-tokens=2048"),
    ),
    "token-threshold": (
        ("org/model-a", "--dbo-decode-token-threshold", "32"),
        ("org/model-a", "--dbo-decode-token-threshold", "64"),
    ),
    "pass-config": (
        ("org/model-a", "--compilation-config", '{"pass_config": {"enable_noop": true}}'),
        ("org/model-a", "--compilation-config", '{"pass_config": {"enable_noop": false}}'),
    ),
    "switch-before-the-model": (
        ("--allow-credentials", "org/model-a"),
        ("--allow-credentials", "org/model-b"),
    ),
    "token-ids-switch-before-the-model": (
        ("--return-tokens-as-token-ids", "org/model-a"),
        ("--return-tokens-as-token-ids", "org/model-b"),
    ),
}
SECRET_SERVER_ARGS = {
    "api-key": ("org/model-a", "--api-key", "{}"),
    "hf-token": ("org/model-a", "--hf-token", "{}"),
    "s3-access-key-id": ("org/model-a", "--s3-access-key-id", "{}"),
    "s3-secret-access-key": ("org/model-a", "--s3-secret-access-key", "{}"),
    "ssl-keyfile": ("org/model-a", "--ssl-keyfile", "made-up/{}.pem"),
    "encryption-keyfile": ("org/model-a", "--encryption-keyfile", "made-up/{}"),
}


def _secret_args(form: tuple[str, ...], word: str) -> tuple[str, ...]:
    return tuple(arg.replace("{}", word) for arg in form)


@pytest.mark.parametrize(
    ("one", "two"), list(ORDINARY_SERVER_ARGS.values()), ids=list(ORDINARY_SERVER_ARGS)
)
def test_an_ordinary_setting_of_a_host_server_changes_its_fingerprint(
    script: Path, one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    kind = host_kind()
    first = kind.resolve(host_side(script, {}, port=8000, args=one)[0], ctx()).side
    second = kind.resolve(host_side(script, {}, port=8000, args=two)[0], ctx()).side
    assert first.identity["argv_sha256"] != second.identity["argv_sha256"]
    assert first.fingerprint != second.fingerprint


@pytest.mark.parametrize("form", list(SECRET_SERVER_ARGS.values()), ids=list(SECRET_SERVER_ARGS))
def test_a_secret_of_a_host_server_leaves_its_fingerprint_alone(
    script: Path, form: tuple[str, ...]
) -> None:
    kind = host_kind()
    found = [
        kind.resolve(host_side(script, {}, port=8000, args=_secret_args(form, word))[0], ctx()).side
        for word in ("kiwi7", "plum4")
    ]
    assert len({side.fingerprint for side in found}) == 1


@pytest.mark.parametrize(
    ("one", "two"), list(ORDINARY_SERVER_ARGS.values()), ids=list(ORDINARY_SERVER_ARGS)
)
def test_an_ordinary_setting_of_a_container_server_changes_its_fingerprint(
    one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    kind = container_kind(FakeEngine())
    first = kind.resolve(container_side(args=one), ctx()).side
    second = kind.resolve(container_side(args=two), ctx()).side
    assert first.identity["args_sha256"] != second.identity["args_sha256"]
    assert first.fingerprint != second.fingerprint


@pytest.mark.parametrize("form", list(SECRET_SERVER_ARGS.values()), ids=list(SECRET_SERVER_ARGS))
def test_a_secret_of_a_container_server_leaves_its_fingerprint_alone(
    form: tuple[str, ...],
) -> None:
    kind = container_kind(FakeEngine())
    found = [
        kind.resolve(container_side(args=_secret_args(form, word)), ctx()).side
        for word in ("kiwi7", "plum4")
    ]
    assert len({side.fingerprint for side in found}) == 1
