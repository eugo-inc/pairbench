# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``image`` side kind against stand-ins for docker and podman.

Every engine call goes to ``FakeEngine``; the timed launch goes to
``RecordingHost``. Nothing here starts a container.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Literal

import pytest

from pairbench import api
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.model import LaunchSettings, Side
from pairbench.sides import container
from pairbench.sides.base import Completed, HostRun, ProcessUsage, run_command
from pairbench.sides.container import (
    EngineFacts,
    ImageKind,
    engine_is_local,
    gpu_options,
    image_identity,
    parse_engine_time,
    two_run_script,
)

# Made-up image facts.
REF = "registry.example/tool:1"
IMAGE_ID = "sha256:" + "0123456789abcdef" * 4
DIGEST = "fedcba9876543210" * 4
DETAILS: dict[str, Any] = {
    "Id": IMAGE_ID,
    "RepoDigests": [f"registry.example/tool@sha256:{DIGEST}"],
    "Os": "linux",
    "Architecture": "arm64",
    "Variant": "v8",
    "Config": {"Entrypoint": None, "Cmd": ["sh"]},
}
# A start and finish 2.25 s apart, and the clock of RecordingHost moving 3 s.
STARTED = "2031-01-02T03:04:05.100000000Z"
FINISHED = "2031-01-02T03:04:07.350000000Z"
STATE: dict[str, Any] = {"ExitCode": 0, "StartedAt": STARTED, "FinishedAt": FINISHED}
NAME = "pairbench-run-a-0003-new"
DOCKER = "/usr/bin/docker"
PODMAN = "/usr/bin/podman"
# SHA-256 of the text "v1\n".
V1_SHA256 = "2d27fbdf4e8ca207afbfa388ca9172fbcc6c70e534af2476b3b704f87debadcf"


class FakeEngine:
    """Answers the calls of one engine's command as docker or podman would."""

    def __init__(
        self,
        *,
        images: Mapping[str, dict[str, Any]] | None = None,
        info: Mapping[str, Any] | None = None,
        shell: bool = True,
        state: Mapping[str, Any] | None = None,
        pull_rc: int = 0,
        identify_out: str = "v1\n",
        leftovers: tuple[str, ...] = (),
        pid: str = "4321",
        rm_rc: int = 0,
        rm_hangs: bool = False,
        writable: bool = True,
        shown: bool = True,
        chown_rc: int = 0,
        on_chown: Callable[[], None] | None = None,
    ) -> None:
        self.images = dict(images if images is not None else {REF: DETAILS})
        self.info = dict(info or {})
        self.shell = shell
        self.state = dict(state if state is not None else STATE)
        self.pull_rc = pull_rc
        self.identify_out = identify_out
        self.leftovers = leftovers
        self.pid = pid
        self.rm_rc = rm_rc
        self.rm_hangs = rm_hangs
        # Whether the image's user may write the files the host creates in the mount.
        self.writable = writable
        # Whether a container sees the folder mounted into it; an engine that cannot
        # reach the folder shows an empty one in its place.
        self.shown = shown
        self.mounted: list[dict[str, bool]] = []
        self.chown_rc = chown_rc
        self.on_chown = on_chown

    def __call__(self, argv: tuple[str, ...]) -> Completed:
        verb, rest = argv[1], argv[2:]
        if verb == "version":
            return Completed(0, "9.9.9\n")
        if verb == "info":
            return Completed(0, json.dumps(self.info))
        if verb == "image":
            ref = rest[-1]
            for key, details in self.images.items():
                if ref in (key, details["Id"]):
                    return Completed(0, json.dumps(details))
            return Completed(1, "", f"Error: No such image: {ref}")
        if verb == "pull":
            if self.pull_rc == 0:
                self.images[rest[-1]] = DETAILS
            return Completed(self.pull_rc, "", "" if self.pull_rc == 0 else "denied")
        if verb == "run":
            entry = rest[rest.index("--entrypoint") + 1]
            if entry == "/bin/sh":
                if not self.shell:
                    return Completed(127, "", "not found")
                files = _files_in_mount(rest)
                if not self.shown:
                    files = dict.fromkeys(files, False)
                self.mounted.append(files)
                if "test -d" in rest[-1] and not all(files.values()):
                    return Completed(4)
                if not self.writable:
                    return Completed(3, "", "sh: 1: cannot create: Permission denied")
                return Completed(0)
            if entry == "chown":
                if self.chown_rc == 0 and self.on_chown is not None:
                    self.on_chown()
                return Completed(self.chown_rc, "", "" if self.chown_rc == 0 else "no chown")
            return Completed(0, self.identify_out)
        if verb == "inspect":
            if "{{json .State}}" in rest:
                return Completed(0, json.dumps(self.state))
            return Completed(0, self.pid + "\n")
        if verb == "rm":
            if self.rm_hangs:
                # What the runner gives back for a command it stopped at its timeout.
                return Completed(-9, "", "", timed_out=True)
            return Completed(self.rm_rc, "", "" if self.rm_rc == 0 else "removal in progress")
        if verb == "kill":
            return Completed(0)
        if verb == "ps":
            return Completed(0, "".join(name + "\n" for name in self.leftovers))
        raise AssertionError(f"unexpected engine call: {argv}")


def _files_in_mount(rest: tuple[str, ...]) -> dict[str, bool]:
    """Say, for each file the mounted folder holds while the container runs, whether it exists."""
    volume = next(
        rest[i + 1]
        for i, word in enumerate(rest)
        if word == "--volume" and rest[i + 1].endswith(":/pairbench/artifacts")
    )
    host = Path(volume.rsplit(":", 1)[0])
    return {
        f"{run}/{name}": (host / run / name).is_file()
        for run in ("run1", "run2")
        for name in ("stdout.txt", "stderr.txt")
    }


def _which(*found: str) -> Callable[..., str | None]:
    def which(word: str, path: str | None = None) -> str | None:
        return f"/usr/bin/{word}" if word in found else None

    return which


Build = Callable[..., tuple[ImageKind, Any, Any]]


@pytest.fixture
def make(fake_runner: Any, recording_host: Any) -> Build:
    def build(
        engine: FakeEngine | None = None, *, found: tuple[str, ...] = ("docker",), host: Any = None
    ) -> tuple[ImageKind, Any, Any]:
        runner = fake_runner(engine or FakeEngine())
        host = host if host is not None else recording_host()
        kind = ImageKind(runner=runner, host=host, which=_which(*found), environ={})
        return kind, runner, host

    return build


def _ctx(settings: LaunchSettings | None = None, **extra: Any) -> api.SideContext:
    environ = {"PATH": "/usr/bin", **extra.pop("environ", {})}
    return api.SideContext(
        run_id="run-a", settings=settings or LaunchSettings(), environ=environ, **extra
    )


def _request(tmp_path: Path, **extra: Any) -> api.LaunchRequest:
    fields: dict[str, Any] = {
        "run_id": "run-a",
        "seq": 3,
        "phase": "round",
        "round": 1,
        "pos": 1,
        "name": "new",
        "artifacts": tmp_path,
    }
    fields.update(extra)
    return api.LaunchRequest(**fields)


SIDE = Side.image("new", REF)


def _verbs(runner: Any) -> list[str]:
    return [argv[1] for argv in runner.argvs()]


# --- identity, look-up and the pull policy ---------------------------------


def test_the_identity_is_the_image_id_the_digest_hashes_and_the_platform(make: Build) -> None:
    kind, _runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx())
    assert dict(resolved.side.identity) == {
        "image_id": IMAGE_ID,
        "digests": (f"sha256:{DIGEST}",),
        "platform": "linux/arm64/v8",
    }
    assert resolved.side.public_identity()["image_id"] == IMAGE_ID
    assert resolved.engine is not None
    assert (resolved.engine.name, resolved.engine.version) == ("docker", "9.9.9")


def test_the_look_up_only_inspects_and_matches_resolve(make: Build) -> None:
    kind, runner, _host = make()
    found = kind.look_up(SIDE, _ctx())
    assert set(_verbs(runner)) == {"version", "info", "image"}
    resolved = kind.resolve(SIDE, _ctx())
    assert found.status == "identified"
    assert found.identity == resolved.side.identity
    assert found.fingerprint == resolved.side.fingerprint != ""


def test_the_look_up_reports_an_absent_image_without_pulling(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(images={}))
    found = kind.look_up(SIDE, _ctx())
    assert (found.status, dict(found.identity), found.fingerprint) == ("absent", {}, "")
    assert "pull" not in _verbs(runner)


def test_the_look_up_refuses_an_absent_image_under_pull_never(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(images={}))
    with pytest.raises(Refusal) as caught:
        kind.look_up(SIDE, _ctx(LaunchSettings(pull="never")))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert "pull" not in _verbs(runner)


def test_the_look_up_without_an_engine_is_unchecked_and_never_a_refusal(make: Build) -> None:
    kind, runner, _host = make(found=())
    found = kind.look_up(SIDE, _ctx())
    assert found.status == "unchecked"
    assert runner.argvs() == []


