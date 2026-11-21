# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``serve`` side kind: a server started for each launch, and the load tool run against it.

What to serve (``model.ServeSpec``) is kept apart from how it is started
(``api.Launcher``). Three launchers are built in: ``docker`` and ``podman``
start the image in a container through the engine's command-line program,
``host`` starts ``command`` as a process on this machine. The config key
``serve.launcher`` picks one; without it the launcher follows the container
engine the launch settings choose.

One launch, in this order:

1. When GPUs are selected, wait up to ``api.GPU_FREE_WAIT_S`` for them to be
   free of other compute processes. Still busy: refused under ``gates.mode``
   ``enforce`` (``E_GATE_FAILED``), a loud note otherwise; the witness then
   sees the other process and marks the round. A count that cannot be read
   is taken as busy at once, without waiting. Then the GPU memory in use is
   recorded.
2. Start the server. This is ``t0``.
3. Poll the readiness path until it answers with a 2xx status:
   ``startup/ready_s``.
4. Send one request and wait for the first non-empty answer:
   ``startup/first_answer_s``, from ``t0``. By default the request is one
   small streaming chat request to ``/v1/chat/completions`` naming the model
   of the config, or the first model of the server's ``/v1/models`` list.
5. Hand the endpoint to the runner's load callback, which runs every load
   level in order, with the power sampler around it.
6. Stop the server, remove it, and write what it printed to ``server.log``.
7. Wait up to ``api.GPU_RELEASE_WAIT_S`` for GPU memory in use to come back
   within ``api.GPU_RELEASE_TOLERANCE_MIB`` of the level of step 1. A
   timeout is refused with ``E_GPU_NOT_RELEASED``.

Stopping the server happens on every path: after a failed readiness check,
a failed first answer, a failed load and an interrupt. Two servers never run
at the same time in one process.

A server that does not become ready in time, exits before it is ready,
gives no first answer, or exits during the load is a failed launch, reported
in the outcome and not raised: the reason goes to ``stderr.txt`` in the
launch's folder. So is a server port that already answers before the start:
the host launcher, and a container launcher on the host's network, use the
port of the spec on this machine, and a process already listening there would
pass the readiness check and take the load in place of the server. That
launch starts nothing.

Start-up phases. ``serve.phases`` maps a phase name to a regular expression.
The first line of the server's output that matches gives the case
``startup/<name>_s``, the time from ``t0`` to the moment the line was read,
when the server wrote it before its first answer. At the first answer the
reader marks how much output the server has written, read or still waiting in
the pipe, and the phases wait, up to ``READER_CATCH_UP_S``, until the reader
has read up to the mark, so a reader that falls behind loses no phase within
that wait; a line it reads late is timed late. Two loud notes say so in the
results: ``startup_phases_read_late`` names the phases whose line was read
after the first answer, and ``startup_phases_left_out`` names the phases
without a time when the wait ran out before the reader reached the mark. A
launch of the rounds hands them back in ``LaunchOutcome.notes``, naming the
launch's entry, and the run gives each once per entry once the round is
complete: for a twin under the twin's own name, and for the positive control
only when one of the phases it names is a primary case, even when the control
is then not judged. A note names every phase it found, primary or not. A
failed or interrupted round gives none, and so does a
warm-up, a launch of the explain step or a profiler. Without ``serve.phases``
the built-in patterns of ``BUILTIN_PHASES`` apply. They are the start-up lines
of the vLLM OpenAI-compatible server, taken from its public source at release
v0.33.0 (https://github.com/vllm-project/vllm/tree/v0.33.0):
``vllm/v1/worker/gpu_model_runner.py`` ("Model loading took"),
``vllm/v1/engine/core.py`` ("init engine (profile, create kv cache, warmup
model) took") and ``vllm/entrypoints/launchers/api_server/entry.py``
("Starting vLLM server on"). Output that matches none gives no phase.

Resource figures cover the load phase. For a container they come from the
container's own cgroup (version 2) files, read inside it with ``cat`` before
and after the load: ``cpu.stat`` gives ``user_usec`` and ``system_usec``,
``memory.stat`` gives ``pgfault`` and ``pgmajfault``. For a host process
they come from ``/proc``: the CPU time, page faults and context switches of
every process of the server's session. A figure that cannot be read, or that
goes down between the two reads, is missing. The peak resident memory is
missing for both: the sources give the peak over the server's whole life,
not over the load phase.

The server's own CPU time over the whole launch (``LaunchOutcome.cpu_s``) is
given by the host launcher, from the exit status of the server's first
process. A container launcher gives none.

An explain launch hands the command that starts the server to
``LaunchRequest.wrap_server`` and starts what comes back. The host launcher
always can. A container launcher can when the launch setting
``perf_counters`` is set; the wrapped command then replaces the image's
entrypoint, so the instrument must be in the image. Otherwise the launch is
refused with ``E_ENGINE_UNSUPPORTED``.
"""

from __future__ import annotations

import bisect
import contextlib
import dataclasses
import http.client
import json
import os
import re
import select
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Final

from pairbench import api, registry
from pairbench.errors import Refusal
from pairbench.model import (
    CASE_STARTUP_FIRST_ANSWER,
    CASE_STARTUP_READY,
    KIND_SERVE,
    STARTUP_PREFIX,
    EngineInfo,
    LaunchSettings,
    Probe,
    Ready,
    ServeSpec,
    Side,
    fingerprint_of,
)
from pairbench.model import NOTE_GPU_BUSY_BEFORE_START as NOTE_GPU_BUSY
from pairbench.sides.base import (
    NOT_STARTED_RC,
    CommandRunner,
    HostProcesses,
    KindBase,
    PinningFailed,
    ProcessUsage,
    find_executable,
    host_environment,
    open_private,
    parse_cpu_list,
    refuse_host_settings,
    require_env_pass,
    resolve_workdir,
    run_command,
    usage_from_rusage,
)
from pairbench.sides.container import (
    NOTE_CONTAINER_NOT_REMOVED,
    NOTE_FILES_NOT_HANDED_BACK,
    REMOVE_WAIT_S,
    RUN_LABEL,
    EngineFacts,
    PidWatcher,
    container_options,
    engine_facts,
    engine_reads,
    files_kept_note,
    hand_back,
    image_identity,
    inspect_image,
    reachable_engines,
    refuse_image_settings,
)
from pairbench.sides.identity import (
    KEY_ARGV_SHA256,
    KEY_EXECUTABLE,
    KEY_EXECUTABLE_SHA256,
    KEY_IMAGE_ID,
    argv_sha256,
    identify_on_host,
    run_identify,
    side_file_sha256,
)

# The launchers built in, by name.
LAUNCHER_DOCKER: Final = "docker"
LAUNCHER_PODMAN: Final = "podman"
LAUNCHER_HOST: Final = "host"
# The identity key of a container server's own arguments.
KEY_ARGS_SHA256: Final = "args_sha256"

# Start-up phases of the vLLM OpenAI-compatible server, from its public source
# at release v0.33.0 (see the module docstring).
BUILTIN_PHASES: Final[Mapping[str, str]] = {
    "weights_loaded": r"Model loading took ",
    "engine_ready": r"init engine \(profile, create kv cache, warmup model\) took ",
    "server_started": r"Starting vLLM server on ",
}
# A phase name: lower case, digits and underscores, starting with a letter.
PHASE_NAME: Final = re.compile(r"[a-z][a-z0-9_]*")
# Phase names taken by the two start-up cases every serving launch gives.
RESERVED_PHASES: Final[tuple[str, ...]] = ("ready", "first_answer")

# Where a started server is reached from this machine.
LOOPBACK: Final = "127.0.0.1"
# The prompt and the length of the default first-answer request.
PROBE_PROMPT: Final = "Say hello."
PROBE_MAX_TOKENS: Final = 8
# How often the readiness path is asked, and how long one request may take.
READY_POLL_S: Final = 0.5
HTTP_TIMEOUT_S: Final = 5.0
# How long a connection to a server port before the start may take.
PORT_CHECK_S: Final = 1.0
# How often the GPUs are read while waiting for them.
GPU_POLL_S: Final = 2.0
# How long a server is given to stop before it is killed.
STOP_GRACE_S: Final = 10
# How long the start-up phases wait for the reader of the server's output to
# read what the server wrote before its first answer.
READER_CATCH_UP_S: Final = 30.0
# The most the reader of the server's output takes from the pipe at once.
READ_CHUNK_BYTES: Final = 65536
# How long an engine command that stops, removes or reads a container may take.
ENGINE_COMMAND_S: Final = 60.0
# The cgroup files of a container that hold its CPU time and page faults.
CGROUP_FILES: Final[tuple[str, ...]] = ("/sys/fs/cgroup/cpu.stat", "/sys/fs/cgroup/memory.stat")
# The loud note given when the GPU memory in use cannot be read before a start.
NOTE_GPU_MEMORY_UNREADABLE: Final = "gpu_memory_unreadable"
# The loud note given when the line of a start-up phase was read after the first answer.
NOTE_PHASES_READ_LATE: Final = "startup_phases_read_late"
# The loud note given when the reader had not caught up and a start-up phase has no time.
NOTE_PHASES_LEFT_OUT: Final = "startup_phases_left_out"
# The launches that hand the two notes above back: the rounds, whose start-up phases the
# results may hold. The results leave the warm-ups out, and the explain step and the
# profilers launch a side outside the capture; those hand back none.
NOTED_PHASES: Final[frozenset[str]] = frozenset({"round"})

# Two servers never run at the same time in one process.
_ONE_SERVER = threading.Lock()


# ---------------------------------------------------------------------------
# Reading the spec
# ---------------------------------------------------------------------------


def serve_spec(side: Side) -> ServeSpec:
    """Return the ``ServeSpec`` of a serving side; one that cannot be read is ``E_USAGE``."""
    try:
        return side.serve_spec()
    except Refusal as exc:
        raise Refusal("E_USAGE", f"side {side.name!r}: {exc.message}") from None


def phase_patterns(spec: ServeSpec, side: str = "") -> dict[str, re.Pattern[str]]:
    """Return the start-up phases to look for: ``serve.phases``, or the built-in ones without it.

    A name that is not lower case letters, digits and underscores, a name of
    one of the two start-up cases every launch gives (``ready``,
    ``first_answer``) and a pattern that is no regular expression are refused
    with ``E_USAGE``.
    """
    given = dict(spec.phases) if spec.phases else dict(BUILTIN_PHASES)
    out: dict[str, re.Pattern[str]] = {}
    for name, pattern in given.items():
        if not PHASE_NAME.fullmatch(name) or name in RESERVED_PHASES:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: a start-up phase name is lower case letters, digits and "
                f"underscores and is neither ready nor first_answer: {name!r}",
            )
        try:
            out[name] = re.compile(pattern)
        except re.error as exc:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: the pattern of the start-up phase {name!r} is no regular "
                f"expression: {exc}",
            ) from None
    return out


# A path on the server: starts with "/", holds no space or control character.
SERVER_PATH: Final = re.compile(r"/[^\s\x00-\x1f\x7f]*")


def check_paths(spec: ServeSpec, side: str = "") -> None:
    """Refuse a readiness path or a first-answer path that is no path on the server.

    Each is put after the server's address as it is, so it starts with
    ``/`` and holds no space or control character; anything else is
    refused with ``E_USAGE`` before a server is started.
    """
    for key, path in (("serve.ready.http", spec.ready.http), ("serve.probe.path", spec.probe.path)):
        if not SERVER_PATH.fullmatch(path):
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: {key} is a path on the server, starting with '/' and holding "
                f"no space or control character: {path!r}",
            )


def phase_case(name: str) -> str:
    """Return the case id of a start-up phase: ``startup/<name>_s``."""
    return f"{STARTUP_PREFIX}{name}_s"


def startup_sample(case: str, seconds: float) -> api.Sample:
    """Return one start-up case: seconds, lower is better."""
    return api.Sample(
        case=case,
        metric=case.removeprefix(STARTUP_PREFIX),
        unit="s",
        better="lower",
        kind="time",
        value=seconds,
    )


# ---------------------------------------------------------------------------
# Talking to the server
# ---------------------------------------------------------------------------


def _opener() -> urllib.request.OpenerDirector:
    # A server on this machine is never reached through a proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_ok(url: str, timeout_s: float) -> bool:
    """Say whether a GET of ``url`` answers with a 2xx status within ``timeout_s``."""
    try:
        with _opener().open(url, timeout=max(timeout_s, 0.01)) as response:
            return 200 <= int(response.status) < 300
    except (OSError, ValueError, http.client.HTTPException):
        return False


def listed_model(base_url: str, timeout_s: float) -> str | None:
    """Return the first model id of the server's ``/v1/models`` list, or ``None``."""
    try:
        with _opener().open(f"{base_url}/v1/models", timeout=max(timeout_s, 0.01)) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        return None
    name = models[0].get("id")
    return name if isinstance(name, str) and name else None


def probe_body(model_name: str | None) -> dict[str, Any]:
    """Return the default first-answer request: one small streaming chat request."""
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": True,
    }
    if model_name:
        body = {"model": model_name, **body}
    return body


