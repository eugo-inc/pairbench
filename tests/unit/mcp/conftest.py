# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What the tool-server tests share: a fake of the MCP SDK and example run folders."""

from __future__ import annotations

import copy
import json
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pairbench.model import Results


class FakeServer:
    """Stands in for the SDK's server class: it records the tools and the transport."""

    def __init__(self, name: str, instructions: str | None = None) -> None:
        self.name = name
        self.instructions = instructions
        self.tools: dict[str, dict[str, Any]] = {}
        self.transports: list[str] = []

    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: Any = None,
        icons: Any = None,
        meta: Any = None,
        structured_output: bool | None = None,
    ) -> None:
        self.tools[str(name)] = {
            "fn": fn,
            "description": description,
            "structured_output": structured_output,
        }

    def run(self, transport: str = "stdio") -> None:
        self.transports.append(transport)


class OlderFakeServer(FakeServer):
    """The older SDK's server class, whose ``add_tool`` takes no ``structured_output``."""

    def add_tool(  # type: ignore[override]
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        self.tools[str(name)] = {"fn": fn, "description": description}


class Sdk:
    """The fake SDK: every server object the code under test made."""

    def __init__(self) -> None:
        self.servers: list[FakeServer] = []

    @property
    def server(self) -> FakeServer:
        assert len(self.servers) == 1
        return self.servers[0]


def _module(name: str, **attributes: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> Sdk:
    """Install a fake of the newer SDK layout, ``mcp.server.mcpserver.MCPServer``."""
    sdk = Sdk()

    def make(name: str, instructions: str | None = None) -> FakeServer:
        made = FakeServer(name, instructions=instructions)
        sdk.servers.append(made)
        return made

    leaf = _module("mcp.server.mcpserver", MCPServer=make)
    middle = _module("mcp.server", mcpserver=leaf)
    monkeypatch.setitem(sys.modules, "mcp", _module("mcp", server=middle))
    monkeypatch.setitem(sys.modules, "mcp.server", middle)
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", leaf)
    return sdk


@pytest.fixture
def older_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> Sdk:
    """Install a fake of the older SDK layout, ``mcp.server.fastmcp.FastMCP``, and nothing newer."""
    sdk = Sdk()

    def make(name: str, instructions: str | None = None) -> FakeServer:
        made = OlderFakeServer(name, instructions=instructions)
        sdk.servers.append(made)
        return made

    leaf = _module("mcp.server.fastmcp", FastMCP=make)
    middle = _module("mcp.server", fastmcp=leaf)
    monkeypatch.setitem(sys.modules, "mcp", _module("mcp", server=middle))
    monkeypatch.setitem(sys.modules, "mcp.server", middle)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", leaf)
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    return sdk


# The SDK modules of the two layouts, and a made-up module outside ``mcp`` that one of
# them fails to import.
NEWER_MODULE = "mcp.server.mcpserver"
OLDER_MODULE = "mcp.server.fastmcp"
MISSING_DEPENDENCY = "made_up_dependency_a"


class FailingFinder:
    """A module finder whose search for one module fails on a dependency outside ``mcp``."""

    def __init__(self, module: str) -> None:
        self.module = module

    def find_spec(self, name: str, path: object = None, target: object = None) -> None:
        if name == self.module:
            raise ImportError(
                f"cannot import name 'made_up_name' from '{MISSING_DEPENDENCY}'",
                name=MISSING_DEPENDENCY,
            )
        return None


@pytest.fixture
def sdk_failing_on(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Sdk]:
    """Return a function that installs a fake SDK whose import of one module fails on a dependency.

    The module named fails with the import error of ``MISSING_DEPENDENCY``.
    When it is the newer layout's module, the older layout is there; when it
    is the older layout's module, the newer layout is absent. Every ``mcp``
    module already imported is taken out of ``sys.modules`` first, so the
    import of the failing module reaches the finder.
    """

    def install(module: str) -> Sdk:
        sdk = Sdk()

        def make(name: str, instructions: str | None = None) -> FakeServer:
            made = OlderFakeServer(name, instructions=instructions)
            sdk.servers.append(made)
            return made

        for name in [key for key in sys.modules if key == "mcp" or key.startswith("mcp.")]:
            monkeypatch.delitem(sys.modules, name)
        middle = _module("mcp.server", __path__=[])
        monkeypatch.setitem(sys.modules, "mcp", _module("mcp", server=middle, __path__=[]))
        monkeypatch.setitem(sys.modules, "mcp.server", middle)
        if module == NEWER_MODULE:
            monkeypatch.setitem(sys.modules, OLDER_MODULE, _module(OLDER_MODULE, FastMCP=make))
        else:
            monkeypatch.setitem(sys.modules, NEWER_MODULE, None)
        monkeypatch.setattr(sys, "meta_path", [FailingFinder(module), *sys.meta_path])
        return sdk

    return install


@pytest.fixture
def no_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import mcp`` fail as it does where the extra is not installed.

    Every ``mcp`` module already imported is hidden too: an import of a
    submodule found in ``sys.modules`` would not look at its parent.
    """
    for name in [key for key in sys.modules if key == "mcp" or key.startswith("mcp.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "mcp", None)


@pytest.fixture
def results(example_results: dict[str, Any]) -> Results:
    """The example results document, with made-up values, as the analysis returns it."""
    return Results.from_json(example_results)


@pytest.fixture
def results_folder(tmp_path: Path, example_results: dict[str, Any]) -> Path:
    """A run folder holding the example results document, with made-up values."""
    folder = tmp_path / "run-a"
    folder.mkdir()
    (folder / "results.json").write_text(json.dumps(example_results), encoding="utf-8")
    return folder


@pytest.fixture
def mixed_results(example_results: dict[str, Any]) -> dict[str, Any]:
    """The example results with a second subject and a secondary case, with made-up values.

    The comparisons are ``matmul`` for ``new`` and for ``newer``, both primary,
    and ``memcpy`` for ``new``, secondary.
    """
    first = example_results["comparisons"][0]
    example_results["comparisons"] += [
        {**copy.deepcopy(first), "subject": "newer"},
        {**copy.deepcopy(first), "case": "memcpy", "primary": False},
    ]
    return example_results


@pytest.fixture
def mixed_results_folder(tmp_path: Path, mixed_results: dict[str, Any]) -> Path:
    """A run folder holding ``mixed_results``."""
    folder = tmp_path / "run-mixed"
    folder.mkdir()
    (folder / "results.json").write_text(json.dumps(mixed_results), encoding="utf-8")
    return folder


@pytest.fixture
def diagnostics_folder(tmp_path: Path, example_diagnostics: dict[str, Any]) -> Path:
    """A run folder holding the example diagnostics document, with made-up values."""
    folder = tmp_path / "run-d"
    folder.mkdir()
    (folder / "diagnostics.json").write_text(json.dumps(example_diagnostics), encoding="utf-8")
    return folder


@pytest.fixture
def capture_file(tmp_path: Path, example_capture_records: list[dict[str, Any]]) -> Path:
    """The example capture, with made-up values, as a file."""
    path = tmp_path / "capture.jsonl"
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in example_capture_records), encoding="utf-8"
    )
    return path
