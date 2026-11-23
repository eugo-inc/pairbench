# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The refusal type, the table of text codes and the exit codes."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from pairbench import errors
from pairbench.errors import CODES, EXIT_CODES, Refusal

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src" / "pairbench"

# Every text code with the exit codes it may carry, the default first.
EXPECTED: dict[str, tuple[int, ...]] = {
    "E_USAGE": (2,),
    "E_CONFIG": (2,),
    "E_SAME_SIDE": (3,),
    "E_SIDE_UNIDENTIFIED": (3,),
    "E_SIDE_UNRESOLVED": (3,),
    "E_ENTRYPOINT_UNREADABLE": (3,),
    "E_ENGINE_UNSUPPORTED": (3,),
    "E_PROFILER_MISSING": (3,),
    "E_PLOT_EXTRA_MISSING": (3,),
    "E_TWIN_DRIFT": (3, 6),
    "E_GATE_FAILED": (4,),
    "E_GATE_UNAVAILABLE": (4,),
    "E_LOCK": (4,),
    "E_PIN_UNSUPPORTED": (4,),
    "E_CPUS_MIXED_TYPES": (4,),
    "E_LAUNCH_FAILED": (5,),
    "E_SIDE_CHANGED": (5,),
    "E_GPU_NOT_RELEASED": (5,),
    "E_TOO_FEW_ROUNDS": (6,),
    "E_CASES_DIFFER": (6,),
    "E_BUDGET": (6,),
    "E_CAPTURE_INCOMPLETE": (6,),
    "E_GRID": (6,),
    "E_TWIN_ORPHAN": (6,),
    "E_ORDER_NOT_VARIED": (6,),
    "E_POOL_SAME": (6,),
    "E_POOL_IDENTICAL_ROWS": (6,),
    "E_POOL_TRUNCATED_COPY": (6,),
    "E_POOL_SIDE_DRIFT": (6,),
    "E_POOL_CASES": (6,),
    "E_POOL_MACHINE": (6,),
    "E_POOL_MIXED_PURPOSE": (6,),
    "E_FIGURE_MISSING": (7,),
    "E_INTERNAL": (8,),
    "E_INTERRUPTED": (130,),
}

# The text codes pairbench raises with a scope other than the experiment.
SCOPES: dict[str, tuple[str, ...]] = {
    "E_USAGE": ("experiment", "case"),
}

EXIT_NAMES: dict[str, int] = {
    "EXIT_OK": 0,
    "EXIT_CHECK_FAILED": 1,
    "EXIT_USAGE": 2,
    "EXIT_SIDE": 3,
    "EXIT_MACHINE": 4,
    "EXIT_LAUNCH": 5,
    "EXIT_ANALYSIS": 6,
    "EXIT_FIGURE_MISSING": 7,
    "EXIT_INTERNAL": 8,
    "EXIT_INTERRUPTED": 130,
}


def test_the_table_holds_exactly_the_known_codes_with_their_exit_codes() -> None:
    assert {code: row.exit_codes for code, row in CODES.items()} == EXPECTED


@pytest.mark.parametrize(("code", "exits"), sorted(EXPECTED.items()))
def test_a_code_has_its_default_exit_code_and_a_one_line_meaning(
    code: str, exits: tuple[int, ...]
) -> None:
    row = CODES[code]
    assert row.code == code
    assert errors.exit_code_for(code) == exits[0]
    assert row.meaning.strip() == row.meaning
    assert row.meaning
    assert "\n" not in row.meaning


@pytest.mark.parametrize(("name", "value"), sorted(EXIT_NAMES.items()))
def test_an_exit_code_has_a_named_constant(name: str, value: int) -> None:
    assert getattr(errors, name) == value


def test_every_exit_code_has_a_meaning() -> None:
    assert sorted(EXIT_CODES) == [0, 1, 2, 3, 4, 5, 6, 7, 8, 130]
    assert all(text for text in EXIT_CODES.values())