def answer_text(event: Any) -> str:
    """Return the text an OpenAI-compatible answer or stream event carries, or ``""``.

    The text is the first choice's ``delta.content``, ``delta.reasoning_content``,
    ``text`` or ``message.content``, whichever is a text that is not empty.
    """
    if not isinstance(event, dict):
        return ""
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    choice = choices[0]
    candidates: list[Any] = [choice.get("text")]
    for key in ("delta", "message"):
        part = choice.get(key)
        if isinstance(part, dict):
            candidates += [part.get("content"), part.get("reasoning_content")]
    return next((c for c in candidates if isinstance(c, str) and c), "")


def first_answer_after(url: str, body: Mapping[str, Any], deadline: float) -> None:
    """Send the request and return when the first non-empty answer arrives.

    A streamed answer (``text/event-stream``) is read event by event; any
    other answer is read whole. No answer by ``deadline`` (a
    ``time.monotonic()`` value), an error status, or an answer that ends
    without text is refused with ``E_LAUNCH_FAILED``.
    """
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError
        with _opener().open(request, timeout=left) as response:
            stream = "text/event-stream" in str(response.headers.get("Content-Type", ""))
            if not stream:
                if answer_text(_json(response.read())):
                    return
                raise _no_answer("the server's answer held no text")
            while time.monotonic() < deadline:
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:"):
                    continue
                payload = text[len("data:") :].strip()
                if payload == "[DONE]":
                    break
                if answer_text(_json(payload.encode("utf-8"))):
                    return
            else:
                raise TimeoutError
    except urllib.error.HTTPError as exc:
        raise _no_answer(f"the first-answer request was answered with status {exc.code}") from None
    except TimeoutError:
        raise _no_answer("the server gave no first answer in time", timed_out=True) from None
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise _no_answer(f"the first-answer request failed: {exc}") from None
    raise _no_answer("the server's answer ended without text")


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None


def _no_answer(message: str, *, timed_out: bool = False) -> Refusal:
    return Refusal("E_LAUNCH_FAILED", message, detail={"timed_out": timed_out})


def free_port() -> int:
    """Return a TCP port on the loopback address that nothing listens on now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def port_answers(port: int, timeout_s: float = PORT_CHECK_S) -> bool:
    """Say whether something accepts a TCP connection on ``port`` of the loopback address."""
    try:
        with socket.create_connection((LOOPBACK, port), timeout=timeout_s):
            return True
    except (OSError, OverflowError, ValueError):
        return False


def refuse_taken_port(port: int, side: str) -> None:
    """Refuse a start with ``E_LAUNCH_FAILED`` when something already answers on ``port``.

    The readiness check, the first answer and the load would reach that
    process in place of the server started for the launch.
    """
    if port_answers(port):
        raise Refusal(
            "E_LAUNCH_FAILED",
            f"side {side!r}: something already answers on port {port} of the loopback address, "
            "so a server started there could not be told apart from it",
            detail={"rc": 1, "timed_out": False},
        )


# ---------------------------------------------------------------------------
# The GPU waits
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Waits:
    """How long the GPU waits last and how often they read the GPUs. Tests shorten them."""

    free_s: float = api.GPU_FREE_WAIT_S
    release_s: float = api.GPU_RELEASE_WAIT_S
    poll_s: float = GPU_POLL_S
    ready_poll_s: float = READY_POLL_S


def wait_gpu_free(gpu: api.GpuProbe, timeout_s: float, poll_s: float) -> bool:
    """Wait until no other compute process is on the selected GPUs; say whether that happened.

    A count that cannot be read gives ``False`` at once: waiting does not make
    it readable.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        count = gpu.compute_processes()
        if count is None:
            return False
        if count == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(poll_s, max(deadline - time.monotonic(), 0.0)))


def wait_memory_back(
    gpu: api.GpuProbe | None,
    level_mib: float,
    *,
    tolerance_mib: float,
    timeout_s: float,
    poll_s: float,
) -> None:
    """Wait until GPU memory in use is within ``tolerance_mib`` of ``level_mib``, or refuse.

    The refusal is ``E_GPU_NOT_RELEASED``; a reading that fails counts as
    not back. Without a GPU probe there is nothing to wait for.
    """
    if gpu is None:
        return
    deadline = time.monotonic() + timeout_s
    used: float | None = None
    while True:
        used = gpu.memory_used_mib()
        if used is not None and used <= level_mib + tolerance_mib:
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_s, max(deadline - time.monotonic(), 0.0)))
    seen = "could not be read" if used is None else "stayed above its level before the start"
    raise Refusal(
        "E_GPU_NOT_RELEASED",
        f"GPU memory in use {seen} for {timeout_s:g} s after the server stopped",
        detail={"level_mib": level_mib, "used_mib": used, "tolerance_mib": tolerance_mib},
    )


# ---------------------------------------------------------------------------
# Resource figures of the load phase
# ---------------------------------------------------------------------------