def test_the_look_up_names_the_pull_under_pull_always(make: Build) -> None:
    kind, runner, _host = make()
    found = kind.look_up(SIDE, _ctx(LaunchSettings(pull="always")))
    assert found.status == "identified"
    assert "always" in found.message
    assert "pull" not in _verbs(runner)


def test_resolve_pulls_a_missing_image_under_pull_missing(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(images={}))
    resolved = kind.resolve(SIDE, _ctx())
    assert (DOCKER, "pull", REF) in runner.argvs()
    assert resolved.side.identity["image_id"] == IMAGE_ID


def test_resolve_does_not_pull_a_present_image_under_pull_missing(make: Build) -> None:
    kind, runner, _host = make()
    kind.resolve(SIDE, _ctx())
    assert "pull" not in _verbs(runner)


def test_resolve_pulls_again_under_pull_always(make: Build) -> None:
    kind, runner, _host = make()
    kind.resolve(SIDE, _ctx(LaunchSettings(pull="always")))
    assert _verbs(runner).count("pull") == 1


def test_resolve_refuses_an_absent_image_under_pull_never(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(images={}))
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx(LaunchSettings(pull="never")))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
    assert "pull" not in _verbs(runner)


def test_a_failed_pull_is_refused(make: Build) -> None:
    kind, _runner, _host = make(FakeEngine(images={}, pull_rc=1))
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)


# How long a question to the engine may take before it counts as not answered.
ENGINE_QUERY_WAIT_S = 60.0
QUERY_VERBS = ("version", "info", "image", "ps")


class SlowImageQueries(FakeEngine):
    """An engine that answers everything but the details of an image, which run out of time."""

    def __call__(self, argv: tuple[str, ...]) -> Completed:
        if argv[1] == "image":
            return Completed(-9, "", "", timed_out=True)
        return super().__call__(argv)


def test_every_question_to_the_engine_has_a_time_limit(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(leftovers=("pairbench-old-0001-a",)))
    kind.look_up(SIDE, _ctx())
    kind.resolve(SIDE, _ctx()).identify()
    kind.doctor()
    asked = [call for call in runner.calls if call.argv[1] in QUERY_VERBS]
    assert {call.argv[1] for call in asked} == set(QUERY_VERBS)
    assert [call.timeout_s for call in asked] == [ENGINE_QUERY_WAIT_S] * len(asked)


@pytest.mark.parametrize("pull", ["missing", "never"])
def test_an_image_question_that_runs_out_of_time_is_refused_and_never_pulls(
    make: Build, pull: str
) -> None:
    kind, runner, _host = make(SlowImageQueries())
    for call in (kind.look_up, kind.resolve):
        with pytest.raises(Refusal) as caught:
            call(SIDE, _ctx(LaunchSettings(pull=pull)))
        assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
        assert caught.value.message == (
            "side 'new': the container engine did not answer within 60 s when asked about "
            f"the image {REF}"
        )
    assert "pull" not in _verbs(runner)


def test_a_launch_never_pulls_and_starts_by_image_id(make: Build, tmp_path: Path) -> None:
    kind, runner, host = make()
    resolved = kind.resolve(SIDE, _ctx())
    before = len(runner.calls)
    resolved.launch(_request(tmp_path))
    assert "pull" not in [argv[1] for argv in runner.argvs()[before:]]
    argv = host.runs[0].argv
    assert argv[argv.index("--pull") + 1] == "never"
    assert IMAGE_ID in argv
    assert REF not in argv


# --- engines ----------------------------------------------------------------


def test_a_named_engine_that_is_not_found_is_refused(make: Build) -> None:
    kind, _runner, _host = make(found=("docker",))
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx(LaunchSettings(engine="podman")))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)


def test_no_engine_at_all_is_refused_by_resolve(make: Build) -> None:
    kind, _runner, _host = make(found=())
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)


def test_auto_takes_the_engine_the_variable_names_when_both_are_found(make: Build) -> None:
    kind, _runner, _host = make(found=("docker", "podman"))
    ctx = _ctx(environ={api.ENGINE_VARIABLE: "podman"})
    resolved = kind.resolve(SIDE, ctx)
    assert resolved.engine is not None
    assert resolved.engine.name == "podman"


def test_auto_takes_docker_when_both_are_found_and_none_is_named(make: Build) -> None:
    kind, _runner, _host = make(found=("docker", "podman"))
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.engine is not None
    assert resolved.engine.name == "docker"


def test_gpu_options_follow_each_engine() -> None:
    assert gpu_options("docker", "all") == ["--gpus", "all"]
    assert gpu_options("docker", "0,2") == ["--gpus", '"device=0,2"']
    assert gpu_options("podman", "all") == ["--device", "nvidia.com/gpu=all"]
    assert gpu_options("podman", "0,2") == [
        "--device",
        "nvidia.com/gpu=0",
        "--device",
        "nvidia.com/gpu=2",
    ]


def test_a_podman_launch_uses_the_podman_device_names(make: Build, tmp_path: Path) -> None:
    kind, _runner, host = make(found=("podman",))
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(gpus="1")))
    resolved.launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv[0] == PODMAN
    assert argv[argv.index("--device") + 1] == "nvidia.com/gpu=1"
    assert "--gpus" not in argv


def test_rootless_docker_without_the_cpuset_controller_refuses_cpus(make: Build) -> None:
    info = {"SecurityOptions": ["name=seccomp", "name=rootless"], "CPUSet": False}
    kind, _runner, _host = make(FakeEngine(info=info))
    for call in (kind.look_up, kind.resolve):
        with pytest.raises(Refusal) as caught:
            call(SIDE, _ctx(LaunchSettings(cpus="0-1")))
        assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
        assert "rootless" in caught.value.message


def test_rootless_podman_on_cgroups_v1_refuses_memory(make: Build) -> None:
    info = {"host": {"security": {"rootless": True}, "cgroupVersion": "v1"}}
    kind, _runner, _host = make(FakeEngine(info=info), found=("podman",))
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx(LaunchSettings(memory="1g")))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_rootless_podman_with_delegated_controllers_pins_and_limits(
    make: Build, tmp_path: Path
) -> None:
    info = {
        "host": {
            "security": {"rootless": True},
            "cgroupVersion": "v2",
            "cgroupControllers": ["cpuset", "cpu", "memory", "pids"],
        }
    }
    kind, _runner, host = make(FakeEngine(info=info), found=("podman",))
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(cpus="2", memory="1g")))
    resolved.launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv[argv.index("--cpuset-cpus") + 1] == "2"


def test_a_memory_limit_that_is_no_size_is_a_usage_error(make: Build) -> None:
    kind, _runner, _host = make()
    with pytest.raises(Refusal) as caught:
        kind.look_up(SIDE, _ctx(LaunchSettings(memory="lots")))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


def test_an_engine_elsewhere_is_not_local() -> None:
    assert engine_is_local("docker", {}, system="Linux") is True
    assert engine_is_local("docker", {"DOCKER_HOST": "unix:///run/x.sock"}, system="Linux")
    assert engine_is_local("docker", {"DOCKER_HOST": "tcp://h.example:1"}, system="Linux") is False
    assert engine_is_local("podman", {"CONTAINER_HOST": "ssh://h.example"}, system="Linux") is False
    assert engine_is_local("docker", {}, system="Darwin") is False


# --- one launch -------------------------------------------------------------


def test_a_launch_is_named_labelled_mounted_and_removed(make: Build, tmp_path: Path) -> None:
    kind, runner, host = make()
    resolved = kind.resolve(SIDE, _ctx())
    resolved.launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv[:2] == (DOCKER, "run")
    assert argv[argv.index("--name") + 1] == NAME
    assert argv[argv.index("--label") + 1] == "pairbench.run=run-a"
    assert argv[argv.index("--volume") + 1] == f"{tmp_path}:/pairbench/artifacts"
    assert "--rm" not in argv
    assert "--privileged" not in argv
    assert host.runs[0].stdout == tmp_path / "stdout.txt"
    assert host.runs[0].stderr == tmp_path / "stderr.txt"
    assert runner.argvs()[-2:] == [
        (DOCKER, "inspect", "--format", "{{json .State}}", NAME),
        (DOCKER, "rm", "--force", NAME),
    ]


def test_run_s_comes_from_the_engine_and_launch_s_from_the_host(
    make: Build, tmp_path: Path
) -> None:
    kind, _runner, _host = make()
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.timing == {"run_s": 2.25, "launch_s": 3.0}
    assert outcome.rc == 0
    assert outcome.timed_out is False


def test_the_exit_code_is_the_container_s(make: Build, tmp_path: Path, recording_host: Any) -> None:
    state = {**STATE, "ExitCode": 3}
    kind, _runner, _host = make(FakeEngine(state=state), host=recording_host(rcs=(3,)))
    assert kind.resolve(SIDE, _ctx()).launch(_request(tmp_path)).rc == 3


