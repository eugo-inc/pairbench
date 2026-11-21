# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Machine and tool facts.

``facts()`` makes the ``api.Facts`` service of a run. It looks at nothing when
it is made.

``MachineFacts.machine_record`` gives the ``machine`` record of a capture.
It holds only what a results document may show and what describes no single
machine: the operating system's name and version, the CPU architecture, the
CPU model string, the model and driver version of each selected GPU, the
container engine's name and version, whether the run is inside a container
or an automated pipeline, and the ``node_type`` the user set. The runner adds
the CPU identity, the cache domains and the CPUs the tool moved to. No fact
kept here holds the host name, a user name, a home or working folder, a
machine id, a serial number, a device id or a network address, and no value
of the environment is read beyond the variables named below. The facts a
results document shows are ``MachineRecord.summary()`` together with the GPU
and engine facts; there is no second reduction here.

Where each fact comes from:

* operating system: on Linux, ``NAME`` and ``VERSION_ID`` of
  ``/etc/os-release`` (or ``/usr/lib/os-release``); on macOS, ``macOS`` and
  the product version; elsewhere the system name and release;
* CPU model: on Linux, the first of the ``/proc/cpuinfo`` keys
  ``model name``, ``Hardware``, ``cpu model`` and ``cpu``, or the CPU
  implementer and part codes that 64-bit Arm machines list there; on macOS,
  ``sysctl -n machdep.cpu.brand_string``; no other key of the file is read;