def parse_cgroup(text: str) -> dict[str, int]:
    """Read ``key value`` lines of cgroup files into a mapping; other lines are skipped."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def cgroup_figures(
    before: Mapping[str, int], after: Mapping[str, int]
) -> tuple[dict[str, float], dict[str, float]]:
    """Return the CPU time and the page faults between two reads of a container's cgroup.

    The first mapping holds ``user_s`` and ``sys_s``, the second
    ``faults_major`` and ``faults_minor`` (``pgfault`` counts both kinds). A
    figure missing from either read, or that goes down, is left out.
    """

    def delta(key: str) -> int | None:
        if key not in before or key not in after or after[key] < before[key]:
            return None
        return after[key] - before[key]

    timing: dict[str, float] = {}
    usage: dict[str, float] = {}
    user, system = delta("user_usec"), delta("system_usec")
    if user is not None:
        timing[api.TIMING_USER_S] = user / 1e6
    if system is not None:
        timing[api.TIMING_SYS_S] = system / 1e6
    faults, major = delta("pgfault"), delta("pgmajfault")
    if major is not None:
        usage[api.USAGE_FAULTS_MAJOR] = float(major)
        if faults is not None and faults >= major:
            usage[api.USAGE_FAULTS_MINOR] = float(faults - major)
    return timing, usage


# The figures of one read of a host session's processes, as /proc gives them.
SESSION_KEYS: Final[tuple[str, ...]] = (
    "user_ticks",
    "sys_ticks",
    "faults_minor",
    "faults_major",
    "ctx_voluntary",
    "ctx_involuntary",
)


def proc_stat_fields(text: str) -> list[str] | None:
    """Return the fields of a ``/proc/<pid>/stat`` line after the command name, or ``None``.

    The first field returned is the state, field 3 of proc(5).
    """
    end = text.rfind(")")
    if end < 0:
        return None
    rest = text[end + 1 :].split()
    return rest if len(rest) >= 15 else None


def session_figures(session: int, proc: Path = Path("/proc")) -> dict[str, int] | None:
    """Sum the CPU time, page faults and context switches of every process of a session.

    The CPU time and the faults include the children each process waited
    for. ``None`` when ``/proc`` cannot be read.
    """
    totals = dict.fromkeys(SESSION_KEYS, 0)
    try:
        entries = [entry for entry in proc.iterdir() if entry.name.isdigit()]
    except OSError:
        return None
    found = False
    for entry in entries:
        try:
            fields = proc_stat_fields((entry / "stat").read_text())
            status = (entry / "status").read_text()
        except OSError:
            continue
        if fields is None or not fields[3].lstrip("-").isdigit() or int(fields[3]) != session:
            continue
        try:
            numbers = [int(value) for value in fields[7:15]]
        except ValueError:
            continue
        minflt, cminflt, majflt, cmajflt, utime, stime, cutime, cstime = numbers
        totals["user_ticks"] += utime + cutime
        totals["sys_ticks"] += stime + cstime
        totals["faults_minor"] += minflt + cminflt
        totals["faults_major"] += majflt + cmajflt
        for line in status.splitlines():
            key, _, value = line.partition(":")
            if key == "voluntary_ctxt_switches" and value.strip().isdigit():
                totals["ctx_voluntary"] += int(value)
            elif key == "nonvoluntary_ctxt_switches" and value.strip().isdigit():
                totals["ctx_involuntary"] += int(value)
        found = True
    return totals if found else None


def session_delta(
    before: Mapping[str, int], after: Mapping[str, int], ticks_per_s: float
) -> tuple[dict[str, float], dict[str, float]]:
    """Return the CPU time and the other figures between two reads of a host session.

    A figure that goes down between the reads (a process that exited takes
    its counts with it) is left out.
    """
    timing: dict[str, float] = {}
    usage: dict[str, float] = {}
    names = {
        "user_ticks": api.TIMING_USER_S,
        "sys_ticks": api.TIMING_SYS_S,
        "faults_minor": api.USAGE_FAULTS_MINOR,
        "faults_major": api.USAGE_FAULTS_MAJOR,
        "ctx_voluntary": api.USAGE_CTX_VOLUNTARY,
        "ctx_involuntary": api.USAGE_CTX_INVOLUNTARY,
    }
    for key, name in names.items():
        if key not in before or key not in after or after[key] < before[key]:
            continue
        change = after[key] - before[key]
        if key.endswith("_ticks"):
            timing[name] = change / ticks_per_s
        else:
            usage[name] = float(change)
    return timing, usage


# ---------------------------------------------------------------------------
# The server process
# ---------------------------------------------------------------------------


class ServerProcess:
    """One started server process: its id, its output, and its exit, collected with its usage.

    The process runs in a session of its own, so a signal to the session
    reaches every process the server started.
    """

    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self._popen = popen
        self.pid = popen.pid
        self.rc: int | None = None
        self.usage: ProcessUsage | None = None

    @property
    def output(self) -> IO[bytes] | None:
        return self._popen.stdout

    def exited(self) -> int | None:
        """Return the exit code when the process has exited, collecting it; else ``None``."""
        if self.rc is not None:
            return self.rc
        if hasattr(os, "wait4"):
            try:
                pid, status, ru = os.wait4(self.pid, os.WNOHANG)
            except ChildProcessError:
                return self._popen.poll()
            if pid == 0:
                return None
            self.rc = os.waitstatus_to_exitcode(status)
            self.usage = usage_from_rusage(ru)
            self._popen.returncode = self.rc
            return self.rc
        self.rc = self._popen.poll()
        return self.rc

    def wait(self, timeout_s: float) -> int | None:
        """Wait up to ``timeout_s`` for the exit; return the exit code or ``None``."""
        deadline = time.monotonic() + timeout_s
        while True:
            rc = self.exited()
            if rc is not None or time.monotonic() >= deadline:
                return rc
            time.sleep(0.05)

    def ended(self, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for the process to end, without collecting its exit.

        A process that ended but was not collected keeps its id, so a signal
        to its session can still reach what it left running. Where the
        platform cannot wait without collecting, the exit is collected.
        """
        if not hasattr(os, "waitid"):
            return self.wait(timeout_s) is not None
        deadline = time.monotonic() + timeout_s
        while True:
            if self.rc is not None:
                return True
            try:
                found = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                return self.wait(0.0) is not None
            if found is not None and found.si_pid == self.pid:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def signal(self, sig: int) -> None:
        """Send a signal to the process's session; a process that is gone is no error.

        Once the exit is collected the id may belong to another process, so
        nothing is sent any more.
        """
        if self.rc is not None:
            return
        try:
            if hasattr(os, "killpg"):
                os.killpg(self.pid, sig)
            else:
                self._popen.send_signal(sig)
        except (ProcessLookupError, PermissionError):
            pass

    def kill_session(self) -> None:
        """Kill every process still running in the server's session, also after its exit.

        The session's id is the id of the server's first process. While any
        process of the session runs, the id stays taken, so it reaches what
        the server left behind even when the server's own exit was collected;
        with none left, the signal reaches nothing. Where the platform has no
        process groups, only the server itself is killed, before its exit is
        collected.
        """
        if not hasattr(os, "killpg"):
            if self.rc is None:
                with contextlib.suppress(OSError):
                    self._popen.kill()
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.pid, signal.SIGKILL)

    def close(self) -> None:
        """Close the output pipe."""
        if self._popen.stdout is not None:
            with contextlib.suppress(OSError):
                self._popen.stdout.close()


