# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The checks workflow: when it runs, what it installs and which tool versions it uses.

The workflow is read as text, line by line, because the tests import only the
standard library, pytest and pairbench at their top. Each job is the block of
lines indented under its name in ``jobs:``.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

CHECKS = ".github/workflows/checks.yml"
LOCK = "site/package-lock.json"
ASTRO = "node_modules/astro"
NODE_FLOOR = re.compile(r">=\s*(\d+\.\d+\.\d+)")
# The events the workflow runs on, and the branch a push runs it for.
EVENTS = ("pull_request", "push", "workflow_dispatch")
PUSHED_BRANCHES = "[main]"
# A newer run replaces an older one of the same pull request; any other run is grouped by its
# commit, so a later push to the branch cannot cancel or replace the run of an earlier commit.
CONCURRENCY = [
    "group: checks-${{ github.workflow }}-${{ github.event.pull_request.number || github.sha }}",
    "cancel-in-progress: true",
]
# The Node.js release the docs job builds the site with: the newest patch of the release
# line the stated floor belongs to.
DOCS_NODE = "22.23.5"
# The tools of the lint group, each pinned to one release, so a new release of either
# cannot change what the checks report by itself.
LINT_PINS = ["mypy==2.4.1", "ruff==0.17.5"]
README_CHECK = [
    "pairbench fill docs/readme/README.in.md \\",
    "--results docs/figures/launch-cost/results.json -o README.md --check",
]
KEPT_RESULTS = "docs/figures/launch-cost/results.json"


def _lines(repo_root: Path) -> list[str]:
    return (repo_root / CHECKS).read_text(encoding="utf-8").splitlines()


def _block(lines: list[str], header: str, indent: int) -> list[str]:
    """The lines indented under the line ``header`` found at ``indent`` spaces."""
    start = lines.index(" " * indent + header)
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line)
    return block


def _job(repo_root: Path, name: str) -> list[str]:
    return _block(_block(_lines(repo_root), "jobs:", 0), f"{name}:", 2)


def _step_run(job: list[str], step: str) -> list[str]:
    """The commands of the step named ``step``, one stripped line each."""
    start = job.index(f"      - name: {step}")
    rest = job[start + 1 :]
    assert rest[0].strip() == "run: |", rest[0]
    commands: list[str] = []
    for line in rest[1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= 8:
            break
        if line.strip():
            commands.append(line.strip())
    return commands


def _value(lines: list[str], key: str) -> list[str]:
    return [
        line.strip()[len(key) + 1 :].strip() for line in lines if line.strip().startswith(key + ":")
    ]


def test_the_checks_run_on_pull_requests_on_pushes_to_main_and_by_hand(repo_root: Path) -> None:
    on = _block(_lines(repo_root), "on:", 0)
    events = sorted(
        line.strip().rstrip(":")
        for line in on
        if line.startswith("  ") and not line.startswith("   ")
    )
    push = _block(on, "push:", 2)

    assert events == sorted(EVENTS)
    assert _value(push, "branches") == [PUSHED_BRANCHES]


def test_only_a_run_of_the_same_pull_request_replaces_a_run(repo_root: Path) -> None:
    concurrency = _block(_lines(repo_root), "concurrency:", 0)

    assert [line.strip() for line in concurrency if line.strip() and line.strip()[0] != "#"] == (
        CONCURRENCY
    )


def test_the_docs_job_builds_with_the_newest_patch_of_the_floor_release(repo_root: Path) -> None:
    packages = json.loads((repo_root / LOCK).read_text(encoding="utf-8"))["packages"]
    floor = NODE_FLOOR.findall(packages[ASTRO]["engines"]["node"])[-1]

    assert _value(_job(repo_root, "docs"), "node-version") == [f'"{DOCS_NODE}"']
    assert tuple(map(int, DOCS_NODE.split("."))) >= tuple(map(int, floor.split(".")))
    assert DOCS_NODE.split(".")[0] == floor.split(".")[0]


def test_the_lint_group_pins_ruff_and_mypy_to_one_release(repo_root: Path) -> None:
    groups = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "dependency-groups"
    ]

    assert sorted(groups["lint"]) == LINT_PINS


def test_the_unit_job_installs_the_extras_its_tests_import(repo_root: Path) -> None:
    install = _step_run(_job(repo_root, "unit"), "Install")

    assert 'python -m pip install -e ".[plot,mcp]" --group dev' in install


def test_the_readme_step_checks_against_the_kept_results_only(repo_root: Path) -> None:
    run = _step_run(_job(repo_root, "lint"), "README figures are current")

    assert run == README_CHECK
    assert (repo_root / KEPT_RESULTS).is_file()
