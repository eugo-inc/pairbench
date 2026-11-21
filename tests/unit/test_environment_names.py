# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Every environment variable the tool reads or sets is its own or a standard one.

The tool's own variables start with ``PAIRBENCH_``. A variable that other
software defines keeps its name, and each one is listed in ``STANDARD`` with
the software that defines it. The reference page of the variables lists
exactly the names the source uses, with one anchor each.

The names are collected from the source's syntax tree, in these forms:

* a module constant whose name holds ``VARIABLE``, such as
  ``CONFIG_VARIABLE = "PAIRBENCH_CONFIG"`` or a tuple, set or mapping of names
  (the values of a mapping); a constant whose name ends in ``PREFIX`` or
  ``PREFIXES`` holds name prefixes;
* a look-up on an environment mapping (a name or attribute called ``env``,
  ``environ`` or ``environment``, or ending in ``_env``): ``.get(NAME)``,
  ``.pop(NAME)``, ``.setdefault(NAME)``, ``[NAME]`` read or written, and
  ``NAME in`` the mapping; ``os.getenv``, ``os.putenv`` and ``os.unsetenv``;
* the keys of a mapping, or the items of a sequence, given as the keyword
  ``env``, ``environ``, ``set`` or ``unset``;
* a prefix tested with ``.startswith`` on a name taken from an environment
  mapping, or beside a test against a constant of names in the same
  ``or``/``and`` expression.

``NAME`` above is a text, a constant, or a collection of either. A prefix is
written with a trailing ``*``, as ``DOCKER_*``.

A second, coarser net catches a name the forms above miss, such as one written
into a copy of an environment held under another name: every key in capitals
used on any mapping (``[KEY]``, ``.get``, ``.pop``, ``.setdefault``, a key of a
mapping written out, a key given to ``.update`` or ``dict``) counts as a name,
unless it is a text code (``E_...``) or listed in ``NOT_VARIABLES`` with what
it is instead.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest

TOOL_PREFIX = "PAIRBENCH_"
PAGE = Path("docs/reference/environment.md")
SOURCE = Path("src/pairbench")
TOOL = "pairbench"
# The scripts of the showcases, and the files of the test suite that read its
# switches. The page lists their own variables beside the tool's.
SHOWCASES = Path("showcases")
HARNESS = (Path("tests/conftest.py"), Path("tests/e2e/conftest.py"))
# A variable a shell script expands: ``$NAME`` or ``${NAME...}``, in capitals.
SHELL_NAME = re.compile(r"\$\{?([A-Z_][A-Z0-9_]*)")

# Standard names the tool reads or sets, each with the software that defines
# it. The reference page names the same software for each.
STANDARD: dict[str, str] = {
    "CI": "automated pipelines (GitHub Actions, GitLab CI/CD)",
    "PATH": "POSIX",
    "HOME": "POSIX",
    "TMPDIR": "POSIX",
    "USER": "login (util-linux)",
    "container": "container managers (systemd container interface)",
    "KUBERNETES_SERVICE_HOST": "Kubernetes",
    "DOCKER_HOST": "Docker",
    "DOCKER_*": "Docker",
    "CONTAINER_HOST": "Podman",
    "CONTAINER_*": "Podman",
    "CONTAINERS_*": "Podman",
    "BUILDAH_*": "Podman",
    "REGISTRY_AUTH*": "Podman",
    "VIRTUAL_ENV": "Python (venv)",
    "CONDA_PREFIX": "conda",
    "CONDA_DEFAULT_ENV": "conda",
    "CONDA_EXE": "conda",
    "PYTHONHOME": "Python",
    "PYTHONPATH": "Python",
    "PYTHONPERFSUPPORT": "Python",
    "CUDA_VISIBLE_DEVICES": "CUDA",
    "CUDA_DEVICE_ORDER": "CUDA",
    "HTTP_PROXY": "Go (net/http)",
    "HTTPS_PROXY": "Go (net/http)",
    "NO_PROXY": "Go (net/http)",
    "ALL_PROXY": "curl",
    "SSL_CERT_FILE": "Go (crypto/x509)",
    "SSL_CERT_DIR": "Go (crypto/x509)",
    "GODEBUG": "Go (runtime)",
    "GOGC": "Go (runtime)",
    "GOMAXPROCS": "Go (runtime)",
    "GOMEMLIMIT": "Go (runtime)",
    "GOTRACEBACK": "Go (runtime)",
    "XDG_*": "XDG Base Directory Specification",
    "LD_*": "the dynamic linker (ld.so)",
    "DYLD_*": "the dynamic linker of macOS (dyld)",
}