class ServerProcesses:
    """Starts server processes. Tests replace it to start a small server of their own."""

    def start(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str | None = None,
        executable: str | None = None,
        cpus: frozenset[int] | None = None,
    ) -> ServerProcess:
        """Start one process with its output (both streams) on a pipe.

        ``cpus`` pins the process: the calling thread takes the set for the
        start and is put back afterwards. A process that cannot start raises
        ``OSError``.
        """
        pinner = HostProcesses()
        try:
            token = pinner.pin(cpus)
        except OSError as exc:
            raise PinningFailed(str(exc)) from exc
        try:
            popen = subprocess.Popen(
                list(argv),
                executable=executable,
                env=dict(env),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            pinner.unpin(token)
        return ServerProcess(popen)


def waiting_bytes(fd: int) -> int | None:
    """Return how many bytes wait to be read from a pipe, or ``None`` where that cannot be read."""
    try:
        import fcntl
        import struct
        import termios

        answer = fcntl.ioctl(fd, termios.FIONREAD, struct.pack("i", 0))
        return int(struct.unpack("i", answer)[0])
    except (ImportError, AttributeError, OSError, ValueError, TypeError):
        return None


class LogReader:
    """Reads a server's output in a thread and stamps each line with the time it was read.

    Each line keeps where it starts in the output, counted in bytes.
    ``mark`` says how much the server has written so far: what the reader
    has taken plus what waits in the pipe. Where the pipe can say what
    waits in it, the reader waits for output and then takes it holding the
    lock ``mark`` holds, so nothing is in neither count; elsewhere the mark
    is what the reader has taken. ``wait_for`` waits until the reader has
    read up to a mark, and ``lines_before`` gives the lines that start
    before it, however late the reader read them.
    """

    def __init__(self, stream: IO[bytes] | None) -> None:
        self.lines: list[tuple[float, str]] = []
        self._starts: list[int] = []
        self._line_end = 0
        self._taken = 0
        self._partial = bytearray()
        self._ended = stream is None
        self._changed = threading.Condition()
        self._fd: int | None = None
        self._thread: threading.Thread | None = None
        if stream is not None:
            with contextlib.suppress(AttributeError, OSError, ValueError):
                fd = stream.fileno()
                if os.name == "posix" and waiting_bytes(fd) is not None:
                    self._fd = fd
            self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
            self._thread.start()

    def _read(self, stream: IO[bytes]) -> None:
        take = getattr(stream, "read1", None)
        if not callable(take):
            # A stream that takes no size, such as one that hands out whole lines.
            readline = stream.readline

            def take(_size: int) -> bytes:
                return readline()

        try:
            while True:
                if self._fd is not None:
                    select.select([self._fd], [], [])
                    with self._changed:
                        if self._took(take(READ_CHUNK_BYTES)):
                            return
                    continue
                chunk = take(READ_CHUNK_BYTES)
                with self._changed:
                    if self._took(chunk):
                        return
        except (OSError, ValueError):
            pass
        finally:
            with self._changed:
                if self._partial:
                    self._add_line(time.monotonic(), bytes(self._partial))
                    self._partial.clear()
                self._ended = True
                self._changed.notify_all()

    def _took(self, chunk: bytes) -> bool:
        """Add what the reader took, under the lock; say whether the output ended."""
        if not chunk:
            return True
        stamp = time.monotonic()
        self._taken += len(chunk)
        self._partial += chunk
        while True:
            end = self._partial.find(b"\n")
            if end < 0:
                break
            self._add_line(stamp, bytes(self._partial[: end + 1]))
            del self._partial[: end + 1]
        self._changed.notify_all()
        return False

    def _add_line(self, stamp: float, raw: bytes) -> None:
        self._starts.append(self._line_end)
        self._line_end += len(raw)
        self.lines.append((stamp, raw.decode("utf-8", "replace").rstrip("\r\n")))

    def mark(self) -> int:
        """Return how many bytes the server has written so far, read or waiting in the pipe."""
        with self._changed:
            waiting = waiting_bytes(self._fd) if self._fd is not None and not self._ended else 0
            return self._taken + (waiting or 0)

    def wait_for(self, mark: int, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for the reader to read up to ``mark``; say whether it did."""
        deadline = time.monotonic() + timeout_s
        with self._changed:
            while self._taken < mark and not self._ended:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._changed.wait(left)
            return True

    def lines_before(self, mark: int) -> list[tuple[float, str]]:
        """Return the lines read so far that start before ``mark``, each with its read time."""
        with self._changed:
            count = bisect.bisect_left(self._starts, mark)
            return list(self.lines[:count])

    def snapshot(self) -> list[tuple[float, str]]:
        with self._changed:
            return list(self.lines)

    def join(self, timeout_s: float) -> bool:
        """Wait up to ``timeout_s`` for the output to end; say whether it did.

        The output stays open while any process that holds it runs, such as
        one the server started in a session of its own.
        """
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            return not self._thread.is_alive()
        return True


def phase_stamps(
    lines: Sequence[tuple[float, str]],
    patterns: Mapping[str, re.Pattern[str]],
) -> dict[str, float]:
    """Return, per phase, the time its first matching line was read.

    ``lines`` are the lines that count, each with the time it was read, in
    the order the server wrote them.
    """
    found: dict[str, float] = {}
    for stamp, text in lines:
        for name, pattern in patterns.items():
            if name not in found and pattern.search(text):
                found[name] = stamp
    return {name: found[name] for name in patterns if name in found}


def phase_times(
    lines: Sequence[tuple[float, str]],
    patterns: Mapping[str, re.Pattern[str]],
    t0: float,
) -> dict[str, float]:
    """Return, per phase, the seconds from ``t0`` to the time its first matching line was read.

    ``lines`` are the lines that count, each with the time it was read, in
    the order the server wrote them.
    """
    return {name: max(stamp - t0, 0.0) for name, stamp in phase_stamps(lines, patterns).items()}


@dataclasses.dataclass(frozen=True)
class PhaseReading:
    """The start-up phases of one launch, and what the reader's lateness did to them.

    ``times`` holds the seconds of each phase that has a time. ``late`` names
    the phases whose line was read after the server's first answer, so their
    time comes after it. ``left_out`` names the phases without a time when the
    reader had not read up to the first answer's mark by the end of the wait:
    the line of such a phase may have been written and not yet read.
    """

    times: dict[str, float]
    late: tuple[str, ...] = ()
    left_out: tuple[str, ...] = ()


def phases_read_late_note(side: str, late: Sequence[str]) -> str:
    """Return the loud note for a launch whose phase lines were read after its first answer."""
    return (
        f"side {side}: the lines of the start-up phases {', '.join(late)} were read after the "
        "server's first answer, so those phases are timed late: a phase is timed when pairbench "
        "reads its line, and the reader of the server's output fell behind; this note is given "
        "once for each side"
    )


def phases_left_out_note(side: str, left_out: Sequence[str], wait_s: float) -> str:
    """Return the loud note for a launch whose reader had not caught up by the end of the wait."""
    return (
        f"side {side}: after a wait of {wait_s:g} s the reader of the server's output had still "
        "not read all the server wrote before its first answer, so the start-up phases without "
        f"a line read by then are left out: {', '.join(left_out)} have no time; this note is "
        "given once for each side"
    )


def phase_notes(name: str, reading: PhaseReading) -> list[api.LaunchNote]:
    """Return the notes of a launch of entry ``name``: phases timed late, phases left out.

    Each note speaks for the cases of the phases it names. The run gives them
    once per entry, after the round (``LaunchOutcome.notes``).
    """
    notes: list[api.LaunchNote] = []
    if reading.late:
        notes.append(
            api.LaunchNote(
                NOTE_PHASES_READ_LATE,
                phases_read_late_note(name, reading.late),
                cases=tuple(phase_case(phase) for phase in reading.late),
            )
        )
    if reading.left_out:
        notes.append(
            api.LaunchNote(
                NOTE_PHASES_LEFT_OUT,
                phases_left_out_note(name, reading.left_out, READER_CATCH_UP_S),
                cases=tuple(phase_case(phase) for phase in reading.left_out),
            )
        )
    return notes


# ---------------------------------------------------------------------------
# Server handles
# ---------------------------------------------------------------------------


def remove_server(
    runner: CommandRunner,
    program: str,
    name: str,
    environ: Mapping[str, str],
    note: api.Notify,
) -> None:
    """Remove the server's container; say so when the engine does not remove it."""
    done = runner([program, "rm", "--force", name], env=environ, timeout_s=REMOVE_WAIT_S)
    if done.timed_out:
        note(
            NOTE_CONTAINER_NOT_REMOVED,
            f"the engine did not remove the server container {name} within "
            f"{REMOVE_WAIT_S:g} s; it may be left behind, and pairbench doctor lists it",
        )
    elif done.rc != 0 and "no such" not in (done.stderr or "").lower():
        note(
            NOTE_CONTAINER_NOT_REMOVED,
            "the container of a serving side could not be removed; pairbench doctor lists it",
        )


def give_back_after_stop(
    give_back: Callable[[], str | None], note: api.Notify, side: str, folder: Path
) -> None:
    """Hand back the files of a launch that an exception or an interrupt stopped.

    The note names the folder every time some files stay with another user.
    When the hand-back itself stops, the note names the folder; an error in
    it is not raised, so the exception that stopped the launch goes on in
    its place, and an interrupt goes on.
    """
    try:
        reason = give_back()
    except BaseException as exc:
        failed = isinstance(exc, Exception)
        why = (
            f"the hand-back stopped on an error ({type(exc).__name__})"
            if failed
            else "an interrupt stopped the hand-back before it ended"
        )
        note(NOTE_FILES_NOT_HANDED_BACK, files_kept_note(side, folder, why, once=False))
        if failed:
            return
        raise
    if isinstance(reason, str):
        note(NOTE_FILES_NOT_HANDED_BACK, files_kept_note(side, folder, reason, once=False))


class _Handle:
    """What both kinds of server have: the waits, the first answer, the log and the stop."""

    def __init__(
        self,
        *,
        process: ServerProcess,
        base_url: str,
        model_name: str | None,
        artifacts: Path,
        gpu: api.GpuProbe | None,
        waits: Waits,
        t0: float,
    ) -> None:
        self._process = process
        self._base_url = base_url
        self._model_name = model_name
        self._artifacts = artifacts
        self._gpu = gpu
        self._waits = waits
        self.t0 = t0
        self._log = LogReader(process.output)
        self._stopped = False
        self.exit_code: int | None = None
        self.answered_at: float | None = None
        # How much output the server had written at its first answer.
        self._answer_mark: int | None = None

    @property
    def endpoint(self) -> api.Endpoint:
        return api.Endpoint(base_url=self._base_url, model_name=self._model_name)

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def cpu_s(self) -> float | None:
        return None

    def _gone(self) -> Refusal | None:
        rc = self._process.exited()
        if rc is None:
            return None
        self.exit_code = rc
        return Refusal(
            "E_LAUNCH_FAILED",
            f"the server exited with {rc} before it was ready",
            detail={"rc": rc, "timed_out": False},
        )

    def wait_ready(self, ready: Ready) -> float:
        """Poll the readiness path until it answers with a 2xx status; return the seconds."""
        deadline = self.t0 + ready.timeout_s
        url = f"{self._base_url}{ready.http}"
        while True:
            gone = self._gone()
            if gone is not None:
                raise gone
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if http_ok(url, min(HTTP_TIMEOUT_S, left)):
                return time.monotonic() - self.t0
            time.sleep(min(self._waits.ready_poll_s, max(deadline - time.monotonic(), 0.0)))
        raise Refusal(
            "E_LAUNCH_FAILED",
            f"the server did not pass its readiness check within {ready.timeout_s:g} s",
            detail={"timed_out": True},
        )

    def first_answer(self, probe: Probe, *, timeout_s: float | None = None) -> float:
        """Send the first-answer request and return the seconds from ``t0`` to the answer.

        The time allowed runs from ``t0``: the readiness timeout, unless
        ``timeout_s`` gives another.
        """
        allowed = timeout_s if timeout_s is not None else Ready().timeout_s
        deadline = self.t0 + allowed
        body: Mapping[str, Any]
        if probe.body is not None:
            body = probe.body
            named = body.get("model")
            if self._model_name is None and isinstance(named, str) and named:
                self._model_name = named
        else:
            if self._model_name is None:
                self._model_name = listed_model(
                    self._base_url, min(HTTP_TIMEOUT_S, deadline - time.monotonic())
                )
                if self._model_name is None:
                    raise _no_answer(
                        "the config names no model and the server's /v1/models list gave none"
                    )
            body = probe_body(self._model_name)
        gone = self._gone()
        if gone is not None:
            raise gone
        first_answer_after(f"{self._base_url}{probe.path}", body, deadline)
        self.answered_at = time.monotonic()
        self._answer_mark = self._log.mark()
        if self._model_name is None:
            # A request body of the config may name no model; the load tool still wants one.
            self._model_name = listed_model(self._base_url, HTTP_TIMEOUT_S)
        return self.answered_at - self.t0

    def phases(self, patterns: Mapping[str, re.Pattern[str]]) -> PhaseReading:
        """Return the start-up phases of the lines the server wrote before its first answer.

        The output the server had written at the first answer, read or
        waiting in the pipe, is waited for, up to ``READER_CATCH_UP_S``, so a
        reader that falls behind loses no phase within that wait. Each phase
        is timed by when its line was read: the reading names the phases read
        after the first answer, and, when the wait ran out, the phases left
        without a time.
        """
        mark = self._answer_mark if self._answer_mark is not None else self._log.mark()
        caught_up = self._log.wait_for(mark, READER_CATCH_UP_S)
        stamps = phase_stamps(self._log.lines_before(mark), patterns)
        answered = self.answered_at
        late = () if answered is None else tuple(n for n, s in stamps.items() if s > answered)
        left_out = () if caught_up else tuple(name for name in patterns if name not in stamps)
        times = {name: max(stamp - self.t0, 0.0) for name, stamp in stamps.items()}
        return PhaseReading(times=times, late=late, left_out=left_out)

    def exited_during_load(self) -> int | None:
        """Return the exit status of a server that exited before its stop, else ``None``."""
        rc = self._process.exited()
        if rc is not None:
            self.exit_code = rc
        return rc

    def begin_load(self) -> Any:
        """Read the resource figures at the start of the load phase."""
        return None

    def end_load(self, before: Any) -> tuple[dict[str, float], dict[str, float]]:
        """Return the CPU time and the other figures of the load phase."""
        return {}, {}

    def _stop_server(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        """Stop and remove the server and write its output to ``server.log``. Safe to repeat."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self._stop_server()
        finally:
            # Closing the output while the reader still waits on it would wait
            # with it; output still held open is left to the reader's thread.
            if self._log.join(5.0):
                self._process.close()
            self._write_log()

    def _write_log(self) -> None:
        text = "".join(f"{line}\n" for _stamp, line in self._log.snapshot())
        with (
            contextlib.suppress(OSError),
            open_private(self._artifacts / api.ARTIFACT_SERVER_LOG) as handle,
        ):
            handle.write(text.encode("utf-8"))

    def wait_released(
        self,
        level_mib: float,
        *,
        tolerance_mib: float = api.GPU_RELEASE_TOLERANCE_MIB,
        timeout_s: float = api.GPU_RELEASE_WAIT_S,
    ) -> None:
        """Wait for GPU memory in use to come back to its level, else ``E_GPU_NOT_RELEASED``."""
        wait_memory_back(
            self._gpu,
            level_mib,
            tolerance_mib=tolerance_mib,
            timeout_s=timeout_s,
            poll_s=self._waits.poll_s,
        )


class ContainerHandle(_Handle):
    """A server in a container, started by the engine's ``run`` command in the foreground."""

    def __init__(
        self,
        *,
        facts: EngineFacts,
        name: str,
        runner: CommandRunner,
        environ: Mapping[str, str],
        note: api.Notify,
        watcher: PidWatcher | None,
        image: str = "",
        settings: LaunchSettings | None = None,
        run_id: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._facts = facts
        self._name = name
        self._runner = runner
        self._environ = dict(environ)
        self._note = note
        self._watcher = watcher
        self._image = image
        self._settings = settings
        self._run_id = run_id
        self._pid: int | None = None

    @property
    def pid(self) -> int | None:
        """The id of the container's first process, when the engine runs on this machine."""
        if self._pid is None and self._watcher is not None:
            self._pid = self._watcher.pid
        return self._pid

    def wait_ready(self, ready: Ready) -> float:
        seconds = super().wait_ready(ready)
        if self._watcher is not None:
            self._pid = self._watcher.stop()
        return seconds

    def _cgroup(self) -> dict[str, int] | None:
        done = self._runner(
            [self._facts.program, "exec", self._name, "cat", *CGROUP_FILES],
            env=self._environ,
            timeout_s=ENGINE_COMMAND_S,
        )
        figures = parse_cgroup(done.stdout)
        return figures or None

    def begin_load(self) -> Any:
        return self._cgroup()

    def end_load(self, before: Any) -> tuple[dict[str, float], dict[str, float]]:
        after = self._cgroup()
        if not isinstance(before, dict) or after is None:
            return {}, {}
        return cgroup_figures(before, after)

    def _stop_server(self) -> None:
        program = self._facts.program
        try:
            if self._watcher is not None:
                self._pid = self._watcher.stop() or self._pid
            if self._process.exited() is None:
                self._runner(
                    [program, "stop", "--time", str(STOP_GRACE_S), self._name],
                    env=self._environ,
                    timeout_s=ENGINE_COMMAND_S,
                )
                if self._process.wait(STOP_GRACE_S + 5.0) is None:
                    self._process.signal(signal.SIGKILL)
                    self._process.wait(5.0)
        finally:
            remove_server(self._runner, program, self._name, self._environ, self._note)

    def hand_back(self) -> str | None:
        """Give the files the server's container wrote in the launch folder back to the caller.

        Return why some of them stay with another user, or ``None`` when none
        do; see ``container.hand_back``. Called after the server is stopped.
        """
        if not self._image or self._settings is None:
            return None

        def remove(name: str) -> None:
            self._runner(
                [self._facts.program, "rm", "--force", name],
                env=self._environ,
                timeout_s=REMOVE_WAIT_S,
            )

        return hand_back(
            self._runner,
            self._facts,
            self._image,
            self._artifacts,
            name=f"{self._name}-chown",
            run_id=self._run_id,
            settings=self._settings,
            environ=self._environ,
            remove=remove,
        )


class HostHandle(_Handle):
    """A server started as a process on this machine, in a session of its own."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ticks = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0

    @property
    def cpu_s(self) -> float | None:
        usage = self._process.usage
        return None if usage is None else usage.user_s + usage.sys_s

    def begin_load(self) -> Any:
        return session_figures(self._process.pid)

    def end_load(self, before: Any) -> tuple[dict[str, float], dict[str, float]]:
        after = session_figures(self._process.pid)
        if not isinstance(before, dict) or after is None:
            return {}, {}
        return session_delta(before, after, self._ticks)

    def _stop_server(self) -> None:
        if self._process.rc is None:
            self._process.signal(signal.SIGTERM)
            self._process.ended(STOP_GRACE_S)
        # What the server started and left behind goes with its session, also
        # when the server exited before its stop and its exit was collected.
        self._process.kill_session()
        self._process.wait(5.0)


# ---------------------------------------------------------------------------
# Launchers
# ---------------------------------------------------------------------------


def _why(exc: OSError) -> str:
    """The reason of an error without the path it names: a message names no path."""
    return exc.strerror or type(exc).__name__


def _stand_in(side: str) -> Side:
    """A side record that carries only a name, for the messages of shared checks."""
    return Side(name=side or "serve", kind=KIND_SERVE)


class _LauncherBase:
    api_version: int = api.API_VERSION
    name: str = ""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        processes: ServerProcesses | None = None,
        waits: Waits | None = None,
    ) -> None:
        self._runner: CommandRunner = runner if runner is not None else run_command
        self._processes = processes if processes is not None else ServerProcesses()
        self.waits = waits if waits is not None else Waits()


class ContainerLauncher(_LauncherBase):
    """Starts a ``ServeSpec`` image in a container with one engine: docker or podman."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        processes: ServerProcesses | None = None,
        waits: Waits | None = None,
        which: Callable[..., str | None] | None = None,
    ) -> None:
        super().__init__(runner=runner, processes=processes, waits=waits)
        self._which = which

    def facts(self, environ: Mapping[str, str], *, required: bool) -> EngineFacts | None:
        """Return this launcher's engine; refuse (``E_SIDE_UNRESOLVED``) when ``required``."""
        if self._which is None:
            found = reachable_engines(self._runner, environ)
        else:
            found = reachable_engines(self._runner, environ, self._which)
        if self.name not in found:
            if required:
                raise Refusal("E_SIDE_UNRESOLVED", f"container engine not found: {self.name}")
            return None
        program, version = found[self.name]
        return engine_facts(self._runner, self.name, program, version, environ)

    @staticmethod
    def _image(spec: ServeSpec, side: str) -> str:
        if not spec.image:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: a serving side started in a container names an image",
            )
        return spec.image

    @staticmethod
    def _refuse(spec: ServeSpec, settings: LaunchSettings, facts: EngineFacts, side: str) -> None:
        refuse_image_settings(_stand_in(side), settings, facts)
        if settings.network == "none":
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {side!r}: a server on the network none cannot be reached by the load tool",
            )

    def _identity(
        self, spec: ServeSpec, details: Mapping[str, Any], settings: LaunchSettings
    ) -> dict[str, Any]:
        identity = image_identity(details)
        identity[KEY_ARGS_SHA256] = argv_sha256(spec.args)
        return identity

    def look_up(self, spec: ServeSpec, ctx: api.SideContext, *, side: str = "") -> api.SideLookup:
        """Inspect an image already on this machine; never pull, start or create anything."""
        ref = self._image(spec, side)
        facts = self.facts(ctx.environ, required=False)
        if facts is None:
            return api.SideLookup(
                status="unchecked",
                message=f"side {side}: the {self.name} engine could not be reached, so the "
                "identity of its server image was not checked",
            )
        self._refuse(spec, ctx.settings, facts, side)
        details = inspect_image(self._runner, facts, ref, ctx.environ, side=side)
        if details is None:
            if ctx.settings.pull == "never":
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side!r}: its server image is not on this machine and the pull "
                    "policy is never",
                    detail={"image": ref},
                )
            return api.SideLookup(
                status="absent",
                message=f"side {side}: its server image is not on this machine; run would pull it",
            )
        message = ""
        if ctx.settings.pull == "always":
            message = f"side {side}: run pulls its server image again (pull policy always)"
        return api.SideLookup(
            status="identified",
            identity=self._identity(spec, details, ctx.settings),
            message=message,
        )

    def resolve(
        self, spec: ServeSpec, ctx: api.SideContext, *, side: str = ""
    ) -> Mapping[str, Any]:
        """Apply the pull policy, inspect the image, run the identify command; return identity."""
        ref = self._image(spec, side)
        facts = self.facts(ctx.environ, required=True)
        assert facts is not None
        self._refuse(spec, ctx.settings, facts, side)
        require_env_pass(_stand_in(side), ctx.settings, ctx.environ)
        details = (
            None
            if ctx.settings.pull == "always"
            else inspect_image(self._runner, facts, ref, ctx.environ, side=side)
        )
        if details is None:
            if ctx.settings.pull == "never":
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side!r}: its server image is not on this machine and the pull "
                    "policy is never",
                    detail={"image": ref},
                )
            pulled = self._runner([facts.program, "pull", ref], env=dict(ctx.environ))
            details = inspect_image(self._runner, facts, ref, ctx.environ, side=side)
            if pulled.rc != 0 or details is None:
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side!r}: its server image could not be pulled",
                    detail={"image": ref, "stderr": pulled.stderr[-2000:]},
                )
        identity = self._identity(spec, details, ctx.settings)
        identity.update(self._identify(str(identity[KEY_IMAGE_ID]), spec, ctx, facts, side))
        return identity

    def identify(self, spec: ServeSpec, ctx: api.SideContext, *, side: str = "") -> dict[str, Any]:
        """Read the identity again by image ID; never pull."""
        facts = self.facts(ctx.environ, required=True)
        assert facts is not None
        ref = self._image(spec, side)
        details = inspect_image(self._runner, facts, ref, ctx.environ, side=side)
        if details is None:
            raise Refusal(
                "E_SIDE_UNIDENTIFIED",
                f"side {side!r}: its server image is no longer on this machine",
            )
        identity = self._identity(spec, details, ctx.settings)
        identity.update(self._identify(str(identity[KEY_IMAGE_ID]), spec, ctx, facts, side))
        return identity

    def _env(
        self, container_env: Mapping[str, str], environ: Mapping[str, str]
    ) -> tuple[dict[str, str], list[str]]:
        """Return the environment of the engine's command and the ``--env`` options."""
        env = dict(environ)
        options: list[str] = []
        for key, value in container_env.items():
            if engine_reads(key):
                options += ["--env", f"{key}={value}"]
            else:
                env[key] = value
                options += ["--env", key]
        return env, options

    def _container_env(self, spec: ServeSpec, ctx: api.SideContext) -> dict[str, str]:
        settings = ctx.settings
        return {
            **settings.env,
            **spec.env,
            **{key: ctx.environ[key] for key in settings.env_pass if key in ctx.environ},
        }

    def _identify(
        self,
        image_id: str,
        spec: ServeSpec,
        ctx: api.SideContext,
        facts: EngineFacts,
        side: str,
    ) -> dict[str, str]:
        identify = ctx.settings.identify
        if not identify:
            return {}
        name = api.container_name(ctx.run_id or "lookup", 0, f"{side or 'serve'}-identify")
        env, env_options = self._env(self._container_env(spec, ctx), ctx.environ)
        argv = [
            facts.program,
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            f"{RUN_LABEL}={ctx.run_id}",
            "--pull",
            "never",
            *container_options(ctx.settings, facts),
            *env_options,
            "--entrypoint",
            identify[0],
            image_id,
            *identify[1:],
        ]
        try:
            return run_identify(
                self._runner, argv, side=side, env=env, timeout_s=ctx.settings.timeout_s
            )
        finally:
            self._runner(
                [facts.program, "rm", "--force", name],
                env=dict(ctx.environ),
                timeout_s=REMOVE_WAIT_S,
            )

    def _server_command(
        self,
        facts: EngineFacts,
        image: str,
        spec: ServeSpec,
        environ: Mapping[str, str],
        *,
        side: str = "",
    ) -> list[str]:
        """The whole command the image runs for the server: its entrypoint and the arguments."""
        details = inspect_image(self._runner, facts, image, environ, side=side) or {}
        config = details.get("Config") or {}
        entry = config.get("Entrypoint") if isinstance(config, Mapping) else None
        cmd = config.get("Cmd") if isinstance(config, Mapping) else None
        words = [str(word) for word in entry] if isinstance(entry, list) else []
        if spec.args:
            return [*words, *spec.args]
        return [*words, *([str(word) for word in cmd] if isinstance(cmd, list) else [])]

    def start(
        self,
        spec: ServeSpec,
        ctx: api.SideContext,
        request: api.LaunchRequest,
        *,
        side: str = "",
    ) -> ContainerHandle:
        """Start the server's container in the foreground and return at once.

        ``spec.image`` is the image ID. The port is published on the loopback
        address at a free port of this machine, unless the container shares
        the host's network.
        """
        facts = self.facts(ctx.environ, required=True)
        assert facts is not None
        image = self._image(spec, side)
        settings = ctx.settings
        artifacts = Path(os.path.abspath(request.artifacts))
        name = api.container_name(request.run_id or ctx.run_id, request.seq, request.name)
        container_env = {**self._container_env(spec, ctx), **request.env}
        entrypoint: list[str] = []
        args: list[str] = list(spec.args)
        if request.wrap_server is not None:
            if not settings.perf_counters:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {side!r}: an instrument runs inside a server container only with the "
                    "launch setting perf_counters",
                )
            command = self._server_command(facts, image, spec, ctx.environ, side=side)
            if not command:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {side!r}: its server image names no command to put an instrument "
                    "in front of",
                )
            wrapped = request.wrap_server(command)
            entrypoint = ["--entrypoint", wrapped.argv[0]]
            args = list(wrapped.argv[1:])
            container_env.update(wrapped.env)
        if settings.network == "host":
            port = spec.port
            publish: list[str] = []
            refuse_taken_port(port, side)
        else:
            port = free_port()
            publish = ["--publish", f"{LOOPBACK}:{port}:{spec.port}"]
        volume = model_volume(spec)
        model_mount = ["--volume", volume] if volume is not None else []
        tool_options: list[str] = []
        for tool in request.tool_files:
            source = os.path.abspath(tool)
            tool_options += ["--volume", f"{source}:{api.TOOLS_IN_CONTAINER}/{tool.name}:ro"]
        engine_env, env_options = self._env(container_env, ctx.environ)
        argv = [
            facts.program,
            "run",
            "--name",
            name,
            "--label",
            f"{RUN_LABEL}={request.run_id or ctx.run_id}",
            "--pull",
            "never",
            "--volume",
            f"{artifacts}:{api.ARTIFACTS_IN_CONTAINER}",
            *publish,
            *container_options(settings, facts),
            *model_mount,
            *env_options,
            *tool_options,
            *entrypoint,
            image,
            *args,
        ]
        watcher: PidWatcher | None = None
        if facts.local:
            watcher = PidWatcher(
                self._runner,
                [facts.program, "inspect", "--format", "{{.State.Pid}}", name],
                ctx.environ,
            )
        t0 = time.monotonic()
        try:
            process = self._processes.start(argv, env=engine_env, executable=facts.program)
        except OSError as exc:
            raise Refusal(
                "E_LAUNCH_FAILED",
                f"side {side!r}: the {self.name} command could not be started: {_why(exc)}",
                detail={"rc": NOT_STARTED_RC, "timed_out": False},
            ) from None
        run_id = request.run_id or ctx.run_id
        watching = False
        try:
            if watcher is not None:
                watcher.start()
                watching = True
            return ContainerHandle(
                facts=facts,
                name=name,
                runner=self._runner,
                environ=ctx.environ,
                note=ctx.note,
                watcher=watcher,
                image=image,
                settings=settings,
                run_id=run_id,
                process=process,
                base_url=f"http://{LOOPBACK}:{port}",
                model_name=spec.model_name,
                artifacts=artifacts,
                gpu=ctx.gpu,
                waits=self.waits,
                t0=t0,
            )
        except BaseException:
            # The engine runs the server's container from here on. However
            # its start is cut short, the engine's client is stopped first,
            # so it cannot start the container after the container is
            # removed; what the container wrote then goes back to the caller
            # before the exception goes on.
            try:
                try:
                    if watching and watcher is not None:
                        with contextlib.suppress(Exception):
                            watcher.stop()
                    with contextlib.suppress(Exception):
                        process.kill_session()
                        process.wait(5.0)
                        process.close()
                finally:
                    with contextlib.suppress(Exception):
                        remove_server(self._runner, facts.program, name, ctx.environ, ctx.note)
            finally:

                def remove(container: str) -> None:
                    self._runner(
                        [facts.program, "rm", "--force", container],
                        env=ctx.environ,
                        timeout_s=REMOVE_WAIT_S,
                    )

                def give_back() -> str | None:
                    return hand_back(
                        self._runner,
                        facts,
                        image,
                        artifacts,
                        name=f"{name}-chown",
                        run_id=run_id,
                        settings=settings,
                        environ=ctx.environ,
                        remove=remove,
                    )

                give_back_after_stop(give_back, ctx.note, side, artifacts)
            raise


