# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Write the reference page of every public Python name from the source.

The page lists each name in ``__all__`` of ``pairbench`` and of
``pairbench.stats``, the ``Refusal`` they raise and the plug-in contract of
``pairbench.api``, each with its signature and its docstring. The source is
read, not imported, so the page is the same on every supported Python.

    python3 tools/api_reference.py            write docs/reference/python-names.md
    python3 tools/api_reference.py --check    exit 1 when that page is stale
"""

from __future__ import annotations

import argparse
import ast
import inspect
import re
import sys
import textwrap
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = "docs/reference/python-names.md"
SOURCE = "src"
WIDTH = 90

# The modules whose public names the page lists, and, for a module without
# ``__all__``, the names to take from it.
MODULES: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("pairbench", None),
    ("pairbench.stats", None),
    ("pairbench.errors", ("Refusal",)),
    (
        "pairbench.api",
        (
            "API_VERSION",
            "SideKind",
            "ResolvedSide",
            "SideContext",
            "SideLookup",
            "Driver",
            "DriverContext",
            "Invocation",
            "Step",
            "Sample",
            "ToolVersion",
            "CaptureReader",
            "Gate",
            "GateContext",
            "RuleProvider",
            "Reporter",
            "ReportOptions",
            "Launcher",
            "ServerHandle",
            "Endpoint",
        ),
    ),
)

# A name that is not defined by a statement the page can show.
VERSION = "__version__"
VERSION_TEXT = (
    "The version of the installed package, a string such as `1.2.3`. It is the "
    "version that `pairbench --version` prints and that every capture and results "
    "document records."
)

DESCRIPTION = (
    "Every public name of pairbench and pairbench.stats, and the plug-in contract of "
    "pairbench.api, with its signature and its docstring, written from the source."
)
TITLE = "Every public Python name"
OPENING = (
    "Each public name of `pairbench` and `pairbench.stats`, the `Refusal` they raise and "
    "the plug-in contract of `pairbench.api` is listed below with its signature and its "
    "docstring, read from the source. [Use pairbench from Python](python-api.md) and "
    "[add a plug-in](plugin-api.md) show how the names fit together."
)
MODEL_NOTE = (
    "Every class of the data model is a frozen dataclass with a JSON form: "
    "`value.to_json()` gives it, and the class method `from_json(data)` reads it back."
)


@dataclass(frozen=True)
class Definition:
    """Where a public name is defined: the module that defines it and its statement."""

    module: str
    node: ast.stmt


class ReferenceError_(Exception):
    """A public name whose definition cannot be found in the source."""


def module_file(repo: Path, module: str) -> Path:
    """Return the source file of a module of the package."""
    base = repo / SOURCE / Path(*module.split("."))
    package = base / "__init__.py"
    return package if package.is_file() else base.with_suffix(".py")


def parse(repo: Path, module: str) -> ast.Module:
    return ast.parse(module_file(repo, module).read_text(encoding="utf-8"))


def _statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield the module-level statements, those under an ``if`` included."""
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _statements(node.body)
            yield from _statements(node.orelse)


