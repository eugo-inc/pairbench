# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The entry point: version, help, usage refusals, exit codes and what is restored afterwards."""

from __future__ import annotations

import argparse
import errno
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench import api, registry
from pairbench.cli import main as entry
from pairbench.errors import EXIT_INTERNAL, EXIT_INTERRUPTED, EXIT_OK, EXIT_USAGE, Refusal
from pairbench.model import FLAG_KEYS, FLAGS_WITHOUT_KEY, REDACTED, TOOL_VERSION

from .conftest import DOCS_LINE, refusal_text

# Package parts that ``pairbench --version`` may not load.
HEAVY_PARTS = (
    "pairbench.runner",
    "pairbench.sides",
    "pairbench.drivers",
    "pairbench.gates",
    "pairbench.charts",
    "pairbench.capture",
    "pairbench.stats",
    "pairbench.report",
    "pairbench.diagnose",
    "pairbench.energy",
    "pairbench.page",
    "pairbench.plan",
    "pairbench.config",
)

VERSION_PROBE = """
import json, sys
from pairbench.cli.main import main
code = main(["--version"])
loaded = sorted(name for name in sys.modules if name.startswith("pairbench"))
print(json.dumps({"code": code, "loaded": loaded}))
"""


def test_version_prints_the_tool_version_on_stdout(cli: Callable[..., Any]) -> None:
    result = cli("--version")

    assert result.code == EXIT_OK
    assert result.out == f"pairbench {TOOL_VERSION}\n"
    assert result.err == ""


def source_environment() -> dict[str, str]:
    """The environment of a child Python that imports this copy of the package."""
    import pairbench

    source = str(Path(pairbench.__file__).resolve().parent.parent)
    rest = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONPATH": source if not rest else source + os.pathsep + rest}


def test_version_loads_no_runner_side_driver_gate_or_chart_module(repo_root: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-c", VERSION_PROBE],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=source_environment(),
    )

    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout.splitlines()[-1])
    assert report["code"] == EXIT_OK
    heavy = [
        name
        for name in report["loaded"]
        if any(name == part or name.startswith(part + ".") for part in HEAVY_PARTS)
    ]
    assert heavy == []
    assert "pairbench.cli.run" not in report["loaded"]


def test_version_with_another_argument_is_a_usage_error(cli: Callable[..., Any]) -> None:
    result = cli("--version", "run")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: ")
    assert result.out == ""


def test_no_command_is_a_usage_error(cli: Callable[..., Any]) -> None:
    result = cli()

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: a command is needed")
    assert result.out == ""


def test_an_unknown_command_is_a_usage_error(cli: Callable[..., Any]) -> None:
    result = cli("launch")

    assert result.code == EXIT_USAGE
    assert result.err == refusal_text(
        "E_USAGE: no command named 'launch'; pairbench --help lists them"
    )


def test_help_lists_every_command(cli: Callable[..., Any]) -> None:
    result = cli("--help")

    assert result.code == EXIT_OK
    for name in entry.COMMANDS:
        assert f"  {name}" in result.out
    assert result.err == ""


@pytest.mark.parametrize("name", sorted(entry.COMMANDS))
def test_help_of_each_command_exits_0_on_stdout(name: str, cli: Callable[..., Any]) -> None:
    result = cli(name, "--help")

    assert result.code == EXIT_OK
    assert result.out.startswith(f"usage: pairbench {name}")
    assert result.err == ""


def test_an_abbreviated_flag_is_refused(cli: Callable[..., Any]) -> None:
    result = cli("run", "--sid", "a=cmd:x")

    assert result.code == EXIT_USAGE
    assert result.err.startswith("E_USAGE: pairbench run: unrecognized arguments: --sid")


def test_a_word_outside_a_closed_set_is_refused(cli: Callable[..., Any]) -> None:
    result = cli("plan", "--side", "a=cmd:x", "--side", "b=cmd:y", "--plots", "sometimes")

    assert result.code == EXIT_USAGE
    assert "E_USAGE: pairbench plan: argument --plots: invalid choice: 'sometimes'" in result.err


def flags_of(parser: argparse.ArgumentParser) -> set[str]:
    return {
        flag
        for action in parser._actions
        for flag in action.option_strings
        if flag.startswith("--") and flag != "--help"
    }