class DockerLauncher(ContainerLauncher):
    """The ``docker`` launcher."""

    name = LAUNCHER_DOCKER


class PodmanLauncher(ContainerLauncher):
    """The ``podman`` launcher."""

    name = LAUNCHER_PODMAN


class HostLauncher(_LauncherBase):
    """Starts a ``ServeSpec``'s ``command``, then its ``args``, as a process on this machine."""

    name = LAUNCHER_HOST

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # By side: the CPUs the tool could run on when a side without a CPU
        # set of its own was resolved, before it moved off a pinned set.
        self._homes: dict[str, frozenset[int] | None] = {}

    @staticmethod
    def argv(spec: ServeSpec, side: str = "") -> tuple[str, ...]:
        """The server's command line: ``command`` and then ``args``."""
        if not spec.command:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: a serving side started by the host launcher names a command",
            )
        if spec.image:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: the host launcher takes command in place of image; give one",
            )
        return (*spec.command, *spec.args)

    def _plan(
        self, spec: ServeSpec, ctx: api.SideContext, side: str
    ) -> tuple[tuple[str, ...], str, dict[str, str], str | None]:
        argv = self.argv(spec, side)
        stand_in = _stand_in(side)
        refuse_host_settings(stand_in, ctx.settings)
        cwd = resolve_workdir(stand_in, ctx.settings)
        environment = host_environment(ctx.environ, ctx.settings)
        environment.update(spec.env)
        executable = find_executable(argv[0], environment=environment, cwd=cwd)
        if executable is None:
            raise Refusal(
                "E_SIDE_UNRESOLVED",
                f"side {side!r}: the server command {Path(argv[0]).name!r} was not found",
                detail={"executable": argv[0]},
            )
        return argv, executable, environment, cwd

    def _identity(self, argv: Sequence[str], executable: str, side: str) -> dict[str, Any]:
        return {
            KEY_EXECUTABLE: executable,
            KEY_EXECUTABLE_SHA256: side_file_sha256(side, "server command", Path(executable)),
            KEY_ARGV_SHA256: argv_sha256(argv),
        }

    def look_up(self, spec: ServeSpec, ctx: api.SideContext, *, side: str = "") -> api.SideLookup:
        """Find the server's executable and hash it; run nothing."""
        argv, executable, _env, _cwd = self._plan(spec, ctx, side)
        return api.SideLookup(status="identified", identity=self._identity(argv, executable, side))

    def resolve(
        self, spec: ServeSpec, ctx: api.SideContext, *, side: str = ""
    ) -> Mapping[str, Any]:
        """Find and hash the executable, run the identify command; return the identity."""
        identity = self.identify(spec, ctx, side=side)
        self._homes[side] = None if ctx.settings.cpus else HostProcesses().home()
        return identity

    def identify(self, spec: ServeSpec, ctx: api.SideContext, *, side: str = "") -> dict[str, Any]:
        """Read the identity again: the executable's hash and the identify command's output."""
        argv, executable, environment, cwd = self._plan(spec, ctx, side)
        require_env_pass(_stand_in(side), ctx.settings, ctx.environ)
        identity = self._identity(argv, executable, side)
        identity.update(
            identify_on_host(
                self._runner, _stand_in(side), ctx.settings, environment=environment, cwd=cwd
            )
        )
        return identity

    def start(
        self,
        spec: ServeSpec,
        ctx: api.SideContext,
        request: api.LaunchRequest,
        *,
        side: str = "",
    ) -> HostHandle:
        """Start the server process and return at once."""
        argv, executable, environment, cwd = self._plan(spec, ctx, side)
        env = {**environment, **request.env}
        command: tuple[str, ...] = argv
        start_executable: str | None = executable
        if request.wrap_server is not None:
            wrapped = request.wrap_server(list(argv))
            command = tuple(wrapped.argv)
            env.update(wrapped.env)
            start_executable = None
        own = parse_cpu_list(ctx.settings.cpus, side=side) if ctx.settings.cpus else None
        artifacts = Path(os.path.abspath(request.artifacts))
        refuse_taken_port(spec.port, side)
        t0 = time.monotonic()
        try:
            try:
                process = self._processes.start(
                    command,
                    env=env,
                    cwd=cwd,
                    executable=start_executable,
                    cpus=own if own is not None else self._homes.get(side),
                )
            except PinningFailed:
                if own is not None:
                    raise
                # The CPUs the tool had cannot be given back: start where the tool runs.
                process = self._processes.start(
                    command, env=env, cwd=cwd, executable=start_executable
                )
        except PinningFailed as exc:
            raise Refusal(
                "E_PIN_UNSUPPORTED",
                f"side {side!r}: the CPUs of the launch setting cpus cannot be pinned on this "
                "machine",
                detail={"cpus": ctx.settings.cpus, "error": str(exc)},
            ) from exc
        except OSError as exc:
            raise Refusal(
                "E_LAUNCH_FAILED",
                f"side {side!r}: the server command could not be started: {_why(exc)}",
                detail={"rc": NOT_STARTED_RC, "timed_out": False},
            ) from None
        return HostHandle(
            process=process,
            base_url=f"http://{LOOPBACK}:{spec.port}",
            model_name=spec.model_name,
            artifacts=artifacts,
            gpu=ctx.gpu,
            waits=self.waits,
            t0=t0,
        )


