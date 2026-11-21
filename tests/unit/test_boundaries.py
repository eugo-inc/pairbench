# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Import boundaries and dependency rules of the package.

The source is read with ``ast``, so a module is judged without being
imported. Each rule is a function over ``{module name: source text}``; it is
run on the real tree, and on small made-up trees that must pass and must
fail, so a rule that stopped seeing anything would be noticed.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
PACKAGE = "pairbench"

HEADER = ("# SPDX-License-Identifier: Apache-2.0", "# Copyright (c) 2026, Eugo, Inc.")
# Folders that hold no source of the project: build output, caches and run folders.
HEADER_SKIPPED = frozenset(
    {"build", "dist", "site", "htmlcov", "node_modules", "pairbench-runs", "__pycache__"}
)

# The module an optional extra provides. An extra is imported only inside a function.
EXTRA_MODULES = frozenset({"pynvml", "mcp", "guidellm", "aiperf", "pytest_benchmark", "matplotlib"})
# The module of the plot extra. Only the charts import it, and only inside a function.
PLOT_MODULE = "matplotlib"
PLOT_PART = "charts"

# sides, drivers, gates and energy do not import each other.
ISOLATED = ("sides", "drivers", "gates", "energy")
# Only the runner composes them. The command line and the tool server may use
# the machine checks alone, for the gate and doctor commands.
MAY_IMPORT_GATES = ("runner", "cli", "mcp")

# stats is pure: it imports only model and errors, and nothing that reaches a
# file, a process or the network.
STATS_ALLOWED = (f"{PACKAGE}.model", f"{PACKAGE}.errors", f"{PACKAGE}.stats")
IMPURE_MODULES = frozenset(
    {
        "asyncio",
        "bz2",
        "concurrent",
        "ctypes",
        "dbm",
        "fileinput",
        "ftplib",
        "glob",
        "gzip",
        "http",
        "importlib",
        "io",
        "lzma",
        "mmap",
        "multiprocessing",
        "os",
        "pathlib",
        "pty",
        "runpy",
        "select",
        "selectors",
        "shelve",
        "shutil",
        "signal",
        "smtplib",
        "socket",
        "sqlite3",
        "ssl",
        "subprocess",
        "tarfile",
        "tempfile",
        "threading",
        "urllib",
        "webbrowser",
        "zipfile",
    }
)
# Calls that reach a file or a process whatever they are called on.
IMPURE_CALLS = frozenset(
    {"open", "read_text", "read_bytes", "write_text", "write_bytes", "Popen", "system"}
)

# The diagnostics part reaches a side through one function of the runner. It
# imports none of the parts the runner composes.
DIAGNOSE_FORBIDDEN_PARTS = ("sides", "drivers", "gates", "energy")
# The charts and the report page read the results document and the
# diagnostics document. Neither reads a capture.
NO_CAPTURE_PARTS = ("charts", "page")

# report reads Results and the diagnostics document, never a capture.
CAPTURE_NAMES = frozenset(
    {
        "Capture",
        "CasesRecord",
        "End",
        "GateRecord",
        "Header",
        "Launch",
        "Lineup",
        "MachineRecord",
        "Observation",
        "ReaderInfo",
        "RoundWitness",
        "Source",
        "Witness",
        "RECORD_TYPES",
        "load_capture",
        "record_from_json",
    }
)

# The command line and the tool server are thin shells over the public
# functions: they reach planning, running, analysis, capture reading, results
# reading, rendering, the explain step, the charts and filling through
# `pairbench.plan`, `run`, `analyse`, `load_capture`, `load_results`, `render`,
# `explain`, `load_diagnostics`, `draw` and `fill`.
SHELLS = ("cli", "mcp")
SHELL_FORBIDDEN_PARTS = (
    "sides",
    "drivers",
    "energy",
    "capture",
    "report",
    "diagnose",
    "charts",
    "page",
)
SHELL_FORBIDDEN_MODULES = (f"{PACKAGE}.stats.analyse", f"{PACKAGE}.results.figures")
SHELL_FORBIDDEN_NAMES = frozenset(
    {
        (f"{PACKAGE}.plan", "build_plan"),
        (f"{PACKAGE}.runner", "run_experiment"),
        (f"{PACKAGE}.results.writer", "read_results"),
    }
)