def test_every_code_the_documentation_names_is_in_the_table() -> None:
    named: set[str] = set()
    pages = [*(REPO / "docs").rglob("*.md"), *(REPO / "skills").rglob("*.md")]
    for page in sorted(pages):
        text = page.read_text(encoding="utf-8")
        if page.is_relative_to(REPO / "docs") and not text.startswith("---\n"):
            continue  # not a page of the documentation site
        named.update(re.findall(r"\bE_[A-Z][A-Z0-9_]*[A-Z0-9]\b", text))
    assert "E_SAME_SIDE" in named
    assert "E_BUDGET" in named
    # "E_CODE" stands for any code where the pages show the shape of a refusal's line.
    named.discard("E_CODE")
    assert sorted(named - set(CODES)) == []


def test_a_refusal_line_escapes_the_control_characters_of_its_message() -> None:
    refusal = Refusal("E_USAGE", "a\x1b[2Jb\x9bc\x7f")
    assert refusal.message == "a\x1b[2Jb\x9bc\x7f"
    assert refusal.line == "E_USAGE: a\\x1b[2Jb\\x9bc\\x7f"


def test_a_refusal_carries_code_exit_code_scope_and_one_line() -> None:
    refusal = Refusal("E_GRID", "cells are missing:\n  round 3,   side new", scope="experiment")
    assert refusal.code == "E_GRID"
    assert refusal.exit_code == 6
    assert refusal.scope == "experiment"
    assert refusal.message == "cells are missing: round 3, side new"
    assert refusal.line == "E_GRID: cells are missing: round 3, side new"
    assert str(refusal) == "E_GRID: cells are missing: round 3, side new"
    assert refusal.to_json() == {
        "code": "E_GRID",
        "scope": "experiment",
        "message": "cells are missing: round 3, side new",
    }
    assert refusal.detail == {}
    assert refusal.results is None


def test_twin_drift_is_exit_3_at_run_start_and_exit_6_in_analysis() -> None:
    assert Refusal("E_TWIN_DRIFT", "made-up").exit_code == 3
    assert Refusal("E_TWIN_DRIFT", "made-up", exit_code=6).exit_code == 6


def test_a_code_cannot_carry_an_exit_code_that_is_not_its_own() -> None:
    with pytest.raises(ValueError, match="E_GRID cannot carry exit code 3"):
        Refusal("E_GRID", "made-up", exit_code=3)


def test_an_unknown_code_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="text code is not in the table: E_MADE_UP"):
        Refusal("E_MADE_UP", "made-up")


def test_the_table_holds_the_scopes_of_each_code() -> None:
    assert {code: row.scopes for code, row in CODES.items()} == {
        code: SCOPES.get(code, ("experiment",)) for code in EXPECTED
    }


def test_a_scope_the_row_does_not_list_is_not_refused() -> None:
    # The scopes of a row document the code; a plug-in may raise it with another scope.
    assert Refusal("E_USAGE", "made-up", scope="case").scope == "case"
    assert Refusal("E_GRID", "made-up", scope="case").scope == "case"
    assert Refusal("E_CONFIG", "made-up", scope="case").to_json() == {
        "code": "E_CONFIG",
        "scope": "case",
        "message": "made-up",
    }


REFUSAL_CLASSES = frozenset({"Refusal", "RefusalRecord"})


def _refusals_raised_in(text: str, where: str) -> list[tuple[str, int, str | None, object]]:
    """Each refusal a source text makes: where it is, its code when the code is written as a
    literal, and its scope: the literal, ``experiment`` when none is given, or the expression
    when it is no literal. A ``Refusal`` or ``RefusalRecord`` is found also under a name it
    is imported as. A scope set after a refusal is made, by assigning an attribute ``scope``
    outside ``__init__``, by ``setattr`` or by ``replace``, is listed with no code and the
    scope ``set after construction``."""
    tree = ast.parse(text)
    names = set(REFUSAL_CLASSES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names |= {a.asname for a in node.names if a.asname and a.name.split(".")[-1] in names}
    inits = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        for inner in ast.walk(node)
    }
    found: list[tuple[str, int, str | None, object]] = []
    later = "set after construction"
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Attribute) and t.attr == "scope" for t in targets):
            if id(node) not in inits:
                found.append((f"{where}:{node.lineno}", node.lineno, None, later))
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        keywords = {k.arg: k.value for k in node.keywords}
        if name == "setattr" and len(node.args) >= 2:
            attribute = node.args[1]
            if isinstance(attribute, ast.Constant) and attribute.value == "scope":
                found.append((f"{where}:{node.lineno}", node.lineno, None, later))
            continue
        if name == "replace" and "scope" in keywords:
            found.append((f"{where}:{node.lineno}", node.lineno, None, later))
            continue
        if name not in names:
            continue
        first = node.args[0] if node.args else keywords.get("code")
        code = first.value if isinstance(first, ast.Constant) else None
        scope: object = "experiment"
        if "scope" in keywords:
            given = keywords["scope"]
            scope = given.value if isinstance(given, ast.Constant) else ast.dump(given)
        found.append(
            (f"{where}:{node.lineno}", node.lineno, code if isinstance(code, str) else None, scope)
        )
    return found


