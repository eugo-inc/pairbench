# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every code block a page marks as an example runs, and gives the output the page shows.

A block is marked by a line ``<!-- example -->`` right before its fence. The marked blocks
of one page run in order in one namespace, so a later block may use what an earlier one
made. A Python block written as an interactive session (lines starting ``>>>``) runs as a
doctest, which compares every output it shows. Any other Python block runs as a script.
In a ``console`` block, each line starting ``$ pairbench`` is run, and everything it prints
on either stream must equal the lines the page shows below it, up to the next command.
"""

from __future__ import annotations

import contextlib
import doctest
import io
import os
import shlex
import subprocess
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

MARK = "<!-- example -->"
LANGUAGES = ("python", "console")
PROMPT = "$ "
TIMEOUT_S = 60
FEWEST_EXAMPLES = 8


@dataclass(frozen=True)
class Example:
    page: str
    line: int
    language: str
    code: str


def marked(page: str, text: str) -> tuple[list[Example], list[str]]:
    """The marked blocks of a page, and a problem for each mark not on a runnable block."""
    lines = text.splitlines()
    found: list[Example] = []
    problems: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != MARK:
            continue
        fence = lines[index + 1] if index + 1 < len(lines) else ""
        language = fence.removeprefix("```").strip()
        if not fence.startswith("```") or language not in LANGUAGES:
            problems.append(f"{page}:{index + 1}: the mark is not on a python or console block")
            continue
        end = next((i for i in range(index + 2, len(lines)) if lines[i] == "```"), None)
        if end is None:
            problems.append(f"{page}:{index + 2}: the block never closes")
            continue
        code = "\n".join(lines[index + 2 : end]) + "\n"
        found.append(Example(page, index + 3, language, code))
    return found, problems


def commands(code: str) -> Iterator[tuple[str, str]]:
    """Each command of a console block with the output the block shows for it."""
    command: str | None = None
    shown: list[str] = []
    for line in code.splitlines():
        if line.startswith(PROMPT):
            if command is not None:
                yield command, "".join(f"{s}\n" for s in shown)
            command, shown = line.removeprefix(PROMPT), []
        elif command is not None:
            shown.append(line)
    if command is not None:
        yield command, "".join(f"{s}\n" for s in shown)


def run_console(example: Example, src: Path, folder: Path) -> list[str]:
    problems: list[str] = []
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH")}
    env["PYTHONPATH"] = str(src)
    for command, shown in commands(example.code):
        argv = shlex.split(command)
        if argv[:1] != ["pairbench"]:
            problems.append(f"{example.page}:{example.line}: not a pairbench command: {command}")
            continue
        done = subprocess.run(
            [sys.executable, "-m", "pairbench", *argv[1:]],
            cwd=folder,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
        if done.stdout != shown:
            problems.append(f"{example.page}:{example.line}: {command}\n{done.stdout}")
    return problems


def run_python(example: Example, module: types.ModuleType) -> list[str]:
    name = f"{example.page}:{example.line}"
    if example.code.lstrip().startswith(">>>"):
        test = doctest.DocTestParser().get_doctest(
            example.code, module.__dict__, name, example.page, example.line
        )
        report = io.StringIO()
        runner = doctest.DocTestRunner(verbose=False)
        result = runner.run(test, out=report.write, clear_globs=False)
        return [f"{name}\n{report.getvalue()}"] if result.failed else []
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(example.code, name, "exec"), module.__dict__)
    except Exception as error:  # the problem is reported with the block that raised it
        return [f"{name}: {type(error).__name__}: {error}"]
    return []


def run_page(examples: list[Example], src: Path, folder: Path) -> list[str]:
    """Run a page's marked blocks in order in one namespace; return what went wrong."""
    module = types.ModuleType("pairbench_docs_example")
    previous = sys.modules.get(module.__name__)
    sys.modules[module.__name__] = module
    problems: list[str] = []
    try:
        for example in examples:
            if example.language == "console":
                problems += run_console(example, src, folder)
            else:
                problems += run_python(example, module)
    finally:
        if previous is None:
            del sys.modules[module.__name__]
        else:
            sys.modules[module.__name__] = previous
    return problems


def page_examples(repo_root: Path, pages: list[Path]) -> dict[str, list[Example]]:
    by_page: dict[str, list[Example]] = {}
    for path in pages:
        page = path.relative_to(repo_root).as_posix()
        found, _ = marked(page, path.read_text(encoding="utf-8"))
        if found:
            by_page[page] = found
    return by_page


REPO = Path(__file__).resolve().parents[3]
PAGES = sorted(p for p in (REPO / "docs").rglob("*.md") if p.read_text("utf-8").startswith("---\n"))
EXAMPLES = page_examples(REPO, PAGES)


def test_every_mark_sits_on_a_block_the_test_can_run() -> None:
    problems: list[str] = []
    for path in PAGES:
        problems += marked(path.relative_to(REPO).as_posix(), path.read_text("utf-8"))[1]

    assert problems == []


def test_the_pages_mark_their_examples() -> None:
    count = sum(len(found) for found in EXAMPLES.values())

    assert count >= FEWEST_EXAMPLES
    assert {"python", "console"} <= {e.language for v in EXAMPLES.values() for e in v}


@pytest.mark.parametrize("page", sorted(EXAMPLES))
def test_the_marked_examples_of_a_page_run_and_show_their_output(
    page: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in [k for k in os.environ if k.startswith("PAIRBENCH")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)

    assert run_page(EXAMPLES[page], REPO / "src", tmp_path) == []


def test_a_wrong_output_a_raising_block_and_a_wrong_console_line_are_each_caught(
    tmp_path: Path,
) -> None:
    examples = [
        Example("x.md", 1, "python", "value = 2\n"),
        Example("x.md", 5, "python", ">>> value + 1\n4\n"),
        Example("x.md", 9, "python", "raise RuntimeError('made up')\n"),
        Example("x.md", 13, "console", "$ pairbench compare\nE_USAGE: not what it prints\n"),
        Example("x.md", 17, "console", "$ ls\n"),
    ]

    problems = run_page(examples, REPO / "src", tmp_path)

    assert [p.split("\n")[0] for p in problems] == [
        "x.md:5",
        "x.md:9: RuntimeError: made up",
        "x.md:13: pairbench compare",
        "x.md:17: not a pairbench command: ls",
    ]


def test_a_mark_on_a_block_in_another_language_is_reported() -> None:
    text = f"# A page\n\n{MARK}\n```toml\na = 1\n```\n\n{MARK}\ntext\n"

    found, problems = marked("x.md", text)

    assert found == []
    assert problems == [
        "x.md:3: the mark is not on a python or console block",
        "x.md:8: the mark is not on a python or console block",
    ]
