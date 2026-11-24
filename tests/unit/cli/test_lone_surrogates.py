# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A lone surrogate is refused only where the results would hold it.

A JSON text can write a surrogate that stands alone, such as ``"\\ud800"``. Such a text is
not UTF-8 text. A run refuses a case, a metric, a unit or a tool version a driver read that
holds one with ``E_LAUNCH_FAILED``, quoting the case as the results show it, its secret forms
hidden and its paths cut, and no key of the tool's output; the message shows the text escaped
as ``errors.printable`` writes it. A text of the tool's output that no driver reads, under any
key, or a folder that the cut of a case id leaves out, is read as it is. A capture that holds
one is read, and its terminal report shows it as ``?``. A byte that is not UTF-8 in an
argument, a variable or a name, which Python reads as a lone surrogate, is kept in the capture
where the results hide it or cut it away, and the run, and a compare of its capture, finish;
where the results would show it, as in an argument of the workload or the setting
``run.node_type``, a run refuses it before it makes the run folder, naming the place and not
the text, and results that would hold one are refused before either results file is written.
A run of the Python API, which writes no results, makes none of these early refusals: its
capture keeps the text as an escape, and its terminal report shows it as ``?``.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pairbench

from .conftest import COMMAND_NOTE, refusal_text

Cli = Callable[..., Any]

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _gbench(name: str, version: str = "v1.9.4") -> str:
    entry = {"run_type": "iteration", "iterations": 10, "time_unit": "ms"}
    return json.dumps(
        {
            "context": {"library_version": version},
            "benchmarks": [
                {**entry, "name": name, "real_time": 2.0, "cpu_time": 1.0},
                {**entry, "name": "BM_Plain", "real_time": 3.0, "cpu_time": 2.0},
            ],
        }
    )


def _compare(cli: Cli, tmp_path: Path, driver: str, name: str, text: str, *more: str) -> Any:
    for side in ("new", "old"):
        (tmp_path / side).mkdir()
        (tmp_path / side / name).write_text(text, encoding="utf-8")
    return cli(
        "compare",
        "--side",
        f"new=file:{tmp_path}/new/{name}",
        "--side",
        f"old=file:{tmp_path}/old/{name}",
        "--driver",
        driver,
        "--out",
        tmp_path / "out",
        *more,
    )


def test_a_gbench_case_named_with_a_lone_surrogate_is_refused_naming_it(
    cli: Cli, tmp_path: Path
) -> None:
    result = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_\ud800"))

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the case BM_\\\\ud800 holds a lone surrogate, which is "
        "not UTF-8 text"
    )
    kept = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [r["message"] for r in kept["refusals"]] == [
        "side 'new': the case BM_\\ud800 holds a lone surrogate, which is not UTF-8 text"
    ]


def test_a_tool_version_with_a_lone_surrogate_is_refused(cli: Cli, tmp_path: Path) -> None:
    result = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_X", "v1.9\udcff"))

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the tool version v1.9\\\\udcff holds a lone surrogate, "
        "which is not UTF-8 text"
    )


def test_a_surrogate_pair_in_a_gbench_case_name_is_read(cli: Cli, tmp_path: Path) -> None:
    result = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_\U0001f680"), "--json")

    assert result.code == 0
    assert [case["id"] for case in json.loads(result.out)["cases"]][:2] == [
        "BM_\U0001f680",
        "BM_\U0001f680/cpu_time",
    ]


def _with_unread_surrogate(doc: Any) -> Any:
    """Return a driver's document with one more member, a text no driver reads that holds a
    lone surrogate, as a tool writes a folder name that is not UTF-8 into its own record."""
    extra = {"made_up_folder": "w\udcffk"}
    if isinstance(doc, list):
        return [{**doc[0], **extra}, *doc[1:]]
    return {**doc, **extra}