def test_a_container_that_never_started_reports_the_engine_s_exit_code(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    state = {"ExitCode": 0, "StartedAt": "0001-01-01T00:00:00Z", "FinishedAt": FINISHED}
    kind, _runner, _host = make(FakeEngine(state=state), host=recording_host(rcs=(125,)))
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.rc == 125
    assert outcome.timing == {"launch_s": 3.0}


def test_a_finish_before_the_start_gives_no_run_time_and_the_engine_s_exit_code(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    state = {"ExitCode": 0, "StartedAt": FINISHED, "FinishedAt": STARTED}
    kind, _runner, _host = make(FakeEngine(state=state), host=recording_host(rcs=(125,)))
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.rc == 125
    assert outcome.timing == {"launch_s": 3.0}


def test_a_state_time_that_is_no_real_date_gives_no_run_time(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    state = {"ExitCode": 0, "StartedAt": STARTED, "FinishedAt": "2031-13-02T03:04:07Z"}
    kind, _runner, _host = make(FakeEngine(state=state), host=recording_host(rcs=(125,)))
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.rc == 125
    assert outcome.timing == {"launch_s": 3.0}


def test_a_relative_folder_and_tool_file_are_mounted_by_their_full_paths(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    folder = Path("artifacts") / "0003-new"
    folder.mkdir(parents=True)
    kind, _runner, host = make()
    resolved = kind.resolve(SIDE, _ctx())
    resolved.launch(
        _request(tmp_path, artifacts=folder, tool_files=(Path("tools") / "sampler.py",))
    )
    argv = host.runs[0].argv
    volumes = [value for flag, value in itertools.pairwise(argv) if flag == "--volume"]
    assert volumes == [
        f"{tmp_path / 'artifacts' / '0003-new'}:/pairbench/artifacts",
        f"{tmp_path / 'tools' / 'sampler.py'}:/pairbench/tools/sampler.py:ro",
    ]


def test_an_image_launch_reports_no_figure_its_engine_does_not_give(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    usage = ProcessUsage(user_s=0.5, sys_s=0.25, figures={"rss_peak_bytes": 1024.0})
    kind, _runner, _host = make(host=recording_host(usages=(usage,)))
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.cpu_s is None
    assert dict(outcome.usage) == {}
    assert "user_s" not in outcome.timing
    assert "sys_s" not in outcome.timing
    assert outcome.second_pid is None


def test_the_container_is_removed_after_an_interrupt(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    kind, runner, host = make(host=recording_host(interrupt_on_reap=True))
    resolved = kind.resolve(SIDE, _ctx())
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(tmp_path))
    calls = runner.argvs()
    assert (DOCKER, "kill", NAME) in calls
    assert calls[-1] == (DOCKER, "rm", "--force", NAME)
    assert calls.index((DOCKER, "kill", NAME)) < len(calls) - 1
    assert host.killed[0] == 4001


def test_a_timeout_stops_the_container_and_is_reported(
    make: Build, tmp_path: Path, recording_host: Any
) -> None:
    class Blocking(recording_host):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.gone = threading.Event()

        def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
            self.log.append("reap")
            self.gone.wait(10.0)
            return -9, None

        def kill(self, pid: int) -> None:
            super().kill(pid)
            self.gone.set()

    state = {**STATE, "ExitCode": 137}
    kind, runner, _host = make(FakeEngine(state=state), host=Blocking())
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(timeout_s=0.05)))
    outcome = resolved.launch(_request(tmp_path))
    assert outcome.timed_out is True
    assert outcome.rc == 137
    assert (DOCKER, "kill", NAME) in runner.argvs()
    assert runner.argvs()[-1] == (DOCKER, "rm", "--force", NAME)


def test_limits_and_capabilities_are_set_exactly_as_asked(make: Build, tmp_path: Path) -> None:
    settings = LaunchSettings(cpus="4-7", memory="2g", network="none", workdir="/w")
    kind, _runner, host = make()
    kind.resolve(SIDE, _ctx(settings)).launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv[argv.index("--cpuset-cpus") + 1] == "4-7"
    assert argv[argv.index("--memory") + 1] == "2g"
    assert argv[argv.index("--memory-swap") + 1] == "2g"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--workdir") + 1] == "/w"
    assert "--cap-add" not in argv
    assert "--gpus" not in argv


def test_perf_counters_add_the_one_capability_and_no_other(make: Build, tmp_path: Path) -> None:
    kind, _runner, host = make()
    kind.resolve(SIDE, _ctx(LaunchSettings(perf_counters=True))).launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv.count("--cap-add") == 1
    assert argv[argv.index("--cap-add") + 1] == "PERFMON"
    assert "--privileged" not in argv
    assert "--security-opt" not in argv


def test_the_command_is_the_side_s_args_else_the_workload_else_none(make: Build) -> None:
    kind, _runner, _host = make()
    own = Side.image("new", REF)
    own_spec = {**own.spec, "args": ("--fast",)}
    with_args = Side(name="new", kind="image", spec=own_spec)
    assert kind.resolve(with_args, _ctx(workload=("w",))).command == ("--fast",)
    assert kind.resolve(SIDE, _ctx(workload=("w", "x"))).command == ("w", "x")
    assert kind.resolve(SIDE, _ctx()).command is None


def test_the_prepared_command_follows_the_image_id(make: Build, tmp_path: Path) -> None:
    kind, _runner, host = make()
    resolved = kind.resolve(SIDE, _ctx(workload=("w", "x")))
    resolved.launch(_request(tmp_path, argv=("w", "x", "--out", "/pairbench/artifacts/r")))
    argv = host.runs[0].argv
    assert argv[argv.index(IMAGE_ID) :] == (IMAGE_ID, "w", "x", "--out", "/pairbench/artifacts/r")


def test_the_artifact_and_tool_paths_inside_the_container(make: Build, tmp_path: Path) -> None:
    kind, _runner, host = make()
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.artifacts_in_side(tmp_path) == "/pairbench/artifacts"
    tool = tmp_path / "tools" / "sampler.py"
    assert resolved.tool_file_in_side(tool) == "/pairbench/tools/sampler.py"
    resolved.launch(_request(tmp_path, tool_files=(tool,)))
    argv = host.runs[0].argv
    assert f"{tool}:/pairbench/tools/sampler.py:ro" in argv


def test_an_explain_launch_on_an_image_with_an_entrypoint_is_refused(
    make: Build, tmp_path: Path
) -> None:
    details = {**DETAILS, "Config": {"Entrypoint": ["/entry"], "Cmd": None}}
    kind, _runner, host = make(FakeEngine(images={REF: details}))
    resolved = kind.resolve(SIDE, _ctx())
    with pytest.raises(Refusal) as caught:
        resolved.launch(_request(tmp_path, phase="explain", argv=("perf", "record", "--", "x")))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
    assert host.runs == []


def _wrap_with(seen: list[tuple[str, ...]]) -> Any:
    def wrap(whole: Sequence[str]) -> api.InstrumentedCommand:
        seen.append(tuple(whole))
        return api.InstrumentedCommand(
            argv=("made-up-perf", "record", "--", *whole), env={"MADE_UP_WRAP": "1"}
        )

    return wrap


@pytest.mark.parametrize("phase", ["explain", "profile"])
def test_an_instrument_goes_in_front_of_the_entrypoint_and_the_command(
    make: Build, tmp_path: Path, phase: str
) -> None:
    details = {**DETAILS, "Config": {"Entrypoint": ["/entry", "-q"], "Cmd": ["default"]}}
    kind, _runner, host = make(FakeEngine(images={REF: details}))
    resolved = kind.resolve(SIDE, _ctx())
    seen: list[tuple[str, ...]] = []
    request = _request(tmp_path, phase=phase, argv=("w", "x"), wrap_server=_wrap_with(seen))
    outcome = resolved.launch(request)
    assert outcome.rc == 0
    assert seen == [("/entry", "-q", "w", "x")]
    argv = host.runs[0].argv
    assert argv[argv.index("--entrypoint") :] == (
        "--entrypoint",
        "made-up-perf",
        IMAGE_ID,
        "record",
        "--",
        "/entry",
        "-q",
        "w",
        "x",
    )
    assert "MADE_UP_WRAP" in argv


def test_an_instrument_goes_in_front_of_the_image_s_default_command(
    make: Build, tmp_path: Path
) -> None:
    details = {**DETAILS, "Config": {"Entrypoint": ["/entry"], "Cmd": ["serve", "--fast"]}}
    kind, _runner, host = make(FakeEngine(images={REF: details}))
    resolved = kind.resolve(SIDE, _ctx())
    seen: list[tuple[str, ...]] = []
    resolved.launch(_request(tmp_path, phase="profile", argv=None, wrap_server=_wrap_with(seen)))
    assert seen == [("/entry", "serve", "--fast")]
    argv = host.runs[0].argv
    assert argv[argv.index(IMAGE_ID) :] == (IMAGE_ID, "record", "--", "/entry", "serve", "--fast")


def test_an_image_that_names_no_command_has_nothing_to_put_an_instrument_in_front_of(
    make: Build, tmp_path: Path
) -> None:
    details = {**DETAILS, "Config": {"Entrypoint": None, "Cmd": None}}
    kind, _runner, host = make(FakeEngine(images={REF: details}))
    resolved = kind.resolve(SIDE, _ctx())
    with pytest.raises(Refusal) as caught:
        resolved.launch(_request(tmp_path, phase="explain", argv=None, wrap_server=_wrap_with([])))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
    assert caught.value.message == (
        "side 'new': its image names no command to put an instrument in front of"
    )
    assert host.runs == []


def test_a_container_that_cannot_be_removed_gives_a_loud_note(make: Build, tmp_path: Path) -> None:
    notes: list[tuple[str, str]] = []
    kind, _runner, _host = make(FakeEngine(rm_rc=1))
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    outcome = resolved.launch(_request(tmp_path))
    assert outcome.rc == 0
    assert outcome.timing == {"run_s": 2.25, "launch_s": 3.0}
    assert [code for code, _message in notes] == ["container_not_removed"]
    assert "doctor" in notes[0][1]


# --- handing files back to the calling user --------------------------------


class Owner:
    """Whose the files the test writes are, as the image side sees them.

    The test cannot give files to another user, so the side's look for files
    of another user sees every file as another user's until the made-up
    ``chown`` has run.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.caller = os.getuid()
        self.done = False
        look = container.foreign_entries

        def foreign(folder: Path, uid: int) -> list[Path]:
            assert uid == self.caller
            return [] if self.done else look(folder, uid + 1)

        monkeypatch.setattr(container, "foreign_entries", foreign)

    def handed_back(self) -> None:
        self.done = True


def _chowns(runner: Any) -> list[tuple[str, ...]]:
    return [
        argv
        for argv in runner.argvs()
        if argv[1] == "run" and "chown" in argv[: argv.index(IMAGE_ID)]
    ]


# The note on files a container left with another user, before why they stay with it.
KEPT = (
    "files a container of side new wrote in {where} of the run folder still belong to the "
    "user its image runs as, so other users may be able to read them and you may not be able "
    "to delete them: {reason}"
)
# The end of the note when a launch that ends as it should names the files of its side.
ONCE = "; later launches of the side are not named again"
CHOWN_NAME = f"{NAME}-chown"
CHOWN_REMOVED = (DOCKER, "rm", "--force", CHOWN_NAME)


def _launch_folder(tmp_path: Path, seq: int = 3) -> Path:
    """A launch folder where a run folder keeps it, holding one file of the launch."""
    folder = tmp_path / "artifacts" / f"{seq:04d}-new"
    folder.mkdir(parents=True)
    (folder / "export.txt").write_text("a made-up export\n", encoding="utf-8")
    return folder


def test_files_a_container_left_to_another_user_are_handed_back(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = Owner(monkeypatch)
    (tmp_path / "out.json").write_text("{}\n")
    notes: list[tuple[str, str]] = []
    kind, runner, _host = make(FakeEngine(on_chown=owner.handed_back))
    settings = LaunchSettings(memory="2g", cpus="2-3")
    resolved = kind.resolve(
        SIDE, _ctx(settings, note=lambda code, message: notes.append((code, message)))
    )
    resolved.launch(_request(tmp_path))
    chowns = _chowns(runner)
    assert len(chowns) == 1
    chown = chowns[0]
    name = chown[chown.index("--name") + 1]
    assert name == "pairbench-run-a-0003-new-chown"
    assert chown[chown.index("--user") + 1] == "0:0"
    assert chown[chown.index("--network") + 1] == "none"
    assert chown[chown.index("--memory") + 1] == "2g"
    assert chown[chown.index("--cpuset-cpus") + 1] == "2-3"
    assert chown[chown.index("--volume") + 1] == f"{tmp_path}:/pairbench/artifacts"
    assert chown[chown.index("--entrypoint") :] == (
        "--entrypoint",
        "chown",
        IMAGE_ID,
        "-R",
        "-h",
        f"{owner.caller}:{tmp_path.stat().st_gid}",
        "/pairbench/artifacts",
    )
    assert (DOCKER, "rm", "--force", name) in runner.argvs()
    assert notes == []


# What a short container of a side whose launches have 2g of memory and CPUs 2-3
# is given between the folder it mounts and its entry point: no swap beyond the
# memory, as a launch of the side has.
SHORT_LIMITS = ("--memory", "2g", "--memory-swap", "2g", "--cpuset-cpus", "2-3")


def test_the_repeat_check_and_the_hand_back_have_the_memory_and_no_swap_of_a_launch(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = Owner(monkeypatch)
    (tmp_path / "out.json").write_text("{}\n")
    kind, runner, _host = make(FakeEngine(on_chown=owner.handed_back))
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(memory="2g", cpus="2-3")))
    assert resolved.cannot_repeat is None
    resolved.launch(_request(tmp_path))
    probe = next(argv for argv in runner.argvs() if argv[1] == "run" and "/bin/sh" in argv)
    assert probe[: probe.index("--volume")] == (
        DOCKER,
        "run",
        "--rm",
        "--name",
        "pairbench-run-a-0000-new-shell",
        "--label",
        "pairbench.run=run-a",
        "--pull",
        "never",
        "--network",
        "none",
    )
    assert probe[probe.index("--volume") + 2 : probe.index("--entrypoint")] == SHORT_LIMITS
    (chown,) = _chowns(runner)
    assert chown[: chown.index("--entrypoint")] == (
        DOCKER,
        "run",
        "--rm",
        "--name",
        "pairbench-run-a-0003-new-chown",
        "--label",
        "pairbench.run=run-a",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        "0:0",
        "--volume",
        f"{tmp_path}:/pairbench/artifacts",
        *SHORT_LIMITS,
    )


def test_a_launch_that_leaves_only_the_caller_s_files_starts_no_second_container(
    make: Build, tmp_path: Path
) -> None:
    (tmp_path / "out.json").write_text("{}\n")
    kind, runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx())
    resolved.launch(_request(tmp_path))
    assert _chowns(runner) == []


def test_files_that_cannot_be_handed_back_give_one_note_naming_the_folder(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    Owner(monkeypatch)
    notes: list[tuple[str, str]] = []
    host = recording_host(durations_ns=(3_000_000_000,) * 2, rcs=(0, 0))
    kind, runner, _host = make(FakeEngine(chown_rc=127), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    for seq in (3, 4):
        folder = tmp_path / "artifacts" / f"000{seq}-new"
        folder.mkdir(parents=True)
        (folder / "out.json").write_text("{}\n")
        resolved.launch(_request(folder, seq=seq))
    assert len(_chowns(runner)) == 2
    assert notes == [
        (
            "files_not_handed_back",
            KEPT.format(where="artifacts/0003-new", reason="the image holds no chown") + ONCE,
        )
    ]


def test_files_chown_did_not_hand_back_are_named(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Owner(monkeypatch)
    (tmp_path / "out.json").write_text("{}\n")
    notes: list[tuple[str, str]] = []
    kind, _runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    resolved.launch(_request(tmp_path))
    assert [code for code, _message in notes] == ["files_not_handed_back"]
    assert "chown in the image left some of them with another user" in notes[0][1]


def test_a_rootless_engine_starts_no_chown_and_names_the_folder(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Owner(monkeypatch)
    folder = tmp_path / "artifacts" / "0003-new"
    folder.mkdir(parents=True)
    (folder / "out.json").write_text("{}\n")
    notes: list[tuple[str, str]] = []
    engine = FakeEngine(info={"SecurityOptions": ["name=seccomp", "name=rootless"]})
    kind, runner, _host = make(engine)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    resolved.launch(_request(folder))
    assert _chowns(runner) == []
    assert [code for code, _message in notes] == ["files_not_handed_back"]
    assert "the engine runs rootless" in notes[0][1]


def test_files_on_a_remote_engine_are_left_as_they_are(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Owner(monkeypatch)
    (tmp_path / "out.json").write_text("{}\n")
    notes: list[tuple[str, str]] = []
    kind, runner, _host = make()
    context = _ctx(
        environ={"DOCKER_HOST": "ssh://made-up.invalid"},
        note=lambda code, message: notes.append((code, message)),
    )
    resolved = kind.resolve(SIDE, context)
    resolved.launch(_request(tmp_path))
    assert _chowns(runner) == []
    assert notes == []


def test_an_interrupted_launch_hands_its_files_back_after_removing_its_container(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    owner = Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    notes: list[tuple[str, str]] = []
    host = recording_host(interrupt_on_reap=True)
    kind, runner, _host = make(FakeEngine(on_chown=owner.handed_back), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(folder))
    calls = runner.argvs()
    chowns = _chowns(runner)
    assert len(chowns) == 1
    assert calls.index((DOCKER, "rm", "--force", NAME)) < calls.index(chowns[0])
    assert calls[-1] == CHOWN_REMOVED
    assert owner.done is True
    assert notes == []


def test_a_launch_that_stops_on_an_error_hands_its_files_back(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    class Broken(recording_host):  # type: ignore[misc]
        def reap(self, pid: int) -> tuple[int, ProcessUsage | None]:
            raise RuntimeError("a made-up failure")

    owner = Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    kind, runner, _host = make(FakeEngine(on_chown=owner.handed_back), host=Broken())
    resolved = kind.resolve(SIDE, _ctx())
    with pytest.raises(RuntimeError, match=r"^a made-up failure$"):
        resolved.launch(_request(folder))
    assert len(_chowns(runner)) == 1
    assert owner.done is True


def test_an_interrupted_launch_whose_files_stay_with_another_user_names_its_folder(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    notes: list[tuple[str, str]] = []
    host = recording_host(interrupt_on_reap=True)
    kind, _runner, _host = make(FakeEngine(chown_rc=1), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(folder))
    assert notes == [
        (
            "files_not_handed_back",
            KEPT.format(where="artifacts/0003-new", reason="chown in the image exited with 1"),
        )
    ]


def test_an_interrupted_launch_is_named_after_its_side_was_named_once(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    Owner(monkeypatch)
    notes: list[tuple[str, str]] = []
    host = recording_host(durations_ns=(3_000_000_000,) * 2, rcs=(0, 0))
    kind, _runner, _host = make(FakeEngine(chown_rc=1), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    resolved.launch(_request(_launch_folder(tmp_path, 3), seq=3))
    host.interrupt_on_reap = True
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(_launch_folder(tmp_path, 4), seq=4))
    reason = "chown in the image exited with 1"
    assert notes == [
        ("files_not_handed_back", KEPT.format(where="artifacts/0003-new", reason=reason) + ONCE),
        ("files_not_handed_back", KEPT.format(where="artifacts/0004-new", reason=reason)),
    ]


def test_a_second_interrupt_during_the_hand_back_names_the_folder(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    def interrupt() -> None:
        raise KeyboardInterrupt

    Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    notes: list[tuple[str, str]] = []
    host = recording_host(interrupt_on_reap=True)
    kind, runner, _host = make(FakeEngine(on_chown=interrupt), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(folder))
    assert runner.argvs()[-1] == CHOWN_REMOVED
    reason = "an interrupt stopped the hand-back before it ended"
    assert notes == [
        ("files_not_handed_back", KEPT.format(where="artifacts/0003-new", reason=reason))
    ]


def test_an_error_in_the_hand_back_of_an_interrupted_launch_keeps_the_interrupt(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_host: Any
) -> None:
    def fail() -> None:
        raise OSError(13, "made-up denial", str(tmp_path / "made-up-place"))

    Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    notes: list[tuple[str, str]] = []
    host = recording_host(interrupt_on_reap=True)
    kind, _runner, _host = make(FakeEngine(on_chown=fail), host=host)
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    with pytest.raises(KeyboardInterrupt):
        resolved.launch(_request(folder))
    # The note names the kind of error only: its text holds a path outside the run folder.
    reason = "the hand-back stopped on an error (PermissionError)"
    assert notes == [
        ("files_not_handed_back", KEPT.format(where="artifacts/0003-new", reason=reason))
    ]


def test_an_engine_whose_program_cannot_start_is_named_as_such(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    removed: list[str] = []
    facts = EngineFacts(name="docker", program=str(tmp_path / "made-up-engine"), version="9")
    reason = container.hand_back(
        run_command,
        facts,
        IMAGE_ID,
        folder,
        name=CHOWN_NAME,
        run_id="run-a",
        settings=LaunchSettings(),
        environ={},
        remove=removed.append,
    )
    assert reason == "the engine's program could not be started"
    assert removed == [CHOWN_NAME]


def test_an_engine_that_cannot_run_the_chown_container_is_named_as_such(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Owner(monkeypatch)
    folder = _launch_folder(tmp_path)
    notes: list[tuple[str, str]] = []
    kind, _runner, _host = make(FakeEngine(chown_rc=125))
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    resolved.launch(_request(folder))
    reason = "the engine could not run the container that runs chown (exit 125)"
    assert notes == [
        ("files_not_handed_back", KEPT.format(where="artifacts/0003-new", reason=reason) + ONCE)
    ]


def test_every_removal_of_a_container_waits_a_bounded_time(make: Build, tmp_path: Path) -> None:
    kind, runner, _host = make()
    settings = LaunchSettings(identify=("tool", "--version"))
    resolved = kind.resolve(SIDE, _ctx(settings))
    assert resolved.cannot_repeat is None
    resolved.launch(_request(tmp_path))
    removals = [call for call in runner.calls if call.argv[1] == "rm"]
    assert len(removals) == 3
    assert [call.timeout_s for call in removals] == [container.REMOVE_WAIT_S] * 3
    assert container.REMOVE_WAIT_S == 60.0


def test_a_removal_that_does_not_end_names_the_container_left_behind(
    make: Build, tmp_path: Path
) -> None:
    notes: list[tuple[str, str]] = []
    kind, _runner, _host = make(FakeEngine(rm_hangs=True))
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    outcome = resolved.launch(_request(tmp_path))
    assert outcome.rc == 0
    assert notes == [
        (
            "container_not_removed",
            f"the engine did not remove the container {NAME} of side new within 60 s; it may "
            "be left behind, and pairbench doctor lists it",
        )
    ]


def test_a_removed_container_gives_no_note(make: Build, tmp_path: Path) -> None:
    notes: list[tuple[str, str]] = []
    kind, _runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx(note=lambda code, message: notes.append((code, message))))
    resolved.launch(_request(tmp_path))
    assert notes == []


# Made-up podman facts: podman writes the image ID without "sha256:" in front
# and its times with the local offset.
PODMAN_ID = "89abcdef01234567" * 4
PODMAN_DETAILS: dict[str, Any] = {
    "Id": PODMAN_ID,
    "Digest": f"sha256:{DIGEST}",
    "RepoDigests": [f"registry.example/tool@sha256:{DIGEST}"],
    "Os": "linux",
    "Architecture": "amd64",
    "Config": {"Cmd": ["sh"]},
}
PODMAN_STATE: dict[str, Any] = {
    "ExitCode": 0,
    "StartedAt": "2031-01-02T04:04:05.100000000+01:00",
    "FinishedAt": "2031-01-02T04:04:07.350000000+01:00",
}


def test_a_podman_shaped_image_resolves_shows_and_launches(make: Build, tmp_path: Path) -> None:
    engine = FakeEngine(images={REF: PODMAN_DETAILS}, state=PODMAN_STATE)
    kind, _runner, host = make(engine, found=("podman",))
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.side.public_identity() == {
        "image_id": PODMAN_ID,
        "digests": [f"sha256:{DIGEST}"],
        "platform": "linux/amd64",
    }
    outcome = resolved.launch(_request(tmp_path))
    argv = host.runs[0].argv
    assert argv[0] == PODMAN
    assert PODMAN_ID in argv
    assert outcome.timing == {"run_s": 2.25, "launch_s": 3.0}
    assert dict(resolved.identify()) == dict(resolved.side.identity)


# --- environment ------------------------------------------------------------


def test_env_pass_values_travel_in_the_engine_s_environment_only(
    make: Build, tmp_path: Path
) -> None:
    settings = LaunchSettings(env_pass=("TOKEN",), env={"MODE": "x"})
    kind, runner, host = make()
    ctx = _ctx(settings, environ={"TOKEN": "s3"})
    resolved = kind.resolve(SIDE, ctx)
    resolved.launch(_request(tmp_path, env=api.env_pad(4)))
    run = host.runs[0]
    assert "s3" not in " ".join(run.argv)
    assert "TOKEN" in run.argv
    assert run.env["TOKEN"] == "s3"
    assert run.env["MODE"] == "x"
    assert run.env["PAIRBENCH_ENV_PAD"] == "xxxx"
    assert "s3" not in json.dumps(dict(resolved.side.identity))
    assert all("s3" not in " ".join(call.argv) for call in runner.calls)


def test_a_variable_the_engine_reads_itself_is_passed_on_the_command_line(
    make: Build, tmp_path: Path
) -> None:
    kind, _runner, host = make()
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(env={"HOME": "/h"}), environ={"HOME": "/c"}))
    resolved.launch(_request(tmp_path))
    run = host.runs[0]
    assert "HOME=/h" in run.argv
    assert run.env["HOME"] == "/c"


def test_env_pass_of_a_variable_the_engine_reads_is_refused(make: Build) -> None:
    kind, _runner, _host = make()
    settings = LaunchSettings(env_pass=("DOCKER_HOST",))
    with pytest.raises(Refusal) as caught:
        kind.look_up(SIDE, _ctx(settings, environ={"DOCKER_HOST": "unix:///x"}))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_a_missing_env_pass_variable_is_a_usage_error(make: Build) -> None:
    kind, _runner, _host = make()
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx(LaunchSettings(env_pass=("TOKEN",))))
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


# --- fingerprint --------------------------------------------------------------


def test_two_sides_that_differ_only_in_name_have_one_fingerprint(make: Build) -> None:
    kind, _runner, _host = make()
    one = kind.resolve(Side.image("old", REF), _ctx())
    two = kind.resolve(Side.image("new", REF), _ctx())
    assert one.side.fingerprint == two.side.fingerprint


def test_the_side_s_args_env_and_limits_change_the_fingerprint(make: Build) -> None:
    kind, _runner, _host = make()
    plain = kind.resolve(SIDE, _ctx()).side.fingerprint
    args = Side(name="new", kind="image", spec={**SIDE.spec, "args": ("-x",)})
    env = Side(name="new", kind="image", spec={**SIDE.spec, "env": {"A": "1"}})
    assert kind.resolve(args, _ctx()).side.fingerprint != plain
    assert kind.resolve(env, _ctx()).side.fingerprint != plain
    assert kind.resolve(SIDE, _ctx(LaunchSettings(memory="1g"))).side.fingerprint != plain


def test_the_environment_pad_does_not_change_the_fingerprint(make: Build, tmp_path: Path) -> None:
    kind, _runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx())
    before = resolved.side.fingerprint
    resolved.launch(_request(tmp_path, env=api.env_pad(9)))
    assert resolved.side.fingerprint == before
    assert kind.resolve(SIDE, _ctx()).side.fingerprint == before


# --- identify -----------------------------------------------------------------


def test_the_identify_command_runs_inside_a_removed_container(make: Build) -> None:
    kind, runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx(LaunchSettings(identify=("tool", "--version"))))
    assert resolved.side.identity["identify_sha256"] == V1_SHA256
    assert resolved.side.identity["identify_output"] == "v1\n"
    run = next(argv for argv in runner.argvs() if argv[1] == "run")
    assert run[run.index("--entrypoint") + 1 :] == ("tool", IMAGE_ID, "--version")
    assert "--rm" in run
    assert run[run.index("--pull") + 1] == "never"
    name = run[run.index("--name") + 1]
    assert (DOCKER, "rm", "--force", name) in runner.argvs()


def test_an_identify_command_without_output_is_refused(make: Build) -> None:
    kind, _runner, _host = make(FakeEngine(identify_out="  \n"))
    with pytest.raises(Refusal) as caught:
        kind.resolve(SIDE, _ctx(LaunchSettings(identify=("tool",))))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)


def test_the_look_up_never_runs_the_identify_command(make: Build) -> None:
    kind, runner, _host = make()
    found = kind.look_up(SIDE, _ctx(LaunchSettings(identify=("tool",))))
    assert "run" not in _verbs(runner)
    assert found.fingerprint == ""


def test_identify_again_inspects_by_image_id_and_never_pulls(make: Build) -> None:
    engine = FakeEngine()
    kind, runner, _host = make(engine)
    resolved = kind.resolve(SIDE, _ctx())
    before = len(runner.calls)
    assert dict(resolved.identify()) == dict(resolved.side.identity)
    after = runner.argvs()[before:]
    assert after == [(DOCKER, "image", "inspect", "--format", "{{json .}}", IMAGE_ID)]


def test_identify_again_refuses_when_the_image_is_gone(make: Build) -> None:
    engine = FakeEngine()
    kind, _runner, _host = make(engine)
    resolved = kind.resolve(SIDE, _ctx())
    engine.images.clear()
    with pytest.raises(Refusal) as caught:
        resolved.identify()
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)


# --- the positive control -----------------------------------------------------


# What dash writes on standard error when a redirection may not be opened.
DENIED = "sh: 1: cannot create /pairbench/artifacts/run2/stderr.txt: Permission denied\n"
# The reason a launch of two runs gives when its shell was refused a run's file.
REFUSED_OUTPUT = (
    "the shell in a container of side new was refused a file where one of the two runs "
    "keeps its output (permission denied), though the check before the first round could "
    "write it"
)


@pytest.mark.parametrize(
    ("two_runs", "rc", "line", "reason"),
    [
        (True, 2, DENIED, REFUSED_OUTPUT),
        (
            True,
            1,
            "sh: can't create /pairbench/artifacts/run1/stdout.txt: Permission denied\n",
            REFUSED_OUTPUT,
        ),
        (True, 2, "w: cannot open /made-up/input: Permission denied\n", None),
        (True, 2, "w: no such input\n", None),
        (False, 2, DENIED, None),
    ],
    ids=["dash", "busybox", "another-file", "another-cause", "one-run"],
)
def test_a_launch_of_two_runs_says_when_its_shell_was_refused_a_run_s_output_file(
    make: Build,
    tmp_path: Path,
    recording_host: Any,
    two_runs: bool,
    rc: int,
    line: str,
    reason: str | None,
) -> None:
    class Says(recording_host):  # type: ignore[misc, valid-type]
        def spawn(self, run: HostRun, stdout: IO[bytes], stderr: IO[bytes]) -> int:
            stderr.write(line.encode())
            return int(super().spawn(run, stdout, stderr))

    engine = FakeEngine(state={**STATE, "ExitCode": rc})
    kind, _runner, _host = make(engine, host=Says(rcs=(rc,)))
    resolved = kind.resolve(SIDE, _ctx(workload=("w",)))
    second = api.PreparedRun(argv=("w",)) if two_runs else None
    outcome = resolved.launch(_request(tmp_path, argv=("w",), second=second))
    assert (outcome.rc, outcome.cannot_repeat) == (rc, reason)


def test_an_image_with_a_shell_runs_both_commands_in_one_container(
    make: Build, tmp_path: Path
) -> None:
    kind, runner, host = make()
    resolved = kind.resolve(SIDE, _ctx(workload=("w",)))
    assert resolved.cannot_repeat is None
    second = api.PreparedRun(argv=("w", "b c"), env={"PAIRBENCH_WORK_FACTOR": "2"})
    outcome = resolved.launch(_request(tmp_path, argv=("w",), second=second))
    argv = host.runs[0].argv
    assert len(host.runs) == 1
    assert argv[argv.index("--entrypoint") + 1] == "/bin/sh"
    assert argv[argv.index(IMAGE_ID) :] == (
        IMAGE_ID,
        "-c",
        "w >/pairbench/artifacts/run1/stdout.txt 2>/pairbench/artifacts/run1/stderr.txt"
        " && PAIRBENCH_WORK_FACTOR=2 w 'b c' >/pairbench/artifacts/run2/stdout.txt"
        " 2>/pairbench/artifacts/run2/stderr.txt",
    )
    for folder in ("run1", "run2"):
        assert (tmp_path / folder / "stdout.txt").is_file()
        assert (tmp_path / folder / "stderr.txt").is_file()
    assert outcome.timing == {"run_s": 2.25, "launch_s": 3.0}
    assert outcome.second_pid is None
    assert runner.argvs()[-1] == (DOCKER, "rm", "--force", NAME)


def test_an_image_without_a_shell_gives_the_reason_and_is_asked_once(make: Build) -> None:
    kind, runner, _host = make(FakeEngine(shell=False))
    resolved = kind.resolve(SIDE, _ctx())
    reason = resolved.cannot_repeat
    assert reason is not None
    assert "/bin/sh" in reason
    assert resolved.cannot_repeat == reason
    probes = [argv for argv in runner.argvs() if argv[1] == "run"]
    assert len(probes) == 1
    name = probes[0][probes[0].index("--name") + 1]
    assert (DOCKER, "rm", "--force", name) in runner.argvs()


def test_the_repeat_check_writes_the_files_of_the_two_runs_as_the_control_does(
    make: Build,
) -> None:
    engine = FakeEngine()
    kind, runner, _host = make(engine)
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.cannot_repeat is None
    probe = next(argv for argv in runner.argvs() if argv[1] == "run")
    assert probe[probe.index("--entrypoint") + 1 :] == (
        "/bin/sh",
        IMAGE_ID,
        "-c",
        "test -x /pairbench/artifacts || exit 3;"
        " { test -d /pairbench/artifacts/run1 && test -d /pairbench/artifacts/run2; } || exit 4;"
        " true >/pairbench/artifacts/run1/stdout.txt && true >/pairbench/artifacts/run1/stderr.txt"
        " && true >/pairbench/artifacts/run2/stdout.txt"
        " && true >/pairbench/artifacts/run2/stderr.txt || exit 3",
    )
    assert engine.mounted == [
        {
            "run1/stdout.txt": True,
            "run1/stderr.txt": True,
            "run2/stdout.txt": True,
            "run2/stderr.txt": True,
        }
    ]
    volume = probe[probe.index("--volume") + 1]
    assert not Path(volume.rsplit(":", 1)[0]).exists()


def test_an_image_user_that_cannot_write_the_mount_gives_the_cause(make: Build) -> None:
    kind, _runner, _host = make(FakeEngine(writable=False))
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.cannot_repeat == (
        "the user the image of side new runs as cannot write the files pairbench creates in "
        "the folder it mounts, where the two runs keep their output; an image whose user is "
        "root or has your user id can"
    )


def _check_rc(mounted: Path) -> int:
    """Run the repeat check's shell text against ``mounted`` in place of the mounted folder."""
    script = container.write_check_script().replace(api.ARTIFACTS_IN_CONTAINER, str(mounted))
    return subprocess.run(["/bin/sh", "-c", script], check=False).returncode


def test_the_repeat_check_tells_a_folder_the_user_cannot_enter_from_one_it_does_not_see(
    tmp_path: Path,
) -> None:
    # A folder the user cannot enter is a folder the user cannot write in, also
    # under a umask that keeps others out; only a folder without the run folders
    # pairbench made counts as one the container does not see.
    if not Path("/bin/sh").exists():
        pytest.skip("needs /bin/sh to run the check's shell text")
    if os.geteuid() == 0:
        pytest.skip("needs a user other than root: root enters any folder")
    made = tmp_path / "made"
    made.mkdir()
    container.make_run_folders(made)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _check_rc(made) == 0
    assert _check_rc(empty) == container.MISSING_CHECK_RC
    made.chmod(0o600)
    try:
        assert _check_rc(made) == container.WRITE_CHECK_RC
    finally:
        made.chmod(0o700)
    (made / "run2" / "stderr.txt").chmod(0o400)
    assert _check_rc(made) == container.WRITE_CHECK_RC


def test_the_repeat_check_folder_lies_beside_the_folder_of_the_side_s_last_launch(
    make: Build, tmp_path: Path
) -> None:
    # The engine mounts the check's folder as it mounted the warm-up's: an engine
    # that cannot reach the system's temporary folder still sees it.
    launches = tmp_path / "run" / "artifacts"
    warm_up = launches / "0001-new"
    warm_up.mkdir(parents=True)
    kind, runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx())
    resolved.launch(_request(warm_up, phase="warmup", round=0, pos=None))
    assert resolved.cannot_repeat is None
    probe = next(argv for argv in runner.argvs() if argv[1] == "run")
    source = Path(probe[probe.index("--volume") + 1].rsplit(":", 1)[0])
    assert source.parent.parent == launches
    assert sorted(path.name for path in launches.iterdir()) == ["0001-new"]


def test_before_any_launch_the_repeat_check_folder_lies_where_the_run_makes_launch_folders(
    make: Build, tmp_path: Path
) -> None:
    # A run without a warm-up asks before the side's first launch; the engine
    # mounts the check's folder from where the run's launch folders will be.
    run = tmp_path / "run"
    run.mkdir()
    launches = run / "artifacts"
    kind, runner, _host = make()
    resolved = kind.resolve(SIDE, _ctx(launch_folders=launches))
    assert resolved.cannot_repeat is None
    probe = next(argv for argv in runner.argvs() if argv[1] == "run")
    source = Path(probe[probe.index("--volume") + 1].rsplit(":", 1)[0])
    assert source.parent.parent == launches
    assert list(launches.iterdir()) == []


@pytest.mark.parametrize("when", ["before any launch", "after a launch"])
def test_the_repeat_check_mounts_its_folder_by_an_absolute_path_from_a_relative_run_folder(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    # A relative mount source is read by the engine as the name of a volume.
    monkeypatch.chdir(tmp_path)
    launches = Path("run") / "artifacts"
    (launches / "0001-new").mkdir(parents=True)
    kind, runner, _host = make()
    if when == "before any launch":
        resolved = kind.resolve(SIDE, _ctx(launch_folders=launches))
    else:
        resolved = kind.resolve(SIDE, _ctx())
        resolved.launch(_request(launches / "0001-new"))
    assert resolved.cannot_repeat is None
    probe = next(argv for argv in runner.argvs() if argv[1] == "run" and "--rm" in argv)
    source = probe[probe.index("--volume") + 1].rsplit(":", 1)[0]
    assert os.path.isabs(source)
    assert Path(source).parent.parent == tmp_path / launches


def test_a_check_folder_the_container_does_not_see_is_not_blamed_on_the_image_user(
    make: Build,
) -> None:
    kind, _runner, _host = make(FakeEngine(shown=False))
    resolved = kind.resolve(SIDE, _ctx())
    assert resolved.cannot_repeat == (
        "the files pairbench created in the folder it mounted into a container of side new did "
        "not show inside it, so whether the image's user can write the files where the two runs "
        "keep their output was not checked"
    )


def test_the_two_commands_include_the_image_s_entrypoint(make: Build, tmp_path: Path) -> None:
    details = {**DETAILS, "Config": {"Entrypoint": ["/entry", "-q"], "Cmd": ["d"]}}
    kind, _runner, host = make(FakeEngine(images={REF: details}))
    resolved = kind.resolve(SIDE, _ctx())
    resolved.launch(_request(tmp_path, argv=None, second=api.PreparedRun(argv=None)))
    script = host.runs[0].argv[-1]
    assert script.startswith("/entry -q d >")
    assert " && /entry -q d >" in script


def test_a_run_variable_no_shell_can_set_is_refused(make: Build, tmp_path: Path) -> None:
    kind, _runner, host = make()
    resolved = kind.resolve(SIDE, _ctx(workload=("w",)))
    second = api.PreparedRun(argv=("w",), env={"A-B": "1"})
    with pytest.raises(Refusal) as caught:
        resolved.launch(_request(tmp_path, argv=("w",), second=second))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)
    assert host.runs == []


def test_the_two_run_script_quotes_every_word() -> None:
    script = two_run_script(["a b"], {"X": "1 2"}, ["c;d"], {})
    assert script == (
        "'a b' >/pairbench/artifacts/run1/stdout.txt 2>/pairbench/artifacts/run1/stderr.txt"
        " && 'c;d' >/pairbench/artifacts/run2/stdout.txt 2>/pairbench/artifacts/run2/stderr.txt"
    ).replace("'a b' >", "X='1 2' 'a b' >")


# --- the id of the container's process ---------------------------------------


def test_with_gpus_on_a_local_engine_the_container_s_pid_is_reported(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(container, "engine_is_local", lambda engine, environ: True)
    kind, _runner, _host = make()
    outcome = kind.resolve(SIDE, _ctx(LaunchSettings(gpus="0"))).launch(_request(tmp_path))
    assert outcome.pid == 4321


def test_without_gpus_the_engine_is_not_asked_for_the_pid(make: Build, tmp_path: Path) -> None:
    kind, runner, _host = make()
    outcome = kind.resolve(SIDE, _ctx()).launch(_request(tmp_path))
    assert outcome.pid is None
    assert all("{{.State.Pid}}" not in argv for argv in runner.argvs())


def test_an_engine_elsewhere_reports_no_pid(
    make: Build, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(container, "engine_is_local", lambda engine, environ: False)
    kind, runner, _host = make()
    outcome = kind.resolve(SIDE, _ctx(LaunchSettings(gpus="0"))).launch(_request(tmp_path))
    assert outcome.pid is None
    assert all("{{.State.Pid}}" not in argv for argv in runner.argvs())


# --- engine times ---------------------------------------------------------------


def test_engine_times_keep_their_nanoseconds_and_zones() -> None:
    assert parse_engine_time(FINISHED) - parse_engine_time(STARTED) == 2_250_000_000  # type: ignore[operator]
    same = parse_engine_time("2031-01-02T04:04:05.100000000+01:00")
    assert same == parse_engine_time(STARTED)
    assert parse_engine_time("2031-01-02T03:04:05Z") == parse_engine_time(
        "2031-01-02T03:04:05.000000000Z"
    )
    podman_style = "2031-01-02T03:04:05.1Z"
    assert parse_engine_time(podman_style) == parse_engine_time(STARTED)


def test_the_engine_s_zero_time_and_other_texts_give_nothing() -> None:
    assert parse_engine_time("0001-01-01T00:00:00Z") is None
    assert parse_engine_time("2031-13-02T03:04:05Z") is None
    assert parse_engine_time("2031-01-02T25:04:05Z") is None
    assert parse_engine_time("yesterday") is None
    assert parse_engine_time(None) is None


# --- the spec of an image side ------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        {"image": "", "args": (), "env": {}, "entrypoint": None},
        {"image": REF, "args": "a b", "env": {}, "entrypoint": None},
        {"image": REF, "args": (), "env": {"A": 1}, "entrypoint": None},
    ],
    ids=["no-image", "args-text", "env-number"],
)
def test_a_spec_the_kind_cannot_read_is_a_usage_error(make: Build, spec: dict[str, Any]) -> None:
    kind, _runner, _host = make()
    side = Side(name="new", kind="image", spec=spec)
    with pytest.raises(Refusal) as caught:
        kind.look_up(side, _ctx())
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)


# --- doctor ---------------------------------------------------------------------


def test_doctor_lists_the_containers_runs_left_behind(make: Build) -> None:
    left = ("pairbench-run-b-0002-old", "pairbench-run-b-0003-new")
    kind, runner, _host = make(FakeEngine(leftovers=left))
    report = kind.doctor()
    assert report.status == "degraded"
    assert report.detail["leftover_containers"] == list(left)
    assert (
        DOCKER,
        "ps",
        "--all",
        "--filter",
        "label=pairbench.run",
        "--format",
        "{{.Names}}",
    ) in runner.argvs()


def test_doctor_without_leftovers_is_ok(make: Build) -> None:
    kind, _runner, _host = make()
    report = kind.doctor()
    assert report.status == "ok"
    assert report.detail["leftover_containers"] == []


def test_doctor_without_an_engine_is_unavailable(make: Build) -> None:
    kind, _runner, _host = make(found=())
    assert kind.doctor().status == "unavailable"


def test_engine_facts_carry_into_the_engine_info() -> None:
    facts = EngineFacts(name="podman", program=PODMAN, version="9.9.9")
    assert (facts.info().name, facts.info().version) == ("podman", "9.9.9")


# --- a real engine, read-only -------------------------------------------------

# A tiny public image. The tests below never pull it and never start a
# container: they only ask the engine about what is already on the machine.
REAL_IMAGE = "busybox:latest"


@pytest.mark.parametrize("engine", ["docker", "podman"])
def test_a_real_engine_s_look_up_matches_its_inspect_output(
    needs: Any, engine: Literal["docker", "podman"]
) -> None:
    program = needs.engine(engine)
    environ = dict(os.environ)
    real = run_command([program, "image", "inspect", "--format", "{{json .}}", REAL_IMAGE])
    if real.rc != 0:
        pytest.skip(f"needs the image {REAL_IMAGE} on this machine; it is never pulled here")
    found = ImageKind().look_up(
        Side.image("new", REAL_IMAGE),
        api.SideContext(run_id="", settings=LaunchSettings(engine=engine), environ=environ),
    )
    details = json.loads(real.stdout)
    assert found.status == "identified"
    assert dict(found.identity) == image_identity(details)
    assert str(found.identity["image_id"]).removeprefix("sha256:") in details["Id"]
    assert len(found.fingerprint) == 64


@pytest.mark.parametrize("engine", ["docker", "podman"])
def test_a_real_engine_reports_to_doctor(needs: Any, engine: str) -> None:
    needs.engine(engine)
    report = ImageKind(environ=dict(os.environ)).doctor()
    assert report.status in ("ok", "degraded")
    assert engine in report.detail["engines"]
    assert all(name.startswith("pairbench-") for name in report.detail["leftover_containers"])


# Ordinary settings whose names say key or token: each pair of values gives two fingerprints.
ORDINARY_IMAGE_ARGS = {
    "queued-tokens": (
        ("--max-num-queued-tokens", "1024"),
        ("--max-num-queued-tokens", "4096"),
    ),
    "key-size": (("--key-size", "16"), ("--key-size", "32")),
    "switch-before-the-model": (
        ("--allow-credentials", "org/model-a"),
        ("--allow-credentials", "org/model-b"),
    ),
    "axis-key": (("-a", "Key=I32"), ("-a", "Key=I64")),
}


@pytest.mark.parametrize(
    ("one", "two"), list(ORDINARY_IMAGE_ARGS.values()), ids=list(ORDINARY_IMAGE_ARGS)
)
def test_an_ordinary_setting_of_an_image_side_changes_its_fingerprint(
    make: Build, one: tuple[str, ...], two: tuple[str, ...]
) -> None:
    kind, _runner, _host = make()
    first = Side(name="new", kind="image", spec={**SIDE.spec, "args": one})
    second = Side(name="new", kind="image", spec={**SIDE.spec, "args": two})
    assert kind.resolve(first, _ctx()).side.fingerprint != (
        kind.resolve(second, _ctx()).side.fingerprint
    )


def test_a_secret_of_an_image_side_leaves_its_fingerprint_alone(make: Build) -> None:
    kind, _runner, _host = make()
    found = {
        kind.resolve(
            Side(name="new", kind="image", spec={**SIDE.spec, "args": ("--api-key", word)}),
            _ctx(),
        ).side.fingerprint
        for word in ("kiwi7", "plum4")
    }
    assert len(found) == 1


# --- what runs the shared workload ------------------------------------------

# A shared workload with a made-up password, given to the image's own entrypoint.
WORKLOAD = ("-s", "made-up-host", "-a", "kiwi7mango", "-n", "1000")
IDENTITY = {"image_id": IMAGE_ID, "digests": (f"sha256:{DIGEST}",), "platform": "linux/arm64/v8"}
UNREADABLE_MESSAGE = (
    "side 'new': the entrypoint of its image could not be read, so the program that runs the "
    "shared workload is not known; set sides.new.entrypoint to the program the image runs"
)


def _with_config(config: Any) -> dict[str, Any]:
    """The made-up image's details with ``Config`` replaced, or left out for ``...``."""
    details = {key: value for key, value in DETAILS.items() if key != "Config"}
    if config is not ...:
        details["Config"] = config
    return details


@pytest.mark.parametrize(
    ("config", "recorded"),
    [
        (
            {"Entrypoint": ["memtier_benchmark"], "Cmd": None},
            {"image_entrypoint": ("memtier_benchmark",)},
        ),
        (
            {"Entrypoint": ["docker-entrypoint.sh"], "Cmd": ["memtier_benchmark"]},
            {
                "image_entrypoint": ("docker-entrypoint.sh",),
                "image_command_program": "memtier_benchmark",
            },
        ),
        (
            {"Entrypoint": None, "Cmd": ["sh"]},
            {"image_entrypoint": (), "image_command_program": "sh"},
        ),
        ({"Entrypoint": [], "Cmd": []}, {"image_entrypoint": ()}),
        ({}, {"image_entrypoint": ()}),
    ],
)
def test_an_image_side_records_what_runs_the_shared_workload(
    make: Build, config: dict[str, Any], recorded: dict[str, Any]
) -> None:
    kind, _runner, _host = make(FakeEngine(images={REF: _with_config(config)}))
    found = kind.look_up(SIDE, _ctx(workload=WORKLOAD))
    resolved = kind.resolve(SIDE, _ctx(workload=WORKLOAD))

    assert dict(found.identity) == {**IDENTITY, **recorded}
    assert dict(resolved.side.identity) == {**IDENTITY, **recorded}
    assert dict(resolved.identify()) == {**IDENTITY, **recorded}


def test_what_an_image_side_records_leaves_its_fingerprint_alone(make: Build) -> None:
    config = {"Entrypoint": ["docker-entrypoint.sh"], "Cmd": ["memtier_benchmark"]}
    kind, _runner, _host = make(FakeEngine(images={REF: _with_config(config)}))
    given = kind.resolve(SIDE, _ctx(workload=WORKLOAD)).side
    none = kind.resolve(SIDE, _ctx()).side

    assert dict(none.identity) == IDENTITY
    assert given.fingerprint == none.fingerprint != ""


@pytest.mark.parametrize(
    "config",
    [
        ...,
        None,
        "made-up",
        {"Entrypoint": "memtier_benchmark"},
        {"Entrypoint": ["memtier_benchmark", 7]},
    ],
    ids=["no-config", "null-config", "text-config", "text-entrypoint", "number-in-entrypoint"],
)
def test_an_unreadable_entrypoint_refuses_the_side_before_any_container_starts(
    make: Build, config: Any
) -> None:
    kind, runner, _host = make(FakeEngine(images={REF: _with_config(config)}))
    for step in (kind.look_up, kind.resolve):
        with pytest.raises(Refusal) as caught:
            step(SIDE, _ctx(workload=WORKLOAD))

        assert (caught.value.code, caught.value.exit_code) == ("E_ENTRYPOINT_UNREADABLE", EXIT_SIDE)
        assert caught.value.message == UNREADABLE_MESSAGE
    assert set(_verbs(runner)) == {"version", "info", "image"}


@pytest.mark.parametrize(
    ("side", "workload"),
    [
        (Side.image("new", REF, entrypoint="memtier_benchmark"), WORKLOAD),
        (Side.image("new", REF, args=("-n", "1000")), WORKLOAD),
        (SIDE, None),
    ],
    ids=["own-entrypoint", "own-args", "no-workload"],
)
def test_a_side_that_names_its_program_or_runs_no_workload_reads_no_entrypoint(
    make: Build, side: Side, workload: tuple[str, ...] | None
) -> None:
    kind, _runner, _host = make(FakeEngine(images={REF: _with_config(None)}))
    found = kind.look_up(side, _ctx(workload=workload))
    resolved = kind.resolve(side, _ctx(workload=workload))

    assert dict(found.identity) == IDENTITY
    assert dict(resolved.side.identity) == IDENTITY
    assert dict(resolved.identify()) == IDENTITY