@pytest.mark.parametrize("name", ["run", "plan"])
def test_run_and_plan_take_every_listed_flag_and_no_other(name: str) -> None:
    import importlib

    module = importlib.import_module(entry.COMMANDS[name][0])
    parser = entry.parser_for(name, "")
    module.add_arguments(parser)

    assert flags_of(parser) == set(FLAG_KEYS) | set(FLAGS_WITHOUT_KEY)


@pytest.mark.parametrize(
    ("args", "before", "after"),
    [
        ([], [], None),
        (["--rounds", "4"], ["--rounds", "4"], None),
        (["--", "x", "--y"], [], ["x", "--y"]),
        (["--rounds", "4", "--", "x"], ["--rounds", "4"], ["x"]),
        (["--side", "--", "--", "x"], ["--side", "--"], ["x"]),
        (["--set", "--", "a", "--", "b"], ["--set", "--", "a"], ["b"]),
        (["--", "--", "x"], [], ["--", "x"]),
        (["--"], [], []),
    ],
)
def test_the_separator_splits_at_the_first_double_dash_that_is_not_a_value(
    args: list[str], before: list[str], after: list[str] | None
) -> None:
    assert entry.split_separator(args) == (before, after)


def test_an_interrupt_returns_130_with_its_line(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(options: argparse.Namespace) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr("pairbench.cli.doctor.command", interrupt)

    result = cli("doctor")

    assert result.code == EXIT_INTERRUPTED
    assert result.err == refusal_text("E_INTERRUPTED: interrupted")


def test_an_unexpected_error_returns_8_with_its_kind(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(options: argparse.Namespace) -> int:
        raise RuntimeError("x")

    monkeypatch.setattr("pairbench.cli.doctor.command", broken)

    result = cli("doctor")

    assert result.code == EXIT_INTERNAL
    assert result.err == refusal_text("E_INTERNAL: RuntimeError: x")


def test_a_refusal_prints_its_line_and_returns_its_exit_code(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(options: argparse.Namespace) -> int:
        raise Refusal("E_LOCK", "x")

    monkeypatch.setattr("pairbench.cli.doctor.command", refused)

    result = cli("doctor")

    assert result.code == 4
    assert result.err == refusal_text("E_LOCK: x")
    assert result.out == ""


def test_the_plugin_switch_is_restored_after_a_command(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def turns_off(options: argparse.Namespace) -> int:
        registry.set_plugins_enabled(False)
        return EXIT_OK

    monkeypatch.setattr("pairbench.cli.doctor.command", turns_off)

    assert registry.plugins_enabled() is True
    assert cli("doctor").code == EXIT_OK
    assert registry.plugins_enabled() is True


ENDING = [n for n in ("SIGHUP", "SIGQUIT", "SIGTERM") if hasattr(signal, n)]


@pytest.fixture
def default_actions() -> Any:
    """Give each ending signal its default action for the test, as a terminal does.

    A signal the test run was started with ignored (under ``nohup``, say) stays
    ignored in the tool, so the tests that expect an interrupt start from the
    default action, and the action the run had is given back afterwards.
    """
    before = {getattr(signal, n): signal.signal(getattr(signal, n), signal.SIG_DFL) for n in ENDING}
    try:
        yield
    finally:
        for number, action in before.items():
            signal.signal(number, action)


@pytest.mark.usefixtures("default_actions")
def test_a_termination_signal_is_an_interrupt_while_a_command_runs(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = signal.getsignal(signal.SIGTERM)
    seen: list[Any] = []

    def terminated(options: argparse.Namespace) -> int:
        handler = signal.getsignal(signal.SIGTERM)
        seen.append(handler)
        assert callable(handler)
        handler(signal.SIGTERM, None)
        return EXIT_OK

    monkeypatch.setattr("pairbench.cli.doctor.command", terminated)

    result = cli("doctor")

    assert result.code == EXIT_INTERRUPTED
    assert seen[0] is not before
    assert signal.getsignal(signal.SIGTERM) is before


@pytest.mark.usefixtures("default_actions")
@pytest.mark.parametrize("name", ENDING)
def test_a_hangup_or_quit_signal_is_an_interrupt_while_a_command_runs(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    number = getattr(signal, name)
    before = signal.getsignal(number)

    def signalled(options: argparse.Namespace) -> int:
        # The default action of these signals ends the process: send one only
        # once a handler is in place.
        assert callable(signal.getsignal(number))
        os.kill(os.getpid(), number)
        return EXIT_OK

    monkeypatch.setattr("pairbench.cli.doctor.command", signalled)

    result = cli("doctor")

    assert result.code == EXIT_INTERRUPTED
    assert result.err.splitlines()[-2:] == [
        "E_INTERRUPTED: interrupted",
        DOCS_LINE + "e_interrupted",
    ]
    assert signal.getsignal(number) is before


@pytest.mark.parametrize("name", ENDING)
def test_a_signal_the_tool_was_started_with_ignored_stays_ignored(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # nohup starts a command with the hangup ignored, so that a run outlives
    # the terminal it was started from.
    number = getattr(signal, name)
    before = signal.signal(number, signal.SIG_IGN)
    seen: list[Any] = []

    def signalled(options: argparse.Namespace) -> int:
        seen.append(signal.getsignal(number))
        os.kill(os.getpid(), number)
        return EXIT_OK

    monkeypatch.setattr("pairbench.cli.doctor.command", signalled)
    try:
        result = cli("doctor")
        after = signal.getsignal(number)
    finally:
        signal.signal(number, before)

    assert result.code == EXIT_OK
    assert result.err == ""
    assert seen == [signal.SIG_IGN]
    assert after is signal.SIG_IGN


def test_the_recorded_command_line_is_redacted(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[tuple[str, ...]] = []

    def record(options: argparse.Namespace) -> int:
        recorded.append(api.recorded_command_line())
        return EXIT_OK

    monkeypatch.setattr("pairbench.cli.plan.command", record)

    cli("plan", "--set", "launch.env.API_TOKEN=x")

    assert recorded == [("pairbench", "plan", "--set", f"launch.env.API_TOKEN={REDACTED}")]
    assert api.recorded_command_line() == ()


def test_the_module_entry_runs_main(repo_root: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "pairbench", "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo_root,
        env=source_environment(),
    )

    assert done.returncode == EXIT_OK
    assert done.stdout == f"pairbench {TOOL_VERSION}\n"


# Commands whose output fills more than one write, and two of a single line.
READER_GONE_COMMANDS = (("doctor",), ("schema", "results"), ("--help",), ("--version",))
# A command that refuses, so its only output is the refusal line on standard error.
REFUSING_COMMAND = ("compare",)


def _run_with(args: tuple[str, ...], *, closed: str) -> subprocess.CompletedProcess[bytes]:
    """Run the command with one stream (``stdout`` or ``stderr``) on a pipe whose reader has gone.

    The other stream is kept, so what the command printed on it can be compared.
    """
    read_end, write_end = os.pipe()
    os.close(read_end)
    streams = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, closed: write_end}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pairbench", *args],
            stdin=subprocess.DEVNULL,
            env=source_environment(),
            timeout=120,
            check=False,
            **streams,
        )
    finally:
        os.close(write_end)


def _run_to_null(args: tuple[str, ...], *, stream: str) -> subprocess.CompletedProcess[bytes]:
    """Run the command with that stream on the null device, which takes every write."""
    streams = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, stream: subprocess.DEVNULL}
    return subprocess.run(
        [sys.executable, "-m", "pairbench", *args],
        stdin=subprocess.DEVNULL,
        env=source_environment(),
        timeout=120,
        check=False,
        **streams,
    )


@pytest.mark.parametrize("args", READER_GONE_COMMANDS, ids=" ".join)
def test_a_reader_that_has_gone_ends_the_command_quietly_with_its_own_code(
    args: tuple[str, ...],
) -> None:
    done = _run_with(args, closed="stdout")
    reference = _run_to_null(args, stream="stdout")

    assert done.stderr == reference.stderr
    assert "BrokenPipeError" not in done.stderr.decode("utf-8", "replace")
    assert done.returncode == reference.returncode


def test_a_refusal_whose_error_reader_has_gone_still_returns_the_refusal_s_code() -> None:
    done = _run_with(REFUSING_COMMAND, closed="stderr")
    reference = _run_to_null(REFUSING_COMMAND, stream="stderr")

    assert reference.returncode == EXIT_USAGE
    assert (done.returncode, done.stdout) == (EXIT_USAGE, b"")


class ClosedPipe:
    """A text stream whose reader has gone: every write and flush fails as a closed pipe does."""

    def write(self, text: str) -> int:
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self) -> None:
        raise BrokenPipeError(32, "Broken pipe")


def test_a_closed_standard_output_drops_the_rest_and_keeps_the_command_going(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[int] = []

    def command(options: argparse.Namespace) -> int:
        print("first line")
        print("second line")
        seen.append(EXIT_OK)
        return 3

    module = argparse.Namespace(add_arguments=lambda parser: None, command=command)
    monkeypatch.setitem(entry.COMMANDS, "made-up", ("made_up_module", "a made-up command"))
    monkeypatch.setattr(entry.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(sys, "stdout", ClosedPipe())

    code = entry.main(["made-up"])

    assert (code, seen) == (3, [EXIT_OK])
    assert capsys.readouterr().err == ""


class GoneTerminal:
    """A stream on a terminal that has closed: every write and flush fails with an I/O error."""

    def write(self, text: str) -> int:
        raise OSError(errno.EIO, "Input/output error")

    def flush(self) -> None:
        raise OSError(errno.EIO, "Input/output error")

    def isatty(self) -> bool:
        return True


class FailingFile(GoneTerminal):
    """A file whose writes fail with an I/O error: a real failure, not a closed reader."""

    def isatty(self) -> bool:
        return False


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_a_closed_terminal_drops_the_rest_and_keeps_the_command_going(
    monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    seen: list[int] = []

    def command(options: argparse.Namespace) -> int:
        print("first line", file=getattr(sys, stream))
        print("second line", file=getattr(sys, stream))
        seen.append(EXIT_OK)
        return 3

    module = argparse.Namespace(add_arguments=lambda parser: None, command=command)
    monkeypatch.setitem(entry.COMMANDS, "made-up", ("made_up_module", "a made-up command"))
    monkeypatch.setattr(entry.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(sys, stream, GoneTerminal())

    code = entry.main(["made-up"])

    assert (code, seen) == (3, [EXIT_OK])


def test_an_io_error_on_a_file_is_not_taken_for_a_closed_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def command(options: argparse.Namespace) -> int:
        print("a line")
        return 3

    module = argparse.Namespace(add_arguments=lambda parser: None, command=command)
    monkeypatch.setitem(entry.COMMANDS, "made-up", ("made_up_module", "a made-up command"))
    monkeypatch.setattr(entry.importlib, "import_module", lambda name: module)
    monkeypatch.setattr(sys, "stdout", FailingFile())

    code = entry.main(["made-up"])

    assert code == EXIT_INTERNAL
    assert capsys.readouterr().err == refusal_text(
        "E_INTERNAL: OSError: [Errno 5] Input/output error"
    )


# Runs as the session leader on a pseudo terminal it makes its controlling
# terminal, with the hangup at its default action, then becomes pairbench.
ON_A_TERMINAL = """
import fcntl, os, signal, sys, termios
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
signal.signal(signal.SIGHUP, signal.SIG_DFL)
os.execv(sys.executable, [sys.executable, "-m", "pairbench", *sys.argv[1:]])
"""
# The command the gate runs: it says it has started, then waits for the hangup.
STARTED_THEN_WAITS = "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(60)"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs a Linux pseudo terminal")
def test_a_command_whose_terminal_closes_ends_as_an_interrupt(tmp_path: Path) -> None:
    import pty

    started = tmp_path / "started"
    try:
        leader, follower = pty.openpty()
    except OSError as exc:
        pytest.skip(f"no pseudo terminal can be opened here: {exc}")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                ON_A_TERMINAL,
                "gate",
                "wait-quiet",
                "--set",
                "gates.quiet.max_busy_cores=100000",
                "--set",
                "gates.quiet.samples=1",
                "--set",
                "gates.quiet.interval_s=0.05",
                "--",
                sys.executable,
                "-c",
                STARTED_THEN_WAITS,
                str(started),
            ],
            stdin=follower,
            stdout=follower,
            stderr=follower,
            start_new_session=True,
            cwd=tmp_path,
            env=source_environment(),
        )
    finally:
        os.close(follower)
    try:
        deadline = time.monotonic() + 60
        while not started.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists()
        os.close(leader)
        leader = -1
        code = process.wait(timeout=60)
    finally:
        if leader != -1:
            os.close(leader)
        if process.poll() is None:
            process.kill()
            process.wait()

    assert code == EXIT_INTERRUPTED
