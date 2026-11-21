# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``cmd`` side kind: substitution, identity, refusals and a real launch."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from pairbench import api
from pairbench.errors import EXIT_SIDE, EXIT_USAGE, Refusal
from pairbench.model import LaunchSettings, Side
from pairbench.sides.base import Completed
from pairbench.sides.command import CommandKind, substitute_workload

# SHA-256 of the canonical JSON text ["made-up-tool","a"].
TOOL_ARGV_SHA256 = "db0592953dd33ce416d89e3c2720bfe2feeabc9fd071c8dc5f3b3c46f77b409d"
# SHA-256 of the script "#!/bin/sh\nexit 0\n" and of "#!/bin/sh\nexit 1\n".
EXIT0_SHA256 = "306c6ca7407560340797866e077e053627ad409277d1b9da58106fce4cf717cb"
EXIT1_SHA256 = "275239824e00e61b0a220e61a41791c7e9b4bd726f8b0c27077a338f8131c9dc"


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    path = folder / "made-up-tool"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def _ctx(tool: Path, **extra: Any) -> api.SideContext:
    environ = {"PATH": str(tool.parent)}
    environ.update(extra.pop("environ", {}))
    settings = extra.pop("settings", LaunchSettings())
    return api.SideContext(run_id="run-a", settings=settings, environ=environ, **extra)


def _no_commands(argv: tuple[str, ...]) -> Completed:
    raise AssertionError(f"no command may run here: {argv}")


SIDE = Side.command("new", ["made-up-tool", "{workload}"])


# --- substitution -----------------------------------------------------------


def test_the_workload_takes_the_place_of_the_placeholder_argument() -> None:
    side = Side.command("new", ["run", "{workload}", "--x"])
    assert substitute_workload(side, side.spec["argv"], ("a", "b")) == ("run", "a", "b", "--x")


def test_a_command_without_the_placeholder_runs_exactly_as_written() -> None:
    side = Side.command("new", ["run", "--x"])
    assert substitute_workload(side, side.spec["argv"], None) == ("run", "--x")


@pytest.mark.parametrize(
    ("argv", "workload", "words"),
    [
        (["run"], ("a",), "add {workload}"),
        (["run", "{workload}"], None, "no shared workload"),
        (["run", "--w={workload}"], ("a",), "argument of its own"),
    ],
    ids=["workload-without-placeholder", "placeholder-without-workload", "inside-an-argument"],
)
def test_a_placeholder_that_cannot_be_filled_is_a_usage_error(
    argv: list[str], workload: tuple[str, ...] | None, words: str
) -> None:
    side = Side.command("new", argv)
    with pytest.raises(Refusal) as caught:
        substitute_workload(side, argv, workload)
    assert (caught.value.code, caught.value.exit_code) == ("E_USAGE", EXIT_USAGE)
    assert words in caught.value.message


# --- identity ---------------------------------------------------------------


def test_the_identity_holds_the_executable_hash_and_the_argument_hash(
    tool: Path, fake_runner: Any
) -> None:
    kind = CommandKind(runner=fake_runner(_no_commands))
    resolved = kind.resolve(SIDE, _ctx(tool, workload=("a",)))
    assert resolved.side.identity == {
        "executable": str(tool),
        "executable_sha256": EXIT0_SHA256,
        "argv_sha256": TOOL_ARGV_SHA256,
    }
    assert resolved.side.public_identity() == {
        "executable_sha256": EXIT0_SHA256,
        "argv_sha256": TOOL_ARGV_SHA256,
    }
    assert resolved.command == ("made-up-tool", "a")
    assert len(resolved.side.fingerprint) == 64


def test_the_look_up_runs_nothing_and_gives_the_fingerprint_resolve_gives(
    tool: Path, fake_runner: Any
) -> None:
    runner = fake_runner(_no_commands)
    kind = CommandKind(runner=runner)
    ctx = _ctx(tool, workload=("a",))
    found = kind.look_up(SIDE, ctx)
    resolved = kind.resolve(SIDE, ctx)
    assert found.status == "identified"
    assert found.identity == resolved.side.identity
    assert found.fingerprint == resolved.side.fingerprint
    assert runner.calls == []


