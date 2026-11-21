# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The timed launch of a host process, the untimed command runner and the launch settings."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pairbench import api
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.model import LaunchSettings, Side
from pairbench.sides.base import (
    GPU_ORDER_VARIABLE,
    GPU_VARIABLE,
    NOT_STARTED_RC,
    HostProcesses,
    HostResolved,
    HostRun,
    ProcessUsage,
    Watchdog,
    host_environment,
    host_outcome,
    launch_on_host,
    parse_cpu_list,
    pinning_supported,
    refuse_host_settings,
    require_env_pass,
    run_command,
    usage_from_rusage,
)

USAGE_A = ProcessUsage(
    user_s=1.5,
    sys_s=0.25,
    figures={
        "rss_peak_bytes": 4096.0,
        "ctx_voluntary": 10.0,
        "ctx_involuntary": 2.0,
        "faults_major": 1.0,
        "faults_minor": 100.0,
    },
)
USAGE_B = ProcessUsage(
    user_s=2.0,
    sys_s=0.5,
    figures={
        "rss_peak_bytes": 8192.0,
        "ctx_voluntary": 5.0,
        "ctx_involuntary": 3.0,
        "faults_major": 0.0,
        "faults_minor": 50.0,
    },
)


def _run(folder: Path, name: str = "") -> HostRun:
    target = folder / name if name else folder
    target.mkdir(parents=True, exist_ok=True)
    return HostRun(
        argv=("work",), env={}, stdout=target / "stdout.txt", stderr=target / "stderr.txt"
    )


# --- the order of the calls -------------------------------------------------