# The package files of these packages import none of the package's own modules at load
# time, so importing one module of a package does not load the others.
BARE_PACKAGES = ("sides", "drivers", "results")


@dataclass(frozen=True)
class Imp:
    """One import statement entry of one module."""

    module: str
    target: str
    name: str | None
    in_function: bool
    typing_only: bool
    lineno: int

    def where(self) -> str:
        what = self.target if self.name is None else f"{self.target}:{self.name}"
        return f"{self.module}:{self.lineno} imports {what}"


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def scan(module: str, source: str, *, is_package: bool = False) -> list[Imp]:
    """List every import of a module's source."""
    found: list[Imp] = []
    base = module if is_package else module.rpartition(".")[0]

    def visit(node: ast.AST, in_function: bool, typing_only: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    found.append(
                        Imp(module, alias.name, None, in_function, typing_only, child.lineno)
                    )
            elif isinstance(child, ast.ImportFrom):
                target = child.module or ""
                if child.level:
                    parts = base.split(".")
                    parts = parts[: len(parts) - (child.level - 1)]
                    target = ".".join([*parts, target] if target else parts)
                for alias in child.names:
                    found.append(
                        Imp(module, target, alias.name, in_function, typing_only, child.lineno)
                    )
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                visit(child, True, typing_only)
            elif isinstance(child, ast.If) and _is_type_checking(child.test):
                for stmt in child.body:
                    visit(ast.Module(body=[stmt], type_ignores=[]), in_function, True)
                for stmt in child.orelse:
                    visit(ast.Module(body=[stmt], type_ignores=[]), in_function, typing_only)
            else:
                visit(child, in_function, typing_only)

    visit(ast.parse(source), False, False)
    return found


def imports_of(tree: Mapping[str, str]) -> list[Imp]:
    out: list[Imp] = []
    for module, source in tree.items():
        out += scan(module, source, is_package=module.endswith(".__init__"))
    return out


def resolved(imp: Imp, tree: Mapping[str, str]) -> str:
    """Return the module an import reaches: ``from a import b`` reaches ``a.b`` when it exists."""
    if imp.name is not None:
        candidate = f"{imp.target}.{imp.name}"
        if candidate in tree or f"{candidate}.__init__" in tree:
            return candidate
    return imp.target


def part(dotted: str) -> str | None:
    """Return the part of the package a module is in: ``pairbench.stats.holm`` gives ``stats``."""
    pieces = dotted.split(".")
    if pieces[0] != PACKAGE:
        return None
    return pieces[1] if len(pieces) > 1 else ""


def real_tree() -> dict[str, str]:
    tree: dict[str, str] = {}
    for path in sorted((SRC / PACKAGE).rglob("*.py")):
        relative = path.relative_to(SRC).with_suffix("")
        tree[".".join(relative.parts)] = path.read_text(encoding="utf-8")
    return tree


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def rule_core_is_stdlib_only(tree: Mapping[str, str]) -> list[str]:
    """The core imports only the standard library; an extra only inside a function."""
    bad: list[str] = []
    for imp in imports_of(tree):
        top = imp.target.split(".")[0]
        if top == PACKAGE or top in sys.stdlib_module_names or top == "__future__":
            continue
        if top in EXTRA_MODULES and (imp.in_function or imp.typing_only):
            continue
        bad.append(imp.where())
    return bad


def rule_stats_is_pure(tree: Mapping[str, str]) -> list[str]:
    """stats imports only model and errors, touches no file and starts no process."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if part(imp.module) != "stats":
            continue
        target = resolved(imp, tree)
        top = target.split(".")[0]
        if top == PACKAGE:
            if not any(target == a or target.startswith(a + ".") for a in STATS_ALLOWED):
                bad.append(imp.where())
        elif top in IMPURE_MODULES:
            bad.append(imp.where())
    for module, source in tree.items():
        if part(module) != "stats":
            continue
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else None
            )
            if name in IMPURE_CALLS:
                bad.append(f"{module}:{node.lineno} calls {name}()")
    return bad


def rule_model_is_pure(tree: Mapping[str, str]) -> list[str]:
    """model imports only the standard library and errors; errors imports nothing of the package."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if imp.module not in (f"{PACKAGE}.model", f"{PACKAGE}.errors"):
            continue
        top = imp.target.split(".")[0]
        if top in IMPURE_MODULES:
            bad.append(imp.where())
        if top != PACKAGE or imp.typing_only:
            continue
        if imp.module.endswith(".model") and resolved(imp, tree) == f"{PACKAGE}.errors":
            continue
        bad.append(imp.where())
    return bad


def rule_isolated_parts(tree: Mapping[str, str]) -> list[str]:
    """sides, drivers, gates and energy do not import each other."""
    bad: list[str] = []
    for imp in imports_of(tree):
        mine, theirs = part(imp.module), part(resolved(imp, tree))
        if mine in ISOLATED and theirs in ISOLATED and mine != theirs:
            bad.append(imp.where())
    return bad


def rule_only_runner_composes(tree: Mapping[str, str]) -> list[str]:
    """Only the runner imports sides, drivers and energy; gates also serve the shells."""
    bad: list[str] = []
    for imp in imports_of(tree):
        mine, theirs = part(imp.module), part(resolved(imp, tree))
        if theirs not in ISOLATED or mine == theirs or mine in ISOLATED or mine == "runner":
            continue
        if theirs == "gates" and mine in MAY_IMPORT_GATES:
            continue
        bad.append(imp.where())
    return bad


def _reaches_a_capture(tree: Mapping[str, str], parts: tuple[str, ...]) -> list[str]:
    """List where a module of the given parts imports or names what holds a capture."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if part(imp.module) not in parts:
            continue
        target = resolved(imp, tree)
        if part(target) == "capture" or (
            target in (PACKAGE, f"{PACKAGE}.model") and imp.name in CAPTURE_NAMES
        ):
            bad.append(imp.where())
    for module, source in tree.items():
        if part(module) not in parts:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr in CAPTURE_NAMES:
                bad.append(f"{module}:{node.lineno} uses {node.attr}")
    return bad


def rule_report_reads_results_only(tree: Mapping[str, str]) -> list[str]:
    """report reads Results and the diagnostics document, never a capture."""
    return _reaches_a_capture(tree, ("report",))


def rule_diagnose_reaches_sides_through_the_runner(tree: Mapping[str, str]) -> list[str]:
    """diagnose imports none of sides, drivers, gates and energy."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if part(imp.module) != "diagnose":
            continue
        if part(resolved(imp, tree)) in DIAGNOSE_FORBIDDEN_PARTS:
            bad.append(imp.where())
    return bad


def rule_charts_and_page_read_no_capture(tree: Mapping[str, str]) -> list[str]:
    """charts and page read Results and the diagnostics document, never a capture."""
    return _reaches_a_capture(tree, NO_CAPTURE_PARTS)


def rule_only_charts_import_the_plot_module(tree: Mapping[str, str]) -> list[str]:
    """Only charts imports matplotlib, and only inside a function."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if imp.target.split(".")[0] != PLOT_MODULE:
            continue
        if part(imp.module) != PLOT_PART or not (imp.in_function or imp.typing_only):
            bad.append(imp.where())
    return bad


def rule_shells_are_thin(tree: Mapping[str, str]) -> list[str]:
    """cli and mcp go through the public functions."""
    bad: list[str] = []
    for imp in imports_of(tree):
        if part(imp.module) not in SHELLS:
            continue
        target = resolved(imp, tree)
        if (
            part(target) in SHELL_FORBIDDEN_PARTS
            or any(target == m or target.startswith(m + ".") for m in SHELL_FORBIDDEN_MODULES)
            or (imp.target, imp.name) in SHELL_FORBIDDEN_NAMES
        ):
            bad.append(imp.where())
    return bad


def rule_bare_packages(tree: Mapping[str, str]) -> list[str]:
    """The package files of sides, drivers and results import none of their own modules."""
    bad: list[str] = []
    for imp in imports_of(tree):
        for name in BARE_PACKAGES:
            if imp.module == f"{PACKAGE}.{name}.__init__" and not imp.in_function:
                target = resolved(imp, tree)
                if target.startswith(f"{PACKAGE}.{name}."):
                    bad.append(imp.where())
    return bad


def rule_plan_is_imported_by_name(tree: Mapping[str, str]) -> list[str]:
    """``pairbench.plan`` is a function and a submodule: import the submodule's names directly.

    ``import pairbench.plan`` and ``from pairbench import plan`` give the
    function where a module is expected.
    """
    bad: list[str] = []
    for imp in imports_of(tree):
        if (imp.name is None and imp.target == f"{PACKAGE}.plan") or (
            imp.target == PACKAGE and imp.name == "plan"
        ):
            bad.append(imp.where())
    return bad


RULES = (
    rule_core_is_stdlib_only,
    rule_stats_is_pure,
    rule_model_is_pure,
    rule_isolated_parts,
    rule_only_runner_composes,
    rule_report_reads_results_only,
    rule_diagnose_reaches_sides_through_the_runner,
    rule_charts_and_page_read_no_capture,
    rule_only_charts_import_the_plot_module,
    rule_shells_are_thin,
    rule_bare_packages,
    rule_plan_is_imported_by_name,
)


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.__name__)
def test_the_source_tree_keeps_the_rule(rule) -> None:  # type: ignore[no-untyped-def]
    assert rule(real_tree()) == []


def test_every_rule_is_applied_to_the_source_tree() -> None:
    written = sorted(name for name in globals() if name.startswith("rule_"))
    assert written == sorted(rule.__name__ for rule in RULES)
    assert len(RULES) == 12


# ---------------------------------------------------------------------------
# Each rule sees what it must refuse, and lets through what it must allow
# ---------------------------------------------------------------------------

P = PACKAGE

MUST_FAIL: tuple[tuple[str, dict[str, str], str], ...] = (
    ("rule_core_is_stdlib_only", {f"{P}.runner": "import requests\n"}, "requests"),
    ("rule_core_is_stdlib_only", {f"{P}.energy.nvml": "import pynvml\n"}, "pynvml"),
    ("rule_stats_is_pure", {f"{P}.stats.holm": f"from {P}.api import Sample\n"}, "api"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "import subprocess\n"}, "subprocess"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "def f():\n    open('x')\n"}, "open()"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "import io\n"}, "io"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "import sqlite3\n"}, "sqlite3"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "from importlib import resources\n"}, "importlib"),
    ("rule_stats_is_pure", {f"{P}.stats.floor": "import threading\n"}, "threading"),
    (
        "rule_stats_is_pure",
        {f"{P}.stats.floor": "import builtins\ndef f():\n    builtins.open('x')\n"},
        "open()",
    ),
    (
        "rule_stats_is_pure",
        {f"{P}.stats.floor": "def f(p):\n    return p.read_text()\n"},
        "read_text()",
    ),
    ("rule_stats_is_pure", {f"{P}.stats.a": f"import {P}\n"}, P),
    ("rule_model_is_pure", {f"{P}.model": f"from {P} import api\n", f"{P}.api": ""}, "api"),
    ("rule_model_is_pure", {f"{P}.model": "import subprocess\n"}, "subprocess"),
    ("rule_model_is_pure", {f"{P}.errors": f"from {P}.model import Results\n"}, "model"),
    (
        "rule_isolated_parts",
        {f"{P}.sides.serve": f"from {P}.drivers import guidellm\n", f"{P}.drivers.guidellm": ""},
        "drivers",
    ),
    (
        "rule_isolated_parts",
        {f"{P}.gates.quiet": f"def f():\n    import {P}.energy.smi\n"},
        "energy",
    ),
    ("rule_isolated_parts", {f"{P}.drivers.base": "from ..gates import quiet\n"}, "gates"),
    ("rule_only_runner_composes", {f"{P}.plan": f"import {P}.sides.base\n"}, "sides"),
    ("rule_only_runner_composes", {f"{P}.report.terminal": f"import {P}.gates.base\n"}, "gates"),
    ("rule_only_runner_composes", {f"{P}.cli.doctor": f"import {P}.energy.smi\n"}, "energy"),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.markdown": f"from {P}.model import Capture\n"},
        "Capture",
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.fill": f"from {P}.capture import reader\n", f"{P}.capture.reader": ""},
        "capture",
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.markdown": f"from {P} import load_capture\n"},
        "load_capture",
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.markdown": f"from {P} import model\nx = model.Capture\n"},
        "uses Capture",
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.terminal": f"import {P}\ndef f(p):\n    return {P}.load_capture(p)\n"},
        "uses load_capture",
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.terminal": f"from {P}.model import Witness\n"},
        "Witness",
    ),
    (
        "rule_diagnose_reaches_sides_through_the_runner",
        {f"{P}.diagnose.explain": f"from {P}.sides import container\n", f"{P}.sides.container": ""},
        "sides",
    ),
    (
        "rule_diagnose_reaches_sides_through_the_runner",
        {f"{P}.diagnose.instruments": f"import {P}.drivers.perf\n"},
        "drivers",
    ),
    (
        "rule_diagnose_reaches_sides_through_the_runner",
        {f"{P}.diagnose.explain": f"def f():\n    from {P}.gates import locks\n"},
        "gates",
    ),
    (
        "rule_diagnose_reaches_sides_through_the_runner",
        {f"{P}.diagnose.explain": "from ..energy import sampler\n"},
        "energy",
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {f"{P}.charts.rounds": f"from {P}.model import Capture\n"},
        "Capture",
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {f"{P}.charts.noise": f"from {P}.capture import reader\n", f"{P}.capture.reader": ""},
        "capture",
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {f"{P}.page.html": f"from {P} import load_capture\n"},
        "load_capture",
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {f"{P}.page.html": f"from {P} import model\nx = model.Observation\n"},
        "uses Observation",
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {f"{P}.charts.__init__": f"import {P}\ndef f(p):\n    return {P}.load_capture(p)\n"},
        "uses load_capture",
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {f"{P}.charts.verdict": "import matplotlib\n"},
        "matplotlib",
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {f"{P}.charts.rounds": "from matplotlib import pyplot\n"},
        "matplotlib",
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {f"{P}.page.html": "def f():\n    import matplotlib\n"},
        "matplotlib",
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {f"{P}.report.markdown": "def f():\n    import matplotlib.pyplot\n"},
        "matplotlib",
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {f"{P}.diagnose.flame": "def f():\n    from matplotlib import figure\n"},
        "matplotlib",
    ),
    ("rule_core_is_stdlib_only", {f"{P}.charts.verdict": "import matplotlib\n"}, "matplotlib"),
    ("rule_only_runner_composes", {f"{P}.diagnose.explain": f"import {P}.sides.base\n"}, "sides"),
    ("rule_shells_are_thin", {f"{P}.cli.run": f"from {P}.diagnose import explain\n"}, "diagnose"),
    ("rule_shells_are_thin", {f"{P}.cli.report": f"import {P}.charts\n"}, "charts"),
    ("rule_shells_are_thin", {f"{P}.mcp.server": f"from {P}.page import html\n"}, "page"),
    ("rule_shells_are_thin", {f"{P}.cli.run": f"from {P}.runner import run_experiment\n"}, "run"),
    (
        "rule_shells_are_thin",
        {f"{P}.mcp.server": f"from {P}.stats.analyse import analyse_captures\n"},
        "analyse",
    ),
    ("rule_shells_are_thin", {f"{P}.cli.report": f"import {P}.report.terminal\n"}, "report"),
    ("rule_shells_are_thin", {f"{P}.cli.compare": f"from {P}.capture import text\n"}, "capture"),
    (
        "rule_bare_packages",
        {f"{P}.sides.__init__": "from . import base\n", f"{P}.sides.base": ""},
        "base",
    ),
    ("rule_plan_is_imported_by_name", {f"{P}.runner": f"import {P}.plan\n"}, "plan"),
    ("rule_plan_is_imported_by_name", {f"{P}.cli.plan": f"from {P} import plan\n"}, "plan"),
)

MUST_PASS: tuple[tuple[str, dict[str, str]], ...] = (
    ("rule_core_is_stdlib_only", {f"{P}.energy.nvml": "def f():\n    import pynvml\n"}),
    ("rule_core_is_stdlib_only", {f"{P}.runner": f"import json\nfrom {P} import model\n"}),
    (
        "rule_stats_is_pure",
        {
            f"{P}.stats.holm": (
                f"import math\nfrom {P}.model import Rule\nfrom {P}.stats import floor\n"
            )
        },
    ),
    ("rule_model_is_pure", {f"{P}.model": f"import json\nfrom {P}.errors import Refusal\n"}),
    (
        "rule_model_is_pure",
        {
            f"{P}.errors": (
                "from typing import TYPE_CHECKING\n"
                f"if TYPE_CHECKING:\n    from {P}.model import Results\n"
            )
        },
    ),
    (
        "rule_isolated_parts",
        {f"{P}.sides.serve": f"from {P}.sides import base\nfrom {P} import api\n"},
    ),
    (
        "rule_only_runner_composes",
        {
            f"{P}.runner": (
                f"import {P}.sides.base\nimport {P}.gates.base\nimport {P}.energy.sampler\n"
            )
        },
    ),
    ("rule_only_runner_composes", {f"{P}.cli.gate": f"from {P}.gates import quiet\n"}),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.markdown": f"from {P}.model import Results\n"},
    ),
    (
        "rule_report_reads_results_only",
        {
            f"{P}.report.markdown": (
                f"from {P} import model\n"
                "def f(results: model.Results) -> str:\n"
                "    return results.artifacts.capture or results.run.command or ''\n"
            )
        },
    ),
    (
        "rule_report_reads_results_only",
        {f"{P}.report.terminal": f"from {P}.model import Diagnostics, Results\n"},
    ),
    (
        "rule_diagnose_reaches_sides_through_the_runner",
        {
            f"{P}.diagnose.explain": (
                f"import subprocess\nfrom {P} import api, model\n"
                f"from {P}.runner import open_explain\nfrom {P}.diagnose import folded\n"
            )
        },
    ),
    (
        "rule_charts_and_page_read_no_capture",
        {
            f"{P}.page.html": (
                f"import html\nfrom {P}.model import Diagnostics, Results\n"
                "def f(results: Results) -> str:\n"
                "    return results.artifacts.capture or ''\n"
            ),
            f"{P}.charts.rounds": f"from {P}.model import Results, Series\n",
        },
    ),
    (
        "rule_only_charts_import_the_plot_module",
        {
            f"{P}.charts.verdict": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from matplotlib.figure import Figure\n"
                "def draw():\n    import matplotlib\n    matplotlib.use('svg')\n"
            )
        },
    ),
    ("rule_core_is_stdlib_only", {f"{P}.charts.verdict": "def f():\n    import matplotlib\n"}),
    (
        "rule_shells_are_thin",
        {
            f"{P}.cli.run": (
                f"import {P}\nfrom {P} import registry\nfrom {P}.plan import format_plan\n"
                f"from {P}.stats import selftest\nfrom {P}.results.writer import write_results\n"
                f"from {P}.runner import record_profiles\nfrom {P}.gates import quiet\n"
                f"from {P}.runner import look_up_sides\nfrom {P}.config import load_experiment\n"
                f"from {P}.api import SideLookup, delegate\n"
            )
        },
    ),
    ("rule_shells_are_thin", {f"{P}.mcp.server": f"from {P}.cli.doctor import collect\n"}),
    (
        "rule_bare_packages",
        {f"{P}.results.__init__": "import json\nfrom importlib import resources\n"},
    ),
    ("rule_plan_is_imported_by_name", {f"{P}.runner": f"from {P}.plan import build_plan\n"}),
)


@pytest.mark.parametrize(("rule", "tree", "needle"), MUST_FAIL)
def test_a_rule_refuses_what_breaks_it(rule: str, tree: dict[str, str], needle: str) -> None:
    found = globals()[rule](tree)
    assert len(found) == 1, found
    assert needle in found[0]


@pytest.mark.parametrize(("rule", "tree"), MUST_PASS)
def test_a_rule_allows_what_keeps_it(rule: str, tree: dict[str, str]) -> None:
    assert globals()[rule](tree) == []


def test_relative_imports_are_resolved() -> None:
    found = scan(f"{P}.sides.serve", "from . import base\nfrom ..drivers.wall import WallDriver\n")
    assert [(i.target, i.name) for i in found] == [
        (f"{P}.sides", "base"),
        (f"{P}.drivers.wall", "WallDriver"),
    ]


# ---------------------------------------------------------------------------
# Every module imports with nothing installed beside the package
# ---------------------------------------------------------------------------

_IMPORT_ALL = """
import importlib, json, sys
failed = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except BaseException as exc:
        failed[name] = f"{type(exc).__name__}: {exc}"
print(json.dumps(failed))
"""


def test_every_module_imports_with_an_empty_path() -> None:
    modules = sorted(name.removesuffix(".__init__") for name in real_tree())
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH_")}
    env["PATH"] = ""
    env["PYTHONPATH"] = str(SRC)
    done = subprocess.run(
        [sys.executable, "-c", _IMPORT_ALL, json.dumps(modules)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {}
    assert f"{PACKAGE}.model" in modules


def _loaded_after(statements: str) -> list[str]:
    """Run statements in a fresh interpreter and list the modules of the package it loaded."""
    code = (
        "import sys\n"
        f"{statements}\n"
        "print(','.join(sorted(m for m in sys.modules if m.split('.')[0] == 'pairbench')))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC), "PATH": ""}
    done = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip().split(",")


def test_importing_the_package_loads_no_other_module_of_the_package() -> None:
    assert _loaded_after("import pairbench") == ["pairbench"]


def test_a_public_name_is_loaded_from_the_model_on_first_use() -> None:
    model_only = ["pairbench", "pairbench.errors", "pairbench.model"]
    assert _loaded_after("import pairbench\npairbench.Side") == model_only
    assert _loaded_after("from pairbench import Experiment, Results") == model_only
    assert _loaded_after("import pairbench\nprint(pairbench.__version__, file=sys.stderr)") == (
        model_only
    )
    assert _loaded_after("import pairbench\npairbench.plan\npairbench.explain") == ["pairbench"]


def test_every_public_name_of_the_package_loads() -> None:
    loaded = _loaded_after(
        "import pairbench\n"
        "missing = [n for n in pairbench.__all__ if not hasattr(pairbench, n)]\n"
        "assert missing == [], missing\n"
        "assert set(pairbench.__all__) <= set(dir(pairbench))\n"
        "from pairbench import *\n"
    )
    assert loaded == ["pairbench", "pairbench.errors", "pairbench.model"]


# ---------------------------------------------------------------------------
# Licence header
# ---------------------------------------------------------------------------


def source_files(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` and ``.sh`` file of a repository, wherever it lies.

    Hidden folders are left out, apart from ``.github``, and so are the
    folders that hold build output, caches and run folders.
    """
    for folder, names, files in os.walk(root):
        names[:] = sorted(
            name
            for name in names
            if name not in HEADER_SKIPPED
            and not name.endswith(".egg-info")
            and (not name.startswith(".") or name == ".github")
        )
        for name in sorted(files):
            if name.endswith((".py", ".sh")):
                yield Path(folder) / name


def _source_files() -> Iterator[Path]:
    return source_files(REPO)


def missing_header(text: str) -> bool:
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    return tuple(lines[:2]) != HEADER


def test_every_source_file_starts_with_the_licence_header() -> None:
    files = list(_source_files())
    assert REPO / "src" / PACKAGE / "model.py" in files
    bad = [str(p.relative_to(REPO)) for p in files if missing_header(p.read_text(encoding="utf-8"))]
    assert bad == []


def test_the_header_check_looks_at_every_folder_of_the_repository(tmp_path: Path) -> None:
    wanted = [
        "top.py",
        "docs/gen.py",
        "tools/error_rates.py",
        "showcases/a/run.sh",
        ".github/scripts/check.sh",
        "src/pkg/deep/er/mod.py",
    ]
    unwanted = [
        ".venv/lib/site.py",
        ".git/hooks/pre-commit.sh",
        "build/lib/mod.py",
        "dist/mod.py",
        "site/gen.py",
        "pairbench-runs/r1/run.sh",
        "src/pkg.egg-info/mod.py",
        "docs/page.md",
    ]
    for name in (*wanted, *unwanted):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("made-up\n", encoding="utf-8")
    found = sorted(str(p.relative_to(tmp_path)) for p in source_files(tmp_path))
    assert found == sorted(wanted)


def test_the_header_check_sees_a_missing_and_a_shebang_header() -> None:
    assert missing_header('"""No header."""\n')
    assert missing_header(HEADER[0] + "\n\n" + HEADER[1] + "\n")
    assert not missing_header("#!/bin/sh\n" + "\n".join(HEADER) + "\necho made-up\n")
    assert not missing_header("\n".join(HEADER) + "\n")
