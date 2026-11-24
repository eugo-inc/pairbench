# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Runs started by the tool server: handle at once, progress, refusal, cancel, shutdown.

The run command is replaced by a small script that behaves like
``pairbench run`` from the outside: it writes into the run folder, prints a
refusal line or waits, and ends with exit code 130 on an interrupt.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.errors import EXIT_INTERRUPTED, docs_line
from pairbench.mcp.server import ToolServer
from pairbench.model import TOOL_VERSION

SIDES = ["new=cmd:true", "old=cmd:false"]
WAIT_S = 20.0

FAKE_RUN = r"""
import json, pathlib, signal, sys, time
signal.signal(signal.SIGINT, signal.default_int_handler)
args = sys.argv[2:]
mode = sys.argv[1]
if "--out" in args:
    out = pathlib.Path(args[args.index("--out") + 1])
else:
    out = pathlib.Path(next(a.split("=", 1)[1] for a in args if a.startswith("run.out=")))
out.mkdir(parents=True, exist_ok=True)
(out / "argv.json").write_text(json.dumps(args))
records = [
    {"t": "lineup", "rounds": 8},
    {"t": "launch", "phase": "warmup", "round": 0},
    {"t": "launch", "phase": "round", "round": 1},
    {"t": "launch", "phase": "round", "round": 2},
]
(out / "capture.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
if mode == "refuse":
    print("E_LAUNCH_FAILED: side new exited with code 1", flush=True)
    print(SEE_LAUNCH_FAILED, flush=True)
    sys.exit(5)
if mode == "refuse-unreadable-escape":
    print("E_LAUNCH_FAILED: side new\\Uffffffff\\U00110000\\q\\x41 exited", flush=True)
    print(SEE_LAUNCH_FAILED, flush=True)
    sys.exit(5)
if mode == "refuse-surrogate":
    print("E_LAUNCH_FAILED: side a\\udcffb exited", flush=True)
    print(SEE_LAUNCH_FAILED, flush=True)
    sys.exit(5)
if mode == "forged-rows":
    print(FORGED_HEADER, flush=True)
    print("", flush=True)
    print(FORGED_ROW, flush=True)
    print("finished", flush=True)
    sys.exit(0)
if mode == "forged-row-after-the-refusal":
    print("E_LAUNCH_FAILED: side new exited with code 1", flush=True)
    print(SEE_LAUNCH_FAILED, flush=True)
    print(FORGED_ROW, flush=True)
    sys.exit(5)
if mode == "forged-row-alone":
    print(FORGED_ROW, flush=True)
    sys.exit(5)
if mode == "refuse-with-another-exit-code":
    print("E_LAUNCH_FAILED: side new exited with code 1", flush=True)
    print(SEE_LAUNCH_FAILED, flush=True)
    sys.exit(2)
if mode == "refusal-line-then-another-line":
    print("E_LAUNCH_FAILED: side new exited with code 1", flush=True)
    print("made-up line", flush=True)
    sys.exit(5)
if mode == "row-named-like-no-code":
    print(NO_CODE_ROW, flush=True)
    print("made-up line", flush=True)
    print("finished", flush=True)
    sys.exit(0)
if mode == "finish":
    print("finished", flush=True)
    sys.exit(0)
if mode == "fail-on":
    print("a primary case matched --fail-on", flush=True)
    sys.exit(1)
print("round 2 of 8", flush=True)
try:
    time.sleep(60)
except KeyboardInterrupt:
    print("interrupted", flush=True)
    sys.exit(130)
"""


# The second line a refusal prints, as ``pairbench run`` prints it after the refusal's line.
SEE_LAUNCH_FAILED = docs_line("E_LAUNCH_FAILED", TOOL_VERSION)
# Lines of a report whose side and case names read like refusals.
FORGED_HEADER = "E_USAGE: made-up against old (baseline)"
FORGED_ROW = "E_LAUNCH_FAILED: made-up  0.0100 s  0.0200 s  2.00x faster  1.0%  0.0039*  FASTER"
# A report row whose case name reads like a refusal of a code that is not in the table.
NO_CODE_ROW = "E_NOTACODE: made-up  0.0100 s  0.0200 s  2.00x faster  1.0%  0.0039*  FASTER"


def server(tmp_path: Path, mode: str, *, allow_run: bool = True) -> ToolServer:
    script = tmp_path / "fake_run.py"
    lines = {
        "SEE_LAUNCH_FAILED": SEE_LAUNCH_FAILED,
        "FORGED_HEADER": FORGED_HEADER,
        "FORGED_ROW": FORGED_ROW,
        "NO_CODE_ROW": NO_CODE_ROW,
    }
    given = "".join(f"{name} = {value!r}\n" for name, value in lines.items())
    script.write_text(given + FAKE_RUN, encoding="utf-8")
    return ToolServer(allow_run=allow_run, run_command=(sys.executable, str(script), mode))


