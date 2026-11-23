# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The tool server: its tools, their answers and refusals, and its contact with the SDK.

The SDK is faked here; ``test_stdio.py`` talks to the real one where the
``mcp`` extra is installed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

import pairbench
from pairbench.errors import Refusal
from pairbench.mcp import library, server
from pairbench.mcp.server import ToolServer
from pairbench.model import Results

from .conftest import MISSING_DEPENDENCY, NEWER_MODULE, OLDER_MODULE

EVERY_TOOL = (
    "doctor",
    "plan",
    "run_start",
    "run_status",
    "run_cancel",
    "results",
    "diagnostics",
    "compare",
    "explain",
    "fill",
    "selftest",
    "schema",
)
RUN_TOOLS = ("run_start", "run_cancel")
TOOLS_WITHOUT_RUNS = tuple(name for name in EVERY_TOOL if name not in RUN_TOOLS)
MADE_UP_PLUGIN = "made-up-plugin-a"
EXIT_USAGE = 2
EXIT_INTERNAL = 8
MADE_UP_RELEASE = "2.3.0"
DOCS_LINE_USAGE = (
    "pairbench: see https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_usage\n"
)
DOCS_LINE_INTERNAL = (
    "pairbench: see https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_internal\n"
)
NOT_INSTALLED = "the tool server is not available here (mcp): install pairbench[mcp]"
REINSTALL = "reinstall it with pip install 'pairbench[mcp]'"
# What the server says of an SDK module that fails to import a dependency outside ``mcp``.
DEPENDENCY_FAILED = (
    "the tool-server library mcp 2.3.0 is a broken install: it cannot import "
    f"made_up_dependency_a; {REINSTALL}"
)
WITHOUT_ALLOW_RUN = (
    "this server was started without --allow-run, so it does not offer {tool}: start it with "
    "pairbench mcp --allow-run"
)


def answer(tools: ToolServer, tool: str, /, **arguments: Any) -> dict[str, Any]:
    text = tools.call(tool, **arguments)
    document: dict[str, Any] = json.loads(text)
    return document