# Names that must be found, so a collector that finds nothing cannot pass.
KNOWN = frozenset(
    {
        "PAIRBENCH_CONFIG",
        "PAIRBENCH_OUT",
        "PAIRBENCH__*",
        "PAIRBENCH_WORK_FACTOR",
        "PAIRBENCH_ENV_PAD",
        "CI",
        "PATH",
        "container",
        "CUDA_VISIBLE_DEVICES",
        "PYTHONPERFSUPPORT",
        "DOCKER_HOST",
        "DOCKER_*",
        "PYTHONHOME",
        "VIRTUAL_ENV",
    }
)

# Keys in capitals that the source uses on a mapping and that are not
# environment variables, each with what it is.
NOT_VARIABLES: dict[str, str] = {
    "NAME": "a key of the operating system's os-release file",
    "VERSION_ID": "a key of the operating system's os-release file",
}

ENV_RECEIVER = re.compile(r"^_*(?:\w+_)?(?:env|environ|environment)$")
ENV_KEYWORDS = frozenset({"env", "environ", "set", "unset"})
LOOKUPS = frozenset({"get", "pop", "setdefault"})
OS_CALLS = frozenset({"getenv", "putenv", "unsetenv"})
WRAPPERS = frozenset({"sorted", "list", "tuple", "set", "frozenset"})
CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
PREFIX_NAME = re.compile(r"PREFIX(?:ES)?$")
# The page's section on the engine's own variables, and what it says of their case.
ENGINE_SECTION = "## Variables the container engine's command reads"
ANY_CASE = "A name matches in any case: `http_proxy` counts as `HTTP_PROXY`."
UPPER_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
TEXT_CODE = re.compile(r"^E_[A-Z0-9_]+$")
HEADING = re.compile(r"^### `([^`]+)`\s*$")
DEFINED_BY = re.compile(r"^Defined by (.+?)\.\s*$")


# ---------------------------------------------------------------------------
# The collector
# ---------------------------------------------------------------------------


def _receiver(node: ast.AST) -> bool:
    """Say whether a node names an environment mapping."""
    if isinstance(node, ast.Name):
        return bool(ENV_RECEIVER.match(node.id))
    if isinstance(node, ast.Attribute):
        return bool(ENV_RECEIVER.match(node.attr))
    return False


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """The module-level assignments of upper-case names, by name."""
    found: dict[str, ast.expr] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and CONSTANT_NAME.match(target.id):
            found[target.id] = value
    return found


