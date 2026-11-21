# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``image`` side kind: a container image, one fresh container per launch.

Engines. docker and podman are driven through their command-line programs.
Every difference between the two lives in this module. What the engines take
and report is as their own documentation describes it:

* docker: the ``docker container run`` reference
  (https://docs.docker.com/reference/cli/docker/container/run/, read for
  docker 29.8) for ``--gpus all``, ``--gpus '"device=0,2"'``,
  ``--pull never`` and ``--env NAME``; the Docker Engine API 1.51
  (https://docs.docker.com/reference/api/engine/version/v1.51.yaml) for the
  ``SystemInfo`` fields ``CPUSet``, ``MemoryLimit`` and ``SecurityOptions``
  (which lists ``name=rootless`` on a rootless daemon) and the
  ``ContainerState`` fields ``StartedAt``, ``FinishedAt``, ``ExitCode`` and
  ``Pid``.
* podman: the ``podman run`` page
  (https://docs.podman.io/en/v5.4.0/markdown/podman-run.1.html, podman
  5.4.0), which says ``--cpuset-cpus``, ``--memory`` and ``--memory-swap``
  are not supported on cgroups v1 rootless systems, and the ``podman image
  inspect`` page of the same release, whose ``Id`` carries no ``sha256:``
  in front. GPUs are CDI device names, ``--device nvidia.com/gpu=all`` or one
  ``--device nvidia.com/gpu=<index>`` per GPU, as the NVIDIA Container
  Toolkit's CDI page shows
  (https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html,
  read for toolkit 1.18).

A request the engine cannot honour, such as a CPU set on an engine that
cannot pin, is refused with the reason.

Lifecycle. The pull policy applies in ``resolve`` and nowhere else. A launch
starts the image by its ID with pulling disabled, in a container named with
``api.container_name`` and labelled with the run id, with the launch's folder
mounted at ``api.ARTIFACTS_IN_CONTAINER``. After it exits the engine is asked
for the container's state, and the container is removed, also after a
timeout, a failure or an interrupt. Leftover containers carry the label and
are listed by ``ImageKind.doctor``.

Ownership. Files a container writes into the launch's folder belong to the
image's user, often root. After a launch that left such files, on an engine
that runs containers on this machine, one short container of the same image
runs ``chown`` as root on the folder, with the launch's memory limit and CPU
set and no network, and is removed after it (``hand_back``; a serving side's
server container gets the same after it stops). When that cannot be done
(the image holds no ``chown``, the engine refuses, or the engine runs
rootless so the files belong to a user id of its user namespace), one loud
note per side names the folder.

Timings. ``run_s`` is the container's own start-to-finish time as the engine
reports it; ``launch_s`` is the wall time on the host from the start request
to the exit of the engine's command.

Resource usage. Of the engine, a launch reads only the container's state: its
exit code, the id of its first process and its start and finish times. It
reads no resource figure, so it reports no CPU time and no other resource
figure: ``cpu_s`` is ``None`` and ``usage`` is empty. ``container_usage`` is
the one place that would read them.

Values of environment variables reach the container through the environment
of the engine's command (``--env NAME``), so they do not appear on a command
line another user of the machine can list. A variable the engine's command
reads itself (``engine_reads``) is passed as ``--env NAME=VALUE`` instead, so
the engine's command keeps the caller's value; ``env_pass`` refuses such a
name.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import shlex
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import (
    IMAGE_COMMAND_PROGRAM_KEY,
    IMAGE_ENTRYPOINT_KEY,
    KIND_IMAGE,
    EngineInfo,
    LaunchSettings,
    Side,
    fingerprint_of,
)
from pairbench.sides.base import (
    CommandRunner,
    HostProcesses,
    HostRun,
    KindBase,
    launch_on_host,
    open_private,
    parse_cpu_list,
    require_env_pass,
)
from pairbench.sides.identity import (
    KEY_DIGESTS,
    KEY_IMAGE_ID,
    KEY_PLATFORM,
    digest_hashes,
    run_identify,
)

# The label every container of a launch carries; its value is the run id.
RUN_LABEL: Final = "pairbench.run"
# The loud note given when a container could not be removed after its launch.
NOTE_CONTAINER_NOT_REMOVED: Final = "container_not_removed"
# The capability that lets a process use performance counters.
PERF_CAPABILITY: Final = "PERFMON"
# The shell one container runs two commands with.
SHELL: Final = "/bin/sh"
# How often the id of a container's first process is asked for while it starts.
PID_POLL_S: Final = 0.05
# How long the engine's command that removes a container may take.
REMOVE_WAIT_S: Final = 60.0
# How long the container that hands a launch's files back to the calling user may take.
HAND_BACK_WAIT_S: Final = 60.0
# How long a question to the engine (its version, its facts, the details of an image,
# its containers) may take before it counts as not answered.
ENGINE_QUERY_WAIT_S: Final = 60.0
# The loud note given when files a container wrote stay with another user.
NOTE_FILES_NOT_HANDED_BACK: Final = "files_not_handed_back"
# The exit code of a command that is not found in the image.
NOT_FOUND_RC: Final = 127
# The exit code of ``run`` when the engine itself fails, its daemon out of reach
# included. Docker's "Running containers", "Exit status"
# (https://docs.docker.com/engine/containers/run/#exit-status: "the error is with
# Docker daemon itself"), and podman-run(1) of Podman 5.4.0, "Exit Status"
# (https://docs.podman.io/en/v5.4.0/markdown/podman-run.1.html: "The error is with
# Podman itself"), both give 125.
ENGINE_FAILED_RC: Final = 125
# The exit code of the repeat check when the shell ran but could not write
# the run folders' files: the image's user may not write in the mounted folder.
WRITE_CHECK_RC: Final = 3
# The exit code of the repeat check when the run folders pairbench created in
# the mounted folder are not there: the container does not see that folder.
MISSING_CHECK_RC: Final = 4
# What a shell writes when it may not open a file for a redirection.
DENIED_WORDS: Final = "permission denied"
# How much of the end of a launch's standard error is read for that message.
STDERR_TAIL_BYTES: Final = 65536
# The form of a memory limit both engines read: a whole number with an
# optional unit b, k, m or g.
MEMORY_PATTERN: Final = re.compile(r"[0-9]+[bkmgBKMG]?")
# A variable name the shell can assign.
SHELL_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Variables the engine's own command reads, by name and by prefix. A container
# variable of such a name is passed on the command line, so the engine's
# command keeps the caller's value; an ``env_pass`` variable of such a name is
# refused, since its value would then show on that command line.
ENGINE_OWN_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "HOME",
        "PATH",
        "TMPDIR",
        "USER",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "GODEBUG",
        "GOGC",
        "GOMAXPROCS",
        "GOMEMLIMIT",
        "GOTRACEBACK",
    }
)
ENGINE_OWN_PREFIXES: Final[tuple[str, ...]] = (
    "DOCKER_",
    "CONTAINER_",
    "CONTAINERS_",
    "BUILDAH_",
    "REGISTRY_AUTH",
    "XDG_",
    "LD_",
    "DYLD_",
)
# The variables that point an engine's command at another machine.
REMOTE_VARIABLES: Final[Mapping[str, str]] = {"docker": "DOCKER_HOST", "podman": "CONTAINER_HOST"}
_ENGINE_TIME = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)(?:\s.*)?")


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineFacts:
    """What a launch needs to know about the engine it uses.

    ``cpuset`` and ``memory`` say whether the engine can pin a container to
    CPUs and limit its memory. ``local`` says the engine runs containers on
    this machine, so the id of a container's process is an id of this
    machine.
    """

    name: str
    program: str
    version: str
    rootless: bool = False
    cpuset: bool = True
    memory: bool = True
    local: bool = True

    def info(self) -> EngineInfo:
        return EngineInfo(name=self.name, version=self.version)


