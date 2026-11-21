# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Machine and tool facts, read from a made-up system tree and made-up programs."""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from pairbench import api, provenance
from pairbench.api import Facts, ToolFact
from pairbench.model import CpuRecord, EngineInfo, GpuInfo, MachineRecord, MachineSummary
from pairbench.provenance import (
    MachineFacts,
    Platform,
    cpuinfo_model,
    facts,
    os_release_name,
    parse_gpus,
    version_of,
)
from pairbench.provenance import run_command as real_run_command

LINUX = Platform(
    system="Linux", machine="x86_64", release="0.0.0-made-up", mac_version="", processor=""
)
ARM = Platform(system="Linux", machine="aarch64", release="0.0.0", mac_version="", processor="")
MAC = Platform(system="Darwin", machine="arm64", release="0.0.0", mac_version="10.99", processor="")

OS_RELEASE = """\
PRETTY_NAME="Made Up Linux 1.2 (Example)"
NAME="Made Up Linux"
VERSION_ID="1.2"
VERSION="1.2 (Example)"
ID=madeup
HOME_URL="https://example.invalid/"
"""

CPUINFO_X86 = """\
processor\t: 0
vendor_id\t: MadeUpVendor
cpu family\t: 6
model\t\t: 0
model name\t: Made Up CPU 9000 @ 1.00GHz
cpu MHz\t\t: 1000.000
Serial\t\t: 00000000deadbeef

processor\t: 1
model name\t: Made Up CPU 9000 @ 1.00GHz
"""

CPUINFO_ARM = """\
processor\t: 0
BogoMIPS\t: 2000.00
Features\t: fp asimd
CPU implementer\t: 0x00
CPU architecture: 8
CPU variant\t: 0x0
CPU part\t: 0x000
CPU revision\t: 0
"""

GPU_QUERY_ALL = ("nvidia-smi", "--query-gpu=index,name,driver_version", "--format=csv,noheader")
GPU_LINES = "1, Made Up GPU B, 000.00.01\n0, Made Up GPU A, 000.00.01\n"

# Values that identify a machine. None may reach a machine record.
MARKERS = (
    "host-a",
    "made-up-user",
    "/home/",
    "00000000000000000000000000000000",
    "00000000deadbeef",
    "GPU-00000000-0000-0000-0000-000000000000",
    "made-up-secret",
)


class FakeCommands:
    """Answers the commands a test names, records every command asked for."""

    def __init__(self, answers: dict[tuple[str, ...], str | None] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> str | None:
        self.asked.append(tuple(argv))
        return self.answers.get(tuple(argv))


def _which(*found: str) -> provenance.Which:
    return lambda name: f"/opt/made-up/bin/{name}" if name in found else None


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _no_real_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a test reached the real machine")

    monkeypatch.setattr(provenance, "run_command", refuse)
    monkeypatch.setattr(provenance.shutil, "which", refuse)
    monkeypatch.setattr(platform, "node", refuse)
    monkeypatch.setattr(socket, "gethostname", refuse)


# --- the machine record ---------------------------------------------------------------


def test_a_linux_machine_record_from_a_made_up_tree(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"etc/os-release": OS_RELEASE, "proc/cpuinfo": CPUINFO_X86})
    commands = FakeCommands(
        {
            GPU_QUERY_ALL: GPU_LINES,
            ("docker", "--version"): "Docker version 0.0.1, build 0000000\n",
        }
    )
    machine = MachineFacts(
        root=root, run=commands, which=_which("nvidia-smi", "docker"), system=LINUX
    )
    record = machine.machine_record(gpus="all", node_type="node-type-a", environ={})
    assert record == MachineRecord(
        os="Made Up Linux 1.2",
        arch="x86_64",
        cpu=CpuRecord(model="Made Up CPU 9000 @ 1.00GHz"),
        gpu=(
            GpuInfo(model="Made Up GPU A", driver="000.00.01"),
            GpuInfo(model="Made Up GPU B", driver="000.00.01"),
        ),
        engine=EngineInfo(name="docker", version="0.0.1"),
        in_container=False,
        ci=False,
        node_type="node-type-a",
        tool_cpus=None,
    )
    assert commands.asked == [GPU_QUERY_ALL, ("docker", "--version")]


