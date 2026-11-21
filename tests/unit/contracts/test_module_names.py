# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each module of the package binds each of its top-level names once.

A module that binds a name twice at its top level keeps only the binding that
comes last, so code written beside the first one reads the second. Python, ruff
and mypy all accept it, so this test reads every module of the package and
lists each name a module binds twice: a function, a class, or a name given a
value. Functions marked ``overload`` are left out, since they are written once
per form on purpose.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pairbench

PACKAGE = Path(pairbench.__file__).parent


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    return False


def _top_level_names(tree: ast.Module) -> list[str]:
    """Return each name the top level of a module binds, once per binding."""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_overload(node):
                names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(target.id for target in node.targets if isinstance(target, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            names.append(node.target.id)
    return names


def test_the_top_level_names_are_read_from_the_source() -> None:
    tree = ast.parse(
        "from typing import overload\n"
        "A = 1\n"
        "B: int = 2\n"
        "C: int\n"
        "def f() -> None: ...\n"
        "@overload\n"
        "def g(x: int) -> int: ...\n"
        "def g(x: int) -> int: return x\n"
        "class K: ...\n"
        "A = 3\n"
    )

    assert _top_level_names(tree) == ["A", "B", "f", "g", "K", "A"]


def test_no_module_of_the_package_binds_a_top_level_name_twice() -> None:
    twice: list[str] = []
    for module in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        counts = Counter(_top_level_names(tree))
        twice.extend(
            f"{module.relative_to(PACKAGE)}: {name}" for name, count in counts.items() if count > 1
        )

    assert twice == []