def _version_argv(program: str, engine: str) -> list[str]:
    field_name = "Server" if engine == "docker" else "Client"
    return [program, "version", "--format", f"{{{{.{field_name}.Version}}}}"]


def reachable_engines(
    runner: CommandRunner,
    environ: Mapping[str, str],
    which: Callable[..., str | None] = shutil.which,
) -> dict[str, tuple[str, str]]:
    """Return the engines whose program is on ``PATH`` and answers, as ``{name: (program,
    version)}``."""
    found: dict[str, tuple[str, str]] = {}
    for engine in api.ENGINES:
        program = which(engine, path=environ.get("PATH", os.defpath))
        if not program:
            continue
        done = runner(
            _version_argv(program, engine), env=dict(environ), timeout_s=ENGINE_QUERY_WAIT_S
        )
        version = done.stdout.strip()
        if done.rc == 0 and not done.timed_out and version:
            found[engine] = (program, version.splitlines()[0])
    return found


def engine_is_local(engine: str, environ: Mapping[str, str], system: str | None = None) -> bool:
    """Say whether the engine runs its containers on this machine, as its processes.

    That holds on Linux when the engine's command is not pointed at another
    machine by ``DOCKER_HOST`` or ``CONTAINER_HOST``. Elsewhere the engine runs
    containers in a virtual machine. ``system`` is the platform name, by
    default ``platform.system()``.
    """
    remote = environ.get(REMOTE_VARIABLES.get(engine, ""), "")
    name = system if system is not None else platform.system()
    return name == "Linux" and (not remote or remote.startswith("unix://"))


def engine_facts(
    runner: CommandRunner, engine: str, program: str, version: str, environ: Mapping[str, str]
) -> EngineFacts:
    """Ask the engine whether it runs rootless and which limits it can set."""
    local = engine_is_local(engine, environ)
    if engine == "docker":
        done = runner(
            [program, "info", "--format", "{{json .}}"],
            env=dict(environ),
            timeout_s=ENGINE_QUERY_WAIT_S,
        )
        info = _json_object(done.stdout) if done.rc == 0 else {}
        options = info.get("SecurityOptions") or []
        rootless = any("rootless" in str(item) for item in options)
        return EngineFacts(
            name=engine,
            program=program,
            version=version,
            rootless=rootless,
            cpuset=bool(info.get("CPUSet", True)),
            memory=bool(info.get("MemoryLimit", True)),
            local=local,
        )
    done = runner(
        [program, "info", "--format", "json"], env=dict(environ), timeout_s=ENGINE_QUERY_WAIT_S
    )
    info = _json_object(done.stdout) if done.rc == 0 else {}
    host = _mapping(info.get("host"))
    rootless = bool(_mapping(host.get("security")).get("rootless", False))
    controllers = [str(item) for item in host.get("cgroupControllers") or []]
    version_one = str(host.get("cgroupVersion", "")).lower() == "v1"
    return EngineFacts(
        name=engine,
        program=program,
        version=version,
        rootless=rootless,
        cpuset=not rootless or (not version_one and "cpuset" in controllers),
        memory=not rootless or (not version_one and "memory" in controllers),
        local=local,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return _mapping(value)


def gpu_options(engine: str, gpus: str) -> list[str]:
    """Return the options that give a container the GPUs ``gpus`` selects (``all`` or indices)."""
    if engine == "docker":
        return ["--gpus", "all" if gpus == "all" else f'"device={gpus}"']
    if gpus == "all":
        return ["--device", "nvidia.com/gpu=all"]
    out: list[str] = []
    for index in gpus.split(","):
        out.extend(["--device", f"nvidia.com/gpu={index}"])
    return out


def memory_options(memory: str | None) -> list[str]:
    """Return the options that limit a container to ``memory`` with no swap.

    Docker's "Resource constraints", "--memory-swap details"
    (https://docs.docker.com/engine/containers/resource_constraints/): with
    ``--memory-swap`` at the same value as ``--memory``, "the container doesn't
    have access to swap"; without it, the container "can use as much swap as
    the --memory setting". ``None`` gives no options.
    """
    return [] if memory is None else ["--memory", memory, "--memory-swap", memory]


def container_options(
    settings: LaunchSettings, facts: EngineFacts, *, gpus: bool = True
) -> list[str]:
    """Return the options of ``engine run`` that apply the launch settings.

    ``cpus`` pins the container to its CPU set, ``memory`` limits its memory
    and leaves it no swap beyond that, ``gpus`` gives it GPUs in the engine's
    own syntax, ``perf_counters`` adds the capability to use performance
    counters and no other capability. Nothing is ever run privileged.
    """
    options: list[str] = []
    if settings.cpus is not None:
        options += ["--cpuset-cpus", settings.cpus]
    options += memory_options(settings.memory)
    if gpus and settings.gpus is not None:
        options += gpu_options(facts.name, settings.gpus)
    if settings.network is not None:
        options += ["--network", settings.network]
    if settings.workdir is not None:
        options += ["--workdir", settings.workdir]
    for mount in settings.mounts:
        options += ["--volume", mount]
    if settings.perf_counters:
        options += ["--cap-add", PERF_CAPABILITY]
    return options


def engine_reads(name: str) -> bool:
    """Say whether the engine's own command reads the variable ``name``."""
    upper = name.upper()
    return upper in ENGINE_OWN_VARIABLES or upper.startswith(ENGINE_OWN_PREFIXES)


def refuse_image_settings(side: Side, settings: LaunchSettings, facts: EngineFacts) -> None:
    """Refuse a launch setting the engine cannot honour, with the reason."""
    private = sorted(name for name in settings.env_pass if engine_reads(name))
    if private:
        raise Refusal(
            "E_ENGINE_UNSUPPORTED",
            f"side {side.name!r}: the {facts.name} command reads the variable "
            f"{', '.join(private)} itself, so env_pass cannot forward it to the container "
            "without showing its value on a command line",
        )
    if settings.memory is not None and not MEMORY_PATTERN.fullmatch(settings.memory):
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: memory is a whole number with an optional unit b, k, m or g: "
            f"{settings.memory!r}",
        )
    if settings.cpus is not None:
        parse_cpu_list(settings.cpus, side=side.name)
        if not facts.cpuset:
            raise Refusal("E_ENGINE_UNSUPPORTED", _cannot(side, facts, "cpus", "cpuset"))
    if settings.memory is not None and not facts.memory:
        raise Refusal("E_ENGINE_UNSUPPORTED", _cannot(side, facts, "memory", "memory"))