def test_two_sides_that_differ_only_in_name_have_one_fingerprint(tool: Path) -> None:
    kind = CommandKind()
    ctx = _ctx(tool, workload=("a",))
    one = kind.resolve(SIDE, ctx).side.fingerprint
    other = kind.resolve(Side.command("old", ["made-up-tool", "{workload}"]), ctx).side.fingerprint
    assert one == other


def test_the_env_table_of_the_launch_settings_changes_the_fingerprint(tool: Path) -> None:
    kind = CommandKind()
    plain = kind.resolve(SIDE, _ctx(tool, workload=("a",))).side.fingerprint
    settings = LaunchSettings(env={"OMP_NUM_THREADS": "4"})
    tuned = kind.resolve(SIDE, _ctx(tool, workload=("a",), settings=settings)).side.fingerprint
    assert plain != tuned


def test_the_identify_command_runs_in_resolve_with_the_launch_environment(
    tool: Path, fake_runner: Any
) -> None:
    runner = fake_runner(lambda argv: Completed(rc=0, stdout="v1\n"))
    settings = LaunchSettings(identify=("made-up-tool", "--version"), env={"A": "1"})
    kind = CommandKind(runner=runner)
    resolved = kind.resolve(SIDE, _ctx(tool, workload=("a",), settings=settings))
    assert runner.argvs() == [("made-up-tool", "--version")]
    assert runner.calls[0].env == {"PATH": str(tool.parent), "A": "1"}
    assert resolved.side.identity["identify_output"] == "v1\n"
    assert set(resolved.side.public_identity()) == {
        "executable_sha256",
        "argv_sha256",
        "identify_sha256",
    }
    resolved.identify()
    assert len(runner.calls) == 2


def test_the_look_up_never_runs_the_identify_command_and_then_gives_no_fingerprint(
    tool: Path, fake_runner: Any
) -> None:
    runner = fake_runner(_no_commands)
    settings = LaunchSettings(identify=("made-up-tool", "--version"))
    found = CommandKind(runner=runner).look_up(SIDE, _ctx(tool, workload=("a",), settings=settings))
    assert found.fingerprint == ""
    assert "identify_output" not in found.identity


def test_identify_reads_the_executable_again(tool: Path) -> None:
    resolved = CommandKind().resolve(SIDE, _ctx(tool, workload=("a",)))
    tool.write_text("#!/bin/sh\nexit 1\n")
    assert resolved.identify()["executable_sha256"] == EXIT1_SHA256


def test_a_relative_executable_is_found_in_the_working_directory(tmp_path: Path) -> None:
    script = tmp_path / "bench.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    side = Side.command("new", ["./bench.sh"])
    ctx = api.SideContext(
        run_id="run-a", settings=LaunchSettings(workdir=str(tmp_path)), environ={"PATH": ""}
    )
    resolved = CommandKind().resolve(side, ctx)
    assert resolved.side.identity["executable"] == str(script)


# --- refusals ---------------------------------------------------------------


def test_an_executable_that_is_not_there_is_refused_naming_only_the_file(tool: Path) -> None:
    side = Side.command("new", ["/made/up/path/missing-tool"])
    for call in (CommandKind().look_up, CommandKind().resolve):
        with pytest.raises(Refusal) as caught:
            call(side, _ctx(tool))
        assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNRESOLVED", EXIT_SIDE)
        assert "missing-tool" in caught.value.message
        assert "/made/up/path" not in caught.value.message


def _unreadable(path: Path) -> None:
    path.chmod(0o111)
    if os.access(path, os.R_OK):
        pytest.skip("this user reads a file without read permission (the superuser does)")


@pytest.mark.parametrize("call", ["look_up", "resolve"])
def test_an_executable_that_may_run_but_not_be_read_is_a_side_refusal(
    tool: Path, call: str
) -> None:
    _unreadable(tool)
    with pytest.raises(Refusal) as caught:
        getattr(CommandKind(), call)(SIDE, _ctx(tool, workload=("a",)))
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)
    assert caught.value.message == (
        "side 'new': the executable 'made-up-tool' cannot be read, so its hash cannot be recorded"
    )


def test_an_executable_that_turns_unreadable_during_the_run_is_a_side_refusal(
    tool: Path,
) -> None:
    resolved = CommandKind().resolve(SIDE, _ctx(tool, workload=("a",)))
    _unreadable(tool)
    with pytest.raises(Refusal) as caught:
        resolved.identify()
    assert (caught.value.code, caught.value.exit_code) == ("E_SIDE_UNIDENTIFIED", EXIT_SIDE)


