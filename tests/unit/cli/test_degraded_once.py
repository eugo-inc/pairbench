# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A run where no container engine can be reached says the census line once in each report.

The run checks the machine once before the locks and once at the short
recheck after them, so its capture holds two census records and its results
two equal ``machine_state.degraded`` entries; pooling two such captures
gives four. The terminal report and ``results.md`` of the run and of the
pooled results, the run's ``report.html``, and ``pairbench report`` of each
results file in each format say the entry once.
"""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import sys
from typing import Any

import pytest

from pairbench.api import ENGINE_VARIABLE
from pairbench.errors import EXIT_OK

ENTRY = {
    "name": "census",
    "status": "unavailable",
    "message": "no container engine could be reached",
}
TERMINAL = "Check census: unavailable (no container engine could be reached)."
MARKDOWN = f"- {TERMINAL}"
PAGE = "Check census: unavailable: no container engine could be reached"
PYTHON = shlex.quote(sys.executable)
QUICK = (
    "--gates",
    "warn",
    "--set",
    "gates.quiet.samples=1",
    "--set",
    "gates.quiet.interval_s=0.1",
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


def _main(*args: object) -> tuple[int, str, str]:
    from pairbench.api import CliMain, delegate

    main: CliMain = delegate("main")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main([str(arg) for arg in args])
    return code, out.getvalue(), err.getvalue()


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Two finished runs of two command sides with a PATH that holds no container engine,
    and the pooled results of their captures."""
    folder = tmp_path_factory.mktemp("no-engine")
    empty = folder / "bin"
    empty.mkdir()
    made: dict[str, Any] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("PATH", str(empty))
        patch.delenv(ENGINE_VARIABLE, raising=False)
        patch.chdir(folder)
        for name in ("first", "second"):
            made[name] = _main(
                "run",
                "--side",
                f"new=cmd:{PYTHON} -c pass",
                "--side",
                f"old=cmd:{PYTHON} -S -c pass",
                "--baseline",
                "old",
                *QUICK,
                "--out",
                name,
            )
        made["pooled"] = _main(
            "compare", "first/capture.jsonl", "second/capture.jsonl", "--out", "pooled"
        )
    made["folder"] = folder
    return made


def _counts(text: str) -> tuple[int, int, int]:
    """How often the line of each report form is in a text."""
    lines = text.splitlines()
    return lines.count(TERMINAL), lines.count(MARKDOWN), text.count(PAGE)


def test_the_run_prints_the_census_line_once_on_standard_output(runs: dict[str, Any]) -> None:
    code, out, err = runs["first"]

    assert code == EXIT_OK, err
    assert _counts(out) == (1, 0, 0)
    assert TERMINAL not in err


def test_each_run_records_the_census_once_per_phase(runs: dict[str, Any]) -> None:
    for name in ("first", "second"):
        folder = runs["folder"] / name
        rows = [json.loads(line) for line in (folder / "capture.jsonl").read_text().splitlines()]
        census = [r for r in rows if r.get("t") == "gate" and r.get("name") == "census"]
        results = json.loads((folder / "results.json").read_text(encoding="utf-8"))

        assert [r["status"] for r in census] == ["unavailable", "unavailable"]
        assert results["machine_state"]["degraded"].count(ENTRY) == 2


def test_the_pooled_results_hold_the_entry_of_each_capture(runs: dict[str, Any]) -> None:
    code, _, err = runs["pooled"]
    results = json.loads((runs["folder"] / "pooled" / "results.json").read_text(encoding="utf-8"))

    assert code == EXIT_OK, err
    assert results["machine_state"]["degraded"].count(ENTRY) == 4


def test_the_pooled_results_print_the_census_line_once_on_standard_output(
    runs: dict[str, Any],
) -> None:
    code, out, err = runs["pooled"]

    assert code == EXIT_OK, err
    assert _counts(out) == (1, 0, 0)
    assert TERMINAL not in err


def test_the_written_reports_of_the_run_say_the_census_line_once(runs: dict[str, Any]) -> None:
    folder = runs["folder"] / "first"
    markdown = (folder / "results.md").read_text(encoding="utf-8")
    page = (folder / "report.html").read_text(encoding="utf-8")

    assert _counts(markdown) == (0, 1, 0)
    assert _counts(page) == (0, 0, 1)


def test_the_written_report_of_the_pooled_results_says_the_census_line_once(
    runs: dict[str, Any],
) -> None:
    markdown = (runs["folder"] / "pooled" / "results.md").read_text(encoding="utf-8")

    assert _counts(markdown) == (0, 1, 0)


@pytest.mark.parametrize("name", ["first", "pooled"])
@pytest.mark.parametrize(
    ("fmt", "said"),
    [
        pytest.param("terminal", (1, 0, 0), id="terminal"),
        pytest.param("markdown", (0, 1, 0), id="markdown"),
        pytest.param("html", (0, 0, 1), id="html"),
    ],
)
def test_pairbench_report_says_the_census_line_once(
    cli: Any, runs: dict[str, Any], name: str, fmt: str, said: tuple[int, int, int]
) -> None:
    result = cli("report", runs["folder"] / name / "results.json", "--format", fmt)

    assert result.code == EXIT_OK, result.err
    assert _counts(result.out) == said
    assert "census" not in result.err