class Collector:
    """Collect the environment variable names of a tree of Python files."""

    def __init__(self, root: Path) -> None:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        self.trees = {
            path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in paths
        }
        self.constants: dict[str, ast.expr] = {}
        for tree in self.trees.values():
            for name, value in _module_constants(tree).items():
                self.constants.setdefault(name, value)
        self.names: set[str] = set()
        self.prefixes: set[str] = set()

    # -- resolving a node to texts ------------------------------------------

    def texts(self, node: ast.AST | None, *, values: bool = True, depth: int = 0) -> list[str]:
        """The texts a node stands for: a text, a constant, a collection of either."""
        if node is None or depth > 8:
            return []
        deeper = depth + 1
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            value = self.constants.get(name)
            return self.texts(value, depth=deeper) if value is not None else []
        if isinstance(node, ast.Starred):
            return self.texts(node.value, values=values, depth=deeper)
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            return [text for item in node.elts for text in self.texts(item, depth=deeper)]
        if isinstance(node, ast.Dict):
            chosen = node.values if values else [key for key in node.keys if key is not None]
            return [text for item in chosen for text in self.texts(item, depth=deeper)]
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in WRAPPERS and node.args:
                return self.texts(node.args[0], depth=deeper)
            if isinstance(func, ast.Attribute) and func.attr == "get":
                # NAMES.get(key, default) on a mapping constant of names.
                return self.texts(func.value, depth=deeper)
        return []

    # -- the forms ----------------------------------------------------------

    def collect(self) -> set[str]:
        for name, value in self.constants.items():
            if "VARIABLE" in name:
                self._add(self.texts(value), prefix=bool(PREFIX_NAME.search(name)))
        for tree in self.trees.values():
            from_env = self._names_taken_from_env(tree)
            for node in ast.walk(tree):
                self._visit(node, from_env)
        return {*self.names, *(f"{prefix}*" for prefix in self.prefixes)}

    def _add(self, texts: Iterable[str], *, prefix: bool = False) -> None:
        (self.prefixes if prefix else self.names).update(text for text in texts if text)

    def _names_taken_from_env(self, tree: ast.Module) -> set[str]:
        """Loop names bound by iterating an environment mapping."""
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.For | ast.comprehension):
                continue
            if not self._iterates_env(node.iter):
                continue
            target = node.target
            first = target.elts[0] if isinstance(target, ast.Tuple) else target
            if isinstance(first, ast.Name):
                found.add(first.id)
        return found

    def _iterates_env(self, node: ast.expr) -> bool:
        while isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in WRAPPERS and node.args:
                node = node.args[0]
            elif isinstance(func, ast.Attribute) and func.attr in {"items", "keys"}:
                node = func.value
            else:
                return False
        return _receiver(node)

    def _visit(self, node: ast.AST, from_env: set[str]) -> None:
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in LOOKUPS and _receiver(func.value) and node.args:
                    self._add(self.texts(node.args[0]))
                is_os = isinstance(func.value, ast.Name) and func.value.id == "os"
                if func.attr in OS_CALLS and is_os and node.args:
                    self._add(self.texts(node.args[0]))
                if (
                    func.attr == "startswith"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in from_env
                    and node.args
                ):
                    self._add(self.texts(node.args[0]), prefix=True)
            for keyword in node.keywords:
                if keyword.arg in ENV_KEYWORDS:
                    self._add(self.texts(keyword.value, values=False))
        elif isinstance(node, ast.Subscript) and _receiver(node.value):
            self._add(self.texts(node.slice))
        elif isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, ast.In | ast.NotIn) and _receiver(right):
                    self._add(self.texts(node.left))
        elif isinstance(node, ast.BoolOp):
            self._beside_a_holder(node)

    def _beside_a_holder(self, node: ast.BoolOp) -> None:
        """``x in NAMES or x.startswith(PREFIXES)``: the prefixes are names too."""
        holders = [
            right
            for value in node.values
            if isinstance(value, ast.Compare)
            for op, right in zip(value.ops, value.comparators, strict=True)
            if isinstance(op, ast.In | ast.NotIn)
            and isinstance(right, ast.Name)
            and "VARIABLE" in right.id
        ]
        if not holders:
            return
        for value in node.values:
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr == "startswith"
                and value.args
            ):
                self._add(self.texts(value.args[0]), prefix=True)


def collect(root: Path) -> set[str]:
    """Every environment variable name the Python files under ``root`` read or set."""
    return Collector(root).collect()


def mapping_keys(root: Path) -> set[str]:
    """Every key in capitals the Python files under ``root`` use on any mapping.

    Text codes (``E_...``) are left out; the keys of ``NOT_VARIABLES`` are not.
    """
    collector = Collector(root)
    found: list[str] = []
    for tree in collector.trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and not _is_literal_type(node.value):
                found += collector.texts(node.slice)
            elif isinstance(node, ast.Dict):
                found += [text for key in node.keys for text in collector.texts(key)]
            elif isinstance(node, ast.Call):
                func = node.func
                attribute = func.attr if isinstance(func, ast.Attribute) else None
                if attribute in LOOKUPS and node.args:
                    found += collector.texts(node.args[0])
                if attribute == "update" or (isinstance(func, ast.Name) and func.id == "dict"):
                    found += [keyword.arg for keyword in node.keywords if keyword.arg]
    return {text for text in found if UPPER_KEY.match(text) and not TEXT_CODE.match(text)}