def _cannot(side: Side, facts: EngineFacts, setting: str, controller: str) -> str:
    what = "pin a container to CPUs" if setting == "cpus" else "limit the memory of a container"
    why = f" (it runs rootless without the {controller} controller)" if facts.rootless else ""
    return (
        f"side {side.name!r}: the {facts.name} engine cannot {what} here{why}, "
        f"so the launch setting {setting} cannot be honoured"
    )


# ---------------------------------------------------------------------------
# The image
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageSpec:
    """What an image side declares: the reference, its own arguments, environment, entrypoint."""

    ref: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    entrypoint: str | None = None


def image_spec(side: Side) -> ImageSpec:
    """Read the spec of an image side, or refuse one the kind cannot read with ``E_USAGE``."""
    spec = side.spec
    ref = spec.get("image")
    args = spec.get("args") or ()
    env = spec.get("env") or {}
    entrypoint = spec.get("entrypoint")
    if (
        not isinstance(ref, str)
        or not ref
        or isinstance(args, str)
        or not isinstance(args, Sequence)
        or not all(isinstance(arg, str) for arg in args)
        or not isinstance(env, Mapping)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        or (entrypoint is not None and not isinstance(entrypoint, str))
    ):
        raise Refusal(
            "E_USAGE",
            f"side {side.name!r}: an image side names an image, and its args, env and "
            "entrypoint are texts",
        )
    return ImageSpec(ref=ref, args=tuple(args), env=dict(env), entrypoint=entrypoint)


def image_identity(details: Mapping[str, Any]) -> dict[str, Any]:
    """Read the identity of an image from the engine's inspect output.

    ``image_id`` is the engine's image ID, ``digests`` the digest hashes
    without registry or repository, ``platform`` the operating system and
    architecture, with the variant where the image has one. This is the one
    function both ``look_up`` and ``resolve`` use.
    """
    image_id = details.get("Id")
    if not isinstance(image_id, str) or not image_id:
        raise Refusal("E_SIDE_UNIDENTIFIED", "the engine reported no image ID")
    repo_digests = details.get("RepoDigests") or []
    platform = "/".join(
        str(part)
        for part in (details.get("Os"), details.get("Architecture"), details.get("Variant"))
        if part
    )
    return {
        KEY_IMAGE_ID: image_id,
        KEY_DIGESTS: tuple(digest_hashes([str(item) for item in repo_digests])),
        KEY_PLATFORM: platform,
    }


def image_head(
    name: str, spec: ImageSpec, details: Mapping[str, Any], workload: Sequence[str] | None
) -> dict[str, Any]:
    """Read what runs the shared workload in a container of an image side, from the engine's
    inspect output.

    A side that names no entrypoint and no ``args`` and is given a workload runs that workload
    behind its image's own entrypoint. For such a side this returns the entrypoint as a tuple,
    empty when the image has none, and the first word of the image's command when it has one,
    so that the analysis reads the workload as the words after that program. Any other side
    gets an empty mapping. An inspect output whose entrypoint cannot be read refuses the side,
    since the program its workload is given to is then not known.
    """
    if spec.entrypoint or spec.args or not workload:
        return {}
    config = details.get("Config")
    found = config.get("Entrypoint") if isinstance(config, Mapping) else None
    readable = isinstance(config, Mapping) and (
        found is None or (isinstance(found, list) and all(isinstance(word, str) for word in found))
    )
    if not readable:
        raise Refusal(
            "E_ENTRYPOINT_UNREADABLE",
            f"side {name!r}: the entrypoint of its image could not be read, so the program "
            f"that runs the shared workload is not known; set sides.{name}.entrypoint to the "
            "program the image runs",
        )
    out: dict[str, Any] = {IMAGE_ENTRYPOINT_KEY: tuple(found or ())}
    command = config.get("Cmd") if isinstance(config, Mapping) else None
    if isinstance(command, list) and command and isinstance(command[0], str) and command[0]:
        out[IMAGE_COMMAND_PROGRAM_KEY] = command[0]
    return out


def parse_engine_time(text: Any) -> int | None:
    """Read a time the engine reports (RFC 3339 with nanoseconds) as nanoseconds since the epoch.

    The engine's zero time (year 1) means "not happened" and gives ``None``,
    as does a text that is no such time.
    """
    if not isinstance(text, str):
        return None
    match = _ENGINE_TIME.fullmatch(text.strip())
    if not match:
        return None
    base, fraction, zone = match.groups()
    if base.startswith("0001-"):
        return None
    try:
        stamp = datetime.fromisoformat(base + ("+00:00" if zone == "Z" else zone))
    except ValueError:
        return None
    nanos = int(((fraction or "") + "000000000")[:9])
    return int(stamp.timestamp()) * 1_000_000_000 + nanos