* GPUs: ``nvidia-smi --query-gpu=index,name,driver_version
  --format=csv,noheader`` for the selected GPUs, and nothing when no GPU is
  selected (query fields from the nvidia-smi documentation,
  https://docs.nvidia.com/deploy/nvidia-smi/index.html, and the
  ``--help-query-gpu`` list in the pynvml repository at release 11.5.3,
  https://github.com/gpuopenanalytics/pynvml/blob/11.5.3/help_query_gpu.txt);
* container engine: the engine ``auto`` would pick among docker and podman on
  ``PATH`` (``api.find_engine``), and the version its ``--version`` prints;
* inside a container: the files ``/.dockerenv`` or ``/run/.containerenv``,
  the variable ``container`` or ``KUBERNETES_SERVICE_HOST``, or a docker,
  kubepods, containerd, libpod or lxc part in ``/proc/self/cgroup``; a file
  that cannot be looked at counts as absent;
* automated pipeline: ``api.is_ci``.

``MachineFacts.tools`` lists the external programs pairbench can use and
whether each is on ``PATH``, with the version its ``--version`` prints. The
empty command ``true`` is looked for and not asked for a version. No path of
a program is kept.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from pairbench.api import ENGINES, ToolFact, find_engine, is_ci
from pairbench.model import CpuRecord, EngineInfo, GpuInfo, MachineRecord

# How long one call of an external program may take.
COMMAND_TIMEOUT_S: Final = 10.0

UNKNOWN: Final = "unknown"
EMPTY_COMMAND: Final = "true"

# The external programs ``tools`` looks for, in the order they are listed.
TOOLS: Final[tuple[str, ...]] = (
    "docker",
    "podman",
    "nvidia-smi",
    "nsys",
    "ncu",
    "perf",
    "hyperfine",
    "conda",
    EMPTY_COMMAND,
)

GPU_QUERY: Final = "index,name,driver_version"
CPUINFO_MODEL_KEYS: Final[tuple[str, ...]] = ("model name", "hardware", "cpu model", "cpu")
CONTAINER_FILES: Final[tuple[str, ...]] = (".dockerenv", "run/.containerenv")
CONTAINER_VARIABLES: Final[tuple[str, ...]] = ("container", "KUBERNETES_SERVICE_HOST")

_VERSION = re.compile(r"\d+(?:\.\d+)+")
_CGROUP_CONTAINER = re.compile(r"(^|[/:])(docker|kubepods|containerd|libpod|lxc)([/.:-]|$)")

Run = Callable[[Sequence[str]], str | None]
Which = Callable[[str], str | None]


def run_command(argv: Sequence[str]) -> str | None:
    """Run a short command and return what it printed, or ``None`` when it failed."""
    try:
        done = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout or done.stderr


@dataclass(frozen=True)
class Platform:
    """What the interpreter reports about the system; tests pass made-up values."""

    system: str = field(default_factory=platform.system)
    machine: str = field(default_factory=platform.machine)
    release: str = field(default_factory=platform.release)
    mac_version: str = field(default_factory=lambda: platform.mac_ver()[0])
    processor: str = field(default_factory=platform.processor)


def version_of(text: str | None) -> str | None:
    """Return the first version number in a program's output, such as ``27.3.1``."""
    if not text:
        return None
    found = _VERSION.search(text)
    return found.group(0) if found else None


def _clean(text: str) -> str:
    """Keep one line of printable text, with runs of white space made one space."""
    return " ".join("".join(c for c in text if c.isprintable()).split())


def _key_values(text: str, separator: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        key, sep, value = line.partition(separator)
        if sep:
            pairs.append((key.strip(), value.strip()))
    return pairs


def os_release_name(text: str) -> str | None:
    """Return ``NAME VERSION_ID`` from the text of an os-release file."""
    values: dict[str, str] = {}
    for key, value in _key_values(text, "="):
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    name = _clean(values.get("NAME", ""))
    version = _clean(values.get("VERSION_ID", ""))
    if not name:
        return None
    return f"{name} {version}" if version else name


def cpuinfo_model(text: str) -> str | None:
    """Return the CPU model string from the text of ``/proc/cpuinfo``."""
    values: dict[str, str] = {}
    for key, value in _key_values(text, ":"):
        values.setdefault(key.lower(), value)
    for key in CPUINFO_MODEL_KEYS:
        value = _clean(values.get(key, ""))
        if value:
            return value
    implementer = _clean(values.get("cpu implementer", ""))
    part = _clean(values.get("cpu part", ""))
    if implementer and part:
        return f"CPU implementer {implementer} part {part}"
    return None


def parse_gpus(text: str) -> tuple[GpuInfo, ...]:
    """Read the lines of the GPU query: ``index, name, driver version``, in index order."""
    found: list[tuple[int, GpuInfo]] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3 or not (parts[0].isascii() and parts[0].isdigit()):
            continue
        name = _clean(", ".join(parts[1:-1]))
        driver = _clean(parts[-1])
        if name and driver:
            found.append((int(parts[0]), GpuInfo(model=name, driver=driver)))
    return tuple(info for _, info in sorted(found, key=lambda pair: pair[0]))


class MachineFacts:
    """The ``api.Facts`` service: machine and tool facts.

    ``root`` is the folder the system files are read under, ``run`` runs a
    short command and returns its output, ``which`` finds a program on
    ``PATH``. Tests pass made-up ones, so nothing of the machine is read.
    """

    def __init__(
        self,
        *,
        root: Path = Path("/"),
        run: Run | None = None,
        which: Which | None = None,
        system: Platform | None = None,
    ) -> None:
        self._root = root
        self._run = run or run_command
        self._which = which or shutil.which
        self._platform = system

    def _system(self) -> Platform:
        return self._platform or Platform()

    def _read(self, relative: str) -> str | None:
        try:
            return (self._root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def os_name(self) -> str:
        """Return the operating system's name and version."""
        system = self._system()
        if system.system == "Linux":
            for relative in ("etc/os-release", "usr/lib/os-release"):
                text = self._read(relative)
                name = os_release_name(text) if text is not None else None
                if name:
                    return name
            return "Linux"
        if system.system == "Darwin":
            version = _clean(system.mac_version)
            return f"macOS {version}" if version else "macOS"
        name = _clean(f"{system.system} {system.release}")
        return name or UNKNOWN

    def arch(self) -> str:
        """Return the CPU architecture."""
        return _clean(self._system().machine) or UNKNOWN

    def cpu_model(self) -> str:
        """Return the CPU model string."""
        system = self._system()
        if system.system == "Linux":
            text = self._read("proc/cpuinfo")
            model = cpuinfo_model(text) if text is not None else None
            if model:
                return model
        elif system.system == "Darwin":
            out = self._run(["sysctl", "-n", "machdep.cpu.brand_string"])
            if out and _clean(out):
                return _clean(out)
        return _clean(system.processor) or UNKNOWN

    def gpus(self, gpus: str | None) -> tuple[GpuInfo, ...]:
        """Return the model and driver version of each selected GPU."""
        if gpus is None or not self._which("nvidia-smi"):
            return ()
        argv = ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader"]
        if gpus.strip() != "all":
            argv += ["-i", ",".join(part.strip() for part in gpus.split(","))]
        out = self._run(argv)
        return parse_gpus(out) if out else ()

    def engine(self, environ: Mapping[str, str]) -> EngineInfo | None:
        """Return the container engine ``auto`` would pick, with its version."""
        found = [name for name in ENGINES if self._which(name)]
        name = find_engine("auto", found, environ)
        if name is None:
            return None
        return EngineInfo(name=name, version=version_of(self._run([name, "--version"])) or UNKNOWN)

    def _exists(self, relative: str) -> bool:
        """Say whether a file exists; a path that cannot be looked at counts as absent."""
        try:
            return (self._root / relative).exists()
        except OSError:
            return False

    def in_container(self, environ: Mapping[str, str]) -> bool:
        """Say whether this process runs inside a container."""
        if any(self._exists(relative) for relative in CONTAINER_FILES):
            return True
        if any(environ.get(name, "").strip() for name in CONTAINER_VARIABLES):
            return True
        cgroup = self._read("proc/self/cgroup") or ""
        return any(_CGROUP_CONTAINER.search(line) for line in cgroup.splitlines())

    def machine_record(
        self, *, gpus: str | None, node_type: str | None, environ: Mapping[str, str]
    ) -> MachineRecord:
        """Return the ``machine`` record of a capture, without the CPU identity."""
        return MachineRecord(
            os=self.os_name(),
            arch=self.arch(),
            cpu=CpuRecord(model=self.cpu_model()),
            gpu=self.gpus(gpus),
            engine=self.engine(environ),
            in_container=self.in_container(environ),
            ci=is_ci(environ),
            node_type=node_type,
        )

    def tool(self, name: str) -> ToolFact:
        """Say whether one external program is on ``PATH``, and its version."""
        if not self._which(name):
            return ToolFact(name=name, found=False, note="not found on PATH")
        if name == EMPTY_COMMAND:
            return ToolFact(name=name, found=True, note="the empty command; no version is read")
        version = version_of(self._run([name, "--version"]))
        if version is None:
            return ToolFact(name=name, found=True, note="its version could not be read")
        return ToolFact(name=name, found=True, version=version)

    def tools(self) -> list[ToolFact]:
        """List the external programs looked for and which were found."""
        return [self.tool(name) for name in TOOLS]


def facts() -> MachineFacts:
    """Make the machine and tool facts of a run (``pairbench.api.MakeFacts``)."""
    return MachineFacts()