# ---------------------------------------------------------------------------
# The resolved side
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Failure:
    rc: int
    timed_out: bool
    message: str


class ServeResolved:
    """A resolved serving side: one server start per launch, the load run against it."""

    def __init__(
        self,
        *,
        side: Side,
        spec: ServeSpec,
        start_spec: ServeSpec,
        launcher: api.Launcher,
        ctx: api.SideContext,
        engine: EngineInfo | None,
        waits: Waits,
    ) -> None:
        self._side = side
        self._spec = spec
        self._start_spec = start_spec
        self._launcher = launcher
        self._ctx = ctx
        self._engine = engine
        self._waits = waits
        self._phases = phase_patterns(spec, side.name)
        self._hand_back_noted = False

    @property
    def side(self) -> Side:
        return self._side

    @property
    def command(self) -> tuple[str, ...] | None:
        return None

    @property
    def engine(self) -> EngineInfo | None:
        return self._engine

    @property
    def rounds_available(self) -> int | None:
        return None

    @property
    def cannot_repeat(self) -> str | None:
        """A serving launch repeats its load against one server start, so it always can."""
        return None

    @property
    def in_container(self) -> bool:
        return self._launcher.name != LAUNCHER_HOST

    def identify(self) -> Mapping[str, Any]:
        """Read the identity again; never pull."""
        launcher = self._launcher
        if isinstance(launcher, ContainerLauncher | HostLauncher):
            return launcher.identify(self._start_spec, self._ctx, side=self._side.name)
        return launcher.look_up(self._start_spec, self._ctx).identity

    def artifacts_in_side(self, host: Path) -> str:
        if self.in_container:
            return api.ARTIFACTS_IN_CONTAINER
        return os.path.abspath(host)

    def tool_file_in_side(self, host: Path) -> str:
        if self.in_container:
            return f"{api.TOOLS_IN_CONTAINER}/{host.name}"
        return os.path.abspath(host)

    def close(self) -> None:
        return None

    # --- one launch ------------------------------------------------------

    def _gpu_level(self) -> float | None:
        """Step 1: wait for the GPUs to be free, then record the GPU memory in use."""
        gpu = self._ctx.gpu
        if gpu is None:
            return None
        if not wait_gpu_free(gpu, self._waits.free_s, self._waits.poll_s):
            message = (
                f"side {self._side.name}: the selected GPUs still held another compute process "
                f"after {self._waits.free_s:g} s, or could not be read, before the server start"
            )
            if self._ctx.mode == "enforce":
                raise Refusal("E_GATE_FAILED", message)
            self._ctx.note(NOTE_GPU_BUSY, message)
        level = gpu.memory_used_mib()
        if level is None:
            self._ctx.note(
                NOTE_GPU_MEMORY_UNREADABLE,
                f"side {self._side.name}: the GPU memory in use could not be read before the "
                "server start, so the wait for it to be released after the stop is skipped",
            )
        return level

    def _start(self, request: api.LaunchRequest) -> api.ServerHandle:
        launcher = self._launcher
        if isinstance(launcher, ContainerLauncher | HostLauncher):
            return launcher.start(self._start_spec, self._ctx, request, side=self._side.name)
        return launcher.start(self._start_spec, self._ctx, request)

    def launch(self, request: api.LaunchRequest) -> api.LaunchOutcome:
        """Run the seven steps of a serving launch; the server is stopped on every path."""
        if request.second is not None:
            raise Refusal(
                "E_INTERNAL",
                "a serving launch runs its load twice through the load callback, never as a "
                "second command",
            )
        with _ONE_SERVER:
            began = time.monotonic()
            level = self._gpu_level()
            # The launch timeout runs from the server start to the end of the
            # load; the GPU waits before the start and after the stop keep
            # their own limits.
            failure: _Failure | None = None
            samples: list[api.Sample] = []
            notes: list[api.LaunchNote] = []
            timing: dict[str, float] = {}
            usage: dict[str, float] = {}
            started = time.monotonic()
            # From here on, the start itself stops and removes the server
            # when it is cut short; once it returns, the try below does.
            try:
                handle = self._start(request)
            except Refusal as exc:
                if exc.code != "E_LAUNCH_FAILED":
                    raise
                rc = (exc.detail or {}).get("rc")
                self._write_failure(request.artifacts, exc.message)
                return api.LaunchOutcome(
                    rc=rc if isinstance(rc, int) and rc != 0 else NOT_STARTED_RC,
                    timing={api.TIMING_LAUNCH_S: time.monotonic() - began},
                )
            try:
                try:
                    failure = self._serve(handle, request, samples, notes, timing, usage, started)
                finally:
                    handle.stop()
                stopped = time.monotonic()
                if level is not None:
                    handle.wait_released(
                        level,
                        tolerance_mib=api.GPU_RELEASE_TOLERANCE_MIB,
                        timeout_s=self._waits.release_s,
                    )
                finished = time.monotonic()
            except BaseException:
                # However the launch stops, what the server's container wrote
                # goes back to the caller before the run's owner-only pass and
                # before it exits.
                self._hand_back(handle, request.artifacts, stopped=True)
                raise
            # After both times are read, so the hand-back is not timed.
            self._hand_back(handle, request.artifacts)
        t0 = getattr(handle, "t0", began)
        timing[api.TIMING_RUN_S] = stopped - t0
        timing[api.TIMING_LAUNCH_S] = finished - began
        rc = 0
        timed_out = False
        if failure is not None:
            rc, timed_out = failure.rc, failure.timed_out
            self._write_failure(request.artifacts, failure.message)
        cpu_s = getattr(handle, "cpu_s", None)
        return api.LaunchOutcome(
            rc=rc,
            timing=timing,
            timed_out=timed_out,
            cpu_s=cpu_s if isinstance(cpu_s, float) else None,
            samples=tuple(samples),
            pid=getattr(handle, "pid", None),
            usage=usage,
            notes=tuple(notes),
        )

    def _hand_back(self, handle: api.ServerHandle, folder: Path, *, stopped: bool = False) -> None:
        """Give back the files the server's container left to another user; note when it cannot.

        As for an image side: the note names the folder once per side for
        launches that ended as they should, and every time for a launch that
        stopped on an exception or an interrupt (``stopped``). When the
        hand-back itself is stopped, the note names the folder before the
        exception goes on; an error in the hand-back of a stopped launch is
        not raised, so the exception that stopped the launch goes on in its
        place.
        """
        give_back = getattr(handle, "hand_back", None)
        if not callable(give_back):
            return
        name = self._side.name
        if stopped:
            give_back_after_stop(give_back, self._ctx.note, name, folder)
            return
        try:
            reason = give_back()
        except BaseException as exc:
            why = (
                f"the hand-back stopped on an error ({type(exc).__name__})"
                if isinstance(exc, Exception)
                else "an interrupt stopped the hand-back before it ended"
            )
            self._ctx.note(
                NOTE_FILES_NOT_HANDED_BACK, files_kept_note(name, folder, why, once=False)
            )
            raise
        if not isinstance(reason, str):
            return
        if self._hand_back_noted:
            return
        self._hand_back_noted = True
        self._ctx.note(NOTE_FILES_NOT_HANDED_BACK, files_kept_note(name, folder, reason))

    def _serve(
        self,
        handle: api.ServerHandle,
        request: api.LaunchRequest,
        samples: list[api.Sample],
        notes: list[api.LaunchNote],
        timing: dict[str, float],
        usage: dict[str, float],
        started: float,
    ) -> _Failure | None:
        """Steps 3 to 5. A server that fails before the load gives the failure it reports.

        With a launch timeout, the readiness wait, the first answer and the
        load all end by ``started`` plus the timeout, whichever of them runs
        at that moment; the load is handed that moment as its deadline.
        """
        spec = self._spec
        limit = self._ctx.settings.timeout_s
        deadline = None if limit is None else started + limit
        t0 = getattr(handle, "t0", started)
        t0 = t0 if isinstance(t0, float) else started
        allowed = spec.ready.timeout_s
        limited = deadline is not None and deadline - t0 < allowed
        if deadline is not None and limited:
            allowed = max(0.0, deadline - t0)
        stage = "before the server was ready"
        try:
            ready = dataclasses.replace(spec.ready, timeout_s=allowed) if limited else spec.ready
            ready_s = handle.wait_ready(ready)
            stage = "before the server's first answer"
            if isinstance(handle, _Handle):
                first_s = handle.first_answer(spec.probe, timeout_s=allowed)
            else:
                first_s = handle.first_answer(spec.probe)
        except Refusal as exc:
            if exc.code != "E_LAUNCH_FAILED":
                raise
            detail = exc.detail or {}
            exit_code = getattr(handle, "exit_code", None)
            rc = exit_code if isinstance(exit_code, int) and exit_code != 0 else 1
            timed_out = bool(detail.get("timed_out"))
            message = exc.message
            if timed_out and limited and limit is not None:
                message = f"the launch ran into its timeout of {limit:g} s {stage}"
            return _Failure(rc=rc, timed_out=timed_out, message=message)
        samples.append(startup_sample(CASE_STARTUP_READY, ready_s))
        samples.append(startup_sample(CASE_STARTUP_FIRST_ANSWER, first_s))
        phases = getattr(handle, "phases", None)
        if callable(phases):
            reading = phases(self._phases)
            for name, seconds in reading.times.items():
                samples.append(startup_sample(phase_case(name), seconds))
            if request.phase in NOTED_PHASES:
                notes += phase_notes(request.name, reading)
        if request.load is not None:
            begin = getattr(handle, "begin_load", None)
            end = getattr(handle, "end_load", None)
            before = begin() if callable(begin) else None
            endpoint = handle.endpoint
            if deadline is not None:
                endpoint = dataclasses.replace(endpoint, deadline=deadline)
            request.load(endpoint)
            load_ended = time.monotonic()
            if callable(end):
                cpu, figures = end(before)
                timing.update(cpu)
                usage.update(figures)
            # The load may have run, in part, against no server at all.
            exited = getattr(handle, "exited_during_load", None)
            gone_rc = exited() if callable(exited) else None
            if isinstance(gone_rc, int):
                return _Failure(
                    rc=gone_rc if gone_rc != 0 else 1,
                    timed_out=False,
                    message=f"the server exited with {gone_rc} during the load",
                )
            if deadline is not None and limit is not None and load_ended >= deadline:
                return _Failure(
                    rc=1,
                    timed_out=True,
                    message=f"the launch ran into its timeout of {limit:g} s during the load",
                )
        return None

    @staticmethod
    def _write_failure(artifacts: Path, message: str) -> None:
        with contextlib.suppress(OSError):
            Path(artifacts).mkdir(parents=True, exist_ok=True)
            with open_private(Path(artifacts) / api.ARTIFACT_STDERR, append=True) as handle:
                handle.write(f"pairbench: {message}\n".encode())