def _is_literal_type(node: ast.expr) -> bool:
    """Whether a subscripted node is ``Literal``, whose texts are values of a type."""
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", None)
    return name == "Literal"


def source_names(root: Path) -> set[str]:
    """The names ``collect`` finds, with the keys ``mapping_keys`` finds that are not listed."""
    return collect(root) | {key for key in mapping_keys(root) if key not in NOT_VARIABLES}


def shell_names(root: Path) -> set[str]:
    """Every variable name in capitals the shell scripts under ``root`` expand."""
    return {
        match.group(1)
        for path in sorted(root.rglob("*.sh"))
        for match in SHELL_NAME.finditer(path.read_text(encoding="utf-8"))
    }


def side_names(repo_root: Path) -> set[str]:
    """The tool's own names the showcase scripts and the test suite's switches use."""
    found = shell_names(repo_root / SHOWCASES)
    for path in HARNESS:
        found |= collect(repo_root / path)
    return {name for name in found if name.startswith(TOOL_PREFIX)}


def strays(names: Iterable[str]) -> list[str]:
    """The names that are neither the tool's own nor a listed standard name."""
    return sorted(
        name for name in names if not name.startswith(TOOL_PREFIX) and name not in STANDARD
    )


# ---------------------------------------------------------------------------
# The reference page
# ---------------------------------------------------------------------------