@pytest.mark.parametrize(
    ("driver", "fixture", "more"),
    [
        pytest.param("gbench", "drivers/gbench/gbench.json", (), id="gbench"),
        pytest.param("nvbench", "drivers/nvbench/nvbench.json", (), id="nvbench"),
        pytest.param(
            "pytest-benchmark",
            "drivers/pytest-benchmark/pytest-benchmark.json",
            (),
            id="pytest-benchmark",
        ),
        pytest.param("hyperfine", "drivers/hyperfine/hyperfine-v1.json", (), id="hyperfine"),
        pytest.param("llama-bench", "drivers/llama-bench/stdout.txt", (), id="llama-bench"),
        pytest.param(
            "guidellm", "serving/guidellm/guidellm-c1.json", ("--levels", "1"), id="guidellm"
        ),
        pytest.param(
            "vllm-bench",
            "serving/vllm-bench/vllm-bench-c1.json",
            ("--levels", "1"),
            id="vllm-bench",
        ),
        pytest.param(
            "aiperf",
            "serving/aiperf/aiperf-c2/profile_export.jsonl",
            ("--levels", "2"),
            id="aiperf",
        ),
    ],
)
def test_every_json_driver_reads_output_with_a_lone_surrogate_where_it_reads_nothing(
    cli: Cli, tmp_path: Path, driver: str, fixture: str, more: tuple[str, ...]
) -> None:
    source = FIXTURES / fixture
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        changed = "".join(json.dumps(_with_unread_surrogate(r)) + "\n" for r in records)
    else:
        changed = json.dumps(_with_unread_surrogate(json.loads(text)))
    for side, body in (("new", changed), ("old", text), ("plain", text)):
        (tmp_path / side).mkdir()
        (tmp_path / side / source.name).write_text(body, encoding="utf-8")

    def cases(new: str) -> Any:
        result = cli(
            "compare",
            "--side",
            f"new=file:{tmp_path}/{new}/{source.name}",
            "--side",
            f"old=file:{tmp_path}/old/{source.name}",
            "--driver",
            driver,
            "--json",
            *more,
        )
        assert result.code == 0, result.err
        return [case["id"] for case in json.loads(result.out)["cases"]]

    assert "\\udcff" in changed
    shown = cases("new")
    assert shown == cases("plain")
    assert shown


def test_the_lines_driver_refuses_a_case_with_a_lone_surrogate(cli: Cli, tmp_path: Path) -> None:
    line = "::pairbench:: " + json.dumps({"case": "a\udfff", "value": 1}) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the case a\\\\udfff holds a lone surrogate, which is not "
        "UTF-8 text"
    )


def test_the_lines_driver_refuses_a_unit_with_a_lone_surrogate(cli: Cli, tmp_path: Path) -> None:
    line = "::pairbench:: " + json.dumps({"case": "c1", "value": 1, "unit": "s\udcff"}) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the unit of case 'c1': s\\\\udcff holds a lone "
        "surrogate, which is not UTF-8 text"
    )


def test_the_lines_driver_names_an_unknown_key_that_holds_a_lone_surrogate(
    cli: Cli, tmp_path: Path
) -> None:
    record = {"case": "c1", "value": 1, "unit": "s", "where": "l\udcffd"}
    line = "::pairbench:: " + json.dumps(record) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: stdout.txt line 1: unknown key 'where'; a line holds case, value, "
        "unit, better"
    )


def test_a_case_named_by_a_path_through_a_folder_that_is_not_utf_8_is_read(
    cli: Cli, tmp_path: Path
) -> None:
    case = f"{tmp_path}/l\udcffd/input.dat"
    line = "::pairbench:: " + json.dumps({"case": case, "value": 1.0, "unit": "s"}) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    assert result.code == 0
    _shared_files_hold_no_surrogate(tmp_path / "out")
    kept = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert kept["cases"][0]["id"] == "input.dat"
    assert b"udcff" not in (tmp_path / "out" / "capture.jsonl").read_bytes()


# A made-up secret, put together so that no line of this file holds it whole.
MADE_UP_SECRET = "madeup" + "secretvalue"


def _shared_files(out: Path) -> str:
    return "".join(
        (out / name).read_text(encoding="utf-8") for name in ("results.json", "results.md")
    )


@pytest.mark.parametrize(
    ("driver", "name", "text", "said"),
    [
        pytest.param(
            "lines",
            "stdout.txt",
            "::pairbench:: "
            + json.dumps({"case": f"t[token={MADE_UP_SECRET} l\udcffd]", "value": 1})
            + "\n",
            "side 'new': the case t[token=<hidden> l\\udcffd] holds a lone surrogate, "
            "which is not UTF-8 text",
            id="lines",
        ),
        pytest.param(
            "gbench",
            "gbench.json",
            _gbench(f"BM_Get[token={MADE_UP_SECRET} l\udcffd]"),
            "side 'new': the case BM_Get[token=<hidden> l\\udcffd] holds a lone surrogate, "
            "which is not UTF-8 text",
            id="gbench",
        ),
        pytest.param(
            "lines",
            "stdout.txt",
            "::pairbench:: "
            + json.dumps({"case": f"t[token={MADE_UP_SECRET}]", "value": 1, "unit": "s\udcff"})
            + "\n",
            "side 'new': the unit of case 't[token=<hidden>]': s\\udcff holds a lone "
            "surrogate, which is not UTF-8 text",
            id="unit-of-a-case",
        ),
    ],
)
def test_a_lone_surrogate_refusal_shows_the_case_with_its_secret_hidden(
    cli: Cli, tmp_path: Path, driver: str, name: str, text: str, said: str
) -> None:
    result = _compare(cli, tmp_path, driver, name, text)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: " + said.replace("\\", "\\\\")
    )
    kept = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [r["message"] for r in kept["refusals"]] == [said]
    assert MADE_UP_SECRET not in result.err
    assert MADE_UP_SECRET not in _shared_files(tmp_path / "out")