@pytest.mark.parametrize("call", ["look_up", "resolve"])
def test_a_memory_limit_is_refused_by_look_up_and_resolve(tool: Path, call: str) -> None:
    settings = LaunchSettings(memory="8g")
    with pytest.raises(Refusal) as caught:
        getattr(CommandKind(), call)(SIDE, _ctx(tool, workload=("a",), settings=settings))
    assert (caught.value.code, caught.value.exit_code) == ("E_ENGINE_UNSUPPORTED", EXIT_SIDE)


def test_a_working_directory_that_is_not_there_is_refused(tool: Path) -> None:
    settings = LaunchSettings(workdir="/made/up/nowhere")
    with pytest.raises(Refusal) as caught:
        CommandKind().resolve(SIDE, _ctx(tool, workload=("a",), settings=settings))
    assert caught.value.code == "E_SIDE_UNRESOLVED"


def test_an_unset_env_pass_variable_is_refused_by_resolve_only(tool: Path) -> None:
    settings = LaunchSettings(env_pass=("MADE_UP_PASSED",))
    ctx = _ctx(tool, workload=("a",), settings=settings)
    assert CommandKind().look_up(SIDE, ctx).status == "identified"
    with pytest.raises(Refusal) as caught:
        CommandKind().resolve(SIDE, ctx)
    assert caught.value.code == "E_USAGE"


def test_a_spec_without_arguments_is_a_usage_error(tool: Path) -> None:
    side = Side(name="new", kind="cmd", spec={"argv": []})
    with pytest.raises(Refusal) as caught:
        CommandKind().look_up(side, _ctx(tool))
    assert caught.value.code == "E_USAGE"


def test_the_registry_finds_the_kind_under_its_name() -> None:
    from pairbench import registry

    kind = registry.side_kind("cmd")
    assert isinstance(kind, CommandKind)
    assert (kind.name, kind.api_version) == ("cmd", api.API_VERSION)


# --- a real launch ----------------------------------------------------------

REPORT = (
    "import os; "
    "print(len(os.environ.get('PAIRBENCH_ENV_PAD', '')), "
    "os.environ.get('PAIRBENCH_WORK_FACTOR', 'unset'), os.environ.get('KEPT', 'unset'))"
)


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="needs os.wait4 for the resource usage")
def test_a_real_launch_runs_the_command_with_the_pad_and_without_the_callers_tool_variables(
    tmp_path: Path,
) -> None:
    side = Side.command("new", [sys.executable, "-c", REPORT])
    environ = {**os.environ, "PAIRBENCH_WORK_FACTOR": "2", "KEPT": "yes"}
    ctx = api.SideContext(run_id="run-a", settings=LaunchSettings(), environ=environ)
    resolved = CommandKind().resolve(side, ctx)
    before = resolved.side.fingerprint
    request = api.LaunchRequest(
        run_id="run-a",
        seq=1,
        phase="round",
        round=1,
        pos=1,
        name="new",
        artifacts=tmp_path,
        argv=resolved.command,
        env=api.env_pad(12),
    )
    outcome = resolved.launch(request)
    assert outcome.rc == 0
    assert (tmp_path / "stdout.txt").read_text() == "12 unset yes\n"
    assert outcome.timing["run_s"] == outcome.timing["launch_s"]
    assert set(outcome.usage) == set(api.USAGE_KEYS)
    assert resolved.side.fingerprint == before


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="needs os.wait4 for the resource usage")
def test_a_real_launch_that_runs_into_its_timeout_says_it_timed_out(tmp_path: Path) -> None:
    side = Side.command("new", [sys.executable, "-c", "import time; time.sleep(30)"])
    settings = LaunchSettings(timeout_s=0.3)
    ctx = api.SideContext(run_id="run-a", settings=settings, environ=dict(os.environ))
    resolved = CommandKind().resolve(side, ctx)
    request = api.LaunchRequest(
        run_id="run-a",
        seq=1,
        phase="round",
        round=1,
        pos=1,
        name="new",
        artifacts=tmp_path,
        argv=resolved.command,
        env=api.env_pad(0),
    )
    outcome = resolved.launch(request)
    assert (outcome.rc, outcome.timed_out) == (-9, True)
