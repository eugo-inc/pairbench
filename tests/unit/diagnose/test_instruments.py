# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The instruments: the commands they wrap, the readers of their output, what the machine allows.

No test runs ``perf``: the machine's facts are read from a made-up process
file system and a made-up ``perf`` on ``PATH``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from pairbench.api import InstrumentedCommand, InstrumentedLaunch
from pairbench.diagnose import instruments, pysampler
from pairbench.diagnose.instruments import HostFacts
from pairbench.errors import Refusal

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "diagnose"
EVENTS = (
    "instructions,cycles,branches,branch-misses,cache-references,cache-misses,"
    "task-clock,context-switches,cpu-migrations,page-faults"
)


def test_counters_puts_perf_stat_in_front_of_the_command() -> None:
    wrapped = instruments.counters.wrap(["./app", "--n", "3"], out="/pairbench/artifacts", tools={})
    assert wrapped == InstrumentedCommand(
        argv=(
            "perf",
            "stat",
            "-x",
            ";",
            "-o",
            "/pairbench/artifacts/perf-stat.txt",
            "-e",
            EVENTS,
            "--",
            "./app",
            "--n",
            "3",
        ),
        outputs=("perf-stat.txt",),
    )
    assert instruments.counters.name == "counters"
    assert instruments.counters.tool_files == ()


def test_stacks_runs_a_fixed_script_with_the_command_as_its_arguments() -> None:
    wrapped = instruments.Stacks(hz=49, call_graph="dwarf").wrap(
        ["./app", "$(x)"], out="/out/", tools={}
    )
    assert wrapped.argv == (
        "sh",
        "-c",
        instruments.STACKS_SCRIPT,
        "pairbench-stacks",
        "/out/",
        "49",
        "dwarf",
        "./app",
        "$(x)",
    )
    assert wrapped.env == {"PYTHONPERFSUPPORT": "1"}
    assert wrapped.outputs == ("perf-script.txt", "perf-buildids.txt")
    assert (instruments.stacks.hz, instruments.stacks.call_graph) == (99, "fp")
    assert "./app" not in instruments.STACKS_SCRIPT


FAKE_PERF = """#!/bin/sh
# A made-up perf: it logs its arguments and writes what each subcommand would.
echo "$@" >> "$PERF_LOG"
case "$1" in
record)
  while [ "$1" != "-o" ]; do shift; done
  data=$2
  while [ "$1" != "--" ]; do shift; done
  shift
  printf 'data' > "$data"
  "$@"
  exit $?
  ;;
script) printf 'app 1 [000] 1.0: cycles:\\n\\t aa main (/app)\\n\\n' ;;
buildid-list) printf '11 /app\\n' ;;
esac
"""


