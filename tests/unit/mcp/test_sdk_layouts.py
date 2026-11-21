# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The ``mcp`` extra's bounds, and the SDK import's type check against each SDK layout.

The ``mcp`` package keeps its server class in one of two places:
``mcp.server.fastmcp.FastMCP`` in the 1.x releases, and
``mcp.server.mcpserver.MCPServer`` in the 2.x releases. Most 2.x releases also
ship ``mcp.server.fastmcp`` as a typed module with no API, whose import raises.
Each layout is written here as a small typed stand-in on the type checker's
search path, and the check skips installed packages, so it reads the stand-in
and never an installed ``mcp``. Skipped where mypy is not installed.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

WAIT_S = 300.0
SERVER_FILE = "src/pairbench/mcp/server.py"
MYPY_SUCCESS = "Success: no issues found in 1 source file\n"
MCP_EXTRA = ["mcp>=1.21.1,<3"]

OLDER_CLASS = """\
from collections.abc import Callable
from typing import Any, Literal

class FastMCP:
    def __init__(
        self, name: str | None = None, instructions: str | None = None, **settings: Any
    ) -> None: ...
    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None: ...
    def run(self, transport: Literal["stdio", "sse"] = "stdio") -> None: ...
"""

NEWER_CLASS = """\
from collections.abc import Callable
from typing import Any, Literal

class MCPServer:
    def __init__(
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
    ) -> None: ...
    def add_tool(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        structured_output: bool | None = None,
    ) -> None: ...
    def run(self, transport: Literal["stdio", "sse", "streamable-http"] = "stdio") -> None: ...
"""

MODULE_WITH_NO_API = '"""A module with no API: importing it raises ModuleNotFoundError."""\n'

PACKAGE = {"mcp/__init__.pyi": "", "mcp/server/__init__.pyi": ""}

LAYOUTS = {
    # mcp 1.x
    "fastmcp-package": {**PACKAGE, "mcp/server/fastmcp/__init__.pyi": OLDER_CLASS},
    # mcp 2.0.0 and 2.1.0
    "mcpserver-package": {**PACKAGE, "mcp/server/mcpserver/__init__.pyi": NEWER_CLASS},
    # mcp 2.0.1, 2.1.1 and the 2.x releases after them
    "mcpserver-package-and-fastmcp-module-with-no-api": {
        **PACKAGE,
        "mcp/server/mcpserver/__init__.pyi": NEWER_CLASS,
        "mcp/server/fastmcp.pyi": MODULE_WITH_NO_API,
    },
}


def test_the_mcp_extra_is_bounded_to_the_tested_releases(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["optional-dependencies"]["mcp"] == MCP_EXTRA


def write_layout(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_the_sdk_import_passes_the_type_check_against_each_layout(
    layout: str, tmp_path: Path, repo_root: Path
) -> None:
    if importlib.util.find_spec("mypy") is None:
        pytest.skip("needs mypy (pip install mypy)")
    stand_in = tmp_path / "stand-in"
    write_layout(stand_in, LAYOUTS[layout])

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            "pyproject.toml",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--follow-imports",
            "silent",
            "--no-site-packages",
            "--no-color-output",
            SERVER_FILE,
        ],
        cwd=repo_root,
        env={**os.environ, "MYPYPATH": str(stand_in)},
        capture_output=True,
        text=True,
        timeout=WAIT_S,
        check=False,
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (0, MYPY_SUCCESS, "")