def test_the_record_leaves_the_cpu_identity_to_the_runner(tmp_path: Path) -> None:
    machine = MachineFacts(root=tmp_path, run=FakeCommands(), which=_which(), system=LINUX)
    record = machine.machine_record(gpus=None, node_type=None, environ={})
    assert record.cpu.identity == ()
    assert record.cpu.cache_domains == ()
    assert record.tool_cpus is None


def test_nothing_that_identifies_the_machine_reaches_the_record(tmp_path: Path) -> None:
    root = _tree(
        tmp_path,
        {
            "etc/os-release": OS_RELEASE,
            "proc/cpuinfo": CPUINFO_X86,
            "etc/hostname": "host-a\n",
            "etc/machine-id": "00000000000000000000000000000000\n",
            "proc/self/cgroup": "0::/user.slice/made-up-user.slice\n",
        },
    )
    commands = FakeCommands(
        {
            GPU_QUERY_ALL: GPU_LINES,
            (
                "nvidia-smi",
                "--query-gpu=index,uuid,serial",
                "--format=csv,noheader",
            ): "0, GPU-00000000-0000-0000-0000-000000000000, 0000000000000\n",
            ("podman", "--version"): "podman version 0.0.2\n",
        }
    )
    environ = {
        "HOSTNAME": "host-a",
        "USER": "made-up-user",
        "HOME": "/home/made-up-user",
        "PWD": "/home/made-up-user/work",
        "MADE_UP_VARIABLE": "made-up-secret",
    }
    machine = MachineFacts(
        root=root, run=commands, which=_which("nvidia-smi", "podman"), system=LINUX
    )
    record = machine.machine_record(gpus="all", node_type=None, environ=environ)
    written = json.dumps(record.to_json())
    shown = json.dumps(record.summary().to_json())
    for marker in MARKERS:
        assert marker not in written
        assert marker not in shown
    for argv in commands.asked:
        assert not any(word in " ".join(argv) for word in ("uuid", "serial", "pci", "mac"))


def test_the_facts_a_results_document_shows_are_the_summary(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"etc/os-release": OS_RELEASE, "proc/cpuinfo": CPUINFO_X86})
    machine = MachineFacts(root=root, run=FakeCommands(), which=_which(), system=LINUX)
    record = machine.machine_record(gpus=None, node_type=None, environ={})
    assert record.summary() == MachineSummary(
        os="Made Up Linux 1.2", arch="x86_64", cpu_model="Made Up CPU 9000 @ 1.00GHz"
    )


# --- operating system -----------------------------------------------------------------


def test_the_os_name_is_name_and_version_id_of_os_release() -> None:
    assert os_release_name(OS_RELEASE) == "Made Up Linux 1.2"
    assert os_release_name("NAME='Made Up'\n") == "Made Up"
    assert os_release_name("NAME=Plain\nVERSION_ID=7\n") == "Plain 7"
    assert os_release_name("VERSION_ID=7\n") is None
    assert os_release_name("") is None


def test_the_second_os_release_file_is_read_when_the_first_is_missing(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"usr/lib/os-release": 'NAME="Other Made Up"\nVERSION_ID="3"\n'})
    assert MachineFacts(root=root, system=LINUX).os_name() == "Other Made Up 3"


def test_linux_without_an_os_release_file_is_named_linux(tmp_path: Path) -> None:
    assert MachineFacts(root=tmp_path, system=LINUX).os_name() == "Linux"


def test_macos_is_named_with_its_product_version(tmp_path: Path) -> None:
    assert MachineFacts(root=tmp_path, system=MAC).os_name() == "macOS 10.99"
    bare = Platform(system="Darwin", machine="arm64", release="", mac_version="", processor="")
    assert MachineFacts(root=tmp_path, system=bare).os_name() == "macOS"