# -- the SDK ---------------------------------------------------------------------------


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module named ``mcp`` is the installed library, of a made-up supported release.

    The refusal for a library that cannot be loaded reads both, so its text
    does not depend on what is installed where the tests run.
    """
    monkeypatch.setattr(library, "found", lambda: library.LIBRARY)
    monkeypatch.setattr(library, "release", lambda: MADE_UP_RELEASE)


def test_main_lists_every_tool_but_the_run_tools_and_serves_on_stdio(fake_sdk: Any) -> None:
    code = server.main(allow_run=False)

    assert code == 0
    made = fake_sdk.server
    assert made.name == "pairbench"
    assert made.instructions == server.INSTRUCTIONS
    assert made.listed() == TOOLS_WITHOUT_RUNS
    assert tuple(made.tools) == (*TOOLS_WITHOUT_RUNS, *RUN_TOOLS)
    assert made.transports == ["stdio"]


def test_main_with_allow_run_lists_the_run_tools_too(fake_sdk: Any) -> None:
    server.main(allow_run=True)

    assert tuple(fake_sdk.server.tools) == EVERY_TOOL
    assert fake_sdk.server.listed() == EVERY_TOOL


def test_with_allow_run_the_server_is_the_sdk_class_itself(fake_sdk: Any) -> None:
    from mcp.server.mcpserver import MCPServer

    server.main(allow_run=True)

    assert type(fake_sdk.server) is MCPServer


@pytest.mark.parametrize("tool", RUN_TOOLS)
def test_a_run_tool_left_out_answers_a_call_with_how_to_start_the_server_with_it(
    tool: str, fake_sdk: Any
) -> None:
    server.main(allow_run=False)

    registered = fake_sdk.server.tools[tool]
    refused = json.loads(registered["fn"]())["refusal"]

    assert registered["description"] == server.STAND_IN_HELP
    assert registered["structured_output"] is False
    assert (refused["code"], refused["exit_code"], refused["message"]) == (
        "E_USAGE",
        EXIT_USAGE,
        WITHOUT_ALLOW_RUN.format(tool=tool),
    )


def test_every_tool_answers_text_and_asks_for_no_structured_output(fake_sdk: Any) -> None:
    server.main(allow_run=True)

    for name, tool in fake_sdk.server.tools.items():
        assert tool["structured_output"] is False, name
        assert tool["description"], name


def test_a_registered_tool_answers_through_the_sdk_function(fake_sdk: Any) -> None:
    server.main(allow_run=False)

    text = fake_sdk.server.tools["explain"]["fn"](term="twin")

    assert json.loads(text)["text"] == server.GLOSSARY["twin"]


def test_the_older_sdk_layout_is_used_when_the_newer_is_absent(older_fake_sdk: Any) -> None:
    code = server.main(allow_run=False)

    assert code == 0
    made = older_fake_sdk.server
    assert made.name == "pairbench"
    assert made.instructions == server.INSTRUCTIONS
    assert made.listed() == TOOLS_WITHOUT_RUNS
    assert tuple(made.tools) == (*TOOLS_WITHOUT_RUNS, *RUN_TOOLS)
    assert made.transports == ["stdio"]


@pytest.mark.parametrize("tool", RUN_TOOLS)
def test_the_older_layout_answers_a_run_tool_left_out_with_how_to_start_it(
    tool: str, older_fake_sdk: Any
) -> None:
    server.main(allow_run=False)

    refused = json.loads(older_fake_sdk.server.tools[tool]["fn"]())["refusal"]

    assert refused["message"] == WITHOUT_ALLOW_RUN.format(tool=tool)


@pytest.mark.parametrize("failing", [NEWER_MODULE, OLDER_MODULE])
@pytest.mark.usefixtures("installed")
def test_an_import_error_outside_mcp_while_the_sdk_loads_is_a_broken_install(
    failing: str, sdk_failing_on: Any
) -> None:
    sdk = sdk_failing_on(failing)

    with pytest.raises(Refusal) as raised:
        server.main(allow_run=False)

    assert (raised.value.code, raised.value.message) == ("E_USAGE", DEPENDENCY_FAILED)
    assert isinstance(raised.value.__cause__, ImportError)
    assert raised.value.__cause__.name == MISSING_DEPENDENCY
    assert sdk.servers == []


@pytest.mark.parametrize("failing", [NEWER_MODULE, OLDER_MODULE])
@pytest.mark.usefixtures("installed")
def test_the_command_reports_an_import_error_outside_mcp_as_a_broken_install(
    failing: str, sdk_failing_on: Any, cli: Any
) -> None:
    sdk_failing_on(failing)

    result = cli("mcp")

    assert (result.code, result.out, result.err) == (
        EXIT_USAGE,
        "",
        f"E_USAGE: {DEPENDENCY_FAILED}\n{DOCS_LINE_USAGE}",
    )


# A made-up failure of an SDK module that is not an import error; its text holds a path.
OTHER_FAILURE_TEXT = "a made-up failure in /home/user-a/made-up-env/mcp/server/__init__.py"
# What the server says of an SDK module that fails with such an error.
MODULE_FAILED = (
    "the tool-server library mcp 2.3.0 is a broken install: one of its modules cannot be "
    f"imported; {REINSTALL}"
)


@pytest.mark.parametrize("failing", [NEWER_MODULE, OLDER_MODULE])
@pytest.mark.parametrize("kind", [TypeError, AttributeError, RuntimeError])
@pytest.mark.usefixtures("installed")
def test_an_sdk_module_failing_with_another_error_is_a_broken_install(
    failing: str, kind: type[Exception], sdk_failing_on: Any
) -> None:
    sdk = sdk_failing_on(failing, error=kind(OTHER_FAILURE_TEXT))

    with pytest.raises(Refusal) as raised:
        server.main(allow_run=False)

    assert (raised.value.code, raised.value.exit_code, raised.value.message) == (
        "E_USAGE",
        EXIT_USAGE,
        MODULE_FAILED,
    )
    assert type(raised.value.__cause__) is kind
    assert sdk.servers == []


@pytest.mark.parametrize("failing", [NEWER_MODULE, OLDER_MODULE])
@pytest.mark.usefixtures("installed")
def test_the_command_reports_another_error_of_an_sdk_module_without_its_text(
    failing: str, sdk_failing_on: Any, cli: Any
) -> None:
    sdk_failing_on(failing, error=TypeError(OTHER_FAILURE_TEXT))

    result = cli("mcp")

    assert (result.code, result.out, result.err) == (
        EXIT_USAGE,
        "",
        f"E_USAGE: {MODULE_FAILED}\n{DOCS_LINE_USAGE}",
    )
    assert "/home" not in result.err


@pytest.mark.parametrize("missing", ["mcp_types", "mcpx", "starlette", MISSING_DEPENDENCY])
@pytest.mark.usefixtures("installed")
def test_a_newer_layout_failing_outside_mcp_is_reported_without_trying_the_older(
    missing: str, sdk_failing_on: Any
) -> None:
    sdk = sdk_failing_on(NEWER_MODULE, missing=missing)

    with pytest.raises(Refusal) as raised:
        server.sdk_server(server.SERVER_NAME, server.INSTRUCTIONS)

    assert raised.value.message == (
        f"the tool-server library mcp 2.3.0 is a broken install: it cannot import {missing}; "
        f"{REINSTALL}"
    )
    assert sdk.servers == []


@pytest.mark.parametrize("missing", ["mcp", "mcp.server.mcpserver", "mcp.made_up_module_a"])
def test_a_newer_layout_failing_inside_mcp_falls_back_to_the_older(
    missing: str, sdk_failing_on: Any
) -> None:
    sdk = sdk_failing_on(NEWER_MODULE, missing=missing)

    made = server.sdk_server(server.SERVER_NAME, server.INSTRUCTIONS)

    assert sdk.servers == [made]
    assert type(made).__name__ == "FastMCP"


def test_with_neither_layout_the_error_of_the_newer_is_the_one_reported(
    sdk_failing_on: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library, "found", lambda: library.LIBRARY)
    monkeypatch.setattr(library, "release", lambda: "1.2.0")
    sdk_failing_on(NEWER_MODULE, missing=NEWER_MODULE, other_layout=False)

    with pytest.raises(Refusal) as raised:
        server.sdk_server(server.SERVER_NAME, server.INSTRUCTIONS)

    assert raised.value.message == (
        "the tool-server library mcp 1.2.0 is a broken install: it cannot import "
        f"mcp.server.mcpserver, and pairbench supports mcp>=1.21.1,<3; {REINSTALL}"
    )
    assert isinstance(raised.value.__cause__, ImportError)
    assert raised.value.__cause__.name == NEWER_MODULE


@pytest.mark.usefixtures("installed")
def test_an_import_error_while_the_sdk_serves_is_a_broken_install(
    fake_sdk: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp.server.mcpserver import MCPServer

    def run(self: Any, transport: str = "stdio") -> None:
        raise ModuleNotFoundError("No module named 'starlette'", name="starlette")

    monkeypatch.setattr(MCPServer, "run", run)

    with pytest.raises(Refusal) as raised:
        server.main(allow_run=False)

    assert raised.value.message == (
        f"the tool-server library mcp 2.3.0 is a broken install: it cannot import starlette; "
        f"{REINSTALL}"
    )


def test_without_the_extra_main_refuses_with_the_install_hint(no_sdk: None) -> None:
    with pytest.raises(Refusal) as raised:
        server.main(allow_run=False)

    assert (raised.value.code, raised.value.message) == ("E_USAGE", NOT_INSTALLED)
    assert isinstance(raised.value.__cause__, ImportError)
    assert library.in_library(raised.value.__cause__.name)


def test_the_command_without_the_extra_refuses_with_the_install_hint(
    no_sdk: None, cli: Any
) -> None:
    result = cli("mcp")

    assert (result.code, result.out, result.err) == (
        EXIT_USAGE,
        "",
        f"E_USAGE: {NOT_INSTALLED}\n{DOCS_LINE_USAGE}",
    )


@pytest.mark.parametrize("name", ["mcp_types", "mcpx", MISSING_DEPENDENCY])
def test_the_command_raises_an_import_error_outside_mcp_that_reaches_it_as_it_is(
    name: str, cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def main(*, allow_run: bool) -> int:
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(server, "main", main)

    result = cli("mcp")

    assert (result.code, result.out, result.err) == (
        EXIT_INTERNAL,
        "",
        f"E_INTERNAL: ModuleNotFoundError: No module named {name!r}\n{DOCS_LINE_INTERNAL}",
    )


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("mcp", NOT_INSTALLED),
        (
            "mcp.server.made_up_module_a",
            "the tool-server library mcp 2.3.0 is a broken install: it cannot import "
            f"mcp.server.made_up_module_a; {REINSTALL}",
        ),
    ],
)
@pytest.mark.usefixtures("installed")
def test_the_command_reads_an_import_error_inside_mcp_that_reaches_it_as_the_server_does(
    name: str, message: str, cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def main(*, allow_run: bool) -> int:
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(server, "main", main)

    result = cli("mcp")

    assert (result.code, result.out, result.err) == (
        EXIT_USAGE,
        "",
        f"E_USAGE: {message}\n{DOCS_LINE_USAGE}",
    )


def test_the_command_starts_the_server_with_the_run_tools_only_when_allowed(
    fake_sdk: Any, cli: Any
) -> None:
    plain = cli("mcp")
    allowed = cli("mcp", "--allow-run")

    assert (plain.code, allowed.code) == (0, 0)
    first, second = fake_sdk.servers
    assert set(RUN_TOOLS).isdisjoint(first.listed())
    assert set(RUN_TOOLS) <= set(second.listed())


def test_the_sdk_is_imported_inside_one_function_only() -> None:
    import ast
    import inspect

    def by_name(node: ast.AST) -> list[str]:
        """The SDK module an ``importlib.import_module("...")`` call names, if ``node`` is one."""
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.partition(".")[0] == "mcp"
        ):
            return [node.args[0].value]
        return []

    tree = ast.parse(inspect.getsource(server))
    importing: list[str] = []
    reading_by_name: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            names = (
                [inner.module or ""]
                if isinstance(inner, ast.ImportFrom)
                else [alias.name for alias in inner.names]
                if isinstance(inner, ast.Import)
                else []
            )
            if any(name.partition(".")[0] == "mcp" for name in names):
                importing.append(node.name)
            if by_name(inner):
                reading_by_name.append(node.name)
    every_by_name = [name for node in ast.walk(tree) for name in by_name(node)]
    top_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            (alias.name if isinstance(node, ast.Import) else node.module or "").startswith("mcp")
            for alias in node.names
        )
    ]

    assert set(importing) == {"sdk_server"}
    assert reading_by_name == ["sdk_server"]
    assert every_by_name == ["mcp.server.fastmcp"]
    assert top_level == []


# -- calling ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", RUN_TOOLS)
def test_a_run_tool_without_allow_run_says_how_to_start_the_server_with_it(name: str) -> None:
    tools = ToolServer(allow_run=False)

    refused = answer(tools, name, handle="x")["refusal"]

    assert (refused["code"], refused["exit_code"], refused["message"]) == (
        "E_USAGE",
        EXIT_USAGE,
        WITHOUT_ALLOW_RUN.format(tool=name),
    )


def test_a_tool_that_does_not_exist_is_named_as_such() -> None:
    refused = answer(ToolServer(allow_run=False), "made_up_tool_a")["refusal"]

    assert (refused["code"], refused["message"]) == ("E_USAGE", "no tool named 'made_up_tool_a'")


def test_the_run_methods_refuse_without_allow_run_even_when_called_directly() -> None:
    tools = ToolServer(allow_run=False)

    with pytest.raises(Refusal) as start:
        tools.run_start(sides=["new=cmd:true", "old=cmd:false"])
    with pytest.raises(Refusal) as cancel:
        tools.run_cancel(handle="made-up-handle-a")

    assert (start.value.code, start.value.message) == (
        "E_USAGE",
        WITHOUT_ALLOW_RUN.format(tool="run_start"),
    )
    assert (cancel.value.code, cancel.value.message) == (
        "E_USAGE",
        WITHOUT_ALLOW_RUN.format(tool="run_cancel"),
    )


def test_a_refusal_is_an_answer_with_code_exit_code_scope_and_message() -> None:
    refused = answer(ToolServer(allow_run=False), "schema", name="made-up")

    assert set(refused) == {"refusal"}
    assert refused["refusal"]["code"] == "E_USAGE"
    assert refused["refusal"]["exit_code"] == 2
    assert refused["refusal"]["scope"] == "experiment"
    assert "made-up" in refused["refusal"]["message"]
    assert refused["refusal"]["docs"] == DOCS_E_USAGE


DOCS_E_USAGE = "https://eugo.io/docs/pairbench/0.2/reference/exit-codes/#e_usage"


def test_an_unexpected_error_is_answered_as_an_internal_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = ToolServer(allow_run=False)

    def broken() -> dict[str, Any]:
        raise RuntimeError("a made-up failure")

    monkeypatch.setattr(tools, "selftest", broken)
    refused = answer(tools, "selftest")["refusal"]

    assert refused["code"] == "E_INTERNAL"
    assert refused["exit_code"] == 8


def test_what_a_tool_prints_goes_to_standard_error_never_to_the_protocol_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = ToolServer(allow_run=False)

    def noisy() -> dict[str, Any]:
        print("a made-up line")
        return {"ok": True}

    monkeypatch.setattr(tools, "selftest", noisy)
    got = answer(tools, "selftest")
    printed = capsys.readouterr()

    assert got == {"ok": True}
    assert printed.out == ""
    assert "a made-up line" in printed.err


# -- doctor ----------------------------------------------------------------------------


def test_doctor_names_no_plug_in() -> None:
    document = {
        "tool": {"name": "pairbench", "version": "0.1.0"},
        "tools": [{"name": "docker", "found": False, "version": None, "note": None}],
        "side_kinds": {MADE_UP_PLUGIN: {"status": "ok", "summary": "loaded", "detail": {}}},
        "drivers": {
            MADE_UP_PLUGIN: {"status": "experimental", "summary": "loaded", "detail": {}},
            "made-up-plugin-b": {"status": "ok", "summary": "loaded", "detail": {}},
        },
        "gates": {},
        "capture_readers": {},
        "reporters": {},
        "launchers": {MADE_UP_PLUGIN: {"status": "degraded", "summary": "x", "detail": {}}},
        "instruments": {"counters": {"status": "unavailable", "summary": "x", "detail": {}}},
        "plot_extra": {"installed": False},
        "plugins": {"enabled": True, "loaded": 3, "failed": [f"{MADE_UP_PLUGIN}: failed"]},
        "degraded": [f"launchers {MADE_UP_PLUGIN}: x", "instruments counters: x"],
        "experimental": [MADE_UP_PLUGIN],
        "leftover_containers": [],
    }

    shown = server._without_plugin_names(document)

    assert MADE_UP_PLUGIN not in json.dumps(shown)
    assert "made-up-plugin-b" not in json.dumps(shown)
    assert shown["drivers"] == {"count": 2, "by_status": {"experimental": 1, "ok": 1}}
    assert shown["launchers"] == {"count": 1, "by_status": {"degraded": 1}}
    assert shown["plugins"] == {"enabled": True, "loaded": 3, "failed": 1}
    assert shown["degraded_instruments"] == ["instruments counters: x"]
    assert shown["degraded_plugins"] == 1
    assert shown["experimental_drivers"] == 1
    assert shown["instruments"] == document["instruments"]
    assert shown["tools"] == document["tools"]


def test_doctor_on_this_machine_counts_every_group_instead_of_naming_it() -> None:
    from pairbench.cli.doctor import GROUPS
    from pairbench.model import BUILTIN_DRIVERS

    got = answer(ToolServer(allow_run=False), "doctor")

    for _group, word in GROUPS:
        assert set(got[word]) == {"count", "by_status"}, word
    assert "degraded" not in got
    assert "experimental" not in got
    assert got["drivers"]["count"] >= len(BUILTIN_DRIVERS)


# -- plan ------------------------------------------------------------------------------


def test_plan_answers_the_text_of_the_plan_command_and_its_numbers() -> None:
    got = answer(
        ToolServer(allow_run=False),
        "plan",
        sides=["new=cmd:true", "old=cmd:false"],
        sets=["run.rounds=8", "explain.mode=off", "controls.positive=off"],
    )

    assert "refusal" not in got, got
    assert got["rounds_planned"] == 8
    assert got["balanced"] is True
    assert got["lineup"] == ["new", "new~same", "old", "old~same"]
    assert got["control"] is None
    assert "new~same" in got["text"]


def test_plan_escapes_names_in_its_text_and_keeps_them_in_its_numbers() -> None:
    odd = "a\x1b[31mb"
    got = answer(
        ToolServer(allow_run=False),
        "plan",
        sides=[f"{odd}=cmd:true", "c\u202ed=cmd:false"],
        sets=["run.rounds=8", "explain.mode=off", "controls.positive=off"],
    )

    assert got["lineup"] == [odd, f"{odd}~same", "c\u202ed", "c\u202ed~same"]
    assert got["text"].startswith(
        "# lineup: a\\x1b[31mb, a\\x1b[31mb~same, c\\u202ed, c\\u202ed~same\n"
    )
    assert "\x1b" not in got["text"]
    assert "\u202e" not in got["text"]


def test_plan_refuses_sides_that_are_result_files() -> None:
    refused = answer(
        ToolServer(allow_run=False),
        "plan",
        sides=["new=file:a/*.json", "old=file:b/*.json"],
    )["refusal"]

    assert refused["code"] == "E_USAGE"
    assert "compare" in refused["message"]


def test_plan_refuses_a_bad_config_key_with_the_config_code() -> None:
    refused = answer(
        ToolServer(allow_run=False),
        "plan",
        sides=["new=cmd:true", "old=cmd:false"],
        sets=["made_up_key=1"],
    )["refusal"]

    assert refused["code"] == "E_CONFIG"
    assert refused["exit_code"] == 2


# -- results, diagnostics and explain --------------------------------------------------


def test_results_answers_the_document_from_a_file_or_its_folder(results_folder: Path) -> None:
    tools = ToolServer(allow_run=False)

    from_folder = answer(tools, "results", path=str(results_folder))
    from_file = answer(tools, "results", path=str(results_folder / "results.json"))

    assert from_folder == from_file
    assert from_folder["schema"] == "pairbench/results/v1"
    assert from_folder["comparisons"][0]["outcome"] == "better"


def test_results_of_one_case_answers_its_comparisons(results_folder: Path) -> None:
    got = answer(ToolServer(allow_run=False), "results", path=str(results_folder), case="matmul")

    assert [c["subject"] for c in got["comparisons"]] == ["new"]
    assert got["rule"]["name"] == "strict"


def test_results_of_one_case_for_one_side_answers_that_side_only(
    mixed_results_folder: Path,
) -> None:
    tools = ToolServer(allow_run=False)
    path = str(mixed_results_folder)

    both = answer(tools, "results", path=path, case="matmul")
    one = answer(tools, "results", path=path, case="matmul", subject="newer")

    assert [c["subject"] for c in both["comparisons"]] == ["new", "newer"]
    assert [c["subject"] for c in one["comparisons"]] == ["newer"]


def test_results_of_an_unknown_case_refuses_and_lists_the_cases(results_folder: Path) -> None:
    refused = answer(
        ToolServer(allow_run=False), "results", path=str(results_folder), case="made-up"
    )["refusal"]

    assert refused["code"] == "E_USAGE"
    assert "matmul" in refused["message"]


def test_results_of_a_missing_file_is_a_refusal_not_an_error(tmp_path: Path) -> None:
    got = answer(ToolServer(allow_run=False), "results", path=str(tmp_path / "absent.json"))

    assert got["refusal"]["code"] == "E_USAGE"
    assert got["refusal"]["exit_code"] == 2


def test_diagnostics_carries_the_notice_that_it_holds_names_from_the_users_code(
    diagnostics_folder: Path,
) -> None:
    tools = ToolServer(allow_run=False)

    whole = answer(tools, "diagnostics", path=str(diagnostics_folder))
    findings = answer(tools, "diagnostics", path=str(diagnostics_folder), findings_only=True)

    assert whole["notice"] == server.NAMES_NOTICE
    assert whole["diagnostics"]["schema"] == "pairbench/diagnostics/v1"
    assert findings["notice"] == server.NAMES_NOTICE
    assert findings["findings"] == whole["diagnostics"]["findings"]


def test_explain_a_term_outcome_or_reason() -> None:
    tools = ToolServer(allow_run=False)

    assert answer(tools, "explain", term="noise floor")["text"] == server.GLOSSARY["noise floor"]
    assert "inside the noise bar" in answer(tools, "explain", term="inside_noise")["text"]
    assert answer(tools, "explain", term="TIE")["text"].startswith("The outcome TIE")
    assert "better" in answer(tools, "explain", term="faster")["text"]


def test_explain_an_unknown_term_refuses_and_lists_the_terms() -> None:
    refused = answer(ToolServer(allow_run=False), "explain", term="made-up")["refusal"]

    assert refused["code"] == "E_USAGE"
    assert "twin" in refused["message"]


def test_explain_needs_a_term_or_a_results_file_but_not_both(results_folder: Path) -> None:
    tools = ToolServer(allow_run=False)

    neither = answer(tools, "explain")["refusal"]
    both = answer(tools, "explain", term="twin", results=str(results_folder))["refusal"]

    assert neither["code"] == both["code"] == "E_USAGE"


def test_explain_a_comparison_in_plain_words_from_the_recorded_fields(
    results_folder: Path,
) -> None:
    got = answer(ToolServer(allow_run=False), "explain", results=str(results_folder), case="matmul")

    (only,) = got["comparisons"]
    text = only["text"]
    assert only["subject"] == "new"
    assert "In 16 paired rounds, new was lower in 15 and higher in 1." in text
    assert "0.80x" in text
    assert "34/65536" in text
    assert "corrected for testing 2 cases at once" in text
    assert "Verdict: FASTER (outcome better)" in text
    assert "measured from each side's twin" in text


def test_explain_under_a_rule_that_grades_raw_p_values_says_why_the_corrected_p_differs(
    tmp_path: Path, example_results: dict[str, Any]
) -> None:
    example_results["rule"] = {
        "name": "made-up-raw",
        "fields": {"name": "made-up-raw", "p_source": "raw"},
        "family_size": 2,
        "plain": "corrected for testing 2 cases at once",
    }
    folder = tmp_path / "run-raw"
    folder.mkdir()
    (folder / "results.json").write_text(json.dumps(example_results), encoding="utf-8")

    got = answer(ToolServer(allow_run=False), "explain", results=str(folder), case="matmul")

    text = got["comparisons"][0]["text"]
    assert "corrected for testing" not in text
    assert (
        "The exact sign test gives p = 0.0005 (34/65536); rule made-up-raw grades each case on "
        "this p-value, uncorrected: it does not correct for testing 2 cases at once, which "
        "would give 0.001 (p_corrected), never smaller."
    ) in text


def test_explain_says_a_secondary_case_is_secondary_and_a_primary_one_is_not(
    mixed_results_folder: Path,
) -> None:
    tools = ToolServer(allow_run=False)
    path = str(mixed_results_folder)

    (secondary,) = answer(tools, "explain", results=path, case="memcpy")["comparisons"]
    primary = answer(tools, "explain", results=path, case="matmul")["comparisons"]
    newer = answer(tools, "explain", results=path, case="matmul", subject="newer")["comparisons"]

    assert "The case is secondary" in secondary["text"]
    assert [c["subject"] for c in primary] == ["new", "newer"]
    assert all("The case is secondary" not in c["text"] for c in primary)
    assert [c["subject"] for c in newer] == ["newer"]


def test_explain_says_when_the_repeat_without_disturbed_rounds_was_not_computed(
    results: Results,
) -> None:
    (first,) = results.comparisons
    skipped = dataclasses.replace(
        first,
        sensitivity=dataclasses.replace(
            first.sensitivity,
            rounds_set_aside=tuple(range(1, 17)),
            ratio=None,
            outcome=None,
            agrees=None,
            not_computed="too_many_disturbed",
        ),
    )

    text = server.explain_comparison(results, skipped)

    assert (
        "The comparison without the 16 disturbed rounds was not computed: more than half "
        "of the rounds are disturbed." in text
    )
    assert "None" not in text
    assert "does not agree" not in text


def test_explain_says_why_a_comparison_has_no_verdict(results: Results) -> None:
    (first,) = results.comparisons
    no_verdict = dataclasses.replace(
        first,
        verdict="NO VERDICT",
        outcome="no_verdict",
        reason="no_floor",
        reasons=("no_floor",),
        p_raw=None,
        p_raw_fraction=None,
        p_corrected=None,
        bar=None,
    )

    text = server.explain_comparison(results, no_verdict)

    assert "outcome no_verdict, reason no_floor" in text
    assert server.REASON_TEXT["no_floor"] in text
    assert "sign test" not in text


def test_explain_names_the_medians_that_are_too_far_apart(results: Results) -> None:
    (first,) = results.comparisons
    far = dataclasses.replace(
        first,
        verdict="NO VERDICT",
        outcome="no_verdict",
        reason="too_far_apart",
        reasons=("too_far_apart",),
        subject_median=1e300,
        baseline_median=1e-10,
        ratio=None,
        statistic=None,
        gap=None,
        bar=None,
    )

    text = server.explain_comparison(results, far)

    assert "outcome no_verdict, reason too_far_apart" in text
    assert (
        "too_far_apart: the medians 1e+300 and 1e-10 are too far apart for their ratio to be a "
        "finite number."
    ) in text


def test_explain_shows_a_short_exact_fraction_and_points_to_a_long_one(results: Results) -> None:
    (first,) = results.comparisons
    short = dataclasses.replace(first, p_raw=34 / 65536, p_raw_fraction=(34, 65536))
    assert "(34/65536)" in server.explain_comparison(results, short)
    # 1200 rounds that all went one way: a denominator of 361 digits.
    long = dataclasses.replace(first, p_raw=1e-300, p_raw_fraction=(2, 2**1200))
    text = server.explain_comparison(results, long)
    assert str(2**1200) not in text
    assert max(len(word) for word in text.split()) < 40
    assert "the exact fraction is p_raw_fraction in the results" in text


# -- compare ---------------------------------------------------------------------------


def test_compare_refuses_inputs_that_do_not_fit(capture_file: Path) -> None:
    tools = ToolServer(allow_run=False)
    cases = (
        {},
        {"captures": [str(capture_file)], "sides": ["new=file:a.json", "old=file:b.json"]},
        {"captures": [str(capture_file)], "driver": "wall"},
        {"sides": ["new=file:a.json", "old=file:b.json"]},
        {"sides": ["new=file:a.json", "old=file:b.json"], "reader": "jsonl", "driver": "wall"},
    )

    for arguments in cases:
        assert answer(tools, "compare", **arguments)["refusal"]["code"] == "E_USAGE", arguments


def test_compare_with_out_on_a_file_is_refused_as_usage(
    monkeypatch: pytest.MonkeyPatch, capture_file: Path, results: Results, tmp_path: Path
) -> None:
    monkeypatch.setattr(pairbench, "analyse", lambda captures, **options: results)
    (tmp_path / "taken").write_text("kept\n")

    got = answer(
        ToolServer(allow_run=False),
        "compare",
        captures=[str(capture_file)],
        out=str(tmp_path / "taken"),
    )["refusal"]

    assert (got["code"], got["exit_code"]) == ("E_USAGE", 2)
    assert got["message"] == "the results folder taken is a file, not a folder"


def test_compare_analyses_the_captures_with_the_strict_rule_and_writes_only_with_out(
    monkeypatch: pytest.MonkeyPatch, capture_file: Path, results: Results, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def analyse(captures: Any, **options: Any) -> Results:
        calls.append({"captures": list(captures), **options})
        return results

    monkeypatch.setattr(pairbench, "analyse", analyse)
    tools = ToolServer(allow_run=False)

    shown = answer(tools, "compare", captures=[str(capture_file)])
    written = answer(tools, "compare", captures=[str(capture_file)], out=str(tmp_path / "out"))

    assert calls[0]["rule"] == "strict"
    assert calls[0]["baseline"] is None
    assert calls[0]["allow_incomplete"] is False
    assert len(calls[0]["captures"]) == 1
    assert "folder" not in shown
    assert shown["results"]["comparisons"][0]["outcome"] == "better"
    assert written["folder"] == str(tmp_path / "out")
    assert (tmp_path / "out" / "results.json").is_file()


def test_compare_hands_a_refused_analysis_back_with_its_results(
    monkeypatch: pytest.MonkeyPatch, capture_file: Path, results: Results
) -> None:
    def analyse(captures: Any, **options: Any) -> Results:
        raise Refusal("E_TOO_FEW_ROUNDS", "a made-up refusal", results=results)

    monkeypatch.setattr(pairbench, "analyse", analyse)

    got = answer(ToolServer(allow_run=False), "compare", captures=[str(capture_file)])

    assert got["refusal"]["code"] == "E_TOO_FEW_ROUNDS"
    assert got["refusal"]["exit_code"] == 6
    assert got["results"]["schema"] == "pairbench/results/v1"


def test_compare_of_unreadable_result_files_writes_the_results_it_refuses(
    tmp_path: Path,
) -> None:
    for name in ("new1.json", "old1.json"):
        (tmp_path / name).write_text("not json\n", encoding="utf-8")
    out = tmp_path / "out"

    got = answer(
        ToolServer(allow_run=False),
        "compare",
        sides=[f"new=file:{tmp_path}/new*.json", f"old=file:{tmp_path}/old*.json"],
        driver="gbench",
        out=str(out),
    )

    assert got["refusal"]["code"] == "E_LAUNCH_FAILED"
    written = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert got["results"] == written
    assert (out / "results.md").is_file()


def test_compare_reads_serving_result_files_at_the_level_levels_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    folder = Path(__file__).parents[2] / "fixtures" / "serving" / "guidellm"
    sides = [f"new=file:{folder}/guidellm-c1.json", f"old=file:{folder}/guidellm-c2.json"]
    tools = ToolServer(allow_run=False)

    without = answer(tools, "compare", sides=sides, driver="guidellm")
    read = answer(tools, "compare", sides=sides, driver="guidellm", levels="1")
    stray = answer(tools, "compare", captures=["a.jsonl"], levels="1")

    assert without["refusal"]["code"] == "E_USAGE"
    assert "workload.levels" in without["refusal"]["message"]
    assert "c1/ttft_ms_median" in {c["case"] for c in read["results"]["comparisons"]}
    assert stray["refusal"]["message"] == (
        "levels names the load level of result files given as sides"
    )


def test_compare_refuses_sides_that_launch() -> None:
    refused = answer(
        ToolServer(allow_run=False),
        "compare",
        sides=["new=cmd:true", "old=file:b.json"],
        driver="wall",
    )["refusal"]

    assert refused["code"] == "E_USAGE"


# -- fill, selftest and schema ---------------------------------------------------------


def test_fill_returns_writes_or_checks_the_filled_text(
    results_folder: Path, tmp_path: Path
) -> None:
    template = tmp_path / "page.in.md"
    template.write_text("ratio {{fig:matmul.new_vs_old.ratio}}\n", encoding="utf-8")
    output = tmp_path / "page.md"
    results_file = str(results_folder / "results.json")
    tools = ToolServer(allow_run=False)

    returned = answer(tools, "fill", template=str(template), results=[results_file])
    unchecked = answer(
        tools,
        "fill",
        template=str(template),
        results=[results_file],
        output=str(output),
        check=True,
    )
    written = answer(
        tools, "fill", template=str(template), results=[results_file], output=str(output)
    )
    checked = answer(
        tools,
        "fill",
        template=str(template),
        results=[results_file],
        output=str(output),
        check=True,
    )

    assert returned == {"text": "ratio 0.80x\n"}
    assert unchecked == {"output": "page.md", "exists": False, "matches": False}
    assert written == {"written": "page.md"}
    assert output.read_text(encoding="utf-8") == "ratio 0.80x\n"
    assert checked == {"output": "page.md", "exists": True, "matches": True}


def test_fill_with_named_results_and_a_missing_figure(results_folder: Path, tmp_path: Path) -> None:
    template = tmp_path / "page.in.md"
    template.write_text("{{fig:a/matmul.new_vs_old.ratio}} {{fig:made.up}}\n", encoding="utf-8")
    tools = ToolServer(allow_run=False)

    refused = answer(
        tools,
        "fill",
        template=str(template),
        results=[f"a={results_folder / 'results.json'}"],
    )["refusal"]

    assert refused["code"] == "E_FIGURE_MISSING"
    assert refused["exit_code"] == 7


def test_fill_check_needs_an_output(tmp_path: Path) -> None:
    template = tmp_path / "page.in.md"
    template.write_text("plain\n", encoding="utf-8")

    refused = answer(ToolServer(allow_run=False), "fill", template=str(template), check=True)

    assert refused["refusal"]["code"] == "E_USAGE"


def test_fill_check_against_an_output_that_cannot_be_read_is_a_usage_refusal(
    tmp_path: Path,
) -> None:
    template = tmp_path / "page.in.md"
    template.write_text("plain\n", encoding="utf-8")
    folder = tmp_path / "page.md"
    folder.mkdir()

    refused = answer(
        ToolServer(allow_run=False),
        "fill",
        template=str(template),
        output=str(folder),
        check=True,
    )["refusal"]

    assert refused["code"] == "E_USAGE"
    assert refused["exit_code"] == 2
    assert "page.md" in refused["message"]


def test_selftest_answers_every_control() -> None:
    from pairbench.api import RunSelftest, delegate

    run_selftest: RunSelftest = delegate("selftest")
    expected = [result.id for result in run_selftest()]

    got = answer(ToolServer(allow_run=False), "selftest")

    assert got["passed"] is True
    assert [c["id"] for c in got["controls"]] == expected


@pytest.mark.parametrize("name", ["capture", "results", "config", "diagnostics"])
def test_schema_answers_each_schema(name: str) -> None:
    from pairbench.results import schema_text

    got = answer(ToolServer(allow_run=False), "schema", name=name)

    assert got == json.loads(schema_text(name))


# -- the instructions ------------------------------------------------------------------


def test_the_instructions_and_descriptions_name_no_plug_in_beyond_the_builtins() -> None:
    specs = server.tool_specs(ToolServer(allow_run=True))

    assert tuple(spec.name for spec in specs) == EVERY_TOOL
    assert "--allow-run" in server.INSTRUCTIONS
    assert "UNRESOLVED" in server.INSTRUCTIONS
    assert MADE_UP_PLUGIN not in " ".join(spec.description for spec in specs)


# What the descriptions of the tools that take a case say of a name given without its mark.
UNMARKED_NAME = {
    "results": "a name given without its mark gives those of every case it shows with a mark",
    "explain": "a name given without its mark explains those of every case it shows with a mark",
}


@pytest.mark.parametrize(("name", "words"), sorted(UNMARKED_NAME.items()))
def test_a_tool_that_takes_a_case_says_what_a_name_without_its_mark_gives(
    name: str, words: str
) -> None:
    specs = {spec.name: spec for spec in server.tool_specs(ToolServer(allow_run=False))}

    assert words in specs[name].description


def test_every_outcome_and_reason_has_plain_words() -> None:
    from pairbench.model import (
        OUTCOMES,
        REASONS_NO_VERDICT,
        REASONS_RESERVED,
        REASONS_UNRESOLVED,
    )

    assert set(server.OUTCOME_TEXT) == set(OUTCOMES)
    assert set(server.REASON_TEXT) == {*REASONS_NO_VERDICT, *REASONS_UNRESOLVED, *REASONS_RESERVED}