def test_one_run_does_nothing_but_start_and_collect_between_the_clock_reads(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host()
    launch_on_host([_run(tmp_path)], host=host)
    assert host.log == ["open", "open", "pin", "clock", "spawn", "reap", "clock", "unpin", "kill"]


def test_two_runs_open_every_file_before_the_first_read_and_share_one_interval(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(durations_ns=(3_000_000_000, 5_000_000_000), rcs=(0, 0))
    result = launch_on_host([_run(tmp_path, "run1"), _run(tmp_path, "run2")], host=host)
    assert host.log == [
        "open",
        "open",
        "open",
        "open",
        "pin",
        "clock",
        "spawn",
        "reap",
        "spawn",
        "reap",
        "clock",
        "unpin",
        "kill",
        "kill",
    ]
    assert result.run_ns == 8_000_000_000
    assert result.pids == (4001, 4002)


def test_a_fake_side_whose_two_runs_take_3_and_5_units_reads_one_interval_of_8(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(durations_ns=(3_000_000_000, 5_000_000_000), rcs=(0, 0))
    outcome = host_outcome(launch_on_host([_run(tmp_path, "a"), _run(tmp_path, "b")], host=host))
    assert outcome.timing == {"run_s": 8.0, "launch_s": 8.0}
    assert outcome.pid == 4001
    assert outcome.second_pid == 4002


def test_the_second_run_does_not_start_when_the_first_fails(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(durations_ns=(3_000_000_000, 5_000_000_000), rcs=(2, 0))
    outcome = host_outcome(launch_on_host([_run(tmp_path, "a"), _run(tmp_path, "b")], host=host))
    assert host.log.count("spawn") == 1
    assert outcome.rc == 2
    assert outcome.timing["run_s"] == 3.0
    assert outcome.second_pid is None


def test_a_failed_second_run_gives_its_own_exit_code(tmp_path: Path, recording_host: Any) -> None:
    host = recording_host(durations_ns=(1, 1), rcs=(0, 7))
    result = launch_on_host([_run(tmp_path, "a"), _run(tmp_path, "b")], host=host)
    assert result.rc == 7


def test_a_command_that_cannot_start_reports_127_and_says_why_in_its_stderr_file(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(spawn_error=FileNotFoundError(2, "No such file or directory"))
    run = _run(tmp_path)
    result = launch_on_host([run], host=host)
    assert result.rc == NOT_STARTED_RC
    assert result.pids == ()
    assert "reap" not in host.log
    assert run.stderr.read_text().startswith("cannot start the command: ")


def test_an_interrupt_stops_and_collects_the_running_process_and_is_raised_again(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(interrupt_on_reap=True)
    with pytest.raises(KeyboardInterrupt):
        launch_on_host([_run(tmp_path)], host=host)
    assert host.log == ["open", "open", "pin", "clock", "spawn", "reap", "kill", "reap", "unpin"]
    assert host.killed == [4001]


def test_the_cpus_are_handed_to_the_seam_before_the_first_read(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host()
    launch_on_host([_run(tmp_path)], host=host, cpus=frozenset({2, 3}))
    assert host.pinned == frozenset({2, 3})
    assert host.log.index("pin") < host.log.index("clock")


def test_the_timeout_is_armed_before_the_cpus_are_pinned(
    tmp_path: Path, recording_host: Any
) -> None:
    def timers() -> set[threading.Thread]:
        return {t for t in threading.enumerate() if isinstance(t, threading.Timer)}

    class Watching(recording_host):  # type: ignore[misc]
        def pin(self, cpus: frozenset[int] | None) -> Any:
            self.timers_at_pin = timers() - before
            return super().pin(cpus)

    before = timers()
    host = Watching()
    launch_on_host([_run(tmp_path)], host=host, timeout_s=60.0, cpus=frozenset({2}))
    assert len(host.timers_at_pin) == 1


def test_a_timeout_that_passes_between_two_runs_is_reported(
    tmp_path: Path, recording_host: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    watch = Watchdog.watch

    def watch_then_pass(self: Watchdog, pid: int | None) -> None:
        watch(self, pid)
        if pid is None:
            self._fire()

    monkeypatch.setattr(Watchdog, "watch", watch_then_pass)
    host = recording_host(durations_ns=(1, 1), rcs=(0, 0))
    result = launch_on_host([_run(tmp_path, "a"), _run(tmp_path, "b")], host=host, timeout_s=60.0)
    assert host.log.count("spawn") == 1
    assert result.timed_out is True
    assert result.pids == (4001,)


# --- resource usage ---------------------------------------------------------


def test_the_usage_of_two_runs_adds_up_and_keeps_the_larger_peak(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(durations_ns=(1_000_000_000, 1_000_000_000), usages=(USAGE_A, USAGE_B))
    host.rcs = [0, 0]
    outcome = host_outcome(launch_on_host([_run(tmp_path, "a"), _run(tmp_path, "b")], host=host))
    assert outcome.timing == {"run_s": 2.0, "launch_s": 2.0, "user_s": 3.5, "sys_s": 0.75}
    assert outcome.cpu_s == 4.25
    assert outcome.usage == {
        "rss_peak_bytes": 8192.0,
        "ctx_voluntary": 15.0,
        "ctx_involuntary": 5.0,
        "faults_major": 1.0,
        "faults_minor": 150.0,
    }


def test_a_platform_that_reports_no_usage_gives_no_cpu_time_and_no_figures(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(usages=(None,))
    outcome = host_outcome(launch_on_host([_run(tmp_path)], host=host))
    assert outcome.timing == {"run_s": 3.0, "launch_s": 3.0}
    assert outcome.cpu_s is None
    assert outcome.usage == {}


def test_the_resource_cases_of_a_host_launch_come_from_its_usage(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(durations_ns=(2_000_000_000,), usages=(USAGE_A,))
    samples = api.resource_samples(host_outcome(launch_on_host([_run(tmp_path)], host=host)))
    assert {sample.case: sample.value for sample in samples} == {
        "res/user": 1.5,
        "res/sys": 0.25,
        "res/cores": 0.875,
        "res/rss_peak": 4096.0,
        "res/ctx_voluntary": 10.0,
        "res/ctx_involuntary": 2.0,
        "res/faults_major": 1.0,
        "res/faults_minor": 100.0,
    }


RUSAGE = SimpleNamespace(
    ru_utime=1.25,
    ru_stime=0.5,
    ru_maxrss=2048,
    ru_nvcsw=7,
    ru_nivcsw=3,
    ru_majflt=1,
    ru_minflt=99,
)


def test_peak_memory_is_kilobytes_on_linux_and_bytes_on_macos() -> None:
    assert usage_from_rusage(RUSAGE, "linux").figures["rss_peak_bytes"] == 2097152.0
    assert usage_from_rusage(RUSAGE, "darwin").figures["rss_peak_bytes"] == 2048.0
    assert usage_from_rusage(RUSAGE, "linux") == ProcessUsage(
        user_s=1.25,
        sys_s=0.5,
        figures={
            "rss_peak_bytes": 2097152.0,
            "ctx_voluntary": 7.0,
            "ctx_involuntary": 3.0,
            "faults_major": 1.0,
            "faults_minor": 99.0,
        },
    )


# --- real processes ---------------------------------------------------------

needs_wait4 = pytest.mark.skipif(
    not hasattr(os, "wait4"), reason="needs os.wait4, the exit status call that reports usage"
)


@needs_wait4
def test_a_real_process_writes_its_output_to_files_and_reports_its_usage(tmp_path: Path) -> None:
    run = HostRun(
        argv=(sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"),
        env=dict(os.environ),
        stdout=tmp_path / "stdout.txt",
        stderr=tmp_path / "stderr.txt",
    )
    outcome = host_outcome(launch_on_host([run], host=HostProcesses()))
    assert outcome.rc == 0
    assert run.stdout.read_text() == "out\n"
    assert run.stderr.read_text() == "err\n"
    assert outcome.timing["run_s"] == outcome.timing["launch_s"]
    assert outcome.timing["run_s"] > 0
    assert set(outcome.usage) == set(api.USAGE_KEYS)
    assert outcome.usage["rss_peak_bytes"] > 0
    assert outcome.cpu_s == outcome.timing["user_s"] + outcome.timing["sys_s"]


@needs_wait4
def test_a_real_process_that_runs_into_its_timeout_is_stopped(tmp_path: Path) -> None:
    run = HostRun(
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        env=dict(os.environ),
        stdout=tmp_path / "stdout.txt",
        stderr=tmp_path / "stderr.txt",
    )
    started = time.monotonic()
    result = launch_on_host([run], host=HostProcesses(), timeout_s=0.3)
    assert time.monotonic() - started < 10
    assert result.timed_out is True
    assert result.rc == -9


@needs_wait4
def test_a_process_the_launch_left_running_is_stopped_after_the_launch(tmp_path: Path) -> None:
    script = (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "print(child.pid)"
    )
    run = HostRun(
        argv=(sys.executable, "-c", script),
        env=dict(os.environ),
        stdout=tmp_path / "stdout.txt",
        stderr=tmp_path / "stderr.txt",
    )
    result = launch_on_host([run], host=HostProcesses())
    assert result.rc == 0
    left = int(run.stdout.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(left, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the process the launch left running was not stopped")


@pytest.mark.skipif(not pinning_supported(), reason="needs a platform that pins processes to CPUs")
def test_a_real_process_runs_on_the_pinned_cpus_and_the_tool_stays_where_it_was(
    tmp_path: Path,
) -> None:
    before = os.sched_getaffinity(0)
    cpu = min(before)
    run = HostRun(
        argv=(sys.executable, "-c", "import os; print(sorted(os.sched_getaffinity(0)))"),
        env=dict(os.environ),
        stdout=tmp_path / "stdout.txt",
        stderr=tmp_path / "stderr.txt",
    )
    result = launch_on_host([run], host=HostProcesses(), cpus=frozenset({cpu}))
    assert result.rc == 0
    assert run.stdout.read_text() == f"[{cpu}]\n"
    assert os.sched_getaffinity(0) == before


# --- the untimed runner -----------------------------------------------------


def test_run_command_returns_output_and_never_raises(tmp_path: Path) -> None:
    done = run_command([sys.executable, "-c", "print('hello')"])
    assert (done.rc, done.stdout, done.timed_out) == (0, "hello\n", False)
    missing = run_command([str(tmp_path / "no-such-program")])
    assert missing.rc == NOT_STARTED_RC
    slow = run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.3)
    assert slow.timed_out is True


# --- launch settings --------------------------------------------------------


def test_a_cpu_list_reads_ranges_and_single_cpus() -> None:
    assert parse_cpu_list("4-7") == frozenset({4, 5, 6, 7})
    assert parse_cpu_list("0,2,4") == frozenset({0, 2, 4})
    assert parse_cpu_list("1,3-4") == frozenset({1, 3, 4})


def test_a_cpu_range_that_runs_backwards_is_a_usage_error() -> None:
    with pytest.raises(Refusal) as caught:
        parse_cpu_list("7-4", side="new")
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


@pytest.mark.parametrize(
    "settings",
    [
        LaunchSettings(memory="8g"),
        LaunchSettings(mounts=("/a:/b",)),
        LaunchSettings(network="none"),
    ],
    ids=["memory", "mounts", "network"],
)
def test_memory_mounts_and_network_are_refused_on_a_host_side(settings: LaunchSettings) -> None:
    side = Side.command("new", ["work"])
    with pytest.raises(Refusal) as caught:
        refuse_host_settings(side, settings)
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
    assert "'new'" in caught.value.message


@pytest.mark.parametrize(
    "settings",
    [LaunchSettings(memory=""), LaunchSettings(network="")],
    ids=["memory", "network"],
)
def test_an_empty_memory_or_network_value_is_refused_on_a_host_side(
    settings: LaunchSettings,
) -> None:
    with pytest.raises(Refusal) as caught:
        refuse_host_settings(Side.command("new", ["work"]), settings)
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_perf_counters_change_nothing_on_a_host_side() -> None:
    refuse_host_settings(Side.command("new", ["work"]), LaunchSettings(perf_counters=True))


def test_gpus_beside_an_env_table_that_sets_the_device_variable_is_refused() -> None:
    settings = LaunchSettings(gpus="0", env={GPU_VARIABLE: "1"})
    with pytest.raises(Refusal) as caught:
        refuse_host_settings(Side.command("new", ["work"]), settings)
    assert caught.value.code == "E_USAGE"


def test_an_env_pass_variable_that_is_not_set_is_refused() -> None:
    settings = LaunchSettings(env_pass=("MADE_UP_PASSED",))
    with pytest.raises(Refusal) as caught:
        require_env_pass(Side.command("new", ["work"]), settings, {})
    assert caught.value.code == "E_USAGE"
    assert "MADE_UP_PASSED" in caught.value.message


def test_the_host_environment_drops_tool_variables_and_layers_the_settings() -> None:
    environ = {
        "PATH": "/made/up/bin",
        "PAIRBENCH_WORK_FACTOR": "2",
        "PAIRBENCH_ENV_PAD": "xxxx",
        "KEEP": "caller",
        "DROP": "caller",
        GPU_VARIABLE: "3",
    }
    settings = LaunchSettings(gpus="0,1", env={"KEEP": "settings", "OMP_NUM_THREADS": "4"})
    env = host_environment(environ, settings, remove=("DROP",), selection={"SELECTED": "yes"})
    assert env == {
        "PATH": "/made/up/bin",
        "KEEP": "settings",
        "OMP_NUM_THREADS": "4",
        "SELECTED": "yes",
        GPU_VARIABLE: "0,1",
        GPU_ORDER_VARIABLE: "PCI_BUS_ID",
    }


def test_gpus_all_removes_the_device_variable_so_every_device_is_visible() -> None:
    env = host_environment({GPU_VARIABLE: "3"}, LaunchSettings(gpus="all"))
    assert GPU_VARIABLE not in env
    assert GPU_ORDER_VARIABLE not in env


def test_a_gpu_index_counts_in_bus_order_whatever_the_caller_had() -> None:
    environ = {GPU_ORDER_VARIABLE: "FASTEST_FIRST"}
    env = host_environment(environ, LaunchSettings(gpus="1"))
    assert (env[GPU_VARIABLE], env[GPU_ORDER_VARIABLE]) == ("1", "PCI_BUS_ID")


def test_the_env_table_sets_the_device_order_over_the_default() -> None:
    settings = LaunchSettings(gpus="1", env={GPU_ORDER_VARIABLE: "FASTEST_FIRST"})
    env = host_environment({}, settings)
    assert env[GPU_ORDER_VARIABLE] == "FASTEST_FIRST"


@pytest.mark.parametrize("environ", [{}, {GPU_ORDER_VARIABLE: "FASTEST_FIRST"}])
def test_no_gpu_selection_leaves_the_device_order_as_the_caller_had_it(
    environ: dict[str, str],
) -> None:
    assert host_environment(environ, LaunchSettings()) == environ


def test_env_pass_forwards_a_tool_variable_that_is_named_outright() -> None:
    environ = {"PAIRBENCH_MADE_UP": "v"}
    env = host_environment(environ, LaunchSettings(env_pass=("PAIRBENCH_MADE_UP",)))
    assert env == {"PAIRBENCH_MADE_UP": "v"}


# --- a resolved host side ---------------------------------------------------


def _resolved(host: HostProcesses, settings: LaunchSettings | None = None) -> HostResolved:
    return HostResolved(
        side=Side.command("new", ["work", "--fast"]),
        settings=settings or LaunchSettings(),
        command=("work", "--fast"),
        executable="/made/up/bin/work",
        environment={"BASE": "1"},
        cwd=None,
        read_identity=lambda: {"executable_sha256": "0" * 64},
        host=host,
    )


def _request(tmp_path: Path, **extra: Any) -> api.LaunchRequest:
    return api.LaunchRequest(
        run_id="run-a",
        seq=1,
        phase="round",
        round=1,
        pos=1,
        name="new",
        artifacts=tmp_path,
        **extra,
    )


def test_a_host_side_runs_the_request_as_given_with_the_launch_environment(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host()
    side = _resolved(host, LaunchSettings(timeout_s=30.0))
    outcome = side.launch(
        _request(tmp_path, argv=("work", "--fast", "--out=x"), env={"PAIRBENCH_ENV_PAD": "xx"})
    )
    (run,) = host.runs
    assert run.argv == ("work", "--fast", "--out=x")
    assert run.executable == "/made/up/bin/work"
    assert run.env == {"BASE": "1", "PAIRBENCH_ENV_PAD": "xx"}
    assert run.stdout == tmp_path / "stdout.txt"
    assert run.stderr == tmp_path / "stderr.txt"
    assert outcome.rc == 0
    assert outcome.pid == 4001


def test_a_command_another_program_wraps_is_started_by_that_program(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host()
    _resolved(host).launch(_request(tmp_path, argv=("perf", "stat", "work", "--fast")))
    assert host.runs[0].executable is None


def test_a_launch_with_a_second_run_writes_each_run_into_its_own_folder(
    tmp_path: Path, recording_host: Any
) -> None:
    for name in api.RUN_FOLDERS:
        (tmp_path / name).mkdir()
    host = recording_host(durations_ns=(1, 1), rcs=(0, 0))
    side = _resolved(host)
    second = api.PreparedRun(argv=("work", "--fast", "--out=run2"), env={"B": "2"})
    side.launch(_request(tmp_path, argv=("work", "--fast", "--out=run1"), second=second))
    first_run, second_run = host.runs
    assert first_run.stdout == tmp_path / "run1" / "stdout.txt"
    assert second_run.stderr == tmp_path / "run2" / "stderr.txt"
    assert second_run.argv == ("work", "--fast", "--out=run2")
    assert second_run.env == {"BASE": "1", "B": "2"}


def test_a_host_side_sees_its_folders_and_tool_files_where_they_are(
    tmp_path: Path, recording_host: Any
) -> None:
    side = _resolved(recording_host())
    assert side.artifacts_in_side(tmp_path) == str(tmp_path)
    assert side.tool_file_in_side(tmp_path / "sampler.py") == str(tmp_path / "sampler.py")
    assert side.cannot_repeat is None
    assert side.engine is None
    assert side.rounds_available is None
    side.close()
    side.close()


def test_a_host_side_sees_a_relative_folder_and_tool_file_by_their_full_paths(
    tmp_path: Path, recording_host: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    side = _resolved(recording_host())
    assert side.artifacts_in_side(Path("runs/a")) == str(tmp_path / "runs" / "a")
    assert side.tool_file_in_side(Path("tools/sampler.py")) == str(
        tmp_path / "tools" / "sampler.py"
    )


def test_a_side_without_cpus_launches_where_the_tool_ran_when_it_was_resolved(
    tmp_path: Path, recording_host: Any
) -> None:
    host = recording_host(home_cpus=frozenset({0, 1, 2, 3}))
    side = _resolved(host)
    host.home_cpus = frozenset({0})
    assert side.launch(_request(tmp_path)).rc == 0
    assert host.pinned == frozenset({0, 1, 2, 3})


def test_a_side_with_its_own_cpus_launches_on_them(tmp_path: Path, recording_host: Any) -> None:
    host = recording_host(home_cpus=frozenset({0, 1, 2, 3}))
    assert _resolved(host, LaunchSettings(cpus="2-3")).launch(_request(tmp_path)).rc == 0
    assert host.pinned == frozenset({2, 3})


def test_a_side_whose_cpus_cannot_be_given_back_launches_where_the_tool_runs(
    tmp_path: Path, recording_host: Any
) -> None:
    home = frozenset({0, 1, 2, 3})
    host = recording_host(home_cpus=home, refused=home, durations_ns=(1, 1), rcs=(0, 0))
    side = _resolved(host)
    assert side.launch(_request(tmp_path)).rc == 0
    assert host.pinned is None
    assert host.log.count("spawn") == 1
    host.log.clear()
    assert side.launch(_request(tmp_path)).rc == 0
    assert host.log.count("pin") == 1


@pytest.mark.skipif(not pinning_supported(), reason="needs a platform that pins processes to CPUs")
def test_a_real_unpinned_side_runs_on_the_cpus_the_tool_had_before_it_moved(
    tmp_path: Path,
) -> None:
    before = os.sched_getaffinity(0)
    if len(before) < 2:
        pytest.skip("needs at least two CPUs this test may run on")
    command = (sys.executable, "-c", "import os; print(sorted(os.sched_getaffinity(0)))")
    side = HostResolved(
        side=Side.command("new", list(command)),
        settings=LaunchSettings(),
        command=command,
        executable=sys.executable,
        environment=dict(os.environ),
        cwd=None,
        read_identity=dict,
        host=HostProcesses(),
    )
    # The tool moves itself off another side's pinned CPU after the sides are resolved.
    os.sched_setaffinity(0, {max(before)})
    try:
        outcome = side.launch(_request(tmp_path, argv=command))
    finally:
        os.sched_setaffinity(0, before)
    assert outcome.rc == 0
    assert (tmp_path / "stdout.txt").read_text() == f"{sorted(before)}\n"


def test_a_real_host_process_seam_reads_the_cpus_the_tool_may_use() -> None:
    expected = frozenset(os.sched_getaffinity(0)) if pinning_supported() else None
    assert HostProcesses().home() == expected


def test_cpus_that_cannot_be_pinned_are_refused_at_the_launch(tmp_path: Path) -> None:
    class Unpinnable(HostProcesses):
        def pin(self, cpus: frozenset[int] | None) -> Any:
            raise OSError(22, "Invalid argument")

    side = _resolved(Unpinnable(), LaunchSettings(cpus="9999"))
    with pytest.raises(Refusal) as caught:
        side.launch(_request(tmp_path))
    # Pinning asked for where it cannot be done: exit 4, the machine was refused.
    assert (caught.value.code, caught.value.exit_code) == ("E_PIN_UNSUPPORTED", 4)
    assert "'new'" in caught.value.message


# What a process prints may hold the values of its command line: only its owner may read it.
PRIVATE_MODE = 0o600


@pytest.mark.parametrize("umask", [0o000, 0o022], ids=["umask-000", "umask-022"])
def test_a_process_s_output_files_are_readable_by_their_owner_only(
    tmp_path: Path, umask: int
) -> None:
    old = os.umask(umask)
    try:
        with HostProcesses().open_output(tmp_path / "stdout.txt") as out:
            out.write(b"made-up output\n")
    finally:
        os.umask(old)
    assert (tmp_path / "stdout.txt").stat().st_mode & 0o777 == PRIVATE_MODE
    assert (tmp_path / "stdout.txt").read_bytes() == b"made-up output\n"
