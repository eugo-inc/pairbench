# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The note after a run: what the shared files show of the command, and where secrets belong.

``pairbench run`` prints it once on standard error after the verdicts of a
run that finished, and after the last write of the results of a run that was
refused or interrupted once results were written, before the refusal's lines.
``pairbench compare`` prints it when it writes results files or prints the
results document. A refusal that writes no results prints no such note.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.cli.common import NOTE_COMMAND_SHOWN, command_shown_message
from pairbench.errors import (
    CONFIG_PAGE,
    EXIT_ANALYSIS,
    EXIT_CHECK_FAILED,
    EXIT_INTERRUPTED,
    EXIT_LAUNCH,
    EXIT_OK,
    EXIT_USAGE,
    SHARED_COMMAND_ANCHOR,
    section_address,
)
from pairbench.mcp.server import ToolServer

ADDRESS = "https://eugo.io/docs/pairbench/0.2/reference/config/#what-the-shared-files-hide"
NOTE = (
    "pairbench: note: command_shown: results.json, results.md and report.html show the "
    "command with each --side spec, each --set value and the secret forms pairbench "
    "recognises hidden, and each absolute path cut to its last part "
    "(report.include_image_refs shows image references); put secrets in environment "
    f"variables: {ADDRESS}"
)
SRC = Path(__file__).resolve().parents[3] / "src"
# ``pairbench run`` started from this source tree, as the tool server starts it.
RUN_FROM_SOURCE = (
    "import sys; sys.path.insert(0, sys.argv.pop(1)); "
    "from pairbench.cli.main import main; sys.exit(main(['run', *sys.argv[1:]]))"
)
WAIT_S = 60.0
LAUNCH_FAILED = "E_LAUNCH_FAILED: the warm-up launch of 'new' exited with 1"
INTERRUPTED = "E_INTERRUPTED: interrupted after the results were written"
INCOMPLETE = "E_CAPTURE_INCOMPLETE: the capture "
SEE = "pairbench: see https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#"
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "6",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
)


def run(cli: Any, *flags: str, new: str = "true") -> Any:
    """``pairbench run`` of two command sides that run ``true``, one through ``env``.

    Neither side has a twin, so the one case is NO VERDICT. ``new`` replaces
    the command of the side ``new``.
    """
    return cli(
        "run",
        "--side",
        f"new=cmd:{new}",
        "--side",
        "old=cmd:env true",
        "--baseline",
        "old",
        *QUICK,
        *flags,
        "--out",
        "run",
    )


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_note_names_the_section_that_lists_the_forms() -> None:
    assert NOTE_COMMAND_SHOWN == "command_shown"
    assert section_address(CONFIG_PAGE, SHARED_COMMAND_ANCHOR, "0.2.1") == ADDRESS
    assert f"pairbench: note: {NOTE_COMMAND_SHOWN}: {command_shown_message()}" == NOTE


# The pages that say what the note says, and the part of it each must hold.
NOTE_PAGES = ("docs/reference/commands.md", "skills/pairbench/SKILL.md")
PATH_CUT = "each absolute path cut to its last part"


@pytest.mark.parametrize("relative", NOTE_PAGES)
def test_a_page_that_repeats_the_note_says_each_absolute_path_is_cut(relative: str) -> None:
    text = " ".join((SRC.parent / relative).read_text(encoding="utf-8").split())

    assert PATH_CUT in NOTE
    assert PATH_CUT in text


def test_a_run_prints_the_note_once_as_its_last_line(cli: Any, in_tmp: Path) -> None:
    result = run(cli)

    assert result.code == EXIT_OK
    assert result.err.splitlines().count(NOTE) == 1
    assert result.err.splitlines()[-1] == NOTE
    assert NOTE not in result.out


def test_under_json_the_note_follows_the_verdicts_and_stays_off_standard_output(
    cli: Any, in_tmp: Path
) -> None:
    result = run(cli, "--json")

    assert result.code == EXIT_OK
    assert json.loads(result.out)["schema"] == "pairbench/results/v1"
    lines = result.err.splitlines()
    assert lines.count(NOTE) == 1
    assert lines[-1] == NOTE
    assert any(line.split() == ["new", "against", "old", "(baseline)"] for line in lines[:-1])