def container_usage(state: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Return the CPU time and the other resource figures of an exited container.

    The first mapping holds ``user_s`` and ``sys_s``, the second the keys of
    ``api.USAGE_KEYS``. ``state`` is the container's state as the engine
    reported it, which holds none of them, so both are empty: every figure is
    missing for the launch, and none is estimated.
    """
    return {}, {}


def two_run_script(
    first: Sequence[str],
    first_env: Mapping[str, str],
    second: Sequence[str],
    second_env: Mapping[str, str],
) -> str:
    """Return the shell text one container runs both commands of a launch with.

    Each run writes its standard output and standard error into its own
    folder under the mount; the second runs only when the first exited with
    zero, and the shell exits with the code of the run that failed. Each
    run's own variables are set for that run alone.
    """
    parts: list[str] = []
    for argv, env, folder in (
        (first, first_env, api.RUN_FOLDERS[0]),
        (second, second_env, api.RUN_FOLDERS[1]),
    ):
        inside = f"{api.ARTIFACTS_IN_CONTAINER}/{folder}"
        assign = " ".join(f"{name}={shlex.quote(value)}" for name, value in env.items())
        command = " ".join(shlex.quote(word) for word in argv)
        out = shlex.quote(f"{inside}/{api.ARTIFACT_STDOUT}")
        err = shlex.quote(f"{inside}/{api.ARTIFACT_STDERR}")
        parts.append(f"{assign + ' ' if assign else ''}{command} >{out} 2>{err}")
    return " && ".join(parts)


def run_output_denied(stderr: Path) -> bool:
    """Whether the shell of a launch of two runs was refused the output file of a run.

    The shell says so on the container's standard error, which the engine
    writes to ``stderr``: a line that names a run's output file inside the
    container and says permission was denied. Each run's own output goes to
    its folder, so no run writes such a line there.
    """
    try:
        with stderr.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - STDERR_TAIL_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    files = [
        f"{api.ARTIFACTS_IN_CONTAINER}/{run}/{output}"
        for run in api.RUN_FOLDERS
        for output in (api.ARTIFACT_STDOUT, api.ARTIFACT_STDERR)
    ]
    return any(
        DENIED_WORDS in line.lower() and any(name in line for name in files)
        for line in text.splitlines()
    )


def make_run_folders(folder: Path) -> None:
    """Create the folders and empty output files of a launch's two runs under ``folder``.

    Each file is made empty and readable and writable by its owner only
    (``open_private``), whatever the umask, as every other file that holds
    what a process printed. The control's shell writes each run's output into
    these files from inside the container, so the image's user must be root
    or have the caller's user id; the repeat check creates them the same way,
    so it meets the same owner and permissions.
    """
    for run in api.RUN_FOLDERS:
        (folder / run).mkdir(parents=True, exist_ok=True)
        for output in (api.ARTIFACT_STDOUT, api.ARTIFACT_STDERR):
            open_private(folder / run / output).close()


def caller_uid() -> int | None:
    """Return the user id of this process, or ``None`` on a system without one."""
    getuid = getattr(os, "getuid", None)
    return int(getuid()) if callable(getuid) else None


def foreign_entries(folder: Path, uid: int) -> list[Path]:
    """Return the files and folders under ``folder`` that user ``uid`` does not own.

    A folder that cannot be listed counts as not owned. Symbolic links are
    not followed. The folders still to list are kept in a list, not in calls
    of a function to itself, so folders nested deeper than the recursion
    limit are read too. An entry whose path is longer than the system
    allows cannot be read, so it counts as not owned.
    """
    found: list[Path] = []
    waiting = [folder]
    while waiting:
        here = waiting.pop()
        try:
            with os.scandir(here) as listing:
                entries = list(listing)
        except OSError as error:
            found.append(Path(error.filename) if error.filename else here)
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.stat(follow_symlinks=False).st_uid != uid:
                    found.append(path)
                if entry.is_dir(follow_symlinks=False):
                    waiting.append(path)
            except OSError:
                found.append(path)
    return found


def hand_back(
    runner: CommandRunner,
    facts: EngineFacts,
    image: str,
    folder: Path,
    *,
    name: str,
    run_id: str,
    settings: LaunchSettings,
    environ: Mapping[str, str],
    remove: Callable[[str], None],
) -> str | None:
    """Give the files a container wrote in ``folder`` back to the calling user.

    Return why some of them stay with another user, or ``None`` when none
    do. Nothing runs when every entry already belongs to the caller, or when
    the engine runs containers on another machine. Otherwise one container
    of ``image``, named ``name``, runs ``chown`` as root on the folder with
    the launch's memory limit and CPU set and no network; the files get the
    caller's user id and the group of ``folder`` itself. ``remove`` removes
    that container afterwards.
    """
    uid = caller_uid()
    if uid is None or not facts.local or not folder.is_dir():
        return None
    if not foreign_entries(folder, uid):
        return None
    if facts.rootless:
        return (
            "the engine runs rootless, so they belong to a user id of its user namespace, "
            "which pairbench does not map back"
        )
    argv = [
        facts.program,
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"{RUN_LABEL}={run_id}",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        "0:0",
        "--volume",
        f"{os.path.abspath(folder)}:{api.ARTIFACTS_IN_CONTAINER}",
        *memory_options(settings.memory),
        *(["--cpuset-cpus", settings.cpus] if settings.cpus else []),
        "--entrypoint",
        "chown",
        image,
        "-R",
        "-h",
        f"{uid}:{folder.stat().st_gid}",
        api.ARTIFACTS_IN_CONTAINER,
    ]
    try:
        done = runner(argv, env=dict(environ), timeout_s=HAND_BACK_WAIT_S)
    finally:
        remove(name)
    if not done.started:
        return "the engine's program could not be started"
    if done.timed_out:
        return f"chown in the image did not end within {HAND_BACK_WAIT_S:g} s"
    if done.rc == ENGINE_FAILED_RC:
        return f"the engine could not run the container that runs chown (exit {done.rc})"
    if done.rc == NOT_FOUND_RC:
        return "the image holds no chown"
    if done.rc != 0:
        return f"chown in the image exited with {done.rc}"
    if foreign_entries(folder, uid):
        return "chown in the image left some of them with another user"
    return None


def files_kept_note(side: str, folder: Path, reason: str, *, once: bool = True) -> str:
    """Return the loud note for files of side ``side`` left with another user in ``folder``.

    The note names the folder by its place in the run folder. ``once`` says
    that later launches of the side are not named.
    """
    where = f"{folder.parent.name}/{folder.name}" if folder.parent.name else folder.name
    return (
        f"files a container of side {side} wrote in {where} of the run folder still belong to "
        "the user its image runs as, so other users may be able to read them and you may not "
        f"be able to delete them: {reason}"
        + ("; later launches of the side are not named again" if once else "")
    )


def write_check_script() -> str:
    """Return the shell text that writes each file of the two runs, as the control does.

    It exits with ``WRITE_CHECK_RC`` when the image's user cannot enter the
    mounted folder or cannot write one of the files, and with
    ``MISSING_CHECK_RC`` when the user can enter the folder but the run
    folders pairbench made are not in it: the container does not see the
    folder pairbench mounted.
    """
    root = shlex.quote(api.ARTIFACTS_IN_CONTAINER)
    folders = [shlex.quote(f"{api.ARTIFACTS_IN_CONTAINER}/{run}") for run in api.RUN_FOLDERS]
    paths = [
        shlex.quote(f"{api.ARTIFACTS_IN_CONTAINER}/{run}/{output}")
        for run in api.RUN_FOLDERS
        for output in (api.ARTIFACT_STDOUT, api.ARTIFACT_STDERR)
    ]
    there = " && ".join(f"test -d {folder}" for folder in folders)
    writes = " && ".join(f"true >{path}" for path in paths)
    return (
        f"test -x {root} || exit {WRITE_CHECK_RC}; "
        f"{{ {there}; }} || exit {MISSING_CHECK_RC}; "
        f"{writes} || exit {WRITE_CHECK_RC}"
    )


class PidWatcher:
    """Asks the engine for the id of a container's first process while the container starts.

    It runs in a thread started before the launch's first clock read and
    stopped after the second, and stops asking once it has the id.
    """

    def __init__(self, runner: CommandRunner, argv: list[str], env: Mapping[str, str]) -> None:
        self._runner = runner
        self._argv = argv
        self._env = dict(env)
        self._done = threading.Event()
        self.pid: int | None = None
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _watch(self) -> None:
        while not self._done.is_set():
            answer = self._runner(self._argv, env=self._env, timeout_s=5.0)
            text = answer.stdout.strip()
            if answer.rc == 0 and text.isdigit() and int(text) > 0:
                self.pid = int(text)
                return
            self._done.wait(PID_POLL_S)

    def stop(self) -> int | None:
        self._done.set()
        self._thread.join(timeout=10.0)
        return self.pid


# ---------------------------------------------------------------------------
# A resolved image side
# ---------------------------------------------------------------------------


class ImageResolved:
    """A resolved image side: one fresh container per launch, removed after it."""

    def __init__(
        self,
        *,
        side: Side,
        spec: ImageSpec,
        details: Mapping[str, Any],
        settings: LaunchSettings,
        facts: EngineFacts,
        workload: tuple[str, ...] | None,
        environ: Mapping[str, str],
        runner: CommandRunner,
        host: HostProcesses,
        note: api.Notify,
        run_id: str,
        launch_folders: Path | None = None,
    ) -> None:
        self._side = side
        self._spec = spec
        self._details = dict(details)
        self._settings = settings
        self._facts = facts
        self._environ = dict(environ)
        self._runner = runner
        self._host = host
        self._note = note
        self._run_id = run_id
        self._hand_back_noted = False
        self._workload: tuple[str, ...] = tuple(workload or ())
        self._command: tuple[str, ...] | None = spec.args or (tuple(workload) if workload else None)
        self._env = {
            **settings.env,
            **spec.env,
            **{name: environ[name] for name in settings.env_pass if name in environ},
        }
        self._repeat_checked = False
        self._repeat_reason: str | None = None
        # The folder that holds the folder of the side's latest launch; before
        # any launch, the folder in which the run makes launch folders.
        self._launches_folder: Path | None = launch_folders
        self._identify_count = 0

    # --- what the runner reads -------------------------------------------

    @property
    def side(self) -> Side:
        return self._side

    @property
    def command(self) -> tuple[str, ...] | None:
        return self._command

    @property
    def whole_command(self) -> tuple[str, ...] | None:
        """The whole command line a container of the side runs, or ``None`` when it has none.

        That is the entrypoint followed by the side's command, or by the
        image's default command when the side gives none: the words an
        instrument is put in front of on an explain launch.
        """
        return tuple(self._full_command(self._command)) or None

    @property
    def engine(self) -> EngineInfo | None:
        return self._facts.info()

    @property
    def rounds_available(self) -> int | None:
        return None

    @property
    def image_id(self) -> str:
        return str(self._side.identity[KEY_IMAGE_ID])

    @property
    def cannot_repeat(self) -> str | None:
        """Whether one container of the image can run two commands.

        It needs ``/bin/sh``, and the image's user must be able to write the
        files of the two runs that pairbench creates in the folder it mounts.
        Asked once, by starting a container of the image whose ``/bin/sh``
        writes those files in a folder made as a launch makes it, beside the
        folder of the side's latest launch (the warm-up's, in a run), so the
        engine mounts it as it mounts a launch's folder. Before the side's
        first launch it lies in the folder where the run makes launch
        folders, made when missing; outside a run, under the system's
        temporary folder. The answer is kept for the run.
        """
        if not self._repeat_checked:
            self._repeat_reason = self._probe_shell()
            self._repeat_checked = True
        return self._repeat_reason

    def identify(self) -> Mapping[str, Any]:
        """Inspect the image by its ID again and run the identify command again. Never pulls."""
        details = inspect_image(
            self._runner, self._facts, self.image_id, self._environ, side=self._side.name
        )
        if details is None:
            raise Refusal(
                "E_SIDE_UNIDENTIFIED",
                f"side {self._side.name!r}: its image is no longer on this machine",
            )
        identity = image_identity(details)
        identity.update(image_head(self._side.name, self._spec, details, self._workload))
        identity.update(self._identify())
        return identity

    def artifacts_in_side(self, host: Path) -> str:
        return api.ARTIFACTS_IN_CONTAINER

    def tool_file_in_side(self, host: Path) -> str:
        return f"{api.TOOLS_IN_CONTAINER}/{host.name}"

    def close(self) -> None:
        return None

    # --- helpers ---------------------------------------------------------

    def _engine_env(self, container_env: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
        """Return the environment of the engine's command and the ``--env`` options."""
        env = dict(self._environ)
        options: list[str] = []
        for name, value in container_env.items():
            if engine_reads(name):
                options += ["--env", f"{name}={value}"]
            else:
                env[name] = value
                options += ["--env", name]
        return env, options

    def _name(self, seq: int, what: str) -> str:
        return api.container_name(self._run_id or "lookup", seq, what)

    def _remove(self, name: str) -> None:
        done = self._runner(
            [self._facts.program, "rm", "--force", name],
            env=self._environ,
            timeout_s=REMOVE_WAIT_S,
        )
        if done.timed_out:
            self._note(
                NOTE_CONTAINER_NOT_REMOVED,
                f"the engine did not remove the container {name} of side {self._side.name} "
                f"within {REMOVE_WAIT_S:g} s; it may be left behind, and pairbench doctor lists it",
            )
        elif done.rc != 0 and "no such" not in (done.stderr or "").lower():
            self._note(
                NOTE_CONTAINER_NOT_REMOVED,
                f"a container of side {self._side.name} could not be removed; "
                "pairbench doctor lists it",
            )

    def _probe_shell(self) -> str | None:
        name = self._name(0, f"{self._side.name}-shell")
        beside = self._launches_folder
        if beside is not None:
            # Before the first launch the run has not made this folder yet.
            with contextlib.suppress(OSError):
                beside.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="pairbench-repeat-",
            dir=beside if beside is not None and beside.is_dir() else None,
            ignore_cleanup_errors=True,
        ) as scratch:
            # A relative run folder gives a relative folder here on some Python
            # versions; the engine reads a relative mount source as a volume name.
            folder = Path(os.path.abspath(scratch)) / "launch"
            folder.mkdir()
            make_run_folders(folder)
            argv = [
                self._facts.program,
                "run",
                "--rm",
                "--name",
                name,
                "--label",
                f"{RUN_LABEL}={self._run_id}",
                "--pull",
                "never",
                "--network",
                "none",
                "--volume",
                f"{folder}:{api.ARTIFACTS_IN_CONTAINER}",
                *memory_options(self._settings.memory),
                *(["--cpuset-cpus", self._settings.cpus] if self._settings.cpus else []),
                "--entrypoint",
                SHELL,
                self.image_id,
                "-c",
                write_check_script(),
            ]
            try:
                done = self._runner(argv, env=self._environ, timeout_s=self._settings.timeout_s)
            finally:
                self._remove(name)
        if done.rc == 0 and not done.timed_out:
            return None
        if done.rc == WRITE_CHECK_RC and not done.timed_out:
            return (
                f"the user the image of side {self._side.name} runs as cannot write the files "
                "pairbench creates in the folder it mounts, where the two runs keep their "
                "output; an image whose user is root or has your user id can"
            )
        if done.rc == MISSING_CHECK_RC and not done.timed_out:
            return (
                f"the files pairbench created in the folder it mounted into a container of "
                f"side {self._side.name} did not show inside it, so whether the image's user can "
                "write the files where the two runs keep their output was not checked"
            )
        return (
            f"the image of side {self._side.name} did not run {SHELL} (exit {done.rc}), so one "
            "container cannot run its command twice"
        )

    def _hand_back(self, folder: Path, seq: int, what: str, *, stopped: bool = False) -> None:
        """Give the files a container wrote in ``folder`` back to the calling user.

        See ``hand_back``. When some stay with another user, a loud note names
        the folder: once per side for launches that ended as they should, and
        every time for a launch that stopped on an exception or an interrupt
        (``stopped``). When the hand-back itself is stopped, the note names the
        folder before the exception goes on; an error in the hand-back of a
        stopped launch is not raised, so the exception that stopped the
        launch goes on in its place.
        """
        try:
            reason = hand_back(
                self._runner,
                self._facts,
                self.image_id,
                folder,
                name=self._name(seq, f"{what}-chown"),
                run_id=self._run_id,
                settings=self._settings,
                environ=self._environ,
                remove=self._remove,
            )
        except BaseException as exc:
            failed = isinstance(exc, Exception)
            why = (
                f"the hand-back stopped on an error ({type(exc).__name__})"
                if failed
                else "an interrupt stopped the hand-back before it ended"
            )
            self._note(
                NOTE_FILES_NOT_HANDED_BACK,
                files_kept_note(self._side.name, folder, why, once=False),
            )
            if stopped and failed:
                return
            raise
        if reason is None:
            return
        if stopped:
            self._note(
                NOTE_FILES_NOT_HANDED_BACK,
                files_kept_note(self._side.name, folder, reason, once=False),
            )
            return
        if self._hand_back_noted:
            return
        self._hand_back_noted = True
        self._note(NOTE_FILES_NOT_HANDED_BACK, files_kept_note(self._side.name, folder, reason))

    def _identify(self) -> dict[str, str]:
        identify = self._settings.identify
        if not identify:
            return {}
        self._identify_count += 1
        name = self._name(0, f"{self._side.name}-identify-{self._identify_count}")
        env, env_options = self._engine_env(self._env)
        argv = [
            self._facts.program,
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            f"{RUN_LABEL}={self._run_id}",
            "--pull",
            "never",
            *container_options(self._settings, self._facts),
            *env_options,
            "--entrypoint",
            identify[0],
            self.image_id,
            *identify[1:],
        ]
        try:
            return run_identify(
                self._runner,
                argv,
                side=self._side.name,
                env=env,
                timeout_s=self._settings.timeout_s,
            )
        finally:
            self._remove(name)

    def _entrypoint(self) -> list[str]:
        if self._spec.entrypoint:
            return [self._spec.entrypoint]
        config = self._details.get("Config") or {}
        found = config.get("Entrypoint") if isinstance(config, Mapping) else None
        return [str(word) for word in found] if isinstance(found, list) else []

    def _full_command(self, argv: tuple[str, ...] | None) -> list[str]:
        """The whole command a container runs for ``argv``: entrypoint and arguments."""
        if argv:
            return [*self._entrypoint(), *argv]
        if self._spec.entrypoint:
            return [self._spec.entrypoint]
        config = self._details.get("Config") or {}
        cmd = config.get("Cmd") if isinstance(config, Mapping) else None
        return [
            *self._entrypoint(),
            *([str(word) for word in cmd] if isinstance(cmd, list) else []),
        ]

    # --- one launch ------------------------------------------------------

    def launch(self, request: api.LaunchRequest) -> api.LaunchOutcome:
        """Start one container, wait for it, read its times, remove it."""
        self._launches_folder = request.artifacts.parent
        instrumented = request.phase in ("explain", "profile")
        if instrumented and request.wrap_server is None and self._entrypoint():
            raise Refusal(
                "E_ENGINE_UNSUPPORTED",
                f"side {self._side.name!r}: its image has an entrypoint, so an instrument "
                "cannot be put in front of its command",
            )
        name = self._name(request.seq, request.name)
        container_env = dict(self._env)
        entrypoint: list[str] = (
            ["--entrypoint", self._spec.entrypoint] if self._spec.entrypoint else []
        )
        if request.wrap_server is not None:
            # The instrument goes in front of the whole command line the
            # container would run, and replaces the image's entrypoint.
            whole = self._full_command(request.argv)
            if not whole or request.second is not None:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {self._side.name!r}: its image names no command to put an "
                    "instrument in front of",
                )
            wrapped = request.wrap_server(whole)
            container_env.update(request.env)
            container_env.update(wrapped.env)
            entrypoint = ["--entrypoint", wrapped.argv[0]]
            command = list(wrapped.argv[1:])
        elif request.second is None:
            container_env.update(request.env)
            command = list(request.argv or ())
        else:
            first = self._full_command(request.argv)
            second = self._full_command(request.second.argv)
            if not first or not second:
                raise Refusal(
                    "E_ENGINE_UNSUPPORTED",
                    f"side {self._side.name!r}: its image names no command to run twice",
                )
            for env in (request.env, request.second.env):
                bad = sorted(key for key in env if not SHELL_NAME.fullmatch(key))
                if bad:
                    raise Refusal(
                        "E_ENGINE_UNSUPPORTED",
                        f"side {self._side.name!r}: a variable of one run is no name a shell "
                        f"can set: {', '.join(bad)}",
                    )
            make_run_folders(request.artifacts)
            entrypoint = ["--entrypoint", SHELL]
            command = ["-c", two_run_script(first, request.env, second, request.second.env)]
        engine_env, env_options = self._engine_env(container_env)
        tool_options: list[str] = []
        for tool in request.tool_files:
            source = os.path.abspath(tool)
            tool_options += ["--volume", f"{source}:{self.tool_file_in_side(tool)}:ro"]
        argv = (
            self._facts.program,
            "run",
            "--name",
            name,
            "--label",
            f"{RUN_LABEL}={request.run_id}",
            "--pull",
            "never",
            "--volume",
            f"{os.path.abspath(request.artifacts)}:{api.ARTIFACTS_IN_CONTAINER}",
            *container_options(self._settings, self._facts),
            *env_options,
            *tool_options,
            *entrypoint,
            self.image_id,
            *command,
        )
        run = HostRun(
            argv=argv,
            env=engine_env,
            stdout=request.artifacts / api.ARTIFACT_STDOUT,
            stderr=request.artifacts / api.ARTIFACT_STDERR,
            executable=self._facts.program,
        )

        def stop(pid: int) -> None:
            self._runner([self._facts.program, "kill", name], env=self._environ, timeout_s=30.0)
            self._host.kill(pid)

        watcher: PidWatcher | None = None
        if self._settings.gpus is not None and self._facts.local:
            watcher = PidWatcher(
                self._runner,
                [self._facts.program, "inspect", "--format", "{{.State.Pid}}", name],
                self._environ,
            )
            watcher.start()
        try:
            try:
                result = launch_on_host(
                    [run], host=self._host, timeout_s=self._settings.timeout_s, stop=stop
                )
                pid = watcher.stop() if watcher is not None else None
                state = self._state(name)
            finally:
                if watcher is not None:
                    watcher.stop()
                self._remove(name)
        except BaseException:
            # However the launch stops, what its container wrote goes back to
            # the caller before the run's owner-only pass and before it exits.
            self._hand_back(request.artifacts, request.seq, request.name, stopped=True)
            raise
        self._hand_back(request.artifacts, request.seq, request.name)
        timing: dict[str, float] = {api.TIMING_LAUNCH_S: result.run_ns / 1e9}
        started = parse_engine_time(state.get("StartedAt"))
        finished = parse_engine_time(state.get("FinishedAt"))
        rc = result.rc
        if started is not None and finished is not None and finished >= started:
            timing[api.TIMING_RUN_S] = (finished - started) / 1e9
            exit_code = state.get("ExitCode")
            if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                rc = exit_code
        cpu, usage = container_usage(state)
        timing.update(cpu)
        cpu_s = None
        if api.TIMING_USER_S in cpu and api.TIMING_SYS_S in cpu:
            cpu_s = cpu[api.TIMING_USER_S] + cpu[api.TIMING_SYS_S]
        cannot = None
        if (
            request.second is not None
            and rc != 0
            and not result.timed_out
            and run_output_denied(request.artifacts / api.ARTIFACT_STDERR)
        ):
            cannot = (
                f"the shell in a container of side {self._side.name} was refused a file where "
                "one of the two runs keeps its output (permission denied), though the check "
                "before the first round could write it"
            )
        return api.LaunchOutcome(
            rc=rc,
            timing=timing,
            timed_out=result.timed_out,
            cpu_s=cpu_s,
            pid=pid,
            usage=usage,
            cannot_repeat=cannot,
        )

    def _state(self, name: str) -> dict[str, Any]:
        done = self._runner(
            [self._facts.program, "inspect", "--format", "{{json .State}}", name],
            env=self._environ,
            timeout_s=60.0,
        )
        return _json_object(done.stdout) if done.rc == 0 else {}