def test_another_system_is_named_with_its_release(tmp_path: Path) -> None:
    other = Platform(
        system="MadeUpOS", machine="riscv64", release="4.5", mac_version="", processor=""
    )
    assert MachineFacts(root=tmp_path, system=other).os_name() == "MadeUpOS 4.5"
    nothing = Platform(system="", machine="", release="", mac_version="", processor="")
    assert MachineFacts(root=tmp_path, system=nothing).os_name() == "unknown"
    assert MachineFacts(root=tmp_path, system=nothing).arch() == "unknown"


# --- CPU model ------------------------------------------------------------------------


def test_the_cpu_model_is_the_model_name_line() -> None:
    assert cpuinfo_model(CPUINFO_X86) == "Made Up CPU 9000 @ 1.00GHz"


def test_an_arm_machine_without_a_model_name_gives_its_implementer_and_part() -> None:
    assert cpuinfo_model(CPUINFO_ARM) == "CPU implementer 0x00 part 0x000"


def test_other_model_keys_are_read_in_order() -> None:
    assert cpuinfo_model("processor : 0\nHardware : Made Up Board\n") == "Made Up Board"
    assert cpuinfo_model("cpu model : Made Up R0\n") == "Made Up R0"
    assert cpuinfo_model("cpu : Made Up P0, altivec supported\n") == "Made Up P0, altivec supported"
    assert cpuinfo_model("processor : 0\ncpu MHz : 1.0\nSerial : 00000000deadbeef\n") is None


def test_the_cpu_model_falls_back_to_the_processor_name(tmp_path: Path) -> None:
    with_name = Platform(
        system="Linux", machine="x86_64", release="", mac_version="", processor="Made Up X"
    )
    assert MachineFacts(root=tmp_path, system=with_name).cpu_model() == "Made Up X"
    assert MachineFacts(root=tmp_path, system=LINUX).cpu_model() == "unknown"


def test_an_arm_record_from_a_made_up_tree(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"proc/cpuinfo": CPUINFO_ARM})
    machine = MachineFacts(root=root, run=FakeCommands(), which=_which(), system=ARM)
    record = machine.machine_record(gpus=None, node_type=None, environ={})
    assert record.arch == "aarch64"
    assert record.cpu.model == "CPU implementer 0x00 part 0x000"


def test_macos_reads_the_cpu_brand_string(tmp_path: Path) -> None:
    commands = FakeCommands({("sysctl", "-n", "machdep.cpu.brand_string"): "Made Up M0\n"})
    assert MachineFacts(root=tmp_path, run=commands, system=MAC).cpu_model() == "Made Up M0"
    assert MachineFacts(root=tmp_path, run=FakeCommands(), system=MAC).cpu_model() == "unknown"


# --- GPUs -----------------------------------------------------------------------------


def test_no_gpu_is_queried_when_none_is_selected(tmp_path: Path) -> None:
    commands = FakeCommands({GPU_QUERY_ALL: GPU_LINES})
    machine = MachineFacts(root=tmp_path, run=commands, which=_which("nvidia-smi"), system=LINUX)
    assert machine.gpus(None) == ()
    assert commands.asked == []


def test_selected_gpus_are_queried_by_index(tmp_path: Path) -> None:
    query = (*GPU_QUERY_ALL, "-i", "1")
    commands = FakeCommands({query: "1, Made Up GPU B, 000.00.01\n"})
    machine = MachineFacts(root=tmp_path, run=commands, which=_which("nvidia-smi"), system=LINUX)
    assert machine.gpus("1") == (GpuInfo(model="Made Up GPU B", driver="000.00.01"),)
    assert commands.asked == [query]
    machine.gpus(" 2 , 0 ")
    assert commands.asked[-1] == (*GPU_QUERY_ALL, "-i", "2,0")