def page_entries(text: str) -> Iterator[tuple[str, str | None]]:
    """Each variable heading of the page with its "Defined by" text."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        heading = HEADING.match(line)
        if not heading:
            continue
        defined: str | None = None
        for following in lines[index + 1 :]:
            if following.startswith("#"):
                break
            found = DEFINED_BY.match(following.strip())
            if found:
                defined = found.group(1)
                break
        yield heading.group(1), defined


def anchor(heading: str) -> str:
    """The anchor a Markdown heading gets: lower-cased, word characters, ``-`` and ``_`` kept."""
    return re.sub(r"[^\w\- ]", "", heading).strip().lower().replace(" ", "-")


def plain(text: str) -> str:
    """A Markdown text without its links and code marks."""
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "")


# ---------------------------------------------------------------------------
# The source
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def names(repo_root: Path) -> set[str]:
    return source_names(repo_root / SOURCE)


def test_the_collector_finds_the_names_the_source_is_known_to_use(names: set[str]) -> None:
    assert sorted(KNOWN - names) == []


def test_every_name_is_the_tool_s_own_or_a_listed_standard_name(names: set[str]) -> None:
    assert strays(names) == []


def test_every_listed_standard_name_is_used_by_the_source(names: set[str]) -> None:
    assert sorted(set(STANDARD) - names) == []


def test_the_tool_s_own_names_are_written_in_capitals(names: set[str]) -> None:
    own = [name for name in names if name.startswith(TOOL_PREFIX)]

    assert own
    assert [name for name in own if name != name.upper()] == []


def test_the_showcase_scripts_expand_only_the_tool_s_names_or_standard_ones(
    repo_root: Path,
) -> None:
    found = shell_names(repo_root / SHOWCASES)

    assert "PAIRBENCH_SHOWCASE_ENGINE" in found
    assert strays(found) == []


def test_the_test_suite_s_switches_carry_the_prefix(repo_root: Path) -> None:
    found: set[str] = set()
    for path in HARNESS:
        found |= {name for name in collect(repo_root / path) if "REQUIRE" in name or "TEST" in name}

    assert found
    assert [name for name in sorted(found) if not name.startswith(TOOL_PREFIX)] == []


def test_a_shell_name_is_found_in_both_forms(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_text(
        '#!/bin/sh\nloops=${MADE_UP_LOOPS:-1}\necho "$MADE_UP_PLAIN" $lower\n', encoding="utf-8"
    )

    assert shell_names(tmp_path) == {"MADE_UP_LOOPS", "MADE_UP_PLAIN"}


# Each form the collector reads, written into a made-up module with a name
# that has no prefix and is not a standard name.
FORMS = {
    "a text read from os.environ": 'import os\nos.environ.get("MADE_UP_SETTING")\n',
    "os.getenv": 'import os\nos.getenv("MADE_UP_SETTING")\n',
    "a constant read from a mapping": (
        'SETTING_VARIABLE = "MADE_UP_SETTING"\n'
        "def f(environ):\n    return environ.get(SETTING_VARIABLE)\n"
    ),
    "a text written into a mapping": 'def f(env):\n    env["MADE_UP_SETTING"] = "1"\n',
    "a membership test": 'def f(environ):\n    return "MADE_UP_SETTING" in environ\n',
    "a mapping given as env": 'def f(run):\n    run(env={"MADE_UP_SETTING": "1"})\n',
    "names given as unset": 'def f(run):\n    run(unset=("MADE_UP_SETTING",))\n',
    "a new member of a constant of names": 'OWN_VARIABLES = ("PAIRBENCH_X", "MADE_UP_SETTING")\n',
    "an attribute named like an environment": (
        'class A:\n    def f(self):\n        return self._environment["MADE_UP_SETTING"]\n'
    ),
    "a prefix tested on names of the environment": (
        'def f(environ):\n    return [n for n in environ if n.startswith("MADE_UP_")]\n'
    ),
}


@pytest.mark.parametrize("form", sorted(FORMS))
def test_a_name_without_the_prefix_is_found_in_each_form(tmp_path: Path, form: str) -> None:
    (tmp_path / "module.py").write_text(FORMS[form], encoding="utf-8")

    found = strays(collect(tmp_path))

    assert found in (["MADE_UP_SETTING"], ["MADE_UP_*"])


def test_a_name_with_the_prefix_or_a_standard_name_passes(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(
        'import os\nos.environ.get("PAIRBENCH_TOKEN")\nos.environ.get("CI")\n', encoding="utf-8"
    )

    found = collect(tmp_path)

    assert found == {"PAIRBENCH_TOKEN", "CI"}
    assert strays(found) == []


def test_a_capitalised_key_of_any_mapping_is_found(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(
        "SETTING = 'MADE_UP_CONSTANT'\n"
        "def f(table, more):\n"
        "    out = dict(table)\n"
        '    out["MADE_UP_WRITTEN"] = "1"\n'
        "    out[SETTING] = more.get('MADE_UP_READ')\n"
        "    more.update({'MADE_UP_UPDATED': '1'}, MADE_UP_KEYWORD='1')\n"
        "    kind: Literal['MADE_UP_VALUE'] = 'MADE_UP_VALUE'\n"
        "    return {'MADE_UP_SHOWN': 1, 'E_MADE_UP': 2, 'lower_key': 3, 'NAME': 4}, out\n",
        encoding="utf-8",
    )

    assert sorted(mapping_keys(tmp_path)) == [
        "MADE_UP_CONSTANT",
        "MADE_UP_KEYWORD",
        "MADE_UP_READ",
        "MADE_UP_SHOWN",
        "MADE_UP_UPDATED",
        "MADE_UP_WRITTEN",
        "NAME",
    ]
    assert strays(source_names(tmp_path)) == [
        "MADE_UP_CONSTANT",
        "MADE_UP_KEYWORD",
        "MADE_UP_READ",
        "MADE_UP_SHOWN",
        "MADE_UP_UPDATED",
        "MADE_UP_WRITTEN",
    ]


def test_every_listed_key_that_is_not_a_variable_is_used_by_the_source(repo_root: Path) -> None:
    assert sorted(set(NOT_VARIABLES) - mapping_keys(repo_root / SOURCE)) == []


def test_texts_that_are_not_variable_names_are_left_out(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(
        'LABEL = "MADE_UP_LABEL"\n'
        "def f(table, environ):\n"
        '    table["MADE_UP_KEY"] = 1\n'
        '    return "MADE_UP_WORD".startswith("MADE"), environ.get(LABEL.lower())\n',
        encoding="utf-8",
    )

    assert collect(tmp_path) == set()


# ---------------------------------------------------------------------------
# A variable passed through by name
# ---------------------------------------------------------------------------

# A name with the tool's prefix: a command side does not inherit it, so it
# reaches the launch only through ``env_pass``. The tests start with every such
# name removed, so the test sets it itself.
PASSED_NAME = "PAIRBENCH_MADE_UP_HUB_TOKEN"
PASSED_VALUE = "made-up-value-0451"
# The workload fails unless the variable reached it with its value, and never
# prints the value.
CHECKING_WORKLOAD = f"""\
import json, os, sys
if os.environ.get("{PASSED_NAME}") != "{PASSED_VALUE}":
    sys.exit(3)