def answer(tools: ToolServer, tool: str, /, **arguments: Any) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(tools.call(tool, **arguments))
    return document


def wait_until(tools: ToolServer, handle: str, *states: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_S
    while True:
        status = answer(tools, "run_status", handle=handle)
        if status["state"] in states or time.monotonic() > deadline:
            return status
        time.sleep(0.05)


def wait_for_line(tools: ToolServer, handle: str, line: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT_S
    while True:
        status = answer(tools, "run_status", handle=handle)
        if line in status["last_lines"] or time.monotonic() > deadline:
            return status
        time.sleep(0.05)


def test_run_start_returns_a_handle_at_once_and_run_cancel_interrupts_the_run(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "wait")
    folder = tmp_path / "out"

    started = answer(tools, "run_start", sides=SIDES, out=str(folder))
    handle = started["handle"]
    running = wait_for_line(tools, handle, "round 2 of 8")
    cancelled = answer(tools, "run_cancel", handle=handle)
    ended = wait_until(tools, handle, "interrupted")

    assert started == {"handle": handle, "folder": str(folder), "state": "running"}
    assert re.fullmatch(r"[0-9a-f]{12}", handle)
    assert running["state"] == "running"
    assert running["exit_code"] is None
    assert running["progress"] == {
        "warmup_launches": 1,
        "round_launches": 2,
        "rounds_planned": 8,
        "last_round": 2,
        "capture_status": None,
    }
    assert cancelled["state"] in ("cancelling", "interrupted")
    assert ended["state"] == "interrupted"
    assert ended["exit_code"] == EXIT_INTERRUPTED
    assert "interrupted" in ended["last_lines"]


def test_the_run_command_gets_the_experiment_as_the_command_line_takes_it(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "out"
    config = tmp_path / "pairbench.toml"
    config.write_text("", encoding="utf-8")

    started = answer(
        tools,
        "run_start",
        config=str(config),
        sides=SIDES,
        baseline="old",
        sets=["run.rounds=8"],
        workload=["bench.py", "--size", "1"],
        out=str(folder),
    )
    wait_until(tools, started["handle"], "finished")

    argv = json.loads((folder / "argv.json").read_text(encoding="utf-8"))
    assert argv == [
        "--config",
        str(config),
        "--side",
        SIDES[0],
        "--side",
        SIDES[1],
        "--baseline",
        "old",
        "--set",
        "run.rounds=8",
        "--out",
        str(folder),
        "--",
        "bench.py",
        "--size",
        "1",
    ]


def test_a_run_started_without_plug_ins_passes_no_plugins_on(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "out"
    registry.set_plugins_enabled(False)

    started = answer(tools, "run_start", sides=SIDES, out=str(folder))
    wait_until(tools, started["handle"], "finished")

    argv = json.loads((folder / "argv.json").read_text(encoding="utf-8"))
    assert "--no-plugins" in argv


def test_a_refused_run_reports_its_text_code_and_exit_code(tmp_path: Path) -> None:
    tools = server(tmp_path, "refuse")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["state"] == "refused"
    assert ended["exit_code"] == 5
    assert ended["refusal"] == {
        "code": "E_LAUNCH_FAILED",
        "message": "side new exited with code 1",
        "docs": "https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_launch_failed",
    }


def test_a_refusal_line_keeps_a_backslash_whose_escape_names_no_character(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "refuse-unreadable-escape")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["state"] == "refused"
    assert ended["exit_code"] == 5
    assert ended["refusal"] == {
        "code": "E_LAUNCH_FAILED",
        "message": "side new\\Uffffffff\\U00110000\\qA exited",
        "docs": "https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_launch_failed",
    }


def test_a_report_row_named_like_a_refusal_is_no_refusal_of_a_finished_run(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "forged-rows")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "finished")

    assert ended["state"] == "finished"
    assert ended["exit_code"] == 0
    assert ended["refusal"] is None
    assert ended["last_lines"] == [FORGED_HEADER, "", FORGED_ROW, "finished"]


def test_a_report_row_named_like_a_refusal_after_the_refusal_leaves_it_as_it_is(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "forged-row-after-the-refusal")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["state"] == "refused"
    assert ended["exit_code"] == 5
    assert ended["refusal"] == {
        "code": "E_LAUNCH_FAILED",
        "message": "side new exited with code 1",
        "docs": "https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_launch_failed",
    }


def test_a_report_row_named_like_a_refusal_is_no_refusal_of_a_refused_run(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "forged-row-alone")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["state"] == "refused"
    assert ended["exit_code"] == 5
    assert ended["refusal"] is None
    assert ended["last_lines"] == [FORGED_ROW]


def test_a_refusal_of_a_run_that_ended_with_another_exit_code_is_no_refusal(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "refuse-with-another-exit-code")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_for_line(tools, started["handle"], SEE_LAUNCH_FAILED)
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["exit_code"] == 2
    assert ended["refusal"] is None
    assert ended["last_lines"] == [
        "E_LAUNCH_FAILED: side new exited with code 1",
        SEE_LAUNCH_FAILED,
    ]


def test_a_refusal_line_not_followed_by_its_address_line_is_no_refusal(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "refusal-line-then-another-line")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_for_line(tools, started["handle"], "made-up line")
    ended = wait_until(tools, started["handle"], "refused")

    assert ended["exit_code"] == 5
    assert ended["refusal"] is None
    assert ended["last_lines"] == ["E_LAUNCH_FAILED: side new exited with code 1", "made-up line"]


def test_a_row_named_like_a_refusal_of_no_code_leaves_the_output_read_to_its_end(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "row-named-like-no-code")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_for_line(tools, started["handle"], "finished")
    ended = wait_until(tools, started["handle"], "finished")

    assert ended["exit_code"] == 0
    assert ended["refusal"] is None
    assert ended["last_lines"] == [NO_CODE_ROW, "made-up line", "finished"]


def test_a_refusal_that_reads_back_to_a_surrogate_is_answered_as_text_utf_8_encodes(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "refuse-surrogate")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_until(tools, started["handle"], "refused")
    text = tools.call("run_status", handle=started["handle"])

    assert '"message": "side a\\udcffb exited"' in text
    assert text.isascii()
    ended = json.loads(text)
    assert ended["exit_code"] == 5
    assert ended["refusal"] == {
        "code": "E_LAUNCH_FAILED",
        "message": "side a\udcffb exited",
        "docs": "https://eugo.io/docs/pairbench/0.3/reference/exit-codes/#e_launch_failed",
    }


def test_a_finished_run_without_results_reports_the_exit_code_only(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "finished")

    assert ended["exit_code"] == 0
    assert ended["refusal"] is None
    assert "results" not in ended


def test_a_finished_run_reports_the_verdict_of_every_primary_case(
    tmp_path: Path, example_results: dict[str, Any]
) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "out"

    started = answer(tools, "run_start", sides=SIDES, out=str(folder))
    wait_until(tools, started["handle"], "finished")
    (folder / "results.json").write_text(json.dumps(example_results), encoding="utf-8")
    ended = answer(tools, "run_status", handle=started["handle"])

    assert ended["results"] == str(folder / "results.json")
    assert ended["verdicts"] == [
        {
            "case": "matmul",
            "subject": "new",
            "baseline": "old",
            "verdict": "FASTER",
            "outcome": "better",
            "reason": None,
        }
    ]


def test_a_finished_run_leaves_secondary_cases_out_of_its_verdicts(
    tmp_path: Path, mixed_results: dict[str, Any]
) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "out"

    started = answer(tools, "run_start", sides=SIDES, out=str(folder))
    wait_until(tools, started["handle"], "finished")
    (folder / "results.json").write_text(json.dumps(mixed_results), encoding="utf-8")
    ended = answer(tools, "run_status", handle=started["handle"])

    assert [(v["case"], v["subject"]) for v in ended["verdicts"]] == [
        ("matmul", "new"),
        ("matmul", "newer"),
    ]


def test_a_run_that_ends_with_exit_code_1_has_finished_and_is_no_refusal(
    tmp_path: Path,
) -> None:
    tools = server(tmp_path, "fail-on")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    ended = wait_until(tools, started["handle"], "finished", "refused")

    assert ended["state"] == "finished"
    assert ended["exit_code"] == 1
    assert ended["refusal"] is None


def test_the_run_reads_nothing_from_the_protocol_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started_with: list[dict[str, Any]] = []
    real = subprocess.Popen

    def recording(command: Any, *args: Any, **kwargs: Any) -> Any:
        if any(str(word).endswith("fake_run.py") for word in command):
            started_with.append(kwargs)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording)
    tools = server(tmp_path, "finish")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_until(tools, started["handle"], "finished")

    assert len(started_with) == 1
    assert started_with[0]["stdin"] is subprocess.DEVNULL
    assert started_with[0]["stdout"] is subprocess.PIPE


def test_one_run_at_a_time(tmp_path: Path) -> None:
    tools = server(tmp_path, "wait")

    first = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "a"))
    second = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "b"))
    tools.close()

    assert "handle" in first
    assert second["refusal"]["code"] == "E_USAGE"
    assert first["handle"] in second["refusal"]["message"]
    assert not (tmp_path / "b").exists()