# ---------------------------------------------------------------------------
# The kind
# ---------------------------------------------------------------------------


class ServeKind(KindBase):
    """The ``serve`` side kind."""

    name = KIND_SERVE

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        host: HostProcesses | None = None,
        launchers: Mapping[str, api.Launcher] | None = None,
        waits: Waits | None = None,
        which: Callable[..., str | None] | None = None,
    ) -> None:
        super().__init__(runner=runner, host=host)
        self._launchers = dict(launchers) if launchers is not None else None
        self._waits = waits
        self._which = which

    def _launcher_name(
        self, spec: ServeSpec, settings: LaunchSettings, environ: Mapping[str, str], side: str
    ) -> str | None:
        """The launcher of a side: ``serve.launcher``, else the engine the settings choose.

        ``None`` when the choice follows ``auto`` and no engine can be reached.
        """
        if spec.launcher:
            return spec.launcher
        if not spec.image:
            raise Refusal(
                "E_USAGE",
                f"side {side!r}: a serving side without an image names its launcher "
                "(serve.launcher = host for a command)",
            )
        if settings.engine in api.ENGINES:
            return settings.engine
        if self._which is None:
            found = reachable_engines(self._runner, environ)
        else:
            found = reachable_engines(self._runner, environ, self._which)
        return api.find_engine(settings.engine, list(found), environ)

    def launcher(self, name: str) -> api.Launcher:
        """Return the launcher of this name: the one handed in, else the registered one."""
        if self._launchers is not None and name in self._launchers:
            return self._launchers[name]
        return registry.launcher(name)

    def look_up(self, side: Side, ctx: api.SideContext) -> api.SideLookup:
        """Read the identity of the server without starting it; fill in the fingerprint."""
        spec = serve_spec(side)
        phase_patterns(spec, side.name)
        check_paths(spec, side.name)
        name = self._launcher_name(spec, ctx.settings, ctx.environ, side.name)
        if name is None:
            return api.SideLookup(
                status="unchecked",
                message=f"side {side.name}: no container engine could be reached, so the "
                "identity of its server was not checked",
            )
        launcher = self.launcher(name)
        if isinstance(launcher, ContainerLauncher | HostLauncher):
            found = launcher.look_up(spec, ctx, side=side.name)
        else:
            found = launcher.look_up(spec, ctx)
        if found.status != "identified" or ctx.settings.identify:
            return found
        fingerprint = fingerprint_of(found.identity, _effective(ctx.settings, spec, name))
        return dataclasses.replace(found, fingerprint=fingerprint)

    def resolve(self, side: Side, ctx: api.SideContext) -> api.ResolvedSide:
        """Resolve the server through its launcher and record identity and fingerprint."""
        spec = serve_spec(side)
        phase_patterns(spec, side.name)
        check_paths(spec, side.name)
        name = self._launcher_name(spec, ctx.settings, ctx.environ, side.name)
        if name is None:
            api.choose_engine(ctx.settings.engine, [], ctx.environ)
            raise Refusal(
                "E_SIDE_UNRESOLVED", "no container engine found: neither docker nor podman"
            )
        launcher = self.launcher(name)
        if isinstance(launcher, ContainerLauncher | HostLauncher):
            identity = dict(launcher.resolve(spec, ctx, side=side.name))
        else:
            identity = dict(launcher.resolve(spec, ctx))
        fingerprint = fingerprint_of(identity, _effective(ctx.settings, spec, name))
        start_spec = spec
        engine: EngineInfo | None = None
        if name != LAUNCHER_HOST and isinstance(identity.get(KEY_IMAGE_ID), str):
            start_spec = dataclasses.replace(spec, image=str(identity[KEY_IMAGE_ID]))
        if isinstance(launcher, ContainerLauncher):
            facts = launcher.facts(ctx.environ, required=False)
            engine = facts.info() if facts is not None else None
        waits = self._waits
        if waits is None:
            waits = launcher.waits if isinstance(launcher, _LauncherBase) else Waits()
        return ServeResolved(
            side=side.with_identity(identity, fingerprint),
            spec=spec,
            start_spec=start_spec,
            launcher=launcher,
            ctx=ctx,
            engine=engine,
            waits=waits,
        )


def model_volume(spec: ServeSpec) -> str | None:
    """The read-only mount of a container server's model location, at the same path."""
    if not spec.model or not Path(spec.model).exists():
        return None
    where = os.path.abspath(spec.model)
    return f"{where}:{where}:ro"


def _effective(settings: LaunchSettings, spec: ServeSpec, launcher: str) -> dict[str, Any]:
    """The part of the settings and the spec that goes into a serving side's fingerprint."""
    args: Sequence[str] = spec.args
    mounts: tuple[str, ...] = ()
    if launcher == LAUNCHER_HOST:
        args = (*spec.command, *spec.args)
    else:
        volume = model_volume(spec)
        mounts = (volume,) if volume is not None else ()
    return settings.effective(args=args, env=spec.env, mounts=mounts)