def inspect_image(
    runner: CommandRunner,
    facts: EngineFacts,
    ref: str,
    environ: Mapping[str, str],
    *,
    side: str = "",
) -> dict[str, Any] | None:
    """Return the engine's inspect output of an image on this machine, or ``None`` when absent.

    An engine that does not answer within ``ENGINE_QUERY_WAIT_S`` is refused
    with ``E_SIDE_UNRESOLVED``, naming ``side`` when it is given: a slow
    engine is never taken for an absent image, which would be pulled.
    """
    done = runner(
        [facts.program, "image", "inspect", "--format", "{{json .}}", ref],
        env=dict(environ),
        timeout_s=ENGINE_QUERY_WAIT_S,
    )
    if done.timed_out:
        raise Refusal(
            "E_SIDE_UNRESOLVED",
            f"{f'side {side!r}: ' if side else ''}the container engine did not answer within "
            f"{ENGINE_QUERY_WAIT_S:g} s when asked about the image {ref}",
            detail={"image": ref},
        )
    if done.rc != 0:
        return None
    details = _json_object(done.stdout)
    return details or None


# ---------------------------------------------------------------------------
# The kind
# ---------------------------------------------------------------------------


class ImageKind(KindBase):
    """The ``image`` side kind, and what it reports to ``pairbench doctor``."""

    name = KIND_IMAGE

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        host: HostProcesses | None = None,
        which: Callable[..., str | None] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(runner=runner, host=host)
        self._which = which if which is not None else shutil.which
        self._doctor_environ = environ

    def _facts(
        self, settings: LaunchSettings, environ: Mapping[str, str], *, required: bool
    ) -> EngineFacts | None:
        """The engine of a side: refused when ``required`` and none is found, else ``None``."""
        found = reachable_engines(self._runner, environ, self._which)
        if required:
            engine: str | None = api.choose_engine(settings.engine, list(found), environ)
        else:
            engine = api.find_engine(settings.engine, list(found), environ)
        if engine is None:
            return None
        program, version = found[engine]
        return engine_facts(self._runner, engine, program, version, environ)

    def _engine(self, settings: LaunchSettings, environ: Mapping[str, str]) -> EngineFacts:
        facts = self._facts(settings, environ, required=True)
        if facts is None:
            raise Refusal(
                "E_SIDE_UNRESOLVED", "no container engine found: neither docker nor podman"
            )
        return facts

    def look_up(self, side: Side, ctx: api.SideContext) -> api.SideLookup:
        """Inspect an image already on this machine; never pull, start or create anything."""
        spec = image_spec(side)
        facts = self._facts(ctx.settings, ctx.environ, required=False)
        if facts is None:
            return api.SideLookup(
                status="unchecked",
                message=f"side {side.name}: no container engine could be reached, so the "
                "identity of its image was not checked",
            )
        refuse_image_settings(side, ctx.settings, facts)
        details = inspect_image(self._runner, facts, spec.ref, ctx.environ, side=side.name)
        if details is None:
            if ctx.settings.pull == "never":
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side.name!r}: its image is not on this machine and the pull policy "
                    "is never",
                    detail={"image": spec.ref},
                )
            return api.SideLookup(
                status="absent",
                message=f"side {side.name}: its image is not on this machine; run would pull it",
            )
        identity = image_identity(details)
        identity.update(image_head(side.name, spec, details, ctx.workload))
        fingerprint = ""
        if not ctx.settings.identify:
            fingerprint = fingerprint_of(identity, _effective(ctx.settings, spec))
        message = ""
        if ctx.settings.pull == "always":
            message = f"side {side.name}: run pulls its image again (pull policy always)"
        return api.SideLookup(
            status="identified", identity=identity, fingerprint=fingerprint, message=message
        )

    def resolve(self, side: Side, ctx: api.SideContext) -> api.ResolvedSide:
        """Apply the pull policy, inspect the image, run the identify command, record identity."""
        spec = image_spec(side)
        facts = self._engine(ctx.settings, ctx.environ)
        refuse_image_settings(side, ctx.settings, facts)
        require_env_pass(side, ctx.settings, ctx.environ)
        details = (
            None
            if ctx.settings.pull == "always"
            else inspect_image(self._runner, facts, spec.ref, ctx.environ, side=side.name)
        )
        if details is None:
            if ctx.settings.pull == "never":
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side.name!r}: its image is not on this machine and the pull policy "
                    "is never",
                    detail={"image": spec.ref},
                )
            pulled = self._runner([facts.program, "pull", spec.ref], env=dict(ctx.environ))
            details = inspect_image(self._runner, facts, spec.ref, ctx.environ, side=side.name)
            if pulled.rc != 0 or details is None:
                raise Refusal(
                    "E_SIDE_UNRESOLVED",
                    f"side {side.name!r}: its image could not be pulled",
                    detail={"image": spec.ref, "stderr": pulled.stderr[-2000:]},
                )
        identity = image_identity(details)
        identity.update(image_head(side.name, spec, details, ctx.workload))
        resolved = ImageResolved(
            side=side.with_identity(identity, ""),
            spec=spec,
            details=details,
            settings=ctx.settings,
            facts=facts,
            workload=ctx.workload,
            environ=ctx.environ,
            runner=self._runner,
            host=self._host,
            note=ctx.note,
            run_id=ctx.run_id,
            launch_folders=ctx.launch_folders,
        )
        identity.update(resolved._identify())
        fingerprint = fingerprint_of(identity, _effective(ctx.settings, spec))
        resolved._side = side.with_identity(identity, fingerprint)
        return resolved

    def doctor(self) -> api.DoctorReport:
        """Report the engine found and the containers that runs left behind."""
        environ = self._doctor_environ if self._doctor_environ is not None else dict(os.environ)
        found = reachable_engines(self._runner, environ, self._which)
        if not found:
            return api.DoctorReport(
                status="unavailable", summary="no container engine found: neither docker nor podman"
            )
        leftovers: list[str] = []
        for program, _version in found.values():
            done = self._runner(
                [
                    program,
                    "ps",
                    "--all",
                    "--filter",
                    f"label={RUN_LABEL}",
                    "--format",
                    "{{.Names}}",
                ],
                env=environ,
                timeout_s=ENGINE_QUERY_WAIT_S,
            )
            if done.rc == 0:
                leftovers += [
                    line.strip()
                    for line in done.stdout.splitlines()
                    if line.strip().startswith(api.CONTAINER_PREFIX)
                ]
        engines = ", ".join(f"{name} {version}" for name, (_program, version) in found.items())
        detail = {
            "engines": {name: version for name, (_program, version) in found.items()},
            "leftover_containers": leftovers,
        }
        if leftovers:
            return api.DoctorReport(
                status="degraded",
                summary=f"{engines}; {len(leftovers)} container(s) left behind by runs: remove "
                "them with the engine's rm command",
                detail=detail,
            )
        return api.DoctorReport(
            status="ok", summary=f"{engines}; no container left behind", detail=detail
        )


def _effective(settings: LaunchSettings, spec: ImageSpec) -> dict[str, Any]:
    return settings.effective(args=spec.args, entrypoint=spec.entrypoint, env=spec.env)
