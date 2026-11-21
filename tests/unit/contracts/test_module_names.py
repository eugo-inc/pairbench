# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each module of the package binds each of its top-level names once.

A module that binds a name twice at its top level keeps only the binding that
comes last, so code written beside the first one reads the second. Python, ruff
and mypy all accept it, so this test reads every module of the package and
lists each name a module binds twice: a function, a class, a name given a
value (also as a part of a tuple or a list, or after ``*``), or a name an
import binds (``import a.b`` binds ``a``, ``import a as b`` and
``from m import a as b`` bind ``b``; ``import a`` and ``import a.b`` bind ``a`` to one
package, so the two count once), at the top level or inside a top-level
``if`` or ``try``. Of an ``if`` and its ``else``, or of a ``try`` body and its
handlers, only one runs, so a name bound once in each is bound once. Functions
marked ``overload`` are left out, since they are written once per form on
purpose.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

import pairbench

PACKAGE = Path(pairbench.__file__).parent


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == "overload":
            return True
    return False


def _target_names(target: ast.expr) -> list[str]:
    """Return each name an assignment to ``target`` binds."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _target_names(element)]
    return []


def _either(packages: set[str], *branches: list[ast.stmt]) -> list[str]:
    """Return the names of branches of which one runs: each name as often as the most of them."""
    most: Counter[str] = Counter()
    for branch in branches:
        most |= Counter(_body_names(branch, packages))
    return list(most.elements())


def _body_names(body: list[ast.stmt], packages: set[str]) -> list[str]:
    """Return each name the statements of ``body`` bind, once per binding.

    ``packages`` holds the packages a plain ``import`` of the module has bound
    so far, each of which is counted the first time only.
    """
    names: list[str] = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_overload(node):
                names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(name for target in node.targets for name in _target_names(target))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names.extend(_target_names(node.target))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    names.append(alias.asname)
                elif (package := alias.name.partition(".")[0]) not in packages:
                    packages.add(package)
                    names.append(package)
        elif isinstance(node, ast.ImportFrom):
            names.extend(alias.asname or alias.name for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.If):
            names.extend(_either(packages, node.body, node.orelse))
        elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            names.extend(
                _either(
                    packages, node.body + node.orelse, *(handler.body for handler in node.handlers)
                )
            )
            names.extend(_body_names(node.finalbody, packages))
    return names


def _top_level_names(tree: ast.Module) -> list[str]:
    """Return each name the top level of a module binds, once per binding."""
    return _body_names(tree.body, set())


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

    assert _top_level_names(tree) == ["overload", "A", "B", "f", "g", "K", "A"]


# (a module's source, the names its top level binds, each as often as it is bound)
BINDINGS: dict[str, tuple[str, dict[str, int]]] = {
    "an import and an import as a name": (
        "import os.path\nimport json as j\nfrom a import b, c as d\nfrom e import *\n",
        {"os": 1, "j": 1, "b": 1, "d": 1},
    ),
    "a package and a module of it imported": (
        "import importlib\nimport importlib.util\n",
        {"importlib": 1},
    ),
    "a package imported and then given a value": ("import os\nos = 1\n", {"os": 2}),
    "a name imported twice": ("import json as j\nfrom x import y as j\n", {"j": 2}),
    "a tuple, a list and a starred name": (
        "A, (B, *C) = 1, (2, 3)\n[D, E] = 4, 5\nF: int = 6\n",
        {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1},
    ),
    "a name bound in a tuple and again alone": ("A, B = 1, 2\nB = 3\n", {"A": 1, "B": 2}),
    "a name bound in the if and the else": (
        "if X:\n    import tomllib\nelse:\n    tomllib = None\n",
        {"tomllib": 1},
    ),
    "a name bound twice in the if": ("if X:\n    A = 1\n    A = 2\n", {"A": 2}),
    "a name bound in the try and its handler": (
        "try:\n    import tomllib\nexcept ImportError:\n    tomllib = None\n",
        {"tomllib": 1},
    ),
    "a name bound in the try and again after it": (
        "try:\n    A = 1\nexcept ValueError:\n    pass\nfinally:\n    B = 2\nA = 3\n",
        {"A": 2, "B": 1},
    ),
    "a name bound in the try and its else": (
        "try:\n    A = 1\nexcept ValueError:\n    pass\nelse:\n    A = 2\n",
        {"A": 2},
    ),
}


@pytest.mark.parametrize("name", list(BINDINGS))
def test_every_binding_of_a_top_level_name_is_counted(name: str) -> None:
    source, counts = BINDINGS[name]

    assert Counter(_top_level_names(ast.parse(source))) == Counter(counts)


def test_no_module_of_the_package_binds_a_top_level_name_twice() -> None:
    twice: list[str] = []
    for module in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        counts = Counter(_top_level_names(tree))
        twice.extend(
            f"{module.relative_to(PACKAGE)}: {name}" for name, count in counts.items() if count > 1
        )

    assert twice == []