def test_a_shown_case_with_a_lone_surrogate_is_refused_without_its_folders(
    cli: Cli, tmp_path: Path
) -> None:
    case = "/home/made-up-user/made-up-project/l\udcffd.dat"
    line = "::pairbench:: " + json.dumps({"case": case, "value": 1.0, "unit": "s"}) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the case l\\\\udcffd.dat holds a lone surrogate, which "
        "is not UTF-8 text"
    )
    for name in ("results.json", "results.md"):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert "made-up" not in text
        assert "home" not in text


# A made-up user name and a made-up token, put together so that no line of this file holds
# them whole.
MADE_UP_USER = "madeup" + "username"
MADE_UP_TOKEN = "ghp_" + "Madeup0Token1Value2Not3Real4"


def _pytest_benchmark_with(extra: dict[str, Any]) -> str:
    source = FIXTURES / "drivers" / "pytest-benchmark" / "pytest-benchmark.json"
    doc = json.loads(source.read_text(encoding="utf-8"))
    doc["benchmarks"][0].setdefault("extra_info", {}).update(extra)
    return json.dumps(doc)


@pytest.mark.parametrize(
    ("extra", "secret"),
    [
        pytest.param(
            {f"/home/{MADE_UP_USER}/data/input.csv": "l\udcffd"}, MADE_UP_USER, id="home-path-key"
        ),
        pytest.param({f"token={MADE_UP_TOKEN}": "l\udcffd"}, MADE_UP_TOKEN, id="token-key"),
        pytest.param({MADE_UP_TOKEN: "l\udcffd"}, MADE_UP_TOKEN, id="bare-token-key"),
        pytest.param(
            {"password": {MADE_UP_SECRET: "l\udcffd"}}, MADE_UP_SECRET, id="secret-under-a-key"
        ),
    ],
)
def test_a_lone_surrogate_under_a_key_no_driver_reads_shows_no_key_of_the_document(
    cli: Cli, tmp_path: Path, extra: dict[str, Any], secret: str
) -> None:
    result = _compare(cli, tmp_path, "pytest-benchmark", "pb.json", _pytest_benchmark_with(extra))

    assert result.code == 0, result.err
    _shared_files_hold_no_surrogate(tmp_path / "out")
    assert secret not in result.out
    assert secret not in result.err
    assert secret not in _shared_files(tmp_path / "out")
    assert secret not in (tmp_path / "out" / "capture.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("meta", "secret"),
    [
        pytest.param({f"token={MADE_UP_TOKEN}": "l\udcffd"}, MADE_UP_TOKEN, id="token-key"),
        pytest.param({MADE_UP_TOKEN: "l\udcffd"}, MADE_UP_TOKEN, id="bare-token-key"),
        pytest.param(
            {"password": {MADE_UP_SECRET: "l\udcffd"}}, MADE_UP_SECRET, id="secret-under-a-key"
        ),
    ],
)
def test_the_lines_driver_names_only_its_unknown_key_above_a_lone_surrogate(
    cli: Cli, tmp_path: Path, meta: dict[str, Any], secret: str
) -> None:
    line = "::pairbench:: " + json.dumps({"case": "t", "value": 1, "meta": meta}) + "\n"

    result = _compare(cli, tmp_path, "lines", "stdout.txt", line)

    said = "stdout.txt line 1: unknown key 'meta'; a line holds case, value, unit, better"
    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(f"E_LAUNCH_FAILED: {said}")
    kept = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert [r["message"] for r in kept["refusals"]] == [said]
    assert secret not in result.err
    assert secret not in _shared_files(tmp_path / "out")


