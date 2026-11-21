# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the test suite needs, and the setup line of the contributing guide that installs it.

A test module imports only the standard library, pytest and pairbench at its
top; anything else is imported in the test that needs it, through
``pytest.importorskip``, so a missing package skips that test visibly
instead of failing the whole module. The packages of the ``test``, ``lint``
and ``build`` dependency groups, and every extra a test imports, are all on the
setup line, and the agent guide gives the same setup commands as the
contributing guide, so no test skips on the documented setup.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWED_AT_TOP = {"pytest", "pairbench", "__future__"}
SETUP_GROUPS = ("test", "lint", "build")
# The extras whose packages a test imports through pytest.importorskip.
TESTED_EXTRAS = {"mcp": "mcp", "plot": "matplotlib"}


def _top_imports(path: Path) -> list[str]:
    """The packages a module imports in its own body, not inside a function."""
    names: list[str] = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module.split(".")[0])
    return names


def test_a_test_module_imports_only_the_standard_library_pytest_and_pairbench_at_its_top() -> None:
    outside = {
        f"{path.relative_to(ROOT)}: {name}"
        for path in sorted((ROOT / "tests").rglob("*.py"))
        for name in _top_imports(path)
        if name not in sys.stdlib_module_names and name not in ALLOWED_AT_TOP
    }
    assert sorted(outside) == []


def test_the_check_sees_a_package_imported_at_the_top(tmp_path: Path) -> None:
    module = tmp_path / "test_made_up.py"
    module.write_text("import json\nimport madeuppkg.sub\n\ndef f():\n    import other\n")
    assert _top_imports(module) == ["json", "madeuppkg"]


def _setup_line(name: str = "CONTRIBUTING.md") -> str:
    text = (ROOT / name).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("pip install -e ")]
    assert len(lines) == 1, lines
    return lines[0]


def _setup_block(name: str) -> list[str]:
    """The commands of the fenced block that holds the setup line, without comments."""
    text = (ROOT / name).read_text(encoding="utf-8")
    for block in re.findall(r"^```\n(.*?)^```", text, flags=re.MULTILINE | re.DOTALL):
        if _setup_line(name) in block:
            return [line.split(" #")[0].rstrip() for line in block.splitlines()]
    raise AssertionError(f"{name} has no fenced block with the setup line")


def test_the_setup_line_installs_every_package_the_tests_and_the_lint_need() -> None:
    groups = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "dependency-groups"
    ]
    wanted = {
        re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
        for group in SETUP_GROUPS
        for requirement in groups[group]
    }
    installed = set(_setup_line().split()[3:])
    assert wanted
    assert sorted(wanted - installed) == []


def test_the_setup_line_installs_every_extra_a_test_imports() -> None:
    extras = re.search(r"\.\[([^\]]*)\]", _setup_line())
    assert extras is not None
    assert sorted(set(TESTED_EXTRAS) - set(extras.group(1).split(","))) == []
    imported = {
        found
        for path in sorted((ROOT / "tests").rglob("*.py"))
        for found in re.findall(r'importorskip\(\s*"([a-z_]+)', path.read_text(encoding="utf-8"))
    }
    optional = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]
    from_extras = {
        re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].replace("-", "_")
        for requirements in optional.values()
        for requirement in requirements
    }
    assert sorted((imported & from_extras) - set(TESTED_EXTRAS.values())) == []


def test_the_agent_guide_gives_the_same_setup_commands_as_the_contributing_guide() -> None:
    assert _setup_block("AGENTS.md") == _setup_block("CONTRIBUTING.md")