def public_names(tree: ast.Module) -> list[str]:
    """Return the strings of a module's ``__all__``."""
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        named = any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets)
        value = getattr(node, "value", None) if named else None
        if isinstance(value, (ast.List, ast.Tuple)):
            return [
                e.value
                for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    raise ReferenceError_("the module has no __all__")


def find(repo: Path, module: str, name: str, seen: frozenset[str] = frozenset()) -> Definition:
    """Find the statement that defines ``name`` as ``module`` exposes it."""
    if module in seen:
        raise ReferenceError_(f"{module}.{name}: the imports go round in a circle")
    tree = parse(repo, module)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return Definition(module, node)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return Definition(module, node)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return Definition(module, node)
    for node in _statements(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return find(repo, node.module, alias.name, seen | {module})
    raise ReferenceError_(f"{module}.{name} is not defined in the source")


def docstring(node: ast.stmt) -> str:
    """Return a statement's docstring as Markdown: code spans in single backticks."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return ""
    text = ast.get_docstring(node, clean=True) or ""
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    return _escape(text)


def _escape(text: str) -> str:
    """Keep a ``<`` outside code spans from opening an HTML tag."""
    parts = re.split(r"(`[^`]*`)", text)
    return "".join(
        part if part.startswith("`") else re.sub(r"<(?=[A-Za-z/!?])", "&lt;", part)
        for part in parts
    )


def _parameters(args: ast.arguments) -> list[str]:
    """Return the parameters of a signature as written, ``/`` and ``*`` included."""
    out: list[str] = []
    positional = [*args.posonlyargs, *args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(args.defaults))
    defaults += args.defaults
    for index, (arg, default) in enumerate(zip(positional, defaults, strict=True)):
        out.append(_parameter(arg, default))
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            out.append("/")
    if args.vararg is not None:
        out.append("*" + _parameter(args.vararg, None))
    elif args.kwonlyargs:
        out.append("*")
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        out.append(_parameter(arg, kw_default))
    if args.kwarg is not None:
        out.append("**" + _parameter(args.kwarg, None))
    return out


def _parameter(arg: ast.arg, default: ast.expr | None) -> str:
    text = arg.arg
    if arg.annotation is not None:
        text += ": " + ast.unparse(arg.annotation)
        if default is not None:
            text += " = " + ast.unparse(default)
    elif default is not None:
        text += "=" + ast.unparse(default)
    return text


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> list[str]:
    """Return the ``def`` lines of a function, one parameter per line when long."""
    parameters = _parameters(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    one = f"{indent}def {node.name}({', '.join(parameters)}){returns}"
    if len(one) <= WIDTH:
        return [one]
    inner = [f"{indent}    {p}," for p in parameters]
    return [f"{indent}def {node.name}(", *inner, f"{indent}){returns}"]


def _decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    return [f"@{ast.unparse(d)}" for d in node.decorator_list]


def _is_class_var(node: ast.AnnAssign) -> bool:
    return "ClassVar" in ast.unparse(node.annotation)


def fields(node: ast.ClassDef) -> list[str]:
    """Return the field lines of a class: its annotated names, class variables left out."""
    lines: list[str] = []
    for item in node.body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and not item.target.id.startswith("_")
            and not _is_class_var(item)
        ):
            line = f"{item.target.id}: {ast.unparse(item.annotation)}"
            if item.value is not None:
                line += f" = {ast.unparse(item.value)}"
            lines.append(line)
    return lines


def methods(node: ast.ClassDef) -> list[ast.FunctionDef]:
    """Return the public methods a class body defines."""
    return [
        item
        for item in node.body
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
    ]


def _heading(level: int, anchor: str, label: str) -> str:
    return f'{"#" * level} <span id="{anchor}"></span>`{label}`'


def _code(lines: Sequence[str]) -> list[str]:
    return ["```python", *lines, "```"]


def render_function(qualified: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    out = [_heading(3, qualified, qualified), ""]
    out += _code([*_decorators(node), *signature(node)])
    text = docstring(node)
    return out + (["", text] if text else []) + [""]


def render_class(qualified: str, node: ast.ClassDef) -> list[str]:
    bases = ", ".join(ast.unparse(b) for b in node.bases if not ast.unparse(b).startswith("_"))
    head = f"class {node.name}({bases}):" if bases else f"class {node.name}:"
    body = [f"    {line}" for line in fields(node)]
    if not body:
        body = [
            line
            for item in node.body
            if isinstance(item, ast.FunctionDef) and item.name == "__init__"
            for line in signature(item, "    ")
        ]
    out = [_heading(3, qualified, qualified), ""]
    out += _code([*_decorators(node), head, *(body or ["    ..."])])
    text = docstring(node)
    out += (["", text] if text else []) + [""]
    for method in methods(node):
        name = f"{qualified}.{method.name}"
        out += [_heading(4, name, f"{node.name}.{method.name}"), ""]
        out += _code([*_decorators(method), *signature(method)])
        text = docstring(method)
        out += (["", text] if text else []) + [""]
    return out


def render_value(qualified: str, node: ast.stmt) -> list[str]:
    out = [_heading(3, qualified, qualified), ""]
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        out += _code([ast.unparse(node)])
    return [*out, ""]


def _group(definition: Definition) -> int:
    node = definition.node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return 0
    if isinstance(node, ast.ClassDef):
        return 1
    return 2


def module_names(repo: Path, module: str, chosen: tuple[str, ...] | None) -> list[str]:
    return list(chosen) if chosen is not None else public_names(parse(repo, module))


def render(repo: Path = REPO) -> str:
    """Return the page."""
    lines = [
        "---",
        f'description: "{DESCRIPTION}"',
        "---",
        "",
        f"# {TITLE}",
        "",
        *textwrap.wrap(OPENING, 95, break_on_hyphens=False),
        "",
        "This page is written by `tools/api_reference.py`; do not edit it by hand.",
        "",
    ]
    for module, chosen in MODULES:
        lines += [f'## <span id="{module}"></span>Module `{module}`', ""]
        found: list[tuple[str, Definition | None]] = []
        for name in module_names(repo, module, chosen):
            found.append((name, None if name == VERSION else find(repo, module, name)))
        if any(d is not None and d.module == "pairbench.model" for _, d in found):
            lines += [*textwrap.wrap(MODEL_NOTE, 95, break_on_hyphens=False), ""]
        ordered = sorted(found, key=lambda item: 2 if item[1] is None else _group(item[1]))
        for name, definition in ordered:
            qualified = f"{module}.{name}"
            if definition is None:
                text = textwrap.wrap(VERSION_TEXT, 95, break_on_hyphens=False)
                lines += [_heading(3, qualified, qualified), "", *text, ""]
                continue
            node = definition.node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines += render_function(qualified, node)
            elif isinstance(node, ast.ClassDef):
                lines += render_class(qualified, node)
            else:
                lines += render_value(qualified, node)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def anchors(repo: Path = REPO) -> list[str]:
    """Return the anchor of every public name the page must carry."""
    out: list[str] = []
    for module, chosen in MODULES:
        out += [f"{module}.{name}" for name in module_names(repo, module, chosen)]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=inspect.cleandoc(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the page is stale")
    args = parser.parse_args(argv)
    page = REPO / PAGE
    text = render(REPO)
    if args.check:
        current = page.read_text(encoding="utf-8") if page.is_file() else ""
        if current != text:
            print(f"{PAGE} is stale: run python3 tools/api_reference.py", file=sys.stderr)
            return 1
        return 0
    page.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