def _rewritten(capture: Path, old: bytes, new: bytes) -> None:
    """Write ``new`` for each ``old`` in a capture's records, and give its end record the new
    hash, as a capture written with that text holds it."""
    lines = capture.read_bytes().splitlines(keepends=True)
    body = b"".join(lines[:-1])
    assert old in body
    body = body.replace(old, new)
    end = json.loads(lines[-1])
    end["sha256_of_preceding"] = hashlib.sha256(body).hexdigest()
    capture.write_bytes(body + (json.dumps(end, separators=(",", ":")) + "\n").encode())


@pytest.mark.parametrize(
    ("old", "new", "read", "said", "terminal"),
    [
        pytest.param(
            b'"BM_X"',
            b'"BM_\\ud800"',
            "BM_\ud800",
            "cases[0].id: BM_\\\\ud800",
            "\nBM_?      0.00200 s  0.00200 s  1.00x ",
            id="case-escape",
        ),
        pytest.param(
            b'"BM_X"',
            b'"BM_\xed\xa0\x80"',
            "BM_\ud800",
            "cases[0].id: BM_\\\\ud800",
            "\nBM_?      0.00200 s  0.00200 s  1.00x ",
            id="case-encoded-surrogate",
        ),
        pytest.param(
            b'"unit":"s"',
            b'"unit":"s\\udcff"',
            "s\udcff",
            "cases[0].unit: s\\\\udcff",
            "\nBM_X      0.00200 s?  0.00200 s?  1.00x ",
            id="unit",
        ),
        pytest.param(
            b'"v1.9.4"',
            b'"v1.9\\udcff"',
            "v1.9\udcff",
            "provenance.driver.tool_versions[0]: v1.9\\\\udcff",
            "\nValues read by driver gbench, tool version v1.9?.\n",
            id="tool-version",
        ),
        pytest.param(
            b'"node_type":null',
            b'"node_type":"g\\udcffb"',
            "g\udcffb",
            "provenance.node_type: g\\\\udcffb",
            "\nValues read by driver gbench, tool version v1.9.4.\n",
            id="node-type",
        ),
    ],
)
def test_a_capture_with_a_lone_surrogate_the_results_show_reads_and_is_refused_as_results(
    cli: Cli, tmp_path: Path, old: bytes, new: bytes, read: str, said: str, terminal: str
) -> None:
    made = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_X"))
    assert made.code == 0
    capture = tmp_path / "out" / "capture.jsonl"
    _rewritten(capture, old, new)

    (loaded,) = pairbench.load_capture(capture)
    held = {
        "BM_\ud800": {o.case for o in loaded.observations},
        "s\udcff": {c.unit for c in loaded.cases},
        "v1.9\udcff": {x.tool_version for x in loaded.launches},
        "g\udcffb": {loaded.machine.node_type if loaded.machine is not None else None},
    }[read]
    assert read in held

    shown = cli("compare", capture)
    assert shown.code == 0
    assert shown.err == ""
    assert terminal in shown.out
    assert not any("\ud800" <= c <= "\udfff" for c in shown.out)

    refusal = refusal_text(
        f"E_USAGE: the results cannot be written: {said} holds a lone surrogate, which is not "
        "UTF-8 text"
    ).splitlines()
    written = cli("compare", capture, "--out", tmp_path / "again")
    assert written.code == 2
    assert written.out == ""
    assert _refusal_lines(written.err) == refusal
    assert list((tmp_path / "again").iterdir()) == []

    # The command line run in this process prints to a text buffer, which holds any text.
    printed = cli("compare", capture, "--json")
    assert printed.code == 0
    assert read in printed.out
    assert json.loads(printed.out)["schema"] == "pairbench/results/v1"


@pytest.mark.parametrize("fmt", ["terminal", "markdown", "json", "html"])
def test_a_results_file_with_a_lone_surrogate_is_refused_in_every_format(
    cli: Cli, tmp_path: Path, example_results: dict[str, Any], fmt: str
) -> None:
    example_results["notes"] = [{"code": "made_up", "message": "a\ud800"}]
    (tmp_path / "results.json").write_text(json.dumps(example_results), encoding="utf-8")

    result = cli("report", tmp_path / "results.json", "--format", fmt)

    assert result.code == 2
    assert result.out == ""
    assert result.err == refusal_text(
        "E_USAGE: results file results.json: notes[0].message: a\\\\ud800 holds a lone "
        "surrogate, which is not UTF-8 text"
    )