factor = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))
print("::pairbench::", json.dumps({{"case": "c", "value": 1.0 * factor, "unit": "s"}}))
"""


def test_a_variable_passed_by_name_reaches_the_launch_and_its_value_is_written_nowhere(
    cli: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workload = tmp_path / "workload.py"
    workload.write_text(CHECKING_WORKLOAD, encoding="utf-8")
    config = tmp_path / "pairbench.toml"
    config.write_text(
        "[workload]\n"
        f"argv = [{json.dumps(str(workload))}]\n"
        'driver = "lines"\n'
        "[sides.new]\n"
        f'cmd = [{json.dumps(sys.executable)}, "{{workload}}"]\n'
        "[sides.old]\n"
        f'cmd = [{json.dumps(sys.executable)}, "-B", "{{workload}}"]\n'
        "baseline = true\n"
        "[launch]\n"
        f'env_pass = ["{PASSED_NAME}"]\n'
        "[controls]\n"
        'positive_via = "factor"\n'
        "[explain]\n"
        'mode = "off"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(PASSED_NAME, PASSED_VALUE)
    out = tmp_path / "run"

    result = cli("run", "--config", config, "--gates", "off", "--plots", "off", "--out", out)

    assert result.code == 0, result.err
    written = [path for path in sorted(out.rglob("*")) if path.is_file()]
    assert written
    holding = [
        path.relative_to(out).as_posix()
        for path in written
        if PASSED_VALUE.encode() in path.read_bytes()
    ]
    assert holding == []
    assert PASSED_VALUE not in result.out + result.err
    assert PASSED_NAME in (out / "capture.jsonl").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def entries(repo_root: Path) -> list[tuple[str, str | None]]:
    return list(page_entries((repo_root / PAGE).read_text(encoding="utf-8")))


def test_the_page_lists_every_name_of_the_source_and_no_other(
    repo_root: Path, names: set[str], entries: list[tuple[str, str | None]]
) -> None:
    listed = [name for name, _defined in entries]
    every = names | side_names(repo_root)

    assert sorted(set(listed) - every) == []
    assert sorted(every - set(listed)) == []


def test_each_name_has_one_heading_and_its_own_anchor(
    entries: list[tuple[str, str | None]],
) -> None:
    listed = [name for name, _defined in entries]
    anchors = [anchor(f"`{name}`") for name in listed]

    assert sorted({name for name in listed if listed.count(name) > 1}) == []
    assert len(set(anchors)) == len(anchors)
    assert [name for name, made in zip(listed, anchors, strict=True) if not made] == []


def test_the_page_names_who_defines_each_variable(entries: list[tuple[str, str | None]]) -> None:
    wrong: list[str] = []
    for name, defined in entries:
        expected = TOOL if name.startswith(TOOL_PREFIX) else STANDARD.get(name)
        if defined is None or expected is None or plain(defined) != expected:
            wrong.append(f"{name}: {defined!r} (expected {expected!r})")

    assert wrong == []


def test_the_page_says_the_engine_s_names_match_in_any_case(repo_root: Path) -> None:
    from pairbench.sides.container import engine_reads

    assert engine_reads("http_proxy")
    assert engine_reads("docker_config")
    text = (repo_root / PAGE).read_text(encoding="utf-8")
    section = text.split(ENGINE_SECTION, 1)[1].split("\n### ", 1)[0]
    assert ANY_CASE in " ".join(section.split())


def test_the_anchor_of_a_heading_keeps_capitals_out_and_underscores_in() -> None:
    assert anchor("`PAIRBENCH_CONFIG`") == "pairbench_config"
    assert anchor("`DOCKER_*`") == "docker_"
    assert anchor("`container`") == "container"