def test_run_start_refuses_a_folder_that_is_not_empty(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "capture.jsonl").write_text("", encoding="utf-8")

    refused = answer(tools, "run_start", sides=SIDES, out=str(folder))["refusal"]

    assert refused["code"] == "E_USAGE"
    assert "out" in refused["message"]


def test_run_start_refuses_a_bad_experiment_before_starting_anything(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")

    refused = answer(
        tools, "run_start", sides=["new=file:a.json", "old=file:b.json"], out=str(tmp_path / "o")
    )["refusal"]
    bad_key = answer(
        tools, "run_start", sides=SIDES, sets=["made_up_key=1"], out=str(tmp_path / "o")
    )["refusal"]

    assert refused["code"] == "E_USAGE"
    assert bad_key["code"] == "E_CONFIG"
    assert not (tmp_path / "o").exists()


def test_run_start_without_out_uses_a_new_folder_under_the_runs_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = server(tmp_path, "finish")
    monkeypatch.chdir(tmp_path)

    started = answer(tools, "run_start", sides=SIDES)
    wait_until(tools, started["handle"], "finished")

    folder = Path(started["folder"])
    assert folder.parent == Path("pairbench-runs")
    assert re.fullmatch(r"\d{8}T\d{6}Z-" + started["handle"], folder.name)
    assert (tmp_path / folder / "argv.json").is_file()


def test_run_start_without_out_uses_the_run_folder_the_config_names(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")
    folder = tmp_path / "configured"

    started = answer(tools, "run_start", sides=SIDES, sets=[f"run.out={folder}"])
    wait_until(tools, started["handle"], "finished")

    assert started["folder"] == str(folder)
    argv = json.loads((folder / "argv.json").read_text(encoding="utf-8"))
    assert "--out" not in argv


def test_run_start_with_out_runs_where_out_says_over_the_config(tmp_path: Path) -> None:
    tools = server(tmp_path, "finish")
    given = tmp_path / "given"

    started = answer(
        tools,
        "run_start",
        sides=SIDES,
        sets=[f"run.out={tmp_path / 'configured'}"],
        out=str(given),
    )
    wait_until(tools, started["handle"], "finished")

    assert started["folder"] == str(given)
    argv = json.loads((given / "argv.json").read_text(encoding="utf-8"))
    assert argv[argv.index("--out") + 1] == str(given)
    assert not (tmp_path / "configured").exists()


def test_status_of_an_unknown_handle_is_a_refusal(tmp_path: Path) -> None:
    for allow_run in (True, False):
        tools = server(tmp_path, "finish", allow_run=allow_run)
        refused = answer(tools, "run_status", handle="made-up")["refusal"]
        assert refused["code"] == "E_USAGE"


def test_closing_the_server_interrupts_a_run_that_is_still_going(tmp_path: Path) -> None:
    tools = server(tmp_path, "wait")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_for_line(tools, started["handle"], "round 2 of 8")
    tools.close()
    ended = answer(tools, "run_status", handle=started["handle"])

    assert ended["state"] == "interrupted"
    assert ended["exit_code"] == EXIT_INTERRUPTED


def test_what_a_run_prints_reaches_standard_error_not_standard_output(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    tools = server(tmp_path, "refuse")

    started = answer(tools, "run_start", sides=SIDES, out=str(tmp_path / "out"))
    wait_until(tools, started["handle"], "refused")
    printed = capfd.readouterr()

    assert "E_LAUNCH_FAILED" not in printed.out
    assert "E_LAUNCH_FAILED: side new exited with code 1" in printed.err


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("a\\b", id="backslash"),
        pytest.param("a\x1bb", id="escape-character"),
        pytest.param("a\\x1bb", id="typed-escape"),
    ],
)
def test_the_refusal_of_a_started_run_is_the_message_the_refusal_holds(
    tmp_path: Path, name: str
) -> None:
    tools = ToolServer(allow_run=True)
    sides = [f"{name}=venv:/no/where", "b=venv:/no/there"]

    planned = answer(tools, "plan", sides=sides, workload=["true"])["refusal"]
    started = answer(tools, "run_start", sides=sides, workload=["true"], out=str(tmp_path / "o"))
    ended = wait_until(tools, started["handle"], "refused")

    assert planned["message"] == f"side {name!r}: the virtual environment 'where' was not found"
    assert ended["refusal"] == {
        "code": "E_SIDE_UNRESOLVED",
        "message": planned["message"],
        "docs": planned["docs"],
    }