# A workload that prints one made-up value of one case, as the lines driver reads it.
BENCH = 'print("::pairbench:: {\\"case\\": \\"c1\\", \\"value\\": 1.0, \\"unit\\": \\"s\\"}")\n'
# A text with a byte that is not UTF-8, as Python gives it from an argument or a variable.
NOT_UTF8 = "v\udcffw"
RUN_FLAGS = (
    "--driver",
    "lines",
    "--gates",
    "off",
    "--rounds",
    "6",
    "--rounds-exact",
    "--explain",
    "off",
    "--plots",
    "off",
    "--positive-control",
    "off",
)


def _refusal_lines(err: str) -> list[str]:
    """Standard error without the notes, which depend on the machine."""
    return [line for line in err.splitlines() if not line.startswith("pairbench: note: ")]


def _run(
    cli: Cli,
    tmp_path: Path,
    side: str,
    *more: str,
    out: str = "out",
    workload: tuple[str, ...] = (),
) -> Any:
    (tmp_path / "bench.py").write_text(BENCH, encoding="utf-8")
    python = sys.executable
    return cli(
        "run",
        "--side",
        side.format(python=python),
        "--side",
        f"b=cmd:{python} -I {{workload}}",
        *RUN_FLAGS,
        "--out",
        tmp_path / out,
        *more,
        "--",
        tmp_path / "bench.py",
        *workload,
    )


def _shared_files_hold_no_surrogate(folder: Path, *more: str) -> None:
    """The results files are UTF-8 text and hold no surrogate, escaped or not."""
    for name in ("results.json", "results.md", *more):
        text = (folder / name).read_bytes().decode("utf-8")
        assert "\\udcff" not in text
        assert "\udcff" not in text


@pytest.mark.parametrize(
    ("kwargs", "said"),
    [
        pytest.param(
            {"workload": (NOT_UTF8,)},
            "E_USAGE: argument 23 of the command line is not UTF-8 text, which the results are",
            id="workload-argument",
        ),
        pytest.param(
            {"out": "out" + NOT_UTF8},
            "E_USAGE: argument 20 of the command line is not UTF-8 text, which the results are",
            id="results-folder",
        ),
        pytest.param(
            {"workload": (NOT_UTF8,), "side": "a=cmd:env X=" + NOT_UTF8 + " {python} {{workload}}"},
            "E_USAGE: argument 23 of the command line is not UTF-8 text, which the results are",
            id="hidden-side-spec-then-workload-argument",
        ),
    ],
)
def test_a_run_refuses_an_argument_the_results_show_that_is_not_utf_8_before_any_launch(
    cli: Cli, tmp_path: Path, kwargs: dict[str, Any], said: str
) -> None:
    side = kwargs.pop("side", "a=cmd:{python} {{workload}}")
    result = _run(cli, tmp_path, side, **kwargs)

    assert result.code == 2
    assert result.out == ""
    assert _refusal_lines(result.err) == refusal_text(said).splitlines()
    assert "\\udcff" not in result.err
    assert [p.name for p in tmp_path.iterdir()] == ["bench.py"]


@pytest.mark.parametrize(
    ("side", "more"),
    [
        pytest.param("a=cmd:env X=" + NOT_UTF8 + " {python} {{workload}}", (), id="side-spec"),
        pytest.param("a=cmd:{python} {{workload}} " + NOT_UTF8, (), id="side-argument"),
        pytest.param(
            "a=cmd:{python} {{workload}}",
            ("--set", "launch.env={ X = '" + NOT_UTF8 + "' }"),
            id="set-value",
        ),
    ],
)
def test_a_run_carries_an_argument_the_results_hide_that_is_not_utf_8(
    cli: Cli, tmp_path: Path, side: str, more: tuple[str, ...]
) -> None:
    result = _run(cli, tmp_path, side, *more)

    assert result.code == 0
    _shared_files_hold_no_surrogate(tmp_path / "out", "report.html")
    capture = tmp_path / "out" / "capture.jsonl"
    assert b"\\udcff" in capture.read_bytes().splitlines()[0]
    again = cli("compare", capture, "--out", tmp_path / "again")
    assert again.code == 0
    _shared_files_hold_no_surrogate(tmp_path / "again")


