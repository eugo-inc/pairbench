# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Apply each change of the mutation list to a copy of the repository and run its test.

    python tests/mutants/run_mutants.py [--only M01,M02] [--show-failures]

The repository is copied to a temporary folder once. Every named test must
pass on the unchanged copy first. Then each change is applied on its own,
its test is run with ``pytest`` and the file is put back. A change is
caught when its test fails (``pytest`` exit code 1). It survives when the
test still passes, which makes this command exit 1. Any other outcome, a
text that is not found exactly once or a test that does not run, is an
error and exits 2. ``--show-failures`` names the tests that failed, which
helps to pick the test of a new entry.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IGNORED = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "venvs",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    "site",
    "pairbench-runs",
    "*.egg-info",
)
TIMEOUT_S = 600
PYTEST_FAILED = 1


def load_list() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutants", Path(__file__).with_name("mutants.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mutants"] = module
    spec.loader.exec_module(module)
    return module


def problems_of(mutant: Any, root: Path) -> list[str]:
    """What is wrong with an entry of the list, read against the tree at ``root``."""
    found: list[str] = []
    path = root / mutant.file
    if not path.is_file():
        return [f"{mutant.file} does not exist"]
    count = path.read_text(encoding="utf-8").count(mutant.old)
    if count != 1:
        found.append(f"the text to change is found {count} times in {path.name}, not once")
    old_lines, new_lines = mutant.old.split("\n"), mutant.new.split("\n")
    changed = sum(a != b for a, b in zip(old_lines, new_lines, strict=False))
    if len(old_lines) != len(new_lines) or changed != 1:
        found.append("the change is not exactly one changed line")
    test_file = mutant.test.split("::")[0]
    if not (root / test_file).is_file():
        found.append(f"the test file {test_file} does not exist")
    return found


def pytest(copy: Path, targets: Sequence[str], *, show: bool) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"]
    if not show:
        argv.append("-x")
    return subprocess.run(
        [*argv, *targets],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT_S,
    )


def imported_from(copy: Path) -> Path:
    """Where the package is imported from in the copy, as pytest's ``pythonpath`` sets it."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); import pairbench; print(pairbench.__file__)",
        ],
        cwd=copy,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(done.stdout.strip()).resolve()


def failed_tests(output: str) -> list[str]:
    return [line.split(" ", 2)[1] for line in output.splitlines() if line.startswith("FAILED ")]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", default="", help="the ids to apply, separated by commas")
    parser.add_argument("--show-failures", action="store_true")
    options = parser.parse_args(argv)
    mutants = list(load_list().MUTANTS)
    if options.only:
        wanted = set(options.only.split(","))
        mutants = [m for m in mutants if m.id in wanted]
    bad = {m.id: problems_of(m, ROOT) for m in mutants}
    bad = {key: value for key, value in bad.items() if value}
    if bad:
        for key, value in bad.items():
            print(f"error  {key}: {'; '.join(value)}")
        return 2
    with tempfile.TemporaryDirectory(prefix="pairbench-mutants-") as scratch:
        copy = Path(scratch) / "repo"
        shutil.copytree(ROOT, copy, ignore=IGNORED)
        where = imported_from(copy)
        if not where.is_relative_to(copy.resolve()):
            print(f"error  the package is imported from outside the copy: {where}")
            return 2
        baseline = pytest(copy, sorted({m.test for m in mutants}), show=False)
        if baseline.returncode != 0:
            print("error  the named tests do not pass on the unchanged copy:")
            print(baseline.stdout[-4000:])
            return 2
        survived = errors = 0
        for mutant in mutants:
            path = copy / mutant.file
            original = path.read_text(encoding="utf-8")
            path.write_text(original.replace(mutant.old, mutant.new, 1), encoding="utf-8")
            try:
                done = pytest(copy, [mutant.test], show=options.show_failures)
            finally:
                path.write_text(original, encoding="utf-8")
            if done.returncode == PYTEST_FAILED:
                word = "caught"
            elif done.returncode == 0:
                word = "SURVIVED"
                survived += 1
            else:
                word = f"ERROR (pytest exit {done.returncode})"
                errors += 1
            print(f"{word:<8} {mutant.id}  {mutant.title}  [{mutant.test}]")
            if options.show_failures:
                for name in failed_tests(done.stdout):
                    print(f"           failed: {name}")
            if done.returncode not in (0, PYTEST_FAILED):
                print(done.stdout[-2000:] + done.stderr[-2000:])
    caught = len(mutants) - survived - errors
    print(f"{caught} of {len(mutants)} changes caught, {survived} survived, {errors} errors")
    if errors:
        return 2
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
