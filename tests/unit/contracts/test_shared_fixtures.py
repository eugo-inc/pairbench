# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What every test shares: the cleaned environment, the helpers for tests that need
an engine, a GPU or an external program, and the in-process command line."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench import registry
from pairbench.model import PluginCounts


@pytest.fixture
def shared(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The module of shared fixtures, with its list of unmet needs set aside."""
    root = Path(__file__).resolve().parents[2] / "conftest.py"
    found = [
        plugin
        for plugin in request.config.pluginmanager.get_plugins()
        if getattr(plugin, "__file__", None) == str(root)
    ]
    assert len(found) == 1
    module = found[0]
    monkeypatch.setattr(module, "_unmet", [])
    yield module


def test_no_pairbench_variable_reaches_a_test() -> None:
    assert [name for name in os.environ if name.startswith("PAIRBENCH_")] == []


def test_the_variables_are_removed_before_each_test(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAIRBENCH_OUT", "made-up")
    monkeypatch.setenv("PAIRBENCH__RUN__ROUNDS", "24")
    monkeypatch.setenv("OTHER_VARIABLE", "kept")
    shared._remove_pairbench_variables(monkeypatch)
    assert "PAIRBENCH_OUT" not in os.environ
    assert "PAIRBENCH__RUN__ROUNDS" not in os.environ
    assert os.environ["OTHER_VARIABLE"] == "kept"


def test_the_registry_starts_empty_for_every_test() -> None:
    assert registry.counts() == PluginCounts(loaded=0, failed=0)
    assert registry.failures() == ()
    assert registry.plugins_enabled() is True


def test_a_missing_engine_skips_with_a_message_that_names_it(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shared.shutil, "which", lambda name: None)
    monkeypatch.setattr(shared, "REQUIRE_ENGINE", "")
    with pytest.raises(pytest.skip.Exception) as skipped:
        shared._engine("tests/made_up.py::test_x", None)
    assert str(skipped.value) == "needs a container engine: docker or podman is not on PATH"
    with pytest.raises(pytest.skip.Exception) as named:
        shared._engine("tests/made_up.py::test_y", "podman")
    assert str(named.value) == "needs a container engine: podman is not on PATH"
    assert shared._unmet == [
        ("tests/made_up.py::test_x", "needs a container engine: docker or podman is not on PATH"),
        ("tests/made_up.py::test_y", "needs a container engine: podman is not on PATH"),
    ]


def test_an_engine_that_is_found_is_returned(shared: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shared.shutil, "which", lambda name: "/made/up/podman" if name == "podman" else None
    )
    monkeypatch.setattr(shared, "REQUIRE_ENGINE", "")
    assert shared._engine("tests/made_up.py::test_x", None) == "podman"
    assert shared._engine("tests/made_up.py::test_x", "podman") == "podman"
    assert shared._unmet == []


def test_a_required_engine_turns_the_skip_into_a_failure(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shared.shutil, "which", lambda name: None)
    monkeypatch.setattr(shared, "REQUIRE_ENGINE", "docker")
    with pytest.raises(pytest.fail.Exception) as failed:
        shared._engine("tests/made_up.py::test_x", None)
    assert "needs a container engine: docker is not on PATH" in str(failed.value)
    assert "PAIRBENCH_REQUIRE_ENGINE=docker turns this skip into a failure" in str(failed.value)
    with pytest.raises(pytest.fail.Exception):
        shared._engine("tests/made_up.py::test_x", "docker")
    with pytest.raises(pytest.skip.Exception):
        shared._engine("tests/made_up.py::test_x", "podman")


def test_gpu_tests_run_only_when_asked_for(shared: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shared, "GPU_TESTS", False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        shared._gpu("tests/made_up.py::test_x")
    assert str(skipped.value) == ("needs a GPU: set PAIRBENCH_TEST_GPU=1 on a machine that has one")
    monkeypatch.setattr(shared, "GPU_TESTS", True)
    assert shared._gpu("tests/made_up.py::test_x") is None


def test_a_missing_external_program_skips_with_a_message_that_names_it(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shared.shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception) as skipped:
        shared._tool("tests/made_up.py::test_x", "made-up-tool")
    assert str(skipped.value) == "needs the external program 'made-up-tool' on PATH"
    monkeypatch.setattr(shared.shutil, "which", lambda name: f"/made/up/{name}")
    assert shared._tool("tests/made_up.py::test_x", "made-up-tool") == "/made/up/made-up-tool"


def test_the_switches_are_read_from_the_environment_when_the_tests_start(
    repo_root: Path,
) -> None:
    script = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('shared_fixtures', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['shared_fixtures'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(module.REQUIRE_PLOT, module.GPU_TESTS, module.REQUIRE_ENGINE)\n"
    )
    shared_file = str(repo_root / "tests" / "conftest.py")

    def read(**switches: str) -> str:
        environ = {k: v for k, v in os.environ.items() if not k.startswith("PAIRBENCH_")}
        done = subprocess.run(
            [sys.executable, "-c", script, shared_file],
            env={**environ, **switches},
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    assert read() == "False False"
    assert read(PAIRBENCH_REQUIRE_PLOT="1") == "True False"
    assert read(PAIRBENCH_TEST_GPU="1") == "False True"
    assert read(PAIRBENCH_REQUIRE_ENGINE="podman") == "False False podman"


def test_a_missing_plot_extra_skips_with_a_message_that_names_it(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setattr(shared, "REQUIRE_PLOT", False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        shared._plot("tests/made_up.py::test_x")
    assert str(skipped.value) == "needs the plot extra: matplotlib is not installed"
    assert shared._unmet == [
        ("tests/made_up.py::test_x", "needs the plot extra: matplotlib is not installed")
    ]


def test_a_required_plot_extra_turns_the_skip_into_a_failure(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setattr(shared, "REQUIRE_PLOT", True)
    with pytest.raises(pytest.fail.Exception) as failed:
        shared._plot("tests/made_up.py::test_x")
    assert "needs the plot extra: matplotlib is not installed" in str(failed.value)
    assert "PAIRBENCH_REQUIRE_PLOT=1 turns this skip into a failure" in str(failed.value)
    assert shared._unmet == []


def test_a_plot_extra_that_is_installed_lets_the_test_run(
    shared: Any, needs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    made_up = types.ModuleType("matplotlib")
    made_up.__spec__ = types.SimpleNamespace(name="matplotlib")  # type: ignore[assignment]
    monkeypatch.setitem(sys.modules, "matplotlib", made_up)
    monkeypatch.setattr(shared, "REQUIRE_PLOT", True)
    assert shared._plot("tests/made_up.py::test_x") is None
    assert needs.plot() is None
    assert shared._unmet == []


def test_the_example_documents_of_a_run_with_the_control_and_of_the_diagnostics(
    example_capture_run_records: list[dict[str, Any]],
    example_diagnostics: dict[str, Any],
    shared: Any,
) -> None:
    example_capture_run_records.append({"made_up": 1})
    example_diagnostics["made_up"] = 1
    assert len(shared._EXAMPLE_CAPTURE_RUN_RECORDS) == 5
    assert "made_up" not in shared._EXAMPLE_DIAGNOSTICS


def test_the_banner_lists_every_test_that_did_not_run(shared: Any) -> None:
    class Reporter:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def section(self, title: str, sep: str = "=") -> None:
            self.lines.append(f"[{title}]")

        def write_line(self, line: str) -> None:
            self.lines.append(line)

    quiet = Reporter()
    shared.pytest_terminal_summary(quiet)
    assert quiet.lines == []
    shared._unmet.append(("tests/made_up.py::test_x", "needs a GPU: made-up reason"))
    loud = Reporter()
    shared.pytest_terminal_summary(loud)
    assert loud.lines == [
        "[skipped for a missing engine, GPU or external program]",
        "SKIPPED tests/made_up.py::test_x: needs a GPU: made-up reason",
        "1 test(s) did not run for that reason.",
    ]


class _Node:
    """A test as the needs fixture sees it: its id and the marks it carries."""

    def __init__(self, *marks: str) -> None:
        self.nodeid = "tests/made_up.py::test_x"
        self._marks = marks

    def get_closest_marker(self, name: str) -> object | None:
        return name if name in self._marks else None


UNMARKED_ENGINE = (
    "this test asks for a container engine without the needs_engine mark: mark it with "
    "pytest.mark.needs_engine, so a run that leaves out that mark leaves this test out too"
)


def test_the_needs_fixture_asks_the_same_helpers(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shared.shutil, "which", lambda name: f"/made/up/{name}")
    monkeypatch.setattr(shared, "REQUIRE_ENGINE", "")
    monkeypatch.setattr(shared, "GPU_TESTS", True)
    needs = shared.Needs(_Node("needs_engine"))
    assert needs.engine() == "docker"
    assert needs.engine("podman") == "podman"
    assert needs.tool("made-up-tool") == "/made/up/made-up-tool"
    assert needs.gpu() is None


def test_a_test_that_asks_for_an_engine_without_the_mark_fails_before_any_look_up(
    shared: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    looked: list[str] = []
    monkeypatch.setattr(
        shared.shutil, "which", lambda name: looked.append(name) or f"/made/up/{name}"
    )
    monkeypatch.setattr(shared, "REQUIRE_ENGINE", "")
    for name in (None, "docker", "podman"):
        with pytest.raises(pytest.fail.Exception) as failed:
            shared.Needs(_Node("needs_tool")).engine(name)
        assert str(failed.value) == UNMARKED_ENGINE
    assert looked == []
    assert shared._unmet == []


def test_the_needs_fixture_reads_the_marks_of_the_test_it_serves(
    request: pytest.FixtureRequest, needs: Any
) -> None:
    assert needs._node is request.node


def _calls_engine(node: ast.AST, helpers: set[str]) -> bool:
    for found in ast.walk(node):
        if not isinstance(found, ast.Call):
            continue
        called = found.func
        if (
            isinstance(called, ast.Attribute)
            and called.attr == "engine"
            and isinstance(called.value, ast.Name)
            and called.value.id == "needs"
        ):
            return True
        if isinstance(called, ast.Name) and called.id in helpers:
            return True
    return False


def _tests_that_ask_for_an_engine(tree: ast.Module) -> list[ast.FunctionDef]:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    helpers: set[str] = set()
    grew = True
    while grew:
        grew = False
        for function in functions:
            if function.name not in helpers and _calls_engine(function, helpers):
                helpers.add(function.name)
                grew = True
    return [f for f in functions if f.name.startswith("test_") and f.name in helpers]


def _module_marks(tree: ast.Module, source: str) -> str:
    return "".join(
        ast.get_source_segment(source, node) or ""
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
    )


def _marks_of(function: ast.FunctionDef, source: str, names: dict[str, str]) -> str:
    texts = []
    for decorator in function.decorator_list:
        text = ast.get_source_segment(source, decorator) or ""
        texts.append(text)
        texts.extend(names.get(word, "") for word in names if word in text)
    return "".join(texts)


def test_every_test_that_asks_for_an_engine_carries_the_needs_engine_mark() -> None:
    root = Path(__file__).resolve().parents[2]
    unmarked = []
    asking = 0
    for path in sorted(root.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        if "needs.engine(" not in source or path == Path(__file__).resolve():
            continue
        tree = ast.parse(source)
        names = {
            target.id: ast.get_source_segment(source, node) or ""
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        module = _module_marks(tree, source)
        for function in _tests_that_ask_for_an_engine(tree):
            asking += 1
            if "needs_engine" not in module + _marks_of(function, source, names):
                unmarked.append(f"{path.relative_to(root)}::{function.name}")
    assert asking >= 13
    assert unmarked == []


def _command_line(monkeypatch: pytest.MonkeyPatch, main: Callable[..., Any]) -> None:
    module = types.ModuleType("pairbench.cli.main")
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pairbench.cli.main", module)


def test_the_command_line_helper_returns_exit_code_and_both_streams(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def main(argv: list[str]) -> int:
        seen.append(argv)
        print("on standard output")
        print("on standard error", file=sys.stderr)
        return 6

    _command_line(monkeypatch, main)
    result = cli("compare", Path("a.jsonl"), "--rounds", 8)
    assert result.code == 6
    assert result.out == "on standard output\n"
    assert result.err == "on standard error\n"
    assert seen == [["compare", "a.jsonl", "--rounds", "8"]]


@pytest.mark.parametrize(("raised", "code"), [(2, 2), (None, 0), ("a message", 1)])
def test_the_command_line_helper_turns_an_exit_into_its_code(
    cli: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, raised: Any, code: int
) -> None:
    def main(argv: list[str]) -> int:
        raise SystemExit(raised)

    _command_line(monkeypatch, main)
    assert cli("made-up").code == code


def test_the_example_documents_are_fresh_copies(
    example_results: dict[str, Any], example_config: dict[str, Any], shared: Any
) -> None:
    example_results["made_up"] = 1
    example_config["made_up"] = 1
    assert "made_up" not in shared._EXAMPLE_RESULTS
    assert "made_up" not in shared._EXAMPLE_CONFIG


def test_the_root_of_the_repository_holds_the_package(repo_root: Path) -> None:
    assert (repo_root / "pyproject.toml").is_file()
    assert (repo_root / "src" / "pairbench" / "model.py").is_file()