def test_a_run_carries_a_variable_that_is_not_utf_8(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAIRBENCH__LAUNCH__ENV", "{ X = '" + NOT_UTF8 + "' }")

    result = _run(cli, tmp_path, "a=cmd:{python} {{workload}}")

    assert result.code == 0
    _shared_files_hold_no_surrogate(tmp_path / "out", "report.html")
    assert b"\\udcff" in (tmp_path / "out" / "capture.jsonl").read_bytes().splitlines()[0]


@pytest.mark.parametrize("route", ["set", "variable"])
def test_a_run_refuses_a_node_type_that_is_not_utf_8_before_any_launch(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    more: tuple[str, ...] = ()
    if route == "set":
        more = ("--set", "run.node_type=g" + NOT_UTF8 + "b")
    else:
        monkeypatch.setenv("PAIRBENCH__RUN__NODE_TYPE", "g" + NOT_UTF8 + "b")

    result = _run(cli, tmp_path, "a=cmd:{python} {{workload}}", *more)

    assert result.code == 2
    assert result.out == ""
    assert (
        _refusal_lines(result.err)
        == refusal_text(
            "E_USAGE: the setting run.node_type is not UTF-8 text, which the results are"
        ).splitlines()
    )
    assert "\\udcff" not in result.err
    assert [p.name for p in tmp_path.iterdir()] == ["bench.py"]


@pytest.mark.parametrize("absolute", [True, False], ids=["absolute", "relative"])
def test_a_file_side_in_a_folder_whose_name_is_not_utf_8_is_compared(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, absolute: bool
) -> None:
    line = "::pairbench:: " + json.dumps({"case": "c1", "value": 1.0, "unit": "s"}) + "\n"
    for folder in ("n" + NOT_UTF8, "o"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "s.txt").write_text(line, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    new = f"{tmp_path}/n{NOT_UTF8}/s.txt" if absolute else f"n{NOT_UTF8}/s.txt"

    result = cli(
        "compare",
        "--side",
        f"new=file:{new}",
        "--side",
        "old=file:o/s.txt",
        "--driver",
        "lines",
        "--out",
        "out",
    )

    assert result.code == 0
    text = (tmp_path / "out" / "results.json").read_bytes().decode("utf-8")
    assert "\\udcff" not in text
    assert json.loads(text)["run"]["command"] == (
        "pairbench compare --side 'new=file:<hidden>' --side 'old=file:<hidden>' "
        "--driver lines --out out"
    )
    (capture,) = pairbench.load_capture(tmp_path / "out" / "capture.jsonl")
    assert capture.header.argv[3] == f"new=file:{new}"
    assert capture.sides[0].spec["paths"] == (new,)


def _with_header_argv(capture: Path, argv: list[str]) -> None:
    """Give a capture another command line in its header, and its end record the new hash."""
    lines = capture.read_bytes().splitlines(keepends=True)
    header = json.loads(lines[0])
    header["argv"] = argv
    body = (json.dumps(header, separators=(",", ":")) + "\n").encode() + b"".join(lines[1:-1])
    end = json.loads(lines[-1])
    end["sha256_of_preceding"] = hashlib.sha256(body).hexdigest()
    capture.write_bytes(body + (json.dumps(end, separators=(",", ":")) + "\n").encode())


def test_results_that_would_show_a_lone_surrogate_are_refused_before_either_file(
    cli: Cli, tmp_path: Path
) -> None:
    line = "::pairbench:: " + json.dumps({"case": "c1", "value": 1.0, "unit": "s"}) + "\n"
    made = _compare(cli, tmp_path, "lines", "s.txt", line)
    assert made.code == 0
    capture = tmp_path / "out" / "capture.jsonl"
    _with_header_argv(capture, ["pairbench", "compare", "x" + NOT_UTF8 + "y.txt"])

    result = cli("compare", capture, "--out", tmp_path / "again")

    assert result.code == 2
    assert result.out == ""
    said = (
        "E_USAGE: the results cannot be written: run.command: pairbench compare "
        "'xv\\\\udcffwy.txt' holds a lone surrogate, which is not UTF-8 text"
    )
    assert _refusal_lines(result.err) == refusal_text(said).splitlines()
    assert not (tmp_path / "again" / "results.json").exists()
    assert not (tmp_path / "again" / "results.md").exists()


def test_a_run_in_a_working_folder_that_is_not_utf_8_runs(
    cli: Cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / ("wd" + NOT_UTF8)
    folder.mkdir()
    monkeypatch.chdir(folder)
    (folder / "bench.py").write_text(BENCH, encoding="utf-8")
    python = sys.executable

    result = cli(
        "run",
        "--side",
        f"a=cmd:{python} {{workload}}",
        "--side",
        f"b=cmd:{python} -I {{workload}}",
        *RUN_FLAGS,
        "--out",
        "out",
        "--",
        "bench.py",
    )

    assert result.code == 0
    assert (folder / "out" / "results.json").is_file()
    assert (cli("compare", folder / "out" / "capture.jsonl").code) == 0


def _plain(*fields: tuple[str, object]) -> str:
    return "::pairbench:: " + json.dumps({"case": "c1", "value": 1, **dict(fields)}) + "\n"


@pytest.mark.parametrize(
    ("driver", "text", "sets", "escaped", "terminal"),
    [
        pytest.param(
            "lines",
            _plain(("case", "a\udfff")),
            [],
            b'"a\\udfff"',
            "\na?    1.00 s  1.00 s  1.00x   -      -  NO VERDICT ",
            id="case",
        ),
        pytest.param(
            "lines",
            _plain(("unit", "s\udcff")),
            [],
            b'"s\\udcff"',
            "\nc1    1.00 s?  1.00 s?  1.00x   -      -  NO VERDICT ",
            id="unit",
        ),
        pytest.param(
            "gbench",
            _gbench("BM_X", "v1.9\udcff"),
            [],
            b'"v1.9\\udcff"',
            "\nValues read by driver gbench, tool version v1.9?.\n",
            id="tool-version",
        ),
        pytest.param(
            "lines",
            _plain(),
            ["run.node_type=g\udcffb"],
            b'"g\\udcffb"',
            "\nc1    1.00 s  1.00 s  1.00x   -      -  NO VERDICT ",
            id="node-type",
        ),
    ],
)
def test_a_run_of_the_python_api_keeps_a_lone_surrogate_in_its_capture(
    tmp_path: Path, driver: str, text: str, sets: list[str], escaped: bytes, terminal: str
) -> None:
    from pairbench import config

    for side in ("new", "old"):
        (tmp_path / side).mkdir()
        (tmp_path / side / "out.txt").write_text(text, encoding="utf-8")
    flags = config.flag_config(
        {"--driver": driver, "--explain": "off", "--plots": "off"},
        sides=[f"new=file:{tmp_path}/new/out.txt", f"old=file:{tmp_path}/old/out.txt"],
        baseline=None,
    )
    experiment = config.load_experiment(None, environ={}, flags=flags, sets=sets)

    capture = pairbench.run(experiment, out=tmp_path / "run")

    assert escaped in (tmp_path / "run" / "capture.jsonl").read_bytes()
    shown = pairbench.render(pairbench.analyse(capture), "terminal")
    assert terminal in shown
    assert not any("\ud800" <= c <= "\udfff" for c in shown)


def _json_to(capture: Path, errors: str) -> tuple[int, bytes, str]:
    """Run ``compare CAPTURE --json`` with standard output a UTF-8 stream whose error handler
    is ``errors``, as Python sets it under a C or POSIX locale (``surrogateescape``) and under
    a UTF-8 one (``strict``); return the exit code, the bytes written and standard error."""
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    raw, err = io.BytesIO(), io.StringIO()
    stream = io.TextIOWrapper(raw, encoding="utf-8", errors=errors, write_through=True)
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(err):
        code = main(["compare", str(capture), "--json"])
    stream.flush()
    return code, raw.getvalue(), err.getvalue()


@pytest.mark.parametrize(
    ("old", "new", "byte"),
    [
        pytest.param(b'"BM_X"', b'"BM_\\udcff"', b'"BM_\xff"', id="case"),
        pytest.param(b'"unit":"s"', b'"unit":"s\\udcff"', b'"unit": "s\xff"', id="unit"),
    ],
)
def test_json_of_a_capture_is_printed_where_standard_output_writes_the_surrogate_back(
    cli: Cli, tmp_path: Path, old: bytes, new: bytes, byte: bytes
) -> None:
    # Standard output under a C or POSIX locale writes a surrogate from U+DC80 to U+DCFF as
    # the byte it stands for, so the document prints as it does with any other text.
    made = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_X"))
    assert made.code == 0
    capture = tmp_path / "out" / "capture.jsonl"
    _rewritten(capture, old, new)

    code, written, _err = _json_to(capture, "surrogateescape")

    assert code == 0
    assert byte in written
    document = json.loads(written.decode("utf-8", "surrogateescape"))
    assert document["schema"] == "pairbench/results/v1"


@pytest.mark.parametrize(
    ("new", "errors", "said"),
    [
        pytest.param(b'"BM_\\udcff"', "strict", "BM_\\\\udcff", id="utf-8-locale"),
        pytest.param(b'"BM_\\ud800"', "surrogateescape", "BM_\\\\ud800", id="not-a-byte"),
    ],
)
def test_json_of_a_capture_is_refused_where_standard_output_cannot_write_the_surrogate(
    cli: Cli, tmp_path: Path, new: bytes, errors: str, said: str
) -> None:
    made = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_X"))
    assert made.code == 0
    capture = tmp_path / "out" / "capture.jsonl"
    _rewritten(capture, b'"BM_X"', new)

    code, written, err = _json_to(capture, errors)

    assert code == 2
    assert written == b""
    assert (
        err.splitlines()[-2:]
        == refusal_text(
            f"E_USAGE: the results cannot be written: cases[0].id: {said} holds a lone surrogate, "
            "which is not UTF-8 text"
        ).splitlines()
    )


# A made-up secret value, put together so that no line of this file holds it whole.
MADE_UP_SECRET = "madeup" + "secretvalue"


@pytest.mark.parametrize(
    ("unit", "said"),
    [
        pytest.param(
            "s token=" + MADE_UP_SECRET + " \\udcff",
            "cases[0].unit: s token=<hidden> \\\\udcff holds a lone surrogate",
            id="secret",
        ),
        pytest.param(
            "/made/up/folder/s\\udcff",
            "cases[0].unit: s\\\\udcff holds a lone surrogate",
            id="path",
        ),
    ],
)
def test_a_text_the_results_cannot_be_written_with_is_shown_as_a_case_is_shown(
    cli: Cli, tmp_path: Path, unit: str, said: str
) -> None:
    made = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_X"))
    assert made.code == 0
    capture = tmp_path / "out" / "capture.jsonl"
    _rewritten(capture, b'"unit":"s"', f'"unit":"{unit}"'.encode())

    written = cli("compare", capture, "--out", tmp_path / "again")

    assert written.code == 2
    assert written.out == ""
    assert (
        _refusal_lines(written.err)
        == refusal_text(
            f"E_USAGE: the results cannot be written: {said}, which is not UTF-8 text"
        ).splitlines()
    )
    assert MADE_UP_SECRET not in written.err
    assert "folder" not in written.err


@pytest.mark.parametrize(
    ("driver", "name", "text", "said"),
    [
        pytest.param(
            "lines",
            "stdout.txt",
            "::pairbench:: "
            + json.dumps({"case": "c1", "value": 1, "unit": f"s token={MADE_UP_SECRET} \udcff"})
            + "\n",
            "the unit of case 'c1': s token=<hidden> \\\\udcff holds a lone surrogate, which is "
            "not UTF-8 text",
            id="unit-secret",
        ),
        pytest.param(
            "lines",
            "stdout.txt",
            "::pairbench:: "
            + json.dumps({"case": "c1", "value": 1, "unit": "s /home/made-up-user/l\udcffd/x.dat"})
            + "\n",
            "the unit of case 'c1' holds a lone surrogate, which is not UTF-8 text",
            id="unit-path",
        ),
        pytest.param(
            "gbench",
            "gbench.json",
            _gbench("BM_X", f"v1.9 token={MADE_UP_SECRET} \udcff"),
            "the tool version v1.9 token=<hidden> \\\\udcff holds a lone surrogate, which is "
            "not UTF-8 text",
            id="tool-version-secret",
        ),
    ],
)
def test_a_lone_surrogate_outside_the_case_is_quoted_as_a_case_is_shown(
    cli: Cli, tmp_path: Path, driver: str, name: str, text: str, said: str
) -> None:
    result = _compare(cli, tmp_path, driver, name, text)

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(f"E_LAUNCH_FAILED: side 'new': {said}")
    written = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert written["refusals"][0]["message"] == f"side 'new': {said}".replace("\\\\", "\\")
    for shown in (result.err, (tmp_path / "out" / "results.md").read_text(encoding="utf-8")):
        assert MADE_UP_SECRET not in shown
        assert "made-up-user" not in shown


@pytest.mark.parametrize(
    "version",
    [
        pytest.param("v1.9\udcff", id="version-with-a-surrogate"),
        pytest.param("v9.0.0", id="untested-version"),
    ],
)
def test_a_case_with_a_lone_surrogate_is_refused_before_the_tool_version_is_read(
    cli: Cli, tmp_path: Path, version: str
) -> None:
    result = _compare(cli, tmp_path, "gbench", "gbench.json", _gbench("BM_\ud800", version))

    assert result.code == 5
    assert result.out == ""
    assert result.err == COMMAND_NOTE + refusal_text(
        "E_LAUNCH_FAILED: side 'new': the case BM_\\\\ud800 holds a lone surrogate, which is "
        "not UTF-8 text"
    )