def _raised_in_package() -> list[tuple[str, int, str | None, object]]:
    return [
        found
        for path in sorted(SRC.rglob("*.py"))
        for found in _refusals_raised_in(
            path.read_text(encoding="utf-8"), str(path.relative_to(SRC.parent))
        )
    ]


def test_every_refusal_pairbench_raises_has_a_scope_its_row_lists() -> None:
    raised = _raised_in_package()
    assert len(raised) > 100
    wrong = [
        (where, code, scope)
        for where, _line, code, scope in raised
        if code is not None and (code not in CODES or scope not in CODES[code].scopes)
    ]
    assert wrong == []
    # A refusal whose code is chosen at run time is raised with the default scope, which
    # every row lists, and no scope is set after a refusal is made.
    unnamed = [(where, scope) for where, _line, code, scope in raised if code is None]
    assert unnamed
    assert all(scope == "experiment" for _where, scope in unnamed), unnamed
    assert all("experiment" in row.scopes for row in CODES.values())
    assert {scope for _w, _l, code, scope in raised if code is not None} == {"experiment", "case"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from pairbench.errors import Refusal as Refused\n"
            "Refused('E_GRID', 'x', scope='case')\n",
            [("made-up.py:2", 2, "E_GRID", "case")],
            id="imported-under-another-name",
        ),
        pytest.param(
            "import pairbench.errors as e\ne.Refusal('E_GRID', 'x', scope='case')\n",
            [("made-up.py:2", 2, "E_GRID", "case")],
            id="through-a-module-alias",
        ),
        pytest.param(
            "RefusalRecord(code='E_GRID', scope='case', message='x')\n",
            [("made-up.py:1", 1, "E_GRID", "case")],
            id="a-record",
        ),
        pytest.param(
            "r = Refusal('E_GRID', 'x')\nr.scope = 'case'\n",
            [
                ("made-up.py:1", 1, "E_GRID", "experiment"),
                ("made-up.py:2", 2, None, "set after construction"),
            ],
            id="scope-assigned-later",
        ),
        pytest.param(
            "r = Refusal('E_GRID', 'x')\nsetattr(r, 'scope', 'case')\n",
            [
                ("made-up.py:1", 1, "E_GRID", "experiment"),
                ("made-up.py:2", 2, None, "set after construction"),
            ],
            id="scope-set-by-setattr",
        ),
        pytest.param(
            "r = RefusalRecord(code='E_GRID', scope='experiment', message='x')\n"
            "r = replace(r, scope='case')\n",
            [
                ("made-up.py:1", 1, "E_GRID", "experiment"),
                ("made-up.py:2", 2, None, "set after construction"),
            ],
            id="scope-replaced",
        ),
        pytest.param(
            "class R:\n    def __init__(self):\n        self.scope = 'case'\n",
            [],
            id="scope-made-in-init",
        ),
    ],
)
def test_the_scope_scan_finds_every_way_a_refusal_gets_its_scope(
    source: str, expected: list[tuple[str, int, str | None, object]]
) -> None:
    assert sorted(_refusals_raised_in(source, "made-up.py"), key=str) == sorted(expected, key=str)


def test_an_unknown_scope_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="scope must be one of experiment, case"):
        Refusal("E_GRID", "made-up", scope="side")  # type: ignore[arg-type]


def test_a_refusal_keeps_detail_for_the_caller() -> None:
    refusal = Refusal("E_FIGURE_MISSING", "two figures are missing", detail={"missing": ["a", "b"]})
    assert refusal.exit_code == 7
    assert refusal.detail == {"missing": ["a", "b"]}
    assert "missing" not in refusal.to_json()