def test_gpus_are_none_when_the_query_program_is_missing_or_fails(tmp_path: Path) -> None:
    commands = FakeCommands()
    assert MachineFacts(root=tmp_path, run=commands, which=_which(), system=LINUX).gpus("all") == ()
    assert commands.asked == []
    with_program = MachineFacts(
        root=tmp_path, run=commands, which=_which("nvidia-smi"), system=LINUX
    )
    assert with_program.gpus("all") == ()


def test_the_gpu_lines_are_read_in_index_order() -> None:
    assert parse_gpus(GPU_LINES) == (
        GpuInfo(model="Made Up GPU A", driver="000.00.01"),
        GpuInfo(model="Made Up GPU B", driver="000.00.01"),
    )
    assert parse_gpus("0, Made Up, GPU C, 000.00.02\n") == (
        GpuInfo(model="Made Up, GPU C", driver="000.00.02"),
    )
    assert parse_gpus("No devices were found\n0, , 1.0\nx, A, 1.0\n") == ()


def test_a_gpu_index_outside_ascii_digits_is_skipped() -> None:
    superscript_two = chr(0xB2)
    lines = f"{superscript_two}, Made Up GPU A, 000.00.01\n1, Made Up GPU B, 000.00.01\n"
    assert parse_gpus(lines) == (GpuInfo(model="Made Up GPU B", driver="000.00.01"),)


def test_every_repository_the_facts_cite_is_pinned_to_a_release() -> None:
    links = re.findall(r"https://github\.com/\S+", provenance.__doc__ or "")
    assert links
    for link in links:
        assert "/blob/" in link, link


# --- container engine, container, pipeline --------------------------------------------


def test_the_engine_is_the_one_auto_would_pick(tmp_path: Path) -> None:
    commands = FakeCommands(
        {
            ("docker", "--version"): "Docker version 0.0.1, build 0000000\n",
            ("podman", "--version"): "podman version 0.0.2\n",
        }
    )
    both = MachineFacts(root=tmp_path, run=commands, which=_which("docker", "podman"), system=LINUX)
    assert both.engine({}) == EngineInfo(name="docker", version="0.0.1")
    preferred = {api.ENGINE_VARIABLE: "podman"}
    assert both.engine(preferred) == EngineInfo(name="podman", version="0.0.2")
    none = MachineFacts(root=tmp_path, run=commands, which=_which(), system=LINUX)
    assert none.engine({}) is None


def test_an_engine_whose_version_cannot_be_read_is_recorded_as_unknown(tmp_path: Path) -> None:
    machine = MachineFacts(root=tmp_path, run=FakeCommands(), which=_which("podman"), system=LINUX)
    assert machine.engine({}) == EngineInfo(name="podman", version="unknown")


@pytest.mark.parametrize(
    ("files", "environ"),
    [
        ({".dockerenv": ""}, {}),
        ({"run/.containerenv": ""}, {}),
        ({}, {"container": "podman"}),
        ({}, {"KUBERNETES_SERVICE_HOST": "10.0.0.1"}),
        ({"proc/self/cgroup": "12:pids:/docker/0000000000\n"}, {}),
        ({"proc/self/cgroup": "1:name=systemd:/kubepods/pod0\n"}, {}),
        ({"proc/self/cgroup": "0::/machine.slice/libpod-0000.scope\n"}, {}),
        ({"proc/self/cgroup": "0::/system.slice/containerd-0000.scope\n"}, {}),
        ({"proc/self/cgroup": "0::/lxc.payload.made-up/init.scope\n"}, {}),
    ],
)
def test_a_container_is_recognised(
    tmp_path: Path, files: dict[str, str], environ: dict[str, str]
) -> None:
    machine = MachineFacts(root=_tree(tmp_path, files), system=LINUX)
    assert machine.in_container(environ) is True


def test_a_host_process_is_not_in_a_container(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"proc/self/cgroup": "0::/user.slice/user-1000.slice/session-1.scope\n"})
    assert MachineFacts(root=root, system=LINUX).in_container({"container": ""}) is False
    assert MachineFacts(root=tmp_path / "empty", system=LINUX).in_container({}) is False