def test_a_run_that_fails_on_an_outcome_still_prints_the_note_once(cli: Any, in_tmp: Path) -> None:
    result = run(cli, "--fail-on", "no_verdict")

    assert result.code == EXIT_CHECK_FAILED
    lines = result.err.splitlines()
    assert lines.count(NOTE) == 1
    assert lines[-1] == NOTE
    assert "pairbench: --fail-on no_verdict: case wall of side new against old" in lines[:-1]


def test_a_run_whose_launch_fails_prints_the_note_before_the_refusal(
    cli: Any, in_tmp: Path
) -> None:
    result = run(cli, new="false")

    assert result.code == EXIT_LAUNCH
    assert (in_tmp / "run" / "results.json").is_file()
    lines = result.err.splitlines()
    assert lines.count(NOTE) == 1
    assert lines[-3:] == [NOTE, LAUNCH_FAILED, SEE + "e_launch_failed"]


def test_a_run_interrupted_after_the_results_prints_the_note_before_the_refusal(
    cli: Any, in_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(pairbench, "explain", interrupt)
    result = cli(
        "run",
        "--side",
        "new=cmd:true",
        "--side",
        "old=cmd:env true",
        "--baseline",
        "old",
        *QUICK[:-4],
        "--explain",
        "always",
        "--plots",
        "off",
        "--out",
        "run",
    )

    assert result.code == EXIT_INTERRUPTED
    lines = result.err.splitlines()
    assert lines.count(NOTE) == 1
    assert lines[-3:] == [NOTE, INTERRUPTED, SEE + "e_interrupted"]


def test_a_refused_run_prints_no_note(cli: Any, in_tmp: Path) -> None:
    result = cli("run", "--side", "new=cmd:true", "--rounds", "0", "--", "true")

    assert result.code == EXIT_USAGE
    assert NOTE not in result.err


@pytest.fixture
def capture_file(cli: Any, in_tmp: Path) -> Path:
    assert run(cli).code == EXIT_OK
    return in_tmp / "run" / "capture.jsonl"


@pytest.mark.parametrize(
    ("flags", "noted"),
    [
        (("--out", "again"), True),
        (("--json",), True),
        ((), False),
    ],
)
def test_compare_prints_the_note_when_it_writes_or_prints_results(
    cli: Any, capture_file: Path, flags: tuple[str, ...], noted: bool
) -> None:
    result = cli("compare", str(capture_file), *flags)

    assert result.code == EXIT_OK
    assert result.err.splitlines().count(NOTE) == (1 if noted else 0)
    if noted:
        assert result.err.splitlines()[-1] == NOTE


@pytest.fixture
def failed_capture(cli: Any, in_tmp: Path) -> Path:
    assert run(cli, new="false").code == EXIT_LAUNCH
    return in_tmp / "run" / "capture.jsonl"


@pytest.mark.parametrize(
    ("flags", "noted"),
    [
        (("--out", "again"), True),
        (("--json",), True),
        ((), False),
    ],
)
def test_a_refused_compare_prints_the_note_when_it_writes_or_prints_results(
    cli: Any, failed_capture: Path, flags: tuple[str, ...], noted: bool
) -> None:
    result = cli("compare", str(failed_capture), *flags)

    assert result.code == EXIT_ANALYSIS
    lines = result.err.splitlines()
    assert lines.count(NOTE) == (1 if noted else 0)
    assert lines[-2].startswith(INCOMPLETE)
    assert lines[-1] == SEE + "e_capture_incomplete"
    if noted:
        assert lines[-3] == NOTE


def test_the_tool_server_shows_the_note_as_the_last_line_of_a_finished_run(in_tmp: Path) -> None:
    tools = ToolServer(
        allow_run=True, run_command=(sys.executable, "-c", RUN_FROM_SOURCE, str(SRC))
    )
    sets = [
        "gates.mode=off",
        "run.rounds=6",
        "run.same_vs_same=off",
        "controls.positive=off",
        "explain.mode=off",
        "plots.mode=off",
    ]
    started = tools.run_start(
        sides=["new=cmd:true", "old=cmd:env true"], baseline="old", sets=sets, out="run"
    )
    deadline = time.monotonic() + WAIT_S
    status = tools.run_status(started["handle"])
    while status["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.1)
        status = tools.run_status(started["handle"])

    assert status["exit_code"] == EXIT_OK
    assert status["last_lines"].count(NOTE) == 1
    assert status["last_lines"][-1] == NOTE
