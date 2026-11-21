# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Through a real ``run``: a refusal that names a case id names it with its secret hidden.

Two command sides run a workload that prints lines for the ``lines`` driver. Each line names
the case ``test_api[token:VALUE]``, and one thing about the lines is wrong: the value is not
a finite number, is missing or is no number, the unit is empty, ``better`` is no word the
tool knows, or the case is printed twice. The run is refused with ``E_LAUNCH_FAILED``, and
the message in ``results.json`` and ``results.md`` names the case as the reports show it,
``test_api[token:<hidden>]``. Two cases that differ only in the hidden value are refused
with ``E_USAGE`` and the same shown name, and a ``--case`` pattern typed with the value,
which matches no case as the reports show it, is named with the value hidden. Every value is
made up.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.errors import EXIT_LAUNCH, EXIT_USAGE

Cli = Callable[..., Any]

# A made-up password and a second one, neither a credential word nor random-looking.
VALUE = "kiwi7mango42"
OTHER = "plum3fig88qz"
CASE = f"test_api[token:{VALUE}]"
SHOWN = "test_api[token:<hidden>]"
# The same name as results.md writes it, with Markdown's marks escaped.
SHOWN_MD = r"test\_api\[token:\<hidden\>\]"
QUICK = (
    "--gates",
    "off",
    "--rounds",
    "4",
    "--same-vs-same",
    "off",
    "--positive-control",
    "off",
    "--explain",
    "off",
    "--plots",
    "off",
    "--allow-identical",
    "--allow-underpowered",
)
SIDES = ("--side", "old=cmd:env {workload}", "--side", "new=cmd:env {workload}")
# A workload that prints each of its lines after the lines driver's mark.
PROGRAM = """\
import json
for line in json.loads({lines!r}):
    print("::pairbench:: " + line)
"""
HEAD = f'{{"case": "{CASE}", '
# Each row: the lines the workload prints, and the message the refusal carries.
REFUSED: dict[str, tuple[tuple[str, ...], str]] = {
    "a value that is not a finite number": (
        (HEAD + '"value": NaN, "unit": "s"}',),
        f"case '{SHOWN}': the value nan is not a finite number",
    ),
    "a line with no value": (
        (HEAD + '"unit": "s"}',),
        f"stdout.txt line 1: the case '{SHOWN}' has no value",
    ),
    "a value that is no number": (
        (HEAD + '"value": "fast", "unit": "s"}',),
        f"stdout.txt line 1: the value of '{SHOWN}' is not a number",
    ),
    "an empty unit": (
        (HEAD + '"value": 1.5, "unit": ""}',),
        f"stdout.txt line 1: the unit of '{SHOWN}' is not a text that is not empty",
    ),
    "a word for better the tool does not know": (
        (HEAD + '"value": 1.5, "unit": "s", "better": "up"}',),
        f"stdout.txt line 1: better of '{SHOWN}' is 'up'; it is one of lower, higher, none",
    ),
    "a case printed twice": (
        (HEAD + '"value": 1.5, "unit": "s"}', HEAD + '"value": 2.5, "unit": "s"}'),
        f"stdout.txt: the case '{SHOWN}' is given twice",
    ),
}


def pieces(text: str, value: str) -> list[str]:
    """Return each six characters in a row of the value that the text holds."""
    return [value[at : at + 6] for at in range(len(value) - 5) if value[at : at + 6] in text]


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working folder the run is started in."""
    folder = tmp_path / "work"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def refused(cli: Cli, work: Path, lines: tuple[str, ...]) -> tuple[Any, dict[str, Any], str]:
    """Run the lines, and return the result, ``results.json`` and ``results.md``."""
    program = work / "lines.py"
    program.write_text(PROGRAM.format(lines=json.dumps(list(lines))), encoding="utf-8")
    result = cli(
        "run",
        *SIDES,
        *QUICK,
        "--driver",
        "lines",
        "--out",
        "out",
        "--",
        sys.executable,
        program,
    )
    out = work / "out"
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    markdown = (out / "results.md").read_text(encoding="utf-8")
    return result, results, markdown


@pytest.mark.slow
@pytest.mark.parametrize("form", sorted(REFUSED))
def test_a_refusal_names_the_case_with_its_secret_hidden(cli: Cli, work: Path, form: str) -> None:
    lines, message = REFUSED[form]

    result, results, markdown = refused(cli, work, lines)

    assert result.code == EXIT_LAUNCH, result.err
    assert "E_LAUNCH_FAILED" in result.err
    assert [refusal["message"] for refusal in results["refusals"]] == [message]
    assert markdown.count("- Refused, E\\_LAUNCH\\_FAILED (experiment): ") == 1
    assert SHOWN_MD in markdown
    shared = json.dumps(results) + markdown + result.out + result.err
    assert pieces(shared, VALUE) == []
    assert not os.path.exists(work / "out" / "report.html")


@pytest.mark.slow
def test_two_cases_that_differ_only_in_a_hidden_value_are_refused(cli: Cli, work: Path) -> None:
    lines = (
        HEAD + '"value": 1.5, "unit": "s"}',
        f'{{"case": "test_api[token:{OTHER}]", "value": 2.5, "unit": "s"}}',
    )

    result, results, markdown = refused(cli, work, lines)

    assert result.code == EXIT_USAGE, result.err
    assert "E_USAGE" in result.err
    assert SHOWN in result.err
    shared = json.dumps(results) + markdown + result.out + result.err
    assert pieces(shared, VALUE) == []
    assert pieces(shared, OTHER) == []


@pytest.mark.slow
def test_a_case_pattern_that_matches_no_case_is_named_with_its_secret_hidden(
    cli: Cli, work: Path
) -> None:
    program = work / "lines.py"
    lines = (HEAD + '"value": 1.5, "unit": "s"}', '{"case": "test_tokenize[hello]", "value": 2.5}')
    program.write_text(PROGRAM.format(lines=json.dumps(list(lines))), encoding="utf-8")

    result = cli(
        "run",
        *SIDES,
        *QUICK,
        "--driver",
        "lines",
        "--case",
        CASE,
        "--out",
        "out",
        "--",
        sys.executable,
        program,
    )

    assert result.code == EXIT_USAGE, result.err
    assert "E_USAGE" in result.err
    results = json.loads((work / "out" / "results.json").read_text(encoding="utf-8"))
    markdown = (work / "out" / "results.md").read_text(encoding="utf-8")
    assert [refusal["message"] for refusal in results["refusals"]] == [
        f"the primary case pattern '{SHOWN}' matches no case of this run; its cases are: "
        "'res/cores', 'res/ctx_involuntary', 'res/ctx_voluntary', 'res/faults_major', "
        "'res/faults_minor', 'res/rss_peak', 'res/sys', 'res/user', "
        f"'{SHOWN}', 'test_tokenize[hello]'"
    ]
    shared = json.dumps(results) + markdown + result.out + result.err
    assert pieces(shared, VALUE) == []