needs_permissions = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs a user that a folder without permissions keeps out",
)


@needs_permissions
def test_a_marker_folder_that_cannot_be_searched_counts_as_no_marker(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"proc/self/cgroup": "0::/user.slice/session-1.scope\n"})
    locked = root / "run"
    locked.mkdir()
    locked.chmod(0)
    try:
        machine = MachineFacts(root=root, run=FakeCommands(), which=_which(), system=LINUX)
        assert machine.in_container({}) is False
        assert machine.machine_record(gpus=None, node_type=None, environ={}).in_container is False
    finally:
        locked.chmod(0o700)


def test_an_automated_pipeline_is_recorded_from_the_environment(tmp_path: Path) -> None:
    machine = MachineFacts(root=tmp_path, run=FakeCommands(), which=_which(), system=LINUX)
    assert machine.machine_record(gpus=None, node_type=None, environ={"CI": "true"}).ci is True
    assert machine.machine_record(gpus=None, node_type=None, environ={"CI": "0"}).ci is False


# --- tools ----------------------------------------------------------------------------


def test_every_tool_is_listed_with_whether_it_was_found_and_its_version() -> None:
    commands = FakeCommands(
        {
            ("docker", "--version"): "Docker version 0.0.1, build 0000000\n",
            ("perf", "--version"): "perf version 0.0.3\n",
            ("ncu", "--version"): "Made Up Profiler\nCopyright (c) 2001-2002\nVersion 0.0.4.0\n",
            ("hyperfine", "--version"): "",
        }
    )
    machine = MachineFacts(
        run=commands, which=_which("docker", "perf", "ncu", "hyperfine", "true"), system=LINUX
    )
    assert machine.tools() == [
        ToolFact(name="docker", found=True, version="0.0.1"),
        ToolFact(name="podman", found=False, note="not found on PATH"),
        ToolFact(name="nvidia-smi", found=False, note="not found on PATH"),
        ToolFact(name="nsys", found=False, note="not found on PATH"),
        ToolFact(name="ncu", found=True, version="0.0.4.0"),
        ToolFact(name="perf", found=True, version="0.0.3"),
        ToolFact(name="hyperfine", found=True, note="its version could not be read"),
        ToolFact(name="conda", found=False, note="not found on PATH"),
        ToolFact(name="true", found=True, note="the empty command; no version is read"),
    ]
    assert ("true", "--version") not in commands.asked
    for fact in machine.tools():
        assert "/opt/made-up" not in json.dumps(fact.__dict__)


def test_the_real_command_runner_keeps_only_the_output_of_a_command_that_succeeded(
    tmp_path: Path,
) -> None:
    printed = [sys.executable, "-c", "print('0.0.1')"]
    on_errors = [sys.executable, "-c", "import sys; sys.stderr.write('0.0.2\\n')"]
    failed = [sys.executable, "-c", "print('0.0.3'); raise SystemExit(1)"]
    assert real_run_command(printed) == "0.0.1\n"
    assert real_run_command(on_errors) == "0.0.2\n"
    assert real_run_command(failed) is None
    assert real_run_command([str(tmp_path / "missing")]) is None


def test_the_first_version_number_is_taken() -> None:
    assert version_of("Docker version 0.0.1, build 0000000") == "0.0.1"
    assert version_of("Copyright (c) 2001-2002\nVersion 0.0.4.0 (build 0)") == "0.0.4.0"
    assert version_of("made up tool 12") is None
    assert version_of("") is None
    assert version_of(None) is None


# --- the delegate ---------------------------------------------------------------------


def test_making_the_facts_reads_nothing() -> None:
    made: Facts = facts()
    assert isinstance(made, MachineFacts)
    assert api.DELEGATES["facts"] == ("pairbench.provenance", "facts", api.MakeFacts)