def _fake_perf(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    perf = folder / "perf"
    perf.write_text(FAKE_PERF, encoding="utf-8")
    perf.chmod(perf.stat().st_mode | stat.S_IXUSR)
    return perf


def test_the_stacks_script_reads_the_recording_back_removes_it_and_keeps_the_exit_code(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    _fake_perf(bin_dir)
    out = tmp_path / "out"
    out.mkdir()
    marker = tmp_path / "ran"
    wrapped = instruments.Stacks().wrap(
        ["sh", "-c", 'touch "$1"; exit 3', "work", str(marker)], out=str(out), tools={}
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PERF_LOG": str(tmp_path / "log"),
    }
    done = subprocess.run(wrapped.argv, env=env, check=False, capture_output=True, text=True)
    assert done.returncode == 3
    assert marker.is_file()
    assert sorted(p.name for p in out.iterdir()) == [
        "perf-buildids.txt",
        "perf-script.err",
        "perf-script.txt",
    ]
    assert (
        out / "perf-script.txt"
    ).read_text() == "app 1 [000] 1.0: cycles:\n\t aa main (/app)\n\n"
    assert (out / "perf-buildids.txt").read_text() == "11 /app\n"
    calls = (tmp_path / "log").read_text().splitlines()
    assert calls[0].startswith(
        f"record -F 99 --call-graph fp --buildid-all -o {out}/perf.data -- sh"
    )
    assert calls[1] == f"script -i {out}/perf.data -F comm,pid,tid,time,event,ip,sym,dso"
    assert calls[2] == f"buildid-list -i {out}/perf.data"


def test_the_stacks_script_never_runs_a_word_of_the_command_as_shell(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _fake_perf(bin_dir)
    out = tmp_path / "out"
    out.mkdir()
    hostile = f"$(touch {tmp_path}/owned)"
    wrapped = instruments.Stacks().wrap(["echo", hostile], out=str(out), tools={})
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PERF_LOG": str(tmp_path / "log"),
    }
    done = subprocess.run(wrapped.argv, env=env, check=False, capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, hostile + "\n")
    assert not (tmp_path / "owned").exists()


def test_the_stacks_script_reads_nothing_back_when_perf_recorded_nothing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    perf = bin_dir / "perf"
    perf.write_text("#!/bin/sh\necho 'perf_event_paranoid setting is 4' >&2\nexit 255\n")
    perf.chmod(0o755)
    out = tmp_path / "out"
    out.mkdir()
    wrapped = instruments.Stacks().wrap(["true"], out=str(out), tools={})
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    done = subprocess.run(wrapped.argv, env=env, check=False, capture_output=True, text=True)
    assert done.returncode == 255
    assert "perf_event_paranoid" in done.stderr
    assert list(out.iterdir()) == []


def test_pystacks_puts_the_sampler_between_the_interpreter_and_the_program() -> None:
    wrapped = instruments.pystacks.wrap(
        ["/usr/bin/python3.12", "-u", "-X", "dev", "bench.py", "--n", "3"],
        out="/pairbench/artifacts",
        tools={"pysampler.py": "/pairbench/tools/pysampler.py"},
    )
    assert wrapped.argv == (
        "/usr/bin/python3.12",
        "-u",
        "-X",
        "dev",
        "/pairbench/tools/pysampler.py",
        "--out",
        "/pairbench/artifacts",
        "--hz",
        "99",
        "--",
        "bench.py",
        "--n",
        "3",
    )
    assert wrapped.outputs == ("pystacks.folded", "pystacks-too-old.txt")
    assert wrapped.env == {}
    assert instruments.pystacks.tool_files == (Path(pysampler.__file__),)


@pytest.mark.parametrize(
    "argv",
    [
        ["hyperfine", "--export-json", "/pairbench/artifacts/h.json", "python3 bench.py"],
        ["./app", "python3"],
        [],
    ],
)
def test_pystacks_refuses_a_command_that_does_not_start_with_python(argv: list[str]) -> None:
    with pytest.raises(Refusal) as caught:
        instruments.pystacks.wrap(argv, out="/o", tools={})
    assert (caught.value.code, caught.value.message) == (
        "E_ENGINE_UNSUPPORTED",
        "the sampler of pystacks runs only a command that starts with a Python interpreter",
    )


def test_pystacks_falls_back_to_the_sampler_file_when_no_tool_path_is_given() -> None:
    wrapped = instruments.PyStacks(hz=7).wrap(["python", "-m", "pkg"], out="/o", tools={})
    assert wrapped.argv == (
        "python",
        str(instruments.SAMPLER_FILE),
        "--out",
        "/o",
        "--hz",
        "7",
        "--",
        "-m",
        "pkg",
    )


@pytest.mark.parametrize(
    ("argv", "head", "program"),
    [
        (["python3", "x.py", "a"], ["python3"], ["x.py", "a"]),
        (
            ["python3", "-u", "-X", "dev", "-m", "mod", "a"],
            ["python3", "-u", "-X", "dev"],
            ["-m", "mod", "a"],
        ),
        (["python3", "-OOc", "print(1)"], ["python3", "-OO"], ["-c", "print(1)"]),
        (["python3", "-cprint(1)", "a"], ["python3"], ["-cprint(1)", "a"]),
        (["python3", "-Wignore", "x.py"], ["python3", "-Wignore"], ["x.py"]),
        (["python3", "-W", "ignore", "x.py"], ["python3", "-W", "ignore"], ["x.py"]),
        (["python3", "-uW", "error", "x.py"], ["python3", "-uW", "error"], ["x.py"]),
        (
            ["python3", "--check-hash-based-pycs", "never", "x.py"],
            ["python3", "--check-hash-based-pycs", "never"],
            ["x.py"],
        ),
        (["python3", "-I", "-", "a"], ["python3", "-I"], ["-", "a"]),
        (["python3", "-u"], ["python3", "-u"], []),
        ([], [], []),
    ],
)
def test_split_interpreter(argv: list[str], head: list[str], program: list[str]) -> None:
    assert instruments.split_interpreter(argv) == (head, program)


def test_the_counts_of_the_real_run_add_up_over_both_core_types() -> None:
    reading = instruments.read_counters((FIXTURES / "perf-stat.txt").read_text(encoding="utf-8"))
    assert reading.values == {
        "instructions": 8502870854.0,
        "cycles": 1841034817.0,
        "branches": 1709223351.0,
        "branch-misses": 4496377.0,
        "cache-references": 2850045818.0,
        "cache-misses": 14155627.0,
        "task-clock": 282.60,
        "context-switches": 117.0,
        "cpu-migrations": 3.0,
        "page-faults": 1361.0,
    }
    assert reading.not_counted == ()


def test_an_event_no_line_of_which_was_counted_is_named() -> None:
    text = (
        "100;;cpu_atom/instructions/;10;50.00;;\n"
        "<not counted>;;cpu_core/instructions/;0;0.00;;\n"
        "<not supported>;;cycles;0;100.00;;\n"
        "<not counted>;;cpu_atom/cache-misses/;0;0.00;;\n"
        "<not counted>;;cpu_core/cache-misses/;0;0.00;;\n"
        "7;;page-faults:u;10;100.00;;\n"
        "short line\n"
    )
    reading = instruments.read_counters(text)
    assert reading.values == {"instructions": 100.0, "page-faults": 7.0}
    assert reading.not_counted == (
        "cycles",
        "branches",
        "branch-misses",
        "cache-references",
        "cache-misses",
        "task-clock",
        "context-switches",
        "cpu-migrations",
    )


def test_a_count_that_is_no_finite_number_is_not_counted() -> None:
    text = (
        "nan;;instructions;10;100.00;;\n"
        "inf;;cpu_atom/cycles/;10;50.00;;\n"
        "50;;cpu_core/cycles/;10;50.00;;\n"
        "1e999;;branches;10;100.00;;\n"
        "-inf;;cache-misses;10;100.00;;\n"
        "1e308;;cpu_atom/branch-misses/;10;50.00;;\n"
        "1e308;;cpu_core/branch-misses/;10;50.00;;\n"
        "7;;page-faults;10;100.00;;\n"
    )
    reading = instruments.read_counters(text)
    # A line that is no finite number is passed over as a line not counted is.
    assert reading.values == {"cycles": 50.0, "page-faults": 7.0}
    assert reading.not_counted == (
        "instructions",
        "branches",
        "branch-misses",
        "cache-references",
        "cache-misses",
        "task-clock",
        "context-switches",
        "cpu-migrations",
    )


@pytest.mark.parametrize(
    ("printed", "name"),
    [
        ("armv8_pmuv3_1/instructions/", "instructions"),
        ("instructions:u", "instructions"),
        ("cpu_core/cache-misses/u", "cache-misses"),
        (" task-clock ", "task-clock"),
        ("cycles", "cycles"),
    ],
)
def test_event_name(printed: str, name: str) -> None:
    assert instruments.event_name(printed) == name


def _proc(root: Path, paranoid: str | None, cap_eff: str | None) -> Path:
    (root / "sys" / "kernel").mkdir(parents=True)
    (root / "self").mkdir()
    if paranoid is not None:
        (root / "sys" / "kernel" / "perf_event_paranoid").write_text(paranoid + "\n")
    if cap_eff is not None:
        (root / "self" / "status").write_text(f"Name:\tpython\nCapEff:\t{cap_eff}\nCapBnd:\t0\n")
    return root


def test_host_facts_read_the_setting_the_capabilities_and_perf_on_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", "3", "0000004000000000"))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    perf = _fake_perf(tmp_path / "bin")
    facts = instruments.host_facts({"PATH": str(tmp_path / "bin")})
    assert facts == HostFacts(perf=str(perf), paranoid=3, capabilities=1 << 38, euid=1000)
    assert facts.forbidding() is None


def test_host_facts_without_perf_and_without_a_readable_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", None, None))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    (tmp_path / "empty").mkdir()
    facts = instruments.host_facts({"PATH": str(tmp_path / "empty")})
    assert facts == HostFacts(perf=None, paranoid=None, capabilities=None, euid=1000)


def test_host_facts_ignore_a_setting_that_is_no_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", "x", "zz"))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    facts = instruments.host_facts({"PATH": ""})
    assert (facts.paranoid, facts.capabilities) == (None, None)


FORBIDS_4 = (
    "the kernel setting perf_event_paranoid is 4, which forbids it "
    "for a process without the capability CAP_PERFMON"
)


@pytest.mark.parametrize(
    ("facts", "forbidding"),
    [
        (HostFacts(perf="perf", paranoid=2, capabilities=0, euid=1000), None),
        (HostFacts(perf="perf", paranoid=-1, capabilities=0, euid=1000), None),
        (HostFacts(perf="perf", paranoid=None, capabilities=0, euid=1000), None),
        (HostFacts(perf="perf", paranoid=4, capabilities=0, euid=1000), FORBIDS_4),
        (HostFacts(perf="perf", paranoid=4, capabilities=None, euid=None), FORBIDS_4),
        (HostFacts(perf="perf", paranoid=4, capabilities=1 << 38, euid=1000), None),
        (HostFacts(perf="perf", paranoid=4, capabilities=1 << 21, euid=1000), None),
        (HostFacts(perf="perf", paranoid=4, capabilities=1 << 20, euid=1000), FORBIDS_4),
        (HostFacts(perf="perf", paranoid=4, capabilities=0, euid=0), None),
    ],
)
def test_what_forbids_perf(facts: HostFacts, forbidding: str | None) -> None:
    assert facts.forbidding() == forbidding


OPEN = HostFacts(perf="/usr/bin/perf", paranoid=2, capabilities=0, euid=1000)
NO_PERF = HostFacts(perf=None, paranoid=2, capabilities=0, euid=1000)
CLOSED = HostFacts(perf="/usr/bin/perf", paranoid=4, capabilities=0, euid=1000)


@pytest.mark.parametrize(
    ("instrument", "place", "facts", "perf_counters", "reason"),
    [
        ("counters", "host", OPEN, False, None),
        ("stacks", "host", NO_PERF, False, "not_installed"),
        ("counters", "host", CLOSED, True, "not_permitted"),
        ("counters", "container", NO_PERF, False, "no_capability"),
        ("stacks", "container", CLOSED, True, None),
        ("counters", "unknown", NO_PERF, False, None),
        ("pystacks", "host", NO_PERF, False, None),
        ("pystacks", "container", NO_PERF, False, None),
    ],
)
def test_what_is_skipped_without_a_launch(
    instrument: str,
    place: instruments.Place,
    facts: HostFacts,
    perf_counters: bool,
    reason: str | None,
) -> None:
    assert instruments.skip_before_launch(instrument, place, facts, perf_counters) == reason


def _launched(
    folder: Path, rc: int, files: dict[str, str], *, timed_out: bool = False
) -> InstrumentedLaunch:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return InstrumentedLaunch(rc=rc, artifacts=folder, timed_out=timed_out)


KPTR_WARNING = (
    "WARNING: Kernel address maps (/proc/{kallsyms,modules}) are restricted,\n"
    "check /proc/sys/kernel/kptr_restrict and /proc/sys/kernel/perf_event_paranoid.\n"
)
PARANOID = (
    "Error:\nAccess to performance monitoring is limited.\nperf_event_paranoid setting is 4\n"
)


@pytest.mark.parametrize(
    ("instrument", "rc", "files", "place", "timed_out", "judged"),
    [
        ("counters", 0, {"perf-stat.txt": "1;;cycles;1;100.00;;\n"}, "host", False, ("ok", None)),
        ("stacks", 0, {"perf-script.txt": "x"}, "container", False, ("ok", None)),
        ("pystacks", 0, {"pystacks.folded": "a 1\n"}, "host", False, ("ok", None)),
        ("counters", 0, {}, "host", False, ("failed", "launch_failed")),
        ("counters", 0, {"perf-stat.txt": ""}, "host", False, ("failed", "launch_failed")),
        ("stacks", 255, {"stderr.txt": PARANOID}, "host", False, ("skipped", "not_permitted")),
        ("stacks", 1, {"server.log": PARANOID}, "container", False, ("skipped", "not_permitted")),
        (
            "counters",
            127,
            {"stderr.txt": "perf: not found"},
            "container",
            False,
            ("skipped", "not_in_image"),
        ),
        ("counters", 127, {}, "host", False, ("skipped", "not_installed")),
        ("counters", 127, {}, "unknown", False, ("skipped", "not_installed")),
        (
            "pystacks",
            86,
            {"pystacks-too-old.txt": "old"},
            "host",
            False,
            ("skipped", "interpreter_too_old"),
        ),
        ("pystacks", 86, {}, "host", False, ("failed", "launch_failed")),
        ("pystacks", 127, {}, "container", False, ("failed", "launch_failed")),
        ("counters", 0, {"perf-stat.txt": "x"}, "host", True, ("failed", "launch_failed")),
        ("counters", 127, {}, "container", True, ("failed", "launch_failed")),
        ("stacks", 3, {"perf-script.txt": "x"}, "host", False, ("failed", "launch_failed")),
        (
            "stacks",
            2,
            {"stderr.txt": "Segmentation fault"},
            "host",
            False,
            ("failed", "launch_failed"),
        ),
        (
            "counters",
            255,
            {"perf-stat.txt": "# started on Thu Jan  1 00:00:00 1970\n\n", "stderr.txt": PARANOID},
            "host",
            False,
            ("skipped", "not_permitted"),
        ),
        (
            "stacks",
            1,
            {"perf-script.txt": "x", "stderr.txt": KPTR_WARNING},
            "host",
            False,
            ("failed", "launch_failed"),
        ),
        ("stacks", 1, {"stderr.txt": KPTR_WARNING}, "host", False, ("failed", "launch_failed")),
        ("pystacks", 1, {"stderr.txt": PARANOID}, "host", False, ("failed", "launch_failed")),
        ("pystacks", 0, {"pystacks.folded": ""}, "host", False, ("ok", None)),
        ("pystacks", 0, {}, "host", False, ("failed", "launch_failed")),
    ],
)
def test_how_a_launch_is_judged(
    tmp_path: Path,
    instrument: str,
    rc: int,
    files: dict[str, str],
    place: instruments.Place,
    timed_out: bool,
    judged: tuple[str, str | None],
) -> None:
    launch = _launched(tmp_path / "a", rc, files, timed_out=timed_out)
    assert instruments.judge_launch(instrument, launch, place) == judged


def test_the_doctor_reports_perf_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", "2", "0"))
    (tmp_path / "empty").mkdir()
    reports = instruments.doctor_reports({"PATH": str(tmp_path / "empty")})
    assert sorted(reports) == ["counters", "pystacks", "stacks"]
    assert reports["counters"].status == "unavailable"
    assert reports["counters"].summary == "perf: its program is not installed"
    assert reports["stacks"] == reports["counters"]
    assert reports["pystacks"].status == "ok"
    assert reports["pystacks"].summary == (
        "the sampler of pairbench needs no privilege; it runs a Python workload on the "
        "side's interpreter, Python 3.8 or newer, where perf cannot run"
    )


def test_the_doctor_names_the_setting_and_the_capability_when_the_system_forbids_perf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", "4", "0"))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    _fake_perf(tmp_path / "bin")
    reports = instruments.doctor_reports({"PATH": str(tmp_path / "bin")})
    assert reports["counters"].status == "unavailable"
    assert reports["counters"].summary == "perf is installed, but " + FORBIDS_4
    assert reports["counters"].detail == {
        "setting": "perf_event_paranoid",
        "value": 4,
        "capability": "CAP_PERFMON",
    }


def test_the_doctor_says_ok_when_perf_is_installed_and_permitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(instruments, "PROC", _proc(tmp_path / "proc", "1", "0"))
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    _fake_perf(tmp_path / "bin")
    reports = instruments.doctor_reports({"PATH": str(tmp_path / "bin")})
    assert (reports["stacks"].status, reports["stacks"].summary) == (
        "ok",
        "perf is installed and the system permits it",
    )
